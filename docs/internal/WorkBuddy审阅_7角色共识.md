# WorkBuddy审阅报告 — 7角色共识讨论

> 日期: 2026-06-02

## 架构师 (architect)

# 架构师审阅意见

## 一、技术缺失共识

| # | 缺失项 | 判断 | 理由 |
|---|--------|------|------|
| 1 | 实体归一5步算法 | **采纳** | 关键缺口。PRD写了算法逻辑，技术设计必须补代码实现。建议补充：(1) 置信度计算细节（字段匹配权重）；(2) 上下文相似度的embedding策略（用OpenAI还是本地模型）；(3) HITL确认的UI交互协议（前后端接口） |
| 2 | 商机匹配度五维算法 | **采纳** | 这是F-05核心功能，现有代码只有简陋的4行关联强度计算，无法支撑商机匹配。建议补充：(1) D4 LLM判断的prompt模板；(2) 五维分数的调试日志（方便调参）；(3) 边界case处理（缺字段时的降级策略） |
| 3 | Todo状态机 | **采纳** | 数据完整性刚需。建议补充：(1) PostgreSQL CHECK约束（防止非法状态）；(2) 状态转移审计日志（记录who/when/from/to）；(3) snoozed恢复的定时任务容错机制（避免漏恢复） |
| 4 | 话题标签数据结构+余弦相似度 | **修改采纳** | 结构正确，但有两点建议：(1) 话题向量用pgvector扩展而非list类型，支持索引加速；(2) 余弦相似度可用pgvector的<=>操作符，无需应用层计算；(3) 补话题标签的归并逻辑（"SaaS定价策略"和"SaaS pricing"是同一话题） |
| 5 | 领域分类YAML配置 | **采纳** | L2动态扩展是PRD明确的方案D，必须补。建议补充：(1) L2升级的定时检查任务；(2) L2审核的UI界面协议（人工确认时）；(3) 多租户场景下L2配置是全局还是租户级隔离 |
| 6 | same_city推断逻辑 | **修改采纳** | 逻辑正确，但建议补充：(1) 城市名归一化（"北京"="Beijing"="BJ"）；(2) 省会城市特殊处理（广州和深圳算不算同城）；(3) 城市信息的更新策略（名片扫描更新了company_city，是否覆盖旧值） |
| 7 | 关联强度时间衰减函数 | **采纳** | PRD明确λ=0.01，技术设计必须补。建议补充：(1) 衰减参数可配置化（不同关联类型可能需要不同λ）；(2) 衰减下限保护（即使365天未联系，强关联如ex_colleague不应降为0）；(3) last_interaction的更新触发时机（是否包括被动触发如查看卡片） |
| 8 | 离线策略（前端） | **修改采纳** | PoC可以不补，但Phase1必须补。建议：(1) PoC阶段明确"需要网络"的限制；(2) Phase1离线策略聚焦"查看已缓存卡片+Todo"，不做离线写入；(3) 补Service Worker缓存策略（哪些API响应可缓存） |
| 9 | PromiseLink→CarryMem写入映射表 | **采纳** | Protocol接口已定义，但语义映射缺失。建议补充：(1) 每种写入的schema定义（CarryMem期望的JSON结构）；(2) 写入失败的重试策略；(3) CarryMem未部署时的Mock数据存储（避免PoC期间写入丢失） |

## 二、文档矛盾共识

| # | 矛盾点 | 对齐方案 | 理由 |
|---|--------|----------|------|
| 1 | 存储策略 | **采纳PoC用SQLite方案** | 理由正确：(1) PoC验证AI能力，不是基础设施；(2) 和CarryMem技术栈一致；(3) Docker单机部署零配置。**但需补充**：PRD §5.12明确写"PoC阶段：SQLite（参考CarryMem哲学）"；技术设计补SQLite→PostgreSQL迁移脚本模板 |
| 2 | 关联强度时间衰减 | **采纳补时间衰减函数** | PRD术语表已明确λ=0.01，技术设计的简化版算法不符。建议：(1) 技术设计§4.3的代码示例更新为带衰减的版本；(2) PRD术语表补完整公式（避免歧义） |
| 3 | 商机匹配度 | **采纳补五维算法** | 技术设计的关联强度算法不等于商机匹配度。建议：(1) 明确关联强度是"两个实体的连接紧密度"，商机匹配度是"Todo与Person的匹配度"；(2) 关联强度用于图谱构建，商机匹配度用于推荐排序；(3) 补F-05的SQL查询示例（如何从图谱中筛选候选人） |
| 4 | Event.raw_text长度 | **采纳补CHECK约束** | TEXT无限制会导致：(1) LLM处理超时；(2) 数据库膨胀。建议：(1) PostgreSQL加CHECK约束`length(raw_text) <= 500000`；(2) 应用层截断+告警（超长会议记录保留前500KB）；(3) 补大文件处理策略（分段处理还是拒绝） |
| 5 | CarryMem协议 | **采纳改为SDK filter API** | 硬编码字符串匹配不可维护。建议：(1) 依赖CarryMem SDK的filter方法；(2) 技术设计补CarryMem SDK的依赖版本（确保API兼容）；(3) 补NullMemoryProvider的filter实现（本地过滤逻辑） |

## 三、Slogan共识

| 项目 | 判断 | 理由 |
|------|------|------|
| 主Slogan："见面只是开始" | **采纳** | (1) 简洁有力；(2) 正面表述；(3) 留悬念引发好奇。**但需确认**：是否符合品牌调性（偏年轻化还是商务稳重）|
| 副Slogan："下次联系的理由，我们给你找好了" | **修改采纳** | 语义正确，但略冗长。建议简化："下次联系的理由，帮你找好了"（10字→8字）。或更直接："联系理由，我们备好了"（更符合商务简洁风格）|
| 废弃现有Slogan | **采纳** | "每次见面，都不白费"确实是负面规避型表述，且未直接指向产品能力 |

## 四、PoC存储共识

| 项目 | 判断 | 理由 |
|------|------|------|
| PoC用SQLite | **强烈采纳** | (1) 和CarryMem技术栈一致，降低学习成本；(2) PoC用户≤5人，SQLite够用；(3) Docker单机部署零配置；(4) 数据文件可直接备份/迁移。**架构优势**：SQLite→PostgreSQL迁移路径清晰（SQLAlchemy ORM一致） |
| Phase1用PG+Redis | **采纳** | 100用户规模需要并发支持，SQLite会成为瓶颈。**建议补充**：(1) Redis缓存策略（哪些数据缓存、TTL多久）；(2) PG索引优化清单（基于PoC阶段的慢查询分析）；(3) 迁移检查清单（确保SQLite数据完整迁移） |
| ES推迟到Phase2 | **采纳** | Phase1用PG的GIN索引+pg_trgm扩展足够。**但需确认**：全文搜索的性能阈值（多少数据量/多少并发时PG会扛不住），提前准备ES接入方案 |

## 五、其他建议

### 5.1 PRD补充项（采纳）

| # | 补充项 | 判断 | 理由 |
|---|--------|------|------|
| 1 | 补CarryMem集成接口章节 | **采纳** | 技术设计已定义Protocol，PRD需要引用。建议在PRD §6（系统架构）增加"6.X CarryMem集成"章节，说明：(1) Protocol接口定义；(2) NullMemoryProvider降级策略；(3) 数据写入映射表 |
| 2 | 存储策略统一声明 | **采纳** | PRD §5.12当前提三层存储，需改为：PoC SQLite / Phase1 PG+Redis / Phase2按需ES。**同时补充**：存储分层的决策依据（数据量/QPS阈值） |
| 3 | LLM成本估算 | **采纳** | $2.35/月/用户是合理估算。建议补充：(1) 成本优化策略（prompt压缩、批处理）；(2) 成本告警阈值（超预算时的降级方案）；(3) 本地模型替代可能性（Phase2） |
| 4 | 关联强度完整公式 | **采纳** | 术语表的λ=0.01需要完整公式支撑。建议：(1) 补公式；(2) 补各关联类型的base值表格；(3) 补公式的边界测试case（如0天/365天的计算结果） |

### 5.2 技术设计补充项

| # | 补充项 | 判断 | 理由 |
|---|--------|------|------|
| 1 | LLM prompt模板 | **采纳** | 4条管线的核心驱动，必须有代码实现。建议：(1) 补card_save/meeting/call三条管线的prompt模板；(2) 补few-shot示例（提升抽取准确率）；(3) 补prompt版本管理机制（方便A/B测试） |
| 2 | 迁移脚本模板 | **采纳** | SQLite→PostgreSQL需要迁移脚本。建议补充：(1) schema迁移（Alembic）；(2) 数据迁移（带数据校验）；(3) 回滚脚本（迁移失败时） |
| 3 | 监控指标清单 | **采纳** | 技术设计提了"监控告警"但未列指标。建议补充：(1) 业务指标（实体归一准确率、Todo生成率）；(2) 性能指标（API P95延迟、LLM调用成功率）；(3) 成本指标（LLM token消耗、存储增长速率） |

### 5.3 架构风险点（需注意）

| # | 风险点 | 影响 | 缓解方案 |
|---|--------|------|---------|
| 1 | **实体归一的误合并** | 错误合并两个同名不同人，用户信任度崩溃 | (1) 置信度≥0.85才自动合并；(2) 合并后24小时内允许撤销；(3) HITL确认UI必须清晰展示合并依据 |
| 2 | **LLM幻觉导致错误Todo** | "建议联系李总谈融资"但李总是竞对CEO | (1) Todo生成加置信度字段；(2) 低置信度Todo标记"待确认"；(3) 用户可举报错误Todo，反馈到prompt优化 |
| 3 | **时间衰减过快** | λ=0.01时，180天未联系的重要关系（如投资人）衰减到0.17 | (1) 衰减下限保护（重要关联类型如investor/mentor不低于0.3）；(2) 用户可标记"重要关系"豁免衰减；(3) Phase1后根据数据调整λ |
| 4 | **SQLite→PG迁移数据丢失** | PoC期间产生的归一决策、手动标注丢失 | (1) 迁移前全量备份；(2) 迁移后数据校验（count/checksum）；(3) 迁移脚本幂等性（可重复执行） |
| 5 | **CarryMem集成延迟** | CarryMem SDK更新慢，PromiseLink功能受阻 | (1) NullMemoryProvider必须功能完整（不依赖CarryMem也能运行）；(2) Protocol接口版本管理；(3) Mock数据生成器（测试用） |

### 5.4 PoC验证关键指标（建议明确）

PRD退出条件定义了LLM抽取≥90%、归一误合并<5%、F1>0.65，但缺少具体测试方法。建议补充：

| 指标 | 测试方法 | 通过标准 | 失败应对 |
|------|---------|---------|---------|
| LLM抽取准确率 | 人工标注50个名片/会议记录，计算精准率/召回率 | P≥0.90, R≥0.85 | 优化prompt/切换模型 |
| 归一误合并率 | 构造20组同名不同人case，检查合并结果 | 误合并≤1例 | 调整置信度阈值 |
| F1（商机匹配） | 人工标注30个Todo，对比推荐Top5的准确率 | F1≥0.65 | 调整五维权重 |
| 端到端延迟 | 测试名片扫描→卡片生成全流程 | P95<2s | 优化LLM调用/缓存策略 |

---

## 总结

1. **9项技术缺失**：全部采纳或修改采纳，P0项（实体归一、商机匹配、Todo状态机）必须在PoC前补齐，P1项Phase1前补齐，P2项Phase2前补齐。

2. **5项文档矛盾**：全部采纳对齐方案，存储策略统一为"PoC SQLite / Phase1 PG+Redis / Phase2按需ES"。

3. **Slogan**：主标语采纳，副标语建议简化为8字版本。

4. **PoC存储**：强烈采纳SQLite方案，技术理由充分，且和CarryMem一致。

5. **架构风险**：补充5个关键风险点的缓解方案，特别是实体归一误合并和时间衰减过快。

整体评价：WorkBuddy的审阅非常到位，发现的缺失项都是真实缺口，建议的对齐方案合理。作为架构师，我认为**补齐P0三项是PoC启动的必要条件，不可妥协**。

---

## 产品经理 (product-manager)

# Product Manager 审阅意见

从产品验证角度，我关注三个关键问题：
1. **这些缺失是否阻碍PoC核心假设验证？**
2. **文档矛盾是否影响开发启动？**
3. **Slogan是否能驱动用户行为？**

---

## 技术缺失共识

| # | 缺失项 | 判断 | 理由 |
|---|--------|------|------|
| 1 | 实体归一5步算法 | **采纳** | PoC退出条件之一是"归一误合并<5%"，没有完整算法无法验证这个指标。P0优先级合理。 |
| 2 | 商机匹配度五维算法 | **采纳** | F-05是核心用户价值，"下次联系的理由"依赖这个算法。但建议PoC先实现简化版（D1+D2+D5三维），D3/D4涉及embedding和LLM调用，Phase1再补全。 |
| 3 | Todo状态机 | **采纳** | snoozed→pending的定时恢复是"开车去拜访"场景的关键体验，必须补。 |
| 4 | 话题标签数据结构 | **修改采纳** | PoC阶段先跳过。理由：话题标签只在meeting/call管线产生，PoC重点验证card_save管线（名片扫描）和基础关联发现。Phase1验证会议场景时再补。 |
| 5 | 领域分类YAML配置 | **修改采纳** | PoC用硬编码18个L1领域即可，L2动态扩展在Phase1验证。但YAML文件结构现在定义好，避免后期返工。 |
| 6 | same_city推断逻辑 | **采纳** | same_city是最高频关联类型之一，影响关联发现的召回率。PoC必须有。 |
| 7 | 关联强度时间衰减 | **不采纳（PoC）** | PoC数据时间跨度≤3周，时间衰减效应不明显。建议Phase1再补，PoC先用静态强度。这样可节省0.5天工作量，不影响核心假设验证。 |
| 8 | 离线策略 | **不采纳（PoC）** | 同意P2优先级。PoC在办公室WiFi环境测试，Phase1验证外出场景时再补。 |
| 9 | PromiseLink→CarryMem映射表 | **不采纳（PoC）** | PoC用NullMemoryProvider，不依赖CarryMem集成。Phase1集成时再补。 |

**PoC工作量重估**：P0项（1+2简化版+3+6）约3天，P1项（5仅YAML结构）约0.5天，总计3.5天。可接受。

---

## 文档矛盾共识

| # | 矛盾点 | 对齐方案 | 理由 |
|---|--------|---------|------|
| 1 | **存储策略** | **完全采纳SQLite方案** | 核心论据：PoC验证的是"LLM能否准确抽取实体+关联"，不是验证"PG能否扛住并发"。SQLite零依赖部署，降低PoC环境复杂度，和CarryMem技术栈一致。Phase1切换PG时只需改连接字符串+补migrations，风险可控。 |
| 2 | **关联强度时间衰减** | **Phase1补充** | 如上所述，PoC时间窗太短看不出衰减效应，不影响"关联发现F1>0.65"的退出条件验证。 |
| 3 | **商机匹配度** | **PoC简化版+Phase1完整版** | PoC先做D1（关键词）+D2（行业）+D5（历史），够验证"Todo推荐是否有价值"。D3（话题向量）和D4（LLM语义）在Phase1补全。 |
| 4 | **raw_text长度限制** | **采纳CHECK约束** | 500KB限制合理（对应约25万字中文/12.5万英文词），防止极端输入拖垮LLM。建议应用层先校验+友好提示，数据库层加CHECK作为最后防线。 |
| 5 | **CarryMem协议** | **Phase1对齐** | PoC用NullMemoryProvider，这个矛盾不影响PoC。但建议现在就在技术设计里写清楚"Phase1集成时用CarryMem SDK的filter API"，避免后期接口理解偏差。 |

---

## Slogan共识

### 主Slogan："见面只是开始" ✅ **强烈推荐采纳**

**理由**：
1. **钩子强**：短、直接、重新定义用户认知。5个字容易记，容易传播。
2. **情绪精准**：商务人士的核心焦虑不是"联系人太多管理不过来"，而是"见过了没下文"。这句话戳中痛点。
3. **和产品核心能力强关联**：Todo/行动建议的本质就是"把见面变成起点，而不是终点"。

### 副Slogan："下次联系的理由，我们给你找好了" ✅ **采纳**

**理由**：
1. **功能指向清晰**：用户立刻知道产品能帮他做什么。
2. **解决实际问题**：许总场景"想跟进，没理由"是最常见的行动障碍，这句话直接给解决方案。
3. **行动导向**：从"信息管理"升级到"行动推进"，符合Todo替代Alert的产品哲学。

### 和现有Slogan对比

| 维度 | 现有 | 建议 | PM判断 |
|------|------|------|--------|
| 记忆成本 | 中（11字+6字） | 低（5字+13字） | ✅ 更易传播 |
| 情绪钩子 | 弱（理性描述） | 强（痛点→解决方案） | ✅ 更能驱动下载 |
| 产品指向 | 模糊 | 精准（Todo） | ✅ 降低认知成本 |
| A/B测试建议 | 可测试"停留在微信里"的共鸣度 | 可测试"见面只是开始"的点击率 | 建议Phase1前做Landing Page A/B测试 |

**行动建议**：
- PoC阶段先用新Slogan做内部测试（5人+客户团队反馈）
- Phase1启动前做小范围Landing Page A/B测试（100-200访客）
- 根据转化率数据最终确认

---

## PoC存储共识

### SQLite方案 ✅ **完全采纳**

**产品验证视角的核心论据**：

| 维度 | SQLite | PostgreSQL | PM判断 |
|------|--------|-----------|--------|
| **部署复杂度** | 单文件，零配置 | 需Docker/云服务+连接池配置 | ✅ PoC重点是验证AI能力，不是验证基础设施 |
| **数据可观察性** | 可直接用DB Browser打开查看 | 需psql/pgAdmin | ✅ PoC期间频繁检查数据质量，SQLite更便捷 |
| **和CarryMem一致性** | 相同技术栈 | 不同 | ✅ 降低集成风险 |
| **迁移成本** | Phase1切换时改连接字符串+补migrations | N/A | ✅ 可接受（1-2天工作量） |
| **PoC退出条件影响** | 无（5人并发量SQLite够用） | 无 | ✅ 不影响任何指标验证 |

**风险评估**：
- ❌ **无风险**：PoC数据量<1000条Event，SQLite性能瓶颈远未触达
- ✅ **额外收益**：SQLite文件可直接备份分享，方便客户团队异地测试

### 分期存储路径 ✅ **采纳**

| 阶段 | 存储方案 | 理由 |
|------|---------|------|
| **PoC（3周）** | SQLite + 内存缓存 | 验证AI能力，零新依赖 |
| **Phase1（6周）** | PostgreSQL + Redis | 支持100人并发，PG的GIN索引够用全文搜索 |
| **Phase2** | PG + Redis + (按需ES) | 数据量>10万Event或搜索QPS>100再引入ES |

**ES推迟的产品逻辑**：
- PoC/Phase1的搜索场景主要是"找某个人"（精确匹配），不是"找所有讨论过SaaS定价的会议"（全文检索）
- 等Phase2有真实搜索日志后，再根据长尾查询占比决定是否引入ES
- PG的pg_trgm扩展+GIN索引可兜底模糊搜索，避免过早优化

---

## 其他建议

### 1. LLM成本估算 ✅ **采纳+补充**

WorkBuddy的估算（$2.35/月/用户）是合理的，但建议补充：

| 场景 | PoC预算 | Phase1预算 | 备注 |
|------|---------|-----------|------|
| **5人×3周测试** | $35 | N/A | 5人 × $2.35 × 1月 ≈ $12，考虑调试额外消耗×3倍 |
| **100人×6周** | N/A | $350 | 100人 × $2.35 × 1.5月 |
| **失败案例预留** | $50 | $100 | LLM抽取失败需重试，预留额外30% |
| **合计** | **$85** | **$450** | PoC可接受，Phase1需提前申请预算 |

**成本优化建议**（Phase2考虑）：
- 高频场景（名片扫描）用GPT-4o-mini
- 低频高价值场景（会议深度分析）用GPT-4
- 探索本地模型（Llama 3.1 70B）替代可能性

### 2. PoC退出条件量化补充 ✅ **建议增加2个指标**

PRD现有退出条件很好，建议补充：

| 类别 | 现有指标 | 建议补充 | 理由 |
|------|---------|---------|------|
| **AI准确性** | LLM抽取≥90%、归一误合并<5%、F1>0.65 | + 商机匹配度准确率≥70% | F-05是核心价值，需独立验证 |
| **用户行为** | DAU≥30持续2周、TTS使用率≥40% | + Todo行动转化率≥25% | 验证"行动建议"是否真的推动了行动 |

**Todo行动转化率定义**：
- 分子：状态变为in_progress/done的Todo数
- 分母：生成的所有Todo数（不含dismissed）
- 目标≥25%意味着：生成4个建议，至少有1个被执行

### 3. 话题标签优先级调整 ⚠️ **需确认**

WorkBuddy建议话题标签P1，我建议降级为P2（Phase1）。需要和tech-lead确认：

**如果同意降级P2**：
- PoC只验证card_save管线（名片）+ 基础关联发现
- meeting管线在Phase1验证
- 节省1天开发时间

**如果坚持P1**：
- 那就必须在PoC包含meeting管线测试
- 需要准备测试用会议录音+标注数据
- PoC工作量+2天（话题标签1天+meeting管线集成1天）

我倾向于降级P2，理由：PoC应该聚焦最小可验证单元（名片场景），会议场景复杂度高，放Phase1更稳妥。

### 4. 实体归一5步算法——建议增加可观察性 ✅ **补充需求**

算法本身设计合理，但PoC期间需要频繁调试阈值（0.85/0.70），建议补充：

```python
class ResolutionResult:
    """归一结果——增加可观察性字段"""
    action: ResolutionAction  # MERGE / CONFIRM / CREATE
    target: Optional[Entity]
    confidence: float
    # 新增：调试信息
    matched_step: str  # "exact_match" / "alias_match" / "fuzzy_match" / ...
    matched_fields: dict  # {"name": 0.95, "company": 1.0, "title": 0.8}
    explanation: str  # "同名+同公司，置信度0.95，自动合并"
```

这样PoC期间可以快速定位"为什么这两个实体被合并了"，加速调试。

---

## 最终行动清单（产品视角）

| # | 行动 | 负责方 | DDL | 阻塞关系 |
|---|------|--------|-----|---------|
| 1 | **补实体归一5步算法**（含可观察性字段） | tech-lead | PoC D-3 | 阻塞PoC启动 |
| 2 | **补商机匹配度简化版**（D1+D2+D5） | tech-lead | PoC D-3 | 阻塞PoC启动 |
| 3 | **补Todo状态机+定时恢复** | tech-lead | PoC D-3 | 阻塞PoC启动 |
| 4 | **补same_city推断逻辑** | tech-lead | PoC D-3 | 阻塞PoC启动 |
| 5 | **PRD补存储策略声明**（SQLite→PG路径） | product-manager | 本周 | 文档对齐 |
| 6 | **PRD补CarryMem集成接口声明** | product-manager | 本周 | 文档对齐 |
| 7 | **PRD补LLM成本预算表** | product-manager | 本周 | 预算申请 |
| 8 | **Slogan内部测试**（新vs旧，5人反馈） | product-manager | PoC week 1 | 准备Phase1宣传物料 |
| 9 | **领域分类YAML结构定义** | tech-lead | PoC week 2 | 不阻塞开发，但早定义避免返工 |
| 10 | **话题标签优先级最终确认** | product-manager + tech-lead | 明天 | 决定PoC范围 |

**关键路径**：1+2+3+4必须在PoC启动前完成，预计3.5天。

---

## 总结

WorkBuddy审阅质量极高，9项技术缺失中7项必须解决，5项文档矛盾全部需要对齐。

**最关键的3个决策**：
1. ✅ **PoC用SQLite** — 降低复杂度，聚焦AI能力验证
2. ✅ **Slogan改为"见面只是开始"** — 情绪钩子更强，行动导向更清晰
3. ⚠️ **话题标签降级P2** — 需tech-lead确认，影响PoC范围

PoC工作量增加3.5天可接受，不影响3周时间窗。关键是**现在就把这3.5天的技术债补上**，避免PoC期间反复返工。

---

## 开发者 (solo-coder)

# solo-coder 角色的审阅共识

## 技术缺失共识

| # | 缺失项 | 判断 | 理由 |
|---|--------|------|------|
| 1 | 实体归一5步算法 | **采纳** | WorkBuddy提供的代码框架可直接用。补充点：<br>1. fuzzy_match建议用rapidfuzz库（比jaro_winkler快3倍）<br>2. context_confirm逻辑需补充（company+title+city三元组匹配）<br>3. 置信度计算建议加权重衰减（exact 1.0 → alias 0.95 → fuzzy max 0.90）<br>**估算：1.5天**（含单元测试） |
| 2 | 商机匹配度五维算法 | **采纳** | 代码框架合理，但需补充：<br>1. `_keyword_overlap`用Jaccard还是TF-IDF？建议TF-IDF（处理高频词）<br>2. `_llm_semantic_judge`是同步调用还是异步batch？建议batch（成本优化）<br>3. topic_vector存储格式？建议用pgvector扩展（原生向量相似度查询）<br>**估算：2天**（含LLM prompt调试） |
| 3 | Todo状态机 | **修改采纳** | 不建议用PostgreSQL ENUM，理由：<br>1. ENUM修改需ALTER TYPE，PoC阶段状态可能调整<br>2. 应用层校验更灵活（可加日志、审计）<br>3. 用CHECK约束 + Python Enum类组合<br><br>建议方案：<br>```python<br>class TodoStatus(str, Enum):<br>    PENDING = "pending"<br>    IN_PROGRESS = "in_progress"<br>    DONE = "done"<br>    DISMISSED = "dismissed"<br>    SNOOZED = "snoozed"<br><br># SQL<br>ALTER TABLE todos ADD CONSTRAINT status_check <br>CHECK (status IN ('pending', 'in_progress', 'done', 'dismissed', 'snoozed'));<br>```<br>定时恢复用APScheduler（比Celery轻量）<br>**估算：0.5天** |
| 4 | 话题标签数据结构 | **采纳** | 补充建议：<br>1. tag_vector用pgvector的vector(1536)类型（原生索引）<br>2. 加GIN索引`CREATE INDEX idx_topic_tags_vector ON topic_tags USING ivfflat (tag_vector vector_cosine_ops);`<br>3. cosine_similarity函数改用pgvector的`<=>` 操作符（性能提升50%）<br>**估算：0.5天** |
| 5 | 领域分类YAML配置 | **采纳** | YAML可直接用。补充动态L2扩展逻辑：<br>```python<br>class DomainTaxonomy:<br>    async def promote_to_L2(self, l1: str, keyword: str):<br>        freq = await self.get_keyword_frequency(l1, keyword)<br>        if freq >= self.config["min_frequency"]:<br>            current_l2 = await self.get_L2_count(l1)<br>            if current_l2 < self.config["max_L2_per_domain"]:<br>                await self.add_L2(l1, keyword)<br>```<br>**估算：1天** |
| 6 | same_city推断逻辑 | **修改采纳** | 代码框架OK，但`_get_city`实现需明确：<br>1. 名片JSON的city字段路径（properties.contact_info.city？）<br>2. 公司地址→城市的解析逻辑（用LLM还是正则？）<br>3. visited_city要不要存？（建议存但不用于关联）<br>建议加城市标准化（"北京" vs "Beijing"）<br>**估算：1天**（含地址解析调试） |
| 7 | 关联强度时间衰减函数 | **采纳** | 公式可直接用。补充：<br>1. λ=0.01是否可配置？（不同关联类型可能衰减率不同）<br>2. 建议加缓存（strength计算高频，可缓存1小时）<br>3. 边界case：last_interaction未来时间（用户手动设置due_date）<br>**估算：0.5天** |
| 8 | 离线策略（前端） | **采纳推迟** | 同意PoC不补，Phase1前必须补。补充技术选型建议：<br>1. 小程序用wx.setStorageSync存关键数据（实体列表、待办、最近事件）<br>2. H5用IndexedDB（支持结构化查询）<br>3. 同步策略：启动时diff，后台增量同步<br>**估算：2天**（Phase1前） |
| 9 | PromiseLink→CarryMem写入映射表 | **采纳** | 表格清晰。补充：<br>1. declare_memory的payload schema需要CarryMem SDK文档<br>2. update_rule的rule格式需要明确（JSON？DSL？）<br>3. 建议加失败重试队列（CarryMem不可用时）<br>**估算：1天**（Phase2前） |

**P0总估算：4.5天**（缺失1+2+3）  
**P1总估算：3天**（缺失4+5+6+7）  
**P2总估算：3天**（缺失8+9，Phase1/2前）

---

## 文档矛盾共识

| # | 矛盾点 | 对齐方案 | 理由 |
|---|--------|---------|------|
| 1 | 存储策略 | **采纳SQLite→PG→ES三阶段** | 同意WorkBuddy建议。补充实现细节：<br>- PoC用SQLite，schema与PG保持兼容（SQLAlchemy统一抽象）<br>- 迁移脚本用Alembic管理<br>- ES推迟但预留接口（search_service抽象层）<br>**代码影响：新增SQLite dialect配置** |
| 2 | 关联强度时间衰减 | **采纳补时间衰减** | 已在缺失7处理，补充`calculate_association_strength`函数到`association_engine.py`<br>**代码影响：修改1个函数，加2个单元测试** |
| 3 | 商机匹配度 | **采纳补五维算法** | 已在缺失2处理，补充`OpportunityMatcher`类到`matching_engine.py`<br>**代码影响：新增1个模块，约200行** |
| 4 | Event.raw_text长度 | **采纳应用层校验** | 不建议SQL CHECK（500KB的CHECK约束会拖慢INSERT），改用：<br>```python<br>class Event(Base):<br>    @validates('raw_text')<br>    def validate_raw_text(self, key, value):<br>        if value and len(value.encode('utf-8')) > 512000:<br>            raise ValueError("raw_text exceeds 500KB")<br>        return value<br>```<br>**代码影响：加1个validator** |
| 5 | CarryMem协议 | **采纳改用SDK filter API** | 技术设计的硬编码字符串匹配不可维护。改为：<br>```python<br>memories = await carrymem_client.recall(<br>    user_id=user_id,<br>    filters={<br>        "type": "fact_declaration",<br>        "domain": context.get("domain"),<br>        "time_range": (start, end)<br>    }<br>)<br>```<br>需要CarryMem SDK文档确认filter参数schema<br>**代码影响：重构recall_memories方法** |

**总代码改动估算：1天**

---

## Slogan共识

**判断：部分采纳**

同意主Slogan"见面只是开始"——5个字，简洁有力，情绪钩子强。

但副Slogan"下次联系的理由，我们给你找好了"有点长（17个字），建议再精简：

| 原建议 | 优化版A | 优化版B |
|-------|---------|---------|
| 下次联系的理由，我们给你找好了 | 下次见他的理由，都在这 | 联系的时机和理由，都帮你想好了 |

**推荐优化版A**（11个字，更口语）

**从开发角度的影响**：Slogan不影响代码，但会影响：
1. 微信服务号推送文案模板
2. 小程序启动页文案
3. Todo卡片的action文案

建议产品定slogan后，我一次性更新所有文案常量。

---

## PoC存储共识

**判断：完全采纳SQLite方案**

理由：
1. **零依赖**：不用启Docker Postgres，本地开发体验更好
2. **迁移成本低**：SQLAlchemy抽象层，改个DATABASE_URL就能切PG
3. **CarryMem一致性**：两个产品用同一套存储，集成更自然
4. **备份简单**：一个.db文件，方便PoC期间快速回滚

**需要注意的SQL兼容性问题**：

| 特性 | SQLite | PostgreSQL |
|------|--------|------------|
| JSONB | JSON (no indexing) | JSONB (GIN索引) |
| ENUM | TEXT + CHECK | ENUM type |
| 全文搜索 | FTS5 | pg_trgm / tsvector |
| 向量搜索 | ❌ | pgvector |

**PoC阶段workaround**：
1. 话题标签相似度用Python的cosine_similarity（内存计算，<100条可接受）
2. 全文搜索用SQLite FTS5（建虚拟表）
3. ENUM用TEXT + CHECK

**迁移到PG的清单**（Phase1启动时）：
- [ ] 改DATABASE_URL
- [ ] 话题向量改用pgvector
- [ ] 全文搜索改用pg_trgm
- [ ] 添加Redis缓存层
- [ ] Alembic迁移脚本

**估算：SQLite→PG迁移 0.5天**

---

## 其他建议

### 1. LLM成本估算——需要加失败重试预算

WorkBuddy估算$2.35/月/用户，但没算失败重试。实际场景：
- LLM偶发429/500错误
- 用户修改Event后重新处理
- 实体归一的人工确认→LLM重新分析

**建议加20%冗余**：$2.82/月/用户

**成本优化建议**：
1. card_save管线用GPT-4o-mini（已是最便宜）
2. meeting管线的话题提取可试Gemini 1.5 Flash（便宜30%）
3. 批量处理用batch API（50%折扣）

### 2. WorkBuddy提供的代码片段直接可用性评估

| 代码片段 | 可用性 | 需要补充 |
|---------|--------|----------|
| EntityResolutionEngine | ✅ 90%可用 | 补context_confirm实现 |
| OpportunityMatcher | ✅ 80%可用 | 补LLM prompt模板 |
| time_decay_weight | ✅ 100%可用 | - |
| SnoozeRecoveryScheduler | ✅ 95%可用 | 补APScheduler配置 |
| TopicTag表 | ✅ 100%可用 | - |
| domain_taxonomy.yaml | ✅ 100%可用 | - |

**总结**：WorkBuddy的代码质量很高，80%以上可直接集成，剩余20%是业务逻辑细节（如LLM prompt、城市解析规则）。

### 3. 技术债务预警

PoC阶段可以接受的技术债：
1. ✅ SQLite（Phase1还）
2. ✅ 内存计算向量相似度（Phase1还）
3. ✅ 无Redis缓存（Phase1还）
4. ✅ 硬编码LLM prompt（Phase2重构）

**不可接受的技术债**：
1. ❌ 不写单元测试（PoC就要写，特别是实体归一和商机匹配）
2. ❌ 不做错误处理（LLM调用必须有重试+降级）
3. ❌ 不做日志审计（调试AI行为必须）

### 4. 开发优先级建议（按dependency）

```
第1周（P0）：
├─ Day1-2: 实体归一5步算法 + 单元测试
├─ Day3-4: 商机匹配度五维算法 + 单元测试
└─ Day5: Todo状态机 + 定时恢复

第2周（P1）：
├─ Day1: 话题标签数据结构 + 余弦相似度
├─ Day2: 领域分类YAML + L2动态扩展
└─ Day3-4: same_city推断 + 时间衰减函数

第3周（集成）：
├─ Day1-2: CarryMem Protocol集成
├─ Day3: 4条管线联调
└─ Day4-5: 端到端测试 + bug修复
```

### 5. 测试策略建议

WorkBuddy没提测试，我补充：

| 模块 | 测试类型 | 覆盖率目标 |
|------|---------|-----------|
| EntityResolutionEngine | 单元测试 + 边界case | 90% |
| OpportunityMatcher | 单元测试 + LLM mock | 80% |
| Association强度计算 | 单元测试 + 时间模拟 | 95% |
| Todo状态机 | 状态转换表测试 | 100% |
| 4条管线 | 集成测试 + 真实数据 | 70% |

**关键测试case**：
1. 实体归一的边界case（同名不同人、中英文混合）
2. 商机匹配的负样本（不相关的人推荐给Todo）
3. 时间衰减的极端case（10年前的关联）

---

## 总估算

| 阶段 | 工作量 | 内容 |
|------|--------|------|
| P0补缺 | 4.5天 | 实体归一+商机匹配+Todo状态机 |
| P1补缺 | 3天 | 话题标签+领域分类+城市推断+时间衰减 |
| 文档矛盾对齐 | 1天 | 5处矛盾的代码修改 |
| 单元测试 | 2天 | 核心算法测试覆盖 |
| **合计** | **10.5天** | PoC启动前必须完成 |

**结论**：WorkBuddy的审阅非常专业，发现的9项缺失都是真缺失，提供的代码框架80%可直接用。按这个清单补齐，PoC开发可以顺利启动。

---

## 测试专家 (tester)

# 测试专家视角审阅意见

## 核心立场
作为测试专家，我关注**可测试性、边界条件、状态机完整性、算法验证**。9项技术缺失中，优先关注影响PoC验证的P0项和状态机完整性。

---

## 技术缺失共识

| # | 缺失项 | 判断 | 理由 |
|---|--------|------|------|
| 1 | 实体归一5步算法代码 | **采纳** | P0，PoC核心验证点。需补测试用例：精确匹配边界（大小写/空格/特殊字符）、置信度分级边界（0.85/0.70阈值）、HITL触发条件。建议补充测试数据集：典型场景10组 + 边界场景15组 |
| 2 | 商机匹配度五维算法 | **采纳** | P0，F-05核心算法。需补单元测试：每维度单独验证 + 权重加成测试 + 边界case（全0/全1/混合）。建议先mock LLM判断维度，避免测试不稳定 |
| 3 | Todo状态机 | **强烈采纳** | **测试最关注**。状态机是测试重点，缺失会导致：①非法状态流转无法拦截 ②snoozed恢复逻辑无法验证 ③并发操作下状态一致性问题。必须补：①状态流转表 ②CHECK约束 ③定时恢复逻辑 + 测试桩 |
| 4 | 话题标签+余弦相似度 | **修改采纳** | P1，但PoC阶段可用假数据验证。建议：①先硬编码3-5个话题标签 ②余弦相似度用numpy验证（精度≥0.0001）③Phase1前补完整embedding流程 |
| 5 | 领域分类YAML配置 | **采纳** | P1，测试需要确定性数据。YAML配置便于测试fixture加载。建议补：①schema验证 ②L2动态扩展的回归测试（防止手动编辑破坏结构） |
| 6 | same_city推断逻辑 | **修改采纳** | P1，但逻辑复杂度需控制。建议：①明确city字段规范化规则（"北京" vs "北京市" vs "Beijing"）②补城市别名表 ③测试覆盖：精确匹配/别名匹配/推断失败降级 |
| 7 | 关联强度时间衰减函数 | **采纳** | P1，数学函数需高精度测试。建议补：①标准测试向量（PRD给的5个时间点：7/30/90/180/365天）②浮点数精度验证（±0.01容差）③边界case（负数天/0天/超大天数） |
| 8 | 离线策略（前端） | **不采纳（PoC）** | P2，PoC阶段在线验证即可。Phase1前必须补，测试重点：①离线队列持久化 ②上线后同步冲突解决 ③离线期间状态变更的版本控制 |
| 9 | PromiseLink→CarryMem映射表 | **不采纳（PoC）** | P2，PoC用NullMemoryProvider即可。Phase2集成测试时补，重点验证：①映射完整性 ②写入失败回滚 ③CarryMem侧数据一致性校验 |

---

## 文档矛盾共识

| # | 矛盾点 | 对齐方案 | 理由 |
|---|--------|----------|------|
| 1 | 存储策略 | **采纳** PoC用SQLite | 测试视角：SQLite便于fixture管理、事务回滚、测试隔离。Docker单机部署无环境依赖。Phase1迁移到PG时需补：①数据迁移脚本测试 ②PG特有feature测试（如JSONB索引） |
| 2 | 关联强度时间衰减 | **采纳** 补时间衰减函数 | 测试需要确定性算法。建议补：①时间Mock机制（冻结datetime.utcnow）②回归测试（防止λ值变更导致历史数据strength失效） |
| 3 | 商机匹配度 | **采纳** 必须补五维算法 | 同缺失2。测试重点：①权重加成的可测试性（0.95总权重是否合理？）②边界case覆盖率≥90% |
| 4 | Event.raw_text长度 | **采纳** 补CHECK约束 | 测试必须验证边界。建议：①数据库层CHECK约束（≤500KB）②应用层提前校验 + 友好错误提示 ③测试case：499KB/500KB/501KB三档 |
| 5 | CarryMem协议硬编码 | **采纳** 改用SDK filter API | 测试视角：硬编码字符串匹配易碎，无法mock。改为SDK后需补：①SDK mock fixture ②filter API集成测试 ③协议版本兼容性测试 |

---

## Todo状态机详细测试建议（重点）

### 状态流转表（必须补）

```python
# tests/state_machine/test_todo_transitions.py
VALID_TRANSITIONS = {
    "pending": ["in_progress", "dismissed", "snoozed"],
    "in_progress": ["done", "dismissed", "pending"],
    "snoozed": ["pending"],
    "done": [],  # 终态
    "dismissed": [],  # 终态
}

@pytest.mark.parametrize("from_state,to_state,expected", [
    ("pending", "in_progress", True),
    ("pending", "done", False),  # 非法流转
    ("done", "pending", False),  # 终态不可逆
    ("snoozed", "in_progress", False),  # 必须先恢复到pending
])
async def test_state_transitions(from_state, to_state, expected):
    """验证状态流转合法性"""
    todo = await create_todo(status=from_state)
    result = await todo.transition_to(to_state)
    assert result.success == expected
```

### 定时恢复逻辑测试（核心）

```python
# tests/scheduler/test_snooze_recovery.py
@pytest.mark.asyncio
async def test_snooze_recovery_at_exact_time(freezer):
    """验证精确时间点恢复"""
    # 创建延期到明天10:00的Todo
    todo = await create_todo(status="snoozed", snoozed_until="2026-06-03T10:00:00Z")
    
    # 时间冻结在明天9:59:59（未到期）
    freezer.move_to("2026-06-03T09:59:59Z")
    await scheduler.recover_expired_snoozes()
    assert (await get_todo(todo.id)).status == "snoozed"
    
    # 时间冻结在明天10:00:00（到期）
    freezer.move_to("2026-06-03T10:00:00Z")
    await scheduler.recover_expired_snoozes()
    assert (await get_todo(todo.id)).status == "pending"

@pytest.mark.asyncio
async def test_snooze_recovery_preserves_original_state():
    """验证恢复到正确的原始状态"""
    # 从in_progress延期的Todo，应恢复到in_progress而非pending
    todo = await create_todo(status="in_progress")
    await todo.snooze(until="2026-06-03T10:00:00Z")
    
    # 验证original_status字段记录正确
    schedule = await get_snooze_schedule(todo.id)
    assert schedule.original_status == "in_progress"
    
    # 恢复后验证
    await scheduler.recover_expired_snoozes()
    assert (await get_todo(todo.id)).status == "in_progress"

@pytest.mark.asyncio
async def test_snooze_recovery_race_condition():
    """验证并发恢复的幂等性"""
    todo = await create_todo(status="snoozed", snoozed_until="2026-06-03T10:00:00Z")
    
    # 模拟2个scheduler实例同时执行恢复
    await asyncio.gather(
        scheduler.recover_expired_snoozes(),
        scheduler.recover_expired_snoozes(),
    )
    
    # 验证：①Todo状态正确 ②snooze_schedule记录只删除一次 ③无重复日志
    assert (await get_todo(todo.id)).status == "pending"
    assert await count_snooze_schedules() == 0
```

### 边界测试case

```python
@pytest.mark.parametrize("scenario,expected_behavior", [
    ("snooze_to_past", "reject_with_error"),  # 延期到过去时间
    ("snooze_done_todo", "reject_with_error"),  # 对已完成Todo延期
    ("dismiss_while_in_progress", "allow_and_log"),  # 进行中的Todo被忽略
    ("concurrent_status_update", "last_write_wins"),  # 并发状态更新
])
async def test_todo_edge_cases(scenario, expected_behavior):
    """边界场景测试"""
    ...
```

---

## 时间衰减函数验证建议

### 标准测试向量

```python
# tests/algorithms/test_time_decay.py
STANDARD_TEST_VECTORS = [
    # (days, expected_weight, tolerance)
    (7, 0.93, 0.01),
    (30, 0.74, 0.01),
    (90, 0.41, 0.01),
    (180, 0.17, 0.01),
    (365, 0.03, 0.01),
]

@pytest.mark.parametrize("days,expected,tolerance", STANDARD_TEST_VECTORS)
def test_time_decay_standard_vectors(days, expected, tolerance):
    """验证PRD定义的5个标准时间点"""
    last_interaction = datetime.utcnow() - timedelta(days=days)
    actual = time_decay_weight(last_interaction, lam=0.01)
    assert abs(actual - expected) <= tolerance

def test_time_decay_boundary_conditions():
    """边界条件"""
    # 负数天（未来时间）→ 返回1.0
    future = datetime.utcnow() + timedelta(days=10)
    assert time_decay_weight(future) == 1.0
    
    # 0天 → 返回1.0
    now = datetime.utcnow()
    assert time_decay_weight(now) == 1.0
    
    # 超大天数（10年）→ 趋近0但不报错
    very_old = datetime.utcnow() - timedelta(days=3650)
    assert 0 <= time_decay_weight(very_old) < 0.01
```

---

## 实体归一算法测试建议

### 测试数据集设计

```python
# tests/fixtures/entity_resolution_cases.py
TYPICAL_CASES = [
    {
        "name": "完全相同（大小写不敏感）",
        "new": {"name": "张三", "company": "字节跳动"},
        "existing": [{"name": "张三", "company": "字节跳动"}],
        "expected_action": "MERGE",
        "expected_confidence": 1.0,
    },
    {
        "name": "别名匹配",
        "new": {"name": "Bob", "company": "Google"},
        "existing": [{"name": "Robert", "aliases": ["Bob"], "company": "Google"}],
        "expected_action": "MERGE",
        "expected_confidence": 0.95,
    },
    # ... 补充到10组
]

BOUNDARY_CASES = [
    {
        "name": "同名不同公司（置信度0.75，需确认）",
        "new": {"name": "李四", "company": "阿里巴巴"},
        "existing": [{"name": "李四", "company": "腾讯"}],
        "expected_action": "CONFIRM",
        "expected_confidence": 0.75,
    },
    {
        "name": "模糊匹配边界（编辑距离=1，刚好85%）",
        "new": {"name": "Wang Lei", "company": "Microsoft"},
        "existing": [{"name": "Wang Le", "company": "Microsoft"}],
        "expected_action": "MERGE",  # or CONFIRM，取决于算法实现
        "min_confidence": 0.85,
    },
    # ... 补充到15组
]
```

### 算法正确性验证

```python
@pytest.mark.parametrize("case", TYPICAL_CASES)
async def test_entity_resolution_typical(case):
    """典型场景验证"""
    result = await resolution_engine.resolve(case["new"], case["existing"])
    assert result.action == case["expected_action"]
    assert abs(result.confidence - case["expected_confidence"]) < 0.05

@pytest.mark.parametrize("case", BOUNDARY_CASES)
async def test_entity_resolution_boundary(case):
    """边界场景验证"""
    result = await resolution_engine.resolve(case["new"], case["existing"])
    assert result.action == case["expected_action"]
    if "min_confidence" in case:
        assert result.confidence >= case["min_confidence"]
```

---

## Slogan共识

**不采纳（超出测试职责）**

测试专家不评价市场文案。但从测试视角提醒：Slogan变更需同步更新：
- UI文案测试case
- 截图/视频素材验证
- 多语言翻译一致性测试

---

## PoC存储共识

**采纳 SQLite方案**

测试视角理由：
1. **测试隔离性**：每个测试用例独立数据库文件，无需复杂的清理逻辑
2. **Fixture管理**：SQLite文件可直接打包为测试fixture，便于回归测试
3. **事务回滚**：测试失败时事务自动回滚，无残留数据
4. **零环境依赖**：CI/CD无需配置PG/Redis服务
5. **性能基准**：PoC阶段数据量小，SQLite足够验证业务逻辑

Phase1迁移到PG时需补：
- **数据迁移测试**：SQLite→PG迁移脚本的正确性验证
- **JSONB索引测试**：PG特有feature的性能测试
- **并发测试**：PG的事务隔离级别验证

---

## 其他建议

### 1. LLM调用的可测试性设计（P0）

**问题**：商机匹配度D4维度和实体归一Step 3都依赖LLM，测试不稳定。

**建议**：
```python
# 抽象LLM调用为接口
class LLMProvider(Protocol):
    async def semantic_judge(self, prompt: str) -> float:
        ...

# 测试时注入MockLLMProvider
class MockLLMProvider:
    def __init__(self, responses: dict):
        self.responses = responses  # 预设响应映射表
    
    async def semantic_judge(self, prompt: str) -> float:
        # 根据prompt关键词返回预设分数
        for keyword, score in self.responses.items():
            if keyword in prompt:
                return score
        return 0.5  # 默认中等分数

# 测试用法
@pytest.fixture
def mock_llm():
    return MockLLMProvider({
        "SaaS + CRM": 0.9,
        "医疗 + 互联网": 0.7,
        "完全不相关": 0.1,
    })

async def test_opportunity_matching_with_mock_llm(mock_llm):
    matcher = OpportunityMatcher(llm_provider=mock_llm)
    score = await matcher.calculate_match_score(...)
    assert score >= 0.8  # 验证逻辑正确性，而非LLM准确性
```

### 2. 置信度阈值的配置化（P1）

**问题**：实体归一的0.85/0.70阈值硬编码，无法A/B测试。

**建议**：
```yaml
# configs/entity_resolution.yaml
confidence_thresholds:
  auto_merge: 0.85
  require_confirm: 0.70
  
# 测试时可覆盖
@pytest.fixture
def resolution_config():
    return {
        "auto_merge": 0.80,  # 降低阈值，测试更多边界case
        "require_confirm": 0.65,
    }
```

### 3. 关联强度计算的回归测试（P1）

**问题**：关联强度公式复杂（base + evidence + decay + frequency），修改一处可能破坏全局。

**建议**：
```python
# tests/regression/test_association_strength.py
# 固化20个真实case的计算结果，防止算法变更导致历史数据失效
REGRESSION_VECTORS = [
    {
        "case": "校友关系，刚认识，低频",
        "input": {
            "base": 0.5,
            "evidence_count": 1,
            "last_interaction": "2026-06-01",
            "frequency": 1,
        },
        "expected": 0.55,  # base 0.5 + evidence 0.05 = 0.55
    },
    # ... 补充到20组
]

@pytest.mark.parametrize("vector", REGRESSION_VECTORS)
def test_association_strength_regression(vector, freezer):
    freezer.move_to("2026-06-02")  # 冻结时间
    actual = calculate_association_strength(**vector["input"])
    assert abs(actual - vector["expected"]) < 0.01
```

### 4. Todo生成的幂等性测试（P0）

**问题**：同一个Event多次触发Todo生成，会产生重复Todo吗？

**建议**：
```python
async def test_todo_generation_idempotency():
    """验证同一Event不会重复生成Todo"""
    event = await create_event(...)
    
    # 第一次生成
    todos_1 = await generate_todos(event)
    assert len(todos_1) == 3
    
    # 再次调用（模拟重试/重启）
    todos_2 = await generate_todos(event)
    assert len(todos_2) == 3
    
    # 验证：①数据库中只有3条Todo ②ID相同
    all_todos = await db.query(Todo).filter_by(event_id=event.id).all()
    assert len(all_todos) == 3
    assert set(t.id for t in todos_1) == set(t.id for t in todos_2)
```

### 5. 性能基线测试（P2，Phase1前补）

**问题**：PRD定义了P95延迟要求（名片<1s，会议<5s），但技术设计没有验证方案。

**建议**：
```python
# tests/performance/test_latency.py
@pytest.mark.performance
async def test_card_save_p95_latency():
    """验证名片扫描P95 < 1s"""
    latencies = []
    for _ in range(100):
        start = time.time()
        await process_card_save(sample_card_image)
        latencies.append(time.time() - start)
    
    p95 = np.percentile(latencies, 95)
    assert p95 < 1.0, f"P95延迟 {p95:.2f}s 超过1s要求"
```

---

## 总结：测试优先级建议

| 优先级 | 项目 | 验收标准 |
|--------|------|---------|
| **P0** | Todo状态机测试 | ①状态流转覆盖率100% ②定时恢复逻辑验证 ③并发安全测试 |
| **P0** | 实体归一算法测试 | ①典型case 10组 ②边界case 15组 ③置信度精度±0.05 |
| **P0** | LLM调用Mock机制 | ①所有LLM调用可mock ②测试稳定性>99% |
| **P1** | 商机匹配度算法测试 | ①五维度单独验证 ②权重加成测试 ③边界case覆盖率≥90% |
| **P1** | 时间衰减函数测试 | ①PRD 5个标准向量 ②浮点精度±0.01 ③边界条件覆盖 |
| **P1** | 关联强度回归测试 | ①固化20个真实case ②算法变更时强制运行 |
| **P2** | 性能基线测试 | ①P95延迟验证 ②Phase1前完成 |

---

## 安全专家 (security)

# Security角色审阅反馈

## 身份声明
作为安全专家，我的职责是识别和缓解数据泄露、注入攻击、权限滥用、隐私侵犯等风险。我关注的核心是：用户数据在采集、存储、传输、访问各环节的保护措施是否充分。

---

## 技术缺失共识

| # | 缺失项 | 判断 | 理由 |
|---|--------|------|------|
| 1 | 实体归一5步算法 | **采纳** | 从安全角度，算法透明性有助于审计误合并风险。建议补充：在HITL确认环节记录审计日志（谁在何时确认了哪个归一决策），用于追溯误合并导致的数据泄露 |
| 2 | 商机匹配度五维算法 | **采纳** | 算法本身无安全问题。但LLM语义判断（D4）需要传输Todo和Person的敏感信息到外部API，建议补充：1) PII脱敏策略（姓名→hash，手机号→mask）；2) LLM调用日志审计 |
| 3 | Todo状态机 | **采纳** | 状态机本身无安全问题。但snoozed状态涉及定时任务，建议补充：防止恶意用户通过批量snooze DDoS定时恢复器（限制每用户同时snooze的Todo数量≤50） |
| 4 | 话题标签+余弦相似度 | **修改采纳** | 算法无安全问题，但topic_vector存储1536维float需要约6KB/条。建议：1) 限制每个event的话题标签数量≤20；2) 向量数据不进入备份（可重新生成），减少泄露面 |
| 5 | 领域分类YAML配置 | **采纳** | 配置文件本身无安全问题。建议补充：L2动态扩展需要admin权限操作，记录审计日志（谁添加了哪个L2分类） |
| 6 | same_city推断逻辑 | **修改采纳** | 城市信息本身是敏感PII（可定位用户）。建议补充：1) company_city和residence_city分别存储，访问权限分离；2) visited_city仅保留30天（GDPR最小必要原则）；3) 城市推断的LLM调用需脱敏（"某人在北京见面"→"在[CITY]见面"） |
| 7 | 关联强度时间衰减 | **采纳** | 算法无安全问题 |
| 8 | 离线策略（前端） | **修改采纳** | **关键安全风险**：离线数据存储在客户端，若用户设备丢失或被盗，敏感数据可能泄露。建议补充：1) 离线数据必须加密存储（AES-256-GCM，密钥派生自用户PIN+设备指纹）；2) 离线数据TTL=7天自动清除；3) 用户可远程擦除离线数据（通过服务端推送指令） |
| 9 | PromiseLink→CarryMem映射 | **修改采纳** | **关键安全风险**：跨系统写入需要明确权限边界。建议补充：1) declare_memory调用必须携带scoped token（仅能写入特定类型记忆）；2) CarryMem应验证写入来源（PromiseLink的service account）；3) 敏感决策（如"用户忽略某Todo"）应加签名防篡改 |

---

## 文档矛盾共识

| # | 矛盾点 | 对齐方案 | 理由 |
|---|--------|----------|------|
| 1 | 存储策略 | **修改采纳**：PoC用SQLite，但必须补充加密方案 | SQLite文件若被复制走，所有数据暴露。建议：1) 使用SQLCipher（SQLite加密扩展）；2) 密钥存储在环境变量或密钥管理服务，不硬编码；3) PoC结束后销毁数据库文件 |
| 2 | 关联强度时间衰减 | **采纳** | 无安全影响 |
| 3 | 商机匹配度算法 | **采纳**（见技术缺失#2的补充） | 需补充LLM调用的PII脱敏 |
| 4 | **Event.raw_text长度限制** | **强烈采纳500KB限制** | **关键安全问题**：1) 防止DoS攻击（恶意用户上传GB级文本耗尽存储）；2) 防止成本攻击（超长文本导致LLM token费用爆炸）；3) 防止信息过载（500KB约25万字，已经是极限会议记录）。建议实现：应用层校验+PG CHECK约束双重防护，超长文本截断并记录告警 |
| 5 | CarryMem协议 | **采纳**，改用SDK filter API | 硬编码字符串匹配易被绕过（如注入特殊字符），SDK API通常有输入验证 |

---

## Slogan共识

**不采纳**

**理由**：Slogan变更不是安全专家的职责范围。但从隐私角度提醒：任何对外宣传都不应暗示"我们会分析你的所有社交关系"，避免引发隐私担忧。现有和建议的Slogan都未触及红线，可以使用。

---

## PoC存储共识

**修改采纳：SQLite + SQLCipher加密**

**理由**：
1. **支持SQLite的原因**：PoC阶段零新依赖，降低攻击面（不引入PG/Redis的远程访问漏洞）
2. **强制加密的原因**：PoC通常在开发者本机或测试服务器运行，这些环境的物理安全和访问控制较弱。SQLite文件若被拷贝走，所有用户数据（包括名片、会议记录、商业机密）全部泄露
3. **具体方案**：
   ```python
   # 使用SQLCipher
   from sqlalchemy import create_engine
   
   db_key = os.environ.get("PROMISELINK_DB_KEY")  # 从环境变量读取
   if not db_key:
       raise RuntimeError("DB encryption key not set")
   
   engine = create_engine(
       f"sqlite+pysqlcipher://:{db_key}@/promiselink_poc.db"
   )
   ```
4. **密钥管理**：PoC阶段可以用环境变量，Phase1必须切换到密钥管理服务（如AWS KMS、HashiCorp Vault）

**Phase1切换到PG+Redis后的额外要求**：
- PG必须启用TLS连接
- Redis必须启用AUTH认证+TLS
- 数据库备份必须加密存储

---

## 其他建议

### 1. raw_text的安全处理（高优先级）

**问题**：PRD说raw_text≤500KB，但技术设计用TEXT无限制，这是**DoS攻击和成本攻击的双重风险**。

**建议**：
```sql
-- 方案A: PG CHECK约束（运行时验证）
ALTER TABLE events ADD CONSTRAINT raw_text_max_size 
    CHECK (octet_length(raw_text) <= 512000);  -- 500KB=512000字节

-- 方案B: 应用层双重验证
async def create_event(raw_text: str, ...):
    if len(raw_text.encode('utf-8')) > 512000:
        # 截断+告警
        logger.warning(
            "raw_text exceeds 500KB, truncating",
            extra={"user_id": user_id, "size": len(raw_text)}
        )
        raw_text = raw_text[:500000]  # 粗略截断到500K字符
    
    # 继续处理...
```

**附加防护**：
- 速率限制：每用户每天最多上传10个event（防止批量攻击）
- 内容扫描：检测raw_text中的恶意payload（如SQL注入片段、XSS脚本）

---

### 2. CarryMem写入权限隔离（高优先级）

**问题**：PromiseLink通过declare_memory写入CarryMem，若权限控制不当，PromiseLink的漏洞可能污染CarryMem的全部用户数据。

**建议**：
```python
# PromiseLink调用CarryMem时使用scoped token
class CarryMemClient:
    def __init__(self):
        self.token = self._get_scoped_token(
            scope=["memory:write:fact", "memory:write:decision"],
            exclude=["memory:write:rule"]  # 不允许写入规则
        )
    
    async def declare_memory(self, user_id: str, entry: dict):
        # 验证entry类型在允许范围内
        if entry["type"] not in ["fact_declaration", "decision"]:
            raise PermissionError(f"PromiseLink cannot write {entry['type']}")
        
        # 调用CarryMem API，携带scoped token
        await self.carrymem_api.post(
            "/memories",
            json=entry,
            headers={"Authorization": f"Bearer {self.token}"}
        )
```

**权限矩阵**：
| PromiseLink产出 | CarryMem记忆类型 | PromiseLink是否可写 |
|--------------|-----------------|------------------|
| 新实体 | fact_declaration | ✅ |
| 新关联 | relationship | ✅ |
| 用户确认归一 | decision | ✅ |
| 用户忽略Todo | user_preference | ❌（应通过CarryMem的规则引擎API） |
| 商机匹配结果 | decision | ✅ |

---

### 3. 离线策略的安全加固（Phase1前必须完成）

**问题**：WorkBuddy报告提到"离线策略缺失"，但从安全角度，离线功能是**最高风险**功能之一。

**必须实现的安全措施**（按优先级）：

**P0（不实现则不能上线）**：
1. **端到端加密**：离线数据用AES-256-GCM加密，密钥派生自用户PIN+设备指纹
   ```javascript
   // 前端示例
   const deviceKey = await deriveKey(userPIN, deviceFingerprint);
   const encryptedData = await crypto.subtle.encrypt(
       { name: "AES-GCM", iv: randomIV },
       deviceKey,
       offlineData
   );
   localStorage.setItem("promiselink_offline", encryptedData);
   ```

2. **远程擦除**：用户在Web端可触发"擦除所有设备的离线数据"
   ```python
   # 后端API
   @app.post("/api/users/{user_id}/wipe-offline")
   async def wipe_offline_data(user_id: str):
       # 推送擦除指令到所有设备
       await push_service.send(
           user_id=user_id,
           message={"action": "wipe_offline_data"}
       )
       # 记录审计日志
       await audit_log.write({
           "user_id": user_id,
           "action": "wipe_offline_requested",
           "timestamp": datetime.utcnow()
       })
   ```

3. **自动过期**：离线数据TTL=7天，超期自动删除
   ```javascript
   const offlineData = JSON.parse(localStorage.getItem("promiselink_offline"));
   if (Date.now() - offlineData.timestamp > 7 * 24 * 60 * 60 * 1000) {
       localStorage.removeItem("promiselink_offline");
   }
   ```

**P1（建议实现）**：
4. **生物识别验证**：访问离线数据需要Face ID/Touch ID
5. **离线数据最小化**：仅缓存"最近7天的Todo+最近见过的50个人"，不缓存完整关系图

---

### 4. LLM调用的PII脱敏（Phase1前必须完成）

**问题**：商机匹配度算法的D4维度需要把Todo和Person的敏感信息发给LLM，这是**数据泄露风险**。

**建议**：
```python
def sanitize_for_llm(todo: Todo, person: Entity) -> dict:
    """脱敏敏感字段后再传给LLM"""
    return {
        "todo": {
            "description": todo.description,  # 保留
            "keywords": todo.keywords,  # 保留
            "domain_l1": todo.domain_l1,  # 保留
            # 不传递：user_id, raw_event_text
        },
        "person": {
            "name_hash": hashlib.sha256(person.name.encode()).hexdigest()[:8],  # 脱敏
            "company": person.properties.get("company"),  # 保留
            "title": person.properties.get("title"),  # 保留
            "industry": person.properties.get("industry"),  # 保留
            # 不传递：phone, email, wechat_id
        }
    }

# LLM调用
async def _llm_semantic_judge(self, todo: Todo, person: Entity) -> float:
    sanitized = sanitize_for_llm(todo, person)
    response = await openai.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{
            "role": "user",
            "content": f"判断以下商机和人物的匹配度：{json.dumps(sanitized)}"
        }]
    )
    # 记录审计日志
    await audit_log.write({
        "action": "llm_judge",
        "sanitized_input": sanitized,
        "user_id": todo.user_id
    })
    return float(response.choices[0].message.content)
```

---

### 5. 审计日志的强制要求（Phase1前必须完成）

**必须记录的操作**（按重要性）：
1. **P0（数据变更）**：
   - 实体归一确认/拒绝（谁合并了哪两个实体）
   - Todo状态变更（谁把Todo标记为done/dismissed）
   - 关联创建/删除（谁建立了A和B的关联）
   
2. **P1（敏感查询）**：
   - 查询某人的完整关系图（谁查了谁的人脉）
   - 导出数据（谁导出了哪些数据）
   
3. **P2（系统操作）**：
   - 登录/登出
   - 权限变更

**审计日志格式**：
```json
{
    "timestamp": "2026-06-02T10:30:00Z",
    "user_id": "user_123",
    "action": "entity_merge_confirmed",
    "details": {
        "source_entity_id": "ent_456",
        "target_entity_id": "ent_789",
        "confidence": 0.82
    },
    "ip": "203.0.113.42",
    "user_agent": "PromiseLink-iOS/1.0"
}
```

**保留期限**：
- PoC：30天
- Phase1+：1年（符合GDPR要求）

---

## 总结：安全专家的核心关注

| 风险项 | 当前状态 | 建议行动 | 优先级 |
|--------|---------|---------|--------|
| raw_text无限制 | 🔴 高风险 | 强制500KB限制+截断 | P0 |
| 离线数据未加密 | 🔴 高风险 | 端到端加密+远程擦除 | P0（Phase1前） |
| LLM调用传输PII | 🟡 中风险 | PII脱敏+审计日志 | P1 |
| CarryMem写入无隔离 | 🟡 中风险 | scoped token+权限矩阵 | P1 |
| PoC用明文SQLite | 🟡 中风险 | 改用SQLCipher | P0 |
| 缺少审计日志 | 🟡 中风险 | 补齐P0操作日志 | P1 |
| same_city泄露位置 | 🟢 低风险 | visited_city 30天TTL | P2 |

**Bottom Line（红线）**：
1. raw_text必须限制500KB，不能妥协
2. 离线功能如果不加密，Phase1不能上线
3. PoC的SQLite必须加密，即使只有5个用户

以上。

---

## 运维工程师 (devops)

# DevOps角色审阅报告

## 角色声明
作为运维工程师，我重点关注：部署复杂度、迁移风险、成本可控性、监控可观测性、故障恢复能力。

---

## 技术缺失共识

| # | 缺失项 | 判断 | 理由 |
|---|--------|------|------|
| 1 | 实体归一5步算法 | **采纳** | 算法逻辑不影响运维，但需要确保异常case不会导致死循环或OOM。建议加超时和内存限制 |
| 2 | 商机匹配度五维算法 | **采纳** | 同上，关注点是LLM调用的超时和降级策略。建议补circuit breaker |
| 3 | Todo状态机 | **强烈采纳** | 状态机混乱会导致数据不一致，直接影响运维排障。PG ENUM + CHECK约束是正确方案。定时恢复任务需要idempotent设计，避免重复执行 |
| 4 | 话题标签+余弦相似度 | **采纳** | 1536维向量存储需要评估PG性能。如果Phase1日活>50人，建议引入pgvector扩展而非纯JSON存储 |
| 5 | 领域分类YAML配置 | **修改采纳** | YAML配置可以，但需要热加载机制。不能每次改配置都重启服务。建议用etcd/consul或至少支持SIGHUP重载 |
| 6 | same_city推断逻辑 | **采纳** | 逻辑合理，但城市名需要标准化（如"北京"/"Beijing"/"BJ"统一）。建议维护城市别名映射表 |
| 7 | 关联强度时间衰减函数 | **采纳** | 纯计算逻辑，无运维风险。但需要在监控中加"异常高强度关联"告警，防止算法bug |
| 8 | 离线策略（前端） | **修改采纳** | Phase1前必须补，但需要明确离线数据的本地存储上限（如最多缓存100条Todo）。否则用户设备存储被撑爆 |
| 9 | PromiseLink→CarryMem映射表 | **采纳** | 需要补，且需要版本化。如果CarryMem协议升级，旧版PromiseLink不能写坏数据 |

---

## 文档矛盾共识

| # | 矛盾点 | 对齐方案 | 理由 |
|---|--------|---------|------|
| 1 | **存储策略** | **强烈采纳PoC用SQLite** | 见下方"PoC存储共识"详细分析 |
| 2 | 关联强度时间衰减 | **采纳补时间衰减** | 算法逻辑无运维影响，但需要在监控dashboard加"平均关联强度"指标，观察衰减是否符合预期 |
| 3 | 商机匹配度算法 | **采纳补五维算法** | 五维算法涉及多次LLM调用（D4维度）。运维关注点：需要补**并发限流**和**成本告警**。单用户每日LLM调用>1000次应触发告警 |
| 4 | Event.raw_text长度 | **修改采纳** | 不能无限制。建议：PG层TEXT类型+应用层校验≤1MB（2倍PRD的500KB冗余）。超过1MB的会议记录应该拆分Event或压缩存储 |
| 5 | CarryMem协议硬编码 | **采纳改用SDK** | 硬编码字符串匹配是运维噩梦，协议升级必炸。必须用CarryMem SDK的versioned API |

---

## PoC存储共识

### 强烈建议：PoC用SQLite

**采纳理由**：

1. **零运维成本**
   - 无需Docker编排Redis/PG
   - 无需配置主从、备份策略
   - 单个文件`promiselink.db`，`cp`即备份

2. **和CarryMem技术栈一致**
   - CarryMem已验证SQLite在单机5-10用户场景稳定
   - 共享运维经验，不引入新变量

3. **PoC目标聚焦**
   - PoC验证的是"AI能否准确抽取实体/关联/Todo"，不是验证"PG能否扛住100 QPS"
   - 过早优化是万恶之源

4. **迁移风险可控**
   - SQLite→PG的数据迁移是标准操作
   - Schema几乎1:1映射（除了JSON→JSONB）
   - 3周PoC期间数据量<1000条，dump+restore<10分钟

**Phase1迁移复杂度评估**：

| 迁移项 | 复杂度 | 工作量 | 风险 |
|--------|--------|--------|------|
| Schema迁移 | 低 | 4小时 | 低（自动化工具成熟） |
| 数据迁移 | 低 | 2小时 | 低（数据量<10MB） |
| 应用层改造 | 中 | 1天 | 中（需要改连接池、事务隔离级别） |
| Redis缓存层 | 中 | 1天 | 中（需要设计缓存key命名、失效策略） |
| 部署脚本 | 中 | 0.5天 | 低（Docker Compose模板现成） |
| **总计** | | **3天** | **可控** |

**Phase1迁移检查清单**：

```bash
# 迁移前检查
□ PoC数据备份（sqlite3 .dump）
□ PG schema DDL准备（含索引、约束）
□ 数据清洗脚本（去重、格式统一）

# 迁移中操作
□ 停止PoC服务（维护窗口通知用户）
□ SQLite数据导出→CSV
□ PG数据导入（COPY命令）
□ 数据一致性校验（count/checksum）

# 迁移后验证
□ 应用层smoke test（增删改查）
□ LLM管线端到端测试
□ 监控指标确认（响应时间、错误率）
□ 回滚预案演练
```

**不采纳ES的理由**（Phase2再评估）：

- PoC+Phase1阶段数据量<10万条，PG的GIN索引+pg_trgm足够
- ES引入后：多一个服务要运维、多一套数据同步链路（双写或binlog订阅）、多一个故障点
- 过早优化的代价：ES集群最低3节点（master选举），PoC/Phase1根本用不上

---

## LLM成本共识

### 现有估算的问题

WorkBuddy给的$2.35/月/用户是**理想场景**，未考虑：

1. **降级场景成本**
   - LLM超时重试：每次重试消耗翻倍
   - 用户反复修改：归一确认、Todo编辑触发重新计算
   - 批量历史数据处理：Phase1迁移时重新跑管线

2. **隐藏成本**
   - Embedding向量生成（话题标签、实体描述）：text-embedding-3-small约$0.02/1M tokens
   - 商机匹配D4维度（LLM语义判断）：高频触发

3. **峰值成本**
   - 用户批量上传会议记录：单日token消耗可能是平均值的5-10倍

### 修改采纳建议

| 场景 | WorkBuddy估算 | 补充成本 | 调整后估算 |
|------|--------------|---------|-----------|
| 正常使用 | $2.35/月 | +$0.5（Embedding+重试） | $2.85/月 |
| 峰值场景 | - | +$1.5（批量处理+反复修改） | $4.35/月 |
| **安全预算** | | | **$5/月/活跃用户** |

**成本控制措施**（必须在Phase1实现）：

```python
# 用户级别限流
class LLMRateLimiter:
    MAX_TOKENS_PER_DAY = 50_000  # 每用户每日token上限
    MAX_CALLS_PER_HOUR = 100     # 每用户每小时调用次数上限
    
    async def check_quota(self, user_id: str) -> bool:
        daily_usage = await redis.get(f"llm:daily:{user_id}")
        hourly_calls = await redis.get(f"llm:hourly:{user_id}")
        
        if daily_usage > self.MAX_TOKENS_PER_DAY:
            # 降级到缓存结果或简化算法
            return False
        if hourly_calls > self.MAX_CALLS_PER_HOUR:
            # 触发限流告警
            return False
        return True
```

**监控告警阈值**：

| 指标 | 告警阈值 | 动作 |
|------|---------|------|
| 单用户日消耗 | >$10 | 人工审核（是否滥用） |
| 全局日消耗 | >$500 | 限流策略启用 |
| LLM错误率 | >5% | 切换降级模型（gpt-3.5-turbo） |

---

## Slogan共识

**不采纳（非运维职责）**

Slogan是品牌/产品决策，运维无发言权。但从**技术指标命名**角度，建议：

- 如果用"见面只是开始"，监控指标不要叫"meeting_start_count"，应该叫"connection_initiated"（更符合slogan语境）

---

## 其他建议

### 1. 监控可观测性缺失（P0）

技术设计提到"监控告警阈值"，但没有**指标体系设计**。建议补：

```yaml
# 关键指标（遵循RED方法）
Rate:
  - api_requests_per_second
  - llm_calls_per_minute
  - entity_resolution_per_hour

Errors:
  - api_error_rate (目标<1%)
  - llm_timeout_rate (目标<5%)
  - entity_merge_conflict_rate (目标<2%)

Duration:
  - api_p95_latency (目标<500ms)
  - llm_p95_latency (目标<3s)
  - pipeline_end_to_end_p95 (目标<10s)

# 业务指标
Business:
  - daily_active_users
  - events_processed_per_day
  - todos_generated_per_user
  - association_discovery_rate (新关联/事件数)
```

**告警规则**：

| 指标 | 告警条件 | 严重级别 |
|------|---------|---------|
| api_error_rate | >5% 持续5分钟 | P1 |
| llm_timeout_rate | >10% | P2 |
| daily_llm_cost | >$500 | P1 |
| postgres_connection_pool | >80%使用率 | P2 |

### 2. 备份策略缺失（P1）

技术设计提了"PG备份策略"但没细节。建议：

**PoC阶段（SQLite）**：
```bash
# 每日备份
0 2 * * * cp /data/promiselink.db /backup/promiselink_$(date +\%Y\%m\%d).db

# 保留策略：最近7天全量 + 每周日归档
```

**Phase1阶段（PostgreSQL）**：
```bash
# 增量备份（WAL归档）
archive_mode = on
archive_command = 'cp %p /backup/wal/%f'

# 全量备份（每日）
0 2 * * * pg_dump promiselink | gzip > /backup/promiselink_$(date +\%Y\%m\%d).sql.gz

# 保留策略：
# - 最近7天：全量
# - 最近30天：每周日全量
# - 30天前：每月1日全量
```

**RTO/RPO目标**：
- PoC: RTO=1小时, RPO=24小时（可接受丢失1天数据）
- Phase1: RTO=15分钟, RPO=1小时（WAL归档）

### 3. 容灾演练缺失（P2）

建议Phase1前进行一次**故障注入演练**：

| 场景 | 注入方式 | 预期恢复时间 |
|------|---------|-------------|
| PG主库宕机 | `systemctl stop postgresql` | <15分钟（手动切从库） |
| Redis全失效 | `redis-cli FLUSHALL` | <5分钟（应用层降级，直连PG） |
| LLM服务超时 | 网络延迟注入 | 立即（降级到缓存结果） |
| 磁盘满 | `fallocate -l 10G` | <30分钟（清理日志+扩容） |

### 4. 部署架构建议

**PoC阶段**：
```
单机Docker
├── promiselink-api (FastAPI)
├── promiselink-worker (Celery)
├── promiselink-scheduler (APScheduler)
└── promiselink.db (SQLite)
```

**Phase1阶段**：
```
Docker Compose
├── promiselink-api (2副本 + Nginx LB)
├── promiselink-worker (2副本)
├── promiselink-scheduler (1副本)
├── postgres (主)
├── postgres-replica (从，只读)
└── redis (单实例，非集群模式)
```

**Phase2阶段**（视数据量）：
- PG切主从+连接池（PgBouncer）
- Redis切哨兵模式
- 考虑K8s（如果需要弹性扩容）

### 5. 日志策略

**PoC阶段**：
- stdout/stderr直接输出
- Docker logs保留7天

**Phase1阶段**：
- 结构化日志（JSON格式）
- 分级：DEBUG/INFO/WARN/ERROR
- 敏感信息脱敏（raw_text中的手机号/邮箱）
- 日志聚合（ELK或Loki）

**关键日志点**：
```python
# 必须记录的操作
- 实体归一决策（merge/confirm/create）
- LLM调用（prompt hash, token消耗, 耗时）
- Todo状态流转
- CarryMem写入操作
- 用户敏感操作（删除Event/Entity）
```

---

## 最终判断总结

| 类别 | 采纳项 | 修改采纳项 | 不采纳项 |
|------|--------|-----------|---------|
| 技术缺失 | 1,2,3,4,6,7,9 | 5,8 | 无 |
| 文档矛盾 | 1,2,3,5 | 4 | 无 |
| 其他建议 | PoC用SQLite | LLM成本+$2.65安全冗余 | Slogan（非运维职责） |

**最关键的3个建议**：
1. **PoC用SQLite**（零运维成本，3周后迁移PG工作量仅3天）
2. **Todo状态机必须补**（数据一致性影响运维排障）
3. **LLM成本预算从$2.35调整到$5**（含降级+峰值+Embedding）

**Phase1前必须补的运维基础设施**：
- 监控指标体系（Prometheus + Grafana）
- 备份+恢复演练
- 日志聚合（至少是结构化JSON）
- LLM成本+限流告警

---

## UI设计师 (ui-designer)

# UI设计师视角的PromiseLink审阅共识

## 核心立场
作为UI设计师，我关注的优先级是：**用户可感知的体验** > **视觉和交互设计依赖** > **后台算法细节**。我会重点评估那些直接影响界面状态、用户操作流程、信息呈现的技术点。

---

## 技术缺失共识

| # | 缺失项 | 判断 | 理由 |
|---|--------|------|------|
| 1 | 实体归一5步算法 | **采纳**（P0） | 直接决定"合并/新建"确认弹窗的触发时机和置信度展示。没有这个算法，交互设计无法确定何时打断用户、如何呈现合并建议 |
| 2 | 商机匹配度五维算法 | **采纳**（P0） | Todo卡片需要展示匹配理由（如"同行业·话题相关"），无此算法无法设计推荐理由的信息层级和视觉权重 |
| 3 | Todo状态机（CHECK+流转+定时恢复） | **强烈采纳**（P0） | **这是最影响UX的缺失**。snoozed状态的交互设计完全依赖状态机：<br>• 用户点"稍后处理"后界面如何反馈？<br>• snoozed卡片的视觉样式？（置灰？标记？）<br>• 到期恢复时如何通知？（消息？红点？）<br>• in_progress和pending的视觉区分度？<br>没有状态机定义，Todo模块的所有交互都无法落地 |
| 4 | 话题标签数据结构+余弦相似度 | **修改采纳**（P1→P2） | 话题标签在界面上是辅助信息（卡片下方的tag云），不影响核心流程。PoC阶段可以用简化的关键词提取+精确匹配，Phase1再补余弦相似度 |
| 5 | 领域分类YAML配置+L2动态扩展 | **修改采纳**（P1→P2） | 行业标签在UI上是单选/多选筛选器，PoC固定18个L1够用。L2动态扩展是后台逻辑，不影响前端交互 |
| 6 | same_city推断逻辑 | **采纳**（P1） | 影响关联卡片的"同城"标签展示和筛选功能，但PoC阶段不做地理筛选可以降级处理 |
| 7 | 关联强度时间衰减函数 | **修改采纳**（P1→P2） | 关联强度决定"强关联/弱关联"的视觉样式（线条粗细、颜色深浅），但PoC阶段可以用静态基准值，Phase1再加时间衰减 |
| 8 | 离线策略（前端） | **强烈采纳**（P0→P1） | **许总"开车去拜访"场景是真实痛点**，TTS播报在离线时必须可用。但技术上可以分阶段：<br>• PoC：仅支持在线，明确告知用户<br>• Phase1：必须支持离线缓存+后台同步<br>建议升级到P1，Phase1启动前必须有方案 |
| 9 | PromiseLink→CarryMem写入映射表 | **不采纳**（P2保持） | 这是后台集成细节，不影响用户可见的交互 |

---

## 文档矛盾共识

| # | 矛盾点 | 对齐方案 | 理由 |
|---|--------|---------|------|
| 1 | **存储策略** | **采纳WorkBuddy建议**（PoC用SQLite，Phase1用PG+Redis） | 从UX角度，用户感知不到数据库类型，但SQLite部署更轻量，PoC验证速度更快。关键是要在UI上做**性能预期管理**：如果PoC阶段搜索慢，需要loading状态+预期时间提示 |
| 2 | **关联强度** | **修改采纳**（Phase1补时间衰减，PoC用静态值） | 时间衰减影响"强/弱关联"的视觉呈现，但PoC阶段可以用固定强度，Phase1再优化。需要在设计系统中预留"强度等级"的视觉变量（如opacity 40%/60%/100%） |
| 3 | **商机匹配度** | **强烈采纳**（必须补五维算法） | 直接影响Todo卡片的推荐理由展示，这是说服用户采纳建议的关键。UI需要设计"为什么推荐"的信息层级（主标题+副标题+标签） |
| 4 | **Event.raw_text长度** | **采纳**（补CHECK约束≤500KB） | 超长文本会导致移动端渲染卡顿，必须在数据层限制。UI设计需要配合"文本截断+展开"交互 |
| 5 | **CarryMem协议** | **不采纳**（P2保持） | 后台技术细节，不影响用户交互 |

---

## Slogan共识

### 情感分析（UI设计师核心能力）

**现有Slogan的UX问题：**
1. **"让重要的人，不止停留在微信里"**
   - 情绪基调：**轻微焦虑**（"停留"暗示一种困境）
   - 用户反应：理性认同但缺乏行动冲动
   - 视觉延展困难：很难从这句话推导出视觉语言

2. **"每次见面，都不白费"**
   - 情绪基调：**防御性**（"不白费"是负面避损）
   - 用户反应："嗯有道理"但不会主动分享
   - 视觉延展困难：slogan本身没有动作感

**WorkBuddy建议Slogan的UX优势：**

| 维度 | "见面只是开始" | "下次联系的理由，我们给你找好了" |
|------|---------------|------------------------------|
| **情绪基调** | ✅ 积极主动，暗示"后续有价值" | ✅ 实用贴心，直接解决痛点 |
| **记忆点** | ✅ 5字短句，节奏感强 | ✅ 口语化，像朋友在说话 |
| **分享意愿** | ✅ 高（暗示"我有秘密武器"） | ✅ 高（朋友会问"怎么找的？"） |
| **视觉延展性** | ✅ 强：可以设计"起点→路径→目标"的视觉隐喻 | ✅ 强：可以设计"智能推荐卡片"的动效 |
| **品牌调性** | ✅ 赋能感（产品是加速器） | ✅ 陪伴感（产品是助手） |

### 判断
**强烈采纳** WorkBuddy的Slogan建议，原因：
1. **情绪钩子更强**：从"避免损失"转向"获得增益"，符合人性的正面激励
2. **视觉设计更好落地**："起点"可以延展出引导动画、进度隐喻、路径可视化等设计元素
3. **符合Todo核心功能**：slogan直指"下次联系的理由"，和产品核心能力（行动型Todo）强绑定

### UI设计建议
基于新Slogan，建议的视觉语言：
- **主色调**：从静态的蓝/灰转向动态的橙/绿（行动感）
- **核心隐喻**：路径/箭头/连接线（"开始"暗示方向）
- **动效设计**：Todo卡片出现时从左下角"生长"出来（暗示"找到了"）
- **空状态文案**："还没见过新朋友？去扫张名片吧"（呼应"开始"）

---

## PoC存储共识

### 判断
**采纳** SQLite方案，但需要配合UI设计做**性能预期管理**。

### 理由（UI设计师视角）
1. **部署速度优先**：PoC阶段验证AI能力，不是验证基础设施。SQLite让测试人员更快拿到可用版本
2. **性能劣化可控**：≤5人规模下，SQLite性能足够。关键是要在UI层做好：
   - **Loading状态设计**：搜索/加载时明确告知"正在查询"
   - **预期管理文案**："PoC测试版，搜索速度较慢"
   - **降级方案**：如果查询>3s，显示"正在努力查找..."而不是空白

3. **一致性体验**：和CarryMem用同样的数据库，减少开发者的认知负担

### 配合UI设计要求
- **Phase1切换到PG时，必须做性能对比测试**，确保用户感知到"变快了"
- **在设置页面加入"数据同步状态"指示器**（SQLite本地/PG云端）

---

## 离线策略的UX影响分析

### 判断
**强烈建议升级到P1**（Phase1前必须补），并给出分阶段实现方案。

### 理由
**许总"开车去拜访"场景是真实高频痛点**，离线策略直接决定产品是否可用。

### 分阶段实现建议

#### PoC阶段（3周）
**最小化离线支持**：
- ✅ 名片扫描：本地OCR+离线暂存，有网后上传
- ✅ TTS播报：预缓存最近10条Todo的语音文件（~2MB）
- ❌ 会议记录：必须在线（LLM处理依赖网络）
- ❌ 实时搜索：必须在线

**UI配合**：
- 顶部状态栏显示"离线模式"标识（飞机图标+橙色）
- 离线时禁用的功能置灰+toast提示"需要网络连接"
- 离线暂存的数据显示"待同步"标签（云图标+虚线边框）

#### Phase1阶段（6周）
**完整离线支持**：
- ✅ 所有核心数据离线可读（Entity/Association/Todo）
- ✅ 离线修改本地暂存，有网后后台同步
- ✅ 冲突解决策略：服务端优先+本地diff提示
- ✅ TTS缓存扩展到最近50条

**UI配合**：
- 同步冲突时弹窗展示diff，用户选择保留哪个版本
- 设置页加入"离线数据管理"：查看缓存大小、清理过期数据

### 交互设计关键点
1. **离线状态的视觉反馈**：
   - 在线：顶部状态栏无标识
   - 离线：顶部显示橙色"离线模式"标签
   - 同步中：标签变为蓝色"同步中"+进度条

2. **离线操作的反馈**：
   - 离线添加Todo：卡片右上角显示"☁️待同步"图标
   - 同步成功：图标变为"✓已同步"+短暂绿色高亮
   - 同步失败：图标变为"⚠️同步失败"+点击可重试

3. **TTS离线播报的交互**：
   - 播放前检查缓存，未缓存时显示"需下载语音"
   - 用户可以在设置中手动"预下载最近Todo语音"

---

## Todo状态机的交互设计（重点展开）

### 为什么这是最重要的缺失
Todo状态机直接决定了用户的**核心操作流程**，没有状态定义，以下交互全部无法设计：
1. 用户点击"稍后处理"后界面如何变化？
2. in_progress的Todo如何与pending区分？
3. snoozed的Todo到期时如何通知用户？
4. dismissed的Todo如何不再打扰用户？

### 基于WorkBuddy提供的状态机的交互设计方案

#### 状态流转可视化
```
pending ─────┬─────> in_progress ───┬───> done
             │                       │
             ├─────> dismissed       └───> dismissed
             │
             └─────> snoozed ────[定时]────> pending
```

#### 各状态的UI设计

| 状态 | 视觉样式 | 位置 | 用户操作 |
|------|---------|------|---------|
| **pending** | 白色卡片，左侧蓝色竖条 | 列表顶部 | 点击→详情页（包含"开始处理""忽略""稍后处理"按钮） |
| **in_progress** | 白色卡片，左侧绿色竖条 | pending下方 | 点击→详情页（包含"完成""取消"按钮） |
| **snoozed** | 灰色半透明卡片，左侧虚线竖条，右上角显示"📅 X天后提醒" | 列表底部折叠区域 | 点击→详情页（包含"立即恢复""修改时间"按钮） |
| **done** | 不在主列表显示，进入"已完成"归档页 | 归档页 | 点击→详情页（只读，无操作按钮） |
| **dismissed** | 不在主列表显示，进入"已忽略"归档页 | 归档页 | 点击→详情页（包含"恢复"按钮） |

#### 关键交互流程

**1. 稍后处理（snoozed）流程**
```
用户点击Todo卡片 → 详情页 → 点击"稍后处理"按钮
    ↓
弹出时间选择器（预设选项：1小时后 / 明天 / 3天后 / 自定义）
    ↓
用户选择"明天" → 卡片视觉变化：
    • 左侧竖条变为虚线
    • 整体透明度降至60%
    • 右上角显示"📅 明天 9:00"
    • 卡片动画：向下淡出+移动到列表底部
    ↓
第二天9:00到期时：
    • 发送通知："[Todo标题] 已到提醒时间"
    • 卡片动画：从底部淡入+恢复到顶部
    • 左侧竖条恢复蓝色实线
    • 右上角显示"🔔 刚刚恢复"标签（3秒后消失）
```

**2. 开始处理（in_progress）流程**
```
用户点击"开始处理"按钮
    ↓
卡片视觉变化：
    • 左侧竖条从蓝色变为绿色
    • 卡片位置不变（仍在顶部）
    • 右侧增加进度指示器（如果Todo有子任务）
    ↓
用户可以：
    • 点击"完成"→ 卡片淡出+进入归档
    • 点击"取消"→ 恢复pending状态
    • 放置不管 → 保持in_progress（不自动恢复）
```

**3. 完成（done）流程**
```
用户点击"完成"按钮
    ↓
卡片动画：
    • 左侧竖条变为灰色
    • 整体淡出（0.3s）
    • 显示"✓ 已完成"toast提示
    ↓
卡片移入"已完成"归档页，主列表中消失
```

#### 定时恢复的技术要求
从UX角度，对技术设计的具体要求：
1. **恢复时机**：每小时检查一次到期的snoozed Todo
2. **通知策略**：
   - 高优先级Todo（🔴）：弹窗通知+声音
   - 中优先级Todo（🟢）：顶部banner通知
   - 低优先级Todo（⚪🔵）：红点提示
3. **批量恢复**：如果同时有多个Todo到期，合并通知"3个待办已到提醒时间"

---

## 其他建议

### 1. 关于LLM成本估算
**采纳**，但建议补充UI层的成本控制策略：
- 用户可见的"AI处理进度"指示器（避免用户以为卡死）
- 会议记录上传前的文件大小检查+警告："该文件较大，处理可能需要30秒"
- 设置页加入"AI处理历史"：展示本月已处理的事件数+预估成本（透明化）

### 2. 关于实体归一的HITL确认
**强烈建议补充交互设计细节**：
- **确认弹窗的信息层级**：
  ```
  [主标题] 发现可能是同一人
  [副标题] 置信度：75%
  [对比卡片] 左侧：新名片信息 | 右侧：已有联系人信息
  [按钮] [合并] [新建] [取消]
  ```
- **置信度的视觉呈现**：
  - ≥85%：绿色进度条+"推荐合并"
  - 70-85%：黄色进度条+"可能相同"
  - <70%：不弹窗，直接新建

### 3. 关于话题标签的UI优先级
**修改采纳**（降级到P2），理由：
- 话题标签在Todo卡片中是辅助信息，不影响核心决策
- PoC阶段可以用简单的关键词提取+精确匹配，视觉上显示为"标签云"
- Phase1再补余弦相似度算法，优化"相关话题"推荐

### 4. 关于商机匹配度的视觉呈现
**强烈建议PRD补充"匹配理由的视觉设计规范"**：
- **五维打分如何展示给用户？**
  - 方案A：显示总分（如"匹配度：82%"）+主要原因（如"同行业·话题相关"）
  - 方案B：显示维度雷达图（5个维度的分布）
  - **建议方案A**（简洁，移动端友好）

- **匹配理由的信息层级**：
  ```
  [Todo卡片]
  标题：跟进张三关于SaaS定价的讨论
  推荐理由：与李四匹配 · 同行业 · 话题相关  <-- 主要原因
  [详情展开后]
  匹配度：82%
  • 关键词重叠：90% (SaaS、定价)
  • 行业一致性：100% (互联网/软件)
  • 话题相似度：75%
  • 历史合作：有过1次合作
  ```

---

## 总结：UI设计师的优先级排序

### 必须在PoC前补齐（P0）
1. ✅ Todo状态机（直接影响核心交互）
2. ✅ 实体归一5步算法（决定HITL弹窗设计）
3. ✅ 商机匹配度五维算法（决定推荐理由展示）

### Phase1前补齐（P1）
4. ✅ 离线策略（许总场景刚需）
5. ✅ same_city推断逻辑（影响筛选功能）

### Phase2评估（P2）
6. ⏸️ 话题标签余弦相似度（辅助信息，可降级）
7. ⏸️ 领域分类L2动态扩展（后台逻辑，不影响前端）
8. ⏸️ 时间衰减函数（视觉优化，可延后）

### 非技术建议（立即采纳）
9. ✅ Slogan更新为"见面只是开始"
10. ✅ PoC用SQLite+配套性能预期管理

---
