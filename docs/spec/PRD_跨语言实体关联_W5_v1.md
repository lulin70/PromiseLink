# PRD — 跨语言实体关联（W5）

> **版本**: v1.2
> **日期**: 2026-09-08
> **状态**: DevSquad 复核修订版，待最终准入签署；未通过 Test Plan approval 不得进入实现
> **父规划**: [ONTOLOGY_SEMANTIC_CONTRACT_PLAN.md](../planning/ONTOLOGY_SEMANTIC_CONTRACT_PLAN.md)（W5 = L4/L5，依赖 W1+W4）
> **承接**: W1+W2 契约已落地；W3 纠偏回流 + W4 实体规范化已落地；离线模式已具备
> **技术设计**: [TECH_DESIGN_跨语言实体关联_W5_v1.md](../design/TECH_DESIGN_跨语言实体关联_W5_v1.md)
> **实施门禁**: 未完成准入测试计划、双数据库/反幽灵/E2E 门禁前，不得写 W5 生产代码。
> **变更说明**: v1.2——补齐 Entity/Todo 共用 operation/audit 事实模型、HMAC secret 生命周期、`key_version`/`operation_key`、并发与 replay 语义、双数据库 migration 门禁、真实用户 E2E、Anti-ghost runner、manifest 及发布阻塞状态。

---

## 1. 背景与问题

### 1.1 现状

W4 落地后的实体规范化能力：

- `Entity.aliases` JSON 字段已存在（同语言别名，靠解析自学习）
- `synonym_dict.py` 两层字典（JSON 配置 + 代码种子），但**种子全部是同语言等价**（如 "张三"→["Zhang San", "老张"] 中英文混合条目极少量，无系统性跨语言覆盖）
- `EntityResolutionEngine` 7 步 pipeline（exact→alias→synonym→difflib→fuzzy→context→llm），阈值 0.85/0.70，`synonym_match`/`difflib_match` 为 confirm-only
- `Step03_SemanticEmbedding` 已存在，`embedding_provider` 支持 local / api（OpenAI 兼容）——**embedding 基础设施已具备，无需新增向量库**

缺口：

- **跨语言主体归一缺失**："John Smith"（英文纪要）与"约翰·史密斯"（中文录入）会创建两个实体，人脉图谱碎片化，承诺/待办跟进断链
- W1 契约黄金集**仅中文样本**——换英文/日文输入时抽取质量无回归仪表
- LLM 抽取 prompt 未明确要求输出跨语言别名——多语言原文中的译名信息在抽取阶段被丢弃
- 同一待办的跨语言表述（"follow up next week" vs "下周跟进"）无归一路径（ROADMAP L5）

### 1.2 核心问题

W1-W4 解决了"中文单语言的解析显式化、纠偏闭环、确定性规范化"，但用户真实输入是**多语言混合**的（英文会议纪要 + 中文复盘 + 日文名片）。跨语言碎片直接削弱产品的核心承诺——人脉/承诺不遗漏。

---

## 2. 目标与非目标

### 2.1 目标

| # | 工作流 | 目标 | 度量 |
|---|---|---|---|
| G-W5-1 | 抽取多语言 | 英文/日文原文录入时，实体抽取质量与中文同级 | 黄金集新增多语言分层，抽取断言全过 |
| G-W5-2 | 跨语言候选 | 同一主体跨语言表述能产生"可能是同一人"候选（不自动合并） | `"John Smith" 录入后 → 候选列表含"约翰·史密斯"，置信度 ≥ 阈值，active entity 数量不变 |
| G-W5-3 | 纠偏闭环 | 跨语言确认/拒绝走 W3 审计回流 | `EntityCorrection` 行含 `action=select_existing`，候选集留痕 |
| G-W5-4 | 跨语言待办（L5） | 同一待办的中/英/日表述生成同一 Todo 的 confirm-only 候选 | 时间语义、语言归一与候选评分；默认关闭，不自动关联 |

### 2.2 非目标（明确不做）

- ❌ **不引入实时翻译 API**（成本高、延迟大——ROADMAP 既定结论）
- ❌ **不做自动翻译录入文本**（保持原文 + 多语言实体，ROADMAP 决策点 3 默认答案）
- ❌ **不做自动合并**——跨语言匹配天然低置信，必须用户确认（继承 W4 硬边界）
- ❌ 不新增向量库（embedding 复用 `Step03` 既有基础设施；若选 embedding 路线，仅复用现有 provider）
- ❌ 不改前端 UI 结构（复用现有多候选人脉纠偏 UI，仅候选依据文案需展示"跨语言匹配"）

---

## 3. 用户故事

| # | 角色 | 故事 | 验收 |
|---|---|---|---|
| US-W5-1 | 用户 | 我先用英文纪要录入了 "John Smith"，后用中文补录"约翰·史密斯"，系统提示"可能是同一人" | 候选列表出现对方，依据含"跨语言匹配"；确认后 aliases 互相追加，仅一个 active 实体 |
| US-W5-2 | 用户 | 我拒绝了跨语言候选，因为其实是两个人 | 拒绝不触发任何合并；`EntityCorrection` 留痕；下次同名输入不再重复推荐（same-pair 冷却） |
| US-W5-3 | 用户 | 我录入日文名片 "ジョン・スミス"，系统能识别并与已有英文/中文实体关联 | 三语映射场景候选产生 |
| US-W5-4 | 用户 | 英文纪要里的 "follow up next week" 和我中文待办"下周跟进"被归为同一待办 | L5 归一候选 confirm-only |
| US-W5-5 | 开发者 | 我改抽取 prompt 或换模型时，多语言抽取质量有回归仪表 | 黄金集多语言层 CI 可跑（LLM 成本 job 手动触发，同 W2） |

---

## 4. 功能需求（FR）

### 4.1 FR-W5-1 抽取阶段多语言输出契约

扩展 W1 抽取 prompt 契约：

- 实体 `name` 始终保留原文写法。
- `canonical_zh` 是独立可选字段：模型有可靠证据时输出，否则为 `null`；它不是 alias。
- `aliases` 只收录有证据的等价写法，不把自动翻译/猜测写成事实。
- 黄金集正例必须填写并断言 `canonical_zh`；无法可靠确定的负例允许 `null`。
- 只有用户在候选确认流程中明确确认、且后端通过候选 token 校验后，`canonical_zh` 才可作为 alias 候选写回；抽取阶段不得自动写入 `Entity.aliases`。
- schema 扩展向后兼容，缺省字段不改变旧行为。

### 4.2 FR-W5-3 跨语言匹配策略

`EntityResolutionEngine` 新增 `_step_cross_language`：

- 必须按请求生命周期或按 `user_id` 隔离；禁止跨 user 复用 engine 可变状态、候选集合、ORM 对象或 embedding cache。
- 字典/alias 命中和 embedding 语义匹配均只生成候选，不执行合并。
- 任何跨语言路径在最终决策层强制 `action=CONFIRM`，客户端不得提交或升级为 `MERGE`。
- embedding 仅在 provider/model/dimension/embedding space/profile 一致时使用；失败、metadata 缺失或空间不一致时安全降级，不允许 API/local 静默跨空间 fallback。
- 独立向量索引是派生数据，主数据库是实体、事件、Todo 和纠偏审计的唯一事实源；W5 初版禁止使用未标 metadata 的持久向量。

### 4.2.1 候选 token 与确认/拒绝语义

候选接口返回服务端签名的 opaque `candidate_token`，绑定：`version`、`key_version`、`user_id`、`event_id`、`scope_type`、`extracted_entity_id`/`source_todo_id`、候选 digest、`operation_key`、resolver 版本、score 版本、embedding space、签发时间、TTL 与 nonce。客户端不得解码、修改或自行构造可信候选集合。

- 默认 TTL 10 分钟且有服务端上限；确认/拒绝成功后 token 一次性消费。
- 后端重新校验签名、绑定关系、digest、resolver/score/space/TTL，并从主数据库重新读取候选。
- 过期、篡改、跨 user/event/entity、候选变化或空间不符按统一错误契约处理：签名/绑定/digest/版本/空间等不合法返回 `candidate_token_invalid`（HTTP 400）；签名有效、scope 正确但首次提交已晚于 `expires_at` 返回 `candidate_token_expired`（HTTP 410），均零业务写入。
- 已完成 token 的重放返回原确认/拒绝结果，不重复 merge、alias、cooldown 或 audit；并发重放同样幂等。
- 客户端不可写 `Entity.properties`，不可提交 score、cooldown、alias、resolver 或 embedding space 作为事实。

### 4.2.2 Entity/Todo operation 与 audit 事实模型

W5 不新增独立 token/cooldown 表，扩展既有 `EntityCorrection` 作为 Entity/Todo 共用 operation/audit 事实源。最小持久化字段为：

```text
token_hash
token_key_version
candidate_digest
operation_key
resolver_version
score_version
embedding_space
token_issued_at
token_expires_at
operation_status
completed_at
result_summary
source_todo_id
selected_todo_id
candidate_todo_ids
```

Entity scope 为 `user_id + event_id + extracted_entity_id`，Todo scope 为 `user_id + event_id + source_todo_id`。`operation_key` 按 scope 唯一；confirm/reject 通过行锁或等价 compare-and-set 只允许一个终态。已完成 operation 的重试返回 `result_summary`，不重复业务写入、alias、cooldown 或 audit；只保存 token hash，不保存原始 token、HMAC secret 或完整输入文本。

### 4.2.3 HMAC secret 生命周期

secret 必须来自受控服务端 secret provider；`key_version` 用于轮换和 emergency revocation，签名比较使用 constant-time comparison。旧 key 仅在既有 token TTL 内有效；首次提交已过 `expires_at` 的有效 token 返回 `candidate_token_expired`，撤销 key version、篡改、错误 scope 或版本不匹配返回 `candidate_token_invalid`，且零业务写入。合法已完成 operation 的 replay 仍返回持久化结果。



### 4.2.4 Token Protocol（规范性契约）

本节为 Entity 与 Todo 共用的唯一 token 规范；技术设计、测试计划和实现必须逐字段遵守，不能用“等价实现”改变语义。

| 字段 | 类型/编码 | 约束 |
|---|---|---|
| `version` | ASCII string | 固定为 `w5-token-v1`；未知版本拒绝 |
| `key_version` | ASCII string | 服务端密钥版本；撤销后新请求拒绝，旧 token 不因轮换自动延长 |
| `user_id`/`event_id` | UUID string | 绑定请求 scope；必须与认证上下文和 URL 一致 |
| `extracted_entity_id_or_source_todo_id` | UUID string | Entity 与 Todo 二选一，按 `scope_type` 解释 |
| `scope_type` | enum | `entity` 或 `todo`；不可由客户端切换 |
| `candidate_digest` | lowercase hex | 对服务端有序候选 DTO 做 RFC 8785 等价的 canonical JSON 后 SHA-256 |
| `operation_key` | lowercase hex/string | 服务端生成；同 scope 唯一，不能由客户端自由重用 |
| `resolver_version`/`score_version`/`embedding_space` | ASCII string | 绑定生成时配置；当前配置不匹配即拒绝 |
| `issued_at`/`expires_at` | UTC RFC3339 | `expires_at > issued_at`；TTL 默认 600 秒且不得超过服务端上限 |
| `nonce` | 128-bit random, base64url | 每次签发唯一；防止同 payload 重签名产生相同 token |
| `signature` | HMAC-SHA256, lowercase hex | 对 canonical payload 签名；服务端 constant-time 比较 |

规范化规则：字段名按上表固定顺序；字符串 UTF-8、Unicode NFC、禁止额外空白；时间统一 UTC；数组按服务端 rank 顺序；签名前不得包含原始 token、secret 或未脱敏输入文本。对外 token 为 `base64url(canonical_payload_bytes || "." || ASCII(signature_hex))` 的 opaque 字符串，客户端只能原样携带。

验证顺序固定为：解析格式 → 查 key version → constant-time 校验签名 → 校验 nonce → 校验认证 scope → 重新计算 candidate digest → 校验 resolver/score/space → 在主库读取 operation。签名、格式、绑定、digest、版本、空间、撤销状态任一步失败均返回 `candidate_token_invalid`（HTTP 400），且在业务事务开启前完成，不产生业务写入；签名有效、scope 正确但首次提交晚于 `expires_at` 时返回 `candidate_token_expired`（HTTP 410）。密钥轮换只影响新签发 token；旧 key 在 TTL 内可验证，emergency revocation 后立即拒绝。已落档终态 operation 的合法 replay 优先返回原结果，不因 token 已过期而改变既有结果。

### 4.2.5 Entity/Todo 共用 operation schema、状态机与 API 错误契约

`EntityCorrection` 是唯一 operation/audit 事实源；不新增 W5 token、cooldown 或 Todo correction 表。以下字段为规范最小集（既有字段沿用原语义，新增字段允许为空以兼容旧数据）：

```text
id, user_id, event_id, correction_type, scope_type
entity_id, source_todo_id, selected_entity_id, selected_todo_id
candidate_entity_ids, candidate_todo_ids, candidate_digest
operation_key, token_hash, token_key_version
resolver_version, score_version, embedding_space
token_issued_at, token_expires_at
operation_status, action, result_summary
created_at, completed_at
```

约束：Entity scope 为 `user_id + event_id + entity_id`，Todo scope 为 `user_id + event_id + source_todo_id`；`operation_key` 在 scope 内唯一；`token_hash` 只能保存不可逆摘要；不得保存 raw token、HMAC secret、完整输入文本或客户端提交的 score/resolver/space/cooldown。所有终态结果通过主库唯一事实判定。

状态机（`invalid` 是请求结果，不是持久化状态）：

| 当前 | 事件 | 下一状态 | 业务写入 | 返回语义 |
|---|---|---|---|---|
| `issued` | 首次提交合法 token | `pending` | 建立 operation/audit 事实 | 进入处理 |
| `pending` | `confirm` | `confirmed` | 一次事务更新 Entity/Todo 与 audit | 成功结果 |
| `pending` | `reject`/`ignore` | `rejected` | 仅写 correction/audit 与 cooldown 事实 | 成功结果 |
| `pending` | TTL 到期且尚未提交 | `expired` | 仅允许记录过期事实，不写业务对象 | `candidate_token_expired` |
| 任一终态 | 相同 operation replay | 保持终态 | 零重复业务写 | 原结果，幂等 |
| 任一终态 | 相反 action 并发/重试 | 保持首个终态 | 零重复业务写 | `operation_already_completed` |
| 任一状态 | 签名/scope/digest/version 不合法 | 不创建/不改变状态 | 零业务写 | `candidate_token_invalid` |

并发 confirm/reject 必须以唯一 `operation_key` 加行锁或等价 compare-and-set 抢占；只有首个提交者能从 `pending` 转移到终态。网络重试不得创建第二条 audit，不得再次 merge、追加 alias 或刷新 cooldown。

API 错误契约适用于 Entity 与 Todo command endpoint，响应统一为 `{error:{code,message,retryable,operation_key}}`，不得返回 token payload：

| code | HTTP | retryable | 零业务写 | 客户端行为 |
|---|---:|---:|---:|---|
| `candidate_token_invalid` | 400 | 否 | 是 | 丢弃 token，重新获取候选 |
| `candidate_token_expired` | 410 | 否 | 是 | 刷新候选，不自动确认 |
| `operation_already_completed` | 409 | 否 | 是 | GET operation 并展示首个结果 |
| `candidate_scope_forbidden` | 403 | 否 | 是 | 停止请求并记录安全事件 |
| `candidate_not_found` | 404 | 否 | 是 | 刷新页面/候选，不创建对象 |
| `operation_conflict` | 409 | 是 | 是 | 退避后读取 operation/result |
| `embedding_space_unavailable` | 503 | 是 | 是 | 使用服务端安全降级结果，不切换空间 |
| `audit_write_failed` | 500 | 是 | 是 | 提示稍后重试；事务必须回滚 |
| `request_invalid` | 422 | 否 | 是 | 修正请求，不重试同一 payload |
| `w5_disabled` | 404/403 | 否 | 是 | 按普通 W4/Todo 流程继续 |

所有 5xx/`operation_conflict` 重试必须带原 `operation_key`，服务端先读 operation 再决定是否重试；禁止客户端自行生成候选集合或将错误转换成 MERGE。


`synonym_dict.py` 字典结构扩展为三语：

- 种子条目 ≥ 10 组人名 + 5 组公司名（中↔英↔日，全部合成数据，红线 §6-1）
- `find_aliases(name, type_)` 语义不变——跨语言别名收编进同一 family
- 用户确认跨语言候选后，仅将人工确认的原文、可靠 aliases 与 `canonical_zh` 写入既有 alias/字典回流路径；抽取阶段的 `canonical_zh` 不自动写入 alias。

### 4.4 FR-W5-4 纠偏闭环集成（复用 W3）

- 跨语言候选确认/拒绝走既有纠偏接口；确认写入 `EntityCorrection(action=select_existing)`，拒绝写入 `EntityCorrection(action=ignore)`。
- 拒绝冷却以 W3 `EntityCorrection(action=ignore)` 审计为唯一事实来源，默认 30 天；不再让客户端写 `Entity.properties`，不新增 W5 冷却表或客户端可写 metadata。
- 确认后仅将用户明确确认的原文、可靠 aliases 和 `canonical_zh` 作为 alias 候选写回；`canonical_zh` 抽取本身不自动成为 alias。
- PII 红线与 W3 一致（原文过 redact、日志零原文）；主数据库审计与业务写入同事务。

### 4.5 FR-W5-5 黄金集多语言分层（扩展 W2）

- 黄金集按 `en_to_zh`、`zh_to_en`、`ja_to_zh`、`zh_to_ja`、`en_to_ja`、`ja_to_en`、person/company、positive/negative 及 Todo 有/无时间信息分层；每个分层必须有非零分母。发布候选报告 Recall@5、MRR@5、false-positive rate、Todo Recall@5、分母、失败 case ID 和基线 commit。
- 发布前必须通过 SQLite/PostgreSQL 独立进程真实用户 E2E、唯一 Anti-ghost runner 和证据 manifest 校验；E2E 只能使用公开 API/UI，不得导入内部 resolver、直接写数据库或只断言 HTTP 状态码。
- 唯一 E2E 命令为 `scripts/e2e/e2e_w5_real_user.py`，唯一 Anti-ghost 命令为 `scripts/quality/check_w5_antighost.py --strict`；manifest 至少包含 commit、命令、数据库、migration head、config digest、结果计数、指标阈值和 PII 扫描结果。

### 4.6.1 Todo 用户状态流（面向用户）

```text
Todo 生成
  └─ W5 开关关闭 → 普通 Todo 流程，不生成跨语言候选
  └─ W5 灰度开启 → 读取服务端候选
       ├─ 无候选/安全降级 → 保留原 Todo，可继续手工编辑
       └─ 有候选 → 展示“可能关联”+ confirm-only
            ├─ 确认 → Todo operation pending → confirmed；只更新 Todo 关联并写 todo audit
            ├─ 拒绝 → Todo operation pending → rejected；原 Todo 不变，写 ignore audit/cooldown
            ├─ 忽略/取消 → 不提交 operation；页面可稍后再次读取候选
            └─ 超时/5xx → 不猜测结果；按 operation_key 重读服务端状态后再重试
```

用户刷新页面、重复点击或多端并发时，前端必须重新读取服务端 operation/result；不得依赖前端内存状态。Todo 文本永远不得写入 `Entity.aliases`，确认不得触发 Entity merge，候选生成不得改变 active Todo 或 active Entity 数量。成功确认/拒绝后再次提交只展示首个结果；只有用户明确操作才允许改变 Todo 关联。


- 配置项 `cross_language_todo_enabled` 默认 `false`，仅在准入测试通过后按灰度开启。
- Todo 候选使用服务端签名 token，绑定 user/event/todo/candidate digest/resolver/score/space/TTL；confirm/reject/audit/cooldown 与实体候选同语义。
- 中/英/日 Todo 所有路径最终 `CONFIRM-only`；确认复用既有 Todo 关联路径，拒绝写 `correction_type=todo`、`action=ignore` 审计；不得触发实体 merge。
- 过期/篡改/重放 token 的零写入与幂等语义必须 E2E 验证。
---

## 5. 非功能需求（NFR）

| # | 需求 | 指标 |
|---|---|---|
| NFR-W5-1 | 跨语言匹配不拖慢解析 pipeline | `_step_cross_language` 单事件增量 < 500ms（字典级 O(1)；语义级批量一次调用） |
| NFR-W5-2 | operation/audit 事实源 | 不新增独立 W5 token/cooldown 表；扩展既有 `EntityCorrection` 承载 Entity/Todo 的 token hash、候选绑定、operation 状态、结果 replay 与 Todo scope；客户端不可写入 `Entity.properties` |
| NFR-W5-3 | 零自动合并 | 跨语言命中 100% CONFIRM（测试门禁硬断言 active entity 数量不变） |
| NFR-W5-4 | 多语言抽取无回归 | 黄金集 multilingual 层字段断言全过；中文层分数不下降 |
| NFR-W5-5 | embedding 复用 | 若选 embedding 路线：不新增向量库/新 provider，复用 `embedding_provider` 既有链路 |
| NFR-W5-6 | 跨用户隔离 | 候选产生与字典自学习均强制 `user_id` 作用域；字典 JSON 按用户隔离或全局只读种子 |

---

## 6. 安全区与红线（继承父规划 §5 + W3/W4 增量）

1. **黄金集/字典种子仅合成数据**——真实姓名/公司名一律伪造（三语一致）。
2. **零自动合并**——跨语言所有路径最终 `CONFIRM-only`，active entity 数量不得因候选生成变化。
3. **服务端候选 token**——候选集合由签名 opaque token 绑定，后端校验 user/event/entity/digest/resolver/score/space/TTL；过期/篡改/重放语义明确且幂等。
4. **审计驱动冷却**——冷却以 W3 `EntityCorrection(action=ignore)` 为事实来源，客户端不可写 `Entity.properties`，不新增 W5 专用表。
5. **canonical_zh 边界**——独立可选；黄金集正例必填；只有人工确认后才能作为 alias。
6. **主库与向量边界**——主数据库是事实源，独立向量索引是派生数据；W5 禁用未标 metadata 持久向量，失败安全降级，禁止 API/local 静默跨空间 fallback。
7. **契约向后兼容**——schema 扩展字段全部 optional，旧数据零迁移。
8. **翻译边界**——禁止在解析链路调用外部翻译 API，保持用户原文。

---

### 7. 决策与范围基线（已由 DevSquad 复核收敛）

| # | 议题 | 当前基线 |
|---|---|---|
| D1 | 语义级跨语言匹配 | embedding 先行；仅同一 provider/model/dimension/space/profile 可比，黄金集不达标或运行失败时安全降级；不做静默跨空间 fallback |
| D2 | 是否翻译录入文本 | 不翻译，保持原文与独立 `canonical_zh`；不调用外部翻译 API |
| D3 | L5 跨语言待办 | 纳入本期；`cross_language_todo_enabled` 默认关闭，准入测试通过后灰度，最终决策 `CONFIRM-only` |
| D4 | 冷却事实来源 | W3 `EntityCorrection(action=ignore)` 审计；客户端不可写 `Entity.properties`，不新增 W5 专用表 |
| D5 | 候选提交可信来源 | 服务端签名 opaque token；candidate digest、resolver、score、space、TTL 均由后端校验 |
| D6 | 数据事实源 | 主数据库是唯一事实源；独立向量索引是可重建派生数据，未标 metadata 的持久向量禁用 |

> 这些是当前产品/技术边界，范围已完成收敛。
---

## 8. 配置、灰度、回滚与可观测性

默认值必须安全关闭：

```text
cross_language_enabled=false
cross_language_todo_enabled=false
cross_language_embedding_enabled=false
cross_language_candidate_token_ttl_seconds=600
cross_language_rejection_cooldown_days=30
cross_language_rollout_percent=0
cross_language_embedding_provider=local
cross_language_embedding_model=all-MiniLM-L6-v2
cross_language_embedding_dimension=384
cross_language_embedding_space=local/all-MiniLM-L6-v2/384
cross_language_embedding_profile_version=w5-v1
```

灰度只按 user 白名单/百分比开启；失败时先回滚 rollout=0，再关闭 W5 开关，不切换 provider/space，不删除主数据库 audit、alias 或确认事实。告警覆盖 token invalid/replay、跨 scope 阻断、metadata 拒绝、主库/向量不一致、审计写失败、safe degrade 超阈值及任何跨语言 `MERGE`。

## 8.1 双数据库 migration 规范序列

W5 不新增独立 token/cooldown 表，但若 `EntityCorrection` 扩展字段需要 migration，SQLite 与 PostgreSQL 必须分别执行同一有序流程，禁止 `Base.metadata.create_all()` 替代真实 migration：

1. **Preflight**：冻结 PR commit、配置 digest、目标 migration head；备份数据库并确认当前 head、UTC 时钟、SQLite `PRAGMA foreign_keys=ON`。
2. **Upgrade**：在临时 SQLite 文件/内存库和真实 PostgreSQL 16 服务上分别执行 `alembic upgrade head`，记录 dialect、old head、new head 和退出码。
3. **Schema verify**：检查 `EntityCorrection` 字段、类型、nullable、唯一约束和索引；校验旧 W3/W4 数据可读，禁止写入 raw token/secret。
4. **Behavior verify**：在两种数据库运行相同的 token replay、confirm/reject、Todo audit/cooldown、UUID、UTC、JSON/JSONB、rollback 核心矩阵。
5. **Rollback drill**：在 disposable 数据库演练 `downgrade`/恢复；不得对已确认事实做破坏性回滚，失败即阻断发布。
6. **Evidence**：manifest 记录 backend、migration head、schema digest、命令、时间、结果和脱敏日志；SQLite、PostgreSQL 证据独立归档。

任何一个数据库未执行真实 migration、head 不一致、foreign key 未启用、schema digest 不一致或核心矩阵未通过，W5 保持 blocked；不得用单库结果推断另一数据库通过。

## 8.2 Manifest schema、validator 与证据策略

W5 证据 manifest 的 `schema_version` 固定为 `w5-evidence-v1`，每个 job 必须输出以下最小 JSON 结构（字段缺失、类型错误、时间倒置、计数不一致均失败）：

```json
{
  "schema_version": "w5-evidence-v1",
  "commit_sha": "40-hex",
  "command": "string",
  "started_at": "UTC RFC3339",
  "finished_at": "UTC RFC3339",
  "database_backend": "sqlite|postgresql",
  "migration_head": "string",
  "config_digest": "sha256 hex, no secret",
  "embedding_profile": {"provider":"string","model":"string","dimension":384,"space":"string","profile_version":"string"},
  "sample_count": 0,
  "counts": {"pass":0,"fail":0,"skip":0,"xfail":0},
  "metrics": {"name":{"value":0.0,"threshold":"string","comparator":"string"}},
  "artifacts": ["relative/path"],
  "pii_scan_result": "pass|fail",
  "validator_version": "w5-manifest-validator-v1"
}
```

Validator 必须校验：上述 JSON schema、`commit_sha` 与运行 commit、命令 allowlist（仅允许 `w5-contract-unit`、`w5-integration-sqlite`、`w5-integration-postgresql`、`w5-golden`、`w5-e2e`、`w5-performance`、`w5-anti-ghost`）、UTC 时间和 `finished_at >= started_at`、backend/head 与实际数据库、`sample_count` 与 evaluator 分母、pass/fail/skip/xfail 总数、metrics comparator/threshold、artifact 路径限定在 evidence root、PII/secret 扫描结果为 `pass`。任一失败返回非零退出码并阻断发布；validator 不得自动修补缺失字段。

W4 baseline 不在文档闭环阶段凭空生成。其唯一契约为 `schema_version=w4-baseline-v1`、`baseline_commit`、`dataset_version=w4-golden-v1`、`evaluator_version=w4-evaluator-v1`、正整数 `sample_count`、分层 counts/metrics、`artifacts` 和 `pii_scan_result`；必须由实际 W4 测试/evaluator 运行生成并绑定 commit。当前可追溯来源为 `tests/test_w4_semantic_contract.py` 与 `scripts/e2e/e2e_w3_w4_real_user.py`，但在真实运行产生 `docs/evidence/w4_baseline.json` 前，不得宣称 W4 baseline artifact 已存在或达到发布证据要求。

证据只保存合成 ID、脱敏摘要、指标和必要日志片段；原始 token、HMAC secret、完整输入文本、姓名/邮箱/手机号不得进入 manifest、artifact、日志或截图。证据 owner 为测试角色，运维负责归档访问控制；默认保留 180 天，发布/回滚证据至少保留至下一次 W5 版本发布后 30 天，安全事件证据按安全团队 hold，不得因普通清理删除。

## 8.3 灰度 RACI、告警阈值与回滚证据

| 活动 | R（执行） | A（最终负责） | C（协商） | I（知会） |
|---|---|---|---|---|
| Token/schema/迁移门禁 | 测试、架构 | 架构 | 安全、运维 | 产品、编码 |
| Golden/W4 baseline | 测试 | 测试 | 架构、产品 | 运维、编码 |
| 真实用户 E2E | 测试、UI | 产品 | 安全、运维、架构 | 编码 |
| 灰度提量 | 运维 | 产品 | 架构、安全、测试 | 编码、UI |
| 告警响应/回滚 | 运维 | 运维 | 安全、架构、产品 | 测试、编码、UI |
| 证据归档/retention | 运维 | 测试 | 安全 | 产品、架构 |

提量必须按 `0% → allowlist → 1% → 5% → 25% → 100%`，每阶段至少观察一个业务周期（≥7 天且 ≥1k 候选请求/天）；下一阶段前必须有四类角色书面批准、双库 manifest 验证通过、W4 baseline 无回归、告警无未关闭 P1/P2。回滚顺序固定为 `rollout_percent=0 → cross_language_todo_enabled=false → cross_language_embedding_enabled=false → cross_language_enabled=false`，不删除 audit/alias/confirmed facts。

默认告警阈值：任一跨语言 `MERGE`、任一跨 scope 成功写入、任一 PII/secret 命中、任一 audit write failure 为 **P0 立即回滚并 paging**；`candidate_token_invalid` 在 5 分钟内超过请求量 5% 或较前一小时基线增长 3 倍为 **P1 paging**；主库/向量 truth conflict > 0、vector metadata rejected > 1%、safe degrade > 10%、confirm/reject 5xx > 1%（5 分钟）为 **P1 paging**；p95 latency 超预算 20%、Todo cooldown suppressed 较基线增长 3 倍为 **P2 ticket + 观察**。阈值触发时必须保存触发前后 30 分钟脱敏 metrics、manifest、配置 digest、migration head、回滚命令和审批记录。


| 里程碑 | 交付物 | 验收标准 |
|---|---|---|
| **M-W5.1** | 抽取契约扩展 + multilingual 黄金集 | 英/日样本断言全过；正例 `canonical_zh` 必填且独立；中文层无回归；仅文档/测试资产先行 |
| **M-W5.2** | 三语字典 + 匹配策略 + candidate token | 签名/绑定/TTL/篡改/过期/重放和幂等测试通过；跨语言 100% CONFIRM；active entity 数不因候选变化 |
| **M-W5.3** | W3 审计闭环 + 审计驱动冷却 | 确认 alias 仅人工确认后写回；拒绝 `EntityCorrection(action=ignore)` 驱动冷却；客户端 properties 写入被拒绝 |
| **M-W5.4** | 跨语言 Todo | `cross_language_todo_enabled` 默认关闭；灰度后中英日 candidate token→confirm/reject/audit/cooldown E2E 通过；不得实体 merge |
| **M-G3** | 发布前模拟真实用户 E2E | 合成用户/数据完成英文纪要→中文补录→候选确认/拒绝→重放/过期→审计/alias 校验，SQLite/PostgreSQL 各一轮并归档证据 |

### 准入测试计划（实现前）

- 契约/单元：`canonical_zh`、CONFIRM-only、阈值/TTL/space/cache key。
- 安全：token 篡改/过期/跨 scope/digest/resolver/score/space、客户端伪造 candidate/merge/properties。
- 幂等：confirm/reject 首次、重复、并发重试只产生一条 audit。
- 双数据库：SQLite/PostgreSQL 全路径、事务回滚、主库事实与派生索引不一致。
- 隔离/反幽灵：双 user 交错请求、engine/cache/index 不跨 scope、无 W5 专用表、无隐式跨空间 fallback/跨语言 MERGE。
- E2E：实体与 Todo candidate token→confirm/reject/audit/cooldown、provider/向量失败安全降级、灰度/回滚、告警演练；发布前做模拟真实用户旅程。
- 准入必须无 skip/xfail 掩盖失败，独立测试角色维护测试，未全部通过不得进入实现。

---

## 10. 生命周期与当前状态

文档先行：当前仅完成 PRD/技术设计收敛与准入测试计划，**不得进入实现、不得编写生产代码**。下一步必须先完成并通过双数据库、反幽灵、独立测试角色、指标告警演练和真实用户模拟 E2E；通过后才可进入实现→验证→发布流程。
