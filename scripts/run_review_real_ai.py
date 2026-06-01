#!/usr/bin/env python3
"""
EventLink 产品设计评审 - 使用 DevSquad 多角色团队（真实AI模式）
"""
import sys
import os

# 添加 DevSquad 到路径
sys.path.insert(0, '../DevSquad')

from scripts.collaboration.dispatcher import MultiAgentDispatcher
from scripts.collaboration.llm_backend import create_backend

# 评审任务描述（保持不变）
REVIEW_TASK = """
## 任务：EventLink 产品设计全面评审

你是一个专业的产品设计评审团队，请对 CarryMem EventLink 产品设计进行全面评审。

### 项目概述
EventLink 是 CarryMem 记忆系统的扩展模块：
- **核心价值**：新事件进来时，自动与已有记忆交叉关联，主动推送用户看不到的商脉和人脉线索
- **定位**：从"记住你是谁"升级到"帮你发现你错过了什么"
- **目标用户**：商务人士（需要管理大量人脉和商机）

### 核心技术设计
1. **数据模型**：
   - Event（事件）：会议/日程/对话，包含实体列表和关联列表
   - Entity（实体）：5种类型（人物/组织/技术/项目/属性）
   - Association（关联）：7种类型（同校/前同事/竞对/技术同源/商机关联/风险关联/供应链）
   - Alert（提醒）：3种类型（机会/风险/上下文）

2. **处理管道**：实体抽取 → 实体归一 → 关联发现 → 提醒生成 → 存储更新

3. **存储方案**：SQLite + 邻接表模拟图结构（4张表：entities/associations/events/alerts）

4. **架构**：三层结构（应用层 → 关联层(EventLink) → 记忆层(CarryMem)）
   - 关联层消费记忆层数据但不修改记忆层代码
   - 通过 relationship 类型的 metadata 扩展存储关联信息

5. **输入源**：
   - MVP：手动输入、对话摘要
   - 后续：日历同步、录音转写、CRM导入、邮件摘要

6. **输出方式**：
   - CLI命令行工具
   - MCP工具扩展
   - Graphviz DOT可视化
   - 后续：Web仪表盘

### 商业模式
- 基础版：免费开源本地运行
- AI抽取：用户自配API Key
- 云端同步+团队共享：订阅制
- 录音转写：按量计费

### 开发路线图
- Phase 1 (MVP)：手动输入+简单关联，零依赖零LLM
- Phase 2：LLM实体抽取+语义关联+规则引擎联动
- Phase 3：外部数据源+日历同步+提醒频率控制
- Phase 4：商务版App/Web仪表盘/团队共享/CRM集成

### 已识别的开放问题
1. 实体归一准确率问题
2. 多跳推理计算成本
3. 隐私顾虑（人脉图谱敏感性）
4. 团队图谱权限模型
5. LLM抽取成本控制
6. 竞对关系判断依据
7. 与合作伙伴产品集成边界

---

## 请从你的专业角色角度进行深入评审

### 评审要求

**每个角色必须至少提出 3-5 个关键问题或建议**，包括：

1. **具体的问题点**（不是泛泛而谈）
2. **潜在的影响**（对产品/技术/用户的负面影响）
3. **改进建议**（可操作的行动项）
4. **优先级评估**（P0必须解决/P1重要/P2改进/P3可选）

### 角色分工

**如果你是架构师(Architect)**：
- 三层架构是否合理？耦合度是否合适？
- SQLite邻接表方案的扩展性瓶颈在哪里？
- 数据一致性如何保证？并发访问怎么处理？
- 与CarryMem现有架构的集成是否优雅？
- 是否需要考虑微服务化？

**如果你是产品经理(Product Manager)**：
- 目标用户画像是否清晰？场景覆盖完整吗？
- MVP范围是否恰当？会不会过度工程化？
- 提醒策略的用户体验够好吗？打扰度如何控制？
- 商业模式可持续吗？定价策略合理吗？
- 与CRM/知识库/AI助手的差异化足够明显吗？
- 用户onboarding流程如何设计？

**如果你是安全专家(Security)**：
- 本地运行的数据安全措施够不够？
- 云端版本的加密和访问控制如何实现？
- 实体归一过程中的隐私泄露风险？
- 团队共享场景下的权限隔离怎么做？
- API Key管理的安全性？
- GDPR/个人信息保护法合规性？

**如果你是测试专家(Tester)**：
- 测试策略应该如何分层？
- 关键测试用例有哪些？边界条件？
- 如何验证关联发现的准确性（precision/recall）？
- 如何测试提醒的相关性和不打扰性？
- 性能测试基准是什么？（响应时间/吞吐量）
- 数据质量保障机制？

**如果你是开发者(Coder)**：
- 技术实现难点在哪里？
- LLM调用的错误处理和降级策略？
- 实体归一的算法复杂度和准确率？
- 多跳查询的性能优化方案？
- 代码可维护性和测试性如何保证？

**如果你是运维工程师(DevOps)**：
- 本地部署的复杂性如何降低？
- 云端版本的运维挑战有哪些？
- 监控告警机制如何设计？
- 数据备份恢复策略？
- 版本升级迁移路径？

**如果你是UI/UX设计师(UI Designer)**：
- CLI交互体验是否友好？
- 可视化方案是否满足需求？
- 提醒展示的最佳实践？
- 移动端适配考虑？
- 无障碍访问(accessibility)？

---

### 输出格式要求

请按照以下结构输出：

#### 1. 角色专业视角评审（你的角色）
- [ ] 问题1：xxx
  - 影响：xxx
  - 建议：xxx
  - 优先级：P0/P1/P2/P3
- [ ] 问题2：xxx
  ...

#### 2. 跨领域关注点（即使不是你的专业也要提）
- 提出至少2个其他领域的观察或疑问

#### 3. Top 5 必须解决的问题
- 从所有问题中筛选出最关键的5个

#### 4. 整体评估
- 可行性评分（1-10分）
- 最大风险点
- 核心建议

请务必深入挖掘，提供具体的、可操作的建议！
"""

def main():
    print("=" * 80)
    print("EventLink 产品设计评审 - DevSquad 多角色团队（真实AI模式）")
    print("=" * 80)
    print()

    # 创建 LLM Backend（使用提供的 API Key）
    backend = create_backend(
        "openai",
        api_key=os.environ.get("MOKA_API_KEY", ""),
        base_url=os.environ.get("MOKA_BASE_URL", "https://api.moka-ai.com/v1"),
        model=os.environ.get("MOKA_MODEL", "moka/claude-sonnet-4-6"),
    )

    # 创建 Dispatcher
    disp = MultiAgentDispatcher(
        llm_backend=backend,
        enable_warmup=True,
        enable_compression=True,
        enable_permission=True,
        enable_memory=True,
    )

    try:
        # 执行多角色评审
        # 使用全部7个角色进行全面评审
        result = disp.dispatch(
            task_description=REVIEW_TASK,
            roles=["architect", "product-manager", "security", "tester", "solo-coder", "devops", "ui-designer"],
            mode="parallel",  # 所有角色并行执行
            dry_run=False,
        )

        # 输出结果
        print("\n" + "=" * 80)
        print("✅ 评审完成！正在生成完整报告...")
        print("=" * 80)
        print()

        if result.success:
            markdown_report = result.to_markdown()

            # 保存到文件
            report_path = "./EventLink_DevSquad_真实AI评审报告.md"
            with open(report_path, 'w', encoding='utf-8') as f:
                f.write(markdown_report)

            print(f"\n🎉 真实AI评审报告已保存到: {report_path}")
            print(f"📊 报告大小: {len(markdown_report)} 字符")
            print(f"⏱️ 耗时: {result.duration_seconds:.2f}秒")
            print(f"👥 参与角色: {', '.join(result.matched_roles)}")

            # 输出摘要
            print("\n" + "=" * 80)
            print("📋 执行摘要")
            print("=" * 80)
            print(result.summary[:2000] if len(result.summary) > 2000 else result.summary)

        else:
            print("❌ 评审失败:")
            for error in result.errors:
                print(f"  - {error}")
            print(result.summary)

    except Exception as e:
        print(f"❌ 发生错误: {e}")
        import traceback
        traceback.print_exc()
    finally:
        disp.shutdown()
        print("\n🎉 DevSquad 评审完成")

if __name__ == "__main__":
    main()
