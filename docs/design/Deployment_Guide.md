# PromiseLink 部署指南

> **版本**: 0.5.0（产品分级重构 — 基础版/专业版/定制版 + 网关中继架构）
> **日期**: 2026-06-11
> **定位**: AI驱动的个人商务关系经营助手 — 先成就关系，再促成合作
> **参考**: 技术设计 v2.5 §9（部署架构与数据主权）、§8.0.5（监控指标）、§8.0.6（数据库迁移策略）
> **技术栈**: Python 3.11 / FastAPI / httpx async / Pydantic v2

---

## 1. 部署概述

### 1.1 部署策略

PromiseLink是个人产品，SQLite完全够用。采用功能递进式部署，PG/Redis仅在销售团队定制版中按需引入：

| 阶段 | 基础设施 | 数据库 | 缓存 | 成本 | 用户规模 | 目标 |
|------|----------|--------|------|------|----------|------|
| **PoC（概念验证）** | 本地 Docker Desktop | SQLite | 无 | 零云成本 | 单用户 | 概念验证、核心流程跑通 |
| **基础版（本地免费）** | 本地 Docker Desktop | SQLite | 无 | 零云成本 | 单用户 | 本地可用产品，Taro H5浏览器访问 |
| **专业版（网关中继）** | 本地Docker + 云中继网关 | SQLite | 无(网关代理AI) | ~50元/月 | 单用户 | 随时随地微信小程序访问 |
| **定制版** | 云端 Docker Compose | PostgreSQL 16 | Redis 7 | ~500元/月 | 销售团队 | 多用户协作（独立分支） |

> **决策变更（2026-06-11）**：个人版长期使用SQLite，不做PG/Redis迁移。理由：单用户无并发场景，SQLite处理百万行无压力，PG/Redis增加成本和复杂度但无收益。

**关键约束**：
- 不做原生APP，微信小程序是主入口
- LLM推理走云端API（OpenAI/Anthropic/Moka AI），不部署本地模型
- PoC阶段零云成本，所有服务运行在本地Docker内
- **数据主权**：数据属于用户，PromiseLink是processor不是owner（详见 §8.6.5）

### 1.2 环境要求表

| 项目 | PoC（概念验证） | 基础版（本地免费） | 专业版（网关中继） | 定制版 |
|------|-----|---------|--------|--------|
| **操作系统** | macOS / Linux / Windows(WSL2) | macOS / Linux / Windows(WSL2) | macOS / Linux / Windows(WSL2) | Ubuntu 22.04+ |
| **Docker** | Docker Desktop 24+ | Docker Desktop 24+ | Docker Desktop 24+ | Docker Engine 24+ |
| **Docker Compose** | v2.20+ | v2.20+ | v2.20+ | v2.20+ |
| **Python** | 3.11+（宿主机调试用） | 3.11+（宿主机调试用） | N/A（容器内） | N/A |
| **内存** | ≥4GB 可用 | ≥4GB 可用 | ≥4GB 可用 | ≥8GB 可用 |
| **磁盘** | ≥2GB 可用 | ≥2GB 可用 | ≥2GB 可用 | ≥50GB 可用 |
| **CPU** | ≥2核 | ≥2核 | ≥2核 | ≥4核 |
| **网络** | 需访问LLM API | 需访问LLM API | 需访问中继网关 | 需公网IP+域名 |
| **LLM API Key** | 必需 | 必需 | 不需要（网关代理） | 必需 |

---

## 2. PoC本地部署

### 2.1 前置条件

| 依赖 | 版本要求 | 安装验证 | 说明 |
|------|----------|----------|------|
| Docker Desktop | 24+ | `docker --version` | 包含Docker Compose |
| Python | 3.11+ | `python3 --version` | 仅宿主机调试时需要 |
| LLM API Key | - | - | OpenAI / Anthropic / Moka AI 任选其一 |

**[F-50新增] 语音助手额外依赖**：

| 依赖 | 版本要求 | 安装验证 | 说明 |
|------|----------|----------|------|
| **Python: edge-tts** | ≥6.1.0 | `pip show edge-tts` | Azure Edge-TTS（免费在线TTS），专业版语音合成核心 |
| **系统: ffmpeg** | ≥4.0 | `ffmpeg -version` | TTS音频格式转换（Edge-TTS输出mp3需要） |
| **系统: sox/soxi** | ≥14.4 | `soxi --version` | 音频处理工具（可选，用于调试音频文件） |

> **说明**：whisper（本地ASR）已在AI dependencies中，如需本地语音识别请确认已安装。PoC阶段edge-tts通过Dockerfile自动安装，宿主机无需手动pip install。

### 2.2 快速启动（5步完成）

```bash
# 1. 克隆项目
git clone <repo-url> && cd PromiseLink

# 2. 创建环境配置
cp .env.poc.example .env.poc

# 3. 编辑配置，填入必填项
#    PROMISELINK_SECRET_KEY=（执行下方命令生成）
#    LLM_API_KEY=（填入你的API Key）
#    LLM_BASE_URL=（填入对应的API地址）
python3 -c "import secrets; print(secrets.token_urlsafe(32))"
# 将输出值填入 PROMISELINK_SECRET_KEY

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
│ • 创建 venv /opt/venv           │     │ • 创建 promiselink 非 root 用户    │
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
| 运行用户 | `promiselink`（非root, UID随机） | 安全最佳实践 |
| 工作目录 | `/app/src` | 确保Python可找到promiselink包 |
| 数据目录 | `/data`（promiselink用户所有） | SQLite持久化目录 |
| 暴露端口 | `8000` | FastAPI/Uvicorn |
| 健康检查 | `HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3` | 探测 `/api/v1/health` |
| 启动命令 | `uvicorn promiselink.main:app --host 0.0.0.0 --port 8000` | 异步ASGI服务器 |

**[F-50新增] Stage 2 — Voice Assistant 扩展**：

在Runtime阶段追加以下指令（位于 `COPY` 应用代码之后、`HEALTHCHECK` 之前）：

```dockerfile
# === [F-50] Voice Assistant ===
# 安装Edge-TTS（Azure免费在线TTS引擎）
RUN pip install --no-cache-dir edge-tts>=6.1.0

# TTS缓存目录（持久化已合成音频，避免重复调用）
RUN mkdir -p /var/cache/promiselink/tts && chown promiselink:promiselink /var/cache/promiselink/tts
```

| 配置项 | 值 | 说明 |
|--------|-----|------|
| Python依赖 | `edge-tts>=6.1.0` | Azure Edge-TTS，免费在线TTS |
| TTS缓存目录 | `/var/cache/promiselink/tts` | 已合成音频持久化缓存 |
| 目录权限 | `promiselink:promiselink` | 非root用户所有，安全最佳实践 |

> **注意**：Voice功能不需要新增容器或服务，作为现有API服务的模块运行。

**镜像优势**：
- 最终镜像仅包含运行时依赖（无gcc/libpq-dev等构建工具）
- 非 root 用户运行，降低安全风险
- 内置健康检查，支持Docker Compose/K8s自动探测
- SQLite数据目录权限正确归属promiselink用户

### 2.4 docker-compose.poc.yml 使用说明 [0.2.0更新]

> [0.2.0更新] 已确认 `docker-compose.poc.yml` 与实际文件完全一致，包含以下完整配置。

PoC阶段默认启动单个API服务容器（`promiselink-api`），同时预定义了PostgreSQL和Redis服务供专业版启用：

**核心服务（promiselink-api）配置**：

| 配置项 | 值 | 说明 |
|--------|-----|------|
| 镜像 | `promiselink:poc` | 本地构建（context: .） |
| 端口 | `8000:8000` | FastAPI / Uvicorn |
| 环境变量 | `.env.poc` 文件加载 | 支持 `PROMISELINK_STAGE`, `PROMISELINK_DB_PATH` 覆盖 |
| 数据卷 | `./data:/data` | SQLite持久化（容器内路径 `/data`） |
| 内存限制 | **512M**（预留128M） | SQLite+FastAPI足够，LLM走云端不占本地内存 |
| CPU限制 | **1.0核**（预留0.25核） | 单用户场景无需多核 |
| 健康检查 | `/api/v1/health` | 30s间隔，10s超时，3次重试，40s启动等待期 |
| 重启策略 | `unless-stopped` | 异常自动重启，手动停止除外 |
| 日志轮转 | json-file驱动，10MB×3文件 | 防止日志无限增长占满磁盘 |
| 网络 | `promiselink-poc-net`（bridge） | 独立桥接网络，为后续扩展预留隔离空间 |

**[F-50新增] Voice Assistant 扩展配置**：

Voice功能不需要新增服务（复用现有 `promiselink-api` 服务），但需在现有服务配置中追加以下内容：

**新增 Volume Mount**：
```yaml
# TTS缓存持久化（已合成音频避免重复调用Edge-TTS）
volumes:
  - ./data:/data
  - ./data/tts_cache:/var/cache/promiselink/tts    # [F-50新增]
```

**新增 Environment Variables**：
```yaml
environment:
  # ... 已有环境变量 ...
  # === [F-50] Voice Assistant ===
  - TTS_VOICE_NAME=zh-CN-XiaoxiaoNeural     # TTS语音角色
  - TTS_RATE=-10%                            # 语速调节（负值减速，正值加速）
  - VOICE_ENABLED=true                       # Feature Flag：可关闭语音功能
```

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `TTS_VOICE_NAME` | `zh-CN-XiaoxiaoNeural` | Azure Edge-TTS语音角色（中文女声） |
| `TTS_RATE` | `-10%` | 语速：`-50%~+100%`，负值减速更清晰 |
| `VOICE_ENABLED` | `true` | Feature Flag，设为 `false` 可完全关闭语音模块 |

**可选服务（PoC默认不启动，专业版启用）**：

| 服务 | 镜像 | 用途 | 状态 |
|------|------|------|------|
| `postgres` | `postgres:16-alpine` | 专业版主数据库 | 已定义，默认注释 |
| `redis` | `redis:7-alpine` | 专业版缓存与会话存储 | 已定义，默认注释 |

**常用命令**：

```bash
# 启动服务（仅promiselink-api）
docker compose -f docker-compose.poc.yml up -d --build

# 查看日志
docker compose -f docker-compose.poc.yml logs -f

# 查看服务状态
docker compose -f docker-compose.poc.yml ps

# 停止服务（数据保留）
docker compose -f docker-compose.poc.yml down

# 停止并清除数据
docker compose -f docker-compose.poc.yml down -v

# 专业版：启动含PG+Redis的完整栈
docker compose -f docker-compose.poc.yml up -d postgres redis promiselink-api
```

### 2.5 .env.poc 配置说明

| 变量 | 默认值 | 必填 | 说明 |
|------|--------|------|------|
| `PROMISELINK_STAGE` | `poc` | 否 | 运行阶段标识 |
| `PROMISELINK_DB_PATH` | `/data/promiselink_poc.db` | 否 | SQLite容器内路径 |
| `PROMISELINK_SECRET_KEY` | - | **是** | JWT签名密钥，用 `secrets.token_urlsafe(32)` 生成 |
| `PROMISELINK_JWT_PRIVATE_KEY_PATH` | - | 否 | JWT私钥路径（PoC用HS256可不填） |
| `PROMISELINK_JWT_PUBLIC_KEY_PATH` | - | 否 | JWT公钥路径 |
| `LLM_API_KEY` | - | **是** | LLM API密钥 |
| `LLM_BASE_URL` | - | **是** | LLM API地址 |
| `LLM_MODEL` | `gpt-4` | 否 | 模型名称 |
| `LLM_TIMEOUT` | `30` | 否 | 请求超时（秒） |
| `LLM_MAX_RETRIES` | `3` | 否 | 最大重试次数 |
| `PROMISELINK_LOG_LEVEL` | `INFO` | 否 | 日志级别 |
| `PROMISELINK_CORS_ORIGINS` | `http://localhost:3000` | 否 | CORS允许来源 |

### 2.6 数据目录说明

```
PromiseLink/
├── data/                        # 持久化数据目录（git已忽略）
│   └── promiselink_poc.db         # SQLite数据库文件
├── .env.poc                     # 环境变量（git已忽略）
├── docker-compose.poc.yml       # PoC编排文件
└── .env.poc.example             # 环境变量模板
```

- `data/` 目录映射到容器内 `/data`，SQLite文件自动创建
- `.env.poc` 已被 `.gitignore` 排除，不会提交到版本库
- 删除 `data/promiselink_poc.db` 等同于重置所有数据
- 数据属于用户，PromiseLink是processor不是owner（数据主权原则）

### 2.7 健康检查验证

```bash
# 基础健康检查
curl http://localhost:8000/api/v1/health

# 检查Docker容器健康状态
docker inspect --format='{{.State.Health.Status}}' promiselink-api

# 查看容器资源使用
docker stats promiselink-api --no-stream

# 查看最近日志
docker compose -f docker-compose.poc.yml logs --tail=50
```

### 2.8 常见问题排查

| 问题 | 原因 | 解决方案 |
|------|------|----------|
| 端口8000被占用 | 其他服务占用 | 修改 `docker-compose.poc.yml` 端口映射，如 `8001:8000` |
| 容器启动后立即退出 | `.env.poc` 缺少必填项 | 检查 `PROMISELINK_SECRET_KEY` 和 `LLM_API_KEY` 是否已填 |
| 健康检查失败 | 应用启动慢或数据库初始化失败 | 等待40s启动期；查看日志 `docker compose logs` |
| LLM调用超时 | 网络问题或API Key无效 | 检查 `LLM_BASE_URL` 和 `LLM_API_KEY`；增大 `LLM_TIMEOUT` |
| 数据库文件权限错误 | 宿主机目录权限 | `chmod 777 ./data` 或调整Docker用户映射 |
| 容器内存不足 | 数据量过大 | 增大 `deploy.resources.limits.memory` |

### 2.9 托管PoC部署模式 [0.4.8新增]

[0.4.8新增] 本节面向**不具备服务器运维能力的非技术用户**，提供一种介于本地PoC和专业版之间的轻量云端部署方案。用户只需准备一台轻量云服务器，即可通过微信小程序访问PromiseLink，无需自行管理本地Docker环境。

#### 2.9.1 概述

**适用场景**：
- 用户无法在本地运行Docker Desktop（如公司电脑受限、无Linux/macOS环境）
- 需要微信小程序随时访问PromiseLink（本地PoC无法被小程序访问）
- 不想投入专业版级别的运维成本（PG+Redis+Nginx全套）
- 希望以最低成本验证PromiseLink核心流程

**与本地PoC的区别**：

| 对比项 | 本地PoC（§2.1~§2.8） | 托管PoC（本节） |
|--------|----------------------|-----------------|
| 运行环境 | 本地Docker Desktop | 云端轻量服务器 |
| 数据库 | SQLite（本地文件） | SQLite（云端持久化卷） |
| 访问方式 | localhost:8000 | HTTPS域名（公网可访问） |
| 小程序接入 | ❌ 不支持 | ✅ 支持 |
| 月度成本 | 零云成本 | 参考云厂商报价 |
| 运维要求 | 需懂Docker基础 | 需懂SSH+基础Linux命令 |

#### 2.9.2 架构图

```
┌─────────────────────────────────────────────────────────────────┐
│                        云端轻量服务器（2C4G）                     │
│                                                                 │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │ Docker Compose                                            │  │
│  │                                                           │  │
│  │  ┌─────────────────┐    ┌─────────────────────────────┐  │  │
│  │  │  promiselink-api   │    │  Nginx（反向代理+SSL终止）   │  │  │
│  │  │  :8000           │◄───│  :443 → :8000               │  │  │
│  │  │  SQLite /data    │    │  Let's Encrypt证书           │  │  │
│  │  └─────────────────┘    └─────────────────────────────┘  │  │
│  │                                                           │  │
│  └───────────────────────────────────────────────────────────┘  │
│                                                                 │
│  数据持久化：./data/promiselink_poc.db（Docker Volume）            │
└─────────────────────────────────────────────────────────────────┘
          ▲
          │ HTTPS
          │
┌─────────┴──────────┐    ┌─────────────────────┐
│  微信小程序         │    │  LLM API（云端）     │
│  （用户主入口）      │    │  OpenAI/Anthropic/   │
│                     │    │  Moka AI             │
└─────────────────────┘    └─────────────────────┘
```

**架构要点**：
- 服务器上仅运行2个Docker容器：promiselink-api + Nginx
- 数据库仍使用SQLite，与本地PoC保持一致（零额外运维）
- Nginx负责SSL终止和反向代理，使微信小程序可通过HTTPS访问
- LLM调用走云端API，服务器不部署本地模型

#### 2.9.3 前置条件

| 依赖 | 说明 | 费用 |
|------|------|------|
| 云服务器 | 2C4G最低配置，推荐阿里云/腾讯云轻量应用服务器 | ~50元/月 |
| 域名 | 已备案域名（微信小程序要求HTTPS+备案域名） | ~50元/年 |
| SSL证书 | Let's Encrypt免费证书（Certbot自动管理） | 免费 |
| LLM API Key | OpenAI / Anthropic / Moka AI 任选其一 | 按用量计费 |
| SSH访问 | 服务器需开放22端口用于远程管理 | 免费 |

> **域名备案说明**：微信小程序要求后端域名必须已完成ICP备案，备案流程通常需要7~20个工作日，建议提前准备。

#### 2.9.4 部署步骤

**Step 1：准备轻量云服务器**

| 云厂商 | 推荐配置 | 说明 |
|--------|---------|------|
| 阿里云轻量应用服务器 | 2C4G / 60GB SSD | 新用户首年优惠 |
| 腾讯云轻量应用服务器 | 2C4G / 60GB SSD | 新用户首年优惠 |
| 华为云HECS | 2C4G / 40GB SSD | 备选 |

> **选择建议**：优先选择阿里云或腾讯云（生态成熟、文档齐全），操作系统选Ubuntu 22.04 LTS。

**Step 2：配置域名 + HTTPS**

```bash
# 1. 域名解析：将域名A记录指向服务器公网IP
#    例如：api.promiselink.cn → 123.45.67.89

# 2. 安装Nginx和Certbot
sudo apt update && sudo apt install -y nginx certbot python3-certbot-nginx

# 3. 配置Nginx基础反向代理
sudo tee /etc/nginx/sites-available/promiselink <<'EOF'
server {
    listen 80;
    server_name api.promiselink.cn;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 60s;
        proxy_send_timeout 60s;
    }
}
EOF

sudo ln -sf /etc/nginx/sites-available/promiselink /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx

# 4. 获取Let's Encrypt SSL证书（自动配置HTTPS）
sudo certbot --nginx -d api.promiselink.cn

# 5. 验证自动续期
sudo certbot renew --dry-run
```

**Step 3：安装Docker + Docker Compose**

```bash
# 安装Docker Engine
curl -fsSL https://get.docker.com | sudo sh

# 将当前用户加入docker组（免sudo）
sudo usermod -aG docker $USER

# 重新登录后验证
docker --version
docker compose version
```

**Step 4：克隆项目 + 配置环境**

```bash
# 克隆项目
git clone <repo-url> && cd PromiseLink

# 创建环境配置
cp .env.poc.example .env.poc

# 编辑配置
nano .env.poc
# 必填项：
#   PROMISELINK_SECRET_KEY=<用下方命令生成>
#   LLM_API_KEY=<你的API Key>
#   LLM_BASE_URL=<对应的API地址>
#   PROMISELINK_CORS_ORIGINS=["https://api.promiselink.cn"]

# 生成SECRET_KEY
python3 -c "import secrets; print(secrets.token_urlsafe(32))"
```

**Step 5：启动服务**

```bash
# 构建并启动（使用PoC编排文件）
docker compose -f docker-compose.poc.yml up -d --build

# 确认容器运行状态
docker compose -f docker-compose.poc.yml ps
```

**Step 6：验证健康检查**

```bash
# 本地验证
curl http://localhost:8000/api/v1/health

# 外部HTTPS验证
curl https://api.promiselink.cn/api/v1/health
```

预期响应：

```json
{
  "status": "healthy",
  "version": "0.4.8",
  "stage": "poc"
}
```

**Step 7：配置微信小程序域名白名单**

在微信公众平台（mp.weixin.qq.com）→ 开发管理 → 开发设置中，添加以下域名：

| 配置项 | 域名 |
|--------|------|
| request合法域名 | `https://api.promiselink.cn` |
| uploadFile合法域名 | `https://api.promiselink.cn` |
| downloadFile合法域名 | `https://api.promiselink.cn` |

#### 2.9.5 运维管理

**备份策略**：

| 备份项 | 方式 | 频率 | 保留周期 |
|--------|------|------|----------|
| SQLite数据库 | `cp data/promiselink_poc.db data/backup/` | 每日 | 7天 |
| .env配置 | 手动备份到安全位置 | 变更时 | 永久 |
| Nginx配置 | `/etc/nginx/sites-available/promiselink` | 变更时 | 永久 |

**自动备份脚本**（crontab）：

```bash
# 每天凌晨3点备份SQLite数据库
0 3 * * * cd /path/to/PromiseLink && mkdir -p data/backup && cp data/promiselink_poc.db data/backup/promiselink_poc_$(date +\%Y\%m\%d).db && find data/backup -name "promiselink_poc_*.db" -mtime +7 -delete
```

**监控**：

| 监控项 | 方式 | 说明 |
|--------|------|------|
| 服务健康 | 健康检查脚本（同§5.3） | 每5分钟探测 `/api/v1/health` |
| 磁盘空间 | `df -h` | 定期检查，SQLite增长缓慢 |
| 容器状态 | `docker compose ps` | 确认容器运行中 |
| SSL证书 | Certbot自动续期 | 证书到期前自动续签 |

**更新升级**：

```bash
# 拉取最新代码并重新构建
cd /path/to/PromiseLink
git pull origin main
docker compose -f docker-compose.poc.yml up -d --build

# 验证更新成功
curl https://api.promiselink.cn/api/v1/health
```

#### 2.9.6 专业版升级（SQLite长期方案）

> **决策变更（2026-06-11）**：个人版专业版继续使用SQLite，无需迁移到PG。托管PoC→专业版仅需切换域名+HTTPS配置，数据无需迁移。

```
托管PoC（SQLite） ──域名+HTTPS──▶ 专业版（SQLite，功能打磨）
```

**升级步骤**（无需数据迁移）：

```bash
# 1. 确认SQLite数据完整
sqlite3 data/promiselink_poc.db "SELECT COUNT(*) FROM events;"

# 2. 更新配置（仅环境变量）
# 编辑 .env 修改以下配置：
#   PROMISELINK_STAGE=phase1
#   （DATABASE_URL保持SQLite不变）

# 3. 启动专业版服务
docker compose -f docker-compose.poc.yml up -d --build

# 4. 验证服务
curl https://api.promiselink.cn/api/v1/health
```

**定制版迁移**（销售团队场景，独立分支）：

当需要升级到定制版（PostgreSQL + Redis + 多租户）时，按以下步骤迁移：

```
个人版（SQLite） ──数据导出──▶ 定制版（PostgreSQL + Redis）
```

```bash
# 1. 导出SQLite数据
sqlite3 data/promiselink_poc.db .dump > /tmp/promiselink_dump.sql

# 2. 转换SQL方言（SQLite → PostgreSQL）
python3 scripts/migrate_sqlite_to_pg.py /tmp/promiselink_dump.sql > /tmp/promiselink_pg.sql

# 3. 切换到定制版编排文件
# 编辑 .env 修改以下配置：
#   PROMISELINK_STAGE=custom
#   DATABASE_URL=postgresql+asyncpg://promiselink:STRONG_PASSWORD@postgres:5432/promiselink
#   REDIS_ENABLED=true
#   REDIS_URL=redis://redis:6379/0

# 4. 启动定制版服务（含PG+Redis）
docker compose -f docker-compose.custom.yml up -d --build

# 5. 初始化PG数据库
docker compose exec promiselink alembic upgrade head

# 6. 导入数据
psql promiselink < /tmp/promiselink_pg_data_only.sql

# 7. 验证数据完整性
python3 scripts/verify_migration.py --source sqlite --target postgresql
```

#### 2.9.7 成本估算

> **说明**：以下为用户自备云资源的成本估算参考，非 PromiseLink 收取费用。专业版授权费用请咨询销售团队。

| 成本项 | 说明 |
|--------|------|
| 云服务器（2C4G） | 参考阿里云/腾讯云轻量应用服务器报价 |
| 域名 | 参考域名注册商报价 |
| SSL证书 | Let's Encrypt 免费 |
| LLM API | 按用量，参考模型厂商报价 |

> **成本对比**：基础版（零云成本）vs 托管 PoC（自备云资源成本），托管 PoC 以极低成本实现微信小程序随时访问。

### 2.10 基础版 vs 专业版 Docker配置

本节对比基础版（本地免费）与专业版（网关中继）的Docker部署差异，帮助用户根据需求选择合适的部署方案。

#### 2.10.1 架构差异

**基础版Docker**：仅FastAPI + SQLite + 本地Embedding，无网关连接。用户通过Taro H5在本地浏览器访问。

```
┌──────────────────────────────────────┐
│  本地 Docker Desktop                  │
│                                      │
│  ┌────────────────────────────────┐  │
│  │  promiselink-api                 │  │
│  │  :8000                         │  │
│  │  FastAPI + SQLite + Embedding  │  │
│  └────────────────────────────────┘  │
│                                      │
│  访问方式：localhost:8000 (Taro H5)   │
└──────────────────────────────────────┘
```

**专业版Docker**：与基础版相同的单容器，但设置 `RELAY_GATEWAY_URL` 环境变量后，relay_client 作为 FastAPI 进程内的后台 asyncio Task 自动启动，AI调用走网关代理。用户通过微信小程序随时随地访问。

> **关键设计**：relay_client 是 **FastAPI进程内的嵌入式模块**（embedded module），**不是独立容器**。设置 `RELAY_GATEWAY_URL` 时自动启动，未设置时不启动。

```
┌──────────────────────────────────────┐
│  本地 Docker Desktop                  │
│                                      │
│  ┌────────────────────────────────┐  │
│  │  promiselink-api                 │  │
│  │  :8000                         │  │
│  │  FastAPI + SQLite + Embedding  │  │
│  │  ┌──────────────────────────┐  │  │
│  │  │ relay_client（嵌入式模块）│  │  │
│  │  │ 后台asyncio Task         │  │  │
│  │  │ AI调用走网关代理         │  │  │
│  │  └────────────┬─────────────┘  │  │
│  └───────────────┼────────────────┘  │
│                  │ WSS                │
└──────────────────┼───────────────────┘
                   │
        ┌──────────▼──────────┐    ┌─────────────┐
        │ 云中继网关           │    │ 微信小程序   │
        │ (PromiseLink)         │◄───│ （用户入口） │
        └────────────────────┘    └─────────────┘
```

#### 2.10.2 Docker Compose差异表

| 配置项 | 基础版（本地免费） | 专业版（网关中继） |
|--------|-------------------|-------------------|
| **服务** | promiselink-api | promiselink-api（内含relay_client后台Task） |
| **端口** | 8000:8000 | 8000:8000 |
| **数据库** | SQLite（本地文件） | SQLite（本地文件） |
| **AI调用** | 本地LLM_API_KEY直连 | 网关代理（无需本地API Key） |
| **Embedding** | 本地计算 | 本地计算 |
| **网关连接** | 无 | WSS连接云中继网关（relay_client后台Task） |
| **访问方式** | Taro H5浏览器 | 微信小程序 + Taro H5 |
| **环境变量** | LLM_API_KEY + POC_SECRET | LLM_API_KEY + POC_SECRET + RELAY_GATEWAY_URL + RELAY_TOKEN |
| **月成本** | 零云成本 | ~50元/月（网关服务费） |

#### 2.10.3 基础版安装命令

```bash
# 基础版：仅本地Docker，Taro H5浏览器访问
docker run -d \
  -p 8000:8000 \
  -v ~/promiselink-data:/app/data \
  -e LLM_API_KEY=sk-xxx \
  -e POC_SECRET=your-secret \
  promiselink:latest

# Taro H5编译
cd PromiseLink/frontend && npm run build:h5
```

#### 2.10.4 专业版安装命令

```bash
# 专业版：本地Docker + 云中继网关，微信小程序访问
docker run -d \
  -p 8000:8000 \
  -v ~/promiselink-data:/app/data \
  -e LLM_API_KEY=sk-xxx \
  -e POC_SECRET=your-secret \
  -e RELAY_GATEWAY_URL=wss://api.promiselink.cn/relay \
  -e RELAY_TOKEN=your-relay-token \
  promiselink:latest

# Taro H5编译（专业版也支持H5访问）
cd PromiseLink/frontend && npm run build:h5
# 微信小程序编译（独立仓库 PromiseLink-miniapp）
# cd PromiseLink-miniapp && npm run build:weapp
```

#### 2.10.5 版本切换

基础版和专业版使用相同的Docker镜像，通过环境变量控制行为：

| 环境变量 | 基础版 | 专业版 | 说明 |
|----------|--------|--------|------|
| `RELAY_GATEWAY_URL` | 不设置 | `wss://api.promiselink.cn/relay` | 设置即启用网关中继 |
| `RELAY_TOKEN` | 不设置 | 网关认证Token | 网关连接凭证 |

> **说明**：从基础版升级到专业版无需重新部署，只需添加 `RELAY_GATEWAY_URL` 和 `RELAY_TOKEN` 环境变量后重启容器即可。relay_client在检测到 `RELAY_GATEWAY_URL` 配置后，作为FastAPI进程内的后台asyncio Task自动启动，无需独立容器。

---

## 3. CI/CD流水线 [0.2.0新增]

### 3.1 GitHub Actions概览 [0.2.0新增]

[0.2.0新增] PromiseLink使用GitHub Actions实现持续集成，配置文件位于 `.github/workflows/ci.yml`。每次push到`main`/`develop`分支或向`main`提交PR时自动触发。

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
│   mypy src/promiselink --ignore-missing-imports → 类型注解检查     │
│   注：|| true 表示类型错误不阻断CI（渐进式采用）                  │
├─────────────────────────────────────────────────────────────────┤
│ Step 6: Run Tests (pytest)                                       │
│   pytest tests/ -v --cov=src/promiselink                          │
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
| `DATABASE_URL` | `postgresql+asyncpg://promiselink:promiselink_test@localhost:5432/promiselink_test` | 异步PG连接串 |
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
| 自动部署(专业版) | main分支推送 | SSH到云服务器执行 `docker compose pull && up -d` |
| 小程序自动化发布 | Taro构建就绪 | `miniprogram-ci` 自动上传+提审 |
| 环境扩散部署 | 定制版启动前 | dev → staging → production 多环境流水线 |

---

## 4. 专业版部署（网关中继方案）

> **决策变更（2026-06-11）**：专业版采用网关中继架构，本地Docker运行应用服务，通过云中继网关实现微信小程序访问和AI调用代理。无需自建云端服务器，无需域名备案，本地Docker + 网关即可完成部署。

### 4.1 架构概述

专业版的核心是**云中继网关**（Relay Gateway），它解决了两个关键问题：
1. **微信小程序访问**：小程序需要公网HTTPS域名，网关提供统一入口
2. **AI调用代理**：网关代理LLM API调用，用户无需自行配置API Key

```
┌──────────────────────────────────────────────────────────┐
│  用户本地环境（Docker Desktop）                            │
│                                                          │
│  ┌────────────────────────────────────────────────────┐  │
│  │  promiselink-api（单容器）                            │  │
│  │  :8000                                             │  │
│  │  FastAPI + SQLite + 本地Embedding                  │  │
│  │  ┌──────────────────────────────────────────────┐  │  │
│  │  │ relay_client（嵌入式模块，后台asyncio Task）  │  │  │
│  │  │ 自动连接云中继网关 / AI调用走网关代理         │  │  │
│  │  │ 心跳保活+断线重连                            │  │  │
│  │  └──────────────────────┬───────────────────────┘  │  │
│  └─────────────────────────┼──────────────────────────┘  │
│                            │                              │
└────────────────────────────┼──────────────────────────────┘
                             │ WSS (WebSocket over TLS)
                             │
┌────────────────────────────▼──────────────────────────────┐
│  PromiseLink 云中继网关（托管服务）                           │
│                                                           │
│  ┌─────────────────┐  ┌─────────────────┐                │
│  │  WebSocket中继   │  │  AI代理服务      │                │
│  │  小程序↔本地服务  │  │  LLM API转发    │                │
│  └────────┬────────┘  └────────┬────────┘                │
│           │                     │                          │
└───────────┼─────────────────────┼──────────────────────────┘
            │                     │
   ┌────────▼────────┐   ┌───────▼────────┐
   │  微信小程序      │   │  LLM API       │
   │  （用户主入口）  │   │  (OpenAI等)    │
   └─────────────────┘   └────────────────┘
```

### 4.2 前置条件

| 依赖 | 说明 |
|------|------|
| Docker Desktop | 24+（本地运行） |
| Docker Compose | v2.20+ |
| 中继网关Token | 从PromiseLink获取的RELAY_TOKEN |
| 内存 | ≥4GB 可用 |

> **优势**：专业版无需云服务器、无需域名、无需SSL证书、无需ICP备案，仅需本地Docker + 网关Token即可部署。

### 4.3 Docker部署

专业版使用SQLite + 云中继网关，无需PG/Redis：

```yaml
# 服务清单（专业版）— relay_client为FastAPI进程内模块，非独立容器
services:
  promiselink:        # FastAPI 应用 + SQLite + 本地Embedding + relay_client后台Task
```

**部署步骤**：

```bash
# 1. 克隆项目
git clone <repo-url> && cd PromiseLink

# 2. 创建环境配置
cp .env.poc.example .env
# 编辑 .env，修改以下关键项：
#   PROMISELINK_STAGE=professional
#   DATABASE_URL=sqlite+aiosqlite:///./data/promiselink.db
#   RELAY_GATEWAY_URL=wss://api.promiselink.cn/relay
#   RELAY_TOKEN=your-relay-token
#   （无需REDIS_URL，专业版使用内存缓存）
#   （无需LLM_API_KEY，AI调用走网关代理）

# 3. 启动服务（relay_client作为后台Task自动启动）
docker compose -f docker-compose.poc.yml up -d --build

# 4. 验证relay_client已启动
docker compose logs promiselink | grep "relay_client"
# 预期输出：relay_client started, connecting to wss://api.promiselink.cn/relay

# 5. 验证健康检查
curl http://localhost:8000/api/v1/health
```

### 4.4 中继网关配置

| 配置项 | 环境变量 | 默认值 | 说明 |
|--------|---------|--------|------|
| 网关地址 | `RELAY_GATEWAY_URL` | - | 云中继网关WebSocket地址 |
| 认证Token | `RELAY_TOKEN` | - | 网关连接凭证（从PromiseLink获取） |
| 心跳间隔 | `RELAY_HEARTBEAT_INTERVAL` | `30` | 心跳保活间隔（秒） |
| 重连延迟 | `RELAY_RECONNECT_DELAY` | `5` | 断线重连初始延迟（秒） |
| 最大重连延迟 | `RELAY_MAX_RECONNECT_DELAY` | `60` | 断线重连最大延迟（秒） |

**relay_client行为**（FastAPI进程内后台asyncio Task）：
- `RELAY_GATEWAY_URL` 设置时自动启动，未设置时不启动
- 启动后自动连接云中继网关
- 定期发送心跳保活（默认30秒）
- 断线自动重连（指数退避，5s→10s→20s→40s→60s）
- AI调用自动走网关代理，无需本地配置LLM API Key
- 微信小程序请求通过网关中继转发到本地服务

### 4.5 定制版PostgreSQL配置（销售团队场景）

> 仅定制版需要，专业版使用SQLite。

| 配置项 | 推荐值 | 说明 |
|--------|--------|------|
| 版本 | 16-alpine | 轻量镜像（与CI一致） |
| 数据库名 | `promiselink` | - |
| 用户名 | `promiselink` | 专用账号，非root |
| 密码 | 强随机密码 | 32位以上，含大小写数字特殊字符 |
| 数据卷 | `postgres_data` | Docker命名卷持久化 |
| 连接池 | 默认 | 单用户无需调优 |

### 4.6 定制版Redis配置（销售团队场景）

> 仅定制版需要，专业版使用内存缓存。

| 配置项 | 推荐值 | 说明 |
|--------|--------|------|
| 版本 | 7-alpine | 轻量镜像 |
| 端口 | 6379 | 仅容器内网访问 |
| 密码 | 强随机密码 | `requirepass` 配置 |
| 最大内存 | 128mb | 单用户足够 |
| 淘汰策略 | `allkeys-lru` | 内存不足时淘汰最少使用 |

### 4.7 微信小程序域名白名单配置

专业版通过云中继网关接入微信小程序，网关已提供HTTPS域名。在微信公众平台（mp.weixin.qq.com）配置以下域名：

| 配置项 | 域名 | 说明 |
|--------|------|------|
| request合法域名 | `https://api.promiselink.cn` | API请求（经网关中继） |
| socket合法域名 | `wss://api.promiselink.cn` | WebSocket中继连接 |
| uploadFile合法域名 | `https://api.promiselink.cn` | 文件上传 |
| downloadFile合法域名 | `https://api.promiselink.cn` | 文件下载 |
| webview业务域名 | `promiselink.cn` | H5页面 |

> **说明**：专业版无需自行配置Nginx和SSL证书，云中继网关已处理HTTPS终止和域名管理。

**小程序 app.json 配置**：

```json
{
  "networkTimeout": {
    "request": 10000
  }
}
```

### 4.8 备份与恢复

**SQLite备份**（专业版本地数据）：

```bash
# 手动备份
cp ~/promiselink-data/promiselink_poc.db ~/promiselink-data/backup/promiselink_poc_$(date +%Y%m%d).db

# 定时备份（crontab）
# 每天凌晨3点备份
0 3 * * * mkdir -p ~/promiselink-data/backup && cp ~/promiselink-data/promiselink_poc.db ~/promiselink-data/backup/promiselink_poc_$(date +\%Y\%m\%d).db && find ~/promiselink-data/backup -name "promiselink_poc_*.db" -mtime +7 -delete
```

**定制版PostgreSQL备份**：

```bash
# 手动备份
docker compose exec postgres pg_dump -U promiselink promiselink > backup_$(date +%Y%m%d).sql

# 定时备份（crontab）
0 3 * * * cd /path/to/PromiseLink && docker compose exec -T postgres pg_dump -U promiselink promiselink | gzip > /backups/promiselink_$(date +\%Y\%m\%d).sql.gz

# 恢复
gunzip -c backup_20260604.sql.gz | docker compose exec -T postgres psql -U promiselink promiselink
```

**备份保留策略**：

| 备份类型 | 保留周期 | 存储位置 |
|----------|----------|----------|
| 每日备份 | 7天 | 本地 ~/promiselink-data/backup/ |
| 每周备份 | 4周 | 本地 ~/promiselink-data/backup/ |
| 手动备份 | 永久 | 按需归档 |

---

## 5. 监控指标体系 [0.2.0新增]

### 5.1 P0业务指标（Prometheus） [0.2.0新增]

[0.2.0新增] 以下6项P0指标来自技术设计v2.5 §8.0.5，是PromiseLink业务健康度的核心观测信号。建议在专业版接入Prometheus+Grafana进行可视化监控。

#### 指标1：Input Scope分类延迟

```yaml
name: promiselink_input_scope_classification_duration_seconds
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
name: promiselink_todos_generated_total
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
name: promiselink_relationship_brief_query_duration_seconds
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
name: promiselink_relationship_stage_transitions_total
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
name: promiselink_pii_sanitization_coverage
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
name: promiselink_http_requests_total
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

### 5.1.1 Voice专用监控指标 [F-50新增]

[F-50新增] 以下4项指标专门用于语音助手（F-50）模块的运行观测，建议与§5.1的6项P0指标一同接入Prometheus+Grafana。

| 指标名 | 类型 | Labels | 说明 | 告警阈值 |
|--------|------|--------|------|---------|
| `voice_query_duration_seconds` | histogram | intent, result | 语音查询端到端延迟（ASR→NLU→LLM→TTS全链路） | P95 > 8s |
| `voice_intent_confidence` | histogram | intent | NLU意图识别置信度分布 | < 0.7 占比 > 20% |
| `voice_asr_error_total` | counter | error_type | ASR错误计数（网络/超时/格式） | 任意 > 10/min |
| `voice_tts_cache_hit_rate` | gauge | — | TTS缓存命中率（避免重复调用Edge-TTS） | < 50% |

**Prometheus查询示例**：

```promql
# 语音查询P95延迟
histogram_quantile(0.95, sum(rate(voice_query_duration_seconds_bucket[5m])) by (le))

# 意图识别低置信度比例（<0.7视为不可靠）
sum(rate(voice_intent_confidence_bucket{le="0.7"}[5m]))
/
sum(rate(voice_intent_confidence_count[5m]))

# ASR错误速率（按类型分组）
sum(rate(voice_asr_error_total[5m])) by (error_type)

# TTS缓存命中率趋势
voice_tts_cache_hit_rate
```

**Grafana面板建议**：

| 面板 | 图表类型 | 查询 | 说明 |
|------|----------|------|------|
| 语音查询延迟分布 | Heatmap | `voice_query_duration_seconds` | 热力图展示延迟分布 |
| 意图置信度分布 | Pie Chart | `voice_intent_confidence_count` | 各意图置信度占比 |
| ASR错误趋势 | Time Series | `rate(voice_asr_error_total[5m])` | 错误计数时序 |
| TTS缓存命中率 | Gauge | `voice_tts_cache_hit_rate` | 实时命中率 |

### 5.2 监控工具链推荐 [0.2.0新增]

| 阶段 | 方案 | 组件 |
|------|------|------|
| **PoC** | Docker内置 | `docker stats` + `docker compose logs -f` + 健康检查脚本 |
| **专业版** | Prometheus + Grafana | Prometheus采集 + Grafana仪表盘（6项P0指标Dashboard） |
| **定制版** | 云监控套件 | 阿里云ARMS / 腾讯云监控 + 自建告警通道 |

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
    echo "PromiseLink health check failed: HTTP $RESPONSE" >> /var/log/promiselink_alert.log
    # 可接入企业微信/钉钉通知
fi
```

---

## 6. 定制版 K8s部署

### 6.1 概述

定制版为生产增强阶段，采用Kubernetes编排，实现高可用与弹性扩缩容。本节仅规划方向，不详细展开。

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
charts/promiselink/
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

[0.2.0新增] PromiseLink使用Alembic（SQLAlchemy官方迁移工具）管理数据库Schema变更。

**初始化步骤**（首次设置）：

```bash
# 1. 安装Alembic（已在requirements.txt中）
pip install alembic

# 2. 初始化Alembic目录结构
alembic init alembic

# 3. 配置alembic.ini
#    修改 sqlalchemy.url 为你的数据库连接串
#    PoC: sqlite:///./data/promiselink_poc.db
#    专业版: postgresql://promiselink:***@localhost:5432/promiselink

# 4. 配置 env.py（关键：关联SQLAlchemy模型）
# alembic/env.py 内容如下：
from promiselink.models import Base
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
PromiseLink/
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
└── src/promiselink/models.py        # SQLAlchemy ORM模型定义
```

### 7.2 Autogenerate工作流 [0.2.0新增]

[0.2.0新增] 推荐使用Alembic autogenerate功能自动检测模型变更并生成迁移脚本：

```bash
# 1. 修改 SQLAlchemy 模型（src/promiselink/models.py）
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
| 3 | **定制版迁移是一次性全量迁移** | 个人版SQLite→定制版PG，不走Alembic增量，使用SQLite dump + 方言转换 + PG导入 |
| 4 | **迁移前必须备份** | 自动化脚本先执行 `pg_dump` 再 `alembic upgrade` |
| 5 | **零停机迁移** | 新增列用DEFAULT值，不锁表；删列分两步（先标记deprecated→下个主版本删除） |

### 7.5 SQLite→PostgreSQL升级路径（定制版专用） [0.2.0新增，2026-06-11更新]

> **注意**：个人版长期使用SQLite，此迁移路径仅适用于销售团队定制版。

```bash
# ===== Step 1: 导出SQLite数据 =====
sqlite3 data/promiselink_poc.db .dump > /tmp/promiselink_dump.sql

# ===== Step 2: 转换SQL方言（SQLite → PostgreSQL） =====
python3 scripts/migrate_sqlite_to_pg.py /tmp/promiselink_dump.sql > /tmp/promiselink_pg.sql
# 转换内容包括：
#   - SQLite AUTOINCREMENT → PG SERIAL/BIGSERIAL
#   - SQLite INTEGER PRIMARY KEY → PG BIGINT PRIMARY KEY
#   - SQLite 't'/'f' 布尔 → PG TRUE/FALSE
#   - SQLite 双引号标识符 → PG 双引号（基本兼容）
#   - SQLite 特有函数替换（datetime('now') → NOW() 等）

# ===== Step 3: 创建PG数据库并执行Alembic初始迁移 =====
createdb promiselink
alembic upgrade head

# ===== Step 4: 导入数据（跳过已由Alembic创建的表结构） =====
psql promiselink < /tmp/promiselink_pg_data_only.sql

# ===== Step 5: 验证数据完整性 =====
python3 scripts/verify_migration.py --source sqlite --target postgresql
```

**迁移验证方法**：

```bash
# 1. 记录数对比
echo "SQLite:" && sqlite3 data/promiselink_poc.db \
  "SELECT 'events', COUNT(*) FROM events
   UNION ALL SELECT 'entities', COUNT(*) FROM entities
   UNION ALL SELECT 'associations', COUNT(*) FROM associations
   UNION ALL SELECT 'todos', COUNT(*) FROM todos;"

echo "PostgreSQL:" && docker compose exec postgres psql -U promiselink -c \
  "SELECT 'events' as tbl, COUNT(*) FROM events
   UNION ALL SELECT 'entities', COUNT(*) FROM entities
   UNION ALL SELECT 'associations', COUNT(*) FROM associations
   UNION ALL SELECT 'todos', COUNT(*) FROM todos;"

# 2. 抽样数据对比（随机取10条比对关键字段）
python3 scripts/verify_migration.py --source sqlite --target postgresql --sample-size 10

# 3. 功能验证
curl -H "Authorization: Bearer $TOKEN" https://api.promiselink.cn/api/v1/entities
curl -H "Authorization: Bearer $TOKEN" https://api.promiselink.cn/api/v1/events
```

**迁移改动量预估**：

| 迁移项 | PoC | 专业版 | 改动量 |
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
| API对接进度滞后 | 超过 **3周** 未完成 | 小程序前端无法对接PromiseLink API |

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
taro init promiselink-miniapp

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

[0.2.0新增] 自建小程序需对接PromiseLink后端API的关键事项：

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

**CORS配置**：确保 `PROMISELINK_CORS_ORIGINS` 包含小程序请求来源（开发阶段为本地调试地址，生产阶段为小程序合法域名）。

---

## 8.5 Voice Service 运维手册 [F-50新增]

[F-50新增] 本节提供语音助手模块（F-50）的运维指导，涵盖常见问题排查、性能调优参数和安全检查清单。

### 8.5.1 常见问题排查

| 问题 | 可能原因 | 排查步骤 |
|------|---------|---------|
| TTS无声音输出 | edge-tts网络不通（无法访问Microsoft TTS endpoint） | 容器内执行 `curl -I https://speech.platform.bing.com/consumer/speech/synthesize/readaloud/edge/v1?TracingId=test` 测试连通性；检查DNS和代理设置 |
| ASR识别不准 | 背景噪音大 / 音频采样率不匹配 | 检查API响应中 `asr_confidence` 字段值，若持续 < 0.6 建议用户在安静环境重试；确认音频格式为16kHz单声道WAV/MP3 |
| 查询超时（>8s） | LLM API响应慢 / 网络延迟高 | 检查响应中 `processing_time_ms` 字段定位瓶颈环节（ASR/NLU/LLM/TTS）；必要时增大 `LLM_TIMEOUT` |
| TTS缓存不命中 | answer_text变化频繁（LLM输出不稳定） | 检查响应中 `tts_cached` 字段；若命中率低考虑对answer_text做归一化（去除时间戳等变化内容） |
| 语音功能完全不可用 | `VOICE_ENABLED=false` 或 edge-tts未安装 | 确认环境变量 `VOICE_ENABLED=true`；容器内执行 `python -c "import edge_tts; print(edge_tts.__version__)"` 验证安装 |

**端到端排查命令**：

```bash
# 1. 验证edge-tts可用性
docker compose exec promiselink-api python -c "
import asyncio, edge_tts
async def test():
    communicate = edge_tts.Communicate('测试语音', 'zh-CN-XiaoxiaoNeural')
    await communicate.save('/tmp/test_tts.mp3')
    print('TTS OK: /tmp/test_tts.mp3')
asyncio.run(test())
"

# 2. 检查TTS缓存目录
docker compose exec promiselink-api ls -la /var/cache/promiselink/tts/

# 3. 查看Voice相关日志
docker compose logs promiselink-api 2>&1 | grep -i "voice\|tts\|asr\|nlu"

# 4. 检查Voice环境变量
docker compose exec promiselink-api env | grep -E "^TTS_|^VOICE_"
```

### 8.5.2 性能调优参数

| 参数 | 默认值 | 调优建议 | 说明 |
|------|--------|----------|------|
| `TTS_CACHE_TTL` | `24h` | 高频场景可延长到 `72h` | TTS缓存过期时间，延长可提高命中率但占用更多磁盘 |
| `NLU_RULE_THRESHOLD` | `0.85` | 提高到 `0.9` 减少LLM调用但降低覆盖率 | 规则引擎意图识别阈值，越高越严格 |
| `VOICE_SESSION_TTL` | `7d` | 分析需求可延长到 `30d` | 语音会话保留时长，影响多轮对话上下文 |
| `TTS_MAX_TEXT_LENGTH` | `500字符` | 根据实际场景调整 | 单次TTS合成最大文本长度，超长文本需分段 |
| `ASR_AUDIO_MAX_SIZE` | `10MB` | PoC足够，专业版按需调整 | ASR上传音频最大尺寸限制 |

**性能基准目标（PoC阶段）**：

| 环节 | 目标延迟 | 说明 |
|------|----------|------|
| ASR（语音→文字） | < 2s | 使用云端Whisper API |
| NLU（意图识别） | < 500ms | 规则引擎优先，兜底LLM |
| LLM查询生成 | < 5s | 受限于外部API响应 |
| TTS（文字→语音） | < 1s | Edge-TTS + 缓存命中时 < 100ms |
| **端到端总计** | **< 8s** | P95告警阈值 |

### 8.5.3 安全检查清单（语音相关）

部署Voice功能前，请逐项确认以下安全措施：

- [ ] **TTS缓存目录权限**：`/var/cache/promiselink/tts` 归属 `promiselink` 用户（非world-writable），验证：`stat /var/cache/promiselink/tts`
- [ ] **认证保护**：`/voice/*` 所有端点均需JWT认证（含 `/voice/tts`、`/voice/query`、`/voice/session`）
- [ ] **原始音频不落地**：`voice_sessions` 表仅存储ASR转录文本，**不存储**原始音频二进制数据
- [ ] **PII脱敏**：TTS输出经过PII脱敏管道处理（手机号/邮箱/微信号等敏感信息已替换）
- [ ] **聚合数据安全**：`voice_analytics` 统计数据不含任何个人身份信息（PII），仅包含聚合指标
- [ ] **网络加密**：edge-tts所有网络访问走HTTPS（默认行为，无需额外配置）
- [ ] **输入大小限制**：ASR音频上传有文件大小限制（默认10MB），防止DoS攻击
- [ ] **速率限制**：语音查询端点纳入全局限流策略（默认100次/分/user_id）

---

## 9. 环境变量参考

### 9.1 完整环境变量表

| 变量名 | 默认值 | 必填 | 阶段 | 说明 |
|--------|--------|------|------|------|
| **应用基础** | | | | |
| `PROMISELINK_STAGE` | `development` | 否 | 全部 | 运行阶段：`poc` / `phase1` / `phase2` |
| `PROMISELINK_SECRET_KEY` | `change-me-in-production` | **是** | 全部 | JWT签名密钥，生产环境必须修改（≥32字符） |
| `PROMISELINK_DB_PATH` | `/data/promiselink_poc.db` | 否 | PoC | SQLite数据库路径（容器内） |
| `PROMISELINK_LOG_LEVEL` | `INFO` | 否 | 全部 | 日志级别：DEBUG/INFO/WARNING/ERROR |
| `PROMISELINK_CORS_ORIGINS` | `["http://localhost:3000"]` | 否 | 全部 | CORS允许来源，JSON数组格式 |
| **数据库** | | | | |
| `DATABASE_URL` | `sqlite:///./data/promiselink.db` | 否 | 全部 | 数据库连接串，专业版改为PG异步串 |
| **Redis** | | | | |
| `REDIS_URL` | `redis://localhost:6379/0` | 否 | 专业版+ | Redis连接串 |
| `REDIS_ENABLED` | `false` | 否 | 全部 | 是否启用Redis |
| **认证** | | | | |
| `ALGORITHM` | `HS256` | 否 | 全部 | JWT算法，专业版改为RS256 |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | `15` | 否 | 全部 | Access Token有效期（分钟） |
| `REFRESH_TOKEN_EXPIRE_DAYS` | `7` | 否 | 全部 | Refresh Token有效期（天） |
| `PROMISELINK_JWT_PRIVATE_KEY_PATH` | - | 否 | 专业版+ | RS256私钥路径 |
| `PROMISELINK_JWT_PUBLIC_KEY_PATH` | - | 否 | 专业版+ | RS256公钥路径 |
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
| **语音助手(F-50)** | | | | |
| `VOICE_ENABLED` | `true` | 否 | 专业版+ | Feature Flag：是否启用语音功能（`true`/`false`） |
| `TTS_VOICE_NAME` | `zh-CN-XiaoxiaoNeural` | 否 | 专业版+ | Edge-TTS语音角色名称 |
| `TTS_RATE` | `-10%` | 否 | 专业版+ | TTS语速调节（`-50%~+100%`） |
| `TTS_CACHE_TTL` | `86400` | 否 | 专业版+ | TTS缓存过期时间（秒），默认24h |
| `NLU_RULE_THRESHOLD` | `0.85` | 否 | 专业版+ | NLU规则引擎意图识别阈值 |
| `VOICE_SESSION_TTL` | `604800` | 否 | 专业版+ | 语音会话保留时间（秒），默认7d |

---

## 10. 故障排查手册

### 10.1 常见错误及解决方案

| 错误现象 | 可能原因 | 排查步骤 | 解决方案 |
|----------|----------|----------|----------|
| 容器无法启动 | 配置文件缺失/错误 | `docker compose logs` 查看启动日志 | 检查 `.env` 文件是否完整 |
| 401 Unauthorized | JWT密钥不匹配 | 检查 `PROMISELINK_SECRET_KEY` 是否一致 | 确保所有服务使用相同密钥 |
| 500 Internal Error | 数据库连接失败 | 检查 `DATABASE_URL` 和数据库状态 | 确认PG/SQLite可访问 |
| LLM调用429 | API限流 | 检查API Key配额 | 降低调用频率或升级API套餐 |
| LLM调用超时 | 网络问题 | `curl $LLM_BASE_URL` 测试连通性 | 检查网络/代理设置 |
| 数据库迁移失败 | 表结构不一致 | `alembic current` 查看当前版本 | `alembic upgrade head` 重新迁移 |
| CORS报错 | Origin不在白名单 | 检查 `PROMISELINK_CORS_ORIGINS` | 添加请求来源到白名单 |
| Redis连接失败 | Redis未启动或密码错误 | `docker compose ps redis` | 启动Redis或修正密码配置 |
| 小程序请求失败 | 域名未配置白名单 | 检查微信公众平台配置 | 添加 `https://api.promiselink.cn` |
| 磁盘空间不足 | 日志/数据过大 | `df -h` 检查磁盘 | 清理日志或扩容磁盘 |

### 10.2 日志查看方法

```bash
# 查看全部服务日志
docker compose logs -f

# 查看指定服务日志
docker compose logs -f promiselink
docker compose logs -f postgres
docker compose logs -f redis

# 查看最近N行日志
docker compose logs --tail=100 promiselink

# 按时间过滤日志
docker compose logs --since="2026-06-04T10:00:00" promiselink

# 导出日志到文件
docker compose logs promiselink > promiselink.log 2>&1
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

| 检查项 | PoC | 专业版 | 验证方法 |
|--------|-----|--------|----------|
| `PROMISELINK_SECRET_KEY` 不为默认值 | ✅ | ✅ | 检查 `.env` 文件 |
| LLM API Key 不在代码仓库中 | ✅ | ✅ | `git log --all --full-history -- "*.env*"` |
| `.env` 文件被 `.gitignore` 排除 | ✅ | ✅ | `git status` 不显示 `.env` |
| 数据库密码为强随机密码 | - | ✅ | 32位以上随机字符串 |
| Redis密码已设置 | - | ✅ | 检查 `requirepass` 配置 |
| 容器端口不暴露到公网 | - | ✅ | 仅Nginx暴露80/443 |
| Docker镜像为最新版 | ✅ | ✅ | `docker pull` 更新基础镜像 |
| Dockerfile非root用户运行 | ✅ | ✅ | `USER promiselink` 已配置 |
| HEALTHCHECK已启用 | ✅ | ✅ | 30s间隔/10s超时/3次重试 |

### 11.2 生产环境安全加固

| 加固项 | 说明 | 阶段 |
|--------|------|------|
| **TLS强制** | 全部HTTP请求301跳转HTTPS | 专业版 |
| **HSTS启用** | `Strict-Transport-Security` 头 | 专业版 |
| **CORS严格白名单** | 仅允许生产域名 | 专业版 |
| **PII字段加密** | AES-256-GCM加密phone/email/wechat | 专业版 |
| **JWT RS256** | 非对称签名替代HS256 | 专业版 |
| **Ticket模式** | 小程序WebView安全认证 | 专业版 |
| **Redis密码** | `requirepass` + `protected-mode` | 专业版 |
| **PG SSL连接** | 数据库连接启用SSL | 专业版 |
| **限流配置** | Redis按user_id限流100次/分 | 专业版 |
| **请求签名** | HMAC-SHA256防重放 | 专业版 |
| **审计日志** | 数据库审计表记录所有写操作 | 专业版 |
| **数据导出/删除** | 用户数据主权保障 | 专业版 |
| **定期依赖扫描** | `pip audit` + `bandit` | 专业版 |
| **Docker镜像扫描** | `trivy image promiselink:latest` | 专业版 |
| **备份加密** | pg_dump输出加密存储 | 定制版 |
| **KMS密钥管理** | 密钥不落盘，运行时获取 | 定制版 |
| **TDE透明加密** | 数据库全量加密 | 定制版 |

---

## 12. Insight Engine 部署 [0.3.0新增]

> PromiseLink从"被动记录"升级为"主动服务"，Insight Engine引入动态优先级评分和隐式反馈收集。本节定义Insight Engine相关的部署配置。

### 12.1 优先级评分定时任务 [0.3.0新增]

PriorityScorer每小时重新计算所有活跃Todo的动态分数。

**PoC阶段**：简单Cron脚本

```bash
# crontab -e 添加以下条目
# 每小时整点重新计算动态分数
0 * * * * cd /path/to/PromiseLink && python -m promiselink.jobs.recalculate_scores >> /var/log/promiselink/scores.log 2>&1
```

**recalculate_scores脚本**：

```python
# promiselink/jobs/recalculate_scores.py
"""
定时任务：重新计算所有活跃Todo的dynamic_score
公式（PoC）：Score = 0.4 × urgency + 0.6 × importance
"""
import asyncio
from datetime import datetime, timezone
from promiselink.core.database import get_session
from promiselink.models import Todo
from promiselink.insight.priority_scorer import PriorityScorer
from sqlalchemy import select


async def recalculate_all_scores():
    scorer = PriorityScorer()
    async with get_session() as session:
        # 查询所有未完成Todo
        result = await session.execute(
            select(Todo).where(Todo.status.in_(["pending", "in_progress"]))
        )
        todos = result.scalars().all()

        for todo in todos:
            todo.dynamic_score = await scorer.calculate(todo)
            todo.score_calculated_at = datetime.now(timezone.utc)

        await session.commit()
        print(f"[{datetime.now()}] Recalculated scores for {len(todos)} todos")


if __name__ == "__main__":
    asyncio.run(recalculate_all_scores())
```

**专业版**：升级为Celery Beat / APScheduler

| 方案 | 优点 | 缺点 |
|------|------|------|
| Celery Beat | 成熟稳定、支持分布式、与Redis集成 | 需额外部署Celery Worker |
| APScheduler | 轻量、集成在FastAPI进程内 | 不支持分布式、单点故障 |

**推荐**：专业版使用APScheduler（单用户场景足够），定制版迁移到Celery Beat。

### 12.2 pgcrypto扩展（专业版） [0.3.0新增]

concern和capability字段包含敏感商业信息，专业版需启用字段级加密。

**安装pgcrypto扩展**：

```sql
-- 在PostgreSQL中执行
CREATE EXTENSION IF NOT EXISTS pgcrypto;
```

**验证安装**：

```sql
-- 验证扩展已安装
SELECT extname, extversion FROM pg_extension WHERE extname = 'pgcrypto';

-- 测试加密函数
SELECT encrypt('test_data'::bytea, 'secret_key'::bytea, 'aes');
SELECT decrypt(encrypt('test_data'::bytea, 'secret_key'::bytea, 'aes'), 'secret_key'::bytea, 'aes');
```

**Alembic迁移脚本**：

```python
# alembic/versions/006_concern_capability_encryption.py
"""Encrypt concern and capability fields

Revision ID: 006
Revises: 005
Create Date: 2026-06-06
"""
from alembic import op
import sqlalchemy as sa


def upgrade() -> None:
    # 1. 启用pgcrypto扩展
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")

    # 2. 添加加密列（临时）
    op.add_column("entities", sa.Column("concerns_encrypted", sa.LargeBinary, nullable=True))
    op.add_column("entities", sa.Column("capabilities_encrypted", sa.LargeBinary, nullable=True))

    # 3. 迁移数据（使用应用层加密，避免SQL中暴露密钥）
    # 注意：实际迁移应通过应用脚本完成，此处仅示意

    # 4. 验证数据完整性后，删除明文列（下个主版本）


def downgrade() -> None:
    op.drop_column("entities", "capabilities_encrypted")
    op.drop_column("entities", "concerns_encrypted")
    # pgcrypto扩展保留（其他功能可能依赖）
```

**加密策略**：

| 字段 | 加密方式 | 密钥来源 |
|------|---------|---------|
| concerns | AES-256-GCM | 环境变量 `ENCRYPTION_KEY` |
| capabilities | AES-256-GCM | 环境变量 `ENCRYPTION_KEY` |

> **安全注意**：`ENCRYPTION_KEY` 不得硬编码或提交到代码仓库，通过环境变量或KMS注入。

### 12.3 Adapter同步任务（专业版） [0.3.0新增]

DataSourceAdapter需要定时同步外部数据源，以下为专业版的同步任务配置。

| 数据源 | 同步频率 | 实现方式 | 速率限制 |
|--------|---------|---------|---------|
| Email | 每15分钟 | IMAP IDLE / 轮询 | 10封/次 |
| Calendar | 每30分钟 | CalDAV / Exchange API | 50事件/次 |

**后台Worker配置**：

```python
# promiselink/jobs/adapter_sync.py
"""Adapter同步后台任务"""
import asyncio
from datetime import datetime, timezone
from promiselink.adapters import EmailAdapter, CalendarAdapter
from promiselink.core.pipeline import process_event


async def sync_email():
    adapter = EmailAdapter()
    if not await adapter.authenticate():
        print(f"[{datetime.now()}] Email auth failed, skipping sync")
        return

    events = await adapter.fetch_new_events()
    for event in events:
        await process_event(event)
    print(f"[{datetime.now()}] Email sync: {len(events)} new events")


async def sync_calendar():
    adapter = CalendarAdapter()
    if not await adapter.authenticate():
        print(f"[datetime.now()}] Calendar auth failed, skipping sync")
        return

    events = await adapter.fetch_new_events()
    for event in events:
        await process_event(event)
    print(f"[{datetime.now()}] Calendar sync: {len(events)} new events")
```

**APScheduler集成（专业版推荐）**：

```python
# promiselink/jobs/scheduler.py
from apscheduler.schedulers.asyncio import AsyncIOScheduler

scheduler = AsyncIOScheduler()

# 每15分钟同步邮件
scheduler.add_job(sync_email, "interval", minutes=15, id="email_sync")

# 每30分钟同步日历
scheduler.add_job(sync_calendar, "interval", minutes=30, id="calendar_sync")
```

**速率限制**：每个Adapter同步任务内置速率限制，防止短时间内大量数据涌入导致Pipeline过载。

### 12.4 监控指标 [0.3.0新增]

Insight Engine和DataSourceAdapter新增以下Prometheus监控指标：

| 指标名 | 类型 | Labels | 说明 | 告警阈值 |
|--------|------|--------|------|---------|
| `promiselink_priority_score_calculations_total` | counter | status (success/error) | 优先级分数计算次数 | error率 > 5% |
| `promiselink_implicit_feedback_adjustments_total` | counter | feedback_type (completed_order/less_remind/mark_important) | 隐式反馈调整次数 | 无阈值，观察趋势 |
| `promiselink_adapter_sync_duration_seconds` | histogram | adapter (email/calendar/wechat) | Adapter同步耗时 | P95 > 30s |
| `promiselink_adapter_sync_errors_total` | counter | adapter, error_type (auth/network/parse/rate_limit) | Adapter同步错误计数 | 任意 > 5/min |

**Prometheus查询示例**：

```promql
# 优先级分数计算成功率
sum(rate(promiselink_priority_score_calculations_total{status="success"}[5m]))
/
sum(rate(promiselink_priority_score_calculations_total[5m]))

# Adapter同步P95延迟
histogram_quantile(0.95, sum(rate(promiselink_adapter_sync_duration_seconds_bucket[5m])) by (le, adapter))

# Adapter错误速率（按类型分组）
sum(rate(promiselink_adapter_sync_errors_total[5m])) by (adapter, error_type)

# 隐式反馈调整趋势
sum(rate(promiselink_implicit_feedback_adjustments_total[1h])) by (feedback_type)
```

**Grafana面板建议**：

| 面板 | 图表类型 | 查询 | 说明 |
|------|----------|------|------|
| 优先级计算成功率 | Gauge | success/total比率 | 目标>95% |
| Adapter同步延迟 | Time Series | P95 by adapter | 各数据源同步性能 |
| Adapter错误趋势 | Stacked Area | errors by adapter+type | 错误分类趋势 |
| 隐式反馈分布 | Pie Chart | adjustments by type | 反馈类型占比 |

### 12.5 DependencyAnalyzer 部署 [0.3.1新增]

F-55 依赖性全图谱路径分析。DependencyAnalyzer为纯Python算法模块，无额外部署依赖。

**部署依赖**：

| 依赖项 | 说明 |
|--------|------|
| Python标准库 | `collections.deque`（BFS遍历）、`dataclasses` |
| SQL查询 | 查询`todos`和`associations`表，复用现有数据库连接 |
| 外部服务 | 无（不依赖Redis/外部API/LLM调用） |

**关键特性**：
- **纯Python算法**：依赖图构建和dependency_score计算均在应用进程内完成
- **SQL查询**：通过现有SQLAlchemy会话查询Todo和Entity关联数据
- **无额外容器**：不需要新增Docker服务或Sidecar
- **无额外cron**：在Pipeline Step 8.5内同步执行，不需要独立定时任务

**性能预估**（PoC单用户场景）：

| 指标 | 预估值 | 说明 |
|------|--------|------|
| 依赖图构建耗时 | < 500ms | N=200 Todo, E=100 Entity关联 |
| 内存增量 | < 10MB | 依赖图内存占用 |
| 数据库查询 | 2~3次 | 查询活跃Todo + Entity关联 |

### 12.6 ContextMatcher 部署 [0.3.1新增]

F-56 场景匹配Event表驱动。ContextMatcher需要Event表索引优化以保障查询性能。

**部署依赖**：

| 依赖项 | 说明 |
|--------|------|
| Python标准库 | `datetime`（时间计算）、`dataclasses` |
| SQL查询 | 查询`events`表（meeting类型日程），复用现有数据库连接 |
| Event表索引 | **需要新增复合索引**（见下方） |
| 外部服务 | 无（不依赖Redis/外部API/LLM调用） |

**Event表索引优化**：

ContextMatcher高频查询Event表获取近期日程，需要创建复合索引：

```sql
-- PoC阶段（SQLite）
CREATE INDEX IF NOT EXISTS idx_events_context
ON events(user_id, event_type, created_at);

-- 专业版阶段（PostgreSQL）
CREATE INDEX IF NOT EXISTS idx_events_context
ON events(user_id, event_type, created_at);
```

**Alembic迁移脚本**：

```python
# alembic/versions/007_events_context_index.py
"""Add context matching index on events table

Revision ID: 007
Revises: 006
Create Date: 2026-06-06
"""
from alembic import op


def upgrade() -> None:
    op.create_index(
        "idx_events_context",
        "events",
        ["user_id", "event_type", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("idx_events_context", table_name="events")
```

**索引效果预估**：

| 数据规模 | 无索引 | 有索引 | 说明 |
|---------|--------|--------|------|
| 1000条Event | ~50ms | <5ms | PoC典型规模 |
| 10000条Event | ~500ms | <10ms | 专业版规模 |

**关键特性**：
- **纯Python算法**：场景匹配计算在应用进程内完成
- **无额外容器**：不需要新增Docker服务
- **无额外cron**：在Pipeline Step 8.5内与DependencyAnalyzer并行执行

### 12.7 PriorityScorerV2 定时评分任务 [0.3.1新增]

PriorityScorerV2整合四维评分（紧急性/重要性/依赖性/场景匹配），定时任务配置与PoC现有方案相同。

**定时任务配置**：

| 配置项 | 值 | 说明 |
|--------|-----|------|
| 执行频率 | 每小时整点 | 与PoC PriorityScorer相同 |
| 执行方式 | cron脚本 | 复用现有 `recalculate_scores.py`，升级为PriorityScorerV2 |
| 无额外cron | ✅ | 不需要新增独立定时任务 |

**recalculate_scores脚本升级**：

```python
# promiselink/jobs/recalculate_scores.py
"""
定时任务：重新计算所有活跃Todo的dynamic_score
公式（PriorityScorerV2）：
  Score = 0.25×urgency + 0.35×importance + 0.20×dependency + 0.20×context
降级：当DependencyAnalyzer/ContextMatcher不可用时，回退到PoC公式
  Score = 0.4×urgency + 0.6×importance
"""
import asyncio
from datetime import datetime, timezone
from promiselink.core.database import get_session
from promiselink.models import Todo
from promiselink.insight.priority_scorer_v2 import PriorityScorerV2
from promiselink.insight.dependency_analyzer import DependencyAnalyzer
from promiselink.insight.context_matcher import ContextMatcher
from promiselink.core.association_engine import AssociationDiscoveryEngine
from sqlalchemy import select


async def recalculate_all_scores():
    # 初始化依赖组件
    association_engine = AssociationDiscoveryEngine()
    dependency_analyzer = DependencyAnalyzer(association_engine)
    context_matcher = ContextMatcher()

    scorer = PriorityScorerV2(
        dependency_analyzer=dependency_analyzer,
        context_matcher=context_matcher,
    )

    async with get_session() as session:
        # 查询所有未完成Todo
        result = await session.execute(
            select(Todo).where(Todo.status.in_(["pending", "in_progress"]))
        )
        todos = result.scalars().all()

        for todo in todos:
            todo.dynamic_score = await scorer.calculate(todo)
            todo.score_calculated_at = datetime.now(timezone.utc)

        await session.commit()
        print(f"[{datetime.now()}] Recalculated scores for {len(todos)} todos (V2)")


if __name__ == "__main__":
    asyncio.run(recalculate_all_scores())
```

**降级行为**：当DependencyAnalyzer或ContextMatcher初始化失败时，PriorityScorerV2自动回退到PoC公式（0.4×urgency + 0.6×importance），确保评分不中断。

### 12.8 EmbeddingProvider部署 [0.4.0新增]

#### 12.8.1 sqlite-vec安装

```bash
# 安装sqlite-vec（可选，加速向量搜索）
pip install sqlite-vec

# 验证安装
python -c "import sqlite_vec; print('sqlite-vec available')"

# 如果安装失败（编译环境问题），系统自动降级为Python余弦相似度
# 不影响功能，仅性能略降
```

**安装验证清单**:

| 检查项 | 命令 | 期望结果 |
|--------|------|---------|
| sqlite-vec安装 | `pip show sqlite-vec` | 版本号显示 |
| Python导入 | `python -c "import sqlite_vec"` | 无报错 |
| 降级测试 | 卸载sqlite-vec后启动服务 | 日志显示"降级为Python余弦相似度" |

#### 12.8.2 API Key配置

```bash
# .env 文件追加（复用LLM_API_KEY，无需新增独立密钥）
LLM_API_KEY=sk-your-moka-ai-key-here

# EmbeddingProvider自动复用LLM_API_KEY
# 调用 https://api.moka-ai.com/v1/embeddings
```

**配置验证**:

```bash
# 验证API Key可用
curl -X POST https://api.moka-ai.com/v1/embeddings \
  -H "Authorization: Bearer $LLM_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"model": "text-embedding-3-small", "input": ["测试"]}'
```

#### 12.8.3 缓存策略

| 参数 | 个人版值 | 定制版值 | 说明 |
|------|---------|---------|------|
| 缓存位置 | 内存dict | Redis | 个人版重启清空，定制版持久化 |
| 缓存键 | SHA256(text) | SHA256(text) | 确保相同文本命中缓存 |
| 缓存TTL | 无（重启清空） | 7天 | 定制版自动过期 |
| 缓存大小 | 无限制 | 100MB上限 | 定制版内存保护 |

### 12.9 SemanticSearchEngine部署 [0.4.0新增]

#### 12.9.1 索引构建

```bash
# Pipeline自动触发：Entity创建/更新时自动生成embedding
# 无需手动触发

# 手动重建索引（首次部署或数据修复时）
curl -X POST http://localhost:8000/api/v1/search/reindex \
  -H "Authorization: Bearer $JWT_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"scope": "full", "target_types": ["entity", "event"]}'
```

**索引构建性能预估**:

| 数据量 | 嵌入时间 | 存储空间 | 说明 |
|--------|---------|---------|------|
| 100条 | ~10s | ~300KB | PoC典型规模 |
| 500条 | ~50s | ~1.5MB | 专业版初期 |
| 2000条 | ~3min | ~6MB | 专业版中期 |

#### 12.9.2 降级模式

当sqlite-vec不可用时，SemanticSearchEngine自动降级为Python余弦相似度计算：

```python
# 自动降级日志示例
# INFO: sqlite-vec不可用，降级为Python余弦相似度
# INFO: 搜索方法: python_cosine, 延迟: 50ms/1000条
```

**降级性能对比**:

| 指标 | sqlite-vec | Python余弦 | 差异 |
|------|-----------|-----------|------|
| 1000条搜索延迟 | ~5ms | ~50ms | 10x |
| 内存占用 | 低 | 中（numpy数组） | 略高 |
| 精度 | float32 | float64 | Python更高 |
| 安装复杂度 | 需编译 | 零依赖 | Python更简单 |

#### 12.9.3 定制版迁移（pgvector）

```bash
# 定制版: PostgreSQL + pgvector
# 1. 安装pgvector扩展
psql -c "CREATE EXTENSION IF NOT EXISTS vector;"

# 2. 数据迁移脚本
python scripts/migrate_embeddings_to_pg.py

# 3. 构建IVFFlat索引
psql -c "CREATE INDEX idx_vec_cosine ON vector_embeddings
         USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);"
```

**迁移检查清单**:

| 步骤 | 命令 | 验证 |
|------|------|------|
| pgvector安装 | `SELECT extversion FROM pg_extension WHERE extname='vector'` | 版本号 |
| 数据迁移 | `SELECT COUNT(*) FROM vector_embeddings` | 条目数一致 |
| 索引构建 | `EXPLAIN ANALYZE SELECT ... ORDER BY embedding <=> ...` | 使用索引扫描 |
| 功能验证 | `POST /api/v1/search/semantic` | search_method="pgvector" |

### 12.10 EmailAdapter IMAP配置 [0.4.1新增]

> **对应功能**: F-36 EmailAdapter邮件同步（PRD §5.17.2）
> **依赖**: Python标准库 imaplib + email，无额外系统依赖

**IMAP连接配置**:

| 参数 | 环境变量 | 默认值 | 说明 |
|------|---------|--------|------|
| IMAP主机 | `EMAIL_IMAP_HOST` | — | 如 imap.gmail.com |
| IMAP端口 | `EMAIL_IMAP_PORT` | 993 | SSL默认993，非SSL为143 |
| 邮箱地址 | `EMAIL_ADDRESS` | — | 用户邮箱地址 |
| 应用密码 | `EMAIL_APP_PASSWORD` | — | 应用专用密码（非登录密码） |
| 使用SSL | `EMAIL_USE_SSL` | true | 专业版强制SSL |
| 收件箱 | `EMAIL_FOLDER` | INBOX | 默认收件箱 |

**常见邮箱IMAP配置**:

| 邮箱 | IMAP主机 | 端口 | 认证方式 |
|------|---------|------|---------|
| Gmail | imap.gmail.com | 993 | 应用密码（需开启2FA） |
| Outlook/Hotmail | outlook.office365.com | 993 | 应用密码 |
| QQ邮箱 | imap.qq.com | 993 | 授权码 |
| 163邮箱 | imap.163.com | 993 | 授权码 |

**Docker Compose配置**:

```yaml
# docker-compose.poc.yml 追加
services:
  promiselink:
    environment:
      - EMAIL_IMAP_HOST=${EMAIL_IMAP_HOST:-}
      - EMAIL_IMAP_PORT=${EMAIL_IMAP_PORT:-993}
      - EMAIL_ADDRESS=${EMAIL_ADDRESS:-}
      - EMAIL_APP_PASSWORD=${EMAIL_APP_PASSWORD:-}
      - EMAIL_USE_SSL=${EMAIL_USE_SSL:-true}
      - EMAIL_FOLDER=${EMAIL_FOLDER:-INBOX}
```

**同步频率**: 专业版每15分钟同步一次（复用§12.3 APScheduler配置）。

**安全注意事项**:
- 应用密码存储在 `.env` 文件中，不提交Git
- 专业版使用应用密码，OAuth2推迟到定制版
- IMAP连接强制SSL/TLS

**验证命令**:

```bash
# 验证IMAP连接
curl -s http://localhost:8000/api/v1/email/sync \
  -X POST \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"imap_host":"imap.gmail.com","email":"user@gmail.com","password":"app-password"}'
```

### 12.11 CSV导入文件大小限制配置 [0.4.1新增]

> **对应功能**: F-08 CSV导入（PRD §5.17.1）
> **依赖**: Python标准库 csv，无额外系统依赖

**文件大小限制**:

| 参数 | 环境变量 | 默认值 | 说明 |
|------|---------|--------|------|
| 最大文件大小 | `CSV_MAX_FILE_SIZE_MB` | 10 | 单次导入CSV文件最大MB |
| 最大行数 | `CSV_MAX_ROWS` | 5000 | 单次导入最大行数 |

**CSV格式要求**:

| 要求 | 说明 |
|------|------|
| 必需列 | `name`（姓名） |
| 可选列 | company, title, phone, email, wechat, concern, capability |
| 编码 | UTF-8优先，自动降级GBK |
| 分隔符 | 逗号（标准CSV） |
| 首行 | 必须为列名头 |

**Nginx上传限制**（专业版）:

```nginx
# nginx.conf 追加
client_max_body_size 10m;  # 与CSV_MAX_FILE_SIZE_MB对齐
```

**FastAPI文件上传配置**:

```python
# 已在 import_csv.py 中实现
# UploadFile 默认无大小限制，由 Nginx 层控制
```

**导入性能预估**:

| 行数 | 预估耗时 | 说明 |
|------|---------|------|
| 100 | < 2s | 含EntityResolution |
| 500 | < 8s | 含EntityResolution |
| 1000 | < 15s | 含EntityResolution |
| 5000 | < 60s | 含EntityResolution，建议异步 |

**验证命令**:

```bash
# 验证CSV导入
curl -s http://localhost:8000/api/v1/import/csv \
  -X POST \
  -H "Authorization: Bearer $TOKEN" \
  -F "file=@contacts.csv"
```

---

## 版本历史

| 版本 | 日期 | 变更内容 | 作者 |
|------|------|----------|------|
| v1.0 | 2026-06-03 | 初始版本，包含8章节完整部署指南 | 架构师 |
| **0.2.0** | **2026-06-04** | **POC阶段重大更新：①D8-1 Dockerfile多阶段构建详细说明(builder→runtime非root) ②D8-2 新增GitHub Actions CI/CD完整章节(trigger/strategy/services/steps/lint/typecheck/test/coverage) ③D8-3 确认docker-compose.poc.yml与实际文件一致(含PG/Redis预定义) ④D8-4 新增6项P0 Prometheus监控指标(input_scope延迟/Todo分布/查询延迟/阶段变更频率/脱敏覆盖率/400率) ⑤D8-5 新增Alembic数据库迁移章节(初始化+autogenerate+铁律+SQLite→PG升级路径) ⑥D8-6 新增自建小程序Taro备选方案(触发条件+构建流程+CI上传+API对接) ⑦D8-7 版本号改为0.2.0+参考更新为技术设计v2.5 §9** | **DevSquad** |
| **0.2.0+F-50** | **2026-06-05** | **F-50语音助手部署内容：①§2.1 新增edge-tts Python依赖+ffmpeg/sox系统依赖 ②§2.3 Dockerfile Runtime阶段追加edge-tts安装+TTS缓存目录创建 ③§2.4 docker-compose新增TTS缓存volume mount+3项Voice环境变量(TTS_VOICE_NAME/TTS_RATE/VOICE_ENABLED) ④§5.1.1 新增4项Voice专用Prometheus指标(延迟/置信度/ASR错误/TTS缓存命中率)+查询示例+Grafana面板建议 ⑤§8.5 新增Voice Service运维手册(排查/调优参数/安全检查清单) ⑥§9.1 环境变量表追加6项Voice变量** | **DevSquad** |
| **0.3.0** | **2026-06-06** | **DevSquad Review更新 — Insight Engine部署：①§12.1 优先级评分定时任务(PoC: cron每小时执行recalculate_scores脚本 + Phase1: Celery Beat/APScheduler方案对比+推荐APScheduler) ②§12.2 pgcrypto扩展Phase1(CREATE EXTENSION安装+验证+Alembic迁移脚本006+AES-256-GCM加密策略+ENCRYPTION_KEY安全注入) ③§12.3 Adapter同步任务Phase1(Email每15分钟/Calendar每30分钟+后台Worker配置+APScheduler集成+速率限制) ④§12.4 监控指标4项(promiselink_priority_score_calculations_total/promiselink_implicit_feedback_adjustments_total/promiselink_adapter_sync_duration_seconds/promiselink_adapter_sync_errors_total+Prometheus查询示例+Grafana面板建议)** |
| **0.3.1** | **2026-06-06** | **F-55/F-56 依赖性与场景匹配部署：①§12.5 DependencyAnalyzer部署[0.3.1新增](纯Python算法+SQL查询+无额外容器/无额外cron/无外部依赖+性能预估<500ms) ②§12.6 ContextMatcher部署[0.3.1新增](Event表索引优化CREATE INDEX idx_events_context ON events(user_id,event_type,created_at)+Alembic迁移脚本007+索引效果预估+纯Python算法无额外容器) ③§12.7 PriorityScorerV2定时评分任务[0.3.1新增](复用现有cron每小时整点+recalculate_scores脚本升级为V2四维评分+降级策略回退PoC公式)** | **DevSquad** |
| **0.4.0** | **2026-06-06** | **F-57/F-58 语义搜索与关联发现增强部署：①§12.8 EmbeddingProvider部署[0.4.0新增] — 12.8.1 sqlite-vec安装(pip install sqlite-vec+安装验证清单+自动降级) 12.8.2 API Key配置(复用LLM_API_KEY+curl验证命令) 12.8.3 缓存策略(PoC内存dict重启清空/Phase1 Redis TTL=7天) ②§12.9 SemanticSearchEngine部署[0.4.0新增] — 12.9.1 索引构建(Pipeline自动触发+手动reindex API+性能预估100条~10s) 12.9.2 降级模式(sqlite-vec不可用时Python余弦相似度+性能对比5ms vs 50ms) 12.9.3 Phase2迁移(pgvector+IVFFlat索引+迁移检查清单)** | **DevSquad** |
| **0.4.1** | **2026-06-07** | **F-08/F-36 EmailAdapter/CSV导入部署：①§12.10 EmailAdapter IMAP配置[0.4.1新增] — IMAP连接参数6项环境变量+常见邮箱配置表(Gmail/Outlook/QQ/163)+Docker Compose配置+SSL强制+Phase1应用密码/Phase2 OAuth2+同步频率15分钟+验证命令 ②§12.11 CSV导入文件大小限制配置[0.4.1新增] — 文件大小10MB/行数5000限制+CSV格式要求5项+Nginx上传限制对齐+导入性能预估4档+验证命令** |
| **0.4.8** | **2026-06-08** | **托管PoC部署模式：①§1.1 三阶段部署策略表新增"托管PoC"行(云端轻量服务器+SQLite+参考云厂商报价+小程序接入) ②§1.2 环境要求表新增"托管PoC"列 ③§2.9 托管PoC部署模式[0.4.8新增] — 2.9.1 概述(适用场景+与本地PoC对比表) 2.9.2 架构图(云端服务器+Docker Compose+promiselink-api+Nginx+SQLite+微信小程序+LLM API) 2.9.3 前置条件(云服务器2C4G/域名/SSL证书/LLM API Key/SSH+域名备案说明) 2.9.4 部署步骤7步(准备服务器→域名HTTPS→安装Docker→克隆配置→启动服务→健康检查→小程序白名单) 2.9.5 运维管理(备份策略+自动备份脚本+监控+更新升级) 2.9.6 迁移到Phase1(SQLite导出→PG导入→切换compose文件) 2.9.7 成本估算(参考云厂商报价，不含LLM，约为Phase1的1/4)** | **DevSquad** |
| **0.5.0** | **2026-06-11** | **产品分级重构+网关中继架构：①§1.1 部署策略表重构(PoC→PoC概念验证/托管PoC→基础版本地免费/Phase1→专业版网关中继/移除Phase2/定制版保留) ②§1.2 环境要求表更新为4列(PoC/基础版/专业版/定制版) ③§2.10 基础版vs专业版Docker配置[0.5.0新增] — 2.10.1 架构差异(基础版:仅FastAPI+SQLite+本地Embedding/专业版:+relay_client+网关代理AI) 2.10.2 Docker Compose差异表 2.10.3 基础版安装命令(docker run+Taro H5编译) 2.10.4 专业版安装命令(docker run+RELAY_GATEWAY_URL+RELAY_TOKEN) 2.10.5 版本切换(同镜像+环境变量控制) ④§4 重构为专业版部署网关中继方案(4.1架构概述+4.2前置条件+4.3 Docker部署+4.4中继网关配置+4.7微信小程序域名白名单+4.8备份与恢复) ⑤移除§4 Nginx/SSL配置(网关已处理)** | **DevSquad** |

---

> **文档状态**: ✅ 0.5.0 产品分级重构完成（基础版/专业版/定制版 + 网关中继架构）
> **下次审查**: 专业版网关上线后 / 定制版开发启动前
> **维护负责人**: DevSquad架构师
> **适用阶段**: PoC → 基础版（本地免费）→ 专业版（网关中继）→ 定制版（销售团队）
