#!/usr/bin/env python3
"""
EventLink PRD v4.3 + 技术设计 v2.4 二轮验证性Review
使用 DevSquad 7角色全员 + 真实 Moka AI 后端
"""

import os
import sys
import json

# 添加 DevSquad 到路径
sys.path.insert(0, '../.trae/skills/devsquad')

from scripts.collaboration.dispatcher import MultiAgentDispatcher
from scripts.collaboration.llm_backend import create_backend

# ============================================================
# Moka AI 后端配置（真实LLM）
# ============================================================
MOKA_API_KEY = "sk-GWSmGaP4XYK3YDWi80gGZTtae8eb7id1mgCAYDdvDgoFpUzX"
MOKA_BASE_URL = "https://api.moka-ai.com/v1"
MOKA_MODEL = "moka/claude-sonnet-4-6"

# ============================================================
# Review 任务描述（二轮验证性Review）
# ============================================================
TASK_DESCRIPTION = """
## 任务：EventLink PRD v4.3 + 技术设计 v2.4 — 7角色全员二轮验证性Review

### 背景
EventLink项目已完成文档三轮迭代：
1. 第一轮：李总v1.2建议 → PM+Arch评审 → PRD v4.2 + 技术设计v2.2
2. 第二轮：7角色全员一轮Review → 发现2项P0阻塞(BLK-1/BLK-2) + 多项改进建议
3. 第三轮：PRD v4.2→v4.3 + 技术设计v2.3→v2.4（修复BLK问题+融入许总反馈+采纳7角色意见）

### 本轮性质
**验证性Review**（非发现性Review）。重点验证以下内容是否已在v4.3/v2.4中正确修复和实现：

#### 一、验证P0阻塞问题是否已修复

**BLK-1: evidence_quote PII脱敏策略**
- 一轮发现：evidence_quote字段存储原始对话片段，可能含PII，无脱敏策略
- 需验证：PRD和技术设计中是否已定义完整的PII脱敏流程？
- 检查点：sanitize_llm_input()清洗、redact_pii_from_text()函数、不建全文索引、API返回前脱敏

**BLK-2: input_scope服务端强制校验**
- 一轮发现：API允许客户端传入input_scope覆盖自动分类结果，存在越权风险
- 需验证：技术设计Step 0是否增加了SC-01安全约束？
- 检查点：永远以服务端classify()为准、非法值返回400、客户端值仅作hint

**BLK-3: action_type枚举统一**
- 一轮发现：PRD中5种与技术设计中6种不一致
- 需验证：是否已统一为6种(my_promise/their_promise/my_followup/mutual_action/system_reminder/unclear)？

#### 二、验证许总POC反馈是否已融入

**F-49 日视图功能**
- 许总需求："一天4波或6波会议的主题在同一天可以分别显示"
- 需验证：F-49功能定义是否存在且完整？API端点是否已定义？

**主题互通语言包装**
- 许总需求："主题间是可以互通且可以无限扩展"
- 需验证：F-04关联发现引擎是否已增加"主题互通"用户视角语言？

**终身智能体助手愿景**
- 许总需求："成为终身智能体助手"
- 需验证：产品愿景章节是否已强化"终身"属性？CarryMem记忆层支撑是否已描述？

**TTS/ASR语音交互**
- 许总需求："除了文字可以语音互动"
- 需验证：技术设计中是否有ASR/TTS技术路径规划？PoC Mock方案？

#### 三、验证7角色意见是否已采纳

| 意见来源 | 具体意见 | 验证要点 |
|---------|---------|---------|
| PM | 测试方法学文档计划 | PoC退出条件是否有测试方法学表？ |
| DevOps | 监控指标定义 | 是否新增P0业务指标？ |
| UI | 展示优先级 | F-47推进卡12模块是否有优先级分级？ |
| Arch | evidence_event_id字段 | todos表是否新增该外键字段？ |
| Arch | PATCH乐观锁 | RelationshipBrief阶段变更API是否有乐观锁？ |

#### 四、检查新引入的不一致

- PRD v4.3与技术设计v2.4之间的一致性
- 新增内容与现有内容的风格一致性
- 版本号/日期/变更记录的准确性

### 输入材料位置
1. PRD v4.3: ./docs/spec/PRD_V1.md
2. 技术设计v2.4: ./docs/architecture/EventLink_技术设计_v1.md
3. 一轮Review报告: ./docs/internal/EventLink_v4.2_v2.3_7角色全员Review报告.md
4. 许总反馈: ./docs/external/for_许总/20260604_许总POC反馈_符合想象_四点确认.md

### 输出要求
每个角色必须给出：
1. **总体判定**：✅ 全部通过 / ⚠️ 有遗留项 / ❌ 有新问题
2. **逐项验证**：对上述每个BLK项/许总反馈/7角色意见给出：**已修复/已融入/已采纳** + 具体证据引用
3. **新问题**：如有新发现的不一致或遗漏，明确列出
4. **最终建议**：是否可以进入实施阶段
"""


def main():
    print("=" * 80)
    print("EventLink v4.3+v2.4 二轮验证性Review - DevSquad 7角色全员")
    print("=" * 80)
    print(f"后端: {MOKA_BASE_URL}")
    print(f"模型: {MOKA_MODEL}")
    print(f"模式: consensus (共识投票)")
    print(f"角色: 7个全角色 (PM/Arch/Sec/Tester/Coder/DevOps/UI)")
    print("-" * 80)

    # 创建真实后端
    print("\n[1/4] 初始化 Moka AI 后端...")
    backend = create_backend(
        "openai",  # 使用 OpenAI 兼容接口
        api_key=MOKA_API_KEY,
        base_url=MOKA_BASE_URL,
        model=MOKA_MODEL,
    )
    
    # 测试连接
    try:
        test_result = backend.generate("Reply with only: OK", max_tokens=5)
        print(f"      后端连接成功! 测试响应: {test_result.strip()}")
    except Exception as e:
        print(f"      ⚠️ 后端测试警告: {e}")
        print("      继续执行...")

    # 创建 Dispatcher
    print("\n[2/4] 初始化 DevSquad MultiAgentDispatcher...")
    import tempfile
    work_dir = tempfile.mkdtemp(prefix="eventlink_review_v2_")
    
    disp = MultiAgentDispatcher(
        llm_backend=backend,
        persist_dir=work_dir,
        enable_warmup=True,
        enable_compression=True,
        enable_permission=True,
        enable_memory=True,
    )

    # 7个全角色
    roles = [
        "product-manager",
        "architect",
        "security",
        "tester",
        "solo-coder",
        "devops",
        "ui-designer",
    ]

    print(f"\n[3/4] 执行二轮验证性Review (consensus模式, 超时300秒)...")
    print(f"      角色: {', '.join([r.split('-')[0] for r in roles])}")

    result = disp.dispatch(
        task_description=TASK_DESCRIPTION,
        roles=roles,
        mode="consensus",  # 共识模式
        dry_run=False,
    )

    # 输出结果
    print("\n[4/4] Review 完成!")
    print("=" * 80)
    
    if result.success:
        print(f"✅ Review 成功完成!")
        print(f"   耗时: {result.duration_seconds:.2f}秒")
        print(f"   参与角色: {result.matched_roles}")
    else:
        print(f"⚠️ Review 完成但有警告")
        if result.errors:
            for err in result.errors:
                print(f"   错误: {err}")

    # 生成Markdown报告
    report = result.to_markdown()
    
    # 保存报告
    output_path = "./docs/internal/EventLink_v4.3_v2.4_二轮Review_最终报告.md"
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(report)
    
    print(f"\n📄 报告已保存到: {output_path}")
    
    # 打印摘要
    print("\n" + "=" * 80)
    print("摘要 (Summary)")
    print("=" * 80)
    print(result.summary[:2000] if len(result.summary) > 2000 else result.summary)

    # 清理
    disp.shutdown()
    
    return result


if __name__ == "__main__":
    main()
