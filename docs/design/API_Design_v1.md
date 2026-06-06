# EventLink API设计文档

> **版本**: 0.2.7 (POC阶段)
> **日期**: 2026-06-06
> **阶段**: POC (0.2.x series)
> **设计师**: 架构师 + 开发团队
> **参考**: PRD v4.3, 技术设计 v2.7 §7
> **v2.6变更**: Insight Engine API新增priority-breakdown/upcoming-context端点(§3.13)、Todo schema新增dependency_raw/context_raw字段
> **v2.7变更**: 新增§3.15 Semantic Search API（3个端点+SearchResult schema, F-57/F-58）

---

## 1. API设计原则

### 1.1 RESTful风格
- **资源导向**: URL表示资源，HTTP方法表示操作
- **无状态**: 每个请求包含完整的身份验证信息
- **统一接口**: 标准HTTP方法（GET/POST/PATCH/DELETE）
- **HATEOAS**: 响应中包含相关资源链接

### 1.2 版本管理
- **URL版本号**: `/api/v1/...`
- **向后兼容**: 新版本不破坏旧版本
- **废弃策略**: 提前6个月通知废弃，保留2个版本

### 1.3 性能要求
- **响应时间**: P95 < 200ms
- **并发支持**: 100 QPS（PoC阶段）
- **限流策略**: 单用户100次/分钟

---

## 2. 认证与授权

### 2.1 临时授权码模式（小程序→H5）

```mermaid
sequenceDiagram
    participant MP as 小程序
    participant API as EventLink API
    participant H5 as H5页面
    
    MP->>API: POST /api/v1/auth/ticket<br/>{action, person_id}
    API-->>MP: {code: "xxx", expires_in: 60}
    MP->>H5: 打开WebView<br/>?ticket=xxx
    H5->>API: POST /api/v1/auth/exchange<br/>{ticket: "xxx"}
    API-->>H5: {access_token, refresh_token}
    H5->>H5: 保存token到sessionStorage
```

#### 2.1.1 生成授权码

**端点**: `POST /api/v1/auth/ticket`

**请求**:
```json
{
  "action": "view_person",
  "person_id": "uuid-of-person",
  "user_id": "uuid-of-user"
}
```

**响应**:
```json
{
  "code": "T_AbCdEf12345",
  "expires_in": 60,
  "created_at": "2026-06-02T10:00:00Z"
}
```

**说明**:
- Ticket存储在Redis，60秒有效
- 单次使用（exchange后自动删除）

#### 2.1.2 交换Token

**端点**: `POST /api/v1/auth/exchange`

**请求**:
```json
{
  "ticket": "T_AbCdEf12345"
}
```

**响应**:
```json
{
  "access_token": "eyJhbGc...",
  "refresh_token": "eyJhbGc...",
  "token_type": "Bearer",
  "expires_in": 900,
  "user_id": "uuid"
}
```

**JWT Payload**:
```json
{
  "user_id": "uuid",
  "exp": 1622620800,
  "iat": 1622619900,
  "iss": "eventlink"
}
```

### 2.2 JWT认证（v2.0安全加固）

**Header格式**:
```http
Authorization: Bearer eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9...
```

**Token格式**: `Bearer <JWT>`
**签名算法**: HS256（cryptography库）

**Payload结构**:
```json
{
  "sub": "user_id (UUID)",
  "iat": 1622619900,
  "exp": 1622706300,
  "role": "user"
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| `sub` | string (UUID) | 用户唯一标识，对应 user_id |
| `iat` | integer | 签发时间（Unix时间戳） |
| `exp` | integer | 过期时间（Unix时间戳，默认24小时） |
| `role` | string | 角色标识（预留扩展，当前固定为 `"user"`） |

**安全约束（4项）**:

| # | 约束 | 说明 | 实现要求 |
|---|------|------|---------|
| SC-JWT-1 | Secret Key ≥ 256位 | 签名密钥必须为≥256位随机值 | 启动时校验非默认值，否则拒绝启动 |
| SC-JWT-2 | Token黑名单机制 | 登出/吊销的Token立即失效 | 写入Redis，TTL = token剩余有效期 |
| SC-JWT-3 | Refresh Token旋转 | 每次刷新生成新token对，旧token立即失效 | 防止token重放攻击 |
| SC-JWT-4 | CORS白名单 | 跨域请求仅允许配置的Origin列表 | **禁止使用 `*` 通配符** |

**Token刷新**: `POST /api/v1/auth/refresh`

---

## 3. 核心API端点

### 3.1 Events API

#### 3.1.1 创建事件

**端点**: `POST /api/v1/events`

**请求**:
```json
{
  "event_type": "card_save",
  "source": "iamhere",
  "title": "扫描张三名片",
  "timestamp": "2026-06-02T10:00:00Z",
  "raw_text": "张三\nCEO\nAI公司\n13812345678",
  "input_scope": "auto",
  "metadata": {
    "card_image_url": "https://...",
    "language": "zh-CN"
  }
}
```

**字段说明**:
- `event_type`: 事件类型（必填）
- `source`: 来源（可选）
- `title`: 标题（必填）
- `timestamp`: 时间戳（必填，ISO 8601）
- `raw_text`: 原始文本（必填）
- `input_scope`: 输入分类（可选，v2.0新增）。仅接受 `"auto"` 或不传。传 `"auto"` 时服务端调用 InputClassifier 自动分类；不传时同 auto 行为。传入其他值返回 `400 INVALID_INPUT_SCOPE`。**安全约束 SC-01**：永远不以客户端传入值作为最终 scope，服务端始终以 classify() 结果为准。
- `metadata`: 元数据（可选）

**错误响应 — input_scope 非法值**: `400 Bad Request`
```json
{
  "error": {
    "code": "E1004",
    "message": "无效的 input_scope 值",
    "details": {
      "provided_value": "invalid_scope",
      "valid_values": ["auto"],
      "hint": "仅接受 'auto' 或不传该字段"
    }
  }
}
```

**响应**: `201 Created`
```json
{
  "id": "event-uuid",
  "event_type": "card_save",
  "status": "processing",
  "created_at": "2026-06-02T10:00:01Z",
  "estimated_completion": "2026-06-02T10:00:03Z"
}
```

#### 3.1.2 查询事件

**端点**: `GET /api/v1/events/{id}`

**响应**: `200 OK`
```json
{
  "id": "event-uuid",
  "event_type": "card_save",
  "title": "扫描张三名片",
  "timestamp": "2026-06-02T10:00:00Z",
  "raw_text": "...",
  "metadata": {},
  "extracted_entities": [
    {
      "entity_id": "entity-uuid",
      "entity_type": "person",
      "name": "张三",
      "confidence": 0.95
    }
  ],
  "created_at": "2026-06-02T10:00:01Z"
}
```

---

### 3.2 Entities API

#### 3.2.1 搜索实体

**端点**: `GET /api/v1/entities`

**查询参数**:
- `q`: 搜索关键词
- `type`: 实体类型筛选
- `sensitivity`: 资源敏感度筛选（matchable|no_match）
- `limit`: 返回数量（默认20）
- `offset`: 分页偏移

**示例**: `GET /api/v1/entities?q=张三&type=person&sensitivity=matchable&limit=10`

**响应**: `200 OK`
```json
{
  "total": 1,
  "items": [
    {
      "id": "entity-uuid",
      "entity_type": "person",
      "name": "张三",
      "company": "AI公司",
      "title": "CEO",
      "resource_sensitivity": "matchable",
      "relationship_stage": "new_connection",
      "properties": {
        "resource": ["AI算法专家"],
        "demand": ["寻找联合创始人"]
      },
      "created_at": "2026-06-01T10:00:00Z",
      "updated_at": "2026-06-02T10:00:00Z"
    }
  ],
  "links": {
    "next": "/api/v1/entities?offset=10&limit=10"
  }
}
```

#### 3.2.2 实体详情（含画像）

**端点**: `GET /api/v1/entities/{id}`

**响应**: `200 OK`
```json
{
  "id": "entity-uuid",
  "entity_type": "person",
  "name": "张三",
  "aliases": ["张三三", "Zhang San"],
  "company": "AI公司",
  "title": "CEO",
  "city": "北京",
  "resource_sensitivity": "matchable",
  "properties": {
    "resource": ["AI算法专家", "有5年CV经验"],
    "demand": ["寻找联合创始人"],
    "profile": {
      "phone": "138****5678",
      "email": "zhangsan@example.com",
      "education": ["清华大学"],
      "industry": "人工智能"
    }
  },
  "associations": [
    {
      "assoc_type": "alumni",
      "target_entity": {
        "id": "uuid",
        "name": "李四"
      },
      "confidence": 0.9
    }
  ],
  "concerns": [
    {
      "id": "concern-uuid",
      "topic": "融资进展",
      "status": "active",
      "source": "manual",
      "created_at": "2026-06-01T10:00:00Z"
    }
  ],
  "promises": [
    {
      "id": "promise-uuid",
      "content": "下周介绍赵六给张三认识",
      "due_at": "2026-06-10T00:00:00Z",
      "status": "pending",
      "created_at": "2026-06-02T10:00:00Z"
    }
  ],
  "contributions": [
    {
      "id": "contribution-uuid",
      "content": "帮助张三对接了AI算法团队",
      "date": "2026-05-20",
      "created_at": "2026-05-20T10:00:00Z"
    }
  ],
  "related_events_count": 5,
  "created_at": "2026-06-01T10:00:00Z",
  "updated_at": "2026-06-02T10:00:00Z",
  "links": {
    "events": "/api/v1/entities/entity-uuid/events",
    "graph": "/api/v1/entities/entity-uuid/graph"
  }
}
```

#### 3.2.3 修正实体信息

**端点**: `PATCH /api/v1/entities/{id}`

**请求**:
```json
{
  "title": "CTO",
  "properties": {
    "profile": {
      "phone": "13912345678"
    }
  }
}
```

**响应**: `200 OK`（返回更新后的实体）

#### 3.2.4 修改资源敏感度

**端点**: `PATCH /api/v1/entities/{id}/sensitivity`

**说明**: 修改实体的资源敏感度标记。敏感度为2级：`matchable`（可参与匹配）和 `no_match`（不参与匹配）。标记为 `no_match` 的实体资源不会出现在资源匹配结果中。

**请求**:
```json
{
  "resource_sensitivity": "no_match"
}
```

**响应**: `200 OK`
```json
{
  "id": "entity-uuid",
  "resource_sensitivity": "no_match",
  "updated_at": "2026-06-03T10:00:00Z"
}
```

**错误响应**: `422 Unprocessable Entity`
```json
{
  "error": {
    "code": "E1003",
    "message": "无效的敏感度值，仅支持 matchable 或 no_match",
    "details": {
      "provided_value": "private"
    }
  }
}
```

#### 3.2.5 添加/确认关注点

**端点**: `PATCH /api/v1/entities/{id}/concern`

**说明**: 为指定实体添加关注点或确认已有关注点。关注点用于记录您对该实体的持续关注领域。

**请求**:
```json
{
  "topic": "融资进展",
  "action": "add",
  "source": "manual"
}
```

**字段说明**:
- `topic`: 关注点主题
- `action`: 操作类型，`add`（添加）或 `confirm`（确认已有关注点）
- `source`: 来源，`manual`（手动添加）或 `llm_infer`（AI推断）

**响应**: `200 OK`
```json
{
  "id": "concern-uuid",
  "entity_id": "entity-uuid",
  "topic": "融资进展",
  "status": "active",
  "source": "manual",
  "created_at": "2026-06-03T10:00:00Z"
}
```

#### 3.2.6 添加/更新承诺

**端点**: `PATCH /api/v1/entities/{id}/promise`

**说明**: 为指定实体添加承诺或更新已有承诺。承诺用于跟踪您对他人许下的约定。

**请求**:
```json
{
  "content": "下周介绍赵六给张三认识",
  "due_at": "2026-06-10T00:00:00Z",
  "action": "add"
}
```

**字段说明**:
- `content`: 承诺内容
- `due_at`: 承诺截止时间（ISO 8601）
- `action`: 操作类型，`add`（添加）或 `update`（更新已有承诺）
- `promise_id`: 更新时需提供已有承诺ID

**响应**: `200 OK`
```json
{
  "id": "promise-uuid",
  "entity_id": "entity-uuid",
  "content": "下周介绍赵六给张三认识",
  "due_at": "2026-06-10T00:00:00Z",
  "status": "pending",
  "created_at": "2026-06-03T10:00:00Z"
}
```

#### 3.2.7 记录帮助

**端点**: `PATCH /api/v1/entities/{id}/contribution`

**说明**: 记录您为指定实体提供的帮助。帮助记录用于追踪人际关系中的付出与贡献。

**请求**:
```json
{
  "content": "帮助张三对接了AI算法团队",
  "date": "2026-05-20"
}
```

**字段说明**:
- `content`: 帮助内容描述
- `date`: 帮助发生日期（ISO 8601 date）

**响应**: `200 OK`
```json
{
  "id": "contribution-uuid",
  "entity_id": "entity-uuid",
  "content": "帮助张三对接了AI算法团队",
  "date": "2026-05-20",
  "created_at": "2026-06-03T10:00:00Z"
}
```

---

### 3.3 Associations API

#### 3.3.1 查询关联

**端点**: `GET /api/v1/associations`

**查询参数**:
- `entity_id`: 实体ID
- `assoc_type`: 关联类型
- `min_confidence`: 最小置信度（默认0.7）

**示例**: `GET /api/v1/associations?entity_id=uuid&min_confidence=0.8`

**响应**: `200 OK`
```json
{
  "total": 3,
  "items": [
    {
      "id": "assoc-uuid",
      "source_entity": {
        "id": "uuid",
        "name": "张三"
      },
      "target_entity": {
        "id": "uuid",
        "name": "李四"
      },
      "assoc_type": "alumni",
      "confidence": 0.9,
      "evidence": {
        "method": "教育背景匹配",
        "matched_fields": ["education"]
      },
      "created_at": "2026-06-02T10:00:00Z"
    }
  ]
}
```

#### 3.3.2 实体关系图谱

**端点**: `GET /api/v1/entities/{id}/graph`

**查询参数**:
- `depth`: 遍历深度（默认2，最大3）
- `min_confidence`: 最小置信度

**响应**: `200 OK`
```json
{
  "nodes": [
    {
      "id": "uuid",
      "name": "张三",
      "entity_type": "person"
    },
    {
      "id": "uuid",
      "name": "李四",
      "entity_type": "person"
    }
  ],
  "edges": [
    {
      "source": "uuid",
      "target": "uuid",
      "assoc_type": "alumni",
      "confidence": 0.9
    }
  ]
}
```

---

### 3.4 Todos API

#### 3.4.1 待办列表

**端点**: `GET /api/v1/todos`

**查询参数**:
- `status`: pending\|in_progress\|done\|dismissed\|snoozed
- `type`: cooperation_signal\|risk\|care\|promise\|followup\|help
- `priority`: high\|medium\|low
- `due_before`: 截止时间筛选（ISO 8601）
- **[v2.5新增] `sort`**: 排序方式（可选）。枚举值：
  - `smart` — （默认）按动态评分(dynamic_score)降序排列，分数高的优先展示
  - `due_date` — 按截止时间升序排列，最紧急的优先
- **[v2.5新增] `view`**: 视图类型（可选，见§3.9.4）
- **[0.2.1更新] `summary_level`**: 摘要级别（可选）。枚举值：
  - `brief` — （默认）标准Todo列表格式，适合Dashboard展示
  - `detail` — 完整信息，包含完整context和关联数据
  - `voice` — 自然语言摘要，适合TTS语音输出。当 `summary_level=voice` 时响应额外返回 `voice_summary` 字段（已格式化的自然语言回答文本）

**Todo类型与莫兰迪色系映射**:

| 类型 | 色系 | 色值 | 描述前缀 | 说明 |
|------|------|------|---------|------|
| cooperation_signal | 雾白 | #B8C4C0 | ⚪ | 合作信号 |
| risk | 烟粉 | #C4A7A0 | 🔴 | 风险预警 |
| care | 雾蓝 | #A0B0C4 | 🔵 | 关注关怀 |
| promise | 雾绿 | #A0C4A8 | 🟢 | 承诺跟踪 |
| followup | 雾金 | #C4C0A0 | 🟡 | 跟进确认 |
| help | 雾紫 | #B0A0C4 | 🟣 | 帮助记录 |

**示例**: `GET /api/v1/todos?status=pending&priority=high`

**响应**: `200 OK`
```json
{
  "total": 6,
  "items": [
    {
      "id": "todo-uuid-1",
      "todo_type": "cooperation_signal",
      "status": "pending",
      "priority": "high",
      "morandi_color": "#B8C4C0",
      "description": "⚪ 合作信号：张三寻找AI算法专家",
      "related_entity": {
        "id": "uuid",
        "name": "张三"
      },
      "context": {
        "match_score": 0.85,
        "reason": "您有AI算法经验，匹配张三的需求"
      },
      "due_date": "2026-06-10T00:00:00Z",
      "completed_rank": null,
      "dynamic_score": 72.5,
      "created_at": "2026-06-03T10:00:00Z"
    },
    {
      "id": "todo-uuid-2",
      "todo_type": "risk",
      "status": "pending",
      "priority": "high",
      "morandi_color": "#C4A7A0",
      "description": "🔴 风险：李四的公司近期融资困难，合作项目可能受影响",
      "related_entity": {
        "id": "uuid",
        "name": "李四"
      },
      "context": {
        "risk_type": "financial",
        "reason": "李四所在公司近期公开报道融资受阻"
      },
      "due_date": "2026-06-05T00:00:00Z",
      "completed_rank": null,
      "dynamic_score": 85.2,
      "created_at": "2026-06-03T10:00:00Z"
    },
    {
      "id": "todo-uuid-3",
      "todo_type": "care",
      "status": "pending",
      "priority": "medium",
      "morandi_color": "#A0B0C4",
      "description": "🔵 关注：王五近期出席了AI行业峰会",
      "related_entity": {
        "id": "uuid",
        "name": "王五"
      },
      "context": {
        "source": "公开活动信息",
        "reason": "王五在AI峰会发表演讲，可能对您的项目有参考价值"
      },
      "due_date": null,
      "completed_rank": null,
      "dynamic_score": 45.8,
      "created_at": "2026-06-03T10:00:00Z"
    },
    {
      "id": "todo-uuid-4",
      "todo_type": "promise",
      "status": "pending",
      "priority": "medium",
      "morandi_color": "#A0C4A8",
      "description": "🟢 承诺：建议联系赵六，介绍给张三",
      "related_entity": {
        "id": "uuid",
        "name": "赵六"
      },
      "context": {
        "action_type": "introduction",
        "reason": "赵六有AI算法团队管理经验，张三正在寻找联合创始人"
      },
      "due_date": "2026-06-08T00:00:00Z",
      "completed_rank": null,
      "dynamic_score": 68.3,
      "created_at": "2026-06-03T10:00:00Z"
    },
    {
      "id": "todo-uuid-5",
      "todo_type": "followup",
      "status": "pending",
      "priority": "medium",
      "morandi_color": "#C4C0A0",
      "description": "🟡 跟进：孙七与周八可能存在合作关系，请确认",
      "related_entity": {
        "id": "uuid",
        "name": "孙七"
      },
      "context": {
        "confirm_type": "association",
        "reason": "根据活动记录，孙七和周八同时出席了3次行业活动，AI推测可能存在合作关系",
        "suggested_action": "确认或否认此关联"
      },
      "due_date": "2026-06-07T00:00:00Z",
      "completed_rank": null,
      "dynamic_score": 52.1,
      "created_at": "2026-06-03T10:00:00Z"
    },
    {
      "id": "todo-uuid-6",
      "todo_type": "help",
      "status": "pending",
      "priority": "low",
      "morandi_color": "#B0A0C4",
      "description": "🟣 帮助：您与吴九已3个月未联系，建议主动问候",
      "related_entity": {
        "id": "uuid",
        "name": "吴九"
      },
      "context": {
        "last_contact": "2026-03-03",
        "gap_days": 92,
        "reason": "长期未联系可能导致关系弱化，建议发送问候或分享行业资讯"
      },
      "due_date": "2026-06-06T00:00:00Z",
      "completed_rank": null,
      "dynamic_score": 30.4,
      "created_at": "2026-06-03T10:00:00Z"
    }
  ]
}
```

> **[0.2.1更新]** 当 `summary_level=voice` 时，响应额外返回 `voice_summary` 字段（已PII脱敏的自然语言摘要文本，可直接用于TTS合成）：
```json
{
  "total": 6,
  "items": [...],
  "voice_summary": "您目前有6项待办需要处理。高优先级的有3项：张三寻找AI算法专家的合作信号、李四公司融资困难的风险预警、以及建议联系赵六介绍给张三的承诺跟踪。此外还有3项中低优先级的事项。"
}
```

#### 3.4.2 更新Todo状态

**端点**: `PATCH /api/v1/todos/{id}`

**请求**:
```json
{
  "status": "in_progress",
  "notes": "已联系张三",
  "action_type": "my_promise",
  "promisor_id": "entity-uuid",
  "beneficiary_id": "entity-uuid"
}
```

**字段说明**（v2.0新增字段）:
- `status`: 目标状态
- `notes`: 备注信息
- `action_type`: 动作类型（可选，v2.0新增）。枚举值：`my_promise`（我的承诺）、`their_promise`（对方承诺）、`help_provided`（已提供帮助）、`care_expression`（关怀表达）、`cooperation_signal`（合作信号）、`followup_needed`（需要跟进）
- `promisor_id`: 承诺人实体ID（可选，v2.0新增，当 action_type 为 promise 类型时使用）
- `beneficiary_id`: 受益人实体ID（可选，v2.0新增，当 action_type 为 promise 类型时使用）

**响应**: `200 OK`（返回更新后的Todo）

#### 3.4.3 Todo反馈闭环

**端点**: `POST /api/v1/todos/{id}/feedback`

**请求**:
```json
{
  "feedback_type": "useful",
  "rating": 5,
  "comment": "非常有帮助，已介绍给张三"
}
```

**响应**: `200 OK`
```json
{
  "message": "感谢反馈，已记录"
}
```

#### 3.4.4 Snooze延迟

**端点**: `POST /api/v1/todos/{id}/snooze`

**请求**:
```json
{
  "snooze_until": "2026-06-10T09:00:00Z"
}
```

**响应**: `200 OK`

#### 3.4.5 Promise类型Todo示例

**说明**: promise类型用于跟踪您对他人许下的承诺，包含截止时间（due_at）和完成备注（completion_note）。

**创建Promise Todo请求**:
```json
{
  "todo_type": "promise",
  "description": "承诺下周介绍赵六给张三认识",
  "priority": "medium",
  "related_entity_id": "entity-uuid",
  "due_at": "2026-06-10T00:00:00Z",
  "context": {
    "promise_content": "介绍赵六给张三认识",
    "made_at": "2026-06-03T10:00:00Z"
  }
}
```

**完成Promise Todo请求**:
```json
{
  "status": "done",
  "completion_note": "已于6月8日安排赵六和张三见面，双方交流愉快"
}
```

**响应**: `200 OK`
```json
{
  "id": "todo-uuid",
  "todo_type": "promise",
  "status": "done",
  "priority": "medium",
  "morandi_color": "#A0C4A8",
  "description": "承诺下周介绍赵六给张三认识",
  "related_entity": {
    "id": "entity-uuid",
    "name": "张三"
  },
  "context": {
    "promise_content": "介绍赵六给张三认识",
    "made_at": "2026-06-03T10:00:00Z"
  },
  "due_at": "2026-06-10T00:00:00Z",
  "completion_note": "已于6月8日安排赵六和张三见面，双方交流愉快",
  "completed_at": "2026-06-08T18:00:00Z",
  "created_at": "2026-06-03T10:00:00Z"
}
```

#### 3.4.6 Care类型Todo示例

**说明**: care类型用于记录对某人的关注关怀事项，包含关注主题（concern_topic）。

**创建Care Todo请求**:
```json
{
  "todo_type": "care",
  "description": "关注王五的融资进展",
  "priority": "medium",
  "related_entity_id": "entity-uuid",
  "context": {
    "concern_topic": "融资进展",
    "source": "公开活动信息",
    "reason": "王五在AI峰会发表演讲，可能对您的项目有参考价值"
  }
}
```

**响应**: `200 OK`
```json
{
  "id": "todo-uuid",
  "todo_type": "care",
  "status": "pending",
  "priority": "medium",
  "morandi_color": "#A0B0C4",
  "description": "关注王五的融资进展",
  "related_entity": {
    "id": "entity-uuid",
    "name": "王五"
  },
  "context": {
    "concern_topic": "融资进展",
    "source": "公开活动信息",
    "reason": "王五在AI峰会发表演讲，可能对您的项目有参考价值"
  },
  "due_date": null,
  "created_at": "2026-06-03T10:00:00Z"
}
```

#### 3.4.7 Cooperation Signal类型Todo示例

**说明**: cooperation_signal类型用于发现潜在的合作机会信号，由AI自动识别或手动创建。

**创建Cooperation Signal Todo请求**:
```json
{
  "todo_type": "cooperation_signal",
  "description": "合作信号：张三寻找AI算法专家",
  "priority": "high",
  "related_entity_id": "entity-uuid",
  "context": {
    "match_score": 0.85,
    "signal_type": "demand_supply_match",
    "reason": "您有AI算法经验，匹配张三的需求"
  }
}
```

**响应**: `200 OK`
```json
{
  "id": "todo-uuid",
  "todo_type": "cooperation_signal",
  "status": "pending",
  "priority": "high",
  "morandi_color": "#B8C4C0",
  "description": "合作信号：张三寻找AI算法专家",
  "related_entity": {
    "id": "entity-uuid",
    "name": "张三"
  },
  "context": {
    "match_score": 0.85,
    "signal_type": "demand_supply_match",
    "reason": "您有AI算法经验，匹配张三的需求"
  },
  "due_date": "2026-06-10T00:00:00Z",
  "created_at": "2026-06-03T10:00:00Z"
}
```

---

### 3.5 Digest API（摘要）

#### 3.5.1 早晨简报

**端点**: `GET /api/v1/digest/morning`

**响应**: `200 OK`
```json
{
  "date": "2026-06-02",
  "sections": [
    {
      "title": "今日要见的人",
      "items": [
        {
          "entity_id": "uuid",
          "name": "张三",
          "meeting_time": "10:00",
          "briefing": "AI公司CEO，寻找联合创始人"
        }
      ]
    },
    {
      "title": "待办提醒",
      "items": [
        {
          "todo_id": "uuid",
          "description": "联系李四介绍给张三"
        }
      ]
    }
  ]
}
```

#### 3.5.2 晚间总结

**端点**: `GET /api/v1/digest/evening`

**响应**: `200 OK`
```json
{
  "date": "2026-06-02",
  "summary": {
    "events_processed": 5,
    "new_entities": 3,
    "new_associations": 8,
    "new_todos": 2,
    "completed_todos": 1
  },
  "highlights": [
    {
      "type": "new_cooperation_signal",
      "description": "发现张三和李四都在寻找AI人才"
    }
  ]
}
```

---

### 3.6 Mini Program API（小程序专用）

#### 3.6.1 今日会议

**端点**: `GET /api/v1/mini/today`

**响应**: `200 OK`
```json
{
  "date": "2026-06-02",
  "meetings": [
    {
      "time": "10:00",
      "person": {
        "id": "uuid",
        "name": "张三",
        "company": "AI公司",
        "title": "CEO",
        "avatar_url": "https://..."
      },
      "briefing": "AI公司CEO，清华校友，寻找联合创始人"
    }
  ]
}
```

#### 3.6.2 人物速览

**端点**: `GET /api/v1/mini/person/{id}`

**响应**: `200 OK`
```json
{
  "id": "uuid",
  "name": "张三",
  "company": "AI公司",
  "title": "CEO",
  "key_points": [
    "清华校友（2010届）",
    "寻找AI算法联合创始人",
    "有5年CV经验"
  ],
  "associations_summary": "2个校友，1个前同事",
  "last_contact": "2026-06-01"
}
```

#### 3.6.3 TTS语音播报

**端点**: `GET /api/v1/mini/person/{id}/tts`

**查询参数**:
- `voice`: 语音风格（默认female_neutral）

**响应**: `200 OK`（音频流）
```
Content-Type: audio/mpeg
Content-Length: 45678
```

#### 3.6.4 语音录入

**端点**: `POST /api/v1/mini/voice-input`

**请求**: `multipart/form-data`
```
audio: <audio file>
language: zh-CN
```

**响应**: `201 Created`
```json
{
  "event_id": "uuid",
  "transcription": "今天见了张三，讨论了AI合作",
  "status": "processing"
}
```

---

### 3.7 Resources API（资源管理）

> **⚠️ F-05 暂停声明（Phase 2）**: 商机匹配相关API在 Phase 1 暂不实现。以下端点标记为 **Phase 2**：
> - `GET /api/v1/resources/match` — 资源匹配查询（单边匹配+六维加权评分算法）
> - 商机匹配度五维算法（keyword/industry/topic/llm/history/callability）
>
> **原因**: Phase 1 聚焦"关系经营闭环"核心能力（关系推进卡、Dashboard、日视图），资源匹配作为 Phase 2 深度整合能力延后。
> **替代方案**: Phase 1 使用简化的 PromiseFulfillmentEngine（承诺兑现闭环）替代完整八维匹配。

> **定位**: 资源管理是AI驱动的个人商务关系经营助手的核心能力，支持单边匹配——"我的需求匹配我人脉的供给"。

#### 3.7.1 查看实体资源列表

**端点**: `GET /api/v1/entities/{id}/resources`

**说明**: 查看指定实体的资源标签列表，包括该实体拥有的资源（resource）和需求（demand）。

**响应**: `200 OK`
```json
{
  "entity_id": "entity-uuid",
  "entity_name": "张三",
  "resources": [
    {
      "id": "resource-uuid-1",
      "type": "resource",
      "tag": "AI算法专家",
      "callability": "high",
      "source": "manual",
      "created_at": "2026-06-01T10:00:00Z"
    },
    {
      "id": "resource-uuid-2",
      "type": "resource",
      "tag": "有5年CV经验",
      "callability": "medium",
      "source": "llm_extract",
      "created_at": "2026-06-01T10:00:00Z"
    },
    {
      "id": "resource-uuid-3",
      "type": "demand",
      "tag": "寻找联合创始人",
      "callability": "high",
      "source": "manual",
      "created_at": "2026-06-01T10:00:00Z"
    }
  ],
  "total": 3
}
```

#### 3.7.2 添加资源标签

**端点**: `POST /api/v1/entities/{id}/resources`

**说明**: 为指定实体添加资源标签。可标记为 resource（供给）或 demand（需求），并设置可调用度（callability）。

**请求**:
```json
{
  "type": "resource",
  "tag": "GPU算力资源",
  "callability": "high",
  "source": "manual"
}
```

**字段说明**:
- `type`: 资源方向，`resource`（供给）或 `demand`（需求）
- `tag`: 资源标签描述
- `callability`: 可调用度，`high`/`medium`/`low`，表示该资源的可触达程度
- `source`: 来源，`manual`（手动添加）或 `llm_extract`（AI提取）

**响应**: `201 Created`
```json
{
  "id": "resource-uuid-new",
  "entity_id": "entity-uuid",
  "type": "resource",
  "tag": "GPU算力资源",
  "callability": "high",
  "source": "manual",
  "created_at": "2026-06-03T10:00:00Z"
}
```

#### 3.7.3 删除资源标签

**端点**: `DELETE /api/v1/entities/{id}/resources/{resource_id}`

**说明**: 删除指定实体的某个资源标签。

**响应**: `204 No Content`

**错误响应**: `404 Not Found`
```json
{
  "error": {
    "code": "E1001",
    "message": "资源标签不存在",
    "details": {
      "resource_id": "resource-uuid"
    }
  }
}
```

#### 3.7.4 资源匹配查询

**端点**: `GET /api/v1/resources/match`

**说明**: 单边资源匹配——查询"我的需求"匹配"我人脉的供给"。匹配算法采用六维加权评分：

| 维度 | 权重 | 说明 |
|------|------|------|
| keyword | 25% | 关键词语义匹配 |
| industry | 20% | 行业领域匹配 |
| topic | 15% | 话题/技术方向匹配 |
| llm | 10% | LLM深度语义理解匹配 |
| history | 10% | 历史交互记录匹配 |
| callability | 20% | 资源可调用度评分 |

**查询参数**:
- `demand_tag`: 需求标签关键词（必填）
- `min_score`: 最低匹配分数（默认0.5，范围0-1）
- `limit`: 返回数量（默认20）
- `offset`: 分页偏移

**示例**: `GET /api/v1/resources/match?demand_tag=AI算法专家&min_score=0.6&limit=10`

**响应**: `200 OK`
```json
{
  "demand_tag": "AI算法专家",
  "total": 3,
  "items": [
    {
      "entity": {
        "id": "entity-uuid",
        "name": "李四",
        "company": "算法科技",
        "title": "CTO"
      },
      "matched_resource": {
        "id": "resource-uuid",
        "tag": "AI算法团队管理",
        "type": "resource",
        "callability": "high"
      },
      "match_score": 0.87,
      "score_breakdown": {
        "keyword": 0.22,
        "industry": 0.18,
        "topic": 0.13,
        "llm": 0.08,
        "history": 0.06,
        "callability": 0.20
      },
      "match_reason": "李四在AI算法领域有深厚背景，且可调用度高，与您的需求高度匹配"
    },
    {
      "entity": {
        "id": "entity-uuid-2",
        "name": "王五",
        "company": "数据智能",
        "title": "技术总监"
      },
      "matched_resource": {
        "id": "resource-uuid-2",
        "tag": "CV算法研究",
        "type": "resource",
        "callability": "medium"
      },
      "match_score": 0.72,
      "score_breakdown": {
        "keyword": 0.18,
        "industry": 0.15,
        "topic": 0.12,
        "llm": 0.07,
        "history": 0.05,
        "callability": 0.15
      },
      "match_reason": "王五在CV算法方向有研究经验，可调用度中等"
    }
  ]
}
```

**注意**: 匹配结果仅包含 `resource_sensitivity` 为 `matchable` 的实体资源，`no_match` 的实体不会出现在匹配结果中。

---

### 3.8 AI输出语言规则

> **定位**: 所有LLM生成的响应必须遵循统一的语言规则，确保用户能清晰区分AI推断与事实，并对敏感结论保持审慎。

#### 3.8.1 规则概述

所有LLM生成的API响应必须包含以下三个标记字段：

| 字段 | 类型 | 说明 |
|------|------|------|
| `confidence_level` | string | 置信度等级：`high`/`medium`/`low` |
| `is_ai_inference` | boolean | 是否为AI推测内容 |
| `requires_confirmation` | boolean | 是否需要用户确认（敏感结论必标） |

#### 3.8.2 置信度等级定义

| 等级 | 含义 | 适用场景 |
|------|------|---------|
| `high` | 高置信度 | 基于明确数据源的事实性结论 |
| `medium` | 中置信度 | 基于部分证据的合理推断 |
| `low` | 低置信度 | 基于弱信号的推测性结论 |

#### 3.8.3 敏感结论判定规则

以下场景的AI输出必须标记 `requires_confirmation: true`：
- 资源敏感度判定（`resource_sensitivity`）
- 关联关系推断（`associations`中confidence < 0.8的项）
- 合作信号识别（`cooperation_signal`类型Todo）
- 风险预警（`risk`类型Todo）

#### 3.8.4 响应示例

**AI推断的关联关系**:
```json
{
  "assoc_type": "alumni",
  "target_entity": {
    "id": "uuid",
    "name": "李四"
  },
  "confidence": 0.75,
  "confidence_level": "medium",
  "is_ai_inference": true,
  "requires_confirmation": true,
  "evidence": {
    "method": "教育背景匹配",
    "matched_fields": ["education"]
  }
}
```

**AI推断的合作信号Todo**:
```json
{
  "id": "todo-uuid",
  "todo_type": "cooperation_signal",
  "status": "pending",
  "priority": "high",
  "morandi_color": "#B8C4C0",
  "description": "合作信号：张三寻找AI算法专家",
  "related_entity": {
    "id": "uuid",
    "name": "张三"
  },
  "context": {
    "match_score": 0.85,
    "signal_type": "demand_supply_match",
    "reason": "您有AI算法经验，匹配张三的需求"
  },
  "confidence_level": "high",
  "is_ai_inference": true,
  "requires_confirmation": true,
  "due_date": "2026-06-10T00:00:00Z",
  "created_at": "2026-06-03T10:00:00Z"
}
```

**事实性实体信息（非AI推断）**:
```json
{
  "id": "entity-uuid",
  "entity_type": "person",
  "name": "张三",
  "company": "AI公司",
  "title": "CEO",
  "confidence_level": "high",
  "is_ai_inference": false,
  "requires_confirmation": false
}
```

---

### 3.9 Dashboard & 关系推进卡 API（v2.0新增，P0端点）

> **定位**: v2.3/v2.4 新增的P0核心端点，支撑关系经营闭环。

#### 3.9.1 获取关系推进卡

**端点**: `GET /api/v1/persons/{id}/relationship-brief`

**说明**: 获取指定人物的关系推进卡，包含当前阶段、关注点、洞察、贡献、待兑现承诺、反馈记录等12模块信息。**PII脱敏**：返回前对 evidence_quote 等文本字段执行 `redact_pii_from_text()` 处理。

**路径参数**:
- `id`: 人物实体ID（UUID）

**[0.2.1更新] 查询参数**:
- `summary_level`: 摘要级别（可选）。枚举值：
  - `brief` — （默认）完整12模块详情，适合关系推进卡页面展示
  - `detail` — 扩展信息，包含更多历史交互数据
  - `voice` — 自然语言摘要，适合TTS语音输出。当 `summary_level=voice` 时响应额外返回 `voice_summary` 字段

**响应**: `200 OK`
```json
{
  "id": "brief-uuid",
  "person_id": "entity-uuid",
  "person_name": "张三",
  "current_stage": "understanding_needs",
  "stage_reason": "已识别对方关注点：融资进展",
  "confirmed_by_user": false,
  "latest_interaction": {
    "event_id": "event-uuid",
    "timestamp": "2026-06-03T14:00:00Z",
    "summary": "讨论了AI算法合作方向"
  },
  "next_node": "了解对方关心什么",
  "next_node_condition": "已识别对方至少1个关注点",
  "concerns": [
    {
      "topic": "融资进展",
      "status": "active",
      "source": "manual"
    }
  ],
  "need_insights": [
    {
      "insight": "对方正在寻找联合创始人",
      "confidence_level": "medium",
      "is_ai_inference": true,
      "requires_confirmation": true
    }
  ],
  "contributions": [
    {
      "content": "帮助对接了AI算法团队",
      "date": "2026-05-20"
    }
  ],
  "pending_promises": [
    {
      "content": "下周介绍赵六给张三认识",
      "due_at": "2026-06-10T00:00:00Z",
      "status": "pending"
    }
  ],
  "feedback_records": [],
  "cooperation_direction_candidate": null,
  "version": 3,
  "created_at": "2026-06-01T10:00:00Z",
  "updated_at": "2026-06-04T12:00:00Z",
  "voice_summary": "张总目前处于了解需求阶段。您最近一次交流是6月3日，讨论了AI算法合作方向。张总当前关注融资进展，正在寻找联合创始人。您已帮助对接了AI算法团队。还有一个待兑现承诺：下周介绍赵六给张总认识，截止日期是6月10日。"
}
```

> **[0.2.1更新]** `voice_summary` 字段仅在 `summary_level=voice` 时返回，为已PII脱敏的自然语言摘要文本，可直接用于TTS合成。

#### 3.9.2 用户确认阶段变更（含乐观锁）

**端点**: `PATCH /api/v1/persons/{id}/relationship-brief/stage`

**说明**: 用户主动确认关系阶段变更。使用乐观锁（version 字段）防止并发冲突。**RS-01硬编码规则**：关系阶段不可仅由AI自动升级，必须用户确认。

**请求**:
```json
{
  "stage": "value_response",
  "reason": "已向对方提供了有价值的行业报告",
  "version": 3
}
```

**字段说明**:
- `stage`: 目标阶段（必填）。7阶段枚举：
  - `new_connection` — 新认识
  - `understanding_needs` — 了解需求
  - `value_response` — 价值回应
  - `cooperation_exploration` — 合作探索
  - `intent_confirmed` — 意向确认
  - `execution` — 执行合作
  - `review` — 复盘回顾（终态）
- `reason`: 变更原因（可选）
- `version`: 乐观锁版本号（必填）。客户端读取 relationship-brief 时携带的 version 值

**合法的阶段转换规则**:

| 当前阶段 | 可转换到 |
|---------|---------|
| new_connection | understanding_needs |
| understanding_needs | value_response, new_connection |
| value_response | cooperation_exploration, understanding_needs |
| cooperation_exploration | intent_confirmed, value_response |
| intent_confirmed | execution, cooperation_exploration |
| execution | review, intent_confirmed |
| review | —（终态） |

**响应**: `200 OK`
```json
{
  "id": "brief-uuid",
  "current_stage": "value_response",
  "previous_stage": "understanding_needs",
  "stage_reason": "已向对方提供了有价值的行业报告",
  "confirmed_by_user": true,
  "version": 4,
  "updated_at": "2026-06-04T15:00:00Z"
}
```

**错误响应 — 乐观锁冲突**: `409 Conflict`
```json
{
  "error": {
    "code": "E1005",
    "error_type": "OPTIMISTIC_LOCK_CONFLICT",
    "message": "关系推进卡已被其他请求更新，请刷新后重试",
    "details": {
      "current_version": 5,
      "client_version": 3,
      "hint": "请重新获取最新 relationship-brief 后重试"
    },
    "timestamp": "2026-06-04T15:00:01Z",
    "request_id": "req-uuid"
  }
}
```

**错误响应 — 非法阶段转换**: `422 Unprocessable Entity`
```json
{
  "error": {
    "code": "E1003",
    "message": "不允许从 new_connection 转移到 execution",
    "details": {
      "from_stage": "new_connection",
      "to_stage": "execution",
      "allowed_targets": ["understanding_needs"]
    }
  }
}
```

#### 3.9.3 今日Dashboard

**端点**: `GET /api/v1/dashboard/today`

**说明**: 获取今日Dashboard概览，聚焦"需要回应的连接"——包含今日会议、待处理Todo、需要跟进的人物等关键信息。

**响应**: `200 OK`
```json
{
  "date": "2026-06-04",
  "summary": {
    "total_meetings": 3,
    "pending_todos": 7,
    "connections_need_response": 2
  },
  "meetings": [
    {
      "time": "09:00-10:30",
      "title": "供应链优化方案讨论",
      "participants": [
        {"entity_id": "uuid", "name": "张总", "avatar": null}
      ],
      "todo_count": 2,
      "key_topics": ["供应链", "成本优化"]
    }
  ],
  "pending_todos": [
    {
      "id": "todo-uuid",
      "todo_type": "promise",
      "description": "承诺：建议联系赵六，介绍给张三",
      "related_entity_name": "赵六",
      "due_date": "2026-06-05T00:00:00Z",
      "morandi_color": "#A0C4A8"
    }
  ],
  "connections_need_response": [
    {
      "entity_id": "uuid",
      "name": "李四",
      "relationship_stage": "cooperation_exploration",
      "last_interaction": "2026-06-02",
      "suggested_action": "确认合作方向是否明确"
    }
  ]
}
```

#### 3.9.4 我的待回应任务视图

**端点**: `GET /api/v1/todos?view=my-responses`

**说明**: 扩展 Todo 列表查询参数，支持 `view` 视图筛选。`my-responses` 视图返回需要用户主动回应的任务（如等待对方回应的 followup、需要确认的合作信号等）。

**新增查询参数**:
- `view`: 视图类型（可选，v2.0新增）
  - `all` — 默认，返回所有Todo（向后兼容）
  - `my-responses` — 我的待回应任务（含等待对方回应视图）
  - `waiting-their-response` — 仅显示等待对方回应的任务

**示例**: `GET /api/v1/todos?view=my-responses&status=pending&priority=high`

**响应**: `200 OK`（格式与现有 TodoList 一致，items 按 urgency 排序）

---

### 3.10 记录贡献与反馈 API（v2.0新增）

#### 3.10.1 记录已提供的帮助/回应

**端点**: `POST /api/v1/contributions`

**说明**: 独立记录为他人提供的帮助或做出的回应。与 PATCH `/entities/{id}/contribution` 的区别在于：本端点为独立创建，不依赖已有实体上下文；同时会自动关联到对应人物的关系推进卡的 contributions 数组中。

**请求**:
```json
{
  "target_entity_id": "entity-uuid",
  "content": "帮助张三对接了AI算法团队",
  "contribution_type": "help_provided",
  "date": "2026-05-20",
  "related_event_id": "event-uuid"
}
```

**字段说明**:
- `target_entity_id`: 目标人物实体ID（必填）
- `content`: 帮助/回应内容描述（必填）
- `contribution_type`: 类型（可选）。枚举：`help_provided`（提供帮助）、`response_made`（做出回应）、`resource_shared`（共享资源）、`introduction_made`（引荐介绍）
- `date`: 发生日期（可选，ISO 8601 date，默认当天）
- `related_event_id`: 关联事件ID（可选）

**响应**: `201 Created`
```json
{
  "id": "contribution-uuid",
  "user_id": "user-uuid",
  "target_entity_id": "entity-uuid",
  "target_entity_name": "张三",
  "content": "帮助张三对接了AI算法团队",
  "contribution_type": "help_provided",
  "date": "2026-05-20",
  "related_event_id": "event-uuid",
  "created_at": "2026-06-04T10:00:00Z"
}
```

#### 3.10.2 记录反馈与下一步

**端点**: `POST /api/v1/feedbacks`

**说明**: 记录对某次互动/合作的反馈及规划下一步行动。反馈会写入对应关系推进卡的 feedback_records 数组中，并可能触发新的 Todo 生成。

**请求**:
```json
{
  "target_entity_id": "entity-uuid",
  "feedback_type": "positive",
  "rating": 5,
  "comment": "交流很有价值，双方在AI算法方向高度互补",
  "next_steps": [
    {
      "action": "schedule_followup",
      "description": "安排下一次深度交流",
      "due_date": "2026-06-15"
    }
  ],
  "related_event_id": "event-uuid"
}
```

**字段说明**:
- `target_entity_id`: 目标人物实体ID（必填）
- `feedback_type`: 反馈类型（必填）。枚举：`positive`（正面）、`neutral`（中性）、`negative`（负面）、`needs_attention`（需关注）
- `rating`: 评分（可选，1-5分）
- `comment`: 反馈内容（可选）
- `next_steps`: 下一步行动列表（可选）
  - `action`: 行动类型。枚举：`schedule_followup`（安排跟进）、`send_resource`（发送资源）、`make_introduction`（做引荐）、`update_stage`（更新阶段）
  - `description`: 行动描述
  - `due_date`: 计划日期（ISO 8601 date）
- `related_event_id`: 关联事件ID（可选）

**响应**: `201 Created`
```json
{
  "id": "feedback-uuid",
  "target_entity_id": "entity-uuid",
  "target_entity_name": "张三",
  "feedback_type": "positive",
  "rating": 5,
  "comment": "交流很有价值，双方在AI算法方向高度互补",
  "next_steps": [
    {
      "action": "schedule_followup",
      "description": "安排下一次深度交流",
      "due_date": "2026-06-15"
    }
  ],
  "generated_todos": [
    {
      "id": "todo-uuid",
      "todo_type": "followup",
      "description": "🟡 跟进：安排与张三的下次深度交流"
    }
  ],
  "created_at": "2026-06-04T10:00:00Z"
}
```

---

### 3.11 日视图API（F-49, Phase 1, v2.0新增）

**端点**: `GET /api/v1/dashboard/day-view?date=YYYY-MM-DD`

**说明**: 按日期聚合展示当日所有会议分组、参与人、关联Todo和关键词摘要。用于日历视图和时间线展示。

**查询参数**:
- `date`: 查询日期（必填，格式 YYYY-MM-DD，默认今天）
- **[0.2.1更新] `summary_level`**: 摘要级别（可选）。枚举值：
  - `brief` — （默认）一句话摘要，适合Dashboard卡片展示
  - `detail` — 完整列表，适合日历详情页
  - `voice` — 自然语言段落，适合TTS语音输出。当 `summary_level=voice` 时响应额外返回 `answer_paragraph` 字段（已格式化的自然语言回答文本）
- **[0.2.1更新] `natural_date`**: 自然语言日期（可选）。NLU解析后的自然语言日期表达，服务端转为具体date值。枚举值：`"今天"` | `"明天"` | `"后天"` | `"本周"` | `"下周"`

**响应**: `200 OK`
```json
{
  "date": "2026-06-04",
  "meeting_groups": [
    {
      "event_id": "event-uuid-1",
      "title": "供应链优化方案讨论",
      "time": "09:00-10:30",
      "participants": [
        {"entity_id": "uuid", "name": "张总", "avatar": null},
        {"entity_id": "uuid", "name": "李总", "avatar": null}
      ],
      "todo_count": 2,
      "key_topics": ["供应链", "成本优化"]
    },
    {
      "event_id": "event-uuid-2",
      "title": "AI算法合作方向探讨",
      "time": "14:00-15:30",
      "participants": [
        {"entity_id": "uuid", "name": "王五", "avatar": null}
      ],
      "todo_count": 1,
      "key_topics": ["AI算法", "联合创始人"]
    }
  ],
  "total_meetings": 4,
  "total_pending_todos": 7,
  "answer_paragraph": "您今天一共有4场会议。上午9点到10点半，您和张总、李总讨论供应链优化方案；下午2点到3点半，和王五探讨AI算法合作方向。此外您还有7项待办需要处理。"
}
```

> **[0.2.1更新]** `answer_paragraph` 字段仅在 `summary_level=voice` 时返回，为已PII脱敏的自然语言段落文本，可直接用于TTS合成。

**实现要点**:
- events 表按 `user_id + date(timestamp)` GROUP BY
- 每个 event 关联 entities（通过 event_entities 中间表或 properties）
- 每个 event 关联 todos（通过 event_id 外键）
- key_topics 从 `event.title` + LLM 抽取的 topics 中获取
- 复用现有 PaginatedResponse 格式

---

### 3.12 Voice Assistant API（F-50, Phase 1.1, v0.2.1新增）

> **[F-50新增] 定位**: 语音问答交互层，接收ASR识别后的文本，经NLU意图识别后调用对应业务API，返回自然语言答案+预生成TTS音频URL。Phase 1.1为一次性会话模式（无多轮对话）。
> **关键约束**: 不存储原始音频；TTS输出需PII脱敏（复用 `redact_pii_from_text()`）；所有端点需JWT认证。

#### 3.12.1 NLU意图枚举定义

> **[F-50新增]** 语音助手支持的自然语言理解（NLU）意图类型，按优先级分阶段交付。

```python
class VoiceIntent(str, Enum):
    # Phase 1.1 核心 (P0)
    SCHEDULE_QUERY = "schedule_query"          # 日程查询("今天有什么会")
    PROMISE_TRACKER = "promise_tracker"        # 承诺追踪("我答应谁什么还没做")
    RELATIONSHIP_STATUS = "relationship_status" # 关系推进("张总到哪步了")

    # Phase 1.2 扩展 (P1)
    SCHEDULE_RANGE = "schedule_range"          # 范围日程("明后天有什么安排")
    ACTION_SUGGESTION = "action_suggestion"    # 行动建议("该联系谁")

    # Phase 2 (P2)
    CONVERSATION_REVIEW = "conversation_review" # 交流回顾("聊了什么主题")
    KNOWLEDGE_RETRIEVAL = "knowledge_retrieval" # 知识检索("物流方面的新知识")

    # 系统级
    UNCLEAR = "unclear"                        # 无法识别
```

**意图与业务API映射**:

| 意图 | 调用API | summary_level |
|------|---------|---------------|
| `schedule_query` | `GET /api/v1/dashboard/day-view?summary_level=voice` | voice |
| `promise_tracker` | `GET /api/v1/todos?todo_type=promise&status=pending&summary_level=voice` | voice |
| `relationship_status` | `GET /api/v1/persons/{id}/relationship-brief?summary_level=voice` | voice |

#### 3.12.2 Voice Session 数据模型

> **[F-50新增]** 语音会话的请求/响应数据结构定义。

**VoiceSessionCreate — 请求体**:

```python
class VoiceSessionCreate(BaseModel):
    query_text: str = Field(..., min_length=1, max_length=500, description="ASR识别后的文字")
    asr_confidence: float = Field(None, ge=0.0, le=1.0, description="ASR置信度")
    voice_input: bool = Field(True, description="标记来源为语音")
    client_timestamp: datetime = Field(..., description="客户端时间戳(ISO 8601)")
```

**VoiceSessionResponse — 响应体**:

```python
class VoiceSessionResponse(BaseModel):
    session_id: str = Field(..., description="会话唯一标识")
    intent: VoiceIntent = Field(..., description="NLU识别的意图")
    intent_confidence: float = Field(..., ge=0.0, le=1.0, description="意图识别置信度")
    answer_text: str = Field(..., description="自然语言回答文本(已PII脱敏)")
    tts_url: Optional[str] = Field(None, description="预生成的TTS音频URL")
    source_data: dict = Field(..., description="原始数据引用(用于前端展示详情)")
    processing_time_ms: int = Field(..., description="服务端处理耗时(ms)")
    suggest_questions: Optional[List[str]] = Field(None, description="当intent=unclear时提供建议问题")
```

#### 3.12.3 创建语音问答会话

**[F-50新增] 端点**: `POST /api/v1/voice/session`

**说明**: 创建一次性语音问答会话。接收ASR识别后的文本，执行NLU意图识别，调用对应业务API获取数据，生成自然语言回答并预生成TTS音频。

**请求**:
```json
{
  "query_text": "我今天的会议是什么",
  "asr_confidence": 0.95,
  "voice_input": true,
  "client_timestamp": "2026-06-05T10:30:00Z"
}
```

**字段说明**:
- `query_text`: ASR识别后的文字（必填，1-500字符）
- `asr_confidence`: ASR引擎返回的置信度（可选，0.0-1.0）
- `voice_input`: 标记来源为语音（可选，默认true）
- `client_timestamp`: 客户端发起请求的时间戳（必填，ISO 8601）

**响应**: `200 OK`
```json
{
  "session_id": "sess_abc123",
  "intent": "schedule_query",
  "intent_confidence": 0.92,
  "answer_text": "您今天有2场会议。下午2点和张总讨论项目进度，下午4点参加周会。",
  "tts_url": "/api/v1/voice/tts/sess_abc123.mp3",
  "source_data": {
    "type": "day_view",
    "date": "2026-06-05",
    "event_count": 2
  },
  "processing_time_ms": 1850
}
```

**响应 — NLU无法识别意图 (422)**:
```json
{
  "session_id": "sess_def456",
  "intent": "unclear",
  "intent_confidence": 0.35,
  "answer_text": "抱歉，我没有完全理解您的意思。您可以试试问我以下问题：",
  "tts_url": "/api/v1/voice/tts/sess_def456.mp3",
  "source_data": null,
  "processing_time_ms": 420,
  "suggest_questions": [
    "我今天有什么会议？",
    "我答应过谁什么事情？",
    "张总的关系到哪一步了？"
  ]
}
```

**错误响应**:

| HTTP状态码 | 错误码 | 场景 |
|-----------|--------|------|
| 400 | E1000 | query_text为空或超长 |
| 401 | E2000 | 未提供JWT Token或Token无效 |
| 422 | E1003 | NLU无法识别意图（返回suggest_questions） |

**处理流程**:

```
1. 接收 ASR 文本 → 校验 query_text 非空
2. NLU 意图识别 → 提取 intent + entities (日期/人名)
3. 根据 intent 调用对应业务API (带 summary_level=voice)
4. LLM 生成自然语言回答 → PII脱敏 (redact_pii_from_text)
5. TTS 引擎生成音频 → 存储到临时缓存 (TTL=5分钟)
6. 返回 session_id + answer_text + tts_url + source_data
```

#### 3.12.4 获取TTS音频

**[F-50新增] 端点**: `GET /api/v1/voice/tts/{session_id}`

**说明**: 获取指定语音会话预生成的TTS音频文件（MP3格式）。音频文件在服务端临时缓存，5分钟后自动清理。

**路径参数**:
- `session_id`: 语音会话ID（由 POST /voice/session 返回）

**响应**: `200 OK`
```
Content-Type: audio/mpeg
Content-Length: 45678
Cache-Control: private, max-age=300
```

**响应体**: MP3二进制音频流

**错误响应**:

| HTTP状态码 | 场景 |
|-----------|------|
| 401 | 未认证 |
| 404 | session_id不存在或TTS音频已过期(TTL=5分钟) |

**安全约束**:
- 需要JWT认证（防止未授权访问音频内容）
- Cache-Control设为private（不经过共享缓存）
- 音频文件不持久化存储，TTL过期后自动删除

#### 3.12.5 语音回答质量反馈

**[F-50新增] 端点**: `POST /api/v1/voice/feedback`

**说明**: 用户对语音回答的质量反馈，用于NLU模型持续优化和答案质量监控。

**请求**:
```json
{
  "session_id": "sess_abc123",
  "rating": "helpful",
  "comment": "回答对了但太长了"
}
```

**字段说明**:
- `session_id`: 语音会话ID（必填）
- `rating`: 反馈评级（必填）。枚举值：
  - `helpful` — 有帮助
  - `not_helpful` — 没有帮助
  - `wrong_intent` — 意图识别错误
  - `unclear` — 回答不清晰
- `comment`: 补充说明（可选，最大200字符）

**响应**: `200 OK`
```json
{
  "message": "感谢反馈，已记录",
  "session_id": "sess_abc123"
}
```

**错误响应**:

| HTTP状态码 | 错误码 | 场景 |
|-----------|--------|------|
| 400 | E1000 | 缺少session_id或rating |
| 401 | E2000 | 未认证 |
| 404 | E1001 | session_id不存在 |

---

### 3.13 Insight Engine API（v2.5 新增）

> **定位**: Insight Engine 将 Todo 从"被动记录"升级为"主动服务"，基于动态优先级评分和隐式反馈驱动用户注意力。

#### 3.13.1 按动态评分排序的 Todo 列表

**端点**: `GET /api/v1/todos?sort=smart`

**说明**: 按动态评分(dynamic_score)降序排列返回 Todo 列表，分数高的优先展示。这是默认排序方式。

**认证**: Bearer Token

**限流**: 100次/分钟（统一限流）

**查询参数**: 同 §3.4.1，额外支持 `sort=smart`（默认）

**响应**: 同 §3.4.1 Todo 列表格式，items 按 dynamic_score DESC 排序

**示例**: `GET /api/v1/todos?sort=smart&status=pending`

#### 3.13.2 按截止时间排序的 Todo 列表

**端点**: `GET /api/v1/todos?sort=due_date`

**说明**: 按截止时间升序排列，最紧急的优先。无截止日期的 Todo 排在最后。

**认证**: Bearer Token

**限流**: 100次/分钟

**查询参数**: 同 §3.4.1，`sort=due_date`

**响应**: 同 §3.4.1 Todo 列表格式，items 按 due_date ASC 排序（NULL 排最后）

**示例**: `GET /api/v1/todos?sort=due_date&status=pending`

#### 3.13.3 触发优先级重新计算

**端点**: `POST /api/v1/insights/calculate`

**说明**: 手动触发所有 Todo 的动态优先级分数重新计算。适用于用户修改了关系推进卡信息后希望立即看到分数变化。

**认证**: Bearer Token

**限流**: 10次/分钟（计算密集型，独立限流）

**请求**:
```json
{
  "scope": "all",
  "reason": "manual_recalc"
}
```

**字段说明**:
- `scope`: 计算范围（可选，默认 `all`）。枚举值：
  - `all` — 重新计算所有 Todo
  - `entity` — 仅重新计算指定人物的 Todo（需提供 `entity_id`）
  - `overdue` — 仅重新计算已过期的 Todo
- `entity_id`: 人物实体ID（可选，当 scope=entity 时必填）
- `reason`: 触发原因（可选，默认 `manual_recalc`）

**响应**: `200 OK`
```json
{
  "calculated_count": 28,
  "updated_count": 12,
  "scope": "all",
  "triggered_by": "manual_recalc",
  "calculation_time_ms": 450,
  "score_changes": [
    {
      "todo_id": "todo-uuid",
      "old_score": 65.3,
      "new_score": 72.5,
      "factors": {
        "urgency": 0.85,
        "importance": 0.72
      }
    }
  ]
}
```

**错误码**:

| HTTP状态码 | 错误码 | 场景 |
|-----------|--------|------|
| 401 | E2000 | 未认证 |
| 422 | E1003 | scope=entity 但未提供 entity_id |
| 429 | E3000 | 超过限流（10次/分钟） |

#### 3.13.4 获取隐式反馈统计

**端点**: `GET /api/v1/insights/feedback-stats`

**说明**: 获取隐式反馈的统计数据，包括完成顺序分布、权重调整历史、每日再平衡结果等。

**认证**: Bearer Token

**限流**: 100次/分钟

**查询参数**:
- `period`: 统计周期（可选，默认 `7d`）。枚举值：`1d` / `7d` / `30d`
- `entity_id`: 筛选指定人物（可选）

**示例**: `GET /api/v1/insights/feedback-stats?period=7d`

**响应**: `200 OK`
```json
{
  "period": "7d",
  "total_completions": 45,
  "rank_distribution": {
    "top3": 12,
    "top10": 28,
    "beyond10": 5
  },
  "entity_weight_changes": [
    {
      "entity_id": "entity-uuid",
      "entity_name": "张三",
      "old_weight": 0.50,
      "current_weight": 0.62,
      "weight_delta": +0.12,
      "completion_count": 8
    }
  ],
  "daily_rebalance_results": [
    {
      "date": "2026-06-05",
      "entities_updated": 5,
      "avg_weight_change": 0.03
    }
  ],
  "negative_feedback_count": 2,
  "cold_attention_entities": []
}
```

**错误码**:

| HTTP状态码 | 错误码 | 场景 |
|-----------|--------|------|
| 401 | E2000 | 未认证 |
| 404 | E1001 | entity_id 不存在 |

#### 3.13.5 获取Todo优先级评分详情（v2.6 新增, F-55/F-56）

**端点**: `GET /api/v1/todos/{todo_id}/priority-breakdown`

**说明**: 返回指定Todo的四维评分详情（urgency/importance/dependency/context），包含每个维度的原始得分和计算因子。用于前端展示"为什么这个Todo排在前面"的可解释性面板。

**认证**: Bearer Token

**限流**: 100次/分钟

**路径参数**:
- `todo_id`: Todo ID（UUID）

**响应**: `200 OK`
```json
{
  "todo_id": "todo-uuid",
  "dynamic_score": 72.5,
  "score_calculated_at": "2026-06-06T10:00:00Z",
  "phase": "phase1",
  "weights": {
    "urgency": 0.30,
    "importance": 0.35,
    "dependency": 0.20,
    "context_match": 0.15
  },
  "breakdown": {
    "urgency": {
      "score": 0.85,
      "raw": {
        "days_until_due": 1,
        "lambda": 0.1,
        "formula": "exp(-λ × days_until_due)"
      }
    },
    "importance": {
      "score": 0.72,
      "raw": {
        "brief_score": 72,
        "formula": "brief_score / 100"
      }
    },
    "dependency": {
      "score": 0.45,
      "raw": {
        "depth_weight_sum": 1.5,
        "blocked_count": 2,
        "block_weight": 0.3,
        "max_depth": 3,
        "formula": "Σ(1/depth) × min(1.0, blocked_count × 0.3)"
      }
    },
    "context": {
      "score": 0.917,
      "raw": {
        "entity_id": "entity-uuid",
        "hours_until": 2.0,
        "window_hours": 24,
        "matched_event": {
          "event_title": "供应链优化方案讨论",
          "nearest_meeting_at": "2026-06-06T14:00:00Z"
        },
        "formula": "max(0, 1 - hours_until / 24)"
      }
    }
  }
}
```

> **PoC阶段说明**: PoC阶段 dependency 和 context 维度未启用，对应 score 固定为 0.0，raw 返回 `{"reason": "not_enabled_in_poc"}`。

**错误码**:

| HTTP状态码 | 错误码 | 场景 |
|-----------|--------|------|
| 401 | E2000 | 未认证 |
| 404 | E1001 | todo_id 不存在 |

#### 3.13.6 获取即将见面的Entity及关联Todo（v2.6 新增, F-56）

**端点**: `GET /api/v1/users/{user_id}/upcoming-context`

**说明**: 返回未来24h即将见面的Entity列表及每个Entity关联的待办Todo。用于"会前准备"场景——用户在会议前快速查看与该人物相关的所有待办事项。

**认证**: Bearer Token

**限流**: 100次/分钟

**路径参数**:
- `user_id`: 用户ID（UUID）

**查询参数**:
- `hours`: 时间窗口（可选，默认24，范围1-72）

**示例**: `GET /api/v1/users/{user_id}/upcoming-context?hours=24`

**响应**: `200 OK`
```json
{
  "user_id": "user-uuid",
  "window_hours": 24,
  "upcoming_meetings": [
    {
      "event_id": "event-uuid-1",
      "event_title": "供应链优化方案讨论",
      "event_type": "meeting",
      "meeting_at": "2026-06-06T14:00:00Z",
      "hours_until": 2.5,
      "entities": [
        {
          "entity_id": "entity-uuid",
          "entity_name": "张三",
          "company": "AI公司",
          "title": "CEO",
          "relationship_stage": "understanding_needs",
          "related_todos": [
            {
              "todo_id": "todo-uuid-1",
              "todo_type": "promise",
              "description": "承诺下周介绍赵六给张三认识",
              "status": "pending",
              "priority": "medium",
              "due_date": "2026-06-08T00:00:00Z",
              "dynamic_score": 72.5,
              "morandi_color": "#A0C4A8"
            },
            {
              "todo_id": "todo-uuid-2",
              "todo_type": "followup",
              "description": "跟进：张三的融资进展",
              "status": "pending",
              "priority": "low",
              "due_date": null,
              "dynamic_score": 45.2,
              "morandi_color": "#C4C0A0"
            }
          ]
        }
      ]
    }
  ],
  "total_meetings": 3,
  "total_todos": 7,
  "generated_at": "2026-06-06T11:30:00Z"
}
```

**错误码**:

| HTTP状态码 | 错误码 | 场景 |
|-----------|--------|------|
| 401 | E2000 | 未认证 |
| 404 | E1001 | user_id 不存在 |

---

### 3.14 DataSourceAdapter API（v2.5 新增）

> **定位**: 多数据源适配器管理接口，支持用户配置和同步不同来源的数据（微信转发、邮件、日历等）。

#### 3.14.1 列出已配置的数据源

**端点**: `GET /api/v1/adapters`

**说明**: 列出当前用户已配置的所有数据源适配器。

**认证**: Bearer Token

**限流**: 100次/分钟

**响应**: `200 OK`
```json
{
  "total": 3,
  "items": [
    {
      "id": "adapter-uuid-1",
      "adapter_name": "manual",
      "is_active": true,
      "last_sync_at": "2026-06-06T08:00:00Z",
      "created_at": "2026-06-01T10:00:00Z"
    },
    {
      "id": "adapter-uuid-2",
      "adapter_name": "voice",
      "is_active": true,
      "last_sync_at": "2026-06-06T09:30:00Z",
      "created_at": "2026-06-01T10:00:00Z"
    },
    {
      "id": "adapter-uuid-3",
      "adapter_name": "wechat_forward",
      "is_active": false,
      "last_sync_at": null,
      "created_at": "2026-06-05T14:00:00Z"
    }
  ]
}
```

> **安全约束**: 响应中不返回 `config_encrypted` 字段内容，防止密钥泄露。

#### 3.14.2 添加新数据源配置

**端点**: `POST /api/v1/adapters`

**说明**: 为当前用户添加新的数据源适配器配置。

**认证**: Bearer Token

**限流**: 10次/分钟（写操作独立限流）

**请求**:
```json
{
  "adapter_name": "wechat_forward",
  "config": {
    "webhook_url": "https://...",
    "api_key": "sk-xxx"
  }
}
```

**字段说明**:
- `adapter_name`: 适配器名称（必填）。枚举值：`manual` / `voice` / `wechat_forward` / `email` / `calendar`
- `config`: 适配器配置（可选）。JSON对象，内容因适配器类型而异。**服务端加密后存储，API响应中不返回**

**响应**: `201 Created`
```json
{
  "id": "adapter-uuid-new",
  "adapter_name": "wechat_forward",
  "is_active": true,
  "last_sync_at": null,
  "created_at": "2026-06-06T10:00:00Z"
}
```

**错误码**:

| HTTP状态码 | 错误码 | 场景 |
|-----------|--------|------|
| 400 | E1000 | 缺少 adapter_name |
| 401 | E2000 | 未认证 |
| 409 | E1002 | 该用户已配置同名适配器（UNIQUE约束冲突） |
| 422 | E1003 | adapter_name 不在合法枚举值内 |

#### 3.14.3 手动触发同步

**端点**: `POST /api/v1/adapters/{name}/sync`

**说明**: 手动触发指定数据源的同步操作。同步为异步执行，立即返回任务ID。

**认证**: Bearer Token

**限流**: 5次/分钟/适配器（同步操作资源密集）

**路径参数**:
- `name`: 适配器名称（枚举值：`manual` / `voice` / `wechat_forward` / `email` / `calendar`）

**请求**:
```json
{
  "full_sync": false
}
```

**字段说明**:
- `full_sync`: 是否全量同步（可选，默认 `false`）。`false` 为增量同步，`true` 为全量同步

**响应**: `202 Accepted`
```json
{
  "task_id": "sync-task-uuid",
  "adapter_name": "wechat_forward",
  "status": "queued",
  "estimated_duration_ms": 5000,
  "created_at": "2026-06-06T10:00:00Z"
}
```

**错误码**:

| HTTP状态码 | 错误码 | 场景 |
|-----------|--------|------|
| 401 | E2000 | 未认证 |
| 404 | E1001 | 适配器未配置 |
| 409 | E1002 | 已有同步任务在执行中 |
| 429 | E3000 | 超过限流（5次/分钟/适配器） |

#### 3.14.4 删除数据源配置

**端点**: `DELETE /api/v1/adapters/{name}`

**说明**: 删除指定数据源的配置。`manual` 和 `voice` 为系统内置适配器，不可删除，仅可禁用。

**认证**: Bearer Token

**限流**: 10次/分钟

**路径参数**:
- `name`: 适配器名称

**响应**: `204 No Content`

**错误码**:

| HTTP状态码 | 错误码 | 场景 |
|-----------|--------|------|
| 401 | E2000 | 未认证 |
| 404 | E1001 | 适配器未配置 |
| 422 | E1003 | 尝试删除内置适配器（manual/voice），请使用 PATCH 设置 is_active=false |

### 3.15 Semantic Search API（v2.7 新增, F-57/F-58）

> **定位**: 提供基于向量嵌入的语义搜索能力，支持Entity/Event的自然语言查询，同时为关联发现提供语义增强（F-58）。

#### 3.15.1 语义搜索

**端点**: `POST /api/v1/search/semantic`

**说明**: 根据自然语言查询，返回语义最相似的Entity和Event列表。搜索范围限定为当前用户数据。

**认证**: Bearer Token

**限流**: 20次/分钟

**请求体**:

```json
{
  "query": "做AI创业的张总",
  "user_id": "auto",           // 从JWT提取，忽略客户端传入
  "top_k": 10,                 // 可选，默认10，范围1-50
  "target_types": ["entity", "event"],  // 可选，默认全部
  "min_similarity": 0.5        // 可选，默认0.5，范围0.0-1.0
}
```

**响应**: `200 OK`

```json
{
  "query": "做AI创业的张总",
  "results": [
    {
      "target_type": "entity",
      "target_id": "entity-uuid-001",
      "name": "张三",
      "company": "AI创业公司",
      "similarity": 0.8923,
      "matched_text": "姓名: 张三 | 公司: AI创业公司 | 行业: 科技 | 关注: AI应用落地 - 寻找合作伙伴",
      "highlights": ["AI创业", "张总"]
    },
    {
      "target_type": "event",
      "target_id": "event-uuid-002",
      "name": "与张三讨论AI合作方案",
      "similarity": 0.7541,
      "matched_text": "与张三讨论AI合作方案 | 参与者: 张三, 李四 | 类型: meeting | 关键内容: AI应用场景",
      "highlights": ["AI", "张三"]
    }
  ],
  "total": 2,
  "search_method": "sqlite_vec",  // "sqlite_vec" | "python_cosine"
  "latency_ms": 45
}
```

**错误码**:

| HTTP状态码 | 错误码 | 场景 |
|-----------|--------|------|
| 400 | E1000 | 参数校验失败（top_k>50, min_similarity<0等） |
| 401 | E2000 | 未认证 |
| 503 | E4000 | 语义搜索服务不可用（embedding API故障） |

#### 3.15.2 向量索引统计

**端点**: `GET /api/v1/search/stats`

**说明**: 返回当前用户的向量索引统计信息，用于监控和调试。

**认证**: Bearer Token

**限流**: 10次/分钟

**响应**: `200 OK`

```json
{
  "user_id": "user-uuid",
  "total_embeddings": 156,
  "by_type": {
    "entity": 98,
    "event": 58
  },
  "index_method": "sqlite_vec",   // "sqlite_vec" | "python_cosine"
  "last_indexed_at": "2026-06-06T10:30:00Z",
  "cache_size": 234,
  "embedding_model": "text-embedding-3-small",  // API模式; 本地降级为all-MiniLM-L6-v2
  "embedding_dimensions": 768  // API模式768维; 本地降级384维
}
```

#### 3.15.3 重建索引

**端点**: `POST /api/v1/search/reindex`

**说明**: 触发向量索引重建。异步执行，立即返回任务ID。

**认证**: Bearer Token

**限流**: 2次/小时

**请求体**:

```json
{
  "scope": "full",     // "full" 全量重建 | "incremental" 增量更新
  "target_types": ["entity", "event"]  // 可选，默认全部
}
```

**响应**: `202 Accepted`

```json
{
  "task_id": "reindex-task-uuid",
  "status": "started",
  "scope": "full",
  "estimated_items": 156,
  "started_at": "2026-06-06T10:30:00Z"
}
```

**错误码**:

| HTTP状态码 | 错误码 | 场景 |
|-----------|--------|------|
| 401 | E2000 | 未认证 |
| 409 | E1002 | 已有重建任务在执行中 |
| 429 | E3000 | 超过限流（2次/小时） |

#### 3.15.4 SearchResult Schema

```python
from pydantic import BaseModel
from typing import Optional

class SearchResultItem(BaseModel):
    """语义搜索结果项"""
    target_type: str           # "entity" | "event"
    target_id: str             # 目标ID
    name: str                  # Entity名称或Event标题
    company: Optional[str]     # 仅Entity有值
    similarity: float          # 余弦相似度 [0, 1]
    matched_text: str          # 生成embedding的原始文本
    highlights: list[str]      # 高亮关键词

class SemanticSearchResponse(BaseModel):
    """语义搜索响应"""
    query: str
    results: list[SearchResultItem]
    total: int
    search_method: str         # "sqlite_vec" | "python_cosine"
    latency_ms: int

class SearchStatsResponse(BaseModel):
    """搜索统计响应"""
    user_id: str
    total_embeddings: int
    by_type: dict[str, int]
    index_method: str
    last_indexed_at: Optional[str]
    cache_size: int
    embedding_model: str
    embedding_dimensions: int

class ReindexRequest(BaseModel):
    """重建索引请求"""
    scope: str = "full"        # "full" | "incremental"
    target_types: list[str] = ["entity", "event"]

class ReindexResponse(BaseModel):
    """重建索引响应"""
    task_id: str
    status: str                # "started"
    scope: str
    estimated_items: int
    started_at: str
```

---

## 4. 安全策略（v2.0新增）

### 4.1 PII脱敏API行为

> **定位**: 所有涉及用户隐私信息的API端点，在返回响应前必须执行 `redact_pii_from_text()` 脱敏处理。

**脱敏执行端点清单**:

| 端点 | 脱敏字段 | 说明 |
|------|---------|------|
| `GET /api/v1/entities/{id}` | `properties.profile.phone`, `properties.profile.email`, `evidence_quote` | 实体详情中的联系方式和证据引用 |
| `GET /api/v1/persons/{id}/relationship-brief` | `evidence_quote`, `need_insights[].insight` | 关系推进卡中的文本字段 |
| `GET /api/v1/associations` | `evidence.matched_fields`, `evidence.method` | 关联关系中的证据文本 |
| `GET /api/v1/todos` | `context.reason`, `description` | Todo中的上下文描述 |
| `GET /api/v1/digest/morning` / `evening` | 所有文本字段 | 摘要中的所有内容 |
| `GET /api/v1/mini/person/{id}` | `key_points`, `associations_summary` | 小程序人物速览 |
| `GET /api/v1/data/export` | **全部PII字段** | 数据导出（CSV/JSON均适用） |
| **[0.2.1新增]** `POST /api/v1/voice/session` | `answer_text` | 语音回答文本（TTS合成前脱敏） |
| **[0.2.1新增]** `GET /api/v1/voice/tts/{session_id}` | 音频内容 | TTS音频（合成源文本已脱敏） |

**不执行脱敏的端点**:
- `POST /api/v1/events` — 接收原始输入，存储前做 sanitize 清洗但不脱敏
- `PATCH /api/v1/entities/{id}` — 用户主动编辑，不做脱敏
- `POST /api/v1/contributions` — 用户主动提交，不做脱敏

**PII检测与掩码规则**:

| PII类型 | 正则模式 | 掩码规则 | 示例 |
|---------|---------|---------|------|
| 手机号(中国大陆) | `1[3-9]\d{9}` | 前3后4中间**** | 138****5678 |
| 邮箱 | `[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}` | 用户名部分*** | ***@example.com |
| 身份证号 | `\d{17}[\dXx]` | 前14后4中间****** | **************1234 |
| 银行卡号 | `\d{16,19}` | 前4后4中间**** | **** **** **** 1234 |
| 微信号 | `[a-zA-Z][-a-zA-Z0-9_]{5,19}` | 第2位后*** | w*** |

**实现要点**:
- 脱敏仅在 **API返回层** 执行，**存储层保留原文**（已加密）
- 工具函数位置：`src/eventlink/core/text_utils.py → redact_pii_from_text()`
- 单元测试必须覆盖每种PII类型
- 导出功能(CSV/JSON)同样执行脱敏

### 4.2 input_scope SC-01安全约束

> **定位**: v2.4 新增的安全约束，防止客户端通过 input_scope 字段绕过服务端分类逻辑。

**约束规则（SC-01）**:

```
POST /api/v1/events 的 input_scope 字段处理流程：

1. 客户端传 "auto" 或不传 → 服务端调用 InputClassifier.classify() → 返回分类结果 ✅
2. 客户端传具体枚举值 → 仅作为 hint，服务端仍以 classify() 结果为准 ⚠️
3. 客户端传非法值（不在合法枚举内且非 "auto"）→ 返回 400 INVALID_INPUT_SCOPE ❌
4. 核心原则：永远不以客户端传入值作为最终 scope
```

**合法枚举值（服务端内部使用，不接受客户端直接传入）**:

```python
VALID_SCOPES = {
    "relationship_interaction",   # 关系互动
    "identity_update",            # 身份更新
    "meeting_minutes",            # 会议纪要
    "partner_feedback",           # 合作方反馈（终止管线）
    "internal_review",            # 内部回顾（终止管线）
    "resource_inquiry",           # 资源咨询
    "care_expression",            # 关怀表达
    "cooperation_signal",         # 合作信号
}
```

**校验伪代码**:

```python
def resolve_input_scope(client_scope: str | None, raw_text: str, event_type: str) -> dict:
    # 非法值校验
    if client_scope and client_scope not in VALID_SCOPES and client_scope != "auto":
        raise HTTPException(
            status_code=400,
            detail={
                "error": "INVALID_INPUT_SCOPE",
                "code": "E1004",
                "message": f"Invalid input_scope: {client_scope}",
                "valid_values": ["auto"],
                "hint": "仅接受 'auto' 或不传该字段"
            }
        )
    # 永远以服务端classify()结果为准
    result = InputClassifier.classify(raw_text, event_type)
    return result  # {scope, confidence, reason}
```

### 4.3 数据导出API（GDPR数据携带权, Phase 1提前）

**端点**: `GET /api/v1/data/export?format=json|csv`

**说明**: 支持用户导出其全量个人数据，满足 GDPR 式"数据携带权"(Right to Data Portability)。原计划 Phase 2 实现，提前至 Phase 1。

**查询参数**:
- `format`: 导出格式（必填）。`json` — JSON格式；`csv` — CSV格式

**认证**: 需要 Bearer Token（同其他端点）

**响应**: `200 OK`

**JSON格式**:
```json
{
  "exported_at": "2026-06-04T10:00:00Z",
  "user_id": "user-uuid",
  "format": "json",
  "data": {
    "entities": [
      {
        "id": "entity-uuid",
        "entity_type": "person",
        "name": "张三",
        "company": "AI公司",
        "title": "CEO",
        "relationship_stage": "understanding_needs",
        "created_at": "2026-06-01T10:00:00Z"
      }
    ],
    "events": [
      {
        "id": "event-uuid",
        "event_type": "meeting",
        "title": "供应链优化方案讨论",
        "timestamp": "2026-06-04T09:00:00Z",
        "created_at": "2026-06-04T09:05:00Z"
      }
    ],
    "todos": [
      {
        "id": "todo-uuid",
        "todo_type": "promise",
        "status": "pending",
        "description": "承诺下周介绍赵六给张三认识",
        "created_at": "2026-06-03T10:00:00Z"
      }
    ],
    "relationship_briefs": [
      {
        "id": "brief-uuid",
        "person_id": "entity-uuid",
        "current_stage": "understanding_needs",
        "created_at": "2026-06-01T10:00:00Z"
      }
    ]
  },
  "pii_redacted": true,
  "total_records": {
    "entities": 15,
    "events": 42,
    "todos": 28,
    "relationship_briefs": 12
  }
}
```

**CSV格式**: 多文件ZIP下载，每个实体类型一个CSV文件（entities.csv, events.csv, todos.csv, relationship_briefs.csv）

**安全要求**:
- **PII自动脱敏**：导出数据中所有PII字段均已执行 `redact_pii_from_text()`
- 导出操作记录审计日志
- 单次导出限制：最多导出最近2年数据
- 限流：每用户每24小时最多3次导出请求

---

## 5. 错误码定义

### 5.1 HTTP状态码

| 状态码 | 说明 | 使用场景 |
|--------|------|---------|
| 200 | OK | 成功查询 |
| 201 | Created | 成功创建资源 |
| 204 | No Content | 成功删除 |
| 400 | Bad Request | 参数错误 |
| 401 | Unauthorized | 未认证或token过期 |
| 403 | Forbidden | 权限不足 |
| 404 | Not Found | 资源不存在 |
| 409 | Conflict | 资源冲突（如重复创建） |
| 422 | Unprocessable Entity | 语义错误（如验证失败） |
| 429 | Too Many Requests | 超过限流 |
| 500 | Internal Server Error | 服务器错误 |
| 503 | Service Unavailable | 服务暂时不可用 |

### 5.2 业务错误码

**统一错误响应格式**:
```json
{
  "error": {
    "code": "E1001",
    "message": "实体不存在",
    "details": {
      "entity_id": "uuid"
    },
    "timestamp": "2026-06-02T10:00:00Z",
    "request_id": "req-uuid"
  }
}
```

**错误码表**:

| 错误码 | 说明 | HTTP状态码 |
|--------|------|-----------|
| E1000 | 参数缺失 | 400 |
| E1001 | 资源不存在 | 404 |
| E1002 | 重复资源 | 409 |
| E1003 | 验证失败 | 422 |
| E1004 | 无效的input_scope值 | 400 |
| E1005 | 乐观锁冲突 | 409 |
| E2000 | Token无效 | 401 |
| E2001 | Token过期 | 401 |
| E2002 | 权限不足 | 403 |
| E3000 | 限流超限 | 429 |
| E4000 | LLM调用失败 | 503 |
| E4001 | 数据库异常 | 500 |
| E5000 | 未知错误 | 500 |

#### v2.0 新增错误码说明

**E1004 — INVALID_INPUT_SCOPE（400 Bad Request）**

当 `POST /api/v1/events` 的 `input_scope` 字段传入非法值时返回。合法值仅接受 `"auto"` 或不传该字段。

```json
{
  "error": {
    "code": "E1004",
    "error_type": "INVALID_INPUT_SCOPE",
    "message": "无效的 input_scope 值",
    "details": {
      "provided_value": "invalid_scope",
      "valid_values": ["auto"],
      "hint": "仅接受 'auto' 或不传该字段"
    },
    "timestamp": "2026-06-04T10:00:00Z",
    "request_id": "req-uuid"
  }
}
```

**E1005 — OPTIMISTIC_LOCK_CONFLICT（409 Conflict）**

当 `PATCH /api/v1/persons/{id}/relationship-brief/stage` 的乐观锁版本号不匹配时返回。客户端需重新获取最新 relationship-brief 后重试。

```json
{
  "error": {
    "code": "E1005",
    "error_type": "OPTIMISTIC_LOCK_CONFLICT",
    "message": "关系推进卡已被其他请求更新，请刷新后重试",
    "details": {
      "current_version": 5,
      "client_version": 3,
      "hint": "请重新获取最新 relationship-brief 后重试"
    },
    "timestamp": "2026-06-04T15:00:01Z",
    "request_id": "req-uuid"
  }
}
```

---

## 6. 分页与排序

### 6.1 分页参数

**查询参数**:
- `limit`: 每页数量（默认20，最大100）
- `offset`: 偏移量（默认0）

**响应包含links**:
```json
{
  "total": 100,
  "items": [...],
  "links": {
    "self": "/api/v1/entities?offset=20&limit=20",
    "next": "/api/v1/entities?offset=40&limit=20",
    "prev": "/api/v1/entities?offset=0&limit=20",
    "first": "/api/v1/entities?offset=0&limit=20",
    "last": "/api/v1/entities?offset=80&limit=20"
  }
}
```

### 6.2 排序参数

**查询参数**:
- `sort`: 排序字段（默认created_at）
- `order`: asc\|desc（默认desc）

**示例**: `GET /api/v1/todos?sort=priority&order=desc`

---

## 7. 限流策略

### 7.1 限流规则

> **设计原则**: EventLink定位为AI驱动的个人商务关系经营助手，采用单用户模式，无RBAC/多租户/团队协作，因此限流策略为统一单用户限流。

| 限流对象 | 限制 | 时间窗口 | 说明 |
|---------|------|---------|------|
| 单用户（统一） | 100次 | 1分钟 | 所有API端点统一限流，无角色区分 |

**PoC阶段说明**: PoC阶段限流可适当放宽，建议设置为200次/分钟，以便充分测试和验证功能。正式上线后恢复为100次/分钟。

### 7.2 限流响应

**响应头**:
```http
X-RateLimit-Limit: 100
X-RateLimit-Remaining: 95
X-RateLimit-Reset: 1622620800
```

**超限响应**: `429 Too Many Requests`
```json
{
  "error": {
    "code": "E3000",
    "message": "超过限流，请1分钟后重试",
    "retry_after": 60
  }
}
```

---

## 8. OpenAPI 3.0规范（YAML）

```yaml
openapi: 3.0.3
info:
  title: EventLink API
  version: 2.0.0
  description: |
    EventLink AI驱动的个人商务关系经营助手API
    v2.0新增：关系推进卡API、Dashboard API、日视图API、贡献与反馈API、数据导出API、安全策略（PII脱敏/SC-01/JWT加固）
  contact:
    name: CarryMem团队
    email: support@carrymem.com

servers:
  - url: https://api.eventlink.example.com/api/v1
    description: 生产环境
  - url: http://localhost:8000/api/v1
    description: 开发环境

security:
  - BearerAuth: []

paths:
  /events:
    post:
      summary: 创建事件
      requestBody:
        required: true
        content:
          application/json:
            schema:
              $ref: '#/components/schemas/EventCreate'
      responses:
        '201':
          description: 创建成功
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/Event'
        '400':
          $ref: '#/components/responses/BadRequest'

  /entities:
    get:
      summary: 搜索实体
      parameters:
        - name: q
          in: query
          schema:
            type: string
        - name: type
          in: query
          schema:
            type: string
            enum: [person, organization, technology, project, attribute]
        - name: sensitivity
          in: query
          description: 资源敏感度筛选
          schema:
            type: string
            enum: [matchable, no_match]
        - name: limit
          in: query
          schema:
            type: integer
            default: 20
        - name: offset
          in: query
          schema:
            type: integer
            default: 0
      responses:
        '200':
          description: 成功
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/EntityList'

  /entities/{id}/sensitivity:
    patch:
      summary: 修改资源敏感度
      parameters:
        - name: id
          in: path
          required: true
          schema:
            type: string
            format: uuid
      requestBody:
        required: true
        content:
          application/json:
            schema:
              type: object
              required: [resource_sensitivity]
              properties:
                resource_sensitivity:
                  type: string
                  enum: [matchable, no_match]
      responses:
        '200':
          description: 修改成功
        '422':
          $ref: '#/components/responses/BadRequest'

  /entities/{id}/concern:
    patch:
      summary: 添加/确认关注点
      parameters:
        - name: id
          in: path
          required: true
          schema:
            type: string
            format: uuid
      requestBody:
        required: true
        content:
          application/json:
            schema:
              $ref: '#/components/schemas/ConcernUpdate'
      responses:
        '200':
          description: 操作成功
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/Concern'
        '422':
          $ref: '#/components/responses/BadRequest'

  /entities/{id}/promise:
    patch:
      summary: 添加/更新承诺
      parameters:
        - name: id
          in: path
          required: true
          schema:
            type: string
            format: uuid
      requestBody:
        required: true
        content:
          application/json:
            schema:
              $ref: '#/components/schemas/PromiseUpdate'
      responses:
        '200':
          description: 操作成功
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/Promise'
        '422':
          $ref: '#/components/responses/BadRequest'

  /entities/{id}/contribution:
    patch:
      summary: 记录帮助
      parameters:
        - name: id
          in: path
          required: true
          schema:
            type: string
            format: uuid
      requestBody:
        required: true
        content:
          application/json:
            schema:
              $ref: '#/components/schemas/ContributionCreate'
      responses:
        '200':
          description: 操作成功
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/Contribution'
        '422':
          $ref: '#/components/responses/BadRequest'

  /todos:
    get:
      summary: 待办列表
      parameters:
        - name: status
          in: query
          schema:
            type: string
            enum: [pending, in_progress, done, dismissed, snoozed]
        - name: type
          in: query
          schema:
            type: string
            enum: [cooperation_signal, risk, care, promise, followup, help]
        - name: priority
          in: query
          schema:
            type: string
            enum: [high, medium, low]
        - name: due_before
          in: query
          schema:
            type: string
            format: date-time
      responses:
        '200':
          description: 成功
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/TodoList'

  /entities/{id}/resources:
    get:
      summary: 查看实体资源列表
      parameters:
        - name: id
          in: path
          required: true
          schema:
            type: string
            format: uuid
      responses:
        '200':
          description: 成功
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/ResourceList'
    post:
      summary: 添加资源标签
      parameters:
        - name: id
          in: path
          required: true
          schema:
            type: string
            format: uuid
      requestBody:
        required: true
        content:
          application/json:
            schema:
              $ref: '#/components/schemas/ResourceCreate'
      responses:
        '201':
          description: 创建成功

  /entities/{id}/resources/{resource_id}:
    delete:
      summary: 删除资源标签
      parameters:
        - name: id
          in: path
          required: true
          schema:
            type: string
            format: uuid
        - name: resource_id
          in: path
          required: true
          schema:
            type: string
            format: uuid
      responses:
        '204':
          description: 删除成功
        '404':
          description: 资源标签不存在

  /resources/match:
    get:
      summary: 资源匹配查询（单边匹配）
      parameters:
        - name: demand_tag
          in: query
          required: true
          schema:
            type: string
        - name: min_score
          in: query
          schema:
            type: number
            default: 0.5
            minimum: 0
            maximum: 1
        - name: limit
          in: query
          schema:
            type: integer
            default: 20
        - name: offset
          in: query
          schema:
            type: integer
            default: 0
      responses:
        '200':
          description: 匹配成功
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/ResourceMatchResult'

  /voice/session:
    post:
      summary: 创建语音问答会话（F-50）
      description: |
        接收ASR识别后的文本，经NLU意图识别后调用对应业务API，返回自然语言答案+预生成TTS音频URL。
        Phase 1.1为一次性会话模式（无多轮对话）。
      requestBody:
        required: true
        content:
          application/json:
            schema:
              $ref: '#/components/schemas/VoiceSessionCreate'
      responses:
        '200':
          description: 语音问答成功
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/VoiceSessionResponse'
        '400':
          $ref: '#/components/responses/BadRequest'
        '401':
          $ref: '#/components/responses/Unauthorized'
        '422':
          description: NLU无法识别意图
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/VoiceSessionResponse'

  /voice/tts/{session_id}:
    get:
      summary: 获取TTS音频（F-50）
      description: 获取指定语音会话预生成的TTS音频文件（MP3格式）。音频文件5分钟后自动清理。
      parameters:
        - name: session_id
          in: path
          required: true
          schema:
            type: string
      responses:
        '200':
          description: MP3音频流
          content:
            audio/mpeg:
              schema:
                type: string
                format: binary
        '401':
          $ref: '#/components/responses/Unauthorized'
        '404':
          description: session_id不存在或TTS音频已过期

  /voice/feedback:
    post:
      summary: 语音回答质量反馈（F-50）
      description: 用户对语音回答的质量反馈，用于NLU模型持续优化和答案质量监控。
      requestBody:
        required: true
        content:
          application/json:
            schema:
              $ref: '#/components/schemas/VoiceFeedbackCreate'
      responses:
        '200':
          description: 反馈记录成功
          content:
            application/json:
              schema:
                type: object
                properties:
                  message:
                    type: string
                  session_id:
                    type: string
        '400':
          $ref: '#/components/responses/BadRequest'
        '401':
          $ref: '#/components/responses/Unauthorized'

components:
  securitySchemes:
    BearerAuth:
      type: http
      scheme: bearer
      bearerFormat: JWT

  schemas:
    EventCreate:
      type: object
      required: [event_type, title, timestamp, raw_text]
      properties:
        event_type:
          type: string
          enum: [card_save, meeting, call, manual]
        source:
          type: string
        title:
          type: string
        timestamp:
          type: string
          format: date-time
        raw_text:
          type: string
        metadata:
          type: object

    Event:
      allOf:
        - $ref: '#/components/schemas/EventCreate'
        - type: object
          properties:
            id:
              type: string
              format: uuid
            created_at:
              type: string
              format: date-time

    EntityList:
      type: object
      properties:
        total:
          type: integer
        items:
          type: array
          items:
            $ref: '#/components/schemas/Entity'
        links:
          type: object

    Entity:
      type: object
      properties:
        id:
          type: string
          format: uuid
        entity_type:
          type: string
        name:
          type: string
        company:
          type: string
        title:
          type: string
        resource_sensitivity:
          type: string
          enum: [matchable, no_match]
          description: 资源敏感度标记，matchable可参与匹配，no_match不参与匹配
          default: matchable
        properties:
          type: object

    TodoType:
      type: string
      enum: [cooperation_signal, risk, care, promise, followup, help]
      description: |
        Todo类型枚举：
        - cooperation_signal: 合作信号（雾白#B8C4C0）
        - risk: 风险预警（烟粉#C4A7A0）
        - care: 关注关怀（雾蓝#A0B0C4）
        - promise: 承诺跟踪（雾绿#A0C4A8）
        - followup: 跟进确认（雾金#C4C0A0）
        - help: 帮助记录（雾紫#B0A0C4）

    MorandiColor:
      type: string
      enum: ['#B8C4C0', '#C4A7A0', '#A0B0C4', '#A0C4A8', '#C4C0A0', '#B0A0C4']
      description: |
        莫兰迪色系映射：
        - #B8C4C0: 雾白（cooperation_signal）
        - #C4A7A0: 烟粉（risk）
        - #A0B0C4: 雾蓝（care）
        - #A0C4A8: 雾绿（promise）
        - #C4C0A0: 雾金（followup）
        - #B0A0C4: 雾紫（help）

    Todo:
      type: object
      properties:
        id:
          type: string
          format: uuid
        todo_type:
          $ref: '#/components/schemas/TodoType'
        status:
          type: string
          enum: [pending, in_progress, done, dismissed, snoozed]
        priority:
          type: string
          enum: [high, medium, low]
        morandi_color:
          $ref: '#/components/schemas/MorandiColor'
        description:
          type: string
        related_entity:
          type: object
          properties:
            id:
              type: string
              format: uuid
            name:
              type: string
        context:
          type: object
        due_date:
          type: string
          format: date-time
          nullable: true
        completed_rank:
          type: integer
          nullable: true
          description: 完成序号(隐式反馈用, v2.5新增)
        dynamic_score:
          type: number
          nullable: true
          minimum: 0
          maximum: 100
          description: 动态优先级分(v2.5新增)
        breakdown:
          type: object
          nullable: true
          description: 四维评分详情(v2.6新增)
          properties:
            urgency:
              type: number
              description: 紧急度得分(0-1)
            importance:
              type: number
              description: 重要度得分(0-1)
            dependency:
              type: number
              description: 依赖阻塞度得分(0-1, F-55)
            context:
              type: number
              description: 场景匹配度得分(0-1, F-56)
            dependency_raw:
              type: object
              nullable: true
              description: 依赖分析原始计算因子(F-55, v2.6新增)
              properties:
                depth_weight_sum:
                  type: number
                blocked_count:
                  type: integer
                block_weight:
                  type: number
                max_depth:
                  type: integer
                formula:
                  type: string
            context_raw:
              type: object
              nullable: true
              description: 场景匹配原始计算因子(F-56, v2.6新增)
              properties:
                entity_id:
                  type: string
                  format: uuid
                hours_until:
                  type: number
                window_hours:
                  type: integer
                matched_event:
                  type: object
                  nullable: true
                  properties:
                    event_title:
                      type: string
                    nearest_meeting_at:
                      type: string
                      format: date-time
                formula:
                  type: string
        created_at:
          type: string
          format: date-time

    TodoList:
      type: object
      properties:
        total:
          type: integer
        items:
          type: array
          items:
            $ref: '#/components/schemas/Todo'

    ResourceCreate:
      type: object
      required: [type, tag, callability]
      properties:
        type:
          type: string
          enum: [resource, demand]
          description: resource=供给，demand=需求
        tag:
          type: string
          description: 资源标签描述
        callability:
          type: string
          enum: [high, medium, low]
          description: 可调用度，表示该资源的可触达程度
        source:
          type: string
          enum: [manual, llm_extract]
          description: 来源，manual=手动添加，llm_extract=AI提取

    Resource:
      type: object
      properties:
        id:
          type: string
          format: uuid
        entity_id:
          type: string
          format: uuid
        type:
          type: string
          enum: [resource, demand]
        tag:
          type: string
        callability:
          type: string
          enum: [high, medium, low]
        source:
          type: string
          enum: [manual, llm_extract]
        created_at:
          type: string
          format: date-time

    ResourceList:
      type: object
      properties:
        entity_id:
          type: string
          format: uuid
        entity_name:
          type: string
        resources:
          type: array
          items:
            $ref: '#/components/schemas/Resource'
        total:
          type: integer

    ResourceMatchItem:
      type: object
      properties:
        entity:
          type: object
          properties:
            id:
              type: string
              format: uuid
            name:
              type: string
            company:
              type: string
            title:
              type: string
        matched_resource:
          type: object
          properties:
            id:
              type: string
              format: uuid
            tag:
              type: string
            type:
              type: string
              enum: [resource, demand]
            callability:
              type: string
              enum: [high, medium, low]
        match_score:
          type: number
          minimum: 0
          maximum: 1
        score_breakdown:
          type: object
          properties:
            keyword:
              type: number
            industry:
              type: number
            topic:
              type: number
            llm:
              type: number
            history:
              type: number
            callability:
              type: number
        match_reason:
          type: string

    ResourceMatchResult:
      type: object
      properties:
        demand_tag:
          type: string
        total:
          type: integer
        items:
          type: array
          items:
            $ref: '#/components/schemas/ResourceMatchItem'

    ConcernUpdate:
      type: object
      required: [topic, action]
      properties:
        topic:
          type: string
          description: 关注点主题
        action:
          type: string
          enum: [add, confirm]
          description: 操作类型，add=添加，confirm=确认已有关注点
        source:
          type: string
          enum: [manual, llm_infer]
          description: 来源，manual=手动添加，llm_infer=AI推断

    Concern:
      type: object
      properties:
        id:
          type: string
          format: uuid
        entity_id:
          type: string
          format: uuid
        topic:
          type: string
          description: 关注点主题
        status:
          type: string
          enum: [active, resolved, dismissed]
          description: 关注点状态
        source:
          type: string
          enum: [manual, llm_infer]
        created_at:
          type: string
          format: date-time

    PromiseUpdate:
      type: object
      required: [content, action]
      properties:
        content:
          type: string
          description: 承诺内容
        due_at:
          type: string
          format: date-time
          description: 承诺截止时间
        action:
          type: string
          enum: [add, update]
          description: 操作类型，add=添加，update=更新已有承诺
        promise_id:
          type: string
          format: uuid
          description: 更新时需提供已有承诺ID

    Promise:
      type: object
      properties:
        id:
          type: string
          format: uuid
        entity_id:
          type: string
          format: uuid
        content:
          type: string
          description: 承诺内容
        due_at:
          type: string
          format: date-time
          description: 承诺截止时间
        status:
          type: string
          enum: [pending, done, overdue, cancelled]
          description: 承诺状态
        created_at:
          type: string
          format: date-time

    ContributionCreate:
      type: object
      required: [content, date]
      properties:
        content:
          type: string
          description: 帮助内容描述
        date:
          type: string
          format: date
          description: 帮助发生日期

    Contribution:
      type: object
      properties:
        id:
          type: string
          format: uuid
        entity_id:
          type: string
          format: uuid
        content:
          type: string
          description: 帮助内容描述
        date:
          type: string
          format: date
          description: 帮助发生日期
        created_at:
          type: string
          format: date-time

    AIInferenceMarker:
      type: object
      description: AI输出语言规则标记，所有LLM生成的响应应包含此标记
      properties:
        confidence_level:
          type: string
          enum: [high, medium, low]
          description: |
            置信度等级：
            - high: 基于明确数据源的事实性结论
            - medium: 基于部分证据的合理推断
            - low: 基于弱信号的推测性结论
        is_ai_inference:
          type: boolean
          description: 是否为AI推测内容
        requires_confirmation:
          type: boolean
          description: 是否需要用户确认（敏感结论必标）

    VoiceIntent:
      type: string
      enum: [schedule_query, promise_tracker, relationship_status, schedule_range, action_suggestion, conversation_review, knowledge_retrieval, unclear]
      description: |
        语音助手NLU意图枚举（F-50）：
        - schedule_query: 日程查询(P0)
        - promise_tracker: 承诺追踪(P0)
        - relationship_status: 关系推进(P0)
        - schedule_range: 范围日程(P1)
        - action_suggestion: 行动建议(P1)
        - conversation_review: 交流回顾(P2)
        - knowledge_retrieval: 知识检索(P2)
        - unclear: 无法识别

    VoiceSessionCreate:
      type: object
      required: [query_text, client_timestamp]
      properties:
        query_text:
          type: string
          minLength: 1
          maxLength: 500
          description: ASR识别后的文字
        asr_confidence:
          type: number
          minimum: 0.0
          maximum: 1.0
          description: ASR置信度
        voice_input:
          type: boolean
          default: true
          description: 标记来源为语音
        client_timestamp:
          type: string
          format: date-time
          description: 客户端时间戳(ISO 8601)

    VoiceSessionResponse:
      type: object
      required: [session_id, intent, intent_confidence, answer_text, source_data, processing_time_ms]
      properties:
        session_id:
          type: string
          description: 会话唯一标识
        intent:
          $ref: '#/components/schemas/VoiceIntent'
        intent_confidence:
          type: number
          minimum: 0.0
          maximum: 1.0
          description: 意图识别置信度
        answer_text:
          type: string
          description: 自然语言回答文本(已PII脱敏)
        tts_url:
          type: string
          nullable: true
          description: 预生成的TTS音频URL
        source_data:
          type: object
          description: 原始数据引用(用于前端展示详情)
          properties:
            type:
              type: string
            date:
              type: string
              format: date
            event_count:
              type: integer
        processing_time_ms:
          type: integer
          description: 服务端处理耗时(ms)
        suggest_questions:
          type: array
          items:
            type: string
          nullable: true
          description: 当intent=unclear时提供建议问题

    VoiceFeedbackCreate:
      type: object
      required: [session_id, rating]
      properties:
        session_id:
          type: string
          description: 语音会话ID
        rating:
          type: string
          enum: [helpful, not_helpful, wrong_intent, unclear]
          description: 反馈评级
        comment:
          type: string
          maxLength: 200
          description: 补充说明

    SummaryLevel:
      type: string
      enum: [brief, detail, voice]
      description: |
        摘要级别枚举（F-50新增，用于voice API调用下游端点时）：
        - brief: 一句话摘要，适合Dashboard卡片展示（默认）
        - detail: 完整列表，适合详情页
        - voice: 自然语言段落，适合TTS语音输出

    Error:
      type: object
      properties:
        error:
          type: object
          properties:
            code:
              type: string
            message:
              type: string
            details:
              type: object
            timestamp:
              type: string
              format: date-time
            request_id:
              type: string

  responses:
    BadRequest:
      description: 参数错误
      content:
        application/json:
          schema:
            $ref: '#/components/schemas/Error'
    
    Unauthorized:
      description: 未认证
      content:
        application/json:
          schema:
            $ref: '#/components/schemas/Error'
```

---

## 9. API版本管理策略

> **7角色架构评审共识**：API版本管理是P3 Gate的必要条件，必须在P8前确定。

### 9.1 版本体系（三层版本号）

EventLink采用**语义化版本号（SemVer）**管理API演进：

| 层级 | 格式 | 含义 | 示例 | 变更触发 |
|------|------|------|------|---------|
| **主版本** | `/api/v{N}/` | URL路径版本，兼容性破坏时递增 | `/api/v1/` → `/api/v2/` | 删除字段/修改类型/修改URL结构 |
| **次版本** | `X-API-Version: {N}.{M}` | 响应头声明，新增功能时递增 | `1.0` → `1.1` → `1.2` | 新增端点/新增字段/新增枚举值 |
| **补丁版本** | `X-API-Patch: {N}.{M}.{P}` | 内部修复，客户端无感 | `1.2.0` → `1.2.1` | Bug修复/性能优化/文档修正 |

**当前版本**：主版本v1，次版本2.0，补丁版本2.0.0

### 9.2 版本协商机制

客户端通过请求头声明期望版本，服务端通过响应头返回实际版本：

```http
# 客户端请求
GET /api/v1/todos
Accept-Version: 1.2        # 客户端期望的最低次版本（可选）

# 服务端响应
HTTP/1.1 200 OK
X-API-Version: 1.2.0       # 实际响应的完整版本号
X-API-Deprecated: false     # 当前端点是否已废弃
```

**版本不匹配处理**：

| 场景 | 客户端版本 | 服务端版本 | 处理方式 |
|------|-----------|-----------|---------|
| 客户端版本过低 | 1.0 | 1.2 | 正常响应，缺失字段返回null |
| 客户端请求已废弃字段 | 1.0 | 1.2 | 响应头 `Warning: 299 - "field X is deprecated"` |
| 主版本不匹配 | v1 | v2 | 返回 `410 Gone` + 迁移指南URL |
| 客户端版本过高 | 1.5 | 1.2 | 返回 `400 Bad Request` + 支持的最高版本 |

### 9.3 兼容性规则

**兼容变更（次版本递增，不升级主版本）**：

| 操作 | 示例 | 规则 |
|------|------|------|
| ✅ 新增可选字段 | 响应增加 `priority` 字段 | 旧客户端忽略新字段 |
| ✅ 新增端点 | `GET /api/v1/digest/evening` | 旧客户端不调用 |
| ✅ 新增枚举值 | Todo类型增加 `milestone` | 旧客户端显示为"未知类型" |
| ✅ 放松验证规则 | `title` 从必填改为可选 | 旧客户端仍传必填字段 |
| ✅ 增加查询参数 | `GET /todos?sort=priority` | 旧参数仍有效 |

**破坏性变更（必须升级主版本）**：

| 操作 | 示例 | 替代方案 |
|------|------|---------|
| ❌ 删除字段 | 移除 `morandi_color` | 先标记deprecated→6个月后在新主版本移除 |
| ❌ 修改字段类型 | `confidence` 从float改为string | 新增字段 `confidence_level`，旧字段保留 |
| ❌ 修改URL结构 | `/todos` → `/tasks` | 新URL在新主版本，旧URL保留+重定向 |
| ❌ 修改语义 | `status=pending` 含义变更 | 新增状态值，不修改旧值含义 |
| ❌ 收紧验证规则 | 可选字段改为必填 | 新增必填字段用新名称 |

### 8.4 废弃流程

```
阶段1: 活跃（Active）          → 正常使用，无任何标记
阶段2: 弃用预告（Deprecated）  → 响应头添加 Deprecation: true + Sunset: <date>
阶段3: 冻结（Frozen）          → 仍可用但不再修复Bug，文档标注FROZEN
阶段4: 下线（Gone）            → 返回 410 Gone + 迁移指南URL
```

**时间线**：

| 阶段 | 持续时间 | 通知方式 | 客户端影响 |
|------|---------|---------|-----------|
| Active→Deprecated | 提前6个月 | 响应头+文档+变更日志 | 无，但应开始迁移 |
| Deprecated→Frozen | 再3个月 | 文档FROZEN标记 | 不再修复Bug |
| Frozen→Gone | 再3个月 | 返回410 | 客户端必须已迁移 |

**总计**：从标记Deprecated到正式下线，给予**12个月**过渡期。

### 9.5 多版本共存策略

**路由层实现**（FastAPI）：

```python
from fastapi import FastAPI, APIRouter

app = FastAPI()

# v1路由
v1_router = APIRouter(prefix="/api/v1")
# v2路由（未来）
v2_router = APIRouter(prefix="/api/v2")

# 版本感知的依赖注入
async def version_context(version: str = Header(default="1.0", alias="Accept-Version")):
    return {"api_version": version}

# v1端点
@v1_router.get("/todos")
async def list_todos_v1(ctx=Depends(version_context)):
    # v1兼容：morandi_color字段保留
    return {"items": [...], "morandi_color": "#A0C4A8"}

# v2端点（未来示例：morandi_color改为color_scheme）
@v2_router.get("/todos")
async def list_todos_v2(ctx=Depends(version_context)):
    return {"items": [...], "color_scheme": {"primary": "#A0C4A8", "name": "雾绿"}}

app.include_router(v1_router)
app.include_router(v2_router)
```

**版本共存规则**：
- 同时运行最多2个主版本（v1 + v2）
- 次版本通过代码分支管理，不部署独立服务
- 旧版本共享同一数据库，通过Schema版本字段区分

### 9.6 数据库Schema版本管理

**Alembic迁移策略**：

```bash
# 初始化
alembic init alembic

# 生成迁移脚本
alembic revision --autogenerate -m "add_concern_promise_contribution"

# 执行迁移
alembic upgrade head

# 回滚
alembic downgrade -1

# 查看当前版本
alembic current
```

**迁移与API版本对应**：

| Alembic版本 | API主版本 | 变更内容 |
|------------|----------|---------|
| 001_initial | v1 | 初始4表（events/entities/associations/todos） |
| 002_todo_types_v2 | v1 | Todo类型重命名（DDL ALTER CHECK约束） |
| 003_concern_promise | v1 | entities.properties新增concern/promise/contribution |
| 004_snooze_schedules | v1 | 新增snooze_schedules表 |

**关键规则**：
- 每次API次版本变更必须对应一个Alembic迁移脚本
- 迁移脚本必须包含 `upgrade()` 和 `downgrade()`
- 破坏性Schema变更（删列/改类型）只能在新的API主版本中执行
- PoC→Phase1迁移是一次性全量迁移，不走Alembic增量

### 9.7 客户端SDK版本策略

| 客户端 | 版本管理方式 | 最低支持版本 |
|--------|------------|------------|
| 微信小程序 | 小程序版本号 + API版本检查 | v1.0 |
| H5页面 | 构建时注入API_VERSION | v1.2 |
| Swagger UI | 自动跟随服务端版本 | 当前版本 |

**客户端版本检查**（小程序启动时）：

```javascript
// 小程序启动时检查API版本兼容性
async function checkApiCompatibility() {
  const response = await fetch('/api/v1/health')
  const serverVersion = response.headers.get('X-API-Version')
  const [major, minor] = serverVersion.split('.').map(Number)
  
  if (major > 1) {
    // 主版本不匹配，提示用户更新小程序
    wx.showModal({
      title: '需要更新',
      content: 'EventLink已升级，请更新小程序以继续使用',
      showCancel: false
    })
  }
}
```

### 9.8 版本变更日志

所有API版本变更必须记录在 `CHANGELOG.md` 和 API文档的版本历史章节中：

```markdown
## [1.2.0] - 2026-06-03
### Added
- PATCH /api/v1/entities/{id}/concern — 添加/确认关注点
- PATCH /api/v1/entities/{id}/promise — 添加/更新承诺
- PATCH /api/v1/entities/{id}/contribution — 记录帮助
- AI输出语言规则标记（confidence_level/is_ai_inference/requires_confirmation）

### Changed
- Todo类型枚举重命名（opportunity→cooperation_signal等6种）

### Deprecated
- 无
```

---

## 10. 性能监控

### 10.1 响应时间目标

| 端点类别 | P50 | P95 | P99 |
|---------|-----|-----|-----|
| 查询类（GET） | <50ms | <200ms | <500ms |
| 创建类（POST） | <100ms | <300ms | <1s |
| 复杂查询（图谱） | <500ms | <2s | <5s |

### 10.2 监控指标

```python
# 响应头包含性能指标
X-Response-Time: 145ms
X-DB-Time: 23ms
X-LLM-Time: 95ms
X-Cache-Hit: true
```

---

## 11. 版本历史

| 版本 | 日期 | 变更 |
|------|------|------|
| v1.0 | 2026-06-02 | 初始版本 |
| v1.1 | 2026-06-03 | Todos类型扩展为6种（opportunity/risk/context/action/pending_confirm/resource_maint）；添加莫兰迪色系morandi_color字段；Entities API添加resource_sensitivity字段及sensitivity端点；新增Resources API（资源管理+六维匹配算法）；限流策略改为单用户统一限流（移除RBAC三级）；OpenAPI规范同步更新 |
| v1.2 | 2026-06-03 | Todo类型重命名（opportunity→cooperation_signal, context→care, action→promise, pending_confirm→followup, resource_maint→help）；Entities API新增concern/promise/contribution字段及三个PATCH端点（concern/promise/contribution）；Todos API新增promise/care/cooperation_signal类型详细示例；新增§3.8 AI输出语言规则（confidence_level/is_ai_inference/requires_confirmation）；OpenAPI规范同步更新（TodoType枚举、新增Concern/Promise/Contribution/AIInferenceMarker schema） |
| v1.3 | 2026-06-03 | §8 API版本管理策略全面补齐：三层版本号（SemVer）+ 版本协商机制 + 兼容性规则 + 废弃流程（12个月过渡期）+ 多版本共存（FastAPI路由层）+ Alembic数据库迁移策略 + 客户端SDK版本策略 + 版本变更日志规范 |
| **v2.0** | **2026-06-04** | **v2.0大版本升级（参考 PRD v4.3 + 技术设计 v2.5 §7）：**<br/>**① D2-1** 版本头更新<br/>**② D2-2 新增6个P0 API端点**: GET relationship-brief / PATCH stage(乐观锁) / GET dashboard/today / GET todos?view=my-responses / POST contributions / POST feedbacks<br/>**③ D2-3 日视图API (F-49)**: GET /api/v1/dashboard/day-view<br/>**④ D2-4 现有端点变更**: POST /events增加input_scope字段 / PATCH /todos增加action_type+promisor_id+beneficiary_id / GET /entities返回值增加relationship_stage<br/>**⑤ D2-5 JWT认证加固**: Payload结构(sub/iat/exp/role) + 4项安全约束(Secret≥256/黑名单/Refresh旋转/CORS白名单)<br/>**⑥ D2-6 PII脱敏行为**: 标注7类端点执行redact_pii_from_text() + 5种PII掩码规则<br/>**⑦ D2-7 SC-01安全约束**: input_scope服务端强制校验，永远不以客户端值为准<br/>**⑧ D2-8 错误码扩展**: E1004 INVALID_INPUT_SCOPE(400) + E1005 OPTIMISTIC_LOCK_CONFLICT(409)<br/>**⑨ D2-9 数据导出API**: GET /api/v1/data/export?format=json\|csv（GDPR数据携带权，Phase 1提前）<br/>**⑩ D2-10 F-05暂停声明**: 商机匹配相关API标记Phase 2 |
| **v0.2.1** | **2026-06-05** | **[F-50新增] 语音助手API (Voice Assistant, Phase 1.1)：**<br/>**① F50-1 新增§3.12 Voice Assistant API章节**:<br/>　- POST /api/v1/voice/session — 创建语音问答会话(NLU意图识别→业务API调用→自然语言回答→TTS预生成)<br/>　- GET /api/v1/voice/tts/{session_id} — 获取预生成TTS音频(MP3流, Cache-Control private max-age=300)<br/>　- POST /api/v1/voice/feedback — 语音回答质量反馈(NLU模型优化用)<br/>**② F50-2 NLU意图枚举 VoiceIntent**: schedule_query/promise_tracker/relationship_status(P0) + schedule_range/action_suggestion(P1) + conversation_review/knowledge_retrieval(P2) + unclear<br/>**③ F50-3 VoiceSessionCreate/VoiceSessionResponse 数据模型定义**<br/>**④ F50-4 现有端点变更** — summary_level参数(三档: brief/detail/voice):<br/>　- GET /api/v1/dashboard/day-view(F-49) + natural_date参数("今天"|"明天"|"后天"|"本周"|"下游") → answer_paragraph字段<br/>　- GET /api/v1/persons/{id}/relationship-brief(F-47) → voice_summary字段<br/>　- GET /api/v1/todos → voice_summary字段<br/>**⑤ F50-5 PII脱敏清单扩展**: POST /voice/session(answer_text) + GET /voice/tts(音频内容)<br/>**关键约束**: 不存储原始音频; TTS输出PII脱敏; 所有端点JWT认证; TTL=5分钟音频缓存 |
| **v2.5** | **2026-06-06** | **Insight Engine + DataSourceAdapter API (v2.5)：**<br/>**① 新增§3.13 Insight Engine API**:<br/>　- GET /api/v1/todos?sort=smart — 按动态评分排序(默认)<br/>　- GET /api/v1/todos?sort=due_date — 按截止时间排序<br/>　- POST /api/v1/insights/calculate — 触发优先级重新计算(scope: all/entity/overdue, 限流10次/分)<br/>　- GET /api/v1/insights/feedback-stats — 获取隐式反馈统计(period: 1d/7d/30d)<br/>**② 新增§3.14 DataSourceAdapter API**:<br/>　- GET /api/v1/adapters — 列出已配置数据源(不返回config_encrypted)<br/>　- POST /api/v1/adapters — 添加新数据源配置(adapter_name枚举5值, config加密存储)<br/>　- POST /api/v1/adapters/{name}/sync — 手动触发同步(异步, 限流5次/分/适配器)<br/>　- DELETE /api/v1/adapters/{name} — 删除数据源配置(manual/voice不可删)<br/>**③ Todo响应schema新增字段**: completed_rank(完成序号) + dynamic_score(动态优先级分, 0-100)<br/>**④ OpenAPI YAML Todo schema更新**: 新增completed_rank(integer, nullable) + dynamic_score(number, 0-100, nullable) |
| **v2.6** | **2026-06-06** | **F-55/F-56 Insight Engine API扩展 (v2.6)：**<br/>**① §3.13 Insight Engine API新增2个端点**:<br/>　- GET /api/v1/todos/{todo_id}/priority-breakdown — 返回四维评分详情(urgency/importance/dependency/context)，含每个维度的原始得分和计算因子，支持可解释性面板<br/>　- GET /api/v1/users/{user_id}/upcoming-context — 返回未来24h即将见面的Entity及关联Todo，支持会前准备场景<br/>**② Todo schema breakdown字段扩展**: 新增dependency_raw(依赖分析原始因子, F-55) + context_raw(场景匹配原始因子, F-56)<br/>**③ OpenAPI YAML Todo schema更新**: 新增breakdown对象(含urgency/importance/dependency/context四维得分 + dependency_raw/context_raw原始因子) |
| **v2.7** | **2026-06-06** | **F-57/F-58 语义搜索与关联发现增强 API (v2.7)：**<br/>**① 新增§3.15 Semantic Search API**:<br/>　- POST /api/v1/search/semantic — 语义搜索(query+top_k+target_types+min_similarity，返回SearchResultItem列表含similarity/highlights)<br/>　- GET /api/v1/search/stats — 向量索引统计(total_embeddings/by_type/index_method/cache_size)<br/>　- POST /api/v1/search/reindex — 重建索引(full/incremental，异步202返回task_id，限流2次/小时)<br/>**② 新增SearchResult Schema**: SearchResultItem + SemanticSearchResponse + SearchStatsResponse + ReindexRequest + ReindexResponse<br/>**③ 数据隔离**: user_id从JWT提取，搜索结果按user_id过滤，忽略客户端传入的user_id** |

---

*最后更新: 2026-06-06*
