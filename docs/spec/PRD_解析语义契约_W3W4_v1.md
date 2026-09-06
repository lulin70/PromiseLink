# PRD — 纠偏回流（W3）与实体规范化（W4）

> **版本**: v1.0
> **日期**: 2026-09-05
> **状态**: 已裁决，进入设计阶段
> **父规划**: [ONTOLOGY_SEMANTIC_CONTRACT_PLAN.md](../planning/ONTOLOGY_SEMANTIC_CONTRACT_PLAN.md)（W3/W4 工作流，七角色共识）
> **承接**: W1+W2 解析语义契约已落地（commit 8bf08f6、f576a06），本 PRD 在契约之上构建纠偏数据流与确定性规则
> **变更说明**: v1.0 初版——W3 纠偏回流 + W4 实体规范化 + 共现规则三件事的需求定义；父规划 §7 四项裁决已落档

---

## 1. 背景与问题

### 1.1 W3 现状：纠偏一次性 UI 交互，无数据闭环

现有能力：
- `POST /events/{event_id}/correct` 五类纠偏（人脉 select_existing/create_new/ignore、待办 edit/delete/add、承诺 confirm/ignore/modify/add、关联 modify/delete）
- `POST /entities/{entity_id}/merge` + `POST /entities/{entity_id}/confirm` + `GET /entities/duplicates` 手动合并三件套
- 前端 `CorrectionPanel.tsx` 4-zone（people/relation/todo/promise）完整交互

缺口：
- 纠偏仅"原地修改"业务数据，**无审计行、无回放能力**——用户每次选择正确人脉的信号被丢弃
- 纠偏原文片段含 PII 时直接走业务字段，**无脱敏**（`correct_event()` 全程未触发 `redact_pii_from_text`）
- 月度纠偏模式审核、契约迭代所需的"按错误模式聚类"视图无落点
- 180 天保留策略未落地

### 1.2 W4 现状：5 步算法 + 12 类关联，但缺乏确定性规则层

现有能力：
- `EntityResolutionEngine` 5 步算法（exact→alias→fuzzy→context→llm）：基于 `rapidfuzz.token_sort_ratio`，阈值 0.85/0.70
- `Entity.aliases` JSON 字段已存个人别名
- `AssociationDiscoveryEngine` 12 类关联 + 共现（单事件）+ 180 天半衰期
- `EntityMergeService` 人工合并 + 引用迁移（todos/associations/embeddings）

缺口：
- **无受控同义词字典**（仅中文敬称白名单硬编码），公司/中文人称别名靠 aliases 自学
- **无 difflib 80% cutoff**（规划明确提到，rapidfuzz 外的零依赖旁路）
- **3 次/90 天共现规则**未实现（仅单事件共现）
- **规范化仅"产生候选"边界**未硬编码测试覆盖——存在自动合并误判风险
- `RelationshipBrief` 不联动高频联系人标签

### 1.3 核心问题

W1 解决了"解析语义显式化"，W2 提供了"换模型/改 prompt 的回归仪表"，但**契约之外的两条 Ontology 关键路径仍是隐式的**：

1. **纠偏数据流**——用户是 W3 的真值源，纠偏数据是后验派 Ontology 自演化的燃料
2. **确定性规则层**——SQL/规则算的（共现频次、同义表）不应进 LLM，确定性等价或更高的结论

后果：解析质量提升依赖 LLM 反复试错，月度契约迭代无数据底座。

---

## 2. 目标与非目标

### 2.1 目标

| # | 工作流 | 目标 | 度量 |
|---|---|---|---|
| G-W3 | 纠偏回流 | 每次纠偏留痕（脱敏后），180 天保留，按错误模式聚类可查 | `EntityCorrection` 表存在；POST `/correct` 同事务写入；月度聚合仅统计、不含原文 |
| G-W4 | 实体规范化 | 同义词字典 + difflib 80% cutoff + 3 次/90 天共现规则全部落地 | `synonym_dict.py` 启动加载；共现扫描 Step 入 pipeline；`Entity.properties.frequent_contact` 字段命中阈值 |

### 2.2 非目标（明确不做）

- ❌ 不改 LLM prompt（沿用 W1 契约）
- ❌ 不引入向量库/embedding（继承父规划 §6）
- ❌ 不做跨语言别名（L4/W5）
- ❌ 不改前端 UI（仅 `EventCorrectResponse` 类型补字段 + `CorrectionPanel` 类型同步）
- ❌ 不做自动合并——W4 规范化只产生候选，必须用户确认

---

## 3. 用户故事

### 3.1 W3 用户故事

| # | 角色 | 故事 | 验收 |
|---|---|---|---|
| US-W3-1 | 用户 | 我在多候选人脉场景选了"青梧科技林晚秋"，下次遇到类似歧义时系统能记住偏好 | 月度纠偏聚合视图展示「同名不同公司」模式计数 |
| US-W3-2 | 运维 | 排查线上纠偏质量突变 | 日志 `correction_recorded` 含 `correction_type`、`selected_entity_id`、`contract_version` |
| US-W3-3 | 隐私合规 | 纠偏记录 180 天后自动清理 | 清理 cron 跑通；聚合统计保留（模式数/最近时间），原文/片段清除 |
| US-W3-4 | 开发者 | 业务写入失败时审计行也回滚（无半成功） | `correct_event` 整体一个事务，failure 注入验证全部回滚 |

### 3.2 W4 用户故事

| # | 角色 | 故事 | 验收 |
|---|---|---|---|
| US-W4-1 | 用户 | 我录入「青梧的林总」时，系统通过字典识别这是「林晚秋」 | `EntityResolution` 命中 `_step_synonym`，候选分数 0.97；不自动合并，仅入候选 |
| US-W4-2 | 用户 | 我看到同义词建议列表可确认/拒绝 | UI 显示「可能是同一人 + 依据」；拒绝不触发任何持久化变更 |
| US-W4-3 | 用户 | 我的人脉 A 和 B 在 3 个不同事件中共同出现，应被标记为「高频联系人」 | `Entity.properties.frequent_contact.count >= 3` + `last_seen` 在 90 天内；`RelationshipBrief` 显示此关系 |
| US-W4-4 | 用户 | 仅出现 2 次或跨度超过 90 天，不应误标 | 边界测试：2 次共现/3 次跨 91 天 → `frequent_contact` 字段不存在或 count<3 |

---

## 4. 功能需求（FR）

### 4.1 W3 — 纠偏回流

#### FR-W3-1 EntityCorrection 模型

新表 `entity_corrections`（`src/promiselink/models/entity_correction.py`）：

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `id` | UUID PK | 是 | |
| `user_id` | UUID indexed | 是 | 隔离 |
| `event_id` | UUID FK→events.id | 是 | 事件上下文 |
| `correction_type` | str(20) | 是 | enum: `entity / todo / promise / association` |
| `entity_id` | UUID FK→entities.id nullable | 否 | 仅 entity/promise/association 纠偏有 |
| `original_extracted_text` | Text | 否 | **先过 redact_pii_from_text 再写入** |
| `original_canonical_name` | str(200) | 否 | |
| `candidate_entity_ids` | JSONB | 否 | 候选集 id 列表（仅 entity 纠偏） |
| `selected_entity_id` | UUID nullable | 否 | 用户最终选择 |
| `action` | str(20) | 是 | 与 `EventCorrectRequest.action` 对齐：`select_existing/create_new/ignore/edit/delete/add/modify/confirm` |
| `created_at` | DateTime(timezone=True) indexed | 是 | |

索引：
- `idx_entity_corrections_user_time(user_id, created_at DESC)`
- `idx_entity_corrections_event(event_id)`
- `idx_entity_corrections_type_time(correction_type, created_at DESC)`

#### FR-W3-2 写入埋点

`POST /events/{event_id}/correct`（`src/promiselink/api/v1/event_pipeline_api.py:331`）在每个纠偏分支（人脉/待办/承诺/关联）落 `EntityCorrection` 行，**与业务写入同事务**。原文片段必先 `redact_pii_from_text()` 再写入 `original_extracted_text`。

#### FR-W3-3 PII 脱敏

`redact_pii_from_text` 现有 5 类（手机/邮箱/身份证/银行卡/微信号）直接复用。**扩展**覆盖：
- 姓名/公司 — 不强脱敏（业务实体必须保留识别度），但若测试断言手机/邮箱/身份证正则零命中必须通过
- 日志 `correction_recorded` 输出仅 `event_id`/`correction_type`/`action`/`entity_id`/`user_id`，**绝不打印** `original_extracted_text` / `selected_entity_id` 外的内容

#### FR-W3-4 聚合视图（只读 + 仅模式统计）

新增 `GET /api/v1/entity-corrections/aggregations?days=30`：
- 按 `correction_type × action` 分组统计 count + 最近时间
- 不返回 `original_extracted_text`、`selected_entity_id`、`candidate_entity_ids` 中任何原文或可识别 id 之外的字段
- 仅返回 `{correction_type, action, count, last_seen}` 四元组

#### FR-W3-5 180 天保留

新文件 `src/promiselink/services/entity_correction_retention.py`：
- `async def cleanup_entity_corrections(session, retention_days=180) -> int`：删除 `created_at < now() - 180d` 的行
- 注册后台 worker：参照 `main.py:_scheduled_event_maintenance()` 风格，每日 03:00 UTC 跑一次（与现有 scheduled_events 共用 `_shutdown_event`）
- 配置：`config.py` 新增 `entity_correction_retention_days: int = 180`

#### FR-W3-6 前端类型同步

`frontend/src/services/api.ts:330-341` `EventCorrectResponse` 补 `promises_created` + `associations_updated` 字段（v5.6 后端已声明但前端 TS 类型遗漏）。
`CorrectionPanel.tsx` 无 UI 改动（仅 TS 类型断言补全）。

### 4.2 W4 — 实体规范化

#### FR-W4-1 同义词字典

新文件 `src/promiselink/services/synonym_dict.py`：
- `PERSON_SYNONYMS: dict[str, list[str]]`（默认种子 5 条，例：`{"张三": ["Zhang San", "老张"]}`）
- `COMPANY_SYNONYMS: dict[str, list[str]]`（默认种子 3 条，例：`{"阿里巴巴": ["阿里", "Alibaba"]}`）
- `load_synonyms(path: str | None = None)`：从 `data/synonyms.json`（首次启动从代码常量填充）加载
- `find_aliases(name: str, type_: Literal["person","company"]) -> list[str]`：查询该 name 的所有别名

#### FR-W4-2 difflib 80% cutoff

新文件 `src/promiselink/services/entity_normalization.py`：
- `_step_difflib_fuzzy()`：用 `difflib.SequenceMatcher.ratio() >= 0.80` 返回 `(confidence=0.82, matched_fields={"name": ratio, "method": "difflib"})`
- 在 `EntityResolutionEngine.resolve()` 的 `steps` 列表最前插入 `("synonym_match", _step_synonym, 0.97)`、alias_match 之后插入 `("difflib_match", _step_difflib_fuzzy, 0.82)`，不破坏现有 4 步
- `_step_synonym` 命中即返回 `confidence=0.97`（同义表是确定性最高的旁路）

#### FR-W4-3 规范化只产生候选

**硬约束**：`_step_synonym` / `_step_difflib_fuzzy` 命中后，引擎返回 `ResolutionAction.CONFIRM`（不是 MERGE）——必须用户确认。这是继承父规划 §6「❌ 不做自动合并」的硬边界，测试门禁硬断言「规范化命中时 active entity 数量不变」。

#### FR-W4-4 3 次/90 天共现规则

新文件 `src/promiselink/services/frequent_contact_scanner.py`：
- `async def scan_frequent_contacts(session, user_id) -> list[dict]`
- SQL 聚合：按 `(source_entity_id, target_entity_id)` 在 90 天内 `COUNT(DISTINCT event_id) >= 3`
- 给满足条件的实体对 → 给两端 `Entity.properties["frequent_contact"] = {"count": n, "since": ..., "last_seen": ..., "window_days": 90}`
- 触发 `RelationshipBriefService.update_brief_from_event` 联动 `data["frequent_contact_flag"]`

新 Step `Step10b_FrequentContactScan`（`src/promiselink/services/steps/step_10b_frequent_contact.py`）：
- 注册到 `_PIPELINE_STEPS`（在 Step10 之后、Step11 之前）
- `config.py` 新增 `co_occurrence_threshold: int = 3`、`co_occurrence_window_days: int = 90`
- 边界：阈值与窗口天数**必须可配置**（父规划 §4 编码角色意见）

#### FR-W4-5 高频联系人 API

新增 `GET /api/v1/entities/{entity_id}/frequent-contacts`：
- 返回该实体的所有频繁联系对（另一端实体 id + name + count + last_seen + window_days）
- 仅 200；不存在或跨用户 → 404

---

## 5. 非功能需求（NFR）

| # | 需求 | 指标 |
|---|---|---|
| NFR-W3-1 | 纠偏事务原子性 | `correct_event` 内任一写入失败 → 全部回滚（测试断言事务注入） |
| NFR-W3-2 | PII 零泄露 | 落库前后正则扫描：手机/邮箱/身份证格式零命中 |
| NFR-W3-3 | 保留清理幂等 | 同一秒连续两次 cleanup → 第二条删 0 行 |
| NFR-W3-4 | 180 天清理对聚合影响 | 清理仅删行，不影响 `correction_type × action` 聚合计数（聚合覆盖完整时间窗口） |
| NFR-W4-1 | 同义词字典加载性能 | < 50ms（启动一次） |
| NFR-W4-2 | difflib 不显著拖慢 resolution | `_step_difflib_fuzzy` 单次 < 1ms（已有 alias_index 是 O(1) 候选过滤） |
| NFR-W4-3 | 共现扫描 SQL 性能 | `idx_associations_source_event_id` + `idx_entities_user_id` 已存在，< 200ms（5k entities 量级） |
| NFR-W4-4 | 零 schema 漂移 | W4 不新增/修改表（用 `Entity.properties` JSON 字段扩展） |
| NFR-W4-5 | 零 LLM 成本 | W4 全部用 SQL/规则/字典/difflib，不触发 LLM 调用 |

---

## 6. 安全区与红线（继承父规划 §5 + 增量）

### W3 红线
1. **原文片段必脱敏**：写入 `original_extracted_text` 前必过 `redact_pii_from_text`
2. **聚合视图零原文**：仅返回 `{correction_type, action, count, last_seen}`，绝不返 `raw_text` / `evidence_quote` / id 之外字段
3. **日志零原文**：`correction_recorded` 日志键值仅含 `event_id / correction_type / action / entity_id / user_id / contract_version`
4. **跨用户不可见**：`GET /entity-corrections` 与聚合端点均强制 `user_id == current_user`

### W4 红线
1. **零自动合并**：`_step_synonym` / `_step_difflib_fuzzy` 命中后 `action=CONFIRM`，绝不 `MERGE`
2. **阈值可配置**：3 次/90 天必须可在 settings 改，禁写死
3. **共现按事件去重**：`COUNT(DISTINCT event_id)`，同一事件重复处理不计
4. **跨用户隔离**：扫描 SQL 强制 `WHERE user_id = :uid`

---

## 7. 裁决记录（继承父规划 §7，W3/W4 子项）

| # | 议题 | 裁决 | PRD 落地 |
|---|---|---|---|
| 1 | W1+W2 本周启动 | ✅ 可以 | 已落地 (commit 8bf08f6、f576a06) |
| 2 | 黄金集 CI 触发 | 手动，或每次推送 Git 时 | W1 PRD FR-3 双层方案 |
| 3 | **纠偏数据保留 180 天** | ✅ 可以 | FR-W3-5 + NFR-W3-3 |
| 4 | **W4 共现阈值 3 次/90 天** | ✅ 可以 | FR-W4-4 + NFR-W4-3 |

---

## 8. 里程碑与验收

| 里程碑 | 交付物 | 验收标准 |
|---|---|---|
| **M-W3.1**（D1-2） | FR-W3-1 模型 + FR-W3-2 写入埋点 + FR-W3-3 PII 脱敏 | `correct_event` 同事务写 `EntityCorrection`；脱敏单测覆盖 5 类 PII；事务回滚注入测试 |
| **M-W3.2**（D3-4） | FR-W3-4 聚合视图 + FR-W3-5 180 天保留 + FR-W3-6 前端同步 | 聚合端点 200 + 零原文；cleanup worker cron 跑通；TS 类型补字段 |
| **M-W4.1**（D1-2） | FR-W4-1 同义词字典 + FR-W4-2 difflib + FR-W4-3 边界 | `_step_synonym` / `_step_difflib_fuzzy` 命中 `CONFIRM` 而非 `MERGE`；边界测试 active entity 数量不变 |
| **M-W4.2**（D3-5） | FR-W4-4 共现规则 + FR-W4-5 API + Step10b 注册 | `Entity.properties.frequent_contact` 命中 3/90 天；2 次/91 天不触发；`GET /frequent-contacts` 200 |
| **M-G1-G2**（D5-6） | 全量回归 + ruff + 类型 | 0 failed；ruff 0；契约哈希不变（仅扩字段） |
| **M-G3**（D7） | 真实用户 e2e：`scripts/e2e/e2e_w3_w4_real_user.py` | 同名纠偏选已有/创建/忽略 3 场景 + 共现 3/2/91 天边界全过 + 证据归档 |

---

## 9. 生命周期后续

按项目生命周期推进：
PRD（本文档）→ **技术设计文档** → **测试计划**（G1-G4） → 实现 → 验证 → 发布。每阶段文档先行，达成共识后进代码。

W3 与 W4 实施顺序：**W3 M-W3.1 → W3 M-W3.2 → W4 M-W4.1 → W4 M-W4.2 → G1-G3 收尾**（W3 为 W4 提供确认数据回流底座，符合父规划 §2 表中「W3 为 B4 提供确认数据回流底座」）。
