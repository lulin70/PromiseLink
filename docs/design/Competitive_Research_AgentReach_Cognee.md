# 竞品研究：Agent-Reach 与 cognee 对 PromiseLink 的借鉴意义

> **研究日期**: 2026-07-01
> **研究对象**: [Agent-Reach](https://github.com/Panniantong/Agent-Reach) (v1.5.0, 3万星, 2026-06-11) + [cognee](https://github.com/topoteretes/cognee) (v1.0.4, 12k+星)
> **研究主题**: 互联网感知（联系人动态）+ 关系图谱存储
> **PromiseLink 当前版本**: v0.7.0 (基础版 Staging 就绪，综合成熟度 87/100)
> **分析视角**: 产品经理 + 架构师双视角
> **分析人**: DevSquad 产品经理/架构师

---

## 一、执行摘要

### 1.1 核心结论（TL;DR）

| 研究方向 | 结论 | 优先级 | 建议版本 |
|---------|------|--------|---------|
| **互联网感知（联系人动态）** | ✅ 值得做，但需分层。基础版做"轻量感知"（RSS + 手动 URL），专业版借鉴 Agent-Reach 多后端路由做"深度感知"（LinkedIn/Twitter） | 🟠 P1 | 基础版 MVP + 专业版完整 |
| **关系图谱存储迁移到图数据库** | ❌ 不建议迁移。当前 SQLite + associations 表 + Python 图遍历已足够。真正的差距是"查询模式"而非"存储引擎" | 🟡 P2 | 不迁移，增强查询 |
| **借鉴 Agent-Reach 多后端路由架构** | ✅ 专业版强烈建议借鉴。基础版只借鉴设计理念，不引入依赖 | 🟠 P1 | 专业版 |
| **借鉴 cognee 知识图谱方案** | ⚠️ 部分借鉴。Ontology 实体规范化 + memify 动态强化思想可借鉴，但三存储引擎架构过重 | 🟡 P2 | 选择性借鉴 |

### 1.2 三个关键判断

1. **互联网感知是 PromiseLink 核心闭环的自然延伸，不是新业务**。当前 LLM prompt 已写"考虑时机（节日、行业事件、对方动态）"但无数据源——这是已识别但未实现的需求，不是造新轮子。Agent-Reach 恰好提供了"如何低成本获取互联网动态"的工程答案。

2. **关系图谱不需要图数据库**。PromiseLink 的 `associations` 表已是标准的图边表（source + target + type + confidence + evidence），已有索引，已有 Python BFS 遍历。Codebase-Memory 项目证明 SQLite 单文件可实现亚毫秒图谱查询。迁移 Neo4j 会破坏"基础版本地运行、无 Docker"的硬约束，收益不抵成本。真正的差距是多跳查询模式（recursive CTE）和图算法（NetworkX），这些都不需要换存储。

3. **Agent-Reach 是"能力层"不是"工具"，借鉴方式要分层**。基础版（MPL、本地、无 Docker）不应捆绑 Agent-Reach（它依赖 Node.js、mcporter、多个 CLI 工具），但应借鉴其"首选+备选"路由模式构建自己的轻量 channels。专业版（Docker、云端网关）可以直接集成 Agent-Reach 作为互联网感知后端。

---

## 二、Agent-Reach 架构分析

### 2.1 项目定位

**Agent-Reach = AI Agent 的互联网能力层（Capability Layer）**

关键定位声明（来自 CLAUDE.md）：
> "Positioning: installer + doctor + config tool. NOT a wrapper — after install, agents call upstream tools directly."
> "Agent Reach is a 'glue layer' — only route and call, don't reimagine."

它**不是**又一个爬虫库或 API 封装，而是**选型 + 安装 + 体检 + 路由**的元层（meta-layer）。实际读取由 Agent 直接调用上游开源工具（yt-dlp、twitter-cli、gh CLI、bili-cli、OpenCLI、feedparser 等）完成。

### 2.2 三层架构

```
┌─────────────────────────────────────────────────────────┐
│  Layer 3: Agent 直接调用上游工具                          │
│  (yt-dlp / twitter-cli / gh CLI / bili-cli / feedparser) │
└─────────────────────────────────────────────────────────┘
                         ▲
                         │ 调用
┌─────────────────────────────────────────────────────────┐
│  Layer 2: 后端路由（首选 + 备选有序列表）                  │
│  每个平台 = 有序后端列表，首选挂了自动切备选               │
│  agent-reach doctor 真实探测每个后端可用性                │
└─────────────────────────────────────────────────────────┘
                         ▲
                         │ 注册
┌─────────────────────────────────────────────────────────┐
│  Layer 1: 渠道注册（channels/）                           │
│  每个平台一个独立文件，继承 BaseChannel                    │
│  契约: can_handle(url) / read(url) / search(query) / check()│
│  SKILL.md 自注册到 Agent skills 目录                      │
└─────────────────────────────────────────────────────────┘
```

### 2.3 渠道文件结构

```
channels/
├── web.py          → Jina Reader
├── twitter.py      → twitter-cli ▸ OpenCLI ▸ bird
├── youtube.py      → yt-dlp
├── github.py       → gh CLI
├── bilibili.py     → bili-cli ▸ OpenCLI ▸ 搜索 API（yt-dlp 已退役）
├── reddit.py       → OpenCLI ▸ rdt-cli（必须登录态）
├── xiaohongshu.py  → OpenCLI ▸ xiaohongshu-mcp ▸ xhs-cli
├── linkedin.py     → linkedin-mcp ▸ Jina Reader
├── rss.py          → feedparser
├── exa_search.py   → Exa via mcporter
└── __init__.py     → 渠道注册（doctor 检测用）
```

### 2.4 核心设计理念

#### 2.4.1 多后端路由 + 自动降级

每个平台是一个**有序后端列表**，而非单一实现。换接入方式 = 调整列表顺序，不是重写代码。

**真实案例（2026-06）**: yt-dlp 被 B站风控 412 封死 → Agent-Reach 切换到 bili-cli，用户零操作。这验证了多后端路由的必要性——互联网平台反爬策略会变，单一后端必然失效。

#### 2.4.2 真实探测（real-probing）

`agent-reach doctor` 不只是检查命令是否存在，而是**真实调用**每个后端验证可用性，并给出修复处方。这是区分"装了"和"能用"的关键。

#### 2.4.3 SKILL.md 自注册

安装时在 Agent 的 skills 目录写入 SKILL.md，Agent 遇到"搜推特"、"看视频"等需求时自动知道调用哪个上游工具。这是**声明式能力发现**而非命令式 API 调用。

#### 2.4.4 Cookie 安全模型

- Cookie 只存本地 `~/.agent-reach/config.yaml`，文件权限 600
- 优先使用 Chrome 插件 [Cookie-Editor](https://chromewebstore.google.com/detail/cookie-editor/hlkenndednhfkekhgcdicdfddnkalmdm) 导出
- **明确警告封号风险**：建议使用专用小号，不用主账号

### 2.5 平台覆盖（13+ 平台）

| 平台 | 装好即用 | 配置后解锁 | 商务关系经营价值 |
|------|---------|-----------|----------------|
| 🌐 网页 | ✅ Jina Reader | — | 🟢 高（读任意文章/博客） |
| 📺 YouTube | ✅ yt-dlp 字幕 | — | 🟡 中（技术内容） |
| 📡 RSS | ✅ feedparser | — | 🟢 高（订阅联系人博客/公司动态） |
| 🔍 全网搜索 | — | Exa 语义搜索 | 🟢 高（搜联系人名字） |
| 📦 GitHub | ✅ 公开仓库 | 私有仓库 | 🟡 中（技术人脉） |
| 🐦 Twitter/X | ✅ 读单条 | 搜索/时间线 | 🟢 高（联系人动态） |
| 📺 B站 | ✅ bili-cli | 字幕 | 🟡 低 |
| 📖 Reddit | — | 搜索+读帖 | 🟡 低 |
| 📕 小红书 | — | 搜索/阅读 | 🟡 低（消费品牌） |
| 💼 LinkedIn | ✅ Jina Reader | Profile/公司/职位 | 🟢 极高（商务人脉核心） |
| 💻 V2EX | ✅ 热门/节点 | — | 🟡 低 |
| 📈 雪球 | ✅ 行情/搜索 | — | 🟡 中（投资人脉） |
| 🎙️ 小宇宙播客 | — | Whisper 转录 | 🟡 中（联系人上播客） |

**对 PromiseLink 价值排序**: LinkedIn > RSS > Web > Twitter > 全网搜索 > GitHub > 雪球 > 播客

### 2.6 局限性分析

| 局限 | 说明 | 对 PromiseLink 的影响 |
|------|------|---------------------|
| **面向 Agent，非应用** | 设计为 Agent 通过 shell 调用，PromiseLink 是 FastAPI 应用，需适配 | 中（需包装为 Python API 或 subprocess） |
| **依赖重** | Node.js + mcporter + 多个 CLI 工具 | 高（破坏基础版"无 Docker"约束） |
| **Cookie 封号风险** | Twitter/小红书明确警告可能封号 | 高（商业产品不能让用户封号） |
| **读为主，无定时订阅** | 无 cron/scheduler，不能定时拉取联系人动态 | 高（关系经营需要主动推送） |
| **无数据结构化** | 返回文本，需 PromiseLink 自行提取实体 | 中（PromiseLink 已有 LLM 增强层） |
| **中国大陆访问** | Reddit/Twitter 需代理 | 中（基础版用户多在大陆） |

---

## 三、cognee 已有分析回顾 + 新增洞察

### 3.1 已有分析回顾（来自 CarryMem 竞品分析）

> 完整分析见: `/Users/lin/trae_projects/carrymem/docs/COMPETITIVE_ANALYSIS_MEMORY_GRAPH.md`

cognee 的核心架构对 PromiseLink 的借鉴价值（提取与 PromiseLink 相关部分）：

| cognee 特性 | 对 PromiseLink 的适用性 | 借鉴价值 |
|------------|----------------------|---------|
| **三存储引擎**（Graph + Vector + Relational） | ⚠️ 过重。PromiseLink 基础版只需 SQLite | 低（架构层面） |
| **ECL 管道**（Extract-Cognify-Load） | ✅ PromiseLink 已有类似管道（事件录入→实体提取→关联发现） | 中（概念对齐） |
| **memify 动态精炼** | ✅ 适用于 RelationshipBrief（关系推进卡应随互动动态更新） | 高（思想借鉴） |
| **Ontology 实体规范化** | ✅ PromiseLink 实体（人名/公司名）需规范化（"张总" vs "张三" vs "Zhang San"） | 高（直接借鉴） |
| **Session + Permanent 双层** | ⚠️ PromiseLink 是单用户私密助手，无双层需求 | 低 |
| **14 检索模式** | ⚠️ PromiseLink 当前单一查询模式已够用 | 低（中期考虑） |
| **全异步 API** | ⚠️ PromiseLink 同步 SQLite 在个人版规模够用 | 低（长期债） |

### 3.2 新增洞察（2026-07-01 最新状态）

#### 3.2.1 cognee 从 Kuzu 迁移到 FalkorDB

GitHub 分支 `feat/replace-kuzu-with-falkorDB` 显示 cognee 正在将图存储引擎从 Kuzu 替换为 FalkorDB。

**含义**: Kuzu 作为嵌入式图数据库曾被 cognee 选用，但可能在生产中遇到瓶颈（性能/稳定性/生态）。FalkorDB 是基于 Redis 的图数据库，更适合云端部署。

**对 PromiseLink 的启示**: 连 cognee 这样的图数据库重度用户都在迁移引擎，说明图数据库选型不稳定。PromiseLink **不应**在基础版引入任何图数据库依赖，SQLite 的稳定性远高于图数据库。

#### 3.2.2 cognee API 简化为 remember/recall/forget/improve

cognee 从早期的 `add()/cognify()/search()` 三步管道，简化为 `remember()/recall()/forget()/improve()` 四个语义化 API。

**对 PromiseLink 的启示**: PromiseLink 的 API 设计已比 cognee 更贴近用户语义（`record_event` / `get_relationship_brief` / `discover_associations`），无需调整。

#### 3.2.3 cognee 的 Claude Code 插件集成

cognee 通过 Claude Code 插件实现 session memory 自动捕获（PostToolUse hook）和 session end 时同步到永久图谱。

**对 PromiseLink 的启示**: PromiseLink 的事件录入已是结构化的，不需要这种 hook 机制。但**思想可借鉴**：互联网感知的"动态捕获"可以类似 cognee 的 session memory——临时存储，确认有价值后再提升为永久 Association。

---

## 四、互联网感知（联系人动态）借鉴分析

### 4.1 产品视角

#### 4.1.1 PromiseLink 是否需要"联系人动态"功能？

**需要，且是核心闭环的自然延伸。**

证据：
1. **PRD 已埋点**: `Integration_Design_v1.md` L1372 的 LLM prompt 明确写道"考虑时机（节日、行业事件、**对方动态**）"，但无数据源支撑——这是已识别但未实现的需求。
2. **核心痛点对齐**: PromiseLink 解决三大困境"记不住/想不清/**顾不上**"。"顾不上"的本质是错过最佳维护时机，而"对方动态"正是时机的信号源。
3. **核心闭环闭环需要**: 互动→关注→承诺→帮助→**反馈**。"反馈"环节目前只能靠用户手动录入，互联网动态可提供被动反馈信号（对方发了文章、换了工作、上了新闻）。

#### 4.1.2 用户场景

| 场景 | 信号源 | PromiseLink 的价值 |
|------|--------|------------------|
| 联系人换了工作 | LinkedIn 动态 | 触发"恭喜"todo，更新 RelationshipBrief 的 stage |
| 联系人发了技术文章 | RSS / Twitter | 提供"帮忙转发/评论"的 help todo，强化关系 |
| 联系人公司上新闻 | 全网搜索 | 主动推送"是否需要祝贺/安慰" |
| 联系人上播客 | 小宇宙 | 生成"听完后讨论点"todo |
| 联系人 GitHub 开源新项目 | GitHub | 提供"star/贡献"的 help todo |

#### 4.1.3 与现有"关联发现"功能的关系

**互补增强，非替代。**

当前 AssociationEngine 的信号源：
- 共现分析（同事件出现 → strength+0.1）
- 类型推断（同公司 → colleague，同行业 → competitor）
- topic_overlap（concerns/capabilities 语义匹配）

互联网感知可新增信号源：
- **共同曝光**（两人在同一篇文章/新闻中出现 → 新增 assoc_type `co_exposure`）
- **互动痕迹**（A 转发了 B 的文章 → 新增 assoc_type `online_interaction`，strength+0.2）
- **职业关联**（两人在同一时段更换公司 → 强化 `colleague` 关联置信度）

#### 4.1.4 基础版 vs 专业版的功能划分

| 功能 | 基础版（MPL、本地、免费） | 专业版（Docker、云端、付费） |
|------|------------------------|--------------------------|
| **手动 URL 粘贴** | ✅ 用户粘贴联系人文章链接，LLM 提取摘要+实体 | ✅ |
| **RSS 订阅** | ✅ 订阅联系人博客/公司 RSS，定时拉取 | ✅ |
| **网页阅读** | ✅ Jina Reader 读任意网页（零配置） | ✅ |
| **LinkedIn 动态** | ❌（Cookie 风险+代理问题） | ✅（借鉴 Agent-Reach linkedin-mcp） |
| **Twitter/X 动态** | ❌（Cookie 封号风险） | ✅（专业版用专用小号） |
| **全网搜索联系人** | ❌（依赖 Exa MCP） | ✅ |
| **GitHub 动态** | ✅（gh CLI 公开仓库无 Cookie 风险） | ✅ |
| **定时扫描+推送** | ❌（本地运行无 cron） | ✅（云端 scheduler） |
| **动态→todo 自动生成** | ✅（LLM 增强层处理） | ✅ |

**划分原则**:
- 基础版只做**零配置、零 Cookie、零代理**的渠道（RSS + Web + GitHub 公开数据）
- 专业版做**需要登录态/代理**的渠道（LinkedIn + Twitter），并承担封号风险提示
- 基础版的"手动 URL 粘贴"是兜底方案，确保所有用户都能用

#### 4.1.5 MVP 方案设计

**基础版 MVP（P1，2 周开发量）**:

```
用户操作: 在联系人详情页粘贴 URL → "添加动态"
系统动作:
  1. Jina Reader 抓取网页内容 (curl https://r.jina.ai/URL)
  2. LLM 增强层提取: 摘要 + 提及的人物/公司 + 与联系人的关联度
  3. 存储为 Event (event_type=online_activity, source=url)
  4. 触发 AssociationEngine 重新计算关联
  5. 若关联度 > 0.7，生成 help todo (如"转发/评论/祝贺")
```

**基础版 RSS 订阅（P1，1 周开发量）**:
- 用户为联系人添加 RSS feed URL
- 应用启动时拉取最新文章（不做定时，避免本地 cron 依赖）
- 新文章 → 生成 Event → 触发 LLM 摘要 → 可选 help todo

**专业版完整方案（P2，4 周开发量）**:
- 借鉴 Agent-Reach 的 `channels/` 架构
- 实现 LinkedIn + Twitter + GitHub 三个高价值渠道
- 云端 scheduler 每日扫描
- 动态仪表盘 + 推送通知

### 4.2 架构视角

#### 4.2.1 是否借鉴 Agent-Reach 的多后端路由架构？

**专业版：是。基础版：只借鉴理念，不引入依赖。**

**基础版不直接集成 Agent-Reach 的原因**:
1. Agent-Reach 依赖 Node.js + mcporter + 多个 CLI 工具，违反基础版"本地运行、无 Docker"约束
2. Agent-Reach 面向 Agent shell 调用，PromiseLink 是 FastAPI 应用，集成方式不匹配
3. 基础版只需 3 个零配置渠道（RSS + Web + GitHub），不值得引入整个 Agent-Reach

**基础版借鉴方式**:
- 借鉴 `channels/` 目录结构，创建 `promise link/channels/` 模块
- 每个渠道一个文件，实现统一契约: `fetch(contact_identifier) → List[DynamicItem]`
- 内置 3 个渠道: `rss.py` (feedparser) / `web.py` (Jina Reader via httpx) / `github.py` (gh CLI via subprocess)

**专业版集成方式**:
- 专业版 Docker 环境可直接 `pip install agent-reach` 作为依赖
- 包装 Agent-Reach 的 channel API 为 PromiseLink 的 `InternetSensingService`
- 或参考其选型，自行实现 LinkedIn/Twitter 渠道（避免传递 Agent-Reach 的重依赖）

#### 4.2.2 集成架构设计（专业版）

```
┌─────────────────────────────────────────────────────────┐
│  PromiseLink 专业版 - InternetSensingService             │
├─────────────────────────────────────────────────────────┤
│  SensingScheduler (云端 cron, 每日扫描)                  │
│  ↓                                                       │
│  ChannelRouter (借鉴 Agent-Reach 多后端路由)             │
│  ├─ linkedin_channel.py → linkedin-mcp ▸ Jina Reader    │
│  ├─ twitter_channel.py  → twitter-cli ▸ OpenCLI         │
│  ├─ rss_channel.py      → feedparser                    │
│  ├─ web_channel.py      → Jina Reader                   │
│  ├─ github_channel.py   → gh CLI                        │
│  └─ search_channel.py   → Exa (全网搜索联系人名字)       │
│  ↓                                                       │
│  DynamicProcessor                                       │
│  ├─ LLM 摘要提取 (复用现有 LLM 增强层)                   │
│  ├─ 实体匹配 (动态中的人名 → PromiseLink Entity)         │
│  ├─ 关联度评分 (动态内容 vs 联系人 concerns/capabilities)│
│  └─ Todo 生成 (help 类型, 借鉴现有 todo 生成逻辑)        │
│  ↓                                                       │
│  Storage (存为 Event, event_type=online_activity)       │
└─────────────────────────────────────────────────────────┘
```

#### 4.2.3 数据模型扩展

新增 `contact_dynamics_sources` 表（订阅源管理）:

```sql
CREATE TABLE contact_dynamics_sources (
    id UUID PRIMARY KEY,
    user_id UUID NOT NULL REFERENCES users(id),
    entity_id UUID NOT NULL REFERENCES entities(id),  -- 关联到哪个联系人
    source_type VARCHAR(20) NOT NULL,  -- rss | linkedin | twitter | github | web
    source_url VARCHAR(500) NOT NULL,  -- RSS feed URL / LinkedIn profile URL / Twitter handle
    last_fetched_at TIMESTAMPTZ,
    fetch_status VARCHAR(20) DEFAULT 'active',  -- active | paused | error
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_dynamics_source_entity ON contact_dynamics_sources(entity_id);
CREATE INDEX idx_dynamics_source_type ON contact_dynamics_sources(source_type);
```

动态内容复用现有 `events` 表（`event_type='online_activity'`），无需新建表。这样 AssociationEngine 可无缝处理。

---

## 五、关系图谱存储借鉴分析

### 5.1 PromiseLink 当前图谱存储现状

#### 5.1.1 数据模型

PromiseLink 的 `associations` 表**本质就是图边表**:

| 字段 | 图论含义 |
|------|---------|
| source_entity_id | 边的起点 |
| target_entity_id | 边的终点 |
| assoc_type | 边的类型（8 种: alumni/ex_colleague/same_city/competitor/tech_overlap/deal_link/risk_link/supply_chain） |
| confidence | 边的权重（0.0-1.0） |
| evidence | 边的证据（JSONB） |
| user_id | 子图分区键（每个用户一个独立子图） |

`entities` 表是图的**节点表**。`events` 表是节点上的**事件标注**。`relationship_briefs` 是节点的**聚合视图**。

#### 5.1.2 已有的图遍历能力

PromiseLink 已在 Python 层实现图遍历（见 `Algorithm_Design_v1.md` §4.3）:

```python
# 承诺依赖图（build_promise_dependency_graph）
# 用 Dict[str, List[str]] 邻接表 + BFS 遍历查找阻塞链
graph: Dict[str, List[str]] = {}
# BFS 遍历查找阻塞链
def _find_blocking_chains(self, todo_id, graph) -> Tuple[int, List[int]]:
    ...
```

#### 5.1.3 已有的索引

```sql
CREATE INDEX idx_assoc_source ON associations(source_entity_id);
CREATE INDEX idx_assoc_target ON associations(target_entity_id);
CREATE INDEX idx_assoc_type ON associations(assoc_type);
CREATE INDEX idx_assoc_confidence ON associations(confidence) WHERE confidence >= 0.7;
CREATE UNIQUE INDEX idx_assoc_unique ON associations(user_id, source_entity_id, target_entity_id, assoc_type);
```

索引设计已考虑图查询的常见模式（按起点查、按终点查、按类型查、按权重过滤）。

### 5.2 是否需要迁移到图数据库？

**结论：不需要。当前 SQLite + SQLAlchemy 完全够用。**

#### 5.2.1 规模分析

| 维度 | 个人版规模 | SQLite 性能边界 | 是否够用 |
|------|-----------|---------------|---------|
| 联系人数量 | 100-2000 | 百万级 | ✅ 远超需求 |
| 事件数量 | 1000-50000 | 百万级 | ✅ 远超需求 |
| 关联边数量 | 500-10000 | 百万级 | ✅ 远超需求 |
| 图遍历深度 | 1-3 跳 | recursive CTE 支持 | ✅ |
| 并发查询 | 单用户 | SQLite WAL 模式 | ✅ |

Codebase-Memory 项目证明：SQLite 单文件可索引 Linux 内核（28M LOC, 75K files），亚毫秒查询。PromiseLink 的数据量比其小 3 个数量级。

#### 5.2.2 迁移图数据库的成本

| 成本项 | Neo4j | Kuzu | FalkorDB |
|--------|-------|------|---------|
| **基础版约束** | ❌ 需 Java JVM + 独立服务 | ⚠️ 嵌入式但增加依赖 | ❌ 需 Redis |
| **部署复杂度** | 高（独立服务+备份+ license） | 中（嵌入式库） | 高（Redis 依赖） |
| **运维成本** | 高 | 低 | 中 |
| **学习曲线** | Cypher 查询语言 | Cypher（OpenCypher） | Cypher |
| **与现有代码兼容** | 需重写 AssociationEngine | 需适配 | 需适配 |
| **MPL 兼容性** | 社区版 GPL，商业版付费 | MIT | SSPL（争议） |

**关键约束冲突**: 基础版要求"本地运行、无 Docker、MPL 开源"。Neo4j 社区版是 GPL（与 MPL 兼容但需开源），商业版付费；FalkorDB 是 SSPL（MongoDB 协议，开源争议）。任何图数据库都会破坏基础版的轻量定位。

#### 5.2.3 cognee 迁移引擎的警示

cognee 从 Kuzu 迁移到 FalkorDB 的事实说明：**图数据库选型不稳定，引擎迁移成本高**。PromiseLink 不应在这个阶段绑定任何图数据库。

### 5.3 真正的差距：查询模式，不是存储引擎

当前 PromiseLink 的图查询能力**只做了 1 跳**（直接关联）。真正的差距是多跳查询和图算法。

#### 5.3.1 应增加的查询模式（用 SQLite recursive CTE 实现）

**多跳关联查询**（SQLite 3.8+ 支持 WITH RECURSIVE）:

```sql
-- 查找 A 到 B 的所有路径（最多 3 跳）
WITH RECURSIVE path_cte AS (
    SELECT source_entity_id AS start, target_entity_id AS end, 
           assoc_type, confidence, 1 AS depth,
           CAST(source_entity_id || '->' || target_entity_id AS TEXT) AS path
    FROM associations WHERE source_entity_id = 'entity_A'
    UNION ALL
    SELECT p.start, a.target_entity_id, a.assoc_type, 
           p.confidence * a.confidence, p.depth + 1,
           p.path || '->' || a.target_entity_id
    FROM path_cte p
    JOIN associations a ON p.end = a.source_entity_id
    WHERE p.depth < 3 AND p.end != 'entity_B'
)
SELECT * FROM path_cte WHERE end = 'entity_B' ORDER BY confidence DESC;
```

**社区发现**（找紧密关联的圈子）: 用 Python NetworkX 内存计算，不持久化:

```python
import networkx as nx

def find_communities(user_id: str) -> List[List[str]]:
    G = nx.DiGraph()
    # 从 SQLite 加载边
    edges = db.query("SELECT source_entity_id, target_entity_id, confidence FROM associations WHERE user_id = ?", user_id)
    G.add_weighted_edges_from([(e.source, e.target, e.confidence) for e in edges])
    # Louvain 社区发现（与 Codebase-Memory 同算法）
    communities = nx.community.louvain_communities(G.to_undirected())
    return [list(c) for c in communities]
```

**中心性分析**（找关键人脉节点）:

```python
def find_key_connectors(user_id: str) -> List[Tuple[str, float]]:
    G = build_graph(user_id)
    # 介数中心性：谁是人脉网络的"桥梁"
    betweenness = nx.betweenness_centrality(G)
    return sorted(betweenness.items(), key=lambda x: -x[1])[:10]
```

#### 5.3.2 借鉴 cognee Ontology 实体规范化

PromiseLink 的实体（人名/公司名）存在碎片化问题：
- "张总" / "张三" / "Zhang San" / "张三（ABC公司）" 可能是同一个人
- "字节跳动" / "ByteDance" / "字节" 是同一家公司

**借鉴 cognee 的 Ontology 思想，但不引入 RDF/OWL**（过重）:

```python
# 简单实现：同义词字典 + difflib 模糊匹配
class EntityNormalizer:
    SYNONYMS = {
        "字节跳动": ["ByteDance", "字节", "bytedance"],
        "腾讯": ["Tencent", "tencent"],
    }
    
    def normalize(self, entity_text: str) -> str:
        for canonical, aliases in self.SYNONYMS.items():
            if entity_text.lower() in [a.lower() for a in aliases]:
                return canonical
            # 模糊匹配 (80% cutoff, 同 cognee)
            for alias in aliases:
                if difflib.SequenceMatcher(None, entity_text.lower(), alias.lower()).ratio() > 0.8:
                    return canonical
        return entity_text
```

#### 5.3.3 借鉴 cognee memify 思想强化 RelationshipBrief

当前 `RelationshipBrief`（关系推进卡）是静态存储。借鉴 cognee 的 memify，可基于使用信号动态强化:

```python
# 当前: RelationshipBrief 创建后基本不变
# 借鉴后: 基于互动频率动态调整 stage 和 next_node
class RelationshipBriefRefiner:
    def refine(self, brief: RelationshipBrief, recent_events: List[Event]) -> RelationshipBrief:
        # 频繁互动 → stage 前进
        if len(recent_events) > 5 and brief.current_stage == "acquaintance":
            brief.current_stage = "active_contact"
            brief.stage_reason = "近30天互动5次以上，关系活跃"
        # 长期无互动 → stage 后退
        if len(recent_events) == 0 and brief.last_interaction_days > 180:
            brief.current_stage = "dormant"
            brief.next_node = "节假日问候重新激活"
        return brief
```

---

## 六、对 PromiseLink 的建议（分基础版/专业版）

### 6.1 基础版建议（MPL、本地、免费）

| 编号 | 建议 | 借鉴来源 | 优先级 | 开发量 | 风险 |
|------|------|---------|--------|--------|------|
| **B1** | 实现手动 URL 粘贴 → 动态提取 → Event 存储 | Agent-Reach web.py (Jina Reader) | 🟠 P1 | 2 周 | 低 |
| **B2** | 实现 RSS 订阅渠道（feedparser） | Agent-Reach rss.py | 🟠 P1 | 1 周 | 低 |
| **B3** | 创建 `channels/` 目录结构，统一渠道契约 | Agent-Reach 架构 | 🟡 P2 | 1 周 | 低 |
| **B4** | 实现实体规范化层（字典 + difflib） | cognee Ontology | 🟡 P2 | 1 周 | 低 |
| **B5** | 用 SQLite recursive CTE 实现多跳关联查询 | cognee 图遍历 | 🟡 P2 | 1 周 | 低 |
| **B6** | 引入 NetworkX 做社区发现/中心性（内存计算） | Codebase-Memory Louvain | 🟡 P2 | 1 周 | 低 |
| **B7** | RelationshipBrief 动态强化（基于互动频率） | cognee memify | 🟢 P3 | 1 周 | 低 |
| **❌** | 迁移到图数据库 | cognee 三存储 | — | — | 不建议 |

### 6.2 专业版建议（Docker、云端、付费）

| 编号 | 建议 | 借鉴来源 | 优先级 | 开发量 | 风险 |
|------|------|---------|--------|--------|------|
| **P1** | 集成 Agent-Reach 或借鉴其多后端路由实现 LinkedIn/Twitter 渠道 | Agent-Reach 完整架构 | 🟠 P1 | 3 周 | 中（Cookie 风险） |
| **P2** | 实现 InternetSensingService + SensingScheduler（云端 cron） | Agent-Reach + 自研 | 🟠 P1 | 2 周 | 中 |
| **P3** | 全网搜索联系人名字（Exa MCP） | Agent-Reach exa_search.py | 🟡 P2 | 1 周 | 中 |
| **P4** | 动态仪表盘 + 推送通知 | 自研 | 🟡 P2 | 2 周 | 低 |
| **P5** | 动态→关联发现信号融合（co_exposure/online_interaction） | 自研 | 🟡 P2 | 1 周 | 低 |
| **P6** | Cookie 安全管理（专用小号提示、加密存储） | Agent-Reach 安全模型 | 🟠 P1 | 1 周 | 中 |

### 6.3 不建议的事项

| 事项 | 原因 |
|------|------|
| ❌ 基础版迁移到 Neo4j/Kuzu/FalkorDB | 破坏"本地运行、无 Docker"约束，数据规模不需要 |
| ❌ 基础版集成 Agent-Reach 完整依赖 | Node.js/mcporter 违反轻量约束 |
| ❌ 基础版支持 Twitter/小红书 Cookie 渠道 | 封号风险，商业产品不可接受 |
| ❌ 引入 cognee 三存储架构 | 过重，PromiseLink 不需要向量+图+关系三引擎 |
| ❌ 引入 RDF/OWL Ontology | 过重，字典+模糊匹配足够 |
| ❌ 关系图谱作为主展示 | PRD §1.1 已明确排除："关系图谱作为主展示" |

---

## 七、优先级和实施路线图建议

### 7.1 优先级矩阵

```
高收益
  │
  │  B1(手动URL)    P1(LinkedIn/Twitter)
  │  B2(RSS)        P2(SensingScheduler)
  │  B4(实体规范化)  P6(Cookie安全)
  │
  │  B5(多跳CTE)    P3(全网搜索)
  │  B6(NetworkX)   P4(动态仪表盘)
  │  B3(channels)   P5(信号融合)
  │  B7(memify)
  │
  └──────────────────────────────────→ 高成本
```

### 7.2 实施路线图

#### Phase 1: 基础版互联网感知 MVP（v0.8.0，2-3 周）

**目标**: 验证"联系人动态"功能的产品价值，零 Cookie 风险。

- [ ] B1: 手动 URL 粘贴 → Jina Reader 抓取 → LLM 提取 → Event 存储
- [ ] B2: RSS 订阅渠道（feedparser，应用启动时拉取）
- [ ] B3: 创建 `channels/` 目录结构（rss.py / web.py / github.py）

**验收标准**:
- 用户可为联系人粘贴 URL，系统自动生成 Event + 可选 todo
- 用户可订阅联系人 RSS，新文章自动生成 Event
- E2E 测试：粘贴 URL → Event 生成 → AssociationEngine 触发 → RelationshipBrief 更新

#### Phase 2: 图查询能力增强（v0.9.0，2 周）

**目标**: 释放现有关系图谱的潜力，不换存储。

- [ ] B4: 实体规范化层（字典 + difflib，80% cutoff）
- [ ] B5: SQLite recursive CTE 多跳查询（A→B→C 路径）
- [ ] B6: NetworkX 社区发现 + 中心性分析（内存计算）
- [ ] B7: RelationshipBrief 动态强化

**验收标准**:
- "张总"和"Zhang San"能识别为同一人
- 查询 A 到 B 的关联路径，返回所有 ≤3 跳的路径
- 能发现人脉网络中的社区（紧密关联的圈子）

#### Phase 3: 专业版深度感知（v1.0.0 Pro，4-5 周）

**目标**: 专业版上线互联网感知完整能力，作为付费卖点。

- [ ] P1: LinkedIn + Twitter 渠道（借鉴 Agent-Reach 多后端路由）
- [ ] P2: InternetSensingService + 云端 SensingScheduler
- [ ] P3: 全网搜索联系人名字（Exa MCP）
- [ ] P4: 动态仪表盘 + 推送通知
- [ ] P5: 动态→关联发现信号融合
- [ ] P6: Cookie 安全管理 + 专用小号提示

**验收标准**:
- 专业版用户订阅 LinkedIn 动态，联系人换工作时自动推送 todo
- 动态仪表盘展示所有联系人的最新动态
- Cookie 加密存储，明确提示封号风险

### 7.3 与现有 v0.7.0 Staging 发布的关系

当前 v0.7.0 已 Staging 就绪，**不建议**在发布前加入互联网感知功能。建议：

1. **v0.7.0 发布**（当前）：基础版 Staging → 内部灰度（许总+5-10 熟人）→ 公开 repo
2. **v0.8.0**：基础版互联网感知 MVP（B1+B2+B3）
3. **v0.9.0**：图查询增强（B4+B5+B6+B7）
4. **v1.0.0 Pro**：专业版深度感知（P1-P6）

---

## 八、风险评估

### 8.1 互联网感知风险

| 风险 | 等级 | 缓解措施 |
|------|------|---------|
| **Cookie 封号** | 🔴 高（Twitter/小红书） | 基础版不支持；专业版强制专用小号 + 明确风险提示 |
| **反爬封锁** | 🟡 中 | 借鉴 Agent-Reach 多后端路由，首选挂了切备选 |
| **数据合规** | 🟡 中 | 只抓取公开数据；RSS 是用户主动订阅；LinkedIn/Twitter 遵守 ToS |
| **LLM 成本** | 🟡 中 | 动态摘要用 LLM，需控制调用频率；基础版只在用户主动粘贴时调用 |
| **数据质量** | 🟡 中 | LLM 提取的实体可能错误；需用户确认机制 |
| **中国大陆访问** | 🟡 中（Twitter/Reddit） | 基础版不涉及；专业版用户需自备代理或用云端网关 |

### 8.2 图查询增强风险

| 风险 | 等级 | 缓解措施 |
|------|------|---------|
| **recursive CTE 性能** | 🟢 低 | 限制最大深度（3 跳）+ 索引已就位 |
| **NetworkX 内存** | 🟢 低 | 个人版规模（<10K 边），内存占用 <50MB |
| **实体规范化误判** | 🟡 中 | 模糊匹配 80% cutoff 可能误合并；需用户确认机制 |
| **RelationshipBrief 频繁变更** | 🟡 中 | 限制精炼频率（每周一次），避免 stage 频繁跳动 |

### 8.3 战略风险

| 风险 | 等级 | 缓解措施 |
|------|------|---------|
| **功能蔓延** | 🟡 中 | 互联网感知是 PRD 已埋点需求，非新业务；但需严格控制范围 |
| **偏离核心闭环** | 🟡 中 | 互联网感知必须服务于"互动→关注→承诺→帮助→反馈"闭环，不做独立信息流 |
| **与 Agent-Reach 耦合** | 🟡 中 | 专业版可选依赖，不硬编码；基础版完全不依赖 |
| **图数据库迁移压力** | 🟢 低 | 本报告已论证不迁移的合理性；若定制版有需求，用 PostgreSQL recursive CTE |

---

## 九、附录

### 9.1 参考资料

- [Agent-Reach GitHub](https://github.com/panniantong/Agent-Reach) (v1.5.0, 2026-06-11)
- [Agent-Reach CLAUDE.md](https://github.com/Panniantong/Agent-Reach/blob/main/CLAUDE.md)
- [cognee GitHub](https://github.com/topoteretes/cognee) (v1.0.4)
- [cognee 文档](https://docs.cognee.ai/)
- [CarryMem 竞品分析: 记忆从存储 → 关系图谱与压缩效率](file:///Users/lin/trae_projects/carrymem/docs/COMPETITIVE_ANALYSIS_MEMORY_GRAPH.md)
- [Codebase-Memory-MCP GitHub](https://github.com/DeusData/codebase-memory-mcp)

### 9.2 PromiseLink 相关文档

- [PRD 核心](file:///Users/lin/trae_projects/PromiseLink/docs/spec/PRD_核心.md) (v4.8)
- [技术设计](file:///Users/lin/trae_projects/PromiseLink/docs/architecture/PromiseLink_技术设计_v1.md)
- [算法设计](file:///Users/lin/trae_projects/PromiseLink/docs/design/Algorithm_Design_v1.md) (v2.8)
- [数据库设计](file:///Users/lin/trae_projects/PromiseLink/docs/design/Database_Design_v1.md) (v3.0)
- [集成设计](file:///Users/lin/trae_projects/PromiseLink/docs/design/Integration_Design_v1.md) (v2.9)
- [项目状态](file:///Users/lin/trae_projects/PromiseLink/docs/PROJECT_STATUS.md) (v0.7.0)

### 9.3 术语表

| 术语 | 含义 |
|------|------|
| Capability Layer | 能力层，Agent-Reach 的定位，负责选型/安装/体检/路由，不负责底层读取 |
| ECL | cognee 的核心管道: Extract-Cognify-Load |
| memify | cognee 的动态精炼步骤，剪枝陈旧节点、强化频繁连接 |
| Ontology | 本体论，cognee 用 RDF/OWL 规范化实体类型 |
| recursive CTE | SQL 递归公用表表达式，可实现多跳图遍历 |
| Louvain | 社区发现算法，识别紧密关联的节点群 |
| RelationshipBrief | PromiseLink 的关系推进卡，聚合视图 |
| AssociationEngine | PromiseLink 的关联发现引擎 |

---

> **报告结束**。本报告基于 2026-07-01 的公开信息分析，建议在实施前与团队 review 优先级排序，并根据 v0.7.0 Staging 灰度反馈调整路线图。
