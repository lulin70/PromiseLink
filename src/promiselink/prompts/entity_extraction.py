"""Entity extraction prompt templates.

受控词表（concern/capability）通过 format 注入，唯一事实源在
promiselink.core.contract（W1 语义契约：词表变更会改变契约哈希）。
"""

from promiselink.core.contract import CAPABILITY_TERMS, CONCERN_TERMS

_CONCERN_STR = "、".join(CONCERN_TERMS)
_CAPABILITY_STR = "、".join(CAPABILITY_TERMS)

TEMPLATE_1_CARD_EXTRACTION = """你是一个商务名片信息提取专家。请从以下OCR识别的文本中提取结构化信息。

规则：
1. 如果某个字段无法识别，设为null
2. 电话号码统一格式：保留原始格式
3. resource字段：从职位/公司推断此人的核心能力和资源
4. demand字段：从公司业务方向推断此人可能的需求
5. 如果无法推断resource/demand，设为空数组
6. concern字段：从此人的职位/行业/公司业务推断此人当前最关注的业务问题或挑战（受控词表+自由文本）
7. capability字段：从此人的职位/公司推断此人的核心专业能力（受控词表+自由文本）
8. concern受控词表：{concern_terms}
9. capability受控词表：{capability_terms}
10. 如果无法推断concern/capability，设为空数组

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
  "concern": [{{"category": "融资", "detail": "正在寻求A轮融资"}}],
  "capability": [{{"category": "投资决策", "detail": "专注早期科技投资"}}],
  "industry": "行业",
  "confidence": 0.95,
  "is_ai_inference": true,
  "confidence_level": "confirmed|inferred|speculated",
  "requires_confirmation": false
}}"""

TEMPLATE_2_CONVERSATION_EXTRACTION = """你是一个商务交流信息提取专家。请从以下交流记录文本中提取关键信息。

输入格式说明（重要）：
- 输入可能是【对话转写】（如"李总说：...张总说：..."），也可能是【结构化纪要】（如"参会人：李总、张总""议题：...""决议：..."）
- 请自适应识别输入格式，并采用对应的提取策略

规则：
1. 人物：提取所有提及的真实人物
   - 对话转写：提取说话人和被提及的人
   - 结构化纪要：从"参会人""出席""与会""参与人""汇报人""主持人"等字段中识别人物，也从纪要正文提及中识别人物
2. 事件：提取讨论的事件/会议/项目
3. 资源识别：识别每个人物拥有的核心资源（能力、人脉、渠道）
4. 需求识别：识别每个人物表达的需求
5. 关键词：提取业务相关词汇
6. 结构化推断（重要）：
   - 当提到公司名称时，请推断该公司所在城市（如可确定）
   - 当提到公司或业务时，请推断所属行业（如可确定）
   - 当人物背景涉及教育经历时，提取毕业院校
   - 当讨论技术产品/方案时，提取相关技术栈关键词
   - 当人物职业经历被提及时，提取过往工作单位
7. 如果信息不足以判断，对应字段设为null
8. concern识别：识别每个人物当前最关注的业务问题或挑战
9. capability识别：识别每个人物的核心专业能力
10. concern受控词表：{concern_terms}
11. capability受控词表：{capability_terms}

虚拟角色过滤规则（重要）：
- 仅提取真实存在的人物，不要提取角色名或虚拟身份
- 角色名示例：PM、架构师、产品经理、设计师、开发、测试、运营等——这些是职能描述，不是具体人物
- 第一人称代词（"我"、"我们"）是记录者本人，不是需要提取的外部人物，严禁提取
- 判断标准：如果一个人名只在讨论框架/分析视角/组织架构描述中出现，而非作为实际参会者或被明确提及的真实人物，则不应提取
- 例如："PM建议..."中的"PM"不提取；但"许总（PM）说..."中的"许总"应提取
- 例如："架构师负责设计"不提取；但"李总作为架构师提出了..."中的"李总"应提取
- 例如："我答应张总..."中的"我"不提取；"张总说我可以..."中的"我"也不提取

输出语言规则：
1. 输出语言必须与输入语言一致
2. 推测内容必须标注（来源：原文引用）
3. 禁止对他人资源做确定性判断
4. 禁止建议索取资源

交流记录文本（{language}）：
{transcript}

输出JSON格式：
{{
  "persons": [
    {{
      "name": "姓名",
      "company": "公司（如提及）",
      "title": "职位（如提及）",
      "city": "公司所在城市（根据公司名推断，如无法确定则null）",
      "industry": "行业（根据公司业务推断，如无法确定则null）",
      "schools": ["毕业院校（如提及或可推断）"],
      "tech_stack": ["相关技术栈（从讨论的技术内容中提取）"],
      "work_history": ["过往工作单位（如提及）"],
      "resource": ["此人的能力/人脉/渠道"],
      "demand": ["此人表达的需求"],
      "concern": [{{"category": "融资", "detail": "..."}}],
      "capability": [{{"category": "投资决策", "detail": "..."}}]
    }}
  ],
  "events": [
    {{
      "name": "事件名称",
      "time": "时间（如提及）",
      "location": "地点（如提及）",
      "topic": "主题（本次交流的核心话题/领域）"
    }}
  ],
  "keywords": ["关键词1", "关键词2"],
  "summary": "对话摘要（50字以内）",
  "is_ai_inference": true,
  "confidence_level": "confirmed|inferred|speculated",
  "requires_confirmation": false
}}"""
