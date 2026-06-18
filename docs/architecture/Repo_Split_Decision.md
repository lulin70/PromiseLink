# PromiseLink 仓库分开决策 (Repo Split Decision)

> **版本**: v1.0
> **日期**: 2026-06-18
> **决策状态**: 已批准 (Approved)
> **决策依据**: `docs/external/for_team/PromiseLink_代码安全规范_2026-06-17.md`
> **影响范围**: PromiseLink 基础版/专业版代码组织、CI/CD、发布流程

---

## 1. 决策背景

### 1.1 安全规范要求

《PromiseLink 代码安全规范》(2026-06-17) 第一章明确规定了代码分层与仓库策略：

| 层级 | 内容 | 仓库 | 访问权限 |
|------|------|------|----------|
| 基础版 | 本地 Docker + Taro H5 | 公开（AGPL v3） | 任何人 |
| 专业版 | 微信小程序 + 云端 API + 网关 | 私有 | 项目组成员 |
| 共享库 | 基础/专业共用的工具函数 | 公开子包或私有 npm | 按需 |

**铁律：不要用 monorepo + .gitignore 隔离公开和私有代码。** 一个人手滑 `push --force` 就全漏。

### 1.2 当前违规情况

当前 PromiseLink 仓库（`lulin70/PromiseLink`，公开）存在以下违规：

| 违规项 | 位置 | 风险等级 | 说明 |
|--------|------|----------|------|
| 专业版网关代码混入公开 repo | `gateway/` | 🔴 高 | 整个云端 AI 网关（含 API Key 池、计费、许可验证逻辑）在公开仓库 |
| 专业版服务模块混入公开 repo | `src/promiselink/services/` | 🟡 中 | ASR/TTS/OCR/NLU/NLG/邮件/微信转发等专业版服务模块在公开仓库 |
| 专业版 API 路由混入公开 repo | `src/promiselink/api/v1/` | 🟡 中 | voice/media/email_sync/wechat_forward/import_csv/privacy 等专业版路由在公开仓库 |
| 旧架构依赖"同代码库+配置区分" | `edition_architecture.md` §2 | 🟡 中 | 通过 `APP_EDITION` 配置区分，违反"双 repo"铁律 |

### 1.3 决策触发点

`gateway/` 目录是纯专业版代码（云端 AI 网关服务），不应出现在公开仓库。一旦公开仓库被 clone 或 fork，专业版核心商业逻辑（API Key 池管理、计费模型、许可验证）将完全泄露，直接摧毁专业版的商业护城河。

---

## 2. 决策方案

### 2.1 核心决策：双 repo + API 桥接

**放弃** 旧方案"同代码库 + `APP_EDITION` 配置区分"。
**采用** 新方案"双 repo + API 桥接"。

| 维度 | 旧方案（废弃） | 新方案（采用） |
|------|---------------|---------------|
| 代码组织 | 单一 monorepo，配置区分 | 双 repo，物理隔离 |
| 公开/私有隔离 | `.gitignore` + 配置开关 | 独立仓库 + 访问权限 |
| 版本区分 | `APP_EDITION=basic/pro` | 不同 repo，不同代码集 |
| 专业版保护 | 路由不注册（返回 404） | 代码不在公开 repo 中 |
| 桥接方式 | 无（同进程） | `relay_client` ↔ 网关 API |

### 2.2 仓库清单

| 仓库 | 地址 | 可见性 | 许可证 | 用途 |
|------|------|--------|--------|------|
| **基础版** | `lulin70/PromiseLink` | 🌐 公开 | AGPL v3 | 基础版全部代码 + `relay_client` 公开子包 |
| **专业版** | `lulin70/PromiseLink-Pro` | 🔒 私有 | 商业许可 (Commercial) | 网关 + 小程序 + 专业版特有代码 |

### 2.3 共享库策略

- **`relay_client`（公开子包）**：随基础版 repo 开源，作为基础版连接专业版网关的客户端模块。专业版用户本地 Docker 启用此模块即可连接网关。
- **网关 API（私有服务）**：专业版 repo 私有，作为独立云端服务运行。基础版通过 `relay_client` 经 WSS 连接网关。
- **基础版核心（公开依赖）**：专业版本地部署依赖基础版核心代码（通过 pip 安装或 git submodule 引入），在其上叠加专业版模块。

---

## 3. 代码归属划分

### 3.1 基础版 repo（`lulin70/PromiseLink`，公开 AGPL v3）

包含基础版全部代码及公开共享子包：

| 目录/文件 | 说明 | 备注 |
|-----------|------|------|
| `src/promiselink/core/` | 核心工具（auth, crypto, exceptions, logging, rate_limiter 等） | 基础版核心 |
| `src/promiselink/models/` | 数据模型（entity, event, todo, association, reminder, scheduled_event 等） | 基础版核心 |
| `src/promiselink/services/` | 基础版服务（event_pipeline, entity_extractor, todo_generator, promise_*, association_discovery, priority_scorer, semantic_search, llm_client, embedding_provider 等） | **仅保留基础版服务，专业版服务移出** |
| `src/promiselink/services/relay_client.py` | 🆕 网关中继客户端（公开子包） | 专业版用户启用，连接专业版网关 |
| `src/promiselink/api/v1/` | 基础版 API 路由（auth, events, entities, todos, promises, dashboard*, export, health, associations, demand_input, reminders, scheduled_events, relationship_briefs 等） | **仅保留基础版路由，专业版路由移出** |
| `src/promiselink/prompts/` | LLM Prompt 模板 | 基础版核心 |
| `src/promiselink/schemas/` | Pydantic schemas | 基础版核心 |
| `src/promiselink/alembic/` | 数据库迁移 | 基础版核心 |
| `src/promiselink/config.py` | 配置（保留 `APP_EDITION` 字段用于兼容，但基础版固定为 `basic`） | 基础版核心 |
| `src/promiselink/main.py` | FastAPI 入口（仅注册基础版路由） | 基础版核心 |
| `frontend/` | Taro H5 前端 | 基础版前端 |
| `tests/` | 基础版测试 | **移除专业版测试** |
| `scripts/` | 安装/启动/e2e 脚本 | 基础版工具 |
| `docs/` | 公开文档 | 基础版文档 |
| `monitoring/` | 监控配置 | 基础版运维 |
| `nginx/` | Nginx 配置 | 基础版运维 |
| 根目录配置 | `Dockerfile`, `docker-compose.basic.yml`, `pyproject.toml`, `requirements.txt`, `LICENSE`(AGPL v3), `README.md`, `CONTRIBUTING.md`, `SECURITY.md` 等 | 基础版工程文件 |

### 3.2 专业版 repo（`lulin70/PromiseLink-Pro`，私有商业许可）

包含专业版全部代码：

| 目录/文件 | 来源 | 说明 |
|-----------|------|------|
| `gateway/` | 从基础版 repo 迁入 | 云端 AI 网关（中继路由、AI 代理、Key 池、许可验证、计费） |
| `miniapp/` | 新建/从 `PromiseLink-miniapp` 整合 | 微信小程序（原生语音录入、TTS、名片扫描、WebView 查询） |
| `pro-services/` | 从 `src/promiselink/services/` 迁出 | 专业版服务模块：`asr_service.py`, `tts_service.py`, `ocr_service.py`, `nlu_intent_classifier.py`, `nlg_service.py`, `voice_query_service.py`, `email_adapter.py`, `wechat_forward_adapter.py` |
| `pro-api/` | 从 `src/promiselink/api/v1/` 迁出 | 专业版 API 路由：`voice.py`, `voice_query.py`, `media.py`, `email_sync.py`, `wechat_forward.py`, `import_csv.py`, `privacy.py` |
| `pro-config/` | 新建 | 专业版配置覆盖（`APP_EDITION=pro`, relay 设置, 媒体服务配置, PII 加密配置等） |
| `pro-migrations/` | 从 `src/promiselink/alembic/versions/` 迁出专业版相关 | 专业版特有表结构迁移（voice_sessions 等） |
| `pro-tests/` | 从 `tests/` 迁出专业版测试 | 专业版功能测试 |
| `deploy/` | 新建 | 专业版部署编排（网关 docker-compose、本地专业版 docker-compose） |
| 根目录配置 | 新建 | `pyproject.toml`(商业许可), `LICENSE`(商业), `README.md`(私有), CI 配置 |

### 3.3 专业版本地部署的代码组合

专业版用户本地 Docker 运行时，代码由两部分组合：

```
专业版本地 Docker 代码栈:
├── 基础版核心 (来自 PromiseLink repo, 公开)
│   └── pip install promiselink  或  git submodule
│       ├── src/promiselink/core/         (基础核心)
│       ├── src/promiselink/models/       (基础模型)
│       ├── src/promiselink/services/     (基础服务 + relay_client)
│       └── src/promiselink/api/v1/       (基础路由)
│
└── 专业版叠加 (来自 PromiseLink-Pro repo, 私有)
    ├── pro-services/    (专业服务: ASR/TTS/OCR/NLU/NLG/邮件/微信)
    ├── pro-api/         (专业路由: voice/media/email/wechat/csv/privacy)
    └── pro-config/      (专业配置: APP_EDITION=pro, relay 启用)
```

**依赖管理方式**（二选一，Phase 1 推荐 git submodule）：
- **git submodule**：专业版 repo 通过 submodule 引用基础版 repo 的特定 tag，构建时拉取
- **pip 包**：基础版发布到 PyPI/GitHub Packages，专业版 `pip install promiselink==<version>`

---

## 4. 数据流向

### 4.1 基础版 → 专业版网关（API 桥接）

```
┌─────────────────────────────────────────────────────────────┐
│  基础版 repo (公开 AGPL v3)          专业版 repo (私有商业)    │
│                                                             │
│  ┌──────────────────────┐         ┌──────────────────────┐ │
│  │  用户本地 Docker       │         │  云端 AI 网关         │ │
│  │  (基础版核心 + relay)  │         │  (gateway/)          │ │
│  │                      │  WSS    │                      │ │
│  │  relay_client ───────┼────────>│  中继路由器           │ │
│  │  (公开子包)           │  出站   │  AI代理层 ──> LLM API │ │
│  │                      │  连接   │  许可验证             │ │
│  │  基础版业务逻辑        │         │  用量计费             │ │
│  │  (事件/实体/待办/承诺) │         │                      │ │
│  └──────────────────────┘         └──────────────────────┘ │
│                                             ↑               │
│                                    微信小程序 (miniapp/)     │
│                                    HTTPS 直连网关            │
└─────────────────────────────────────────────────────────────┘
```

### 4.2 三场景 AI 调用路径

| 场景 | 用户状态 | 入口 | AI 后端 | Key 来源 | 网络要求 |
|------|----------|------|---------|----------|----------|
| 场景1 | 纯基础版（未付费） | 浏览器局域网 | 本地模型/自带 Key | 用户自备 | 完全离线可用 |
| 场景2 | 专业版 + 在家浏览器 | 浏览器局域网 | 云端 AI（我方 Key） | 网关代理 | 需联网验证 |
| 场景3 | 专业版 + 出门小程序 | 微信小程序 | 云端 AI（我方 Key） | 网关代理 | 正常路径 |

**场景2/3 数据流**：
```
基础版业务逻辑 (本地) 
    → 标注 X-AI-Call 请求头
    → relay_client (公开子包, 本地)
    → WSS 出站连接
    → 专业版网关 (私有, 云端)
    → LLM API (DeepSeek/Moka AI)
    → 原路返回
```

### 4.3 隐私边界（不变）

- 业务数据（关系/事件/实体）始终存储在用户本地 Docker（SQLite）
- 网关仅做加密中继 + AI 代理，不持久化业务内容
- `relay_client` 仅传输 JWT 令牌（用户 ID + 付费状态）和 AI 调用 payload

---

## 5. 迁移计划

### 5.1 Phase 1：立即迁移（阻断泄漏）

**目标**：将 `gateway/` 目录从公开 repo 移至私有 repo，消除最高风险。

| 步骤 | 操作 | 负责人 | 验证方法 |
|------|------|--------|----------|
| 1 | 创建私有 repo `lulin70/PromiseLink-Pro` | DevOps | repo 可访问且为 private |
| 2 | 将 `gateway/` 目录完整复制到 `PromiseLink-Pro/gateway/` | Coder | 文件完整性校验 |
| 3 | 在私有 repo 配置 CI、pre-commit hook、分支保护 | DevOps | CI 流水线可运行 |
| 4 | 从公开 repo `lulin70/PromiseLink` 删除 `gateway/` 目录 | Coder | `git log` 确认删除 |
| 5 | 清理公开 repo git history 中的 gateway 残留（`git filter-repo`） | DevOps | `git log -- gateway/` 无记录 |
| 6 | 公开 repo 添加 `.gitignore` 防止 gateway/ 被重新加入 | Coder | 提交 gateway/ 被 reject |
| 7 | 更新公开 repo 的 `pyproject.toml`/`requirements.txt` 移除 gateway 依赖 | Coder | 基础版测试全绿 |

**⚠️ 关键**：步骤 5 必须清理 git history，否则通过 `git log -p` 仍可获取历史版本的专业版代码。

### 5.2 Phase 2：专业版服务模块迁移

**目标**：将专业版服务模块和 API 路由从公开 repo 移至私有 repo。

| 步骤 | 操作 | 验证方法 |
|------|------|----------|
| 1 | 将专业版服务模块迁至 `PromiseLink-Pro/pro-services/` | 模块导入正常 |
| 2 | 将专业版 API 路由迁至 `PromiseLink-Pro/pro-api/` | 路由注册正常 |
| 3 | 公开 repo 移除上述模块，清理 git history | 公开 repo 无专业版代码 |
| 4 | 公开 repo 基础版测试全绿（移除专业版测试） | `pytest` 通过 |
| 5 | 专业版 repo 配置 git submodule 引用基础版 repo | submodule 可拉取 |
| 6 | 专业版本地 Docker 构建验证（基础核心 + 专业叠加） | docker-compose up 成功 |

**涉及文件清单**（从公开 repo 迁出）：
- 服务：`asr_service.py`, `tts_service.py`, `ocr_service.py`, `nlu_intent_classifier.py`, `nlg_service.py`, `voice_query_service.py`, `email_adapter.py`, `wechat_forward_adapter.py`
- 路由：`voice.py`, `voice_query.py`, `media.py`, `email_sync.py`, `wechat_forward.py`, `import_csv.py`, `privacy.py`
- 测试：对应的 `test_voice_api.py`, `test_voice_query_api.py`, `test_media_api.py`, `test_email_adapter.py`, `test_wechat_forward_*.py`, `test_import_csv_api.py`, `test_nlu_intent_classifier.py`, `test_nlg_service.py`, `test_tts_service.py`

### 5.3 Phase 3：小程序整合

**目标**：将微信小程序代码整合到专业版 repo。

| 步骤 | 操作 | 验证方法 |
|------|------|----------|
| 1 | 将 `lulin70/PromiseLink-miniapp` 迁移/整合到 `PromiseLink-Pro/miniapp/` | 小程序可编译 |
| 2 | 更新小程序的 API 地址指向专业版网关 | 网络请求正常 |
| 3 | 原 miniapp repo 归档或设为私有 | repo 不可公开访问 |

### 5.4 迁移时间线

| 阶段 | 内容 | 时间窗口 | 优先级 |
|------|------|----------|--------|
| Phase 1 | gateway/ 迁移 + history 清理 | 1-2 天 | 🔴 立即执行 |
| Phase 2 | 专业版服务/路由迁移 | 3-5 天 | 🟡 公开发布前完成 |
| Phase 3 | 小程序整合 | 1-2 天 | 🟢 专业版发布前完成 |

---

## 6. 风险评估

### 6.1 技术风险

| 风险 | 等级 | 影响 | 缓解措施 |
|------|------|------|----------|
| git history 残留专业版代码 | 🔴 高 | 攻击者通过 `git log -p` 获取历史版本 | 使用 `git filter-repo` 彻底清理，清理后重新 force push |
| 双 repo 代码同步困难 | 🟡 中 | 基础版升级后专业版需跟进 | 使用 git submodule 锁定 tag + 自动化同步检测 CI |
| 专业版依赖基础版核心，基础版 breaking change | 🟡 中 | 专业版构建失败 | 基础版遵循 semver，专业版 CI 锁定兼容版本范围 |
| relay_client 接口与网关协议不一致 | 🟡 中 | 专业版用户连接失败 | 协议版本化 + 集成测试覆盖 relay ↔ gateway 链路 |
| 公开 repo 误提交专业版代码 | 🟡 中 | 二次泄漏 | pre-commit hook 检查专业版文件名模式 + CI 扫描 |

### 6.2 业务风险

| 风险 | 等级 | 影响 | 缓解措施 |
|------|------|------|----------|
| 专业版开发效率降低（双 repo 切换） | 🟡 中 | 开发体验下降 | 使用 git submodule 一键拉取，IDE 多 repo 工作区 |
| 基础版开源社区贡献无法直接用于专业版 | 🟢 低 | 部分贡献需人工移植 | 接受此代价，换取安全隔离 |
| 公开 repo 迁移期间服务中断 | 🟢 低 | 短期不可用 | 迁移在低峰期进行，基础版用户无感知 |

### 6.3 安全风险

| 风险 | 等级 | 影响 | 缓解措施 |
|------|------|------|----------|
| 迁移前历史已泄露 | 🔴 高 | 专业版代码可能已被 clone | 1) 立即迁移 2) 审计 GitHub fork 列表 3) 考虑重构核心算法逻辑 |
| 私有 repo 权限管理不当 | 🟡 中 | 离职员工带走代码 | 禁止 fork、分支保护、离职当天撤销权限、定期审查成员 |
| LLM API Key 泄露 | 🔴 高 | 直接经济损失 | Key 仅存网关侧环境变量，不入 repo，pre-commit hook 拦截 |

### 6.4 迁移后验证清单

| # | 验证项 | 验证方法 | 通过标准 |
|---|--------|----------|----------|
| 1 | 公开 repo 无 gateway/ 目录 | `ls gateway/` | 目录不存在 |
| 2 | 公开 repo git history 无 gateway 记录 | `git log --all -- gateway/` | 无任何 commit |
| 3 | 公开 repo 无专业版服务模块 | `ls src/promiselink/services/asr_service.py` | 文件不存在 |
| 4 | 公开 repo 基础版测试全绿 | `pytest tests/` | 全部通过 |
| 5 | 公开 repo 基础版可独立运行 | `docker-compose -f docker-compose.basic.yml up` | 服务正常启动 |
| 6 | 私有 repo 网关可运行 | `docker-compose -f deploy/gateway.yml up` | 网关正常启动 |
| 7 | 专业版本地 Docker 可组合运行 | 基础核心 + 专业叠加构建 | 服务正常启动 |
| 8 | relay_client 可连接网关 | 集成测试 | WSS 连接建立成功 |
| 9 | 私有 repo 可见性为 private | GitHub repo 设置 | 可见性 = private |
| 10 | 公开 repo LICENSE 为 AGPL v3 | `cat LICENSE` | AGPL v3 全文 |

---

## 7. 决策记录

| 维度 | 内容 |
|------|------|
| **决策** | 基础版和专业版分 repo：PromiseLink（公开 AGPL v3）+ PromiseLink-Pro（私有商业许可） |
| **决策日期** | 2026-06-18 |
| **决策依据** | 《PromiseLink 代码安全规范》铁律：不用 monorepo + .gitignore 隔离公开和私有代码 |
| **替代方案** | ① monorepo + .gitignore（否决：违反铁律）② 同代码库 + 配置区分（否决：专业版代码仍泄露）③ 双 repo + API 桥接（采用） |
| **影响文档** | `edition_architecture.md`、`Pro_Edition_Architecture.md`、`project_memory.md` |
| **执行负责人** | 待分配 |
| **完成标准** | 见 §6.4 迁移后验证清单（10 项全部通过） |

---

## 8. 附录

### 8.1 相关文档

- `docs/external/for_team/PromiseLink_代码安全规范_2026-06-17.md` — 代码安全规范（决策依据）
- `docs/architecture/edition_architecture.md` — 版本架构（已更新仓库策略章节）
- `docs/architecture/Pro_Edition_Architecture.md` — 专业版架构（已更新部署架构）
- `docs/planning/Pro_Edition_Implementation_Plan.md` — 专业版实现计划

### 8.2 git filter-repo 清理命令参考

```bash
# 安装 git-filter-repo
pip install git-filter-repo

# 在公开 repo 中彻底移除 gateway/ 的所有历史记录
cd PromiseLink
git filter-repo --path gateway/ --invert-paths

# 验证清理结果
git log --all -- gateway/  # 应无输出

# 强制推送（⚠️ 需团队协调，会重写历史）
git push origin --force --all
git push origin --force --tags
```

> ⚠️ `git filter-repo` 会重写所有 commit hash，执行前需：1) 通知所有协作者 2) 备份 repo 3) 协作者重新 clone。
