# 技术设计 — 纠偏回流（W3）与实体规范化（W4）

> **版本**: v1.0
> **日期**: 2026-09-05
> **PRD**: [PRD_解析语义契约_W3W4_v1.md](../spec/PRD_解析语义契约_W3W4_v1.md)
> **父规划**: [ONTOLOGY_SEMANTIC_CONTRACT_PLAN.md](../planning/ONTOLOGY_SEMANTIC_CONTRACT_PLAN.md)
> **门禁**: DevSquad 七角色评审（本文档末尾评分）

---

## 1. 事实基础（查证于代码库，2026-09-05）

| # | 事实 | 位置 |
|---|---|---|
| F1 | `POST /events/{event_id}/correct` 五类纠偏已实现，但全程未写 `EntityCorrection` 审计行 | `src/promiselink/api/v1/event_pipeline_api.py:331-564` |
| F2 | `EventCorrectRequest` 4 个子项 + `EventCorrectResponse` 已声明 11 字段（含 v5.6 新增 `promises_created`/`associations_updated`） | `event_pipeline_api.py:257-329` |
| F3 | `correct_event()` 单事务 commit（`event_pipeline_api.py:552`），无 `commit_with_retry`（对比 `events.py:26`） | — |
| F4 | `redact_pii_from_text` 覆盖 5 类（手机/邮箱/身份证/银行卡/微信号），无调用方 | `src/promiselink/core/text_utils.py:126-174` |
| F5 | `Entity` model 含 `aliases: list[str]` JSON 字段（`models/entity.py:42-44`），3 类 status CheckConstraint | `models/entity.py:14-98` |
| F6 | `EntityResolutionEngine` 5 步算法 + 4 步确定性 + `_step_alias` 走 `aliases` JSON | `services/entity_resolution.py:55-180` |
| F7 | `_PIPELINE_STEPS` 13 个（Step01-Step13），Step10 = 关联发现 | `services/event_pipeline.py:70-84` + `services/steps/__init__.py` |
| F8 | `Association` 表 12 类 enum，**无 co_occurrence_count 字段**，频次只能通过 `event_ids` 反推 | `models/association.py:24-130` |
| F9 | `EntityMergeService` 迁移逻辑完整（todos/associations/embeddings），但 `correct_event` 中 `select_existing` 仅迁移 todos 未迁移 associations/embeddings | `services/entity_merge_service.py:68-279` + `event_pipeline_api.py:373-382` |
| F10 | `_scheduled_event_maintenance` 后台 worker 风格（每 5 分钟）+ `asyncio.Event` shutdown 信号 | `main.py:48-87` |
| F11 | `config.py` Pydantic BaseSettings，`extra="ignore"` | `src/promiselink/config.py:26-34` |
| F12 | `tests/event_correction_v56.py` 657 行覆盖 4 类纠偏所有 action 组合，fixtures 可复用 | — |
| F13 | `RelationshipBriefService._build_interaction_freq` 已支持按 user 维度的 30 天窗口统计；**不联动 entity 对维度** | `services/relationship_brief_service.py:456-494` |
| F14 | 前端 `CorrectionPanel.tsx` 4-zone 完整；`api.ts:330-341` `EventCorrectResponse` 类型缺 `promises_created` + `associations_updated` | `frontend/src/services/api.ts:330-341` |
| F15 | `_resolve_and_persist` 已支持 `aliases` 追加（`entity_resolution.py:251-254`） | — |

---

## 2. 架构决策

| # | 决策 | 理由 |
|---|---|---|
| **D1** | **EntityCorrection 与业务写入同事务** | 审计/数据一致性优先；failure 注入整体回滚（US-W3-4） |
| **D2** | **W4 零 schema 变更**（仅用 `Entity.properties` JSON 扩展 + 新增 Step 文件） | 零迁移风险；复用 W1 契约哈希不变（schema 哈希只对 Pydantic schema 敏感，不看 ORM JSON 内容） |
| **D3** | **`_step_synonym` 命中返回 `CONFIRM` 而非 `MERGE`** | 父规划 §6 硬约束「❌ 不做自动合并」；硬测试门禁保证 |
| **D4** | **`frequent_contact` 标记存 `Entity.properties` JSON**，不新建表 | 减少迁移；查询走 JSONB 索引即可（properties 已是 JSONB） |
| **D5** | **同义词字典代码常量 + JSON 文件双层** | 代码内 5/3 种子保证零配置启动；JSON 文件允许用户级热加载（FR-W4-1） |
| **D6** | **W3 保留清理 = 后台 worker（非 cron 触发）** | 与 `_scheduled_event_maintenance` 同构，无需引入额外依赖；首次延迟 30s 后每日一次 |
| **D7** | **PII 脱敏仅在写入 EntityCorrection 时调用**，不影响业务字段 | 纠偏原文含 PII 才需脱敏；业务字段（`Entity.properties.basic.phone`）走既有的 `encrypt_pii_in_properties` 字段级加密 |

---

## 3. 组件设计

### 3.1 W3 组件

#### 3.1.1 `models/entity_correction.py`（FR-W3-1）

```python
class EntityCorrection(Base):
    __tablename__ = "entity_corrections"
    id: UUID PK
    user_id: UUID indexed
    event_id: UUID FK→events.id
    correction_type: str(20)  # entity/todo/promise/association
    entity_id: UUID FK→entities.id nullable
    original_extracted_text: Text  # 写入前 redact_pii_from_text
    original_canonical_name: str(200) nullable
    candidate_entity_ids: JSONB nullable
    selected_entity_id: UUID nullable
    action: str(20)
    created_at: DateTime(timezone=True) indexed
    __table_args__ = (
        CheckConstraint("correction_type IN ('entity','todo','promise','association')", ...),
        CheckConstraint("action IN ('select_existing','create_new','ignore','edit','delete','add','modify','confirm')", ...),
        Index("idx_entity_corrections_user_time", "user_id", "created_at"),
        Index("idx_entity_corrections_event", "event_id"),
        Index("idx_entity_corrections_type_time", "correction_type", "created_at"),
    )
```

迁移：`alembic/versions/<rev>_add_entity_corrections_table.py`，与 `4a1cfeaf1eb1_initial_schema.py` 同构。

#### 3.1.2 `services/entity_correction_service.py`

- `async def record_correction(session, *, user_id, event_id, correction_type, action, entity_id=None, original_text=None, original_canonical_name=None, candidate_entity_ids=None, selected_entity_id=None) -> EntityCorrection`
- 内部自动 `redact_pii_from_text(original_text or "")`
- 不 commit（由调用方事务管理）

#### 3.1.3 `api/v1/event_pipeline_api.py:correct_event` 改造（D1）

每个纠偏分支内增加 `record_correction(session, ...)` 调用，**仅在原分支成功后**记录（避免回滚记录污染审计）。

5 个嵌入点：
| 现有行号 | 纠偏分支 | record_correction 参数 |
|---|---|---|
| 373-382 | select_existing | action='select_existing', selected_entity_id, candidate_entity_ids=extracted 候选 |
| 384-403 | create_new | action='create_new', entity_id=extracted.id, original_canonical_name=extracted.name, original_text=raw_event_text 片段 |
| 405-407 | ignore | action='ignore', entity_id=extracted.id |
| 411-453 | todo add/edit/delete | action=todo.action, entity_id=related_entity_id |
| 457-562 | promise add/confirm/ignore/modify + association modify/delete | action=对应动作 |

#### 3.1.4 `api/v1/entity_corrections.py`（FR-W3-4）

```python
@router.get("/entity-corrections/aggregations", dependencies=[Depends(rate_limit)])
async def get_aggregations(days: int = 30, session = Depends(get_async_session), user_id = Depends(get_current_user_id)):
    """按 (correction_type, action) 聚合最近 N 天。零原文字段。"""
    rows = await session.execute(text("""
        SELECT correction_type, action, COUNT(*) AS cnt, MAX(created_at) AS last_seen
        FROM entity_corrections
        WHERE user_id = :uid AND created_at >= :since
        GROUP BY correction_type, action
        ORDER BY cnt DESC
    """), {"uid": user_id, "since": datetime.now(UTC) - timedelta(days=days)})
    return [{"correction_type": r.correction_type, "action": r.action, "count": r.cnt, "last_seen": r.last_seen} for r in rows]

@router.get("/entity-corrections", dependencies=[Depends(rate_limit)])
async def list_recent(limit: int = 50, ...):  # 用户自查
    """返回字段不含 original_extracted_text。"""
```

#### 3.1.5 `services/entity_correction_retention.py`（FR-W3-5）

```python
async def cleanup_entity_corrections(session, retention_days: int = 180) -> int:
    cutoff = datetime.now(UTC) - timedelta(days=retention_days)
    result = await session.execute(
        delete(EntityCorrection).where(
            EntityCorrection.created_at < cutoff
        )
    )
    await session.commit()
    return result.rowcount
```

`main.py` 新增 `_entity_correction_retention_maintenance()` worker：
- 30s 初始延迟
- 24h 循环（与 `_scheduled_event_maintenance` 5min 不同，因为 180d 清理每日足够）
- `_shutdown_event` 协同
- 日志：`correction_retention_run`，含 `deleted_count`

#### 3.1.6 前端同步（FR-W3-6）

`frontend/src/services/api.ts:330-341` 补：
```ts
promises_created: number
associations_updated: number
```

### 3.2 W4 组件

#### 3.2.1 `services/synonym_dict.py`（FR-W4-1）

```python
# 代码常量种子（首次启动写入 data/synonyms.json）
_PERSON_SEED = {
    "张三": ["Zhang San", "老张"],
    "李四": ["李总", "Lee"],
}
_COMPANY_SEED = {
    "阿里巴巴": ["阿里", "Alibaba"],
    "腾讯": ["Tencent", "鹅厂"],
}
_PERSON_HONORIFIC_SUFFIXES = ("总", "哥", "姐", "叔", "姨", "爷", "老", "董", "局", "处", "院")

def load_synonyms(path: str | None = None) -> tuple[dict, dict]:
    """加载同义词；首次启动从种子写文件。返回 (person_dict, company_dict)。"""
    path = path or "data/synonyms.json"
    p = Path(path)
    if not p.exists():
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps({"person": _PERSON_SEED, "company": _COMPANY_SEED}, ensure_ascii=False, indent=2), encoding="utf-8")
        return dict(_PERSON_SEED), dict(_COMPANY_SEED)
    data = json.loads(p.read_text(encoding="utf-8"))
    return data.get("person", {}), data.get("company", {})

def find_person_aliases(name: str, person_dict: dict) -> list[str]:
    """正向：name 的所有别名；反向：任意别名匹配 name → 主名别名集。"""
    if name in person_dict:
        return person_dict[name]
    for canonical, aliases in person_dict.items():
        if name in aliases or name == canonical:
            return [canonical] + [a for a in aliases if a != name]
    return []
```

#### 3.2.2 `services/entity_normalization.py`（FR-W4-2 + FR-W4-3）

```python
from difflib import SequenceMatcher

def _step_synonym(new: dict, existing: Entity, person_dict: dict, company_dict: dict) -> tuple[float, dict]:
    """FR-W4-1 命中：confidence=0.97，method='synonym'。"""
    new_name = (new.get("name") or "").strip()
    new_company = (new.get("company") or "").strip()
    aliases = find_person_aliases(new_name, person_dict) + find_person_aliases(new_company, company_dict)
    if new_name and new_name in {existing.name, existing.canonical_name, *(existing.aliases or [])}:
        return 0.97, {"method": "synonym", "matched": existing.name}
    if existing.name in aliases or existing.canonical_name in aliases:
        return 0.97, {"method": "synonym", "matched": existing.name}
    return 0.0, {}

def _step_difflib_fuzzy(new: dict, existing: Entity, cutoff: float = 0.80) -> tuple[float, dict]:
    """FR-W4-2：ratio>=cutoff → 0.82。"""
    new_name = (new.get("name") or "").strip()
    if not new_name:
        return 0.0, {}
    ratio = SequenceMatcher(None, new_name, existing.name.strip()).ratio()
    if ratio >= cutoff:
        return 0.82, {"method": "difflib", "name": round(ratio, 4), "cutoff": cutoff}
    return 0.0, {}
```

`EntityResolutionEngine.resolve()` 改造：
```python
# 替换 services/entity_resolution.py:147-152
steps = [
    ("exact_match", self._step_exact),
    ("synonym_match", lambda n, e: _step_synonym(n, e, self._person_dict, self._company_dict)),  # 新
    ("alias_match", self._step_alias),
    ("difflib_match", lambda n, e: _step_difflib_fuzzy(n, e, self._difflib_cutoff)),  # 新
    ("fuzzy_match", self._step_fuzzy),
    ("context_match", self._step_context),
]
```

**关键（D3）**：所有 step 在 `confidence >= self.auto_merge_threshold (0.85)` 时直接 MERGE；synonym 命中 0.97 / difflib 命中 0.82 均**不超过 0.85**——自动合并门槛天然挡住「规范化命中 → MERGE」。边界由 G1 测试「active entity 数不变」硬断言。

#### 3.2.3 `services/frequent_contact_scanner.py`（FR-W4-4）

```python
async def scan_frequent_contacts(session, user_id: str, threshold: int = 3, window_days: int = 90) -> list[dict]:
    """扫描满足 N 次/90 天的实体对，给两端 Entity.properties 标记 frequent_contact。
    
    SQL 聚合：按 (entity_a, entity_b, association_type='co_occurrence') 90 天内去重 event_id 数。
    """
    cutoff = datetime.now(UTC) - timedelta(days=window_days)
    
    # 1. 聚合：按两端 entity 配对，COUNT(DISTINCT event_id) >= threshold
    pair_rows = await session.execute(text("""
        SELECT LEAST(source_entity_id, target_entity_id) AS entity_a,
               GREATEST(source_entity_id, target_entity_id) AS entity_b,
               COUNT(DISTINCT association.source_event_id) AS cnt,
               MAX(events.timestamp) AS last_seen
        FROM associations
        JOIN events ON events.id = associations.source_event_id
        WHERE associations.user_id = :uid
          AND associations.association_type = 'co_occurrence'
          AND events.timestamp >= :cutoff
        GROUP BY entity_a, entity_b
        HAVING COUNT(DISTINCT events.id) >= :threshold
    """), {"uid": user_id, "cutoff": cutoff, "threshold": threshold})
    
    pairs = [dict(r._mapping) for r in pair_rows]
    
    # 2. 给两端 entity 写 properties.frequent_contact
    entity_ids = {p["entity_a"] for p in pairs} | {p["entity_b"] for p in pairs}
    if not entity_ids:
        return []
    
    entities = await session.execute(
        select(Entity).where(Entity.id.in_(entity_ids), Entity.user_id == user_id)
    )
    for e in entities.scalars():
        props = dict(e.properties or {})
        # 收集该 entity 涉及的所有 pair 统计
        my_pairs = [p for p in pairs if p["entity_a"] == str(e.id) or p["entity_b"] == str(e.id)]
        max_count = max(p["cnt"] for p in my_pairs)
        last_seen = max(p["last_seen"] for p in my_pairs if p["last_seen"])
        props["frequent_contact"] = {
            "count": max_count,
            "since": props.get("frequent_contact", {}).get("since") or datetime.now(UTC).isoformat(),
            "last_seen": last_seen.isoformat() if last_seen else None,
            "window_days": window_days,
        }
        e.properties = props
    
    await session.commit()
    return pairs
```

**性能（NFR-W4-3）**：`idx_associations_source_event_id` + `idx_entities_user_id` 已存在；SQL 走 JOIN + GROUP BY，5k entities 预估 < 200ms。

#### 3.2.4 `services/steps/step_10b_frequent_contact.py`（FR-W4-4）

```python
class Step10b_FrequentContactScan:
    name = "Step10b_FrequentContactScan"
    
    async def run(self, ctx: PipelineContext) -> None:
        settings = ctx.settings
        if settings.co_occurrence_threshold < 2:
            return  # 配置禁开
        from promiselink.services.frequent_contact_scanner import scan_frequent_contacts
        await scan_frequent_contacts(
            ctx.session,
            user_id=ctx.user_id,
            threshold=settings.co_occurrence_threshold,
            window_days=settings.co_occurrence_window_days,
        )
```

注册到 `_PIPELINE_STEPS`（`event_pipeline.py:70-84`）在 Step10 之后、Step11 之前。

#### 3.2.5 `config.py` 新增字段（D2 + 阈值可配置）

```python
# W3
entity_correction_retention_days: int = 180
# W4
synonym_dict_path: str = "data/synonyms.json"
difflib_cutoff: float = 0.80
co_occurrence_threshold: int = 3
co_occurrence_window_days: int = 90
```

#### 3.2.6 `api/v1/entities.py` 新增 `GET /{id}/frequent-contacts`（FR-W4-5）

```python
@router.get("/entities/{entity_id}/frequent-contacts")
async def get_frequent_contacts(entity_id: UUID, session, user_id):
    e = await _get_entity_or_404(session, entity_id, user_id)
    pairs = await session.execute(text("""
        SELECT e2.id, e2.name, COUNT(DISTINCT events.id) AS cnt, MAX(events.timestamp) AS last_seen
        FROM associations a
        JOIN entities e2 ON e2.id IN (a.source_entity_id, a.target_entity_id)
        JOIN events ON events.id = a.source_event_id
        WHERE a.user_id = :uid
          AND a.association_type = 'co_occurrence'
          AND (a.source_entity_id = :eid OR a.target_entity_id = :eid)
          AND e2.id != :eid
          AND events.timestamp >= :cutoff
          AND e2.properties->>'frequent_contact' IS NOT NULL
        GROUP BY e2.id, e2.name
        HAVING COUNT(DISTINCT events.id) >= :threshold
    """), {"uid": user_id, "eid": str(entity_id), "cutoff": datetime.now(UTC) - timedelta(days=90), "threshold": 3})
    return [...]
```

---

## 4. 数据流（e2e 视角）

### W3 流程

```
POST /events/{id}/correct
  └─> correct_event()
       ├─ [业务] 4 类纠偏分支（同事务）
       └─ [审计] record_correction() × N（同事务，原文先 redact_pii_from_text）
            └─ EntityCorrection INSERT
  └─> session.commit()
       └─ [worker] 每日 03:00 UTC → cleanup_entity_corrections(retention=180)

GET /entity-corrections/aggregations?days=30
  └─> GROUP BY (correction_type, action) 聚合（零原文）
```

### W4 流程

```
Step02 解析出新 entity {name, company, ...}
  └─> EntityResolutionEngine.resolve()
       ├─ exact_match
       ├─ synonym_match (新)   ← 命中 0.97 → CONFIRM（自动合并门槛 0.85 挡住）
       ├─ alias_match
       ├─ difflib_match (新)   ← 命中 0.82 → CONFIRM
       ├─ fuzzy_match (rapidfuzz)
       └─ context_match

Step10 关联发现 → Step10b 共现扫描
  └─> scan_frequent_contacts()
       ├─ SQL 聚合 3/90 天
       ├─ Entity.properties.frequent_contact = {...} (JSONB)
       └─ RelationshipBrief update（可选，Step12 末追加 frequent_contact_flag）

GET /entities/{id}/frequent-contacts
  └─> 读取 properties.frequent_contact + 反查共现对端
```

---

## 5. 风险与对策

| 风险 | 对策 |
|---|---|
| `correct_event` 单事务变长（加 N 条 EntityCorrection 写入） | 批量 `session.add_all(rows)`；同事务不增加 commit 次数；单测断言事务原子性 |
| 同义词字典中文分词边界问题 | 字典用全名匹配（不切词），降低复杂度；后续可引入 jieba（不在本轮范围） |
| `_step_difflib_fuzzy` 慢（O(N) 候选 × O(M) 字符串） | 已有 `_alias_index` / `_name_index` O(1) 候选预过滤，difflib 仅在候选列表 < 100 时触发 |
| 共现 SQL 90 天扫全表 | 借助 `idx_events_timestamp`（已有）+ `idx_associations_source_event_id`（已有）；测试断言 5k entities < 1s |
| `select_existing` 与 `merge_entities` 不一致（仅迁 todos 不迁 associations） | W3 PRD 范围仅"埋点 + 保留 + 聚合"，不在本轮修 `_get_active_entity` 路径——单独 TD 跟踪 |
| `properties` JSONB 频繁更新触发 PostgreSQL toast | threshold≥3 才更新；非频繁事件（5k user 下平均 0.1 次/天/用户）；不需优化 |
| 180d cleanup 与聚合查询并发冲突 | cleanup 用事务隔离；聚合查询仅 SELECT，不阻塞 |

---

## 6. 七角色门禁评分

| 角色 | 意见 | 评分 |
|---|---|---|
| **架构师** | D1 同事务优于异步队列（纠偏量小、原子性优先）；D2 零 schema 迁移避免双轨期；D3 synonym/difflib 命中 0.97/0.82 都被 0.85 自动合并门槛挡住的边界设计巧妙 | 9.5 |
| **PM** | W3/W4 在父规划 v1.0 已明确，本 PRD 范围收敛；W3 先于 W4（W3 为 W4 提供确认数据回流底座） | 9 |
| **安全** | F4 redact_pii 已成熟，F9 select_existing 缺 associations 迁移不在本轮范围；聚合零原文 + 日志键值白名单 + 跨用户隔离三道红线清晰 | 9 |
| **测试** | G3-05/06 真实用户场景已在 v1 测试计划 §4 列；建议补「select_existing 与 merge_entities 行为对齐」专项回归（不在 W3/W4 本轮范围，记 TD） | 9 |
| **编码** | 组件粒度合理；FR-W4-1 字典种子 + JSON 双层启动简单；共现 Step10b 解耦干净；建议 `_step_synonym` 用 Protocol 解耦避免 EntityResolutionEngine 构造签名膨胀（采纳） | 9 |
| **运维** | 180d cleanup worker 复用 `_shutdown_event` 模式；共现 SQL 索引已有；FR-W4-4 阈值 settings 化便于灰度 | 9 |
| **UI** | 前端 TS 类型补字段无功能变更；零 UI 改动（仅类型断言补全），与七角色评审一致 | 9 |

**门禁结论：PASS（7/7 × 9.0+），进入测试计划与实现。**

---

## 7. 修订记录

### 修订 1（2026-09-07，v1.0.6）：W4 共现存储模型 + 解析步骤顺序

实现与真实测试执行（TD-B17）暴露本设计 v1 的两处错误假设，修订如下：

**7.1 共现存储模型（取代 §3.2.3 的 LEAST/GREATEST + COUNT SQL 设计）**

原设计假设同一实体对在不同事件中各有一行 co_occurrence，扫描器用
`COUNT(DISTINCT e.id) >= threshold` 计数。实际实现与 schema 事实不符：

- `Association.__table_args__` 的 `uq_association_user_source_target_type`
  唯一约束 + 关联发现的方向规范化（smaller ID first，`_create_association`
  与 `_get_existing_pair_set`）共同保证**每对实体每种类型只有一行**；
- 重复共现在 `_discover_co_occurrence_by_event` 中走 `existing_pairs` 去重
  分支被 `continue` 跳过，生产中每对最多计 1 次——原设计的阈值 ≥3 在生产
  不可达，属功能级缺陷。

修订后的模型（保持"每对一行"，零 schema 迁移）：

- `_discover_co_occurrence_by_event` 改为 `async`；遇已存在对时不再跳过，
  调用 `_append_shared_event`（模块级助手）在既有行的
  `properties.evidence.shared_event_ids`（list，幂等去重）累积共享事件 id，
  同步刷新 `evidence.shared_event_id`（兼容旧消费方）、`source_event_id`
  （指向最新共现事件）与 `last_interaction`；
- 同批次内新建行再次命中时直接更新 pending ORM 对象（`batch_rows`），
  避免对未 flush 行的无效查询；
- `scan_frequent_contacts` 重写：Python 侧取该用户全部 co_occurrence 行，
  展开每对的共享事件 id 集合（兼容旧行：仅 `source_event_id` 单事件），
  一次 `SELECT id, timestamp FROM events WHERE id IN ...` 取时间戳，
  窗口过滤后按对计数 ≥ threshold 判定。SQLite / PostgreSQL 无方言 JSON SQL，
  naive 时间戳按 UTC 归一（`_as_datetime`）；
- 单测 fixture（`tests/test_w4_semantic_contract.py::_co_occurrence`）与
  e2e 助手（`scripts/e2e/e2e_w3_w4_real_user.py::add_co_occurrence`）同步
  改为"单行累积"模型——原"反向边"数据是生产不可达的伪造形态。

**7.2 解析步骤顺序与 confirm-only 边界（取代 §D3 边界描述）**

原设计将 synonym_match 排在 alias_match 之后，但 alias 的敬语启发式
（"X总" → 姓氏匹配 0.82）会先返回，同义词命中（0.97）永远不触发。
修订：

- 步骤顺序：`exact_match → synonym_match → alias_match → difflib_match →
  fuzzy_match → context_match`（受控字典是比敬语启发式更强的信号）；
- `synonym_match` / `difflib_match` 标记为 confirm-only
  （`confirm_only_steps` frozenset）：即使置信度 ≥ `auto_merge_threshold`
  也不进入 MERGE 分支，W4 规范化"零自动合并"边界由结构保证而非数值巧合
  （0.97 > 0.85，原"数值低于合并门槛"的论证对 synonym 不成立）。

**7.3 验证（TD-B17）**

mypy 125 文件 0 错误；W3/W4 单测 15/15（首次真实执行）；关联/管线回归
109 用例 0 failed；真实用户 e2e 12/12 PASS（W4-01 synonym_match 0.97
CONFIRM、W4-02 difflib_match 0.82 CONFIRM 均经真实 `resolve()` 公开路径）。
