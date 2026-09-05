"""Synthetic name pool for golden test cases (PII red line).

All person/company names in golden cases MUST come from this pool —
real-user PII must never enter git (PRD §6).
"""

# 虚构人名（两字/三字组合，非真实公众人物）
SYNTHETIC_PERSON_NAMES: list[str] = [
    "陈子昂", "林晚秋", "周慕云", "许静之", "沈书白", "顾清和", "叶望舒",
    "陆知行", "苏念真", "程既明", "孟繁星", "贺疏桐", "温故", "费晚棠",
    "秦望山", "冯至远", "方念北", "崔颢然", "凌未寒", "纪春生",
]

# 虚构公司名
SYNTHETIC_COMPANY_NAMES: list[str] = [
    "远山资本", "青梧科技", "临江制造", "望津物流", "栖云数据",
    "南山新材", "百川智能", "星野传媒", "澄海生物", "韶光能源",
]

# 虚构学校名
SYNTHETIC_SCHOOL_NAMES: list[str] = [
    "江南理工大学", "临海大学", "望江交通大学", "南岭科技大学",
]
