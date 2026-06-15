# 🤖 Multi-Agent 协作结果

**任务**: PromiseLink 架构重新设计(客户视角驱动)

⚠️ 核心原则:架构从用户场景倒推,不是从技术正推!
先定义用户看到的页面和操作,再设计支撑这些页面的架构。

基于P1评审发现的问题,重新设计架构。关键要求:

1. 【页面架构】先定义前端页面结构:
 - 首页/仪表盘:用户第一眼看到什么?今日Todo?最近事件?快捷操作?
 - Todo列表页:信息型/行动型怎么分?筛选?排序?
 - 事件详情页:原始文本+AI提取结果+关联Todo+操作按钮
 - 实体详情页:属性+来源标记+关联实体+编辑入口
 - 数据管理中心:事件/实体/关联/标签的浏览和管理
 - 名片扫描结果页:扫描后即时展示什么?
 - 会议纪要结果页:4种类型的差异化展示
 - 搜索页:模糊查找+交叉检索

2. 【用户操作流程】定义核心操作链路:
 - 扫描名片→看到结果→执行行动→标记完成
 - 上传会议纪要→看到分析→确认/修正→执行行动项
 - 浏览数据→发现错误→修正→验证修正效果
 - 搜索→找到实体→查看关联→添加/删除关联

3. 【API设计】从页面操作倒推API:
 - 每个页面需要哪些API?
 - 用户操作触发哪些API调用?
 - API响应格式是否匹配页面展示需求?

4. 【技术架构】支撑上述页面的后端架构:
 - 三层模型(L1/L2/L3)的解耦设计
 - 4条事件管线的路由和调度
 - 实体归一5步算法
 - 关联发现3步算法
 - Todo生成与追踪引擎
 - 数据模型(Entity/Association/Event/Todo)

5. 【性能保障】从用户体验倒推性能要求:
 - 名片扫描结果页加载<3s
 - Todo列表加载<1s
 - 实体详情页加载<500ms
 - 会议纪要处理<30s(后台异步)

技术栈:FastAPI + PostgreSQL 15 + Redis 7 + NetworkX + Moka AI(Claude Sonnet) + spaCy

【各角色评审要求】
每个角色必须回答:这个架构能让用户顺畅完成核心操作吗?哪里会卡住?

架构师:架构是否支撑所有页面和操作?瓶颈在哪?
PM:页面结构是否覆盖所有用户故事?有没有遗漏场景?
安全:用户隐私数据在哪个环节最危险?
测试:端到端用户操作路径是否可测?
开发者:实现复杂度?3周PoC能做多少?
DevOps:部署方案?监控指标是否反映用户体验?
UI:页面间导航是否流畅?信息架构是否合理?


P1评审共识摘要:
任务「PromiseLink PRD v1.6 客户视角评审 ⚠️ 核心要求:每个角色问自己:如果我是用户,我拿到这个产品,我能做什么?我缺什么?哪里不顺? 产品定位:E」已完成多Agent协作。
参与角色: 产品经理, UI设计师, 测试专家, 架构师, 开发者, 运维工程师, 安全专家 (7个)
执行结果: 7/7 个Worker成功
协作耗时: 119.65s
Scratchpad关键发现: # Scratchpad Summary (scratchpad-20260601-180503)
**Total entries**: 7 | **Active findings**: 7 | **Conflicts**: 0

## 🔍 Key Findings (7)
- [architect-e3622a/architect] # PromiseLink PRD v1.6 客户视角评审 - 系
**状态**: ✅ 成功
**耗时**: 142.88s
**参与角色**: product-manager, devops, ui-designer, architect, solo-coder, tester, security

## 📋 执行摘要
任务「PromiseLink 架构重新设计(客户视角驱动)

⚠️ 核心原则:架构从用户场景倒推,不是从技术正推!
先定义用户看到的页面和操作,再设计支撑这些页面的架构。」已完成多Agent协作。
参与角色: 产品经理, 运维工程师, UI设计师, 架构师, 开发者, 测试专家, 安全专家 (7个)
执行结果: 7/7 个Worker成功
协作耗时: 111.80s
Scratchpad关键发现: # Scratchpad Summary (scratchpad-20260601-180503)
**Total entries**: 15 | **Active findings**: 14 | **Conflicts**: 0

## 🔍 Key Findings (14)
- [ui-designer-30adfb/ui-designer] # PromiseLink 架构重新设计(客户视角驱

## 👥 各角色产出

### 🏗️ 架构师 [✅]
---
# PromiseLink 架构重新设计(客户视角驱动)

## 第一步:用户页面与操作流程定义

### 1. 页面架构(用户视角)

#### 1.1 首页/仪表盘
**用户第一眼看到:**
- 今日待办(Today's Todos):信息型(蓝色)vs 行动型(红色)分类显示
- 最近事件流(Recent Events):最近7天的事件时间线
- 快捷操作区:
  - 扫描名片
  - 上传会议纪要
  - 快速搜索
- 统计卡片:待办数量、实体总数、本周新增关联

**关键操作:**
- 点击Todo → 跳转Todo详情/关联事件
- 点击事件 → 跳转事件详情页
- 快捷扫描 → 直接进入扫描流程

#### 1.2 Todo列表页
**信息架构:**
```
[筛选栏] 类型(信息型/行动型) | 状态(待办/进行中/已完成) | 来源(名片/会议/邮件/聊天)
[排序] 优先级 | 截止日期 | 创建时间

[Todo卡片]
├─ 标题 + 类型标签(信息型/行动型)
├─ 来源事件(可点击跳转)
├─ 关联实体(人/组织/项目)
├─ 截止日期 + 优先级
└─ 操作按钮:[标记完成] [编辑] [删除]
```

**关键操作:**
- 标记完成 → 状态变更 + 完成时间记录
- 点击来源事件 → 跳转事件详情页
- 点击关联实体 → 跳转实体详情页

#### 1.3 事件详情页
**信息层次:**
```
[事件头部]
├─ 事件类型标签(名片/会议/邮件/聊天)
├─ 创建时间 + 来源标记
└─ 操作:[重新处理] [删除]

[原始内容区]
├─ 原始文本/图片(可展开/折叠)
└─ 原始数据完整性标记

[AI提取结果]
├─ 提取的实体列表(可点击跳转)
├─ 提取的关联关系(可视化图)
└─ 置信度标记

[生成的Todos]
├─ Todo列表(按类型分组)
└─ 操作:[添加Todo] [批量完成]

[关联数据]
├─ 关联的其他事件
└─ 关联的实体网络
```

**关键操作:**
- 点击实体 → 跳转实体详情页
- 修正提取错误 → 触发实体归一重算
- 添加Todo → 打开Todo创建表单

#### 1.4 实体详情页
**信息架构:**
```
[实体头部]
├─ 实体类型(人/组织/项目/地点)
├─ 主属性(姓名/公司名/项目名)
└─ 操作:[编辑] [合并] [删除]

[属性面板]
├─ 所有属性列表
├─ 来源标记(哪个事件提取的)
└─ 置信度标记

[关联实体网络]
├─ 关系图可视化(NetworkX渲染)
├─ 关联类型标签(works_at/reports_to/collaborates_with)
└─ 操作:[添加关联] [删除关联]

[来源事件]
├─ 提到该实体的所有事件
└─ 时间线展示

[关联Todos]
└─ 涉及该实体的所有待办
```

**关键操作:**
- 编辑属性 → 触发实体归一重算
- 合并实体 → 选择目标实体 → 确认合并
- 添加关联 → 搜索目标实体 → 选择关系类型 → 确认

#### 1.5 数据管理中心
**四个Tab:**
```
[事件管理]
├─ 事件列表(按类型/时间筛选)
├─ 批量操作:[重新处理] [删除]
└─ 统计:处理成功率、平均处理时间

[实体管理]
├─ 实体列表(按类型筛选)
├─ 批量操作:[合并] [删除]
└─ 统计:实体总数、孤立实体数

[关联管理]
├─ 关联列表(按类型筛选)
├─ 批量操作:[删除]
└─ 统计:关联总数、关联密度

[标签管理]
├─ 标签列表
├─ 批量操作:[合并] [删除]
└─ 统计:标签使用频率
```

#### 1.6 名片扫描结果页
**即时展示:**
```
[扫描状态]
├─ 进度条:OCR → 实体提取 → 关联发现 → Todo生成
└─ 预计剩余时间

[扫描结果](3秒内加载)
├─ 识别的联系人信息
├─ 自动生成的Todos(行动型优先)
├─ 发现的关联(如果该人已存在)
└─ 操作:[确认] [修正] [保存到通讯录]
```

**关键操作:**
- 修正信息 → 实时更新实体属性
- 确认 → 保存实体 + 创建Todos
- 保存到通讯录 → 导出vCard格式

#### 1.7 会议纪要结果页
**4种类型差异化展示:**

**A. 一对一会议:**
```
[会议信息]
├─ 参与人(2人)
├─ 会议时间
└─ 会议主题

[关键讨论点]
├─ 讨论主题列表
└─ 每个主题的决策/行动项

[行动项Todos]
├─ 按负责人分组
└─ 截止日期标记
```

**B. 团队会议:**
```
[会议信息]
├─ 参与人列表(>2人)
├─ 会议时间
└─ 会议主题

[议程与决策]
├─ 议程项列表
├─ 每项的讨论结果
└─ 投票/共识标记

[行动项分配]
├─ 按负责人分组的Todos
└─ 依赖关系标记
```

**C. 客户会议:**
```
[会议信息]
├─ 客户方参与人
├─ 我方参与人
├─ 会议时间
└─ 会议目的

[客户需求]
├─ 需求列表
├─ 优先级标记
└─ 承诺的交付物

[跟进行动]
├─ 内部行动项
├─ 客户侧行动项
└─ 下次会议安排
```

**D. 头脑风暴:**
```
[会议信息]
├─ 参与人
├─ 会议时间
└─ 讨论主题

[创意列表]
├─ 所有提出的想法
├─ 想法分类
└─ 投票/评分

[后续行动]
├─ 需要验证的想法
├─ 需要原型的想法
└─ 需要研究的想法
```

#### 1.8 搜索页
**搜索能力:**
```
[搜索框]
├─ 全文搜索(事件/实体/Todo)
├─ 高级筛选:类型/时间范围/标签
└─ 搜索历史

[搜索结果]
├─ 按相关性排序
├─ 结果类型分组(事件/实体/Todo)
├─ 高亮匹配文本
└─ 快速操作按钮

[交叉检索]
├─ "找到所有与[实体A]相关的[实体B]"
├─ "找到[时间范围]内的[事件类型]"
└─ "找到[人]负责的所有待办"
```

---

## 第二步:核心用户操作流程

### 流程1:扫描名片 → 执行行动
```
用户操作                    系统响应                      页面跳转
─────────────────────────────────────────────────────────────
1. 点击"扫描名片"          → 打开相机/上传界面           → 扫描页
2. 拍照/上传图片           → 显示进度条(OCR中)          → 结果页(加载中)
3. 等待3秒                 → 显示识别结果               → 结果页(完成)
   - 联系人信息
   - 自动生成的Todos
   - 发现的关联
4. 确认/修正信息           → 保存实体 + 创建Todos       → Todo列表页
5. 点击行动型Todo          → 显示Todo详情               → Todo详情页
6. 标记完成                → 更新状态 + 记录完成时间    → Todo列表页(刷新)
```

**API调用链:**
```
POST /api/v1/events/business-card
  ↓ (异步处理)
GET /api/v1/events/{event_id}/status (轮询)
  ↓ (完成后)
GET /api/v1/events/{event_id}/result
  ↓ (用户确认)
POST /api/v1/entities (批量创建)
POST /api/v1/todos (批量创建)
  ↓ (用户操作)
PATCH /api/v1/todos/{todo_id}/complete
```

### 流程2:上传会议纪要 → 确认/修正 → 执行行动项
```
用户操作                    系统响应                      页面跳转
─────────────────────────────────────────────────────────────
1. 点击"上传会议纪要"      → 打开文件选择器             → 上传页
2. 选择文件(txt/docx/pdf)  → 显示上传进度               → 结果页(加载中)
3. 等待30秒(后台处理)      → 显示处理进度               → 结果页(处理中)
   - 识别会议类型
   - 提取参与人
   - 生成行动项
4. 查看结果                → 显示差异化结果页           → 会议结果页
   - 一对一/团队/客户/头脑风暴
5. 修正错误信息            → 实时更新实体/关联          → 会议结果页(刷新)
6. 确认                    → 保存所有数据               → Todo列表页
7. 执行行动项              → 标记完成                   → Todo详情页
```

**API调用链:**
```
POST /api/v1/events/meeting-minutes
  ↓ (异步处理)
GET /api/v1/events/{event_id}/status (轮询)
  ↓ (完成后)
GET /api/v1/events/{event_id}/result
  ↓ (用户修正)
PATCH /api/v1/entities/{entity_id}
PATCH /api/v1/associations/{association_id}
  ↓ (用户确认)
POST /api/v1/events/{event_id}/confirm
  ↓ (用户操作)
PATCH /api/v1/todos/{todo_id}/complete
```

### 流程3:浏览数据 → 发现错误 → 修正 → 验证
```
用户操作                    系统响应                      页面跳转
─────────────────────────────────────────────────────────────
1. 进入数据管理中心        → 显示实体列表               → 数据管理页
2. 点击某个实体            → 显示实体详情               → 实体详情页
3. 发现属性错误            → 点击编辑按钮               → 编辑模式
4. 修改属性                → 实时验证 + 保存            → 实体详情页(刷新)
5. 系统触发归一重算        → 后台更新关联关系           → (后台)
6. 查看关联网络            → 显示更新后的关系图         → 实体详情页(刷新)
7. 验证修正效果            → 检查关联事件/Todos         → 相关页面
```

**API调用链:**
```
GET /api/v1/entities
  ↓
GET /api/v1/entities/{entity_id}
  ↓ (用户编辑)
PATCH /api/v1/entities/{entity_id}
  ↓ (触发归一)
POST /api/v1/entities/{entity_id}/recalculate (后台)
  ↓ (验证)
GET /api/v1/entities/{entity_id}/associations
GET /api/v1/entities/{entity_id}/events
```

### 流程4:搜索 → 找到实体 → 查看关联 → 添加/删除关联
```
用户操作                    系统响应                      页面跳转
─────────────────────────────────────────────────────────────
1. 在搜索框输入关键词      → 实时搜索建议               → 搜索页
2. 按回车搜索              → 显示搜索结果               → 搜索结果页
3. 点击某个实体            → 显示实体详情               → 实体详情页
4. 查看关联网络            → 显示关系图                 → 实体详情页
5. 点击"添加关联"          → 打开关联选择器             → 模态框
6. 搜索目标实体            → 显示候选实体               → 模态框
7. 选择关系类型            → 显示关系类型列表           → 模态框
8. 确认添加                → 保存关联 + 更新图          → 实体详情页(刷新)
```

**API调用链:**
```
GET /api/v1/search?q={keyword}
  ↓
GET /api/v1/entities/{entity_id}
  ↓
GET /api/v1/entities/{entity_id}/associations
  ↓ (添加关联)
GET /api/v1/entities/search?q={target_keyword}
POST /api/v1/associations
  ↓ (刷新)
GET /api/v1/entities/{entity_id}/associations
```

---

## 第三步:API设计(从页面操作倒推)

### 3.1 事件处理API

#### POST /api/v1/events/business-card
**请求:**
```json
{
  "image": "base64_encoded_image",
  "metadata": {
    "source": "mobile_app",
    "timestamp": "2025-06-01T10:30:00Z"
  }
}
```

**响应:**
```json
{
  "event_id": "evt_abc123",
  "status": "processing",
  "estimated_time": 3
}
```

#### GET /api/v1/events/{event_id}/status
**响应:**
```json
{
  "event_id": "evt_abc123",
  "status": "completed",
  "progress": 100,
  "stages": {
    "ocr": "completed",
    "entity_extraction": "completed",
    "association_discovery": "completed",
    "todo_generation": "completed"
  }
}
```

#### GET /api/v1/events/{event_id}/result
**响应(名片):**
```json
{
  "event_id": "evt_abc123",
  "event_type": "business_card",
  "raw_content": {
    "image_url": "https://...",
    "ocr_text": "John Doe\nSenior Engineer\nAcme Corp\n..."
  },
  "extracted_entities": [
    {
      "entity_id": "ent_person_001",
      "type": "person",
      "attributes": {
        "name": "John Doe",
        "title": "Senior Engineer",
        "email": "john@acme.com",
        "phone": "+1-555-0100"
      },
      "confidence": 0.95
    },
    {
      "entity_id": "ent_org_001",
      "type": "organization",
      "attributes": {
        "name": "Acme Corp"
      },
      "confidence": 0.98
    }
  ],
  "associations": [
    {
      "association_id": "assoc_001",
      "source_entity_id": "ent_person_001",
      "target_entity_id": "ent_org_001",
      "relationship_type": "works_at",
      "confidence": 0.92
    }
  ],
  "generated_todos": [
    {
      "todo_id": "todo_001",
      "type": "action",
      "title": "Follow up with John Doe",
      "description": "Send introduction email to john@acme.com",
      "priority": "high",
      "due_date": "2025-06-03T17:00:00Z"
    },
    {
      "todo_id": "todo_002",
      "type": "information",
      "title": "Add John Doe to CRM",
      "description": "Update contact database with new connection",
      "priority": "medium"
    }
  ]
}
```

#### POST /api/v1/events/meeting-minutes
**请求:**
```json
{
  "file": "multipart/form-data",
  "metadata": {
    "meeting_type": "auto_detect",
    "meeting_date": "2025-06-01T14:00:00Z"
  }
}
```

**响应:**
```json
{
  "event_id": "evt_meeting_001",
  "status": "processing",
  "estimated_time": 30
}
```

#### GET /api/v1/events/{event_id}/result (会议纪要)
**响应(团队会议):**
```json
{
  "event_id": "evt_meeting_001",
  "event_type": "meeting_minutes",
  "meeting_type": "team_meeting",
  "raw_content": {
    "file_url": "https://...",
    "text": "Team Meeting - Q2 Planning\n..."
  },
  "extracted_entities": [
    {
      "entity_id": "ent_person_002",
      "type": "person",
      "attributes": {"name": "Alice Smith"},
      "confidence": 0.96
    },
    {
      "entity_id": "ent_person_003",
      "type": "person",
      "attributes": {"name": "Bob Johnson"},
      "confidence": 0.94
    },
    {
      "entity_id": "ent_project_001",
      "type": "project",
      "attributes": {"name": "Q2 Product Launch"},
      "confidence": 0.89
    }
  ],
  "meeting_structure": {
    "participants": ["ent_person_002", "ent_person_003"],
    "agenda_items": [
      {
        "topic": "Q2 Product Launch Timeline",
        "discussion": "Agreed to move launch date to June 15",
        "decision": "Launch date: June 15, 2025",
        "action_items": ["todo_003", "todo_004"]
      }
    ]
  },
  "generated_todos": [
    {
      "todo_id": "todo_003",
      "type": "action",
      "title": "Finalize product specs",
      "assignee": "ent_person_002",
      "due_date": "2025-06-05T17:00:00Z",
      "priority": "high"
    },
    {
      "todo_id": "todo_004",
      "type": "action",
      "title": "Schedule launch meeting",
      "assignee": "ent_person_003",
      "due_date": "2025-06-08T17:00:00Z",
      "priority": "medium"
    }
  ]
}
```

### 3.2 Todo管理API

#### GET /api/v1/todos
**请求参数:**
```
?type=action|information
&status=pending|in_progress|completed
&source=business_card|meeting|email|chat
&sort=priority|due_date|created_at
&page=1&page_size=20
```

**响应:**
```json
{
  "todos": [
    {
      "todo_id": "todo_001",
      "type": "action",
      "title": "Follow up with John Doe",
      "description": "Send introduction email",
      "status": "pending",
      "priority": "high",
      "due_date": "2025-06-03T17:00:00Z",
      "source_event": {
        "event_id": "evt_abc123",
        "event_type": "business_card"
      },
      "related_entities": [
        {"entity_id": "ent_person_001", "name": "John Doe"}
      ],
      "created_at": "2025-06-01T10:35:00Z"
    }
  ],
  "pagination": {
    "total": 45,
    "page": 1,
    "page_size": 20,
    "total_pages": 3
  }
}
```

#### PATCH /api/v1/todos/{todo_id}/complete
**请求:**
```json
{
  "completion_note": "Email sent, waiting for response"
}
```

**响应:**
```json
{
  "todo_id": "todo_001",
  "status": "completed",
  "completed_at": "2025-06-02T09:15:00Z",
  "completion_note": "Email sent, waiting for response"
}
```

### 3.3 实体管理API

#### GET /api/v1/entities/{entity_id}
**响应:**
```json
{
  "entity_id": "ent_person_001",
  "type": "person",
  "attributes": {
    "name": "John Doe",
    "title": "Senior Engineer",
    "email": "john@acme.com",
    "phone": "+1-555-0100",
    "company": "Acme Corp"
  },
  "metadata": {
    "created_at": "2025-06-01T10:35:00Z",
    "updated_at": "2025-06-01T10:35:00Z",
    "confidence": 0.95,
    "source_events": ["evt_abc123"]
  },
  "associations": [
    {
      "association_id": "assoc_001",
      "target_entity": {
        "entity_id": "ent_org_001",
        "type": "organization",
        "name": "Acme Corp"
      },
      "relationship_type": "works_at",
      "confidence": 0.92
    }
  ],
  "related_todos": [
    {
      "todo_id": "todo_001",
      "title": "Follow up with John Doe",
      "status": "pending"
    }
  ],
  "source_events": [
    {
      "event_id": "evt_abc123",
      "event_type": "business_card",
      "created_at": "2025-06-01T10:30:00Z"
    }
  ]
}
```

#### PATCH /api/v1/entities/{entity_id}
**请求:**
```json
{
  "attributes": {
    "title": "Lead Engineer",
    "phone": "+1-555-0101"
  }
}
```

**响应:**
```json
{
  "entity_id": "ent_person_001",
  "updated_attributes": ["title", "phone"],
  "recalculation_triggered": true,
  "recalculation_job_id": "job_recalc_001"
}
```

#### GET /api/v1/entities/{entity_id}/associations
**响应:**
```json
{
  "entity_id": "ent_person_001",
  "associations": [
    {
      "association_id": "assoc_001",
      "target_entity": {
        "entity_id": "ent_org_001",
        "type": "organization",
        "name": "Acme Corp"
      },
      "relationship_type": "works_at",
      "confidence": 0.92,
      "source_events": ["evt_abc123"]
    }
  ],
  "network_graph": {
    "nodes": [
      {"id": "ent_person_001", "type": "person", "label": "John Doe"},
      {"id": "ent_org_001", "type": "organization", "label": "Acme Corp"}
    ],
    "edges": [
      {
        "source": "ent_person_001",
        "target": "ent_org_001",
        "type": "works_at"
      }
    ]
  }
}
```

### 3.4 关联管理API

#### POST /api/v1/associations
**请求:**
```json
{
  "source_entity_id": "ent_person_001",
  "target_entity_id": "ent_person_002",
  "relationship_type": "collaborates_with",
  "metadata": {
    "note": "Working together on Q2 project"
  }
}
```

**响应:**
```json
{
  "association_id": "assoc_002",
  "source_entity_id": "ent_person_001",
  "target_entity_id": "ent_person_002",
  "relationship_type": "collaborates_with",
  "confidence": 1.0,
  "created_at": "2025-06-02T10:00:00Z"
}
```

#### DELETE /api/v1/associations/{association_id}
**响应:**
```json
{
  "association_id": "assoc_002",
  "deleted": true,
  "affected_entities": ["ent_person_001", "ent_person_002"]
}
```

### 3.5 搜索API

#### GET /api/v1/search
**请求参数:**
```
?q=john
&type=entity|event|todo
&entity_type=person|organization|project|location
&time_range=last_7_days|last_30_days|all
&page=1&page_size=20
```

**响应:**
```json
{
  "query": "john",
  "results": {
    "entities": [
      {
        "entity_id": "ent_person_001",
        "type": "person",
        "name": "John Doe",
        "highlight": "<mark>John</mark> Doe",
        "relevance_score": 0.98
      }
    ],
    "events": [
      {
        "event_id": "evt_abc123",
        "event_type": "business_card",
        "snippet": "Business card from <mark>John</mark> Doe",
        "relevance_score": 0.85
      }
    ],
    "todos": [
      {
        "todo_id": "todo_001",
        "title": "Follow up with <mark>John</mark> Doe",
        "relevance_score": 0.92
      }
    ]
  },
  "pagination": {
    "total": 3,
    "page": 1,
    "page_size": 20
  }
}
```

#### GET /api/v1/search/cross
**请求参数:**
```
?entity_a=ent_person_001
&entity_b_type=organization
&relationship_type=works_at
```

**响应:**
```json
{
  "query": {
    "entity_a": "ent_person_001",
    "entity_b_type": "organization",
    "relationship_type": "works_at"
  },
  "results": [
    {
      "entity_id": "ent_org_001",
      "type": "organization",
      "name": "Acme Corp",
      "relationship": "works_at",
      "confidence": 0.92
    }
  ]
}
```

---

## 第四步:技术架构(支撑页面的后端设计)

### 4.1 三层架构模型

```
┌─────────────────────────────────────────────────────────────┐
│                        L1: API Layer                         │
│  (FastAPI Routes, Request Validation, Response Formatting)   │
└─────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────┐
│                    L2: Business Logic Layer                  │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐      │
│  │ Event Router │  │ Entity       │  │ Todo         │      │
│  │ (4 Pipelines)│  │ Unification  │  │ Engine       │      │
│  └──────────────┘  └──────────────┘  └──────────────┘      │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐      │
│  │ Association  │  │ Search       │  │ Notification │      │
│  │ Discovery    │  │ Engine       │  │ Service      │      │
│  └──────────────┘  └──────────────┘  └──────────────┘      │

### 🤖 solo [✅]
---
# PromiseLink 架构重新设计(客户视角驱动)

## 一、用户视角出发点

作为开发者,我首先要问:**用户拿到这个产品,第一步做什么?**

### 核心用户旅程
1. **扫描名片** → 立即看到联系人信息 → 看到"需要跟进"提示 → 点击完成
2. **上传会议纪要** → 等待30秒 → 看到行动项列表 → 逐个执行
3. **打开App** → 看到今日待办 → 点击查看详情 → 标记完成
4. **搜索联系人** → 看到关联的所有事件 → 发现需要修正的信息 → 编辑保存

## 二、页面架构设计(从用户第一眼看到的开始)

### 2.1 首页/仪表盘 (`/`)
**用户第一眼看到:**
```
┌─────────────────────────────────────┐
│ 今日待办 (3)                    [全部] │
├─────────────────────────────────────┤
│ 🔴 跟进张三 - 讨论合作方案          │
│    来源: 会议纪要 2024-01-15        │
│ 🟡 回复李四邮件                     │
│    来源: 名片扫描 2024-01-14        │
│ 🟢 准备周报                         │
│    来源: 周会纪要 2024-01-13        │
├─────────────────────────────────────┤
│ 最近事件 (5)                    [全部] │
├─────────────────────────────────────┤
│ 📄 销售会议纪要 - 30分钟前          │
│ 👤 王五名片 - 2小时前               │
│ 📧 客户邮件 - 昨天                  │
├─────────────────────────────────────┤
│ 快捷操作                            │
│ [扫描名片] [上传纪要] [搜索]        │
└─────────────────────────────────────┘
```

**API需求:**
- `GET /api/v1/dashboard/summary` - 获取仪表盘数据
  ```json
  {
    "todos_today": [...],
    "recent_events": [...],
    "stats": {
      "pending_todos": 3,
      "total_entities": 156,
      "total_events": 89
    }
  }
  ```

### 2.2 Todo列表页 (`/todos`)
**用户操作:**
- 切换信息型/行动型
- 按优先级/时间排序
- 筛选来源(名片/会议/邮件/微信)
- 批量标记完成

```
┌─────────────────────────────────────┐
│ [行动型] [信息型]  排序:[优先级▼]   │
├─────────────────────────────────────┤
│ 筛选: [全部来源▼] [全部状态▼]      │
├─────────────────────────────────────┤
│ ☐ 🔴 跟进张三 - 讨论合作方案        │
│    📄 会议纪要 | 2024-01-15 14:30   │
│    [查看详情] [标记完成]            │
├─────────────────────────────────────┤
│ ☐ 🟡 回复李四邮件                   │
│    👤 名片扫描 | 2024-01-14 10:20   │
│    [查看详情] [标记完成]            │
└─────────────────────────────────────┘
```

**API需求:**
- `GET /api/v1/todos?type=action&sort=priority&source=meeting&status=pending`
- `PATCH /api/v1/todos/{id}/complete`
- `POST /api/v1/todos/batch-complete` - 批量完成

### 2.3 事件详情页 (`/events/{id}`)
**用户看到:**
- 原始文本(可折叠)
- AI提取结果(高亮显示)
- 关联的Todo列表
- 关联的实体(人/组织/地点)
- 操作按钮(编辑/删除/重新分析)

```
┌─────────────────────────────────────┐
│ 📄 销售会议纪要                     │
│ 2024-01-15 14:30 | 会议类型         │
├─────────────────────────────────────┤
│ [原始文本▼]                         │
│ 今天与张三讨论了Q1合作方案...       │
├─────────────────────────────────────┤
│ AI提取结果                          │
│ 参与人: 张三(ABC公司), 李四(我方)  │
│ 决策: 下周一前提交方案              │
│ 行动项: 跟进张三确认细节            │
├─────────────────────────────────────┤
│ 关联Todo (2)                        │
│ ☐ 跟进张三 - 讨论合作方案           │
│ ☐ 准备Q1方案文档                    │
├─────────────────────────────────────┤
│ 关联实体 (3)                        │
│ 👤 张三 (ABC公司 销售总监)          │
│ 🏢 ABC公司                          │
│ 📍 北京办公室                       │
├─────────────────────────────────────┤
│ [编辑] [删除] [重新分析]            │
└─────────────────────────────────────┘
```

**API需求:**
- `GET /api/v1/events/{id}` - 完整事件数据
- `POST /api/v1/events/{id}/reanalyze` - 重新分析
- `PATCH /api/v1/events/{id}` - 编辑事件

### 2.4 实体详情页 (`/entities/{id}`)
**用户操作:**
- 查看实体属性
- 查看来源标记(哪些事件提到过)
- 查看关联实体(同事/公司/项目)
- 编辑属性
- 合并重复实体

```
┌─────────────────────────────────────┐
│ 👤 张三                             │
│ ABC公司 | 销售总监                  │
├─────────────────────────────────────┤
│ 基本信息                            │
│ 手机: 138****1234                   │
│ 邮箱: zhangsan@abc.com              │
│ 微信: zhangsan_abc                  │
├─────────────────────────────────────┤
│ 来源标记 (3次提及)                  │
│ 📄 销售会议纪要 - 2024-01-15        │
│ 👤 名片扫描 - 2024-01-10            │
│ 📧 邮件往来 - 2024-01-08            │
├─────────────────────────────────────┤
│ 关联实体                            │
│ 🏢 ABC公司 (所属公司)               │
│ 👤 李四 (同事关系)                  │
│ 📁 Q1合作项目 (参与项目)            │
├─────────────────────────────────────┤
│ [编辑] [合并重复] [删除]            │
└─────────────────────────────────────┘
```

**API需求:**
- `GET /api/v1/entities/{id}` - 实体详情
- `GET /api/v1/entities/{id}/mentions` - 来源事件列表
- `GET /api/v1/entities/{id}/associations` - 关联实体
- `PATCH /api/v1/entities/{id}` - 编辑实体
- `POST /api/v1/entities/merge` - 合并实体

### 2.5 名片扫描结果页 (`/scan/result/{scan_id}`)
**用户期望: 扫描后3秒内看到结果**

```
┌─────────────────────────────────────┐
│ ✅ 名片识别完成                     │
├─────────────────────────────────────┤
│ 👤 张三                             │
│ ABC公司 | 销售总监                  │
│ 📞 138****1234                      │
│ 📧 zhangsan@abc.com                 │
├─────────────────────────────────────┤
│ 🤖 AI建议                           │
│ • 发现重复: 可能与"张三(ABC)"重复  │
│ • 建议行动: 添加到CRM系统           │
│ • 关联项目: Q1合作项目              │
├─────────────────────────────────────┤
│ [保存] [编辑] [重新扫描]            │
└─────────────────────────────────────┘
```

**API需求:**
- `POST /api/v1/scan/business-card` - 上传名片图片
- `GET /api/v1/scan/{scan_id}/status` - 轮询处理状态
- `GET /api/v1/scan/{scan_id}/result` - 获取结果

### 2.6 会议纪要结果页 (`/meeting/result/{meeting_id}`)
**4种类型差异化展示:**

**销售会议:**
```
┌─────────────────────────────────────┐
│ 📊 销售会议分析                     │
├─────────────────────────────────────┤
│ 客户信息                            │
│ 👤 张三 (ABC公司)                   │
│ 需求: Q1合作方案                    │
│ 预算: 50-100万                      │
├─────────────────────────────────────┤
│ 行动项 (3)                          │
│ ☐ 下周一前提交方案                  │
│ ☐ 跟进技术对接                      │
│ ☐ 准备报价单                        │
├─────────────────────────────────────┤
│ 下次跟进: 2024-01-22                │
└─────────────────────────────────────┘
```

**技术会议:**
```
┌─────────────────────────────────────┐
│ 💻 技术会议分析                     │
├─────────────────────────────────────┤
│ 技术决策                            │
│ • 采用FastAPI框架                   │
│ • 使用PostgreSQL 15                 │
│ • Redis做缓存                       │
├─────────────────────────────────────┤
│ 待解决问题 (2)                      │
│ ⚠️ 性能瓶颈: 实体归一算法           │
│ ⚠️ 数据一致性: 并发写入             │
├─────────────────────────────────────┤
│ 行动项 (4)                          │
│ ☐ 完成架构设计文档                  │
│ ☐ 搭建开发环境                      │
└─────────────────────────────────────┘
```

**API需求:**
- `POST /api/v1/meeting/analyze` - 上传会议纪要
- `GET /api/v1/meeting/{id}/status` - 处理状态(异步)
- `GET /api/v1/meeting/{id}/result` - 获取分析结果

### 2.7 数据管理中心 (`/data`)
**用户操作:**
- 浏览所有事件/实体/关联
- 批量操作(删除/导出)
- 数据质量检查(重复/缺失)

```
┌─────────────────────────────────────┐
│ [事件] [实体] [关联] [标签]         │
├─────────────────────────────────────┤
│ 实体列表 (156)                      │
│ 搜索: [____] 类型:[全部▼]          │
├─────────────────────────────────────┤
│ ☐ 👤 张三 (ABC公司)                 │
│    3次提及 | 2个关联                │
│ ☐ 👤 李四 (我方)                    │
│    5次提及 | 4个关联                │
│ ☐ 🏢 ABC公司                        │
│    8次提及 | 6个关联                │
├─────────────────────────────────────┤
│ [批量删除] [导出CSV] [质量检查]     │
└─────────────────────────────────────┘
```

**API需求:**
- `GET /api/v1/data/entities?page=1&limit=20&type=person`
- `GET /api/v1/data/events?page=1&limit=20&source=meeting`
- `POST /api/v1/data/quality-check` - 数据质量检查
- `POST /api/v1/data/export` - 导出数据

### 2.8 搜索页 (`/search`)
**用户操作:**
- 模糊搜索(名字/公司/关键词)
- 交叉检索(找到张三相关的所有会议)
- 时间范围筛选

```
┌─────────────────────────────────────┐
│ 搜索: [张三___________] [🔍]        │
│ 时间: [最近30天▼] 类型:[全部▼]     │
├─────────────────────────────────────┤
│ 找到 8 个结果                       │
├─────────────────────────────────────┤
│ 👤 张三 (ABC公司 销售总监)          │
│    3次提及 | 2个关联                │
├─────────────────────────────────────┤
│ 📄 销售会议纪要 - 2024-01-15        │
│    提到: 张三, ABC公司, Q1合作      │
├─────────────────────────────────────┤
│ 👤 名片扫描 - 2024-01-10            │
│    张三的名片                       │
└─────────────────────────────────────┘
```

**API需求:**
- `GET /api/v1/search?q=张三&type=all&date_range=30d`
- `GET /api/v1/search/cross?entity_id=123` - 交叉检索

## 三、核心操作流程(端到端)

### 3.1 扫描名片流程
```
用户操作                    系统响应                    API调用
─────────────────────────────────────────────────────────────
1. 打开相机扫描             显示取景框                  -
2. 拍照                     上传中...                   POST /api/v1/scan/business-card
3. 等待2-3秒                处理中(显示进度)           GET /api/v1/scan/{id}/status (轮询)
4. 看到识别结果             显示联系人信息              GET /api/v1/scan/{id}/result
5. 确认/编辑                保存到数据库                POST /api/v1/entities
6. 看到"需要跟进"提示       自动生成Todo                POST /api/v1/todos
7. 点击"标记完成"           Todo状态更新                PATCH /api/v1/todos/{id}/complete
```

**性能要求:**
- 步骤2→3: <500ms (上传)
- 步骤3→4: <3s (OCR + AI分析)
- 步骤4→5: <200ms (保存)

### 3.2 上传会议纪要流程
```
用户操作                    系统响应                    API调用
─────────────────────────────────────────────────────────────
1. 选择文件上传             上传中...                   POST /api/v1/meeting/analyze
2. 等待处理                 显示进度(0%→100%)          GET /api/v1/meeting/{id}/status
3. 30秒后看到结果           显示分析结果页面            GET /api/v1/meeting/{id}/result
4. 查看行动项列表           显示Todo列表                -
5. 逐个标记完成             Todo状态更新                PATCH /api/v1/todos/{id}/complete
6. 点击实体查看详情         跳转到实体详情页            GET /api/v1/entities/{id}
```

**性能要求:**
- 步骤1→2: <1s (上传)
- 步骤2→3: <30s (AI分析,异步)
- 步骤3→4: <500ms (加载结果)

### 3.3 数据修正流程
```
用户操作                    系统响应                    API调用
─────────────────────────────────────────────────────────────
1. 搜索"张三"               显示搜索结果                GET /api/v1/search?q=张三
2. 发现重复实体             显示2个"张三"               -
3. 点击"合并重复"           显示合并预览                GET /api/v1/entities/123,456
4. 确认合并                 执行合并                    POST /api/v1/entities/merge
5. 验证修正效果             显示合并后的实体            GET /api/v1/entities/{new_id}
6. 查看关联事件             显示所有提及                GET /api/v1/entities/{id}/mentions
```

**性能要求:**
- 步骤1→2: <1s (搜索)
- 步骤4→5: <2s (合并操作)

## 四、技术架构(支撑上述页面)

### 4.1 三层模型解耦设计

```
┌─────────────────────────────────────────────────────────┐
│ L1: 原始事件层 (Raw Events)                             │
│ - 存储原始文本,不做任何处理                             │
│ - 表: raw_events (id, source, content, created_at)      │
│ - 用途: 审计追溯,重新分析                               │
└─────────────────────────────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────┐
│ L2: 结构化事件层 (Structured Events)                    │
│ - AI提取的结构化数据                                    │
│ - 表: structured_events (id, raw_event_id, entities,    │
│       associations, todos, metadata)                    │
│ - 用途: 快速查询,关联分析                               │
└─────────────────────────────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────┐
│ L3: 知识图谱层 (Knowledge Graph)                        │
│ - 归一化的实体和关联                                    │
│ - 表: entities, associations, entity_mentions           │
│ - 用途: 全局搜索,关联发现,数据管理                      │
└─────────────────────────────────────────────────────────┘
```

**解耦优势:**
1. **可重新分析**: L1不变,重新生成L2和L3
2. **性能优化**: L3预计算,查询快
3. **数据一致性**: L2→L3单向流动,避免循环依赖

### 4.2 四条事件管线

```python
# 管线路由器
class EventPipelineRouter:
    def route(self, event: RawEvent) -> Pipeline:
        """根据事件源路由到对应管线"""
        if event.source == "business_card":
            return BusinessCardPipeline()
        elif event.source == "meeting_notes":
            return MeetingNotesPipeline()
        elif event.source == "email":
            return EmailPipeline()
        elif event.source == "wechat":
            return WeChatPipeline()
        else:
            raise ValueError(f"Unknown source: {event.source}")

# 管线基类
class Pipeline(ABC):
    @abstractmethod
    async def process(self, raw_event: RawEvent) -> StructuredEvent:
        """处理原始事件,返回结构化事件"""
        pass
    
    async def extract_entities(self, content: str) -> List[Entity]:
        """提取实体"""
        pass
    
    async def extract_associations(self, entities: List[Entity]) -> List[Association]:
        """提取关联"""
        pass
    
    async def generate_todos(self, structured_event: StructuredEvent) -> List[Todo]:
        """生成Todo"""
        pass

# 名片管线
class BusinessCardPipeline(Pipeline):
    async def process(self, raw_event: RawEvent) -> StructuredEvent:
        # 1. OCR识别
        ocr_result = await self.ocr_service.recognize(raw_event.content)
        
        # 2. AI提取实体(人名/公司/职位/联系方式)
        entities = await self.extract_entities(ocr_result)
        
        # 3. 实体归一(检查重复)
        unified_entities = await self.entity_unification_service.unify(entities)
        
        # 4. 生成Todo(信息型: "已添加张三到联系人")
        todos = await self.generate_todos(StructuredEvent(entities=unified_entities))
        
        return StructuredEvent(
            raw_event_id=raw_event.id,
            entities=unified_entities,
            associations=[],
            todos=todos,
            metadata={"ocr_confidence": ocr_result.confidence}
        )

# 会议纪要管线
class MeetingNotesPipeline(Pipeline):
    async def process(self, raw_event: RawEvent) -> StructuredEvent:
        # 1. 识别会议类型
        meeting_type = await self.classify_meeting_type(raw_event.content)
        
        # 2. 根据类型选择提取策略
        if meeting_type == "sales":
            extractor = SalesMeetingExtractor()
        elif meeting_type == "technical":
            extractor = TechnicalMeetingExtractor()
        else:
            extractor = GeneralMeetingExtractor()
        
        # 3. 提取实体和关联
        entities = await extractor.extract_entities(raw_event.content)
        associations = await extractor.extract_associations(entities)
        
        # 4. 实体归一
        unified_entities = await self.entity_unification_service.unify(entities)
        
        # 5. 生成Todo(行动型: "跟进张三讨论方案")
        todos = await extractor.generate_todos(raw_event.content, unified_entities)
        
        return StructuredEvent(
            raw_event_id=raw_event.id,
            entities=unified_entities,
            associations=associations,
            todos=todos,
            metadata={"meeting_type": meeting_type}
        )
```

### 4.3 实体归一5步算法

```python
class EntityUnificationService:
    """实体归一服务 - 解决重复实体问题"""
    
    async def unify(self, entities: List[Entity]) -> List[Entity]:
        """
        5步归一算法:
        1. 精确匹配(名字+类型完全相同)
        2. 模糊匹配(编辑距离<2)
        3. 语义匹配(embedding相似度>0.9)
        4. 上下文匹配(同一事件中的实体)
        5. 人工确认(相似度0.7-0.9,需要用户确认)
        """
        unified = []
        
        for entity in entities:
            # 步骤1: 精确匹配
            exact_match = await self.find_exact_match(entity)
            if exact_match:
                unified.append(exact_match)
                continue
            
            # 步骤2: 模糊匹配
            fuzzy_matches = await self.find_fuzzy_matches(entity)
            if len(fuzzy_matches) == 1:
                unified.append(fuzzy_matches[0])
                continue
            
            # 步骤3: 语义匹配
            semantic_matches = await self.find_semantic_matches(entity)
            if len(semantic_matches) == 1 and semantic_matches[0].similarity > 0.9:
                unified.append(semantic_matches[0].entity)
                continue
            
            # 步骤4: 上下文匹配
            context_match = await self.find_context_match(entity)
            if context_match:
                unified.append(context_match)
                continue
            
            # 步骤5: 需要人工确认
            if fuzzy_matches or semantic_matches:
                # 创建待确认记录
                await self.create_merge_suggestion(entity, fuzzy_matches + [m.entity for m in semantic_matches])
            
            # 创建新实体
            new_entity = await self.create_entity(entity)
            unified.append(new_entity)
        
        return unified
    
    async def find_exact_match(self, entity: Entity) -> Optional[Entity]:
        """精确匹配: 名字+类型完全相同"""
        return await self.db.query(
            "SELECT * FROM entities WHERE name = $1 AND type = $2",
            entity.name, entity.type
        )
    
    async def find_fuzzy_matches(self, entity: Entity) -> List[Entity]:
        """模糊匹配: 编辑距离<2"""
        candidates = await self.db.query(
            "SELECT * FROM entities WHERE type = $1 AND levenshtein(name, $2) < 2",
            entity.type, entity.name
        )
        return candidates
    
    async def find_semantic_matches(self, entity: Entity) -> List[SimilarityMatch]:
        """语义匹配: embedding相似度>0.7"""
        entity_embedding = await self.embedding_service.embed(entity.name)
        
        # 使用pgvector进行向量搜索
        candidates = await self.db.query(
            """
            SELECT *, 1 - (embedding <=> $1) as similarity
            FROM entities
            WHERE type = $2 AND 1 - (embedding <=> $1) > 0.7
            ORDER BY similarity DESC
            LIMIT 5
            """,
            entity_embedding, entity.type
        )
        
        return [SimilarityMatch(entity=c, similarity=c.similarity) for c in candidates]
```

### 4.4 关联发现3步算法

```python
class AssociationDiscoveryService:
    """关联发现服务 - 自动发现实体间关系"""
    
    async def discover(self, entities: List[Entity], context: str) -> List[Association]:
        """
        3步关联发现:
        1. 显式关联(文本中明确提到: "张三是ABC公司的销售总监")
        2. 隐式关联(共现关系: 同一事件中出现的实体)
        3. 推理关联(基于已知关联推理: 张三→ABC公司, 李四→ABC公司 => 张三和李四是同事)
        """
        associations = []
        
        # 步骤1: 显式关联
        explicit = await self.extract_explicit_associations(entities, context)
        associations.extend(explicit)
        
        # 步骤2: 隐式关联(共现)
        implicit = await self.extract_implicit_associations(entities, context)
        associations.extend(implicit)
        
        # 步骤3: 推理关联
        inferred = await self.infer_associations(entities, associations)
        associations.extend(inferred)
        
        return associations
    
    async def extract_explicit_associations(self, entities: List[Entity], context: str) -> List[Association]:
        """提取显式关联"""
        # 使用spaCy依存句法分析
        doc = self.nlp(context)
        associations = []
        
        for token in doc:
            if token.dep_ in ["nsubj", "dobj", "pobj"]:
                # 找到主语-谓语-宾语关系
                subject = self.find_entity(token.head.head, entities)
                relation = token.head.text
                object = self.find_entity(token, entities)
                
                if subject and object:
                    associations.append(Association(
                        source=subject,
                        target=object,
                        relation=relation,
                        confidence=0.9
                    ))
        
        return associations
    
    async def extract_implicit_associations(self, entities: List[Entity], context: str) -> List[Association]:
        """提取隐式关联(共现)"""
        associations = []
        
        # 同一事件中的实体建立"共现"关联
        for i, e1 in enumerate(entities):
            for e2 in entities[i+1:]:
                associations.append(Association(
                    source=e1,
                    target=e2,
                    relation="co_occurrence",
                    confidence=0.6
                ))
        
        return associations
    
    async def infer_associations(self, entities: List[Entity], known_associations: List[Association]) -> List[Association]:
        """推理关联"""
        # 使用NetworkX构建

### 🔒 安全专家 [✅]
---
# PromiseLink 架构重新设计(客户视角驱动)

## 设计原则确认

✅ **从用户场景倒推架构,不是从技术正推**
✅ **先定义页面和操作,再设计支撑架构**
✅ **每个设计决策必须回答:这能让用户顺畅完成操作吗?**

---

## 第一部分:用户页面架构(用户看到什么)

### 1.1 首页/仪表盘(Dashboard)
**用户第一眼看到:**
```
┌─────────────────────────────────────────┐
│ 今日待办 (3)                    [全部]  │
├─────────────────────────────────────────┤
│ 🔴 [行动] 联系张三讨论合作 (来自名片)    │
│    截止:今天 18:00                       │
│ 🟡 [信息] 确认李四的邮箱地址             │
│    来源:会议纪要-产品评审                │
│ 🟢 [行动] 准备下周演示材料               │
├─────────────────────────────────────────┤
│ 最近事件 (5)                    [全部]  │
├─────────────────────────────────────────┤
│ 📇 名片扫描 - 王五 CTO (2小时前)        │
│ 📝 会议纪要 - 技术架构讨论 (昨天)       │
│ 📧 邮件 - 客户需求确认 (2天前)          │
├─────────────────────────────────────────┤
│ 快捷操作                                 │
│ [📷 扫描名片] [📝 上传纪要] [🔍 搜索]   │
└─────────────────────────────────────────┘
```

**关键设计决策:**
- **今日Todo优先级排序**: 行动型>信息型,截止时间近的在前
- **来源标记**: 每个Todo显示来源事件,点击可跳转
- **快捷操作**: 3个最高频操作直接入口

**支撑API:**
- `GET /api/v1/dashboard/today-todos` - 今日待办(带优先级排序)
- `GET /api/v1/dashboard/recent-events?limit=5` - 最近事件
- `GET /api/v1/dashboard/stats` - 统计数据(待办数/实体数/关联数)

---

### 1.2 Todo列表页
**信息架构:**
```
┌─────────────────────────────────────────┐
│ 待办事项                                 │
│ [行动型 23] [信息型 15] [已完成 47]     │
├─────────────────────────────────────────┤
│ 筛选: [全部来源▼] [全部优先级▼] [搜索] │
│ 排序: [截止时间▼]                       │
├─────────────────────────────────────────┤
│ 行动型待办 (23)                          │
├─────────────────────────────────────────┤
│ ☐ 联系张三讨论合作                      │
│   📇 来自:名片扫描-张三                  │
│   ⏰ 截止:今天 18:00                     │
│   [标记完成] [延期] [详情]              │
├─────────────────────────────────────────┤
│ ☐ 发送合同给李四审阅                    │
│   📝 来自:会议纪要-合同评审              │
│   ⏰ 截止:明天                           │
│   [标记完成] [延期] [详情]              │
├─────────────────────────────────────────┤
│ 信息型待办 (15)                          │
├─────────────────────────────────────────┤
│ ☐ 确认王五的公司地址                    │
│   📇 来自:名片扫描-王五                  │
│   [标记完成] [详情]                      │
└─────────────────────────────────────────┘
```

**关键设计决策:**
- **分类Tab**: 行动型/信息型/已完成 - 用户心智模型清晰
- **来源可追溯**: 每个Todo显示来源事件,点击跳转到事件详情
- **快速操作**: 标记完成/延期/详情 - 减少点击层级
- **筛选维度**: 来源类型(名片/会议/邮件/聊天) + 优先级 + 关键词

**支撑API:**
- `GET /api/v1/todos?type=action&status=pending` - 获取待办列表
- `PATCH /api/v1/todos/{id}/complete` - 标记完成
- `PATCH /api/v1/todos/{id}/postpone` - 延期
- `GET /api/v1/todos/{id}` - 获取详情

---

### 1.3 事件详情页
**信息架构:**
```
┌─────────────────────────────────────────┐
│ 📇 名片扫描 - 张三                       │
│ 2024-06-01 14:30 | 已处理               │
├─────────────────────────────────────────┤
│ 原始内容                                 │
│ ┌─────────────────────────────────────┐ │
│ │ [名片图片预览]                       │ │
│ │ 张三                                 │ │
│ │ 技术总监                             │ │
│ │ ABC科技有限公司                      │ │
│ │ 13800138000                          │ │
│ │ zhangsan@abc.com                     │ │
│ └─────────────────────────────────────┘ │
├─────────────────────────────────────────┤
│ AI提取结果                               │
│ 👤 人物: 张三 (技术总监)                │
│    [查看实体详情]                        │
│ 🏢 组织: ABC科技有限公司                │
│    [查看实体详情]                        │
│ 📞 联系方式: 13800138000                │
│ 📧 邮箱: zhangsan@abc.com               │
├─────────────────────────────────────────┤
│ 生成的待办 (2)                           │
│ ☐ 联系张三讨论技术合作                  │
│ ☐ 确认ABC科技的业务范围                 │
│    [添加待办]                            │
├─────────────────────────────────────────┤
│ 发现的关联                               │
│ 张三 --[就职于]--> ABC科技有限公司      │
│    [编辑关联]                            │
├─────────────────────────────────────────┤
│ 操作                                     │
│ [重新处理] [删除事件] [导出]            │
└─────────────────────────────────────────┘
```

**关键设计决策:**
- **原始内容保留**: 用户可验证AI提取准确性
- **实体可点击**: 跳转到实体详情页查看完整信息
- **待办可管理**: 直接在事件页面添加/完成待办
- **关联可视化**: 显示发现的实体关系
- **重新处理**: 如果AI提取错误,可重新触发处理

**支撑API:**
- `GET /api/v1/events/{id}` - 获取事件详情(含原始内容+提取结果+待办+关联)
- `POST /api/v1/events/{id}/reprocess` - 重新处理事件
- `POST /api/v1/events/{id}/todos` - 为事件添加待办
- `DELETE /api/v1/events/{id}` - 删除事件

---

### 1.4 实体详情页
**信息架构:**
```
┌─────────────────────────────────────────┐
│ 👤 张三                                  │
│ 类型:人物 | 置信度:95% | [编辑]         │
├─────────────────────────────────────────┤
│ 属性                                     │
│ 职位: 技术总监                           │
│ 电话: 13800138000                        │
│ 邮箱: zhangsan@abc.com                   │
│ 微信: zhangsan_tech                      │
│    [添加属性]                            │
├─────────────────────────────────────────┤
│ 来源标记 (3个事件)                       │
│ 📇 名片扫描 (2024-06-01) - 主要来源     │
│ 📝 会议纪要-技术讨论 (2024-05-28)       │
│ 📧 邮件-合作意向 (2024-05-25)           │
│    [查看所有来源]                        │
├─────────────────────────────────────────┤
│ 关联实体                                 │
│ --[就职于]--> 🏢 ABC科技有限公司        │
│    来源:名片扫描 | 置信度:98%            │
│ --[认识]--> 👤 李四                     │
│    来源:会议纪要 | 置信度:85%            │
│    [添加关联] [编辑关联]                 │
├─────────────────────────────────────────┤
│ 相关待办 (2)                             │
│ ☐ 联系张三讨论技术合作                  │
│ ☑ 发送产品介绍给张三 (已完成)           │
├─────────────────────────────────────────┤
│ 操作                                     │
│ [合并实体] [删除实体] [导出]            │
└─────────────────────────────────────────┘
```

**关键设计决策:**
- **来源可追溯**: 显示实体来自哪些事件,用户可验证准确性
- **置信度透明**: AI提取的置信度显示,低置信度提示用户确认
- **关联可视化**: 显示实体间关系,支持添加/编辑/删除
- **合并实体**: 如果发现重复实体(如"张三"和"张总"),可手动合并

**支撑API:**
- `GET /api/v1/entities/{id}` - 获取实体详情(含属性+来源+关联+待办)
- `PATCH /api/v1/entities/{id}` - 更新实体属性
- `POST /api/v1/entities/{id}/attributes` - 添加属性
- `POST /api/v1/entities/{id}/associations` - 添加关联
- `POST /api/v1/entities/merge` - 合并实体
- `DELETE /api/v1/entities/{id}` - 删除实体

---

### 1.5 数据管理中心
**信息架构:**
```
┌─────────────────────────────────────────┐
│ 数据管理中心                             │
│ [事件] [实体] [关联] [标签]             │
├─────────────────────────────────────────┤
│ 事件管理 (共156个)                       │
│ 筛选: [名片▼] [全部状态▼] [时间范围▼]  │
│ 排序: [时间倒序▼]                       │
├─────────────────────────────────────────┤
│ 📇 名片扫描 - 张三 (2024-06-01)         │
│    状态:已处理 | 提取:2实体 3待办        │
│    [查看详情] [重新处理] [删除]         │
├─────────────────────────────────────────┤
│ 📝 会议纪要 - 技术讨论 (2024-05-28)     │
│    状态:已处理 | 提取:5实体 7待办        │
│    [查看详情] [重新处理] [删除]         │
├─────────────────────────────────────────┤
│ 实体管理 (共342个)                       │
│ 筛选: [人物▼] [全部置信度▼] [搜索]     │
│ 排序: [最近更新▼]                       │
├─────────────────────────────────────────┤
│ 👤 张三 (技术总监)                      │
│    置信度:95% | 来源:3个事件             │
│    [查看详情] [编辑] [合并] [删除]      │
├─────────────────────────────────────────┤
│ 关联管理 (共128个)                       │
│ 筛选: [全部类型▼] [置信度▼]            │
├─────────────────────────────────────────┤
│ 张三 --[就职于]--> ABC科技              │
│    置信度:98% | 来源:名片扫描            │
│    [编辑] [删除]                         │
└─────────────────────────────────────────┘
```

**关键设计决策:**
- **分类Tab**: 事件/实体/关联/标签 - 清晰的数据分类
- **批量操作**: 支持批量删除/重新处理/导出
- **筛选和排序**: 多维度筛选,快速定位数据
- **置信度筛选**: 快速找到低置信度数据进行人工确认

**支撑API:**
- `GET /api/v1/events?type=business_card&status=processed` - 事件列表
- `GET /api/v1/entities?type=person&confidence_min=0.8` - 实体列表
- `GET /api/v1/associations?type=works_for` - 关联列表
- `DELETE /api/v1/events/batch` - 批量删除事件
- `POST /api/v1/events/batch/reprocess` - 批量重新处理

---

### 1.6 名片扫描结果页
**用户操作流程:**
```
用户扫描名片 → 上传图片 → 等待处理(3s) → 看到结果页
```

**结果页展示:**
```
┌─────────────────────────────────────────┐
│ ✅ 名片扫描完成                          │
├─────────────────────────────────────────┤
│ [名片图片预览]                           │
├─────────────────────────────────────────┤
│ 提取信息                                 │
│ 👤 张三 - 技术总监                      │
│ 🏢 ABC科技有限公司                      │
│ 📞 13800138000                          │
│ 📧 zhangsan@abc.com                     │
│    [确认无误] [需要修正]                │
├─────────────────────────────────────────┤
│ 生成的待办 (2)                           │
│ ☐ 联系张三讨论技术合作                  │
│ ☐ 确认ABC科技的业务范围                 │
│    [添加到待办] [稍后处理]              │
├─────────────────────────────────────────┤
│ 下一步                                   │
│ [继续扫描] [查看待办列表] [返回首页]    │
└─────────────────────────────────────────┘
```

**关键设计决策:**
- **即时反馈**: 扫描后立即显示结果,不需要跳转到其他页面
- **确认机制**: 用户可确认或修正提取信息
- **待办预览**: 显示生成的待办,用户可选择添加或忽略
- **流畅衔接**: 提供"继续扫描"快捷操作,支持批量扫描场景

**支撑API:**
- `POST /api/v1/events/business-card` - 上传名片(multipart/form-data)
- `GET /api/v1/events/{id}/status` - 轮询处理状态
- `GET /api/v1/events/{id}` - 获取处理结果
- `PATCH /api/v1/events/{id}/confirm` - 确认提取结果
- `PATCH /api/v1/events/{id}/correct` - 修正提取结果

---

### 1.7 会议纪要结果页
**4种类型差异化展示:**

#### 类型1: 产品评审会议
```
┌─────────────────────────────────────────┐
│ 📝 产品评审会议 - 2024-06-01            │
│ 参与者: 张三, 李四, 王五 (3人)          │
├─────────────────────────────────────────┤
│ 决策事项 (5)                             │
│ ✓ 功能A优先级提升到P0                   │
│ ✓ 延期功能B到下个版本                   │
│ ✓ 增加预算50万用于性能优化               │
├─────────────────────────────────────────┤
│ 行动项 (7)                               │
│ ☐ 张三: 更新技术方案文档 (截止:本周五)  │
│ ☐ 李四: 协调设计资源 (截止:下周一)      │
│    [全部添加到待办]                      │
├─────────────────────────────────────────┤
│ 讨论要点                                 │
│ • 性能瓶颈分析                           │
│ • 用户反馈汇总                           │
│ • 竞品对比                               │
└─────────────────────────────────────────┘
```

#### 类型2: 客户拜访记录
```
┌─────────────────────────────────────────┐
│ 📝 客户拜访 - ABC公司 - 2024-06-01      │
│ 客户方: 张三(CTO), 李四(产品总监)       │
│ 我方: 王五(销售), 赵六(技术)            │
├─────────────────────────────────────────┤
│ 客户需求 (3)                             │
│ • 需要支持10万并发用户                   │
│ • 要求数据本地化部署                     │
│ • 希望2个月内上线                        │
├─────────────────────────────────────────┤
│ 跟进事项 (5)                             │
│ ☐ 发送技术方案给张三 (截止:明天)        │
│ ☐ 准备PoC演示环境 (截止:下周)           │
│    [全部添加到待办]                      │
├─────────────────────────────────────────┤
│ 关键信息                                 │
│ 预算: 200万                              │
│ 决策周期: 1个月                          │
│ 竞争对手: XYZ公司                        │
└─────────────────────────────────────────┘
```

#### 类型3: 技术讨论会议
```
┌─────────────────────────────────────────┐
│ 📝 技术架构讨论 - 2024-06-01            │
│ 参与者: 张三, 李四, 王五 (3人)          │
├─────────────────────────────────────────┤
│ 技术决策 (4)                             │
│ ✓ 采用微服务架构                         │
│ ✓ 使用PostgreSQL作为主数据库            │
│ ✓ Redis用于缓存和会话                   │
├─────────────────────────────────────────┤
│ 待解决问题 (3)                           │
│ ☐ 确认消息队列选型 (负责人:张三)        │
│ ☐ 评估云服务商 (负责人:李四)            │
│    [全部添加到待办]                      │
├─────────────────────────────────────────┤
│ 技术风险                                 │
│ • 数据迁移复杂度高                       │
│ • 团队缺乏微服务经验                     │
└─────────────────────────────────────────┘
```

#### 类型4: 一般会议
```
┌─────────────────────────────────────────┐
│ 📝 周例会 - 2024-06-01                  │
│ 参与者: 张三, 李四, 王五, 赵六 (4人)    │
├─────────────────────────────────────────┤
│ 讨论内容                                 │
│ • 项目进度汇报                           │
│ • 资源协调                               │
│ • 风险识别                               │
├─────────────────────────────────────────┤
│ 行动项 (6)                               │
│ ☐ 张三: 完成模块A开发 (截止:本周五)     │
│ ☐ 李四: 更新项目计划 (截止:明天)        │
│    [全部添加到待办]                      │
├─────────────────────────────────────────┤
│ 提取的实体 (8)                           │
│ 👤 张三, 李四, 王五, 赵六                │
│ 📁 项目A, 模块B                          │
└─────────────────────────────────────────┘
```

**关键设计决策:**
- **类型识别**: AI自动识别会议类型,差异化展示
- **结构化提取**: 决策/行动项/讨论要点分类展示
- **批量添加待办**: 一键添加所有行动项到待办列表
- **实体关联**: 自动提取参与者和提及的实体

**支撑API:**
- `POST /api/v1/events/meeting-minutes` - 上传会议纪要
- `GET /api/v1/events/{id}/status` - 轮询处理状态(异步处理,最长30s)
- `GET /api/v1/events/{id}` - 获取处理结果(含类型识别)
- `POST /api/v1/events/{id}/todos/batch` - 批量添加待办

---

### 1.8 搜索页
**信息架构:**
```
┌─────────────────────────────────────────┐
│ 🔍 搜索                                  │
│ [搜索框: 输入关键词、人名、公司名...]   │
├─────────────────────────────────────────┤
│ 高级筛选                                 │
│ 类型: [全部▼] [人物] [组织] [事件]     │
│ 时间: [全部时间▼] [最近7天] [自定义]   │
│ 来源: [全部来源▼] [名片] [会议] [邮件] │
├─────────────────────────────────────────┤
│ 搜索结果 (23)                            │
├─────────────────────────────────────────┤
│ 👤 张三 - 技术总监                      │
│    ABC科技有限公司                       │
│    来源: 名片扫描 (2024-06-01)          │
│    [查看详情]                            │
├─────────────────────────────────────────┤
│ 📝 会议纪要 - 技术讨论                  │
│    提及: 张三, 李四, 微服务架构          │
│    时间: 2024-05-28                      │
│    [查看详情]                            │
├─────────────────────────────────────────┤
│ 🏢 ABC科技有限公司                      │
│    关联: 张三(就职于), 李四(就职于)     │
│    来源: 3个事件                         │
│    [查看详情]                            │
└─────────────────────────────────────────┘
```

**关键设计决策:**
- **全文搜索**: 支持模糊匹配,搜索实体名称、属性、事件内容
- **交叉检索**: 可同时搜索实体、事件、待办
- **高级筛选**: 类型/时间/来源多维度筛选
- **结果分类**: 按类型分组显示(实体/事件/待办)

**支撑API:**
- `GET /api/v1/search?q=张三&type=entity,event&limit=20` - 全文搜索
- `GET /api/v1/search/suggest?q=张` - 搜索建议(自动补全)
- `GET /api/v1/search/advanced` - 高级搜索(支持复杂筛选条件)

---

## 第二部分:用户操作流程(用户怎么用)

### 2.1 核心操作流程1: 扫描名片→执行行动→标记完成

```
┌─────────────────────────────────────────┐
│ 步骤1: 扫描名片                          │
│ 用户: 打开App → 点击"扫描名片" → 拍照   │
│ 系统: 上传图片 → OCR识别 → AI提取       │
│ 耗时: <3s                                │
├─────────────────────────────────────────┤
│ 步骤2: 查看结果                          │
│ 用户: 看到提取的姓名/职位/公司/联系方式 │
│ 系统: 显示置信度 + 生成的待办建议       │
│ 用户: 确认无误 或 修正错误信息          │
├─────────────────────────────────────────┤
│ 步骤3: 添加待办                          │
│ 用户: 选择"联系张三讨论合作"添加到待办  │
│ 系统: 创建待办 + 关联到名片事件         │
├─────────────────────────────────────────┤
│ 步骤4: 执行行动                          │
│ 用户: 从首页看到"今日待办" → 点击待办   │
│ 系统: 显示待办详情 + 来源名片信息       │
│ 用户: 查看张三的联系方式 → 拨打电话     │
├─────────────────────────────────────────┤
│ 步骤5: 标记完成                          │
│ 用户: 通话结束 → 点击"标记完成"         │
│ 系统: 更新待办状态 → 从今日待办移除     │
└─────────────────────────────────────────┘
```

**可能卡住的地方:**
- ❌ OCR识别错误 → 用户需要手动修正 → 提供"需要修正"快捷入口
- ❌ 生成的待办不合适 → 用户可删除或编辑 → 提供"编辑待办"功能
- ❌ 找不到待办来源 → 待办详情页显示来源事件链接

**API调用链:**
```
POST /api/v1/events/business-card (上传名片)
  ↓
GET /api/v1/events/{id}/status (轮询状态)
  ↓
GET /api/v1/events/{id} (获取结果)
  ↓
PATCH /api/v1/events/{id}/confirm (确认结果)
  ↓
POST /api/v1/todos (添加待办)
  ↓
GET /api/v1/dashboard/today-todos (查看今日待办)
  ↓
PATCH /api/v1/todos/{id}/complete (标记完成)
```

---

### 2.2 核心操作流程2: 上传会议纪要→确认/修正→执行行动项

```
┌─────────────────────────────────────────┐
│ 步骤1: 上传会议纪要                      │
│ 用户: 点击"上传纪要" → 选择文件/粘贴文本│
│ 系统: 上传文件 → AI分析(异步,最长30s)   │
│ 用户: 看到"处理中"提示 → 可继续其他操作 │
├─────────────────────────────────────────┤
│ 步骤2: 收到处理完成通知                  │
│ 系统: 推送通知"会议纪要已处理完

### 🤖 product [✅]
---
# PromiseLink 架构重新设计(客户视角驱动)

## 设计原则确认

✅ **核心原则理解**:从用户看到的页面和操作倒推架构,而非从技术栈正推。

---

## 第一部分:页面架构设计

### 1.1 首页/仪表盘 (Dashboard)

**用户第一眼看到什么?**

```
┌─────────────────────────────────────────────────┐
│ PromiseLink Dashboard                    [搜索🔍] │
├─────────────────────────────────────────────────┤
│                                                 │
│ 📋 今日待办 (3)                    [查看全部→] │
│ ┌─────────────────────────────────────────┐   │
│ │ 🔴 给张伟发送合同 (来自:商务会议)         │   │
│ │ 🟡 回复李娜邮件 (来自:名片扫描)           │   │
│ │ 🟢 准备周五演示材料 (来自:项目会议)       │   │
│ └─────────────────────────────────────────┘   │
│                                                 │
│ 📅 最近事件 (5)                    [查看全部→] │
│ ┌─────────────────────────────────────────┐   │
│ │ 2小时前 | 名片扫描 | 王芳 - 华为销售总监  │   │
│ │ 昨天    | 会议纪要 | Q1产品规划会议       │   │
│ │ 3天前   | 邮件     | 客户需求讨论         │   │
│ └─────────────────────────────────────────┘   │
│                                                 │
│ ⚡ 快捷操作                                     │
│ [📷 扫描名片] [📝 上传会议纪要] [🔍 搜索实体]  │
│                                                 │
│ 📊 数据概览                                     │
│ 实体: 127 | 关联: 89 | 待办: 12 | 事件: 45    │
└─────────────────────────────────────────────────┘
```

**关键设计决策**:
- **优先级排序**:今日Todo置顶(按紧急度颜色编码)
- **上下文线索**:每个Todo显示来源事件,点击可跳转
- **快速行动**:3个核心操作按钮直接可达
- **数据感知**:底部概览让用户了解系统积累的知识量

---

### 1.2 Todo列表页

**信息型/行动型怎么分?**

```
┌─────────────────────────────────────────────────┐
│ 待办事项                                        │
├─────────────────────────────────────────────────┤
│ [全部] [行动型] [信息型] [已完成]              │
│ 排序: [紧急度↓] [创建时间] [来源事件]          │
│ 筛选: [来源类型▼] [关联实体▼] [标签▼]         │
├─────────────────────────────────────────────────┤
│                                                 │
│ 🔴 行动型 (需要执行操作)                        │
│ ┌─────────────────────────────────────────┐   │
│ │ ☐ 给张伟发送合同                         │   │
│ │   📎 来自: 2024-06-01 商务会议纪要       │   │
│ │   👤 关联: 张伟(ABC公司-采购经理)        │   │
│ │   ⏰ 截止: 明天 18:00                    │   │
│ │   [标记完成] [查看详情] [延期]           │   │
│ └─────────────────────────────────────────┘   │
│                                                 │
│ 🟡 信息型 (需要记住的信息)                      │
│ ┌─────────────────────────────────────────┐   │
│ │ ☐ 李娜偏好周三下午开会                   │   │
│ │   📎 来自: 2024-05-30 名片扫描           │   │
│ │   👤 关联: 李娜(XYZ科技-产品总监)        │   │
│ │   [已知晓] [添加备注]                    │   │
│ └─────────────────────────────────────────┘   │
└─────────────────────────────────────────────────┘
```

**关键设计决策**:
- **明确分类**:行动型(需执行)vs信息型(需记住)
- **上下文完整**:显示来源事件+关联实体+截止时间
- **差异化操作**:行动型有"标记完成",信息型有"已知晓"
- **多维筛选**:按来源类型/关联实体/标签交叉筛选

---

### 1.3 事件详情页

**原始文本+AI提取结果+关联Todo+操作按钮**

```
┌─────────────────────────────────────────────────┐
│ ← 返回  事件详情: 商务会议纪要                  │
├─────────────────────────────────────────────────┤
│ 📄 原始内容                                     │
│ ┌─────────────────────────────────────────┐   │
│ │ 会议时间: 2024-06-01 14:00               │   │
│ │ 参会人员: 张伟(ABC公司)、李明(我方)      │   │
│ │ 讨论内容: 合同条款修订...                │   │
│ │ [查看完整文本]                           │   │
│ └─────────────────────────────────────────┘   │
│                                                 │
│ 🤖 AI提取结果                                   │
│ ┌─────────────────────────────────────────┐   │
│ │ 识别实体 (3):                            │   │
│ │ • 张伟 [人物] - ABC公司采购经理          │   │
│ │ • ABC公司 [组织]                         │   │
│ │ • 采购合同 [文档]                        │   │
│ │                                          │   │
│ │ 发现关联 (2):                            │   │
│ │ • 张伟 --工作于--> ABC公司               │   │
│ │ • 张伟 --负责--> 采购合同                │   │
│ │                                          │   │
│ │ 生成待办 (2):                            │   │
│ │ • [行动] 给张伟发送修订后的合同          │   │
│ │ • [信息] 张伟决策周期约2周               │   │
│ └─────────────────────────────────────────┘   │
│                                                 │
│ 🔧 操作                                         │
│ [重新分析] [修正提取结果] [添加备注] [删除]    │
└─────────────────────────────────────────────────┘
```

**关键设计决策**:
- **原始+提取并列**:用户可对比验证AI准确性
- **可修正设计**:每个提取结果可单独修正
- **关联可视化**:实体关系用自然语言表达
- **重新分析入口**:修正后可触发重新分析

---

### 1.4 实体详情页

**属性+来源标记+关联实体+编辑入口**

```
┌─────────────────────────────────────────────────┐
│ ← 返回  实体详情: 张伟                          │
├─────────────────────────────────────────────────┤
│ 👤 基本信息                                     │
│ ┌─────────────────────────────────────────┐   │
│ │ 姓名: 张伟                               │   │
│ │ 类型: 人物                               │   │
│ │ 职位: 采购经理                           │   │
│ │ 公司: ABC公司                            │   │
│ │ 电话: 138****1234                        │   │
│ │ 邮箱: zhang.wei@abc.com                  │   │
│ │ [编辑] [合并实体]                        │   │
│ └─────────────────────────────────────────┘   │
│                                                 │
│ 📌 来源追溯 (3个事件)                           │
│ • 2024-06-01 商务会议纪要 (首次提及)            │
│ • 2024-05-28 名片扫描 (补充联系方式)            │
│ • 2024-05-20 邮件往来 (确认职位)                │
│                                                 │
│ 🔗 关联实体 (5)                                 │
│ • ABC公司 [组织] --工作于-->                    │
│ • 李明 [人物] --合作伙伴-->                     │
│ • 采购合同 [文档] --负责-->                     │
│ • 产品演示 [事件] --参与-->                     │
│ • 技术方案 [文档] --审阅-->                     │
│ [添加关联] [查看关系图谱]                       │
│                                                 │
│ 📋 相关待办 (2)                                 │
│ • 给张伟发送合同 [未完成]                       │
│ • 张伟决策周期约2周 [信息型]                    │
└─────────────────────────────────────────────────┘
```

**关键设计决策**:
- **来源透明**:每个属性标注来源事件,可追溯
- **关联可视化**:关系类型用自然语言表达
- **合并入口**:发现重复实体时可手动合并
- **上下文完整**:显示相关Todo,形成闭环

---

### 1.5 数据管理中心

**事件/实体/关联/标签的浏览和管理**

```
┌─────────────────────────────────────────────────┐
│ 数据管理中心                                    │
├─────────────────────────────────────────────────┤
│ [事件] [实体] [关联] [标签]                     │
├─────────────────────────────────────────────────┤
│ 实体管理 (127个)                                │
│ 筛选: [类型▼] [来源▼] [创建时间▼]              │
│ 搜索: [___________________________] 🔍          │
│                                                 │
│ ┌─────────────────────────────────────────┐   │
│ │ 👤 张伟 | 人物 | 3个来源 | 5个关联       │   │
│ │ [查看] [编辑] [合并] [删除]              │   │
│ ├─────────────────────────────────────────┤   │
│ │ 🏢 ABC公司 | 组织 | 2个来源 | 8个关联    │   │
│ │ [查看] [编辑] [合并] [删除]              │   │
│ ├─────────────────────────────────────────┤   │
│ │ 📄 采购合同 | 文档 | 1个来源 | 3个关联   │   │
│ │ [查看] [编辑] [合并] [删除]              │   │
│ └─────────────────────────────────────────┘   │
│                                                 │
│ 批量操作: [合并选中] [删除选中] [导出]         │
└─────────────────────────────────────────────────┘
```

**关键设计决策**:
- **统一管理入口**:事件/实体/关联/标签集中管理
- **批量操作**:支持批量合并/删除/导出
- **来源统计**:显示每个实体的来源数量
- **关联统计**:显示关联数量,帮助识别核心实体

---

### 1.6 名片扫描结果页

**扫描后即时展示什么?**

```
┌─────────────────────────────────────────────────┐
│ 名片扫描结果                                    │
├─────────────────────────────────────────────────┤
│ 📷 原始图片                                     │
│ ┌─────────────────────────────────────────┐   │
│ │ [名片图片预览]                           │   │
│ └─────────────────────────────────────────┘   │
│                                                 │
│ 🤖 识别结果                                     │
│ ┌─────────────────────────────────────────┐   │
│ │ 姓名: 王芳                               │   │
│ │ 职位: 销售总监                           │   │
│ │ 公司: 华为技术有限公司                   │   │
│ │ 电话: 139-1234-5678                      │   │
│ │ 邮箱: wang.fang@huawei.com               │   │
│ │ 地址: 深圳市龙岗区...                    │   │
│ │ [修正信息]                               │   │
│ └─────────────────────────────────────────┘   │
│                                                 │
│ 🔍 智能发现                                     │
│ • 系统中已存在"王芳"(华为-市场经理)             │
│   可能是同一人? [合并] [忽略]                   │
│ • 华为技术有限公司已存在,自动关联               │
│                                                 │
│ 📋 生成待办 (2)                                 │
│ • [信息] 王芳负责华南区销售                     │
│ • [行动] 一周内跟进王芳的合作意向               │
│                                                 │
│ 🔧 操作                                         │
│ [保存] [重新扫描] [取消]                        │
└─────────────────────────────────────────────────┘
```

**关键设计决策**:
- **即时反馈**:扫描后立即显示识别结果
- **智能去重**:自动检测可能重复的实体
- **自动关联**:已存在的组织自动关联
- **即时Todo**:扫描完成即生成待办事项

---

### 1.7 会议纪要结果页

**4种类型的差异化展示**

```
┌─────────────────────────────────────────────────┐
│ 会议纪要分析结果                                │
├─────────────────────────────────────────────────┤
│ 📄 会议信息                                     │
│ 类型: 项目会议 | 时间: 2024-06-01 14:00         │
│ 参会人: 5人 | 时长: 90分钟                      │
│                                                 │
│ 🎯 核心内容 (项目会议特有)                      │
│ ┌─────────────────────────────────────────┐   │
│ │ 项目: Q2产品迭代                         │   │
│ │ 里程碑: 6月15日完成原型设计              │   │
│ │ 风险: 设计资源不足                       │   │
│ │ 决策: 外包部分UI设计工作                 │   │
│ └─────────────────────────────────────────┘   │
│                                                 │
│ 👥 识别实体 (8)                                 │
│ • 李明 [人物] - 项目经理                        │
│ • 张伟 [人物] - 技术负责人                      │
│ • Q2产品迭代 [项目]                             │
│ • 原型设计 [任务]                               │
│ ...                                             │
│                                                 │
│ 📋 行动项 (5)                                   │
│ • [行动] 李明联系外包设计公司 (截止:6月3日)    │
│ • [行动] 张伟评估技术方案 (截止:6月5日)        │
│ • [信息] 下次会议6月8日                         │
│                                                 │
│ 🔧 操作                                         │
│ [确认无误] [修正结果] [重新分析] [保存]        │
└─────────────────────────────────────────────────┘
```

**4种类型差异化**:
- **项目会议**:突出里程碑/风险/决策
- **商务会议**:突出客户需求/报价/合同条款
- **头脑风暴**:突出创意点/投票结果/待验证假设
- **一对一**:突出个人反馈/职业发展/私密信息

---

### 1.8 搜索页

**模糊查找+交叉检索**

```
┌─────────────────────────────────────────────────┐
│ 搜索                                            │
├─────────────────────────────────────────────────┤
│ [_____________________________________] 🔍       │
│ 高级筛选: [实体类型▼] [时间范围▼] [来源▼]     │
│                                                 │
│ 搜索结果: "张伟" (15条)                         │
│                                                 │
│ 👤 实体 (3)                                     │
│ • 张伟 - ABC公司采购经理                        │
│ • 张伟 - XYZ科技工程师 (可能重复?)              │
│ • 张伟华 - DEF集团CEO                           │
│                                                 │
│ 📄 事件 (8)                                     │
│ • 2024-06-01 商务会议纪要 (提及张伟)            │
│ • 2024-05-28 名片扫描 (张伟)                    │
│ ...                                             │
│                                                 │
│ 📋 待办 (4)                                     │
│ • 给张伟发送合同                                │
│ • 跟进张伟的反馈                                │
│ ...                                             │
│                                                 │
│ 🔗 交叉检索                                     │
│ 与"张伟"相关的其他实体:                         │
│ • ABC公司 (8次共现)                             │
│ • 采购合同 (5次共现)                            │
│ • 李明 (3次共现)                                │
└─────────────────────────────────────────────────┘
```

**关键设计决策**:
- **全局搜索**:跨实体/事件/Todo搜索
- **模糊匹配**:支持拼音/简写/近似匹配
- **交叉检索**:显示共现实体,发现隐藏关联
- **去重提示**:搜索结果中标注可能重复的实体

---

## 第二部分:用户操作流程

### 2.1 扫描名片→看到结果→执行行动→标记完成

```
用户操作流程:
1. 首页点击"扫描名片"
   ↓
2. 拍照/上传名片图片
   ↓ (后台:OCR识别 + 实体归一 + 关联发现 + Todo生成)
3. 3秒内看到"名片扫描结果页"
   - 识别的联系信息
   - 智能去重提示
   - 自动生成的Todo
   ↓
4. 用户修正错误信息(如有)
   ↓
5. 点击"保存"
   ↓
6. 跳转到"实体详情页"或"Todo列表页"
   ↓
7. 用户执行Todo(如"一周内跟进")
   ↓
8. 标记Todo为"已完成"
   ↓
9. 系统记录完成时间,更新实体活跃度
```

**关键时间节点**:
- 扫描→结果展示: <3s
- 保存→跳转: <500ms
- 标记完成→更新: <200ms

---

### 2.2 上传会议纪要→看到分析→确认/修正→执行行动项

```
用户操作流程:
1. 首页点击"上传会议纪要"
   ↓
2. 选择文件类型(文本/音频/视频)
   ↓
3. 上传文件
   ↓ (后台:异步处理,30s内完成)
4. 看到"处理中"提示,可继续使用其他功能
   ↓
5. 收到通知"会议纪要分析完成"
   ↓
6. 打开"会议纪要结果页"
   - 识别的实体
   - 发现的关联
   - 生成的行动项
   ↓
7. 用户逐项确认/修正
   - 修正错误的实体识别
   - 补充遗漏的关联
   - 调整行动项优先级
   ↓
8. 点击"确认无误"
   ↓
9. 行动项自动添加到Todo列表
   ↓
10. 用户从Todo列表执行行动项
```

**关键时间节点**:
- 上传→开始处理: <1s
- 处理完成→通知: <30s
- 确认→Todo生成: <500ms

---

### 2.3 浏览数据→发现错误→修正→验证修正效果

```
用户操作流程:
1. 进入"数据管理中心"
   ↓
2. 浏览实体列表,发现"张伟"有2个重复条目
   ↓
3. 点击"合并实体"
   ↓
4. 系统展示2个实体的详细信息对比
   ↓
5. 用户选择保留哪些属性
   ↓
6. 点击"确认合并"
   ↓ (后台:合并实体 + 更新关联 + 重新计算图谱)
7. 合并完成,跳转到合并后的实体详情页
   ↓
8. 用户验证:
   - 属性是否正确
   - 关联是否完整
   - 来源追溯是否清晰
   ↓
9. 如有问题,点击"撤销合并"
```

**关键时间节点**:
- 合并操作: <2s
- 图谱重新计算: <5s
- 撤销合并: <1s

---

### 2.4 搜索→找到实体→查看关联→添加/删除关联

```
用户操作流程:
1. 在搜索框输入"张伟"
   ↓
2. 看到搜索结果(实体/事件/Todo)
   ↓
3. 点击"张伟 - ABC公司采购经理"
   ↓
4. 进入实体详情页,看到5个关联实体
   ↓
5. 用户发现遗漏:"张伟"应该关联"技术方案"文档
   ↓
6. 点击"添加关联"
   ↓
7. 搜索"技术方案",选择关联类型"审阅"
   ↓
8. 点击"确认"
   ↓
9. 关联立即显示在实体详情页
   ↓
10. 用户点击"查看关系图谱"
   ↓
11. 看到张伟的完整关系网络可视化
```

**关键时间节点**:
- 搜索响应: <500ms
- 添加关联: <300ms
- 图谱渲染: <1s

---

## 第三部分:API设计(从页面操作倒推)

### 3.1 Dashboard页面API

```python
# GET /api/dashboard
# 响应格式:
{
  "today_todos": [
    {
      "id": "todo-123",
      "type": "action",  # action | info
      "title": "给张伟发送合同",
      "source_event": {
        "id": "event-456",
        "type": "meeting_minutes",
        "title": "商务会议"
      },
      "related_entities": [
        {"id": "entity-789", "name": "张伟", "type": "person"}
      ],
      "priority": "high",  # high | medium | low
      "due_date": "2024-06-02T18:00:00Z"
    }
  ],
  "recent_events": [
    {
      "id": "event-456",
      "type": "business_card_save",
      "title": "王芳 - 华为销售总监",
      "created_at": "2024-06-01T10:30:00Z",
      "entity_count": 3,
      "todo_count": 2
    }
  ],
  "stats": {
    "entities": 127,
    "associations": 89,
    "todos": 12,
    "events": 45
  }
}
```

---

### 3.2 Todo列表页API

```python
# GET /api/todos?type=action&status=pending&sort=priority
# 响应格式:
{
  "todos": [
    {
      "id": "todo-123",
      "type": "action",
      "title": "给张伟发送合同",
      "description": "发送修订后的采购合同给张伟审阅",
      "source_event": {
        "id": "event-456",
        "type": "meeting_minutes",
        "title": "商务会议",
        "created_at": "2024-06-01T14:00:00Z"
      },
      "related_entities": [
        {
          "id": "entity-789",
          "name": "张伟",
          "type": "person",
          "attributes": {"company": "ABC公司", "position": "采购经理"}
        }
      ],
      "priority": "high",
      "status": "pending",  # pending | completed | cancelled
      "due_date": "2024-06-02T18:00:00Z",
      "created_at": "2024-06-01T14:30:00Z"
    }
  ],
  "pagination": {
    "total": 12,
    "page": 1,
    "page_size": 20
  }
}

# PATCH /api/todos/{todo_id}
# 请求体:
{
  "status": "completed",
  "completion_note": "已通过邮件发送"
}
```

---

### 3.3 事件详情页API

```python
# GET /api/events/{event_id}
# 响应格式:
{
  "id": "event-456",
  "type": "meeting_minutes",
  "subtype": "business_meeting",
  "title": "商务会议纪要",
  "raw_content": "会议时间: 2024-06-01 14:00\n参会人员: 张伟(ABC公司)、李明(我方)\n讨论内容: 合同条款修订...",
  "created_at": "2024-06-01T14:30:00Z",
  "extracted_entities": [
    {
      "id": "entity-789",
      "name": "张伟",
      "type": "person",
      "attributes": {"company": "ABC公司", "position": "采购经理"},
      "confidence": 0.95,
      "source_span": {"start": 25, "end": 27}  # 在原始文本中的位置
    }
  ],
  "discovered_associations": [
    {
      "id": "assoc-101",
      "source_entity": {"id": "entity-789", "name": "张伟"},
      "target_entity": {"id": "entity-790", "name": "ABC公司"},
      "relation_type": "works_at",
      "confidence": 0.92
    }
  ],
  "generated_todos": [
    {
      "id": "todo-123",
      "type": "action",
      "title": "给张伟发送合同",
      "priority": "high"
    }
  ]
}

# POST /api/events/{event_id}/reanaly

### 🧪 测试专家 [✅]
---
# PromiseLink 架构重新设计(客户视角驱动)

## 一、用户视角:页面与操作流程优先

### 1.1 页面架构设计

#### 1.1.1 首页/仪表盘 (`/dashboard`)
**用户第一眼看到:**
```
┌─────────────────────────────────────────┐
│ 今日待办 (5)              [全部查看→]  │
├─────────────────────────────────────────┤
│ ⚡ 紧急: 回复张总邮件 (来自:会议纪要)   │
│ 📞 今日: 致电李经理 (来自:名片扫描)     │
│ 📅 本周: 准备Q2报告 (来自:邮件)        │
├─────────────────────────────────────────┤
│ 最近事件 (3)              [全部查看→]  │
├─────────────────────────────────────────┤
│ 🎤 销售会议纪要 - 2小时前              │
│ 👤 王总名片 - 今天上午                 │
│ 📧 合作意向邮件 - 昨天                 │
├─────────────────────────────────────────┤
│ 快捷操作                                │
│ [📷 扫描名片] [📄 上传纪要] [🔍 搜索]  │
└─────────────────────────────────────────┘
```

**API需求:**
- `GET /api/v1/dashboard/summary` - 返回今日Todo(前5条)、最近事件(前3条)、统计数据
- `GET /api/v1/todos?status=pending&limit=5&sort=priority,due_date`
- `GET /api/v1/events?limit=3&sort=created_at:desc`

#### 1.1.2 Todo列表页 (`/todos`)
**信息架构:**
```
┌─────────────────────────────────────────┐
│ 筛选: [全部▾] [信息型] [行动型]         │
│ 排序: [优先级▾] [截止日期] [创建时间]   │
├─────────────────────────────────────────┤
│ 行动型 (3)                              │
│ ☐ [高] 回复张总邮件                     │
│   📎 来源: 销售会议纪要 | ⏰ 今天       │
│   [标记完成] [延期] [查看详情]          │
│                                         │
│ ☐ [中] 致电李经理讨论合作               │
│   📎 来源: 李经理名片 | ⏰ 本周五       │
├─────────────────────────────────────────┤
│ 信息型 (2)                              │
│ ☐ 记录: 张总提到Q2预算增加20%           │
│   📎 来源: 销售会议纪要                 │
│   [已知晓] [添加备注]                   │
└─────────────────────────────────────────┘
```

**API需求:**
- `GET /api/v1/todos?type={informational|actionable}&status={pending|completed}&sort={priority|due_date|created_at}`
- `PATCH /api/v1/todos/{id}` - 更新状态、延期、添加备注
- `POST /api/v1/todos/{id}/complete` - 标记完成

#### 1.1.3 事件详情页 (`/events/{id}`)
**信息展示:**
```
┌─────────────────────────────────────────┐
│ 销售会议纪要                            │
│ 类型: 会议纪要 | 时间: 2024-06-01 14:00│
├─────────────────────────────────────────┤
│ 原始文本 [展开/收起]                    │
│ "今天与张总讨论了Q2合作计划..."         │
├─────────────────────────────────────────┤
│ AI提取结果                              │
│ 👤 人物: 张总(CEO, ABC公司)             │
│ 🏢 组织: ABC公司                        │
│ 📅 时间: 2024-06-01                     │
│ 📍 地点: 会议室A                        │
├─────────────────────────────────────────┤
│ 关联Todo (3)                            │
│ ☐ 回复张总邮件 [查看]                   │
│ ☐ 准备合作方案 [查看]                   │
│ ☑ 发送会议纪要 [已完成]                 │
├─────────────────────────────────────────┤
│ 操作                                    │
│ [重新处理] [导出] [删除]                │
└─────────────────────────────────────────┘
```

**API需求:**
- `GET /api/v1/events/{id}` - 完整事件数据(原始文本+提取结果+关联Todo)
- `POST /api/v1/events/{id}/reprocess` - 重新处理
- `GET /api/v1/events/{id}/todos` - 关联的Todo列表

#### 1.1.4 实体详情页 (`/entities/{id}`)
**信息展示:**
```
┌─────────────────────────────────────────┐
│ 张总                                    │
│ 类型: 人物 | 置信度: 95%                │
├─────────────────────────────────────────┤
│ 属性                                    │
│ 姓名: 张伟                              │
│ 职位: CEO                               │
│ 公司: ABC公司                           │
│ 电话: 138****1234                       │
│ 邮箱: zhang@abc.com                     │
│ [编辑属性]                              │
├─────────────────────────────────────────┤
│ 来源标记 (3)                            │
│ • 销售会议纪要 (2024-06-01)             │
│ • 名片扫描 (2024-05-28)                 │
│ • 邮件往来 (2024-05-20)                 │
├─────────────────────────────────────────┤
│ 关联实体                                │
│ 🏢 ABC公司 (工作于)                     │
│ 👤 李经理 (同事)                        │
│ [添加关联]                              │
├─────────────────────────────────────────┤
│ 相关Todo (2)                            │
│ ☐ 回复张总邮件                          │
│ ☑ 发送会议纪要给张总                    │
└─────────────────────────────────────────┘
```

**API需求:**
- `GET /api/v1/entities/{id}` - 实体详情(属性+来源+关联+Todo)
- `PATCH /api/v1/entities/{id}` - 更新属性
- `GET /api/v1/entities/{id}/sources` - 来源事件列表
- `GET /api/v1/entities/{id}/associations` - 关联实体
- `POST /api/v1/associations` - 添加关联
- `DELETE /api/v1/associations/{id}` - 删除关联

#### 1.1.5 数据管理中心 (`/data-management`)
**Tab结构:**
```
┌─────────────────────────────────────────┐
│ [事件] [实体] [关联] [标签]             │
├─────────────────────────────────────────┤
│ 事件列表 (共128条)                      │
│ 筛选: [类型▾] [日期范围] [处理状态]    │
│                                         │
│ 🎤 销售会议纪要 | 2024-06-01 | ✓处理完成│
│ 👤 王总名片 | 2024-06-01 | ✓处理完成    │
│ 📧 合作邮件 | 2024-05-31 | ⏳处理中     │
│                                         │
│ [批量操作▾] 已选3条                     │
└─────────────────────────────────────────┘
```

**API需求:**
- `GET /api/v1/events?type={}&date_from={}&date_to={}&status={}&page={}&limit={}`
- `GET /api/v1/entities?type={}&page={}&limit={}`
- `GET /api/v1/associations?page={}&limit={}`
- `DELETE /api/v1/events/batch` - 批量删除
- `POST /api/v1/events/batch/reprocess` - 批量重新处理

#### 1.1.6 名片扫描结果页 (`/scan-result/{event_id}`)
**即时展示:**
```
┌─────────────────────────────────────────┐
│ 扫描完成 ✓                              │
├─────────────────────────────────────────┤
│ 识别到的信息:                           │
│ 👤 李经理                               │
│ 🏢 XYZ科技有限公司                      │
│ 📞 139-1234-5678                        │
│ 📧 li@xyz.com                           │
│ 📍 北京市朝阳区...                      │
│                                         │
│ [确认信息] [修正错误]                   │
├─────────────────────────────────────────┤
│ 生成的待办 (2)                          │
│ ☐ 致电李经理跟进合作                    │
│ ☐ 记录: 李经理负责产品采购              │
│                                         │
│ [查看详情] [返回首页]                   │
└─────────────────────────────────────────┘
```

**API需求:**
- `POST /api/v1/events/business-card` - 上传名片图片(返回event_id)
- `GET /api/v1/events/{id}/processing-status` - 轮询处理状态
- `GET /api/v1/events/{id}` - 获取完整结果

#### 1.1.7 会议纪要结果页 (`/meeting-result/{event_id}`)
**4种类型差异化展示:**
```
┌─────────────────────────────────────────┐
│ 会议纪要处理完成 ✓                      │
│ 类型: 销售会议                          │
├─────────────────────────────────────────┤
│ 关键信息                                │
│ 👤 参与人: 张总, 李经理, 我             │
│ 🏢 涉及公司: ABC公司, XYZ公司           │
│ 📅 讨论时间: 2024 Q2                    │
│ 💰 预算: 200万                          │
├─────────────────────────────────────────┤
│ 行动项 (5)                              │
│ ☐ [高优] 回复张总邮件 - 今天            │
│ ☐ [中优] 准备合作方案 - 本周五          │
│ ☐ 发送会议纪要给参会人 - 明天           │
├─────────────────────────────────────────┤
│ 决策记录 (2)                            │
│ • 确定Q2合作预算200万                   │
│ • 下次会议定在6月15日                   │
├─────────────────────────────────────────┤
│ [查看完整纪要] [导出PDF] [返回首页]    │
└─────────────────────────────────────────┘
```

**API需求:**
- `POST /api/v1/events/meeting-minutes` - 上传纪要(返回event_id)
- `GET /api/v1/events/{id}/processing-status` - 轮询处理状态
- `GET /api/v1/events/{id}` - 获取完整结果(包含分类后的结构化数据)

#### 1.1.8 搜索页 (`/search`)
**搜索界面:**
```
┌─────────────────────────────────────────┐
│ 🔍 [搜索框: "张总"]          [搜索]     │
│ 范围: ☑实体 ☑事件 ☑Todo                │
├─────────────────────────────────────────┤
│ 实体结果 (2)                            │
│ 👤 张总 (CEO, ABC公司)                  │
│    来源: 3个事件 | 关联: 2个实体        │
│ 👤 张经理 (销售总监, DEF公司)           │
│    来源: 1个事件                        │
├─────────────────────────────────────────┤
│ 事件结果 (5)                            │
│ 🎤 销售会议纪要 - 2024-06-01            │
│    提到: 张总, ABC公司, Q2预算          │
│ 📧 合作邮件 - 2024-05-28                │
├─────────────────────────────────────────┤
│ Todo结果 (3)                            │
│ ☐ 回复张总邮件                          │
│ ☑ 发送会议纪要给张总                    │
└─────────────────────────────────────────┘
```

**API需求:**
- `GET /api/v1/search?q={query}&scope={entities,events,todos}&page={}&limit={}`
- 支持模糊匹配、全文搜索、交叉检索

---

### 1.2 核心用户操作流程

#### 流程1: 扫描名片→执行行动→标记完成
```
用户操作                    系统响应                    API调用
─────────────────────────────────────────────────────────────
1. 拍照/上传名片           显示上传进度                POST /events/business-card
                                                      (multipart/form-data)
                          ↓
2. 等待处理(3s内)          显示处理动画                GET /events/{id}/processing-status
                          "正在识别..."               (轮询,间隔1s)
                          ↓
3. 查看识别结果            展示实体+Todo               GET /events/{id}
   "李经理, XYZ公司"       [确认信息] [修正错误]
                          ↓
4. 点击"确认信息"          跳转到Todo列表              (前端路由)
                          ↓
5. 查看生成的Todo          显示"致电李经理"            GET /todos?source_event={id}
                          ↓
6. 点击"标记完成"          Todo状态变为已完成          PATCH /todos/{todo_id}
                          显示完成动画                {status: "completed"}
                          ↓
7. 返回首页                今日待办数量-1              GET /dashboard/summary
```

#### 流程2: 上传会议纪要→确认/修正→执行行动项
```
用户操作                    系统响应                    API调用
─────────────────────────────────────────────────────────────
1. 上传纪要文件            显示上传进度                POST /events/meeting-minutes
   (txt/docx/pdf)                                     (multipart/form-data)
                          ↓
2. 等待处理(30s内)         显示处理进度                GET /events/{id}/processing-status
                          "正在分析... 60%"           (轮询,间隔2s)
                          ↓
3. 查看分析结果            展示4类信息:                GET /events/{id}
                          - 关键信息(人物/组织)
                          - 行动项(5条)
                          - 决策记录(2条)
                          - 讨论要点
                          ↓
4. 发现错误                点击"修正错误"              (前端进入编辑模式)
   "张总职位识别错了"      
                          ↓
5. 修改实体属性            保存修改                    PATCH /entities/{id}
   CEO → 董事长                                       {title: "董事长"}
                          ↓
6. 验证修正效果            刷新页面,显示新值           GET /events/{id}
                          ↓
7. 执行行动项              点击Todo"回复张总"          (前端路由到Todo详情)
                          ↓
8. 标记完成                Todo状态更新                PATCH /todos/{id}
                                                      {status: "completed"}
```

#### 流程3: 浏览数据→发现错误→修正→验证
```
用户操作                    系统响应                    API调用
─────────────────────────────────────────────────────────────
1. 进入数据管理中心        显示事件列表                GET /events?page=1&limit=20
                          ↓
2. 点击某个事件            显示事件详情                GET /events/{id}
                          ↓
3. 发现实体错误            点击实体"张总"              (前端路由)
   "电话号码错了"          
                          ↓
4. 进入实体详情页          显示实体完整信息            GET /entities/{id}
                          ↓
5. 点击"编辑属性"          进入编辑模式                (前端状态切换)
                          ↓
6. 修改电话号码            保存修改                    PATCH /entities/{id}
   138****1234                                        {phone: "139****5678"}
   → 139****5678
                          ↓
7. 验证修正效果            刷新页面,显示新值           GET /entities/{id}
                          检查"来源标记"中            GET /entities/{id}/sources
                          所有引用是否一致
```

#### 流程4: 搜索→查看关联→添加/删除关联
```
用户操作                    系统响应                    API调用
─────────────────────────────────────────────────────────────
1. 在搜索框输入"张总"      显示搜索建议                GET /search/suggestions?q=张
                          (实时,防抖300ms)
                          ↓
2. 点击搜索                显示搜索结果                GET /search?q=张总
                          - 2个实体
                          - 5个事件
                          - 3个Todo
                          ↓
3. 点击实体"张总"          显示实体详情                GET /entities/{id}
                          ↓
4. 查看关联实体            显示关联图:                 GET /entities/{id}/associations
                          张总 ─工作于→ ABC公司
                          张总 ─同事→ 李经理
                          ↓
5. 点击"添加关联"          弹出选择框                  (前端模态框)
                          "选择关联类型和目标实体"
                          ↓
6. 选择关联                创建关联                    POST /associations
   张总 ─合作伙伴→ 王总                               {
                                                        source_id: "张总",
                                                        target_id: "王总",
                                                        type: "合作伙伴"
                                                      }
                          ↓
7. 验证关联                刷新关联图,显示新关联       GET /entities/{id}/associations
                          ↓
8. 删除错误关联            点击关联旁的"删除"          DELETE /associations/{id}
                          确认删除
```

---

## 二、API设计(从页面操作倒推)

### 2.1 API分组与端点

#### 2.1.1 Dashboard API
```
GET /api/v1/dashboard/summary
响应:
{
  "today_todos": {
    "total": 5,
    "high_priority": 2,
    "items": [
      {
        "id": "todo-123",
        "title": "回复张总邮件",
        "type": "actionable",
        "priority": "high",
        "due_date": "2024-06-01",
        "source_event": {
          "id": "event-456",
          "type": "meeting_minutes",
          "title": "销售会议纪要"
        }
      }
    ]
  },
  "recent_events": {
    "total": 128,
    "items": [
      {
        "id": "event-456",
        "type": "meeting_minutes",
        "title": "销售会议纪要",
        "created_at": "2024-06-01T14:00:00Z",
        "processing_status": "completed"
      }
    ]
  },
  "stats": {
    "total_entities": 45,
    "total_associations": 78,
    "pending_todos": 5
  }
}
```

#### 2.1.2 Todo API
```
GET /api/v1/todos
查询参数:
  - type: informational | actionable
  - status: pending | completed | snoozed
  - priority: high | medium | low
  - sort: priority | due_date | created_at
  - page, limit

响应:
{
  "items": [...],
  "pagination": {
    "page": 1,
    "limit": 20,
    "total": 45,
    "total_pages": 3
  }
}

PATCH /api/v1/todos/{id}
请求体:
{
  "status": "completed",
  "notes": "已完成电话沟通"
}

POST /api/v1/todos/{id}/snooze
请求体:
{
  "snooze_until": "2024-06-05T09:00:00Z"
}
```

#### 2.1.3 Event API
```
POST /api/v1/events/business-card
Content-Type: multipart/form-data
请求体:
  - image: file (jpg/png)
  - metadata: {user_id, timestamp}

响应:
{
  "event_id": "event-789",
  "status": "processing",
  "estimated_time": 3
}

GET /api/v1/events/{id}/processing-status
响应:
{
  "status": "processing | completed | failed",
  "progress": 60,
  "message": "正在提取实体...",
  "estimated_remaining": 10
}

GET /api/v1/events/{id}
响应:
{
  "id": "event-789",
  "type": "business_card",
  "status": "completed",
  "created_at": "2024-06-01T10:00:00Z",
  "raw_content": {
    "image_url": "...",
    "ocr_text": "..."
  },
  "extracted_data": {
    "entities": [
      {
        "id": "entity-101",
        "type": "person",
        "name": "李经理",
        "attributes": {
          "title": "销售总监",
          "company": "XYZ科技",
          "phone": "139-1234-5678",
          "email": "li@xyz.com"
        },
        "confidence": 0.95
      }
    ],
    "associations": [...],
    "todos": [
      {
        "id": "todo-202",
        "title": "致电李经理跟进合作",
        "type": "actionable",
        "priority": "medium"
      }
    ]
  }
}

POST /api/v1/events/{id}/reprocess
触发重新处理(幂等操作)
```

#### 2.1.4 Entity API
```
GET /api/v1/entities/{id}
响应:
{
  "id": "entity-101",
  "type": "person",
  "name": "张总",
  "attributes": {
    "full_name": "张伟",
    "title": "CEO",
    "company": "ABC公司",
    "phone": "138****1234",
    "email": "zhang@abc.com"
  },
  "confidence": 0.95,
  "created_at": "2024-05-20T10:00:00Z",
  "updated_at": "2024-06-01T14:00:00Z",
  "sources": [
    {
      "event_id": "event-456",
      "event_type": "meeting_minutes",
      "event_title": "销售会议纪要",
      "extracted_at": "2024-06-01T14:00:00Z"
    }
  ],
  "associations": [
    {
      "id": "assoc-301",
      "type": "works_at",
      "target_entity": {
        "id": "entity-102",
        "type": "organization",
        "name": "ABC公司"
      }
    }
  ],
  "related_todos": [
    {
      "id": "todo-123",
      "title": "回复张总邮件",
      "status": "pending"
    }
  ]
}

PATCH /api/v1/entities/{id}
请求体:
{
  "attributes": {
    "phone": "139****5678"
  }
}

响应:
{
  "id": "entity-101",
  "updated_at": "2024-06-01T15:00:00Z",
  "changes": {
    "phone": {
      "old": "138****1234",
      "new": "139****5678"
    }
  }
}
```

#### 2.1.5 Association API
```
GET /api/v1/associations?entity_id={id}
响应:
{
  "items": [
    {
      "id": "assoc-301",
      "type": "works_at",
      "source_entity": {...},
      "target_entity": {...},
      "confidence": 0.90,
      "created_at": "2024-06-01T14:00:00Z"
    }
  ]
}

POST /api/v1/associations
请求体:
{
  "source_entity_id": "entity-101",
  "target_entity_id": "entity-102",
  "type": "partner",
  "metadata": {
    "note": "Q2合作伙伴"
  }
}

DELETE /api/v1/associations/{id}
```

#### 2.1.6 Search API
```
GET /api/v1/search
查询参数:
  - q: 搜索关键词
  - scope: entities,events,todos (逗号分隔)
  - page, limit

响应:
{
  "entities": {
    "total": 2,
    "items": [...]
  },
  "events": {
    "total": 5,
    "items": [...]
  },
  "todos": {
    "total": 3,
    "items": [...]
  }
}

GET /api/v1/search/suggestions?q={partial_query}
响应:
{
  "suggestions": [
    {
      "type": "entity",
      "id": "entity-101",
      "name": "张总",
      "highlight": "<em>张</em>总"
    }
  ]
}
```

---

## 三、技术架构(支撑页面的后端设计)

### 3.1 三层模型解耦设计

```
┌─────────────────────────────────────────────────────────┐
│                    L1: API Layer                        │
│  (FastAPI Routes, Request/Response Models)              │
│  - 处理HTTP请求                                         │
│  - 参数验证(Pydantic)                                   │
│  - 响应格式化                                           │
│  - 错误处理                                             │
└─────────────────────────────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────┐
│                 L2: Business Logic Layer                │
│  (Services, Orchestrators)                              │
│  - EventProcessingService: 事件处理编排                 │
│  - EntityResolutionService: 实体归一化                  │
│  - AssociationDiscoveryService: 关联发现                │
│  - TodoGenerationService: Todo生成                      │
│  - SearchService: 搜索逻辑                              │
└─────────────────────────────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────┐
│                  L3: Data Access Layer                  │
│  (Repositories, ORM Models)                             │
│  - EventRepository: 事件CRUD                            │
│  - EntityRepository: 实体CRUD + 图查询                  │
│  - AssociationRepository: 关联CRUD                      │
│  - TodoRepository: Todo CRUD                            │
│  - CacheRepository: Redis缓存                           │
└─────────────────────────────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────┐
│                   Data Storage Layer                    │
│  - PostgreSQL 15: 主数据存储                            │
│  - Redis 7: 缓存 + 任务队列                             │
│  - NetworkX: 图计算(内存)                               │
└─────────────────────────────────────────────────────────┘
```

**解耦原则:**
1. **L1不直接访问L3**: API层通过Service层访问数据
2. **L2无

### ⚙️ DevOps工程师 [✅]
---
# PromiseLink 架构重新设计(客户视角驱动)

## 🎯 设计原则确认

**核心方法论**:从用户看到的屏幕倒推到数据库表结构,而不是反过来。

---

## 1️⃣ 页面架构设计(用户第一视角)

### 1.1 首页/仪表盘 (`/dashboard`)

**用户第一眼看到:**
```
┌─────────────────────────────────────────┐
│ 📊 PromiseLink Dashboard                  │
├─────────────────────────────────────────┤
│ 🔥 今日待办 (3)                         │
│  ☐ 回复张三邮件 (来自:名片扫描)         │
│  ☐ 准备周五会议材料 (来自:会议纪要)     │
│  ☐ 跟进李四合作事宜 (来自:邮件)         │
│                                         │
│ 📅 近期事件 (5)                         │
│  • 2024-01-15 扫描了王五名片            │
│  • 2024-01-14 上传了项目启动会纪要      │
│  • 2024-01-13 收到合作意向邮件          │
│                                         │
│ ⚡ 快捷操作                             │
│  [📷 扫描名片] [📝 上传纪要] [🔍 搜索]  │
└─────────────────────────────────────────┘
```

**页面数据需求:**
- 今日未完成Todo列表(按优先级排序)
- 最近7天事件时间线(最多10条)
- 统计数据:待办总数、实体总数、关联总数

**API需求:**
```
GET /api/v1/dashboard/summary
Response: {
  "todos_today": [...],
  "recent_events": [...],
  "stats": {"pending_todos": 3, "entities": 45, "associations": 78}
}
```

---

### 1.2 Todo列表页 (`/todos`)

**信息型/行动型分类展示:**
```
┌─────────────────────────────────────────┐
│ 📋 待办事项                             │
├─────────────────────────────────────────┤
│ [行动型] [信息型] [全部] [已完成]       │
│                                         │
│ 🎯 行动型 (需要你做事)                  │
│  ☐ 回复张三邮件 - 截止:今天 17:00       │
│     来源:名片扫描 | 优先级:高           │
│  ☐ 准备周五会议材料 - 截止:1月19日      │
│     来源:会议纪要 | 优先级:中           │
│                                         │
│ 📖 信息型 (需要你知道)                  │
│  ☐ 张三公司地址已更新                   │
│     来源:名片扫描 | 无截止日期          │
│  ☐ 李四提到了新的合作方向               │
│     来源:会议纪要 | 无截止日期          │
└─────────────────────────────────────────┘
```

**筛选/排序选项:**
- 筛选:类型(行动/信息)、状态(待办/已完成)、来源(名片/纪要/邮件/聊天)、优先级
- 排序:截止日期、创建时间、优先级

**API需求:**
```
GET /api/v1/todos?type=action&status=pending&sort=deadline
Response: {
  "todos": [...],
  "total": 15,
  "filters_applied": {...}
}
```

---

### 1.3 事件详情页 (`/events/{event_id}`)

**展示结构:**
```
┌─────────────────────────────────────────┐
│ 📄 事件详情 - 名片扫描                  │
├─────────────────────────────────────────┤
│ 📅 2024-01-15 14:30 | 类型:名片扫描     │
│                                         │
│ 📸 原始内容                             │
│  [名片图片预览]                         │
│                                         │
│ 🤖 AI提取结果                           │
│  姓名: 张三                             │
│  职位: 产品经理                         │
│  公司: ABC科技                          │
│  电话: 138****1234                      │
│  邮箱: zhangsan@abc.com                 │
│  [✏️ 修正提取结果]                      │
│                                         │
│ ✅ 生成的待办 (2)                       │
│  ☐ 回复张三邮件                         │
│  ☐ 添加张三到CRM系统                    │
│                                         │
│ 🔗 关联实体 (3)                         │
│  👤 张三 (Person)                       │
│  🏢 ABC科技 (Organization)              │
│  📧 zhangsan@abc.com (Contact)          │
│                                         │
│ 🎬 操作                                 │
│  [🗑️ 删除事件] [📤 导出] [🔄 重新处理]  │
└─────────────────────────────────────────┘
```

**API需求:**
```
GET /api/v1/events/{event_id}
Response: {
  "event": {...},
  "raw_content": {...},
  "extracted_data": {...},
  "todos": [...],
  "entities": [...],
  "associations": [...]
}
```

---

### 1.4 实体详情页 (`/entities/{entity_id}`)

**展示结构:**
```
┌─────────────────────────────────────────┐
│ 👤 实体详情 - 张三                      │
├─────────────────────────────────────────┤
│ 类型: Person | 置信度: 95%              │
│                                         │
│ 📋 属性                                 │
│  姓名: 张三                             │
│  职位: 产品经理                         │
│  公司: ABC科技                          │
│  电话: 138****1234                      │
│  邮箱: zhangsan@abc.com                 │
│  [✏️ 编辑属性]                          │
│                                         │
│ 📍 来源标记                             │
│  • 名片扫描 (2024-01-15) - 主要来源    │
│  • 会议纪要 (2024-01-10) - 补充信息    │
│                                         │
│ 🔗 关联实体 (5)                         │
│  🏢 ABC科技 (works_at)                  │
│  👤 李四 (colleague)                    │
│  📧 zhangsan@abc.com (has_contact)      │
│  📄 项目合作协议 (mentioned_in)         │
│  🏢 XYZ公司 (partner_with)              │
│  [➕ 添加关联]                          │
│                                         │
│ 📅 相关事件 (3)                         │
│  • 2024-01-15 名片扫描                  │
│  • 2024-01-10 会议纪要                  │
│  • 2024-01-08 邮件往来                  │
│                                         │
│ 🎬 操作                                 │
│  [🔀 合并实体] [🗑️ 删除] [📤 导出]      │
└─────────────────────────────────────────┘
```

**API需求:**
```
GET /api/v1/entities/{entity_id}
Response: {
  "entity": {...},
  "attributes": {...},
  "sources": [...],
  "associations": [...],
  "related_events": [...]
}
```

---

### 1.5 数据管理中心 (`/data-management`)

**Tab式导航:**
```
┌─────────────────────────────────────────┐
│ 🗄️ 数据管理中心                         │
├─────────────────────────────────────────┤
│ [📄 事件] [👤 实体] [🔗 关联] [🏷️ 标签] │
│                                         │
│ === 实体管理 ===                        │
│ 筛选: [类型▼] [来源▼] [置信度▼]        │
│ 搜索: [_________________] [🔍]          │
│                                         │
│ ┌─────────────────────────────────────┐ │
│ │ 👤 张三 | Person | 95% | 3个来源    │ │
│ │ 🏢 ABC科技 | Org | 98% | 2个来源   │ │
│ │ 📧 zhangsan@abc.com | Contact | 100%│ │
│ └─────────────────────────────────────┘ │
│                                         │
│ [批量操作▼] 已选择 0 项                 │
└─────────────────────────────────────────┘
```

**API需求:**
```
GET /api/v1/entities?type=person&confidence_min=0.8&page=1
GET /api/v1/associations?entity_id=xxx
GET /api/v1/events?status=processed&page=1
GET /api/v1/tags
```

---

### 1.6 名片扫描结果页 (`/scan-result/{event_id}`)

**即时展示(扫描后3秒内):**
```
┌─────────────────────────────────────────┐
│ ✅ 名片扫描完成                         │
├─────────────────────────────────────────┤
│ 📸 扫描图片                             │
│  [名片图片]                             │
│                                         │
│ 🤖 识别结果                             │
│  ✓ 姓名: 张三                           │
│  ✓ 职位: 产品经理                       │
│  ✓ 公司: ABC科技                        │
│  ✓ 电话: 138****1234                    │
│  ✓ 邮箱: zhangsan@abc.com               │
│  ⚠️ 地址: [置信度低,请确认]             │
│                                         │
│ ✅ 自动生成待办 (2)                     │
│  ☐ 回复张三邮件                         │
│  ☐ 添加张三到CRM系统                    │
│                                         │
│ 🎬 下一步                               │
│  [✏️ 修正信息] [✅ 确认无误] [🗑️ 删除]  │
└─────────────────────────────────────────┘
```

**API需求:**
```
POST /api/v1/events/business-card/scan
  (multipart/form-data: image file)
Response: {
  "event_id": "evt_xxx",
  "extracted_data": {...},
  "confidence_scores": {...},
  "todos_generated": [...],
  "entities_created": [...]
}
```

---

### 1.7 会议纪要结果页 (`/meeting-result/{event_id}`)

**4种类型差异化展示:**

#### 类型1: 项目启动会
```
┌─────────────────────────────────────────┐
│ 📝 会议纪要分析 - 项目启动会            │
├─────────────────────────────────────────┤
│ 📅 2024-01-15 | 参会人: 5人             │
│                                         │
│ 🎯 会议目标                             │
│  启动XYZ项目,明确分工和里程碑           │
│                                         │
│ 👥 参会人员                             │
│  张三(PM)、李四(开发)、王五(设计)...    │
│                                         │
│ ✅ 行动项 (5)                           │
│  ☐ 张三: 完成PRD v1.0 - 截止1月20日     │
│  ☐ 李四: 搭建开发环境 - 截止1月18日     │
│  ☐ 王五: 输出UI原型 - 截止1月22日       │
│                                         │
│ 📌 决策事项 (3)                         │
│  • 采用FastAPI框架                      │
│  • 每周三下午3点例会                    │
│  • 使用Jira管理任务                     │
│                                         │
│ 🔗 关联实体 (8)                         │
│  👤 张三、李四、王五...                 │
│  🏢 XYZ项目                             │
│  📄 PRD文档                             │
└─────────────────────────────────────────┘
```

#### 类型2: 客户拜访
```
┌─────────────────────────────────────────┐
│ 📝 会议纪要分析 - 客户拜访              │
├─────────────────────────────────────────┤
│ 🏢 客户: ABC公司 | 日期: 2024-01-15     │
│                                         │
│ 💼 客户需求                             │
│  • 需要CRM系统集成                      │
│  • 预算范围: 50-80万                    │
│  • 期望3月上线                          │
│                                         │
│ 🤝 商机评估                             │
│  意向度: ⭐⭐⭐⭐ (高)                   │
│  预计成交: 2024-Q1                      │
│                                         │
│ ✅ 跟进事项 (3)                         │
│  ☐ 发送方案PPT - 截止1月17日            │
│  ☐ 安排技术交流会 - 截止1月20日         │
│  ☐ 准备报价单 - 截止1月22日             │
│                                         │
│ 🔗 关联实体                             │
│  🏢 ABC公司                             │
│  👤 客户方:张总、李经理                 │
│  👤 我方:销售王五、技术赵六             │
└─────────────────────────────────────────┘
```

**API需求:**
```
POST /api/v1/events/meeting-minutes/upload
  (multipart/form-data: file or text)
Response: {
  "event_id": "evt_xxx",
  "meeting_type": "project_kickoff",
  "extracted_data": {
    "attendees": [...],
    "action_items": [...],
    "decisions": [...],
    "key_points": [...]
  },
  "todos_generated": [...],
  "entities_created": [...]
}
```

---

### 1.8 搜索页 (`/search`)

**模糊查找+交叉检索:**
```
┌─────────────────────────────────────────┐
│ 🔍 搜索                                 │
├─────────────────────────────────────────┤
│ [张三_____________________] [🔍 搜索]   │
│                                         │
│ 高级筛选:                               │
│  类型: [全部▼] 时间: [最近30天▼]       │
│  来源: [全部▼] 标签: [___________]     │
│                                         │
│ === 搜索结果 (15) ===                   │
│                                         │
│ 👤 实体 (3)                             │
│  • 张三 (Person) - 产品经理@ABC科技     │
│  • 张三丰 (Person) - 技术总监@XYZ       │
│  • 张三的公司 (Organization)            │
│                                         │
│ 📄 事件 (8)                             │
│  • 2024-01-15 扫描了张三名片            │
│  • 2024-01-10 会议提到张三              │
│  • 2024-01-08 收到张三邮件              │
│                                         │
│ ✅ 待办 (4)                             │
│  • 回复张三邮件                         │
│  • 跟进张三合作事宜                     │
└─────────────────────────────────────────┘
```

**API需求:**
```
GET /api/v1/search?q=张三&type=all&date_range=30d
Response: {
  "entities": [...],
  "events": [...],
  "todos": [...],
  "associations": [...],
  "total": 15
}
```

---

## 2️⃣ 用户操作流程(端到端)

### 流程1: 扫描名片→执行行动→标记完成

```
用户操作                    系统响应                    API调用
─────────────────────────────────────────────────────────────
1. 点击"扫描名片"           打开相机/文件选择器          -
2. 拍照/上传图片            显示上传进度                POST /api/v1/events/business-card/scan
3. 等待3秒                  显示扫描结果页              (后台:OCR→NER→实体归一→Todo生成)
4. 查看识别结果             高亮低置信度字段            -
5. 修正错误信息             实时保存修改                PATCH /api/v1/events/{id}/extracted-data
6. 点击"确认无误"           跳转到Todo列表              -
7. 看到"回复张三邮件"       显示Todo详情                GET /api/v1/todos?source_event={id}
8. 点击Todo                 打开Todo详情页              GET /api/v1/todos/{todo_id}
9. 执行行动(发邮件)         -                           -
10. 勾选"已完成"            Todo标记完成,从列表消失     PATCH /api/v1/todos/{id} {status: "done"}
```

**关键体验指标:**
- 步骤3(扫描结果):<3秒
- 步骤5(修正保存):实时(<200ms)
- 步骤7(Todo列表):<1秒

---

### 流程2: 上传会议纪要→确认/修正→执行行动项

```
用户操作                    系统响应                    API调用
─────────────────────────────────────────────────────────────
1. 点击"上传纪要"           打开文件选择器              -
2. 选择文件                 显示上传进度                POST /api/v1/events/meeting-minutes/upload
3. 等待30秒                 显示"正在分析..."进度条     (后台异步处理)
4. 收到通知                 "会议纪要分析完成"          WebSocket推送 或 轮询
5. 点击通知                 跳转到会议结果页            GET /api/v1/events/{id}
6. 查看行动项列表           显示5个行动项               -
7. 发现"张三"应为"李四"     点击修正                    -
8. 修改负责人               实时保存                    PATCH /api/v1/todos/{id} {assignee: "李四"}
9. 点击"确认无误"           行动项进入Todo列表          -
10. 在Todo列表执行          逐个完成                    PATCH /api/v1/todos/{id}
```

**关键体验指标:**
- 步骤3(分析完成):<30秒(后台异步)
- 步骤4(通知延迟):<5秒
- 步骤8(修正保存):实时(<200ms)

---

### 流程3: 浏览数据→发现错误→修正→验证

```
用户操作                    系统响应                    API调用
─────────────────────────────────────────────────────────────
1. 进入数据管理中心         显示实体列表                GET /api/v1/entities?page=1
2. 发现重复实体             "张三"出现2次               -
   (张三-Person-1)
   (张三-Person-2)
3. 点击第一个"张三"         显示实体详情                GET /api/v1/entities/{id1}
4. 查看来源标记             来源:名片扫描               -
5. 点击"合并实体"           弹出合并确认对话框          -
6. 选择第二个"张三"         显示合并预览                GET /api/v1/entities/{id2}
7. 确认合并                 执行合并,显示进度           POST /api/v1/entities/merge
                                                        {source: id1, target: id2}
8. 合并完成                 跳转到合并后实体详情        GET /api/v1/entities/{id2}
9. 验证关联关系             显示所有关联(来自两个实体)  -
10. 验证相关事件            显示所有来源事件            -
```

**关键体验指标:**
- 步骤1(列表加载):<1秒
- 步骤3(详情加载):<500ms
- 步骤7(合并执行):<2秒

---

### 流程4: 搜索→查看关联→添加/删除关联

```
用户操作                    系统响应                    API调用
─────────────────────────────────────────────────────────────
1. 在搜索框输入"张三"       实时显示搜索建议            GET /api/v1/search/suggest?q=张三
2. 选择"张三(Person)"       跳转到实体详情页            GET /api/v1/entities/{id}
3. 查看关联实体             显示5个关联                 -
4. 发现缺少"ABC科技"关联    点击"添加关联"              -
5. 搜索"ABC科技"            显示搜索结果                GET /api/v1/entities/search?q=ABC科技
6. 选择"ABC科技(Org)"       选择关联类型                -
7. 选择"works_at"           确认添加                    POST /api/v1/associations
                                                        {from: 张三, to: ABC科技, type: works_at}
8. 添加成功                 关联出现在列表              GET /api/v1/entities/{id}
9. 发现错误关联             点击"删除"                  -
10. 确认删除                关联从列表消失              DELETE /api/v1/associations/{id}
```

**关键体验指标:**
- 步骤1(搜索建议):<300ms
- 步骤7(添加关联):<500ms
- 步骤10(删除关联):<300ms

---

## 3️⃣ API设计(从页面倒推)

### 3.1 核心API清单

#### Dashboard APIs
```
GET /api/v1/dashboard/summary
  → 今日Todo、近期事件、统计数据
```

#### Todo APIs
```
GET /api/v1/todos
  ?type=action|info
  &status=pending|done
  &source=business_card|meeting|email|chat
  &sort=deadline|priority|created_at
  → Todo列表(分页)

GET /api/v1/todos/{todo_id}
  → Todo详情

PATCH /api/v1/todos/{todo_id}
  Body: {status: "done", assignee: "xxx", ...}
  → 更新Todo

DELETE /api/v1/todos/{todo_id}
  → 删除Todo
```

#### Event APIs
```
POST /api/v1/events/business-card/scan
  Body: multipart/form-data (image)
  → 扫描名片(同步返回结果)

POST /api/v1/events/meeting-minutes/upload
  Body: multipart/form-data (file) 或 {text: "..."}
  → 上传会议纪要(异步处理)

GET /api/v1/events/{event_id}
  → 事件详情(含原始内容、提取结果、关联Todo/实体)

GET /api/v1/events/{event_id}/status
  → 异步事件处理状态(用于轮询)

PATCH /api/v1/events/{event_id}/extracted-data
  Body: {field: "name", value: "张三", ...}
  → 修正提取结果

DELETE /api/v1/events/{event_id}
  → 删除事件
```

#### Entity APIs
```
GET /api/v1/entities
  ?type=person|organization|contact|document
  &confidence_min=0.8
  &source=business_card|meeting|...
  &page=1&page_size=20
  → 实体列表(分页)

GET /api/v1/entities/{entity_id}
  → 实体详情(含属性、来源、关联、相关事件)

PATCH /api/v1/entities/{entity_id}
  Body: {attributes: {...}, ...}
  → 更新实体属性

POST /api/v1/entities/merge
  Body: {source_id: "xxx", target_id: "yyy"}
  → 合并实体

DELETE /api/v1/entities/{entity_id}
  → 删除实体

GET /api/v1/entities/search
  ?q=张三&type=person
  → 搜索实体(用于添加关联时)
```

#### Association APIs
```
GET /api/v1/associations
  ?entity_id=xxx
  → 获取实体的所有关联

POST /api/v1/associations
  Body: {from_entity_id: "xxx", to_entity_id: "yyy", type: "works_at"}
  → 添加关联

DELETE /api/v1/associations/{association_id}
  → 删除关联

GET /api/v1/associations/types
  → 获取支持的关联类型列表
```

#### Search APIs
```
GET /api/v1/search
  ?q=张三
  &type=all|entity|event|todo
  &date_range=7d|30d|90d|all
  &source=business_card|meeting|...
  → 全局搜索

GET /api/v1/search/suggest
  ?q=张
  → 搜索建议(自动补全)
```

---

### 3.2 API响应格式标准

**成功响应:**
```json
{
  "success": true,
  "data": {...},
  "meta": {
    "page": 1,
    "page_size": 20,
    "total": 100
  }
}
```

**错误响应:**
```json
{
  "success": false,
  "error": {
    "code": "ENTITY_NOT_FOUND",
    "message": "实体不存在",
    "details": {...}
  }
}
```

**异步任务响应:**
```json
{
  "success": true,
  "task_id": "task_xxx",
  "status": "processing",
  "estimated_time": 30
}
```

---

## 4️⃣ 技术架构(支撑页面的后端设计)

### 4.1 三层模型解耦

```
┌─────────────────────────────────────────────────────────┐
│ L1: API Layer (FastAPI)                                 │
│  - 路由定义                                             │
│  - 请求验证(Pydantic)                                   │
│  - 响应序列化                                           │
│  - 错误处理                                             │
└─────────────────────────────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────┐
│ L2: Service Layer (业务逻辑)                            │
│  - EventService: 事件管线路由                           │
│  - EntityService: 实体归一算法                          │
│  - AssociationService: 关联发现算法                     │
│  - TodoService: Todo生成与追踪                          │
│  - SearchService: 搜索与索引                            │
└─────────────────────────────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────┐
│ L3: Data Layer (数据访问)                               │
│  - Repository模式                                       │
│  - PostgreSQL: 结构化数据(Entity/Association/Event/Todo)│
│  - Redis: 缓存(实体索引、搜索结果)                      │
│  - NetworkX: 图计算(关联发现)                           │
└─────────────────────────────────────────────────────────┘
```

**解耦原则:**
- L1不包含业务逻辑,只做参数验证和响应格式化
- L2不直接操作数据库,通过L3的Repository
- L3不包含业务规则,只提供CRUD接口

---

### 4.2 四条事件管线

### 🤖 ui [✅]
---
# PromiseLink 架构重新设计(客户视角驱动)

## 设计原则确认
✅ 从用户场景倒推,不是从技术正推
✅ 先定义页面和操作,再设计支撑架构
✅ 每个设计决策必须回答:"这能让用户顺畅完成核心操作吗?"

---

## 第一部分:用户页面架构(用户第一眼看到什么)

### 1.1 首页/仪表盘(Dashboard)
**用户第一眼看到:**
```
┌─────────────────────────────────────────┐
│ PromiseLink - 今日概览                     │
├─────────────────────────────────────────┤
│ 🔴 紧急待办 (3)                          │
│ ├─ 回复张总邮件 (今天 14:00前)          │
│ ├─ 准备周五演示材料 (明天)              │
│ └─ 联系李工讨论技术方案 (本周)          │
│                                          │
│ 📊 本周统计                              │
│ ├─ 处理事件: 12 | 新增Todo: 8           │
│ ├─ 完成Todo: 5  | 新增联系人: 3         │
│                                          │
│ 🎯 快捷操作                              │
│ [📷 扫描名片] [📝 上传会议纪要]          │
│ [🔍 搜索] [📋 查看所有Todo]              │
│                                          │
│ 📅 最近事件 (5条)                        │
│ ├─ 会议纪要_产品评审.txt (2小时前)      │
│ ├─ 名片_张伟.jpg (今天 10:30)           │
│ └─ ...                                   │
└─────────────────────────────────────────┘
```

**关键设计决策:**
- 紧急待办置顶(红色标记),按截止时间排序
- 统计数据提供成就感和进度感知
- 快捷操作直达核心功能(扫描/上传)
- 最近事件提供上下文连续性

**API需求:**
- `GET /api/dashboard/summary` - 返回今日Todo、统计、最近事件
- `GET /api/todos?urgent=true&limit=5` - 紧急待办
- `GET /api/events/recent?limit=5` - 最近事件

---

### 1.2 Todo列表页(核心工作台)
**信息型/行动型分离展示:**
```
┌─────────────────────────────────────────┐
│ Todo列表                                 │
├─────────────────────────────────────────┤
│ [行动型] [信息型] [全部] [已完成]       │
│ 排序: [截止时间▼] [优先级] [创建时间]  │
│ 筛选: [标签] [来源事件] [关联实体]      │
├─────────────────────────────────────────┤
│ 🔴 行动型 (需要执行)                     │
│ ┌─────────────────────────────────────┐ │
│ │ ☐ 回复张总邮件                       │ │
│ │   📅 今天 14:00前 | 🏷️ 紧急          │ │
│ │   来源: 会议纪要_产品评审.txt        │ │
│ │   关联: 张总(CEO) → 产品路线图       │ │
│ │   [查看详情] [标记完成] [延期]       │ │
│ └─────────────────────────────────────┘ │
│                                          │
│ 📘 信息型 (需要记住)                     │
│ ┌─────────────────────────────────────┐ │
│ │ ☐ 张总偏好:周五下午开会              │ │
│ │   来源: 名片_张伟.jpg                │ │
│ │   关联: 张总(CEO)                    │ │
│ │   [查看详情] [已知晓]                │ │
│ └─────────────────────────────────────┘ │
└─────────────────────────────────────────┘
```

**关键设计决策:**
- 行动型/信息型Tab分离,避免混淆
- 每个Todo显示来源事件和关联实体(可追溯)
- 操作按钮差异化:行动型[标记完成],信息型[已知晓]
- 筛选器支持交叉检索(标签+实体+事件)

**API需求:**
- `GET /api/todos?type=action&status=pending&sort=deadline` - 行动型待办
- `GET /api/todos?type=info&status=pending` - 信息型待办
- `PATCH /api/todos/{id}/complete` - 标记完成
- `GET /api/todos/{id}/context` - 获取Todo的完整上下文(来源事件+关联实体)

---

### 1.3 事件详情页(原始+AI提取结果)
**用户看到完整处理链路:**
```
┌─────────────────────────────────────────┐
│ 事件详情: 会议纪要_产品评审.txt         │
├─────────────────────────────────────────┤
│ 📄 原始内容                              │
│ ┌─────────────────────────────────────┐ │
│ │ 2025-06-01 产品评审会议              │ │
│ │ 参会人:张总(CEO)、李工(CTO)...       │ │
│ │ 决策:Q3上线PromiseLink MVP...          │ │
│ └─────────────────────────────────────┘ │
│                                          │
│ 🤖 AI提取结果                            │
│ ├─ 事件类型: 会议纪要(决策型)           │
│ ├─ 处理管线: Pipeline 3(决策型会议)     │
│ ├─ 置信度: 92%                          │
│                                          │
│ 👥 提取实体 (3个)                        │
│ ├─ 张总 [Person] → 已归一到"张伟(CEO)" │
│ ├─ PromiseLink [Product] → 新建实体       │
│ └─ Q3 [Timeline] → 关联到"2025Q3"       │
│                                          │
│ 🔗 发现关联 (2条)                        │
│ ├─ 张总 --决策--> PromiseLink MVP         │
│ └─ PromiseLink --计划上线--> 2025Q3       │
│                                          │
│ ✅ 生成Todo (3个)                        │
│ ├─ [行动] 准备MVP演示材料 (本周五)      │
│ ├─ [行动] 联系李工讨论技术方案          │
│ └─ [信息] 张总关注Q3上线时间点          │
│                                          │
│ [重新处理] [修正提取] [删除事件]        │
└─────────────────────────────────────────┘
```

**关键设计决策:**
- 原始内容始终可见(可追溯性)
- AI提取结果分层展示:实体→关联→Todo
- 每个提取项显示置信度和归一状态
- 提供修正入口(用户反馈循环)

**API需求:**
- `GET /api/events/{id}/detail` - 完整事件详情
- `GET /api/events/{id}/extraction` - AI提取结果
- `POST /api/events/{id}/reprocess` - 重新处理
- `PATCH /api/events/{id}/entities/{entity_id}/correct` - 修正实体

---

### 1.4 实体详情页(属性+来源+关联)
**用户看到实体的完整画像:**
```
┌─────────────────────────────────────────┐
│ 实体详情: 张伟(CEO)                      │
├─────────────────────────────────────────┤
│ 📇 基本信息                              │
│ ├─ 类型: Person                         │
│ ├─ 姓名: 张伟                           │
│ ├─ 职位: CEO                            │
│ ├─ 公司: XX科技                         │
│ ├─ 手机: 138****1234                    │
│ ├─ 邮箱: zhang@example.com              │
│                                          │
│ 📊 来源标记 (3个事件)                    │
│ ├─ 名片_张伟.jpg (2025-06-01)           │
│ ├─ 会议纪要_产品评审.txt (2025-06-01)   │
│ └─ 邮件_项目进展.eml (2025-05-28)       │
│                                          │
│ 🔗 关联实体 (5条)                        │
│ ├─ 张伟 --任职--> XX科技 [Company]      │
│ ├─ 张伟 --决策--> PromiseLink [Product]   │
│ ├─ 张伟 --合作--> 李工 [Person]         │
│ └─ ...                                   │
│                                          │
│ 📋 相关Todo (2个)                        │
│ ├─ 回复张总邮件 (今天 14:00前)          │
│ └─ 准备周五演示材料给张总               │
│                                          │
│ [编辑] [合并实体] [删除]                │
└─────────────────────────────────────────┘
```

**关键设计决策:**
- 来源标记提供可追溯性(哪些事件提到这个人)
- 关联实体展示知识图谱(人-公司-产品-时间)
- 相关Todo直接展示(上下文连续性)
- 提供合并入口(解决重复实体问题)

**API需求:**
- `GET /api/entities/{id}/profile` - 实体完整画像
- `GET /api/entities/{id}/sources` - 来源事件列表
- `GET /api/entities/{id}/associations` - 关联实体
- `GET /api/entities/{id}/todos` - 相关Todo
- `POST /api/entities/{id}/merge` - 合并实体

---

### 1.5 数据管理中心(浏览和管理)
**用户看到所有数据的全局视图:**
```
┌─────────────────────────────────────────┐
│ 数据管理中心                             │
├─────────────────────────────────────────┤
│ [事件] [实体] [关联] [标签]             │
├─────────────────────────────────────────┤
│ 📊 实体总览 (125个)                      │
│ ├─ Person: 45 | Company: 23             │
│ ├─ Product: 12 | Timeline: 8            │
│ └─ Other: 37                            │
│                                          │
│ 🔍 筛选和搜索                            │
│ [类型] [标签] [来源事件] [创建时间]     │
│ [搜索框: 模糊查找实体名称...]           │
│                                          │
│ 📋 实体列表                              │
│ ┌─────────────────────────────────────┐ │
│ │ 张伟(CEO) [Person]                   │ │
│ │ ├─ 来源: 3个事件                     │ │
│ │ ├─ 关联: 5条                         │ │
│ │ └─ 最后更新: 2小时前                 │ │
│ │ [查看] [编辑] [删除]                 │ │
│ └─────────────────────────────────────┘ │
│                                          │
│ 🔧 批量操作                              │
│ [导出CSV] [批量删除] [批量打标签]       │
└─────────────────────────────────────────┘
```

**关键设计决策:**
- 分Tab管理不同数据类型(事件/实体/关联/标签)
- 统计数据提供全局感知
- 支持批量操作(提高效率)
- 每个实体显示元数据(来源数、关联数、更新时间)

**API需求:**
- `GET /api/entities?type=Person&limit=50&offset=0` - 分页实体列表
- `GET /api/entities/stats` - 统计数据
- `DELETE /api/entities/batch` - 批量删除
- `POST /api/entities/export` - 导出CSV

---

### 1.6 名片扫描结果页(即时反馈)
**用户扫描后立即看到:**
```
┌─────────────────────────────────────────┐
│ 名片扫描结果                             │
├─────────────────────────────────────────┤
│ 📷 原始图片                              │
│ [名片图片预览]                           │
│                                          │
│ ✅ 识别完成 (3秒)                        │
│                                          │
│ 👤 提取信息                              │
│ ├─ 姓名: 张伟                           │
│ ├─ 职位: CEO                            │
│ ├─ 公司: XX科技                         │
│ ├─ 手机: 138-1234-5678                  │
│ ├─ 邮箱: zhang@example.com              │
│ ├─ 地址: 北京市朝阳区...                │
│                                          │
│ 🤖 AI分析                                │
│ ├─ 实体归一: 发现已存在"张伟(CEO)"      │
│ ├─ 建议操作: 更新现有实体信息           │
│                                          │
│ ✅ 生成Todo (2个)                        │
│ ├─ [行动] 添加张总微信                  │
│ ├─ [信息] 张总公司地址已更新            │
│                                          │
│ [确认保存] [修正信息] [重新扫描]        │
└─────────────────────────────────────────┘
```

**关键设计决策:**
- 原始图片+提取结果并排展示(可验证)
- 实时显示归一结果(避免重复实体)
- 自动生成Todo(立即可执行)
- 提供修正入口(OCR错误修正)

**API需求:**
- `POST /api/events/business-card/scan` - 上传名片图片
- `GET /api/events/{id}/scan-result` - 轮询扫描结果
- `PATCH /api/events/{id}/correct` - 修正提取信息
- `POST /api/events/{id}/confirm` - 确认保存

**性能要求:** <3秒返回结果

---

### 1.7 会议纪要结果页(4种类型差异化展示)
**决策型会议纪要:**
```
┌─────────────────────────────────────────┐
│ 会议纪要分析: 产品评审会议(决策型)      │
├─────────────────────────────────────────┤
│ 🎯 关键决策 (3条)                        │
│ ├─ Q3上线PromiseLink MVP                  │
│ ├─ 优先开发名片扫描功能                 │
│ └─ 预算批准50万                         │
│                                          │
│ 👥 决策者 (2人)                          │
│ ├─ 张伟(CEO) - 最终决策                 │
│ └─ 李工(CTO) - 技术评估                 │
│                                          │
│ ✅ 行动项 (5个)                          │
│ ├─ [紧急] 准备MVP演示材料 (本周五)      │
│ ├─ 联系李工讨论技术方案                 │
│ └─ ...                                   │
│                                          │
│ 📊 影响分析                              │
│ ├─ 影响产品: PromiseLink                  │
│ ├─ 影响时间线: 2025Q3                   │
│ └─ 涉及预算: 50万                       │
└─────────────────────────────────────────┘
```

**头脑风暴型会议纪要:**
```
┌─────────────────────────────────────────┐
│ 会议纪要分析: 产品创意讨论(头脑风暴型) │
├─────────────────────────────────────────┤
│ 💡 创意点 (8个)                          │
│ ├─ AI自动分类Todo                       │
│ ├─ 语音输入会议纪要                     │
│ ├─ 实体关系可视化                       │
│ └─ ...                                   │
│                                          │
│ 🔥 高频主题                              │
│ ├─ AI能力 (提及5次)                     │
│ ├─ 用户体验 (提及4次)                   │
│                                          │
│ 📋 待验证想法 (3个)                      │
│ ├─ [信息] 调研竞品AI功能                │
│ ├─ [信息] 收集用户对语音输入的反馈      │
│ └─ ...                                   │
└─────────────────────────────────────────┘
```

**关键设计决策:**
- 4种会议类型(决策/头脑风暴/进展同步/问题解决)差异化展示
- 决策型突出决策和行动项
- 头脑风暴型突出创意和主题
- 进展同步型突出进度和阻塞
- 问题解决型突出问题和解决方案

**API需求:**
- `POST /api/events/meeting-notes/upload` - 上传会议纪要
- `GET /api/events/{id}/analysis` - 获取分析结果(异步)
- `GET /api/events/{id}/meeting-type` - 获取会议类型

**性能要求:** <30秒完成分析(后台异步)

---

### 1.8 搜索页(模糊查找+交叉检索)
**用户看到智能搜索结果:**
```
┌─────────────────────────────────────────┐
│ 搜索: "张总 产品"                        │
├─────────────────────────────────────────┤
│ 🔍 搜索结果 (12条)                       │
│                                          │
│ 👥 实体 (3个)                            │
│ ├─ 张伟(CEO) - 匹配"张总"               │
│ ├─ PromiseLink [Product] - 匹配"产品"     │
│ └─ 产品路线图 [Document]                │
│                                          │
│ 📄 事件 (5个)                            │
│ ├─ 会议纪要_产品评审.txt                │
│ │   "张总决定Q3上线产品..."             │
│ ├─ 邮件_产品进展.eml                    │
│ └─ ...                                   │
│                                          │
│ ✅ Todo (4个)                            │
│ ├─ 回复张总关于产品的邮件               │
│ ├─ 准备产品演示给张总                   │
│ └─ ...                                   │
│                                          │
│ 🔗 关联 (2条)                            │
│ ├─ 张伟 --决策--> PromiseLink             │
│ └─ 张伟 --关注--> 产品路线图             │
└─────────────────────────────────────────┘
```

**关键设计决策:**
- 分类展示搜索结果(实体/事件/Todo/关联)
- 高亮匹配关键词
- 支持模糊匹配和同义词(张总=张伟)
- 支持交叉检索(实体+标签+时间范围)

**API需求:**
- `GET /api/search?q=张总 产品&types=entity,event,todo` - 全局搜索
- `GET /api/search/suggest?q=张` - 搜索建议

---

## 第二部分:用户操作流程(核心链路)

### 2.1 名片扫描完整链路
```
用户操作                    系统响应                    页面跳转
─────────────────────────────────────────────────────────────
1. 点击[扫描名片]          → 打开相机/文件选择器        Dashboard
2. 拍照/选择图片           → 上传图片                   
3. 等待处理(3秒)           → OCR+实体提取+归一          Loading
4. 查看扫描结果            → 显示提取信息+Todo          ScanResult页
5. 确认/修正信息           → 保存实体+创建Todo          
6. 点击[查看Todo]          → 跳转到Todo列表             TodoList页
7. 执行行动项              → 标记完成                   
8. 返回Dashboard           → 更新统计数据               Dashboard
```

**关键卡点分析:**
- 卡点1: OCR识别错误 → 提供修正入口
- 卡点2: 实体归一失败(重复) → 显示归一建议,用户确认
- 卡点3: Todo不明确 → 允许用户编辑Todo描述

**API调用链:**
```
POST /api/events/business-card/scan
  ↓
GET /api/events/{id}/scan-result (轮询)
  ↓
PATCH /api/events/{id}/correct (如果需要修正)
  ↓
POST /api/events/{id}/confirm
  ↓
GET /api/todos?source_event={id}
```

---

### 2.2 会议纪要上传完整链路
```
用户操作                    系统响应                    页面跳转
─────────────────────────────────────────────────────────────
1. 点击[上传会议纪要]      → 打开文件选择器             Dashboard
2. 选择文件(.txt/.docx)    → 上传文件                   
3. 等待分析(30秒)          → 后台异步处理               Loading
4. 收到通知"分析完成"      → 显示分析结果               MeetingResult页
5. 查看提取的实体/关联     → 展示知识图谱               
6. 查看生成的Todo          → 按类型分组展示             
7. 确认/修正提取结果       → 更新实体和Todo             
8. 点击某个Todo            → 跳转到Todo详情             TodoDetail页
9. 执行行动项              → 标记完成                   
```

**关键卡点分析:**
- 卡点1: 会议类型识别错误 → 允许用户手动选择类型,重新分析
- 卡点2: 实体提取遗漏 → 提供手动添加实体入口
- 卡点3: Todo优先级不准 → 允许用户调整优先级和截止时间

**API调用链:**
```
POST /api/events/meeting-notes/upload
  ↓
GET /api/events/{id}/status (轮询处理状态)
  ↓
GET /api/events/{id}/analysis
  ↓
PATCH /api/events/{id}/entities/{entity_id}/correct
  ↓
PATCH /api/todos/{id}/update
```

---

### 2.3 数据修正完整链路
```
用户操作                    系统响应                    页面跳转
─────────────────────────────────────────────────────────────
1. 浏览实体列表            → 显示所有实体               DataCenter页
2. 发现重复实体            → 点击[合并实体]             
3. 选择要合并的实体        → 显示合并预览               MergePreview页
4. 确认合并                → 执行合并,更新关联          
5. 验证合并结果            → 显示合并后的实体详情       EntityDetail页
6. 检查关联Todo            → 显示相关Todo               
7. 返回实体列表            → 更新列表(重复实体已消失)   DataCenter页
```

**关键卡点分析:**
- 卡点1: 合并后关联丢失 → 合并前显示影响范围,用户确认
- 卡点2: 合并错误无法撤销 → 提供撤销合并功能(保留合并历史)

**API调用链:**
```
GET /api/entities?duplicate=true
  ↓
POST /api/entities/{id}/merge-preview
  ↓
POST /api/entities/{id}/merge
  ↓
GET /api/entities/{id}/profile (验证)
```

---

### 2.4 搜索和关联发现链路
```
用户操作                    系统响应                    页面跳转
─────────────────────────────────────────────────────────────
1. 输入搜索关键词          → 实时搜索建议               Search页
2. 选择搜索结果            → 显示实体详情               EntityDetail页
3. 查看关联实体            → 显示知识图谱               
4. 点击某个关联            → 跳转到关联实体详情         EntityDetail页
5. 发现缺失关联            → 点击[添加关联]             
6. 选择关联类型和目标实体  → 创建新关联                 
7. 验证关联                → 显示更新后的知识图谱       
```

**关键卡点分析:**
- 卡点1: 搜索结果太多 → 提供高级筛选(类型/标签/时间)
- 卡点2: 关联类型不明确 → 提供常用关联类型模板

**API调用链:**
```
GET /api/search?q=keyword
  ↓
GET /api/entities/{id}/profile
  ↓
GET /api/entities/{id}/associations
  ↓
POST /api/associations/create
  ↓
GET /api/entities/{id}/associations (验证)
```

---

## 第三部分:API设计(从页面倒推)

### 3.1 Dashboard API
```python
# 首页概览
GET /api/dashboard/summary
Response:
{
  "urgent_todos": [
    {
      "id": "todo-123",
      "title": "回复张总邮件",
      "type": "action",
      "deadline": "2025-06-01T14:00:00Z",
      "priority": "high",
      "source_event": {"id": "event-456", "title": "会议纪要_产品评审.txt"}
    }
  ],
  "stats": {
    "events_this_week": 12,
    "todos_created": 8,
    "todos_completed": 5,
    "entities_added": 3
  },
  "recent_events": [
    {
      "id": "event-456",
      "title": "会议纪要_产品评审.txt",
      "type": "meeting_notes",
      "created_at": "2025-06-01T10:30:00Z",
      "status": "processed"
    }
  ]
}
```

### 3.2 Todo API
```python
# 获取Todo列表(支持筛选和排序)
GET /api/todos?type=action&status=pending&sort=deadline&limit=20&offset=0
Response:
{
  "total": 45,
  "items": [
    {
      "id": "todo-123",
      "title": "回复张总邮件",
      "type": "action",
      "status": "pending",
      "priority": "high",
      "deadline": "2025-06-01T14:00:00Z",
      "source_event": {
        "id": "event-456",
        "title": "会议纪要_产品评审.txt",
        "type": "meeting_notes"
      },
      "related_entities": [
        {"id": "entity-789", "name": "张伟(CEO)", "type": "Person"}
      ],
      "tags": ["紧急", "产品"]
    }
  ]
}

# 获取Todo完整上下文
GET /api/todos/{id}/context
Response:
{
  "todo": {...},
  "source_event": {
    "

## 📝 Scratchpad 共享区
# Scratchpad Summary (scratchpad-20260601-180503)
**Total entries**: 15 | **Active findings**: 14 | **Conflicts**: 0

## 🔍 Key Findings (14)
- [ui-designer-30adfb/ui-designer] # PromiseLink 架构重新设计(客户视角驱动)

## 设计原则确认
✅ 从用户场景倒推,不是从技术正推
✅ 先定义页面和操作,再设计支撑架构
✅ 每个设计决策必须回答:"这能让用户顺畅完成核心操作吗?"

---

## 第一部分: (confidence: 70%)
- [devops-f914e9/devops] # PromiseLink 架构重新设计(客户视角驱动)

## 🎯 设计原则确认

**核心方法论**:从用户看到的屏幕倒推到数据库表结构,而不是反过来。

---

## 1️⃣ 页面架构设计(用户第一视角)

### 1.1 首页/仪表盘 (confidence: 70%)
- [tester-330991/tester] # PromiseLink 架构重新设计(客户视角驱动)

## 一、用户视角:页面与操作流程优先

### 1.1 页面架构设计

#### 1.1.1 首页/仪表盘 (`/dashboard`)
**用户第一眼看到:**
```
┌──── (confidence: 70%)
- [product-manager-4056da/product-manager] # PromiseLink 架构重新设计(客户视角驱动)

## 设计原则确认

✅ **核心原则理解**:从用户看到的页面和操作倒推架构,而非从技术栈正推。

---

## 第一部分:页面架构设计

### 1.1 首页/仪表盘 (Dash (confidence: 70%)
- [security-6220a1/security] # PromiseLink 架构重新设计(客户视角驱动)

## 设计原则确认

✅ **从用户场景倒推架构,不是从技术正推**
✅ **先定义页面和操作,再设计支撑架构**
✅ **每个设计决策必须回答:这能让用户顺畅完成操作吗?**

-- (confidence: 70%)
- [solo-coder-7a74c7/solo-coder] # PromiseLink 架构重新设计(客户视角驱动)

## 一、用户视角出发点

作为开发者,我首先要问:**用户拿到这个产品,第一步做什么?**

### 核心用户旅程
1. **扫描名片** → 立即看到联系人信息 → 看到"需要跟进 (confidence: 70%)
- [architect-3ad16b/architect] # PromiseLink 架构重新设计(客户视角驱动)

## 第一步:用户页面与操作流程定义

### 1. 页面架构(用户视角)

#### 1.1 首页/仪表盘
**用户第一眼看到:**
- 今日待办(Today's Todos):信息 (confidence: 70%)
- [architect-e3622a/architect] # PromiseLink PRD v1.6 客户视角评审 - 系统架构师视角

## 一、客户视角发现的问题

### P0 级问题（阻塞用户核心体验）

**P0-1: 缺少前端架构定义，用户界面结构完全未定义**
- **用户痛点**：用 (confidence: 70%)
- [ui-designer-70f63b/ui-designer] # UI/UX设计师评审报告
## PromiseLink PRD v1.6 客户视角分析

---

## 一、客户视角发现的问题

### P0 级问题(阻断发布)

**P0-1: 缺失完整的信息架构和页面结构定义**
- **用户痛点* (confidence: 70%)
- [tester-64a379/tester] # 测试专家评审报告 - PromiseLink PRD v1.6

## 一、客户视角问题分析

### P0 级问题(阻断发布)

**P0-1: 缺少端到端用户旅程的验收标准**
- **问题**: PRD定义了20个功能点,但没有定义完 (confidence: 70%)
- [solo-coder-e31fe7/solo-coder] # PromiseLink PRD v1.6 客户视角评审 - 全栈开发者视角

## 一、客户视角问题分析

### P0 级问题(阻塞发布)

**P0-1: 前端页面结构完全缺失**
- **问题**: PRD定义了20个功能,但没有定义 (confidence: 70%)
- [devops-0d7475/devops] # DevOps工程师 - PromiseLink PRD v1.6 客户视角评审

## 1. 客户视角发现的问题

### P0 - 阻断性问题(用户无法正常使用)

**P0-1: 缺少服务可用性保障定义**
- **用户痛点**: 用户 (confidence: 70%)
- [product-manager-d806ae/product-manager] # 产品经理视角评审报告

## 一、客户视角核心问题分析

### P0级问题(阻塞性,必须解决)

**P0-1: 缺失首页/主界面定义**
- **问题**: PRD未定义用户打开App第一眼看到什么
- **用户影响**: 用户不知 (confidence: 70%)
- [security-afe1a3/security] # 安全专家评审报告 - PromiseLink PRD v1.6

## 一、客户视角安全问题分析

### 核心问题:用户最担心什么?

作为商务BD/创业者/投资人,我上传的是:
- **高价值商业信息**:客户名片、会议纪要、商机线索
 (confidence: 70%)

## 📦 上下文压缩
- 耗时: N/A
- 0 tokens → 0 tokens (0%)

## 🧠 记忆系统
- Total: 1
- Knowledge: 0
- Episodic: 0

## 🔒 权限检查
- [🚫] file_create:/tmp/test_output.md: prompt