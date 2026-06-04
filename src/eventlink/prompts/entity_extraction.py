"""Entity extraction prompt templates."""

TEMPLATE_1_CARD_EXTRACTION = """你是一个商务名片信息提取专家。请从以下OCR识别的文本中提取结构化信息。

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
}}"""

TEMPLATE_2_CONVERSATION_EXTRACTION = """你是一个商务对话分析专家。请从以下对话转写文本中提取关键信息。

规则：
1. 人物：提取所有提及的人物，包括说话人和被提及的人
2. 事件：提取讨论的事件/会议/项目
3. 资源识别：识别每个人物拥有的核心资源（能力、人脉、渠道）
4. 需求识别：识别每个人物表达的需求
5. 关键词：提取业务相关词汇
6. 如果信息不足以判断，对应字段设为null

虚拟角色过滤规则（重要）：
- 仅提取真实存在的人物，不要提取角色名或虚拟身份
- 角色名示例：PM、架构师、产品经理、设计师、开发、测试、运营等——这些是职能描述，不是具体人物
- 判断标准：如果一个人名只在讨论框架/分析视角/组织架构描述中出现，而非作为实际参会者或被明确提及的真实人物，则不应提取
- 例如："PM建议..."中的"PM"不提取；但"许总（PM）说..."中的"许总"应提取
- 例如："架构师负责设计"不提取；但"李总作为架构师提出了..."中的"李总"应提取

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
}}"""
