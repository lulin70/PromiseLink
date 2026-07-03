# PromiseLink 数据库设计文档

> **版本**: 3.0 (三级产品模型)
> **日期**: 2026-06-11
> **阶段**: 基础版过渡期
> **设计师**: 架构师团队
> **参考**: PRD v5.0, 技术设计 v3.0 §3.1
> **状态**: 三级产品模型(基础版/专业版/定制版)重构
> **v3.0变更**: 三级产品模型重构——Phase1→专业版、Phase2→定制版；SQLite确认为基础版+专业版长期方案，PG/Redis仅定制版；新增relay_connections表(网关中继连接)、ai_usage_logs表(AI用量计费)；resource/demand字段标注为定制版使用
> **v2.6变更**: score_audit_logs表calculation_factors扩展dependency_score/context_score审计字段
> **v2.7变更**: 新增vector_embeddings表(F-57)、vec_entities虚拟表(F-57)、语义搜索数据存储
> **v2.8变更**: Event模型event_type约束新增'email'和'wechat_forward'，Todo模型properties JSONB新增resource_overuse类型
> **v2.9变更**: todos表扩展fulfillment_status/fulfilled_at/overdue_notified_at字段(F-68)，新增reminder_preferences表(F-69)，新增reminder_logs表(F-69)

---

## 1. 设计原则

### 1.1 数据库策略（三级产品模型）

| 产品层级 | 数据库 | 说明 |
|---------|--------|------|
| **基础版**（本地免费） | SQLite | 零依赖，快速启动，单用户完全够用 |
| **专业版**（网关中继） | SQLite | 长期方案，通过relay gateway提供云端AI能力 |
| **定制版**（团队） | PostgreSQL 15 + Redis | 销售团队多用户场景，高性能、JSONB、全文索引 |

- **数据规模**: 单用户1万条记录以内（SQLite处理百万行无压力）
- **范式**: 实用主义优先，适度反范式化（company/title提取到实体表）

> **决策变更（2026-06-11）**：基础版和专业版长期使用SQLite，不做PG/Redis迁移。PG/Redis仅在定制版中按需引入。此决策消除了基础版和专业版的数据库迁移风险，简化部署和运维。

### 1.2 数据原则
- **事件驱动**: Event是一切数据的源头
- **实体归一**: 通过5步算法避免重复实体
- **软删除**: 关键数据使用deleted_at而非物理删除
- **审计日志**: 全写操作记录created_at/updated_at

---

## 2. ER图

```mermaid
erDiagram
    USERS ||--o{ EVENTS : creates
    USERS ||--o{ ENTITIES : owns
    USERS ||--o{ TODOS : has
    USERS ||--o{ RELATIONSHIP_BRIEFS : tracks

    EVENTS ||--o{ ENTITIES : extracts
    EVENTS {
        uuid id PK
        varchar event_type "card_save|meeting|call|manual|email|wechat_forward"
        varchar source
        varchar title
        timestamptz timestamp
        text raw_text
        jsonb metadata
        varchar input_scope "输入分类（v2.0新增）"
        float input_scope_confidence "分类置信度（v2.0新增）"
        uuid user_id FK
        timestamptz created_at
    }

    ENTITIES ||--o{ ASSOCIATIONS : "source/target"
    ENTITIES {
        uuid id PK
        varchar entity_type "person|organization|technology|project|attribute"
        varchar name
        text_array aliases
        jsonb properties "concern|promise|contribution|resource|demand|profile|resource_sensitivity|relationship_stage"
        varchar company "高频查询列"
        varchar title "高频查询列"
        uuid user_id FK
        timestamptz created_at
        timestamptz updated_at
    }

    ASSOCIATIONS {
        uuid id PK
        uuid source_entity_id FK
        uuid target_entity_id FK
        varchar assoc_type "alumni|ex_colleague|same_city|competitor|tech_overlap|deal_link|risk_link|supply_chain"
        float confidence "0.0-1.0"
        jsonb evidence "支撑证据"
        uuid user_id FK
        timestamptz created_at
    }

    RELATIONSHIP_BRIEFS }o--|| ENTITIES : "about_person"
    RELATIONSHIP_BRIEFS }o--o{ EVENTS : "latest_interaction"
    RELATIONSHIP_BRIEFS {
        uuid id PK
        uuid user_id FK
        uuid person_id FK "→entities(id)"
        varchar current_stage "7阶段枚举"
        text stage_reason
        uuid latest_interaction_id FK "→events(id)"
        text next_node
        text next_node_condition
        text paused_reason
        boolean confirmed_by_user
        integer version "乐观锁"
        jsonb concerns
        jsonb need_insights
        jsonb contributions
        jsonb pending_promises
        jsonb feedback_records
        text cooperation_direction_candidate
        timestamptz created_at
        timestamptz updated_at
    }

    ENTITIES ||--o{ TODOS : "about"
    TODOS {
        uuid id PK
        varchar todo_type "cooperation_signal|risk|care|promise|followup|help"
        varchar status "pending|in_progress|done|dismissed|snoozed"
        varchar priority "high|medium|low"
        text description
        uuid related_entity_id FK
        uuid source_event_id FK
        varchar action_type "6种动作类型（v2.0新增）"
        uuid promisor_id FK "承诺人（v2.0新增）"
        uuid beneficiary_id FK "受益人（v2.0新增）"
        varchar confirmation_status "确认状态（v2.0新增）"
        text evidence_quote "证据原文（v2.0新增）"
        uuid evidence_event_id FK "证据来源（v2.0新增）"
        jsonb context
        timestamptz due_date
        timestamptz snooze_until
        varchar fulfillment_status "兑现状态（v2.9新增）"
        timestamptz fulfilled_at "兑现时间（v2.9新增）"
        timestamptz overdue_notified_at "逾期通知时间（v2.9新增）"
        uuid user_id FK
        timestamptz created_at
        timestamptz updated_at
    }

    USERS {
        uuid id PK
        varchar username
        varchar email
        varchar password_hash
        jsonb preferences
        timestamptz created_at
    }

    USERS ||--o{ VOICE_SESSIONS : "initiates"
    VOICE_SESSIONS ||--o{ VOICE_TURNS : "has"
    VOICE_SESSIONS }o--|| ENTITIES : "references(in slots)"
    VOICE_SESSIONS {
        uuid id PK
        uuid user_id FK
        varchar query_text "ASR识别文字(max 500)"
        float asr_confidence "ASR置信度0-1"
        boolean is_voice_input
        inet client_ip
        varchar intent "识别意图"
        float intent_confidence "意图置信度"
        jsonb slots "槽位填充结果"
        varchar target_api "目标API路径"
        jsonb api_params "API请求参数"
        text answer_text "回答文字(max 2000)"
        varchar answer_source "template|nlg|fallback"
        boolean tts_cached
        varchar user_rating "反馈评分"
        text feedback_comment
        integer processing_time_ms "端到端耗时"
        timestamptz created_at
        timestamptz updated_at
    }

    VOICE_TURNS {
        uuid id PK
        uuid session_id FK
        integer turn_number "第几轮(从1开始)"
        varchar role "user|system|clarification"
        text content "文本内容"
        varchar turn_type "question|answer|error|follow_up|suggestion"
        varchar intent "仅user turn有"
        integer tokens_used "LLM token消耗"
        timestamptz created_at
    }

    VOICE_ANALYTICS {
        uuid id PK
        date date "聚合日期"
        uuid user_id FK
        varchar intent "意图"
        integer total_queries "总查询数"
        float avg_confidence "平均意图置信度"
        float unclear_rate "不确定率"
        float avg_processing_ms "平均处理时长"
        float helpful_rate "有帮助率"
        float tts_hit_rate "TTS缓存命中率"
        float asr_error_rate "ASR错误率"
        timestamptz created_at
        timestamptz updated_at
    }

    USERS ||--o| REMINDER_PREFERENCES : "configures"
    REMINDER_PREFERENCES {
        varchar user_id PK "用户ID"
        jsonb preferred_times "偏好提醒时间"
        integer fatigue_threshold "疲劳阈值"
        time quiet_hours_start "免打扰开始"
        time quiet_hours_end "免打扰结束"
        timestamp updated_at "更新时间"
    }

    USERS ||--o{ REMINDER_LOGS : "receives"
    TODOS ||--o{ REMINDER_LOGS : "tracked_by"
    REMINDER_LOGS {
        varchar id PK
        varchar user_id FK "用户ID"
        varchar todo_id FK "关联Todo"
        varchar reminder_type "提醒类型"
        timestamp sent_at "发送时间"
        varchar action_taken "用户响应"
        integer response_latency_seconds "响应延迟(秒)"
    }

    USERS ||--o{ RELAY_CONNECTIONS : "connects"
    RELAY_CONNECTIONS {
        uuid id PK
        uuid user_id FK "用户ID"
        varchar connection_id "连接唯一标识"
        timestamptz connected_at "连接建立时间"
        timestamptz last_heartbeat "最近心跳时间"
        varchar status "连接状态"
    }

    USERS ||--o{ AI_USAGE_LOGS : "consumes"
    AI_USAGE_LOGS {
        uuid id PK
        uuid user_id FK "用户ID"
        varchar action_type "AI动作类型"
        integer tokens_used "Token消耗量"
        float cost "调用成本(元)"
        timestamptz created_at "创建时间"
    }
```

---

## 3. 表结构详细设计

### 3.1 Events表（事件表）

**用途**: 存储用户提交的所有事件（扫名片/会议/电话/手动）

| 字段名 | 类型 | 约束 | 默认值 | 说明 |
|--------|------|------|--------|------|
| id | UUID | PRIMARY KEY | gen_random_uuid() | 主键 |
| event_type | VARCHAR(20) | NOT NULL | - | card_save\|meeting\|call\|manual\|email\|wechat_forward |
| source | VARCHAR(50) | NOT NULL | - | iamhere\|recording_r1\|manual\|csv_import\|email\|wechat_forward |
| title | VARCHAR(200) | NOT NULL | - | 事件标题 |
| timestamp | TIMESTAMPTZ | NOT NULL | - | 事件发生时间 |
| raw_text | TEXT | NOT NULL | - | 原始文本内容 |
| metadata | JSONB | - | '{}' | 扩展元数据（会议类型/地点等） |
| input_scope | VARCHAR(30) | - | 'relationship_interaction' | 输入分类（F-44，v2.0新增） |
| input_scope_confidence | FLOAT | - | 1.0 | 分类置信度（F-44，v2.0新增） |
| user_id | UUID | NOT NULL, FK(users.id) | - | 用户ID |
| created_at | TIMESTAMPTZ | NOT NULL | NOW() | 创建时间 |

**索引**:
```sql
CREATE INDEX idx_events_user_timestamp ON events(user_id, timestamp DESC);
CREATE INDEX idx_events_type ON events(event_type);
CREATE INDEX idx_events_source ON events(source);
CREATE INDEX idx_events_input_scope ON events(input_scope) WHERE input_scope IS NOT NULL;  -- v2.0新增
```

**JSONB metadata结构**:
```json
{
  "meeting_type": "A|B|C|D",
  "location": "会议地点",
  "participants": ["张三", "李四"],
  "duration_minutes": 60,
  "card_image_url": "https://...",
  "language": "zh-CN|en-US"
}
```

---

### 3.2 Entities表（实体表）

**用途**: 存储归一后的实体（人/组织/技术/项目等）

| 字段名 | 类型 | 约束 | 默认值 | 说明 |
|--------|------|------|--------|------|
| id | UUID | PRIMARY KEY | gen_random_uuid() | 主键 |
| entity_type | VARCHAR(20) | NOT NULL | - | person\|organization\|technology\|project\|attribute |
| name | VARCHAR(100) | NOT NULL | - | 实体名称 |
| aliases | TEXT[] | - | '{}' | 别名数组 |
| properties | JSONB | - | '{}' | 扩展画像（concern/promise/contribution/resource/demand/profile/relationship_stage） |
| company | VARCHAR(100) | - | NULL | 公司（高频查询列） |
| title | VARCHAR(100) | - | NULL | 职位（高频查询列） |
| city | VARCHAR(50) | - | NULL | 城市（高频查询列） |
| user_id | UUID | NOT NULL, FK(users.id) | - | 用户ID |
| created_at | TIMESTAMPTZ | NOT NULL | NOW() | 创建时间 |
| updated_at | TIMESTAMPTZ | NOT NULL | NOW() | 更新时间 |

**索引**:
```sql
CREATE INDEX idx_entities_user_type ON entities(user_id, entity_type);
CREATE INDEX idx_entities_name ON entities(name);
CREATE INDEX idx_entities_company ON entities(company) WHERE company IS NOT NULL;
CREATE INDEX idx_entities_properties ON entities USING GIN(properties jsonb_path_ops);
```

**唯一约束**:
```sql
CREATE UNIQUE INDEX idx_entities_user_name_company 
  ON entities(user_id, name, COALESCE(company, ''))
  WHERE entity_type = 'person';
```

**JSONB properties结构**:
```json
{
  "resource_sensitivity": "matchable",
  "relationship_stage": "new_connection",
  "relationship": {
    "stage": "new_connection",
    "stage_reason": "首次记录互动",
    "paused_reason": null,
    "confirmed_by_user": false,
    "next_node": "了解对方核心需求",
    "next_node_condition": "完成首次深入交流"
  },
  "concern": [
    {
      "topic": "寻找AI方向技术合伙人",
      "source_event_id": "uuid-of-event",
      "confirmed": true,
      "created_at": "2026-06-03T10:00:00Z"
    }
  ],
  "promise": [
    {
      "content": "下周发一份AI算法团队介绍资料",
      "due_at": "2026-06-10T00:00:00Z",
      "source_event_id": "uuid-of-event",
      "status": "pending",
      "created_at": "2026-06-03T10:00:00Z"
    }
  ],
  "contribution": [
    {
      "content": "介绍了李四给张三认识",
      "target_entity_id": "uuid-of-target-entity",
      "date": "2026-06-01",
      "created_at": "2026-06-01T10:00:00Z"
    }
  ],
  "resource": {
    "tags": ["AI算法专家", "有5年CV经验"],
    "description": "计算机视觉领域专家，擅长目标检测与图像分割"
  },
  "demand": {
    "tags": ["寻找联合创始人", "需要前端开发"],
    "description": "创业项目需要技术合伙人，前端方向优先",
    "urgency": "high"
  },
  "profile": {
    "phone": "138xxxx",
    "email": "xxx@example.com",
    "wechat": "xxxxx",
    "linkedin": "https://...",
    "education": ["清华大学", "计算机系"],
    "industry": "人工智能",
    "skills": ["Python", "PyTorch", "NLP"],
    "callability": "可约咖啡"
  }
}
```

> **v2.5新增 concerns/capabilities 结构**（存储在现有 properties JSONB 中，无需DDL变更）:

**concerns 字段**（v2.5新增，替代原有 concern 数组，提供结构化标签）:
```json
{
  "concerns": [
    {
      "tag": "人才招聘",
      "detail": "正在寻找有5年经验的AI算法工程师，prefer CV方向",
      "source_event_id": "uuid-of-event"
    }
  ]
}
```

**capabilities 字段**（v2.5新增）:
```json
{
  "capabilities": [
    {
      "tag": "技术选型",
      "detail": "在微服务架构选型上有丰富经验，主导过3次技术栈迁移",
      "source_event_id": "uuid-of-event"
    }
  ]
}
```

> **迁移说明**: concerns/capabilities 存储在现有 properties JSONB 列中，无需 Schema 变更。原有 concern 数组保持兼容，新增 concerns/capabilities 字段为结构化版本。

> **注意**: `resource` 和 `demand` 字段为 **定制版** 使用，当前阶段保留结构但暂不主动填充。

**resource_sensitivity枚举说明**:
| 值 | 说明 | 匹配行为 |
|---|---|---|
| `matchable` | 可参与匹配 | 该实体的资源/需求可被匹配算法发现和推荐 |
| `no_match` | 不可匹配 | 该实体不参与任何匹配推荐，仅做记录留存 |

**resource字段详细结构**（定制版）:
```json
{
  "tags": ["标签1", "标签2"],
  "description": "资源的自然语言描述"
}
```
- `tags`: 资源标签数组，用于关键词匹配（keyword维度25%权重）
- `description`: 资源的自然语言描述，用于LLM语义匹配（llm维度10%权重）

**demand字段详细结构**（定制版）:
```json
{
  "tags": ["标签1", "标签2"],
  "description": "需求的自然语言描述",
  "urgency": "high|medium|low"
}
```
- `tags`: 需求标签数组，用于关键词匹配
- `description`: 需求的自然语言描述，用于LLM语义匹配
- `urgency`: 需求紧迫度，影响Todo优先级排序

---

### 3.3 Associations表（关联表）

**用途**: 存储实体间的关联关系（8种关联类型）

| 字段名 | 类型 | 约束 | 默认值 | 说明 |
|--------|------|------|--------|------|
| id | UUID | PRIMARY KEY | gen_random_uuid() | 主键 |
| source_entity_id | UUID | NOT NULL, FK(entities.id) | - | 源实体ID |
| target_entity_id | UUID | NOT NULL, FK(entities.id) | - | 目标实体ID |
| assoc_type | VARCHAR(30) | NOT NULL | - | 关联类型（8种） |
| confidence | FLOAT | NOT NULL | 0.0 | 置信度 0.0-1.0 |
| evidence | JSONB | - | '{}' | 支撑证据 |
| user_id | UUID | NOT NULL, FK(users.id) | - | 用户ID |
| created_at | TIMESTAMPTZ | NOT NULL | NOW() | 创建时间 |

**关联类型枚举**:
- `alumni` - 校友关系
- `ex_colleague` - 前同事
- `same_city` - 同城
- `competitor` - 竞对关系
- `tech_overlap` - 技术重叠
- `deal_link` - 交易关联
- `risk_link` - 风险关联（P2）
- `supply_chain` - 供应链关系

**索引**:
```sql
CREATE INDEX idx_assoc_source ON associations(source_entity_id);
CREATE INDEX idx_assoc_target ON associations(target_entity_id);
CREATE INDEX idx_assoc_type ON associations(assoc_type);
CREATE INDEX idx_assoc_confidence ON associations(confidence) WHERE confidence >= 0.7;
CREATE UNIQUE INDEX idx_assoc_unique 
  ON associations(user_id, source_entity_id, target_entity_id, assoc_type);
```

**JSONB evidence结构**:
```json
{
  "method": "同公司匹配",
  "matched_fields": ["company", "title"],
  "source_events": ["event_id_1", "event_id_2"],
  "extracted_from": "会议纪要提到：张三和李四都是阿里巴巴的前同事"
}
```

---

### 3.3b RelationshipBriefs表（关系推进卡表）

**用途**: 为重点联系人生成全貌视图卡片，整合关注点、需求洞察、承诺、反馈、关系阶段等关键信息（F-47，P0必须，v2.0新增）

| 字段名 | 类型 | 约束 | 默认值 | 说明 |
|--------|------|------|--------|------|
| id | UUID | PRIMARY KEY | gen_random_uuid() | 主键 |
| user_id | UUID | NOT NULL | - | 用户ID |
| person_id | UUID | NOT NULL, FK(entities.id) | - | 关联人物实体ID |
| current_stage | VARCHAR(30) | NOT NULL | 'new_connection' | 当前关系阶段（7阶段枚举） |
| stage_reason | TEXT | - | NULL | 阶段原因说明 |
| latest_interaction_id | UUID | FK(events.id) | NULL | 最近互动事件ID |
| next_node | TEXT | - | NULL | 下一推进节点 |
| next_node_condition | TEXT | - | NULL | 节点触发条件 |
| paused_reason | TEXT | - | NULL | 暂停原因 |
| confirmed_by_user | BOOLEAN | - | FALSE | 用户是否确认阶段变更 |
| version | INTEGER | NOT NULL | 1 | 乐观锁版本号 |
| concerns | JSONB | - | '[]' | 关注点列表 |
| need_insights | JSONB | - | '[]' | 需求洞察列表 |
| contributions | JSONB | - | '[]' | 贡献记录列表 |
| pending_promises | JSONB | - | '[]' | 待兑现承诺列表 |
| feedback_records | JSONB | - | '[]' | 反馈记录列表 |
| cooperation_direction_candidate | TEXT | - | NULL | 合作方向候选 |
| created_at | TIMESTAMPTZ | - | NOW() | 创建时间 |
| updated_at | TIMESTAMPTZ | - | NOW() | 更新时间 |

**索引**:
```sql
CREATE INDEX idx_briefs_user ON relationship_briefs(user_id);
CREATE INDEX idx_briefs_person ON relationship_briefs(person_id);
CREATE UNIQUE INDEX idx_briefs_user_person ON relationship_briefs(user_id, person_id);
```

**current_stage 7阶段枚举（F-48）**:

| 阶段值 | 中文名 | 说明 | PoC范围 |
|--------|--------|------|---------|
| `new_connection` | 新连接 | 首次建立联系 | ✅ 启用 |
| `understanding_needs` | 了解需求 | 深入了解对方需求 | ✅ 启用 |
| `value_response` | 价值回应 | 提供价值回应对方 | ✅ 启用 |
| `cooperation_exploration` | 合作探索 | 探讨合作可能性 | 保留枚举，UI不展示 |
| `intent_confirmed` | 意图确认 | 双方合作意图已确认 | 保留枚举，UI不展示 |
| `execution` | 执行中 | 合作正在执行 | 保留枚举，UI不展示 |
| `review` | 回顾复盘 | 阶段性回顾复盘 | 保留枚举，UI不展示 |

> **关键规则 RS-01**: 阶段不可仅由AI自动升级，必须用户确认。AI可基于行为数据建议升级，但最终升级操作需用户在推进卡上主动确认。

**JSONB字段结构示例**:

```json
{
  "concerns": [
    {
      "topic": "寻找AI方向技术合伙人",
      "source_event_id": "uuid-of-event",
      "created_at": "2026-06-03T10:00:00Z"
    }
  ],
  "need_insights": [
    {
      "content": "对方团队急需前端开发资源",
      "confidence": 0.85,
      "source_event_id": "uuid-of-event",
      "created_at": "2026-06-03T10:00:00Z"
    }
  ],
  "contributions": [
    {
      "content": "介绍了李四给张三认识",
      "date": "2026-06-01",
      "created_at": "2026-06-01T10:00:00Z"
    }
  ],
  "pending_promises": [
    {
      "content": "下周发一份AI算法团队介绍资料",
      "due_at": "2026-06-10T00:00:00Z",
      "promisor_type": "my_promise",
      "source_event_id": "uuid-of-event",
      "status": "pending",
      "created_at": "2026-06-03T10:00:00Z"
    }
  ],
  "feedback_records": [
    {
      "type": "stage_confirmation",
      "content": "用户确认从new_connection升级到understanding_needs",
      "created_at": "2026-06-04T15:00:00Z"
    }
  ]
}
```

---

### 3.4 Todos表（待办表）

**用途**: 存储AI生成的待办事项及用户追踪

| 字段名 | 类型 | 约束 | 默认值 | 说明 |
|--------|------|------|--------|------|
| id | UUID | PRIMARY KEY | gen_random_uuid() | 主键 |
| todo_type | VARCHAR(20) | NOT NULL | - | cooperation_signal\|risk\|care\|promise\|followup\|help |
| status | VARCHAR(20) | NOT NULL | 'pending' | pending\|in_progress\|done\|dismissed\|snoozed |
| priority | VARCHAR(10) | NOT NULL | 'medium' | high\|medium\|low |
| description | TEXT | NOT NULL | - | Todo描述 |
| related_entity_id | UUID | FK(entities.id) | NULL | 关联实体ID |
| source_event_id | UUID | FK(events.id) | NULL | 来源事件ID |
| action_type | VARCHAR(25) | - | 'my_promise' | 动作类型6种枚举（F-45，v2.0新增） |
| promisor_id | UUID | FK(entities.id) | NULL | 承诺人ID（F-45，v2.0新增） |
| beneficiary_id | UUID | FK(entities.id) | NULL | 受益人ID（F-45，v2.0新增） |
| confirmation_status | VARCHAR(15) | - | 'pending' | 确认状态（F-45，v2.0新增） |
| evidence_quote | TEXT | - | NULL | 证据原文（F-45 BLK-1，v2.0新增） |
| evidence_event_id | UUID | FK(events.id) | NULL | 证据来源事件ID（F-45，v2.0新增） |
| context | JSONB | - | '{}' | 上下文信息 |
| due_date | TIMESTAMPTZ | - | NULL | 截止时间 |
| snooze_until | TIMESTAMPTZ | - | NULL | 延迟到某时间 |
| user_id | UUID | NOT NULL, FK(users.id) | - | 用户ID |
| created_at | TIMESTAMPTZ | NOT NULL | NOW() | 创建时间 |
| updated_at | TIMESTAMPTZ | NOT NULL | NOW() | 更新时间 |
| completed_rank | INTEGER | - | NULL | 完成序号(隐式反馈用, v2.5新增) |
| dynamic_score | FLOAT | - | NULL | 动态优先级分(v2.5新增) |
| score_calculated_at | TIMESTAMPTZ | - | NULL | 评分时间(v2.5新增) |
| fulfillment_status | VARCHAR(20) | - | 'pending' | 承诺兑现状态(F-68, v2.9新增) |
| fulfilled_at | TIMESTAMPTZ | - | NULL | 兑现时间(F-68, v2.9新增) |
| overdue_notified_at | TIMESTAMPTZ | - | NULL | 逾期通知时间(F-68, v2.9新增) |

**CHECK约束（v2.0新增）**:
```sql
ALTER TABLE todos ADD CONSTRAINT todo_action_type_check
    CHECK (action_type IN ('my_promise','their_promise','my_followup','mutual_action','system_reminder','unclear'));
```

**CHECK约束（v2.5新增）**:
```sql
ALTER TABLE todos ADD CONSTRAINT check_dynamic_score_range
    CHECK (dynamic_score IS NULL OR (dynamic_score >= 0 AND dynamic_score <= 100));
ALTER TABLE todos ADD CONSTRAINT check_score_timestamp_valid
    CHECK (score_calculated_at IS NULL OR score_calculated_at <= CURRENT_TIMESTAMP);
```

**CHECK约束（v2.9新增, F-68）**:
```sql
ALTER TABLE todos ADD COLUMN fulfillment_status VARCHAR(20) DEFAULT 'pending'
  CHECK (fulfillment_status IN ('pending', 'fulfilled', 'overdue', 'expired'));
ALTER TABLE todos ADD COLUMN fulfilled_at TIMESTAMP;
ALTER TABLE todos ADD COLUMN overdue_notified_at TIMESTAMP;
-- 注意：due_date字段已存在，无需新增
```

**fulfillment_status与status正交说明（F-68, v2.9新增）**:
- **status**: 任务执行状态(pending/in_progress/done/dismissed/snoozed)
- **fulfillment_status**: 承诺兑现语义(pending/fulfilled/overdue/expired)
- 仅action_type为promise/their_promise的Todo有fulfillment_status语义

**action_type枚举说明（F-45，v2.0新增）**:

| action_type | 中文名 | 行为规则 |
|-------------|--------|---------|
| `my_promise` | 我的承诺 | 进入我的Todo列表，需跟进兑现 |
| `their_promise` | 对方承诺 | 显示"等待对方回应"，不入Todo |
| `my_followup` | 我的跟进 | 生成跟进型Todo |
| `mutual_action` | 共同行动 | 双方各生成一条Todo |
| `system_reminder` | 系统提醒 | 系统自动生成提醒型Todo |
| `unclear` | 待确认 | 标记为待确认，需用户手动确认后生成Todo |

**索引**:
```sql
CREATE INDEX idx_todos_user_status ON todos(user_id, status);
CREATE INDEX idx_todos_type ON todos(todo_type);
CREATE INDEX idx_todos_priority ON todos(priority);
CREATE INDEX idx_todos_due_date ON todos(due_date) WHERE due_date IS NOT NULL;
CREATE INDEX idx_todos_entity ON todos(related_entity_id);
CREATE INDEX idx_todos_dynamic_score ON todos(user_id, dynamic_score DESC) WHERE dynamic_score IS NOT NULL;  -- v2.5新增
CREATE UNIQUE INDEX idx_todos_completed_rank ON todos(user_id, completed_rank) WHERE completed_rank IS NOT NULL;  -- v2.5新增
```

**todo_type枚举与莫兰迪色映射**:

| todo_type | 中文名 | 莫兰迪色 | 色值 | 说明 |
|-----------|--------|---------|------|------|
| `promise` | 承诺 | 雾绿 | #A0C4A8 | 我答应过的事情，需跟进兑现 |
| `help` | 帮助 | 雾紫 | #B0A0C4 | 可以为对方提供的帮助 |
| `care` | 关心 | 雾蓝 | #A0B0C4 | 对方关注的事项，需留意 |
| `followup` | 跟进 | 雾金 | #C4C0A0 | 需要后续跟进的事项 |
| `cooperation_signal` | 合作信号 | 雾白 | #B8C4C0 | 发现潜在合作/商业机会 |
| `risk` | 风险 | 烟粉 | #C4A7A0 | 识别潜在风险或不利因素 |

**morandi_color在context中的存储**:
```json
{
  "morandi_color": "#A0C4A8"
}
```
> 前端可根据todo_type自动映射颜色，morandi_color字段作为冗余存储确保一致性。

**JSONB context结构**（按todo_type分类）:

**通用字段**（所有类型共享）:
```json
{
  "reason": "Todo生成的简要原因",
  "morandi_color": "#A0C4A8",
  "related_entities": ["entity_id_1", "entity_id_2"],
  "llm_explanation": "LLM生成的详细解释"
}
```

**promise类型特有字段**:
```json
{
  "due_at": "2026-06-10T00:00:00Z",
  "completion_note": "已发送资料至对方邮箱"
}
```

**care类型特有字段**:
```json
{
  "concern_topic": "寻找AI方向技术合伙人",
  "source_event_id": "uuid-of-event"
}
```

**help类型特有字段**:
```json
{
  "target_entity_id": "uuid-of-target-entity",
  "help_description": "可以介绍自己的算法团队给他"
}
```

**cooperation_signal类型特有字段**:
```json
{
  "signal_type": "resource_match",
  "related_entities": ["entity_id_1", "entity_id_2"]
}
```

**risk / followup类型**:
- 使用通用字段即可，无额外特有字段

**risk类型 — resource_overuse子类型（v2.8新增, F-39）**:
```json
{
  "risk_type": "resource_overuse",
  "target_entity_id": "uuid-of-target-entity",
  "request_count": 4,
  "window_days": 30,
  "severity": "warning"
}
```
> 当 `risk_type=resource_overuse` 时，表示资源透支检测触发的风险Todo。severity取值: `warning`(3-5次) / `critical`(≥6次)。

**完整context示例（promise类型）**:
```json
{
  "reason": "您在6月1日会议中答应了张三发送算法团队介绍资料",
  "morandi_color": "#A0C4A8",
  "related_entities": ["entity_id_zhangsan"],
  "llm_explanation": "基于会议纪要，用户承诺下周发送资料...",
  "due_at": "2026-06-10T00:00:00Z",
  "completion_note": null
}
```

**context字段说明**:
| 字段 | 类型 | 适用类型 | 说明 |
|------|------|---------|------|
| reason | string | 全部 | Todo生成的简要原因 |
| morandi_color | string | 全部 | 莫兰迪色值，与todo_type对应 |
| related_entities | string[] | 全部 | 关联实体ID数组 |
| llm_explanation | string | 全部 | LLM生成的详细解释 |
| due_at | string(ISO8601) | promise | 承诺截止时间 |
| completion_note | string\|null | promise | 完成时的备注 |
| concern_topic | string | care | 对方关注的话题 |
| source_event_id | string(UUID) | care | 关注话题来源事件ID |
| target_entity_id | string(UUID) | help | 帮助目标实体ID |
| help_description | string | help | 帮助内容描述 |
| signal_type | string | cooperation_signal | 合作信号类型（resource_match/need_match/opportunity等） |

---

### 3.5 Users表（用户表）

**用途**: 用户账号管理（基础版/专业版暂时单用户）

| 字段名 | 类型 | 约束 | 默认值 | 说明 |
|--------|------|------|--------|------|
| id | UUID | PRIMARY KEY | gen_random_uuid() | 主键 |
| username | VARCHAR(50) | UNIQUE, NOT NULL | - | 用户名 |
| email | VARCHAR(100) | UNIQUE | NULL | 邮箱 |
| password_hash | VARCHAR(255) | NOT NULL | - | 密码哈希（bcrypt） |
| preferences | JSONB | - | '{}' | 用户偏好设置 |
| created_at | TIMESTAMPTZ | NOT NULL | NOW() | 创建时间 |

**索引**:
```sql
CREATE UNIQUE INDEX idx_users_username ON users(username);
CREATE UNIQUE INDEX idx_users_email ON users(email) WHERE email IS NOT NULL;
```

---

### 3.5b ScoreAuditLogs表（评分审计日志表）[v2.5新增, v2.9实现]

**用途**: 记录 Todo 动态优先级分数的变更历史，支撑 Insight Engine 的可解释性和调试。

**实现状态**: ✅ 已实现（ORM模型: `models/score_audit_log.py`, 评分器集成: `services/priority_scorer.py`）

| 字段名 | 类型 | 约束 | 默认值 | 说明 |
|--------|------|------|--------|------|
| id | INTEGER | PRIMARY KEY AUTOINCREMENT | - | 主键（SQLite兼容，PG用BIGSERIAL） |
| todo_id | UUID | NOT NULL, FK(todos.id) | - | 关联Todo ID |
| user_id | UUID | NOT NULL | - | 用户ID |
| old_score | FLOAT | - | NULL | 变更前分数 |
| new_score | FLOAT | NOT NULL | - | 变更后分数 |
| score_version | VARCHAR(20) | NOT NULL | - | 评分模型版本（poc_v1/phase1_v1） |
| calculation_factors | JSONB | NOT NULL | - | 计算因子快照 |
| calculated_by | VARCHAR(50) | NOT NULL | - | 计算器标识（PriorityScorer/PriorityScorerV2） |
| triggered_by | VARCHAR(50) | NOT NULL | - | 触发来源 |
| created_at | TIMESTAMPTZ | NOT NULL | NOW() | 创建时间 |

**score_version枚举说明**:

| 值 | 说明 |
|----|------|
| `poc_v1` | PoC二维模型（urgency + importance） |
| `phase1_v1` | 专业版四维模型（urgency + importance + dependency + context） |

**calculated_by枚举说明**:

| 值 | 说明 |
|----|------|
| `PriorityScorer` | PoC二维评分器 |
| `PriorityScorerV2` | 专业版四维评分器 |

**triggered_by枚举说明**:

| 值 | 说明 |
|----|------|
| `implicit_feedback` | 隐式反馈触发（完成顺序变化） |
| `manual_recalc` | 手动触发重新计算 |
| `scheduled_job` | 定时任务触发（daily_rebalance） |
| `scorer_update` | 评分器主动更新（score_and_update_todo） |

**索引**:
```sql
CREATE INDEX idx_score_audit_user_time ON score_audit_logs(user_id, created_at DESC);
CREATE INDEX idx_score_audit_todo ON score_audit_logs(todo_id, created_at DESC);
```

**calculation_factors JSONB结构示例**:
```json
{
  "urgency": 0.85,
  "importance": 0.72,
  "dependency_score": 0.45,
  "context_score": 0.917,
  "completed_rank": 3,
  "weight_adjustment": 0.05,
  "entity_id": "uuid-of-person",
  "dependency_raw": {
    "depth_weight_sum": 1.5,
    "blocked_count": 2,
    "block_weight": 0.3,
    "max_depth": 3
  },
  "context_raw": {
    "entity_id": "uuid-of-person",
    "hours_until": 2.0,
    "window_hours": 24,
    "formula": "max(0, 1 - hours_until / 24)"
  }
}
```

> **v2.6扩展说明**: calculation_factors 新增 `dependency_score`、`context_score`、`dependency_raw`、`context_raw` 字段，用于审计 F-55 依赖性全图谱路径分析和 F-56 场景匹配Event表驱动的计算因子。专业版启用四维模型后，审计日志将完整记录四个维度的得分和原始计算因子。

---

### 3.5c AdapterConfigs表（数据源适配器配置表）[v2.5新增]

**用途**: 存储多数据源适配器配置，支撑 DataSourceAdapter 接口的多源数据接入能力。

| 字段名 | 类型 | 约束 | 默认值 | 说明 |
|--------|------|------|--------|------|
| id | UUID | PRIMARY KEY | gen_random_uuid() | 主键 |
| user_id | UUID | NOT NULL | - | 用户ID |
| adapter_name | VARCHAR(50) | NOT NULL | - | 适配器名称 |
| config_encrypted | BYTEA | - | NULL | 加密存储API密钥等配置 |
| is_active | BOOLEAN | NOT NULL | true | 是否启用 |
| last_sync_at | TIMESTAMPTZ | - | NULL | 最近同步时间 |
| created_at | TIMESTAMPTZ | NOT NULL | NOW() | 创建时间 |

**adapter_name枚举约束**:
```sql
CONSTRAINT valid_adapter_name CHECK (adapter_name IN ('manual', 'voice', 'wechat_forward', 'email', 'calendar'))
```

**唯一约束**:
```sql
UNIQUE(user_id, adapter_name)
```

**adapter_name枚举说明**:

| 值 | 说明 | 数据格式 |
|----|------|---------|
| `manual` | 手动输入 | 用户直接输入文本 |
| `voice` | 语音输入 | ASR识别后的文本 |
| `wechat_forward` | 微信转发 | 聊天记录转发文本 |
| `email` | 邮件解析 | 邮件正文+元数据 |
| `calendar` | 日历同步 | 会议信息+参与者 |

**安全要求**:
- `config_encrypted` 使用 AES-256-GCM 加密存储 API 密钥等敏感配置
- 解密密钥通过环境变量注入，不存储在数据库中
- 读取配置时应用层解密，API响应中不返回配置内容

---

### 3.5d ReminderPreferences表（提醒偏好表）[v2.9新增, F-69]

**用途**: 存储用户个性化提醒偏好设置，支撑智能提醒引擎的自适应调度。

| 字段名 | 类型 | 约束 | 默认值 | 说明 |
|--------|------|------|--------|------|
| user_id | VARCHAR(36) | PRIMARY KEY | - | 用户ID（与users.id一致） |
| preferred_times | JSONB | - | '["09:00","20:00"]' | 偏好提醒时间列表 |
| fatigue_threshold | INTEGER | - | 5 | 疲劳阈值（每日最大提醒数） |
| quiet_hours_start | TIME | - | '22:00' | 免打扰开始时间 |
| quiet_hours_end | TIME | - | '08:00' | 免打扰结束时间 |
| updated_at | TIMESTAMP | - | CURRENT_TIMESTAMP | 更新时间 |

**DDL**:
```sql
CREATE TABLE reminder_preferences (
  user_id VARCHAR(36) PRIMARY KEY,
  preferred_times JSONB DEFAULT '["09:00","20:00"]',
  fatigue_threshold INTEGER DEFAULT 5,
  quiet_hours_start TIME DEFAULT '22:00',
  quiet_hours_end TIME DEFAULT '08:00',
  updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

**preferred_times JSONB结构示例**:
```json
["09:00", "20:00"]
```
> 用户偏好的提醒推送时间点列表，提醒引擎仅在这些时间窗口内推送提醒。

---

### 3.5e ReminderLogs表（提醒日志表）[v2.9新增, F-69]

**用途**: 记录每次提醒的发送及用户响应情况，支撑提醒效果分析和策略优化。

| 字段名 | 类型 | 约束 | 默认值 | 说明 |
|--------|------|------|--------|------|
| id | VARCHAR(36) | PRIMARY KEY | - | 主键 |
| user_id | VARCHAR(36) | NOT NULL | - | 用户ID |
| todo_id | VARCHAR(36) | NOT NULL, FK(todos.id) | - | 关联Todo ID |
| reminder_type | VARCHAR(30) | NOT NULL | - | 提醒类型 |
| sent_at | TIMESTAMP | NOT NULL | CURRENT_TIMESTAMP | 发送时间 |
| action_taken | VARCHAR(20) | - | NULL | 用户响应动作 |
| response_latency_seconds | INTEGER | - | NULL | 响应延迟（秒） |

**DDL**:
```sql
CREATE TABLE reminder_logs (
  id VARCHAR(36) PRIMARY KEY,
  user_id VARCHAR(36) NOT NULL,
  todo_id VARCHAR(36) NOT NULL REFERENCES todos(id),
  reminder_type VARCHAR(30) NOT NULL CHECK (reminder_type IN ('promise_due', 'followup', 'stage_suggestion', 'dormant_contact')),
  sent_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  action_taken VARCHAR(20) CHECK (action_taken IN ('completed', 'snoozed', 'dismissed', 'ignored')),
  response_latency_seconds INTEGER,
  FOREIGN KEY (todo_id) REFERENCES todos(id)
);
CREATE INDEX idx_reminder_logs_user_sent ON reminder_logs(user_id, sent_at);
```

**reminder_type枚举说明**:

| reminder_type | 中文名 | 说明 |
|---------------|--------|------|
| `promise_due` | 承诺到期提醒 | 承诺即将到期或已到期时触发 |
| `followup` | 跟进提醒 | 需要后续跟进的事项提醒 |
| `stage_suggestion` | 阶段推进建议 | 关系阶段推进建议提醒 |
| `dormant_contact` | 沉默联系人提醒 | 长时间未互动的联系人提醒 |

**action_taken枚举说明**:

| action_taken | 中文名 | 说明 |
|--------------|--------|------|
| `completed` | 已完成 | 用户完成待办 |
| `snoozed` | 延迟 | 用户选择延迟提醒 |
| `dismissed` | 忽略 | 用户主动忽略 |
| `ignored` | 未响应 | 用户未做任何操作 |

---

### 3.5f RelayConnections表（网关中继连接表）[v3.0新增, 📋专业版（尚未实现）]

**用途**: 记录专业版用户通过relay gateway的连接状态，支撑网关中继服务的连接管理和心跳检测。

> **产品层级说明**: 此表仅在 **专业版** 中使用。基础版为本地运行，无需中继连接；定制版为自部署服务，不使用共享网关。

| 字段名 | 类型 | 约束 | 默认值 | 说明 |
|--------|------|------|--------|------|
| id | UUID | PRIMARY KEY | gen_random_uuid() | 主键 |
| user_id | UUID | NOT NULL, FK(users.id) | - | 用户ID |
| connection_id | VARCHAR(100) | NOT NULL, UNIQUE | - | 连接唯一标识（WebSocket connection ID） |
| connected_at | TIMESTAMPTZ | NOT NULL | NOW() | 连接建立时间 |
| last_heartbeat | TIMESTAMPTZ | NOT NULL | NOW() | 最近心跳时间 |
| status | VARCHAR(20) | NOT NULL | 'connected' | 连接状态 |

**status枚举说明**:

| 值 | 说明 |
|----|------|
| `connected` | 连接活跃 |
| `disconnected` | 连接断开 |
| `reconnecting` | 重连中 |

**DDL**:
```sql
CREATE TABLE relay_connections (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL REFERENCES users(id),
  connection_id VARCHAR(100) NOT NULL UNIQUE,
  connected_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  last_heartbeat TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  status VARCHAR(20) NOT NULL DEFAULT 'connected'
    CHECK (status IN ('connected', 'disconnected', 'reconnecting'))
);
CREATE INDEX idx_relay_connections_user ON relay_connections(user_id);
CREATE INDEX idx_relay_connections_status ON relay_connections(status);
CREATE INDEX idx_relay_connections_heartbeat ON relay_connections(last_heartbeat);
```

---

### 3.5g AIUsageLogs表（AI用量日志表）[v3.0新增, 📋专业版（尚未实现）]

**用途**: 记录AI调用的用量和成本，支撑专业版/定制版的用量计费和成本分析。

> **产品层级说明**: 基础版不记录AI用量（本地免费）；专业版通过网关中继调用AI，需记录用量；定制版自部署AI服务，需记录成本。

| 字段名 | 类型 | 约束 | 默认值 | 说明 |
|--------|------|------|--------|------|
| id | UUID | PRIMARY KEY | gen_random_uuid() | 主键 |
| user_id | UUID | NOT NULL, FK(users.id) | - | 用户ID |
| action_type | VARCHAR(30) | NOT NULL | - | AI动作类型 |
| tokens_used | INTEGER | - | 0 | Token消耗量 |
| cost | FLOAT | - | 0.0 | 调用成本（元） |
| created_at | TIMESTAMPTZ | NOT NULL | NOW() | 创建时间 |

**action_type枚举说明**:

| 值 | 说明 |
|----|------|
| `entity_extraction` | 实体抽取 |
| `todo_generation` | Todo生成 |
| `embedding` | 向量嵌入 |
| `semantic_search` | 语义搜索 |
| `voice_nlu` | 语音NLU |
| `ocr` | OCR识别 |
| `asr` | 语音识别 |
| `tts` | 语音合成 |
| `title_generation` | 标题生成 |
| `brief_update` | 推进卡更新 |

**DDL**:
```sql
CREATE TABLE ai_usage_logs (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL REFERENCES users(id),
  action_type VARCHAR(30) NOT NULL
    CHECK (action_type IN ('entity_extraction', 'todo_generation', 'embedding',
      'semantic_search', 'voice_nlu', 'ocr', 'asr', 'tts',
      'title_generation', 'brief_update')),
  tokens_used INTEGER DEFAULT 0,
  cost FLOAT DEFAULT 0.0,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_ai_usage_user_time ON ai_usage_logs(user_id, created_at DESC);
CREATE INDEX idx_ai_usage_action ON ai_usage_logs(action_type);
```

---

### 3.6 VoiceSessions表（语音会话表）[F-50新增]

**用途**: 存储语音助手每次交互的完整会话记录（ASR→NLU→API→NLG→TTS全链路）

> **隐私原则**: 不存储原始音频文件，仅存储ASR识别后的文字及处理元数据。

| 字段名 | 类型 | 约束 | 默认值 | 说明 |
|--------|------|------|--------|------|
| id | UUID | PRIMARY KEY | gen_random_uuid() | 主键 |
| user_id | UUID | NOT NULL, FK(users.id) | - | 用户ID |
| query_text | VARCHAR(500) | NOT NULL | - | ASR识别后的文字（最大500字符） |
| asr_confidence | FLOAT | - | NULL | ASR置信度（0-1） |
| is_voice_input | BOOLEAN | - | TRUE | 是否语音输入（FALSE=手动文字输入） |
| client_ip | INET | - | NULL | 客户端IP（安全审计用） |
| intent | VARCHAR(30) | NOT NULL | - | 识别的意图（schedule_query/promise_tracker/etc） |
| intent_confidence | FLOAT | NOT NULL | - | 意图识别置信度（0-1） |
| slots | JSONB | - | '{}' | 槽位填充结果 |
| target_api | VARCHAR(100) | - | NULL | 调用的目标API路径 |
| api_params | JSONB | - | NULL | API请求参数 |
| answer_text | VARCHAR(2000) | - | NULL | 生成的回答文字（最大2000字符） |
| answer_source | VARCHAR(20) | - | NULL | 回答来源：template / nlg / fallback |
| tts_cached | BOOLEAN | - | FALSE | TTS是否已缓存 |
| user_rating | VARCHAR(20) | - | NULL | 用户反馈：helpful / not_helpful / wrong_intent / unclear |
| feedback_comment | TEXT | - | NULL | 反馈评论 |
| processing_time_ms | INTEGER | - | NULL | 端到端处理耗时（毫秒） |
| created_at | TIMESTAMPTZ | NOT NULL | NOW() | 创建时间 |
| updated_at | TIMESTAMPTZ | NOT NULL | NOW() | 更新时间 |

**索引**:
```sql
CREATE INDEX idx_voice_sessions_user_created ON voice_sessions(user_id, created_at DESC);
CREATE INDEX idx_voice_sessions_intent ON voice_sessions(intent);
CREATE INDEX idx_voice_sessions_created ON voice_sessions(created_at);
```

**slots JSONB结构示例**:
```json
{
  "date": "2026-06-05",
  "person": "张总",
  "time_range": "下午",
  "topic": "合作方案"
}
```

**intent枚举说明**:

| intent值 | 中文名 | 说明 |
|----------|--------|------|
| `schedule_query` | 日程查询 | 查询某人的日程安排 |
| `promise_tracker` | 承诺追踪 | 追踪承诺兑现情况 |
| `entity_search` | 实体搜索 | 搜索联系人/公司信息 |
| `relationship_overview` | 关系概览 | 查看关系阶段和推进建议 |
| `todo_query` | 待办查询 | 查询待办事项状态 |
| `general_qa` | 通用问答 | 其他通用问题 |
| `unclear` | 意图不明 | 无法识别用户意图 |

**answer_source枚举说明**:

| 值 | 说明 |
|----|------|
| `template` | 模板回答（固定场景，无需LLM） |
| `nlg` | NLG生成（LLM动态生成回答） |
| `fallback` | 兜底回答（无法理解时返回的默认回复） |

---

### 3.7 VoiceTurns表（多轮对话轮次表）[F-50新增，专业版启用]

**用途**: 存储多轮对话中的每一轮交互内容，支持上下文延续和澄清追问。

> **⚠️ 产品层级说明**: 此表在 **基础版** 不创建（单轮问答模式）。**专业版** 启用多轮对话后激活。POC阶段如使用SQLite，JSONB字段以TEXT存储JSON格式。

| 字段名 | 类型 | 约束 | 默认值 | 说明 |
|--------|------|------|--------|------|
| id | UUID | PRIMARY KEY | gen_random_uuid() | 主键 |
| session_id | UUID | NOT NULL, FK(voice_sessions.id), CASCADE | - | 所属会话ID |
| turn_number | INTEGER | NOT NULL | - | 第几轮（从1开始） |
| role | VARCHAR(10) | NOT NULL | - | 角色：user / system / clarification |
| content | TEXT | NOT NULL | - | 文本内容 |
| turn_type | VARCHAR(20) | - | NULL | 轮次类型：question / answer / error / follow_up / suggestion |
| intent | VARCHAR(30) | - | NULL | 意图（仅user turn有值） |
| tokens_used | INTEGER | - | NULL | LLM token消耗（成本核算） |
| created_at | TIMESTAMPTZ | NOT NULL | NOW() | 创建时间 |

**唯一约束**:
```sql
CREATE UNIQUE INDEX idx_voice_turns_session_turn ON voice_turns(session_id, turn_number);
```

**索引**:
```sql
CREATE INDEX idx_voice_turns_session ON voice_turns(session_id);
```

**role枚举说明**:

| role值 | 说明 | 典型场景 |
|--------|------|---------|
| `user` | 用户输入 | 用户提问或陈述 |
| `system` | 系统回答 | 助手返回结果 |
| `clarification` | 澄清追问 | 系统向用户确认槽位信息 |

**turn_type枚举说明**:

| turn_type值 | 说明 |
|-------------|------|
| `question` | 问题（用户提问或系统反问） |
| `answer` | 回答（系统给出答案） |
| `error` | 错误（处理异常时的响应） |
| `follow_up` | 追问（基于前一轮的后续问题） |
| `suggestion` | 建议（系统主动给出的推荐） |

---

### 3.8 VoiceAnalytics表（语音分析聚合表）[F-50新增]

**用途**: 按日期+用户+意图维度聚合语音会话数据，用于监控仪表盘和模型优化分析。

> **写入策略**: 由定时任务每日聚合 `voice_sessions` 数据写入，**不实时写入**（分析型数据）。业务代码不应直接操作此表。

| 字段名 | 类型 | 约束 | 默认值 | 说明 |
|--------|------|------|--------|------|
| id | UUID | PRIMARY KEY | gen_random_uuid() | 主键 |
| date | DATE | NOT NULL | - | 聚合日期 |
| user_id | UUID | FK(users.id) | NULL | 用户ID（NULL=全用户聚合） |
| intent | VARCHAR(30) | NOT NULL | - | 意图维度 |
| total_queries | INTEGER | - | 0 | 总查询数 |
| avg_confidence | FLOAT | - | NULL | 平均意图置信度 |
| unclear_rate | FLOAT | - | NULL | 不确定率 = unclear数 / 总数 |
| avg_processing_ms | FLOAT | - | NULL | 平均处理时长（毫秒） |
| helpful_rate | FLOAT | - | NULL | 有帮助率 = helpful评价数 / 已评价总数 |
| tts_hit_rate | FLOAT | - | NULL | TTS缓存命中率 |
| asr_error_rate | FLOAT | - | NULL | ASR错误率（识别失败/重试率） |
| created_at | TIMESTAMPTZ | NOT NULL | NOW() | 创建时间 |
| updated_at | TIMESTAMPTZ | NOT NULL | NOW() | 更新时间 |

**唯一约束**:
```sql
CREATE UNIQUE INDEX idx_voice_analytics_unique ON voice_analytics(date, user_id, intent);
```

**索引**:
```sql
CREATE INDEX idx_voice_analytics_date ON voice_analytics(date);
```

**聚合SQL示例**（定时任务参考）:
```sql
-- 每日聚合任务：从voice_sessions聚合到voice_analytics
INSERT INTO voice_analytics (date, user_id, intent, total_queries, avg_confidence,
    unclear_rate, avg_processing_ms, helpful_rate, tts_hit_rate, asr_error_rate)
SELECT
    CURRENT_DATE - INTERVAL '1 day'::DATE AS date,
    vs.user_id,
    vs.intent,
    COUNT(*) AS total_queries,
    AVG(vs.intent_confidence) AS avg_confidence,
    COUNT(*) FILTER (WHERE vs.intent = 'unclear')::FLOAT / COUNT(*) AS unclear_rate,
    AVG(vs.processing_time_ms) AS avg_processing_ms,
    COUNT(*) FILTER (WHERE vs.user_rating = 'helpful')::FLOAT /
        COUNT(*) FILTER (WHERE vs.user_rating IS NOT NULL) AS helpful_rate,
    COUNT(*) FILTER (WHERE vs.tts_cached = TRUE)::FLOAT / COUNT(*) AS tts_hit_rate,
    COUNT(*) FILTER (WHERE vs.asr_confidence < 0.5 OR vs.asr_confidence IS NULL)::FLOAT / COUNT(*) AS asr_error_rate
FROM voice_sessions vs
WHERE vs.created_at >= CURRENT_DATE - INTERVAL '1 day'
  AND vs.created_at < CURRENT_DATE
GROUP BY vs.user_id, vs.intent
ON CONFLICT (date, user_id, intent)
DO UPDATE SET
    total_queries = EXCLUDED.total_queries,
    avg_confidence = EXCLUDED.avg_confidence,
    unclear_rate = EXCLUDED.unclear_rate,
    avg_processing_ms = EXCLUDED.avg_processing_ms,
    helpful_rate = EXCLUDED.helpful_rate,
    tts_hit_rate = EXCLUDED.tts_hit_rate,
    asr_error_rate = EXCLUDED.asr_error_rate,
    updated_at = NOW();
```

---

## 4. 索引策略

### 4.1 索引设计原则
1. **查询模式驱动**: 基于API查询模式设计索引
2. **复合索引优先**: 高频组合查询使用复合索引
3. **避免过度索引**: 写多读少的表谨慎添加索引
4. **JSONB GIN索引**: 对JSONB字段使用GIN索引支持灵活查询

### 4.2 关键查询优化

**查询1**: 用户最近的事件（首页）
```sql
-- 索引: idx_events_user_timestamp
SELECT * FROM events 
WHERE user_id = ? 
ORDER BY timestamp DESC 
LIMIT 20;
```

**查询2**: 实体搜索（模糊匹配）
```sql
-- 索引: idx_entities_name + idx_entities_company
SELECT * FROM entities 
WHERE user_id = ? 
  AND (name ILIKE ? OR company ILIKE ?)
LIMIT 10;
```

**查询3**: 实体关联图谱（BFS遍历）
```sql
-- 索引: idx_assoc_source + idx_assoc_target
SELECT * FROM associations 
WHERE (source_entity_id = ? OR target_entity_id = ?)
  AND confidence >= 0.7;
```

**查询4**: 今日待办（状态+截止时间）
```sql
-- 索引: idx_todos_user_status + idx_todos_due_date
SELECT * FROM todos 
WHERE user_id = ? 
  AND status IN ('pending', 'in_progress')
  AND (due_date IS NULL OR due_date <= NOW() + INTERVAL '1 day')
ORDER BY priority DESC, created_at ASC;
```

---

## 5. 数据迁移方案

### 5.1 SQLite → PostgreSQL 迁移（定制版专用）

> **注意**：基础版和专业版长期使用SQLite，此迁移仅适用于销售团队定制版。

**场景**: 基础版/专业版SQLite数据迁移到定制版PostgreSQL

**步骤**:

```bash
# 1. 导出SQLite数据为SQL
sqlite3 promiselink_dev.db .dump > dump.sql

# 2. 转换SQL语法（脚本处理）
python scripts/sqlite_to_pg.py dump.sql > pg_dump.sql

# 3. 创建PostgreSQL schema
psql -U promiselink -d promiselink_prod -f schema.sql

# 4. 导入数据
psql -U promiselink -d promiselink_prod -f pg_dump.sql

# 5. 验证数据完整性
python scripts/verify_migration.py
```

**语法差异处理**:

| SQLite | PostgreSQL | 转换 |
|--------|-----------|------|
| `AUTOINCREMENT` | `SERIAL` | 改用UUID主键 |
| `TEXT` | `TEXT/VARCHAR` | 保持TEXT |
| `REAL` | `FLOAT/DOUBLE PRECISION` | 使用FLOAT |
| `BLOB` | `BYTEA` | 使用BYTEA |
| `datetime('now')` | `NOW()` | 替换为NOW() |

### 5.2 数据类型映射

```python
# scripts/sqlite_to_pg.py 核心逻辑
TYPE_MAPPING = {
    'INTEGER': 'INTEGER',
    'TEXT': 'TEXT',
    'REAL': 'FLOAT',
    'BLOB': 'BYTEA',
    'DATETIME': 'TIMESTAMPTZ',
}

def convert_create_table(sqlite_sql):
    # 替换类型
    for old, new in TYPE_MAPPING.items():
        sqlite_sql = sqlite_sql.replace(old, new)
    
    # 替换主键策略
    sqlite_sql = sqlite_sql.replace('AUTOINCREMENT', '')
    sqlite_sql = re.sub(r'id INTEGER PRIMARY KEY', 
                       'id UUID PRIMARY KEY DEFAULT gen_random_uuid()',
                       sqlite_sql)
    
    return sqlite_sql
```

### 5.3 Alembic增量迁移策略（v2.0新增）

**策略概述**: 从v1.2升级到v2.0采用Alembic增量迁移，确保生产数据零丢失、可回滚。

**迁移文件**: `alembic/versions/v120_v200_relationship_upgrade.py`

**迁移步骤**:

```python
"""v1.2 → v2.0: relationship_briefs表 + events/todos扩展字段

Revision ID: v120_v200
Revises: v110_v120
Create Date: 2026-06-04

迁移内容:
1. 新增 relationship_briefs 表（D1-1）
2. events 表追加 input_scope + input_scope_confidence 字段（D1-2）
3. todos 表追加 6个字段 + CHECK约束（D1-3）
4. entities.properties JSONB结构扩展（D1-4，应用层处理）
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

def upgrade():
    # === D1-1: 新增 relationship_briefs 表 ===
    op.create_table(
        'relationship_briefs',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text('gen_random_uuid()')),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('person_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('current_stage', sa.String(30), nullable=False,
                  server_default='new_connection'),
        sa.Column('stage_reason', sa.Text(), nullable=True),
        sa.Column('latest_interaction_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('next_node', sa.Text(), nullable=True),
        sa.Column('next_node_condition', sa.Text(), nullable=True),
        sa.Column('paused_reason', sa.Text(), nullable=True),
        sa.Column('confirmed_by_user', sa.Boolean(), server_default=sa.text('FALSE')),
        sa.Column('version', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('concerns', postgresql.JSONB(), server_default=sa.text("'[]'::jsonb")),
        sa.Column('need_insights', postgresql.JSONB(), server_default=sa.text("'[]'::jsonb")),
        sa.Column('contributions', postgresql.JSONB(), server_default=sa.text("'[]'::jsonb")),
        sa.Column('pending_promises', postgresql.JSONB(), server_default=sa.text("'[]'::jsonb")),
        sa.Column('feedback_records', postgresql.JSONB(), server_default=sa.text("'[]'::jsonb")),
        sa.Column('cooperation_direction_candidate', sa.Text(), nullable=True),
        sa.Column('created_at', sa.TIMESTAMPTZ(), server_default=sa.text('NOW()')),
        sa.Column('updated_at', sa.TIMESTAMPTZ(), server_default=sa.text('NOW()')),
    )
    op.create_index('idx_briefs_user', 'relationship_briefs', ['user_id'])
    op.create_index('idx_briefs_person', 'relationship_briefs', ['person_id'])
    op.create_index('idx_briefs_user_person', 'relationship_briefs',
                    ['user_id', 'person_id'], unique=True)
    op.create_foreign_key('fk_briefs_person', 'relationship_briefs', 'entities',
                          ['person_id'], ['id'])
    op.create_foreign_key('fk_briefs_interaction', 'relationship_briefs', 'events',
                          ['latest_interaction_id'], ['id'])

    # === D1-2: events 表追加字段 ===
    op.add_column('events', sa.Column('input_scope', sa.String(30),
                   server_default='relationship_interaction'))
    op.add_column('events', sa.Column('input_scope_confidence', sa.Float(),
                   server_default='1.0'))
    op.create_index('idx_events_input_scope', 'events', ['input_scope'],
                    postgresql_where=sa.text('input_scope IS NOT NULL'))

    # === D1-3: todos 表追加字段 ===
    op.add_column('todos', sa.Column('action_type', sa.String(25),
                   server_default='my_promise'))
    op.add_column('todos', sa.Column('promisor_id', postgresql.UUID(as_uuid=True)))
    op.add_column('todos', sa.Column('beneficiary_id', postgresql.UUID(as_uuid=True)))
    op.add_column('todos', sa.Column('confirmation_status', sa.String(15),
                   server_default='pending'))
    op.add_column('todos', sa.Column('evidence_quote', sa.Text()))
    op.add_column('todos', sa.Column('evidence_event_id', postgresql.UUID(as_uuid=True)))

    # 添加外键约束
    op.create_foreign_key('todos_promisor_id_fkey', 'todos', 'entities',
                          ['promisor_id'], ['id'])
    op.create_foreign_key('todos_beneficiary_id_fkey', 'todos', 'entities',
                          ['beneficiary_id'], ['id'])
    op.create_foreign_key('todos_evidence_event_id_fkey', 'todos', 'events',
                          ['evidence_event_id'], ['id'])

    # 添加CHECK约束
    op.execute("""
        ALTER TABLE todos ADD CONSTRAINT todo_action_type_check
            CHECK (action_type IN (
                'my_promise','their_promise','my_followup',
                'mutual_action','system_reminder','unclear'
            ))
    """)

    # === D1-4: entities.properties JSONB扩展（应用层处理）===
    # 注意：JSONB内部结构变更无需DDL，由应用层ORM模型负责兼容读写
    # 建议执行数据回填：为现有person实体补充 relationship_stage 字段
    op.execute("""
        UPDATE entities e
        SET properties = jsonb_set(
            COALESCE(e.properties, '{}'::jsonb),
            '{relationship_stage}',
            '"new_connection"'::jsonb
        )
        WHERE e.entity_type = 'person'
          AND e.properties->>'relationship_stage' IS NULL
    """)


def downgrade():
    # 回滚顺序与upgrade相反
    op.drop_constraint('todo_action_type_check', 'todos', type_='check')
    op.drop_constraint('todos_evidence_event_id_fkey', 'todos', type_='foreignkey')
    op.drop_constraint('todos_beneficiary_id_fkey', 'todos', type_='foreignkey')
    op.drop_constraint('todos_promisor_id_fkey', 'todos', type_='foreignkey')

    op.drop_column('todos', 'evidence_event_id')
    op.drop_column('todos', 'evidence_quote')
    op.drop_column('todos', 'confirmation_status')
    op.drop_column('todos', 'beneficiary_id')
    op.drop_column('todos', 'promisor_id')
    op.drop_column('todos', 'action_type')

    op.drop_index('idx_events_input_scope', table_name='events')
    op.drop_column('events', 'input_scope_confidence')
    op.drop_column('events', 'input_scope')

    op.drop_constraint('fk_briefs_interaction', 'relationship_briefs', type_='foreignkey')
    op.drop_constraint('fk_briefs_person', 'relationship_briefs', type_='foreignkey')
    op.drop_index('idx_briefs_user_person', table_name='relationship_briefs')
    op.drop_index('idx_briefs_person', table_name='relationship_briefs')
    op.drop_index('idx_briefs_user', table_name='relationship_briefs')
    op.drop_table('relationship_briefs')
```

**迁移执行命令**:
```bash
# 生成迁移文件（如需手动调整）
alembic revision --autogenerate -m "v120_v200_relationship_upgrade"

# 执行升级
alembic upgrade head

# 验证升级结果
alembic current
alembic history --verbose

# 如需回滚
alembic downgrade -1
```

**迁移验证清单**:
| 验证项 | 方法 | 预期结果 |
|--------|------|---------|
| relationship_briefs表创建 | `\d relationship_briefs` | 20个字段，3个索引，2个FK |
| events新字段存在 | `SELECT column_name FROM information_schema.columns WHERE table_name='events'` | 包含input_scope, input_scope_confidence |
| todos新字段+CHECK | `\d todos` | 6个新字段 + todo_action_type_check约束 |
| 现有数据完整性 | `SELECT COUNT(*) FROM events` + `SELECT COUNT(*) FROM todos` | 数据量不变 |
| 回滚可用性 | `alembic downgrade -1` 后检查 | 恢复到v1.2 schema |

### 5.4 F-50语音助手表迁移（[0.2.1新增]）

**迁移文件**: `alembic/versions/xxx_add_voice_tables.py`

**生成命令**:
```bash
alembic revision --autogenerate -m "add F-50 voice assistant tables"
# 生成: xxx_add_voice_tables.py
```

**迁移内容**:
| 项目 | 详情 |
|------|------|
| 新增表 | `voice_sessions`, `voice_turns`, `voice_analytics` |
| 索引 | 3个（voice_sessions）+ 1个（voice_turns）+ 1个（voice_analytics）= **5个** |
| 唯一约束 | 1个（voice_turns: session_id + turn_number）+ 1个（voice_analytics: date + user_id + intent）= **2个** |
| 外键 | voice_sessions.user_id → users.id, voice_turns.session_id → voice_sessions.id (CASCADE), voice_analytics.user_id → users.id = **3个** |
| Phase说明 | voice_turns表在专业版启用，基础版可跳过创建 |

**Alembic迁移代码**:
```python
"""F-50: 新增语音助手3张表

Revision ID: v200_f50_voice
Revises: v120_v200
Create Date: 2026-06-05

迁移内容:
1. 新增 voice_sessions 表（语音会话，18字段+3索引）
2. 新增 voice_turns 表（多轮对话轮次，9字段+唯一约束，专业版启用）
3. 新增 voice_analytics 表（分析聚合表，12字段+唯一约束）
4. 共计: 3张表 + 5个索引 + 2个唯一约束 + 3个外键

注意:
- SQLite兼容: JSONB→TEXT(JSON格式存储)，INET→VARCHAR(45)
- voice_turns在基础版不使用，但建议提前建表以简化后续迁移
- voice_analytics为聚合表，由定时任务写入，业务代码不直接操作
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

def upgrade():
    # === 1. voice_sessions 表 ===
    op.create_table(
        'voice_sessions',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text('gen_random_uuid()')),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('query_text', sa.String(500), nullable=False),
        sa.Column('asr_confidence', sa.Float(), nullable=True),
        sa.Column('is_voice_input', sa.Boolean(), server_default=sa.text('TRUE')),
        sa.Column('client_ip', postgresql.INET(), nullable=True),
        sa.Column('intent', sa.String(30), nullable=False),
        sa.Column('intent_confidence', sa.Float(), nullable=False),
        sa.Column('slots', postgresql.JSONB(), server_default=sa.text("'{}'::jsonb")),
        sa.Column('target_api', sa.String(100), nullable=True),
        sa.Column('api_params', postgresql.JSONB(), nullable=True),
        sa.Column('answer_text', sa.String(2000), nullable=True),
        sa.Column('answer_source', sa.String(20), nullable=True),
        sa.Column('tts_cached', sa.Boolean(), server_default=sa.text('FALSE')),
        sa.Column('user_rating', sa.String(20), nullable=True),
        sa.Column('feedback_comment', sa.Text(), nullable=True),
        sa.Column('processing_time_ms', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.TIMESTAMPTZ(), server_default=sa.text('NOW()')),
        sa.Column('updated_at', sa.TIMESTAMPTZ(), server_default=sa.text('NOW()')),
    )
    op.create_index('idx_voice_sessions_user_created', 'voice_sessions',
                    ['user_id', 'created_at'])
    op.create_index('idx_voice_sessions_intent', 'voice_sessions', ['intent'])
    op.create_index('idx_voice_sessions_created', 'voice_sessions', ['created_at'])
    op.create_foreign_key('fk_voice_sessions_user', 'voice_sessions', 'users',
                          ['user_id'], ['id'])

    # === 2. voice_turns 表（专业版启用） ===
    op.create_table(
        'voice_turns',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text('gen_random_uuid()')),
        sa.Column('session_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('turn_number', sa.Integer(), nullable=False),
        sa.Column('role', sa.String(10), nullable=False),
        sa.Column('content', sa.Text(), nullable=False),
        sa.Column('turn_type', sa.String(20), nullable=True),
        sa.Column('intent', sa.String(30), nullable=True),
        sa.Column('tokens_used', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.TIMESTAMPTZ(), server_default=sa.text('NOW()')),
    )
    op.create_index('idx_voice_turns_session_turn', 'voice_turns',
                    ['session_id', 'turn_number'], unique=True)
    op.create_index('idx_voice_turns_session', 'voice_turns', ['session_id'])
    op.create_foreign_key('fk_voice_turns_session', 'voice_turns', 'voice_sessions',
                          ['session_id'], ['id'],
                          ondelete='CASCADE')

    # === 3. voice_analytics 表（聚合表，定时任务写入） ===
    op.create_table(
        'voice_analytics',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text('gen_random_uuid()')),
        sa.Column('date', sa.Date(), nullable=False),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('intent', sa.String(30), nullable=False),
        sa.Column('total_queries', sa.Integer(), server_default='0'),
        sa.Column('avg_confidence', sa.Float(), nullable=True),
        sa.Column('unclear_rate', sa.Float(), nullable=True),
        sa.Column('avg_processing_ms', sa.Float(), nullable=True),
        sa.Column('helpful_rate', sa.Float(), nullable=True),
        sa.Column('tts_hit_rate', sa.Float(), nullable=True),
        sa.Column('asr_error_rate', sa.Float(), nullable=True),
        sa.Column('created_at', sa.TIMESTAMPTZ(), server_default=sa.text('NOW()')),
        sa.Column('updated_at', sa.TIMESTAMPTZ(), server_default=sa.text('NOW()')),
    )
    op.create_index('idx_voice_analytics_unique', 'voice_analytics',
                    ['date', 'user_id', 'intent'], unique=True)
    op.create_index('idx_voice_analytics_date', 'voice_analytics', ['date'])
    op.create_foreign_key('fk_voice_analytics_user', 'voice_analytics', 'users',
                          ['user_id'], ['id'])


def downgrade():
    # 按依赖顺序逆序删除
    op.drop_constraint('fk_voice_analytics_user', 'voice_analytics', type_='foreignkey')
    op.drop_index('idx_voice_analytics_date', table_name='voice_analytics')
    op.drop_index('idx_voice_analytics_unique', table_name='voice_analytics')
    op.drop_table('voice_analytics')

    op.drop_constraint('fk_voice_turns_session', 'voice_turns', type_='foreignkey')
    op.drop_index('idx_voice_turns_session', table_name='voice_turns')
    op.drop_index('idx_voice_turns_session_turn', table_name='voice_turns')
    op.drop_table('voice_turns')

    op.drop_constraint('fk_voice_sessions_user', 'voice_sessions', type_='foreignkey')
    op.drop_index('idx_voice_sessions_created', table_name='voice_sessions')
    op.drop_index('idx_voice_sessions_intent', table_name='voice_sessions')
    op.drop_index('idx_voice_sessions_user_created', table_name='voice_sessions')
    op.drop_table('voice_sessions')
```

**SQLite兼容说明（POC阶段）**:

| PostgreSQL类型 | SQLite替代 | 说明 |
|---------------|-----------|------|
| `UUID` | `TEXT` | 存储UUID字符串 |
| `JSONB` | `TEXT` | 存储JSON格式文本，应用层解析 |
| `INET` | `VARCHAR(45)` | IPv4/IPv6地址字符串 |
| `TIMESTAMPTZ` | `TEXT` | ISO8601格式时间戳 |
| `gen_random_uuid()` | 应用层生成 | Python `uuid.uuid4()` |
| `CASCADE`外键 | 应用层级联 | ORM delete cascade |
| `GIN索引` | 不支持 | JSON查询走全表扫描（POC数据量可接受） |

**迁移验证清单**:
| 验证项 | 方法 | 预期结果 |
|--------|------|---------|
| voice_sessions表创建 | `\d voice_sessions` | 18个字段，3个索引，1个FK→users |
| voice_turns表创建 | `\d voice_turns` | 9个字段，2个索引（含UNIQUE），1个FK→voice_sessions(CASCADE) |
| voice_analytics表创建 | `\d voice_analytics` | 12个字段，2个索引（含UNIQUE），1个FK→users |
| 外键级联删除 | 删除voice_session后查voice_turns | 关联turns自动清除 |
| 聚合表唯一约束 | INSERT重复date+user_id+intent | ON CONFLICT DO UPDATE生效 |
| 回滚可用性 | `alembic downgrade -1` 后检查 | 3张表全部移除，无残留 |

---

## 6. 性能优化

### 6.1 查询优化

**EXPLAIN ANALYZE 示例**:
```sql
-- 分析查询计划
EXPLAIN ANALYZE
SELECT e.*, a.assoc_type, a.confidence
FROM entities e
JOIN associations a ON (a.source_entity_id = e.id OR a.target_entity_id = e.id)
WHERE e.user_id = '...'
  AND a.confidence >= 0.7
ORDER BY a.confidence DESC
LIMIT 10;
```

**优化建议**:
1. 避免OR条件（改用UNION）
2. 使用部分索引（WHERE confidence >= 0.7）
3. 限制JOIN表数量（≤3张）

### 6.2 JSONB查询优化

**GIN索引创建**:
```sql
CREATE INDEX idx_entities_properties_gin 
  ON entities USING GIN(properties jsonb_path_ops);
```

**高效JSONB查询**:
```sql
-- ✅ 使用GIN索引
SELECT * FROM entities 
WHERE properties @> '{"industry": "人工智能"}';

-- ❌ 无法使用索引
SELECT * FROM entities 
WHERE properties->>'industry' = '人工智能';
```

### 6.3 分区策略（生产优化）

**按时间分区（事件表）**:
```sql
-- 按月分区
CREATE TABLE events_2026_06 PARTITION OF events
FOR VALUES FROM ('2026-06-01') TO ('2026-07-01');

CREATE TABLE events_2026_07 PARTITION OF events
FOR VALUES FROM ('2026-07-01') TO ('2026-08-01');
```

---

## 7. 数据安全

### 7.1 敏感字段加密

**字段级加密（AES-256-GCM）**:
```sql
-- 使用pgcrypto扩展
CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- 加密存储
INSERT INTO entities (name, properties)
VALUES (
  'John Doe',
  jsonb_set(
    '{}',
    '{encrypted_phone}',
    to_jsonb(pgp_sym_encrypt('13812345678', 'encryption_key'))
  )
);

-- 解密查询
SELECT 
  name,
  pgp_sym_decrypt(properties->'encrypted_phone'::bytea, 'encryption_key') as phone
FROM entities;
```

### 7.2 数据隔离（单用户）

> **设计决策**: PromiseLink定位为AI驱动的**个人商务关系经营助手**，明确排除RBAC、多租户和团队协作。数据隔离通过应用层user_id过滤实现，不使用数据库行级安全（RLS）。

**应用层过滤原则**:
1. 所有查询必须携带`user_id`条件
2. 不依赖数据库RLS策略，由应用层保证数据隔离
3. 单用户场景下，user_id在应用启动时确定，贯穿整个会话

**应用层过滤实现（Python示例）**:

```python
from uuid import UUID
from typing import Optional

class DataIsolation:
    """单用户数据隔离 — 应用层过滤"""
    
    def __init__(self, current_user_id: UUID):
        self.user_id = current_user_id
    
    def filter_query(self, base_query: str) -> str:
        """为查询添加user_id过滤条件"""
        # 简单实现：在WHERE子句中追加user_id条件
        if "WHERE" in base_query.upper():
            return f"{base_query} AND user_id = :user_id"
        else:
            return f"{base_query} WHERE user_id = :user_id"
    
    def get_query_params(self) -> dict:
        """返回查询参数中的user_id"""
        return {"user_id": self.user_id}


# === 使用示例 ===

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

async def get_user_events(
    session: AsyncSession, 
    user_id: UUID,
    limit: int = 20
):
    """获取用户的事件列表 — 应用层过滤"""
    stmt = (
        select(Event)
        .where(Event.user_id == user_id)          # 必须：user_id过滤
        .order_by(Event.timestamp.desc())
        .limit(limit)
    )
    result = await session.execute(stmt)
    return result.scalars().all()


async def get_user_todos(
    session: AsyncSession,
    user_id: UUID,
    status: Optional[str] = None
):
    """获取用户的Todo列表 — 应用层过滤"""
    stmt = select(Todo).where(Todo.user_id == user_id)  # 必须：user_id过滤
    if status:
        stmt = stmt.where(Todo.status == status)
    stmt = stmt.order_by(Todo.priority.desc(), Todo.created_at.asc())
    result = await session.execute(stmt)
    return result.scalars().all()


async def get_entity_with_associations(
    session: AsyncSession,
    user_id: UUID,
    entity_id: UUID
):
    """获取实体及其关联 — 应用层过滤（关联表也需要过滤）"""
    stmt = (
        select(Entity)
        .where(Entity.id == entity_id, Entity.user_id == user_id)  # 实体过滤
    )
    entity = (await session.execute(stmt)).scalar_one_or_none()
    
    if not entity:
        return None
    
    assoc_stmt = (
        select(Association)
        .where(Association.user_id == user_id)                     # 关联也要过滤
        .where(
            (Association.source_entity_id == entity_id) |
            (Association.target_entity_id == entity_id)
        )
    )
    associations = (await session.execute(assoc_stmt)).scalars().all()
    
    return {"entity": entity, "associations": associations}
```

**过滤检查清单**:
| 操作 | 过滤要求 | 示例 |
|------|---------|------|
| SELECT | WHERE user_id = ? | `SELECT * FROM events WHERE user_id = ?` |
| INSERT | 设置user_id字段 | `INSERT INTO events (..., user_id) VALUES (..., ?)` |
| UPDATE | WHERE user_id = ? | `UPDATE todos SET status = ? WHERE id = ? AND user_id = ?` |
| DELETE | WHERE user_id = ? | `DELETE FROM entities WHERE id = ? AND user_id = ?` |

### 7.3 数据主权

> **核心原则**: 用户对自己的所有数据拥有完全控制权。PromiseLink作为个人商务关系经营助手，数据主权是不可妥协的底线。

**数据所有权声明**:
1. 用户创建的所有数据（事件、实体、关联、待办）归用户所有
2. 任何数据收集、处理、存储行为必须透明可追溯
3. 用户有权随时导出、删除自己的全部数据
4. 删除操作为硬删除（非软删除），确保数据彻底清除

**数据导出方案**:

```python
import json
from uuid import UUID
from datetime import datetime
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

async def export_user_data(session: AsyncSession, user_id: UUID) -> dict:
    """导出用户全部数据为JSON格式"""
    
    # 1. 导出事件
    events_stmt = select(Event).where(Event.user_id == user_id)
    events = (await session.execute(events_stmt)).scalars().all()
    
    # 2. 导出实体
    entities_stmt = select(Entity).where(Entity.user_id == user_id)
    entities = (await session.execute(entities_stmt)).scalars().all()
    
    # 3. 导出关联
    associations_stmt = select(Association).where(Association.user_id == user_id)
    associations = (await session.execute(associations_stmt)).scalars().all()
    
    # 4. 导出待办
    todos_stmt = select(Todo).where(Todo.user_id == user_id)
    todos = (await session.execute(todos_stmt)).scalars().all()
    
    # 5. 导出用户信息
    user_stmt = select(User).where(User.id == user_id)
    user = (await session.execute(user_stmt)).scalar_one()
    
    return {
        "export_version": "1.0",
        "exported_at": datetime.utcnow().isoformat(),
        "user": {
            "username": user.username,
            "email": user.email,
            "preferences": user.preferences,
            "created_at": user.created_at.isoformat()
        },
        "events": [e.__dict__ for e in events],
        "entities": [e.__dict__ for e in entities],
        "associations": [a.__dict__ for a in associations],
        "todos": [t.__dict__ for t in todos],
        "summary": {
            "total_events": len(events),
            "total_entities": len(entities),
            "total_associations": len(associations),
            "total_todos": len(todos)
        }
    }
```

**数据删除方案（硬删除+关联清理）**:

```sql
-- ============================================================
-- 数据删除方案：硬删除，按依赖顺序执行
-- 注意：必须在事务中执行，确保原子性
-- ============================================================

BEGIN;

-- 1. 删除待办（依赖实体和事件）
DELETE FROM todos WHERE user_id = :user_id;

-- 2. 删除关联（依赖实体）
DELETE FROM associations WHERE user_id = :user_id;

-- 3. 删除实体（独立表，但被todos和associations引用）
DELETE FROM entities WHERE user_id = :user_id;

-- 4. 删除事件（独立表，但被todos引用）
DELETE FROM events WHERE user_id = :user_id;

-- 5. 删除用户（最后删除，确保关联数据已清理）
DELETE FROM users WHERE id = :user_id;

COMMIT;

-- ============================================================
-- 验证删除结果
-- ============================================================
SELECT 'events' as table_name, COUNT(*) as remaining 
  FROM events WHERE user_id = :user_id
UNION ALL
SELECT 'entities', COUNT(*) 
  FROM entities WHERE user_id = :user_id
UNION ALL
SELECT 'associations', COUNT(*) 
  FROM associations WHERE user_id = :user_id
UNION ALL
SELECT 'todos', COUNT(*) 
  FROM todos WHERE user_id = :user_id;
-- 期望结果：所有表 remaining = 0
```

**删除安全措施**:
| 措施 | 说明 |
|------|------|
| 事务保证 | 所有删除操作在单个事务中执行，失败则回滚 |
| 依赖顺序 | 按外键依赖顺序删除：todos → associations → entities → events → users |
| 删除前确认 | 应用层要求用户二次确认（输入用户名确认） |
| 删除前备份 | 自动触发数据导出，保存为JSON文件后再执行删除 |
| 审计记录 | 删除操作记录到应用日志（不含数据内容，仅记录操作时间和用户ID） |

---

## 8. 备份与恢复

### 8.1 备份策略

**每日全量备份**:
```bash
#!/bin/bash
# scripts/backup.sh
DATE=$(date +%Y%m%d)
pg_dump -U promiselink promiselink_prod | gzip > backup_${DATE}.sql.gz

# 保留最近7天
find backup_*.sql.gz -mtime +7 -delete
```

**实时增量备份（WAL归档）**:
```bash
# postgresql.conf
wal_level = replica
archive_mode = on
archive_command = 'cp %p /backup/wal_archive/%f'
```

### 8.2 恢复演练

**恢复到指定时间点**:
```bash
# 1. 停止服务
systemctl stop promiselink

# 2. 恢复基础备份
gunzip -c backup_20260602.sql.gz | psql -U promiselink promiselink_prod

# 3. 应用WAL日志
pg_waldump /backup/wal_archive/* | psql -U promiselink promiselink_prod

# 4. 启动服务
systemctl start promiselink
```

---

## 9. 监控指标

### 9.1 关键指标

| 指标 | 阈值 | 监控方法 |
|------|------|---------|
| 查询响应时间P95 | <200ms | pg_stat_statements |
| 表大小增长率 | <100MB/day | pg_total_relation_size() |
| 索引使用率 | >80% | pg_stat_user_indexes |
| 缓存命中率 | >95% | pg_stat_database |
| 慢查询数量 | <10/day | log_min_duration_statement=1000 |

### 9.2 监控查询

```sql
-- 慢查询TOP 10
SELECT 
  query, 
  calls, 
  mean_exec_time, 
  total_exec_time
FROM pg_stat_statements
ORDER BY mean_exec_time DESC
LIMIT 10;

-- 表大小TOP 5
SELECT 
  schemaname, 
  tablename, 
  pg_size_pretty(pg_total_relation_size(schemaname||'.'||tablename)) as size
FROM pg_tables
WHERE schemaname = 'public'
ORDER BY pg_total_relation_size(schemaname||'.'||tablename) DESC
LIMIT 5;
```

### 9.X vector_embeddings 表（v2.7 新增, F-57）

> **用途**: 存储Entity/Event的向量嵌入，供SemanticSearchEngine进行语义搜索

```sql
CREATE TABLE vector_embeddings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    target_type TEXT NOT NULL,          -- 'entity' | 'event'
    target_id TEXT NOT NULL,            -- 对应entity.id或event.id
    user_id TEXT NOT NULL,              -- 数据归属用户
    embedding BLOB NOT NULL,            -- API模式768维(3072字节)/本地降级384维(1536字节)float32向量
    source_text TEXT,                   -- 生成embedding的原始文本（用于缓存校验）
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(target_type, target_id)      -- 每个目标仅一条embedding
);

-- 按用户+类型查询索引（语义搜索核心查询路径）
CREATE INDEX idx_vec_user_type ON vector_embeddings(user_id, target_type);

-- 按更新时间索引（增量重建用）
CREATE INDEX idx_vec_updated ON vector_embeddings(updated_at);
```

**字段说明**:

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | INTEGER | PK AUTOINCREMENT | 自增主键 |
| target_type | TEXT | NOT NULL | 目标类型：'entity'或'event' |
| target_id | TEXT | NOT NULL | 目标ID，关联entities.id或events.id |
| user_id | TEXT | NOT NULL | 数据归属用户ID（数据隔离） |
| embedding | BLOB | NOT NULL | API模式768维(3072字节)/本地降级384维(1536字节)float32向量，使用struct.pack存储 |
| source_text | TEXT | 可选 | 生成embedding的原始文本，用于SHA256缓存校验 |
| created_at | TEXT | NOT NULL DEFAULT | 创建时间 |
| updated_at | TEXT | NOT NULL DEFAULT | 更新时间（增量重建用） |

**BLOB存储格式**:
```python
import struct
# 写入: 动态维度float32 → BLOB（API模式768维=3072字节，本地模式384维=1536字节）
dims = len(embedding)  # 由SemanticSearchEngine._actual_dims动态检测
blob = struct.pack(f"{dims}f", *embedding)
# 读取: BLOB → float32向量
dims = len(blob) // 4
embedding = struct.unpack(f"{dims}f", blob)
```

### 9.Y vec_entities 虚拟表（v2.7 新增, F-57, 可选）

> **用途**: sqlite-vec虚拟表，加速向量相似度搜索。当sqlite-vec扩展不可用时，系统自动降级为Python余弦相似度计算。

```sql
-- 仅当sqlite-vec扩展可用时创建
CREATE VIRTUAL TABLE IF NOT EXISTS vec_entities
USING vec0(
    embedding float[384]    # 基础版/专业版使用本地模型384维（定制版迁移pgvector时改为768维）
);
```

**虚拟表与物理表的关系**:
- `vec_entities` 是内存级虚拟表，不持久化到磁盘
- 应用启动时从 `vector_embeddings` 表加载BLOB数据填充
- 查询使用 `WHERE embedding MATCH ? AND k = ?` 语法
- sqlite-vec不可用时自动降级，不影响功能

**定制版迁移说明**（基础版/专业版无需迁移）：

| 特性 | 基础版/专业版 (SQLite) | 定制版 (PostgreSQL) |
|------|----------------|---------------------|
| 向量列类型 | BLOB（API模式3072字节/本地模式1536字节） | vector(768) (pgvector) |
| 索引 | sqlite-vec虚拟表 | IVFFlat / HNSW索引 |
| 查询 | Python余弦 / sqlite-vec | `<=>` 余弦距离操作符 |
| 存储 | 单文件SQLite | PG独立表空间 |

**定制版迁移DDL**（基础版/专业版无需执行）:
```sql
-- PostgreSQL + pgvector
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE vector_embeddings (
    id SERIAL PRIMARY KEY,
    target_type VARCHAR(20) NOT NULL,
    target_id UUID NOT NULL,
    user_id UUID NOT NULL,
    embedding vector(768) NOT NULL,
    source_text TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(target_type, target_id)
);

CREATE INDEX idx_vec_user_type ON vector_embeddings(user_id, target_type);
CREATE INDEX idx_vec_cosine ON vector_embeddings
    USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);
```

---

## 10. 版本演进

| 版本 | 日期 | 变更 |
|------|------|------|
| v1.0 | 2026-06-02 | 初始版本，4张核心表 |
| v1.1 | 2026-06-03 | Todo类型修正（6种：opportunity/risk/context/action/pending_confirm/resource_maint）；移除RLS改为应用层过滤；添加resource_sensitivity字段；添加莫兰迪色映射；添加数据主权章节；Entities properties结构细化 |
| v1.2 | 2026-06-03 | Todo类型重命名（opportunity→cooperation_signal, context→care, action→promise, pending_confirm→followup, resource_maint→help）；莫兰迪色映射更新；Entities properties新增concern/promise/contribution字段；resource/demand标注Phase2；Todos context按类型分类定义 |
| **v2.0** | **2026-06-04** | **李总v1.2+许总POC反馈融合修订（共识清单D1-1~D1-7）：①新增relationship_briefs关系推进卡表（F-47 P0，20字段+3索引+唯一约束+7阶段枚举）②events表追加input_scope/input_scope_confidence字段及索引（F-44）③todos表追加6字段（action_type/promisor_id/beneficiary_id/confirmation_status/evidence_quote/evidence_event_id）+CHECK约束+枚举说明（F-45）④entities.properties JSONB扩展relationship_stage+完整relationship对象结构（F-48）⑤ER图新增RELATIONSHIP_BRIEFS节点及与EVENTS/ENTITIES关系线⑥新增§5.3 Alembic增量迁移策略（含upgrade/downgrade完整代码+验证清单）⑦参考基线对齐PRD v4.3 + 技术设计v2.5 §3.1** |
| **[0.2.1新增]** | **2026-06-05** | **F-50语音助手数据表（3张）：①voice_sessions语音会话表（18字段+3索引，ASR→NLU→API→NLG→TTS全链路记录，不存原始音频，query_text max500/answer_text max2000，含intent/answer_source枚举说明+slots JSONB结构示例）②voice_turns多轮对话轮次表（9字段+唯一约束+CASCADE外键，Phase 1.2启用标注，含role/turn_type枚举说明）③voice_analytics分析聚合表（12字段+唯一约束，定时任务聚合写入，含UPSERT聚合SQL示例）④ER图新增VOICE_SESSIONS/VOICE_TURNS/VOICE_ANALYTICS三节点及users→sessions/sessions→turns/sessions→entities关系线⑤§5.4新增Alembic迁移代码（upgrade/downgrade完整实现+SQLite兼容映射表+6项验证清单）⑥版本保持0.2.0不变（增量更新）** |
| **v2.5** | **2026-06-06** | **Insight Engine + DataSourceAdapter 数据库变更：①todos表新增3字段：completed_rank(完成序号/隐式反馈)、dynamic_score(动态优先级分)、score_calculated_at(评分时间)，含2个CHECK约束(check_dynamic_score_range/check_score_timestamp_valid)和2个索引(idx_todos_dynamic_score/idx_todos_completed_rank)②新增score_audit_logs评分审计日志表（7字段+2索引，triggered_by枚举3值，calculation_factors JSONB结构）③新增adapter_configs数据源适配器配置表（6字段+CHECK约束+唯一约束，adapter_name枚举5值，config_encrypted BYTEA加密存储）④entities.properties JSONB新增concerns/capabilities结构化字段（{tag,detail,source_event_id}格式，无需DDL变更）** |
| **v2.6** | **2026-06-06** | **F-55/F-56 评分审计扩展：①score_audit_logs.calculation_factors JSONB结构扩展，新增dependency_score/context_score/dependency_raw/context_raw字段，用于审计依赖性全图谱路径分析(F-55)和场景匹配Event表驱动(F-56)的计算因子②todos表确认已有dynamic_score/score_calculated_at/completed_rank字段（F-51/F-52已加），无需新增DDL变更③Phase1启用四维模型后审计日志将完整记录四维得分及原始计算因子** |
| **v2.7** | **2026-06-06** | **F-57/F-58 语义搜索与关联发现增强：①新增vector_embeddings表（8字段+2索引+唯一约束，target_type枚举entity/event，embedding BLOB存储API模式768维/本地降级384维float32向量，source_text用于缓存校验，user_id数据隔离）②新增vec_entities虚拟表（sqlite-vec vec0扩展，embedding float[384]（PoC本地模型），可选创建，不可用时Python余弦降级）③Phase2迁移DDL（PostgreSQL+pgvector，vector(768)列类型+IVFFlat索引）** |
| **v2.8** | **2026-06-07** | **F-08/F-21/F-36/F-39/EmailAdapter/WeChatForwardAdapter 数据库变更：①events表event_type枚举扩展新增'email'和'wechat_forward'（无需DDL变更，VARCHAR(20)足够）②events表source枚举扩展新增'csv_import'/'email'/'wechat_forward'（无需DDL变更）③todos表properties JSONB新增resource_overuse子类型结构（risk_type/target_entity_id/request_count/window_days/severity，无需DDL变更）④ER图EVENTS节点event_type注释更新** |
| **v2.9** | **2026-06-11** | **F-68/F-69 承诺兑现追踪与智能提醒引擎：①todos表新增3字段：fulfillment_status(承诺兑现状态pending/fulfilled/overdue/expired, CHECK约束)、fulfilled_at(兑现时间)、overdue_notified_at(逾期通知时间)（F-68）②fulfillment_status与status正交说明：status为任务执行状态，fulfillment_status为承诺兑现语义，仅action_type为promise/their_promise的Todo有fulfillment_status语义（F-68）③新增reminder_preferences提醒偏好表（6字段，user_id主键，preferred_times JSONB偏好时间列表，fatigue_threshold疲劳阈值，quiet_hours免打扰时段）（F-69）④新增reminder_logs提醒日志表（7字段+1索引，reminder_type枚举4值promise_due/followup/stage_suggestion/dormant_contact，action_taken枚举4值completed/snoozed/dismissed/ignored，response_latency_seconds响应延迟）（F-69）⑤ER图新增REMINDER_PREFERENCES/REMINDER_LOGS节点及关系线⑥score_audit_logs表新增score_version字段（VARCHAR(20)，评分模型版本poc_v1/phase1_v1）⑦新增calculated_by字段（VARCHAR(50)，计算器标识PriorityScorer/PriorityScorerV2）⑧triggered_by枚举新增scorer_update值⑨主键改为INTEGER AUTOINCREMENT（SQLite兼容）⑩标记实现状态为已实现** |
| **v3.0** | **2026-06-11** | **三级产品模型重构：①数据库策略重构为三级产品模型（基础版SQLite/专业版SQLite+网关中继/定制版PG+Redis）②Phase1→专业版、Phase2→定制版全量术语替换③新增relay_connections网关中继连接表（6字段+3索引，专业版使用，WebSocket连接管理+心跳检测）④新增ai_usage_logs AI用量日志表（6字段+2索引，专业版/定制版使用，10种action_type枚举，token消耗+成本记录）⑤ER图新增RELAY_CONNECTIONS/AI_USAGE_LOGS节点及关系线⑥resource/demand字段标注从Phase2更新为定制版⑦SQLite确认为基础版+专业版长期方案，PG/Redis仅定制版** |
| v2.1 | TBD | 添加用户反馈表 |

---

*最后更新: 2026-06-11*
