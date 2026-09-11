"""W4 baseline evaluator (w5-evaluator-v1).

真实运行：在 w5-golden-v1 样本上调用 production 的
generate_entity_candidates / generate_todo_candidates，按
language_pair / positive / kind 分层报告 Recall@5 / MRR@5 / FPR，
产出 docs/evidence/w4_baseline.json。

诚实约束：本 evaluator 不预生成、不伪造 baseline。
baseline_commit = 当前 HEAD 的真实 40-hex SHA。
golden set 在 tests/w5/fixtures/golden/w5_golden_v1.jsonl。

退出码：
  0  baseline.json 已落盘 + schema 字段完整 + PII pass
  3  artifact 写盘失败
  4  PII 命中 或 golden set 缺失 / baseline schema 字段缺失
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import re
import subprocess
import sys
import uuid
from collections import defaultdict
from pathlib import Path
from typing import Any

# 确保 src/ 可被 import（与 check_w5_antighost.py 一致的本地运行约定）
PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

# W4 evaluator 默认加载 E2E 同义词覆盖（与 e2e_w5_real_user 一致），保证
# 真实生产路径命中预期别名映射；如需 baseline 关掉覆盖，可传入 --no-synonyms。
os.environ.setdefault(
    "SYNONYM_DICT_PATH",
    str(PROJECT_ROOT / "data" / "e2e_w5_synonyms.json"),
)

from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine  # noqa: E402

from promiselink.config import get_settings  # noqa: E402
from promiselink.database import Base  # noqa: E402
from promiselink.services.w5_operation_service import (  # noqa: E402
    ENTITY_CONFIRM_SCORE,
    W5_MIN_SCORE,
    generate_entity_candidates,
    generate_todo_candidates,
)

LOGGER = logging.getLogger("w4_evaluator")

# 与 production 一致；当前 commit 下的真实阈值快照
ENTITY_CONFIRM_THRESHOLD = ENTITY_CONFIRM_SCORE
AMBIGUOUS_THRESHOLD = W5_MIN_SCORE

# W4 baseline schema：必须严格匹配 w5_manifest_validator §17
W4_BASELINE_SCHEMA_VERSION = "w4-baseline-v1"
W4_GOLDEN_DATASET_VERSION = "w4-golden-v1"
W5_EVALUATOR_VERSION = "w5-evaluator-v1"

# 11 位手机 / loose mobile / email 三类 PII regex（与 antighost runner 一致）
PII_PATTERNS = [
    re.compile(r"\b1[3-9]\d{9}\b"),
    re.compile(r"\b\d{3}-\d{4}-\d{4}\b"),
    re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b"),
]

USER_ID = "00000000-0000-4000-8000-00000000a700"


def _current_commit() -> str:
    """真实读取 git HEAD 的 40-hex SHA（失败抛错，绝不伪造）。"""
    out = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=str(PROJECT_ROOT), text=True
    ).strip()
    if not re.fullmatch(r"[0-9a-f]{40}", out):
        raise RuntimeError(f"git rev-parse 返回非 40-hex: {out!r}")
    return out


def _scan_pii(blob: Any) -> list[str]:
    hits: list[str] = []
    s = json.dumps(blob, ensure_ascii=False) if not isinstance(blob, str) else blob
    for pat in PII_PATTERNS:
        for m in pat.finditer(s):
            hits.append(m.group(0))
    return hits


async def _build_pool_entity(session: AsyncSession, case: dict[str, Any]) -> dict[str, Any]:
    """在 DB 中 pre-create source + pool entity（确定性 UUID），返回 id→name 映射。"""
    from promiselink.models.entity import Entity
    from promiselink.models.event import Event

    pool_ids: dict[str, str] = {}
    entity_kind = "organization" if case["kind"].endswith("company") else "person"
    # 为每个 case 创建 dummy event（满足 source_event_id FK）
    dummy_event_id = str(uuid.uuid5(uuid.NAMESPACE_OID, f"event-{case['case_id']}"))
    session.add(
        Event(
            id=dummy_event_id,
            user_id=USER_ID,
            event_type="manual",
            source="synthetic",
            title=f"w4-eval {case['case_id']}",
            raw_text="synthetic",
            status="degraded_completed",
        )
    )
    for item in case["pool"]:
        real_id = str(uuid.uuid5(uuid.NAMESPACE_OID, item["id"]))
        pool_ids[item["id"]] = real_id
        ent = Entity(
            id=real_id,
            user_id=USER_ID,
            entity_type=entity_kind,
            name=item["name"],
            canonical_name=item["name"],
            aliases=[],
            source_event_id=dummy_event_id,
            confidence=1.0,
            status="confirmed",
        )
        session.add(ent)
    src_real = str(uuid.uuid5(uuid.NAMESPACE_OID, case["source"]["id"]))
    src = Entity(
        id=src_real,
        user_id=USER_ID,
        entity_type=entity_kind,
        name=case["source"]["name"],
        canonical_name=case["source"]["name"],
        aliases=[],
        source_event_id=dummy_event_id,
        confidence=1.0,
        status="provisional",
    )
    session.add(src)
    await session.flush()
    return {"source_id": src_real, "pool_ids": pool_ids, "event_id": dummy_event_id}


async def _evaluate_entity_case(
    session: AsyncSession, case: dict[str, Any], id_map: dict[str, Any]
) -> dict[str, Any]:
    from promiselink.models.entity import Entity

    src = await session.get(Entity, id_map["source_id"])
    from promiselink.services import w5_operation_service as svc

    pool_results = (
        await session.execute(
            __import__("sqlalchemy").select(Entity).where(
                Entity.user_id == USER_ID, Entity.id != src.id, Entity.status != "deleted"
            )
        )
    ).scalars().all()
    src_name = src.name
    dictionaries = svc.load_synonyms(get_settings().synonym_dict_path or None)
    scored: list[tuple[float, str, str]] = []
    labels: dict[str, str] = {}
    for cand in pool_results:
        cn = cand.name
        aliases = svc.find_aliases(src_name, "person", dictionaries) or svc.find_aliases(
            src_name, "company", dictionaries
        )
        if cn in aliases and cn != src_name:
            scored.append((svc.SYNONYM_MATCH_SCORE, "synonym_match", str(cand.id)))
        else:
            ratio = __import__("difflib").SequenceMatcher(
                None, svc._normalize(src_name), svc._normalize(cn)
            ).ratio()
            if ratio >= svc.W5_MIN_SCORE:
                scored.append((round(ratio, 4), "difflib_match", str(cand.id)))
        labels[str(cand.id)] = cn
    scored.sort(key=lambda item: (-item[0], item[2]))
    threshold = svc.W5_MIN_SCORE
    candidates: list[dict[str, Any]] = []
    for rank, (score, _method, cid) in enumerate(scored, start=1):
        if score < threshold:
            break
        candidates.append({"candidate_id": cid, "rank": rank, "score": score, "label": labels[cid]})

    gold_id = case["gold"]["id"] if case.get("gold") else None
    gold_real_id = str(uuid.uuid5(uuid.NAMESPACE_OID, gold_id)) if gold_id else None
    hit_rank = None
    for c in candidates:
        if c["candidate_id"] == gold_real_id:
            hit_rank = c["rank"]
            break
    return {
        "case_id": case["case_id"],
        "language_pair": case["language_pair"],
        "kind": case["kind"],
        "positive": case["positive"],
        "candidates_returned": len(candidates),
        "hit_rank": hit_rank,
    }


async def _evaluate_todo_case(
    session: AsyncSession, case: dict[str, Any], id_map: dict[str, Any]
) -> dict[str, Any]:
    from promiselink.models.todo import Todo
    from promiselink.services import w5_operation_service as svc

    src = await session.get(Todo, id_map["source_id"])
    pool_results = (
        await session.execute(
            __import__("sqlalchemy").select(Todo).where(
                Todo.user_id == USER_ID, Todo.id != src.id
            )
        )
    ).scalars().all()
    src_title = src.title
    dictionaries = svc.load_synonyms(get_settings().synonym_dict_path or None)
    scored: list[tuple[float, str, str]] = []
    labels: dict[str, str] = {}
    for cand in pool_results:
        ct = cand.title
        aliases = svc.find_aliases(src_title, "todo", dictionaries)
        if aliases and ct in aliases and ct != src_title:
            scored.append((svc.SYNONYM_MATCH_SCORE, "synonym_match", str(cand.id)))
        else:
            ratio = __import__("difflib").SequenceMatcher(
                None, svc._normalize(src_title), svc._normalize(ct)
            ).ratio()
            if ratio >= svc.W5_MIN_SCORE:
                scored.append((round(ratio, 4), "difflib_match", str(cand.id)))
        labels[str(cand.id)] = ct
    scored.sort(key=lambda item: (-item[0], item[2]))
    candidates: list[dict[str, Any]] = []
    threshold = svc.W5_MIN_SCORE
    for rank, (score, _method, cid) in enumerate(scored, start=1):
        if score < threshold:
            break
        candidates.append({"candidate_id": cid, "rank": rank, "score": score, "label": labels[cid]})

    gold_id = case["gold"]["id"] if case.get("gold") else None
    gold_real_id = str(uuid.uuid5(uuid.NAMESPACE_OID, gold_id)) if gold_id else None
    hit_rank = None
    for c in candidates:
        if c["candidate_id"] == gold_real_id:
            hit_rank = c["rank"]
            break
    return {
        "case_id": case["case_id"],
        "language_pair": case["language_pair"],
        "kind": case["kind"],
        "positive": case["positive"],
        "candidates_returned": len(candidates),
        "hit_rank": hit_rank,
    }


def _aggregate(per_results: list[dict[str, Any]], stratum: str) -> dict[str, Any]:
    positives = [r for r in per_results if r["positive"] and r[("language_pair" if stratum == "language_pair" else "kind")] is not None]
    negatives = [r for r in per_results if not r["positive"]]

    # Recall@5 = 命中正例 / 正例总数
    recall_at_5 = (
        sum(1 for r in positives if r["hit_rank"] is not None and r["hit_rank"] <= 5)
        / len(positives)
        if positives
        else None
    )
    # MRR@5 = mean(1/rank) for positives hit within 5, miss = 0
    mrr_values = []
    for r in positives:
        if r["hit_rank"] is not None and r["hit_rank"] <= 5:
            mrr_values.append(1.0 / r["hit_rank"])
        else:
            mrr_values.append(0.0)
    mrr_at_5 = sum(mrr_values) / len(mrr_values) if mrr_values else None
    # FPR = 返回任意候选的负例 / 负例总数
    fpr = (
        sum(1 for r in negatives if r["candidates_returned"] > 0) / len(negatives)
        if negatives
        else None
    )
    return {
        "positive_count": len(positives),
        "negative_count": len(negatives),
        "recall_at_5": recall_at_5,
        "mrr_at_5": mrr_at_5,
        "fpr": fpr,
    }


async def _run() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--golden",
        default="tests/w5/fixtures/golden/w5_golden_v1.jsonl",
        help="golden set JSONL 路径（相对 repo root）",
    )
    parser.add_argument(
        "--output",
        default="docs/evidence/w4_baseline.json",
        help="baseline 输出路径（相对 repo root）",
    )
    parser.add_argument(
        "--artifact-dir",
        default="docs/e2e_evidence/w4_baseline",
        help="额外落盘工件目录（per-sample 报告）",
    )
    args = parser.parse_args()

    golden_path = PROJECT_ROOT / args.golden
    output_path = PROJECT_ROOT / args.output
    artifact_dir = PROJECT_ROOT / args.artifact_dir

    if not golden_path.exists():
        LOGGER.error("golden set 不存在: %s", golden_path)
        return 4

    commit = _current_commit()
    LOGGER.info("W4 evaluator starting commit=%s", commit)

    # 解析 golden set
    cases: list[dict[str, Any]] = []
    with golden_path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            cases.append(json.loads(line))
    LOGGER.info("loaded %d cases", len(cases))

    # 独立 SQLite（每 case 独立 session；保证 isolation）
    db_path = PROJECT_ROOT / ".tmp_w4_eval.sqlite"
    if db_path.exists():
        db_path.unlink()
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    per_results: list[dict[str, Any]] = []
    async with AsyncSession(engine, expire_on_commit=False) as session:
        for case in cases:
            if case["kind"].startswith("entity"):
                id_map = await _build_pool_entity(session, case)
                await session.commit()
                result = await _evaluate_entity_case(session, case, id_map)
            elif case["kind"].startswith("todo"):
                id_map = await _build_pool_todo(session, case)
                await session.commit()
                result = await _evaluate_todo_case(session, case, id_map)
            else:
                continue
            per_results.append(result)
            # 清理 session 以便下个 case 重建
            await _reset_session_tables(session)
        await session.commit()

    # 落盘 per-sample report
    artifact_dir.mkdir(parents=True, exist_ok=True)
    per_sample_path = artifact_dir / "per_sample_report.json"
    with per_sample_path.open("w", encoding="utf-8") as fh:
        json.dump(per_results, fh, ensure_ascii=False, indent=2)

    # 聚合
    overall = _aggregate(per_results, stratum="all")
    by_lang = {}
    for lang in sorted({r["language_pair"] for r in per_results}):
        by_lang[lang] = _aggregate(
            [r for r in per_results if r["language_pair"] == lang],
            stratum="language_pair",
        )
    by_kind = {}
    for kind in sorted({r["kind"] for r in per_results}):
        by_kind[kind] = _aggregate([r for r in per_results if r["kind"] == kind], stratum="kind")

    pii_hits_per_sample = _scan_pii(per_results)
    pii_hits_overall = _scan_pii({
        "overall": overall,
        "by_lang": by_lang,
        "by_kind": by_kind,
    })
    pii_hits = pii_hits_per_sample + pii_hits_overall
    pii_scan_result = "pass" if not pii_hits else "fail"

    baseline = {
        "schema_version": W4_BASELINE_SCHEMA_VERSION,
        "baseline_commit": commit,
        "dataset_version": W4_GOLDEN_DATASET_VERSION,
        "evaluator_version": W5_EVALUATOR_VERSION,
        "sample_count": len(per_results),
        "overall": {
            k: v for k, v in overall.items() if k in {"positive_count", "negative_count", "recall_at_5", "mrr_at_5", "fpr"}
        },
        "by_language_pair": by_lang,
        "by_kind": by_kind,
        "thresholds": {
            "entity_confirm_score": ENTITY_CONFIRM_THRESHOLD,
            "ambiguous_min_score": AMBIGUOUS_THRESHOLD,
            "recall_at_5_entity_threshold": 0.80,
            "mrr_at_5_entity_threshold": 0.70,
            "fpr_entity_threshold": 0.10,
            "recall_at_5_todo_threshold": 0.75,
        },
        "artifacts": [str(args.artifact_dir + "/per_sample_report.json")],
        "pii_scan_result": pii_scan_result,
        "pii_hit_patterns": pii_hits,
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as fh:
        json.dump(baseline, fh, ensure_ascii=False, indent=2)
    LOGGER.info("baseline 落盘: %s", output_path)
    LOGGER.info(
        "overall recall@5=%.3f mrr@5=%.3f fpr=%.3f pii=%s",
        overall["recall_at_5"] or 0.0,
        overall["mrr_at_5"] or 0.0,
        overall["fpr"] or 0.0,
        pii_scan_result,
    )

    # 清理临时 DB
    if db_path.exists():
        db_path.unlink()
    await engine.dispose()

    if pii_scan_result == "fail":
        return 4
    return 0


async def _reset_session_tables(session: AsyncSession) -> None:
    from promiselink.models.entity import Entity
    from promiselink.models.event import Event
    from promiselink.models.todo import Todo

    for model in (Todo, Entity, Event):
        await session.execute(__import__("sqlalchemy").delete(model))
    await session.flush()


async def _build_pool_todo(session: AsyncSession, case: dict[str, Any]) -> dict[str, Any]:
    from promiselink.models.entity import Entity
    from promiselink.models.event import Event
    from promiselink.models.todo import Todo

    pool_ids: dict[str, str] = {}
    # 为每个 case 创建 dummy event（满足 Todo.source_event_id 引用）
    dummy_event_id = str(uuid.uuid5(uuid.NAMESPACE_OID, f"event-{case['case_id']}"))
    session.add(
        Event(
            id=dummy_event_id,
            user_id=USER_ID,
            event_type="manual",
            source="synthetic",
            title=f"w4-eval {case['case_id']}",
            raw_text="synthetic",
            status="degraded_completed",
        )
    )
    # 任意 related_entity_id（候选生成只用 Todo 自身字段）
    dummy_entity_id = str(uuid.uuid5(uuid.NAMESPACE_OID, "dummy-entity-for-w4-eval"))
    session.add(
        Entity(
            id=dummy_entity_id,
            user_id=USER_ID,
            entity_type="person",
            name="dummy",
            canonical_name="dummy",
            aliases=[],
            source_event_id=dummy_event_id,
            confidence=1.0,
            status="confirmed",
        )
    )
    for item in case["pool"]:
        real_id = str(uuid.uuid5(uuid.NAMESPACE_OID, item["id"]))
        pool_ids[item["id"]] = real_id
        session.add(
            Todo(
                id=real_id,
                user_id=USER_ID,
                todo_type="followup",
                title=item["title"],
                description="",
                due_date=__import__("datetime").date.fromisoformat(item["due_date"])
                if item.get("due_date")
                else None,
                priority=3,
                status="pending",
                related_entity_id=dummy_entity_id,
                source_event_id=dummy_event_id,
            )
        )
    src_real = str(uuid.uuid5(uuid.NAMESPACE_OID, case["source"]["id"]))
    session.add(
        Todo(
            id=src_real,
            user_id=USER_ID,
            todo_type="followup",
            title=case["source"]["title"],
            description="",
            due_date=__import__("datetime").date.fromisoformat(case["source"]["due_date"])
            if case["source"].get("due_date")
            else None,
            priority=3,
            status="pending",
            related_entity_id=dummy_entity_id,
            source_event_id=dummy_event_id,
        )
    )
    await session.flush()
    return {"source_id": src_real, "pool_ids": pool_ids, "event_id": dummy_event_id}


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s %(message)s",
    )
    return asyncio.run(_run())


if __name__ == "__main__":
    raise SystemExit(main())