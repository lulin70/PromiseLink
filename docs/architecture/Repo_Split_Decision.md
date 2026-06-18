# PromiseLink 仓库分开决策 (Repo Split Decision)

> **版本**: v1.2
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

**依赖管理方式**：
- **git submodule**：专业版 repo 通过 submodule 引用基础版 repo 的特定 tag，构建时拉取
- **pip 包**：基础版发布到 PyPI/GitHub Packages，专业版 `pip install promiselink==<version>`

### 3.4 预构建 Docker 镜像策略（用户一键安装）

> **核心原则**：两个 repo 是开发者和 CI 的事，不是用户的事。用户一键安装只看到一个 Docker 镜像。

**问题**：如果让用户手动 clone 两个 repo 再组装（clone 基础版 → 配 git submodule → 授权 GitHub 访问私有 repo → docker build），体验极差，且普通用户没有 GitHub 私有 repo 访问权限。

**方案**：在 CI（GitHub Actions）中预构建包含"基础版核心 + 专业版叠加"的完整 Docker 镜像，推送到私有容器 Registry（ghcr.io），用户只需 pull 镜像 + 提供 License Key。

```
用户视角的安装流程:
  (1) 拿到 License Key
  (2) docker login ghcr.io -u <username> -p <license_token>
  (3) docker compose -f docker-compose.pro.yml up

CI 构建流程 (在 PromiseLink-Pro 私有 repo 的 GitHub Actions 中执行):
  (1) git submodule update --init        # 拉基础版核心
  (2) 将 pro-services/ pro-api/ pro-config/ 合并到镜像
  (3) docker build -t ghcr.io/lulin70/promiselink-pro:latest
  (4) docker push ghcr.io/lulin70/promiselink-pro:latest
```

**用户拿到的 `docker-compose.pro.yml`**（极简，单个镜像）：

```yaml
services:
  promiselink-pro:
    image: ghcr.io/lulin70/promiselink-pro:latest
    environment:
      - LICENSE_KEY=${LICENSE_KEY}
      - TZ=Asia/Shanghai
    ports:
      - "3000:3000"
    volumes:
      - ./data:/app/data    # 业务数据始终在本地
    restart: unless-stopped
```

**三个安装场景的 repo 涉及量（用户视角）**：

| 用户类型 | 安装命令 | 用户接触的 repo 数 | 需要 GitHub 授权 |
|----------|---------|-------------------|-----------------|
| 基础版 | `git clone` → `docker compose up` | 1 个（公开） | 无需 |
| 专业版 Docker | `docker login ghcr.io` → `docker compose up` | 0 个 | 无需（License Key 验证） |
| 专业版开发者 | `git clone pro-repo` → `git submodule update` | 2 个（公开+私有） | 需要（私有 repo 访问） |

**镜像仓库访问控制**：
- `ghcr.io/lulin70/promiselink-pro` 为 **private** 容器镜像
- 用户通过 License Key 换取临时 pull token（有效期 24h），而非直接授予 GitHub 权限
- License 过期后 pull token 自动失效，已下载的镜像仍可本地运行（业务数据不受影响）

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
| 7 | 配置 CI 预构建 Docker 镜像 + 推送 ghcr.io（§3.4） | 镜像可 pull 且正常运行 |

**涉及文件清单**（从公开 repo 迁出）：
- 服务：`asr_service.py`, `tts_service.py`, `ocr_service.py`, `nlu_intent_classifier.py`, `nlg_service.py`, `voice_query_service.py`, `email_adapter.py`, `wechat_forward_adapter.py`
- 路由：`voice.py`, `voice_query.py`, `media.py`, `email_sync.py`, `wechat_forward.py`, `import_csv.py`, `privacy.py`
- 测试：对应的 `test_voice_api.py`, `test_voice_query_api.py`, `test_media_api.py`, `test_email_adapter.py`, `test_wechat_forward_*.py`, `test_import_csv_api.py`, `test_nlu_intent_classifier.py`, `test_nlg_service.py`, `test_tts_service.py`

### 5.3 Phase 3：小程序整合

**目标**：将微信小程序代码整合到专业版 repo，消除独立的 `PromiseLink-miniapp` 仓库。

**合并决策说明（v1.2补充）**：

原 `lulin70/PromiseLink-miniapp` 独立仓库存在以下问题，决定合并到 `PromiseLink-Pro/miniapp/` 目录：

| 问题 | 影响 | 合并后解决方式 |
|------|------|---------------|
| 小程序与网关强耦合（API地址/认证/中继协议） | 分仓库导致接口变更需跨repo协调 | 同repo内同步修改，CI统一验证 |
| 小程序为专业版专属（基础版用H5） | 独立仓库误导社区认为可独立使用 | 物理归入专业版repo，明确专业版属性 |
| 三仓库（Standard/Pro/miniapp）维护成本高 | 版本对齐困难，release流程复杂 | 收敛为双仓库（PromiseLink + PromiseLink-Pro） |
| 小程序代码含专业版商业逻辑 | 独立公开repo有泄露风险 | 随Pro repo私有化 |

**合并步骤**：

| 步骤 | 操作 | 验证方法 |
|------|------|----------|
| 1 | 将 `lulin70/PromiseLink-miniapp` 迁移/整合到 `PromiseLink-Pro/miniapp/` | 小程序可编译 |
| 2 | 更新小程序的 API 地址指向专业版网关 | 网络请求正常 |
| 3 | 原 miniapp repo 归档或设为私有 | repo 不可公开访问 |
| 4 | 更新 `PromiseLink-Pro/miniapp/` 的 CI 配置，接入专业版流水线 | CI 可运行 |
| 5 | 清理原 miniapp repo 的 git history（如有敏感配置） | `git log` 无敏感信息 |

**合并后的目录结构**：

```
PromiseLink-Pro/                # 专业版仓库（私有）
├── gateway/                    # 云端AI网关
├── miniapp/                    # 微信小程序（原 PromiseLink-miniapp 合并至此）
│   ├── src/                    # 小程序源码
│   ├── project.config.json     # 微信开发者工具配置
│   ├── package.json            # 依赖管理
│   └── README.md               # 小程序开发说明
├── pro-services/               # 专业版服务模块
├── pro-api/                    # 专业版API路由
└── deploy/                     # 部署编排
```

**对基础版的影响**：无。基础版使用 Taro H5 前端（`PromiseLink/frontend/`），与小程序代码完全独立，不共享样式/组件/布局（见 PRD §1.5.7 UI布局策略）。

### 5.4 迁移时间线

| 阶段 | 内容 | 时间窗口 | 优先级 |
|------|------|----------|--------|
| Phase 1 | gateway/ 迁移 + history 清理 | 1-2 天 | 🔴 立即执行 |
| Phase 2 | 专业版服务/路由迁移 | 3-5 天 | 🟡 公开发布前完成 |
| Phase 3 | 小程序整合 | 1-2 天 | 🟢 专业版发布前完成 |

### 5.5 miniapp 仓库独立决策（v1.2 更新）

> **本节为 v1.2 新增决策，取代 §5.3 Phase 3 的"小程序合并到 PromiseLink-Pro"方案。**

**决策**：`PromiseLink-miniapp` 保留独立仓库，不合并到 `PromiseLink-Pro/miniapp/`。

**决策原因**：

1. **独立构建与部署流程**：微信小程序需要独立的构建工具链（微信开发者工具）、独立的审核发布流程（微信小程序平台审核）和独立的版本管理，与后端代码的构建部署流程完全不同。
2. **基础版与专业版共用**：小程序并非专业版专属，基础版和专业版都可能使用小程序入口。若将小程序并入专业版私有仓库，基础版（公开仓库）用户将无法使用小程序，限制了基础版的可访问性。
3. **独立 CI/CD**：小程序的 CI/CD 流程（编译、预览、上传、审核）与后端服务差异显著，独立仓库便于配置专属的小程序发布流水线。

**最终仓库结构**：

| 仓库 | 可见性 | 用途 |
|------|--------|------|
| `PromiseLink` | 🌐 公开（AGPL v3） | 基础版全部代码 |
| `PromiseLink-Pro` | 🔒 私有（商业许可） | 专业版网关 + 专业版特有代码 |
| `PromiseLink-miniapp` | 🔒 私有（商业许可） | 微信小程序（独立构建与部署） |

**对 §5.3 Phase 3 的影响**：§5.3 的合并步骤不再执行。`PromiseLink-miniapp` 保持独立仓库，通过 API 契约与 `PromiseLink`（基础版）和 `PromiseLink-Pro`（专业版网关）解耦协作。

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
| 11 | CI 预构建镜像推送到 ghcr.io | `docker pull ghcr.io/lulin70/promiselink-pro:latest` | 镜像可拉取 |
| 12 | 专业版用户一键安装可用 | `docker compose -f docker-compose.pro.yml up` | 服务正常启动，无需 clone 任何 repo |

---

## 7. 法律合规分析（AGPL v3 传染边界）

> **背景**：基础版采用 AGPL v3 开源，专业版为商业闭源。需明确 AGPL v3 的"传染性"（copyleft）边界，确保专业版商业模式合法合规。本节为技术团队初步评估，正式发布前需由法律顾问出具书面意见。

### 7.1 AGPL v3 传染性基本规则

AGPL v3（GNU Affero General Public License v3）的核心传染规则：

| 触发条件 | 是否传染 | 说明 |
|----------|----------|------|
| 修改 AGPL v3 源码并分发 | ✅ 传染 | 修改后的代码必须以 AGPL v3 开源 |
| 修改 AGPL v3 源码并通过网络提供服务 | ✅ 传染 | AGPL v3 独有的"网络交互"条款，即使不分发也触发 |
| 静态链接 AGPL v3 代码 | ✅ 传染 | 静态链接构成"衍生作品" |
| 动态链接 AGPL v3 代码 | ⚠️ 争议 | FSF 认为传染，部分法律观点认为不传染，保守起见视为传染 |
| 独立进程通过管道/命令行调用 AGPL v3 程序 | ❌ 不传染 | 独立程序间通信不构成"衍生作品" |
| 通过网络 API 调用 AGPL v3 服务 | ❌ 不传染 | 网络通信不构成"链接" |
| 仅运行未修改的 AGPL v3 程序 | ❌ 不传染 | 未修改+未分发，不触发 copyleft |

### 7.2 PromiseLink 各集成场景的传染性分析

| 集成场景 | 技术方式 | 是否触发 AGPL v3 传染 | 分析依据 |
|----------|----------|----------------------|----------|
| **专业版通过 pip install promiselink 安装基础版核心** | Python 包依赖，import 调用 | ⚠️ 需进一步分析 | Python import 是否构成"链接"存在法律争议。FSF 倾向于认为 import 构成衍生作品，但若专业版**不修改**基础版源码、仅作为库调用，且基础版以独立进程运行（如通过 subprocess 或 HTTP），则不传染 |
| **专业版通过 git submodule 引用基础版** | 源码级引用，编译时包含 | ✅ 触发传染 | submodule 将基础版源码纳入专业版构建，构成"衍生作品"，专业版必须开源 |
| **专业版通过 HTTP API 调用基础版（独立进程）** | 网络通信，两进程独立 | ❌ 不传染 | 独立进程间通过 HTTP 通信，不构成"链接"，类似 Apache/nginx 与 GPL 模块的边界 |
| **relay_client 通过 WSS 调用网关** | 网络通信 | ❌ 不传染 | relay_client（基础版公开子包）与网关（专业版私有）通过 WebSocket 通信，独立进程，不传染 |
| **WebView 嵌入基础版 H5 页面** | 浏览器嵌入 | ⚠️ 需法律确认 | WebView 加载 H5 类似浏览器访问网页，理论上不传染。但若 H5 与小程序原生代码深度交互（JS Bridge），可能被视为"链接"。需法律确认是否适用 MPL 2.0 或 AGPL v3 例外条款 |

### 7.3 推荐方案：pip install + 独立进程通信

**推荐的专业版依赖基础版核心的方式**：

```
✅ 推荐：pip install promiselink
   ├── 专业版不修改基础版源码
   ├── 基础版作为 Python 库被 import 调用
   ├── 专业版叠加层（pro-services/pro-api）为独立代码
   └── 商业风险：中等（Python import 的传染性存在争议）

❌ 不推荐：git submodule
   ├── 专业版构建时包含基础版完整源码
   ├── 构成"衍生作品"，触发 AGPL v3 copyleft
   └── 专业版必须开源，商业模式失效

✅ 最安全：HTTP API 独立进程
   ├── 基础版作为独立服务运行（FastAPI 进程）
   ├── 专业版通过 HTTP 调用基础版 API
   ├── 两进程独立，不构成"链接"
   └── 商业风险：低（但增加进程间通信开销）
```

**当前架构决策**（§3.3 专业版本地部署的代码组合）：
- 采用 `pip install promiselink` 方式引入基础版核心
- 专业版叠加层（pro-services/pro-api）为独立代码，不修改基础版源码
- 若法律审查认为 Python import 仍触发传染，降级为 HTTP API 独立进程方案

### 7.4 各组件 License 边界汇总

| 组件 | 所在仓库 | License | 传染风险 |
|------|----------|---------|----------|
| 基础版核心（管线/实体/Todo/Promise/关联） | PromiseLink（公开） | AGPL v3 | 源头 |
| relay_client（网关中继客户端） | PromiseLink（公开） | AGPL v3 | 随基础版开源，专业版可使用 |
| 网关（gateway/） | PromiseLink-Pro（私有） | 商业许可 | ❌ 不传染（独立进程，HTTP/WSS 通信） |
| 微信小程序（miniapp/） | PromiseLink-Pro（私有） | 商业许可 | ⚠️ WebView 嵌入基础版 H5 需法律确认 |
| 专业版服务（pro-services/） | PromiseLink-Pro（私有） | 商业许可 | ⚠️ 若 import 基础版，需法律确认 |
| promiselink-contracts（协议层） | 公开 | MIT | ❌ 不传染（MIT 允许闭源使用） |
| promiselink-utils（工具层） | 公开 | MIT | ❌ 不传染（MIT 允许闭源使用） |

### 7.5 风险缓解措施

1. **基础版核心不修改原则**：专业版通过 pip 安装基础版，**不修改任何基础版源码**。如需定制行为，通过配置项/插件机制/子类继承实现，而非直接修改源文件。
2. **共享协议层用 MIT**：`promiselink-contracts` 和 `promiselink-utils` 采用 MIT License，专业版可自由使用不触发传染。
3. **WebView 嵌入方案备选**：若法律审查认为 WebView 嵌入 AGPL v3 H5 触发传染，备选方案为：① 基础版 H5 改用 MPL 2.0（弱 copyleft，文件级隔离）② 专业版小程序自建查询页面，不嵌入基础版 H5。
4. **法律审查清单**：正式发布前完成以下法律审查：
   - [ ] Python import AGPL v3 包是否构成"衍生作品"（针对 pip install 方案）
   - [ ] WebView 嵌入 AGPL v3 H5 是否触发传染（针对小程序 WebView 方案）
   - [ ] AGPL v3 §13"网络交互"条款对专业版云端部署的适用性
   - [ ] 商业 License 与 AGPL v3 的兼容性声明

### 7.6 免责声明

> ⚠️ **本节分析为技术团队基于对 AGPL v3 的理解所做的初步评估，不构成法律意见。** AGPL v3 的传染性边界在法律实践中存在争议，特别是 Python import、动态链接、WebView 嵌入等场景的判定因司法管辖区而异。**正式发布前，必须由具备开源协议经验的执业律师出具书面法律意见。** 本团队不对本节分析的准确性承担法律责任。

---

## 8. 决策记录

| 维度 | 内容 |
|------|------|
| **决策** | 基础版、专业版、小程序分 repo：PromiseLink（公开 AGPL v3）+ PromiseLink-Pro（私有商业许可）+ PromiseLink-miniapp（私有商业许可，独立构建部署） |
| **决策日期** | 2026-06-18 |
| **决策依据** | 《PromiseLink 代码安全规范》铁律：不用 monorepo + .gitignore 隔离公开和私有代码 |
| **替代方案** | ① monorepo + .gitignore（否决：违反铁律）② 同代码库 + 配置区分（否决：专业版代码仍泄露）③ 双 repo + API 桥接（采用） |
| **影响文档** | `edition_architecture.md`、`Pro_Edition_Architecture.md`、`project_memory.md` |
| **执行负责人** | 待分配 |
| **完成标准** | 见 §6.4 迁移后验证清单（10 项全部通过） |

---

## 9. 附录

### 9.1 相关文档

- `docs/external/for_team/PromiseLink_代码安全规范_2026-06-17.md` — 代码安全规范（决策依据）
- `docs/architecture/edition_architecture.md` — 版本架构（已更新仓库策略章节）
- `docs/architecture/Pro_Edition_Architecture.md` — 专业版架构（已更新部署架构）
- `docs/planning/Pro_Edition_Implementation_Plan.md` — 专业版实现计划

### 9.2 git filter-repo 清理命令参考

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
