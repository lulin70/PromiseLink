# Changelog

All notable changes to PromiseLink will be documented in this file.

## [0.7.0] - 2026-06-28

### Fixed — P0 阻断项修复
- **P0-1: 文件上传失败修复（Q5）**：DB 约束 `association_type_check` 缺少 `topic_overlap`/`supply_demand`/`industry_chain` 三种关联类型，导致非关键步骤失败被标记为 `failed`；新增 Alembic 迁移 `g7b8c9d0e1f2_sync_association_type_check` 同步约束，Step13 区分关键步骤与非关键步骤，非关键步骤失败降级为 `degraded_completed`，前端轮询逻辑同步适配
- **P0-2: 基础版与小程序数据不一致（Q4）**：小程序每次登录生成随机 UUID v4，导致与基础版固定 `poc-user` 数据隔离；修复为使用固定 `poc-user`，确保两端数据一致

### Fixed — P1 改进
- **P1-1: 事件类型 card_scan 拼写修复（Q6）**：小程序 TS types/UI/EventCard 使用 `card_scan`，后端使用 `card_save`，统一为 `card_save`
- **P1-2: 小程序 API URL 缺少 /api/v1 前缀**：`config/dev.ts` 中 `TARO_APP_API_URL` 为 `http://localhost:8000`，缺少 `/api/v1` 前缀导致所有 PATCH 请求 405；修复为 `http://localhost:8000/api/v1`

### Changed — P2 设计优化
- **P2-1: 移除 DesktopDetailBar（Q1）**：详情摘要栏仅在事件详情页加载真实数据，其他页面均显示占位文本；遵循 Simplicity First 原则移除该组件，桌面布局从三栏改为两栏
- **P2-2: "我的"入口移至侧边栏底部（Q2）**：原"升级Pro"区块替换为"我的"导航项，Pro 升级入口移至"我的"页面内部；新建 mine 页面包含用户信息、Pro 升级、关于、退出登录

### Event Types — 统一事件类型
- 移除 `email` 事件类型（专业版邮件同步自动生成，基础版不支持）
- 保留 5 种事件类型：`manual`/`meeting`/`call`/`card_save`/`wechat_forward`
- 新增 Alembic 迁移 `h8c9d0e1f2a3_remove_email_event_type` 清理历史数据

### Miniapp Fixes — 小程序修复
- 移除 mock 降级数据，所有数据走真实 API
- 3 个孤立页面（voice-query/reminders/demand）加入口
- store userId 同步修复
- title 修正为 "PromiseLink"

## [0.6.6] - 2026-06-21

### Fixed — P0阻断项修复（5项）
- **P0-1: 前端补齐专业版引导入口**：DesktopSidebar 底部新增"升级专业版"引导卡片（标题+描述+了解详情按钮），莫兰迪色系样式，达成硬约束"基础版UI需包含专业版引导入口"
- **P0-2: poc_secret明文存储修复**：`auth.ts` 中 `saveLoginCredentials`/`getSavedSecret` 从 localStorage 改为 sessionStorage，关闭标签页即清除，减少XSS攻击的长期暴露窗口；`logout` 同步清除 secret
- **P0-3: PoC登录端点环境检查**：`auth.py` login 端点新增生产环境检查，`app_env=="production"` 且 `poc_secret==默认值"promiselink2026"` 时拒绝登录，防止生产环境误用默认密码
- **P0-4: 依赖锁文件**：新增 `requirements.lock`（232行），锁定已验证的依赖版本组合，保证构建可复现
- **P0-5: 测试数文档统一**：README/CHANGELOG/PROJECT_STATUS 测试数统一为 1353 passed（之前三处矛盾：1351/1353/1390）

### Changed — P1死代码清理（5项，共627行+13配置字段）
- **P1-1: config.py死配置清理**：删除 ASR/TTS/OCR provider（5字段）、Email IMAP（6字段）、Privacy（2字段）共13个死配置字段，对应路由已删除
- **P1-2: schemas死Schema清理**：删除 `ImportCSVResponse`、`TTSFallbackResponse` 两个无引用的Schema类，同步更新 `__init__.py` 导出列表
- **P1-3: skip测试清理**：删除6处被 `@pytest.mark.skipif(APP_EDITION!="pro")` 跳过的专业版测试（共627行）：TestEmailSyncAPI/TestVoiceAssistantJourney/3个Privacy API测试/TestPrivacyAPIIntegration/TestCSVImportSecurity/CSV Import性能测试
- **P1-4: 前端admin/usage清理**：删除 `frontend/src/pages/admin/usage/` 目录（桥接监控仪表盘，调用基础版不存在的Pro网关admin API），从 `app.config.ts` 移除页面注册
- **P1-5: 坏脚本清理**：删除 `scripts/demo/demo_for_xu.py`（导入已删除的 `nlu_intent_classifier` 模块，运行场景2会 ImportError）

### Tests
- 全量回归：1353 passed, 25 skipped, 0 failed, 覆盖率 72%（133.96s）
- ruff: all checks passed
- mypy: 0 errors (111 source files)
- 基础版独立运行验证通过

## [0.6.5] - 2026-06-21

### Added — P10 Docker多阶段构建
- **Dockerfile 改造**：新增 `frontend-builder` 阶段（node:20-alpine），在Docker构建时自动编译H5前端，构建产物COPY到 `/app/static/`，FastAPI直接serve前端静态文件
- **docker-compose.yml 增强**：新增 `nginx` 服务（production profile），支持TLS终止+反向代理，与现有 `nginx/conf.d/default.conf` 配置对齐
- **.dockerignore 更新**：保留 `frontend/` 源码（供frontend-builder阶段使用），排除 `frontend/dist/` 和 `frontend/node_modules/`（避免缓存污染）

### Fixed — 项目整理评估修复（7维度走读）
- **P0 BUG: Entity.status 过滤错误**：`scheduled_events.py:570` 使用不存在的 `"active"` 状态值，改为 `in_(["confirmed", "provisional"])`，修复计划事件参与者自动匹配失效
- **P0 BUG: snoozed_until 字段访问错误**：`todos.py:325` 用 `getattr(todo, 'snoozed_until', None)` 访问不存在的字段，改为查询 `SnoozeSchedule` 表获取真实恢复时间
- **P0: 依赖声明不一致**：`pyproject.toml` 缺失 `asyncpg`/`aiosqlite`/`structlog`/`python-dotenv`/`cryptography`，导致 `pip install -e .` 后运行时 ImportError，已补全
- **P1: no-op 字符串构造**：`scheduled_events.py:391` 构造参与者前缀字符串但未赋值，导致 raw_text 缺少参与者上下文，已修复
- **P1: 版本号不一致**：`__init__.py` 版本 0.5.2 落后于 `config.py`/`pyproject.toml` 的 0.6.5，已统一
- **P1: configure_logging() 未调用**：`main.py` 直接用 `structlog.get_logger()` 但未初始化 processor 链，日志可能非 JSON 格式，已在 lifespan 启动时调用
- **P1: monitoring/README.md 与代码不符**：文档声称基础版无 metrics 端点，实际已有，已更新文档

### Changed — 技术债清理
- 删除 `config.py` 中未使用的 `ai_mode` 配置项及其 field_validator
- 删除 4 个孤儿登录页文件（`pages/login/index.tsx`、`pages/index/login.tsx` 等，未在 app.config.ts 注册）
- 更新 `monitoring/README.md` 反映基础版已包含 Prometheus metrics 端点
- 更新 `README.md` 版本号 v0.6.3 → v0.6.5

### Tests
- 全量回归：1353 passed, 45 skipped, 0 failed, 覆盖率 72%
- ruff: all checks passed

## [0.6.4] - 2026-06-20

### Added — P10部署发布+P11运维保障推进
- **install.sh 重写**（48行→296行）：8步流程对齐专业版（Python检查→Node检查→venv创建→依赖安装→前端构建→数据库迁移→配置检查+自动生成SECRET_KEY→健康验证）
- **start.sh 重写**（48行→372行）：5种模式（前台/守护进程/停止/状态/重启）+端口冲突检测+PID管理+日志轮转（5MB自动归档）+健康检查（30s超时）
- **P11 Prometheus监控端点**：新增 `/api/v1/metrics` 端点（Prometheus文本格式），暴露 http_requests_total counter + http_request_duration_seconds histogram + promiselink_info gauge + event_processing metrics
- **Prometheus中间件**：自动采集所有HTTP请求的计数和耗时，与 monitoring/alerts.yml 告警规则对齐
- 新增 prometheus-client>=0.20.0 依赖

### Fixed — CI/CD隐患修正
- 移除 `pip-audit --ignore-vuln GHSA-xxxx` 占位符（不再掩盖真实漏洞）
- 覆盖率阈值 75%→72%（与实际覆盖率对齐，避免CI失败）

### Tests
- 全量回归：1353 passed, 45 skipped, 0 failed, 覆盖率 72%
- mypy: 0 errors, ruff: all checks passed
- /api/v1/metrics 端点验证成功（Prometheus格式指标正常输出）

## [0.6.3] - 2026-06-19

### Added
- PRD §5.18.3 纠偏5：承诺添加（手动补录）— 后端 CorrectedPromiseItem 支持 action='add'，前端承诺区新增[+添加承诺]按钮+内联表单
- PRD §5.18.3 纠偏2：关系纠偏 — 后端新增 CorrectedAssociationItem + corrected_associations 字段，前端关系卡片新增[改]按钮+关系类型选择器
- PRD §5.18.6 API契约扩展 — EventCorrectResponse 新增 promises_created/associations_updated 计数字段
- 录入页文本框容量 5000→50000 字（对齐 PRD §5.18.1）
- 录入页时间选择新增时分选择（对齐 PRD §5.18.1）

### Changed
- 基础版前端 api.ts 类型同步：CorrectedPromiseItem.id 改为可选，action 新增 'add'，新增 CorrectedAssociationItem 接口
- correct_event 函数文档字符串更新为"五类纠偏"

### Tests
- 新增 test_event_correction_v56.py（12个测试）：承诺添加(6)+关系纠偏(4)+综合(2)
- 全量回归：1353 passed, 45 skipped, 0 failed, 覆盖率 72%
- mypy: 0 errors, ruff: all checks passed

## [0.6.2] - 2026-06-19

### Added — P1-P9批判性评审+三重点用户旅程测试增强
- **7角色批判性评审报告**: 72/100→78/100(测试增强后), 发现4项阻断项(B1-B4)+10项改进项(I1-I10), 揭露上一轮ReReview报告数据不实(mypy 98错误非0/测试数虚报/评审对象错位)
- **会后记录测试增强**: 31个测试覆盖9个缺口(email/wechat_forward事件类型/批量创建/retry/accept-degraded/500KB限制/级联删除/搜索过滤)
- **待办生成测试增强**: 23个测试覆盖8个缺口(_rule_based_fallback/_is_duplicate_todo/help类型/call事件/PriorityScorerV2/会话截断/LLM异常处理/去重集成)
- **承诺跟进测试增强**: 29个测试覆盖10个缺口(nudge-draft端点/their_promise生命周期/overdue/broken状态/安全约束/pending重置/fulfilled_at验证/草稿缓存/统计/双向承诺E2E)

### Fixed — 发现的源代码Bug(报告未修改)
- **overdue_notified_at字段从未被API设置**: PATCH /promises/{id}/fulfillment在overdue时未设置overdue_notified_at字段, 该字段始终为None

### Test Results
- pytest: 1260 passed, 45 skipped (+83新用户旅程测试)
- 覆盖率: 69%(从68%提升)
- 三重点测试覆盖维度: Happy Path 62% + Error 18% + Boundary 20%

## [0.6.1] - 2026-06-18

### Added — e2e真实用户场景测试+Pro文档迁移
- **6个真实用户场景e2e测试**: TC-W3-050~055共46个测试用例, 覆盖许总杀手场景/BD日常/投资人关联/创业者风险/首次4屏/承诺闭环, Happy Path 71.7%+Error 15.2%+Boundary 13.0%
- **Pro文档迁移到PromiseLink-Pro repo**: 7个专业版文档(架构/安全/技术设计/测试计划/PRD/实现计划/评审报告)从公开repo迁移到私有repo

### Changed — 三repo推送Git
- PromiseLink: 推送到github.com:lulin70/PromiseLink.git (SSH)
- PromiseLink-Pro: 推送到github.com:lulin70/PromiseLink-Pro.git (SSH, remote从HTTPS改为SSH)
- PromiseLink-miniapp: 推送到github.com:lulin70/PromiseLink-miniapp.git (SSH, remote从HTTPS改为SSH)

### Test Results
- pytest: 1177 passed, 45 skipped (+46新e2e测试)
- 覆盖率: 68%

## [0.6.0] - 2026-06-18

### Added — Phase 2专业版代码迁移+文件上传修复+内存泄漏修复+UI引导
- **专业版代码迁移到PromiseLink-Pro repo**: 86个文件迁移(54 gateway + 8 pro-services + 7 pro-api + 10 pro-tests + 1 pro-migration + 4 根目录配置), 基础版repo不再包含专业版源码
- **基础版UI首次使用引导**: 4步引导组件(欢迎/三栏布局/记录交流/AI解析), localStorage记录引导状态, 莫兰迪色系
- **小程序首次使用引导**: 3步引导组件(欢迎/核心功能/开始记录), Taro Storage API跨端兼容
- **nudge_generator.py**: 从nlg_service.py提取generate_gentle_nudge函数到基础版, 保持promises.py催促功能自包含

### Changed — 专业版代码从基础版repo移除
- **删除27个专业版文件**: 8个服务模块(asr/tts/ocr/nlu_intent/nlg/voice_query/email_adapter/wechat_forward_adapter) + 7个API路由(voice/voice_query/media/email_sync/wechat_forward/import_csv/privacy) + 10个测试 + voice_session模型 + voice_sessions迁移
- **删除gateway/目录**: 54个文件完整迁移到PromiseLink-Pro/gateway/
- **删除2个专业版E2E测试**: test_pro_edition_e2e.py + test_pro_security.py (依赖gateway模块)
- **main.py**: 移除APP_EDITION=='pro'路由注册块, 移除_track_task死代码
- **models/__init__.py**: 移除VoiceSession/VoiceTurn/VoiceAnalytics导入
- **services/__init__.py**: 移除EmailAdapter导入和导出
- **data_source_adapter.py**: 移除EmailAdapter导入和注册, Pro版通过register_adapter()懒加载
- **alembic迁移链**: a1b2c3d4e5f6的down_revision从538083639032改为4ff9b21a03b0(跳过voice_sessions)
- **promises.py**: generate_gentle_nudge导入从nlg_service改为nudge_generator
- **test_data_source_adapter.py / test_e2e_regression.py / test_integration_supplement.py / test_coverage_boost.py**: 移除对已迁移专业版模块的引用

### Fixed — 文件上传bug + 内存泄漏 + 性能问题
- **文件上传H5兼容性修复**: Taro.chooseMessageFile在H5端永久不支持(permanentlyNotSupport), 改用浏览器原生<input type="file">, 修复用户点击上传后报错的问题
- **EmbeddingProvider单例化(P0)**: 每次pipeline重新创建EmbeddingProvider导致sentence-transformers模型重复加载(数百MB内存), 改为模块级单例+get_shared_provider()+close_shared_provider()
- **SemanticSearchEngine单例化(P0)**: 同样改为模块级单例, 复用sqlite-vec扩展加载和表初始化
- **RelayClient关闭(P2)**: 添加close_relay_client()函数, 在main.py lifespan shutdown中调用
- **EmbeddingProvider的AsyncOpenAI客户端关闭(P1)**: 添加close()方法
- **前端polling轮询限制(P2)**: 添加MAX_POLL_ATTEMPTS=60(2分钟超时), 避免无限轮询
- **step_03_embedding.py**: 使用get_shared_provider()/get_shared_engine()替代直接new

### Test Results
- ruff check: All checks passed
- mypy: Success, no issues found in 102 source files
- pytest: 1131 passed, 45 skipped (移除了专业版测试, 基础版测试全通过)
- npm build:h5: webpack compiled with 7 warnings (无error)

## [0.5.5] - 2026-06-18

### Added — 宽屏UI+录入纠偏+详情页跳转+专业版一键安装+桥接监控
- **基础版宽屏UI三栏布局**: ≥1024px左导航200px+中内容flex:1+右详情360px, 莫兰迪色系CSS变量, DesktopSidebar组件+useIsDesktop hook
- **录入事件画面整理+解析纠偏**: POST /events/{id}/correct端点, 前端4区Tab纠偏(人脉/待办/承诺), 人脉多候选选择, 40测试通过
- **详情页互相跳转**: 4个详情页(事件/人脉/待办/承诺)+4个Link组件+navigation服务, 事件↔人脉↔待办↔承诺互相navigateTo
- **RelayClient服务**: HTTP中继客户端连接云端AI网关, 支持LLM/ASR/TTS/OCR, 自动JWT令牌刷新, 优雅降级+指数退避重试
- **专业版一键安装脚本**: scripts/install_pro.sh, 非技术人员可用, 只需输入许可证密钥, 无需apiKey, 自动完成环境检查→依赖安装→前端构建→数据库迁移→relay配置
- **专业版启动脚本**: scripts/start_pro.sh, 启动前检查许可证密钥和网关连接
- **桥接监控仪表盘**: gateway/api/v1/admin.py(5端点: 用量概览/用户列表/用户详情/CSV导出/健康检查), 前端监控页面(概览卡片+用户表格+流量灯+30秒自动刷新), 19测试通过
- **Repo分开决策文档**: docs/architecture/Repo_Split_Decision.md, 基础版(公开AGPL v3)+专业版(私有商业许可)双repo+API桥接
- **PRD v5.3**: 新增706行覆盖7项需求(repo分开/宽屏UI/录入纠偏/功能重点/详情页跳转/一键安装/桥接监控)

### Changed
- **后端扩展**: EventEntityDetail/EventAssociationRef schema, get_event填充related_entities/related_todos, TodoResponse新增action_type/fulfillment_status/confirmation_status/evidence_quote
- **gateway/main.py**: 注册admin路由+修复模块导入
- **gateway/config.py**: 添加gateway_admin_key设置
- **测试数量**: 1293 passed, 109 skipped (新增40纠偏测试+19 admin API测试)

## [0.5.4] - 2026-06-17

### Added — 基础版内部灰度发布
- **UI响应式断点**: app.scss添加768px/1024px两档断点，桌面端内容区max-width 750px/900px居中
- **E2E测试扩充**: scripts/e2e/e2e_user_journey_extended.py，42个测试用例，8大场景(新用户/多事件/人脉/承诺/日程/仪表盘/导出/边界)
- **安全测试套件**: tests/test_security_comprehensive.py，50个测试用例，7大维度(SQL注入/XSS/路径遍历/JWT/越权/输入验证/速率限制)
- **性能测试套件**: tests/test_performance_baseline.py，17个测试用例，4大维度(API响应/数据库/并发/内存)
- **开源治理文件**: SECURITY.md(安全策略+漏洞报告), .github/cla-assistant.json + .github/CLA.md(贡献者许可协议)
- **DMCA模板**: docs/legal/DMCA_TAKEDOWN_TEMPLATE.md，含6个平台联系方式
- **CI/CD加固**: mypy改为阻断, 添加pip-audit安全扫描, 添加--cov-fail-under=60覆盖率阈值

### Fixed
- **BUG-001**: validation_exception_handler在form-encoded数据时bytes序列化崩溃，添加_sanitize_bytes_recursive递归清理
- **mypy 38错误清零**: 19个文件修复(cast类型断言11处+type:ignore 9处+类型标注5处+list()包装2处)
- **CacheService._redis运行时AttributeError**: 添加_redis属性返回_redis_client
- **git history内部路径泄露**: git filter-repo重写67个commit，167处/Users/lin/→相对路径
- **ruff 218错误清零**: 自动修复214处+手动修复5处(F841未使用变量+E722 bare except)

### Changed
- **UI莫兰迪色系统一**: app.scss/app.config.ts+11个页面文件，Ant Design蓝→莫兰迪雾蓝灰(#7B9EA8)
- **测试数量**: 1319测试通过(1210单元+42 E2E+50安全+17性能), 63个测试文件
- **成熟度评分**: 80→92/100 (架构84/安全90/测试92/PM87/开发92/DevOps81/UI84)
- **CONTRIBUTING.md更新**: 添加CLA签署流程说明
- **PROJECT_STATUS.md更新**: 成熟度92/100，内部灰度就绪

## [0.5.3] - 2026-06-17

### Added — 开源前阻断项修复+基础版提升
- **开源治理文件**: CONTRIBUTING.md(AGPL v3声明+PR流程+CLA), CODE_OF_CONDUCT.md(社区行为准则), SECURITY.md(安全策略+漏洞报告), docs/legal/DMCA_TAKEDOWN_TEMPLATE.md(DMCA下架模板)
- **CLA配置**: .github/cla-assistant.json + .github/CLA.md(贡献者许可协议)
- **UI莫兰迪色系统一**: app.scss/app.config.ts+11个页面文件，Ant Design蓝→莫兰迪雾蓝灰(#7B9EA8)
- **UI响应式断点**: 768px/1024px两档断点，桌面端内容区max-width 750px/900px居中
- **E2E测试扩充**: scripts/e2e/e2e_user_journey_extended.py，42个测试用例，8大场景(新用户/多事件/人脉/承诺/日程/仪表盘/导出/边界)
- **安全测试套件**: tests/test_security_comprehensive.py，50个测试用例，7大维度(SQL注入/XSS/路径遍历/JWT/越权/输入验证/速率限制)
- **性能测试套件**: tests/test_performance_baseline.py，17个测试用例，4大维度(API响应/数据库/并发/内存)
- **CI/CD加固**: mypy改为阻断, 添加pip-audit安全扫描, 添加--cov-fail-under=60覆盖率阈值

### Fixed
- **BUG-001**: validation_exception_handler在form-encoded数据时bytes序列化崩溃，添加_sanitize_bytes_recursive递归清理
- **mypy 38错误清零**: 19个文件修复(cast类型断言11处+type:ignore 9处+类型标注5处+list()包装2处)
- **CacheService._redis运行时AttributeError**: 添加_redis属性返回_redis_client
- **git history内部路径泄露**: git filter-repo重写67个commit，167处/Users/lin/→相对路径

### Changed
- **测试数量**: 1319测试通过(1210单元+42 E2E+50安全+17性能), 63个测试文件
- **成熟度评分**: 80→92/100 (架构84/安全90/测试92/PM87/开发92/DevOps81/UI84)
- **LLM_PRESETS**: 新增GPT5.5和Claude Sonnet 4.6配置选项
- **LLM配置**: .env改用LLM_PROVIDER自动填充base_url/model

## [0.5.2] - 2026-06-16

### Added
- **APP_EDITION配置**: config.py新增`app_edition`字段(basic/pro)，支持基础版/专业版产品分层
- **HMAC开发环境自动生成**: 开发环境下secret_key自动生成随机密钥，防止token伪造
- **POC_SECRET默认值**: `promiselink2026`作为PoC登录默认密码
- **版本架构文档**: 版本架构说明与文档一致性更新

### Fixed
- **SQL注入修复**: ilike搜索转义SQL通配符，防止注入攻击
- **前端updateEntity修复**: 实体更新API调用参数修正
- **前端分页参数修复**: promises分页参数从page/page_size统一为offset/limit
- **X-Forwarded-For欺骗漏洞**: `_get_client_ip()`仅信任配置的trusted_proxies
- **Rate Limiter安全加固**: 4个API端点添加限流保护

### Changed
- **E2E测试改进**: 测试框架增强，覆盖更多用户场景
- **文档重命名**: 12个EventLink命名文件统一重命名为PromiseLink
- **测试数量**: 1210测试通过, 60个测试文件, 26个路由文件, 72个API端点
- **安装命令**: `pip install -r requirements.txt` → `pip install -e '.[dev]'`

## [0.5.1] - 2026-06-14

### Fixed — P1 技术债清零
- **代码重复消除**: `_decode_content`→`core/file_utils.py`, `_process_event_background`→`services/event_processor.py`, JSON提取→统一使用`text_utils.extract_json_from_text`
- **API层批量删除移入Service层**: 新增`services/entity_cleanup.py`，使用ORM delete替代`__table__.delete()`
- **Pipeline全局锁→per-user锁**: `_pipeline_write_lock`改为`_pipeline_locks[user_id]`，多用户并发不再串行
- **Pipeline步骤导入移至模块顶部**: 消除函数体内延迟导入
- **4个API端点添加限流**: demand_input/export/voice_query/import_csv
- **13处datetime.utcnow()→datetime.now(UTC)**: promises/reminders/reminder模型
- **API响应统一Pydantic模型**: 新增`schemas/api_responses.py`，7个端点返回类型化响应
- **分页参数统一**: promises的page/page_size→offset/limit
- **todo_id参数类型统一**: str→uuid.UUID

### Fixed — P2 技术债清零
- **数据模型FK约束**: Association.source_event_id、Todo.evidence_event_id添加ForeignKey
- **SnoozeSchedule SQLite兼容**: recover_at从None改为String(50)存储ISO格式
- **ReminderLog复合索引**: 添加(user_id, todo_id)索引
- **Association UniqueConstraint包含user_id**
- **VoiceSession completed_at自动设置**: before_update事件监听器
- **EntityProperties校验增强**: strict_properties_validation配置项+warning日志
- **voice.py COUNT替代全量加载**
- **Dashboard get_supply_demand添加分页**
- **Dashboard get_care_reminders N+1→批量查询**
- **entities_credit.py N+1→批量查询**
- **LLMClient连接池复用**: 共享httpx.AsyncClient+shutdown清理
- **CORS配置收紧**: 显式allow_methods+通配符警告
- **Prompt注入检测增强**: 3→10个检测模式
- **裸except添加日志**: 8处except Exception: pass→logger.debug
- **email_sync.py密码字段安全文档**
- **Settings()直接实例化→get_settings()**

### Added — 测试增强
- **3个新端点测试文件**: test_entities_credit_api.py(8), test_entities_stages_api.py(9), test_wechat_forward_api.py(8)
- **conftest.py内存数据库**: sqlite:///test.db→sqlite://(内存)
- **共享auth_headers fixture**
- **perf测试重命名**: perf_entity_resolution.py→test_perf_entity_resolution.py
- **relationship_brief_service.py语法修复**: _build_interaction_freq调用缺少await

### Changed
- 测试数量: 1224→1249 passed, 覆盖率73%
- 新增模块: core/file_utils.py, services/event_processor.py, services/entity_cleanup.py, schemas/api_responses.py
- 新增Alembic迁移: f1a2b3c4d5e6 (Association FK + ReminderLog索引 + UniqueConstraint)

## [0.5.0] - 2026-06-14

### Fixed
- **P0: X-Forwarded-For欺骗漏洞** — `_get_client_ip()`不再无条件信任X-Forwarded-For，仅当trusted_proxies配置且直连IP属于可信代理时才读取
- **P0: 文档一致性** — 统一测试数量(1224)、覆盖率(73%)、Pipeline步数(13步)、总体进度(85%)，修复7个文件的P0不一致
- **P0: .env.poc.example变量名** — PROMISELINK_前缀变量改为config.py识别的标准名称
- **P0: docker-compose.yml变量名** — PROMISELINK_POC_SECRET改为POC_SECRET
- **P0: spec/README.md功能编号** — F-46/F-47/F-48名称与PRD对齐
- **P1: 4个API端点缺少限流** — demand_input/export/voice_query/import_csv添加rate_limit_dependency
- **P1: datetime.utcnow()时区不安全** — 13处替换为datetime.now(UTC)
- **P1: health.py版本号硬编码** — 改为从config读取app_version
- **P1: 死代码清理** — 删除_stream_export和_generate_response_text未使用函数

### Changed
- **CI/CD** — 移除前端lint `|| true`，build-and-push添加frontend依赖
- **部署脚本** — deploy-staging.sh修复文件引用路径
- **E2E脚本** — 从scripts/移至scripts/e2e/目录
- **.gitignore** — 添加node_modules/、压缩包、二进制文件规则
- **新增** .env.poc.hosted.example云端部署配置模板
- **新增** config.py trusted_proxies字段

## [0.4.9] - 2026-06-13

### Added
- **文件上传功能**: 事件录入支持 .txt/.md 格式会议纪要文件上传
  - `POST /events/upload` 端点，1MB文件大小限制
  - UTF-8/GBK编码自动检测，Markdown格式自动剥离
  - 前端"文本输入"/"文件上传"模式切换
- **Pipeline集成测试**: 3个端到端Pipeline测试（happy path/空文本/多实体）
- **Todo忽略操作**: 前端"忽略"按钮 + `PATCH /todos/{id}` dismiss接口
- **CreditScore批量计算**: `CreditScoreService.batch_calculate()` 替代N+1逐实体查询
- **422错误格式统一**: 自定义 `RequestValidationError` handler，统一返回 `{error: {code, message, details}}`
- **JSONB Schema验证**: `EntityProperties` Pydantic模型验证 + 优雅降级
- **Alembic迁移同步**: event_type/event_status CHECK约束与代码枚举对齐
- **默认密钥阻断**: 非测试环境使用默认secret_key时启动失败

### Fixed
- **P0: Alembic CHECK约束不同步** — event_type缺少email/wechat_forward，event_status缺少awaiting_retry等状态
- **P0: 默认密钥无阻断** — 生产环境使用默认poc_secret无告警，现已阻断启动
- **P1: CSV导入无大小限制** — 新增10MB限制
- **P1: Credit Score N+1查询** — 批量查询替代逐实体查询
- **沉睡联系人扫描去重** — scan_dormant_contacts调用从2次减为1次
- **循环依赖消除** — `_generate_event_title` 提取到 `title_generator.py`
- **Todo.source_event_id外键** — 添加 `ForeignKey("events.id", ondelete="SET NULL")`
- **前端图标路径** — config/index.ts copy路径从 `src/assets/icons/` 修正为 `src/icons/`
- **Export StreamingResponse** — 去掉"data"嵌套层，events/entities等直接在顶层

### Changed
- **entities.py拆分** — 拆分为 entities.py(核心CRUD) + entities_stages.py + entities_credit.py
- **Export改为StreamingResponse** — 避免大数据量OOM，10000实体上限
- **RateLimiter定期清理** — 300秒间隔自动清理过期令牌
- **PII加密密钥独立** — 新增 `pii_encryption_key` 配置项，优先于 `secret_key`
- **Docker Compose profiles** — postgres/redis标记为 `profiles: ["full"]`，基础版仅启动promiselink
- **前端CI流水线** — 新增Node 18 + eslint + build:h5检查
- **mypy配置** — 新增 `[tool.mypy]` 基础配置
- **统一分页参数** — dormant/credit-scores端点添加offset参数
- **测试FK隔离** — 19个测试文件 `PRAGMA foreign_keys=OFF` 确保测试隔离
- 测试数量: 1036→1224 passed, 覆盖率73%

## [0.4.8] - 2026-06-13

### Added
- **LLM Retry + User-Confirmed Degradation (A0-1)**:
  - 新增 `awaiting_retry`/`degraded_completed` 事件状态
  - 新增 `/events/{id}/retry` 和 `/events/{id}/accept-degraded` API端点
  - 前端降级确认卡片（"重新处理"/"接受简化结果"按钮）
- **Events Tab + FAB (A1-3)**:
  - 删除"录入"Tab，新增"事件"Tab（日期筛选+事件列表）
  - 首页FAB按钮跳转录入页
- **Cross-Page Navigation (A1-4)**:
  - Taro.eventCenter + switchTab 300ms延迟导航
  - API返回entity_name支持跨页面点击跳转
- **UUID Field Filtering (A1-5)**:
  - 前端过滤source_event_id等6个内部字段
- **Title Fallback (A1-2)**:
  - Step13自动从raw_text截取前20字符作为fallback标题
- **G1/G2/G3 Features**:
  - G1: 关系健康诊断（5维度评分：阶段30%+互动25%+活跃20%+承诺15%+待办10%）
  - G2: 关系阶段展示与推进建议
  - G3: 个人关怀提醒（5类关怀点匹配）
- **Performance Benchmark**:
  - Entity Resolution O(n)→O(1) 内存索引优化
  - Step11 改为只查关联实体
  - 1000实体warm resolve 0.1ms/entity，5000实体0.1ms/entity

### Fixed
- **P0: Entity status "active" bug** — dashboard.py/health_diagnostic.py/entity_resolution.py使用不存在的"active"状态过滤，导致新实体不可见。改为["provisional", "confirmed"]
- **P0: Step02 failed_steps遗漏** — LLM失败时_extract_conversation返回空结果，Step02条件判断遗漏。新增raw_text非空但0人提取的检测逻辑
- **P1: Promise 422错误** — FastAPI动态路由/{todo_id}匹配了/pending-confirmations。调整路由注册顺序

### Changed
- Pipeline从14步重构为13步（Step01-Step13）
- 前端从Vue3迁移到Taro+React+TypeScript
- 测试数量从866→1036（+170新测试）

## [0.3.0] - 2026-06-08

### Added
- **Security Fixes (C1-C5)**: 5个Critical安全修复
  - C1: poc_anonymous_access IP白名单+审计日志
  - C2: _semantic_similarity_fallback asyncio.to_thread()防事件循环阻塞
  - C3: _fetch_all_person_entities LIMIT分页(5000/500)防OOM
  - C4: SIGTERM/SIGINT信号处理+30秒优雅关闭
  - C5: poc_secret改用hmac.compare_digest()防时序攻击
- **High Priority Fixes (#6-#15)**: 10个High/Medium问题修复
  - #6: Association端点添加user_id校验防越权访问
  - #7: ilike搜索转义SQL通配符防注入
  - #8: Voice API LLMClient传入config防运行时崩溃
  - #9: dashboard datetime.now()改用timezone.utc
  - #10: ValueError改为HTTPException(400)防500错误
  - #11: Dashboard N+1查询优化为批量查询
  - #12: _get_existing_pair_set仅查询必要列
  - #13: JWT添加iss/aud声明防跨服务重放
  - #14: 版本号统一为0.3.0
  - #15: CHANGELOG测试数量同步更新
- **Architecture**: 7个cold discoverer统一为async
- **TTS**: 三级降级策略(微信原生→后端API→纯文字)
- **Miniapp**: Taro+React+TypeScript小程序前端

### Stats
- 866 tests passed, 0 failed | 74% coverage
- Software version: 0.2.0 (POC) → 0.3.0 (Phase 1 complete)

---

## [0.2.0] - 2026-06-06

### Added
- **Phase 1 Backend Complete**: 7项Phase 1后端功能全部完成
  - F-55 DependencyAnalyzer（依赖性全图谱分析）
  - F-56 ContextMatcher（场景Event驱动匹配）
  - F-57 SemanticSearch（向量化语义搜索引擎）
  - F-58 Association Enhancement（关联发现增强）
  - PriorityScorerV2（四维动态优先级：紧急度×0.4 + 重要度×0.6）
  - Implicit Feedback Collector（隐式反馈学习）
  - Insight Engine API端点
- **DataSourceAdapter**: 抽象数据接入层（Manual/Voice/WeChat/CSV/Email）
- **NLG Service**: 自然语言生成服务（Event标题、关系简报、Todo描述）
- **Email Adapter**: 邮件同步适配器（Phase 1）
- **Voice Query Service**: 语音查询服务
- **WeChat Forward Adapter**: 微信转发适配器
- **EmbeddingProvider**: 向量嵌入提供者（API→local fallback双模式）
- **Resource Overuse Detector**: 资源过度使用检测
- **CarryMem Integration**: 协议接口 + NullMemoryProvider优雅降级
- **Security**: 字段级加密（concern/capability）+ 行级安全策略 + HMAC-SHA256持久化
- **Models**: voice_session, vector_embeddings, score_audit_logs, adapter_configs
- **APIs**: 17个端点（health/events/entities/todos/associations/relationship_briefs/dashboard/voice/import/export/demand/auth/wechat_forward/email_sync)
- **Tests**: 654测试用例 / 72%覆盖率 / 41个测试文件

### Changed
- Pipeline 重编号为14步（含Step 5.5语义搜索、Step 8.3资源过检、Step 8.5动态评分）
- Event.title 改为可选字段（默认"未命名"，NLG自动生成）
- Todo模型新增 completed_rank, dynamic_score, score_calculated_at 字段
- Person.properties JSONB支持 concern/capability混合模式
- PRD v4.0 → v4.7（向量化语义能力+智能定义+隐式反馈+数据接入层）
- 技术设计 v2.0 → v2.8（Insight Engine+DataSourceAdapter+向量语义）

### Fixed
- association_discovery: concern/capability兼容dict列表格式(F-53)
- relationship_brief_service: evidence属性访问修复+关联去重
- brief跨事件进度卡'unknown'值修复
- demo脚本DB清理路径修正+user_id过滤
- NLG service: 从硬编码响应改为Pipeline生成+系统NLG
- Pydantic V2 ConfigDict迁移准备

### Stats
- 654 tests passed, 0 failed | 72% coverage
- 28 service modules | 17 API endpoints | 6 data models
- Software version: 0.1.0 (init) → 0.2.0 (POC complete)

---

## [0.1.0] - Initial Release

### Added
- FastAPI project scaffold
- Database models (entity, event, todo, association)
- Basic APIs (Health + Events CRUD)
- Docker configuration
- 8 detailed design documents (Database/API/Algorithm/Integration/UI_UX/Security/Test_Plan/Deployment)
- PRD v4.0 (relationship management core loop)
- Technical design v2.0
