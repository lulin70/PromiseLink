# PromiseLink 项目生命周期状态总览

> **更新时间**: 2026-07-03 (小程序 CI Playwright UI E2E 修复：62/62 测试 CI 通过)
> **当前阶段**: 基础版 Staging 就绪；代码完成度100%，基础版1378测试收集/1353通过/45跳过/0失败，E2E 15/0通过，专业版339测试通过，小程序62 E2E+8单元=70测试通过（CI 全绿），tsc/mypy零错误
> **产品定位**: AI驱动的个人商务关系经营助手
> **产品层级**: 基础版(本地免费) / 专业版(网关中继) / 定制版(团队)
> **负责人**: 林总 (CarryMem 团队)
> **合作方**: 许总 (IAMHERE 数字名片)

---

## 1. 总览仪表板

```
PromiseLink 项目进度
═══════════════════════════════════════════════════════════

P1  需求分析      ██████████████████████  100%  ✅ 通过 (PRD v5.2)
P2  架构设计      ██████████████████████  100%  ✅ 通过 (7角色共识82%)
P3  技术设计      ██████████████████████  100%  ✅ 通过 (v3.2, +响应式+莫兰迪色系)
P4  数据设计      ██████████████████████  100%  ✅ 通过 (v2.9, +fulfillment_status+reminder表)
P5  交互设计      ██████████████████████  100%  ✅ 通过 (v3.0, +莫兰迪色系+响应式断点)
P6  安全审查      ██████████████████████  100%  ✅ 通过 (v3.0, +50项安全测试+SECURITY.md)
P7  测试计划      ██████████████████████  100%  ✅ 通过 (Test_Plan v3.2, +42 E2E+50安全+17性能)
───────────────────────────────────────────────
P8  实施          ████████████████████░░  92%  🟢 基础版代码完成+专业版引导入口+死代码清理
P9  测试          ████████████████████░░  87%  🟢 1378测试收集/1353通过/45跳过，E2E 15/0通过，覆盖率72%
P10 部署发布      ████████████████████░░  80%  🟡 Docker配置就绪+依赖锁文件，待Staging实部署
P11 运维保障      █████████████░░░░░░░░░  60%  🟡 Prometheus端点已实现，Grafana待配置+无实战运维

═════════════════════════════════════════════════════════════
总体进度: ████████████████████████░░  87% (代码完成度100%，测试1378收集/1353通过，E2E 15/0，成熟度87/100，Phase 1-3 Staging修复完成)

✅ P0-P2阻断项已修复（2026-06-21 v0.6.6）:
  1. ✅ 前端补齐专业版引导入口（侧边栏底部引导卡片）
  2. ✅ poc_secret改用sessionStorage（关闭标签页即清除）
  3. ✅ PoC登录端点加环境检查（生产环境拒绝默认密码）
  4. ✅ 添加依赖锁文件requirements.lock（232行）
  5. ✅ 测试数文档统一为1353（README/CHANGELOG/PROJECT_STATUS一致）
  6. ✅ 删除config.py死配置（ASR/TTS/OCR、Email、Privacy共13字段）
  7. ✅ 删除schemas死Schema（ImportCSVResponse、TTSFallbackResponse）
  8. ✅ 删除6处skip测试（627行死代码）
  9. ✅ 删除前端admin/usage仪表盘（Pro专属功能）
  10. ✅ 删除demo_for_xu.py（导入已删除模块）

分阶段真实进度（三级产品模型）:
  PoC    代码████████████████████ 100%  部署██████████████████ 100%  综合 100%  ← E2E验证通过
  基础版 代码████████████████████ 100%  部署████████████████░░  87%  综合  87%  ← Phase 1-3 Staging修复，tsc/mypy零错误，1378测试收集/1353通过，E2E 15/0
  专业版 代码████████████████████ 100%  部署████████████████░░  85%  综合  85%  ← gateway+pro_api+pro_services+pro_models完整，339测试通过，14路由挂载
  定制版 代码░░░░░░░░░░░░░░░░░░   0%  部署░░░░░░░░░░░░░░░░░░   0%  综合   0%  ← 未启动

最新Commit: Phase 1-3 Staging修复 (E2E链路+PromptInjection硬约束+CI timeout+UUIDStr+三语README+Dockerfile LABEL)
下一里程碑: 配置STAGING secrets → Staging实部署 → 内部灰度(许总+5-10熟人) → 修到90+ → 公开repo+产品发布
```

### Phase 1-3 Staging 修复记录 (2026-07-01 v0.7.0)

**Phase 1: E2E 失败链路修复**
- Phase 1.1: 5个E2E脚本非UUID user_id修复 (commit 5786d90)
- Phase 1.2: datetime timezone迁移(27列) + UUIDStr响应模型(44字段/14文件) (commits 2b7abbe/ebd1012/7dc936b/3590f5f/852a85d)
- Phase 1.3: 移除e2e job continue-on-error + e2e_basic_test `|| true` (commit ed0ef75)
- 结果: E2E basic test 15/0通过 ✅

**Phase 2: Prompt Injection 安全硬约束**
- 新增 PromptInjectionError(LLMError) 异常类 (commit 387ebc4)
- sanitize_llm_input 从strip改为raise，命中注入模式即阻断LLM调用
- LLMClient.call()/generate() 入口统一sanitize闸口
- 5个安全测试从strip断言改为pytest.raises(PromptInjectionError)断言
- 结果: CI test job通过 ✅

**Phase 3: CI/CD 硬约束**
- 7个CI job全部补timeout-minutes (test:20/e2e:15/e2e-nightly:30/frontend:10/security:10/build-and-push:15/deploy-staging:10) (commit ed0ef75)
- 移除e2e-nightly e2e_basic_test的`|| true`掩盖
- 待办: 用户需配置STAGING_SSH_KEY/STAGING_HOST secrets

**Phase 4: 文档硬约束**
- Dockerfile添加ARG VERSION + OCI标准LABEL
- requirements.lock清理: 移除opc-agents本地路径依赖(硬约束违规) + 124个非项目依赖
- 创建README.en.md/README.jp.md三语对齐
- 更新PROJECT_STATUS.md到v0.7.0

---

## 2. 7维度成熟度评分 (2026-07-01 v0.7.0 Phase 1-3 Staging修复后)

> **评分变更说明**: 2026-06-17 旧评分 92/100 → 2026-06-21 走读后 78/100 → v0.6.6 P0-P2修复后 85/100 → v0.7.0 Phase 1-3 Staging修复后 87/100。E2E链路修复+PromptInjection硬约束+CI/CD加固+文档对齐。

| 维度 | 走读后评分 | v0.6.6修复后 | v0.7.0修复后 | 等级 | 修复内容 |
|------|-----------|-------------|-------------|------|----------|
| 架构 | 80 | 82 | 84 | B+ | UUIDStr类型统一PostgreSQL/SQLite响应模型 |
| 安全 | 75 | 82 | 88 | B+ | PromptInjectionError硬约束+LLMClient入口闸口+sanitize raise |
| 测试 | 78 | 85 | 87 | B+ | E2E 15/0通过+UUIDStr修复500错误+移除continue-on-error掩盖 |
| PM | 80 | 85 | 85 | B | 专业版引导入口已添加（硬约束达成） |
| 开发 | 80 | 85 | 85 | B | config.py死配置清理 + schemas死Schema清理 |
| DevOps | 75 | 80 | 86 | B+ | 7个CI job补timeout-minutes+requirements.lock清理本地路径 |
| UI | 72 | 82 | 82 | B | 专业版引导入口 + admin/usage仪表盘清理 |
| **综合** | **78** | **85** | **87** | **B+** | **Phase 1-3 Staging修复完成，E2E/安全/CI-CD硬约束达成** |

---

## 2. 版本信息

| 维度 | 版本 | 说明 |
|------|------|------|
| **PRD** | v5.7 | F-67关系推进卡前端对接+F-68 Promise兑现状态追踪+F-69智能跟进提醒+增强F-45/F-50+§5.18录入页五类纠偏+§1.5.6a三仓库独立策略 |
| **技术设计** | v3.2 | +§4.13 F-67关系推进卡+§4.14 F-68兑现追踪+§4.15 F-69智能提醒 |
| **软件版本** | 0.7.0 | Phase 1-3 Staging修复：E2E链路+PromptInjection硬约束+CI/CD timeout+三语README+Dockerfile LABEL+requirements.lock清理 |
| **API_Design** | v3.1 | +承诺看板API+兑现状态API+提醒API+提醒偏好API |
| **Database_Design** | v3.0 | +三级产品模型+relay_connections+ai_usage_logs+基础版/专业版/定制版 |
| **Algorithm_Design** | v2.8 | DependencyAnalyzer+ContextMatcher+SemanticSearch+PriorityScorerV2+关联发现增强 |
| **Security_Design** | v3.1 | +F-68兑现追踪安全约束+F-69提醒安全约束+their_promise手动标记+催促话术边界 |
| **Test_Plan** | v5.1 | +53新测试用例(F-67:10+F-68:20+F-69:16+E2E:3+安全:4) |
| **Integration_Design** | v2.9 | 托管PoC+数字名片对接决策+语义搜索集成+关联发现增强+DataSourceAdapter集成+邮件场景+Media服务集成 |
| **Deployment_Guide** | v0.5.0 | 向量存储部署+sqlite-vec+pgcrypto+Adapter同步+监控指标+Rate Limiting配置 |
| **UI_UX_Design** | v3.1 | +关系推进卡页面+承诺看板双视图+每日提醒页面 |
| **LLM_Prompt_Templates** | 0.4.1 | 语义搜索模板(24)+concern/capability提取(22)+Event标题生成(23) |

### 设计文档更新状态

| 文档 | 目标版本 | 状态 | 关键变更 |
|------|---------|------|---------|
| API_Design_v1.md | v3.1 | ✅ 完成 | Semantic Search API+Insight Engine API+DataSourceAdapter API+Media API+Privacy API+前端集成API |
| Database_Design_v1.md | v3.0 | ✅ 完成 | 三级产品模型+relay_connections+ai_usage_logs+基础版/专业版/定制版术语替换 |
| Algorithm_Design_v1.md | v2.8 | ✅ 完成 | DependencyAnalyzer+ContextMatcher+SemanticSearch+关联发现增强 |
| Security_Design_v1.md | v3.1 | ✅ 完成 | 向量数据安全(§6.12)+语义搜索安全(§6.13)+Insight安全+Adapter安全+Rate Limiting+前端安全 |
| Test_Plan_v1.md | v5.1 | ✅ 完成 | 托管PoC部署验证(5用例)+名片扫描PoC备注+23个新测试用例+Media+Privacy+Rate Limiting |
| Integration_Design_v1.md | v2.9 | ✅ 完成 | 托管PoC+数字名片对接决策+语义搜索集成+关联发现增强+DataSourceAdapter集成+Media服务集成 |
| Deployment_Guide.md | v0.5.0 | ✅ 完成 | 向量存储部署+sqlite-vec+pgcrypto+监控指标+Rate Limiting配置+托管PoC部署+nginx+HTTPS |
| UI_UX_Design_v1.md | v3.1 | ✅ 完成 | 语义搜索UI+依赖性展示+场景匹配+动态优先级+小程序前端集成 |
| LLM_Prompt_Templates.md | 0.4.1 | ✅ 完成 | 语义搜索模板(24)+concern/capability提取(22)+Event标题生成(23) |

## 2.5 智能演进路线图（v4.5新增）

> **设计背景**：基于与DeepSeek的架构讨论，明确PromiseLink从"被动记录"到"主动服务"的智能演进路径。

### 二维起步、四维演进

| 阶段 | 优先级排序维度 | 反馈机制 | 数据接入 | 关联发现 |
|------|--------------|---------|---------|---------|
| **PoC** | 二维(紧急性+重要性) | 完成顺序隐式反馈 | 手动+语音 | 6种结构化+3种冷类型 |
| **基础版** | 四维(+依赖性+场景) | +长按降权主动反馈 | +邮件+微信转发 | +依赖性分析 |
| **专业版** | 上下文感知推送 | +滑动手势(需原生APP) | +日历同步 | +图数据库+向量搜索 |
| **定制版** | 团队协同优先级 | +团队共享反馈 | +CRM集成 | +跨用户关联发现 |

### 核心架构决策

| 决策 | 选择 | 理由 |
|------|------|------|
| 实体提取粒度 | 强化Person的concern/capability字段 | 不扩展实体类型，成本可控，关联精度更高 |
| 向量化匹配 | 基础版已实现(F-57/F-58) | 本地all-MiniLM-L6-v2(384维)+API降级，sqlite-vec+Python余弦降级 |
| 反馈机制 | 隐式优先(完成顺序) | 零额外交互，零认知负担 |
| 数据接入 | 降低输入摩擦优先于自动抓取 | 微信生态约束+用户信任考量 |
| 邮件设计 | 原子事件+溯源边 | Event存全文，Todo存原子承诺，source_event_id链回 |
| 动态优先级 | 基础版四维: 0.3×紧急性+0.35×重要性+0.2×依赖性+0.15×场景 | PoC二维→基础版四维，依赖性+场景匹配增强 |

### 智能验证指标（PoC新增）

| 指标 | 目标 | 说明 |
|------|------|------|
| 动态排序与静态排序的差异度 | ≥30% | 证明动态排序有实际价值 |
| 高优先级Todo完成率 | ≥60% | 证明排序准确 |
| 隐式反馈学习效果 | 7天内权重调整可见 | 证明学习机制有效 |
| concern/capability提取准确率 | ≥70% | 证明强化提取有效 |

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
| F-51 | 动态优先级排序 | `services/priority_scorer.py` | ✅ PoC | 二维模型(紧急性+重要性) |
| F-52 | 隐式反馈学习 | `services/implicit_feedback.py` | ✅ PoC | 完成顺序→关系权重调整 |
| F-53 | concern/capability强化提取 | `prompts/entity_extraction.py` | ✅ PoC | 受控词表+自由文本混合模式 |
| F-54 | 数据接入层架构 | `services/data_source_adapter.py` | ✅ PoC | DataSourceAdapter接口定义 |

### 基础版 已完成功能

| # | 功能模块 | 实现文件 | 状态 | 说明 |
|---|---------|---------|------|------|
| F-55 | 依赖性全图谱路径分析 | `services/dependency_analyzer.py` | ✅ Phase1 | BFS阻塞链检测，MAX_DEPTH=3 |
| F-56 | 场景匹配Event表驱动 | `services/context_matcher.py` | ✅ Phase1 | 24h窗口，meeting/call场景触发 |
| F-57 | 语义搜索 | `services/embedding_provider.py` + `services/semantic_search.py` | ✅ Phase1 | 三级降级(API→本地→hash)，384维all-MiniLM-L6-v2 |
| F-58 | 关联发现增强 | `services/association_discovery.py` | ✅ Phase1 | 混合得分0.7×structured+0.3×semantic，阈值0.7 |
| — | PriorityScorerV2 | `services/priority_scorer.py` | ✅ Phase1 | 四维评分(紧急性+重要性+依赖性+场景) |
| F-21 | 数据导出API | `api/v1/export.py` | ✅ Phase1 | 用户数据可携带，JSON全量导出 |
| F-36 | 需求录入API | `api/v1/demand_input.py` | ✅ Phase1 | 语音/文字一句话录入需求，LLM+关键词fallback |
| F-39 | 资源透支提醒 | `services/resource_overuse_detector.py` | ✅ Phase1 | 30天3次索取触发warning，Pipeline Step06 |
| F-64 | API Rate Limiting | `core/rate_limiter.py` + `api/v1/dependencies.py` | ✅ Phase1 | 语音/媒体/标准端点分级限流 |
| F-65 | Pipeline Step类重构 | `services/steps/` | ✅ Phase1 | 13个Step类，event_pipeline.py 728→227行 |
| F-66 | 安全修复 | `core/auth.py` + `config.py` | ✅ Phase1 | poc_secret登录+get_current_user_id+动态salt+poc_anonymous_access配置 |
| — | relay_client | `services/relay_client.py` + `relay_endpoints.py` + `relay_models.py` | ✅ Phase1 | 基础版连接专业版网关的桥接客户端 |

### 专业版 已完成功能（独立仓库 PromiseLink-Pro）

> 专业版功能已物理迁移至独立仓库 `PromiseLink-Pro`，包含 `gateway/`、`pro_api/`、`pro_services/`、`pro_models/` 四个包。
> 基础版通过 `relay_client` 可选连接专业版网关使用以下功能（需专业版 License）。

| # | 功能模块 | 实现文件 (PromiseLink-Pro) | 状态 | 说明 |
|---|---------|---------|------|------|
| F-08 | CSV导入API | `pro_api/import_csv.py` | ✅ Pro | 冷启动数据导入，UTF-8/GBK，EntityResolution归一 |
| F-50 | 语音助手查询 | `pro_api/voice_query.py` + `pro_services/voice_query_service.py` | ✅ Pro | 日程查询/承诺追踪/关系推进3类查询指令 |
| — | 邮件EmailAdapter | `pro_services/email_adapter.py` + `pro_api/email_sync.py` | ✅ Pro | IMAP连接+邮件解析为Event+Pipeline触发 |
| — | 微信转发Adapter | `pro_services/wechat_forward_adapter.py` + `pro_api/wechat_forward.py` | ✅ Pro | 聊天记录解析为Event，支持群聊/单聊 |
| F-59 | ASR语音识别服务 | `pro_services/asr_service.py` | ✅ Pro | 语音转文字，支持多Provider配置 |
| F-60 | TTS语音合成服务 | `pro_services/tts_service.py` | ✅ Pro | 文字转语音，支持多Provider配置 |
| F-61 | OCR文字识别服务 | `pro_services/ocr_service.py` | ✅ Pro | 图片文字识别，支持名片/文档场景 |
| F-62 | Media API | `pro_api/media.py` | ✅ Pro | 4端点: /media/asr, /media/tts, /media/ocr, /media/ocr-event |
| F-63 | Privacy API | `pro_api/privacy.py` | ✅ Pro | 3端点: /privacy/data-summary, /privacy/user-data, /privacy/export |
| — | Gateway | `gateway/main.py` | ✅ Pro | 中继网关，挂载14个pro-api路由，admin API + relay API |

### Pipeline 状态（13步完整实现）

```
Step01  Verify + Input scope分类(F-44) + Title生成  ✅  meeting(0.95规则, <1ms)
Step02  Entity extraction + resolution               ✅  LLM NER + concern/capability强化提取 + 5步归一
Step03  Entity embedding(F-57)                       ✅  本地all-MiniLM-L6-v2, 384维, API降级
Step04  Todo generation                              ✅  LLM生成+降噪(F-46:5→3条)
Step05  Promise双向分析(F-45)                        ✅  my_promise+my_followup+their_promise
Step06  资源透支检测(F-39)                           ✅  30天3次索取触发warning Todo
Step07  四维优先级评分(F-55/56)                      ✅  PriorityScorerV2: 紧急性+重要性+依赖性+场景
Step08  Notification                                 ⚠️  微信未配置(跳过)
Step09  Memory store                                 ✅  NullMemory(跳过)
Step10  Association discovery                        ✅  增量发现+冷类型持久化+语义增强(F-58)
Step11  关联→Todo生成                                ✅  关联发现后自动创建行动Todo
Step12  Brief更新(F-47+F-48)                        ✅  8模块更新+evidence属性修复
Step13  标记completed                                ✅

E2E验证: 53.5s | 7/7 PASS | Moka AI真实调用 | Embedding 5条写入(384维)
Demo验证: 4/4场景全通过 | NLU 100%(7/7) | 1224测试, 0 skip, 73%覆盖率
```

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
PromiseLink/
├── docs/
│   ├── spec/                         # 📝 需求规格
│   │   ├── PRD_v1.md                 # PRD v5.2
│   │   ├── PRD_v1_review_report.md   # PRD审核报告
│   │   └── README.md                 # spec索引
│   │
│   ├── architecture/                 # 🏗️ 架构设计
│   │   └── PromiseLink_技术设计_v1.md   # 技术设计 v3.2
│   │
│   ├── design/                       # 🎨 详细设计
│   │   ├── README.md                 # 设计文档索引
│   │   ├── API_Design_v1.md          # API设计 v3.1 ✅
│   │   ├── Algorithm_Design_v1.md    # 算法设计 v2.8 ✅
│   │   ├── Database_Design_v1.md     # 数据库设计 v3.0 ✅
│   │   ├── Integration_Design_v1.md  # 集成设计 v2.9 ✅
│   │   ├── Security_Design_v1.md     # 安全设计 v3.1 ✅
│   │   ├── Test_Plan_v1.md           # 测试计划 v5.1 ✅
│   │   ├── UI_UX_Design_v1.md        # UI/UX设计 v3.1 ✅
│   │   ├── Deployment_Guide.md       # 部署指南 v0.5.0 ✅
│   │   └── LLM_Prompt_Templates.md   # LLM提示词模板 0.4.1 ✅
│   │
│   ├── external/
│   │   ├── for_许总/                  # 📤 对外交付物
│   │   │   └── (会议纪要、交流记录等)
│   │   ├── for_李总/                  # 📤 对外交付物
│   │   │   └── PromiseLink_产品核心价值升级建议_资源匹配供给与维护版.md
│   │   └── for_team/                 # 📋 团队共享文档
│   │       ├── PromiseLink_最终总结报告.md
│   │       ├── PromiseLink_分工模型V2.1_修正版.md
│   │       ├── PromiseLink_POC准备度评估报告.md
│   │       └── PromiseLink_一页纸方案_V2_精简版.md
│   │
│   ├── deliverables/                 # 📦 交付物清单
│   │   ├── PROJECT_STRUCTURE.md
│   │   └── README_SETUP.md
│   │
│   └── DOCUMENTATION_CHECKLIST.md    # 📋 文档检查清单
│
├── src/promiselink/                    # 💻 源代码（基础版，专业版见独立仓库 PromiseLink-Pro）
│   ├── main.py                       # FastAPI应用入口
│   ├── config.py                     # 配置管理
│   ├── database.py                   # 数据库连接（SQLite+PG异步）
│   │
│   ├── models/                       # 数据模型（8个文件，10个模型类）
│   │   ├── event.py                  # Event模型
│   │   ├── entity.py                 # Entity模型
│   │   ├── association.py            # Association模型
│   │   ├── todo.py                   # Todo模型
│   │   ├── relationship_brief.py     # RelationshipBrief模型
│   │   ├── reminder.py               # Reminder模型
│   │   ├── scheduled_event.py        # ScheduledEvent模型
│   │   └── score_audit_log.py        # ScoreAuditLog模型
│   │   # 注：voice_session.py 已迁移至 PromiseLink-Pro/pro_models/
│   │
│   ├── api/v1/                       # REST API（15个路由模块）
│   │   ├── events.py                 # POST/GET/DELETE /events
│   │   ├── entities.py               # GET /entities + 信用/阶段
│   │   ├── associations.py           # GET /associations
│   │   ├── todos.py                  # GET/POST/PATCH /todos
│   │   ├── auth.py                   # JWT认证端点
│   │   ├── health.py                 # 健康检查
│   │   ├── schemas.py                # Pydantic请求/响应模型
│   │   ├── dashboard.py              # Dashboard API入口
│   │   ├── dashboard_day_view.py     # 日视图Dashboard
│   │   ├── dashboard_morning_brief.py # 晨报Dashboard
│   │   ├── dashboard_range_view.py   # 范围视图Dashboard
│   │   ├── dashboard_relationship_health.py # 关系健康Dashboard
│   │   ├── dashboard_supply_demand.py # 供需Dashboard
│   │   ├── demand_input.py           # 需求录入API
│   │   ├── event_pipeline_api.py     # 事件管线API
│   │   ├── event_search_api.py       # 事件搜索API
│   │   ├── export.py                 # 数据导出API
│   │   ├── promises.py               # 承诺API
│   │   ├── relationship_briefs.py    # 关系推进卡API
│   │   ├── reminders.py              # 提醒API
│   │   ├── scheduled_events.py       # 预定事件API
│   │   ├── entities_credit.py        # 实体信用API
│   │   ├── entities_stages.py        # 实体阶段API
│   │   └── metrics.py                # 指标API
│   │   # 注：media/privacy/email_sync/wechat_forward/voice/voice_query/import_csv
│   │   #      已迁移至 PromiseLink-Pro/pro_api/
│   │
│   ├── services/                     # 核心业务逻辑（基础版保留模块）
│   │   ├── event_pipeline.py         # 事件处理管线(728→227行重构)
│   │   ├── steps/                    # Pipeline Step类(13个Step)
│   │   ├── entity_extractor.py       # LLM实体抽取
│   │   ├── entity_resolution.py      # 实体归一引擎（5步算法）
│   │   ├── association_discovery.py  # 关联发现引擎
│   │   ├── association_graph.py      # 关联图谱
│   │   ├── association_matcher.py   # 关联匹配
│   │   ├── association_scoring.py    # 关联评分
│   │   ├── promise_fulfillment.py    # 商机匹配器
│   │   ├── todo_generator.py         # Todo生成器
│   │   ├── todo_state_machine.py     # Todo状态机
│   │   ├── llm_client.py             # LLM客户端封装
│   │   ├── memory_provider.py        # CarryMem记忆层适配
│   │   ├── notification_service.py   # 通知服务
│   │   ├── context_matcher.py        # 场景匹配引擎
│   │   ├── dependency_analyzer.py    # 依赖性全图谱路径分析
│   │   ├── embedding_provider.py     # 向量嵌入提供者
│   │   ├── semantic_search.py        # 语义搜索引擎
│   │   ├── implicit_feedback.py      # 隐式反馈学习
│   │   ├── input_scope_classifier.py # Input scope分类器
│   │   ├── priority_scorer.py        # 动态优先级评分器
│   │   ├── promise_bidirectional.py  # Promise双向分析
│   │   ├── relationship_brief_service.py # 关系推进卡服务
│   │   ├── relationship_stage.py     # 关系阶段管理
│   │   ├── resource_overuse_detector.py # 资源透支检测
│   │   ├── todo_deduplicator.py      # Todo去重降噪
│   │   ├── data_source_adapter.py    # 数据接入层适配器
│   │   ├── relay_client.py           # 专业版网桥接客户端
│   │   ├── relay_endpoints.py        # Relay API端点
│   │   ├── relay_models.py           # Relay数据模型
│   │   ├── entity_cleanup.py         # 实体清理
│   │   ├── health_diagnostic.py      # 健康诊断
│   │   ├── dormant_scanner.py        # 休眠扫描
│   │   ├── credit_score.py           # 信用评分
│   │   ├── nudge_generator.py        # 轻推生成
│   │   └── title_generator.py        # 标题生成
│   │   # 注：asr/tts/ocr/email_adapter/wechat_forward_adapter/voice_query_service/
│   │   #      nlg_service/nlu_intent_classifier 已迁移至 PromiseLink-Pro/pro_services/
│   │
│   ├── core/                         # 基础设施
│   │   ├── auth.py                   # JWT工具函数
│   │   ├── crypto.py                 # 加密/PII脱敏
│   │   ├── redis.py                  # Redis缓存客户端
│   │   ├── rate_limiter.py           # API Rate Limiting
│   │   ├── text_utils.py             # 文本处理工具
│   │   ├── metrics.py                # 指标
│   │   ├── natural_date.py           # 自然语言日期
│   │   ├── file_utils.py             # 文件工具
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
│   ├── ops/                          # 运维脚本
│   │   ├── deploy-staging.sh         # 部署脚本
│   │   ├── backup.sh                 # 备份脚本
│   │   └── backup-cron               # 备份cron配置
│   ├── run_review.py                 # DevSquad Mock模式评审
│   ├── run_review_real_ai.py         # DevSquad 真实AI模式评审
│   ├── e2e_sprint0_pipeline.py      # E2E Pipeline验证 (真实Moka AI)
│   ├── e2e_user_journey.py           # E2E 用户旅程测试
│   ├── e2e_realistic_scenario.py     # E2E 真实场景测试
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
| 需求差距分析已完成 | ✅ 完成 | `docs/internal/PromiseLink_产品设计讨论报告.md` | 47个问题，7维度 |
| AI多角色评审已完成 | ✅ 完成 | `docs/internal/PromiseLink_DevSquad_真实AI评审报告.md` | 7角色，真实API |
| 执行摘要已产出 | ✅ 完成 | `docs/external/for_team/PromiseLink_最终总结报告.md` | Top12问题，可行性7.0/10 |
| 合作方需求已整合 | ✅ 完成 | `docs/internal/PromiseLink_产品架构V2_数字名片整合方案.md` | 数字名片+动态采集整合 |
| **需求量化验收标准** | ✅ 完成 | `docs/spec/PRD_v1.md` (**v4.9**) | 152处量化指标，66项功能（F-01~F-66），含托管PoC+数字名片决策+智能定义+动态优先级+数据接入层+Media架构 |

**P1 Gate 判定**: **✅ 通过** — PRD v4.9已完成，7角色审核共识达成，产品定位演化为"AI驱动的个人商务关系经营助手"，智能定义与边界确立，托管PoC部署模式+数字名片对接决策明确。

---

### P2: 架构设计 (Architecture Design)

| 检查项 | 状态 | 证据文档 | 备注 |
|------|------|---------|------|
| 三层架构模型已定义 | ✅ 完成 | `docs/internal/PromiseLink_技术方案V3_技术版.md` | L1入口→L2标准化→L3引擎 |
| 分工边界已明确 | ✅ 完成 | `docs/external/for_team/PromiseLink_分工模型V2.1_修正版.md` | 应用层(许总) / 引擎层(CarryMem) |
| 技术栈选型已完成 | ✅ 完成 | 技术方案V3 | FastAPI+SQLite(个人版长期)+NetworkX |
| 数据流图已绘制 | ✅ 完成 | 技术设计v2.8 §2 | 含HTTP API调用关系+H5内嵌方案+Insight Engine+Media服务 |
| 多角色共识达成 | ✅ 完成 | 7角色架构评审（加权共识82%） | 许总不参与技术决策 |

**P2 Gate 判定**: **✅ 通过** — 7角色架构评审加权共识82%（≥70%门槛）。

---

### P3: 技术设计 (Technical Design)

| 检查项 | 状态 | 证据文档 | 备注 |
|------|------|---------|------|
| API接口规范已定义 | ✅ 完成 | `docs/design/API_Design_v1.md` (**v2.8**) | Insight Engine API+DataSourceAdapter API+Media API+Privacy API+Todo扩展 |
| 核心数据模型已定义 | ✅ 完成 | `docs/design/Database_Design_v1.md` (**v2.8**) | 3新字段+审计表+adapter_configs |
| 核心算法流程已定义 | ✅ 完成 | `docs/design/Algorithm_Design_v1.md` (**v2.8**) | PriorityScorer+ImplicitFeedbackCollector+concern解析 |
| 实体归一含人工确认+撤回 | ✅ 完成 | Algorithm_Design + 代码实现 | Human-in-the-Loop + Rollback |
| 接口版本管理策略 | ✅ 完成 | API_Design v2.9 | 三层SemVer+废弃流程+Alembic |
| **技术设计v2.8** | ✅ 完成 | `docs/architecture/PromiseLink_技术设计_v1.md` | Insight Engine+DataSourceAdapter+动态评分+邮件场景+Media服务+Rate Limiting |

**P3 Gate 判定**: **✅ 通过** — 技术设计v2.9完整，9份详细设计文档已更新至v2.9/v3.0/v0.4.8/v2.5。

---

### P4: 数据设计 (Data Design)

| 检查项 | 状态 | 证据文档 | 备注 |
|------|------|---------|------|
| 核心数据结构已定义 | ✅ 完成 | `docs/design/Database_Design_v1.md` (**v2.8**) | Event/Entity/Association/Todo + 动态评分字段+审计表 |
| 字段级加密策略 | ✅ 完成 | `docs/design/Security_Design_v1.md` (**v2.8**) | AES-256-GCM + PII检测正则 + Concern数据保护 |
| JSONB使用策略 | ✅ 完成 | Database_Design v2.8 | PostgreSQL 15, metadata灵活扩展 |
| 图数据存储方案 | ✅ 完成 | Database_Design v2.8 | NetworkX + igraph |
| Alembic迁移就绪 | ✅ 完成 | `src/promiselink/alembic/` | 初始schema迁移脚本 |
| **3NF或反范式化论证** | ✅ 完成 | Database_Design v2.8 | 实用主义优先 |

**P4 Gate 判定**: **✅ 通过** — Database_Design v2.8完成，含完整ER图与动态评分字段+审计表。

---

### P5: 交互设计 (Interaction Design)

| 检查项 | 状态 | 证据文档 | 备注 |
|------|------|---------|------|
| 对外交付物已就绪 | ✅ 完成 | `docs/external/for_许总/PromiseLink_技术方案V3_网页版.html` | 富文本HTML |
| H5页面方案已定义 | ✅ 完成 | 技术设计v2.8 §2.1 | WebView内嵌方案 |
| UI/UX设计稿 | ✅ 完成 | `docs/design/UI_UX_Design_v1.md` (v2.3) | 动态优先级排序UI+隐式反馈UI+关注与能力展示 |

**P5 Gate 判定**: **✅ 通过** — 对外交付物已完成，UI/UX设计已更新至v2.5（动态优先级+隐式反馈+关注与能力+小程序前端集成）。

---

### P6: 安全审查 (Security Review)

| 检查项 | 状态 | 证据文档 | 备注 |
|------|------|---------|------|
| 传输加密 | ✅ 完成 | `docs/design/Security_Design_v1.md` (**v2.8**) | TLS 1.3 + HSTS |
| 身份认证 | ✅ 完成 | Security_Design v2.9 + 代码实现 | JWT HS256 (access:15min, refresh:7d) + poc_secret登录 |
| 权限控制 | ✅ 完成 | Security_Design v2.9 | JWT认证 + 单用户数据隔离 + get_current_user_id |
| 数据加密 | ✅ 完成 | Security_Design v2.9 + `core/crypto.py` | AES-256-GCM 字段级 + 动态salt |
| PII脱敏 | ✅ 完成 | Security_Design v2.9 §3.6 | 6种PII检测正则 + redact_pii_from_text() |
| SC-01输入分类越权防护 | ✅ 完成 | Security_Design v2.9 §5.6 | input_scope服务端强制校验 |
| STRIDE威胁模型 | ✅ 完成 | Security_Design v2.9 §1.2 | 6类标准分类+实施状态追踪 |
| 审计日志 | ✅ 完成 | Security_Design v2.9 | 全写操作记录 |
| API Rate Limiting | ✅ 完成 | Security_Design v2.9 + `core/rate_limiter.py` | 语音/媒体/标准端点分级限流 |
| **无P0/P1漏洞** | ⚠️ 设计层面 | Security_Design v2.9 | P9阶段补充渗透测试 |

**P6 Gate 判定**: **✅ 通过（设计阶段v3.0+验证通过）** — Insight安全(§6.7)+Adapter安全(§6.8)+Concern数据保护(§6.9)+Rate Limiting安全覆盖全面，安全检查8/8通过。

---

### P7: 测试计划 (Test Planning)

| 检查项 | 状态 | 证据文档 | 备注 |
|------|------|---------|------|
| PoC验证计划已制定 | ✅ 完成 | `docs/design/Test_Plan_v1.md` (**v4.9**) | 参考PRD v4.9/技术设计v2.8 |
| Week1准入标准 | ✅ 完成 | Test_Plan v2.8 | 20张名片解析>95%, 延迟<200ms |
| Week2准入标准 | ✅ 完成 | Test_Plan v2.8 | Precision@5>70%, Recall@10>60%, F1>0.65 |
| Week3准入标准 | ✅ 完成 | Test_Plan v2.8 | E2E延迟<10s, 可录屏Demo |
| E2E测试要求 | ✅ 完成 | Test_Plan v2.8 | 含模拟真实用户使用的E2E测试 |
| P0功能验证用例 | ✅ 完成 | Test_Plan v2.8 | F-44~F-66专项测试用例+Media+Privacy+Rate Limiting测试 |

**P7 Gate 判定**: **✅ 通过** — Test_Plan v4.9已全面刷新，含P0功能+E2E+安全+Insight Engine+Media+Privacy+Rate Limiting+前端集成测试。

---

### P8: 实施阶段 (Implementation) — 当前重点

| 检查项 | 状态 | 证据 | 备注 |
|------|------|------|------|
| 开发环境搭建 | ✅ 完成 | `pyproject.toml`, `requirements.txt`, `Dockerfile` | FastAPI项目脚手架 |
| Event接入API | ✅ 完成 | `src/promiselink/api/v1/events.py` | POST/GET/DELETE /api/v1/events |
| Entity API | ✅ 完成 | `src/promiselink/api/v1/entities.py` | GET /api/v1/entities |
| Association API | ✅ 完成 | `src/promiselink/api/v1/associations.py` | GET /api/v1/associations |
| Todo API | ✅ 完成 | `src/promiselink/api/v1/todos.py` | GET/POST/PATCH /api/v1/todos |
| Auth API (JWT) | ✅ 完成 | `src/promiselink/api/v1/auth.py` + `core/auth.py` | JWT认证端点 |
| Health API | ✅ 完成 | `src/promiselink/api/v1/health.py` | 基础+数据库健康检查 |
| 数据库模型 | ✅ 完成 | `src/promiselink/models/` 9个文件 | Event/Entity/Association/Todo/RelationshipBrief/VoiceSession/Reminder/ScoreAuditLog |
| 数据库连接 | ✅ 完成 | `src/promiselink/database.py` | SQLite+PostgreSQL异步支持 |
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
| Alembic迁移 | ✅ 完成 | `src/promiselink/alembic/` | 初始schema |
| Pydantic Schema | ✅ 完成 | `api/v1/schemas.py` | 请求/响应模型 |
| Docker配置 | ✅ 完成 | `docker-compose.yml` | SQLite/PostgreSQL/Redis三种配置 |
| **F-44 input_scope分类器** | ✅ 完成 | `services/input_scope_classifier.py` + 规则缓存 | Algorithm_Design v2.0 |
| **F-45 Promise双向动作** | ✅ 完成 | Todo model扩展 + action_type枚举 + LLM fallback | API_Design v2.0 + DB_Design v2.0 |
| **F-46 Todo降噪** | ✅ 完成 | `services/todo_dedup.py` + DB级删除(pending_deletions) | Algorithm_Design v2.0 |
| **F-47 RelationshipBrief推进卡** | ✅ 完成 | 12模块BriefService + API聚合视图 + 乐观锁 | API_Design v2.0 |
| **F-48 RelationshipStage阶段** | ✅ 完成 | 7阶段状态机 + STAGE_TRANSITIONS + RS-01确认 | DB_Design v2.0 + API_Design v2.0 |
| **F-49 日视图Dashboard** | ✅ 完成 | GET /dashboard/day-view + 自然语言日期解析(中英文) | API_Design v2.0 |
| **F-50 智能语音助手** | ✅ Pro | (Pro) NLU两阶段分类器(9意图) + VoiceSession 3表 + Voice API | Algorithm_Design v2.0 + Integration_Design v2.0 |
| **F-51 动态优先级排序** | ✅ 完成 | PriorityScorer二维模型(紧急性+重要性) | Algorithm_Design v2.8 + API_Design v2.9 |
| **F-52 隐式反馈学习** | ✅ 完成 | ImplicitFeedbackCollector(完成顺序→权重调整) | Algorithm_Design v2.8 + Database_Design v2.8 |
| **F-53 concern/capability强化提取** | ✅ 完成 | 受控词表+自由文本混合模式 | Algorithm_Design v2.8 + LLM_Prompt_Templates 0.4.1 |
| **F-54 数据接入层架构** | ✅ 完成 | DataSourceAdapter接口+邮件场景+微信约束 | Integration_Design v2.8 + API_Design v2.9 |
| **F-55 依赖性全图谱路径分析** | ✅ 完成 | DependencyAnalyzer(BFS阻塞链+3跳间接依赖) | Algorithm_Design v2.8 + Tech v2.8 |
| **F-56 场景匹配Event表驱动** | ✅ 完成 | ContextMatcher(24h窗口+线性衰减) | Algorithm_Design v2.8 + Tech v2.8 |
| **F-59 ASR语音识别服务** | ✅ Pro | (Pro) `pro_services/asr_service.py` + asr_provider配置 | Integration_Design v2.8 |
| **F-60 TTS语音合成服务** | ✅ Pro | (Pro) `pro_services/tts_service.py` + tts_provider配置 | Integration_Design v2.8 |
| **F-61 OCR文字识别服务** | ✅ Pro | (Pro) `pro_services/ocr_service.py` + ocr_provider配置 | Integration_Design v2.8 |
| **F-62 Media API** | ✅ Pro | (Pro) `pro_api/media.py` (4端点: asr/tts/ocr/ocr-event) | API_Design v2.9 |
| **F-63 Privacy API** | ✅ Pro | (Pro) `pro_api/privacy.py` (3端点: data-summary/user-data/export) | API_Design v2.9 |
| **F-64 API Rate Limiting** | ✅ 完成 | `core/rate_limiter.py` + `api/v1/dependencies.py` | Security_Design v2.9 |
| **F-65 Pipeline Step类重构** | ✅ 完成 | `services/steps/` (13 Step类) | Algorithm_Design v2.8 |
| **F-66 安全修复** | ✅ 完成 | poc_secret登录+get_current_user_id+动态salt+poc_anonymous_access | Security_Design v2.9 |
| **代码审查通过** | ✅ 完成 | P0-P3修复+CI收紧+tsc/mypy零错误 | DevSquad 7维度审查 |

**P8 Gate 判定**: **✅ 三仓库代码完成，可发布** — 基础版1353测试通过+tsc/mypy零错误，专业版339测试通过+14路由挂载，小程序62 E2E+8单元=70测试通过（CI 全绿）+secureStorage整改完成。三级产品模型：基础版(本地免费)+专业版(网关中继)+定制版(团队)。基础版通过relay_client连接专业版网关。

**当前状态**:
- ✅ 0.1.x 初始化阶段完成
- ✅ 0.2.x POC增强阶段 — Sprint 0 + PoC优化 + 演示准备 全部完成
- ✅ 0.3.x PoC代码完成 — F-44~F-69 + 1224测试
- ✅ 0.4.x Phase A-D代码完成 — F-67/F-68/F-69代码+测试
- ✅ 0.6.x 录入页五类纠偏完成 — 人脉/关系/待办/承诺确认/承诺添加(手动补录)+文本框50000字+时分选择+1353测试通过
- 🟡 基础版 — Docker打包 + Taro H5 + 一键安装脚本（本地免费，SQLite长期方案）
- 🟡 专业版 — 网关中继设计完成，实现未开始（SQLite+relay gateway）
- ❌ 定制版 — 销售团队版（PG+Redis+多租户，独立分支，按需启动）

---

### P9: 测试执行 (Test Execution)

| 检查项 | 状态 | 证据 | 备注 |
|------|------|------|------|
| 单元测试 | ✅ 完成 | 1224测试通过，覆盖率73% | 目标覆盖率≥70% ✅ 达成 |
| 集成测试 | ✅ 完成 | API端到端+前端集成 | Media/Privacy/Rate Limiting/前端集成测试 |
| 算法准确率验证 | ✅ 完成 | 实体归一+关联发现+F-44~F-46 | 1224测试覆盖 |
| 性能基准测试 | ✅ 完成 | 所有P95延迟<500ms | 性能验证通过 |
| 安全渗透测试 | ✅ 完成 | 8/8安全检查通过 | 安全验证通过 |
| E2E测试（模拟真实用户） | ✅ 完成 | Demo 4/4场景全通过+前端E2E | Test_Plan v4.9要求 |

**P9 Gate 判定**: **🟡 单元/集成测试通过，生产验证缺失** — 1224单元/集成测试通过，但缺少生产环境E2E、压力测试、安全渗透测试。测试通过≠产品可用。

---

### P10: 部署与发布 (Deployment & Release)

| 检查项 | 状态 | 证据 | 备注 |
|------|------|------|------|
| Docker容器化 | ✅ 完成 | `Dockerfile` + `docker-compose.yml` | 多阶段构建(builder→runtime非root) |
| GitHub Actions CI/CD | ✅ 完成 | `Deployment_Guide` v0.4.8 | trigger/strategy/services/steps/lint/typecheck/test/coverage |
| Alembic数据库迁移 | ✅ 完成 | `src/promiselink/alembic/` | 初始化+autogenerate+SQLite→PG升级路径 |
| Prometheus监控指标 | ✅ 完成 | `Deployment_Guide` v0.4.8 + `prometheus.yml` | 6项P0指标(input_scope延迟/Todo分布等)+Rate Limiting指标 |
| **托管PoC部署** | ✅ 完成 | `docker-compose.hosted-poc.yml` + `nginx/` + `.env.poc.hosted` | nginx反向代理+HTTPS配置+certbot自动证书+部署脚本 |
| **部署脚本** | ✅ 完成 | `scripts/ops/deploy-staging.sh` | 一键部署脚本 |
| **备份脚本** | ✅ 完成 | `scripts/backup.sh` | 数据库+Redis备份 |
| Staging环境部署 | ❌ 未开始 | - | |
| 回滚方案 | ⏳ 设计完成 | Deployment_Guide | 数据库迁移回滚 |
| 发布检查清单 | ❌ 未开始 | - | |
| 托管PoC部署检查清单 | 🟡 部分完成 | HTTPS配置就绪 | 实际HTTPS证书+域名绑定待完成 |

**P10 Gate 判定**: **🟡 部署配置就绪，未实际部署** — Docker/CI/CD/nginx/部署脚本就绪，但无域名、无HTTPS证书、无生产Key、未执行过deploy.sh。配置就绪≠部署完成。

---

### P11: 运维与保障 (Operations & Assurance)

| 检查项 | 状态 | 证据 | 备注 |
|------|------|------|------|
| 监控告警 | ✅ 完成 | `prometheus.yml` + Grafana待配置 | Prometheus metrics已定义+配置文件就绪 |
| 日志聚合 | ❌ 未开始 | - | ELK/Loki |
| 备份策略 | ✅ 完成 | `scripts/backup.sh` | PG dump + Redis AOF，自动备份脚本就绪 |

**P11 Gate 判定**: **✅ 部分完成（60%）** — Prometheus监控配置+备份脚本就绪，日志聚合待实施。

---

## 6. 阶段依赖关系与关键路径

```
当前所处位置:
                [P1 ✅] ──→ [P2 ✅] ──→ [P3 ✅] ──→ [P6 ✅] ──→ [P7 ✅] ──→ [P8 ✅] ──→ [P9 ✅] ──→ [P10✅90%] ──→ [P11🟡60%]
                   │           │           │                        ▲
                   ├→ [P4 ✅] ──┘           └→ [P5 ✅] ────────────────┘
                   └→ [P5(depends P1+P3)]                         YOU ARE HERE

关键路径: 本地E2E验证 → 基础版Docker打包 → 一键安装脚本 → 发布基础版 → 专业版网关开发
当前节点: PoC代码完成+1224测试通过，基础版SQLite长期方案已确认，需Docker打包+安装脚本
下一节点: 本地E2E验证 → 基础版Docker打包 → 发布基础版 → 专业版网关开发
定制版: 销售团队需求时启动（独立分支，PG+Redis+多租户）
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
2026-06-04  ├─ ★ M4: 批次1 P0文档完成
            │         7份设计文档更新至v2.0/0.2.0
            │         Commit: 2d5dd6d
            │
2026-06-05  ├─ ★ M5: PRD v4.4 + F-50智能语音助手设计完成
            │         新增F-50智能语音助手功能（NLU+语音会话+多轮对话）[F-50新增]
            │
2026-06-05  ├─ ★ M6: Sprint 0 全量P0编码完成 (commit 179c1f8)
            │         F-44~F-50 七项功能全部实现 (472→490测试)
            │
2026-06-05  ├─ ★ M7: PoC优化完成 (commit ee9be45)
            │         DB级去重 + Brief聚合视图 + Pipeline并行化
            │
     ★      └─ ★ M8: 许总演示就绪 (commit 0900f73)

2026-06-06  ├─ ★ M9: PRD v4.5 + 技术设计 v2.6 + 9份文档v2.5同步 (commit a1e0fd0)
            ├─ ★ M10: POC验收通过 (commit 62cc311)
            │         F-44~F-54全部编码+542测试+Demo 4/4+P9回归测试集
            │
2026-06-07  ├─ ★ M11: Phase 1后端功能完成 (F-55~F-58+EmailAdapter+WeChatForwardAdapter)
            │         735测试通过, Pipeline 14步完整实现
            │
2026-06-08  ├─ ★ M12: Phase 1全功能完成里程碑
            │         F-59~F-66(Media+Privacy+Rate Limiting+安全修复+Pipeline重构)
            │         PRD v4.8 + 866测试通过, 0 skip, 覆盖率74%(目标≥70%)
            │
2026-06-09  ├─ ★ M13: 前端集成+托管PoC部署就绪 ← 当前位置
            │         Taro小程序前端联调完成 + 1224测试 + 73%覆盖率
            │         托管PoC部署(docker-compose.hosted-poc.yml+nginx+HTTPS+部署脚本+备份脚本)
            │         性能P95<500ms + 安全8/8通过 + PoC准备度82/100
```

---

## 8. 下一步行动计划

### 📋 基础版打包发布，下一阶段: 发布基础版

| # | 行动项 | 负责方 | 产出 | 对应变更 |
|---|--------|--------|------|---------|
| 1 | **本地E2E验证** | CarryMem | 本地完整用户旅程验证通过 | P9验证完成 |
| 2 | **基础版Docker打包** | CarryMem | Docker镜像+docker-compose基础版配置 | P10基础版部署 |
| 3 | **Taro H5前端打包** | CarryMem | H5可访问版本 | P8前端完成 |
| 4 | **一键安装脚本** | CarryMem | install.sh脚本 | P10安装体验 |
| 5 | **发布基础版** | CarryMem | 基础版可用 | P10里程碑 |

### ✅ 已完成Sprint回顾

| Sprint | 功能 | 状态 |
|--------|------|------|
| Sprint 0 | 冻结方向 + 回归测试集 | ✅ 完成 |
| Sprint 1 | F-44~F-48 五项P0核心 | ✅ 完成 |
| Sprint 2 | F-47/F-48完整版 + F-49 Dashboard | ✅ 完成 |
| Sprint 3 | F-50 智能语音助手 | ✅ 完成 |
| Phase 1 扩展 | F-51~F-58 动态优先级+语义搜索+数据接入 | ✅ 完成 |
| Phase 1 媒体 | F-59~F-66 Media+Privacy+Rate Limiting+安全修复 | ✅ 完成 |
| 前端集成 | Taro小程序前端开发+后端联调 | ✅ 完成 |
| 托管PoC部署 | docker-compose.hosted-poc.yml+nginx+HTTPS+部署脚本+备份脚本 | ✅ 完成 |

---

## 9. 风险登记册

| ID | 风险描述 | 概率 | 影响 | 应对策略 | 状态 |
|----|---------|------|------|---------|------|
| R01 | 许总对技术方案提出大幅修改意见 | 中 | 高 | 快速迭代HTML版本（已验证4轮迭代能力） | 🟡 监控中 |
| R02 | 小程序→PromiseLink边界接口缺口（名片JSON格式+用户映射+metadata schema） | 高 | 中 | ⚠️ 待确认（Phase1前必须补齐） | ①向许总团队获取IAMHERE名片样例JSON ②设计user_auth_mappings表 ③定义card_save metadata schema |
| R03 | LLM实体抽取准确率不达95% | 低 | 高 | spaCy降级兜底 + 人工确认机制 | 🟢 已缓解 |
| R04 | F-44~F-49 五项P0功能实施周期超预期 | 中 | 高 | Sprint拆分：Sprint 1做初版，Sprint 2完善 | 🟡 监控中 |
| R05 | UI_UX_Design更新滞后阻塞前后端联调 | 中 | 中 | 先行API契约对齐，UI并行迭代 | 🟡 监控中 |
| R06 | 许总决定不继续合作 | 低 | 极高 | 核心引擎独立于IAMHERE，可换其他数据源 | 🟢 已缓解 |
| R07 | 托管PoC运维责任风险 | 中 | 中 | 我方承担运维，需SLA保障；制定运维SOP+监控告警 | 🟢 部分缓解 (Prometheus监控+backup.sh备份脚本就绪，SOP待完善) |

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
| 2026-06-05 | **PRD升级至v4.4，新增F-50智能语音助手** | 许总语音交互需求+7角色Review补充 | F-50纳入P0功能集，Sprint 3专项实施 [F-50新增] |
| 2026-06-06 | **PRD升级至v4.5，新增智能定义与边界** | DeepSeek架构讨论启发+DevSquad审核 | §1.7智能定义+动态优先级+隐式反馈+数据接入层+F-51~F-54 |
| 2026-06-06 | **技术设计升级至v2.6** | Insight Engine+DataSourceAdapter+动态评分 | 新增§4.10洞察引擎+§4.11数据接入层 |
| 2026-06-06 | **9份设计文档同步更新至v2.5/0.3.0/v2.0** | DevSquad 4角色审核→3处不一致→全量同步 | P0×3+P1×3+P2×3全部完成 |
| 2026-06-06 | **Pipeline重编号：Step 0/0.5/4.5/7.5→Step 1-14** | 编号混乱影响可读性 | 14步顺序编号，文档已同步 |
| 2026-06-08 | **PRD升级至v4.8，Media架构决策变更** | ASR/TTS/OCR服务独立化+Privacy API+Rate Limiting | F-59~F-66新增，9份文档同步至v2.8/0.4.1/v2.3 |
| 2026-06-08 | **Pipeline Step类重构** | event_pipeline.py 728→227行，可维护性提升 | services/steps/ 13个Step类，Pipeline逻辑清晰化 |
| 2026-06-08 | **安全修复: poc_secret/dynamic salt/get_current_user_id** | POC阶段安全加固 | poc_secret登录+动态salt+poc_anonymous_access配置 |
| 2026-06-09 | **PRD升级至v4.9，新增托管PoC部署模式+数字名片对接决策(PoC不对接)+托管PoC迁移路径** | 托管PoC运维责任明确+数字名片Phase1再评估+迁移路径设计 | Integration_Design v2.9 + Test_Plan v4.9 + PROJECT_STATUS同步更新 |
| 2026-06-09 | **前端-后端集成完成** | Taro小程序前端与FastAPI后端完整联调 | 所有API端点前端可调用，E2E全链路验证通过 |
| 2026-06-09 | **性能基准验证通过** | 所有API端点P95延迟<500ms | 性能达标，可支撑PoC演示 |
| 2026-06-09 | **安全检查8/8通过** | 安全审查全项验证通过 | 无P0/P1漏洞，PoC安全基线达标 |
| 2026-06-09 | **名片扫描采用OCR+LLM方案** | PoC不对接IAMHERE，自建OCR+LLM名片解析链路 | F-61 OCR服务+LLM结构化提取，独立于第三方 |
| 2026-07-03 | **小程序 CI Playwright UI E2E 根因修复** | Taro 4.1.9 DefinePlugin 在 Linux+Node20(CI) 下未替换 `process.env.TARO_APP_API_URL`，运行时 `process` 未定义导致 ReferenceError，app 崩溃白屏（本地 macOS+Node24 替换正常，掩盖问题） | 所有 `process.env` 引用加 `typeof process !== 'undefined'` 守卫；移除 `continue-on-error` 让 UI 失败真正阻塞 CI；62/62 测试 CI 全绿 |

---

## 12. PoC 准备度评估 (PoC Readiness Assessment)

> **评估日期**: 2026-06-11
> **评估基准**: 基础版发布所需全部条件
> **产品层级**: 基础版(本地免费) / 专业版(网关中继) / 定制版(团队)

### 综合评分

```
PoC 准备度评分
═══════════════════════════════════════════════════════════

  总分: 60/100 (代码可用但未部署发布)

  ┌─────────────────────────────────────────────────────┐
  │  ██████████████████████████░░░░░░░░░░░░░░░░  60%  │
  └─────────────────────────────────────────────────────┘

  评估维度 (诚实校准):
  ─────────────────────────────────────────────────────
  后端功能完整度    ██████████████████████  100%  (F-01~F-69 代码完成)
  前端集成完成度    ████████████████░░░░░░   75%  (代码完成，但未Docker打包+H5发布)
  测试覆盖         ████████████████░░░░░░   75%  (1224测试通过，缺本地E2E验证)
  性能验证         ██████████████░░░░░░░░   60%  (开发环境P95<500ms，生产未验证)
  安全验证         ██████████████░░░░░░░░   60%  (代码级8/8通过，缺生产渗透测试)
  部署就绪度       ██████████████░░░░░░░░   55%  (SQLite长期方案确认，需Docker打包+安装脚本)
  运维保障         ████░░░░░░░░░░░░░░░░░░   15%  (脚本就绪，但无实际运维经验)
  文档完整性       ████████████████████░░   90%  (16份文档同步，Database_Design升级v3.0)
═══════════════════════════════════════════════════════════
```

### 诚实校准说明

代码在本地可运行，但未经过Docker打包和一键安装验证，不能称为"产品可用"。

| # | 校准项 | 评估 | 原因 |
|---|--------|------|------|
| 1 | 部署就绪度 | 55% | 配置文件就绪，但未Docker打包+一键安装脚本 |
| 2 | 运维保障 | 15% | 脚本就绪≠运维完成，无实际运维经验 |
| 3 | 性能验证 | 60% | 开发环境数据，生产环境未验证 |
| 4 | 安全验证 | 60% | 代码级检查≠生产渗透测试 |
| 5 | 前端集成 | 75% | 代码完成但未H5打包发布 |

### 基础版发布阻塞项

| # | 阻塞项 | 影响 | 解决方案 | 预计耗时 |
|---|--------|------|---------|---------|
| 1 | 本地E2E验证未完成 | 无法确认完整用户旅程 | 执行本地E2E测试脚本 | 1天 |
| 2 | Docker镜像未打包 | 无法一键安装 | 编写Dockerfile+docker-compose基础版 | 1-2天 |
| 3 | Taro H5前端未打包 | 无Web访问入口 | Taro build:h5 + 静态资源部署 | 1天 |
| 4 | 一键安装脚本未编写 | 用户安装门槛高 | install.sh脚本 | 1-2天 |
| 5 | 运维SOP未完善 | 日常运维无标准流程 | 编写运维手册 | 1-2天 |

### 基础版发布前检查清单

- [ ] 本地E2E验证通过（完整用户旅程）
- [ ] Docker镜像打包完成
- [ ] Taro H5前端打包完成
- [ ] 一键安装脚本编写完成
- [ ] 基础版安装验证（干净环境测试）

---

## 13. 文档索引速查

| 文档 | 路径 | 版本 | 最后更新 |
|------|------|------|---------|
| **项目状态（本文档）** | `docs/PROJECT_STATUS.md` | — | 2026-06-11 |
| 产品需求 | `docs/spec/PRD_v1.md` | v5.2 | 2026-06-11 |
| 需求索引 | `docs/spec/README.md` | — | 2026-06-11 |
| 技术设计 | `docs/architecture/PromiseLink_技术设计_v1.md` | v3.2 | 2026-06-11 |
| API设计 | `docs/design/API_Design_v1.md` | v3.1 | 2026-06-11 |
| 数据库设计 | `docs/design/Database_Design_v1.md` | v3.0 | 2026-06-11 |
| 算法设计 | `docs/design/Algorithm_Design_v1.md` | v2.8 | 2026-06-08 |
| 安全设计 | `docs/design/Security_Design_v1.md` | v3.1 | 2026-06-11 |
| 测试计划 | `docs/design/Test_Plan_v1.md` | v5.1 | 2026-06-11 |
| 集成设计 | `docs/design/Integration_Design_v1.md` | v2.9 | 2026-06-09 |
| 部署指南 | `docs/design/Deployment_Guide.md` | v0.5.0 | 2026-06-11 |
| UI/UX设计 | `docs/design/UI_UX_Design_v1.md` | v3.1 | 2026-06-11 |
| LLM提示词 | `docs/design/LLM_Prompt_Templates.md` | 0.4.1 | 2026-06-08 |

---

*本文档由 DevSquad 11阶段生命周期框架生成，随项目进展持续更新。*
*最后更新: 2026-07-01 (Phase 1-3 Staging修复完成：E2E链路+PromptInjection硬约束+CI/CD timeout+UUIDStr+三语README+Dockerfile LABEL+requirements.lock清理)*
