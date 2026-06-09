"""Todo generation prompt templates."""

TEMPLATE_3_TODO_GENERATION = """你是一个个人商务关系经营助手。请根据以下信息生成一条待办事项。

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
}}"""

TEMPLATE_11_PROMISE_EXTRACTION = """你是一个个人商务关系经营助手。请从以下交流内容中提取"我答应过什么"——即用户自己做出的承诺。

规则：
1. 仅提取用户（第一人称）做出的承诺，不提取对方的承诺
2. 承诺包括：答应做的事、答应提供的资源、答应的见面/通话、答应的介绍/推荐
3. 每个承诺必须包含：对谁承诺、承诺了什么
4. 如果承诺有明确时间，提取时间；如果没有，建议一个合理的截止时间
5. 不推测，仅提取有明确文本依据的承诺
6. 如果没有发现承诺，返回空数组
7. 注意识别隐性承诺关键词：承诺、答应、保证、会、将、一定、没问题、包在我身上、放心、回头我、之后我、下周我、尽快、马上

示例1：
交流内容："我跟张总说了下周三之前把方案发给他，还答应帮他引荐一下李总。"
输出：
```json
{{"promises": [{{"to_person": "张总", "content": "下周三之前把方案发给他", "mentioned_deadline": "下周三", "suggested_deadline": null, "priority": "high", "source_text": "下周三之前把方案发给他"}}, {{"to_person": "张总", "content": "帮他引荐李总", "mentioned_deadline": null, "suggested_deadline": null, "priority": "medium", "source_text": "答应帮他引荐一下李总"}}], "summary": "对张总承诺发方案和引荐李总", "is_ai_inference": false, "confidence_level": "confirmed", "requires_confirmation": false}}
```

示例2：
交流内容："王总说他那边没问题，让我们放心。"
输出：
```json
{{"promises": [], "summary": "未发现用户自身承诺", "is_ai_inference": false, "confidence_level": "confirmed", "requires_confirmation": false}}
```

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
}}"""

TEMPLATE_12_CARE_EXTRACTION = """你是一个个人商务关系经营助手。请从以下交流内容中提取"对方正在关心什么"——即交流对象关注的议题和痛点。

规则：
1. 仅提取对方（非用户本人）表达的关注点
2. 关注点包括：正在解决的问题、正在考虑的方案、正在寻找的资源、表达过的担忧
3. 每个关注点必须包含：谁在关注、关注什么
4. 标注关注点的紧迫程度
5. 不推测，仅提取有明确文本依据的关注点
6. 如果没有发现关注点，返回空数组
7. 注意识别隐性关注信号：担心、焦虑、急需、正在找、希望、考虑、纠结、犹豫、头疼、困扰

示例1：
交流内容："李总说他最近在找新的供应商，现有供应商交期不稳定，很头疼。他还提到公司明年要扩展东南亚市场。"
输出：
```json
{{"cares": [{{"person": "李总", "topic": "供应商交期问题", "detail": "现有供应商交期不稳定，正在寻找新供应商", "urgency": "high", "source_text": "最近在找新的供应商，现有供应商交期不稳定，很头疼"}}, {{"person": "李总", "topic": "东南亚市场扩展", "detail": "公司明年计划扩展东南亚市场", "urgency": "medium", "source_text": "公司明年要扩展东南亚市场"}}], "summary": "李总关注供应商和海外市场", "is_ai_inference": false, "confidence_level": "confirmed", "requires_confirmation": false}}
```

示例2：
交流内容："我跟赵总介绍了我们的方案，他觉得不错，说回头研究一下。"
输出：
```json
{{"cares": [{{"person": "赵总", "topic": "方案评估", "detail": "对我们的方案感兴趣，需要时间研究", "urgency": "low", "source_text": "他觉得不错，说回头研究一下"}}], "summary": "赵总关注方案评估", "is_ai_inference": false, "confidence_level": "confirmed", "requires_confirmation": false}}
```

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
}}"""
