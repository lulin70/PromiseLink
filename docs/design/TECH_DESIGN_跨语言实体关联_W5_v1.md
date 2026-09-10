# 技术设计 — 跨语言实体关联（W5）

> **版本**: v1.2
> **日期**: 2026-09-08
> **状态**: DevSquad 复核修订版，待最终准入签署；未通过 Test Plan approval 不得进入实现
> **PRD**: [PRD_跨语言实体关联_W5_v1.md](../spec/PRD_跨语言实体关联_W5_v1.md)
> **父规划**: [ONTOLOGY_SEMANTIC_CONTRACT_PLAN.md](../planning/ONTOLOGY_SEMANTIC_CONTRACT_PLAN.md)
> **目标版本**: v1.2.x
> **实施门禁**: Test Plan v1.2 未获四类 DevSquad 角色最终批准前，不得编写或合并 W5 生产代码、migration、CI job 或测试占位文件。

---

## 1. 设计目标与硬边界

### 1.1 目标

本设计将 W5 PRD 转换为可实施的技术方案，覆盖：

1. 英文、中文、日文实体的抽取与别名保留。
2. embedding-first 的跨语言实体候选生成。
3. 字典、别名、embedding、必要时 LLM fallback 的统一评分管线。
4. 跨语言候选的 confirm-only 约束与 W3 审计闭环。
5. 拒绝后的同一实体对冷却。
6. 英文/中文/日文 Todo 的 confirm-only 关联。
7. SQLite/PostgreSQL、用户隔离、PII 与离线模式兼容。

### 1.2 不变的硬边界

- 跨语言命中永远只能产生 `CONFIRM`，不得自动 `MERGE`。
- 不调用外部翻译 API，不改写用户原文。
- 不新增向量数据库；不新增独立的 W5 token/cooldown 表。扩展既有 `EntityCorrection`，作为 Entity/Todo 共用 operation/audit 事实源，承载 token hash、operation 状态、候选绑定、结果 replay 与 Todo scope；不把客户端输入当作事实源。
- 真实姓名、公司名、手机号、邮箱不得进入黄金集、种子字典或日志。
- 所有候选查询、embedding、字典学习均以 `user_id` 为边界；`EntityResolutionEngine` 必须按请求生命周期或按 user 隔离，禁止跨 user 复用可变实体对象、候选集和缓存。
- embedding 或 LLM 不可用时，系统必须安全降级为“无候选/需人工确认”，不能扩大自动合并范围。
- 跨语言所有路径在最终决策层硬性 `CONFIRM`，任何分数、LLM 结论或客户端字段均不得升级为 `MERGE`。
- 主数据库是实体、事件、Todo、纠偏审计的唯一事实源；独立向量索引仅为派生数据，W5 初版不得使用缺少完整 metadata（provider/model/dimension/space/profile/version）的持久向量。

---

## 2. 代码现状与设计约束

| 能力 | 当前实现 | W5 设计约束 |
|---|---|---|
| 实体解析 | `EntityResolutionEngine.resolve()` 已有 exact/synonym/alias/difflib/fuzzy/context/LLM 顺序 | 增加独立 `_step_cross_language`，复用 `ResolutionResult`，不破坏 W4 confirm-only |
| embedding | `EmbeddingProvider.embed/embed_batch`，支持 local/api 与缓存 | W5 使用同一 provider 在同一 embedding space 内比较；禁止混用不可比向量 |
| Step03 | `Step03_SemanticEmbedding` 为实体和事件写入既有语义索引 | W5 候选匹配不得依赖缺少完整 metadata 的持久向量，独立向量索引始终是可重建派生数据，主数据库仍为事实源 |
| 同义词 | `synonym_dict.py` 双层字典 | 扩展为三语 family；只有人工确认后的 alias 才能写回，`canonical_zh` 不自动成为 alias |
| 纠偏 | `POST /events/{event_id}/correct` + `record_correction()` 同事务 | 候选 token 绑定并校验 user/event/extracted entity/digest/resolver/score/space/TTL；拒绝冷却以 W3 `EntityCorrection(action=ignore)` 审计为事实来源；禁止客户端写 `Entity.properties` |
| Todo | `TodoGenerator` 当前为名称 substring 首命中 | W5 增加独立 `TodoResolution` 候选流程，候选 token/confirm/reject/audit/cooldown 与实体路径同语义，禁止继续扩大 first-substring-wins 语义 |

### 2.1 embedding 维度问题

当前代码存在以下事实：

- API embedding 默认维度为 768；本地 `all-MiniLM-L6-v2` 为 384 维；sqlite-vec 表按 384 维定义。
- W5 的持久向量 metadata 至少包含 `provider`、`model`、`dimension`、`embedding_space`、`profile_version`、`created_at`；缺一项即视为不可用。
- cache key 必须包含 `user_id`（或明确的全局只读 scope）、`provider`、`model`、`dimension`、`embedding_space`、`profile_version` 与内容 digest；禁止 API/local 或不同空间静默 fallback。

因此 W5 不直接把不同来源的历史向量放在同一比较空间中。W5 v1 采用以下策略：

1. 跨语言候选评分优先使用当前请求生命周期内由同一个 provider/model/space/profile 批量生成的向量。
2. 持久化语义索引只有在 metadata 完整且与当前配置逐项一致时才可用于召回；独立索引故障不得阻断主数据库读写。
3. 无法确认向量空间一致时，禁止 API/local 间静默切换；仅可在显式配置且目标空间一致时走受控 fallback，否则直接安全降级。
4. embedding cache key 增加 `provider/model/dimension/embedding_space/profile_version` 命名空间，避免结果互相污染。
5. 首个实现版本默认不要求迁移既有向量；向量重建作为独立运维任务，不阻塞无 embedding 的基础解析。

---

## 3. 总体架构

```text
事件输入
  |
  v
Step02 Extract
  ├─ language_hint / detected_language
  ├─ original_name
  ├─ canonical_zh (optional)
  └─ multilingual aliases (optional)
  |
  v
EntityResolutionEngine
  ├─ exact_match
  ├─ synonym_match              W4，confirm-only
  ├─ alias_match
  ├─ cross_language_match       W5，confirm-only
  │    ├─ language gate
  │    ├─ three-language dictionary
  │    ├─ alias family
  │    ├─ embedding recall
  │    └─ optional LLM fallback（仅显式同空间配置允许；否则安全降级）
  ├─ 最终决策层：所有跨语言路径强制 `CONFIRM`，客户端不得改变 action
  └─ 主数据库事实源；向量索引仅派生，可丢弃并重建
  |
  ├─ MERGE：仅既有同语言强匹配路径允许，跨语言路径禁止
  ├─ CONFIRM：返回候选、分数、方法、解释
  └─ CREATE：没有达到确认线
  |
  v
Candidate API / CorrectionPanel
  ├─ 展示跨语言匹配依据
  ├─ 用户确认或拒绝
  └─ POST /events/{id}/correct
       ├─ merge_entities()
       ├─ 双向 alias/canonical_zh 写回
       └─ record_correction() 同事务

TodoResolution（Step04 后）
  ├─ 显式实体 ID / alias
  ├─ 时间语义归一
  ├─ embedding 候选
  └─ confirm-only + correction audit
```

### 3.1 候选 token 与统一候选协议

```text
candidate_token = base64url(canonical_payload_bytes || "." || ASCII(signature_hex))
canonical_payload = W5-CJ-v1 ordered object:
  version,
  key_version,
  user_id,
  event_id,
  scope_type,
  extracted_entity_id_or_source_todo_id,
  candidate_digest,
  operation_key,
  resolver_version,
  score_version,
  embedding_space,
  issued_at,
  expires_at,
  nonce
signature_hex = lowercase hexadecimal HMAC-SHA256(server_secret, canonical_payload_bytes)
```

- W5-CJ-v1 是唯一 canonical serialization：字段按规范固定顺序输出；JSON 使用紧凑分隔符、UTF-8、Unicode NFC；时间使用 UTC RFC3339；数组按服务端 rank 顺序；数字使用 RFC 8785 确定性表示。固定字段顺序优先于通用 JSON key 排序。
- 对外 token 固定为 `base64url(canonical_payload_bytes || "." || ASCII(signature_hex))`；`signature_hex` 是 64 位小写十六进制文本，解码后的 payload bytes 与签名文本之间只有一个 ASCII `.`。客户端只能原样携带 opaque token。
- `candidate_digest` 对服务端生成的有序候选 ID、rank、score、method、confirm-only 标记及必要 metadata 做 W5-CJ-v1 canonical JSON 摘要；token 绑定 `user/event/scope`、resolver/score/embedding space 与 TTL。
- 默认 TTL 为 10 分钟，必须配置上限；确认或拒绝成功后 nonce/token 进入一次性消费状态。W5 不新增 token 表：消费状态与结果以现有 `EntityCorrection`/Todo correction 审计事实判定，重复提交返回同一已落档结果。
- 后端确认 token 格式、签名、版本、TTL、user/event/scope、candidate digest、resolver/score/space 与当前服务配置逐项一致，再从主数据库重新读取实体和候选；任何一项失败均不得写入。
- malformed、tampered、scope-invalid、digest-invalid、resolver/score/space-invalid、revoked 或 unknown-version token 返回 `candidate_token_invalid`（HTTP 400）；只有签名有效、scope 正确且首次提交时钟晚于 `expires_at` 的 token 返回 `candidate_token_expired`（HTTP 410）。已完成 operation 的合法 replay 优先返回已落档结果，不因当前时间超过 TTL 而改变结果。

### 3.1.1 Normative Token Protocol

Entity 与 Todo 只能使用同一 `w5-token-v1` opaque protocol。payload 字段、类型和顺序固定为：`version`, `key_version`, `user_id`, `event_id`, `scope_type`, `extracted_entity_id_or_source_todo_id`, `candidate_digest`, `operation_key`, `resolver_version`, `score_version`, `embedding_space`, `issued_at`, `expires_at`, `nonce`。字符串使用 UTF-8 + Unicode NFC，时间使用 UTC RFC3339，候选数组按 rank 顺序，数字使用 RFC 8785 确定性表示；W5-CJ-v1 的固定字段顺序优先于通用 JSON key 排序。对 canonical payload bytes 做 SHA-256 digest，使用对应 `key_version` 的 HMAC-SHA256 签名并编码为 64 位小写十六进制文本，签名比较必须 constant-time。对外 envelope 固定为 `base64url(canonical_payload_bytes || "." || ASCII(signature_hex))`，解码后只允许一个 ASCII `.` 分隔 payload bytes 与签名文本；客户端不得解码、修改或构造 token。

验证顺序固定为格式、版本/key version、签名、nonce、认证 scope、candidate digest、resolver/score/space，再读取主库 operation。malformed、tampered、scope-invalid、digest-invalid、resolver/score/space-invalid、revoked 或 unknown-version token 返回 `candidate_token_invalid`（HTTP 400），并在业务事务开启前保证零业务写入。只有签名有效、scope 正确且首次提交已晚于 `expires_at` 才返回 `candidate_token_expired`（HTTP 410）；默认 TTL 为 600 秒且不得超过服务端上限。轮换不延长旧 token，emergency revocation 立即拒绝。已完成 operation 的合法 replay 返回已落档结果，不因当前时间超过 token TTL 而改变结果。

### 3.1.2 Entity/Todo operation schema 与状态机

`EntityCorrection` 是唯一共享 operation/audit 事实源，最小字段集合为：`scope_type`、`source_todo_id`/`entity_id`、`selected_todo_id`/`selected_entity_id`、`candidate_*_ids`、`candidate_digest`、`operation_key`、`token_hash`、`token_key_version`、`resolver_version`、`score_version`、`embedding_space`、`token_issued_at`、`token_expires_at`、`operation_status`、`action`、`result_summary`、`completed_at`。Entity scope 为 `user_id + event_id + entity_id`，Todo scope 为 `user_id + event_id + source_todo_id`；scope 内 `operation_key` 唯一，禁止保存 raw token/secret/完整输入文本。

| 当前状态 | 触发 | 下一状态 | 规则 |
|---|---|---|---|
| `issued` | 首次合法提交 | `pending` | 只建立 operation 事实 |
| `pending` | confirm | `confirmed` | 与业务更新、audit 同一事务 |
| `pending` | reject/ignore | `rejected` | 只写 correction/audit/cooldown |
| `pending` | 未提交且 TTL 到期 | `expired` | 不写 Entity/Todo 业务事实 |
| 任意终态 | 相同 operation replay | 原终态 | 返回原结果，零重复写 |
| 任意状态 | invalid token | 不变 | 请求失败，零业务写 |

并发 confirm/reject 使用唯一 key 的 row lock 或 compare-and-set；首个成功者决定终态，冲突者读取并返回首个结果。API 错误码、HTTP 映射、retryable 和客户端动作以 PRD §4.2.5 为唯一契约。


- `canonical_zh` 是抽取实体的独立可选字段，不等同于 alias，不因抽取成功、embedding 命中或 LLM 输出自动写入 `Entity.aliases`。
- 黄金集中的正例必须填写 `canonical_zh`，并断言其与样本预期一致；负例或无法可靠确定时允许 `null`。
- 只有用户在候选确认流程中明确确认、且后端通过 token 校验的 `canonical_zh`，才可作为可靠 alias 候选写回；写回前后均保留原文 `name`，不得覆盖原文。



```python
@dataclass
class ResolutionCandidate:
    entity: Entity
    score: float
    method: str
    matched_fields: dict[str, Any]
    explanation: str
    language_pair: tuple[str, str] | None = None
    score_version: str = "w5-v1"
```

对外 API 使用脱敏 DTO，至少返回：

```text
candidate_token
candidate_entity_id
name
canonical_name
aliases
company/title（必要的展示字段）
score
method
matched_fields
explanation
language_pair
rank
confirm_only=true
candidate_set_id
```

候选 DTO 不返回完整解密后的 properties，避免通用实体接口承担过多数据暴露责任。

---

## 4. 抽取契约设计

### 4.1 可选字段扩展

在现有 `ExtractedPerson` 和对应契约中增加可选字段：

```python
language: str | None = None
canonical_zh: str | None = None
aliases: list[str] = field(default_factory=list)
```

约束：

- `name` 始终保存原文写法。
- `canonical_zh` 仅在模型能从原文或上下文可靠提供时输出；不能推断则为 `None`。
- `aliases` 只收录模型明确识别的等价写法，不把任意翻译或猜测写成事实。
- 新字段全部 optional，旧 JSON、旧 mock、旧中文黄金集均可继续通过。
- 字段进入契约版本计算，契约版本变化按 W1 流程更新。

### 4.2 语言判别

语言判别分两层：

1. **显式 hint 优先**：事件 `language` 或抽取结果 `language` 有值时直接使用。
2. **轻量 Unicode 判别**：
   - 平假名/片假名占比达到阈值 → `ja`。
   - 拉丁字母占比达到阈值 → `en`。
   - 仅汉字且无日文假名 → `zh_or_ja_unknown`，不依据单一汉字强行判定。
   - 混合文本 → `mixed`，姓名级别继续使用字典/embedding，不依赖全句语言标签。

语言标签只用于候选过滤与解释，不作为实体身份的唯一证据。

### 4.3 Prompt 兼容

实体抽取 prompt 增加以下输出要求：

- 原文姓名必须保留。
- 可识别时输出 `canonical_zh`。
- 只输出有证据的 aliases。
- 未知字段使用 `null` 或空数组，不生成额外字段。

解析端使用运行时校验：未知字段不影响旧字段；错误类型按安全默认值处理并进入已有 degraded 路径，不阻断整个事件的基础保存。

---

## 5. `_step_cross_language` 设计

### 5.1 触发条件

仅在以下条件同时满足时触发：

1. 新实体与候选实体属于同一 `entity_type`。
2. 新旧名称或别名通过语言判别被识别为不同语言，或字典 family 明确标记为跨语言。
3. 两个实体均属于当前 `user_id`，状态为 `provisional` 或 `confirmed`。
4. 候选未命中拒绝冷却。

同语言候选继续走 W4 原有路径，避免跨语言逻辑改变中文既有行为。

### 5.2 匹配顺序

```text
A. cross-language dictionary family
B. accepted alias family
C. embedding semantic score
D. optional LLM fallback
E. no match
```

每个候选保留最高有效证据，但所有 W5 结果最终都转换为 `CONFIRM`。

### 5.3 字典与 alias 规则

三语字典使用 family 结构，逻辑上等价于：

```json
{
  "person": {
    "synthetic_person_001": {
      "zh": ["林岚"],
      "en": ["Lan Lin"],
      "ja": ["ラン・リン"]
    }
  },
  "company": {
    "synthetic_company_001": {
      "zh": ["示例科技"],
      "en": ["Example Tech"],
      "ja": ["サンプルテック"]
    }
  }
}
```

实现可继续兼容 W4 的 canonical → aliases 结构，但读取时必须把正向和反向 family 规范化为同一内存表示。

字典命中：

- 基础分：`0.97`。
- `method=cross_language_dictionary`。
- `confirm_only=true`。
- 只提供候选，不修改实体，不自动合并。

用户确认后：

- 保留目标实体 canonical name 与抽取实体原文 `name`。
- 仅将用户明确确认的原文名、可靠 aliases，以及经人工确认的 `canonical_zh` 作为 alias 候选双向追加到 `Entity.aliases`；抽取阶段的 `canonical_zh` 单独保存，不自动收编。
- 用户级自学习写回必须带 `user_id` 作用域；全局种子只读。
- alias/实体写回与纠偏审计在同一事务内完成；写回失败则整体失败并可安全重试。

### 5.4 Embedding 语义匹配

#### 输入 profile

实体 embedding 文本采用稳定、可审计的字段顺序：

```text
entity_type=<type> |
name=<original name> |
canonical_zh=<optional> |
aliases=<sorted aliases> |
company=<company> |
title=<title> |
city=<city> |
industry=<industry>
```

规则：

- 不包含手机号、邮箱、身份证等 PII。
- aliases 排序后生成，避免 JSON 顺序造成 cache miss。
- 空字段不写入。
- 新实体与候选实体必须由同一 provider/model 生成。

#### 召回与排序

1. 先按 user、entity_type、active 状态过滤。
2. 先用 exact/alias/dictionary/公司等轻量字段缩小候选集。
3. 候选集上限默认 100；超过上限时保留字典命中、公司/城市相同、姓名脚本相容的候选。
4. 使用 `embed_batch([new_profile, *candidate_profiles])`。
5. 使用归一化 cosine similarity 排序。
6. 语义分数不直接转为 MERGE，只能进入 confirm 区间。

#### 分数分段

| 分数/条件 | 行为 |
|---|---|
| `>= 0.86` 且为跨语言 | 返回 `CONFIRM`，`method=cross_language_embedding` |
| `0.78–0.86` | 返回 `CONFIRM` 候选，但标记 `ambiguous=true`；若 LLM 可用进入 fallback 复核 |
| `< 0.78` | 不推荐为跨语言候选 |
| 无法生成向量/维度不一致 | 跳过 embedding，进入 LLM fallback 或无候选 |

阈值是初始值，必须由多语言黄金集校准；实现前不得将其视为最终线上常量。所有阈值进入配置，不能散落在业务代码中。

### 5.5 LLM fallback

LLM 只作为 embedding 失败或灰区复核手段，不是默认主路径：

- 触发条件：provider 不可用、向量空间不一致、候选最高分在灰区、或黄金集验证要求复核。
- 每个事件最多一次批量调用，最多携带前 5 个候选。
- prompt 只传脱敏姓名、公司、职位、城市、行业及候选 ID，不传手机号/邮箱/原始长文本。
- 返回结构必须包含候选 ID、`is_same_entity`、`confidence`、`reason`；无法解析按否定处理。
- LLM 最高分不得绕过 W5 confirm-only；即使返回 1.0 也只能展示候选。
- 离线 `MockLLMClient` 返回无跨语言推断时，系统应保持无候选/人工创建路径，不伪造跨语言确认。

### 5.6 W5 与既有解析顺序

推荐顺序：

```python
steps = [
    ("exact_match", self._step_exact),
    ("synonym_match", self._step_synonym),
    ("alias_match", self._step_alias),
    ("cross_language_match", self._step_cross_language),
    ("difflib_match", self._step_difflib_fuzzy),
    ("fuzzy_match", self._step_fuzzy),
    ("context_match", self._step_context),
]
```

`cross_language_match` 加入 `confirm_only_steps`，并且在代码结构上单独限制 `ResolutionAction.CONFIRM`，不依赖分数低于自动合并阈值这一偶然条件。

---

## 6. 拒绝冷却

### 6.1 存储与事实来源

不新增表，不接受客户端写入 `Entity.properties`。拒绝必须通过 W3 `EntityCorrection` 写入 `correction_type=entity`、`action=ignore`、候选实体 ID 与人工原因；冷却读取该审计记录计算，不另建 W5 冷却事实。

- `pair_key` 使用排序后的 UUID，避免方向重复；读取时验证两端实体属于同一 user。
- 最近一条有效 `ignore` 审计的 `created_at + cooldown_days` 未过期时抑制推荐；无有效审计或已过期则不抑制。
- 冷却默认 30 天，配置项可覆盖；过期记录可惰性忽略，但不得删除 W3 审计事实。
- 确认与拒绝均以主数据库审计为事实源，向量索引、缓存和客户端状态不得改变冷却结论。

### 6.2 行为

- 冷却期内不展示该实体对的跨语言推荐。
- 冷却只抑制相同 pair，不抑制该实体与其他候选的匹配。
- 拒绝请求必须经过候选 token 校验并记录 `EntityCorrection(action=ignore)`；重复拒绝幂等，不追加重复审计。
- 确认成功后可按业务规则使同 pair 的冷却失效，但必须通过新的确认审计事实决定，不能由客户端清除。


---

## 7. W3 纠偏与 API 设计

### 7.1 候选 API

新增语义明确的后端接口：

```text
GET /events/{event_id}/entities/{extracted_entity_id}/candidates
GET /events/{event_id}/entities/{extracted_entity_id}/todos/candidates
```

候选接口响应必须返回服务端签名的 `candidate_token`（opaque），而不是可由客户端拼装的可信 `candidate_set_id`；`candidate_set_id` 仅作展示/关联标识，不能替代 token。

查询参数：

```text
limit: 1..20，默认 10
include_ambiguous: bool，默认 true
```

接口必须：

- 校验 event、extracted entity、current user 三者一致。
- 复用 `EntityResolutionEngine` 的候选生成和评分，不重复实现 substring 搜索。
- 返回 `candidate_set_id`、候选 rank、score、method、explanation、confirm_only。
- 对候选展示字段做最小化输出。
- 候选查询不写业务数据，不写 alias，不产生 correction audit。

现有 `GET /entities?search=` 保留用于通用实体列表和兼容旧客户端，不再作为 W5 语义候选的首选路径。

### 7.2 纠偏提交

`CorrectedEntityItem` 增加可选字段，保持旧客户端兼容：

```python
candidate_token: str | None = None
candidate_set_id: str | None = None
candidate_entity_ids: list[str] | None = None  # 仅兼容展示/旧请求，不作为可信来源
selected_entity_id: str | None = None
resolution_action: Literal["confirm", "reject"] | None = None
```

客户端不得写入或更新 `Entity.properties`，不得提交 score、resolver、embedding space、cooldown 或 alias 作为事实字段；确认/拒绝的可信语义仅由 token 和后端重新读取的主数据库状态决定。

提交时后端：

1. 校验签名 token、TTL、nonce/幂等状态及 user/event/extracted entity/digest/resolver/score/space。
2. 从主数据库重新读取候选并校验候选仍属于当前 user；客户端提交的 candidate IDs 仅用于兼容校验，不能扩大服务端候选集合。
3. 若为跨语言候选，最终决策层强制 `CONFIRM` 或人工 `reject`，拒绝任何来自客户端的自动 merge 标志。
4. 成功确认后调用完整的 `merge_entities()`，确保 Todo、Association、embedding 引用迁移一致；确认与 alias/canonical_zh 写回同一事务。
5. 同一事务写入 `EntityCorrection`：`correction_type=entity`、`action=select_existing` 或 `ignore`、候选实体 ID、`candidate_digest` 与非 PII resolver metadata。
6. 重放已完成 token 返回原审计结果，不重复 merge、alias、cooldown 或 audit；合法 replay 优先于当前 TTL 判断。首次提交已过 `expires_at` 的有效 token 返回 `candidate_token_expired`（HTTP 410）；其他格式、签名、绑定或版本问题返回 `candidate_token_invalid`（HTTP 400），均零业务写入。

### 7.3 事务边界

```text
begin transaction
  ├─ 校验 user/event/entity/candidate
  ├─ select_existing: merge_entities()
  ├─ aliases/canonical_zh 写回
  ├─ confirm: 取消或替换同 pair rejection
  ├─ reject: 写入 cooldown
  └─ record_correction()
commit
```

任一业务写入失败，候选确认和审计记录一起回滚。

---

## 8. 跨语言 Todo 关联（L5）

### 8.1 新增内部模型

```python
@dataclass
class TodoResolutionCandidate:
    todo: Todo
    score: float
    method: str
    matched_fields: dict[str, Any]
    explanation: str
    confirm_only: bool = True
```

### 8.2 匹配流程

```text
新生成 Todo
  ├─ 已有 related_entity_id → 保留
  ├─ 事件内实体 alias/name 显式命中 → 候选
  ├─ due_date / 时间窗口归一
  ├─ todo_type 与责任动作归一
  ├─ 同一 user 的 active Todo 候选过滤
  ├─ embedding 比较标题+描述
  └─ 返回 confirm-only 候选
```

- 不改 Todo 表结构。候选信息只在处理上下文和确认 API 中传递；确认后复用已有 Todo 更新路径。
- `TodoResolutionCandidate` 与实体候选使用同一签名 opaque token 协议，token 绑定 `user_id/event_id/source_todo_id/candidate_digest/resolver_version/score_version/embedding_space/TTL`。
- Todo confirm/reject 均必须后端 token 校验；确认写入既有 Todo 关联路径并记录 `correction_type=todo`，拒绝记录 `action=ignore` 审计并以该审计计算冷却。
- 过期/篡改/重放语义与实体候选一致：非法 token 零写入；已处理 token 返回同一结果且不重复审计；不允许客户端提交 `related_entity_id`、cooldown 或 alias 作为可信事实。
- 中/英/日 Todo 关联在最终决策层全部 `CONFIRM-only`，不得触发实体 merge 或静默关联。

时间窗口初始规则：

- 明确日期：同一 UTC 日期视为相同日期。
- 相对日期：转换为事件时间基准后的日期区间。
- 仅有“下周/next week”等粒度：允许 ±7 天候选窗口，但必须展示为模糊匹配。
- 无时间信息时不得因文本相似单独自动关联。

Todo 语义匹配初始阈值：

- `>= 0.88`：候选确认区。
- `0.78–0.88`：模糊候选，需额外人工确认。
- `< 0.78`：不推荐。

这些阈值与实体阈值独立校准。

### 8.3 Todo 纠偏

- 中/英/日 Todo 关联全部 confirm-only。
- 用户确认走现有 Todo 编辑/关联路径，并记录 `correction_type=todo`。
- 用户拒绝不修改原 Todo；通过 `correction_type=todo`、`action=ignore` 审计事实计算拒绝 pair 的 cooldown，避免同一事件重复推荐。
- 不把 Todo 的跨语言文本写入实体 alias。
- Todo 候选不能改变实体 active 数量，也不能触发实体 merge。

---

## 9. 数据隔离、安全与隐私

### 9.1 用户隔离

所有入口均必须带 user scope：

- EntityResolutionEngine 的 candidate query。
- embedding profile 与语义搜索。
- 字典读取、学习与写回。
- rejection cooldown。
- Candidate API 与 correction API。
- Todo candidate query。

禁止通过全局内存索引跨 user 复用候选。现有 `_index_loaded` 单布尔缓存在 W5 实现中必须改为按 user 或按请求生命周期隔离，不能将一个用户的 Entity ORM 对象提供给另一个用户。

### 9.2 PII

- embedding profile 不包含 phone/email/身份证/微信号。
- LLM fallback 不传原始长文本，尽量传结构化、脱敏字段。
- EntityCorrection 延续 W3 的 `redact_pii_from_text`。
- 日志只记录事件 ID、方法、分数区间、候选数量和结果状态，不记录姓名原文、候选 ID 列表或原始 prompt。
- 三语字典种子与黄金集仅使用合成数据。

### 9.3 防越权

- 客户端提交的 `selected_entity_id`、candidate set、event ID 均由后端重新查询验证。
- 禁止客户端直接指定 `MERGE`。
- entity/todo ID 必须属于当前用户。
- 候选 API 不暴露其他用户的 properties、aliases 或向量 metadata。

---

## 10. SQLite/PostgreSQL 兼容

### 10.1 共同约束

- UUID 在 SQLite 路径使用字符串绑定，在 PostgreSQL 路径使用 UUID 绑定，沿用 W3 现有转换模式。
- 不使用 PostgreSQL 专属 JSON 查询作为 W5 正确性前提。
- candidate set、cooldown、alias family 的核心判断在 Python 层完成，数据库只负责 user-scoped 查询。
- 时间统一转换为 UTC aware datetime；SQLite naive timestamp 读取时显式归一。

### 10.2 向量索引与双数据库门禁

- 主数据库（SQLite 与 PostgreSQL）是实体、事件、Todo、纠偏审计和确认/拒绝结果的唯一事实源；W5 所有正确性断言必须分别在两种数据库上通过。
- 独立向量索引仅为派生数据，可删除、重建或不可用；W5 初版不得使用未标 metadata 的持久向量。
- 双数据库测试必须覆盖候选生成、token 校验、确认、拒绝、幂等重放、冷却读取、事务回滚与主库/向量索引不一致。
- 向量索引不可用、metadata 缺失或 space 不匹配时，主数据库流程仍可返回字典/alias confirm-only 候选或安全无候选；不得静默跨 provider/model/dimension/space fallback。
- PostgreSQL 生产环境若启用 API embedding，必须单独确认向量索引和模型维度一致后才开启持久化召回。

---

## 11. 配置项

建议新增配置，默认值全部可配置：

```text
cross_language_enabled=false
cross_language_todo_enabled=false
cross_language_embedding_enabled=false
cross_language_embedding_min_score=0.78
cross_language_embedding_confirm_score=0.86
cross_language_embedding_candidate_limit=100
cross_language_embedding_timeout_ms=500
cross_language_llm_fallback_enabled=false
cross_language_llm_fallback_max_candidates=5
cross_language_candidate_token_ttl_seconds=600
cross_language_rejection_cooldown_days=30
cross_language_todo_confirm_score=0.88
cross_language_todo_ambiguous_score=0.78
cross_language_rollout_percent=0
cross_language_embedding_provider=local
cross_language_embedding_model=all-MiniLM-L6-v2
cross_language_embedding_dimension=384
cross_language_embedding_space=local/all-MiniLM-L6-v2/384
cross_language_embedding_profile_version=w5-v1

```

实现时必须对阈值、TTL、灰度和空间配置做范围/一致性校验：

- score ∈ `[0, 1]`；confirm score ≥ min score。
- candidate limit 为正整数且有上限；timeout、TTL 为正整数，TTL 不得超过服务端上限。
- cooldown 不得为负数；rollout percent ∈ `[0, 100]`。
- `embedding_space` 必须由 provider/model/dimension/profile_version 规范化生成，不允许客户端提供。
- 默认全部关闭，先以 0% 灰度进入准入测试；灰度只允许按 user 白名单/百分比逐步开启，禁止在失败时自动切换 provider 或空间。
- 回滚顺序：先将 rollout 设为 0，再关闭 `cross_language_todo_enabled`、`cross_language_embedding_enabled`、`cross_language_enabled`；保留审计，不删除已确认 alias 或主数据库事实。

离线 CI 配置：

```text
LLM_PROVIDER=mock
EMBEDDING_PROVIDER=local
```

在 embedding provider 或本地模型不可用时，测试应断言安全降级，而不是伪造成功匹配。

---

## 12. 性能与可观测性

### 12.1 性能预算

| 阶段 | 目标 |
|---|---:|
| 语言判别 + 字典 family 查找 | < 5ms |
| 非 embedding 轻量候选生成 | < 50ms |
| 受控候选集 embedding batch | p95 < 500ms |
| LLM fallback | 不阻塞主业务提交；单事件最多一次，超时即降级 |
| 候选 API 总耗时 | p95 < 800ms（不含冷启动模型加载） |

首次加载本地 embedding 模型不计入稳定态 p95，但必须单独记录冷启动耗时。解析 pipeline 全链（含 W5 `_step_cross_language`）稳态 p95 < 1500ms（中文 < 1200ms，跨语言 < 1500ms）；冷启动与 LLM fallback 调用不计入此预算。

### 12.2 结构化指标

至少记录计数与耗时：

```text
w5_cross_language_candidate_token_issued
w5_cross_language_candidate_token_invalid{reason="malformed|tampered|binding|digest|space|revoked|unknown_version"}
w5_cross_language_candidate_token_expired
w5_cross_language_confirm_idempotent
w5_cross_language_reject_idempotent
w5_cross_language_todo_candidate_token_issued
w5_cross_language_todo_confirmations
w5_cross_language_todo_rejections
w5_cross_language_todo_cooldown_suppressed
w5_cross_language_audit_write_failures
w5_cross_language_entity_resolution_cross_scope_blocked
w5_cross_language_vector_metadata_rejected
w5_cross_language_vector_fallback_blocked
w5_cross_language_primary_db_truth_conflicts
w5_cross_language_rollout_users
w5_cross_language_safe_degrades
w5_cross_language_embedding_latency_ms
w5_cross_language_candidate_count
```

告警至少包括：token invalid/replay 突增、跨 scope 阻断、vector metadata rejected、主库/派生索引冲突、审计写失败、safe degrade 持续超阈值、确认后 active entity 数异常变化、任一路径出现 `MERGE`。

日志禁止输出原始姓名、原始 Todo 文本和完整候选 ID 列表；token 只记录不可逆 digest/原因，不记录签名 payload。

---

## 13. 验收阈值与回退策略

### 13.1 多语言黄金集门槛

初始黄金集仅使用合成数据：

- 英文实体样本 ≥ 5 条。
- 日文实体样本 ≥ 5 条。
- 中英、中日、英日配对样本各覆盖正例与拒绝例。
- 跨语言实体候选 `Recall@5 ≥ 0.80`。
- 正例 `MRR@5 ≥ 0.70`。
- 拒绝集 false-positive rate ≤ 10%。
- 中文既有黄金集通过率不得低于 W4 基线。
- 跨语言 Todo 正例 `Recall@5 ≥ 0.75`，且不得产生自动合并。

### 13.2 降级条件

满足任一条件时，embedding 不作为最终判断：

- provider 不可用或超时。
- 向量维度/model/provider 不一致。
- 黄金集未达到门槛。
- score 落入灰区且 LLM fallback 可用。
- candidate profile 含非法/空实体身份字段。

降级顺序：

```text
embedding
  -> LLM fallback（最多一次批量调用）
  -> 字典/alias/字段证据的 confirm-only 候选
  -> 无候选，创建新实体或等待人工查找
```

如果 LLM fallback 也不可用，不能把 embedding 灰区候选升级为确认建议。

---

### 13.3 准入测试计划（实现前）

不得进入实现，直至以下测试资产和门禁被定义、可执行并由独立测试角色维护：

1. **契约/单元**：`canonical_zh` 独立可选字段；黄金集正例必填；所有跨语言最终 action 强制 `CONFIRM`；阈值、TTL、space、cache key 校验。
2. **安全**：opaque token 签名、篡改、过期、跨 user/event/entity、candidate digest 变化、resolver/score/space 不匹配；客户端写 `Entity.properties`、伪造 candidate IDs、自动 merge 均拒绝且零写入。
3. **幂等/审计**：confirm/reject 首次成功、同 token 重放、并发重放；结果只产生一条 `EntityCorrection`/Todo audit，重复请求返回同一结果；冷却只由 `EntityCorrection(action=ignore)` 推导。
4. **双数据库**：SQLite 与 PostgreSQL 分别覆盖上述路径、事务回滚、时间/UUID 兼容、主库事实与派生向量不一致。
5. **向量/降级**：metadata 缺失、provider/model/dimension/space/profile 不一致、索引不可用、显式 fallback 不满足时均安全降级；反幽灵断言禁止隐式 API/local 跨空间 fallback。
6. **隔离/反幽灵**：双 user 交错请求、engine/cache/index 生命周期隔离；断言无全局可变候选污染、无 W5 专用表、无客户端 properties 写入口、无跨语言 `MERGE` 调用路径。
7. **Todo E2E**：`cross_language_todo_enabled` 默认关闭、灰度开启后 candidate token → confirm/reject/audit/cooldown；中英日路径均 confirm-only，实体 active 数不变。
8. **真实用户 E2E**：英文纪要→中文补录→候选展示→人工确认/拒绝→重放/过期→aliases 与 audit 校验；失败 provider/索引场景验证安全降级，SQLite/PostgreSQL 各跑一次并归档证据。
9. **发布前模拟真实用户测试**：使用合成账号和合成三语数据，执行灰度、回滚、重复点击、网络重试、双端并发及监控告警验证；不得使用真实 PII。

准入退出条件：全项通过、无 skip/xfail 掩盖失败、反幽灵扫描通过、指标告警演练通过；否则保持“不得进入实现”。

## 14. 实施拆分与回滚

> 以下仅为准入后的实施计划；在准入测试计划完成前不得编写生产代码。

### M-W5.1：抽取契约与三语字典

- 扩展 optional 字段与 prompt。
- 加入语言判别。
- 增加合成三语种子。
- 更新契约 hash、mock 与多语言黄金集。

回滚：关闭 `cross_language_enabled`；旧字段和旧解析路径继续工作。

### M-W5.2：统一候选解析与 embedding

- 抽出共享候选协议。
- 实现 `_step_cross_language`。
- 增加 embedding space gate、cache namespace、候选 API。
- 保持所有跨语言结果 confirm-only。

回滚：关闭 `cross_language_embedding_enabled`，保留字典/alias 候选；不删除既有 aliases。

### M-W5.3：W3 审计与冷却

- 扩展纠偏请求可选 candidate metadata。
- 确保 candidate set 校验和同事务审计。
- 加入 rejection cooldown。
- 确认路径复用完整 `merge_entities()`。

回滚：停止展示跨语言候选；不清理已写入的 audit/cooldown 数据。

### M-W5.4：跨语言 Todo

- 实现 Todo candidate resolver。
- 加入时间语义归一和 embedding 候选。
- 接入 Todo confirm/reject 审计。

回滚：关闭 `cross_language_todo_enabled`，不影响普通 Todo 生成和用户手工编辑。

---

## 15. 技术债与明确不纳入本轮

以下问题已确认存在，但不在 W5 首轮直接扩大范围：

1. 现有完整 `EntityResponse` 与候选 DTO 的长期拆分，可在 W5 API 稳定后继续收敛。
2. 全量历史 embedding 重建与模型迁移，作为独立运维任务。
3. Entity properties 正式 Pydantic schema 与实际存储字段的全面统一，另立契约修复任务。
4. 现有 Todo first-substring-wins 的同语言全面重构；W5 仅增加跨语言候选路径，避免无关行为回归。
5. 前端 UI 结构重做；本轮只增加候选依据、确认/拒绝状态所需的最小字段。

---

## 16. 技术设计验收清单

- [ ] 服务端签名 opaque candidate token 已定义：绑定 user/event/extracted entity/digest/resolver/score/space/TTL，过期/篡改/重放和幂等语义已定义。
- [ ] `canonical_zh` 独立可选、黄金集正例必填，只有人工确认后才能作为 alias 已定义。
- [ ] 拒绝冷却仅由 W3 `EntityCorrection(action=ignore)` 审计推导，客户端不可写 `Entity.properties`。
- [ ] 跨语言实体与 Todo 所有路径在最终决策层硬性 `CONFIRM-only`。
- [ ] EntityResolutionEngine 按请求或 user 隔离；cache key 含 provider/model/dimension/space/profile/version。
- [ ] 主数据库事实源、向量索引派生数据、未标 metadata 持久向量禁用和安全降级已定义。
- [ ] API/local 跨空间静默 fallback 已禁止，失败行为与指标告警已定义。
- [ ] `cross_language_todo_enabled`、Todo candidate token/confirm/reject/audit/cooldown 语义和 E2E 已定义。
- [ ] 配置默认值为安全关闭，灰度/回滚、指标告警、SQLite/PostgreSQL 双数据库和反幽灵测试要求已定义。
- [ ] 双数据库 migration、真实用户 E2E、唯一 Anti-ghost runner、manifest schema/脱敏校验与严格非零退出门禁已定义。


---

## 17. DevSquad 复核结论与当前状态

- 本轮已完成架构、安全、测试、产品与运维问题的修订收敛；四类角色的最终准入签署仍待完成，本版本仅完成设计收敛和准入测试计划。
- W5 不新增专用表，不写生产代码；候选 token 的消费/幂等依赖现有主数据库纠偏审计事实。
- 设计状态为“DevSquad 复核修订版，待最终准入签署；未通过 Test Plan approval 不得进入实现”。
- 原待复核问题已转为测试计划：operation/audit 事实模型、HMAC secret 生命周期、multilingual embedding 门槛、候选 API 接入时序、审计驱动冷却、Todo token 语义、单一 embedding space 与显式降级。

---

*本文档在准入测试计划完成并通过双数据库、反幽灵与真实用户 E2E 门禁后，方可进入实现；当前不得编写生产代码。*
