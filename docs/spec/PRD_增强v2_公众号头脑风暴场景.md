# PromiseLink 基础版增强规格 v2（公众号+头脑风暴场景补充）

> **状态**：草稿，待用户审批
> **日期**：2026-06-12
> **来源**：公众号文章草稿 + AI用例头脑风暴报告
> **前置依赖**：PRD_P0P1增强规格_v1.md (F-E1~F-E6 全部完成)

---

## 变更概述

基于公众号文章草稿和头脑风暴报告中的场景描述，补充实现3个新功能：

| ID | 功能名称 | 来源 | 价值 | 成本 |
|----|---------|------|------|------|
| **F-G1** | 关系健康度诊断 | 头脑风暴#6 (Quick Win 3.50/2.25) | 高 | 低 |
| **F-G2** | 关系阶段展示与流转建议 | 头脑风暴#10 (3.50/2.75) + 公众号模块5核心差异化 | 高 | 中 |
| **F-G3** | 个人关怀点提醒 | 公众号模块3（孩子高考例） | 高 | 中 |

### 设计原则

1. **后端优先复用**：关系阶段机(`RelationshipStageMachine`)、concern字段、relationship_brief等已有数据结构直接利用
2. **前端增量增强**：在现有页面（Dashboard/Entities/实体详情）上增加区块，不新建页面
3. **基础版约束**：纯文本交互，不含语音推送；数据本地存储
4. **文档先行**：本文档审批后方可编码

---

## F-G1: 关系健康度诊断

### 用户故事

> As a 商务人士, I want 一键看到所有人脉关系的健康状态概览, So that 我知道哪些关系需要重点经营、哪些可以维持现状。

### 来源依据

头脑风暴#6：*"一键评估所有关系的健康状态"* — Quick Win象限，价值3.50/成本2.25。7阶段模型已就绪，只需聚合展示。

公众号模块5：*"我们有七种关系阶段，从'刚认识'到'长期伙伴'再到'休眠期'。每个阶段对应的经营动作不一样。"*

### 数据来源（已存在）

| 数据项 | 来源 | 说明 |
|--------|------|------|
| `relationship_stage` | `RelationshipBrief.relationship_stage` | 7阶段枚举值 |
| `total_interactions` | Entity events count | 互动次数 |
| `todo_count` | Entity todos count | 待办数量 |
| `last_interaction_date` | 最新event时间戳 | 最后互动时间 |
| `care_todo_count` | care类型todo数 | 关注对方程度 |
| `promise_todo_count` | promise类型todo数 | 承诺追踪情况 |
| `credit_score` | F-E5已实现的信用分 | 信誉评估 |

### API 设计

**端点**: `GET /dashboard/relationship-health`

**响应模型**:

```python
class HealthItem(BaseModel):
    entity_id: str
    name: str
    company: str | None = None
    stage: str                    # current relationship_stage value
    stage_label: str              # e.g. "初次连接", "了解需求"
    stage_color: str              # e.g. "#A0C4A8"
    health_score: float           # 0-100 综合健康分
    health_level: str             # "healthy" / "attention" / "at_risk"
    interaction_count: int        # 总互动次数
    last_interaction: str | None  # ISO date
    days_since_last: int | None   # 距上次互动天数
    pending_todos: int            # 未完成待办数
    pending_promises: int         # 未兑现承诺数
    suggestion: str               # 经营建议文本

class RelationshipHealthResponse(BaseModel):
    total_entities: int
    healthy_count: int            # health_score >= 70
    attention_count: int          # 40 <= health_score < 70
    at_risk_count: int            # health_score < 40
    items: list[HealthItem]
    summary_text: str             # NLG生成的自然语言摘要
```

### 健康评分算法

```
HealthScore =
  阶段权重(30%)  : stage_order / 7 * 100   (越高级段分数越高)
  互动频率(25%)  : min(100, interactions * 8)
  活跃度(20%)    : days_since_last < 7 → 100, < 30 → 60, < 90 → 30, >= 90 → 0
  承诺健康(15%)  : 有未逾期承诺 → 100, 有逾期 → 40, 无承诺 → 70
  待办密度(10%)  : max(0, 100 - pending_todos * 10)
```

### 健康等级

| 等级 | 分数范围 | 颜色 | 含义 |
|------|---------|------|------|
| healthy | >= 70 | #52c41a 绿 | 关系健康，维持即可 |
| attention | 40-69 | #faad14 黄 | 需要关注，建议主动互动 |
| at_risk | < 40 | #ff4d4f 红 | 关系风险，急需活化 |

### 经营建议模板（非LLM，PoC用规则生成）

```
stage=new_interaction + interactions=1:
  "刚认识不久，建议安排一次深入交流，了解对方业务痛点"

stage=understanding_needs + days_since_last > 14:
  "已了解需求但超过2周未联系，建议跟进近况或分享有价值信息"

stage=value_response + no recent events:
  "有过价值交换，可考虑深化合作或请求引荐"

stage=dormant:
  "关系已沉寂，建议参考沉睡联系人活化建议"

default:
  "保持当前节奏，关注待办事项的按时完成"
```

### 前端设计

**位置**: Dashboard首页 (`pages/index/index.tsx`) 新增"关系健康度"区块

**布局**:
```
┌─────────────────────────────────────┐
│  📊 关系健康度          健康 3 关注 2 风险 1 │
├─────────────────────────────────────┤
│  ┌──────┐ ┌──────┐ ┌──────┐         │
│  │ 张伟  │ │ 王芳  │ │ 刘阳  │  ...   │
│  │ ●了解需│ │ ●初次连│ │ ⚠沉寂  │         │
│  │ 78分  │ │ 45分  │ │ 25分  │         │
│  │ 建议..│ │ 建议..│ │ 活化..│         │
│  └──────┘ └──────┘ └──────┘         │
└─────────────────────────────────────┘
```

**交互**:
- 点击健康卡片 → 跳转到对应实体详情
- 顶部显示三级统计徽章（健康/关注/风险数量）
- 支持按健康等级筛选

### 验收标准

- [ ] API返回所有实体的健康分，按health_score降序排列
- [ ] 健康等级分布与实际数据一致
- [ ] Dashboard正确渲染健康度区块（含统计+卡片列表）
- [ ] 点击卡片跳转实体详情
- [ ] 空状态（无实体时）友好提示
- [ ] `npm run build:h5` 编译通过

---

## F-G2: 关系阶段展示与流转建议

### 用户故事

> As a 商务人士, I want 看到每个联系人的关系处于什么阶段以及如何推进到下一阶段, So that 我有策略地经营每一段关系。

### 来源依据

头脑风暴#10：*"AI建议如何将关系推进到下一阶段"* — 差异化明显，模型已就绪。

公众号模块5核心差异化论点：*"我们有七种关系阶段...每个阶段对应的经营动作不一样。刚认识的人应该保持低频率但定期的互动。深度合作的人应该对承诺兑现度极度敏感。不同阶段，不同策略。这件事目前没有任何竞品在做。"*

### 数据来源（已存在）

| 数据项 | 来源 | 说明 |
|--------|------|------|
| `RelationshipStage` 枚举 | `relationship_stage.py` | 7阶段完整定义 |
| `STAGE_METADATA` | `relationship_stage.py` | label/color/icon/description/order |
| `suggest_transition()` | `RelationshipStageMachine` | 启发式流转建议方法 |
| `STAGE_TRANSITIONS` | `relationship_stage.py` | 合法转换表 |
| 当前实体的stage | `Entity.properties` 或 `RelationshipBrief` | 需要确认取值来源 |

### API 设计

#### 端点1: 获取实体当前阶段和建议

**`GET /entities/{entity_id}/stage-info`**

```python
class StageInfoResponse(BaseModel):
    entity_id: str
    name: str
    current_stage: str              # e.g. "new_connection"
    current_stage_label: str        # e.g. "初次连接"
    current_stage_color: str        # e.g. "#A0C4A8"
    current_stage_desc: str         # 阶段描述
    stage_order: int                # 1-7
    suggestion: StageSuggestion | None  # 流转建议，无建议时为null

class StageSuggestion(BaseModel):
    target_stage: str               # 建议目标阶段
    target_stage_label: str         # e.g. "了解需求"
    target_stage_color: str
    reason: str                     # 建议原因
    action_hint: string             # 用户可执行的动作提示
    requires_confirmation: bool     # 是否需要用户确认
```

#### 端点2: 获取全部阶段路线图（静态数据）

**`GET /entities/stage-map`**

```python
class StageMapItem(BaseModel):
    value: str                     # enum value
    label: str                     # 中文标签
    color: str                     # 显示颜色
    icon: str                      # emoji图标
    description: str               # 阶段描述
    order: int                     # 排序

class StageMapResponse(BaseModel):
    stages: list[StageMapItem]
```

### 流转建议逻辑（已有`suggest_transition()`）

| 当前阶段 | 条件 | 建议目标 | 原因 |
|----------|------|---------|------|
| 任意 | >90天未互动 | dormant | 长期未联系 |
| new_connection | 存在care类todo | understanding_needs | 已关注对方需求 |
| understanding_needs | >=2次价值互动事件 | value_response | 多次价值交换 |
| 其他 | 无触发条件 | null | 维持当前阶段 |

### 前端设计

**位置**: 实体详情弹窗 (`pages/entities/index.tsx` 的 detail modal) 内新增"关系阶段"区块

**布局**:
```
┌──────────────────────────────────────┐
│  🔄 关系阶段                          │
│                                      │
│  👋初次连接 → 🔍了解需求 → 🤝价值回应  │
│       [●当前位置]                     │
│                                      │
│  "已了解需求但超过2周未联系，           │
│   建议跟进近况或分享有价值信息"        │
│                                      │
│  [推进到下一阶段]  [维持当前阶段]      │
└──────────────────────────────────────┘
```

**交互细节**:
- 阶段进度条：横向展示7个阶段，当前阶段高亮
- 建议卡片：黄色背景，显示建议原因和动作提示
- "推进到下一阶段"按钮：调用PATCH接口确认流转
- "维持当前阶段"：关闭建议，不执行操作

### 阶段进度条视觉

使用雾色系颜色（与Todo类型色系一致）：
- 初次连接: #A0C4A8 (雾绿)
- 了解需求: #A0B0C4 (雾蓝)
- 价值回应: #C4C0A0 (雾金)
- 深度信任: #B0A0C4 (雾紫)
- 积极合作: #B8C4C0 (雾白)
- 长期伙伴: #C4A0A0 (烟粉)
- 沉寂: #C4C4C4 (灰)

### 验收标准

- [ ] `/entities/{id}/stage-info` 返回正确的当前阶段和流转建议
- [ ] `/entities/stage-map` 返回完整的7个阶段定义
- [ ] 实体详情弹窗内展示阶段进度条（当前阶段高亮）
- [ ] 存在流转建议时显示建议卡片和操作按钮
- [ ] 无建议时不显示建议区域（不占空间）
- [ ] `npm run build:h5` 编译通过

---

## F-G3: 个人关怀点提醒

### 用户故事

> As a 商务人士, I want 系统提醒我对方个人层面的重要节点（如家人考试、搬家、项目里程碑）, So that 我在合适的时机表达关怀，让关系更有温度。

### 来源依据

公众号模块3（核心差异化论点）：

> *"你三个月前见过一个创业者，他说孩子今年高考。这个信息跟商业毫无关系。传统的CRM绝对不会记这个。但PromiseLink会记住。不仅如此，它会在高考结束后提醒你：'李总的孩子上个月高考结束，可以问一句考得怎么样。'"*

> *"中国式人情世故的本质，不是复杂的规则，是大量的细节。谁能记住更多细节，谁就更得体。"*

这是PromiseLink vs CRM的**最核心差异化场景**——不是商业效率，而是人际温度。

### 数据来源（已存在）

| 数据项 | 来源 | 说明 |
|--------|------|------|
| `properties.concern` | Entity JSONB field | `[{"category": "...", "detail": "..."}]` |
| concern提取 | `entity_extractor.py` + LLM prompt | 从对话中提取关心的事 |
| care-type todos | TodoGenerator | 自动生成的关注类待办 |

### 关怀点分类

 concern字段的`category`已经使用了受控词表（融资、招聘、销售、技术选型、合规、市场拓展、成本控制、供应链、数字化转型、人才保留），但这些偏**商业关切**。

F-G3需要扩展识别**个人层面**的关怀点：

| 分类 | category值 | 示例 | 提醒时机 |
|------|-----------|------|---------|
| 家庭重要事件 | `family_milestone` | 孩子高考、配偶换工作、买房 | 事件发生后1-2周 |
| 个人健康 | `personal_health` | 手术恢复、体检异常 | 适中时机询问 |
| 兴趣爱好 | `hobby_interest` | 跑马拉松、学钢琴、喜欢喝茶 | 相关话题出现时 |
| 项目里程碑 | `project_milestone` | 产品上线、融资到位、搬办公室 | 里程碑前后 |
| 生活变动 | `life_change` | 搬家、换城市、回国 | 变动后1个月内 |

> **PoC策略**: 不修改LLM prompt的受控词表（改动大且不可控），而是在**前端展示层**对现有concern数据做智能筛选和高亮，将包含个人关键词的concern条目标记为"关怀点"。同时后端新增一个聚合API扫描所有实体的concern字段，提取可能的个人关怀条目。

### API 设计

**端点**: `GET /dashboard/care-reminders`

```python
class CareReminderItem(BaseModel):
    entity_id: str
    name: str
    company: str | None = None
    concern_category: str          # original category
    concern_detail: str            # original detail text
    care_type: str                 # "personal" / "business" / "mixed"
    relevance_score: float         # 0-1 关联度评分
    source_event_id: str | None    # 来源事件
    source_event_title: str | None # 来源事件标题
    days_since_mentioned: int      # 距提及天数
    suggested_action: str          # 建议动作文本

class CareRemindersResponse(BaseModel):
    total: int
    personal_items: list[CareReminderItem]   # 个人关怀类
    business_items: list[CareReminderItem]   # 商业关切类（top5）
    summary_text: str                         # NLG摘要
```

### 关怀点识别逻辑（关键词匹配 + LLM增强）

**步骤1: 关键词预筛选**（纯规则，无需LLM）

```python
PERSONAL_KEYWORDS = {
    "family_milestone": ["孩子", "子女", "儿子", "女儿", "高考", "中考", "留学",
                         "结婚", "生子", "宝宝", "夫人", "太太", "先生"],
    "personal_health": ["手术", "住院", "体检", "康复", "生病", "身体", "健康"],
    "hobby_interest": ["跑步", "马拉松", "健身", "高尔夫", "网球", "摄影",
                       "茶", "咖啡", "酒", "旅行", "旅游", "书法", "画画"],
    "project_milestone": ["上线", "发布", "融资", "A轮", "B轮", "搬", "迁",
                          "扩张", "招人", "扩团队", "新产品"],
    "life_change": ["搬家", "换房", "换城市", "回国", "离职", "跳槽", "创业"],
}
```

**步骤2: 匹配评分**

对每个entity的每个concern条目：
1. 遍历PERSONAL_KEYWORDS的每个分类
2. 计算detail文本中关键词命中数
3. 命中>=1个 → 标记为对应care_type
4. `relevance_score = min(1.0, hit_count * 0.3)`

**步骤3: 去重排序**

- 同一entity保留relevance_score最高的1条
- 按 relevance_score × (1 / (days_since_mentioned + 1)) 排序
- 个人关怀类优先展示

### 前端设计

**位置1**: Dashboard首页 (`pages/index/index.tsx`) 新增"关怀提醒"区块

**位置2**: 实体详情弹窗 (`pages/entities/index.tsx`) 的properties区域高亮关怀点

**Dashboard关怀提醒区块布局**:
```
┌─────────────────────────────────────┐
│  💡 关怀提醒                    查看全部 │
├─────────────────────────────────────┤
│  ┌─────────────────────────────────┐ │
│  │ 🏠 李总的孩子今年高考            │ │
│  │    提及于14天前的交流            │ │
│  │    → 可以问一句考得怎么样       │ │
│  └─────────────────────────────────┘ │
│  ┌─────────────────────────────────┐ │
│  │ 🏃 王总最近在跑马拉松            │ │
│  │    提及于30天前的通话            │ │
│  │    → 可以问问最近训练怎么样     │ │
│  └─────────────────────────────────┘ │
└─────────────────────────────────────┘
```

**交互细节**:
- 关怀卡片使用暖黄色背景（#fffbe6），区别于普通待办
- 左侧显示关怀类型图标（🏠家庭/🏃爱好/🏥健康/🚩里程碑）
- 中间显示关怀内容 + 距提及天数
- 底部显示建议动作（斜体灰色）
- 点击卡片 → 跳转实体详情
- "查看全部" → 展开/收起完整列表

**实体详情关怀点高亮**:

在properties展示区域，如果某个concern条目被识别为个人关怀点：
- 条目背景变为浅黄色(#fffbe6)
- 左侧添加竖线标记(#faad14)
- 显示care_type标签（"个人关怀"/"商业关切"）

### 建议动作模板

```python
ACTION_TEMPLATES = {
    "family_milestone": "可以问一句{detail}怎么样了",
    "personal_health": "合适的时候问候一下{detail}的情况",
    "hobby_interest": "聊聊{detail}的近况，这是个很好的破冰话题",
    "project_milestone": "恭喜{detail}，可以问进展如何",
    "life_change": "{detail}后适应得怎么样",
    "default": "记得{detail}，可以在下次交流时提起",
}
```

### 验收标准

- [ ] API正确扫描所有实体的concern字段，识别出个人关怀条目
- [ ] 关键词匹配覆盖上述5大类
- [ ] Dashboard展示关怀提醒区块（个人关怀优先）
- [ ] 关怀卡片显示关怀内容、时间、建议动作
- [ ] 实体详情中关怀点有视觉高亮
- [ ] 无关怀数据时区块隐藏或显示空状态
- [ ] `npm run build:h5` 编译通过

---

## 实现计划

### 依赖顺序

```
F-G1 (关系健康度诊断) ← 无前置依赖，可先开始
     ↓
F-G2 (关系阶段展示) ← 复用G1的部分数据查询逻辑
     ↓
F-G3 (关怀点提醒) ← 独立功能，可与G1并行
```

### 文件变更清单

| 文件 | 变更类型 | 涉及功能 |
|------|---------|---------|
| `src/promiselink/api/v1/dashboard.py` | 新增端点 | G1: `/dashboard/relationship-health`, G3: `/dashboard/care-reminders` |
| `src/promiselink/api/v1/entities.py` | 新增端点 | G2: `/entities/{id}/stage-info`, `/entities/stage-map` |
| `src/promiselink/services/health_diagnostic.py` | **新文件** | G1: 健康评分算法 |
| `frontend/src/services/api.ts` | 新增接口/函数 | G1+G2+G3 所有新API的类型定义 |
| `frontend/src/pages/index/index.tsx` | 新增区块 | G1: 健康度区块, G3: 关怀提醒区块 |
| `frontend/src/pages/index/index.scss` | 新增样式 | G1+G3 样式 |
| `frontend/src/pages/entities/index.tsx` | 新增区块 | G2: 阶段进度条+建议, G3: 关怀点高亮 |
| `frontend/src/pages/entities/index.scss` | 新增样式 | G2+G3 样式 |

### 风险与缓解

| 风险 | 影响 | 缓解措施 |
|------|------|---------|
| concern字段数据稀少（用户还没输入多少数据） | 关怀提醒可能为空 | 展示引导文案："多记录互动，AI会发现更多关怀点" |
| 关系阶段数据缺失（旧实体没有stage） | 健康度/阶段展示可能显示unknown | 默认值为`new_connection`，鼓励用户通过互动自然推进 |
| 关键词匹配误判（商业词被标为个人关怀） | 准确率 | 使用较严格的关键词列表，宁可漏判不误判 |
