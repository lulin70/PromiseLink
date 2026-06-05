# EventLink 部署指南

> **版本**: 0.2.0（POC阶段）
> **日期**: 2026-06-04
> **定位**: AI驱动的个人商务关系经营助手 — 先成就关系，再促成合作
> **参考**: 技术设计 v2.5 §9（部署架构与数据主权）、§8.0.5（监控指标）、§8.0.6（数据库迁移策略）
> **技术栈**: Python 3.11 / FastAPI / httpx async / Pydantic v2

---

## 1. 部署概述

### 1.1 三阶段部署策略

EventLink采用渐进式部署策略，从零成本PoC验证逐步演进到生产级K8s集群：

| 阶段 | 基础设施 | 数据库 | 缓存 | 成本 | 用户规模 | 目标 |
|------|----------|--------|------|------|----------|------|
| **PoC** | 本地 Docker Desktop | SQLite | 无 | 零云成本 | 单用户 | 概念验证、核心流程跑通 |
| **Phase1** | 云端 Docker Compose | PostgreSQL 16 | Redis 7 | ~200元/月 | 单用户（小程序上线） | 生产可用、微信小程序接入 |
| **Phase2** | K8s 集群 | PG + 读写分离 | Redis Cluster | 按需 | 多用户 | 高可用、弹性扩缩容 |

**关键约束**：
- 不做原生APP，微信小程序是主入口
- LLM推理走云端API（OpenAI/Anthropic/Moka AI），不部署本地模型
- PoC阶段零云成本，所有服务运行在本地Docker内
- **数据主权**：数据属于用户，EventLink是processor不是owner（详见 §8.6.5）

### 1.2 环境要求表

| 项目 | PoC | Phase1 | Phase2 |
|------|-----|--------|--------|
| **操作系统** | macOS / Linux / Windows(WSL2) | Ubuntu 22.04+ / CentOS 8+ | K8s 兼容 OS |
| **Docker** | Docker Desktop 24+ | Docker Engine 24+ | containerd |
| **Docker Compose** | v2.20+ | v2.20+ | N/A（Helm） |
| **Python** | 3.11+（宿主机调试用） | N/A（容器内） | N/A |
| **内存** | ≥4GB 可用 | ≥4GB 可用 | 按Pod配置 |
| **磁盘** | ≥2GB 可用 | ≥20GB 可用 | PVC 按需 |
| **CPU** | ≥2核 | ≥2核 | 按Pod配置 |
| **网络** | 需访问LLM API | 需公网IP+域名 | 集群内网络 |
| **LLM API Key** | 必需 | 必需 | 必需 |

---

## 2. PoC本地部署

### 2.1 前置条件

| 依赖 | 版本要求 | 安装验证 | 说明 |
|------|----------|----------|------|
| Docker Desktop | 24+ | `docker --version` | 包含Docker Compose |
| Python | 3.11+ | `python3 --version` | 仅宿主机调试时需要 |
| LLM API Key | - | - | OpenAI / Anthropic / Moka AI 任选其一 |

### 2.2 快速启动（5步完成）

```bash
# 1. 克隆项目
git clone <repo-url> && cd EventLink

# 2. 创建环境配置
cp .env.poc.example .env.poc

# 3. 编辑配置，填入必填项
#    EVENTLINK_SECRET_KEY=（执行下方命令生成）
#    LLM_API_KEY=（填入你的API Key）
#    LLM_BASE_URL=（填入对应的API地址）
python3 -c "import secrets; print(secrets.token_urlsafe(32))"
# 将输出值填入 EVENTLINK_SECRET_KEY

# 4. 构建并启动服务
docker compose -f docker-compose.poc.yml up -d --build

# 5. 验证服务
curl http://localhost:8000/api/v1/health
```

预期健康检查响应：

```json
{
  "status": "healthy",
  "version": "0.2.0",
  "stage": "poc"
}
```

### 2.3 Dockerfile多阶段构建说明 [0.2.0新增]

[0.2.0新增] 当前Dockerfile采用**多阶段构建（Multi-stage Build）**策略，将构建依赖与运行时分离，生成最小化生产镜像：

```
┌─────────────────────────────────┐     ┌─────────────────────────────────┐
│ Stage 1: Builder                │     │ Stage 2: Runtime                │
│ 基础镜像: python:3.11-slim      │────▶│ 基础镜像: python:3.11-slim      │
│                                 │ COPY│                                 │
│ • 安装 gcc + libpq-dev（编译依赖）│──/opt/venv──▶│ • 安装 libpq5 + curl（运行依赖） │
│ • 创建 venv /opt/venv           │     │ • 创建 eventlink 非 root 用户    │
│ • pip install -r requirements.txt│     │ • 复制 venv + 应用代码          │
│                                 │     │ • HEALTHCHECK /api/v1/health    │
│ （此阶段产物不进入最终镜像）       │     │ • CMD uvicorn 启动              │
└─────────────────────────────────┘     └─────────────────────────────────┘
```

**Stage 1 — Builder（构建阶段）**：

| 配置项 | 值 | 说明 |
|--------|-----|------|
| 基础镜像 | `python:3.11-slim` | 轻量Python基础镜像 |
| 工作目录 | `/build` | 构建专用目录 |
| 编译依赖 | `gcc`, `libpq-dev` | psycopg2等C扩展编译所需（最终镜像不包含） |
| 虚拟环境 | `/opt/venv` | 隔离Python依赖 |
| 产出物 | `/opt/venv` 完整虚拟环境 | 通过 `COPY --from=builder` 传递 |

**Stage 2 — Runtime（运行时阶段）**：

| 配置项 | 值 | 说明 |
|--------|-----|------|
| 基础镜像 | `python:3.11-slim` | 与Builder同系列，确保兼容性 |
| 运行依赖 | `libpq5`, `curl` | PostgreSQL客户端库 + 健康检查工具 |
| 运行用户 | `eventlink`（非root, UID随机） | 安全最佳实践 |
| 工作目录 | `/app/src` | 确保Python可找到eventlink包 |
| 数据目录 | `/data`（eventlink用户所有） | SQLite持久化目录 |
| 暴露端口 | `8000` | FastAPI/Uvicorn |
| 健康检查 | `HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3` | 探测 `/api/v1/health` |
| 启动命令 | `uvicorn eventlink.main:app --host 0.0.0.0 --port 8000` | 异步ASGI服务器 |

**镜像优势**：
- 最终镜像仅包含运行时依赖（无gcc/libpq-dev等构建工具）
- 非 root 用户运行，降低安全风险
- 内置健康检查，支持Docker Compose/K8s自动探测
- SQLite数据目录权限正确归属eventlink用户

### 2.4 docker-compose.poc.yml 使用说明 [0.2.0更新]

> [0.2.0更新] 已确认 `docker-compose.poc.yml` 与实际文件完全一致，包含以下完整配置。

PoC阶段默认启动单个API服务容器（`eventlink-api`），同时预定义了PostgreSQL和Redis服务供Phase1启用：

**核心服务（eventlink-api）配置**：

| 配置项 | 值 | 说明 |
|--------|-----|------|
| 镜像 | `eventlink:poc` | 本地构建（context: .） |
| 端口 | `8000:8000` | FastAPI / Uvicorn |
| 环境变量 | `.env.poc` 文件加载 | 支持 `EVENTLINK_STAGE`, `EVENTLINK_DB_PATH` 覆盖 |
| 数据卷 | `./data:/data` | SQLite持久化（容器内路径 `/data`） |
| 内存限制 | **512M**（预留128M） | SQLite+FastAPI足够，LLM走云端不占本地内存 |
| CPU限制 | **1.0核**（预留0.25核） | 单用户场景无需多核 |
| 健康检查 | `/api/v1/health` | 30s间隔，10s超时，3次重试，40s启动等待期 |
| 重启策略 | `unless-stopped` | 异常自动重启，手动停止除外 |
| 日志轮转 | json-file驱动，10MB×3文件 | 防止日志无限增长占满磁盘 |
| 网络 | `eventlink-poc-net`（bridge） | 独立桥接网络，为后续扩展预留隔离空间 |

**可选服务（PoC默认不启动，Phase1启用）**：

| 服务 | 镜像 | 用途 | 状态 |
|------|------|------|------|
| `postgres` | `postgres:16-alpine` | Phase1主数据库 | 已定义，默认注释 |
| `redis` | `redis:7-alpine` | Phase1缓存与会话存储 | 已定义，默认注释 |

**常用命令**：

```bash
# 启动服务（仅eventlink-api）
docker compose -f docker-compose.poc.yml up -d --build

# 查看日志
docker compose -f docker-compose.poc.yml logs -f

# 查看服务状态
docker compose -f docker-compose.poc.yml ps

# 停止服务（数据保留）
docker compose -f docker-compose.poc.yml down

# 停止并清除数据
docker compose -f docker-compose.poc.yml down -v

# Phase1：启动含PG+Redis的完整栈
docker compose -f docker-compose.poc.yml up -d postgres redis eventlink-api
```

### 2.5 .env.poc 配置说明

| 变量 | 默认值 | 必填 | 说明 |
|------|--------|------|------|
| `EVENTLINK_STAGE` | `poc` | 否 | 运行阶段标识 |
| `EVENTLINK_DB_PATH` | `/data/eventlink_poc.db` | 否 | SQLite容器内路径 |
| `EVENTLINK_SECRET_KEY` | - | **是** | JWT签名密钥，用 `secrets.token_urlsafe(32)` 生成 |
| `EVENTLINK_JWT_PRIVATE_KEY_PATH` | - | 否 | JWT私钥路径（PoC用HS256可不填） |
| `EVENTLINK_JWT_PUBLIC_KEY_PATH` | - | 否 | JWT公钥路径 |
| `LLM_API_KEY` | - | **是** | LLM API密钥 |
| `LLM_BASE_URL` | - | **是** | LLM API地址 |
| `LLM_MODEL` | `gpt-4` | 否 | 模型名称 |
| `LLM_TIMEOUT` | `30` | 否 | 请求超时（秒） |
| `LLM_MAX_RETRIES` | `3` | 否 | 最大重试次数 |
| `EVENTLINK_LOG_LEVEL` | `INFO` | 否 | 日志级别 |
| `EVENTLINK_CORS_ORIGINS` | `http://localhost:3000` | 否 | CORS允许来源 |

### 2.6 数据目录说明

```
EventLink/
├── data/                        # 持久化数据目录（git已忽略）
│   └── eventlink_poc.db         # SQLite数据库文件
├── .env.poc                     # 环境变量（git已忽略）
├── docker-compose.poc.yml       # PoC编排文件
└── .env.poc.example             # 环境变量模板
```

- `data/` 目录映射到容器内 `/data`，SQLite文件自动创建
- `.env.poc` 已被 `.gitignore` 排除，不会提交到版本库
- 删除 `data/eventlink_poc.db` 等同于重置所有数据
- 数据属于用户，EventLink是processor不是owner（数据主权原则）

### 2.7 健康检查验证

```bash
# 基础健康检查
curl http://localhost:8000/api/v1/health

# 检查Docker容器健康状态
docker inspect --format='{{.State.Health.Status}}' eventlink-api

# 查看容器资源使用
docker stats eventlink-api --no-stream

# 查看最近日志
docker compose -f docker-compose.poc.yml logs --tail=50
```

### 2.8 常见问题排查

| 问题 | 原因 | 解决方案 |
|------|------|----------|
| 端口8000被占用 | 其他服务占用 | 修改 `docker-compose.poc.yml` 端口映射，如 `8001:8000` |
| 容器启动后立即退出 | `.env.poc` 缺少必填项 | 检查 `EVENTLINK_SECRET_KEY` 和 `LLM_API_KEY` 是否已填 |
| 健康检查失败 | 应用启动慢或数据库初始化失败 | 等待40s启动期；查看日志 `docker compose logs` |
| LLM调用超时 | 网络问题或API Key无效 | 检查 `LLM_BASE_URL` 和 `LLM_API_KEY`；增大 `LLM_TIMEOUT` |
| 数据库文件权限错误 | 宿主机目录权限 | `chmod 777 ./data` 或调整Docker用户映射 |
| 容器内存不足 | 数据量过大 | 增大 `deploy.resources.limits.memory` |

---

## 3. CI/CD流水线 [0.2.0新增]

### 3.1 GitHub Actions概览 [0.2.0新增]

[0.2.0新增] EventLink使用GitHub Actions实现持续集成，配置文件位于 `.github/workflows/ci.yml`。每次push到`main`/`develop`分支或向`main`提交PR时自动触发。

**流水线触发条件**：

| 触发事件 | 分支 | 说明 |
|----------|------|------|
| `push` | `main`, `develop` | 代码推送时运行全量检查 |
| `pull_request` | `main` | PR提交时运行全量检查 |

**执行环境**：

| 配置项 | 值 | 说明 |
|--------|-----|------|
| Runner | `ubuntu-latest` | GitHub托管Linux runner |
| Python版本 | `3.11`（矩阵单值） | 与生产环境一致 |
| 服务容器 | `postgres:16-alpine` | 测试用PG实例（自动健康检查） |

### 3.2 流水线步骤详解 [0.2.0新增]

[0.2.0新增] 流水线按顺序执行以下步骤：

```
┌─────────────────────────────────────────────────────────────────┐
│ Step 1: Checkout                                                │
│   actions/checkout@v4 → 拉取完整仓库代码                         │
├─────────────────────────────────────────────────────────────────┤
│ Step 2: Setup Python                                            │
│   actions/setup-python@v5 → 安装 Python 3.11                    │
├─────────────────────────────────────────────────────────────────┤
│ Step 3: Install Dependencies                                    │
│   pip install -e ".[dev,test]" → 项目依赖（开发+测试extras）    │
│   pip install pytest pytest-cov pytest-asyncio httpx → 测试框架  │
├─────────────────────────────────────────────────────────────────┤
│ Step 4: Linting (ruff)                                          │
│   ruff check src/ tests/ → 代码风格+静态错误检查                 │
├─────────────────────────────────────────────────────────────────┤
│ Step 5: Type Checking (mypy)                                     │
│   mypy src/eventlink --ignore-missing-imports → 类型注解检查     │
│   注：|| true 表示类型错误不阻断CI（渐进式采用）                  │
├─────────────────────────────────────────────────────────────────┤
│ Step 6: Run Tests (pytest)                                       │
│   pytest tests/ -v --cov=src/eventlink                          │
│   --cov-report=xml --cov-report=term-missing                     │
│   环境变量：DATABASE_URL(PG) / TEST_MODE / LLM_API_KEY(测试key) │
│            SECRET_KEY(32位+) / REDIS_ENABLED=false               │
├─────────────────────────────────────────────────────────────────┤
│ Step 7: Upload Coverage                                         │
│   codecov/codecov-action@v4 → 上传覆盖率报告                   │
│   fail_ci_if_error: false → 覆盖率上传失败不阻断CI              │
└─────────────────────────────────────────────────────────────────┘
```

**测试环境变量说明**：

| 变量 | CI中的值 | 说明 |
|------|---------|------|
| `DATABASE_URL` | `postgresql+asyncpg://eventlink:eventlink_test@localhost:5432/eventlink_test` | 异步PG连接串 |
| `TEST_MODE` | `"true"` | 标记测试模式（跳过真实LLM调用） |
| `LLM_API_KEY` | `"test-key-for-ci"` | 测试占位Key（不调用真实API） |
| `SECRET_KEY` | `"ci-test-secret-key-min-32-chars-long"` | CI专用JWT密钥（≥32字符） |
| `REDIS_ENABLED` | `"false"` | PoC阶段CI不需要Redis |

**CI服务质量目标**：

| 指标 | 目标 | 当前状态 |
|------|------|----------|
| ruff lint | 0 error, 0 warning | ✅ 强制通过 |
| mypy typecheck | 渐进式修复中 | ⚠️ 不阻断（`|| true`） |
| pytest | 全部通过 | ✅ 强制通过 |
| coverage | 上传Codecov | ✅ 记录趋势 |

### 3.3 后续CD规划 [0.2.0新增]

[0.2.0新增] 当前CI仅覆盖代码质量门禁，以下CD能力计划在对应阶段补充：

| 能力 | 触发条件 | 计划内容 |
|------|----------|----------|
| Docker镜像构建 | PR合并到main | 自动构建multi-stage镜像并推送到Registry |
| 自动部署(Phase1) | main分支推送 | SSH到云服务器执行 `docker compose pull && up -d` |
| 小程序自动化发布 | Taro构建就绪 | `miniprogram-ci` 自动上传+提审 |
| 环境扩散部署 | Phase2启动前 | dev → staging → production 多环境流水线 |

---

## 4. Phase1云端部署

### 4.1 前置条件

| 依赖 | 说明 |
|------|------|
| 云服务器 | 2核4G+，推荐阿里云/腾讯云轻量应用服务器 |
| 域名 | 已备案域名，如 `eventlink.com` |
| SSL证书 | Let's Encrypt 免费证书（Certbot自动管理） |
| Docker Engine | 24+ |
| Docker Compose | v2.20+ |

### 4.2 Docker Compose部署

Phase1使用 `docker-compose.yml` 编排多服务：

```yaml
# 服务清单
services:
  eventlink:        # FastAPI 应用
  postgres:         # PostgreSQL 16 数据库
  redis:            # Redis 7 缓存
  nginx:            # Nginx 反向代理（需自行添加）
```

**部署步骤**：

```bash
# 1. 服务器初始化
sudo apt update && sudo apt install -y docker.io docker-compose-plugin

# 2. 克隆项目
git clone <repo-url> && cd EventLink

# 3. 创建生产环境配置
cp .env.poc.example .env
# 编辑 .env，修改以下关键项：
#   EVENTLINK_STAGE=production
#   DATABASE_URL=postgresql://eventlink:STRONG_PASSWORD@postgres:5432/eventlink
#   REDIS_ENABLED=true
#   REDIS_URL=redis://redis:6379/0

# 4. 启动全部服务
docker compose up -d --build

# 5. 初始化数据库（首次部署）
docker compose exec eventlink alembic upgrade head
```

### 4.3 PostgreSQL配置

| 配置项 | 推荐值 | 说明 |
|--------|--------|------|
| 版本 | 16-alpine | 轻量镜像（与CI一致） |
| 数据库名 | `eventlink` | - |
| 用户名 | `eventlink` | 专用账号，非root |
| 密码 | 强随机密码 | 32位以上，含大小写数字特殊字符 |
| 数据卷 | `postgres_data` | Docker命名卷持久化 |
| 连接池 | 默认 | 单用户无需调优 |

**数据库初始化**：

```bash
# 进入PostgreSQL容器
docker compose exec postgres psql -U eventlink -d eventlink

# 验证表结构
\dt

# 启用必要扩展
CREATE EXTENSION IF NOT EXISTS pgcrypto;
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
```

### 4.4 Redis配置

| 配置项 | 推荐值 | 说明 |
|--------|--------|------|
| 版本 | 7-alpine | 轻量镜像 |
| 端口 | 6379 | 仅容器内网访问 |
| 密码 | 强随机密码 | `requirepass` 配置 |
| 最大内存 | 128mb | 单用户足够 |
| 淘汰策略 | `allkeys-lru` | 内存不足时淘汰最少使用 |

**Redis安全配置**（`redis.conf`）：

```conf
requirepass YOUR_REDIS_PASSWORD
maxmemory 128mb
maxmemory-policy allkeys-lru
bind 0.0.0.0
protected-mode yes
```

### 4.5 Nginx反向代理

```nginx
upstream eventlink_api {
    server eventlink:8000;
}

server {
    listen 80;
    server_name api.eventlink.com;
    return 301 https://$server_name$request_uri;
}

server {
    listen 443 ssl http2;
    server_name api.eventlink.com;

    # SSL证书
    ssl_certificate /etc/letsencrypt/live/api.eventlink.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/api.eventlink.com/privkey.pem;

    # SSL安全配置
    ssl_protocols TLSv1.3;
    ssl_ciphers TLS_AES_256_GCM_SHA384:TLS_CHACHA20_POLY1305_SHA256;
    ssl_prefer_server_ciphers on;
    add_header Strict-Transport-Security "max-age=31536000; includeSubDomains" always;

    # API代理
    location / {
        proxy_pass http://eventlink_api;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        # 超时配置（LLM调用可能较慢）
        proxy_read_timeout 60s;
        proxy_send_timeout 60s;
    }

    # 健康检查不记日志
    location /api/v1/health {
        proxy_pass http://eventlink_api;
        access_log off;
    }
}
```

### 4.6 SSL/TLS配置

使用Certbot自动管理Let's Encrypt证书：

```bash
# 安装Certbot
sudo apt install -y certbot python3-certbot-nginx

# 首次获取证书
sudo certbot --nginx -d api.eventlink.com -d eventlink.com

# 自动续期（Certbot已内置定时任务）
sudo certbot renew --dry-run
```

### 4.7 微信小程序域名白名单配置

在微信公众平台（mp.weixin.qq.com）配置以下域名：

| 配置项 | 域名 | 说明 |
|--------|------|------|
| request合法域名 | `https://api.eventlink.com` | API请求 |
| socket合法域名 | - | 暂不需要 |
| uploadFile合法域名 | `https://api.eventlink.com` | 文件上传 |
| downloadFile合法域名 | `https://api.eventlink.com` | 文件下载 |
| webview业务域名 | `eventlink.com` | H5页面 |

**小程序 app.json 配置**：

```json
{
  "networkTimeout": {
    "request": 10000
  }
}
```

### 4.8 备份与恢复

**PostgreSQL备份**：

```bash
# 手动备份
docker compose exec postgres pg_dump -U eventlink eventlink > backup_$(date +%Y%m%d).sql

# 定时备份（crontab）
# 每天凌晨3点备份
0 3 * * * cd /path/to/EventLink && docker compose exec -T postgres pg_dump -U eventlink eventlink | gzip > /backups/eventlink_$(date +\%Y\%m\%d).sql.gz

# 恢复
gunzip -c backup_20260604.sql.gz | docker compose exec -T postgres psql -U eventlink eventlink
```

**Redis备份**：Redis默认开启RDB持久化，数据卷已包含持久化文件。

**备份保留策略**：

| 备份类型 | 保留周期 | 存储位置 |
|----------|----------|----------|
| 每日备份 | 7天 | 本地 /backups/ |
| 每周备份 | 4周 | 本地 /backups/ |
| 手动备份 | 永久 | 按需归档 |

---

## 5. 监控指标体系 [0.2.0新增]

### 5.1 P0业务指标（Prometheus） [0.2.0新增]

[0.2.0新增] 以下6项P0指标来自技术设计v2.5 §8.0.5，是EventLink业务健康度的核心观测信号。建议在Phase1接入Prometheus+Grafana进行可视化监控。

#### 指标1：Input Scope分类延迟

```yaml
name: eventlink_input_scope_classification_duration_seconds
type: histogram
help: "Input scope classification latency in seconds"
labels: [input_scope]  # card_save / meeting / call / manual / unknown
buckets: [0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0]
alert_threshold:
  condition: p95 > 3s
  severity: warning
  action: "检查LLM API响应时间或InputClassifier逻辑"
```

**业务含义**：衡量Step0 InputClassifier对用户输入的分类速度。分类延迟过高意味着上游管线整体变慢，直接影响用户体验（名片扫描→Todo的端到端SLA为<5秒）。

#### 指标2：Todo生成计数分布

```yaml
name: eventlink_todos_generated_total
type: counter
help: "Total todos generated, labeled by event and todo type"
labels:
  - event_id         # 关联事件ID（基数较高，注意高基数问题）
  - todo_type        # care / promise / help / followup / cooperation_signal / risk
  - action_type      # 产生该Todo的事件动作类型
alert_threshold:
  condition: 单事件生成Todo数 > 20
  severity: warning
  action: "可能存在AI幻觉或输入噪声过多，检查InputClassifier SC-01约束"
```

**业务含义**：追踪Todo生成的数量和类型分布。异常激增可能表明：
- 输入噪声未被正确过滤（SC-01约束失效）
- LLM输出规则（§4.9）未正确实施
- 单次互动产生的Todo过多导致用户信息过载

#### 指标3：关系简报查询延迟

```yaml
name: eventlink_relationship_brief_query_duration_seconds
type: histogram
help: "Relationship brief query latency in seconds"
labels:
  - person_id        # 查询目标人物ID
  - has_care_data    # 是否包含关注点数据（true/false）
buckets: [0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0]
alert_threshold:
  condition: p95 > 2s
  severity: critical
  action: "检查数据库索引（person_id+updated_at复合索引）或关联查询N+1"
```

**业务含义**：关系简报（Person详情页"关系"Tab）是高频查询端点。延迟过高通常指向数据库查询性能问题（缺少索引或ORM N+1查询）。

#### 指标4：关系阶段变更频率

```yaml
name: eventlink_relationship_stage_transitions_total
type: counter
help: "Relationship stage transition count"
labels:
  - from_stage       # 变更前阶段（stranger→acquaintance→...→partner）
  - to_stage         # 变更后阶段
  - trigger          # 触发方式：user_manual / ai_suggested / auto_promote
alert_threshold:
  condition: 阶段回退率（to_stage序号 < from_stage序号）> 10%
  severity: warning
  action: "检查乐观锁(updated_at)是否正常工作，排除并发冲突"
```

**业务含义**：追踪关系的阶段流转。阶段回退率过高可能表示：
- 并发写入导致乐观锁冲突（PATCH /stage 的 updated_at 校验）
- 用户频繁修正AI建议的阶段判断
- 关系冷却保护机制触发

#### 指标5：PII脱敏覆盖率

```yaml
name: eventlink_pii_sanitization_coverage
type: gauge
help: "PII field sanitization coverage ratio (0.0~1.0)"
labels:
  - pii_type         # phone / email / wechat / address / name
  - context          # llm_call / log_output / api_response / export
alert_threshold:
  condition: 任意pii_type覆盖率 < 0.95
  severity: critical
  action: "立即排查脱敏管道(redact_pii_from_text / _sanitize_for_llm)，存在数据泄露风险"
```

**业务含义**：衡量PII（个人身份信息）脱敏机制的完整性。这是**安全P0指标**——覆盖率低于95%意味着敏感数据可能在LLM调用、日志输出或API响应中以明文泄露。

#### 指标6：HTTP 400错误率

```yaml
name: eventlink_http_requests_total
type: counter
help: "Total HTTP requests by method, endpoint, and status"
labels:
  - method           # GET / POST / PATCH / DELETE
  - endpoint         # API端点路径
  - status           # HTTP状态码（200/400/401/404/500等）
alert_threshold:
  condition: 400率（status=400请求数 / 总请求数）> 5%
  severity: warning
  action: "分析400错误集中在哪个endpoint，通常是请求校验逻辑需要优化"
```

**业务含义**：400错误率反映API请求质量。持续高企的400率通常指向：
- 前端（小程序）传参格式与后端Pydantic模型不一致
- InputClassifier SC-01校验拦截了大量无效输入
- API文档与实际行为不同步

### 5.2 监控工具链推荐 [0.2.0新增]

| 阶段 | 方案 | 组件 |
|------|------|------|
| **PoC** | Docker内置 | `docker stats` + `docker compose logs -f` + 健康检查脚本 |
| **Phase1** | Prometheus + Grafana | Prometheus采集 + Grafana仪表盘（6项P0指标Dashboard） |
| **Phase2** | 云监控套件 | 阿里云ARMS / 腾讯云监控 + 自建告警通道 |

### 5.3 PoC阶段简易监控 [0.2.0更新]

[0.2.0更新] 在PoC阶段尚未引入Prometheus时，可通过以下方式进行基础监控：

| 监控项 | 工具 | 说明 |
|--------|------|------|
| 容器状态 | Docker内置 | `docker compose ps` |
| 资源使用 | `docker stats` | CPU/内存/网络 |
| 应用日志 | Docker日志 | `docker compose logs -f` |
| 健康检查 | `/api/v1/health` | 定时探测 |
| 磁盘空间 | `df -h` | 定时检查 |

**简易告警脚本**（可选）：

```bash
#!/bin/bash
# health_check.sh - 每5分钟执行
RESPONSE=$(curl -s -o /dev/null -w "%{http_code}" http://localhost:8000/api/v1/health)
if [ "$RESPONSE" != "200" ]; then
    echo "EventLink health check failed: HTTP $RESPONSE" >> /var/log/eventlink_alert.log
    # 可接入企业微信/钉钉通知
fi
```

---

## 6. Phase2 K8s部署

### 6.1 概述

Phase2为生产增强阶段，采用Kubernetes编排，实现高可用与弹性扩缩容。本节仅规划方向，不详细展开。

| 项目 | 方案 |
|------|------|
| 集群 | 阿里云ACK / 腾讯云TKE / 自建K8s |
| 镜像仓库 | 阿里云ACR / 腾讯云TCR |
| 数据库 | 云RDS PostgreSQL（主从+只读副本） |
| 缓存 | 云Redis（主从+Cluster模式） |
| 密钥管理 | 云KMS（密钥不落盘） |
| 日志 | ELK / 云日志服务 |
| 监控 | Prometheus + Grafana（含§5.1六项P0指标Dashboard） |

### 6.2 Helm Chart结构

```
charts/eventlink/
├── Chart.yaml
├── values.yaml
├── templates/
│   ├── deployment.yaml          # API服务Deployment
│   ├── service.yaml             # Service暴露
│   ├── ingress.yaml             # Ingress路由
│   ├── configmap.yaml           # 非敏感配置
│   ├── secret.yaml              # 敏感配置
│   ├── hpa.yaml                 # 水平自动扩缩容
│   ├── pdb.yaml                 # Pod中断预算
│   └── _helpers.tpl
└── .helmignore
```

### 6.3 自动扩缩容策略

| 指标 | 目标值 | 最小副本 | 最大副本 | 说明 |
|------|--------|----------|----------|------|
| CPU使用率 | 70% | 2 | 5 | 基础扩缩容 |
| 内存使用率 | 80% | 2 | 5 | 内存保护 |
| 自定义指标（QPS） | 100/秒/Pod | 2 | 5 | 请求驱动扩容 |

---

## 7. 数据库迁移（Alembic） [0.2.0新增]

### 7.1 Alembic初始化 [0.2.0新增]

[0.2.0新增] EventLink使用Alembic（SQLAlchemy官方迁移工具）管理数据库Schema变更。

**初始化步骤**（首次设置）：

```bash
# 1. 安装Alembic（已在requirements.txt中）
pip install alembic

# 2. 初始化Alembic目录结构
alembic init alembic

# 3. 配置alembic.ini
#    修改 sqlalchemy.url 为你的数据库连接串
#    PoC: sqlite:///./data/eventlink_poc.db
#    Phase1: postgresql://eventlink:***@localhost:5432/eventlink

# 4. 配置 env.py（关键：关联SQLAlchemy模型）
# alembic/env.py 内容如下：
from eventlink.models import Base
target_metadata = Base.metadata

def run_migrations_online():
    engine = create_engine(get_db_url())  # 支持多环境切换
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()
```

**项目目录结构**：

```
EventLink/
├── alembic/
│   ├── versions/                  # 迁移脚本目录
│   │   ├── 001_initial_schema.py
│   │   ├── 002_todo_types_v2.py
│   │   ├── 003_concern_promise_contribution.py
│   │   ├── 004_snooze_schedules.py
│   │   └── 005_entity_extract_columns.py
│   ├── env.py                     # 运行时环境配置
│   └── script.py.mako             # 迁移脚本模板
├── alembic.ini                    # Alembic主配置
└── src/eventlink/models.py        # SQLAlchemy ORM模型定义
```

### 7.2 Autogenerate工作流 [0.2.0新增]

[0.2.0新增] 推荐使用Alembic autogenerate功能自动检测模型变更并生成迁移脚本：

```bash
# 1. 修改 SQLAlchemy 模型（src/eventlink/models.py）
#    例如：新增字段、修改列类型、添加新表等

# 2. 自动生成迁移脚本
alembic revision --autogenerate -m "描述本次变更"

# 3. 检查生成的迁移脚本（alembic/versions/xxx_描述.py）
#    确认upgrade()和downgrade()逻辑正确

# 4. 执行迁移
alembic upgrade head

# 5. 如需回滚
alembic downgrade -1    # 回退一个版本
alembic downgrade base   # 回退到初始状态
```

**autogenerate注意事项**：
- autogenerate能检测到：新增/删除表、新增/删除/修改列、外键变更、索引变更
- autogenerate**无法**自动检测：列名重命名（会识别为删列+增列，数据丢失）、数据变更、自定义约束的一些情况
- 每次autogenerate后**必须人工审查**生成的脚本

### 7.3 迁移版本管理 [0.2.0新增]

[0.2.0新增]

| 版本号 | 迁移脚本 | 对应API版本 | 变更内容 |
|--------|---------|-------------|----------|
| 001 | `001_initial_schema.py` | v1.0 | 初始4表（events/entities/associations/todos） |
| 002 | `002_todo_types_v2.py` | v1.2 | Todo类型DDL重命名（CHECK约束更新） |
| 003 | `003_concern_promise_contribution.py` | v1.2 | entities.properties新增concern/promise/contribution结构 |
| 004 | `004_snooze_schedules.py` | v1.2 | 新增snooze_schedules表 |
| 005 | `005_entity_extract_columns.py` | v1.2 | entities表新增company/title/city/industry提取列+触发器 |

### 7.4 迁移铁律 [0.2.0新增]

[0.2.0新增] 以下是数据库迁移必须遵守的铁律（7角色架构评审共识）：

| # | 铁律 | 说明 |
|---|------|------|
| 1 | **每个迁移必须可回滚** | `downgrade()` 必须完整实现，不可留空或抛NotImplementedError |
| 2 | **破坏性变更只能在新主版本** | 删列/改类型必须走API v2，确保旧版客户端不受影响 |
| 3 | **PoC→Phase1是一次性全量迁移** | 不走Alembic增量，使用SQLite dump + 方言转换 + PG导入 |
| 4 | **迁移前必须备份** | 自动化脚本先执行 `pg_dump` 再 `alembic upgrade` |
| 5 | **零停机迁移** | 新增列用DEFAULT值，不锁表；删列分两步（先标记deprecated→下个主版本删除） |

### 7.5 SQLite→PostgreSQL升级路径 [0.2.0新增]

[0.2.0新增] 从PoC（SQLite）升级到Phase1（PostgreSQL）的完整迁移方案：

```bash
# ===== Step 1: 导出SQLite数据 =====
sqlite3 data/eventlink_poc.db .dump > /tmp/eventlink_dump.sql

# ===== Step 2: 转换SQL方言（SQLite → PostgreSQL） =====
python3 scripts/migrate_sqlite_to_pg.py /tmp/eventlink_dump.sql > /tmp/eventlink_pg.sql
# 转换内容包括：
#   - SQLite AUTOINCREMENT → PG SERIAL/BIGSERIAL
#   - SQLite INTEGER PRIMARY KEY → PG BIGINT PRIMARY KEY
#   - SQLite 't'/'f' 布尔 → PG TRUE/FALSE
#   - SQLite 双引号标识符 → PG 双引号（基本兼容）
#   - SQLite 特有函数替换（datetime('now') → NOW() 等）

# ===== Step 3: 创建PG数据库并执行Alembic初始迁移 =====
createdb eventlink
alembic upgrade head

# ===== Step 4: 导入数据（跳过已由Alembic创建的表结构） =====
psql eventlink < /tmp/eventlink_pg_data_only.sql

# ===== Step 5: 验证数据完整性 =====
python3 scripts/verify_migration.py --source sqlite --target postgresql
```

**迁移验证方法**：

```bash
# 1. 记录数对比
echo "SQLite:" && sqlite3 data/eventlink_poc.db \
  "SELECT 'events', COUNT(*) FROM events
   UNION ALL SELECT 'entities', COUNT(*) FROM entities
   UNION ALL SELECT 'associations', COUNT(*) FROM associations
   UNION ALL SELECT 'todos', COUNT(*) FROM todos;"

echo "PostgreSQL:" && docker compose exec postgres psql -U eventlink -c \
  "SELECT 'events' as tbl, COUNT(*) FROM events
   UNION ALL SELECT 'entities', COUNT(*) FROM entities
   UNION ALL SELECT 'associations', COUNT(*) FROM associations
   UNION ALL SELECT 'todos', COUNT(*) FROM todos;"

# 2. 抽样数据对比（随机取10条比对关键字段）
python3 scripts/verify_migration.py --source sqlite --target postgresql --sample-size 10

# 3. 功能验证
curl -H "Authorization: Bearer $TOKEN" https://api.eventlink.com/api/v1/entities
curl -H "Authorization: Bearer $TOKEN" https://api.eventlink.com/api/v1/events
```

**迁移改动量预估**：

| 迁移项 | PoC | Phase 1 | 改动量 |
|--------|-----|---------|--------|
| 数据库连接 | SQLite文件 | PG连接字符串 | 1行配置（DATABASE_URL） |
| 缓存 | 内存dict | Redis URL | 1行配置（REDIS_URL） |
| 认证中间件 | API Key | JWT RS256 | 中间件替换 |
| CarryMem | NullMemoryProvider | 可选接入 | 配置切换 |
| Schema迁移 | 无 | Alembic管理 | 初始化一次 |
| 数据迁移 | - | SQLite→PG一次性 | ~100行迁移脚本 |

---

## 8. 自建小程序部署（Taro备选方案） [0.2.0新增]

### 8.1 触发条件 [0.2.0新增]

[0.2.0新增] 本方案为**备选方案**，仅在满足以下任一条件时启动：

| 触发条件 | 阈值 | 说明 |
|----------|------|------|
| 许总团队无法启动小程序 | 持续 **2周** 以上 | 外包团队交付阻塞 |
| API对接进度滞后 | 超过 **3周** 未完成 | 小程序前端无法对接EventLink API |

**决策原则**：优先使用许总团队的小程序方案；自建Taro方案作为降级保障，确保PoC不因前端阻塞而停滞。

### 8.2 技术方案概述 [0.2.0新增]

[0.2.0新增] 采用 **Taro 3.x** 框架开发微信小程序，实现跨端能力（微信小程序为主，未来可扩展到H5/App）：

```
技术栈：
├── Taro 3.x + React 18          # 跨端框架
├── TypeScript                   # 类型安全
├── NutUI (Taro版) 或 Taro UI    # UI组件库
├── @tarojs/plugin-platform-wechat  # 微信小程序平台插件
└── miniprogram-ci               # 微信小程序CI上传工具
```

### 8.3 构建与发布流程 [0.2.0新增]

[0.2.0新增]

**本地开发**：

```bash
# 1. 安装Taro CLI
npm install -g @tarojs/cli

# 2. 创建Taro项目（如需新建）
taro init eventlink-miniapp

# 3. 微信开发者工具预览
npm run dev:wechat
# 然后在微信开发者工具中导入 dist 目录

# 4. 构建生产包
npm run build:wechat
```

**CI/CD自动上传**（miniprogram-ci）：

```bash
# 1. 安装微信小程序CI工具
npm install -g miniprogram-ci

# 2. 获取上传密钥（微信公众平台 → 开发管理 → 开发设置 → 小程序代码上传）
#    生成 private.key 并下载

# 3. 上传代码到微信后台
npx miniprogram-ci upload \
  --pp ./dist \
  --pkp ./private.key \
  --appid <your-appid> \
  --uv <version> \
  -r 1 \
  --desc "Auto deploy from CI $(date +%Y%m%d%H%M%S)"

# 4. 提交审核（可选自动化）
npx miniprogram-ci preview \
  --pp ./dist \
  --pkp ./private.key \
  --appid <your-appid> \
  --uv <version> \
  -r 1 \
  --desc "Preview for review"
```

**GitHub Actions集成示例**（后续CD阶段启用）：

```yaml
# .github/workflows/wechat-deploy.yml（规划中）
- name: Build Taro mini program
  run: |
    npm ci
    npm run build:wechat

- name: Upload to WeChat
  env:
    WECHAT_APP_ID: ${{ secrets.WECHAT_APP_ID }}
    WECHAT_PRIVATE_KEY: ${{ secrets.WECHAT_PRIVATE_KEY }}
  run: |
    npx miniprogram-ci upload \
      --pp ./dist \
      --pkp <(echo "$WECHAT_PRIVATE_KEY") \
      --appid $WECHAT_APP_ID \
      --uv ${{ github.sha }} \
      -r 1 \
      --desc "Deploy ${{ github.sha }}"
```

### 8.4 小程序API对接要点 [0.2.0新增]

[0.2.0新增] 自建小程序需对接EventLink后端API的关键事项：

| 对接项 | API端点 | 说明 |
|--------|---------|------|
| 用户认证 | `POST /api/v1/auth/login` | 获取JWT Token |
| Token刷新 | `POST /api/v1/auth/refresh` | Refresh Token轮换 |
| 事件录入 | `POST /api/v1/events` | 名片/会议/通话/手工录入 |
| 人物列表 | `GET /api/v1/entities` | Person/Organization列表 |
| Todo列表 | `GET /api/v1/todos` | 待办事项查询 |
| 关系简报 | `GET /api/v1/people/{id}/relationship-brief` | Person详情-关系Tab |
| 阶段变更 | `PATCH /api/v1/people/{id}/relationship-stage` | 乐观锁(updated_at)校验 |
| 日视图 | `GET /api/v1/day-view` | 日程聚合视图 |
| 数据导出 | `GET /api/v1/export` | 全量JSON导出（数据主权） |

**CORS配置**：确保 `EVENTLINK_CORS_ORIGINS` 包含小程序请求来源（开发阶段为本地调试地址，生产阶段为小程序合法域名）。

---

## 9. 环境变量参考

### 9.1 完整环境变量表

| 变量名 | 默认值 | 必填 | 阶段 | 说明 |
|--------|--------|------|------|------|
| **应用基础** | | | | |
| `EVENTLINK_STAGE` | `development` | 否 | 全部 | 运行阶段：`poc` / `phase1` / `phase2` |
| `EVENTLINK_SECRET_KEY` | `change-me-in-production` | **是** | 全部 | JWT签名密钥，生产环境必须修改（≥32字符） |
| `EVENTLINK_DB_PATH` | `/data/eventlink_poc.db` | 否 | PoC | SQLite数据库路径（容器内） |
| `EVENTLINK_LOG_LEVEL` | `INFO` | 否 | 全部 | 日志级别：DEBUG/INFO/WARNING/ERROR |
| `EVENTLINK_CORS_ORIGINS` | `["http://localhost:3000"]` | 否 | 全部 | CORS允许来源，JSON数组格式 |
| **数据库** | | | | |
| `DATABASE_URL` | `sqlite:///./data/eventlink.db` | 否 | 全部 | 数据库连接串，Phase1改为PG异步串 |
| **Redis** | | | | |
| `REDIS_URL` | `redis://localhost:6379/0` | 否 | Phase1+ | Redis连接串 |
| `REDIS_ENABLED` | `false` | 否 | 全部 | 是否启用Redis |
| **认证** | | | | |
| `ALGORITHM` | `HS256` | 否 | 全部 | JWT算法，Phase1改为RS256 |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | `15` | 否 | 全部 | Access Token有效期（分钟） |
| `REFRESH_TOKEN_EXPIRE_DAYS` | `7` | 否 | 全部 | Refresh Token有效期（天） |
| `EVENTLINK_JWT_PRIVATE_KEY_PATH` | - | 否 | Phase1+ | RS256私钥路径 |
| `EVENTLINK_JWT_PUBLIC_KEY_PATH` | - | 否 | Phase1+ | RS256公钥路径 |
| **LLM** | | | | |
| `LLM_API_KEY` | - | **是** | 全部 | LLM API密钥 |
| `LLM_BASE_URL` | - | **是** | 全部 | LLM API地址 |
| `LLM_MODEL` | `claude-sonnet-4-20250514` | 否 | 全部 | 模型名称 |
| `LLM_PROVIDER` | `anthropic` | 否 | 全部 | 提供商：anthropic/openai/moka_ai |
| `LLM_MAX_TOKENS` | `2000` | 否 | 全部 | 单次最大Token数 |
| `LLM_TEMPERATURE` | `0.3` | 否 | 全部 | 生成温度 |
| `LLM_TIMEOUT` | `30` | 否 | 全部 | 请求超时（秒） |
| `LLM_MAX_RETRIES` | `3` | 否 | 全部 | 最大重试次数 |
| **CarryMem集成** | | | | |
| `CARRYMEM_ENABLED` | `false` | 否 | 全部 | 是否启用CarryMem集成 |
| `CARRYMEM_API_URL` | `http://localhost:8100` | 否 | 全部 | CarryMem API地址 |
| `CARRYMEM_API_KEY` | - | 否 | 全部 | CarryMem API密钥 |
| **算法参数** | | | | |
| `ENTITY_RESOLUTION_AUTO_MERGE_THRESHOLD` | `0.85` | 否 | 全部 | 实体自动合并置信度阈值 |
| `ENTITY_RESOLUTION_HUMAN_REVIEW_THRESHOLD` | `0.70` | 否 | 全部 | 实体人工审核阈值 |
| `OPPORTUNITY_MATCH_STRONG_THRESHOLD` | `0.80` | 否 | 全部 | 机会匹配强匹配阈值 |
| `OPPORTUNITY_MATCH_POTENTIAL_THRESHOLD` | `0.60` | 否 | 全部 | 机会匹配潜在匹配阈值 |
| **性能** | | | | |
| `MAX_WORKERS` | `4` | 否 | 全部 | 最大工作线程数 |
| `REQUEST_TIMEOUT` | `30` | 否 | 全部 | 请求超时（秒） |

---

## 10. 故障排查手册

### 10.1 常见错误及解决方案

| 错误现象 | 可能原因 | 排查步骤 | 解决方案 |
|----------|----------|----------|----------|
| 容器无法启动 | 配置文件缺失/错误 | `docker compose logs` 查看启动日志 | 检查 `.env` 文件是否完整 |
| 401 Unauthorized | JWT密钥不匹配 | 检查 `EVENTLINK_SECRET_KEY` 是否一致 | 确保所有服务使用相同密钥 |
| 500 Internal Error | 数据库连接失败 | 检查 `DATABASE_URL` 和数据库状态 | 确认PG/SQLite可访问 |
| LLM调用429 | API限流 | 检查API Key配额 | 降低调用频率或升级API套餐 |
| LLM调用超时 | 网络问题 | `curl $LLM_BASE_URL` 测试连通性 | 检查网络/代理设置 |
| 数据库迁移失败 | 表结构不一致 | `alembic current` 查看当前版本 | `alembic upgrade head` 重新迁移 |
| CORS报错 | Origin不在白名单 | 检查 `EVENTLINK_CORS_ORIGINS` | 添加请求来源到白名单 |
| Redis连接失败 | Redis未启动或密码错误 | `docker compose ps redis` | 启动Redis或修正密码配置 |
| 小程序请求失败 | 域名未配置白名单 | 检查微信公众平台配置 | 添加 `https://api.eventlink.com` |
| 磁盘空间不足 | 日志/数据过大 | `df -h` 检查磁盘 | 清理日志或扩容磁盘 |

### 10.2 日志查看方法

```bash
# 查看全部服务日志
docker compose logs -f

# 查看指定服务日志
docker compose logs -f eventlink
docker compose logs -f postgres
docker compose logs -f redis

# 查看最近N行日志
docker compose logs --tail=100 eventlink

# 按时间过滤日志
docker compose logs --since="2026-06-04T10:00:00" eventlink

# 导出日志到文件
docker compose logs eventlink > eventlink.log 2>&1
```

**应用日志级别说明**：

| 级别 | 用途 | 生产环境建议 |
|------|------|-------------|
| DEBUG | 详细调试信息 | 不建议 |
| INFO | 常规操作记录 | 推荐 |
| WARNING | 潜在问题 | 推荐 |
| ERROR | 错误但服务可用 | 必须记录 |

### 10.3 性能问题排查

| 症状 | 排查方向 | 工具/命令 |
|------|----------|-----------|
| API响应慢 | 数据库查询 | 检查慢查询日志，确认索引 |
| API响应慢 | LLM调用耗时 | 检查 `LLM_TIMEOUT`，监控LLM响应时间 |
| 内存持续增长 | 内存泄漏 | `docker stats` 监控，重启容器临时缓解 |
| CPU占用高 | 计算密集任务 | 检查实体归一/匹配算法是否触发全量计算 |
| 磁盘IO高 | 数据库写入频繁 | 检查批量操作，优化写入策略 |

---

## 11. 安全检查清单

### 11.1 部署前安全检查

| 检查项 | PoC | Phase1 | 验证方法 |
|--------|-----|--------|----------|
| `EVENTLINK_SECRET_KEY` 不为默认值 | ✅ | ✅ | 检查 `.env` 文件 |
| LLM API Key 不在代码仓库中 | ✅ | ✅ | `git log --all --full-history -- "*.env*"` |
| `.env` 文件被 `.gitignore` 排除 | ✅ | ✅ | `git status` 不显示 `.env` |
| 数据库密码为强随机密码 | - | ✅ | 32位以上随机字符串 |
| Redis密码已设置 | - | ✅ | 检查 `requirepass` 配置 |
| 容器端口不暴露到公网 | - | ✅ | 仅Nginx暴露80/443 |
| Docker镜像为最新版 | ✅ | ✅ | `docker pull` 更新基础镜像 |
| Dockerfile非root用户运行 | ✅ | ✅ | `USER eventlink` 已配置 |
| HEALTHCHECK已启用 | ✅ | ✅ | 30s间隔/10s超时/3次重试 |

### 11.2 生产环境安全加固

| 加固项 | 说明 | 阶段 |
|--------|------|------|
| **TLS强制** | 全部HTTP请求301跳转HTTPS | Phase1 |
| **HSTS启用** | `Strict-Transport-Security` 头 | Phase1 |
| **CORS严格白名单** | 仅允许生产域名 | Phase1 |
| **PII字段加密** | AES-256-GCM加密phone/email/wechat | Phase1 |
| **JWT RS256** | 非对称签名替代HS256 | Phase1 |
| **Ticket模式** | 小程序WebView安全认证 | Phase1 |
| **Redis密码** | `requirepass` + `protected-mode` | Phase1 |
| **PG SSL连接** | 数据库连接启用SSL | Phase1 |
| **限流配置** | Redis按user_id限流100次/分 | Phase1 |
| **请求签名** | HMAC-SHA256防重放 | Phase1 |
| **审计日志** | 数据库审计表记录所有写操作 | Phase1 |
| **数据导出/删除** | 用户数据主权保障 | Phase1 |
| **定期依赖扫描** | `pip audit` + `bandit` | Phase1 |
| **Docker镜像扫描** | `trivy image eventlink:latest` | Phase1 |
| **备份加密** | pg_dump输出加密存储 | Phase2 |
| **KMS密钥管理** | 密钥不落盘，运行时获取 | Phase2 |
| **TDE透明加密** | 数据库全量加密 | Phase2 |

---

## 版本历史

| 版本 | 日期 | 变更内容 | 作者 |
|------|------|----------|------|
| v1.0 | 2026-06-03 | 初始版本，包含8章节完整部署指南 | 架构师 |
| **0.2.0** | **2026-06-04** | **POC阶段重大更新：①D8-1 Dockerfile多阶段构建详细说明(builder→runtime非root) ②D8-2 新增GitHub Actions CI/CD完整章节(trigger/strategy/services/steps/lint/typecheck/test/coverage) ③D8-3 确认docker-compose.poc.yml与实际文件一致(含PG/Redis预定义) ④D8-4 新增6项P0 Prometheus监控指标(input_scope延迟/Todo分布/查询延迟/阶段变更频率/脱敏覆盖率/400率) ⑤D8-5 新增Alembic数据库迁移章节(初始化+autogenerate+铁律+SQLite→PG升级路径) ⑥D8-6 新增自建小程序Taro备选方案(触发条件+构建流程+CI上传+API对接) ⑦D8-7 版本号改为0.2.0+参考更新为技术设计v2.5 §9** | **DevSquad** |

---

> **文档状态**: ✅ 0.2.0 POC阶段版本完成
> **下次审查**: Phase1开发启动前 / CI/CD CD部分上线前
> **维护负责人**: DevSquad架构师
> **适用阶段**: PoC（当前）→ Phase1（下一里程碑）
