# EventLink LLM Prompt模板库

> **版本**: v1.2
> **最后更新**: 2026-06-03
> **来源**: Integration_Design_v1.md §3.2-3.6 提取
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
    model="gpt-3.5-turbo",
    temperature=0.3,
)
```

### 模型选择策略

| 模板 | 推荐模型 | 原因 |
|------|---------|------|
| 模板1 名片提取 | gpt-3.5-turbo | 结构化提取，简单任务 |
| 模板2 语音实体抽取 | gpt-4 | 需要理解上下文 |
| 模板3 Todo生成 | gpt-4 | 需要理解6种类型策略 |
| 模板4 商机优化 | gpt-3.5-turbo | 文本优化，中等任务 |
| 模板5 实体归一 | gpt-4 | 需要推理判断 |
| 模板6 关系发现 | gpt-4 | 需要综合分析 |
| 模板7 资源识别 | gpt-4 | 需要深度理解 |
| 模板8 需求提取 | gpt-4 | 需要深度理解 |
| 模板9 敏感度判断 | gpt-4 | 需要安全判断 |
| 模板10 关系维护 | gpt-3.5-turbo | 基于规则+模板生成 |
| 模板11 承诺提取 | gpt-4 | 需要理解承诺语义 |
| 模板12 关注点提取 | gpt-4 | 需要理解关注意图 |

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

**用途**: 从语音转写文本中提取人物实体、事件和资源信息

**输入变量**:

| 变量 | 类型 | 说明 |
|------|------|------|
| transcript | string | ASR转写的对话文本 |
| language | string | 语言代码（zh-CN/en-US） |

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
      "demand": ["此人表达的需求"]
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
      "demand": ["寻找AI赛道优质项目（来源：对话原文）"]
    },
    {
      "name": "王明",
      "company": null,
      "title": null,
      "resource": ["推荐了3个AI项目（来源：对话原文）"],
      "demand": []
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

## 3. 模板3：Todo生成（含todo_type）

**用途**: 根据对话内容和上下文生成待办事项，必须指定todo_type

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

**Prompt**:
```
你是一个个人商务关系经营助手。请根据以下信息生成一条待办事项。

Todo类型：{todo_type}
- promise（承诺）：提取"我答应过什么"，给出兑现承诺的行动步骤和截止时间
- help（帮助）：建议"我能为他做什么"，基于对方需求给出可执行的援助方案
- care（关注）：提取"对方正在关心什么"，标记对方关注点以便跟进
- followup（跟进）：标记需跟进的事项，列出待确认点和下一步行动
- cooperation_signal（合作信号）：识别合作信号，发现资源互补和合作可能
- risk（风险）：识别潜在风险，给出预警和规避措施

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

输出语言规则：
1. 输出语言必须与输入语言一致
2. 禁止建议索取资源
3. 禁止自动撮合
4. 推测必须标记

输出JSON格式：
{{
  "todo_type": "{todo_type}",
  "description": "Todo描述",
  "priority": "high|medium|low",
  "due_date_suggestion": "建议截止时间（ISO 8601）",
  "context": {{
    "reason": "生成原因",
    "suggested_action": "建议行动",
    "related_entities": ["相关人物名"]
  }},
  "is_ai_inference": true,
  "confidence_level": "confirmed|inferred|speculated",
  "requires_confirmation": false
}}
```

**输出示例（cooperation_signal类型）**:
```json
{
  "todo_type": "cooperation_signal",
  "description": "⚪ 合作信号：李总寻找AI项目，王明有3个推荐项目可对接",
  "priority": "high",
  "due_date_suggestion": "2026-06-06T00:00:00Z",
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
  "description": "🟢 帮助：张总最近在关注AI大模型落地，你可以分享相关案例",
  "priority": "medium",
  "due_date_suggestion": "2026-06-08T00:00:00Z",
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

## 附录A：重试与降级策略

| 参数 | 值 | 说明 |
|------|---|------|
| 最大重试次数 | 3 | 超过3次返回错误 |
| 退避策略 | 指数退避 | 1s → 2s → 4s |
| 超时时间 | 30s | 单次请求超时 |
| 降级策略 | Provider切换 | OpenAI → Claude → 通义千问 → 规则降级 |

```python
import asyncio
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=4),
    retry=retry_if_exception_type((LLMTimeoutError, LLMRateLimitError)),
)
async def call_with_retry(prompt: str, model: str = "gpt-4") -> str:
    return await llm_client.call(prompt, model=model)
```

## 附录B：成本控制

| 参数 | 值 | 说明 |
|------|---|------|
| 单次请求Token上限 | 2000 | 防止过长prompt |
| 每日Token配额 | 10万 | 控制日成本 |
| 模型选择策略 | 按场景选模型 | 简单提取用gpt-3.5，复杂推理用gpt-4 |
| 缓存策略 | 相同prompt缓存24h | 避免重复调用 |

## 附录C：LLM错误类型

| 异常类 | 继承 | 说明 |
|--------|------|------|
| `LLMError` | `Exception` | LLM调用基础异常 |
| `LLMTimeoutError` | `LLMError` | 请求超时 |
| `LLMRateLimitError` | `LLMError` | 速率限制 |
| `LLMQuotaExceeded` | `LLMError` | 配额耗尽 |
| `LLMResponseParseError` | `LLMError` | 响应解析失败 |
