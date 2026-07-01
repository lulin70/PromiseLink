# PromiseLink 产品路线图

> **版本**: v1.0
> **日期**: 2026-07-01
> **来源**: [竞品研究 Agent-Reach & cognee](design/Competitive_Research_AgentReach_Cognee.md) + 内部讨论
> **状态**: 待团队 review 和决策

---

## 当前版本：v0.7.0（Staging 就绪）

- 综合成熟度：87/100（7 维度评估）
- E2E 测试：34 个通过（基础版 19 + 专业版 15）
- CI/CD：test/e2e/frontend/security/build-and-push 全部 success
- 待办：用户配置 STAGING_SSH_KEY/STAGING_HOST secrets → Staging 实部署

---

## 路线图（待决策）

### v0.7.0 发布（当前，不加新功能）

| 项目 | 状态 | 说明 |
|------|------|------|
| Staging 灰度 | ⏳ 待 secrets 配置 | 需用户配置 STAGING_SSH_KEY/STAGING_HOST |
| 内部灰度 | ⏳ 计划中 | 许总 + 5-10 熟人 |
| 公开 repo | ⏳ 计划中 | 灰度反馈后 |

**决策点**：v0.7.0 是否直接发布，还是等 Staging 验证后发布？

---

### v0.8.0：基础版互联网感知 MVP（预估 4 周）

**目标**：解决"顾不上"痛点，为关系经营提供被动反馈信号。

| 编号 | 功能 | 借鉴来源 | 开发量 | 优先级 |
|------|------|---------|--------|--------|
| B1 | 手动 URL 粘贴 → Jina Reader 提取内容 → 创建事件 | Agent-Reach web.py | 1 周 | P0 |
| B2 | RSS 订阅 → feedparser 定时拉取 → 关联人脉动态 | Agent-Reach rss.py | 1.5 周 | P0 |
| B3 | channels/ 架构（渠道注册 + 后端路由 + 自动降级） | Agent-Reach 架构理念 | 1.5 周 | P1 |

**决策点**：
1. 互联网感知是否是 v0.8.0 的最高优先级？（vs 其他功能需求）
2. B1（URL 粘贴）是否足以验证产品价值，还是需要 B2（RSS）才有意义？
3. Jina Reader 在中国大陆的可用性需做技术 spike

**风险**：
- Cookie 封号风险（基础版不支持 Twitter/小红书 Cookie 渠道）
- 功能蔓延（互联网感知必须服务于核心闭环，不做独立信息流）

---

### v0.9.0：图查询能力增强（预估 4 周）

**目标**：不换存储引擎，增强关系图谱的查询能力。

| 编号 | 功能 | 借鉴来源 | 开发量 | 优先级 |
|------|------|---------|--------|--------|
| B4 | 实体规范化（同义词字典 + difflib 80% cutoff + 用户确认） | cognee Ontology | 1.5 周 | P0 |
| B5 | SQLite recursive CTE 多跳查询（2-3 跳关系链） | — | 1 周 | P1 |
| B6 | NetworkX 社区发现 + 中心性分析（内存计算） | cognee 图分析 | 1 周 | P1 |
| B7 | RelationshipBrief 基于互动频率动态强化 | cognee memify | 0.5 周 | P2 |

**决策点**：
1. 实体规范化（B4）的误判风险：80% 模糊匹配可能误合并，用户确认机制怎么设计？
2. 多跳查询（B5）的用户场景是什么？用户真的需要看 2-3 跳关系链吗？
3. 是否值得为 NetworkX 引入新依赖？

**明确不做**：
- ❌ 迁移到图数据库（Neo4j/FalkorDB/Kuzu）— 破坏"本地运行、无 Docker"约束
- ❌ 引入 RDF/OWL 本体语言 — 过重

---

### v1.0.0 Pro：专业版深度感知（预估 9 周）

**目标**：专业版付费卖点，深度互联网感知。

| 编号 | 功能 | 借鉴来源 | 开发量 | 优先级 |
|------|------|---------|--------|--------|
| P1 | LinkedIn/Twitter 渠道（专用小号 + Cookie 安全） | Agent-Reach 完整架构 | 3 周 | P0 |
| P2 | SensingScheduler（定时感知 + 降噪 + 去重） | — | 2.5 周 | P0 |
| P3 | 小宇宙播客渠道 | Agent-Reach podcast.py | 1 周 | P1 |
| P4 | 雪球/财经动态渠道 | Agent-Reach xueqiu.py | 1 周 | P1 |
| P5 | 感知结果与 RelationshipBrief 联动 | — | 1 周 | P1 |
| P6 | Cookie 安全模型（加密存储 + 过期检测 + 风险提示） | Agent-Reach Cookie 模型 | 0.5 周 | P0 |

**决策点**：
1. 专业版小程序前端代码在哪里？（PromiseLink-Pro 仓库无前端代码）
2. Cookie 渠道的法律/合规风险？（LinkedIn ToS 禁止自动化访问）
3. SensingScheduler 的感知频率怎么定？（避免被平台封号）

---

## 优先级矩阵

```
高收益
  │
  │  B1 URL粘贴     ─────  B2 RSS订阅
  │  B4 实体规范化        P1 LinkedIn/Twitter
  │
  │  B5 多跳查询    ─────  P2 SensingScheduler
  │  B7 Brief强化        B3 channels架构
  │
  │  B6 NetworkX    ─────  P3 小宇宙播客
  │                       P4 雪球/财经
  │
  └──────────────────────────────────────
低收益                  高成本
```

---

## 不建议的事项（明确排除）

- ❌ 基础版迁移到任何图数据库（破坏"本地运行、无 Docker"约束）
- ❌ 基础版集成 Agent-Reach 完整依赖（违反轻量约束，Agent-Reach 依赖 Node.js）
- ❌ 基础版支持 Twitter/小红书 Cookie 渠道（封号风险）
- ❌ 引入 cognee 三存储架构或 RDF/OWL（过重）
- ❌ 关系图谱作为主展示（PRD §1.1 已明确排除）
- ❌ v0.7.0 发布前加新功能

---

## 决策记录

| 日期 | 决策项 | 决策 | 决策人 |
|------|--------|------|--------|
| 2026-07-01 | 基础版 UI 添加"推迟"按钮 | 添加，与专业版同步 | 用户 |
| 2026-07-01 | v0.7.0 是否加互联网感知 | 不加，Staging 灰度后再议 | 待团队 review |
| 2026-07-01 | 是否迁移图数据库 | 不迁移，SQLite recursive CTE 够用 | 架构师建议 |

---

*最后更新: 2026-07-01（路线图创建，待团队 review 和决策）*
