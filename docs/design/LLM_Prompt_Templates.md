# EventLink LLM Prompt模板库

> **版本**: 0.3.1 (POC阶段, F-55/F-56纯算法实现，无新增LLM模板)
> **最后更新**: 2026-06-06
> **模板总数**: 23个 (模板0-14 + 模板15-21 + [0.3.0新增]模板22-23共2个)
> **阶段**: POC (0.3.x series)
> **来源**: Integration_Design_v2.5 §3.2-3.6 + PRD_v4.3 prompts/ 目录提取
> **用途**: P8实现LLM集成时的直接参考文档，开发者无需翻阅2564行集成设计文档

---

## 0. 使用说明

### 模板调用方式

所有模板通过 `LLMClient.call()` 调用，使用Python `str.format()` 填充变量：

```python
from eventlink.services.llm_client import LLMClient

llm = LLMClient(config)

# 调用模板1：名片信息提取
result = await llm.call(
    prompt=TEMPLATE_1_CARD_EXTRACTION.format(ocr_text=raw_ocr_text),
    model="moka/claude-sonnet-4-6",
    temperature=0.3,
)
```

### 模型选择策略

| 模板 | 推荐模型 | 原因 |
|------|---------|------|
| 模板1 名片提取 | moka/claude-sonnet-4-6 | 结构化提取，简单任务 |
| 模板0 input_scope分类 | moka/claude-sonnet-4-6 | 分类任务，需要理解scope语义 |
| 模板2 语音实体抽取 | moka/claude-sonnet-4-6 | 需要理解上下文 |
| 模板3 Todo生成 | moka/claude-sonnet-4-6 | 需要理解6种action_type策略+降噪规则 |
| 模板4 商机优化 | moka/claude-sonnet-4-6 | 文本优化，中等任务 |
| 模板5 实体归一 | moka/claude-sonnet-4-6 | 需要推理判断 |
| 模板6 关系发现 | moka/claude-sonnet-4-6 | 需要综合分析 |
| 模板7 资源识别 | moka/claude-sonnet-4-6 | 需要深度理解 |
| 模板8 需求提取 | moka/claude-sonnet-4-6 | 需要深度理解 |
| 模板9 敏感度判断 | moka/claude-sonnet-4-6 | 需要安全判断 |
| 模板10 关系维护 | moka/claude-sonnet-4-6 | 基于规则+模板生成 |
| 模板11 承诺提取 | moka/claude-sonnet-4-6 | 需要理解承诺语义 |
| 模板12 关注点提取 | moka/claude-sonnet-4-6 | 需要理解关注意图 |
| 模板13 RelationshipBrief生成 | moka/claude-sonnet-4-6 | 12模块结构化填充 |
| 模板14 RelationshipStage推进建议 | moka/claude-sonnet-4-6 | 关系阶段分析推理 |
| 模板16 NLU意图识别(Stage 2) | moka/claude-sonnet-4-6 | [F-50新增]语音意图精确分类,需低temperature+JSON-only |
| 模板17 NLG-日程查询回答 | moka/claude-sonnet-4-6 | [F-50新增]车载场景口语化短文本生成 |
| 模板18 NLG-承诺追踪回答 | moka/claude-sonnet-4-6 | [F-50新增]待办数据→口语化回答 |
| 模板19 NLG-关系状态回答 | moka/claude-sonnet-4-6 | [F-50新增]关系进展→口语化回答 |
| 模板20 NLG-范围日程回答 | moka/claude-sonnet-4-6 | [F-50 1.2新增]多日日程概览生成 |
| 模板21 NLG-行动建议回答 | moka/claude-sonnet-4-6 | [F-50 1.2新增]关系优先级→行动建议生成 |
| 模板22 Concern/Capability提取 | moka/claude-sonnet-4-6 | [0.3.0新增]Person实体关注点+能力提取,受控词表+自由文本 |
| 模板23 Event标题生成 | moka/claude-sonnet-4-6 | [0.3.0新增]raw_text→简洁事件标题,≤20字 |

### AI输出语言规则（所有模板必须遵守）

#### 禁止行为

| # | 禁止行为 | 说明 |
|---|---------|------|
| 1 | 禁止AI自动判定对方资源 | AI不得对他人拥有的资源做出确定性判断 |
| 2 | 禁止AI建议索取资源 | AI不得建议用户向他人索取资源 |
| 3 | 推测必须标记为推测 | 任何非直接引用的推断必须标注 |
| 4 | 禁止自动撮合 | AI不得自动将A的需求匹配B的资源 |
| 5 | 禁止自动发送 | AI不得自动发送消息或通知 |
| 6 | 禁止推断人格 | AI不得对他人性格/人格做出判断 |

#### 输出标记规范

所有模板输出必须包含：
- `is_ai_inference: true/false` — 是否包含AI推测
- `confidence_level: "confirmed|inferred|speculated"` — 置信度级别
- `requires_confirmation: true/false` — 是否需要用户确认

#### 输出语言约束

所有Prompt模板必须包含以下输出语言约束指令：

```
输出语言规则：
1. 输出语言必须与输入语言一致（中文输入→中文输出，英文输入→英文输出）
2. 专业术语可保留原文，但必须附带中文解释
3. 日期格式统一使用ISO 8601
4. 数值不带单位时使用国际单位制
```

---

## 0. 模板0：Input Scope 分类

**用途**: 对用户输入进行语义分类，确定输入属于哪种scope，以便路由到正确的处理管线

**输入变量**:

| 变量 | 类型 | 说明 |
|------|------|------|
| user_input | string | 用户原始输入文本 |
| context_hint | string | 上下文提示（可选，如来源渠道） |

**8种Scope定义**:

| Scope | 说明 | 关键词特征 | 示例 |
|-------|------|-----------|------|
| `card` | 名片信息 | 名片、OCR、姓名+公司+职位、电话、邮箱 | "扫了张总的名片" |
| `meeting` | 会议纪要 | 会议、纪要、讨论、参会人、议程、决议 | "今天开了产品评审会" |
| `call` | 电话记录 | 电话、通话、沟通、聊了、对方说 | "刚跟李总通了电话" |
| `manual` | 手动补全 | 补充、添加、手动录入、自由文本 | "补充一下王明的信息" |
| `todo_input` | Todo创建 | 待办、提醒、记得、别忘了、跟进 | "提醒我下周联系张总" |
| `relationship` | 关系维护 | 关系、人脉、维护、多久没联系 | "跟李总好久没联系了" |
| `business_opportunity` | 商机线索 | 商机、合作、项目机会、投资、对接 | "李总那边有个AI项目的机会" |
| `query` | 信息查询 | 查找、搜索、谁认识、有没有资源 | "谁认识做NLP的？" |

**Prompt**:
```
你是一个EventLink输入分类器。请判断以下用户输入属于哪种scope。

8种scope定义：
1. card（名片）：名片扫描/OCR识别结果，包含姓名、公司、职位、联系方式等结构化或半结构化信息
2. meeting（会议）：会议纪要、讨论记录，包含参会人、议题、决议等
3. call（电话）：通话记录、沟通摘要，包含对话双方及交流要点
4. manual（手动补全）：用户主动补充的信息录入，自由文本形式
5. todo_input（Todo创建）：待办事项、提醒、跟进任务创建请求
6. relationship（关系维护）：关于人际关系经营、人脉维护的查询或操作
7. business_opportunity（商机线索）：商业合作机会、项目对接、投资意向等
8. query（信息查询）：查找特定人物、资源、关系的查询请求

分类规则：
1. 优先匹配最具体的scope（如同时满足card和manual，选card）
2. 如果输入包含多个scope特征，选择置信度最高的主scope
3. 如果无法明确判断，返回query作为默认值
4. 输出secondary_scopes数组，列出其他可能匹配的scope（置信度>0.3）

用户输入：
{user_input}

上下文提示：
{context_hint}

输出JSON格式：
{{
  "primary_scope": "scope名称",
  "scope_confidence": 0.0-1.0,
  "secondary_scopes": [
    {{"scope": "scope名称", "confidence": 0.0-1.0}}
  ],
  "reasoning": "分类理由",
  "suggested_pipeline": "推荐处理管线",
  "is_ai_inference": false,
  "confidence_level": "confirmed",
  "requires_confirmation": false
}}
```

**输出示例**:
```json
{
  "primary_scope": "card",
  "scope_confidence": 0.95,
  "secondary_scopes": [
    {"scope": "manual", "confidence": 0.3}
  ],
  "reasoning": "输入包含完整的姓名、公司、职位、联系方式字段，符合名片OCR输出特征",
  "suggested_pipeline": "card_save",
  "is_ai_inference": false,
  "confidence_level": "confirmed",
  "requires_confirmation": false
}
```

---

## 1. 模板1：名片信息提取

**用途**: 从OCR识别的名片文本中提取结构化人物信息

**输入变量**:

| 变量 | 类型 | 说明 |
|------|------|------|
| ocr_text | string | OCR识别的原始文本 |

**Prompt**:
```
你是一个商务名片信息提取专家。请从以下OCR识别的文本中提取结构化信息。

规则：
1. 如果某个字段无法识别，设为null
2. 电话号码统一格式：保留原始格式
3. resource字段：从职位/公司推断此人的核心能力和资源
4. demand字段：从公司业务方向推断此人可能的需求
5. 如果无法推断resource/demand，设为空数组

输出语言规则：
1. 输出语言必须与输入语言一致
2. 推测内容必须标注（来源：原文引用）
3. 禁止对他人资源做确定性判断
4. 禁止建议索取资源

OCR文本：
{ocr_text}

输出JSON格式：
{{
  "name": "姓名",
  "company": "公司",
  "title": "职位",
  "phone": "电话",
  "email": "邮箱",
  "city": "城市",
  "resource": ["能力1", "能力2"],
  "demand": ["需求1"],
  "industry": "行业",
  "confidence": 0.95,
  "is_ai_inference": true,
  "confidence_level": "confirmed|inferred|speculated",
  "requires_confirmation": false
}}
```

**输出示例**:
```json
{
  "name": "张三",
  "company": "智源AI科技",
  "title": "CEO",
  "phone": "13812345678",
  "email": "zhangsan@zhiyuan-ai.com",
  "city": "北京",
  "resource": ["AI算法专家（来源：职位CEO，AI公司）", "计算机视觉5年经验（来源：推测，需确认）"],
  "demand": [],
  "industry": "人工智能",
  "confidence": 0.95,
  "is_ai_inference": true,
  "confidence_level": "inferred",
  "requires_confirmation": true
}
```

---

## 2. 模板2：语音实体抽取

**用途**: 从语音转写文本中提取人物实体、事件和资源信息，包含关系阶段初始化

**输入变量**:

| 变量 | 类型 | 说明 |
|------|------|------|
| transcript | string | ASR转写的对话文本 |
| language | string | 语言代码（zh-CN/en-US） |

**relationship_stage 初始值规则**:
- 首次提取的实体，`relationship_stage` 默认设为 `"initial"`（初始接触）
- 如果对话中明确提到已有合作/认识历史，可设为 `"awareness"`（相互了解）
- 不可自动设置为更高级别（如 `exploration`、`negotiation` 等），需用户后续确认

**entities properties 结构更新**:
- 每个person entity新增 `relationship_stage` 字段
- 每个person entity新增 `properties` 对象，包含：
  - `interaction_count`: 交互次数（首次=1）
  - `last_contact_date`: 最近联系日期（如提及）
  - `trust_level`: 信任等级（"low"|"medium"|"high"，默认"low"）
  - `tags`: 标签数组（从对话中提取的关键标签）

**Prompt**:
```
你是一个商务对话分析专家。请从以下对话转写文本中提取关键信息。

规则：
1. 人物：提取所有提及的人物，包括说话人和被提及的人
2. 事件：提取讨论的事件/会议/项目
3. 资源识别：识别每个人物拥有的核心资源（能力、人脉、渠道）
4. 需求识别：识别每个人物表达的需求
5. 关键词：提取业务相关词汇
6. 如果信息不足以判断，对应字段设为null
7. relationship_stage初始化：首次提取默认"initial"，如有明确历史可设"awareness"
8. properties结构：包含interaction_count、last_contact_date、trust_level、tags

输出语言规则：
1. 输出语言必须与输入语言一致
2. 推测内容必须标注（来源：原文引用）
3. 禁止对他人资源做确定性判断
4. 禁止建议索取资源

对话文本（{language}）：
{transcript}

输出JSON格式：
{{
  "persons": [
    {{
      "name": "姓名",
      "company": "公司（如提及）",
      "title": "职位（如提及）",
      "resource": ["此人的能力/人脉/渠道"],
      "demand": ["此人表达的需求"],
      "relationship_stage": "initial|awareness",
      "properties": {{
        "interaction_count": 1,
        "last_contact_date": "ISO 8601日期或null",
        "trust_level": "low|medium|high",
        "tags": ["标签1", "标签2"]
      }}
    }}
  ],
  "events": [
    {{
      "name": "事件名称",
      "time": "时间（如提及）",
      "location": "地点（如提及）",
      "topic": "主题"
    }}
  ],
  "keywords": ["关键词1", "关键词2"],
  "summary": "对话摘要（50字以内）",
  "is_ai_inference": true,
  "confidence_level": "confirmed|inferred|speculated",
  "requires_confirmation": false
}}
```

**输出示例**:
```json
{
  "persons": [
    {
      "name": "李总",
      "company": "盛恒资本",
      "title": "投资总监",
      "resource": ["早期项目投资渠道（来源：对话原文）", "AI领域投资经验（来源：对话原文）"],
      "demand": ["寻找AI赛道优质项目（来源：对话原文）"],
      "relationship_stage": "awareness",
      "properties": {
        "interaction_count": 1,
        "last_contact_date": "2026-06-04",
        "trust_level": "medium",
        "tags": ["投资", "AI", "早期项目"]
      }
    },
    {
      "name": "王明",
      "company": null,
      "title": null,
      "resource": ["推荐了3个AI项目（来源：对话原文）"],
      "demand": [],
      "relationship_stage": "initial",
      "properties": {
        "interaction_count": 1,
        "last_contact_date": null,
        "trust_level": "low",
        "tags": []
      }
    }
  ],
  "events": [
    {
      "name": "投资对接会",
      "time": "下周三",
      "location": "国贸",
      "topic": "AI项目路演"
    }
  ],
  "keywords": ["AI投资", "早期项目", "路演"],
  "summary": "李总寻找AI项目，王明推荐了3个项目并安排下周路演",
  "is_ai_inference": false,
  "confidence_level": "confirmed",
  "requires_confirmation": false
}
```

---

## 3. 模板3：Todo生成（含todo_type + action_type）

**用途**: 根据对话内容和上下文生成待办事项，必须指定todo_type和action_type

**输入变量**:

| 变量 | 类型 | 说明 |
|------|------|------|
| conversation | string | 对话/事件内容 |
| persons | string | 相关人物信息 |
| todo_type | string | Todo类型（6种之一） |
| user_context | string | 用户自身资源/需求背景 |

**6种todo_type及生成策略**:

| todo_type | 说明 | 生成策略 | 优先级倾向 |
|-----------|------|---------|-----------|
| promise | 承诺 | 提取"我答应过什么"，强调兑现承诺的行动步骤和截止时间 | high |
| help | 帮助 | 建议"我能为他做什么"，基于对方需求给出可执行的援助方案 | medium |
| care | 关注 | 提取"对方正在关心什么"，标记对方关注点以便跟进 | medium |
| followup | 跟进 | 标记需跟进的事项，强调待确认点和下一步行动 | medium |
| cooperation_signal | 合作信号 | 识别合作信号，发现资源互补和合作可能 | high |
| risk | 风险 | 识别潜在风险，强调预警和规避措施 | high |

**6种action_type及识别规则**:

| action_type | 说明 | 触发关键词示例 |
|-------------|------|---------------|
| `contact` | 联系触达 | 联系、打电话、发微信、约见面、沟通、对接 |
| `send` | 发送资料 | 发送、分享、转发、邮件、资料、文档、案例 |
| `research` | 调研分析 | 查一下、调研、了解、分析、评估、对比 |
| `prepare` | 准备工作 | 准备、整理、汇总、梳理、草拟、方案 |
| `decide` | 决策确认 | 确认、决定、选择、审批、同意、反馈 |
| `monitor` | 监控跟踪 | 关注、跟踪、监控、观察、留意、跟进进展 |

**降噪规则**:
1. 排除纯寒暄内容（"你好"、"谢谢"、"再见"等）
2. 排除重复信息（同一事项不重复生成Todo）
3. 排除过于模糊的表述（"以后再说"、"有空聊聊"等无明确行动项的内容）
4. 排除已完成的动作（"已经发了"、"已经联系了"等过去完成时）
5. 单次对话最多生成3条Todo，按优先级排序
6. 所有生成的Todo默认 `confirmation: "pending"`，需用户确认后才变为 `confirmed`

**Prompt**:
```
你是一个个人商务关系经营助手。请根据以下信息生成待办事项。

Todo类型：{todo_type}
- promise（承诺）：提取"我答应过什么"，给出兑现承诺的行动步骤和截止时间
- help（帮助）：建议"我能为他做什么"，基于对方需求给出可执行的援助方案
- care（关注）：提取"对方正在关心什么"，标记对方关注点以便跟进
- followup（跟进）：标记需跟进的事项，列出待确认点和下一步行动
- cooperation_signal（合作信号）：识别合作信号，发现资源互补和合作可能
- risk（风险）：识别潜在风险，给出预警和规避措施

Action类型（必须从6种中选择最匹配的一种）：
- contact（联系触达）：联系、打电话、发微信、约见面、沟通、对接
- send（发送资料）：发送、分享、转发、邮件、资料、文档、案例
- research（调研分析）：查一下、调研、了解、分析、评估、对比
- prepare（准备工作）：准备、整理、汇总、梳理、草拟、方案
- decide（决策确认）：确认、决定、选择、审批、同意、反馈
- monitor（监控跟踪）：关注、跟踪、监控、观察、留意、跟进进展

降噪规则：
1. 排除纯寒暄内容（"你好"、"谢谢"、"再见"等）
2. 排除重复信息（同一事项不重复生成）
3. 排除过于模糊的表述（"以后再说"、"有空聊聊"等无明确行动项）
4. 排除已完成的动作（"已经发了"、"已经联系了"等过去完成时）
5. 单次对话最多生成3条Todo，按优先级排序

对话内容：
{conversation}

相关人物：
{persons}

用户背景：
{user_context}

规则：
1. 描述必须简洁明确，不超过100字
2. 根据todo_type采用不同的语气和侧重点
3. priority必须与todo_type匹配
4. due_date建议：promise/cooperation_signal=3天内，risk=1天内，care/followup=7天内，help=5天内
5. context字段必须包含生成此Todo的原因
6. action_type必须从6种中选择最匹配的一种
7. confirmation默认为"pending"，表示待用户确认

输出语言规则：
1. 输出语言必须与输入语言一致
2. 禁止建议索取资源
3. 禁止自动撮合
4. 推测必须标记

输出JSON格式：
{{
  "todo_type": "{todo_type}",
  "action_type": "contact|send|research|prepare|decide|monitor",
  "description": "Todo描述",
  "priority": "high|medium|low",
  "due_date_suggestion": "建议截止时间（ISO 8601）",
  "confirmation": "pending",
  "context": {{
    "reason": "生成原因",
    "suggested_action": "建议行动",
    "related_entities": ["相关人物名"]
  }},
  "is_ai_inference": true,
  "confidence_level": "confirmed|inferred|speculated",
  "requires_confirmation": true
}}
```

**输出示例（cooperation_signal类型）**:
```json
{
  "todo_type": "cooperation_signal",
  "action_type": "contact",
  "description": "⚪ 合作信号：李总寻找AI项目，王明有3个推荐项目可对接",
  "priority": "high",
  "due_date_suggestion": "2026-06-06T00:00:00Z",
  "confirmation": "pending",
  "context": {
    "reason": "李总（盛恒资本投资总监）正在寻找AI赛道项目，与王明推荐的3个项目高度匹配，存在合作可能",
    "suggested_action": "联系王明获取项目详情，安排与李总的路演对接",
    "related_entities": ["李总", "王明"]
  },
  "is_ai_inference": true,
  "confidence_level": "inferred",
  "requires_confirmation": true
}
```

**输出示例（help类型）**:
```json
{
  "todo_type": "help",
  "action_type": "send",
  "description": "🟢 帮助：张总最近在关注AI大模型落地，你可以分享相关案例",
  "priority": "medium",
  "due_date_suggestion": "2026-06-08T00:00:00Z",
  "confirmation": "pending",
  "context": {
    "reason": "张总（AI公司CEO）正在研究大模型落地场景，你有相关行业案例可以分享",
    "suggested_action": "整理2-3个大模型落地案例，微信发给张总参考",
    "related_entities": ["张总"]
  },
  "is_ai_inference": false,
  "confidence_level": "confirmed",
  "requires_confirmation": false
}
```

---

## 4. 模板4：商机描述优化

**用途**: 优化用户输入的商机描述，使其结构化、清晰

**输入变量**:

| 变量 | 类型 | 说明 |
|------|------|------|
| raw_description | string | 用户原始描述 |
| related_person | string | 相关人物信息（可选） |

**Prompt**:
```
你是一个商务写作优化专家。请优化以下商机描述，使其更清晰、更结构化。

规则：
1. 明确区分需求方和资源方
2. 提取业务领域和关键词
3. 评估callability（可联络性）：该商机是否可以通过现有关系触达
4. 保持原意，不添加不存在的信息
5. 优化后描述不超过200字

输出语言规则：
1. 输出语言必须与输入语言一致
2. 禁止添加原文不存在的信息
3. 推测必须标记

原始描述：
{raw_description}

相关人物：
{related_person}

输出JSON格式：
{{
  "optimized_description": "优化后的描述",
  "demand_side": "需求方",
  "resource_side": "资源方",
  "domain": "业务领域",
  "keywords": ["关键词1", "关键词2"],
  "callability": "high|medium|low",
  "callability_reason": "可联络性评估原因",
  "is_ai_inference": true,
  "confidence_level": "confirmed|inferred|speculated",
  "requires_confirmation": false
}}
```

**输出示例**:
```json
{
  "optimized_description": "盛恒资本（投资总监李总）寻找AI赛道早期项目，预算500万-2000万，偏好计算机视觉和NLP方向。可通过王明引荐对接。",
  "demand_side": "盛恒资本（李总）",
  "resource_side": "王明（可引荐3个AI项目）",
  "domain": "AI投资",
  "keywords": ["AI投资", "早期项目", "计算机视觉", "NLP"],
  "callability": "high",
  "callability_reason": "王明与李总有直接联系，可安排路演对接",
  "is_ai_inference": false,
  "confidence_level": "confirmed",
  "requires_confirmation": false
}
```

---

## 5. 模板5：实体归一判断

**用途**: 判断两个实体是否为同一人/同一组织

**输入变量**:

| 变量 | 类型 | 说明 |
|------|------|------|
| entity_a | string | 实体A的信息（JSON） |
| entity_b | string | 实体B的信息（JSON） |

**Prompt**:
```
你是一个实体归一判断专家。请判断以下两个实体是否为同一人/同一组织。

规则：
1. 综合考虑姓名、公司、职位、联系方式、行业等多维度
2. 同一人可能在不同场景使用不同称呼（如"张三"/"张总"/"Zhang San"）
3. 同一人可能换了公司或职位
4. 如果信息冲突（如不同手机号+不同公司+不同行业），判断为不同人
5. 给出0.0-1.0的置信度分数

实体A：
{entity_a}

实体B：
{entity_b}

输出JSON格式：
{{
  "is_same": true|false,
  "confidence": 0.0-1.0,
  "reasoning": "判断理由",
  "conflict_fields": ["冲突字段列表"],
  "matched_fields": ["匹配字段列表"],
  "suggestion": "merge|keep_separate|need_confirm",
  "is_ai_inference": true,
  "confidence_level": "confirmed|inferred|speculated",
  "requires_confirmation": true
}}
```

**输出示例**:
```json
{
  "is_same": true,
  "confidence": 0.88,
  "reasoning": "姓名相同，公司相同，职位从CTO变更为CEO符合晋升路径，手机号前7位一致",
  "conflict_fields": ["title"],
  "matched_fields": ["name", "company", "phone_prefix", "industry"],
  "suggestion": "merge",
  "is_ai_inference": true,
  "confidence_level": "inferred",
  "requires_confirmation": true
}
```

---

## 6. 模板6：关系发现

**用途**: 从文本中发现两个实体之间的潜在关联关系

**输入变量**:

| 变量 | 类型 | 说明 |
|------|------|------|
| entity_a | string | 实体A信息 |
| entity_b | string | 实体B信息 |
| context_text | string | 上下文文本（对话/事件记录） |

**Prompt**:
```
你是一个商务关系分析专家。请分析以下两个实体之间可能存在的关系。

关联类型（8种）：
- alumni：校友关系
- ex_colleague：前同事
- same_city：同城
- competitor：竞对关系
- tech_overlap：技术重叠
- deal_link：交易关联
- risk_link：风险关联
- supply_chain：供应链关系

实体A：
{entity_a}

实体B：
{entity_b}

上下文：
{context_text}

规则：
1. 基于实体信息和上下文文本综合判断
2. 一对实体可能存在多种关联
3. 每种关联给出0.0-1.0的置信度
4. 置信度≥0.7的关联才输出
5. 提供判断依据

输出语言规则：
1. 推测必须标记
2. 禁止推断人格

输出JSON格式：
{{
  "associations": [
    {{
      "assoc_type": "关联类型",
      "confidence": 0.0-1.0,
      "evidence": "判断依据"
    }}
  ],
  "is_ai_inference": true,
  "confidence_level": "confirmed|inferred|speculated",
  "requires_confirmation": false
}}
```

**输出示例**:
```json
{
  "associations": [
    {
      "assoc_type": "alumni",
      "confidence": 0.92,
      "evidence": "两人均毕业于清华大学计算机系，张三2010届，李四2012届"
    },
    {
      "assoc_type": "tech_overlap",
      "confidence": 0.78,
      "evidence": "两人都在AI领域，张三专注CV，李四专注NLP，技术栈有重叠"
    }
  ],
  "is_ai_inference": true,
  "confidence_level": "inferred",
  "requires_confirmation": false
}
```

---

## 7. 模板7：资源识别

**用途**: 从文本中识别人的资源（能力、人脉、渠道）

**输入变量**:

| 变量 | 类型 | 说明 |
|------|------|------|
| text | string | 包含人物信息的文本 |
| person_name | string | 目标人物姓名 |

**Prompt**:
```
你是一个个人商务关系经营助手的资源识别模块。请从以下文本中识别{person_name}的核心资源。

资源分类：
1. 能力资源：专业技能、行业经验、知识储备
2. 人脉资源：可触达的关键人物、社交网络
3. 渠道资源：可调动的资金、项目、市场渠道

规则：
1. 仅提取有明确文本依据的资源，不推测
2. 每个资源标注来源句子
3. 评估资源的稀缺性（高/中/低）
4. 评估资源的可触达性（callability）：用户是否可以通过现有关系链触达

输出语言规则：
1. 禁止AI自动判定对方资源——仅引用原文
2. 禁止建议索取资源
3. 推测必须标记

文本：
{text}

目标人物：{person_name}

输出JSON格式：
{{
  "person": "{person_name}",
  "resources": [
    {{
      "category": "ability|network|channel",
      "description": "资源描述",
      "source_text": "来源原文",
      "scarcity": "high|medium|low",
      "callability": "high|medium|low",
      "callability_reason": "可触达性原因"
    }}
  ],
  "resource_summary": "资源概况（50字内）",
  "is_ai_inference": true,
  "confidence_level": "confirmed|inferred|speculated",
  "requires_confirmation": false
}}
```

**输出示例**:
```json
{
  "person": "李总",
  "resources": [
    {
      "category": "ability",
      "description": "AI领域早期项目投资经验，5年投资总监",
      "source_text": "李总是盛恒资本投资总监，专注AI赛道5年",
      "scarcity": "high",
      "callability": "high",
      "callability_reason": "通过王明可直接引荐"
    },
    {
      "category": "channel",
      "description": "盛恒资本500万-2000万早期项目投资预算",
      "source_text": "预算500万-2000万",
      "scarcity": "high",
      "callability": "medium",
      "callability_reason": "需通过路演形式对接，非直接可触达"
    }
  ],
  "resource_summary": "李总拥有AI投资渠道和人脉网络，是高价值投资类资源",
  "is_ai_inference": false,
  "confidence_level": "confirmed",
  "requires_confirmation": false
}
```

---

## 8. 模板8：需求提取

**用途**: 从文本中提取人的需求，用于商机匹配

**输入变量**:

| 变量 | 类型 | 说明 |
|------|------|------|
| text | string | 包含人物信息的文本 |
| person_name | string | 目标人物姓名 |

**Prompt**:
```
你是一个个人商务关系经营助手的需求提取模块。请从以下文本中提取{person_name}的需求。

需求分类：
1. 人才需求：招聘、合作、推荐
2. 资金需求：融资、投资、预算
3. 资源需求：渠道、供应商、合作伙伴
4. 信息需求：行业信息、市场情报、技术趋势

规则：
1. 仅提取有明确文本依据的需求，不推测
2. 每个需求标注来源句子
3. 评估需求的紧迫性（高/中/低）
4. 评估需求的匹配潜力：用户是否有资源可以匹配此需求

输出语言规则：
1. 禁止AI自动判定对方需求——仅引用原文
2. 禁止建议索取资源
3. 推测必须标记

文本：
{text}

目标人物：{person_name}

输出JSON格式：
{{
  "person": "{person_name}",
  "demands": [
    {{
      "category": "talent|funding|resource|information",
      "description": "需求描述",
      "source_text": "来源原文",
      "urgency": "high|medium|low",
      "match_potential": "high|medium|low",
      "match_reason": "匹配潜力原因"
    }}
  ],
  "demand_summary": "需求概况（50字内）",
  "is_ai_inference": true,
  "confidence_level": "confirmed|inferred|speculated",
  "requires_confirmation": false
}}
```

**输出示例**:
```json
{
  "person": "李总",
  "demands": [
    {
      "category": "resource",
      "description": "寻找AI赛道优质早期项目",
      "source_text": "李总正在寻找AI赛道的优质早期项目",
      "urgency": "high",
      "match_potential": "high",
      "match_reason": "用户认识多个AI创业者，可推荐项目"
    }
  ],
  "demand_summary": "李总急需AI项目推荐和技术评估支持",
  "is_ai_inference": false,
  "confidence_level": "confirmed",
  "requires_confirmation": false
}
```

---

## 9. 模板9：敏感度判断

**用途**: 判断资源/需求是否适合进行匹配推荐，保护用户隐私

**输入变量**:

| 变量 | 类型 | 说明 |
|------|------|------|
| resource_text | string | 资源描述 |
| demand_text | string | 需求描述 |
| person_info | string | 人物信息 |

**Prompt**:
```
你是一个隐私保护专家。请判断以下资源/需求是否适合在个人商务关系经营助手中进行匹配推荐。

敏感度级别：
- matchable：可以匹配推荐。信息属于公开或半公开性质，匹配推荐不会造成隐私风险。
- no_match：不可匹配推荐。信息涉及敏感隐私，匹配推荐可能造成关系损害或隐私泄露。

判断标准：
1. 涉及个人财务状况（薪资、资产）→ no_match
2. 涉及未公开的商业机密 → no_match
3. 涉及个人健康/家庭隐私 → no_match
4. 明确表示不希望被推荐 → no_match
5. 公开可获取的行业信息 → matchable
6. 在公开场合表达的需求 → matchable
7. 一般性的职业能力和经验 → matchable
8. 通用的人脉关系（校友/同行）→ matchable

资源描述：
{resource_text}

需求描述：
{demand_text}

人物信息：
{person_info}

输出JSON格式：
{{
  "sensitivity": "matchable|no_match",
  "confidence": 0.0-1.0,
  "reasoning": "判断理由",
  "risk_points": ["风险点列表（如有）"],
  "safe_alternative": "安全的替代描述（如敏感，给出脱敏版本）",
  "is_ai_inference": true,
  "confidence_level": "confirmed|inferred|speculated",
  "requires_confirmation": true
}}
```

**输出示例（matchable）**:
```json
{
  "sensitivity": "matchable",
  "confidence": 0.92,
  "reasoning": "李总的投资需求在公开路演中表达，属于半公开信息，匹配推荐不会造成隐私风险",
  "risk_points": [],
  "safe_alternative": null,
  "is_ai_inference": false,
  "confidence_level": "confirmed",
  "requires_confirmation": false
}
```

**输出示例（no_match）**:
```json
{
  "sensitivity": "no_match",
  "confidence": 0.88,
  "reasoning": "张总私下透露正在考虑离职创业，此信息未公开，匹配推荐可能损害其当前职位",
  "risk_points": ["未公开的离职意向", "可能影响当前职位稳定性"],
  "safe_alternative": "张总对AI创业方向有兴趣（脱敏版本）",
  "is_ai_inference": true,
  "confidence_level": "inferred",
  "requires_confirmation": true
}
```

---

## 10. 模板10：关系维护建议

**用途**: 基于交互历史生成关系维护建议，辅助用户经营人脉

**输入变量**:

| 变量 | 类型 | 说明 |
|------|------|------|
| person_info | string | 人物信息（JSON） |
| interaction_history | string | 交互历史摘要 |
| days_since_last | int | 距上次联系天数 |

**Prompt**:
```
你是一个个人商务关系经营助手的关系维护模块。请基于以下信息生成关系维护建议。

规则：
1. 根据关系亲密度和重要程度给出不同频次的维护建议
2. 维护方式要自然，避免刻意感
3. 建议要具体可执行，不要笼统的"保持联系"
4. 考虑时机（节日、行业事件、对方动态）
5. 生成todo_type为help的待办建议

输出语言规则：
1. 禁止建议索取资源
2. 禁止自动发送
3. 推测必须标记

人物信息：
{person_info}

交互历史：
{interaction_history}

距上次联系：{days_since_last}天

维护频次参考：
- 核心人脉（高频合作）：7-14天
- 重要人脉（有合作潜力）：14-30天
- 一般人脉（保持联络）：30-60天
- 沉默人脉（长期未联系）：60-90天

输出JSON格式：
{{
  "todo_type": "help",
  "description": "帮助建议描述",
  "priority": "high|medium|low",
  "suggested_action": "具体行动建议",
  "suggested_timing": "建议时机",
  "message_template": "可发送的消息模板（可选）",
  "reasoning": "建议理由",
  "is_ai_inference": true,
  "confidence_level": "confirmed|inferred|speculated",
  "requires_confirmation": false
}}
```

**输出示例**:
```json
{
  "todo_type": "help",
  "description": "🟢 帮助：与李总已21天未联系，建议分享AI行业资讯",
  "priority": "medium",
  "suggested_action": "微信分享一篇AI投资趋势文章，附简短评论",
  "suggested_timing": "工作日上午10-11点（投资圈阅读高峰）",
  "message_template": "李总，看到这篇AI投资趋势分析，跟您之前关注的CV方向相关，供参考",
  "reasoning": "李总是重要投资人人脉，21天未联系接近维护窗口期，分享行业资讯是最自然的触达方式",
  "is_ai_inference": false,
  "confidence_level": "confirmed",
  "requires_confirmation": false
}
```

---

## 11. 模板11：承诺提取

**用途**: 从交流内容中提取"我答应过什么"，生成promise类型的Todo

**输入变量**:

| 变量 | 类型 | 说明 |
|------|------|------|
| conversation | string | 对话/交流内容 |
| persons | string | 相关人物信息 |

**Prompt**:
```
你是一个个人商务关系经营助手。请从以下交流内容中提取"我答应过什么"——即用户自己做出的承诺。

规则：
1. 仅提取用户（第一人称）做出的承诺，不提取对方的承诺
2. 承诺包括：答应做的事、答应提供的资源、答应的见面/通话、答应的介绍/推荐
3. 每个承诺必须包含：对谁承诺、承诺了什么
4. 如果承诺有明确时间，提取时间；如果没有，建议一个合理的截止时间
5. 不推测，仅提取有明确文本依据的承诺
6. 如果没有发现承诺，返回空数组

输出语言规则：
1. 推测必须标记
2. 禁止添加原文不存在的信息

交流内容：
{conversation}

相关人物：
{persons}

输出JSON格式：
{{
  "promises": [
    {{
      "to_person": "承诺对象",
      "content": "承诺内容",
      "mentioned_deadline": "提及的截止时间（如无则为null）",
      "suggested_deadline": "建议截止时间（ISO 8601）",
      "priority": "high|medium|low",
      "source_text": "来源原文"
    }}
  ],
  "summary": "承诺概况（30字内）",
  "is_ai_inference": false,
  "confidence_level": "confirmed|inferred|speculated",
  "requires_confirmation": false
}}
```

**输出示例**:
```json
{
  "promises": [
    {
      "to_person": "李总",
      "content": "下周一前发送AI项目资料",
      "mentioned_deadline": "下周一",
      "suggested_deadline": "2026-06-09T00:00:00Z",
      "priority": "high",
      "source_text": "我说好下周一前把AI项目的资料发给您"
    },
    {
      "to_person": "王明",
      "content": "介绍AI算法工程师",
      "mentioned_deadline": null,
      "suggested_deadline": "2026-06-10T00:00:00Z",
      "priority": "medium",
      "source_text": "我答应帮他介绍一个做AI算法的工程师"
    }
  ],
  "summary": "2项承诺：给李总发资料、给王明介绍人",
  "is_ai_inference": false,
  "confidence_level": "confirmed",
  "requires_confirmation": false
}
```

---

## 12. 模板12：关注点提取

**用途**: 从交流内容中提取"对方正在关心什么"，生成care类型的Todo

**输入变量**:

| 变量 | 类型 | 说明 |
|------|------|------|
| conversation | string | 对话/交流内容 |
| persons | string | 相关人物信息 |

**Prompt**:
```
你是一个个人商务关系经营助手。请从以下交流内容中提取"对方正在关心什么"——即交流对象关注的议题和痛点。

规则：
1. 仅提取对方（非用户本人）表达的关注点
2. 关注点包括：正在解决的问题、正在考虑的方案、正在寻找的资源、表达过的担忧
3. 每个关注点必须包含：谁在关注、关注什么
4. 标注关注点的紧迫程度
5. 不推测，仅提取有明确文本依据的关注点
6. 如果没有发现关注点，返回空数组

输出语言规则：
1. 推测必须标记
2. 禁止AI自动判定对方资源
3. 禁止建议索取资源

交流内容：
{conversation}

相关人物：
{persons}

输出JSON格式：
{{
  "cares": [
    {{
      "person": "关注者",
      "topic": "关注议题",
      "detail": "关注详情",
      "urgency": "high|medium|low",
      "source_text": "来源原文"
    }}
  ],
  "summary": "关注点概况（30字内）",
  "is_ai_inference": false,
  "confidence_level": "confirmed|inferred|speculated",
  "requires_confirmation": false
}}
```

**输出示例**:
```json
{
  "cares": [
    {
      "person": "李总",
      "topic": "AI项目投资评估",
      "detail": "正在寻找AI赛道优质早期项目，关注计算机视觉和NLP方向",
      "urgency": "high",
      "source_text": "李总说他最近一直在看AI赛道的项目，特别是CV和NLP方向的"
    },
    {
      "person": "王明",
      "topic": "团队招聘",
      "detail": "正在招聘AI算法工程师，已经找了2个月还没找到合适的",
      "urgency": "medium",
      "source_text": "王明提到他们团队缺一个AI算法工程师，招了两个月了"
    }
  ],
  "summary": "2个关注点：李总关注AI投资，王明关注招聘",
  "is_ai_inference": false,
  "confidence_level": "confirmed",
  "requires_confirmation": false
}
```

---

## 13. 模板13：RelationshipBrief 生成

**用途**: 根据已有的关系数据生成结构化的 RelationshipBrief，包含12个模块的完整填充

**输入变量**:

| 变量 | 类型 | 说明 |
|------|------|------|
| person_info | string | 目标人物信息（JSON） |
| interaction_history | string | 历史交互记录摘要 |
| existing_data | string | 已有的关系数据（JSON，可选） |

**12模块定义**:

| # | 模块名称 | 说明 | 数据来源 |
|---|---------|------|---------|
| 1 | basic_profile | 基础画像（姓名、公司、职位等） | 实体抽取 + 手动补充 |
| 2 | resource_capability | 资源与能力清单 | 资源识别结果 |
| 3 | demand_analysis | 需求分析 | 需求提取结果 |
| 4 | relationship_stage | 关系阶段 | 当前阶段 + 推进建议 |
| 5 | interaction_history | 交互历史 | 时间线形式的交互记录 |
| 6 | trust_assessment | 信任评估 | 基于交互频次和质量 |
| 7 | cooperation_potential | 合作潜力评估 | 资源-需求匹配度分析 |
| 8 | risk_factors | 风险因素 | 已识别的风险点 |
| 9 | maintenance_strategy | 维护策略 | 建议的维护方式和频次 |
| 10 | next_actions | 下一步行动建议 | 具体可执行的行动项 |
| 11 | network_position | 网络位置 | 在用户人脉网络中的定位 |
| 12 | value_score | 价值评分 | 综合价值量化评分 |

**Prompt**:
```
你是一个EventLink关系分析专家。请根据以下信息生成完整的RelationshipBrief。

目标人物：
{person_info}

历史交互记录：
{interaction_history}

已有关系数据：
{existing_data}

规则：
1. 逐个填充12个模块，每个模块必须包含具体内容
2. 如果某个模块信息不足，标注"待补充"并说明缺少什么
3. 所有推测内容必须标记来源和置信度
4. relationship_stage不可自动升级，仅基于已有证据判断
5. value_score基于多维度加权计算（资源稀缺性×0.3 + 合作潜力×0.3 + 信任度×0.2 + 网络价值×0.2）
6. next_actions最多3条，按优先级排序
7. 输出语言与输入语言一致

输出JSON格式：
{{
  "relationship_brief": {{
    "basic_profile": {{
      "name": "姓名",
      "company": "公司",
      "title": "职位",
      "industry": "行业",
      "city": "城市",
      "contact_methods": ["联系方式"],
      "source": "信息来源"
    }},
    "resource_capability": {{
      "core_resources": ["核心资源列表"],
      "scarcity_level": "high|medium|low",
      "accessibility": "high|medium|low"
    }},
    "demand_analysis": {{
      "current_demands": ["当前需求"],
      "urgency": "high|medium|low",
      "match_with_user_resources": "匹配度说明"
    }},
    "relationship_stage": {{
      "current_stage": "initial|awareness|exploration|negotiation|collaboration|maintenance",
      "stage_since": "ISO 8601日期",
      "evidence": "当前阶段的证据"
    }},
    "interaction_history": [
      {{"date": "日期", "type": "meeting|call|message", "summary": "摘要"}}
    ],
    "trust_assessment": {{
      "level": "low|medium|high",
      "score": 0.0-1.0,
      "factors": ["评分因素"]
    }},
    "cooperation_potential": {{
      "score": 0.0-1.0,
      "areas": ["合作领域"],
      "barriers": ["障碍"]
    }},
    "risk_factors": [
      {{"type": "风险类型", "description": "描述", "severity": "high|medium|low"}}
    ],
    "maintenance_strategy": {{
      "recommended_frequency": "频次建议",
      "preferred_channels": ["渠道"],
      "key_topics": ["话题"]
    }},
    "next_actions": [
      {{"action": "行动", "priority": "high|medium|low", "deadline": "建议时间"}}
    ],
    "network_position": {{
      "role": "hub|connector|specialist|peripheral",
      "connections_count": 数字,
      "strategic_value": "高|中|低"
    }},
    "value_score": {{
      "total": 0.0-100,
      "breakdown": {{
        "resource_scarcity": 0-30,
        "cooperation_potential": 0-30,
        "trust": 0-20,
        "network_value": 0-20
      }}
    }}
  }},
  "is_ai_inference": true,
  "confidence_level": "confirmed|inferred|speculated",
  "requires_confirmation": true
}}
```

**输出示例**:
```json
{
  "relationship_brief": {
    "basic_profile": {
      "name": "李总",
      "company": "盛恒资本",
      "title": "投资总监",
      "industry": "投资/金融",
      "city": "北京",
      "contact_methods": ["微信"],
      "source": "会议纪要+名片扫描"
    },
    "resource_capability": {
      "core_resources": ["AI领域早期项目投资渠道（500万-2000万预算）", "5年AI投资经验", "盛恒资本投资决策影响力"],
      "scarcity_level": "high",
      "accessibility": "medium"
    },
    "demand_analysis": {
      "current_demands": ["寻找AI赛道优质早期项目（CV/NLP方向）"],
      "urgency": "high",
      "match_with_user_resources": "用户认识多个AI创业者，可推荐项目"
    },
    "relationship_stage": {
      "current_stage": "awareness",
      "stage_since": "2026-06-04",
      "evidence": "已参加一次投资对接会，双方有初步了解"
    },
    "interaction_history": [
      {"date": "2026-06-04", "type": "meeting", "summary": "参加AI项目路演"}
    ],
    "trust_assessment": {
      "level": "medium",
      "score": 0.55,
      "factors": ["有1次正式交互", "对方表达过明确需求", "尚未深度合作"]
    },
    "cooperation_potential": {
      "score": 0.78,
      "areas": ["AI项目对接", "行业信息共享"],
      "barriers": ["需通过中间人引荐", "投资决策周期较长"]
    },
    "risk_factors": [],
    "maintenance_strategy": {
      "recommended_frequency": "每2周",
      "preferred_channels": ["微信", "线下活动"],
      "key_topics": ["AI行业趋势", "项目进展"]
    },
    "next_actions": [
      {"action": "整理AI项目资料发送给李总", "priority": "high", "deadline": "2026-06-07"},
      {"action": "邀请参加下次AI创业者沙龙", "priority": "medium", "deadline": "2026-06-15"},
      {"action": "分享AI投资趋势报告", "priority": "low", "deadline": "2026-06-21"}
    ],
    "network_position": {
      "role": "connector",
      "connections_count": 3,
      "strategic_value": "高"
    },
    "value_score": {
      "total": 78,
      "breakdown": {
        "resource_scarcity": 25,
        "cooperation_potential": 24,
        "trust": 11,
        "network_value": 18
      }
    }
  },
  "is_ai_inference": true,
  "confidence_level": "inferred",
  "requires_confirmation": true
}
```

---

## 14. 模板14：RelationshipStage 推进建议

**用途**: AI分析关系是否可以推进到下一阶段，提供推进建议（不自动升级）

**输入变量**:

| 变量 | 类型 | 说明 |
|------|------|------|
| current_relationship_data | string | 当前关系数据（RelationshipBrief JSON） |
| recent_interactions | string | 最近交互记录 |
| user_goal | string | 用户期望的关系目标（可选） |

**关系阶段定义**:

| 阶段 | 英文标识 | 说明 | 进入条件 |
|------|---------|------|---------|
| 初始接触 | `initial` | 首次认识/录入系统 | 名片扫描/首次提及 |
| 相互了解 | `awareness` | 双方有基本了解 | 有过至少1次有效交互 |
| 探索合作 | `exploration` | 开始探讨合作可能性 | 有明确的合作意向表达 |
| 商务谈判 | `negotiation` | 具体的商务条款讨论 | 进入实质性的合作洽谈 |
| 正式合作 | `collaboration` | 已建立合作关系 | 有签约或实际合作行为 |
| 维护期 | `maintenance` | 长期合作关系维护 | 合作稳定后的持续维护 |

**Prompt**:
```
你是一个EventLink关系阶段分析师。请分析以下关系是否可以推进到下一阶段。

重要原则：
1. 仅提供建议，不自动升级关系阶段
2. 必须基于客观证据判断，不推测
3. 如果证据不足，明确指出缺少什么
4. 推进建议必须是用户可执行的具体行动
5. 不建议跳级推进（如从initial直接到negotiation）

当前关系数据：
{current_relationship_data}

最近交互记录：
{recent_interactions}

用户目标：
{user_goal}

输出JSON格式：
{{
  "analysis": {{
    "current_stage": "当前阶段",
    "next_possible_stage": "可能的下一阶段",
    "can_advance": true|false,
    "advance_confidence": 0.0-1.0,
    "evidence_for": ["支持推进的证据"],
    "evidence_against": ["不支持推进的证据或风险"],
    "missing_conditions": ["缺少的条件（如无法推进）"]
  }},
  "recommendation": {{
    "should_advance": "yes|no|wait",
    "reason": "建议理由",
    "suggested_actions": [
      {{"action": "具体行动", "priority": "high|medium|low", "expected_outcome": "预期效果"}}
    ],
    "timeline_estimate": "预计所需时间",
    "risk_warning": "风险提示（如有）"
  }},
  "stage_requirements": {{
    "target_stage": "目标阶段",
    "requirements": ["进入该阶段需要的条件"],
    "which_met": ["已满足的条件"],
    "which_not_met": ["未满足的条件"]
  }},
  "is_ai_inference": true,
  "confidence_level": "confirmed|inferred|speculated",
  "requires_confirmation": true
}}
```

**输出示例（可以推进）**:
```json
{
  "analysis": {
    "current_stage": "awareness",
    "next_possible_stage": "exploration",
    "can_advance": true,
    "advance_confidence": 0.72,
    "evidence_for": [
      "李总在路演中表达了寻找AI项目的明确需求",
      "已通过王明成功引荐",
      "李总主动询问了更多项目详情"
    ],
    "evidence_against": [
      "尚未进行一对一深入沟通",
      "李总的投资决策流程较长"
    ],
    "missing_conditions": []
  },
  "recommendation": {
    "should_advance": "yes",
    "reason": "双方已有初步了解且有明确的合作意向，具备进入探索合作阶段的条件",
    "suggested_actions": [
      {"action": "预约与李总的一对一沟通，深入了解其投资偏好", "priority": "high", "expected_outcome": "获得更详细的投资需求"},
      {"action": "准备2-3个匹配度高的AI项目简介", "priority": "high", "expected_outcome": "展示合作价值"},
      {"action": "邀请李总参加AI创业者闭门会", "priority": "medium", "expected_outface": "增加非正式交流机会"}
    ],
    "timeline_estimate": "2-4周",
    "risk_warning": "李总可能同时接触其他项目源，需保持跟进频率"
  },
  "stage_requirements": {
    "target_stage": "exploration",
    "requirements": [
      "双方有基本了解",
      "有明确的合作意向表达",
      "开始交换具体需求和资源信息"
    ],
    "which_met": ["双方有基本了解", "有明确的合作意向表达"],
    "which_not_met": ["尚未深入交换具体需求和资源信息"]
  },
  "is_ai_inference": true,
  "confidence_level": "inferred",
  "requires_confirmation": true
}
```

**输出示例（暂不建议推进）**:
```json
{
  "analysis": {
    "current_stage": "initial",
    "next_possible_stage": "awareness",
    "can_advance": false,
    "advance_confidence": 0.35,
    "evidence_for": [
      "已获取名片信息"
    ],
    "evidence_against": [
      "仅有1次简短接触",
      "对方未表达任何进一步交流意愿",
      "缺乏共同话题或利益点"
    ],
    "missing_conditions": [
      "需要至少1次有效对话",
      "需要找到共同的兴趣点或合作点"
    ]
  },
  "recommendation": {
    "should_advance": "wait",
    "reason": "目前仅有基础联系信息，缺乏足够的互动来支撑关系推进",
    "suggested_actions": [
      {"action": "等待合适的社交场合再次接触", "priority": "medium", "expected_outcome": "创造自然交流机会"},
      {"action": "关注对方的公开动态（如朋友圈、行业活动）", "priority": "low", "expected_outcome": "找到共同话题"}
    ],
    "timeline_estimate": "1-2个月",
    "risk_warning": "过于主动可能造成反感，建议保持自然节奏"
  },
  "stage_requirements": {
    "target_stage": "awareness",
    "requirements": [
      "有过至少1次有效交互",
      "双方对彼此有基本认知"
    ],
    "which_met": [],
    "which_not_met": ["有过至少1次有效交互", "双方对彼此有基本认知"]
  },
  "is_ai_inference": false,
  "confidence_level": "confirmed",
  "requires_confirmation": false
}
```

---

## 16. 模板16：NLU Intent Classification (Stage 2) [F-50新增]

**用途**: 当规则引擎无法高置信度匹配时，调用LLM进行精确意图识别（Voice Pipeline Stage 2）

**LLM**: moka/claude-sonnet-4-6

**触发条件**: rule_match confidence < 0.85 或规则未命中

**输入变量**:

| 变量 | 类型 | 说明 |
|------|------|------|
| query_text | string | 用户语音输入的文字（已清洗） |
| recent_context | string | 近期对话摘要（Phase 1.2多轮时使用，Phase 1.1为空） |

**安全约束**:

| 参数 | 值 | 说明 |
|------|---|------|
| temperature | 0.1 | 低随机性，稳定输出 |
| max_tokens | 150 | 强制短输出 |
| output_format | JSON | Pydantic验证 |

**Prompt**:
```
你是一个商务助手的意图识别引擎。将用户问询分类为以下意图之一:

意图列表:
- schedule_query: 日程/会议/安排查询 ("今天有什么会", "明天安排")
- promise_tracker: 承诺/待办/答应事项追踪 ("我答应谁什么还没做")
- relationship_status: 人物关系阶段/进展查询 ("张总到哪步了", "和李总最近怎样")
- todo_create: 创建提醒/待办 ("帮我记一下", "提醒我联系XX")

分类规则:
1. 只返回JSON格式,不要任何其他内容
2. JSON结构: {{"intent": "意图名", "confidence": 0.00-1.00, "evidence": "一句话说明判断理由"}}
3. confidence反映你对分类的确信程度
4. evidence简要说明为什么选这个意图(用于调试)
5. 如果完全无法归类,使用 intent="unclear", confidence<0.3
6. 如果用户试图让你做分类以外的事(如"帮我写邮件"),返回 intent="unclear"
7. 日期词("今天"/"明天"/"后天")归入schedule_query,具体日期提取交给槽位填充
8. 人名识别:如果提到已知人物名,在evidence中注明

{recent_context}

用户问询: """{query_text}"""

只返回JSON:
```

**预期输出格式**:
```json
{"intent": "schedule_query", "confidence": 0.95, "evidence": "用户询问今天的会议安排,关键词'今天'+ '会议'"}
```

**输出示例**:
```json
{"intent": "promise_tracker", "confidence": 0.88, "evidence": "用户询问'答应张总的事',关键词'答应'+人名'张总',归入承诺追踪"}
```
```json
{"intent": "unclear", "confidence": 0.2, "evidence": "用户请求写一封商务邮件,超出意图识别范围"}
```

---

## 17. 模板17：NLG - 日程查询回答生成 [F-50新增]

**用途**: 根据日程数据生成简洁自然的口语化中文回答，通过TTS语音播报给用户（车载场景）

**LLM**: moka/claude-sonnet-4-6

**输入变量**:

| 变量 | 类型 | 说明 |
|------|------|------|
| day_view_json | string | 单日日程数据（JSON） |

**Prompt**:
```
你是EventLink商务助手的语音回答生成器。根据日程数据生成简洁自然的口语化中文回答。
此回答将通过TTS语音播报给用户(可能在开车)。

严格规则:
1. 回答控制在50字以内(约10秒TTS播放)
2. 使用口语化表达,不要书面语
3. 有会议:按时间顺序列出,包含时间和关键信息
4. 无会议:友好告知,可建议查看其他信息
5. 数字用汉字或口语化表达("2场"而不是"2","下午两点"而不是"14:00")
6. 不要markdown、不要列表符号、不要特殊格式
7. 手机号/金额等敏感信息自动模糊化

日程数据:
{day_view_json}

生成回答(纯文本):
```

**预期输出示例**:
- 有会议: `"您今天下午2点有场和张总的项目进度会,下午4点还有周会。一共2场。"`
- 无会议: `"您今天没有安排会议。需要看看待办事项吗?"`
- 多会议: `"今天挺忙的,一共有4场。上午10点见客户王总,下午..."`

---

## 18. 模板18：NLG - 承诺追踪回答生成 [F-50新增]

**用途**: 根据待办承诺数据生成口语化中文回答（车载场景）

**LLM**: moka/claude-sonnet-4-6

**输入变量**:

| 变量 | 类型 | 说明 |
|------|------|------|
| todos_json | string | 待办承诺数据（JSON） |

**Prompt**:
```
你是EventLink商务助手的语音回答生成器。根据待办承诺数据生成口语化中文回答。
用户可能在开车,回答要简洁清晰。

规则:
1. 40字以内
2. 有待办:按紧急程度排列,说清楚"答应谁"+"什么事"+"什么时候前完成"
3. 无待办:正面反馈("目前没有待处理的承诺,做得不错!")
4. 数量>3时只说最重要的3个,提示"还有X件可以看详情"
5. 口语化,自然

待办数据:
{todos_json}

生成回答(纯文本):
```

**预期输出示例**:
- 有待办: `"您有3件事还没做完。最急的是答应张总周五前发报价单,还有给李总的资料周三之前准备好。"`
- 无待办: `"太棒了!目前没有待处理的承诺。"`

---

## 19. 模板19：NLG - 关系状态回答生成 [F-50新增]

**用途**: 根据人物关系进展数据生成口语化回答（车载场景）

**LLM**: moka/claude-sonnet-4-6

**输入变量**:

| 变量 | 类型 | 说明 |
|------|------|------|
| relationship_brief_json | string | 人物关系进展简报数据（JSON） |

**Prompt**:
```
你是EventLink商务助手的语音回答生成器。根据人物关系进展数据生成口语化回答。

规则:
1. 45字以内
2. 说明当前阶段 + 最近一次互动时间 + 下一步建议
3. 如果该人物不存在于系统中,友好告知
4. 口语化表达

关系数据:
{relationship_brief_json}

生成回答(纯文本):
```

**预期输出示例**:
- 有进展: `"张总目前在价值回应阶段。上次联系是上周三,聊了项目合作的事。建议这周再跟进一下。"`
- 无记录: `"还没有张总的记录呢。要不要先录入一下?"`

---

## 20. 模板20：NLG - 范围日程回答生成 [F-50 Phase 1.2新增]

**用途**: 支持多日范围的日程概览生成（Phase 1.2多日查询）

**LLM**: moka/claude-sonnet-4-6

**输入变量**:

| 变量 | 类型 | 说明 |
|------|------|------|
| range_view_json | string | 多日范围日程数据（JSON） |

**Prompt**:
```
你是EventLink商务助手的语音回答生成器。根据多日范围日程数据生成口语化中文回答。
此回答将通过TTS语音播报给用户(可能在开车)。

规则:
1. 60字以内
2. 按天分组,每天一句话概括
3. 总天数>3时只说概览
4. 使用口语化表达,数字用汉字
5. 不要markdown、不要列表符号、不要特殊格式

范围日程数据:
{range_view_json}

生成回答(纯文本):
```

**预期输出示例**:
`"明后天您安排不多。明天下午3点有个电话会议,后天全天没安排。"`

---

## 21. 模板21：NLG - 行动建议回答生成 [F-50 Phase 1.2新增]

**用途**: 根据关系优先级数据生成行动建议（车载场景）

**LLM**: moka/claude-sonnet-4-6

**输入变量**:

| 变量 | 类型 | 说明 |
|------|------|------|
| suggestions_json | string | 关系优先级/行动建议数据（JSON） |

**Prompt**:
```
你是EventLink商务助手的语音回答生成器。根据关系优先级数据生成行动建议。
此回答将通过TTS语音播报给用户(可能在开车)。

规则:
1. 50字以内
2. 给出Top 2-3条建议,每条包含:谁 + 为什么 + 建议动作
3. 基于"先成就关系"的利他原则,不是索取
4. 不催促,语气温和
5. 口语化表达,不要markdown和列表符号

建议数据:
{suggestions_json}

生成回答(纯文本):
```

**预期输出示例**:
`"建议您今天联系一下陈总,上次他说想了解物流方案,可以主动分享一下资料。另外张总那边也一周没联系了。"`

---

## 22. 模板22：Concern/Capability提取 [0.3.0新增]

**用途**: 在实体提取阶段（Pipeline Step 5）为每个Person实体提取关注点（concerns）和能力（capabilities），用于Insight Engine动态评分和关系经营建议

**LLM**: moka/claude-sonnet-4-6

**输入变量**:

| 变量 | 类型 | 说明 |
|------|------|------|
| person_info | string | Person实体信息（姓名、公司、职位等） |
| context_text | string | 包含该人物信息的原始文本（对话/事件记录） |

**受控词表（tag字段）**:

| tag | 说明 | 典型场景 |
|-----|------|---------|
| 会议效率 | 会议相关痛点与需求 | 记不住会议决议、会议太多、跟进困难 |
| 资金需求 | 融资/投资/预算相关 | 正在融资、寻找投资机会、预算紧张 |
| 人才招聘 | 招人/团队建设相关 | 招聘困难、缺技术合伙人、团队扩张 |
| 技术选型 | 技术方案/架构决策 | AI落地选型、技术栈迁移、系统重构 |
| 市场拓展 | 市场推广/客户获取 | 开拓新市场、获客成本高、渠道建设 |
| 合作机会 | 合作/对接/资源互补 | 寻找合作伙伴、项目对接、渠道合作 |
| 产品优化 | 产品改进/用户体验 | 产品迭代、用户反馈、功能优化 |
| 运营管理 | 日常运营/流程优化 | 流程低效、管理困难、成本控制 |
| 政策合规 | 法规/合规/资质 | 行业监管、资质申请、合规要求 |
| 其他 | 不属于以上分类的长尾场景 | 量子计算应用、元宇宙探索等新兴领域 |

**Prompt**:
```
你是一个EventLink人物分析专家。请从以下文本中提取{person_name}的关注点（concerns）和能力（capabilities）。

定义：
- concerns（关注点）：此人关心什么、有什么痛点、有什么需求
- capabilities（能力）：此人能提供什么、有什么资源、有什么专长

规则：
1. 每个concern/capability必须包含tag和detail两个字段
2. tag必须使用以下受控词表之一（选择最匹配的）：
   会议效率 | 资金需求 | 人才招聘 | 技术选型 | 市场拓展 | 合作机会 | 产品优化 | 运营管理 | 政策合规 | 其他
3. 如果无法匹配任何受控词表项，使用"其他"
4. detail是自由文本，描述具体的关注点/能力，必须包含原文关键信息
5. 仅提取有明确文本依据的信息，不推测
6. 每个Person最多提取5个concerns和5个capabilities
7. 如果信息不足，返回空数组

输出语言规则：
1. 输出语言必须与输入语言一致
2. 推测必须标记
3. 禁止AI自动判定对方资源——仅引用原文

人物信息：
{person_info}

上下文文本：
{context_text}

输出JSON格式：
{{
  "person": "{person_name}",
  "concerns": [
    {{
      "tag": "受控词表之一",
      "detail": "具体关注点描述"
    }}
  ],
  "capabilities": [
    {{
      "tag": "受控词表之一",
      "detail": "具体能力描述"
    }}
  ],
  "is_ai_inference": true,
  "confidence_level": "confirmed|inferred|speculated",
  "requires_confirmation": false
}}
```

**输出示例**:
```json
{
  "person": "许总",
  "concerns": [
    {
      "tag": "会议效率",
      "detail": "记不住见客户时答应的方案和事，会后跟进困难"
    },
    {
      "tag": "人才招聘",
      "detail": "正在找AI算法工程师，招了两个月没找到合适的"
    }
  ],
  "capabilities": [
    {
      "tag": "合作机会",
      "detail": "公司有AI项目落地需求，可提供合作场景"
    },
    {
      "tag": "资金需求",
      "detail": "公司有预算采购AI解决方案"
    }
  ],
  "is_ai_inference": false,
  "confidence_level": "confirmed",
  "requires_confirmation": false
}
```

**输出示例（长尾场景）**:
```json
{
  "person": "王博士",
  "concerns": [
    {
      "tag": "其他",
      "detail": "想了解量子计算在金融的应用"
    }
  ],
  "capabilities": [
    {
      "tag": "技术选型",
      "detail": "量子计算算法研究5年经验，可提供技术评估"
    }
  ],
  "is_ai_inference": true,
  "confidence_level": "inferred",
  "requires_confirmation": true
}
```

---

## 23. 模板23：Event标题生成 [0.3.0新增]

**用途**: 在事件创建阶段（Pipeline Step 4）从raw_text自动生成简洁的Event标题，用于事件列表展示和快速识别

**LLM**: moka/claude-sonnet-4-6

**输入变量**:

| 变量 | 类型 | 说明 |
|------|------|------|
| raw_text | string | 事件原始文本（对话转写/会议纪要/手动输入） |
| event_type | string | 事件类型（card_save/meeting/call/manual） |

**Prompt**:
```
你是一个EventLink事件标题生成器。请根据以下事件原始文本生成一个简洁的标题。

规则：
1. 标题长度不超过20个字符
2. 聚焦交互类型和关键人物
3. 使用"与XX讨论/交流/沟通XX"的格式
4. 如果是微信聊天，使用"XX微信聊XX"格式
5. 如果是社区活动，使用"XX社区活动交流"格式
6. 省略细节，保留核心信息
7. 不使用标点符号（逗号/句号）
8. 输出纯文本，不要JSON格式

事件类型：{event_type}

原始文本：
{raw_text}

生成标题（纯文本，≤20字）：
```

**输出示例**:

| raw_text摘要 | 生成标题 |
|-------------|---------|
| 与许总讨论智能体在制造业的落地场景和方案 | 与许总讨论智能体落地 |
| 李总微信聊了工作痛点，说招人困难 | 李总微信聊工作痛点 |
| 王主任社区活动上交流了邻里服务经验 | 王主任社区活动交流 |
| 张总电话沟通了新项目合作意向 | 与张总电话沟通合作 |
| 和陈总开会讨论Q3预算分配方案 | 与陈总讨论预算方案 |

---

## 附录A：重试与降级策略

| 参数 | 值 | 说明 |
|------|---|------|
| 最大重试次数 | 3 | 超过3次返回错误 |
| 退避策略 | 指数退避 | 1s → 2s → 4s |
| 超时时间 | 30s | 单次请求超时 |
| 降级策略 | Provider切换 | Moka AI → 规则降级 |

```python
import asyncio
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=4),
    retry=retry_if_exception_type((LLMTimeoutError, LLMRateLimitError)),
)
async def call_with_retry(prompt: str, model: str = "moka/claude-sonnet-4-6") -> str:
    return await llm_client.call(prompt, model=model)
```

## 附录B：成本控制

| 参数 | 值 | 说明 |
|------|---|------|
| 单次请求Token上限 | 4000 | 防止过长prompt（v2.0提升以支持12模块填充） |
| 每日Token配额 | 10万 | 控制日成本 |
| 模型选择策略 | 统一使用Moka AI | moka/claude-sonnet-4-6 |
| 缓存策略 | 相同prompt缓存24h | 避免重复调用 |

## 附录C：F-50 语音助手 Prompt 架构说明 [0.2.1新增]

### Voice Pipeline Prompt调用链

```
用户语音 → ASR → [文字]
                    ↓
            ┌─ Stage 1: 规则匹配(无需LLM) ─┐
            │   命中(conf≥0.85)?           │
            │     Yes → 直接映射API         │
            │     No  ↓                    │
            └─→ Stage 2: LLM意图识别       │
                  (模板16: NLU Intent)      │
                  ↓                        │
            Query Orchestrator调用现有API    │
                  ↓                        │
            NLG回答生成                     │
            (模板17-21: 按意图选择)          │
                  ↓                        │
            TTS语音播报                     │
```

### Prompt选择路由表

| NLU意图 | 选择NLG模板 | 说明 |
|---------|------------|------|
| schedule_query | 模板17 (NLG-Schedule) | 单日日程 |
| schedule_range | 模板20 (NLG-RangeSchedule) | 多日日程 |
| promise_tracker | 模板18 (NLG-PromiseTracker) | 承诺追踪 |
| relationship_status | 模板19 (NLG-RelationshipStatus) | 关系状态 |
| action_suggestion | 模板21 (NLG-ActionSuggestion) | 行动建议 |
| unclear | 固定模板(无需LLM) | "我不太确定您的意思..." |
| todo_create | 固定模板(Phase 1.2) | "好的,已帮您记下..." |

### F-50模板设计原则

| 原则 | NLU(模板16) | NLG(模板17-21) |
|------|-------------|---------------|
| 安全性 | temperature=0.1, max_tokens=150, JSON-only | 敏感信息自动模糊化 |
| 车载友好 | — | ≤50字, 口语化, 无markdown |
| 延迟控制 | 单次≤150 tokens | 单次输出纯文本短句 |
| 降级策略 | 规则引擎conf≥0.85时跳过LLM | unclear/todo_create走固定模板 |

---

## 附录D：LLM错误类型

| 异常类 | 继承 | 说明 |
|--------|------|------|
| `LLMError` | `Exception` | LLM调用基础异常 |
| `LLMTimeoutError` | `LLMError` | 请求超时 |
| `LLMRateLimitError` | `LLMError` | 速率限制 |
| `LLMQuotaExceeded` | `LLMError` | 配额耗尽 |
| `LLMResponseParseError` | `LLMError` | 响应解析失败 |

---

## 版本历史

| 版本 | 日期 | 变更内容 |
|------|------|---------|
| 0.2.0 | 2026-06-04 | 初始版本,包含模板0-14共15个模板 |
| 0.2.1 | 2026-06-05 | [F-50新增]模板16(NLU意图识别)+模板17-21(NLG回答生成)共6个模板;新增附录C(F-50架构说明);原附录C重编号为附录D;模板总数15→21 |
| 0.3.0 | 2026-06-06 | [Insight Engine新增]模板22(Concern/Capability提取,受控词表+自由文本)+模板23(Event标题生成,≤20字);模型选择策略表新增2行;模板总数21→23 |
| 0.3.1 | 2026-06-06 | F-55(依赖性全图谱路径分析)/F-56(场景匹配Event表驱动)为纯算法实现，无新增LLM模板 |
