# EventLink 项目生命周期状态总览

> **更新时间**: 2026-06-04 (D11 批次1 P0文档完成)
> **当前阶段**: POC增强阶段（0.2.x）— 李总v1.2+许总POC反馈融合完成，设计文档全面更新中
> **产品定位**: AI驱动的个人商务关系经营助手
> **负责人**: 林总 (CarryMem 团队)
> **合作方**: 许总 (IAMHERE 数字名片)

---

## 1. 总览仪表板

```
EventLink 项目进度
═══════════════════════════════════════════════════════════

P1  需求分析      ██████████████████████  100%  ✅ 通过 (PRD v4.3)
P2  架构设计      ██████████████████████  100%  ✅ 通过 (7角色共识82%)
P3  技术设计      ██████████████████████  100%  ✅ 通过 (v2.5完整)
P4  数据设计      ██████████████████████  100%  ✅ 通过 (v2.0)
P5  交互设计      ████████████████████░░  85%  ✅ 通过(交付/UI待定)
P6  安全审查      ██████████████████████  100%  ✅ 通过 (v2.0, 10项D3变更)
P7  测试计划      ██████████████████████  100%  ✅ 通过 (Test_Plan v2.0)
───────────────────────────────────────────────
P8  实施          ████████████████░░░░░░░  65%  🟡 进行中 (PoC基础+文档更新中)
P9  测试执行      ░░░░░░░░░░░░░░░░░░░░░░░░   0%  ⬜ 未启动
P10 部署发布      ██████████████░░░░░░░░░  50%  🟡 部分完成(Docker+CI/CD+Alembic就绪)
P11 运维保障      ░░░░░░░░░░░░░░░░░░░░░░░░   0%  ⬜ 未启动

═══════════════════════════════════════════════════════════
总体进度: █████████░░░░░░░░░░░░░░░  45% (POC增强阶段，7份P0设计文档已更新至v2.0)
最新Commit: 2d5dd6d (批次1 P0文档 - API/DB/Algorithm/Security/Test/Integration/Deployment)
下一里程碑: Sprint 0 冻结方向 + 回归测试集建立
```

---

## 2. 版本信息

| 维度 | 版本 | 说明 |
|------|------|------|
| **PRD** | v4.3 | 李总v1.2+许总POC反馈+7角色Review融合修订版 |
| **技术设计** | v2.5 | 文档一致性Bugfix：BLK-3枚举值/F-49路径对齐/乐观锁完善 |
| **软件版本** | 0.2.x | POC增强阶段（0.1.x=初始化 → 0.2.x=POC → 0.3.x=Phase1 → 0.4.x=Phase2） |
| **API_Design** | v2.0 | 10项D2变更（6个新端点+JWT加固+PII脱敏+F-05暂停） |
| **Database_Design** | v2.0 | relationship_stage+properties字段+Alembic迁移 |
| **Algorithm_Design** | v2.0 | input_scope分类器+Promise双向动作+Todo降噪算法 |
| **Security_Design** | v2.0 | 10项D3变更（PII检测正则+JWT规范+STRIDE+SC-01） |
| **Test_Plan** | v2.0 | 参考PRD v4.3/技术设计v2.5全面刷新 |
| **Integration_Design** | v2.0 | CarryMem集成+IAMHERE对接+LLM调用 |
| **Deployment_Guide** | 0.2.0 | Docker多阶段构建+GitHub Actions CI/CD+Prometheus监控+Alembic |
| **UI_UX_Design** | v1.2 | 待更新至v2.0（推进卡+日视图+阶段管理交互） |

### 设计文档更新状态（批次1 已完成）

| 文档 | 目标版本 | 状态 | 关键变更 |
|------|---------|------|---------|
| API_Design_v1.md | v2.0 | ✅ 完成 | 6个新P0端点+JWT+PII+SC-01 |
| Database_Design_v1.md | v2.0 | ✅ 完成 | relationship_stage+properties+迁移脚本 |
| Algorithm_Design_v1.md | v2.0 | ✅ 完成 | F-44/45/46核心算法伪代码 |
| Security_Design_v1.md | v2.0 | ✅ 完成 | PII检测+JWT HS256+STRIDE威胁模型 |
| Test_Plan_v1.md | v2.0 | ✅ 完成 | E2E测试用例+P0功能验证 |
| Integration_Design_v1.md | v2.0 | ✅ 完成 | CarryMem协议+IAMHERE对接+LLM封装 |
| Deployment_Guide.md | 0.2.0 | ✅ 完成 | CI/CD+Docker+Prometheus+Alembic |
| UI_UX_Design_v1.md | v2.0 | ⏳ 待定 | 推进卡F-47+日视图F-49+阶段F-48交互 |

---

## 3. 功能矩阵

### ✅ 已完成功能（PoC基础）

| # | 功能模块 | 实现文件 | 状态 | 说明 |
|---|---------|---------|------|------|
| F-01 | 事件语义路由 | `services/event_pipeline.py` | ✅ PoC | 事件接入+语义路由管线 |
| F-02 | 管线化实体抽取 | `services/entity_extractor.py` + `prompts/entity_extraction.py` | ✅ PoC | LLM NER pipeline |
| F-03 | 实体归一（5步算法） | `services/entity_resolution.py` | ✅ PoC | 含人工确认+撤回机制 |
| F-04 | 关联发现（8种类型） | `services/association_discovery.py` | ✅ PoC | 共现+类型推断+衰减过滤 |
| F-06 | Todo生成与追踪 | `services/todo_generator.py` + `todo_state_machine.py` | ✅ PoC | 6种Todo类型+5状态转移+Snooze |
| — | JWT鉴权 | `api/v1/auth.py` + `core/auth.py` | ✅ PoC | JWT认证模块 |
| — | PII脱敏 | `core/crypto.py` | ✅ PoC | AES-256-GCM字段级加密 |
| — | Redis缓存 | `core/redis.py` | ✅ PoC | Redis 7连接+缓存层 |
| — | LLM客户端 | `services/llm_client.py` | ✅ PoC | Moka AI接口封装 |
| — | CarryMem集成 | `services/memory_provider.py` | ✅ PoC | 记忆层协议适配 |
| — | 数据库迁移 | `alembic/versions/*.py` | ✅ PoC | Alembic初始化schema |

### 🆕 新规划功能（Sprint 1 目标，F-44~F-49）

| # | 功能 | 优先级 | Sprint | 说明 |
|---|------|--------|--------|------|
| **F-44** | input_scope 分类器 | P0 | Sprint 1 | 8种scope自动路由（card_save/meeting/call/manual/followup/feedback/contribution/admin） |
| **F-45** | Promise 双向动作 | P0 | Sprint 1 | action_type 6种（contact/send/research/prepare/decide/monitor）+ promisor/beneficiary |
| **F-46** | Todo 降噪 | P0 | Sprint 1 | 去重+优先级排序+置信度过滤 |
| **F-47** | RelationshipBrief 推进卡 | P0 | Sprint 1~2 | 12模块结构化关系画像 |
| **F-48** | RelationshipStage 阶段管理 | P0 | Sprint 1~2 | AI建议不自动升级+乐观锁并发控制 |
| **F-49** | 日视图 Dashboard | P0额外 | Sprint 2 | GET /dashboard/day-view + GET /dashboard/today |

### 🔒 Security 三项（BLK）

| ID | 安全项 | 对应功能 | 状态 |
|----|--------|---------|------|
| BLK-1 | PII 脱敏 | 全局 | ✅ 设计完成（Security_Design v2.0 §3.6） |
| BLK-2 | input_scope SC-01 | F-44 | ✅ 设计完成（服务端强制校验，不以客户端为准） |
| BLK-3 | action_type 统一 | F-45 | ✅ 设计完成（枚举值一致性修复，v2.5） |

### ⏸️ 暂停功能

| # | 功能 | 原因 | 重启条件 |
|---|------|------|---------|
| F-05 | 商机匹配度（六维打分） | 与"关系经营助手"定位冲突 | Phase 2 条件性重启 |

---

## 4. 项目目录结构

```
EventLink/
├── docs/
│   ├── spec/                         # 📝 需求规格
│   │   ├── PRD_v1.md                 # PRD v4.3（李总v1.2+许总POC融合）
│   │   ├── PRD_v1_review_report.md   # PRD审核报告
│   │   └── README.md                 # spec索引（✅ 已更新至v4.3）
│   │
│   ├── architecture/                 # 🏗️ 架构设计
│   │   └── EventLink_技术设计_v1.md   # 技术设计 v2.5
│   │
│   ├── design/                       # 🎨 详细设计（批次1: 7份→v2.0 ✅）
│   │   ├── README.md                 # 设计文档索引
│   │   ├── API_Design_v1.md          # API设计 v2.0 ✅
│   │   ├── Algorithm_Design_v1.md    # 算法设计 v2.0 ✅
│   │   ├── Database_Design_v1.md     # 数据库设计 v2.0 ✅
│   │   ├── Integration_Design_v1.md  # 集成设计 v2.0 ✅
│   │   ├── Security_Design_v1.md     # 安全设计 v2.0 ✅
│   │   ├── Test_Plan_v1.md           # 测试计划 v2.0 ✅
│   │   ├── UI_UX_Design_v1.md        # UI/UX设计 v1.2 ⏳ 待更新
│   │   ├── Deployment_Guide.md       # 部署指南 0.2.0 ✅
│   │   └── LLM_Prompt_Templates.md   # LLM提示词模板
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
│   ├── internal/                     # 🔒 内部文档
│   │   ├── EventLink_产品设计讨论报告.md
│   │   ├── EventLink_产品设计评审报告.md
│   │   ├── EventLink_DevSquad_真实AI评审报告.md
│   │   ├── EventLink_产品架构V2_数字名片整合方案.md
│   │   └── EventLink_技术方案V3_技术版.md
│   │
│   ├── external/
│   │   ├── for_许总/                  # 📤 对外交付物
│   │   │   └── EventLink_技术方案V3_网页版.html
│   │   ├── for_李总/                  # 📤 对外交付物
│   │   │   └── EventLink_产品核心价值升级建议_资源匹配供给与维护版.md
│   │   └── for_team/                 # 📋 团队共享文档
│   │       ├── EventLink_最终总结报告.md
│   │       ├── EventLink_分工模型V2.1_修正版.md
│   │       └── EventLink_一页纸方案_V2_精简版.md
│   │
│   ├── deliverables/                 # 📦 交付物清单
│   │   ├── PROJECT_STRUCTURE.md
│   │   └── README_SETUP.md
│   │
│   └── DOCUMENTATION_CHECKLIST.md    # 📋 文档检查清单
│
├── src/eventlink/                    # 💻 源代码（PoC实现中）
│   ├── main.py                       # FastAPI应用入口
│   ├── config.py                     # 配置管理
│   ├── database.py                   # 数据库连接（SQLite+PG异步）
│   │
│   ├── models/                       # 数据模型
│   │   ├── event.py                  # Event模型
│   │   ├── entity.py                 # Entity模型
│   │   ├── association.py            # Association模型
│   │   └── todo.py                   # Todo模型
│   │
│   ├── api/v1/                       # REST API
│   │   ├── events.py                 # POST/GET/DELETE /events
│   │   ├── entities.py               # GET /entities
│   │   ├── associations.py           # GET /associations
│   │   ├── todos.py                  # GET/POST/PATCH /todos
│   │   ├── auth.py                   # JWT认证端点
│   │   ├── health.py                 # 健康检查
│   │   └── schemas.py                # Pydantic请求/响应模型
│   │
│   ├── services/                     # 核心业务逻辑
│   │   ├── event_pipeline.py         # 事件处理管线
│   │   ├── entity_extractor.py       # LLM实体抽取
│   │   ├── entity_resolution.py      # 实体归一引擎（5步算法）
│   │   ├── association_discovery.py  # 关联发现引擎
│   │   ├── promise_fulfillment.py    # 商机匹配器
│   │   ├── todo_generator.py         # Todo生成器
│   │   ├── todo_state_machine.py     # Todo状态机
│   │   ├── llm_client.py             # LLM客户端封装
│   │   ├── memory_provider.py        # CarryMem记忆层适配
│   │   └── notification_service.py   # 通知服务
│   │
│   ├── core/                         # 基础设施
│   │   ├── auth.py                   # JWT工具函数
│   │   ├── crypto.py                 # 加密/PII脱敏
│   │   ├── redis.py                  # Redis缓存客户端
│   │   ├── text_utils.py             # 文本处理工具
│   │   ├── wechat.py                 # 微信小程序对接
│   │   ├── logging.py                # 日志配置
│   │   └── exceptions.py             # 自定义异常
│   │
│   ├── prompts/                      # LLM提示词模板
│   │   ├── entity_extraction.py      # 实体抽取prompt
│   │   └── todo_generation.py        # Todo生成prompt
│   │
│   └── alembic/                      # 数据库迁移
│       ├── env.py
│       └── versions/
│           └── 4a1cfeaf1eb1_initial_schema.py
│
├── scripts/                          # 🔧 工具脚本
│   ├── run_review.py                 # DevSquad Mock模式评审
│   └── run_review_real_ai.py         # DevSquad 真实AI模式评审
│
├── archive/                          # 📦 归档
│   └── drafts/
│       └── EventLink_一页纸方案_给许总.md
│
└── data/                             # 💾 运行数据
    └── llm_cache/                    # LLM缓存（可清理）
```

---

## 5. 十一阶段生命周期检查清单

### P1: 需求分析 (Requirements Analysis)

| 检查项 | 状态 | 证据文档 | 备注 |
|--------|------|---------|------|
| 原始需求文档已获取 | ✅ 完成 | `./WorkBuddy/20260320114823/ai-memory/` 下两份参考文档 | 用户版 + 产品设计版 |
| 需求差距分析已完成 | ✅ 完成 | `docs/internal/EventLink_产品设计讨论报告.md` | 47个问题，7维度 |
| AI多角色评审已完成 | ✅ 完成 | `docs/internal/EventLink_DevSquad_真实AI评审报告.md` | 7角色，真实API |
| 执行摘要已产出 | ✅ 完成 | `docs/external/for_team/EventLink_最终总结报告.md` | Top12问题，可行性7.0/10 |
| 合作方需求已整合 | ✅ 完成 | `docs/internal/EventLink_产品架构V2_数字名片整合方案.md` | 数字名片+动态采集整合 |
| **需求量化验收标准** | ✅ 完成 | `docs/spec/PRD_v1.md` (**v4.3**) | 152处量化指标，49项功能（F-01~F-49），含李总v1.2+许总POC反馈融合 |

**P1 Gate 判定**: **✅ 通过** — PRD v4.3已完成，7角色审核共识达成，产品定位演化为"AI驱动的个人商务关系经营助手"。

---

### P2: 架构设计 (Architecture Design)

| 检查项 | 状态 | 证据文档 | 备注 |
|------|------|---------|------|
| 三层架构模型已定义 | ✅ 完成 | `docs/internal/EventLink_技术方案V3_技术版.md` | L1入口→L2标准化→L3引擎 |
| 分工边界已明确 | ✅ 完成 | `docs/external/for_team/EventLink_分工模型V2.1_修正版.md` | 应用层(许总) / 引擎层(CarryMem) |
| 技术栈选型已完成 | ✅ 完成 | 技术方案V3 | FastAPI+PG15+Redis7+NetworkX |
| 数据流图已绘制 | ✅ 完成 | 技术设计v2.5 §2 | 含HTTP API调用关系+H5内嵌方案 |
| 多角色共识达成 | ✅ 完成 | 7角色架构评审（加权共识82%） | 许总不参与技术决策 |

**P2 Gate 判定**: **✅ 通过** — 7角色架构评审加权共识82%（≥70%门槛）。

---

### P3: 技术设计 (Technical Design)

| 检查项 | 状态 | 证据文档 | 备注 |
|------|------|---------|------|
| API接口规范已定义 | ✅ 完成 | `docs/design/API_Design_v1.md` (**v2.0**) | 10项D2变更，6个新P0端点 |
| 核心数据模型已定义 | ✅ 完成 | `docs/design/Database_Design_v1.md` (**v2.0**) | relationship_stage+properties新增 |
| 核心算法流程已定义 | ✅ 完成 | `docs/design/Algorithm_Design_v1.md` (**v2.0**) | F-44/45/46核心算法 |
| 实体归一含人工确认+撤回 | ✅ 完成 | Algorithm_Design + 代码实现 | Human-in-the-Loop + Rollback |
| 接口版本管理策略 | ✅ 完成 | API_Design v2.0 | 三层SemVer+废弃流程+Alembic |
| **技术设计v2.5** | ✅ 完成 | `docs/architecture/EventLink_技术设计_v1.md` | BLK-3修复+F-49对齐+乐观锁完善 |

**P3 Gate 判定**: **✅ 通过** — 技术设计v2.5完整，7份详细设计文档已更新至v2.0/0.2.0。

---

### P4: 数据设计 (Data Design)

| 检查项 | 状态 | 证据文档 | 备注 |
|------|------|---------|------|
| 核心数据结构已定义 | ✅ 完成 | `docs/design/Database_Design_v1.md` (**v2.0**) | Event/Entity/Association/Todo + stage/properties |
| 字段级加密策略 | ✅ 完成 | `docs/design/Security_Design_v1.md` (**v2.0**) | AES-256-GCM + PII检测正则 |
| JSONB使用策略 | ✅ 完成 | Database_Design v2.0 | PostgreSQL 15, metadata灵活扩展 |
| 图数据存储方案 | ✅ 完成 | Database_Design v2.0 | NetworkX + igraph |
| Alembic迁移就绪 | ✅ 完成 | `src/eventlink/alembic/` | 初始schema迁移脚本 |
| **3NF或反范式化论证** | ✅ 完成 | Database_Design v2.0 | 实用主义优先 |

**P4 Gate 判定**: **✅ 通过** — Database_Design v2.0完成，含完整ER图与v1.2→v2.0迁移路径。

---

### P5: 交互设计 (Interaction Design)

| 检查项 | 状态 | 证据文档 | 备注 |
|------|------|---------|------|
| 对外交付物已就绪 | ✅ 完成 | `docs/external/for_许总/EventLink_技术方案V3_网页版.html` | 富文本HTML |
| H5页面方案已定义 | ✅ 完成 | 技术设计v2.5 §2.1 | WebView内嵌方案 |
| UI/UX设计稿 | ⏳ 待更新 | `docs/design/UI_UX_Design_v1.md` (v1.2) | 推进卡+日视图+阶段管理交互待设计 |

**P5 Gate 判定**: **🟡 部分通过** — 对外交付物已完成，UI/UX设计待随F-47/F-48/F-49同步更新至v2.0。

---

### P6: 安全审查 (Security Review)

| 检查项 | 状态 | 证据文档 | 备注 |
|------|------|---------|------|
| 传输加密 | ✅ 完成 | `docs/design/Security_Design_v1.md` (**v2.0**) | TLS 1.3 + HSTS |
| 身份认证 | ✅ 完成 | Security_Design v2.0 + 代码实现 | JWT HS256 (access:15min, refresh:7d) |
| 权限控制 | ✅ 完成 | Security_Design v2.0 | JWT认证 + 单用户数据隔离 |
| 数据加密 | ✅ 完成 | Security_Design v2.0 + `core/crypto.py` | AES-256-GCM 字段级 |
| PII脱敏 | ✅ 完成 | Security_Design v2.0 §3.6 | 6种PII检测正则 + redact_pii_from_text() |
| SC-01输入分类越权防护 | ✅ 完成 | Security_Design v2.0 §5.6 | input_scope服务端强制校验 |
| STRIDE威胁模型 | ✅ 完成 | Security_Design v2.0 §1.2 | 6类标准分类+实施状态追踪 |
| 审计日志 | ✅ 完成 | Security_Design v2.0 | 全写操作记录 |
| **无P0/P1漏洞** | ⚠️ 设计层面 | Security_Design v2.0 | P9阶段补充渗透测试 |

**P6 Gate 判定**: **✅ 通过（设计阶段v2.0）** — 10项D3变更覆盖全面，含PII/JWT/SC-01/STRIDE/TTS安全评估/数据导出安全/依赖安全。

---

### P7: 测试计划 (Test Planning)

| 检查项 | 状态 | 证据文档 | 备注 |
|------|------|---------|------|
| PoC验证计划已制定 | ✅ 完成 | `docs/design/Test_Plan_v1.md` (**v2.0**) | 参考PRD v4.3/技术设计v2.5 |
| Week1准入标准 | ✅ 完成 | Test_Plan v2.0 | 20张名片解析>95%, 延迟<200ms |
| Week2准入标准 | ✅ 完成 | Test_Plan v2.0 | Precision@5>70%, Recall@10>60%, F1>0.65 |
| Week3准入标准 | ✅ 完成 | Test_Plan v2.0 | E2E延迟<10s, 可录屏Demo |
| E2E测试要求 | ✅ 完成 | Test_Plan v2.0 | 含模拟真实用户使用的E2E测试 |
| P0功能验证用例 | ✅ 完成 | Test_Plan v2.0 | F-44~F-49专项测试用例 |

**P7 Gate 判定**: **✅ 通过** — Test_Plan v2.0已全面刷新，含P0五项功能+E2E+安全测试。

---

### P8: 实施阶段 (Implementation) — 当前重点

| 检查项 | 状态 | 证据 | 备注 |
|------|------|------|------|
| 开发环境搭建 | ✅ 完成 | `pyproject.toml`, `requirements.txt`, `Dockerfile` | FastAPI项目脚手架 |
| Event接入API | ✅ 完成 | `src/eventlink/api/v1/events.py` | POST/GET/DELETE /api/v1/events |
| Entity API | ✅ 完成 | `src/eventlink/api/v1/entities.py` | GET /api/v1/entities |
| Association API | ✅ 完成 | `src/eventlink/api/v1/associations.py` | GET /api/v1/associations |
| Todo API | ✅ 完成 | `src/eventlink/api/v1/todos.py` | GET/POST/PATCH /api/v1/todos |
| Auth API (JWT) | ✅ 完成 | `src/eventlink/api/v1/auth.py` + `core/auth.py` | JWT认证端点 |
| Health API | ✅ 完成 | `src/eventlink/api/v1/health.py` | 基础+数据库健康检查 |
| 数据库模型 | ✅ 完成 | `src/eventlink/models/` 4个文件 | Event/Entity/Association/Todo |
| 数据库连接 | ✅ 完成 | `src/eventlink/database.py` | SQLite+PostgreSQL异步支持 |
| 实体抽取模块 | ✅ 完成 | `services/entity_extractor.py` + prompts | LLM NER pipeline |
| 实体归一引擎 | ✅ 完成 | `services/entity_resolution.py` | 5步算法含人工确认 |
| 关联发现引擎 | ✅ 完成 | `services/association_discovery.py` | 共现+类型推断+衰减过滤 |
| 商机匹配引擎 | ✅ 完成 | `services/promise_fulfillment.py` | 六维打分法（⏸️ Phase2暂停） |
| Todo状态机 | ✅ 完成 | `services/todo_state_machine.py` | 5状态转移+Snooze |
| Todo生成器 | ✅ 完成 | `services/todo_generator.py` + prompts | 6种Todo类型生成 |
| 事件处理管线 | ✅ 完成 | `services/event_pipeline.py` | 异步处理pipeline |
| LLM客户端 | ✅ 完成 | `services/llm_client.py` | Moka AI接口封装 |
| CarryMem集成 | ✅ 完成 | `services/memory_provider.py` | 记忆层协议适配 |
| PII脱敏模块 | ✅ 完成 | `core/crypto.py` | AES-256-GCM |
| Redis缓存 | ✅ 完成 | `core/redis.py` | Redis 7连接 |
| 微信对接 | ✅ 完成 | `core/wechat.py` | 小程序Token/用户映射 |
| Alembic迁移 | ✅ 完成 | `src/eventlink/alembic/` | 初始schema |
| Pydantic Schema | ✅ 完成 | `api/v1/schemas.py` | 请求/响应模型 |
| Docker配置 | ✅ 完成 | `docker-compose.yml` | SQLite/PostgreSQL/Redis三种配置 |
| **F-44 input_scope分类器** | ⏳ 待实施 | Algorithm_Design v2.0 | Sprint 1 P0 |
| **F-45 Promise双向动作** | ⏳ 待实施 | Algorithm_Design v2.0 | Sprint 1 P0 |
| **F-46 Todo降噪** | ⏳ 待实施 | Algorithm_Design v2.0 | Sprint 1 P0 |
| **F-47 RelationshipBrief推进卡** | ⏳ 待实施 | API_Design v2.0 | Sprint 1~2 P0 |
| **F-48 RelationshipStage阶段** | ⏳ 待实施 | DB_Design v2.0 | Sprint 1~2 P0 |
| **F-49 日视图Dashboard** | ⏳ 待实施 | API_Design v2.0 | Sprint 2 P0额外 |
| **代码审查通过** | ⏳ 待审查 | - | PoC基础代码+批次1文档 |

**P8 Gate 判定**: **🟡 进行中（65%）** — PoC基础功能全部实现，P0五项新功能(F-44~F-49)待Sprint 1实施。

**当前状态**:
- ✅ 0.1.x 初始化阶段完成（脚手架+数据模型+基础API+核心算法PoC）
- ✅ 0.2.x POC增强阶段进行中 — 批次1文档更新完成（7份P0设计文档→v2.0）
- ⏳ 下一步：Sprint 0 冻结方向 + 回归测试集建立

---

### P9: 测试执行 (Test Execution)

| 检查项 | 状态 | 证据 | 备注 |
|------|------|------|------|
| 单元测试 | ❌ 未开始 | - | 目标覆盖率≥80% |
| 集成测试 | ❌ 未开始 | - | API端到端 |
| 算法准确率验证 | ❌ 未开始 | - | 实体归一+关联发现+F-44~F-46 |
| 性能基准测试 | ❌ 未开始 | - | P95延迟目标 |
| 安全渗透测试 | ❌ 未开始 | - | P0/P1漏洞扫描 |
| E2E测试（模拟真实用户） | ❌ 未开始 | - | Test_Plan v2.0要求 |

**P9 Gate 判定**: **⬜ 未启动** — 等待Sprint 0回归测试集建立后启动

---

### P10: 部署与发布 (Deployment & Release)

| 检查项 | 状态 | 证据 | 备注 |
|------|------|------|------|
| Docker容器化 | ✅ 完成 | `Dockerfile` + `docker-compose.yml` | 多阶段构建(builder→runtime非root) |
| GitHub Actions CI/CD | ✅ 完成 | `Deployment_Guide` 0.2.0 | trigger/strategy/services/steps/lint/typecheck/test/coverage |
| Alembic数据库迁移 | ✅ 完成 | `src/eventlink/alembic/` | 初始化+autogenerate+SQLite→PG升级路径 |
| Prometheus监控指标 | ✅ 完成 | `Deployment_Guide` 0.2.0 | 6项P0指标(input_scope延迟/Todo分布等) |
| Staging环境部署 | ❌ 未开始 | - | |
| 回滚方案 | ⏳ 设计完成 | Deployment_Guide | 数据库迁移回滚 |
| 发布检查清单 | ❌ 未开始 | - | |

**P10 Gate 判定**: **🟡 部分完成（50%）** — Docker+CI/CD+Alembic+Prometheus就绪，Staging部署未开始。

---

### P11: 运维与保障 (Operations & Assurance)

| 检查项 | 状态 | 证据 | 备注 |
|------|------|------|------|
| 监控告警 | ❌ 未开始 | - | Prometheus metrics已定义，Grafana未配置 |
| 日志聚合 | ❌ 未开始 | - | ELK/Loki |
| 备份策略 | ❌ 未开始 | - | PG dump + Redis AOF |

**P11 Gate 判定**: **⬜ 未启动**

---

## 6. 阶段依赖关系与关键路径

```
当前所处位置:
                [P1 ✅] ──→ [P2 ✅] ──→ [P3 ✅] ──→ [P6 ✅] ──→ [P7 ✅] ──→ [P8 🟡65%] ──→ [P9 ⬜] ──→ [P10🟡50%] ──→ [P11⬜]
                   │           │           │                        ▲                                        
                   ├→ [P4 ✅] ──┘           └→ [P5 🟡85%] ────────────┘
                   └→ [P5(depends P1+P3)]                         YOU ARE HERE

关键路径: P1 → P2 → P3 → P7 → P8 → P9 → P10 → P11
当前节点: P8实施阶段（POC增强 0.2.x，批次1文档已完成）
下一节点: Sprint 0 冻结方向 + 回归测试集建立
```

---

## 7. 里程碑时间线

```
2026-05-31  ┌─ M0: 项目启动 + P1-P3 规划阶段
            │
2026-06-01  ├─ M1: P1 Gate通过 — PRD v1.0 + 7角色评审
            │
2026-06-03  ├─ M2: P2-P7 Gate全通过 — 脚手架搭建完成(P8 50%)
            │         Commit: 初始化代码 + 基础API
            │
2026-06-04  ├─ ★ M3: PRD v4.3 + Tech v2.5 发布
            │         李总v1.2 + 许总POC反馈融合完成
            │         Commit: 93b6f9c (PRD+Tech+Security+CI/CD)
            │
2026-06-04  ├─ ★ M4: 批次1 P0文档完成 (当前)
            │         7份设计文档更新至v2.0/0.2.0
            │         Commit: 2d5dd6d (HEAD)
            │
     ?      ├─ M5: Sprint 0 — 冻结方向 + 回归测试集建立
     │      │   (预计 D11-6 ~ D11-10)
     │      │
     ?      ├─ M6: Sprint 1 — P0五项实施 (F-44 ~ F-48)
     │      │   · F-44 input_scope分类器
     │      │   · F-45 Promise双向动作
     │      │   · F-46 Todo降噪
     │      │   · F-47 RelationshipBrief推进卡(初版)
     │      │   · F-48 RelationshipStage阶段管理(初版)
     │      │
     ?      ├─ M7: Sprint 2 — 推进卡完善 + 日视图 + Dashboard
     │      │   · F-47 推进卡完整版
     │      │   · F-48 阶段管理完整版
     │      │   · F-49 日视图 Dashboard
     │      │   · Dashboard 整合
     │      │
     ?      └─ M8: Phase 1 冻结发布 → 0.3.0
```

---

## 8. 下一步行动计划

### 📋 Sprint 0: 冻结方向 + 回归测试集（当前）

| # | 行动项 | 负责方 | 产出 | 对应变更 |
|---|--------|--------|------|---------|
| 1 | **文档更新批次2-3** | CarryMem | UI_UX_Design v2.0 + 文档交叉引用修复 | D11后续 |
| 2 | **回归测试集建立** | CarryMem | PoC现有功能的自动化测试套件 | P9前置 |
| 3 | **方向冻结评审** | 林总 | Sprint 1范围最终确认 | 进入Sprint 1的前置条件 |

### 🎯 Sprint 1: P0 五项核心实施

| # | 功能 | 优先级 | 关键交付物 | 对应设计文档 |
|---|------|--------|-----------|-------------|
| F-44 | input_scope 分类器 | P0 | `services/input_scope_classifier.py` | Algorithm_Design v2.0 |
| F-45 | Promise 双向动作 | P0 | Todo model扩展 + action_type枚举 | API_Design v2.0 + DB_Design v2.0 |
| F-46 | Todo 降噪 | P0 | `services/todo_dedup.py` | Algorithm_Design v2.0 |
| F-47 | RelationshipBrief 推进卡（初版） | P0 | `services/relationship_brief.py` + API端点 | API_Design v2.0 |
| F-48 | RelationshipStage 阶段管理（初版） | P0 | Entity model扩展 + 乐观锁PATCH | DB_Design v2.0 + API_Design v2.0 |

### 🚀 Sprint 2: 推进卡 + 日视图 + Dashboard

| # | 功能 | 优先级 | 关键交付物 |
|---|------|--------|-----------|
| F-47 | RelationshipBrief 推进卡（完整版） | P0 | 12模块画像 + 前端H5组件 |
| F-48 | RelationshipStage 阶段管理（完整版） | P0 | AI建议+阶段流转规则+前端 |
| F-49 | 日视图 Dashboard | P0额外 | GET /dashboard/day-view + today聚合 |
| — | Dashboard 整合 | P0 | 统一仪表盘入口 |

---

## 9. 风险登记册

| ID | 风险描述 | 概率 | 影响 | 应对策略 | 状态 |
|----|---------|------|------|---------|------|
| R01 | 许总对技术方案提出大幅修改意见 | 中 | 高 | 快速迭代HTML版本（已验证4轮迭代能力） | 🟡 监控中 |
| R02 | 小程序→EventLink边界接口缺口（名片JSON格式+用户映射+metadata schema） | 高 | 中 | ⚠️ 待确认（Phase1前必须补齐） | ①向许总团队获取IAMHERE名片样例JSON ②设计user_auth_mappings表 ③定义card_save metadata schema |
| R03 | LLM实体抽取准确率不达95% | 低 | 高 | spaCy降级兜底 + 人工确认机制 | 🟢 已缓解 |
| R04 | F-44~F-49 五项P0功能实施周期超预期 | 中 | 高 | Sprint拆分：Sprint 1做初版，Sprint 2完善 | 🟡 监控中 |
| R05 | UI_UX_Design更新滞后阻塞前后端联调 | 中 | 中 | 先行API契约对齐，UI并行迭代 | 🟡 监控中 |
| R06 | 许总决定不继续合作 | 低 | 极高 | 核心引擎独立于IAMHERE，可换其他数据源 | 🟢 已缓解 |

---

## 10. 当前阻塞项 (Blockers)

| ID | 阻塞描述 | 影响范围 | 缓解方案 | 目标解除时间 |
|----|---------|---------|---------|------------|
| BLK-UI | UI_UX_Design v2.0 未更新（推进卡+日视图+阶段管理交互缺失） | F-47/F-48/F-49 前端开发 | 先行API契约对齐，UI并行迭代 | Sprint 1 前 |
| BLK-DATA | IAMHERE 名片样例 JSON 未到手（影响card_save管线测试） | P8 集成测试 | 使用mock数据进行开发 | 尽早向许总索取 |
| BLK-TEST | 回归测试集未建立（无法保证批次1文档更新未引入回归） | P9 启动 | Sprint 0 优先建立 | Sprint 0 内 |

---

## 11. 决策记录 (Decision Log)

| 日期 | 决策内容 | 理由 | 影响 |
|------|---------|------|------|
| 2026-05-31 | 排除公开信息爬取作为数据来源 | 法律风险 | 竞对判断依赖网页检索+用户标注 |
| 2026-05-31 | 政府采购数据不从文档提及 | 口头沟通更灵活 | 文档只提"专业数据服务增强" |
| 2026-05-31 | 工商API第一期不做，只做网页查找 | 成本控制 | 降低初期投入，验证后再决定 |
| 2026-06-01 | 实体归一必须人工确认+可撤回 | 数据准确性不可妥协 | 增加Step 5 Human-in-the-Loop |
| 2026-06-01 | 文档去除"你/我"指派口吻 | 专业性 | 全文改为第三人称客观描述 |
| 2026-06-01 | CTA区域不含"约电话"语言 | 材料自包含 | 只保留三步骤行动指引 |
| 2026-06-03 | 许总不参与技术决策，架构设计由林总团队决定 | 许总对技术方案不感兴趣 | P2 Gate不再等许总确认 |
| 2026-06-04 | **PRD升级至v4.3** | 李总v1.2反馈+许总POC反馈+7角色Review融合 | 新增F-44~F-49五项P0功能，F-05暂停 |
| 2026-06-04 | **技术设计升级至v2.5** | 文档一致性修复 | BLK-3枚举值统一/F-49路径对齐/乐观锁完善 |
| 2026-06-04 | **7份P0设计文档批量更新至v2.0** | 配合PRD v4.3+Tech v2.5 | API/DB/Algorithm/Security/Test/Integration/Deployment全面同步 |

---

## 12. 文档索引速查

| 文档 | 路径 | 版本 | 最后更新 |
|------|------|------|---------|
| **项目状态（本文档）** | `docs/PROJECT_STATUS.md` | — | 2026-06-04 |
| 产品需求 | `docs/spec/PRD_v1.md` | v4.3 | 2026-06-04 |
| 需求索引 | `docs/spec/README.md` | — | 2026-06-04 |
| 技术设计 | `docs/architecture/EventLink_技术设计_v1.md` | v2.5 | 2026-06-04 |
| API设计 | `docs/design/API_Design_v1.md` | v2.0 | 2026-06-04 |
| 数据库设计 | `docs/design/Database_Design_v1.md` | v2.0 | 2026-06-04 |
| 算法设计 | `docs/design/Algorithm_Design_v1.md` | v2.0 | 2026-06-04 |
| 安全设计 | `docs/design/Security_Design_v1.md` | v2.0 | 2026-06-04 |
| 测试计划 | `docs/design/Test_Plan_v1.md` | v2.0 | 2026-06-04 |
| 集成设计 | `docs/design/Integration_Design_v1.md` | v2.0 | 2026-06-04 |
| 部署指南 | `docs/design/Deployment_Guide.md` | 0.2.0 | 2026-06-04 |
| UI/UX设计 | `docs/design/UI_UX_Design_v1.md` | v1.2 | 待更新 |
| LLM提示词 | `docs/design/LLM_Prompt_Templates.md` | — | — |

---

*本文档由 DevSquad 11阶段生命周期框架生成，随项目进展持续更新。*
*最后更新: 2026-06-04 (D11 批次1 P0文档完成 — 2d5dd6d)*
