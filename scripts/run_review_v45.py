#!/usr/bin/env python3
"""DevSquad review: PRD v4.5 + Tech Design v2.6 consistency check."""

import os
import sys

# Add DevSquad to path
sys.path.insert(0, os.path.expanduser("~/trae_projects/OPC-Agents"))

from scripts.collaboration.dispatcher import MultiAgentDispatcher
from scripts.collaboration.llm_backend import create_backend

# Use Moka AI backend
api_key = os.environ.get("MOKA_API_KEY", "")
if not api_key:
    print("ERROR: MOKA_API_KEY not set")
    sys.exit(1)

backend = create_backend(
    "openai",
    api_key=api_key,
    base_url="https://api.moka-ai.com/v1",
    model="moka/claude-sonnet-4-6",
)

disp = MultiAgentDispatcher(llm_backend=backend)

task = """审核EventLink项目PRD v4.5和技术设计v2.6的更新内容，判断哪些关联文档需要同步修改。

## 更新背景
基于与DeepSeek的架构讨论，EventLink从被动记录升级为主动服务，核心更新包括：

1. PRD v4.5新增：
   - 1.7智能定义与边界（理解/记忆/预见三层能力）
   - 1.7.4 Person实体concern/capability强化提取
   - 1.7.5 动态优先级排序模型（二维到四维演进）
   - 1.7.6 隐式反馈学习机制
   - 5.17数据接入层架构（DataSourceAdapter接口）

2. 技术设计v2.6新增：
   - Insight Engine服务（动态评分/隐式反馈/优先级排序）
   - 4.10洞察引擎设计（PriorityScorer+ImplicitFeedbackCollector）
   - 4.11数据接入层设计
   - Todo模型新增completed_rank/dynamic_score/score_calculated_at

3. PROJECT_STATUS新增：
   - 2.5智能演进路线图
   - F-51到F-54功能矩阵

## 需要审核的内容
1. PRD v4.5和技术设计v2.6的一致性检查
2. 哪些关联文档需要同步修改，按优先级排序：
   - API_Design_v1.md (v2.0)
   - Database_Design_v1.md (v2.0)
   - Algorithm_Design_v1.md (v2.0)
   - Security_Design_v1.md (v2.0)
   - Test_Plan_v1.md (v2.0)
   - UI_UX_Design_v1.md (v1.2)
   - Integration_Design_v1.md (v2.0)
   - Deployment_Guide.md (0.2.0)
   - LLM_Prompt_Templates.md (0.2.0)
3. 每个文档需要修改的具体内容

请各角色从自己的专业视角审核，给出具体的修改建议。
"""

result = disp.dispatch(
    task_description=task,
    roles=["architect", "product-manager", "security", "tester"],
    mode="parallel",
)

print(result.to_markdown())
disp.shutdown()
