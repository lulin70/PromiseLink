# PromiseLink 解析语义契约

> **契约版本**: `f3b3ba49a983`（由代码五源内容哈希自动计算，勿手改）
> **生成**: `python scripts/generate_semantic_contract.py --write`
> **父文档**: [PRD_解析语义契约_v1.md](PRD_解析语义契约_v1.md)

<!-- generated:do-not-edit:v=f3b3ba49a983 -->
## 1. 概念（Class）

### Event（互动事件）
一次录入的原始互动记录（会议/通话/名片/手动/跟进/语音查询等）。

### Entity（人脉）
从事件中抽取的真实人物；附 `properties` JSONB（结构见 §2.1）。

### Todo（待办，含 Promise 逻辑视图）
从事件派生的行动项；Promise（承诺）复用 todos 表，以 todo_type 区分（promise/followup 等），双向分析见 Step05。

### ExtractionResult（解析输出契约）
- `persons`: list[promiselink.services.entity_extractor.ExtractedPerson]
- `keywords`: list[str]
- `summary`: <class 'str'>
- `events`: list[dict]
- `is_ai_inference`: <class 'bool'>
- `confidence_level`: <class 'str'>
- `requires_confirmation`: <class 'bool'>
- `persisted_entities`: list[promiselink.models.entity.Entity]
## 2. 属性

### 2.1 Entity.properties 结构（EntityProperties schema）

**BasicInfo**

- `company`: any
- `title`: any
- `phone`: any
- `email`: any
- `wechat`: any
- `city`: any

**ConcernItem**

- `category`: string
- `detail`: any

**CapabilityItem**

- `category`: string
- `detail`: any

**EntityProperties**


### 2.2 ORM 存储字段

**Event**（15 列）

| 列 | 类型 | 可空 |
|---|---|---|
| `id` | VARCHAR(36) | 否 |
| `user_id` | VARCHAR(36) | 否 |
| `event_type` | VARCHAR(20) | 否 |
| `source` | VARCHAR(50) | 否 |
| `title` | VARCHAR(200) | 否 |
| `timestamp` | DATETIME | 否 |
| `raw_text` | TEXT | 是 |
| `metadata` | JSON | 是 |
| `status` | VARCHAR(20) | 否 |
| `pipeline` | VARCHAR(50) | 是 |
| `failed_steps` | JSON | 是 |
| `input_scope` | VARCHAR(30) | 是 |
| `input_scope_confidence` | FLOAT | 是 |
| `created_at` | DATETIME | 否 |
| `processed_at` | DATETIME | 是 |

**Entity**（12 列）

| 列 | 类型 | 可空 |
|---|---|---|
| `id` | VARCHAR(36) | 否 |
| `user_id` | VARCHAR(36) | 否 |
| `entity_type` | VARCHAR(20) | 否 |
| `name` | VARCHAR(200) | 否 |
| `canonical_name` | VARCHAR(200) | 否 |
| `aliases` | JSON | 是 |
| `properties` | JSON | 是 |
| `source_event_id` | VARCHAR(36) | 否 |
| `confidence` | FLOAT | 否 |
| `status` | VARCHAR(20) | 否 |
| `created_at` | DATETIME | 否 |
| `updated_at` | DATETIME | 否 |

**Todo**（31 列）

| 列 | 类型 | 可空 |
|---|---|---|
| `id` | VARCHAR(36) | 否 |
| `user_id` | VARCHAR(36) | 否 |
| `todo_type` | VARCHAR(20) | 否 |
| `title` | VARCHAR(200) | 否 |
| `description` | TEXT | 是 |
| `related_entity_id` | VARCHAR(36) | 是 |
| `related_association_id` | VARCHAR(36) | 是 |
| `priority` | INTEGER | 否 |
| `status` | VARCHAR(15) | 否 |
| `due_date` | DATETIME | 是 |
| `reminder_at` | DATETIME | 是 |
| `properties` | JSON | 是 |
| `source_event_id` | VARCHAR(36) | 是 |
| `action_type` | VARCHAR(30) | 是 |
| `promisor_id` | VARCHAR(36) | 是 |
| `beneficiary_id` | VARCHAR(36) | 是 |
| `confirmation_status` | VARCHAR(20) | 是 |
| `evidence_quote` | TEXT | 是 |
| `evidence_event_id` | VARCHAR(36) | 是 |
| `feedback` | VARCHAR(50) | 是 |
| `created_at` | DATETIME | 否 |
| `updated_at` | DATETIME | 否 |
| `completed_at` | DATETIME | 是 |
| `dynamic_score` | FLOAT | 是 |
| `score_calculated_at` | DATETIME | 是 |
| `priority_override` | VARCHAR(10) | 是 |
| `priority_source` | VARCHAR(10) | 否 |
| `completed_rank` | INTEGER | 是 |
| `fulfillment_status` | VARCHAR(20) | 否 |
| `fulfilled_at` | DATETIME | 是 |
| `overdue_notified_at` | DATETIME | 是 |

## 3. 关系

- `Entity` ↔ `Event`：多对多参与（事件中出现的人脉；关联发现 Step10/Step11 维护）
- `Todo` → `Event`：待办源于事件（Step04 生成）
- `Todo`(promise) ↔ 双方 Entity：承诺双向分析（Step05，我对他人/他人对我）
- `Entity` ↔ `Entity`：关联网络（AssociationDiscoveryEngine，共现/频率规则）
- `RelationshipBrief` → `Entity`：关系简报随互动持续更新（Step12）

## 4. 约束

1. 虚拟角色不提取：PM/架构师等职能词、第一人称「我」均不是人脉（prompt 硬规则）
2. 禁止对他人资源做确定性判断；推测内容必须标注（来源：原文引用）
3. 禁止建议索取资源
4. `Entity.properties` 写库前必须过 `EntityProperties` 校验（失败降级存储原文并告警）
5. concern/capability 的 category 受控词表约束（§5.1/§5.2），detail 为自由文本
6. 信息不足字段设为 null，禁止编造
7. 歧义（多候选人脉/时间）必须进入人工纠偏流程（requires_confirmation）

## 5. 枚举与受控词表

### 5.1 concern 受控词表

融资、招聘、销售、技术选型、合规、市场拓展、成本控制、供应链、数字化转型、人才保留

### 5.2 capability 受控词表

投资决策、技术架构、产品设计、项目管理、渠道资源、行业人脉、政策解读、数据分析、品牌营销、团队管理

### 5.3 InputScope 输入范围（8 类）

- `card_scan`
- `meeting`
- `call`
- `manual`
- `followup`
- `voice_query`
- `reflection`
- `unknown`

### 5.4 confidence_level 输出置信度

- `confirmed` | `inferred` | `speculated`

<!-- /generated -->

<!-- human-section:semantic-notes -->
## 6. 语义说明（人工维护）

### 6.1 关键字段的业务含义与必填性理由

| 字段 | 业务含义 | 必填性理由 |
|---|---|---|
| `persons[].name` | 人脉的唯一锚点，所有关系推导的起点 | 无名即无实体；虚拟角色/「我」必须过滤（§4.1） |
| `persons[].company/title` | 关系推进的背景信息（对方是谁、能做什么） | 可空：仅寒暄场景可能缺失 |
| `persons[].concern` | 「他正在关心什么」——利他闭环第二步 | 可空：无明确关切时不猜测 |
| `persons[].capability` | 「我能先为他做什么」的依据 | 可空：无明确能力信号时不猜测 |
| `persons[].resource/demand` | 促成合作的两侧 | 可空；resource 禁止确定性判断（§4.2） |
| `todos[].deadline` | 待办提醒的触发依据 | 可空但为空时通知策略降级（无硬截止） |
| `requires_confirmation` | 歧义标记 → 触发用户纠偏 UI | 歧义时不允许静默落库 |

### 6.2 歧义处理策略

| 歧义类型 | 策略 |
|---|---|
| 同名多人 | `requires_confirmation=True` + 候选列表（多候选人脉选择 UI，复用 §5.18 纠偏） |
| 时间歧义（"下周三"） | 由 natural_date 解析为具体日期；无法唯一解析时保留原文并标记 |
| promise 方向歧义（谁承诺谁） | Step05 双向分析输出两侧；无法判断时进入确认流程 |
| 虚拟角色 vs 真实人物 | 按 §4.1 硬规则过滤；边缘 case（"许总（PM）说"）提取真实人名 |

### 6.3 字段类型说明（Pydantic v2 anyOf 显示约定）

§2.1 中显示为 `any` 的字段实为 `str | null`（Optional），schema 的 anyOf 结构在渲染时简化；精确结构以 `EntityProperties.model_json_schema()` 运行时输出为准。

### 6.4 契约演进规则

1. 任何五源（§1-§5 的生成来源）代码变更 → 必须重跑 `--write`，契约哈希随之变化
2. 哈希变化 = 契约版本变化，需在 CHANGELOG 记录一行（哪个源、什么变更）
3. 本节（人工段）只在语义理解变化时更新；生成段永不合入手工改动（CI 拦截）
<!-- /human-section -->
