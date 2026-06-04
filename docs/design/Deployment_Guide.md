# EventLink 部署指南

> **版本**: v1.0
> **日期**: 2026-06-03
> **定位**: AI驱动的个人商务关系经营助手
> **参考**: 技术设计 v1.7, 安全设计 v1.0, 数据库设计 v1.1

---

## 1. 部署概述

### 1.1 三阶段部署策略

EventLink采用渐进式部署策略，从零成本PoC验证逐步演进到生产级K8s集群：

| 阶段 | 基础设施 | 数据库 | 缓存 | 成本 | 用户规模 | 目标 |
|------|----------|--------|------|------|----------|------|
| **PoC** | 本地 Docker Desktop | SQLite | 无 | 零云成本 | 单用户 | 概念验证、核心流程跑通 |
| **Phase1** | 云端 Docker Compose | PostgreSQL 15 | Redis 7 | ~200元/月 | 单用户（小程序上线） | 生产可用、微信小程序接入 |
| **Phase2** | K8s 集群 | PG + 读写分离 | Redis Cluster | 按需 | 多用户 | 高可用、弹性扩缩容 |

**关键约束**：
- 不做原生APP，微信小程序是主入口
- LLM推理走云端API（OpenAI/Anthropic/Moka AI），不部署本地模型
- PoC阶段零云成本，所有服务运行在本地Docker内

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
  "version": "0.1.0",
  "stage": "poc"
}
```

### 2.3 docker-compose.poc.yml 使用说明

PoC阶段仅启动单个API服务容器，无外部依赖：

| 配置项 | 值 | 说明 |
|--------|-----|------|
| 镜像 | `eventlink:poc` | 本地构建 |
| 端口 | `8000:8000` | FastAPI / Uvicorn |
| 数据卷 | `./data:/data` | SQLite持久化 |
| 内存限制 | 512M | SQLite+FastAPI足够，LLM走云端 |
| CPU限制 | 1核 | 单用户无需多核 |
| 健康检查 | `/api/v1/health` | 30s间隔，10s超时，3次重试 |
| 重启策略 | `unless-stopped` | 异常自动重启 |
| 日志轮转 | 10MB×3文件 | 防止磁盘占满 |

**常用命令**：

```bash
# 启动服务
docker compose -f docker-compose.poc.yml up -d --build

# 查看日志
docker compose -f docker-compose.poc.yml logs -f

# 查看服务状态
docker compose -f docker-compose.poc.yml ps

# 停止服务（数据保留）
docker compose -f docker-compose.poc.yml down

# 停止并清除数据
docker compose -f docker-compose.poc.yml down -v
```

### 2.4 .env.poc 配置说明

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

### 2.5 数据目录说明

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

### 2.6 健康检查验证

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

### 2.7 常见问题排查

| 问题 | 原因 | 解决方案 |
|------|------|----------|
| 端口8000被占用 | 其他服务占用 | 修改 `docker-compose.poc.yml` 端口映射，如 `8001:8000` |
| 容器启动后立即退出 | `.env.poc` 缺少必填项 | 检查 `EVENTLINK_SECRET_KEY` 和 `LLM_API_KEY` 是否已填 |
| 健康检查失败 | 应用启动慢或数据库初始化失败 | 等待40s启动期；查看日志 `docker compose logs` |
| LLM调用超时 | 网络问题或API Key无效 | 检查 `LLM_BASE_URL` 和 `LLM_API_KEY`；增大 `LLM_TIMEOUT` |
| 数据库文件权限错误 | 宿主机目录权限 | `chmod 777 ./data` 或调整Docker用户映射 |
| 容器内存不足 | 数据量过大 | 增大 `deploy.resources.limits.memory` |

---

## 3. Phase1云端部署

### 3.1 前置条件

| 依赖 | 说明 |
|------|------|
| 云服务器 | 2核4G+，推荐阿里云/腾讯云轻量应用服务器 |
| 域名 | 已备案域名，如 `eventlink.com` |
| SSL证书 | Let's Encrypt 免费证书（Certbot自动管理） |
| Docker Engine | 24+ |
| Docker Compose | v2.20+ |

### 3.2 Docker Compose部署

Phase1使用 `docker-compose.yml` 编排多服务：

```yaml
# 服务清单
services:
  eventlink:        # FastAPI 应用
  postgres:         # PostgreSQL 15 数据库
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
docker compose exec eventlink python -m alembic upgrade head
```

### 3.3 PostgreSQL配置

| 配置项 | 推荐值 | 说明 |
|--------|--------|------|
| 版本 | 15-alpine | 轻量镜像 |
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

### 3.4 Redis配置

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

### 3.5 Nginx反向代理

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

### 3.6 SSL/TLS配置

使用Certbot自动管理Let's Encrypt证书：

```bash
# 安装Certbot
sudo apt install -y certbot python3-certbot-nginx

# 首次获取证书
sudo certbot --nginx -d api.eventlink.com -d eventlink.com

# 自动续期（Certbot已内置定时任务）
sudo certbot renew --dry-run
```

### 3.7 微信小程序域名白名单配置

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

### 3.8 备份与恢复

**PostgreSQL备份**：

```bash
# 手动备份
docker compose exec postgres pg_dump -U eventlink eventlink > backup_$(date +%Y%m%d).sql

# 定时备份（crontab）
# 每天凌晨3点备份
0 3 * * * cd /path/to/EventLink && docker compose exec -T postgres pg_dump -U eventlink eventlink | gzip > /backups/eventlink_$(date +\%Y\%m\%d).sql.gz

# 恢复
gunzip -c backup_20260603.sql.gz | docker compose exec -T postgres psql -U eventlink eventlink
```

**Redis备份**：Redis默认开启RDB持久化，数据卷已包含持久化文件。

**备份保留策略**：

| 备份类型 | 保留周期 | 存储位置 |
|----------|----------|----------|
| 每日备份 | 7天 | 本地 /backups/ |
| 每周备份 | 4周 | 本地 /backups/ |
| 手动备份 | 永久 | 按需归档 |

### 3.9 监控配置

Phase1推荐轻量监控方案：

| 监控项 | 工具 | 说明 |
|--------|------|------|
| 容器状态 | Docker内置 | `docker compose ps` |
| 资源使用 | `docker stats` | CPU/内存/网络 |
| 应用日志 | Docker日志 | `docker compose logs -f` |
| 健康检查 | `/api/v1/health` | Nginx定时探测 |
| 磁盘空间 | `df -h` | 定时检查 |

**简单告警脚本**（可选）：

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

## 4. Phase2 K8s部署

### 4.1 概述

Phase2为生产增强阶段，采用Kubernetes编排，实现高可用与弹性扩缩容。本节仅规划方向，不详细展开。

| 项目 | 方案 |
|------|------|
| 集群 | 阿里云ACK / 腾讯云TKE / 自建K8s |
| 镜像仓库 | 阿里云ACR / 腾讯云TCR |
| 数据库 | 云RDS PostgreSQL（主从+只读副本） |
| 缓存 | 云Redis（主从+Cluster模式） |
| 密钥管理 | 云KMS（密钥不落盘） |
| 日志 | ELK / 云日志服务 |
| 监控 | Prometheus + Grafana |

### 4.2 Helm Chart结构

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

### 4.3 自动扩缩容策略

| 指标 | 目标值 | 最小副本 | 最大副本 | 说明 |
|------|--------|----------|----------|------|
| CPU使用率 | 70% | 2 | 5 | 基础扩缩容 |
| 内存使用率 | 80% | 2 | 5 | 内存保护 |
| 自定义指标（QPS） | 100/秒/Pod | 2 | 5 | 请求驱动扩容 |

---

## 5. 数据迁移

### 5.1 PoC→Phase1迁移（SQLite→PostgreSQL）

迁移流程：

```
SQLite导出 → 数据转换 → PostgreSQL导入 → 数据验证
```

**迁移步骤**：

```bash
# 1. 导出SQLite数据为JSON
docker compose -f docker-compose.poc.yml exec eventlink \
    python -c "
from eventlink.database import export_all_data
import json
data = export_all_data()
with open('/data/export.json', 'w') as f:
    json.dump(data, f, ensure_ascii=False, indent=2)
print(f'Exported {sum(len(v) for v in data.values())} records')
"

# 2. 复制导出文件到宿主机
docker cp eventlink-api:/data/export.json ./export.json

# 3. 启动Phase1环境（PostgreSQL）
docker compose up -d postgres redis

# 4. 初始化PG数据库表结构
docker compose exec eventlink python -m alembic upgrade head

# 5. 导入数据到PostgreSQL
docker compose exec eventlink python -m eventlink.migrate \
    --source ./export.json \
    --target postgresql

# 6. 验证数据完整性
docker compose exec eventlink python -m eventlink.migrate --verify
```

### 5.2 迁移脚本使用

迁移脚本支持以下参数：

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `--source` | 导出文件路径 | 必填 |
| `--target` | 目标数据库类型 | `postgresql` |
| `--batch-size` | 批量导入大小 | 100 |
| `--verify` | 仅验证模式 | false |
| `--dry-run` | 试运行，不实际写入 | false |

### 5.3 数据验证方法

迁移完成后，执行以下验证：

```bash
# 1. 记录数对比
echo "SQLite:" && sqlite3 data/eventlink_poc.db "SELECT 'events', COUNT(*) FROM events UNION ALL SELECT 'entities', COUNT(*) FROM entities UNION ALL SELECT 'associations', COUNT(*) FROM associations UNION ALL SELECT 'todos', COUNT(*) FROM todos;"

echo "PostgreSQL:" && docker compose exec postgres psql -U eventlink -c "SELECT 'events' as tbl, COUNT(*) FROM events UNION ALL SELECT 'entities', COUNT(*) FROM entities UNION ALL SELECT 'associations', COUNT(*) FROM associations UNION ALL SELECT 'todos', COUNT(*) FROM todos;"

# 2. 抽样数据对比（随机取10条比对关键字段）
docker compose exec eventlink python -m eventlink.migrate --verify --sample-size 10

# 3. 功能验证
curl -H "Authorization: Bearer $TOKEN" https://api.eventlink.com/api/v1/entities
curl -H "Authorization: Bearer $TOKEN" https://api.eventlink.com/api/v1/events
```

---

## 6. 环境变量参考

### 6.1 完整环境变量表

| 变量名 | 默认值 | 必填 | 阶段 | 说明 |
|--------|--------|------|------|------|
| **应用基础** | | | | |
| `EVENTLINK_STAGE` | `development` | 否 | 全部 | 运行阶段：`poc` / `production` |
| `EVENTLINK_SECRET_KEY` | `change-me-in-production` | **是** | 全部 | JWT签名密钥，生产环境必须修改 |
| `EVENTLINK_DB_PATH` | `/data/eventlink_poc.db` | 否 | PoC | SQLite数据库路径（容器内） |
| `EVENTLINK_LOG_LEVEL` | `INFO` | 否 | 全部 | 日志级别：DEBUG/INFO/WARNING/ERROR |
| `EVENTLINK_CORS_ORIGINS` | `["http://localhost:3000"]` | 否 | 全部 | CORS允许来源，JSON数组格式 |
| **数据库** | | | | |
| `DATABASE_URL` | `sqlite:///./data/eventlink.db` | 否 | 全部 | 数据库连接串，Phase1改为PG |
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

## 7. 故障排查手册

### 7.1 常见错误及解决方案

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

### 7.2 日志查看方法

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
docker compose logs --since="2026-06-03T10:00:00" eventlink

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

### 7.3 性能问题排查

| 症状 | 排查方向 | 工具/命令 |
|------|----------|-----------|
| API响应慢 | 数据库查询 | 检查慢查询日志，确认索引 |
| API响应慢 | LLM调用耗时 | 检查 `LLM_TIMEOUT`，监控LLM响应时间 |
| 内存持续增长 | 内存泄漏 | `docker stats` 监控，重启容器临时缓解 |
| CPU占用高 | 计算密集任务 | 检查实体归一/匹配算法是否触发全量计算 |
| 磁盘IO高 | 数据库写入频繁 | 检查批量操作，优化写入策略 |

---

## 8. 安全检查清单

### 8.1 部署前安全检查

| 检查项 | PoC | Phase1 | 验证方法 |
|--------|-----|--------|----------|
| `EVENTLINK_SECRET_KEY` 不为默认值 | ✅ | ✅ | 检查 `.env` 文件 |
| LLM API Key 不在代码仓库中 | ✅ | ✅ | `git log --all --full-history -- "*.env*"` |
| `.env` 文件被 `.gitignore` 排除 | ✅ | ✅ | `git status` 不显示 `.env` |
| 数据库密码为强随机密码 | - | ✅ | 32位以上随机字符串 |
| Redis密码已设置 | - | ✅ | 检查 `requirepass` 配置 |
| 容器端口不暴露到公网 | - | ✅ | 仅Nginx暴露80/443 |
| Docker镜像为最新版 | ✅ | ✅ | `docker pull` 更新基础镜像 |

### 8.2 生产环境安全加固

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

---

> **文档状态**: ✅ 初始版本完成
> **下次审查**: Phase1开发启动前
> **维护负责人**: 架构师
