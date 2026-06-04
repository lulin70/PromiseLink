# EventLink API设计文档

> **版本**: v1.2  
> **日期**: 2026-06-03  
> **设计师**: 架构师 + 开发团队  
> **参考**: PRD v3.6, 技术设计 v1.7 §7

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

### 2.2 JWT认证

**Header格式**:
```http
Authorization: Bearer eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9...
```

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
  "metadata": {
    "card_image_url": "https://...",
    "language": "zh-CN"
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
      "created_at": "2026-06-03T10:00:00Z"
    }
  ]
}
```

#### 3.4.2 更新Todo状态

**端点**: `PATCH /api/v1/todos/{id}`

**请求**:
```json
{
  "status": "in_progress",
  "notes": "已联系张三"
}
```

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

## 4. 错误码定义

### 4.1 HTTP状态码

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

### 4.2 业务错误码

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
| E2000 | Token无效 | 401 |
| E2001 | Token过期 | 401 |
| E2002 | 权限不足 | 403 |
| E3000 | 限流超限 | 429 |
| E4000 | LLM调用失败 | 503 |
| E4001 | 数据库异常 | 500 |
| E5000 | 未知错误 | 500 |

---

## 5. 分页与排序

### 5.1 分页参数

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

### 5.2 排序参数

**查询参数**:
- `sort`: 排序字段（默认created_at）
- `order`: asc\|desc（默认desc）

**示例**: `GET /api/v1/todos?sort=priority&order=desc`

---

## 6. 限流策略

### 6.1 限流规则

> **设计原则**: EventLink定位为AI驱动的个人商务关系经营助手，采用单用户模式，无RBAC/多租户/团队协作，因此限流策略为统一单用户限流。

| 限流对象 | 限制 | 时间窗口 | 说明 |
|---------|------|---------|------|
| 单用户（统一） | 100次 | 1分钟 | 所有API端点统一限流，无角色区分 |

**PoC阶段说明**: PoC阶段限流可适当放宽，建议设置为200次/分钟，以便充分测试和验证功能。正式上线后恢复为100次/分钟。

### 6.2 限流响应

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

## 7. OpenAPI 3.0规范（YAML）

```yaml
openapi: 3.0.3
info:
  title: EventLink API
  version: 1.2.0
  description: EventLink AI驱动的个人商务关系经营助手API
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

## 8. API版本管理策略

> **7角色架构评审共识**：API版本管理是P3 Gate的必要条件，必须在P8前确定。

### 8.1 版本体系（三层版本号）

EventLink采用**语义化版本号（SemVer）**管理API演进：

| 层级 | 格式 | 含义 | 示例 | 变更触发 |
|------|------|------|------|---------|
| **主版本** | `/api/v{N}/` | URL路径版本，兼容性破坏时递增 | `/api/v1/` → `/api/v2/` | 删除字段/修改类型/修改URL结构 |
| **次版本** | `X-API-Version: {N}.{M}` | 响应头声明，新增功能时递增 | `1.0` → `1.1` → `1.2` | 新增端点/新增字段/新增枚举值 |
| **补丁版本** | `X-API-Patch: {N}.{M}.{P}` | 内部修复，客户端无感 | `1.2.0` → `1.2.1` | Bug修复/性能优化/文档修正 |

**当前版本**：主版本v1，次版本1.2，补丁版本1.2.0

### 8.2 版本协商机制

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

### 8.3 兼容性规则

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

### 8.5 多版本共存策略

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

### 8.6 数据库Schema版本管理

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

### 8.7 客户端SDK版本策略

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

### 8.8 版本变更日志

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

## 9. 性能监控

### 9.1 响应时间目标

| 端点类别 | P50 | P95 | P99 |
|---------|-----|-----|-----|
| 查询类（GET） | <50ms | <200ms | <500ms |
| 创建类（POST） | <100ms | <300ms | <1s |
| 复杂查询（图谱） | <500ms | <2s | <5s |

### 9.2 监控指标

```python
# 响应头包含性能指标
X-Response-Time: 145ms
X-DB-Time: 23ms
X-LLM-Time: 95ms
X-Cache-Hit: true
```

---

## 10. 版本历史

| 版本 | 日期 | 变更 |
|------|------|------|
| v1.0 | 2026-06-02 | 初始版本 |
| v1.1 | 2026-06-03 | Todos类型扩展为6种（opportunity/risk/context/action/pending_confirm/resource_maint）；添加莫兰迪色系morandi_color字段；Entities API添加resource_sensitivity字段及sensitivity端点；新增Resources API（资源管理+六维匹配算法）；限流策略改为单用户统一限流（移除RBAC三级）；OpenAPI规范同步更新 |
| v1.2 | 2026-06-03 | Todo类型重命名（opportunity→cooperation_signal, context→care, action→promise, pending_confirm→followup, resource_maint→help）；Entities API新增concern/promise/contribution字段及三个PATCH端点（concern/promise/contribution）；Todos API新增promise/care/cooperation_signal类型详细示例；新增§3.8 AI输出语言规则（confidence_level/is_ai_inference/requires_confirmation）；OpenAPI规范同步更新（TodoType枚举、新增Concern/Promise/Contribution/AIInferenceMarker schema） |
| v1.3 | 2026-06-03 | §8 API版本管理策略全面补齐：三层版本号（SemVer）+ 版本协商机制 + 兼容性规则 + 废弃流程（12个月过渡期）+ 多版本共存（FastAPI路由层）+ Alembic数据库迁移策略 + 客户端SDK版本策略 + 版本变更日志规范 |

---

*最后更新: 2026-06-03*
