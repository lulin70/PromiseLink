# EventLink 产品定位升级v2评审 - PM+架构师讨论报告

> 日期: 2026-06-02
> 反馈来源: 外部创业者李总 + 3份新资料（合作人员关键信息表/16种角色人物/会议标准）

---

## 产品经理(PM)

# EventLink产品定位升级评审意见

## 1. 定位升级评审

**同意升级，但需要分阶段实现。**

**理由：**
- 从"记录工具"到"经营助手"是正确的价值跃迁，解决的是"how to act"而非"what happened"
- 7个核心问题直击商务关系的本质痛点，符合高价值用户（企业主、BD、合伙人）的真实决策场景
- 但需警惕：这7个问题需要大量上下文积累才能给出可信答案，冷启动时AI能力会严重受限

**建议：**
- Phase 1（MVP）：保留"记录+提取"基础能力，在UI层埋入7个问题的交互入口，但初期只能基于有限数据给出"浅层建议"
- Phase 2：当单个联系人交互记录≥5条时，开始输出"关系阶段判断""维护频率建议"等中等难度答案
- Phase 3：当关系网数据丰富后，才能回答"真正能调动什么资源""共同关系网"等高阶问题

---

## 2. 7板块30字段对Entity模型的影响

### 当前Entity模型回顾
现有8个实体：Person/Organization/Event/Topic/Action/Opportunity/Project/Relationship

### 分析
30字段本质是**Person实体的扩展属性集**，但部分字段需要关联到其他实体或新建结构。

### Phase 1应纳入字段（冷启动可用）

#### 直接扩展Person实体（14个字段）
```
板块1: 姓名/性别/年龄/城市/行业/单位/职业/职级 (8)
板块3: 沟通偏好/决策特点 (2)
板块4: 关键能力模型/个人特点标签 (2)
板块5: 个人背景/自有核心资源 (2)
```

#### 需要关联Event/Relationship（4个字段）
```
板块6: 已有关系强度 → Relationship.strength
板块6: 历史合作总结 → 从Event.type=meeting/deal聚合
板块7: 接触频率建议 → 从Event时间序列计算
板块7: 下一次互动抓手 → Action.suggested_next_step
```

### Phase 2及以后纳入（需数据积累）
```
板块2: 沟通场景/禁忌信息/敏感信息/注意事项 (4) → 需NLP从Event.transcript提取
板块3: 行事风格/决策权力 (2) → 需多次交互观察
板块4: 职业高峰时刻 (1) → 需用户主动录入或AI推断
板块5: 平台背书资源 (1) → 需关联Organization.resources
板块6: 共同关系网 (1) → 需图算法计算
板块7: 适配合作场景/合作禁忌 (2) → 需AI综合推理
```

### 数据模型调整建议
```typescript
// Person实体扩展
interface Person {
  // ... 现有字段
  
  // Phase 1新增
  profile: {
    gender?: string
    age?: number
    city: string
    industry: string
    organization: string
    role: string
    seniority: string // 职级
  }
  
  communication: {
    preferredChannel?: 'phone' | 'wechat' | 'email' | 'in-person'
    decisionStyle?: string // 决策特点
    // Phase 2
    prohibitedTopics?: string[]
    sensitiveInfo?: string[]
    notes?: string
  }
  
  capabilities: {
    keySkills: string[]
    personalTags: string[]
    // Phase 2
    careerPeak?: string
  }
  
  resources: {
    personal: string[] // 自有资源
    // Phase 2
    organizational?: string[] // 平台资源
  }
}
```

---

## 3. 16种角色分类与8种关联类型整合

### 当前8种关联类型（Relationship.type）
Colleague/Client/Partner/Mentor/Friend/Family/Acquaintance/Other

### 问题诊断
- 现有分类过于社交化（Friend/Family），不适配商务场景
- 16种角色分类更精准，但过细会增加用户标注负担

### 整合方案：**双层标签体系**

#### 一级分类（用户必选，4大类）
```
GOVERNANCE    // 治理与资本层
PROFESSIONAL  // 专业与执行层  
MARKET        // 市场与拓展层
SERVICE       // 服务与交易层
```

#### 二级分类（AI辅助推荐，16种角色）
```
Relationship {
  category: 'GOVERNANCE' | 'PROFESSIONAL' | 'MARKET' | 'SERVICE'
  role: '股东' | '投资人' | '合伙人(战略)' | ... // 16选1
  level: 1 | 2 | 3 // 角色等级
  
  // 保留原有type作为情感关系维度
  emotionalBond?: 'Mentor' | 'Friend' | 'Acquaintance'
}
```

#### 用户交互流程
1. 创建联系人时，系统根据职业/职级自动推荐category和role
2. 用户确认或修改
3. 随着交互记录增加，AI动态调整level（1→2→3）

---

## 4. 11种会议类型与A/B/C/D类型整合

### 当前4类Event分类
- A类（正式会议）
- B类（临时沟通）
- C类（社交活动）
- D类（关键节点）

### 问题诊断
A/B/C/D分类逻辑模糊，用户理解成本高。11种会议类型更具象，但仅覆盖会议场景。

### 整合方案：**场景化分类**

#### 重构Event.type
```typescript
type EventType = 
  // 结构化会议（对应原A类）
  | 'project_kickoff'        // 项目启动会
  | 'weekly_sync'            // 周例会
  | 'retrospective'          // 项目复盘会
  | 'decision_making'        // 决策会
  | 'brainstorming'          // 头脑风暴会
  | 'expert_review'          // 专家入库评审会
  | 'partner_recruitment'    // 事业合伙人招募说明会
  | 'product_demo'           // 产品介绍与推销会
  
  // 非正式沟通（对应原B类）
  | 'one_on_one'            // 一对一沟通
  | 'info_sync'             // 信息同步会
  | 'casual_chat'           // 临时闲聊
  
  // 社交活动（对应原C类）
  | 'meal'                  // 饭局
  | 'coffee'                // 咖啡会
  | 'activity'              // 团建/活动
  
  // 关键节点（对应原D类）
  | 'contract_signing'      // 合同签署
  | 'milestone_delivery'    // 里程碑交付
  | 'crisis_resolution'     // 危机处理
```

#### 属性增强
```typescript
interface Event {
  type: EventType
  formality: 'formal' | 'informal' | 'social' // 自动推断
  criticalLevel: 1 | 2 | 3 | 4 | 5 // D类=5, A类=3-4, B类=2, C类=1
}
```

---

## 5. MVP-Core功能调整

### 现有MVP范围问题
过于聚焦"记录+提取"，缺少"决策支持"的核心价值体现。

### 调整后的MVP-Core（保持3-4周开发周期）

#### 保留功能
- ✅ 微信聊天记录导入
- ✅ AI提取联系人/待办事项
- ✅ 关系图谱可视化（简化版）

#### 新增功能
- ✅ **关系仪表盘**：每个联系人卡片显示"关系阶段、上次接触时间、下次建议接触时间"
- ✅ **7问快捷入口**：联系人详情页增加"AI经营建议"按钮，点击后显示7个问题的初步答案（基于现有数据）
- ✅ **角色智能标注**：创建联系人时自动推荐category/role/level

#### 删减功能
- ❌ Opportunity推荐（数据不足时推荐质量差，延后到Phase 2）
- ❌ 复杂的图谱分析（改为简单的"共同联系人"列表）

---

## 6. 冷启动方案调整

### 现有问题
依赖大量历史数据才能体现AI价值，新用户空白期体验差。

### 调整后的3阶段冷启动

#### 第1天：引导式快速建档（15分钟完成核心价值体验）
```
1. 导入微信聊天记录（3-5个关键联系人）
2. AI自动生成Person基础档案（姓名/单位/职业）
3. 用户确认并补充角色分类（GOVERNANCE/PROFESSIONAL等）
4. 系统立即生成"关系仪表盘"，显示：
   - 已有关系强度：基于聊天频率计算
   - 沟通偏好：根据聊天时段/渠道推断
   - 维护建议：根据最后接触时间推荐下次联系时间
```

#### 第1周：半自动填充核心字段
```
- 每次查看联系人详情时，AI弹出1-2个补充问题：
  "张总在公司的决策权力是？ A.最终拍板 B.提供建议 C.信息传递"
  "您与李总的沟通更偏好？ A.电话 B.微信 C.线下饭局"
- 用户点击选择即完成标注（无需输入）
- 积累5-10个问答后，7个核心问题的答案质量显著提升
```

#### 第1个月：关系网效应激活
```
- 当录入≥10个联系人后，开始计算共同关系网
- 在Event详情页自动关联相关联系人，形成关系链
- 每周生成"关系健康度报告"：
  哪些重要联系人超过1个月未联系
  哪些合作机会因关系维护不足错失
```

---

## 7. PRD产品概述重写文案

```markdown
# EventLink 产品概述

## 一句话定位
EventLink是为商务人士打造的AI合作关系经营助手，帮你记住认识了谁、聊了什么，更帮你想清楚下一步怎么经营每一段关系。

## 核心价值主张
在商务世界，维护好关系比拥有好资源更重要。但多数人面临三大困境：
- **记不住**：见过的人太多,重要细节遗忘
- **想不清**：不知道对方能调动什么资源、该用什么方式维护
- **顾不上**：日常事务繁忙，错过最佳维护时机

EventLink通过AI技术,帮你回答商务关系经营中的7个核心问题：
1. 这个人现在和我是什么关系阶段？
2. 他真正能调动什么资源？
3. 他是最终拍板的人还是信息传递人？
4. 与他沟通时应该电话、微信、饭局还是正式邮件？
5. 哪些话题不能碰？
6. 下一次见面最适合用什么理由切入？
7. 应该每周维护、每月维护还是有项目再联系？

## 目标用户
- **主要用户**：企业创始人、高管、BD负责人、合伙人
- **典型场景**：需要维护50-200个商务关系，每段关系的经营质量直接影响业务成果
- **痛点强度**：因关系维护不当导致的机会成本每年达数十万至数百万

## 产品定位
不是简单的CRM或通讯录，而是：
- **关系档案管家**：自动记录每次互动、提取关键信息、建立完整的关系画像
- **经营策略顾问**：基于关系阶段、历史互动、资源匹配给出下一步行动建议
- **维护提醒助手**：根据关系重要度和互动频率，智能提醒最佳联系时机

## 核心能力
1. **智能建档**：从微信聊天、会议记录、邮件中自动提取联系人信息，建立30字段的完整档案
2. **关系分析**：识别16种商务角色，判断关系强度、决策权力、资源能力
3. **策略建议**：针对每个联系人给出沟通偏好、维护频率、切入话题建议
4. **关系网图谱**：可视化展示你与关键人物的连接路径，发现潜在合作机会

## 与传统CRM的区别
| 维度 | 传统CRM | EventLink |
|------|---------|-----------|
| 数据来源 | 手动录入 | AI自动提取 |
| 数据颗粒度 | 公司/交易维度 | 人/关系维度 |
| 核心价值 | 管理销售流程 | 经营关系资产 |
| 使用场景 | 团队协作工具 | 个人决策助手 |
| 决策支持 | 销售漏斗分析 | 关系健康度诊断 |

## 成功标准
- **冷启动**：新用户15分钟内完成10个核心联系人建档，获得首次经营建议
- **活跃度**：用户每周主动查看≥3次关系仪表盘
- **粘性**：单个联系人档案积累≥5条互动记录后，用户持续补充信息的比例>60%
- **价值认知**：用户因EventLink建议而采取行动(联系某人/调整沟通方式)的比例>40%

## 商业化路径
- **免费版**：支持管理30个联系人，基础AI分析
- **专业版**：无限联系人、高级AI策略建议、关系网图谱 (¥99/月)
- **企业版**：团队协作、权限管理、API集成 (¥999/月起)
```

---

## 总结建议

**优先级排序：**
1. **立即执行**：重写产品概述、调整MVP功能范围（本周完成）
2. **Phase 1**：扩展Person模型14个字段、实现角色分类、优化冷启动流程（3-4周）
3. **Phase 2**：补充剩余16个字段、引入NLP提取敏感信息、开发关系网图谱（2-3个月）

**风险提示：**
- 7个核心问题的答案质量高度依赖数据积累，需在UI层做好预期管理（如："基于现有3条互动记录，AI给出以下初步建议..."）
- 30字段过多会导致用户疲劳，建议采用"渐进式填充"而非一次性表单
- 16种角色分类需要配套的用户教育内容（如角色说明、典型案例）

---

## 架构师(Architect)

# EventLink技术评审意见

## 1. 定位升级评估

**同意升级，技术可行。**

原因：
- 从"事件关联"到"关系经营"是自然演进，现有L2/L3架构已具备扩展基础
- 7个核心问题本质是**关系状态推理+行动建议生成**，符合当前"关联发现→Todo生成"链路
- 技术风险可控：主要是enrichment pipeline扩展，不涉及架构重构

## 2. 数据结构映射方案

### Entity.properties扩展（向下兼容）
```json
{
  // 原有字段保留
  "company": "string",
  "title": "string", 
  "skills": "array",
  
  // 新增relationship_profile子对象
  "relationship_profile": {
    // 板块1：基础信息（复用现有字段）
    "basic": {
      "company": "ref:company",
      "title": "ref:title",
      "department": "string",
      "location": "string"
    },
    
    // 板块2：关系阶段
    "stage": {
      "current_stage": "enum[initial|developing|stable|strategic]",
      "stage_duration_days": "int",
      "last_stage_change": "timestamp",
      "confidence_score": "float"
    },
    
    // 板块3：资源能力
    "resources": {
      "budget_authority": "enum[none|limited|full]",
      "team_size": "int",
      "key_resources": "array<string>",
      "resource_access_level": "int[1-5]"
    },
    
    // 板块4：决策画像
    "decision": {
      "decision_power": "enum[influencer|decision_maker|gatekeeper|champion]",
      "decision_style": "enum[analytical|intuitive|collaborative|directive]",
      "approval_chain": "array<string>"
    },
    
    // 板块5：沟通偏好
    "communication": {
      "preferred_channels": "array<enum>",
      "response_time_avg_hours": "float",
      "meeting_preference": "enum[formal|casual|structured|freeform]",
      "timezone": "string"
    },
    
    // 板块6：禁忌话题
    "boundaries": {
      "sensitive_topics": "array<string>",
      "competitor_mentions": "array<string>",
      "past_conflicts": "array<{topic,date,severity}>",
      "privacy_level": "enum[open|guarded|private]"
    },
    
    // 板块7：互动策略
    "engagement": {
      "interaction_hooks": "array<{type,description,success_rate}>",
      "maintenance_frequency_days": "int",
      "last_touchpoint": "timestamp",
      "next_suggested_action": "string"
    }
  }
}
```

### 新增数据表
```sql
-- 关系阶段历史
CREATE TABLE relationship_stage_history (
  entity_id UUID,
  stage VARCHAR(20),
  changed_at TIMESTAMP,
  trigger_event_id UUID,
  confidence FLOAT
);

-- 互动效果追踪
CREATE TABLE interaction_effectiveness (
  entity_id UUID,
  hook_type VARCHAR(50),
  attempted_at TIMESTAMP,
  outcome ENUM('success','neutral','negative'),
  context JSONB
);
```

## 3. 角色分类与关联类型整合

### 现有8种关联类型
```
colleague, client, partner, mentor, 
investor, competitor, vendor, contact
```

### 整合方案：**分层映射而非替换**

```typescript
// 新增relation_metadata字段
interface RelationMetadata {
  // L1：现有类型（保留）
  legacy_type: RelationType; 
  
  // L2：16种角色映射
  role_classification: {
    layer: 'strategic' | 'business' | 'operational' | 'support',
    category: 'decision_maker' | 'technical_expert' | ..., // 16类
    level: 1 | 2 | 3,  // 每类3级
    confidence: number
  };
  
  // L3：动态权重
  influence_score: number;  // 基于role算出的综合影响力
  interaction_priority: number;  // 基于stage+role的维护优先级
}
```

**不需要新增relation_type**，用metadata扩展现有类型。

**映射规则示例**：
```
client + decision_maker(L3) → 战略级客户 → influence_score=0.95
colleague + technical_expert(L2) → 业务级协同 → influence_score=0.65
```

## 4. 会议类型与管线整合

### 当前管线4类输出
```
A内部协同 / B对外商务 / C项目复盘 / D知识沉淀
```

### 整合方案：**11种类型→4类输出的路由矩阵**

```typescript
const MEETING_ROUTING_MATRIX = {
  // 外部类(6种) → B对外商务
  'sales': { primary: 'B', secondary: ['D'] },
  'partnership': { primary: 'B', secondary: ['D'] },
  'negotiation': { primary: 'B', secondary: ['C'] },
  'client_support': { primary: 'B', secondary: ['A'] },
  'vendor': { primary: 'B', secondary: ['A'] },
  'industry_event': { primary: 'B', secondary: ['D'] },
  
  // 内部类(5种) → A内部协同/C复盘
  'team_sync': { primary: 'A', secondary: [] },
  'project_review': { primary: 'C', secondary: ['A'] },
  'strategy': { primary: 'A', secondary: ['D'] },
  'training': { primary: 'D', secondary: ['A'] },
  'one_on_one': { primary: 'A', secondary: ['C'] }
};
```

**扩展meeting管线**：
```
L2语义路由 → 识别11种类型 → 
查询路由矩阵 → 生成多输出(primary+secondary) →
L3关联发现增强(根据会议类型调用不同关联算法)
```

## 5. 7个核心问题需要的新引擎

### 新增引擎矩阵

| 核心问题 | 需要的引擎/算法 | 实现复杂度 |
|---------|----------------|-----------|
| 关系阶段 | **Stage Inference Engine**<br>基于交互频率+时长+sentiment变化的FSM | 中 |
| 资源调动 | **Resource Mapping Engine**<br>从title+company+past_events提取能力 | 低 |
| 决策权力 | **Decision Power Analyzer**<br>基于组织图谱+批准链推理 | 高 |
| 沟通偏好 | **Communication Pattern Miner**<br>统计历史channel/time/response数据 | 低 |
| 禁忌话题 | **Sentiment Boundary Detector**<br>NLP识别负面反应+主题聚类 | 中 |
| 互动抓手 | **Engagement Hook Recommender**<br>协同过滤推荐+A/B测试 | 中 |
| 维护频率 | **Touchpoint Scheduler**<br>基于stage+priority的动态调度 | 低 |

### 技术栈建议
```python
# 新增L3子引擎
class RelationshipIntelligenceEngine:
    def __init__(self):
        self.stage_fsm = StageInferenceFSM()  # 状态机
        self.decision_analyzer = DecisionPowerGraph()  # 图算法
        self.sentiment_detector = SentimentBoundaryNLP()  # Transformer模型
        self.hook_recommender = CollaborativeFilter()  # 推荐算法
        self.scheduler = DynamicScheduler()  # 规则引擎
```

## 6. 影响评估

### 性能影响
- **计算增量**：每个entity增加7个子引擎推理 → 预估+200ms/entity
- **优化方案**：lazy evaluation，仅在需要时才计算7问答案并缓存
- **建议**：使用Redis缓存relationship_profile，TTL=24h

### 存储影响
```
原Entity: ~2KB/条
新增数据: relationship_profile(~1.5KB) + history表(~500B/条/天)
预估: 10K entities × 1.5KB = 15MB + 5MB/月增长
```
影响可忽略，JSONB压缩后更小。

### 隐私影响 ⚠️
**高风险区域**：
1. `boundaries.sensitive_topics` - 可能包含个人隐私
2. `decision.approval_chain` - 组织结构敏感
3. `interaction_effectiveness` - 行为追踪数据

**必须措施**：
```sql
-- 字段级加密
ALTER TABLE entities ADD COLUMN 
  encrypted_boundaries BYTEA;  -- AES-256加密

-- 访问控制
CREATE POLICY relationship_profile_policy ON entities
  FOR SELECT USING (owner_id = current_user_id());
  
-- 审计日志
CREATE TABLE profile_access_log (
  accessed_at TIMESTAMP,
  accessor_id UUID,
  entity_id UUID,
  fields_accessed TEXT[]
);
```

## 7. Phase 1 最小可行方案（MVP）

### 目标：3个月内验证核心价值

#### 实现范围（3/7问题）
```
✅ 关系阶段推理（Stage Inference）
✅ 沟通偏好挖掘（Communication Pattern）
✅ 维护频率建议（Touchpoint Scheduler）

🔄 后续迭代
- 资源调动（需组织图谱集成）
- 决策权力（需外部数据源）
- 禁忌话题（需大量训练数据）
- 互动抓手（需A/B测试基建）
```

#### 技术实现
```typescript
// Phase 1 简化架构
class RelationshipEngineV1 {
  // 复用现有L3引擎，新增3个轻量级分析器
  async analyzeRelationship(entity: Entity): Promise<CoreInsights> {
    return {
      stage: this.inferStage(entity.events),  // 基于规则
      communication: this.minePatterns(entity.events),  // 统计分析
      nextAction: this.scheduleTouchpoint(stage, communication)  // 查表
    };
  }
}
```

#### 数据结构（最小集）
```json
{
  "relationship_profile": {
    "stage": {
      "current_stage": "developing",
      "confidence_score": 0.82
    },
    "communication": {
      "preferred_channels": ["email", "meeting"],
      "response_time_avg_hours": 4.2
    },
    "engagement": {
      "maintenance_frequency_days": 14,
      "next_suggested_action": "Follow up on Q1 roadmap discussion"
    }
  }
}
```

#### 集成点
```
修改现有管线：
L2 meeting管线 → 提取沟通metadata →
L3 新增RelationshipEngineV1 → 
输出扩展：原Todo + 新增relationship_insights
```

#### 成功指标
- 关系阶段推理准确率 > 75%（人工标注验证）
- 沟通偏好预测与实际匹配度 > 80%
- 维护提醒转化率 > 30%（用户采纳建议的比例）

---

## 总结建议

**立即执行**：
1. 扩展Entity.properties schema（向下兼容）
2. 实现Phase 1的3个核心引擎
3. 部署隐私保护措施

**3个月内**：
4. 收集用户反馈验证7问优先级
5. 基于真实数据训练stage inference模型

**6个月后**：
6. 根据验证结果决定是否全量实现7问引擎
7. 考虑引入外部数据源（LinkedIn/企查查）增强决策分析

技术债务可控，建议分阶段推进。MVP可在现有架构上快速实现，风险低。
