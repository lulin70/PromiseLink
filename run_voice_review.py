#!/usr/bin/env python3
"""
EventLink 许总语音交互场景 — DevSquad PM + Arch 双角色评审
使用真实 Moka AI 后端，consensus 模式
"""

import sys
import os
import tempfile

# Add DevSquad to path
sys.path.insert(0, "../DevSquad")
sys.path.insert(0, "../DevSquad/scripts")

from scripts.collaboration.dispatcher import MultiAgentDispatcher
from scripts.collaboration.llm_backend import create_backend

# ============================================================
# 评审任务描述（完整上下文）
# ============================================================

TASK_DESCRIPTION = """
## 任务：EventLink 许总语音交互场景 — PM + Arch 双角色评审

### 背景说明
EventLink 是一个 AI 驱动的个人商务关系经营助手。许总作为种子用户，提出了语音交互的核心诉求。

### 许总语音场景原文（核心）

**核心流程**：
许总打开小程序 → 语音问："我今天的会议是什么" → 小程序说"请稍等，我去看一下" → 系统解析意图 → 调用Event API返回文字信息 → 小程序TTS语音回答许总

**7类典型问询**：

| # | 问询类型 | 示例语句 | 对应现有能力 | 复杂度 |
|---|---------|---------|------------|--------|
| 1 | 日程查询 | "我今天的会议是什么？" | 日视图API F-49 + events按日期筛选 | 低 |
| 2 | 日程查询 | "我明后天有什么安排？" | 日视图F-49 + 日期范围查询 | 低 |
| 3 | 交流回顾 | "上周和陈总我们聊了些什么主题？" | entities(陈总) + events关联 + LLM摘要 | 中 |
| 4 | 知识检索 | "上个月关于物流这一块我有了什么新知识？" | entities(物流) + todos(contribution) + 知识聚合 | 中高 |
| 5 | 承诺追踪 | "我答应老王什么事还没做？" | todos(my_promise, status=pending) | 低 |
| 6 | 关系推进 | "张总到哪步了？" | relationship_briefs + stage | 中 |
| 7 | 行动建议 | "今天我应该主动联系谁？" | 排序 + 待回应承诺 | 中 |

**关键交互特征**：
1. 自然语言输入：不是固定命令，是口语化中文问询
2. 中间态反馈："请稍等，我去看一下"
3. TTS语音输出回答（许总有视力障碍+车载场景）
4. 多轮对话潜力：追问具体时间/设提醒
5. 隐私敏感：公共场合可能不方便

### 现有文档基线

**PRD v4.3** 相关条目：
- F-49 日视图（日程查询基础）— Phase 1 P0
- F-47 RelationshipBrief（关系阶段查询）— Phase 1 P0
- F-44 input_scope分类器（可扩展为NLU基础）— PoC已完成
- TTS/ASR Phase 1规划（Integration_Design §5.5, Deployment_Guide §8）
- F-10 语音录入 — Phase 1 P0（许总确认为刚需）
- F-41 TTS播报 — Phase 1 P0（许总确认为刚需）
- Slogan："让每一次连接，都有回应"

**技术设计 v2.5** 已有内容：
- LLM provider: Moka AI (moka/claude-sonnet-4-6)
- ASR方案：微信同声传译插件 / Whisper local
- TTS方案：预合成MP3 / Azure Edge-TTS
- Pipeline: Event → EntityExtractor → TodoGenerator → Store

**已有API端点**：
- GET /api/v1/dashboard/day-view (F-49 日视图)
- GET /api/v1/persons/{id}/relationship-brief (F-47 关系推进卡)
- GET /api/v1/todos?view=my-responses (待回应任务)
- GET /api/v1/entities (实体搜索)
- POST /api/v1/mini/voice-input (语音录入)
- GET /api/v1/mini/person/{id}/tts (TTS播报)

### 需要新增的能力（当前缺口）

| 能力 | 缺口描述 | 工作量预估 |
|------|---------|-----------|
| NLU意图解析引擎 | 从自然语言问询→结构化API调用（非关键词匹配） | 大 |
| 多轮对话状态管理 | 追问上下文保持、会话超时、话题切换 | 中 |
| Answer Generation | 结构化数据→自然语言回答（非模板化） | 中 |
| TTS流式/分段播报 | 长答案分段播放、暂停/继续/重播控制 | 中 |
| 语音UI交互范式 | 唤醒方式、错误恢复("没听清，请再说一次")、无障碍优化 | 中 |

---

## 评审要求

请 **产品经理(PM)** 和 **架构师(Architect)** 分别从各自角度深入分析，然后达成共识。

### 产品经理必须回答的5个问题：

1. **需求定位**：这个语音场景是PoC增强、Phase 1核心、还是Phase 2？为什么？
2. **用户价值**：相比纯文字UI，语音给许总（及类似用户）带来什么不可替代的价值？
3. **优先级排序**：7类问询中哪些是MVP必须支持的？哪些可以后续迭代？
4. **PRD影响**：是否需要新增功能编号（如F-50 Voice Assistant）？对现有F-44~F-49有什么补充？
5. **边界界定**：语音助手的能力边界在哪里？（能做什么/不能做什么）

### 架构师必须回答的5个问题：

1. **架构影响**：需要在现有Pipeline之外新增Voice Pipeline吗？（ASR→NLU→API Query→NLG→TTS）
2. **NLU方案选型**：规则引擎 vs LLM-based intent detection？各优劣？
3. **新增组件清单**：需要新建哪些模块/服务？复用哪些现有组件？
4. **对各设计文档的具体影响**：
   - API_Design：需要新增什么端点？（如 POST /voice/query）
   - Algorithm_Design：NLU算法章节的范围
   - Integration_Design：ASR/TTS集成的细化程度
   - Database_Design：是否需要新表？（会话表/查询日志）
   - Deployment_Guide：是否有新的部署依赖？
5. **风险评估**：技术风险（ASR准确率/NLU延迟/TTS成本）、缓解措施

### 输出格式要求：

1. 双方先各自独立分析
2. 然后列出共识点和分歧点
3. 最终给出对每份文档的具体变更建议
4. 给出优先级建议和下一步行动项
5. 输出完整 Markdown 格式报告
"""


def main():
    print("=" * 70)
    print("EventLink 许总语音交互场景 — DevSquad PM+Arch 双角色评审")
    print("=" * 70)

    # 创建真实Moka AI后端
    backend = create_backend(
        "openai",
        api_key="sk-GWSmGaP4XYK3YDWi80gGZTtae8eb7id1mgCAYDdvDgoFpUzX",
        base_url="https://api.moka-ai.com/v1",
        model="moka/claude-sonnet-4-6",
    )

    # 创建临时工作目录
    work_dir = tempfile.mkdtemp(prefix="eventlink_voice_review_")

    # 创建 Dispatcher
    disp = MultiAgentDispatcher(
        llm_backend=backend,
        persist_dir=work_dir,
        enable_compression=True,
        enable_permission=True,
    )

    print(f"\n[INFO] 工作目录: {work_dir}")
    print("[INFO] 使用真实 Moka AI 后端 (moka/claude-sonnet-4-6)")
    print("[INFO] 角色: product-manager + architect")
    print("[INFO] 模式: consensus (共识模式)")
    print("\n" + "-" * 70)
    print("开始执行评审...")
    print("-" * 70 + "\n")

    try:
        # 执行共识模式评审
        result = disp.dispatch(
            task_description=TASK_DESCRIPTION,
            roles=["product-manager", "architect"],
            mode="consensus",
            dry_run=False,
        )

        # 输出结果
        if result.success:
            report = result.to_markdown()
            print("\n" + "=" * 70)
            print("✅ 评审完成！报告如下：")
            print("=" * 70)
            print(report)

            # 写入文件
            output_dir = "./docs/internal"
            os.makedirs(output_dir, exist_ok=True)
            output_path = os.path.join(output_dir, "EventLink_许总语音场景_DevSquad_PM_Arch_评审报告.md")

            with open(output_path, "w", encoding="utf-8") as f:
                f.write(report)

            print(f"\n📄 报告已写入: {output_path}")
        else:
            print(f"\n❌ 评审失败:")
            print(f"   Errors: {result.errors}")
            print(f"   Summary: {result.summary}")

            # 即使失败也尝试写入部分结果
            output_dir = "./docs/internal"
            os.makedirs(output_dir, exist_ok=True)
            output_path = os.path.join(output_dir, "EventLink_许总语音场景_DevSquad_PM_Arch_评审报告.md")

            partial_report = f"# EventLink 许总语音场景 PM+Arch 评审报告\n\n> ⚠️ 评审未完全成功\n\n## 错误信息\n\n{result.errors}\n\n## 部分摘要\n\n{result.summary}\n\n## Worker Results\n\n"
            if result.worker_results:
                for wr in result.worker_results:
                    partial_report += f"\n### [{wr.get('role', 'unknown')}]\n\n{wr.get('output', 'No output')}\n"

            with open(output_path, "w", encoding="utf-8") as f:
                f.write(partial_report)
            print(f"⚠️ 部分结果已写入: {output_path}")

    except Exception as e:
        print(f"\n❌ 执行异常: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
    finally:
        disp.shutdown()
        print("\n[INFO] Dispatcher 已关闭")


if __name__ == "__main__":
    main()
