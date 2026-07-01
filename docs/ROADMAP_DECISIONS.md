# PromiseLink 产品路线图决策文档

> **用途**：记录竞品研究（Agent-Reach + cognee）后的路线图建议，供团队讨论决策。
> **来源**：[竞品研究报告](design/Competitive_Research_AgentReach_Cognee.md)（694 行，2026-07-01）
> **状态**：待讨论 → 决策 → 实施排期

---

## 一、路线图总览

```
v0.7.0（当前）    Staging 灰度发布，不加新功能
       │
       ▼
v0.8.0（2-3周）   基础版互联网感知 MVP（零 Cookie 风险）
       │           B1 手动URL + B2 RSS + B3 channels/ 架构
       ▼
v0.9.0（2周）     图查询能力增强（不换存储）
       │           B4 实体规范化 + B5 recursive CTE + B6 NetworkX + B7 memify
       ▼
v1.0.0 Pro（4-5周） 专业版深度感知（付费卖点）
                   P1 LinkedIn/Twitter + P2 SensingScheduler + P3-P6
```

---

## 二、各阶段详情

### v0.7.0 — Staging 灰度发布（当前）

**目标**：验证现有核心闭环的稳定性和用户价值。

**范围**：
- [x] E2E 链路修复（UUIDStr + datetime timezone + PromptInjection 硬约束）
- [x] CI/CD 加固（timeout-minutes + 移除 continue-on-error）
- [x] 文档对齐（三语 README + Dockerfile LABEL + requirements.lock 清理）
- [ ] 配置 STAGING secrets → Staging 实部署
- [ ] 内部灰度（许总 + 5-10 熟人）

**决策点**：
- [ ] STAGING secrets 何时配置？
- [ ] 灰度用户名单确定？
- [ ] 灰度反馈收集机制？

---

### v0.8.0 — 基础版互联网感知 MVP

**目标**：验证"联系人动态"功能的产品价值，零 Cookie 风险。

**借鉴来源**：Agent-Reach `channels/` 架构理念（不集成完整依赖）

| 编号 | 功能 | 描述 | 工作量 |
|------|------|------|--------|
| B1 | 手动 URL 粘贴 | Jina Reader 抓取 → LLM 提取 → Event 存储 | 3-4 天 |
| B2 | RSS 订阅 | feedparser 拉取 → 新文章自动生成 Event | 3-4 天 |
| B3 | channels/ 架构 | 创建 rss.py / web.py / github.py 渠道文件 | 2-3 天 |

**验收标准**：
- 用户可为联系人粘贴 URL，系统自动生成 Event + 可选 todo
- 用户可订阅联系人 RSS，新文章自动生成 Event
- E2E 测试：粘贴 URL → Event 生成 → AssociationEngine 触发 → RelationshipBrief 更新

**决策点**：
- [ ] Jina Reader 在中国大陆的可用性？（需技术 spike）
- [ ] RSS 订阅频率？（每日/每周？用户可配置？）
- [ ] 动态生成的 Event 是否进入现有 pipeline？（会消耗 LLM 额度）
- [ ] 基础版是否需要 LLM API Key 配置？（当前基础版本地运行，LLM 为可选）

---

### v0.9.0 — 图查询能力增强

**目标**：释放现有关系图谱的潜力，不换存储。

**借鉴来源**：cognee Ontology 实体规范化 + memify 思想

| 编号 | 功能 | 描述 | 工作量 |
|------|------|------|--------|
| B4 | 实体规范化 | 字典 + difflib 80% cutoff，"张总"="Zhang San" | 3-4 天 |
| B5 | recursive CTE 多跳 | SQLite 递归查询 A→B→C 路径（≤3 跳） | 2-3 天 |
| B6 | NetworkX 社区发现 | 内存计算社区 + 中心性分析 | 2-3 天 |
| B7 | RelationshipBrief 动态强化 | 基于互动频率动态调整 stage 和 next_node | 2-3 天 |

**验收标准**：
- "张总"和"Zhang San"能识别为同一人（用户确认机制）
- 查询 A 到 B 的关联路径，返回所有 ≤3 跳的路径
- 能发现人脉网络中的社区（紧密关联的圈子）

**决策点**：
- [ ] 实体规范化误判的纠偏机制？（合并前需用户确认？）
- [ ] 社区发现结果如何展示？（仪表盘新区域？还是人脉详情页？）
- [ ] RelationshipBrief 精炼频率？（每周一次？事件触发？）
- [ ] 是否需要图可视化？（D3.js / ECharts 关系图？还是文字列表？）

---

### v1.0.0 Pro — 专业版深度感知

**目标**：专业版上线互联网感知完整能力，作为付费卖点。

**借鉴来源**：Agent-Reach 完整多后端路由架构

| 编号 | 功能 | 描述 | 工作量 |
|------|------|------|--------|
| P1 | LinkedIn/Twitter 渠道 | 借鉴多后端路由，首选+备选自动降级 | 5-7 天 |
| P2 | SensingScheduler | 云端定时调度，感知联系人动态 | 3-4 天 |
| P3 | 全网搜索 | Exa MCP 搜索联系人名字 | 2-3 天 |
| P4 | 动态仪表盘 | 展示所有联系人最新动态 + 推送通知 | 3-4 天 |
| P5 | 信号融合 | 动态→关联发现信号融合 | 2-3 天 |
| P6 | Cookie 安全 | 加密存储 + 专用小号提示 | 2-3 天 |

**验收标准**：
- 专业版用户订阅 LinkedIn 动态，联系人换工作时自动推送 todo
- 动态仪表盘展示所有联系人的最新动态
- Cookie 加密存储，明确提示封号风险

**决策点**：
- [ ] Cookie 封号风险如何告知用户？（用户协议？首次使用弹窗？）
- [ ] 专业版云端网关是否需要新增感知服务？
- [ ] 付费定价模型？（按渠道数？按感知频率？）
- [ ] LinkedIn/Twitter ToS 合规审查？

---

## 三、关键判断（来自竞品研究）

### 3.1 互联网感知值得做

- **PRD 已埋点**：`Integration_Design_v1.md` L1372 的 LLM prompt 明确写"考虑时机（节日、行业事件、**对方动态**）"，但无数据源支撑
- **核心闭环的自然延伸**：解决"顾不上"痛点，"反馈"环节目前只能手动录入
- **Agent-Reach 验证了工程可行性**：多后端路由 + 自动降级，2026-06 真实案例

### 3.2 不需要迁移图数据库

- **当前 associations 表本质是图边表**（source+target+type+confidence+evidence）
- **规模远不需要图数据库**：个人版 100-2000 联系人、<10K 边
- **cognee 的警示**：正从 Kuzu 迁移到 FalkorDB，图 DB 选型不稳定
- **真正差距是查询模式**：当前只做 1 跳，应增加 recursive CTE + NetworkX

### 3.3 cognee 选择性借鉴

- **借鉴**：Ontology 实体规范化 + memify 思想
- **不借鉴**：三存储引擎架构（过重）、Session+Permanent 双层（不需要）、全异步 API（同步够用）

---

## 四、明确不建议的事项

| 不建议 | 原因 |
|--------|------|
| 基础版迁移到图数据库 | 破坏"本地运行、无 Docker"约束 |
| 基础版集成 Agent-Reach 完整依赖 | 违反轻量约束（依赖 Node.js/mcporter） |
| 基础版支持 Twitter/小红书 Cookie 渠道 | 封号风险 |
| 引入 cognee 三存储架构或 RDF/OWL | 过重 |
| 关系图谱作为主展示 | PRD §1.1 已明确排除 |

---

## 五、风险评估

| 风险 | 等级 | 缓解措施 |
|------|------|---------|
| Cookie 封号 | 🔴 高 | 基础版不支持；专业版强制专用小号 + 风险提示 |
| 功能蔓延 | 🟡 中 | 互联网感知必须服务于核心闭环，不做独立信息流 |
| 实体规范化误判 | 🟡 中 | 80% 模糊匹配可能误合并，需用户确认机制 |
| LLM 成本 | 🟡 中 | 动态摘要用 LLM，需控制调用频率 |
| 中国大陆访问 | 🟡 中 | Twitter/Reddit 需代理；基础版不涉及 |

---

## 六、决策记录

> 每次讨论后在此记录决策结果。

| 日期 | 议题 | 决策 | 参与者 |
|------|------|------|--------|
| 2026-07-01 | 路线图初稿创建 | 待讨论 | 产品经理 + 架构师（AI） |
| | | | |
| | | | |

---

## 七、下一步行动

1. **团队 review 本文档**，对优先级排序达成共识
2. **v0.7.0 Staging 灰度**，收集用户对"对方动态"功能的反馈，校准 MVP 方案
3. **技术 spike**（若决定推进 v0.8.0）：
   - Jina Reader 在中国大陆的可用性
   - feedparser 集成方式
   - channels/ 目录结构设计

---

*创建时间：2026-07-01*
*来源：[竞品研究 Agent-Reach + cognee](design/Competitive_Research_AgentReach_Cognee.md)*
*文档状态：待团队讨论*
