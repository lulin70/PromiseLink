"""合并重复人脉实体 — 修复身份碎片化时期的重复数据。

背景:
    v0.9.7 身份统一之前，事件来自不同 user_id（e2e-real/real_llm_e2e/wechat/h5-frontend
    等），实体解析引擎按 user_id 隔离查询候选，同名人物（如"李总"）每次都新建实体，
    产生大量重复（王总x9、李总x8、张总x5、许总x4、张伟x2、张三x2、刘总x2）。

合并策略（每组同名 person 实体）:
    1. 幸存者 = created_at 最新的一条（最近的提取质量与数据最全）
    2. todos.related_entity_id            → 指向幸存者
    3. relationship_briefs                → 组内保留 last_updated_at 最新的一条指向幸存者，其余删除
    4. associations                       → source/target 指向幸存者，
       冲突（同 user+source+target+type 已存在）或自关联 → 删除多余行
    5. 幸存者 properties 补全（从重复项填充缺失的 basic 字段），aliases 并集
    6. 重复项标记 status='merged' + properties.merged_into=幸存者ID
       （保留实体行以维持 source_event_id 事件关联历史，不物理删除）

用法:
    python scripts/merge_duplicate_persons.py [--dry-run] [--db PATH]
"""
from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

DEFAULT_DB = Path(__file__).resolve().parent.parent / "data" / "promiselink_poc.db"


def now() -> str:
    return datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")


def load_json(value: str | None, default):
    if not value:
        return default
    try:
        return json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return default


def merge_properties(survivor_props: dict, dupe_props: dict) -> dict:
    """用重复项的 basic 字段补全幸存者缺失字段（幸存者优先）。"""
    merged = dict(survivor_props or {})
    s_basic = dict(merged.get("basic") or {})
    d_basic = dict((dupe_props or {}).get("basic") or {})
    for key, val in d_basic.items():
        if val and not s_basic.get(key):
            s_basic[key] = val
    if s_basic:
        merged["basic"] = s_basic
    return merged


def find_duplicate_groups(conn: sqlite3.Connection) -> list[tuple[str, list[str]]]:
    """返回 [(name, [entity_id 按created_at升序])], 仅含活跃(confirmed/provisional)person。"""
    rows = conn.execute(
        """
        SELECT id, name FROM entities
        WHERE entity_type = 'person' AND status IN ('confirmed', 'provisional')
        ORDER BY created_at ASC
        """
    ).fetchall()
    groups: dict[str, list[str]] = {}
    for eid, name in rows:
        key = (name or "").strip().lower()
        groups.setdefault(key, []).append(eid)
    return [(k, ids) for k, ids in groups.items() if len(ids) > 1]


def merge_group(conn: sqlite3.Connection, name: str, ids: list[str], dry: bool) -> dict:
    """合并一组重复实体。ids 按 created_at 升序，最后一条为幸存者。"""
    survivor_id = ids[-1]
    dupe_ids = ids[:-1]
    stats = {
        "name": name,
        "survivor": survivor_id,
        "merged": len(dupe_ids),
        "todos_moved": 0,
        "briefs_kept": 0,
        "briefs_deleted": 0,
        "assocs_moved": 0,
        "assocs_deleted": 0,
        "props_filled": 0,
    }

    # 1. todos → 幸存者
    for did in dupe_ids:
        cur = conn.execute(
            "UPDATE todos SET related_entity_id = ? WHERE related_entity_id = ?",
            (survivor_id, did),
        )
        stats["todos_moved"] += cur.rowcount

    # 2. relationship_briefs: 组内(含幸存者)保留最新一条
    brief_rows = conn.execute(
        """
        SELECT id, person_entity_id FROM relationship_briefs
        WHERE person_entity_id IN ({}) ORDER BY last_updated_at ASC
        """.format(",".join("?" * len(ids))),
        ids,
    ).fetchall()
    keep_id = brief_rows[-1][0] if brief_rows else None
    for bid, owner in brief_rows:
        if bid == keep_id:
            if owner != survivor_id:
                conn.execute(
                    "UPDATE relationship_briefs SET person_entity_id = ? WHERE id = ?",
                    (survivor_id, bid),
                )
            stats["briefs_kept"] += 1
        else:
            conn.execute("DELETE FROM relationship_briefs WHERE id = ?", (bid,))
            stats["briefs_deleted"] += 1

    # 3. associations 迁移（source 或 target 任一为重复项）
    placeholders = ",".join("?" * len(dupe_ids))
    assoc_rows = conn.execute(
        f"""
        SELECT id, source_entity_id, target_entity_id FROM associations
        WHERE source_entity_id IN ({placeholders}) OR target_entity_id IN ({placeholders})
        """,
        dupe_ids + dupe_ids,
    ).fetchall()
    for aid, src, tgt in assoc_rows:
        new_src = survivor_id if src in dupe_ids else src
        new_tgt = survivor_id if tgt in dupe_ids else tgt
        if new_src == new_tgt:
            # 迁移后自关联（原为两个重复实体之间的关联）→ 无意义，删除
            conn.execute("DELETE FROM associations WHERE id = ?", (aid,))
            stats["assocs_deleted"] += 1
            continue
        exists = conn.execute(
            """
            SELECT 1 FROM associations
            WHERE user_id = (SELECT user_id FROM associations WHERE id = ?)
              AND source_entity_id = ? AND target_entity_id = ?
              AND association_type = (SELECT association_type FROM associations WHERE id = ?)
              AND id != ?
            """,
            (aid, new_src, new_tgt, aid, aid),
        ).fetchone()
        if exists:
            conn.execute("DELETE FROM associations WHERE id = ?", (aid,))
            stats["assocs_deleted"] += 1
        else:
            conn.execute(
                "UPDATE associations SET source_entity_id = ?, target_entity_id = ? WHERE id = ?",
                (new_src, new_tgt, aid),
            )
            stats["assocs_moved"] += 1

    # 4. 幸存者 properties 补全 + aliases 并集
    surv = conn.execute(
        "SELECT properties, aliases FROM entities WHERE id = ?", (survivor_id,)
    ).fetchone()
    surv_props = load_json(surv[0], {}) if surv else {}
    surv_aliases = load_json(surv[1], []) if surv else []
    filled = 0
    for did in dupe_ids:
        d = conn.execute(
            "SELECT properties, aliases FROM entities WHERE id = ?", (did,)
        ).fetchone()
        d_props = load_json(d[0], {}) if d else {}
        d_aliases = load_json(d[1], []) if d else []
        before = json.dumps(surv_props.get("basic") or {}, ensure_ascii=False, sort_keys=True)
        surv_props = merge_properties(surv_props, d_props)
        after = json.dumps(surv_props.get("basic") or {}, ensure_ascii=False, sort_keys=True)
        if before != after:
            filled += 1
        for alias in d_aliases:
            if alias and alias not in surv_aliases:
                surv_aliases.append(alias)
    conn.execute(
        "UPDATE entities SET properties = ?, aliases = ?, updated_at = ? WHERE id = ?",
        (json.dumps(surv_props, ensure_ascii=False), json.dumps(surv_aliases, ensure_ascii=False), now(), survivor_id),
    )
    stats["props_filled"] = filled

    # 5. 重复项标记 merged（保留行以维持 source_event_id 历史关联）
    for did in dupe_ids:
        row = conn.execute("SELECT properties FROM entities WHERE id = ?", (did,)).fetchone()
        props = load_json(row[0], {}) if row else {}
        props["merged_into"] = survivor_id
        conn.execute(
            "UPDATE entities SET status = 'merged', properties = ?, updated_at = ? WHERE id = ?",
            (json.dumps(props, ensure_ascii=False), now(), did),
        )
    return stats


def main() -> int:
    parser = argparse.ArgumentParser(description="合并重复人脉实体")
    parser.add_argument("--db", default=str(DEFAULT_DB), help="SQLite 数据库路径")
    parser.add_argument("--dry-run", action="store_true", help="只报告不落库")
    args = parser.parse_args()

    db_path = Path(args.db).expanduser().resolve()
    if not db_path.exists():
        print(f"[ERROR] 数据库不存在: {db_path}")
        return 1

    if not args.dry_run:
        backup = db_path.with_suffix(db_path.suffix + f".bak_merge_{datetime.now():%Y%m%d_%H%M%S}")
        shutil.copy2(db_path, backup)
        print(f"[备份] {backup}")

    conn = sqlite3.connect(str(db_path))
    conn.isolation_level = None  # 手动事务
    conn.execute("BEGIN")
    try:
        groups = find_duplicate_groups(conn)
        if not groups:
            print("[OK] 无重复实体")
            return 0
        print(f"[发现] {len(groups)} 组重复，共 {sum(len(g[1]) for g in groups)} 条实体")
        total_merged = 0
        for name, ids in groups:
            stats = merge_group(conn, name, ids, args.dry_run)
            total_merged += stats["merged"]
            print(
                f"  {stats['name']}: 保留 {stats['survivor'][:8]} | 合并 {stats['merged']} 条 | "
                f"todos迁移 {stats['todos_moved']} | briefs 保留{stats['briefs_kept']}/删{stats['briefs_deleted']} | "
                f"关联迁移 {stats['assocs_moved']}/删 {stats['assocs_deleted']} | 属性补全 {stats['props_filled']}"
            )
        if args.dry_run:
            conn.execute("ROLLBACK")
            print(f"[DRY-RUN] 回滚，未落库（应合并 {total_merged} 条）")
        else:
            conn.execute("COMMIT")
            print(f"[完成] 已合并 {total_merged} 条重复实体")
    except Exception as exc:
        conn.execute("ROLLBACK")
        print(f"[ERROR] {exc}，已回滚")
        return 1
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
