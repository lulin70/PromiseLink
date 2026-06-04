# EventLink 项目生命周期状态总览

> **更新时间**: 2026-06-03 (P2 Gate通过)
> **当前阶段**: P8启动准备完成（脚手架已搭建，核心算法待实现）
> **产品定位**: AI驱动的个人商务关系经营助手
> **负责人**: 林总 (CarryMem 团队)
> **合作方**: 许总 (IAMHERE 数字名片)

---

## 1. 总览仪表板

```
EventLink 项目进度
═══════════════════════════════════════════════════════════

P1  需求分析      ██████████████████████  100%  ✅ 通过 (PRD v1完成)
P2  架构设计      ██████████████████████  100%  ✅ 通过 (7角色共识82%)
P3  技术设计      ██████████████████████  100%  ✅ 通过 (v1.7完整)
P4  数据设计      ████████████████████░░  85%  ✅ 通过(PoC)
P5  交互设计      ██████████████████████  95%  ✅ 通过(交付)
P6  安全审查      ████████████████████░░  85%  ✅ 通过(设计)
P7  测试计划      ██████████████████████  100%  ✅ 通过 (Test_Plan v1.2)
───────────────────────────────────────────────
P8  实施          ███████████░░░░░░░░░░░░  50%  🟡 进行中 (脚手架完成)
P9  测试执行      ░░░░░░░░░░░░░░░░░░░░░░░░   0%  ⬜ 未启动
P10 部署发布      ░░░░░░░░░░░░░░░░░░░░░░░░   0%  ⬜ 未启动
P11 运维保障      ░░░░░░░░░░░░░░░░░░░░░░░░   0%  ⬜ 未启动

═══════════════════════════════════════════════════════════
总体进度: ████████░░░░░░░░░░░░░░  38% (P8进行中，P2 Gate已通过) ⚠️ 小程序→EventLink边界接口缺口（Phase1前必须补齐：IAMHERE名片JSON格式、微信用户映射、card_save metadata schema）
下一里程碑: Week1 Day3-4实现P0核心算法
```

---

## 2. 项目目录结构

```
EventLink/
├── docs/
│   ├── spec/                         # 📝 需求规格
│   │   ├── PRD_v1.md                 # PRD v4.0（定位演化与利他闭环修订版）
│   │   └── PRD_v1_review_report.md   # PRD审核报告
│   │
│   ├── architecture/                 # 🏗️ 架构设计
│   │   └── EventLink_技术设计_v1.md   # 技术设计 v2.0
│   │
│   ├── design/                       # 🎨 详细设计
│   │   ├── API_Design_v1.md          # API设计 v1.2
│   │   ├── Algorithm_Design_v1.md    # 算法设计 v1.2
│   │   ├── Database_Design_v1.md     # 数据库设计 v1.2
│   │   ├── Integration_Design_v1.md  # 集成设计 v1.2
│   │   ├── Security_Design_v1.md     # 安全设计 v1.1
│   │   ├── Test_Plan_v1.md           # 测试计划 v1.2
│   │   ├── UI_UX_Design_v1.md        # UI/UX设计 v1.2
│   │   └── Deployment_Guide.md       # 部署指南 v1.0
│   │
│   ├── planning/                     # 📅 项目计划
│   │   ├── 20260601_会议纪要.md
│   │   ├── 20260602_许总团队讨论纪要.md
│   │   ├── 会议待确认事项清单.md
│   │   └── 分类体系方向_会议备忘.md
│   │
│   ├── reports/                      # 📊 评审报告
│   │   ├── EventLink_DevSquad_真实AI评审报告.md
│   │   ├── EventLink_POC准备度评估报告.md
│   │   └── EventLink_一页纸方案_给许总.md
│   │
│   ├── internal/                     # 🔒 内部文档（不对外分享）
│   │   ├── EventLink_产品设计讨论报告.md        # P1: 47项问题分析
│   │   ├── EventLink_产品设计评审报告.md         # P1: 设计评审
│   │   ├── EventLink_DevSquad_真实AI评审报告.md  # P1: 7角色AI评审
│   │   ├── EventLink_产品架构V2_数字名片整合方案.md # P2: 战略架构
│   │   └── EventLink_技术方案V3_技术版.md       # P2-P7: 技术方案源文件
│   │
│   ├── external/
│   │   ├── for_许总/                  # 📤 对外交付物
│   │   │   └── EventLink_技术方案V3_网页版.html   # P5: 最终技术提案
│   │   │
│   │   ├── for_李总/                  # 📤 对外交付物
│   │   │   └── EventLink_产品核心价值升级建议_资源匹配供给与维护版.md
│   │   │
│   │   └── for_team/                 # 📋 团队共享文档
│   │       ├── EventLink_最终总结报告.md          # P1: 执行摘要
│   │       ├── EventLink_分工模型V2.1_修正版.md    # P2: 分工协议
│   │       └── EventLink_一页纸方案_V2_精简版.md   # P1: 一页纸概览
│   │
│   ├── deliverables/                 # 📦 交付物清单
│   │   ├── PROJECT_STRUCTURE.md
│   │   └── README_SETUP.md
│   │
│   └── DOCUMENTATION_CHECKLIST.md    # 📋 文档检查清单
│
├── scripts/                          # 🔧 工具脚本
│   ├── run_review.py                 # DevSquad Mock模式评审
│   └── run_review_real_ai.py         # DevSquad 真实AI模式评审
│
├── archive/                          # 📦 归档
│   └── drafts/
│       └── EventLink_一页纸方案_给许总.md     # V1草稿（已被V2+HTML替代）
│
└── data/                             # 💾 运行数据
    └── llm_cache/                    # LLM缓存（可清理）
```

---

## 3. 十一阶段生命周期检查清单

### P1: 需求分析 (Requirements Analysis)

| 检查项 | 状态 | 证据文档 | 备注 |
|--------|------|---------|------|
| 原始需求文档已获取 | ✅ 完成 | `./WorkBuddy/20260320114823/ai-memory/` 下两份参考文档 | 用户版 + 产品设计版 |
| 需求差距分析已完成 | ✅ 完成 | `docs/internal/EventLink_产品设计讨论报告.md` | 47个问题，7维度 |
| AI多角色评审已完成 | ✅ 完成 | `docs/internal/EventLink_DevSquad_真实AI评审报告.md` | 7角色，真实API |
| 执行摘要已产出 | ✅ 完成 | `docs/external/for_team/EventLink_最终总结报告.md` | Top12问题，可行性7.0/10 |
| 合作方需求已整合 | ✅ 完成 | `docs/internal/EventLink_产品架构V2_数字名片整合方案.md` | 数字名片+动态采集整合 |
| **需求量化验收标准** | ✅ 完成 | `docs/spec/PRD_v1.md` (v4.0) | 152处量化指标，7角色审核有条件通过→已修订，定位演化为"关系经营助手" |

**P1 Gate 判定**: **✅ 通过** — PRD v4.0已完成，7角色审核共识达成，所有验收标准可量化，产品定位已从"资源经营"演化为"关系经营"。

**进入P2的条件**: ✅ 已满足

---

### P2: 架构设计 (Architecture Design)

| 检查项 | 状态 | 证据文档 | 备注 |
|------|------|---------|------|
| 三层架构模型已定义 | ✅ 完成 | `docs/internal/EventLink_技术方案V3_技术版.md` | L1入口→L2标准化→L3引擎 |
| 分工边界已明确 | ✅ 完成 | `docs/external/for_team/EventLink_分工模型V2.1_修正版.md` | 应用层(许总) / 引擎层(CarryMem) |
| 技术栈选型已完成 | ✅ 完成 | 技术方案V3 第🛠️节 | FastAPI+PG15+Redis7+NetworkX |
| 数据流图已绘制 | ✅ 完成 | 技术方案V3 ASCII架构图 | 含HTTP API调用关系 |
| 多角色共识达成 | ✅ 完成 | 7角色架构评审（加权共识82%） | 许总不参与技术决策，由林总团队决定 |
| **加权共识≥70%** | ✅ 完成 | 7角色架构评审加权共识82% | 许总不参与技术决策，由林总团队决定 |

**P2 Gate 判定**: **✅ 通过** — 7角色架构评审加权共识82%（≥70%门槛），许总不参与技术决策，由林总团队决定。

**进入P3的条件**: ✅ 已满足

---

### P3: 技术设计 (Technical Design)

| 检查项 | 状态 | 证据文档 | 备注 |
|------|------|---------|------|
| API接口规范已定义 | ✅ 完成 | `docs/design/API_Design_v1.md` (v1.2) | 完整REST API规范 |
| 核心数据模型已定义 | ✅ 完成 | `docs/design/Database_Design_v1.md` (v1.2) | Event, Entity, Association, Todo |
| 核心算法流程已定义 | ✅ 完成 | `docs/design/Algorithm_Design_v1.md` (v1.2) | 实体归一+关联发现+匹配度计算 |
| 实体归一含人工确认+撤回 | ✅ 完成 | Algorithm_Design Step 4-5 | Human-in-the-Loop + Rollback |
| 竞对数据来源已明确 | ✅ 完成 | 技术设计v2.0 | 公开网页检索，不含爬取 |
| 技术匹配度算法已定义 | ✅ 完成 | Algorithm_Design 四维打分法 | Jaccard+行业+LLM+历史 |
| **API无歧义** | ✅ 完成 | API_Design含请求/响应JSON示例 | 可直接用于开发 |
| 接口版本管理策略 | ✅ 完成 | API_Design §8（v1.3） | 三层SemVer+版本协商+废弃流程+Alembic迁移 |

**P3 Gate 判定**: **✅ 通过** — 技术设计v2.0完整，7份详细设计文档已产出，可直接指导PoC开发。

---

### P4: 数据设计 (Data Design)

| 检查项 | 状态 | 证据文档 | 备注 |
|------|------|---------|------|
| 核心数据结构已定义 | ✅ 完成 | `docs/design/Database_Design_v1.md` (v1.2) | Event/Entity/Association/Todo |
| 字段级加密策略 | ✅ 完成 | `docs/design/Security_Design_v1.md` (v1.1) | AES-256-GCM |
| JSONB使用策略 | ✅ 完成 | Database_Design | PostgreSQL 15, metadata字段灵活扩展 |
| 图数据存储方案 | ✅ 完成 | Database_Design | NetworkX + igraph |
| **3NF或反范式化论证** | ✅ 完成 | Database_Design v1.2 | 实用主义优先，适度反范式化 |

**P4 Gate 判定**: **✅ 通过** — Database_Design v1.2完成，含完整ER图与反范式化论证。

---

### P5: 交互设计 (Interaction Design)

| 检查项 | 状态 | 证据文档 | 备注 |
|------|------|---------|------|
| 对外交付物已就绪 | ✅ 完成 | `docs/external/for_许总/EventLink_技术方案V3_网页版.html` | 富文本HTML，渐变紫主题 |
| 预期效果示例已展示 | ✅ 完成 | HTML版第🎯节 | 3个示例卡片(商机/竞对/背景) |
| 分期路线图已展示 | ✅ 完成 | HTML版📋总览表 | 三期演进路径 |
| CTA行动指引清晰 | ✅ 完成 | 三步骤: 提供数据→搭建PoC→演示验证 | 无"约电话"措辞 |
| 移动端适配 | ✅ 完成 | CSS @media查询 | ≤768px响应式 |
| **核心流程可用性验证** | ⚠️ 静态稿 | HTML仅展示，无交互原型 | 许总反馈后可能需要调整 |

**P5 Gate 判定**: **✅ 通过（交付物阶段）** — 作为技术提案文档已达标。

---

### P6: 安全审查 (Security Review)

| 检查项 | 状态 | 证据文档 | 备注 |
|------|------|---------|------|
| 传输加密 | ✅ 完成 | `docs/design/Security_Design_v1.md` (v1.1) | TLS 1.3 + HSTS |
| 身份认证 | ✅ 完成 | Security_Design | JWT (access:15min, refresh:7d) |
| 权限控制 | ✅ 完成 | Security_Design | JWT认证 + 单用户数据隔离（无RBAC） |
| 数据加密 | ✅ 完成 | Security_Design | AES-256-GCM 字段级 |
| API Key管理 | ✅ 完成 | Security_Design | 操作系统钥匙串 |
| 审计日志 | ✅ 完成 | Security_Design | 全写操作记录 |
| 合规性 | ✅ 完成 | Security_Design | GDPR支持 |
| **无P0/P1漏洞** | ⚠️ 设计层面 | Security_Design v1.1 | P9阶段补充渗透测试 |

**P6 Gate 判定**: **✅ 通过（设计阶段）** — Security_Design v1.1覆盖全面，实施后需安全测试。

---

### P7: 测试计划 (Test Planning)

| 检查项 | 状态 | 证据文档 | 备注 |
|------|------|---------|------|
| PoC验证计划已制定 | ✅ 完成 | `docs/design/Test_Plan_v1.md` (v1.2) | 3周计划，含6种Todo类型验证 |
| Week1准入标准 | ✅ 完成 | Test_Plan | 20张名片解析，准确率>95%，延迟<200ms |
| Week2准入标准 | ✅ 完成 | Test_Plan | Precision@5>70%, Recall@10>60%, F1>0.65 |
| Week3准入标准 | ✅ 完成 | Test_Plan | E2E延迟<10s，可录屏Demo |
| E2E测试要求 | ✅ 完成 | Test_Plan v1.2 | 含模拟真实用户使用的E2E测试 |
| **测试计划评审通过** | ✅ 完成 | Test_Plan v1.2 | 独立文档已产出，含产品指标验证 |

**P7 Gate 判定**: **✅ 通过** — Test_Plan v1.2已独立产出，含E2E测试与产品指标验证。

---

### P8: 实施阶段 (Implementation)

| 检查项 | 状态 | 证据 | 备注 |
|------|------|------|------|
| 开发环境搭建 | ✅ 完成 | `pyproject.toml`, `requirements.txt`, `Dockerfile` | FastAPI项目脚手架 |
| Event接入API | ✅ 完成 | `src/eventlink/api/v1/events.py` | POST/GET/DELETE /api/v1/events |
| 数据库模型 | ✅ 完成 | `src/eventlink/models/` 4个文件 | Event/Entity/Association/Todo |
| 数据库连接 | ✅ 完成 | `src/eventlink/database.py` | SQLite+PostgreSQL异步支持 |
| Health API | ✅ 完成 | `src/eventlink/api/v1/health.py` | 基础+数据库健康检查 |
| 实体抽取模块 | ⏳ 待实现 | - | LLM NER pipeline (Week1 Day5-6) |
| 实体归一引擎 | ⏳ 待实现 | - | 5步算法含人工确认 (Week1 Day3-4) |
| 关联发现引擎 | ⏳ 待实现 | - | 共现+类型推断+衰减过滤 (Week2) |
| 商机匹配引擎 | ⏳ 待实现 | - | 六维打分法 (Week1 Day3-4) |
| Todo状态机 | ⏳ 待实现 | - | 5状态转移+Snooze (Week1 Day3-4) |
| Docker配置 | ✅ 完成 | `docker-compose.yml` | SQLite/PostgreSQL/Redis三种配置 |
| **代码审查通过** | ⏳ 待审查 | - | 脚手架代码已就绪 |

**P8 Gate 判定**: **🟡 进行中（50%）** — 脚手架搭建完成，P0核心算法待实现。

**当前状态**: 
- ✅ Week1 Day1-2完成（项目脚手架+数据模型+基础API）
- ⏳ Week1 Day3-4：实现P0三项核心算法（实体归一+商机匹配+Todo状态机）
- ⏳ Week1 Day5-6：完善事件处理管线+LLM集成

---

### P9: 测试执行 (Test Execution)

| 检查项 | 状态 | 证据 | 备注 |
|------|------|------|------|
| 单元测试 | ❌ 未开始 | - | 目标覆盖率≥80% |
| 集成测试 | ❌ 未开始 | - | API端到端 |
| 算法准确率验证 | ❌ 未开始 | - | 实体归一+关联发现 |
| 性能基准测试 | ❌ 未开始 | - | P95延迟目标 |
| 安全渗透测试 | ❌ 未开始 | - | P0/P1漏洞扫描 |
| **覆盖率≥80%** | ❌ 不适用 | - | |
| **P7计划100%执行** | ❌ 不适用 | - | |

**P9 Gate 判定**: **⬜ 未启动**

---

### P10: 部署与发布 (Deployment & Release)

| 检查项 | 状态 | 证据 | 备注 |
|------|------|------|------|
| CI/CD流水线 | ❌ 未开始 | - | GitHub Actions或类似 |
| 容器化打包 | ❌ 未开始 | - | Docker + K8s |
| 部署演练 | ❌ 未开始 | - | Staging环境 |
| 回滚方案 | ❌ 未开始 | - | 数据库迁移回滚 |
| 发布检查清单 | ❌ 未开始 | - | |

**P10 Gate 判定**: **⬜ 未启动**

---

### P11: 运维与保障 (Operations & Assurance)

| 检查项 | 状态 | 证据 | 备注 |
|------|------|------|------|
| 监控告警 | ❌ 未开始 | - | Prometheus metrics |
| 日志聚合 | ❌ 未开始 | - | ELK/Loki |
| 备份策略 | ❌ 未开始 | - | PG dump + Redis AOF |
| P99延迟达标 | ❌ 不适用 | - | |
| 告警100%覆盖 | ❌ 不适用 | - | |

**P11 Gate 判定**: **⬜ 未启动**

---

## 4. 阶段依赖关系与关键路径

```
当前所处位置:
                [P1 ✅] ──→ [P2 ✅] ──→ [P3 ✅] ──→ [P6 ✅] ──→ [P7 ✅] ──→ [P8 🟡50%] ──→ [P9 ⬜] ──→ [P10⬜] ──→ [P11⬜]
                   │           │           │                        ▲                                        
                   ├→ [P4 ✅] ──┘           └→ [P5 ✅] ──────────────┘
                   └→ [P5(depends P1+P3)]                         YOU ARE HERE

关键路径: P1 → P2 → P3 → P7 → P8 → P9 → P10 → P11
当前节点: P8实施阶段（Week1 Day2完成，Day3-4进行中）
下一节点: Week1 Day3-4实现P0三项核心算法
```

---

## 5. 下一步行动计划

### 🎯 立即行动 (Week1 Day3-4，今明两天)

| # | 行动项 | 负责方 | 产出 | 对应阶段 |
|---|--------|--------|------|---------|
| 1 | **实现实体归一引擎** | CarryMem | `src/eventlink/services/entity_resolution.py` | P8 (P0-1) |
| 2 | **实现商机匹配器** | CarryMem | `src/eventlink/services/promise_fulfillment.py` | P8 (P0-2) |
| 3 | **实现Todo状态机** | CarryMem | `src/eventlink/services/todo_state_machine.py` | P8 (P0-3) |

**参考资料**: 技术设计v1.7 §4.4-4.6（第616-941行完整Python代码）

### 📋 本周后续 (Week1 Day5-7)

| # | 行动项 | 负责方 | 产出 | 对应阶段 |
|---|--------|--------|------|---------|
| 4 | 完善Event处理管线 | CarryMem | 异步处理pipeline | P8 |
| 5 | 集成LLM实体抽取 | CarryMem | LLM NER调用 | P8 |
| 6 | 整合测试 | CarryMem | Week1退出标准验证 | P9启动 |

### 🔄 并行工作（不阻塞P8）

| # | 行动项 | 负责方 | 产出 | 对应阶段 |
|---|--------|--------|------|---------|
| 7 | 发送HTML技术方案给许总 | 林总 | 许总反馈 | P2 Gate |
| 8 | 向许总索取名片样例数据 | 林总 | 20张脱敏名片 | P8测试数据 |

### 🚩 里程碑节点

| 里程碑 | 时间预估 | 触发条件 | 交付物 |
|--------|---------|---------|--------|
| **M1: 规划完成** | 即将到达 | 许总确认+PRD+测试计划就绪 | 完整规划文档包 |
| **M2: PoC Demo** | 确认后3周 | M1完成+样例数据到手 | 可演示的最小系统 |
| **M3: 正式合作决策** | M2后1周 | PoC演示成功 | 合作协议/MOU |

---

## 6. 风险登记册

| ID | 风险描述 | 概率 | 影响 | 应对策略 | 状态 |
|----|---------|------|------|---------|------|
| R01 | 许总对技术方案提出大幅修改意见 | 中 | 高 | 快速迭代HTML版本（已验证4轮迭代能力） | 🟡 监控中 |
| R02 | 小程序→EventLink边界接口缺口（名片JSON格式+用户映射+metadata schema） | 高 | 中 | ⚠️ 待确认（Phase1前必须补齐） | ①向许总团队获取IAMHERE名片样例JSON ②设计user_auth_mappings表 ③定义card_save metadata schema |
| R03 | LLM实体抽取准确率不达95% | 低 | 高 | spaCy降级兜底 + 人工确认机制 | 🟢 已缓解 |
| R04 | 竞对关系网页信息检索效果差 | 中 | 中 | 第一期降低预期，以用户标注为主 | 🟢 已缓解 |
| R05 | 许总决定不继续合作 | 低 | 极高 | 核心引擎独立于IAMHERE，可换其他数据源 | 🟢 已缓解 |

---

## 7. 决策记录 (Decision Log)

| 日期 | 决策内容 | 理由 | 影响 |
|------|---------|------|------|
| 2026-05-31 | 排除公开信息爬取作为数据来源 | 法律风险 | 竞对判断依赖网页检索+用户标注 |
| 2026-05-31 | 政府采购数据不从文档提及 | 口头沟通更灵活 | 文档只提"专业数据服务增强" |
| 2026-05-31 | 工商API第一期不做，只做网页查找 | 成本控制 | 降低初期投入，验证后再决定 |
| 2026-06-01 | 实体归一必须人工确认+可撤回 | 数据准确性不可妥协 | 增加Step 5 Human-in-the-Loop |
| 2026-06-01 | 文档去除"你/我"指派口吻 | 专业性 | 全文改为第三人称客观描述 |
| 2026-06-01 | CTA区域不含"约电话"语言 | 材料自包含 | 只保留三步骤行动指引 |
| 2026-06-03 | 许总不参与技术决策，架构设计由林总团队决定 | 许总对技术方案不感兴趣，专注业务合作 | P2 Gate不再等许总确认 |

---

*本文档由 DevSquad 11阶段生命周期框架生成，随项目进展持续更新。*
