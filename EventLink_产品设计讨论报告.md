# EventLink 产品设计讨论报告

> **日期**: 2026-05-31
> **版本**: v1.0
> **状态**: 初稿 - 供团队讨论
> **参考文档**:
>   - CarryMem_EventLink_事件驱动关联发现_用户版.md
>   - CarryMem_EventLink_事件驱动关联发现_产品设计.md

---

## 📋 执行摘要

本报告基于 DevSquad 多角色团队（架构师、产品经理、安全专家、测试专家、开发者、运维工程师、UI设计师）的评审框架，对 EventLink 产品设计进行全面审查。我们识别出 **47个关键问题**，其中 **12个为P0级必须解决**，**18个为P1级重要问题**。整体可行性评分为 **7.2/10**，核心风险集中在实体归一准确率、隐私合规、商业模式可持续性三个方面。

**核心结论**：产品设计思路清晰、定位精准，但在技术实现细节、用户体验打磨、合规性保障方面存在显著缺漏，需要在 Phase 1 开发前进行补充设计。

---

## 一、各角色专业视角评审

### 🏗️ 1.1 架构师视角 (Architect)

#### 问题 A1: SQLite 邻接表方案的扩展性瓶颈 [P0]

**问题描述**:
当前方案使用 SQLite + 邻接表模拟图结构，在数据量增长后会出现严重性能瓶颈：
- **多跳查询性能**：3跳以上关联查询需要多次 JOIN，复杂度 O(n^k)（n=实体数，k=跳数）
- **写入瓶颈**：每次新 Event 触发时需要扫描全部已有实体做关联发现，O(n*m) 复杂度（n=新实体数，m=已有实体数）
- **索引限制**：SQLite 的 B-tree 索引对图查询优化有限，缺乏图遍历专用索引

**潜在影响**:
- 当实体数超过 10,000 时，单次关联发现延迟可能 >5s
- 当关联数超过 100,000 时，多跳查询可能 >10s
- 无法支持实时提醒场景（商务人士期望 <2s 响应）

**改进建议**:

```python
# 方案1: 分层缓存策略（推荐用于 MVP → Phase 2 过渡）
class EntityGraphCache:
    """热点实体缓存层"""
    hot_entities: LRUCache(maxsize=1000)  # 最近活跃的实体
    entity_index: InvertedIndex  # 倒排索引（按类型/属性）
    association_cache: TTLCache  # 关联结果缓存（TTL=1h）

# 方案2: 引入轻量图查询引擎（Phase 3 必备）
# 推荐使用 networkx (纯Python) 或 igraph (C扩展)
import networkx as nx
G = nx.DiGraph()
G.add_node("ent_012", **entity_props)
G.add_edge("ent_012", "ent_025", relation_type="tech_overlap", weight=0.85)

# 2跳查询示例
def two_hop_query(graph, start_entity, relation_type):
    return list(nx.single_source_shortest_path_length(
        G, start_entity, cutoff=2
    ))
```

**优先级**: P0（必须在 Phase 2 前确定技术方案）

---

#### 问题 A2: 三层架构的数据一致性保证机制缺失 [P0]

**问题描述**:
当前设计提到"关联层消费记忆层数据但不修改记忆层代码"，但未明确：
- **事务边界**：Event 处理管道的 5 个步骤（抽取→归一→关联→提醒→存储）是否在同一事务内？
- **失败回滚**：如果 Step 4 提醒生成成功但 Step 5 存储失败，如何处理？
- **并发控制**：多个 Event 同时触发关联发现时的锁机制？
- **最终一致性**：记忆层和关联层数据不同步时的修复策略？

**潜在影响**:
- 数据不一致导致重复提醒或遗漏提醒
- 实体 ID 冲突或关联丢失
- 用户信任度下降

**改进建议**:

```python
# 引入 Saga 模式处理长事务
class EventProcessingSaga:
    def execute(self, event: Event):
        steps = [
            EntityExtractionStep(),
            EntityResolutionStep(),
            AssociationDiscoveryStep(),
            AlertGenerationStep(),
            PersistenceStep()
        ]

        compensating_actions = [
            delete_extracted_entities,      # 回滚 Step 1
            rollback_resolutions,           # 回滚 Step 2
            delete_discovered_associations, # 回滚 Step 3
            mark_alerts_as_stale,           # 回滚 Step 4 (软删除)
        ]

        for i, step in enumerate(steps):
            try:
                result = step.execute(event, context)
            except Exception as e:
                # 执行补偿操作回滚已完成步骤
                for j in range(i-1, -1, -1):
                    compensating_actions[j](event.id)
                raise ProcessingFailedError(f"Step {i} failed: {e}")
```

**优先级**: P0（必须在 Phase 1 实现基础版）

---

#### 问题 A3: 与 CarryMem 现有架构的耦合度过高 [P1]

**问题描述**:
虽然设计原则是"不修改记忆层代码"，但实际存在隐式耦合：
- 直接依赖 `relationship` 类型的 metadata 扩展格式
- 需要消费 `fact_declaration` / `decision` / `user_preference` 类型记忆
- CLI 命令空间冲突（`carrymem add-event` vs `carrymem add-memory`）

**潜在影响**:
- CarryMem 升级时可能破坏 EventLink 兼容性
- 无法独立部署和测试 EventLink
- 违反单一职责原则

**改进建议**:

```python
# 引入适配器模式解耦
class MemoryLayerAdapter:
    """CarryMem 记忆层的抽象接口"""

    def read_memories(self, memory_type: str, query: dict) -> list[Memory]:
        """读取记忆（可替换为任何存储后端）"""
        pass

    def write_memory(self, memory: Memory) -> str:
        """写入记忆"""
        pass

    def get_rules(self, rule_type: str) -> list[Rule]:
        """获取规则"""
        pass

# 具体实现
class CarryMemAdapter(MemoryLayerAdapter):
    def __init__(self, carrymem_instance):
        self.cm = carrymem_instance

    def read_memories(self, memory_type, query):
        return self.cm.recall(f"type:{memory_type} {query}")

# 测试用 Mock 实现
class MockMemoryAdapter(MemoryLayerAdapter):
    ...
```

**优先级**: P1（Phase 1 应该实现适配器层）

---

#### 问题 A4: 缺乏水平扩展能力的设计 [P2]

**问题描述**:
当前架构完全基于本地 SQLite，无法支持：
- 团队共享场景的多租户隔离
- 云端版本的读写分离
- 关联发现的分布式计算

**潜在影响**:
- Phase 4 的团队共享功能需要大规模重构
- 无法应对企业级用户的性能需求

**改进建议**:
- Phase 1-2 保持 SQLite 单机（符合轻量哲学）
- Phase 3 引入 PostgreSQL + pg_graphql 扩展（平滑迁移路径）
- Phase 4 考虑微服务拆分（关联发现服务独立部署）

**优先级**: P2（可在 Phase 2-3 期间规划）

---

### 📦 1.2 产品经理视角 (Product Manager)

#### 问题 P1: 目标用户画像过于宽泛 [P0]

**问题描述**:
当前定义的目标用户是"商务人士（需要管理大量人脉和商机）"，但这个群体内部差异巨大：

| 细分人群 | 核心痛点 | 使用场景 | 技术水平 |
|---------|---------|---------|---------|
| 企业销售总监 | 管理团队客户关系 | 大客户跟进 | 中等 |
| 创业公司CEO | 人脉资源整合 | 融资/合作洽谈 | 较高 |
| 自由顾问 | 个人品牌建设 | 项目机会挖掘 | 高 |
| 投资人 | 项目源管理 | 尽调/投后管理 | 高 |
| 外贸业务员 | 客户/供应商网络 | 订单/供应链 | 低 |

**潜在影响**:
- MVP 功能范围难以收敛（试图满足所有人 = 满足不了任何人）
- 提醒策略无法个性化（不同人群关注点完全不同）
- Onboarding 流程设计困难

**改进建议**:

**Phase 1 聚焦核心用户群**：
- **首选目标**: 年营收 500万-5000万的中小企业主/销售负责人
- **特征**: 每天2-5场会议，管理50-200个联系人，已有CRM但不好用
- **放弃**: 大企业（有专门IT团队）、纯技术人员（不需要）、极低频用户（<1次/周）

**用户画像示例**:
```
姓名: 张总
角色: XX科技公司销售VP，管理15人团队
日常: 每天3-4场客户会议，每周2次行业活动
痛点: 
  - 上周见的客户今天忘了叫什么
  - 两个客户需求类似但没串起来
  - 不小心把A公司的信息透露给B公司（竞对）
现有工具: 企微CRM（只录不推）、Excel联系人本、微信备注
技术能力: 会用智能手机，能接受CLI但不希望太复杂
付费意愿: 如果真能帮到生意，愿意付200-500元/月
```

**优先级**: P0（必须在开发前明确定义）

---

#### 问题 P2: 场景覆盖不完整 - 缺少关键使用场景 [P0]

**问题描述**:
当前文档只覆盖了"开会→自动关联→推送提醒"的主流程，缺少以下关键场景：

**缺失场景 1: 冷启动问题**
- 新用户第一次使用时没有任何历史数据，系统如何提供价值？
- 是否需要引导用户导入历史通讯录/邮件/日历？
- 冷启动期间的用户留存策略？

**缺失场景 2: 数据纠错**
- 用户发现"李总"被错误归一到"李明"，如何快速修正？
- 错误归一的连锁反应如何消除？（已生成的关联、提醒）
- 用户反馈回路如何设计？

**缺失场景 3: 离线/弱网环境**
- 商务人士经常出差、飞机上、地下室会议室无信号
- 离线模式下能否录入Event？能否查看历史关联？
- 网络恢复后的数据同步策略？

**缺失场景 4: 团队协作**
- 销售团队的成员之间能否共享部分图谱？（如竞对信息共享，客户关系私有）
- 经理能否查看下属的人脉覆盖度分析？
- 如何防止敏感商业情报泄露？

**缺失场景 5: 数据导出与迁移**
- 用户想换工具时能否导出完整图谱？
- 能否导入其他CRM/通讯录的数据？
- 数据所有权归属问题？

**潜在影响**:
- 用户在真实使用中遇到这些场景时会感到沮丧
- 冷启动流失率可能 >70%
- 缺少数据导出功能会降低用户信任度和尝试意愿

**改进建议**:

```python
# 冷启动引导流程设计
class ColdStartOnboarding:
    steps = [
        {
            "step": 1,
            "title": "导入你的联系人",
            "action": "upload_contacts",
            "sources": ["微信通讯录", "iPhone联系人", "CSV文件", "企微通讯录"],
            "estimated_time": "2分钟",
            "value_proposition": "导入后立即能看到谁和谁是老同事/同校"
        },
        {
            "step": 2,
            "title": "回顾最近的重要会议",
            "action": "manual_input",
            "template": """
                时间: [日期选择器]
                参与人: [从已导入联系人中选择]
                公司: [自动填充]
                聊了什么: [自由文本]
                关键词: [AI辅助提取建议]
            """,
            "examples": [
                "上周和李总聊了IoT项目",
                "参加了XX行业的峰会",
                "和张总吃了午饭"
            ],
            "min_events": 5,  # 至少输入5个Event才能解锁关联发现
            "value_proposition": "输入5次会议后，系统开始自动发现关联"
        },
        {
            "step": 3,
            "title": "看看发现了什么",
            "action": "show_initial_insights",
            "demo_mode": True,  # 使用示例数据演示效果
            "cta": "开启实时提醒"
        }
    ]
```

**优先级**: P0（必须在 Phase 1 设计中体现）

---

#### 问题 P3: MVP 功能范围评估 - 可能过度工程化 [P1]

**问题描述**:
Phase 1 定义了以下功能：
- ✅ 4张表（entities/associations/events/alerts）
- ✅ 手动输入 Event + 手动标注实体
- ✅ 简单关联发现（同名合并 + co_occurrence）
- ✅ CLI 输出提醒
- ❓ 零外部依赖，零 LLM 调用

**疑问**：
- "简单关联发现"的具体规则是什么？仅靠 co_occurrence（共现）够吗？
- 手动标注实体的用户体验如何？用户愿不愿意每条Event都手动打标签？
- 没有 LLM 支持，提醒质量能达到"有用"的门槛吗？

**潜在影响**:
- 如果 MVP 的关联发现太简单，用户会觉得"这东西没用"
- 如果手动标注太繁琐，用户不会坚持使用
- MVP 验证的不是核心价值假设，而是UI易用性

**改进建议**:

**MVP 范围调整方案**：

| 原MVP | 调整后MVP | 理由 |
|-------|----------|------|
| 手动标注实体 | **半自动标注**（用户提供关键词列表，系统匹配预置词典） | 降低用户负担 |
| 仅 co_occurrence 关联 | **增加 2-3 种硬编码规则**（如同名、同公司自动关联） | 提升提醒质量 |
| CLI 输出 | **CLI + 简单Web页面展示**（单HTML文件，无需服务器） | 降低使用门槛 |
| 零依赖 | **允许可选LLM调用**（用户配Key则启用，否则降级为规则） | 验证核心价值 |

**MVP 成功指标**：
- 用户至少录入 10 条 Event
- 系统至少生成 3 条用户认为"有点意思"的提醒
- 7日留存率 >30%

**优先级**: P1（需要重新评估 MVP 范围）

---

#### 问题 P4: 提醒策略的用户体验细节不足 [P1]

**问题描述**:
当前文档提到了三层过滤机制：
1. 同一关联24小时不重复提醒
2. 高优先级最多每日3条
3. 低优先级聚合为每日摘要
4. 用户忽略3次以上的同类提醒自动降级

**但缺少以下关键细节**：

**时机问题**：
- 提醒应该在什么时候推？会后立即？每天早上9点？还是用户主动查看时？
- 不同类型提醒的最佳触达时间是否不同？（机会提醒适合白天，风险提醒适合决策前）

**渠道问题**：
- MVP阶段只有CLI，用户怎么收到提醒？需要一直开着终端吗？
- 后续是否支持微信/邮件/短信/浏览器推送？
- 推送频率过高时如何优雅地"静音"？

**内容问题**：
- 提醒文案的语气应该是什么风格？正式？口语化？幽默？
- 是否需要提供"为什么推送这条提醒"的解释？
- 用户点击提醒后的下一步行动是什么？（查看详情？标记已读？添加备忘？）

**干扰控制**：
- 如何避免"狼来了"效应（推送太多低质量提醒导致用户关闭通知）？
- 是否需要"专注模式"（工作时间内不打扰）？
- 用户能否自定义提醒偏好？（如"只在周一到周五9am-6pm提醒"）

**潜在影响**:
- 提醒体验差会导致用户关闭通知功能，核心价值丧失
- 推送渠道限制会影响 MVP 的用户参与度

**改进建议**:

```python
# 提醒体验设计规范
ALERT_EXPERIENCE_SPEC = {
    "timing": {
        "realtime": {
            "trigger": "Event处理后30秒内",
            "types": ["risk_high"],  # 只有高风险立即推送
            "channel": "CLI弹窗 + 可选声音提示"
        },
        "daily_digest": {
            "trigger": "每天早9点",
            "types": ["opportunity_all", "context_all", "risk_medium_low"],
            "format": """
                ☀️ 今日商脉洞察 ({date})
                
                🔴 需注意 ({count_risk}条)
                - {risk_item_1}
                - {risk_item_2}
                
                💡 新机会 ({count_opportunity}条)
                - {opportunity_item_1}
                
                📌 背景补充 ({count_context}条)
                - {context_item_1}
                
                [查看详情] [调整提醒设置]
            """
        },
        "on_demand": {
            "trigger": "用户执行 `carrymem alerts` 时",
            "types": "all"
        }
    },

    "content_style": {
        "tone": "professional_but_friendly",  # 专业但亲切
        "max_length": 120,  # 单条提醒不超过120字符
        "must_include": ["who", "what", "so_what", "action_suggestion"],
        "example": {
            "opportunity_high": "🟢 李总(XX科技)的IoT方案，和张总3周前提到的智能工厂有技术重叠。\n💡 建议：可以考虑把两方需求串成一个联合方案。",
            "risk_high": "🔴 注意：XX科技(李总)和YY科技(王总)存在竞争关系，你正在同时接触两家。\n⚠️ 建议：分享信息时注意边界，避免无意中泄露对方商业情报。"
        }
    },

    "feedback_loop": {
        "actions_per_alert": ["dismiss", "confirm", "snooze", "edit"],
        "dismiss_reasons": ["not_relevant", "already_knew", "wrong_entity", "too_noisy"],
        "auto_learning": "连续忽略3次同类提醒 → 自动降低该类提醒优先级 + 弹窗询问是否暂停"
    }
}
```

**优先级**: P1（Phase 1 必须设计基础版提醒体验）

---

#### 问题 P5: 商业模式可持续性质疑 [P1]

**问题描述**:
当前商业模式：
- 基础版：免费开源本地运行
- AI 抽取：用户自配 API Key
- 云端同步+团队共享：订阅制（按人数按年付费）
- 录音转写：按量计费

**质疑点**：

**收入来源过于依赖后期功能**：
- 基础版免费 → 无法直接变现
- AI 抽取成本转嫁给用户 → 用户可能觉得"还要自己花钱？"而放弃
- 云端/团队功能要等到 Phase 4 → 18-24个月后才有收入
- 这18个月如何维持开发？

**定价策略模糊**：
- "订阅制"具体多少钱？参考竞品定价？
- 按人数收费的阈值是多少？（1人？5人？10人？）
- 是否提供免费试用期？试用期的功能限制？

**客户获取成本(CAC) vs 生命周期价值(LTV)**：
- 目标用户（中小企业主）的时间成本高，教育市场难度大
- 免费版用户转化为付费版的转化率预期多少？（一般SaaS 2-5%）
- 如果转化率低，如何盈利？

**与合作伙伴（许总）的利益分配**：
- CarryMem 是引擎，许总做应用外壳
- 收入如何分成？一次性买断？ royalty？技术服务费？
- 许总是否有独家代理权？还是可以多渠道？

**潜在影响**:
- 商业模式不可持续导致项目中途资金断裂
- 定价错误导致要么用户嫌贵要么收入不足
- 合作伙伴利益分配不均导致合作破裂

**改进建议**:

**商业模式调整方案**：

**方案 A: Freemium + 增值服务（推荐）**

```
免费版（个人用户）：
- 本地运行，最多 50 个实体
- 手动输入 Event
- 基础关联发现（co_occurrence + 同名）
- 每日最多 3 条提醒

Pro 版（$9.9/月 or ¥69/月）：
- 无限实体数量
- LLM 自动抽取（包含 API 成本）
- 高级关联发现（7种关联类型全部启用）
- 无限提醒 + 自定义过滤规则
- 导出功能（JSON/CSV/DOT）

Team 版（$29.9/人/月 or ¥199/人/月）：
- 包含 Pro 所有功能
- 团队共享图谱（权限可控）
- 管理后台（成员活跃度/关联覆盖率分析）
- CRM 集成（企微/钉钉/飞书）
- SLA 保障 + 专属客服
```

**方案 B: 开源核心 + 云托管服务**

```
开源社区版：
- 完全开源，自由部署
- 社区支持（GitHub Issues/论坛）

Cloud 托管版（按用量计费）：
- Event 处理次数：$0.01/次
- 实体存储：$0.001/实体/月
- LLM 抽取：$0.05/次（批发价转售）
- 团队协作：$5/人/月
- 免费额度：每月 100 次 Event 处理 + 200 个实体
```

**与许总的合作模式建议**：

```
模式 1: 技术授权（License）
- 许总支付一次性技术授权费：¥50-100万
- CarryMem 团队提供技术支持和升级服务（年费制）
- 许总拥有独家应用开发权（限特定区域/行业）

模式 2: 收入分成（Royalty）
- 许总负责前端开发和销售
- 收入分成比例：CarryMem 30% : 许总 70%
- 最低保底分成：¥X万/年

模式 3: 联合运营（Joint Venture）
- 双方共同出资成立合资公司
- CarryMem 出技术（占股 40-50%）
- 许总 出渠道和运营（占股 50-60%）
- 利润按持股比例分配
```

**优先级**: P1（必须在 Phase 1 启动前确定商业模式）

---

#### 问题 P6: 与竞品的差异化不够明显 [P2]

**问题描述**:
当前文档对比了 CRM（企微/钉钉）和知识库（飞书文档），但忽略了以下竞品：

**直接竞品**：
- **Notion Relations + Database**: 已经可以实现简单的实体关联和自动化提醒
- **Obsidian + Dataview 插件**: 知识图谱 + 自动关联，受技术用户欢迎
- **Roam Research**: 双向链接 + 图谱可视化，主打知识工作者
- **HubSpot CRM Intelligence**: 已有关联推荐功能（竞对检测、商机关联）
- **Salesforce Einstein**: AI驱动的关联发现和预测

**间接竞品**：
- **ChatGPT/Claude + Plugins**: 用户可以直接问 AI "帮我找找这两个人有没有关联"
- **Microsoft Copilot**: Office 365 内置的智能助手，可以分析邮件/日历/联系人
- **飞书/钉钉智能助手**: 国内办公软件正在集成 AI 能力

**差异化挑战**：
- EventLink 强调"主动推送"而非"被动查询"，但 Notion Automation 也能做到
- EventLink 强调"跨事件交叉比对"，但 ChatGPT 也能通过上下文窗口实现
- EventLink 的壁垒在哪里？算法？数据积累？垂直领域Know-how？

**潜在影响**:
- 用户不理解为什么要用一个新工具而不是增强现有工具
- 市场推广困难（"这不就是XXX吗？"）
- 容易被大厂复制（如果核心逻辑不复杂的话）

**改进建议**:

**强化差异化的方向**：

1. **垂直领域深度**：聚焦"中国商务场景"的特殊需求
   - 微信生态集成（微信聊天记录分析、小程序入口）
   - 中文 NER 优化（处理"李总""李哥""老李"等称呼变体）
   - 中国特色的商务礼仪和潜规则（如"酒桌文化"中的关系建立）

2. **隐私优先的价值主张**
   - 完全本地运行（vs 云端 SaaS 的数据安全顾虑）
   - 用户拥有数据所有权（vs 大厂的数据垄断）
   - 可审计的关联推理过程（vs 黑盒 AI 推荐）

3. **开箱即用的体验**
   - 不需要复杂的配置和训练
   - 5分钟上手，10条Event后就有价值输出
   - 与现有工具无缝对接（日历/邮件/IM）

**优先级**: P2（需要在市场定位文档中强化）

---

### 🔒 1.3 安全专家视角 (Security)

#### 问题 S1: 本地运行模式下的数据安全措施不足 [P0]

**问题描述**:
当前文档提到"基础版完全在本地运行，数据不出你的电脑"，但未说明：

**静态数据加密**：
- SQLite 数据库文件是否加密？（默认明文存储）
- 如果电脑被盗/丢失，攻击者能否直接读取所有人脉数据？
- 是否支持数据库密码保护？

**内存安全**：
- Event 处理过程中，原始文本（含敏感商业信息）在内存中停留多久？
- LLM API 调用时，raw_text 是否完整发送给第三方？（即使使用本地模型也有风险）
- 内存dump攻击的可能性？

**访问控制**：
- 本地运行时，同一台电脑的其他用户能否访问数据库？
- 是否支持多用户隔离？（如老板和秘书共用一台电脑）
- CLI命令的权限控制？（谁能执行 `carrymem export-graph` 导出所有数据）

**日志和残留**：
- CLI 输出是否包含敏感信息？（终端历史记录可被恢复）
- 临时文件是否安全删除？
- 错误日志是否会泄露 raw_text？

**潜在影响**:
- 商务人士的人脉数据和商业机密泄露
- 法律责任（客户信息保护不当）
- 品牌声誉损失

**改进建议**:

```python
# 本地安全加固方案
import sqlcipher3  # SQLite 加密版本
from cryptography.fernet import Fernet

class SecureLocalStorage:
    def __init__(self, db_path: str, encryption_key: bytes):
        """
        加密数据库初始化
        - 使用 SQLCipher 加密 SQLite 文件
        - 加密密钥从用户主密码派生（PBKDF2）
        """
        self.conn = sqlcipher3.connect(db_path)
        self.conn.execute(f"PRAGMA key = '{encryption_key.hex()}'")
        self.conn.execute("PRAGMA cipher_page_size = 4096")

    def secure_delete(self, file_path: str):
        """安全删除临时文件（覆写3次）"""
        import os
        with open(file_path, "ba+") as f:
            length = f.tell()
            f.seek(0)
            for _ in range(3):  # DoD 5220.22-M 标准
                f.write(os.urandom(length))
            f.truncate()
        os.remove(file_path)

    def sanitize_log_output(self, text: str) -> str:
        """脱敏日志输出"""
        import re
        # 替换人名为 [PERSON_X]
        text = re.sub(r'(李总|张总|王总)', '[PERSON_REDACTED]', text)
        # 替换公司名为 [ORG_X]
        text = re.subr'(XX科技|YY集团)', '[ORG_REDACTED]', text)
        return text
```

**安全检查清单**：

- [ ] SQLite 数据库使用 SQLCipher 加密（或提供加密选项）
- [ ] 用户首次启动时强制设置主密码
- [ ] 支持密码强度要求和定期更换提醒
- [ ] 敏感操作（导出/删除）需要二次确认
- [ ] CLI 日志默认脱敏（可通过 verbose 模式关闭）
- [ ] 临时文件使用 secure_delete 清理
- [ ] 提供数据完整性校验（SHA256 哈希）

**优先级**: P0（必须在 Phase 1 实现）

---

#### 问题 S2: 云端版本的加密和访问控制设计缺失 [P0]

**问题描述**:
Phase 4 提到云端部署，但完全没有涉及：

**传输加密**：
- API 通信是否使用 TLS 1.3？
- 证书管理策略（Let's Encrypt? 企业证书？）
- 是否支持 mTLS（双向认证）？

**存储加密**：
- 数据库字段级加密 vs 文件级加密 vs 应用层加密？
- 密钥管理服务(KMS)如何选型？（AWS KMS? HashiCorp Vault? 自建？）
- 密钥轮换策略？

**身份认证**：
- 用户认证方式？（用户名密码? OAuth2? SSO?）
- 多因素认证(MFA)支持？
- Session 管理和 Token 刷新机制？

**授权模型**：
- RBAC（基于角色的访问控制）？ABAC（基于属性的）？
- 权限粒度？（实体级？关联级？Event级？）
- 数据隔离？（租户间完全隔离？逻辑隔离？）

**审计日志**：
- 谁在什么时间访问了什么数据？
- 敏感操作（导出/删除/权限变更）的完整记录
- 日志保留期限和防篡改机制？

**合规性**：
- GDPR（欧盟用户）？
- 中国《个人信息保护法》(PIPL)？
- 行业合规（金融/医疗等特殊行业）？

**潜在影响**:
- 云端版本无法满足企业客户的安全要求
- 数据泄露导致法律诉讼和监管罚款
- 失去企业客户的信任

**改进建议**:

```python
# 云端安全架构设计
class CloudSecurityArchitecture:
    encryption = {
        "in_transit": "TLS 1.3 + HSTS",
        "at_rest": "AES-256-GCM (field-level)",
        "key_management": "AWS KMS (Envelope Encryption)",
        "key_rotation": "90 days automatic"
    }

    authentication = {
        "primary": "OAuth 2.0 + OIDC",
        "mfa": "TOTP (Google Authenticator) + WebAuthn (YubiKey)",
        "session": "JWT (access_token: 15min, refresh_token: 7days)"
    }

    authorization = {
        "model": "RBAC + ABAC hybrid",
        "roles": ["admin", "member", "viewer", "external"],
        "permissions": {
            "entity:read": ["admin", "member", "viewer"],
            "entity:write": ["admin", "member"],
            "entity:delete": ["admin"],
            "association:discover": ["admin", "member"],
            "alert:manage": ["self-only"]  # 只能管理自己的提醒
        },
        "data_isolation": "tenant_id column + RLS (Row Level Security)"
    }

    audit_logging = {
        "events": ["login", "logout", "data_access", "export", "permission_change"],
        "storage": "CloudWatch Logs (immutable)",
        "retention": "2 years (compliance requirement)",
        "pii_masking": True  # 日志中PII自动脱敏
    }

    compliance = {
        "gdpr": {
            "right_to_access": "API endpoint for data export",
            "right_to_erasure": "hard_delete + propagate to backups",
            "data_portability": "JSON/CSV export with all associations",
            "consent_management": "explicit opt-in for analytics"
        },
        "pipl": {
            "data_localization": "China region data stays in China",
            "cross_border_transfer": "Standard Contractual Clauses (SCCs)",
            "minimal_collection": "only collect necessary entities"
        }
    }
```

**优先级**: P0（必须在 Phase 4 设计前完成）

---

#### 问题 S3: 实体归一过程中的隐私泄露风险 [P1]

**问题描述**:
实体归一需要将多个 Event 中的信息聚合到同一个实体，这个过程存在隐私风险：

**跨 Event 信息聚合**：
- Event A："李总是XX科技的CTO，年薪200万"
- Event B："李总住在海淀区XX小区XX号"
- 归一后：实体"李总"同时包含薪资和住址信息
- **问题**：用户可能不想让这些信息关联在一起

**第三方服务调用**：
- LLM 实体抽取时，raw_text 发送给 OpenAI/Anthropic
- 即使承诺不训练模型，仍存在数据泄露风险
- 如何确保敏感信息不被外部服务记录？

**别名推断的隐私含义**：
- 系统推断"李总"="李明"="LM"
- 如果推断错误，可能导致信息误传（把A的秘密告诉B）

**潜在影响**:
- 用户隐私边界被打破
- 商业机密通过关联链意外泄露
- 法律纠纷（未经同意的信息聚合）

**改进建议**:

```python
# 隐私保护的实体归一策略
class PrivacyPreservingResolution:
    def resolve_with_consent(self, candidates: list[EntityMatch]) -> Entity:
        """
        带用户确认的实体归一
        """
        confidence_scores = self.calculate_confidence(candidates)

        if max(confidence_scores) > 0.95:
            # 高置信度：自动合并，但记录来源
            merged = self.auto_merge(candidates)
            self.log_merge_event(merged, sources=candidates, method="auto")
            return merged
        elif max(confidence_scores) > 0.8:
            # 中置信度：静默合并，但标记为"待确认"
            merged = self.merge_with_pending_confirmation(candidates)
            self.notify_user(f"疑似发现'{candidates[0].name}'和'{candidates[1].name}'可能是同一人，确认吗？")
            return merged
        else:
            # 低置信度：不合并，分别保留
            return candidates[0]  # 创建新实体

    def sanitize_for_llm(self, raw_text: str) -> str:
        """
        发送给LLM前的脱敏处理
        """
        # 移除明确的PII（身份证号、手机号、邮箱）
        sanitized = re.sub(r'\d{11}', '[PHONE]', raw_text)
        sanitized = re.sub(r'\w+@\w+\.\w+', '[EMAIL]', sanitized)
        sanitized = re.sub(r'\d{17}[\dXx]', '[ID_CARD]', sanitized)

        # 可选：替换人名为占位符（影响抽取准确性）
        if self.privacy_mode == "strict":
            sanitized = re.sub(r'(李总|张总)', '[PERSON]', sanitized)

        return sanitized

    def entity_level_privacy_settings(self, entity_id: str) -> dict:
        """
        实体级别的隐私设置
        """
        return {
            "allow_auto_merge": False,  # 该实体不允许自动归一
            "sensitive_attributes": ["salary", "address"],  # 敏感属性不跨Event聚合
            "visibility": "owner_only",  # 只有创建者可见
            "share_with_team": False  # 不与团队成员共享
        }
```

**优先级**: P1（Phase 2 必须实现）

---

#### 问题 S4: 团队共享场景下的权限隔离复杂性 [P1]

**问题描述**:
Phase 4 提到"团队共享图谱"，但权限模型极其复杂：

**数据分类难题**：
- 哪些信息应该共享？哪些必须私有？
- 示例：
  - ✅ 可共享：公开的竞对关系、行业趋势、通用技术栈
  - ⚠️ 需谨慎：客户联系方式、报价信息、合同条款
  - ❌ 绝不共享：个人人际关系、薪酬信息、政治倾向

**动态权限变化**：
- 张三今天加入团队，他能看到之前所有的历史关联吗？
- 李四离职后，他的数据如何处理？（删除？归档？转移？）
- 跨部门项目组（临时组建）的权限如何管理？

**关联传播的风险**：
- A看到"李总和王总是前同事"，推断出两人关系密切
- 但实际上这个关联是B的私人信息，不应该让A知道
- **如何防止关联链条导致的非预期信息泄露？**

**潜在影响**:
- 敏感商业情报通过共享图谱泄露
- 团队成员之间的信任危机
- 法律风险（违反保密协议）

**改进建议**:

```python
# 团队权限模型设计
class TeamSharingPermissionModel:
    # 数据分级标准
    DATA_CLASSIFICATION = {
        "public": {
            "description": "公开信息，所有团队成员可见",
            "examples": ["公开的竞对关系", "行业新闻", "技术趋势"],
            "default_visibility": "team"
        },
        "internal": {
            "description": "内部信息，仅项目组成员可见",
            "examples": ["客户需求", "项目进度", "报价范围"],
            "default_visibility": "project",
            "require_explicit_share": True
        },
        "confidential": {
            "description": "机密信息，仅本人和相关方可见",
            "examples": ["合同细节", "个人关系", "薪酬信息"],
            "default_visibility": "owner_only",
            "prevent_association_leakage": True  # 防止关联推导
        },
        "restricted": {
            "description": "受限信息，需要逐次审批才能访问",
            "examples": ["M&A信息", "法律诉讼", "政府关系"],
            "approval_workflow": "manager_approval_required"
        }
    }

    # 关联泄露防护
    class AssociationLeakagePrevention:
        def check_association_visibility(
            self,
            association: Association,
            requester: User,
            source_entity_visible: bool,
            target_entity_visible: bool
        ) -> bool:
            """
            检查关联是否对请求者可见
            即使两端实体都可见，关联本身也可能不可见
            """
            if not (source_entity_visible and target_entity_visible):
                return False

            # 检查关联的 evidence 来源
            for event_id in association.evidence:
                event = self.get_event(event_id)
                if event.classification == "confidential":
                    if event.owner != requester and not event.is_shared_with(requester):
                        return False

            # 检查关联类型的敏感性
            if association.relation_type in ["ex_colleague", "alumni"]:
                # 个人关系类关联更严格
                return association.created_by == requester or association.explicitly_shared

            return True
```

**优先级**: P1（Phase 4 必须详细设计，Phase 1 应预留接口）

---

#### 问题 S5: API Key 管理的安全性 [P2]

**问题描述**:
Phase 2 要求用户自行配置 LLM API Key，存在安全隐患：

**Key 存储位置**：
- 明文写在配置文件里？（~/.carrymem/config.yaml）
- 环境变量？（可以通过 /proc 查看其他进程的环境变量）
- 操作系统钥匙串？（macOS Keychain, Windows Credential Manager）

**Key 泄露途径**：
- 配置文件被意外提交到 Git 仓库
- 配置文件备份到云盘（iCloud/百度网盘）
- 日志中打印出 Key（debug 模式下）
- 屏幕分享/截图时暴露 Key

**Key 轮换和撤销**：
- 用户如何更换 Key？
- 如果 Key 被盗用，如何撤销？
- 多设备同步时 Key 如何安全传递？

**潜在影响**:
- 用户的 API Key 被盗用，产生高额费用
- 第三方服务（OpenAI/Anthropic）封禁账号
- 用户经济损失和对产品的信任危机

**改进建议**:

```python
# 安全的 API Key 管理
import keyring  # 跨平台钥匙串访问
from cryptography.fernet import Fernet

class SecureApiKeyManager:
    def __init__(self):
        self.service_name = "CarryMem-EventLink"
        self.keyring_backend = keyring.get_keyring()

    def store_key(self, provider: str, api_key: str):
        """
        安全存储 API Key 到操作系统钥匙串
        - macOS: Keychain
        - Windows: Credential Manager
        - Linux: Secret Service (GNOME Keyring/KWallet)
        """
        # 加密后再存储（双重保护）
        encrypted_key = self._encrypt(api_key)
        self.keyring_backend.set_password(
            self.service_name,
            f"{provider}_api_key",
            encrypted_key
        )

    def get_key(self, provider: str) -> str:
        """获取并解密 API Key"""
        encrypted = self.keyring_backend.get_password(
            self.service_name,
            f"{provider}_api_key"
        )
        if not encrypted:
            raise KeyError(f"No API key configured for {provider}")
        return self._decrypt(encrypted)

    def rotate_key(self, provider: str, new_key: str):
        """轮换 API Key"""
        old_key = self.get_key(provider)
        self.store_key(provider, new_key)
        # 记录轮换事件（审计日志）
        self.log_security_event(
            event_type="api_key_rotated",
            provider=provider,
            timestamp=datetime.utcnow()
        )

    @staticmethod
    def validate_key_not_in_git():
        """检查 API Key 是否被意外提交到 Git"""
        import subprocess
        result = subprocess.run(
            ["git", "grep", "-q", "sk-", "--include", "*.yaml", "--include", "*.env"],
            cwd=os.getcwd(),
            capture_output=True
        )
        if result.returncode == 0:
            raise SecurityError("⚠️ WARNING: API Key detected in git history! Please rotate immediately!")
```

**优先级**: P2（Phase 2 必须实现）

---

#### 问题 S6: GDPR/个人信息保护法合规性 [P2]

**问题描述**:
EventLink 处理大量个人信息（姓名、公司、职位、关系），需要考虑：

**数据主体权利**（GDPR Art. 15-22）：
- 访问权：用户能否导出自己的所有数据（包括关联和推理结果）？
- 更正权：用户能否修正错误的实体信息？
- 删除权（被遗忘权）：用户要求删除某实体时，相关联的所有数据是否也要删除？
- 便携权：数据能否以机器可读格式导出以便迁移到其他工具？
- 反对权：用户能否拒绝某些类型的关联发现（如"不要分析我的家人"）？

**合法处理基础**（GDPR Art. 6）：
- 用户同意：是否需要明确的 opt-in？
- 合法利益：关联发现是否符合"合法利益"？
- 合同履行：如果是企业版，是否属于"合同必需"？

**数据最小化原则**：
- 是否收集了超出必要范围的信息？
- 属性(attribute)实体类型是否容易过度收集（如"李总喜欢喝酒"这种个人信息）？
- 原始文本(raw_text)保留多久？是否需要自动过期？

**跨境数据传输**：
- 如果使用 OpenAI（美国公司），数据出境是否合规？
- 中国 PIPL 要求数据本地化存储，云端版本如何满足？

**DPIA（数据保护影响评估）**：
- 是否需要进行正式的 DPIA？（处理敏感数据/大规模监控/新技术）
- DPIA 文档在哪里？谁来审核？

**潜在影响**:
- 面临巨额罚款（GDPR 最高 2000万欧元或全球营收4%）
- 中国市场监管部门的行政处罚
- 用户集体诉讼

**改进建议**:

```python
# 合规性框架设计
class ComplianceFramework:
    gdpr = {
        "lawful_basis": "consent + legitimate_interests",
        "consent_mechanism": {
            "first_run": "Explicit consent dialog before first Event processing",
            "granularity": "Per-feature consent (extraction, association, alert)",
            "withdrawal": "One-click withdraw at any time",
            "records": "Keep consent logs for audit trail"
        },
        "data_subject_rights": {
            "access": "GET /api/v1/data-export (JSON format, includes all associations)",
            "rectification": "PATCH /api/v1/entities/{id} (user can edit any field)",
            "erasure": "DELETE /api/v1/entities/{id} (cascade delete all related data)",
            "portability": "GET /api/v1/data-export?format=json-csv (standardized schema)",
            "objection": "POST /api/v1/preferences/opt-out (per-relation-type opt-out)"
        },
        "data_retention": {
            "raw_text": "90 days auto-delete (unless user pins)",
            "entities": "Indefinite (until user deletes)",
            "associations": "Recalculate after entity deletion (no stale data)",
            "alerts": "30 days auto-dismiss"
        },
        "dpia_required": True,
        "dpia_document_path": "/docs/compliance/dpia_eventlink.md"
    }

    pipl = {
        "localization": "China-region users' data stored in China (Alibaba Cloud/Tencent Cloud)",
        "cross_border_transfer": "SCCs required for non-China LLM providers",
        "consent": "Separate consent for Chinese users (Chinese language, explicit opt-in)",
        "dpo_required": "Appoint Data Protection Officer for China operations"
    }

    def generate_privacy_policy(self) -> str:
        """自动生成隐私政策文档"""
        template = """
        # EventLink 隐私政策

        ## 我们收集什么数据
        {data_collected}

        ## 我们如何使用数据
        {data_usage}

        ## 数据存储和安全
        {security_measures}

        ## 您的权利
        {user_rights}

        ## 联系我们
        {contact_info}

        最后更新: {last_updated}
        """
        return template.format(...)
```

**优先级**: P2（Phase 1 应开始准备，Phase 2 必须实现）

---

### 🧪 1.4 测试专家视角 (Tester)

#### 问题 T1: 缺乏分层测试策略 [P0]

**问题描述**:
当前文档完全没有提及测试策略，对于一个涉及 NLP、图算法、规则引擎的复杂系统，这是致命缺陷。

**需要的测试层次**：

**单元测试 (Unit Test)**：
- 实体抽取器的准确性（给定文本→正确实体列表？）
- 实体归一算法的正确性（候选实体→正确合并？）
- 关联强度计算公式的边界值（strength ∈ [0,1]?）
- 时间衰减函数的单调性（越旧越低？）
- 提醒模板渲染的正确性（变量替换无误？）

**集成测试 (Integration Test)**：
- Event 处理管道端到端（输入文本→输出提醒？）
- 与 CarryMem 记忆层的交互（读写一致性？）
- 规则引擎联动（remind_always 规则是否生效？）
- 多步骤 Saga 事务（失败时正确回滚？）

**性能测试 (Performance Test)**：
- 单次 Event 处理延迟（目标 <2s for <100 entities）
- 批量导入 1000 条 Event 的吞吐量
- 多跳查询响应时间（2跳 <500ms, 3跳 <2s）
- 并发 10 个 Event 同时处理的资源消耗

**准确性测试 (Accuracy Test)**：
- 实体抽取 Precision/Recall/F1（人工标注金标准）
- 实体归一准确率（多少比例正确合并？）
- 关联发现的 Precision@K（Top-K 关联有多少是有价值的？）
- 提醒相关性评分（用户主观评价 vs 系统排序）

**回归测试 (Regression Test)**：
- 版本升级后历史数据兼容性
- 新增关联类型不影响已有提醒
- 规则变更后不产生意外副作用

**用户验收测试 (UAT)**：
- 真实用户完成典型任务的成功率
- 用户满意度评分（NPS）
- 学习曲线时长（达到熟练使用需要多久？）

**潜在影响**:
- Bug 频发导致用户流失
- 关联发现不准确损害产品信誉
- 性能问题导致用户放弃使用

**改进建议**:

```python
# 测试策略框架
TEST_STRATEGY = {
    "unit_tests": {
        "coverage_target": ">80%",
        "framework": "pytest",
        "key_modules": [
            "tests/test_entity_extraction.py",
            "tests/test_entity_resolution.py",
            "tests/test_association_discovery.py",
            "tests/test_strength_calculation.py",
            "tests/test_alert_generation.py",
            "tests/test_time_decay.py"
        ],
        "example_test_case": """
        def test_extraction_chinese_names():
            \"\"\"Verify: Chinese name extraction from meeting transcript\"\"\"
            text = "今天和李总、张总还有王工一起开了个项目启动会"
            entities = extract_entities(text)

            assert len(entities) == 3
            assert entities[0].name == "李总"
            assert entities[0].entity_type == "person"
            assert entities[1].name == "张总"
            assert entities[2].name == "王工"
        """
    },

    "integration_tests": {
        "focus_areas": [
            "Event pipeline end-to-end",
            "CarryMem adapter integration",
            "Rule engine interaction",
            "Transaction rollback on failure"
        ],
        "test_data": "fixtures/sample_events.json (20+ realistic examples)"
    },

    "performance_tests": {
        "benchmarks": {
            "single_event_processing": "<2s (with <100 entities)",
            "batch_import_1000_events": "<5min",
            "two_hop_query": "<500ms",
            "three_hop_query": "<2s",
            "concurrent_10_events": "<10s total"
        },
        "tools": "locust (load testing) + pytest-benchmark (microbenchmarks)"
    },

    "accuracy_tests": {
        "gold_standard": "manually_annotated_events.json (100 events, expert labeled)",
        "metrics": {
            "entity_extraction": {"precision": ">0.85", "recall": ">0.80", "f1": ">0.82"},
            "entity_resolution": {"accuracy": ">0.90"},
            "association_precision": {"precision@5": ">0.70", "precision@10": ">0.60"}
        },
        "human_evaluation": "5 users rate 100 random alerts (relevant/not relevant/partially)"
    },

    "regression_tests": {
        "smoke_tests": "Run after every commit (CI/CD gate)",
        "version_upgrade": "Import DB from v1.0, run all tests on v1.1",
        "rule_changes": "After adding new remind_* rule, verify no alert floods"
    }
}
```

**优先级**: P0（Phase 1 开发前必须制定测试计划）

---

#### 问题 T2: 缺少关键测试用例和边界条件 [P1]

**问题描述**:
以下是必须覆盖的关键场景和边界条件：

**实体抽取边界条件**：
- 空字符串输入
- 超长文本（>10,000字的会议纪要）
- 纯英文/纯中文/混合语言
- 口语化表达（"那个谁啊"、"就是上次那个人"）
- 错别字和简称（"阿里爸爸"、"鹅厂"）
- 嵌套实体（"XX公司的李总"——公司和人物嵌套）

**实体归一边界条件**：
- 同名不同人（"张伟"是中国最常见的名字）
- 同人不同名（"李总"、"李明"、"老李"、"LM"）
- 名字相似但不相同（"王强" vs "王刚"）
- 公司更名（"XX科技"改名为"YY集团"）
- 人物离职换公司（李总从A公司跳槽到B公司）

**关联发现边界条件**：
- 完全孤立的实体（无任何关联）
- 高度连接的实体（枢纽节点，如行业大佬）
- 新实体 vs 极旧实体（10年前的Event）
- 循环关联（A→B→C→A）
- 自环关联（A→A，如"李总提到了自己之前的观点"）

**提醒生成边界条件**：
- 同一Event触发 >10 条提醒
- 所有提醒都是低优先级
- 用户连续忽略 100 条提醒
- 提醒内容超过长度限制
- 特殊字符和emoji处理

**并发和竞态条件**：
- 两个Event同时触发对同一实体的归一操作
- 用户在关联发现过程中删除了某个实体
- 提醒推送时用户正在修改偏好设置
- 数据备份期间有新的Event进来

**潜在影响**:
- 边界条件Bug导致生产环境崩溃
- 特殊情况下的错误行为损害用户体验
- 安全漏洞（如注入攻击）

**改进建议**:

```python
# 关键测试用例集
BOUNDARY_TEST_CASES = [
    # 实体抽取
    {
        "id": "EXTRACT-001",
        "name": "Empty input handling",
        "input": "",
        "expected": [],
        "category": "edge_case"
    },
    {
        "id": "EXTRACT-002",
        "name": "Very long transcript (>10k chars)",
        "input": generate_long_text(15000),
        "expected": "Should complete within timeout, no truncation error",
        "category": "performance"
    },
    {
        "id": "EXTRACT-003",
        "name": "Colloquial Chinese expressions",
        "input": "就那个谁啊，上次跟你一块吃饭那个",
        "expected": "Should handle gracefully, maybe ask clarification",
        "category": "nlp_quality"
    },
    {
        "id": "EXTRACT-004",
        "name": "Nested entities (company + person)",
        "input": "我是XX科技的李总",
        "expected": [
            {"name": "XX科技", "type": "organization"},
            {"name": "李总", "type": "person", "properties": {"company": "XX科技"}}
        ],
        "category": "complex_case"
    },

    # 实体归一
    {
        "id": "RESOLVE-001",
        "name": "Same name different people (common Chinese names)",
        "input": [
            Entity(name="张伟", company="A公司"),
            Entity(name="张伟", company="B公司")
        ],
        "expected": "Should NOT merge (different context)",
        "action": "Ask user confirmation",
        "category": "accuracy_critical"
    },
    {
        "id": "RESOLVE-002",
        "name": "Same person different names (aliases)",
        "input": [
            Entity(name="李总"),
            Entity(name="李明"),
            Entity(name="老李")
        ],
        "expected": "Should merge if strong contextual evidence",
        "confidence_threshold": ">0.9 for auto-merge",
        "category": "accuracy_critical"
    },
    {
        "id": "RESOLVE-003",
        "name": "Person changed company (job hop)",
        "timeline": [
            Event(date="2025-01", text="李总在A公司"),
            Event(date="2025-06", text="李总跳槽到了B公司")
        ],
        "expected": "Update company attribute, preserve history",
        "category": "temporal_consistency"
    },

    # 关联发现
    {
        "id": "ASSOC-001",
        "name": "Isolated entity (no connections)",
        "input": Entity(name="新人", no_history=True),
        "expected": "No associations found, no errors",
        "category": "edge_case"
    },
    {
        "id": "ASSOC-002",
        "name": "Highly connected hub node",
        "input": IndustryLeaderEntity(connections=500),
        "expected": "Performance acceptable (<2s), top-K associations meaningful",
        "category": "performance"
    },
    {
        "id": "ASSOC-003",
        "name": "Circular association (A→B→C→A)",
        "graph": create_cycle(["A", "B", "C"]),
        "expected": "Handle without infinite loop, detect cycle",
        "category": "algorithm_correctness"
    },

    # 并发
    {
        "id": "CONCUR-001",
        "name": "Concurrent resolution of same entity",
        "scenario": "Event1 and Event2 both trigger resolution of '李总'",
        "expected": "Serializable isolation, one succeeds then other sees updated state",
        "category": "concurrency"
    },
    {
        "id": "CONCUR-002",
        "name": "Delete entity during association discovery",
        "scenario": "User deletes entity while processing",
        "expected": "Graceful error handling, partial rollback",
        "category": "race_condition"
    }
]
```

**优先级**: P1（Phase 1 必须实现核心边界测试）

---

#### 问题 T3: 准确性验证方法缺失 [P1]

**问题描述**:
如何科学地衡量 EventLink 的核心价值——"关联发现的准确性"？当前文档没有定义：

**金标准数据集**：
- 谁来标注"正确的关联"？领域专家？真实用户？
- 标注指南是什么？（什么样的关联算"正确"？）
- 标注者一致性（Inter-Annotator Agreement）如何保证？
- 数据集规模多大才具有统计显著性？（100条？1000条？）

**评估指标体系**：

| 指标 | 定义 | 目标值 | 说明 |
|------|------|--------|------|
| **Precision@K** | Top-K 关联中有多少是用户认为有价值的？ | P@5 > 0.7 | 避免垃圾提醒 |
| ** Recall@K** | 用户关心的关联有多少出现在 Top-K 中？ | R@10 > 0.6 | 避免遗漏重要信息 |
| **Mean Reciprocal Rank (MRR)** | 第一条相关关联排在第几位？ | MRR > 0.5 | 重要关联靠前 |
| **Normalized Discounted Cumulative Gain (nDCG)** | 排序质量综合评估 | nDCG@10 > 0.65 | 考虑位置权重 |
| **User Satisfaction Rate** | 用户对提醒的有用性评分 | >3.5/5 | 主观评价 |
| **Alert Action Rate** | 用户对提醒采取行动的比例 | >20% | 点击/确认/保存 |

**A/B 测试框架**：
- 对照组：随机推送 / 无推送
- 实验组：EventLink 智能推送
- 指标：用户留存、任务完成效率、商业成果（如成交率提升）

**基线对比**：
- Baseline 1：纯共现统计（co_occurrence only）
- Baseline 2：TF-IDF 相似度
- Baseline 3：随机推荐
- EventLink：完整关联发现算法

**潜在影响**:
- 无法量化产品价值
- 不知道算法迭代是否有效
- 无法说服投资人/合作伙伴

**改进建议**:

```python
# 准确性评估框架
ACCURACY_EVALUATION_FRAMEWORK = {
    "gold_dataset": {
        "creation_process": """
            1. Recruit 5 domain experts (sales managers with 10+ yrs experience)
            2. Provide 100 real meeting transcripts (anonymized)
            3. Experts independently label:
               - All entities (person/org/tech/project/attribute)
               - All ground-truth associations (with relation type)
               - All valuable alerts that should be generated
            4. Calculate Cohen's Kappa for inter-annotator agreement
            5. Resolve disagreements through discussion (create consensus set)
            6. Split: 70% training / 15% validation / 15% test
        """,
        "size": 100 events, ~500 entities, ~200 associations,
        "update_frequency": "Quarterly (add new real-world examples)"
    },

    "evaluation_pipeline": {
        "offline_eval": """
            For each test event:
              1. Run EventLink pipeline
              2. Compare discovered associations vs gold standard
              3. Calculate precision/recall/F1 per relation type
              4. Generate confusion matrix (which types are confused?)
            Aggregate metrics across all test events
            Report mean ± std deviation
        """,
        "online_eval": """
            Deploy to beta users (N=20)
            Track:
              - Alert display rate
              - User action rate (click/dismiss/confirm/snooze)
              - Explicit feedback (thumbs up/down)
              - Time spent reading alerts
            Calculate user satisfaction score weekly
        """,
        "ab_test": """
            Design: Randomized controlled trial
            Duration: 4 weeks
            Sample size: 100 users (50 control, 50 treatment)
            Primary metric: User retention (Day 7, Day 30)
            Secondary metrics: Meeting prep time, deal closure rate
            Statistical significance: p < 0.05
        """
    },

    "baseline_comparison": {
        "baselines": {
            "random": "Randomly select K associations as alerts",
            "co_occurrence": "Only use co-occurrence frequency",
            "tfidf": "TF-IDF similarity between entity description texts",
            "llm_zero_shot": "Ask LLM directly 'find associations' (no fine-tuning)"
        },
        "success_criteria": "EventLink must outperform ALL baselines on primary metrics with statistical significance"
    }
}
```

**优先级**: P1（Phase 2 开始前必须有基准测试结果）

---

#### 问题 T4: 性能测试基准未定义 [P2]

**问题描述**:
商务人士对响应时间敏感，但文档没有定义性能SLA：

**响应时间目标**（建议值）：

| 操作 | P50 延迟 | P99 延迟 | 超时阈值 |
|------|---------|---------|---------|
| 单 Event 处理（<50实体） | <1s | <3s | 10s |
| 单 Event 处理（50-200实体） | <2s | <5s | 15s |
| 2跳关联查询 | <200ms | <500ms | 2s |
| 3跳关联查询 | <500ms | <2s | 5s |
| 实体搜索（全文检索） | <100ms | <300ms | 1s |
| 图谱导出（DOT格式，<1000节点） | <2s | <5s | 15s |
| 批量导入 100 条 Event | <30s | <60s | 120s |

**吞吐量目标**（建议值）：
- 单用户：最多 50 Event/天（合理使用强度）
- Team 版（10人）：最多 500 Event/天
- 峰值 QPS：10（突发场景）

**资源约束**（MVP 阶段）：
- 内存：<512MB（本地运行）
- CPU：单核占用 <50%（不影响其他应用）
- 磁盘：<1GB（含数据库和索引）
- 网络：仅在调用 LLM API 时需要（Phase 2+）

**负载测试场景**：
- 正常负载：用户平均每天 5 次 Event
- 突发负载：会议高峰期（上午9-11点，下午2-4点）集中 20 次 Event
- 极端负载：批量导入历史数据（一次性 1000 条 Event）

**潜在影响**:
- 性能不达标导致用户放弃
- 无法支撑企业级客户
- 云端版本成本失控

**改进建议**:

```python
# 性能测试套件
PERFORMANCE_TEST_SUITE = {
    "tools": "pytest-benchmark + locust",

    "benchmark_tests": [
        {
            "name": "single_event_processing_small",
            "setup": "Create graph with 50 entities, 100 associations",
            "test": "Process 1 new event with 5 entities",
            "iterations": 100,
            "target_p50": "<1s",
            "target_p99": "<3s"
        },
        {
            "name": "single_event_processing_large",
            "setup": "Create graph with 500 entities, 2000 associations",
            "test": "Process 1 new event with 10 entities",
            "iterations": 50,
            "target_p50": "<2s",
            "target_p99": "<5s"
        },
        {
            "name": "two_hop_query",
            "setup": "Populate graph with realistic data",
            "test": "Query 2-hop associations for a hub entity",
            "iterations": 200,
            "target_p50": "<200ms",
            "target_p99": "<500ms"
        }
    ],

    "load_tests": [
        {
            "name": "normal_daily_load",
            "scenario": "Simulate 1 user, 5 events spread over 8 hours",
            "duration": "8h simulated",
            "target": "No errors, P99 latency within SLA"
        },
        {
            "name": "peak_hour_burst",
            "scenario": "10 events within 10 minutes (meeting marathon)",
            "duration": "15min",
            "target": "Queue depth <5, no dropped events"
        },
        {
            "name": "bulk_import",
            "scenario": "Import 1000 historical events sequentially",
            "duration": "Target <5min total",
            "target": "Zero data loss, reasonable progress indication"
        }
    ],

    "resource_monitoring": {
        "metrics": ["cpu_percent", "memory_usage_mb", "disk_io_bytes", "network_io_bytes"],
        "thresholds": {
            "cpu_percent": {"warn": 70, "critical": 90},
            "memory_usage_mb": {"warn": 384, "critical": 480},  # 512MB limit
            "disk_io_bytes": {"warn": "10MB/s", "critical": "50MB/s"}
        }
    }
}
```

**优先级**: P2（Phase 1 应建立基准，Phase 2 严格执行）

---

### 💻 1.5 开发者视角 (Coder)

#### 问题 C1: LLM 调用的错误处理和降级策略缺失 [P0]

**问题描述**:
Phase 2 核心依赖 LLM 进行实体抽取，但文档未考虑：

**LLM 服务不可用的情况**：
- OpenAI/Anthropic API 宕机（2023年发生过多次）
- 网络连接中断（特别是国内访问海外API）
- API Key 额度用尽或账单问题
- 速率限制触发（Rate Limit 429 Error）

**LLM 输出质量问题**：
- 返回格式不符合 JSON Schema（如缺少必要字段）
- 返回空结果或乱码
- Hallucination（编造不存在的实体或关联）
- 过于冗长或过于简洁

**成本失控风险**：
- 单次 Event 处理成本多少？（Token 用量估算）
- 用户滥用（故意输入超长文本）
- 批量导入历史数据时的成本爆炸

**降级策略**：
- LLM 不可用时，如何保证基本功能可用？
- 是否有备用 LLM 提供商？（如同时支持 OpenAI 和 Anthropic）
- 是否有完全离线的规则引擎作为最后手段？

**潜在影响**:
- 核心功能完全依赖外部服务，可用性无法保证
- 用户体验不一致（有时很准，有时很差）
- 成本不可控导致亏损

**改进建议**:

```python
# LLM 调用容错和降级框架
import json
from abc import ABC, abstractmethod
from typing import Optional
import backoff  # exponential backoff library

class LLMProvider(ABC):
    """LLM Provider 抽象接口"""

    @abstractmethod
    async def extract_entities(self, text: str) -> list[Entity]:
        pass

    @abstractmethod
    def health_check(self) -> bool:
        pass

class OpenAIProvider(LLMProvider):
    def __init__(self, api_key: str, model: str = "gpt-4o-mini"):
        self.client = AsyncOpenAI(api_key=api_key)
        self.model = model

    @backoff.on_exception(
        backoff.expo,
        (openai.RateLimitError, openai.APIConnectionError),
        max_tries=3,
        max_time=30
    )
    async def extract_entities(self, text: str) -> list[Entity]:
        response = await self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": EXTRACTION_PROMPT},
                {"role": "user", "content": text[:4000]}  # 截断过长文本
            ],
            response_format={"type": "json_object"},
            temperature=0.1,  # 低温度提高确定性
            max_tokens=1000
        )

        raw_response = response.choices[0].message.content

        # 严格的 JSON 解析和验证
        try:
            parsed = json.loads(raw_response)
            validated = self.validate_schema(parsed)
            return validated
        except json.JSONDecodeError:
            raise LLMOutputError("Invalid JSON response")
        except ValidationError as e:
            raise LLMOutputError(f"Schema validation failed: {e}")

    def validate_schema(self, data: dict) -> list[Entity]:
        """验证 LLM 输出符合 Entity Schema"""
        entities = []
        for item in data:
            try:
                entity = Entity(
                    entity_type=item["entity_type"],
                    name=item["name"],
                    aliases=item.get("aliases", []),
                    properties=item.get("properties", {})
                )
                entities.append(entity)
            except KeyError as e:
                logging.warning(f"Missing required field {e} in LLM output, skipping entity")
                continue
        return entities


class RuleBasedFallback(LLMProvider):
    """基于规则的降级方案（零LLM依赖）"""

    def __init__(self, dictionary: dict):
        self.dictionary = dictionary  # 预置词典：{关键词: 实体类型}

    async def extract_entities(self, text: str) -> list[Entity]:
        entities = []
        for keyword, entity_type in self.dictionary.items():
            if keyword in text:
                entities.append(Entity(
                    entity_type=entity_type,
                    name=keyword,
                    extraction_method="rule_based"
                ))
        return entities


class ResilientExtractor:
    """带自动降级的实体抽取器"""

    def __init__(self, providers: list[LLMProvider]):
        self.providers = providers  # 按优先级排序
        self.fallback = RuleBasedFallback(load_default_dictionary())

    async def extract_with_fallback(self, text: str) -> tuple[list[Entity], str]:
        """
        尝试多个Provider，失败则降级
        Returns: (entities, provider_used)
        """
        last_error = None

        for provider in self.providers:
            try:
                if await provider.health_check():
                    entities = await provider.extract_entities(text)
                    return entities, provider.__class__.__name__
            except Exception as e:
                last_error = e
                logging.warning(f"Provider {provider.__class__.__name__} failed: {e}")
                continue

        # 所有 LLM Provider 都失败，降级到规则引擎
        logging.error(f"All LLM providers failed, falling back to rule-based. Last error: {last_error}")
        entities = await self.fallback.extract_entities(text)
        return entities, "rule_based_fallback"

    def estimate_cost(self, text: str) -> dict:
        """估算单次调用成本"""
        token_count = len(text.split()) * 1.3  # 粗略估算
        cost_per_1k_tokens = {
            "gpt-4o-mini": 0.00015,  # $0.15/1M tokens
            "gpt-4o": 0.0025,
            "claude-3-haiku": 0.00025
        }
        return {
            "estimated_tokens": token_count,
            "estimated_cost_usd": token_count / 1000 * cost_per_1k_tokens.get(self.model, 0.001)
        }
```

**优先级**: P0（Phase 2 核心功能，必须设计完善）

---

#### 问题 C2: 实体归一的算法复杂度和准确率挑战 [P0]

**问题描述**:
实体归一是整个系统最关键的环节，也是最难做好的：

**算法挑战**：

1. **指代消解 (Coreference Resolution)**：
   - "他"、"她"、"这个人" 指的是谁？
   - "那家公司"、"上次那个供应商" 指的是哪个组织？
   - 需要上下文理解和长距离依赖建模

2. **别名识别 (Alias Detection)**：
   - 正式名 vs 昵称 vs 称呼（"李明" vs "李总" vs "老李"）
   - 中文名 vs 英文名 vs 拼音（"李明" vs "Li Ming" vs "lm"）
   - 简称 vs 全称（"阿里" vs "阿里巴巴集团"）
   - 错别字和OCR错误（"腾讯" vs "腾迅"）

3. **消歧 (Disambiguation)**：
   - "张伟" 是哪个张伟？（中国有约 30万人叫张伟）
   - 需要结合上下文（公司、行业、时间、地理位置）判断

4. **时效性 (Temporal Consistency)**：
   - 人物换公司、换职位、换手机号
   - 组织改名、重组、并购
   - 关系随时间演变（从陌生人→熟人→合作伙伴→竞争对手）

**当前方案的局限性**：
- 文档提到"根据上下文自动判断"，但没有具体算法
- "拿不准的时候会问你一句"——频繁询问会严重影响用户体验
- 没有提到如何利用已有的 CarryMem 记忆辅助归一

**准确率目标**（建议）：
- 简单场景（同名+同公司）：>98%
- 中等场景（同名+不同公司，但有其他线索）：>90%
- 复杂场景（只有昵称，无其他信息）：>75%
- 总体准确率：>90%

**潜在影响**:
- 归一错误会导致连锁反应（错误关联→错误提醒→用户失去信任）
- 用户频繁纠正会挫伤使用积极性
- 这是产品口碑的决定性因素

**改进建议**:

```python
# 多策略实体归一引擎
class MultiStrategyEntityResolver:

    def __init__(self, graph: EntityGraph, memory_adapter: MemoryLayerAdapter):
        self.graph = graph
        self.memory = memory_adapter
        self.strategies = [
            ExactMatchStrategy(),           # 策略1: 精确匹配
            AliasDictionaryStrategy(),       # 策略2: 别名字典
            ContextualSimilarityStrategy(),  # 策略3: 上下文相似度
            MemoryAssistedStrategy(),        # 策略4: CarryMem 记忆辅助
            LLMDisambiguationStrategy()      # 策略5: LLM 消歧（最后手段）
        ]

    async def resolve(self, new_entity: Entity, context: Event) -> ResolvedEntity:
        """
        多策略级联归一
        """
        candidates = []

        # 策略1: 精确名称匹配
        exact_matches = self.graph.find_by_name(new_entity.name)
        candidates.extend(exact_matches)

        if not candidates:
            # 策略2: 别名字典查找
            alias_matches = self.alias_dict.lookup(new_entity.name)
            candidates.extend(alias_matches)

        if not candidates:
            # 策略3: 上下文相似度（公司/行业/时间）
            similar = self.contextual_similarity.search(
                entity=new_entity,
                context=context,
                threshold=0.85
            )
            candidates.extend(similar)

        if len(candidates) == 0:
            # 无候选，创建新实体
            return ResolvedEntity(entity=new_entity, status="new", confidence=1.0)

        elif len(candidates) == 1:
            # 唯一候选，检查置信度
            confidence = self.calculate_confidence(new_entity, candidates[0], context)
            if confidence > 0.95:
                return ResolvedEntity(entity=candidates[0], status="merged", confidence=confidence)
            else:
                # 策略4: CarryMem 记忆辅助确认
                memory_evidence = self.memory.query_relationships(candidates[0].id)
                if memory_evidence.confirms_match(new_entity, context):
                    return ResolvedEntity(entity=candidates[0], status="merged", confidence=confidence)
                else:
                    # 策略5: LLM 消歧（昂贵，慎用）
                    llm_decision = await self.llm_disambiguate(new_entity, candidates, context)
                    return llm_decision
        else:
            # 多个候选，需要消歧
            ranked = self.rank_candidates(new_entity, candidates, context)
            if ranked[0].confidence > 0.9 and ranked[0].confidence - ranked[1].confidence > 0.2:
                # 显著优于其他候选
                return ranked[0]
            else:
                # 歧义较大，请求用户确认（或暂不合并）
                return ResolvedEntity(
                    entity=new_entity,
                    status="pending_confirmation",
                    candidates=candidates
                )


class AliasDictionary:
    """可学习的别名字典"""

    def __init__(self):
        # 预置常见别名规则
        self.rules = {
            "suffix_patterns": [
                (r"(.+)总$", r"\1"),  # "李总" → "李"
                (r"(.+)工$", r"\1"),  # "王工" → "王"
                (r"(.+)姐$", r"\1"),  # "张姐" → "张"
                (r"老(.+)$", r"\1"),  # "老李" → "李"
                (r"小(.+)$", r"\1"),  # "小王" → "王"
            ],
            "organization_abbreviations": {
                "阿里": "阿里巴巴集团",
                "腾讯": "腾讯控股有限公司",
                "字节": "字节跳动科技有限公司",
                "华为": "华为技术有限公司",
            },
            "english_variants": {
                "Li Ming": ["李明", "lm", "li.ming"]
            }
        }

    def lookup(self, name: str) -> list[Entity]:
        """查找别名的规范形式"""
        results = []

        # 应用后缀规则
        canonical_name = name
        for pattern, replacement in self.rules["suffix_patterns"]:
            match = re.match(pattern, name)
            if match:
                canonical_name = replacement.format(match.group(1))
                break

        # 查找组织简称
        if canonical_name in self.rules["organization_abbreviations"]:
            full_name = self.rules["organization_abbreviations"][canonical_name]
            results.extend(self.graph.find_by_name(full_name))

        # 查找英文名变体
        if canonical_name.lower() in self.rules["english_variants"]:
            variants = self.rules["english_variants"][canonical_name.lower()]
            for variant in variants:
                results.extend(self.graph.find_by_name(variant))

        return results

    def learn_from_feedback(self, alias: str, canonical: str):
        """从用户反馈学习新别名"""
        self.rules["learned_aliases"][alias] = canonical
        self.save_to_disk()  # 持久化
```

**优先级**: P0（这是核心技术难点，需要投入最多研发资源）

---

#### 问题 C3: 多跳查询的性能优化方案缺失 [P1]

**问题描述**:
文档第 7.3 节展示了多跳查询的 SQL 示例，但承认"SQL 写稍显繁琐"。实际问题是：

**性能问题**：
- 2 跳查询：1 次 JOIN（可接受）
- 3 跳查询：2 次 JOIN + 子查询（较慢）
- 4 跳查询：3 次 JOIN（可能很慢）
- 路径查找（A 到 B 的最短路径）：SQL 表达极其困难

**功能缺失**：
- 如何找出"两个实体之间的所有路径"？
- 如何计算"实体的中心度"（谁是最重要的连接者）？
- 如何发现"社区结构"（哪些人形成一个紧密圈子）？
- 如何做"子图匹配"（找到与给定模式匹配的子图）？

**索引优化**：
- 当前索引：source/target/type/status
- 缺少索引：复合索引（source+type）、覆盖索引、全文索引
- 是否需要物化视图（预计算常用的多跳结果）？

**潜在影响**:
- 复杂查询导致用户体验差
- 无法支持高级分析功能（如"影响力分析"）
- 技术债务累积

**改进建议**:

```python
# 多跳查询优化方案
class OptimizedGraphQueries:

    def __init__(self, db_conn):
        self.db = db_conn
        self._create_optimized_indexes()

    def _create_optimized_indexes(self):
        """创建优化的索引组合"""
        indexes = [
            "CREATE INDEX IF NOT EXISTS idx_assoc_composite ON associations(source_entity, relation_type, strength DESC)",
            "CREATE INDEX IF NOT EXISTS idx_assoc_reverse ON associations(target_entity, relation_type)",
            "CREATE INDEX IF NOT EXISTS idx_entities_fulltext USING fts5(name, aliases, properties)",
            "CREATE INDEX IF NOT EXISTS idx_events_composite ON events(timestamp, event_type)"
        ]
        for idx_sql in indexes:
            self.db.execute(idx_sql)

    def k_hop_neighbors(self, entity_id: str, k: int, relation_types: list[str] = None) -> dict:
        """
        优化的 K 跳邻居查询
        使用迭代深化 + BFS 避免重复计算
        """
        visited = {entity_id}
        current_frontier = [entity_id]
        result = {0: [entity_id]}

        for hop in range(1, k + 1):
            next_frontier = []
            placeholders = ','.join(['?' for _ in current_frontier])

            type_filter = ""
            params = current_frontier[:]
            if relation_types:
                type_filter = "AND relation_type IN ({})".format(
                    ','.join(['?' for _ in relation_types])
                )
                params.extend(relation_types)

            sql = f"""
                SELECT DISTINCT a.target_entity, a.relation_type, a.strength
                FROM associations a
                WHERE a.source_entity IN ({placeholders})
                  AND a.status = 'active'
                  {type_filter}
            """

            rows = self.db.execute(sql, params).fetchall()

            for target_id, rel_type, strength in rows:
                if target_id not in visited:
                    visited.add(target_id)
                    next_frontier.append(target_id)

            current_frontier = next_frontier
            result[hop] = current_frontier

            if not current_frontier:
                break  # 无更多邻居

        return result

    def shortest_path(self, source_id: str, target_id: str, max_depth: int = 5) -> list:
        """
        BFS 最短路径查找
        """
        from collections import deque

        queue = deque([(source_id, [source_id])])
        visited = {source_id}

        while queue:
            current_node, path = queue.popleft()

            if len(path) > max_depth:
                continue

            if current_node == target_id:
                return path

            neighbors = self.db.execute("""
                SELECT target_entity FROM associations
                WHERE source_entity = ? AND status = 'active'
            """, (current_node,)).fetchall()

            for (neighbor,) in neighbors:
                if neighbor not in visited:
                    visited.add(neighbor)
                    queue.append((neighbor, path + [neighbor]))

        return []  # 无路径

    def centrality_analysis(self, entity_id: str) -> dict:
        """
        中心性分析（找出重要连接者）
        """
        # Degree centrality（度中心性）
        degree_out = self.db.execute("""
            SELECT COUNT(*) FROM associations WHERE source_entity = ? AND status = 'active'
        """, (entity_id,)).fetchone()[0]

        degree_in = self.db.execute("""
            SELECT COUNT(*) FROM associations WHERE target_entity = ? AND status = 'active'
        """, (entity_id,)).fetchone()[0]

        # Betweenness centrality（介数中心性）- 近似算法
        betweenness = self.approximate_betweenness(entity_id, sample_size=100)

        return {
            "degree_centrality": degree_out + degree_in,
            "betweenness_centrality": betweenness,
            "is_hub": (degree_out + degree_in) > 20  # 阈值可配置
        }

    def community_detection(self, min_size: int = 3) -> list[list[str]]:
        """
        社区检测（发现紧密圈子）
        使用简单的连通分量算法
        """
        import networkx as nx

        # 构建子图（仅加载必要数据）
        G = nx.Graph()
        rows = self.db.execute("""
            SELECT source_entity, target_entity, strength
            FROM associations
            WHERE status = 'active' AND strength > 0.5
        """).fetchall()

        for src, tgt, weight in rows:
            G.add_edge(src, tgt, weight=weight)

        # 连通分量
        communities = list(nx.connected_components(G))

        # 过滤小社区
        large_communities = [list(c) for c in communities if len(c) >= min_size]

        return large_communities
```

**Phase 1-2 使用 SQL 优化**（上面的代码）
**Phase 3+ 考虑引入图数据库**（如 Neo4j Community Edition 或 ArangoDB）

**优先级**: P1（Phase 2 需要优化，Phase 3 可能需要引入图数据库）

---

#### 问题 C4: 代码可维护性和测试性设计不足 [P2]

**问题描述**:
当前文档主要是数据模型和算法描述，缺少工程实践指导：

**模块划分**：
- 代码应该如何组织？Monorepo 还是 Multi-repo？
- 目录结构建议？（src/eventlink/{extract,resolve,associate,alert,persist}）
- 公共工具函数放在哪里？

**接口设计**：
- 模块间的接口契约是什么？（Protocol/Abstract Base Class）
- 如何方便地替换单个组件（如替换 LLM Provider）？
- 依赖注入如何实现？

**配置管理**：
- 配置文件格式？（YAML/TOML/ENV）
- 敏感配置（API Key）如何分离？
- 环境区分（dev/staging/prod）？

**日志和监控**：
- 日志级别和格式规范？
- 关键操作的结构化日志？
- 性能埋点（处理耗时、队列深度等）？

**错误处理**：
- 自定义异常层级？
- 用户友好的错误消息？
- 错误码标准化？

**潜在影响**:
- 代码混乱导致维护困难
- 新开发者上手慢
- Bug 修复引入新 Bug

**改进建议**:

```
推荐的目录结构：
eventlink/
├── src/
│   ├── __init__.py
│   ├── core/
│   │   ├── models.py          # 数据模型 (Event, Entity, Association, Alert)
│   │   ├── config.py          # 配置管理
│   │   ├── exceptions.py      # 自定义异常
│   │   └── constants.py       # 常量定义
│   ├── extract/
│   │   ├── base.py            # 抽象基类
│   │   ├── llm_extractor.py   # LLM 实现
│   │   ├── rule_extractor.py  # 规则实现
│   │   └── prompts.py         # Prompt 模板
│   ├── resolve/
│   │   ├── base.py
│   │   ├── exact_match.py
│   │   ├── alias_dictionary.py
│   │   └── llm_disambiguate.py
│   ├── associate/
│   │   ├── discovery.py       # 关联发现逻辑
│   │   ├── strength.py        # 强度计算
│   │   └── temporal.py        # 时间衰减
│   ├── alert/
│   │   ├── generator.py       # 提醒生成
│   │   ├── templates.py       # 提醒模板
│   │   └── filters.py         # 过滤规则
│   ├── persist/
│   │   ├── database.py        # SQLite 操作
│   │   ├── migrations.py      # 数据库迁移
│   │   └── backup.py          # 备份恢复
│   └── integrations/
│       ├── carrymem_adapter.py
│       ├── calendar_sync.py
│       └── crm_connector.py
├── tests/
│   ├── unit/
│   ├── integration/
│   ├── performance/
│   └── fixtures/
├── docs/
│   ├── architecture.md
│   ├── api_reference.md
│   └── contributing.md
├── pyproject.toml
├── README.md
└── .github/workflows/
    └── ci.yml
```

**优先级**: P2（Phase 1 开始时应建立工程规范）

---

### ⚙️ 1.6 运维视角 (DevOps)

#### 问题 D1: 本地部署复杂性如何降低 [P1]

**问题描述**:
目标用户是商务人士，不是开发者。当前方案要求：
- Python 环境（安装 Python 3.10+）
- pip 安装依赖
- 可能需要编译某些 C 扩展（如 SQLCipher）
- 配置环境变量或配置文件
- 命令行操作

**这对非技术用户来说门槛极高**。

**潜在影响**:
- 用户在安装阶段就放弃
- 技术支持成本高昂
- 限制了用户群体

**改进建议**:

**方案 A: 打包为 standalone 应用（推荐）**

```bash
# 使用 PyInstaller 或 cx_Freeze 打包
pip install pyinstaller
pyinstaller --onefile --windowed --name "EventLink" cli.py

# 生成：
# macOS: EventLink.app (双击即可运行)
# Windows: EventLink.exe
# Linux: EventLink (二进制文件)
```

**方案 B: Docker 容器化（针对稍高级用户）**

```dockerfile
FROM python:3.11-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .

ENTRYPOINT ["python", "-m", "eventlink.cli"]

# 用户只需：
# docker build -t eventlink .
# docker run -v ~/.eventlink:/data eventlink add-event ...
```

**方案 C: Web 安装器（最友好）**

提供一个简单的安装脚本/网页：
1. 下载适用于对应平台的安装包
2. 运行安装向导（图形界面）
3. 设置初始密码
4. 完成！桌面快捷方式已创建

**优先级**: P1（Phase 1 必须提供简易安装方式）

---

#### 问题 D2: 数据备份和恢复策略 [P1]

**问题描述**:
用户的 EventLink 数据包含宝贵的人脉和关联信息，丢失将是灾难性的：

**备份需求**：
- 自动备份（每天？每周？）
- 手动备份触发
- 备份加密（包含敏感信息）
- 备份版本管理（保留最近N个版本）
- 备份完整性校验（SHA256 哈希）

**恢复场景**：
- 电脑损坏/丢失，在新设备恢复
- 误删重要数据，回滚到之前的状态
- 数据库损坏（SQLite corruption）
- 升级到新版本后数据不兼容

**跨设备同步**（后续需求）：
- 手机和平板电脑也能访问数据
- 多台电脑间保持同步
- 冲突解决（两台电脑同时修改了同一实体）

**潜在影响**:
- 数据丢失导致用户彻底放弃产品
- 无法跨设备使用限制了使用场景
- 企业客户要求备份和灾备能力

**改进建议**:

```python
# 数据备份恢复系统
class BackupManager:

    def __init__(self, data_dir: str, backup_dir: str):
        self.data_dir = Path(data_dir)
        self.backup_dir = Path(backup_dir)
        self.backup_dir.mkdir(exist_ok=True)

    def create_backup(self, backup_type: str = "full") -> BackupMetadata:
        """
        创建备份
        """
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_filename = f"eventlink_backup_{timestamp}.zip"

        # 1. 暂停写入（获取一致快照）
        self.acquire_write_lock()

        try:
            # 2. 复制数据库文件
            db_file = self.data_dir / "eventlink.db"
            temp_copy = db_file.with_suffix('.tmp')
            shutil.copy2(db_file, temp_copy)

            # 3. 加密压缩
            with zipfile.ZipFile(self.backup_dir / backup_filename, 'w', zipfile.ZIP_DEFLATED) as zf:
                zf.write(temp_copy, arcname='eventlink.db')

                # 添加元数据
                metadata = {
                    "version": get_version(),
                    "created_at": timestamp,
                    "db_size_bytes": temp_copy.stat().st_size,
                    "sha256_hash": self.calculate_sha256(temp_copy),
                    "entity_count": self.count_entities(),
                    "event_count": self.count_events()
                }
                zf.writestr('metadata.json', json.dumps(metadata, indent=2))

            # 4. 清理临时文件
            temp_copy.unlink()

            # 5. 保留最近 N 个备份
            self.cleanup_old_backups(keep_recent=10)

            return BackupMetadata(**metadata)

        finally:
            self.release_write_lock()

    def restore_backup(self, backup_path: str, confirm: bool = False):
        """
        从备份恢复
        """
        if not confirm:
            raise ConfirmationRequiredError("Please confirm restore operation (destructive!)")

        # 1. 验证备份完整性
        metadata = self.validate_backup(backup_path)

        # 2. 创建当前状态的紧急备份（以防万一）
        emergency_backup = self.create_backup(type="pre_restore")

        # 3. 停止服务
        self.stop_service()

        try:
            # 4. 解压并替换数据库
            with zipfile.ZipFile(backup_path, 'r') as zf:
                zf.extractall(self.data_dir)

            # 5. 验证恢复后的数据库
            if not self.verify_database_integrity():
                raise RestoreFailedError("Database integrity check failed")

            # 6. 记录恢复事件
            self.log_audit_event("backup_restored", {
                "backup_version": metadata["version"],
                "restored_at": datetime.now().isoformat()
            })

        except Exception as e:
            # 恢复失败，回滚到紧急备份
            self.restore_backup(emergency_backup.path, confirm=True)
            raise RestoreFailedError(f"Restore failed, rolled back: {e}")

        finally:
            self.start_service()

    def setup_automatic_backup(self, schedule: str = "daily"):
        """
        配置自动备份
        """
        if schedule == "daily":
            # 使用系统调度器（cron/Task Scheduler）
            schedule_entry = f"0 2 * * * eventlink backup create"  # 每天凌晨2点
            self.add_cron_job(schedule_entry)
        elif schedule == "weekly":
            schedule_entry = "0 2 * * 0 eventlink backup create"  # 每周日凌晨2点
            self.add_cron_job(schedule_entry)
```

**优先级**: P1（Phase 1 必须实现基础备份功能）

---

#### 问题 D3: 监控和告警机制设计 [P2]

**问题描述**:
即使是本地运行的应用，也需要基本的监控：

**健康检查**：
- 数据库连接正常？
- 磁盘空间充足？（<80%使用率）
- 内存使用正常？
- 最后一次成功处理 Event 是什么时候？

**性能监控**：
- Event 处理延迟趋势
- 数据库查询耗时分布
- LLM API 调用成功率
- 错误率和异常类型分布

**用户行为分析（匿名）**：
- 日活用户数（DAU）
- 平均每人每天录入 Event 数
- 提醒查看率和互动率
- 功能使用热力图

**告警通知**：
- 磁盘空间不足 90%
- 连续 3 次 LLM 调用失败
- 数据库查询超时 >10s
- 未处理的错误堆积 >10 个

**潜在影响**:
- 问题发现滞后（用户先报 bug 才知道）
- 性能退化无人察觉
- 无法做数据驱动的产品改进

**改进建议**:

```python
# 轻量级监控系统
class LocalMonitor:

    def __init__(self):
        self.metrics = MetricsCollector()
        self.alert_manager = AlertManager()

    def health_check(self) -> HealthStatus:
        """系统健康检查"""
        checks = {
            "database_connection": self.check_db_connection(),
            "disk_space": self.check_disk_space(threshold_gb=5),
            "memory_usage": self.check_memory_usage(threshold_mb=400),
            "last_successful_processing": self.check_last_processing(max_age_hours=24)
        }

        all_healthy = all(checks.values())
        return HealthStatus(
            healthy=all_healthy,
            checks=checks,
            timestamp=datetime.now()
        )

    def record_metrics(self, metric_name: str, value: float, tags: dict = None):
        """记录指标"""
        self.metrics.record(metric_name, value, tags)

        # 关键指标的自动告警
        ALERT_THRESHOLDS = {
            "event_processing_latency_seconds": {"warn": 3.0, "critical": 10.0},
            "llm_api_error_rate": {"warn": 0.1, "critical": 0.5},
            "disk_usage_percent": {"warn": 80, "critical": 95},
            "memory_usage_mb": {"warn": 384, "critical": 480}
        }

        if metric_name in ALERT_THRESHOLDS:
            thresholds = ALERT_THRESHOLDS[metric_name]
            if value >= thresholds["critical"]:
                self.alert_manager.send_alert(
                    level="critical",
                    message=f"{metric_name} = {value} exceeds critical threshold {thresholds['critical']}"
                )
            elif value >= thresholds["warn"]:
                self.alert_manager.send_alert(
                    level="warning",
                    message=f"{metric_name} = {value} exceeds warning threshold {thresholds['warn']}"
                )

    def generate_report(self, period: str = "daily") -> str:
        """生成监控报告"""
        report = f"""
        # EventLink Monitoring Report ({period})

        ## System Health
        - Uptime: {self.calculate_uptime(period)}%
        - Health Checks Passed: {self.health_check_pass_rate()}%

        ## Performance
        - Avg Event Processing Latency: {self.avg_metric('event_processing_latency_seconds')}s
        - P99 Latency: {self.p99_metric('event_processing_latency_seconds')}s
        - LLM API Success Rate: {self.avg_metric('llm_api_success_rate')}%

        ## Usage Statistics
        - Events Processed: {self.sum_metric('events_processed')}
        - Entities Created: {self.sum_metric('entities_created')}
        - Alerts Generated: {self.sum_metric('alerts_generated')}
        - User Interaction Rate: {self.avg_metric('alert_interaction_rate')}%

        ## Errors
        - Total Errors: {self.sum_metric('errors_total')}
        - Top Error Types: {self.top_errors(5)}

        Generated at: {datetime.now()}
        """
        return report
```

**优先级**: P2（Phase 2 应实现基础监控）

---

### 🎨 1.7 UI/UX 设计师视角 (UI Designer)

#### 问题 U1: CLI 交互体验对非技术用户不友好 [P0]

**问题描述**:
当前设计的唯一交互方式是 CLI 命令行，例如：

```bash
carrymem add-event --type meeting --title "与李总聊IoT" --text "会议纪要内容..."
carrymem entity-graph "李总" --depth 2
carrymem alerts
```

**这对商务人士来说极其不友好**：
- 需要记住命令和参数
- 需要熟悉终端操作
- 错误信息不直观
- 无法可视化展示复杂数据（如图谱）

**潜在影响**:
- 目标用户根本不会使用
- 产品价值无法传达
- 早期用户全是开发者，偏离目标市场

**改进建议**:

**方案 A: 交互式 TUI（Terminal UI）（推荐用于 MVP）**

使用 `rich` 或 `textual` 库创建美观的终端界面：

```python
from textual.app import App, ComposeResult
from textual.widgets import Header, Footer, Static, ListView, ListItem
from textual.containers import Container

class EventLinkApp(App):
    """EventLink Terminal UI"""

    CSS = """
    Screen {
        layout: vertical;
    }
    #main_area {
        layout: horizontal;
        height: 1fr;
    }
    #sidebar {
        width: 25%;
        dock: left;
        background: $surface;
    }
    #content {
        width: 75%;
    }
    """

    def compose(self) -> ComposeResult:
        yield Header()
        yield Container(
            Container(id="sidebar",Static("[bold]导航[/bold]\n\n1. 今日提醒\n2. 录入会议\n3. 搜索实体\n4. 查看图谱\n5. 设置")),
            Container(id="content",Static("欢迎使用 EventLink！\n\n左侧菜单选择功能开始使用。"))
        )
        yield Footer()

    def on_list_view_selected(self, event: ListView.Selected):
        item = event.item
        if item.id == "alerts":
            self.show_alerts()
        elif item.id == "add_event":
            self.show_add_event_form()
        # ...

    def show_add_event_form(self):
        """交互式表单录入 Event"""
        self.query_one("#content").update("""
        [bold]录入新事件[/bold]

        📅 日期时间: [2026-05-31 14:00]
        👥 参与人: （输入名字，回车分隔）
        🏢 相关公司:
        💬 会议内容: （自由文本）
        
        [dim]按 Tab 切换字段，Enter 提交[/dim]
        """)
```

**方案 B: 简单 Web UI（单 HTML 文件）**

```html
<!-- eventlink.html -->
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>EventLink</title>
    <style>
        body { font-family: -apple-system, sans-serif; margin: 40px; }
        .container { max-width: 800px; margin: 0 auto; }
        .card { border: 1px solid #ddd; padding: 20px; margin: 20px 0; border-radius: 8px; }
        button { background: #007AFF; color: white; padding: 10px 20px; border: none; border-radius: 5px; cursor: pointer; }
        input, textarea { width: 100%; padding: 10px; margin: 10px 0; border: 1px solid #ddd; border-radius: 5px; }
    </style>
</head>
<body>
    <div class="container">
        <h1>✨ EventLink</h1>
        <p>发现你看不见的商脉关联</p>

        <div class="card">
            <h2>📝 录入会议</h2>
            <form id="eventForm">
                <input type="datetime-local" placeholder="时间">
                <input type="text" placeholder="参与者（逗号分隔）">
                <input type="text" placeholder="公司名称">
                <textarea rows="5" placeholder="会议内容..."></textarea>
                <button type="submit">提交</button>
            </form>
        </div>

        <div class="card">
            <h2>🔔 今日提醒</h2>
            <div id="alerts">加载中...</div>
        </div>
    </div>

    <script>
        // 通过 HTTP API 与后端通信
        document.getElementById('eventForm').addEventListener('submit', async (e) => {
            e.preventDefault();
            const formData = new FormData(e.target);
            const response = await fetch('/api/events', { method: 'POST', body: formData });
            const result = await response.json();
            alert(`✅ 事件已录入，发现 ${result.alerts_count} 条关联！`);
        });
    </script>
</body>
</html>
```

**方案 C: 桌面应用（Electron/Tauri）**（Phase 3+）

**优先级**: P0（MVP 必须提供比纯 CLI 更友好的界面）

---

#### 问题 U2: 可视化方案不足以满足需求 [P1]

**问题描述**:
当前可视化方案：
1. CLI 文本输出（ASCII art）
2. Graphviz DOT 导出（需额外安装 Graphviz）
3. 后续：Web 仪表盘（Phase 4）

**问题**：
- ASCII art 在实体多的时候不可读
- Graphviz 对普通用户来说太技术化
- 等到 Phase 4 才有好的可视化太晚了

**需要的可视化**：
- **实体卡片**：点击实体查看详细信息（属性、关联、相关Event）
- **关联图谱**：力导向布局，可缩放、可拖拽、可筛选
- **时间线视图**：按时间展示 Event 和关联演化
- **提醒列表**：分组、排序、筛选、批量操作
- **统计仪表板**：实体总数、关联密度、活跃度趋势

**潜在影响**:
- 用户无法直观理解系统的产出
- 价值感知降低（"到底发现了什么？"）
- 无法吸引非技术用户

**改进建议**:

```python
# 使用 PyVis 生成交互式 HTML 图谱（可在浏览器打开）
from pyvis.network import Network

def create_interactive_graph(entities: list, associations: list, output_file: str = "graph.html"):
    """
    生成交互式关联图谱
    """
    net = Network(height="750px", width="100%", bgcolor="#ffffff", font_color="black")

    # 添加节点（按类型着色）
    color_map = {
        "person": "#3498db",      # 蓝色
        "organization": "#e74c3c", # 红色
        "technology": "#2ecc71",   # 绿色
        "project": "#f39c12",      # 橙色
        "attribute": "#9b59b6"     # 紫色
    }

    for entity in entities:
        net.add_node(
            n_id=entity.id,
            label=entity.name,
            title=f"{entity.name}\n{entity.entity_type}\n{json.dumps(entity.properties, ensure_ascii=False)}",
            color=color_map.get(entity.entity_type, "#95a5a6"),
            size=15 + entity.mention_count * 2,  # 节点大小反映活跃度
            shape="dot"
        )

    # 添加边（按类型选择样式）
    edge_style_map = {
        "tech_overlap": {"color": "#3498db", "width": 2, "dashes": False},
        "competitor": {"color": "#e74c3c", "width": 3, "dashes": True},
        "deal_link": {"color": "#2ecc71", "width": 2, "dashes": False},
        "risk_link": {"color": "#e74c3c", "width": 2, "dashes": True},
        "ex_colleague": {"color": "#f39c12", "width": 1, "dashes": False},
        "alumni": {"color": "#9b59b6", "width": 1, "dashes": False}
    }

    for assoc in associations:
        style = edge_style_map.get(assoc.relation_type, {"color": "#95a5a6"})
        net.add_edge(
            source=assoc.source_entity,
            target=assoc.target_entity,
            title=f"{assoc.relation_type}\n强度: {assoc.strength:.2f}",
            value=assoc.strength * 5,  # 边粗细反映强度
            **style
        )

    # 物理参数
    net.force_atlas_2based(gravity=-50, central_gravity=0.01, spring_length=200)

    # 保存为 HTML
    net.save_graph(output_file)
    print(f"✅ 交互式图谱已保存到 {output_file}，用浏览器打开即可查看")

# 使用示例
create_interactive_graph(entities, associations, "./my_graph.html")
```

**优先级**: P1（Phase 1 应提供基础可视化，Phase 2 增强交互性）

---

#### 问题 U3: 提醒展示的最佳实践缺失 [P1]

**问题描述**:
前面产品经理视角已经提到提醒策略问题，这里从 UI/UX 角度补充：

**视觉层次**：
- 如何让高风险提醒一眼就能看到？（颜色？图标？位置？大小？）
- 如何避免视觉噪音？（太多提醒导致"公告栏效应"）
- 如何平衡信息密度和可读性？

**交互设计**：
- 用户看到提醒后应该做什么？（一键操作？展开详情？跳转相关Event？）
- 如何快速批量处理提醒？（全读/全忽略/按类型批量操作）
- 提醒的历史记录如何展示？（搜索？筛选？归档？）

**移动端考虑**（即使 MVP 是桌面端）：
- 提醒是否需要推送到手机？（短信？微信？App Push？）
- 小屏幕上的提醒卡片设计？
- 单手操作优化？

**无障碍访问 (Accessibility)**：
- 色盲用户如何区分提醒类型？（不仅依靠颜色）
- 屏幕阅读器如何朗读提醒内容？
- 键盘导航支持？

**潜在影响**:
- 提醒 UI 差导致用户忽视重要信息
- 移动端缺失限制使用场景
- 无障碍问题导致用户群体受限

**改进建议**:

```python
# 提醒 UI 组件规范
ALERT_UI_COMPONENTS = {
    "alert_card": {
        "layout": """
        ┌─────────────────────────────────────┐
        │ 🔴 [ICON]  [TITLE]            [TIME] │
        ├─────────────────────────────────────┤
        │ [DETAIL TEXT - 2-3 lines max]      │
        │                                     │
        │ 💡 [ACTION SUGGESTION]              │
        │                                     │
        │ [✓ 确认] [✕ 忽略] [⏰ 稍后提醒]    │
        └─────────────────────────────────────┘
        """,
        "colors": {
            "opportunity": {"bg": "#E8F5E9", "border": "#4CAF50", "icon": "🟢"},
            "risk": {"bg": "#FFEBEE", "border": "#F44336", "icon": "🔴"},
            "context": {"bg": "#E3F2FD", "border": "#2196F3", "icon": "🔵"}
        },
        "animations": {
            "new_alert": "slide-in + subtle pulse (once)",
            "hover": "slight scale up + shadow deepen"
        },
        "accessibility": {
            "aria_labels": True,
            "keyboard_shortcuts": {
                "j/k": "navigate up/down",
                "enter": "expand details",
                "c": "confirm alert",
                "d": "dismiss alert"
            },
            "screen_reader_text": "{alert_type}: {title}. {detail}. Suggested action: {action_suggestion}"
        }
    },

    "alert_list": {
        "layout": "grouped by type, sorted by priority desc, time desc",
        "features": [
            "filter_bar (by type/status/time_range)",
            "search_box",
            "bulk_actions_toolbar (select_all/mark_read/dismiss_selected)",
            "pagination (20 items/page)",
            "unread_badge (count)"
        ]
    },

    "mobile_alert_card": {
        "layout": """
        ┌──────────────┐
        │ 🔴 [TITLE]  │
        │ [1-line detail] │
        │ [Swipe right → dismiss] │
        │ [Swipe left → confirm] │
        └──────────────┘
        """,
        "gestures": {
            "swipe_right": "dismiss (with animation)",
            "swipe_left": "confirm & save to notes",
            "long_press": "expand to full card",
            "pull_down": "refresh list"
        }
    }
}
```

**优先级**: P1（Phase 1 必须设计提醒 UI，Phase 2 增强移动端）

---

## 二、跨角色共识的高优先级问题 (Top 12)

基于以上 7 个角色的评审，我们识别出以下 **12 个最高优先级问题**（按紧迫性排序）：

### 🔴 P0 级别（必须在 Phase 1 前解决）

| # | 问题 | 涉及角色 | 核心风险 | 建议行动 |
|---|------|---------|---------|---------|
| 1 | **目标用户画像不清晰** | PM | 做错产品 | 立即开展用户访谈（5-10位目标用户），输出详细用户画像和使用场景 |
| 2 | **冷启动和数据纠错场景缺失** | PM | 用户早期流失 | 设计完整的 onboarding 流程和反馈回路 |
| 3 | **SQLite 扩展性瓶颈未解决** | Architect | 性能灾难 | 确定 Phase 1-3 的技术路线（缓存→networkx→Neo4j） |
| 4 | **数据一致性保证机制缺失** | Architect | 数据混乱 | 实现 Saga 事务模式和失败回滚 |
| 5 | **本地数据安全措施不足** | Security | 数据泄露 | 实现 SQLCipher 加密 + 安全删除 + 权限控制 |
| 6 | **LLM 调用容错和降级策略缺失** | Coder | 核心不可用 | 设计多 Provider + 规则引擎降级方案 |
| 7 | **实体归一算法准确率挑战** | Coder | 产品核心失效 | 投入研发资源，设计多策略级联归一引擎 |
| 8 | **测试策略完全缺失** | Tester | 质量失控 | 制定分层测试计划和准确性评估框架 |
| 9 | **CLI 对非技术用户不友好** | UI Designer | 用户无法使用 | 提供 TUI 或简单 Web UI 作为主要交互方式 |

### 🟡 P1 级别（Phase 1-2 期间解决）

| # | 问题 | 涉及角色 | 核心风险 | 建议行动 |
|---|------|---------|---------|---------|
| 10 | **提醒体验细节不足** | PM/UI | 用户打扰或忽视 | 设计完整的提醒时机/渠道/内容规范 |
| 11 | **商业模式可持续性存疑** | PM | 资金断裂 | 确定定价策略和与许总的合作模式 |
| 12 | **安装部署复杂性高** | DevOps | 用户放弃 | 提供打包好的 standalone 应用或 Docker 镜像 |

---

## 三、具体的改进建议和行动项

### 📌 Phase 0：设计补完期（2-4 周）

**目标**：在写第一行代码前，补全所有缺失的设计文档

#### 行动项清单

- [ ] **AR-01**: 完成目标用户调研（访谈 5-10 位潜在用户）
  - 输出：用户画像 x3（主要/次要/边缘）
  - 输出：用户旅程地图（从接触到熟练使用）
  - 负责人：产品经理
  - 截止：Week 1

- [ ] **AR-02**: 设计冷启动 onboarding 流程
  - 输出：线框图/原型（5-10屏）
  - 输出：冷启动数据导入工具设计
  - 负责人：UI设计师 + 产品经理
  - 截止：Week 2

- [ ] **AR-03**: 完成技术架构设计文档 v2.0
  - 补充：数据一致性机制（Saga/2PC）
  - 补充：性能基准和扩展路线图
  - 补充：错误处理和降级策略
  - 输出：架构文档 + 序列图 + 数据流图
  - 负责人：架构师
  - 截止：Week 2

- [ ] **AR-04**: 完成安全设计文档
  - 补充：本地安全加固方案（加密/访问控制/审计日志）
  - 补充：云端安全架构（Phase 4 预研）
  - 补充：GDPR/PIPL 合规检查清单
  - 输出：安全白皮书 + 合规矩阵
  - 负责人：安全专家
  - 截止：Week 2

- [ ] **AR-05**: 制定测试策略和 QA 计划
  - 输出：测试金字塔（单元/集成/性能/准确性）
  - 输出：金标准数据集构建计划
  - 输出：CI/CD 流水线设计
  - 负责人：测试专家
  - 截止：Week 2

- [ ] **AR-06**: 确定商业模式和定价
  - 输出：定价方案（Freemium/Pro/Team 三档）
  - 输出：与许总的合作协议草案
  - 输出：18个月财务预测（乐观/中性/悲观）
  - 负责人：产品经理 + 商务
  - 截止：Week 3

- [ ] **AR-07**: 设计 MVP 交互原型
  - 输出：可交互的原型（Figma/Axure）
  - 覆盖：Event 录入、提醒查看、实体搜索、图谱浏览
  - 输出：用户测试脚本和评估问卷
  - 负责人：UI设计师
  - 截止：Week 3

- [ ] **AR-08**: 编写实体归一技术方案
  - 输出：算法选型报告（规则/ML/LLM 对比）
  - 输出：准确率目标和评估方法
  - 输出：MVP 阶段的简化方案（牺牲准确率换速度）
  - 负责人：开发者 + 架构师
  - 截止：Week 3

- [ ] **AR-09**: 设计部署和分发方案
  - 输出：PyInstaller/cx_Freeze 打包方案
  - 输出：安装向导流程设计
  - 输出：自动备份策略
  - 负责人：DevOps
  - 截止：Week 4

- [ ] **AR-10**: 组织内部评审会议
  - 邀请所有角色参加
  - 审查上述所有交付物
  - 解决遗留分歧
  - 输出：Phase 1 开发-ready 决策文档
  - 负责人：全体
  - 截止：Week 4

---

## 四、潜在风险点和缓解措施

### 🚨 风险 register

| ID | 风险描述 | 概率 | 影响 | 风险等级 | 缓解措施 | 应急预案 |
|----|---------|------|------|---------|---------|---------|
| R1 | 实体归一准确率低于 80% | 高 | 致命 | 🔴 Critical | 多策略级联 + 用户反馈学习 | 退回到手动标注模式，降低自动化程度 |
| R2 | 用户不愿手动录入 Event | 高 | 严重 | 🔴 High | 极简表单 + 日历自动导入 + 语音输入 | 延后 Phase 1，优先开发日历同步（提前到 Phase 1.5） |
| R3 | LLM API 成本超出用户承受意愿 | 中 | 严重 | 🟠 High | Token 优化 + 批量处理 + 本地小模型替代 | 提供纯规则引擎版本（零成本） |
| R4 | 竞品（ChatGPT/Notion）快速复制核心功能 | 中 | 严重 | 🟠 High | 强化垂直领域深度 + 隐私优势 + 开箱即用 | 加速 Phase 2-3 开发，建立数据和网络效应壁垒 |
| R5 | 云端版本的安全合规投入超预算 | 中 | 中等 | 🟡 Medium | 采用成熟云服务商的安全能力（AWS/Huawei Cloud） | 延后企业版，聚焦个人版市场 |
| R6 | 与许总合作谈判破裂 | 低 | 致命 | 🔴 Critical | 提前签署 MOU（谅解备忘录）+ Plan B（自己做应用层） | 启动 Plan B：招聘前端团队或寻找其他合作伙伴 |
| R7 | 开发进度延期 >50% | 中 | 中等 | 🟡 Medium | Agile 开发 + 每周 Demo + 严格 Scope Control | 砍功能（优先保证核心链路：Event→关联→提醒） |
| R8 | 用户隐私担忧导致不敢使用 | 中 | 严重 | 🟠 High | 完全本地运行 + 透明化数据处理 + 第三方安全审计 | 发布安全白皮书和隐私政策，提供"审计模式"供用户自查 |
| R9 | 多跳查询性能无法满足需求 | 中 | 中等 | 🟡 Medium | 分层缓存 + 异步预计算 + 图数据库迁移 | 限制查询深度（最多3跳），提供"稍后邮件通知"选项 |
| R10 | 团队技能缺口（NLP/图算法/安全） | 中 | 中等 | 🟡 Medium | 外部咨询 + 开源库 + 技术培训 | 简化算法（MVP 用规则代替 ML） |

### 🛡️ 关键风险的深入缓解方案

#### R1: 实体归一准确率风险（最高优先级）

**根因分析**：
- 中文 NER 本身就是难题（分词、命名实体识别）
- 别名和指代消解需要深层语义理解
- 缺乏领域特定的标注数据

**多层防御策略**：

```
Layer 1: 规则引擎（准确率 95%，召回率 60%）
├── 精确匹配（"李总"=="李总"）
├── 别名字典（"李总"→"李明"）
└── 上下文启发式（同Event内的"李总"和"XX科技的李明"是同一人）

Layer 2: 轻量 ML 模型（准确率 88%，召回率 75%）
├── FastText 词向量相似度
├── TF-IDF + 余弦相似度
└── 预训练中文NER模型（spaCy zh / LAC）

Layer 3: LLM 消歧（准确率 92%，召回率 85%）【昂贵】
├── 仅在 Layer 1-2 都不确定时调用
├── 提供充足的上下文（相关Event片段）
└── 温度设为 0.1 提高确定性

Layer 4: 人类反馈（准确率 99%，但有限）
├── 低置信度时询问用户
├── 用户纠正后学习（在线学习）
└── 冷启动阶段重点积累标注数据
```

**准确率提升路线图**：

| 阶段 | 方法 | 预期准确率 | 成本 |
|------|------|-----------|------|
| Phase 1 | 纯规则引擎 | 75-80% | 零 |
| Phase 2 | 规则 + LLM 混合 | 85-90% | $0.05/次 |
| Phase 3 | 规则 + 微调小模型 | 90-93% | 一次性训练成本 |
| Phase 4 | 规则 + 大模型 + 人类反馈 | 95%+ | 持续运营成本 |

---

#### R6: 合作伙伴关系风险（致命但概率低）

**预警信号**：
- 许总迟迟不签正式协议
- 许总提出不合理的要求（如独家永久免费授权）
- 许总团队对技术方案频繁变更需求

**Plan B 详细方案**：

**Option B1: 自己做轻量应用层**
- 使用 Electron/Tauri 打包桌面应用
- 开发周期：2-3个月
- 团队需求：1个前端开发者
- 优点：完全掌控，无需分成
- 缺点：分散研发精力

**Option B2: 寻找备选合作伙伴**
- 联系其他 ISV（独立软件开发商）
- 目标：有企业客户资源的渠道商
- 时间线：并行谈 2-3 家
- 优点：不把鸡蛋放一个篮子里
- 缺点：需要商务资源

**Option B3: 开源社区驱动**
- 将应用层也开源
- 依靠社区贡献插件和UI
- 商业化：托管服务 + 企业支持
- 优点：低成本，潜在高回报
- 缺点：收入不可预测，周期长

**决策树**：
```
Week 4: 与许总签署 MOU?
├── Yes → 继续合作，但设定里程碑 checkpoint
│   └── Week 8: 签署正式合作协议?
│       ├── Yes → 全速推进
│       └── No → 启动 Plan B
└── No → 立即启动 Plan B（推荐 Option B1 + B2 并行）
```

---

## 五、整体评估结论

### 📊 可行性评分：7.2 / 10

**评分细则**：

| 维度 | 评分 (1-10) | 权重 | 加权分 | 说明 |
|------|------------|------|--------|------|
| **市场需求** | 8.5 | 25% | 2.13 | 痛点真实，目标用户愿意付费，但需验证规模 |
| **技术可行性** | 7.0 | 20% | 1.40 | 核心算法有挑战但可行，存在成熟开源方案可借鉴 |
| **团队能力** | 7.5 | 15% | 1.13 | CarryMem 团队有基础，但需补充 NLP/图算法/安全专家 |
| **竞争优势** | 6.5 | 15% | 0.98 | 差异化不够明显，容易被大厂复制，需加快建立壁垒 |
| **商业模式** | 6.0 | 15% | 0.90 | 可持续性质疑，前期投入大回收周期长 |
| **风险可控性** | 7.0 | 10% | 0.70 | 主要风险有缓解方案，但R1/R6 需重点关注 |
| **总计** | - | 100% | **7.24** | **可行，但需补完设计后启动** |

### ✅ 最大风险点（Top 3）

1. **实体归一准确率**（技术核心，决定产品生死）
2. **合作伙伴关系稳定性**（商业成败的关键变量）
3. **用户 onboarding 和早期留存**（冷启动死亡率可能极高）

### 🎯 核心建议（3 条）

#### 建议 1: 延后 Phase 1 开发，插入 Phase 0 设计补完期（2-4周）

**理由**：
当前设计文档在用户体验、安全性、测试策略、商业模式等关键维度存在显著缺漏。匆忙进入开发会导致大量返工。

**Phase 0 交付物**（见上文 AR-01 到 AR-10）：
- 经过验证的用户画像
- 完整的 onboarding 流程设计
- 安全加固方案
- 测试策略和基准
- 确定的商业模式
- 可交互的 MVP 原型

**投入**：
- 人力：全员参与（各角色 20-50% 时间）
- 时间：2-4 周
- 成本：主要是时间成本（少量用户访谈礼品费、原型工具许可费）

**收益**：
- 降低 Phase 1 返工概率 >50%
- 提升团队对齐度
- 早期发现致命风险（如 R6 合作破裂）

---

#### 建议 2: 聚焦核心价值，砍掉 MVP 非必需功能

**当前 MVP 范围的问题**：
试图同时验证太多假设：
- ✅ 要验证：关联发现能不能跑通
- ❓ 要验证：手动录入体验好不好
- ❓ 要验证：CLI 工具够不够用
- ❓ 要验证：SQLite 性能够不够

**精简后的 MVP（Minimum Loveable Product）**：

**只做一件事**：**证明"自动关联发现"能提供用户认可的价值**

**MVP 功能清单**：

必做（Core）：
1. ✅ Event 手动录入（Web 表单，不是 CLI）
2. ✅ 基于 LLM 的实体抽取（用户配 Key，否则用示例数据演示）
3. ✅ 基于规则的关联发现（3-5 种硬编码规则）
4. ✅ 提醒展示（Web 页面，实时刷新）
5. ✅ 5 个预设的示例 Event（开箱即用，无需用户录入）

不做（Cut）：
- ❌ CLI 命令行工具（Phase 2 再做）
- ❌ MCP 工具集成（Phase 2 再做）
- ❌ Graphviz DOT 导出（Phase 2 再做）
- ❌ 日历同步（Phase 3）
- ❌ 团队共享（Phase 4）
- ❌ 复杂的实体归一（MVP 用 LLM 一次性搞定，不做持久化学习）

**MVP 成功标准**：
- 10 个测试用户，每人使用 3 天
- 至少 70% 用户认为"有点意思"或"很有用"
- 至少 50% 用户愿意继续使用（或付费使用增强版）
- 平均每人每天查看提醒 >2 次

**为什么这样砍**：
- 降低开发复杂度（2-3 周可完成 MVP）
- 聚焦验证核心假设（关联发现是否有价值）
- 快速获得用户反馈（比完美更重要）
- 为后续迭代提供真实数据（用户真正关心什么类型的关联）

---

#### 建议 3: 建立两周一个迭代的敏捷节奏，每个迭代以用户测试收尾

**理由**：
EventLink 是强用户体验驱动的产品，不能闭门造车。

**迭代计划示例**：

**Iteration 1 (Week 1-2): MVP Core**
- Goal: 能录入 Event 并看到提醒
- Deliverables:
  - Web 表单录入 Event
  - LLM 实体抽取（调用 OpenAI API）
  - 3 种硬编码关联规则（同公司/同技术/同项目）
  - 提醒列表展示
- 验证: 内部 Dogfooding（团队自己先用 3 天）

**Iteration 2 (Week 3-4): Onboarding + Feedback**
- Goal: 新用户能在 5 分钟内看到价值
- Deliverables:
  - 5 个预设示例 Event
  - 引导式 onboarding（3步 wizard）
  - 用户反馈按钮（👍/👎 + 文本框）
  - 反馈数据收集和分析 dashboard
- 验证: 5 个外部用户测试（1小时访谈）

**Iteration 3 (Week 5-6): Accuracy + Personalization**
- Goal: 关联发现更准确，提醒更个性化
- Deliverables:
  - 别名字典（可编辑）
  - 用户偏好设置（关注/忽略某些类型关联）
  - 提醒频率控制（每日摘要）
  - 准确性仪表板（Precision/Recall 展示）
- 验证: 10 个用户，3 天使用 + 问卷

**Iteration 4 (Week 7-8): Polish + Prepare for Phase 2**
- Goal: MVP 达到可发布质量
- Deliverables:
  - UI 打磨（动画/过渡/响应式）
  - 性能优化（缓存/索引）
  - 文档（用户手册/FAQ）
  - 安装包（Windows/macOS/Linux）
- 验证: 20 个用户 Beta 测试，收集 NPS 分数

**每个迭代的 DoD (Definition of Done)**：
- [ ] 代码完成并通过 Code Review
- [ ] 单元测试覆盖率 >80%
- [ ] 无 P0/P1 Bug
- [ ] 通过用户测试（至少 3 人）
- [ ] 文档更新（README + Changelog）

---

## 六、总结和下一步行动

### 📝 本次评审的核心发现

**EventLink 产品设计的优势**：
1. ✅ **定位清晰**：从"记住你是谁"到"帮你发现你错过了什么"，升级路径明确
2. ✅ **痛点真实**：商务人士确实存在人脉管理和关联发现的刚需
3. ✅ **技术路径合理**：三层架构、SQLite MVP、渐进式增强，符合 CarryMem 轻量哲学
4. ✅ **商业模式初步成型**：Freemium + 订阅制，有清晰的升级路径
5. ✅ **开放性问题识别到位**：文档末尾列出了 7 个关键开放问题

**EventLink 产品设计的缺漏**：
1. ❌ **用户体验设计严重不足**：CLI 对非技术用户不友好，onboarding 缺失，提醒体验粗糙
2. ❌ **安全性和合规性未充分考虑**：本地加密、云端权限、GDPR/PIPL 都没有详细方案
3. ❌ **测试策略完全空白**：没有分层测试计划、准确性评估方法、性能基准
4. ❌ **技术实现的难点未深入分析**：实体归一算法、LLM 容错、多跳查询优化都没有具体方案
5. ❌ **商业模式可持续性存疑**：前期收入来源不明，定价策略模糊，合作伙伴利益分配未定
6. ❌ **目标用户定义过宽**：缺乏清晰的细分人群和用户画像，MVP 功能范围难以收敛
7. ❌ **运维和分发方案缺失**：如何打包、安装、备份、监控都没有考虑

### 🎯 下一步行动（立即开始）

**本周内（Week 0）**：

1. **组织评审结果分享会**（1小时）
   - 参与者：全体核心团队
   - 内容：讲解本报告的核心发现和建议
   - 产出：达成共识，确定是否采纳建议 1（插入 Phase 0）

2. **启动用户调研**（并行）
   - 联系 5-10 位潜在用户（中小企业主/销售VP）
   - 安排 30 分钟电话访谈
   - 访谈提纲见附录 A

3. **成立专项小组**（如果采纳 Phase 0）
   - 产品经理：主导 AR-01, AR-02, AR-06, AR-07
   - 架构师：主导 AR-03, AR-08
   - 安全专家：主导 AR-04
   - 测试专家：主导 AR-05
   - DevOps：主导 AR-09
   - 全体：参与 AR-10

**下周（Week 1）**：

4. **完成用户访谈**并输出用户画像初稿
5. **设计 onboarding 原型**（纸面原型或 Figma）
6. **起草技术架构文档 v2.0**（重点补充数据一致性和性能方案）
7. **与许总沟通** MOU 签署意向（缓解风险 R6）

**附录**：

#### 附录 A: 用户访谈提纲

```
访谈对象：{姓名}，{公司}，{职位}
访谈时间：30 分钟
访谈目的：了解商务人士在人脉管理和信息关联方面的痛点和需求

=== 暖场 (3分钟) ===
1. 请简单介绍一下您的工作内容和日常职责。
2. 您平时主要通过什么方式和客户/合作伙伴保持联系？

=== 现状挖掘 (10分钟) ===
3. 您目前用什么工具来管理客户和人脉信息？（CRM/Excel/笔记本/大脑？）
4. 这些工具用起来有什么不满意的地方？
5. 能否分享一个最近的例子：您事后意识到"当时如果知道XX信息就好了"？
   - 当时发生了什么？
   - 您后来是怎么知道这个信息的？
   - 这个信息对您的决策有什么影响？

=== 痛点深挖 (10分钟) ===
6. 您平均一周要见多少人/参加多少场会议？
7. 见完这些人之后，您通常会做什么？（整理笔记？录入CRM？什么都不做？）
8. 有没有遇到过这种情况：两个人/两件事明明有关联，但您当时没意识到？
   - 后来是怎么发现的？
   - 如果当时就能发现，会有什么不同的做法？
9. 您担心过"不小心把A公司的信息告诉了B公司"这种情况吗？实际发生过吗？

=== 概念验证 (5分钟) ===
10. [展示 EventLink 概念描述]
    - 这个概念听起来怎么样？
    - 您觉得最有价值的功能是什么？
    - 您最大的顾虑是什么？
    - 如果这样的工具存在，您愿意付费使用吗？大概多少钱/月？

=== 结束 (2分钟) ===
11. 还有什么我们没有问到但您觉得重要的？
12. 后续如果我们有原型，您愿意试用并给我们反馈吗？

感谢您的时间！
```

#### 附录 B: 技术选型对比表

| 技术维度 | 方案 A | 方案 B | 方案 C | 推荐 |
|---------|--------|--------|--------|------|
| **实体抽取** | LLM API (GPT-4o-mini) | 本地 NER (spaCy) | 混合 (LLM + 规则) | **C** (MVP用LLM，后续加规则降级) |
| **实体归一** | 纯规则引擎 | 向量相似度 + 阈值 | 多策略级联 | **C** (准确率优先) |
| **图存储** | SQLite + 邻接表 | NetworkX (内存) | Neo4j (图数据库) | **A** (Phase 1-2) → **C** (Phase 3+) |
| **前端框架** | Textual (TUI) | Streamlit (Web) | React (SPA) | **B** (MVP快速验证) → **C** (Phase 3+) |
| **部署方式** | PyInstaller 打包 | Docker 容器 | 云托管 (Railway/Render) | **A** (个人版) → **C** (团队版) |
| **LLM Provider** | OpenAI only | OpenAI + Anthropic fallback | + 本地 Ollama 备选 | **C** (最大灵活性) |

#### 附录 C: 术语表

| 术语 | 英文 | 定义 |
|------|------|------|
| Event | 事件 | 一次会议/对话/日程，关联发现的基本输入单元 |
| Entity | 实体 | 从 Event 中抽取的结构化对象（人/公司/技术等） |
| Association | 关联 | 两个实体之间的关系（如同校/竞对/技术重叠） |
| Alert | 提醒 | 关联发现后推送给用户的通知 |
| 实体归一 | Entity Resolution | 将指向同一真实世界对象的不同表述合并为一个实体 |
| 指代消解 | Coreference Resolution | 确定"他/她/这家公司"指代的具体实体 |
| 冷启动 | Cold Start | 新用户初次使用时因缺乏历史数据而无法获得价值的困境 |
| MVP | Minimum Viable Product | 最小可行产品，用最少功能验证核心假设 |
| Onboarding | 用户引导 | 新用户首次使用时的引导流程 |
| Saga 模式 | Saga Pattern | 分布式系统中管理长事务的设计模式 |
| P0/P1/P2/P3 | 优先级 | P0=必须立即解决, P1=重要, P2=改进, P3=可选 |

---

> **报告编写**: DevSquad 多角色 AI 团队
> **审阅状态**: 待团队讨论
> **版本**: v1.0
> **下次更新**: Phase 0 完成后更新至 v2.0（补充用户调研数据和原型测试结果）

---

## 📌 如何使用本报告

1. **通读全文**：了解所有角色的发现和共识问题
2. **聚焦 Top 12**：优先解决 P0 级别的 9 个问题
3. **执行 Phase 0**：按照行动项清单推进设计补完
4. **跟踪风险**：定期 review risk register，更新缓解措施
5. **迭代改进**：每个 Phase 结束后回顾本报告，更新评估和计划

**祝 EventLink 项目顺利推进！** 🚀
