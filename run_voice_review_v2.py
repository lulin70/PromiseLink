#!/usr/bin/env python3
"""Run voice review and write output to file"""
import sys
import os
import tempfile

# Redirect all output to file
OUTPUT_FILE = "./docs/internal/EventLink_许总语音场景_DevSquad_PM_Arch_评审报告.md"

sys.stdout = open(OUTPUT_FILE + ".log", "w", encoding="utf-8")
sys.stderr = sys.stdout

print("Starting review script...", flush=True)

sys.path.insert(0, "../DevSquad")
sys.path.insert(0, "../DevSquad/scripts")

from scripts.collaboration.dispatcher import MultiAgentDispatcher
from scripts.collaboration.llm_backend import create_backend

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

**关键交互特征**：自然语言输入、中间态反馈("请稍等")、TTS语音输出（视力障碍+车载场景）、多轮对话潜力、隐私敏感

### 现有文档基线
- PRD v4.3: F-49日视图(P1 P0), F-47 RelationshipBrief(P1 P0), F-44 input_scope分类器, F-10语音录入(P1 P0), F-41 TTS播报(P1 P0)
- 技术设计 v2.5: LLM=Moka AI(moka/claude-sonnet-4-6), ASR=微信同声传译/Whisper, TTS=预合成MP3/Azure Edge-TTS
- 已有API: GET /dashboard/day-view, GET /persons/{id}/relationship-brief, GET /todos?view=my-responses, POST /mini/voice-input, GET /mini/person/{id}/tts

### 当前缺口
NLU意图解析引擎(大)、多轮对话状态管理(中)、Answer Generation(中)、TTS流式播报(中)、语音UI交互范式(中)

---

## 评审要求

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
4. **对各设计文档的具体影响**：API_Design新增端点? Algorithm_Design NLU范围? Integration_Design ASR/TTS细化? Database_Design新表? Deployment_Guide新依赖?
5. **风险评估**：技术风险（ASR准确率/NLU延迟/TTS成本）、缓解措施

### 输出格式要求：
双方独立分析→列出共识点和分歧点→对每份文档的具体变更建议→优先级建议和下一步行动项→完整Markdown报告
"""

print("Creating backend...", flush=True)
backend = create_backend(
    "openai",
    api_key="sk-GWSmGaP4XYK3YDWi80gGZTtae8eb7id1mgCAYDdvDgoFpUzX",
    base_url="https://api.moka-ai.com/v1",
    model="moka/claude-sonnet-4-6",
)

work_dir = tempfile.mkdtemp(prefix="eventlink_voice_review_")
print(f"Work dir: {work_dir}", flush=True)

disp = MultiAgentDispatcher(
    llm_backend=backend,
    persist_dir=work_dir,
    enable_compression=True,
    enable_permission=True,
)

print("Dispatching PM+Arch consensus review...", flush=True)
result = disp.dispatch(
    task_description=TASK_DESCRIPTION,
    roles=["product-manager", "architect"],
    mode="consensus",
    dry_run=False,
)

if result.success:
    report = result.to_markdown()
    
    # Write report
    os.makedirs(os.path.dirname(OUTPUT_FILE), exist_ok=True)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write(report)
    
    print("REPORT_START", flush=True)
    print(report, flush=True)
    print("REPORT_END", flush=True)
    print(f"Report written to {OUTPUT_FILE}", flush=True)
else:
    print(f"FAILED: errors={result.errors}, summary={result.summary}", flush=True)
    # Write partial results
    os.makedirs(os.path.dirname(OUTPUT_FILE), exist_ok=True)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write(f"# EventLink 许总语音场景 PM+Arch 评审报告\n\n> ⚠️ 评审未完全成功\n\n## 错误\n\n{result.errors}\n\n## 摘要\n\n{result.summary}\n")
    if result.worker_results:
        with open(OUTPUT_FILE, "a", encoding="utf-8") as f:
            for wr in result.worker_results:
                f.write(f"\n## [{wr.get('role','?')}]\n\n{wr.get('output','')}\n")

disp.shutdown()
print("DONE", flush=True)
sys.stdout.close()
