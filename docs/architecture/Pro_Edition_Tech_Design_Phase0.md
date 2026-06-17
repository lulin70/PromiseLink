# PromiseLink 专业版 Phase 0 技术设计 — 云端AI网关

> **版本**: v1.1
> **日期**: 2026-06-17
> **生命周期阶段**: P3 技术设计
> **对应PRD**: `docs/spec/PRD_Pro_Edition_v1.md` v1.0
> **对应架构**: `docs/architecture/Pro_Edition_Architecture.md` v1.1 (B-1/B-2/B-3已修复)
> **对应实现计划**: `docs/planning/Pro_Edition_Implementation_Plan.md` v1.0 (Phase 0)
> **Review报告**: `docs/planning/Pro_Edition_Review_Report.md` (78/100有条件通过)
> **基础版版本**: v0.5.4 (成熟度 92/100)

---

## 0. 文档定位与读者

本文档是 PromiseLink 专业版 **Phase 0 云端AI网关** 的技术设计文档，面向：
- **后端开发**：按本文档直接编码实现网关服务
- **DevOps**：按本文档部署网关、配置监控与备份
- **测试工程师**：按本文档设计单元/集成/E2E测试用例
- **架构师**：审查技术决策与接口契约

**前置条件**（P2 Review 阻断项已修复）：
- ✅ B-1: 场景3四跳链路延迟分析（架构§4.7，方案A+B推荐组合，P95目标2.5s/TTFB 1.5s）
- ✅ B-2: 专业版配置项已落地 `src/promiselink/config.py`
- ✅ B-3: AI内容隐私边界明确化（架构§6.4，网关日志仅元数据+LLM Provider数据政策+第三方AI披露条款）

**本文档整合的 Review 建议项**（Phase 0 前完成）：
- I-4 许可证防破解增强（RS256 + 设备指纹 + CRL）
- I-5 DDoS防护（Cloudflare 前置）
- I-6 用户级速率限制 + 异常用量告警
- I-9 网关 CI/CD pipeline + 监控指标
- I-10 网关备份策略（PG dump + Redis AOF）

---

## 1. 概述

### 1.1 Phase 0 目标

实现云端AI网关（Cloud AI Gateway），让专业版用户**不需要自配LLM API Key**即可使用全部AI能力（LLM/ASR/TTS/OCR）。网关作为专业版的核心商业基础设施，承担四大职责：

1. **AI代理** — 持有LLM API Key池，代理用户AI调用至 DeepSeek/Moka AI
2. **许可验证** — 验证 `PRO_LICENSE_KEY`，签发JWT，控制专业版功能访问
3. **用量计费** — 计量Token/次数，月度配额管理，红黄绿灯三态
4. **中继转发** — WebSocket长连接映射，小程序↔本地Docker请求中继

### 1.2 设计原则

| 原则 | 说明 | 落实措施 |
|------|------|----------|
| **高可用** | 单点故障不影响用户基础功能 | Key池熔断+冷却恢复、降级模式、PG备份、Redis AOF |
| **可扩展** | 支持水平扩展应对用户增长 | 网关无状态、Redis共享连接映射、PG读写分离预留 |
| **安全** | 防破解、防刷、防泄露 | RS256签名+设备指纹+CRL、用户级限流、日志仅元数据 |
| **可观测** | 全链路监控告警 | Prometheus指标、结构化日志、健康检查、异常告警 |

### 1.3 范围边界

**Phase 0 范围（本文档覆盖）**：
- 网关服务全部模块（API Key池、许可验证、用量计费、中继、AI代理）
- 网关数据层（PostgreSQL + Redis）
- 网关部署（Docker Compose + Nginx + TLS）
- 网关监控告警与备份

**Phase 0 范围外（后续Phase覆盖）**：
- relay_client 本地侧实现（Phase 1）
- 小程序前端适配（Phase 2）
- 语音/媒体/邮件/微信/CSV 联调（Phase 2-5）
- 隐私数据增强（Phase 6）

### 1.4 关键技术决策

| 决策项 | 选择 | 理由 |
|--------|------|------|
| Web框架 | FastAPI | 与基础版业务服务统一技术栈，原生支持WebSocket/async |
| 数据库 | PostgreSQL 16 | 多用户并发、事务一致性、JSONB支持 |
| 缓存 | Redis 7 | 连接映射、限流计数器、JWT黑名单 |
| JWT签名 | RS256（非对称） | I-4建议项：私钥签发、公钥验证，密钥泄露风险低于HS256 |
| 反向代理 | Nginx + Let's Encrypt | TLS终止、WSS升级、429限流 |
| DDoS防护 | Cloudflare 免费版前置 | I-5建议项：基础DDoS防护+CDN |
| 容器编排 | Docker Compose | 单机部署足够（<100用户），K8s留待规模化 |

---

## 2. 系统架构

### 2.1 网关整体架构图

```
                          ┌─────────────────────────────┐
                          │     Cloudflare (CDN+WAF)     │
                          │   DDoS防护 / TLS前置 / 缓存    │
                          └──────────────┬──────────────┘
                                         │ HTTPS/WSS
                                         ▼
┌─────────────────────────────────────────────────────────────────────┐
│                    云端AI网关 VPS (4核8G)                              │
│  ┌────────────────────────────────────────────────────────────────┐ │
│  │                    Nginx (TLS终止 + WSS升级)                      │ │
│  │   443/HTTPS → 8000/http   443/WSS → 8000/ws                     │ │
│  │   限流: 100 req/s per IP   连接数上限: 50 per IP                  │ │
│  └────────────────────────────┬───────────────────────────────────┘ │
│                               │                                      │
│  ┌────────────────────────────▼───────────────────────────────────┐ │
│  │                  网关核心 (FastAPI :8000)                         │ │
│  │                                                                  │ │
│  │  ┌──────────────────────────────────────────────────────────┐   │ │
│  │  │              中间件层 (Middleware)                         │   │ │
│  │  │  RequestID → TLS校验 → JWT验证 → 许可验证 → 限流 → 审计日志 │   │ │
│  │  └──────────────────────────────────────────────────────────┘   │ │
│  │                                                                  │ │
│  │  ┌──────────┐ ┌───────────┐ ┌──────────┐ ┌──────────┐ ┌──────┐ │ │
│  │  │中继路由器 │ │ AI代理层   │ │许可验证   │ │用量计费   │ │监控  │ │ │
│  │  │RelayRouter│ │AIProxy    │ │License   │ │Billing   │ │Metrics│ │ │
│  │  │          │ │           │ │Service   │ │Service   │ │      │ │ │
│  │  │WSS连接映射│ │LLM代理    │ │JWT签发   │ │Token计数 │ │/metrics│ │ │
│  │  │请求转发  │ │ASR代理    │ │RS256签名 │ │红黄绿灯  │ │/health│ │ │
│  │  │响应回传  │ │TTS代理    │ │设备指纹  │ │月度配额  │ │       │ │ │
│  │  │心跳管理  │ │OCR代理    │ │CRL吊销   │ │账单生成  │ │       │ │ │
│  │  └────┬─────┘ └─────┬─────┘ └────┬─────┘ └────┬─────┘ └──────┘ │ │
│  │       │             │            │            │                 │ │
│  │  ┌────▼─────────────▼────────────▼────────────▼──────────────┐ │ │
│  │  │              API Key 池管理器 (APIKeyPool)                  │ │ │
│  │  │  ├── Key1 (DeepSeek) ── health_score: 0.95 ── active       │ │ │
│  │  │  ├── Key2 (DeepSeek) ── health_score: 0.88 ── active       │ │ │
│  │  │  ├── Key3 (Moka AI)  ── health_score: 0.92 ── active       │ │ │
│  │  │  ├── Key4 (Moka AI)  ── health_score: 0.00 ── circuit_open │ │ │
│  │  │  └── 加权轮询 + 健康检查 + 限流冷却 + 熔断恢复              │ │ │
│  │  └────────────────────────────────────────────────────────────┘ │ │
│  └──────────────────────────────────────────────────────────────────┘ │
│                               │                                      │
│  ┌────────────────────────────▼───────────────────────────────────┐ │
│  │                  数据层 (PostgreSQL + Redis)                     │ │
│  │  ├── PG: users / licenses / usage_records / monthly_usage /     │ │
│  │  │        relay_sessions / jwt_blacklist / audit_logs           │ │
│  │  └── Redis: ws_connections / rate_limit:{user_id} /             │ │
│  │            jwt_blacklist / key_pool_state / health_check        │ │
│  └──────────────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────────┘
        │                                        │
        │ WSS (用户PC主动出站)                     │ HTTPS (小程序直连)
        ▼                                        ▼
   用户本地Docker                              微信小程序
   (relay_client)                            (Pro前端)
        │
        ▼
   外部AI服务: DeepSeek API / Moka AI API / 阿里云语音API
```

### 2.2 组件清单

| 组件 | 模块名 | 职责 | 关键依赖 |
|------|--------|------|----------|
| **API Key池管理器** | `APIKeyPool` | 多Key加权轮询、健康检查、限流冷却、熔断恢复 | Redis（状态缓存） |
| **许可验证服务** | `LicenseService` | LICENSE_KEY激活/验证、JWT签发/刷新/吊销、设备指纹绑定 | PG（licenses）、Redis（JWT黑名单） |
| **用量计费服务** | `BillingService` | Token/次数计量、月度配额、红黄绿灯、账单生成 | PG（usage_records、monthly_usage） |
| **中继服务** | `RelayRouter` | WSS连接管理、请求转发、响应回传、心跳检测 | Redis（ws_connections） |
| **AI代理层** | `AIProxy` | LLM/ASR/TTS/OCR请求代理、流式响应、超时重试、Provider降级 | APIKeyPool、BillingService |
| **监控服务** | `MetricsService` | Prometheus指标暴露、健康检查、异常告警 | — |

### 2.3 组件间交互流程

#### 2.3.1 AI调用代理流程（核心）

```
用户请求 POST /api/v1/pro/relay/llm
    │
    ▼
[中间件链]
    ├── RequestIDMiddleware → 生成 request_id (UUID)
    ├── JWTAuthMiddleware → 验证JWT签名(RS256) + 检查CRL黑名单
    ├── LicenseMiddleware → 验证许可证状态(active) + 设备指纹匹配
    ├── RateLimitMiddleware → 用户级限流(100 req/min) + 异常用量检测
    └── AuditLogMiddleware → 记录元数据(不记body)
    │
    ▼
[AIProxy.handle_llm_request]
    ├── 1. BillingService.check_quota(user_id) → 状态灯判定
    │      └── 红灯 → 返回 402 QUOTA_EXCEEDED
    ├── 2. APIKeyPool.select_key(provider) → 加权轮询选Key
    │      └── 无可用Key → 返回 503 NO_AVAILABLE_KEY
    ├── 3. 转发请求至LLM API (流式SSE)
    │      ├── 429 → APIKeyPool.mark_rate_limited(key) → 冷却60s → 重选Key
    │      ├── 5xx连续3次 → APIKeyPool.mark_circuit_open(key) → 熔断5min
    │      └── 超时30s → APIKeyPool.update_health(key, -) → 重试(最多2次)
    ├── 4. 流式响应转发给客户端 (SSE)
    └── 5. BillingService.record_usage(user_id, tokens) → 异步记录用量
              └── 更新 monthly_usage → 触发状态灯变更告警
```

#### 2.3.2 中继转发流程

```
小程序请求 POST /api/v1/pro/relay/llm (或业务请求)
    │
    ▼
[RelayRouter] 判断请求类型
    ├── AI调用 (path=/api/v1/pro/relay/*) → 走AIProxy直连LLM
    └── 业务请求 (path=/api/v1/business/*) → 走WSS中继到本地Docker
         │
         ▼
    查询 Redis ws_connections:{user_id} → 获取本地Docker的WSS连接
         │
         ▼
    通过WSS发送 {type:"request", request_id, payload}
         │
         ▼
    本地Docker处理 → 返回 {type:"response", request_id, payload}
         │
         ▼
    RelayRouter 匹配 request_id → 返回HTTP响应给小程序
```

---

## 3. 数据模型设计

### 3.1 数据库总览

| 表名 | 存储内容 | 保留策略 | 备份频率 |
|------|----------|----------|----------|
| `users` | 用户账户 | 永久 | 每日pg_dump |
| `licenses` | 许可证 | 永久 | 每日pg_dump |
| `api_key_pool` | API Key池 | 永久 | 每日pg_dump |
| `usage_records` | 用量明细 | 90天 | 每日pg_dump |
| `monthly_usage` | 月度汇总 | 永久 | 每日pg_dump |
| `relay_sessions` | 中继会话 | 7天 | 不备份（可重建） |
| `jwt_blacklist` | JWT吊销列表 | 15天（JWT TTL） | 不备份（Redis） |
| `audit_logs` | 审计日志 | 180天 | 每日pg_dump |

### 3.2 License 表

```sql
CREATE TABLE licenses (
    -- 主键与标识
    license_key       VARCHAR(64)  PRIMARY KEY,           -- PL-PRO-xxxx-xxxx-xxxx 格式
    user_id           VARCHAR(64)  NOT NULL,              -- 关联 users.user_id

    -- 订阅信息
    plan_type         VARCHAR(16)  NOT NULL DEFAULT 'pro', -- pro / trial
    billing_cycle     VARCHAR(16)  NOT NULL DEFAULT 'monthly', -- monthly / yearly
    price_cny         DECIMAL(8,2) NOT NULL DEFAULT 29.00,
    early_bird        BOOLEAN      NOT NULL DEFAULT FALSE,

    -- 配额（冗余存储，避免改价时影响存量用户）
    quota_limit_tokens    BIGINT   NOT NULL DEFAULT 500000,  -- 早鸟50万/月
    quota_limit_asr       INT      NOT NULL DEFAULT 200,     -- ASR次/月
    quota_limit_tts       INT      NOT NULL DEFAULT 200,     -- TTS次/月
    quota_limit_ocr       INT      NOT NULL DEFAULT 100,     -- OCR次/月
    quota_used_tokens     BIGINT   NOT NULL DEFAULT 0,       -- 当月已用Token（冗余，加速查询）
    quota_used_asr        INT      NOT NULL DEFAULT 0,
    quota_used_tts        INT      NOT NULL DEFAULT 0,
    quota_used_ocr        INT      NOT NULL DEFAULT 0,
    quota_reset_at        TIMESTAMP NOT NULL DEFAULT NOW(),  -- 下次重置时间（月初）

    -- 状态与时间
    status            VARCHAR(16)  NOT NULL DEFAULT 'active', -- active / expired / cancelled / suspended
    started_at        TIMESTAMP    NOT NULL DEFAULT NOW(),
    expires_at        TIMESTAMP    NOT NULL,                 -- 订阅到期时间
    cancelled_at      TIMESTAMP,                              -- 取消时间（软删除）
    auto_renew        BOOLEAN      NOT NULL DEFAULT FALSE,

    -- 设备绑定（I-4 防破解增强）
    device_fingerprint VARCHAR(128),                          -- 设备指纹（SHA256 of 硬件特征）
    device_bound_at   TIMESTAMP,                              -- 设备绑定时间
    max_devices       INT          NOT NULL DEFAULT 1,        -- 最大绑定设备数

    -- 审计
    created_at        TIMESTAMP    NOT NULL DEFAULT NOW(),
    updated_at        TIMESTAMP    NOT NULL DEFAULT NOW(),

    -- 约束
    CONSTRAINT chk_license_key_format CHECK (license_key ~ '^PL-PRO-[A-Z0-9]{4}-[A-Z0-9]{4}-[A-Z0-9]{4}$'),
    CONSTRAINT chk_plan_type CHECK (plan_type IN ('pro', 'trial')),
    CONSTRAINT chk_status CHECK (status IN ('active', 'expired', 'cancelled', 'suspended')),
    CONSTRAINT chk_quota_limit CHECK (quota_limit_tokens > 0)
);

-- 索引
CREATE INDEX idx_licenses_user_id ON licenses(user_id);
CREATE INDEX idx_licenses_status ON licenses(status) WHERE status = 'active';
CREATE INDEX idx_licenses_expires_at ON licenses(expires_at) WHERE status = 'active';
CREATE UNIQUE INDEX idx_licenses_user_device ON licenses(user_id, device_fingerprint) WHERE device_fingerprint IS NOT NULL;
```

### 3.3 ApiKeyPool 表

```sql
CREATE TABLE api_key_pool (
    -- 主键与标识
    key_id            VARCHAR(64)  PRIMARY KEY,               -- UUID
    provider          VARCHAR(32)  NOT NULL,                  -- deepseek / moka_ai / openai
    api_key_encrypted TEXT         NOT NULL,                  -- AES-256-GCM加密后的Key

    -- 轮询与限流
    weight            INT          NOT NULL DEFAULT 100,      -- 轮询权重（1-100）
    rpm_limit         INT          NOT NULL DEFAULT 60,       -- 每分钟请求上限
    tpm_limit         INT          NOT NULL DEFAULT 100000,   -- 每分钟Token上限

    -- 健康状态（高频更新，实际运行时缓存在Redis）
    health_score      DECIMAL(3,2) NOT NULL DEFAULT 1.00,     -- 健康分 0.00-1.00
    status            VARCHAR(16)  NOT NULL DEFAULT 'active', -- active / rate_limited / circuit_open / disabled
    consecutive_failures INT       NOT NULL DEFAULT 0,        -- 连续失败次数
    last_used_at      TIMESTAMP,                              -- 最后使用时间
    last_error        TEXT,                                   -- 最近错误信息
    cooldown_until    TIMESTAMP,                              -- 冷却截止时间（429触发）
    circuit_opened_at TIMESTAMP,                              -- 熔断开始时间

    -- 配置
    models_supported  JSONB        NOT NULL DEFAULT '[]',     -- 支持的模型列表 ["deepseek-chat","deepseek-coder"]
    base_url          VARCHAR(256) NOT NULL,                  -- API基础URL

    -- 审计
    created_at        TIMESTAMP    NOT NULL DEFAULT NOW(),
    updated_at        TIMESTAMP    NOT NULL DEFAULT NOW(),

    -- 约束
    CONSTRAINT chk_provider CHECK (provider IN ('deepseek', 'moka_ai', 'openai', 'anthropic')),
    CONSTRAINT chk_status CHECK (status IN ('active', 'rate_limited', 'circuit_open', 'disabled')),
    CONSTRAINT chk_health_score CHECK (health_score >= 0.00 AND health_score <= 1.00),
    CONSTRAINT chk_weight CHECK (weight >= 1 AND weight <= 100)
);

-- 索引
CREATE INDEX idx_apikey_provider_status ON api_key_pool(provider, status) WHERE status = 'active';
CREATE INDEX idx_apikey_cooldown ON api_key_pool(cooldown_until) WHERE status = 'rate_limited';
```

### 3.4 UsageRecord 表

```sql
CREATE TABLE usage_records (
    -- 主键
    id                BIGSERIAL    PRIMARY KEY,
    request_id        VARCHAR(64)  NOT NULL,                  -- 关联请求ID（UUID）

    -- 用户与许可
    user_id           VARCHAR(64)  NOT NULL,
    license_key       VARCHAR(64)  NOT NULL,

    -- AI调用信息
    request_type      VARCHAR(16)  NOT NULL,                  -- llm / asr / tts / ocr
    provider          VARCHAR(32)  NOT NULL,                  -- deepseek / moka_ai
    model             VARCHAR(64)  NOT NULL,                  -- deepseek-chat / whisper-1 等
    key_id            VARCHAR(64),                            -- 使用的API Key ID

    -- 计量数据
    input_tokens      INT          NOT NULL DEFAULT 0,        -- 输入Token
    output_tokens     INT          NOT NULL DEFAULT 0,        -- 输出Token
    total_tokens      INT          NOT NULL DEFAULT 0,        -- 总Token
    duration_ms       INT,                                    -- 调用耗时（毫秒）
    cost_cny          DECIMAL(10,6) NOT NULL DEFAULT 0,       -- 成本（人民币）

    -- 状态
    status_code       INT          NOT NULL,                  -- HTTP状态码
    success           BOOLEAN      NOT NULL DEFAULT TRUE,

    -- 时间
    created_at        TIMESTAMP    NOT NULL DEFAULT NOW(),

    -- 约束
    CONSTRAINT chk_request_type CHECK (request_type IN ('llm', 'asr', 'tts', 'ocr')),
    CONSTRAINT chk_tokens CHECK (total_tokens = input_tokens + output_tokens)
);

-- 索引（高频查询优化）
CREATE INDEX idx_usage_user_created ON usage_records(user_id, created_at DESC);
CREATE INDEX idx_usage_license_month ON usage_records(license_key, created_at DESC);
CREATE INDEX idx_usage_request_id ON usage_records(request_id);
CREATE INDEX idx_usage_created_at ON usage_records(created_at);  -- 清理任务用

-- 分区策略（按月分区，90天后清理）
-- CREATE TABLE usage_records_2026_06 PARTITION OF usage_records FOR VALUES FROM ('2026-06-01') TO ('2026-07-01');
```

### 3.5 RelaySession 表

```sql
CREATE TABLE relay_sessions (
    -- 主键
    session_id        VARCHAR(64)  PRIMARY KEY,               -- UUID

    -- 用户与连接
    user_id           VARCHAR(64)  NOT NULL,
    license_key       VARCHAR(64)  NOT NULL,
    device_fingerprint VARCHAR(128),                          -- 设备指纹

    -- 连接信息
    client_ip         INET,                                   -- 客户端IP（经Cloudflare后为真实IP）
    user_agent        VARCHAR(256),                           -- User-Agent
    connection_id     VARCHAR(64)  NOT NULL,                  -- WebSocket连接ID（Redis映射键）

    -- 状态与时间
    status            VARCHAR(16)  NOT NULL DEFAULT 'active', -- active / disconnected / expired
    created_at        TIMESTAMP    NOT NULL DEFAULT NOW(),
    last_active_at    TIMESTAMP    NOT NULL DEFAULT NOW(),    -- 最后心跳时间
    expires_at        TIMESTAMP    NOT NULL,                  -- 会话过期时间（created_at + 24h）
    disconnected_at   TIMESTAMP,                              -- 断开时间

    -- 统计
    requests_count    INT          NOT NULL DEFAULT 0,        -- 会话内请求数
    bytes_transferred BIGINT       NOT NULL DEFAULT 0,        -- 传输字节数

    -- 约束
    CONSTRAINT chk_session_status CHECK (status IN ('active', 'disconnected', 'expired'))
);

-- 索引
CREATE INDEX idx_relay_user_active ON relay_sessions(user_id) WHERE status = 'active';
CREATE INDEX idx_relay_expires ON relay_sessions(expires_at) WHERE status = 'active';
CREATE INDEX idx_relay_last_active ON relay_sessions(last_active_at);
```

### 3.6 辅助表

#### 3.6.1 users 表

```sql
CREATE TABLE users (
    user_id           VARCHAR(64)  PRIMARY KEY,               -- u_xxx
    wechat_openid     VARCHAR(128) UNIQUE,                    -- 微信登录绑定
    nickname          VARCHAR(128),
    email             VARCHAR(128),                           -- 联系邮箱（可选）
    status            VARCHAR(16)  NOT NULL DEFAULT 'active', -- active / banned
    created_at        TIMESTAMP    NOT NULL DEFAULT NOW(),
    updated_at        TIMESTAMP    NOT NULL DEFAULT NOW(),
    CONSTRAINT chk_user_status CHECK (status IN ('active', 'banned'))
);
```

#### 3.6.2 monthly_usage 表（汇总表，加速查询）

```sql
CREATE TABLE monthly_usage (
    user_id           VARCHAR(64)  NOT NULL,
    license_key       VARCHAR(64)  NOT NULL,
    year_month        VARCHAR(7)   NOT NULL,                  -- 2026-06
    total_tokens      BIGINT       NOT NULL DEFAULT 0,
    total_cost_cny    DECIMAL(10,4) NOT NULL DEFAULT 0,
    request_count     INT          NOT NULL DEFAULT 0,
    asr_count         INT          NOT NULL DEFAULT 0,
    tts_count         INT          NOT NULL DEFAULT 0,
    ocr_count         INT          NOT NULL DEFAULT 0,
    status            VARCHAR(16)  NOT NULL DEFAULT 'green',  -- green / yellow / red
    last_updated_at   TIMESTAMP    NOT NULL DEFAULT NOW(),
    PRIMARY KEY (user_id, year_month),
    CONSTRAINT chk_traffic_light CHECK (status IN ('green', 'yellow', 'red'))
);

CREATE INDEX idx_monthly_usage_license ON monthly_usage(license_key, year_month);
```

#### 3.6.3 audit_logs 表

```sql
CREATE TABLE audit_logs (
    id                BIGSERIAL    PRIMARY KEY,
    user_id           VARCHAR(64)  NOT NULL,
    request_id        VARCHAR(64),
    action            VARCHAR(32)  NOT NULL,                  -- license_activate / license_revoke / quota_exceeded / key_circuit_open 等
    resource_type     VARCHAR(32),                            -- license / api_key / usage
    resource_id       VARCHAR(64),
    metadata          JSONB        NOT NULL DEFAULT '{}',     -- 元数据（不含业务内容）
    ip_address        INET,
    created_at        TIMESTAMP    NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_audit_user_created ON audit_logs(user_id, created_at DESC);
CREATE INDEX idx_audit_action ON audit_logs(action, created_at DESC);
```

### 3.7 Redis 数据结构

| Key模式 | 类型 | TTL | 用途 |
|---------|------|-----|------|
| `ws_connections:{user_id}` | Hash | 持久（AOF） | WebSocket连接映射：field=connection_id, value=session_id |
| `rate_limit:{user_id}:{minute}` | String(INCR) | 60s | 用户级速率限制计数器 |
| `rate_limit:{user_id}:hourly` | String(INCR) | 3600s | 异常用量检测（每小时Token数） |
| `jwt_blacklist:{jti}` | String | 900s（JWT TTL） | JWT吊销列表（CRL） |
| `key_pool:state:{key_id}` | Hash | 持久 | Key池运行时状态（health_score/status/consecutive_failures） |
| `key_pool:rpm:{key_id}:{minute}` | String(INCR) | 60s | Key级RPM计数器 |
| `key_pool:tpm:{key_id}:{minute}` | String(INCR) | 60s | Key级TPM计数器 |
| `license:cache:{license_key}` | Hash | 300s | 许可证信息缓存（减少PG查询） |
| `quota:cache:{user_id}:{year_month}` | Hash | 60s | 月度用量缓存 |
| `health_check:status` | Hash | 持久 | 网关健康状态（各组件存活） |

---

## 4. API接口设计

### 4.1 通用约定

#### 4.1.1 基础信息

| 项 | 值 |
|----|----|
| Base URL | `https://api.promiselink.com` |
| API版本 | `/api/v1` |
| 协议 | HTTPS (TLS 1.2+) / WSS |
| 字符编码 | UTF-8 |
| 时间格式 | ISO 8601 (UTC) `2026-06-17T08:00:00Z` |
| 请求ID | UUID v4，通过 `X-Request-ID` 头传递 |

#### 4.1.2 认证方式

**双因素认证**（I-4 防破解增强）：
1. **API Key**：通过 `X-API-Key` 头传递，网关侧预共享密钥
2. **JWT**：通过 `Authorization: Bearer <token>` 头传递，RS256签名

```http
GET /api/v1/pro/usage HTTP/1.1
Host: api.promiselink.com
X-API-Key: pl_gateway_client_xxx
Authorization: Bearer eyJhbGciOiJSUzI1NiIs...
X-Request-ID: 550e8400-e29b-41d4-a716-446655440000
X-Device-Fingerprint: sha256:abc123...
Content-Type: application/json
```

#### 4.1.3 通用响应格式

```json
{
  "request_id": "550e8400-e29b-41d4-a716-446655440000",
  "success": true,
  "data": { ... },
  "error": null
}
```

错误响应：

```json
{
  "request_id": "550e8400-e29b-41d4-a716-446655440000",
  "success": false,
  "data": null,
  "error": {
    "code": "QUOTA_EXCEEDED",
    "message": "本月AI额度已用完",
    "details": {
      "quota_limit": 500000,
      "quota_used": 500000,
      "reset_at": "2026-07-01T00:00:00Z"
    }
  }
}
```

### 4.2 接口清单

| # | 方法 | 路径 | 认证 | 用途 |
|---|------|------|------|------|
| 1 | POST | `/api/v1/pro/license/activate` | API Key + JWT | 激活许可（P0-5修复：需用户先注册登录） |
| 2 | POST | `/api/v1/pro/license/verify` | API Key + JWT | 验证许可 |
| 3 | GET | `/api/v1/pro/usage` | API Key + JWT | 查询用量 |
| 4 | POST | `/api/v1/pro/relay/llm` | API Key + JWT | LLM中继请求 |
| 5 | POST | `/api/v1/pro/relay/asr` | API Key + JWT | ASR中继请求 |
| 6 | POST | `/api/v1/pro/relay/tts` | API Key + JWT | TTS中继请求 |
| 7 | POST | `/api/v1/pro/relay/ocr` | API Key + JWT | OCR中继请求 |
| 8 | GET | `/api/v1/pro/health` | 无 | 网关健康检查 |

### 4.3 接口详细设计

#### 4.3.1 POST /api/v1/pro/license/activate — 激活许可

**用途**：用户输入 `PRO_LICENSE_KEY` 后激活专业版，签发JWT和relay_token。

> ⚠️ **P0-5 安全修复**：激活接口要求用户**先注册登录**，携带已认证的 JWT。`user_id` 从 JWT 中提取，**不接受客户端请求体中传入 user_id**，防止攻击者用他人 license_key 抢先绑定。

**认证方式**：API Key + JWT（用户注册登录后获得的 user JWT）

**请求头**：

```http
POST /api/v1/pro/license/activate HTTP/1.1
Host: api.promiselink.com
X-API-Key: pl_gateway_client_xxx
Authorization: Bearer <user_jwt>  # 用户注册登录后获得，user_id 从中提取
X-Request-ID: 550e8400-e29b-41d4-a716-446655440000
X-Device-Fingerprint: sha256:abc123def456...
Content-Type: application/json
```

**请求体**：

```json
{
  "license_key": "PL-PRO-A1B2-C3D4-E5F6",
  "wechat_openid": "o_xxx",
  "device_fingerprint": "sha256:abc123def456..."
}
```

**字段约束**：

| 字段 | 类型 | 必填 | 约束 |
|------|------|------|------|
| license_key | string | 是 | 格式 `^PL-PRO-[A-Z0-9]{4}-[A-Z0-9]{4}-[A-Z0-9]{4}$` |
| wechat_openid | string | 否 | 微信openid，首次激活时绑定 |
| device_fingerprint | string | 是 | 设备指纹 `^sha256:[a-f0-9]{64}$` |

> **注意**：`user_id` 不在请求体中，由网关从 `Authorization: Bearer <user_jwt>` 的 JWT payload 中提取（`jwt.user_id`）。客户端**禁止**在请求体中传入 `user_id` 字段，若传入则忽略并记录审计日志。

**防抢绑机制**（P0-5）：

- `license_key` 与 `user_id` 的绑定关系在**首次激活时**记录到 `licenses.user_id` 字段
- 绑定后**不可更改**：后续激活请求若 `license_key` 已绑定其他 `user_id`，返回 409 `LICENSE_ALREADY_ACTIVATED`
- 攻击者即使获取他人 license_key，因无法伪造受害者的 JWT（RS256 签名保护），无法抢先绑定
- 绑定关系校验逻辑见 §6.1 激活流程步骤 [4. 用户绑定检查]

**响应体**（200 OK）：

```json
{
  "request_id": "550e8400-e29b-41d4-a716-446655440000",
  "success": true,
  "data": {
    "license": {
      "license_key": "PL-PRO-A1B2-C3D4-E5F6",
      "plan_type": "pro",
      "status": "active",
      "expires_at": "2026-07-17T00:00:00Z",
      "quota_limit_tokens": 500000,
      "quota_limit_asr": 200,
      "quota_limit_tts": 200,
      "quota_limit_ocr": 100
    },
    "tokens": {
      "access_token": "eyJhbGciOiJSUzI1NiIs...",
      "refresh_token": "eyJhbGciOiJSUzI1NiIs...",
      "token_type": "Bearer",
      "expires_in": 900
    },
    "relay_config": {
      "relay_gateway_url": "wss://gw.promiselink.ai/relay",
      "heartbeat_interval": 30,
      "reconnect_interval": 1,
      "reconnect_max": 30
    }
  },
  "error": null
}
```

**错误码**：

| HTTP | error.code | 触发条件 |
|------|-----------|----------|
| 400 | INVALID_LICENSE_KEY_FORMAT | license_key格式错误 |
| 400 | INVALID_DEVICE_FINGERPRINT | 设备指纹格式错误 |
| 404 | LICENSE_NOT_FOUND | license_key不存在 |
| 409 | LICENSE_ALREADY_ACTIVATED | 许可证已被其他用户激活 |
| 409 | DEVICE_LIMIT_EXCEEDED | 超过最大绑定设备数 |
| 410 | LICENSE_EXPIRED | 许可证已过期 |
| 410 | LICENSE_CANCELLED | 许可证已取消 |
| 429 | RATE_LIMIT_EXCEEDED | 激活请求过于频繁 |

#### 4.3.2 POST /api/v1/pro/license/verify — 验证许可

**用途**：每次请求验证JWT有效性 + 许可证状态 + 设备指纹匹配。

**请求体**：

```json
{
  "device_fingerprint": "sha256:abc123def456..."
}
```

**响应体**（200 OK）：

```json
{
  "request_id": "550e8400-e29b-41d4-a716-446655440000",
  "success": true,
  "data": {
    "valid": true,
    "license": {
      "license_key": "PL-PRO-A1B2-C3D4-E5F6",
      "plan_type": "pro",
      "status": "active",
      "expires_at": "2026-07-17T00:00:00Z"
    },
    "quota": {
      "tokens": {
        "limit": 500000,
        "used": 125000,
        "remaining": 375000,
        "percentage": 25.0
      },
      "traffic_light": "green"
    },
    "tokens": {
      "access_token": "eyJhbGciOiJSUzI1NiIs...",
      "expires_in": 600
    }
  },
  "error": null
}
```

**说明**：当 `expires_in < 300`（5分钟）时，自动签发新JWT并返回（无感刷新）。

**错误码**：

| HTTP | error.code | 触发条件 |
|------|-----------|----------|
| 401 | JWT_INVALID | JWT签名无效或格式错误 |
| 401 | JWT_EXPIRED | JWT已过期 |
| 401 | JWT_REVOKED | JWT在CRL黑名单中 |
| 403 | LICENSE_INACTIVE | 许可证状态非active |
| 403 | DEVICE_FINGERPRINT_MISMATCH | 设备指纹不匹配 |
| 403 | LICENSE_EXPIRED | 许可证已过期 |

#### 4.3.3 GET /api/v1/pro/usage — 查询用量

**用途**：查询当月用量、配额、状态灯、历史趋势。

**查询参数**：

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| month | string | 否 | 查询月份 `YYYY-MM`，默认当月 |
| detail | boolean | 否 | 是否返回分类型明细，默认false |

**响应体**（200 OK）：

```json
{
  "request_id": "550e8400-e29b-41d4-a716-446655440000",
  "success": true,
  "data": {
    "month": "2026-06",
    "traffic_light": "green",
    "quota": {
      "tokens": {
        "limit": 500000,
        "used": 125000,
        "remaining": 375000,
        "percentage": 25.0
      },
      "asr": { "limit": 200, "used": 45, "remaining": 155, "percentage": 22.5 },
      "tts": { "limit": 200, "used": 38, "remaining": 162, "percentage": 19.0 },
      "ocr": { "limit": 100, "used": 12, "remaining": 88, "percentage": 12.0 }
    },
    "cost_cny": 0.1250,
    "request_count": 95,
    "reset_at": "2026-07-01T00:00:00Z",
    "history": [
      { "month": "2026-05", "tokens_used": 420000, "traffic_light": "yellow" },
      { "month": "2026-04", "tokens_used": 380000, "traffic_light": "green" }
    ]
  },
  "error": null
}
```

**错误码**：

| HTTP | error.code | 触发条件 |
|------|-----------|----------|
| 401 | JWT_INVALID | JWT无效 |
| 403 | LICENSE_INACTIVE | 许可证非active |

#### 4.3.4 POST /api/v1/pro/relay/llm — LLM中继请求

**用途**：代理LLM调用（DeepSeek/Moka AI），支持流式响应（SSE）。

**请求体**：

```json
{
  "provider": "deepseek",
  "model": "deepseek-chat",
  "messages": [
    { "role": "system", "content": "你是关系经营助手..." },
    { "role": "user", "content": "..." }
  ],
  "max_tokens": 2000,
  "temperature": 0.7,
  "stream": true
}
```

**字段约束**：

| 字段 | 类型 | 必填 | 约束 |
|------|------|------|------|
| provider | string | 是 | `deepseek` / `moka_ai` |
| model | string | 是 | 最大64字符 |
| messages | array | 是 | 1-50条消息 |
| max_tokens | int | 否 | 1-8192，默认2000 |
| temperature | float | 否 | 0.0-2.0，默认0.7 |
| stream | boolean | 否 | 默认false |

**响应（非流式，200 OK）**：

```json
{
  "request_id": "550e8400-e29b-41d4-a716-446655440000",
  "success": true,
  "data": {
    "content": "张总的电话是138****1234...",
    "model": "deepseek-chat",
    "usage": {
      "input_tokens": 150,
      "output_tokens": 80,
      "total_tokens": 230
    },
    "billing": {
      "cost_cny": 0.000230,
      "monthly_status": "green",
      "remaining_tokens": 374770
    }
  },
  "error": null
}
```

**响应（流式，200 OK，Content-Type: text/event-stream）**：

```
event: token
data: {"content": "张", "index": 0}

event: token
data: {"content": "总", "index": 1}

event: done
data: {"usage": {"input_tokens": 150, "output_tokens": 80, "total_tokens": 230}, "billing": {"cost_cny": 0.000230, "monthly_status": "green", "remaining_tokens": 374770}}
```

**错误码**：

| HTTP | error.code | 触发条件 |
|------|-----------|----------|
| 400 | INVALID_REQUEST | 请求体格式错误 |
| 401 | JWT_INVALID | JWT无效 |
| 402 | QUOTA_EXCEEDED | 用量红灯，配额已用完 |
| 403 | LICENSE_INACTIVE | 许可证非active |
| 429 | RATE_LIMIT_EXCEEDED | 用户级速率超限（100 req/min） |
| 429 | PROVIDER_RATE_LIMITED | LLM Provider限流（Key池已切换） |
| 503 | NO_AVAILABLE_KEY | 所有Key不可用（限流/熔断/禁用） |
| 504 | UPSTREAM_TIMEOUT | LLM API超时（30s） |

#### 4.3.5 POST /api/v1/pro/relay/asr — ASR中继请求

**用途**：代理语音转文字（Moka AI Whisper）。

**请求体**（multipart/form-data）：

| 字段 | 类型 | 必填 | 约束 |
|------|------|------|------|
| audio | file | 是 | mp3/wav/m4a，≤25MB，5-60秒 |
| model | string | 否 | 默认 `whisper-1` |
| language | string | 否 | 默认 `zh` |

**响应体**（200 OK）：

```json
{
  "request_id": "550e8400-e29b-41d4-a716-446655440000",
  "success": true,
  "data": {
    "text": "今天和张总吃了午饭，聊了新项目合作",
    "language": "zh",
    "duration_seconds": 8.5,
    "billing": {
      "count": 1,
      "monthly_asr_used": 46,
      "monthly_asr_remaining": 154
    }
  },
  "error": null
}
```

**错误码**：

| HTTP | error.code | 触发条件 |
|------|-----------|----------|
| 400 | INVALID_AUDIO_FORMAT | 音频格式不支持 |
| 400 | AUDIO_TOO_LARGE | 音频>25MB |
| 400 | AUDIO_DURATION_INVALID | 音频<5秒或>60秒 |
| 402 | ASR_QUOTA_EXCEEDED | ASR次数用完 |

#### 4.3.6 POST /api/v1/pro/relay/tts — TTS中继请求

**用途**：代理文字转语音（Moka AI TTS）。

**请求体**：

```json
{
  "text": "张总的电话是138****1234",
  "model": "moka-tts",
  "voice": "zh-female-1",
  "speed": 1.0,
  "response_format": "mp3"
}
```

**字段约束**：

| 字段 | 类型 | 必填 | 约束 |
|------|------|------|------|
| text | string | 是 | 1-500字符 |
| model | string | 否 | 默认 `moka-tts` |
| voice | string | 否 | 默认 `zh-female-1` |
| speed | float | 否 | 0.5-2.0，默认1.0 |
| response_format | string | 否 | `mp3`/`wav`，默认mp3 |

**响应**（200 OK，Content-Type: audio/mpeg）：

二进制音频数据。

**响应头**：

```
X-Request-ID: 550e8400-e29b-41d4-a716-446655440000
X-Billing-Count: 1
X-Billing-TTS-Used: 39
X-Billing-TTS-Remaining: 161
Content-Type: audio/mpeg
Content-Length: 28640
```

**错误码**：

| HTTP | error.code | 触发条件 |
|------|-----------|----------|
| 400 | TEXT_TOO_LONG | 文本>500字符 |
| 402 | TTS_QUOTA_EXCEEDED | TTS次数用完 |

#### 4.3.7 POST /api/v1/pro/relay/ocr — OCR中继请求

**用途**：代理图片文字识别（Moka AI Vision），支持结构化提取。

**请求体**（multipart/form-data）：

| 字段 | 类型 | 必填 | 约束 |
|------|------|------|------|
| image | file | 是 | jpg/png，≤10MB |
| task | string | 否 | `business_card`/`general`，默认`general` |
| model | string | 否 | 默认 `moka-vision` |

**响应体**（200 OK，task=business_card）：

```json
{
  "request_id": "550e8400-e29b-41d4-a716-446655440000",
  "success": true,
  "data": {
    "task": "business_card",
    "structured": {
      "name": "张伟",
      "company": "某某科技有限公司",
      "title": "总经理",
      "phone": "138****1234",
      "email": "zhang***@example.com"
    },
    "raw_text": "张伟\n总经理\n某某科技有限公司\n电话: 138xxxx1234\n邮箱: zhangwei@example.com",
    "billing": {
      "count": 1,
      "monthly_ocr_used": 13,
      "monthly_ocr_remaining": 87
    }
  },
  "error": null
}
```

**错误码**：

| HTTP | error.code | 触发条件 |
|------|-----------|----------|
| 400 | INVALID_IMAGE_FORMAT | 图片格式不支持 |
| 400 | IMAGE_TOO_LARGE | 图片>10MB |
| 402 | OCR_QUOTA_EXCEEDED | OCR次数用完 |

#### 4.3.8 GET /api/v1/pro/health — 网关健康检查

**用途**：网关健康检查（无认证），用于监控和负载均衡探活。

**响应体**（200 OK）：

```json
{
  "status": "healthy",
  "version": "1.0.0",
  "timestamp": "2026-06-17T08:00:00Z",
  "components": {
    "database": "healthy",
    "redis": "healthy",
    "api_key_pool": {
      "status": "healthy",
      "active_keys": 3,
      "total_keys": 4,
      "circuit_open_count": 1
    },
    "llm_providers": {
      "deepseek": "reachable",
      "moka_ai": "reachable"
    }
  },
  "metrics": {
    "active_ws_connections": 42,
    "requests_per_minute": 15,
    "avg_response_ms": 850
  }
}
```

**错误码**：

| HTTP | error.code | 触发条件 |
|------|-----------|----------|
| 503 | GATEWAY_UNHEALTHY | 关键组件不可用 |

---

## 5. API Key池管理算法

### 5.1 算法总览

```
请求到达
    │
    ▼
[1. 过滤可用Key]
    ├── status == 'active'
    ├── cooldown_until < NOW() (已过冷却期)
    ├── circuit_opened_at IS NULL OR circuit_opened_at < NOW() - INTERVAL '5 min' (已过熔断期)
    ├── current_rpm < rpm_limit
    └── current_tpm + estimated_tokens < tpm_limit
    │
    ▼
[2. 加权轮询选择]
    weight = key.weight × key.health_score
    按weight加权随机选择一个Key
    │
    ▼
[3. 调用LLM API]
    ├── 成功(2xx) → update_health(key, +0.05) → reset consecutive_failures → return
    ├── 429限流 → handle_rate_limited(key) → 回到[1]重选
    ├── 5xx错误 → handle_5xx(key) → 回到[1]重选
    ├── 超时(30s) → handle_timeout(key) → 回到[1]重选
    └── 网络错误 → handle_network_error(key) → 回到[1]重选
    │
    ▼
[4. 重试限制]
    最多重试3次（不同Key），超过则返回 503 NO_AVAILABLE_KEY
```

### 5.2 加权轮询策略

**权重计算公式**：

```
effective_weight = base_weight × health_score × (1 - current_rpm / rpm_limit)
```

**示例**：

| Key | provider | base_weight | health_score | current_rpm | rpm_limit | effective_weight |
|-----|----------|-------------|--------------|-------------|-----------|------------------|
| Key1 | deepseek | 100 | 0.95 | 20 | 60 | 100×0.95×(1-20/60) = 63.3 |
| Key2 | deepseek | 100 | 0.88 | 45 | 60 | 100×0.88×(1-45/60) = 22.0 |
| Key3 | moka_ai | 80 | 0.92 | 10 | 60 | 80×0.92×(1-10/60) = 61.3 |

**选择概率**：
- Key1: 63.3 / (63.3+22.0+61.3) = 43.2%
- Key2: 22.0 / 146.6 = 15.0%
- Key3: 61.3 / 146.6 = 41.8%

### 5.3 健康检查机制

**健康分更新规则**：

| 事件 | 健康分变化 | 说明 |
|------|------------|------|
| 请求成功(2xx) | +0.05（上限1.00） | 成功请求提升健康分 |
| 429限流 | -0.20 | 限流显著降低健康分 |
| 5xx错误 | -0.30 | 服务端错误严重降低 |
| 超时 | -0.25 | 超时降低健康分 |
| 网络错误 | -0.20 | 网络问题降低 |
| 探活成功 | +0.10（上限1.00） | 熔断恢复探活 |

**定时探活**（每30秒）：

```
对于所有 status != 'active' 的Key:
    发送轻量请求 (GET /models 或 1 token请求)
    ├── 成功 → health_score += 0.10, 若 health_score >= 0.80 → status = 'active'
    └── 失败 → 保持原状态，等待下次探活
```

### 5.4 限流处理（429响应）

```
收到LLM API 429响应:
    │
    ▼
[1. 标记Key限流]
    status = 'rate_limited'
    cooldown_until = NOW() + INTERVAL '60 seconds'
    health_score -= 0.20 (下限0.00)
    │
    ▼
[2. 记录审计日志]
    audit_log(action='key_rate_limited', resource_id=key_id, metadata={provider, model})
    │
    ▼
[3. 触发Key切换]
    选择下一个可用Key重试请求
    │
    ▼
[4. 冷却到期恢复]
    定时任务检查 cooldown_until < NOW():
    ├── 发送探活请求
    │   ├── 成功 → status = 'active', health_score += 0.10
    │   └── 失败 → cooldown_until = NOW() + INTERVAL '60 seconds' (延长冷却)
```

### 5.5 熔断机制

**熔断触发条件**：连续3次5xx错误

```
收到LLM API 5xx响应:
    │
    ▼
[1. 更新失败计数]
    consecutive_failures += 1
    health_score -= 0.30 (下限0.00)
    │
    ▼
[2. 判断是否熔断]
    IF consecutive_failures >= 3:
        status = 'circuit_open'
        circuit_opened_at = NOW()
        audit_log(action='key_circuit_open', resource_id=key_id)
    │
    ▼
[3. 熔断恢复（5分钟后）]
    定时任务检查 circuit_opened_at < NOW() - INTERVAL '5 minutes':
    ├── 发送探活请求
    │   ├── 成功 → status = 'active', consecutive_failures = 0, health_score = 0.50
    │   └── 失败 → circuit_opened_at = NOW() (重置5分钟计时)
```

### 5.6 恢复机制

**恢复流程**（冷却/熔断结束后）：

```
定时任务（每30秒执行）:
    │
    ▼
[查询待恢复Key]
    SELECT * FROM api_key_pool
    WHERE status IN ('rate_limited', 'circuit_open')
      AND (
        (status = 'rate_limited' AND cooldown_until < NOW())
        OR
        (status = 'circuit_open' AND circuit_opened_at < NOW() - INTERVAL '5 min')
      )
    │
    ▼
[逐个探活]
    FOR each key in 待恢复Key:
        发送探活请求 (GET {base_url}/models, 超时5s)
        ├── 成功(2xx):
        │   UPDATE api_key_pool SET
        │     status = 'active',
        │     consecutive_failures = 0,
        │     health_score = LEAST(health_score + 0.10, 1.00),
        │     cooldown_until = NULL,
        │     circuit_opened_at = NULL,
        │     updated_at = NOW()
        │   WHERE key_id = ?
        │
        └── 失败:
            IF status = 'rate_limited':
                UPDATE api_key_pool SET cooldown_until = NOW() + INTERVAL '60 seconds'
            IF status = 'circuit_open':
                UPDATE api_key_pool SET circuit_opened_at = NOW()
```

### 5.7 Key池状态机

```
                          ┌─────────────┐
                          │   active    │ ← 默认状态
                          │  (可用)     │
                          └──┬──┬──┬────┘
                             │  │  │
              429响应 ───────┘  │  └─────── 连续3次5xx
                             │  │
                             ▼  ▼
                  ┌─────────────┐    ┌─────────────┐
                  │rate_limited │    │circuit_open │
                  │  (冷却60s)  │    │  (熔断5min) │
                  └──────┬──────┘    └──────┬──────┘
                         │                  │
            冷却到期+探活成功                │
                         │                  │
                         ▼                  │
                  ┌─────────────┐           │
                  │   active    │ ←─────────┘
                  │  (恢复)     │   熔断到期+探活成功
                  └─────────────┘
                         │
                  管理员手动禁用
                         │
                         ▼
                  ┌─────────────┐
                  │  disabled   │
                  │ (手动禁用)  │
                  └─────────────┘
```

---

## 6. 许可验证流程

### 6.1 激活流程

> ⚠️ **P0-5 安全修复**：激活接口要求用户先注册登录，携带 JWT。`user_id` 从 JWT 中提取，不接受请求体传入。

```
用户注册登录 → 获得 user JWT → 输入 PRO_LICENSE_KEY + 设备指纹
    │
    ▼
[0. JWT 验证与 user_id 提取] (P0-5 新增)
    验证 Authorization: Bearer <user_jwt> 签名(RS256) + 有效期
    ├── JWT无效 → 401 JWT_INVALID
    ├── JWT过期 → 401 JWT_EXPIRED
    └── 提取 user_id = jwt.user_id（不从请求体读取）
    │
    ▼
[1. 格式校验]
    license_key ~ '^PL-PRO-[A-Z0-9]{4}-[A-Z0-9]{4}-[A-Z0-9]{4}$'
    device_fingerprint ~ '^sha256:[a-f0-9]{64}$'
    ├── 失败 → 400 INVALID_LICENSE_KEY_FORMAT / INVALID_DEVICE_FINGERPRINT
    │
    ▼
[2. 查询许可证]
    SELECT * FROM licenses WHERE license_key = ? FOR UPDATE
    ├── 不存在 → 404 LICENSE_NOT_FOUND
    │
    ▼
[3. 状态检查]
    ├── status = 'expired' → 410 LICENSE_EXPIRED
    ├── status = 'cancelled' → 410 LICENSE_CANCELLED
    ├── status = 'suspended' → 403 LICENSE_SUSPENDED
    ├── expires_at < NOW() → UPDATE status='expired' → 410 LICENSE_EXPIRED
    │
    ▼
[4. 用户绑定检查] (P0-5 防抢绑)
    ├── licenses.user_id IS NULL → 首次绑定，继续步骤[5]
    ├── licenses.user_id == jwt.user_id → 同一用户重新激活，继续步骤[5]
    └── licenses.user_id != jwt.user_id → 409 LICENSE_ALREADY_ACTIVATED
        （license_key 已绑定其他用户，不可更改）
    │
    ▼
[5. 设备绑定检查] (I-4 防破解)
    ├── device_fingerprint IS NULL → 首次激活，绑定设备
    ├── device_fingerprint != 请求设备指纹 → 409 DEVICE_FINGERPRINT_MISMATCH
    ├── 已绑定设备数 >= max_devices → 409 DEVICE_LIMIT_EXCEEDED
    │
    ▼
[6. 绑定用户与设备]
    UPDATE licenses SET
      user_id = ?,                      -- 来自 JWT，非请求体
      device_fingerprint = ?,
      device_bound_at = NOW(),
      status = 'active',
      updated_at = NOW()
    WHERE license_key = ?
    │
    ▼
[7. 签发JWT (RS256)]
    JWT Payload:
    {
      "user_id": "u_abc123",
      "license_key": "PL-PRO-A1B2-C3D4-E5F6",
      "plan_type": "pro",
      "device_fingerprint": "sha256:abc123...",
      "jti": "jwt-uuid-xxx",  // 用于CRL吊销
      "iat": 1718037056,
      "exp": 1718037956  // 15分钟TTL
    }
    使用RSA私钥签名 (RS256)
    │
    ▼
[8. 签发refresh_token]
    refresh_token (7天TTL, 用于刷新access_token)
    │
    ▼
[9. 记录审计日志]
    audit_log(action='license_activate', user_id, resource_id=license_key)
    │
    ▼
[10. 返回响应]
    返回 license信息 + tokens + relay_config
```

### 6.2 验证流程

**每次请求的中间件验证**：

```
请求到达 (携带 Authorization: Bearer <jwt>)
    │
    ▼
[1. JWT格式解析]
    解析 header.payload.signature
    ├── 格式错误 → 401 JWT_INVALID
    │
    ▼
[2. JWT签名验证 (RS256)]
    使用RSA公钥验证签名
    ├── 签名无效 → 401 JWT_INVALID
    │
    ▼
[3. JWT过期检查]
    exp < NOW() → 401 JWT_EXPIRED
    │
    ▼
[4. CRL黑名单检查] (I-4 防破解)
    EXISTS Redis jwt_blacklist:{jti}
    ├── 存在 → 401 JWT_REVOKED
    │
    ▼
[5. 许可证状态检查]
    SELECT status, expires_at, device_fingerprint FROM licenses
    WHERE license_key = ? AND user_id = ?
    ├── status != 'active' → 403 LICENSE_INACTIVE
    ├── expires_at < NOW() → UPDATE status='expired' → 403 LICENSE_EXPIRED
    │
    ▼
[6. 设备指纹匹配] (I-4 防破解)
    device_fingerprint != JWT中的device_fingerprint → 403 DEVICE_FINGERPRINT_MISMATCH
    │
    ▼
[7. 配额检查] (仅AI调用路由)
    BillingService.check_quota(user_id):
    ├── traffic_light = 'red' → 402 QUOTA_EXCEEDED
    │
    ▼
[8. 速率限制检查] (I-6 防刷)
    Redis INCR rate_limit:{user_id}:{minute}
    ├── > 100 → 429 RATE_LIMIT_EXCEEDED
    │
    ▼
[9. 异常用量检测] (I-6 防刷)
    Redis GET rate_limit:{user_id}:hourly_tokens
    ├── > 100000 (10万Token/小时) → 标记异常 + 告警
    │
    ▼
[10. 放行]
    注入 request.state.user_id, request.state.license_key
    进入业务处理
```

### 6.3 刷新流程

**自动刷新（无感续期）**：

```
relay_client 定时任务 (每5分钟检查):
    │
    ▼
[1. 检查access_token剩余时间]
    expires_in = JWT.exp - NOW()
    │
    ▼
[2. 判断是否需要刷新]
    IF expires_in < 300 (5分钟):
        触发刷新
    │
    ▼
[3. 调用刷新接口]
    POST /api/v1/pro/license/verify
    Authorization: Bearer <当前access_token>
    Body: { "device_fingerprint": "..." }
    │
    ▼
[4. 网关处理]
    ├── 验证当前JWT有效
    ├── 签发新JWT (新jti, 新exp)
    ├── 旧JWT加入CRL黑名单 (TTL=剩余有效期)
    └── 返回新access_token
    │
    ▼
[5. relay_client更新本地token]
    替换存储的access_token
    下次请求使用新token
```

**refresh_token刷新**（access_token已过期时）：

```
POST /api/v1/pro/license/refresh
Body: { "refresh_token": "..." }

[网关处理]
    ├── 验证refresh_token签名+有效期(7天)
    ├── 检查关联许可证状态
    ├── 签发新access_token + 新refresh_token
    └── 旧refresh_token加入CRL
```

### 6.4 吊销流程

**管理员吊销**（用户退款/违规时）：

> ⚠️ P0-4 安全修复：管理员接口必须通过双因素认证（admin_api_key + admin_jwt），详见 §6.5 管理员认证机制。未认证请求返回 401。

```
管理员调用内部接口（需携带 admin_api_key + admin_jwt，见 §6.5）:
POST /api/v1/admin/license/revoke
Headers:
  X-Admin-API-Key: ${ADMIN_API_KEY}
  Authorization: Bearer <admin_jwt>
Body: { "license_key": "PL-PRO-xxx", "reason": "user_refund" }

[网关处理]
    │
    ▼
[1. 更新许可证状态]
    UPDATE licenses SET
      status = 'cancelled',
      cancelled_at = NOW(),
      updated_at = NOW()
    WHERE license_key = ?
    │
    ▼
[2. 查询所有活跃JWT的jti]
    查询 Redis ws_connections:{user_id} 获取所有活跃会话
    获取会话关联的 jti 列表
    │
    ▼
[3. 加入CRL黑名单]
    FOR each jti in 活跃JWT:
        SET Redis jwt_blacklist:{jti} = "revoked" EX 900
    │
    ▼
[4. 断开WebSocket连接]
    向所有活跃WSS连接发送 {type:"license_revoked"} 消息
    关闭连接
    │
    ▼
[5. 记录审计日志]
    audit_log(action='license_revoke', resource_id=license_key, metadata={reason})
    │
    ▼
[6. 触发告警]
    通知运维 (邮件/钉钉)
```

### 6.5 管理员认证机制（P0-4 安全修复）

> **背景**：P6 安全审查发现 `/api/v1/admin/*` 管理员接口认证机制未定义，存在越权风险。本节定义管理员账户体系与双因素认证机制。

#### 6.5.1 管理员账户体系

管理员账户与普通用户账户隔离，采用独立的认证体系：

| 要素 | 说明 | 存储位置 |
|------|------|----------|
| `admin_api_key` | 管理员 API Key（预共享密钥） | 环境变量 `ADMIN_API_KEY` |
| `admin_jwt` | 管理员 JWT（短期令牌） | 运行时签发，RS256 签名 |
| `ADMIN_JWT_SECRET` | 管理员 JWT 签名密钥（独立于用户 JWT） | 环境变量 + Docker Secret |
| `admin_id` | 管理员标识（如 `admin_001`） | 环境变量 `ADMIN_ID` |

**密钥隔离原则**：
- 管理员 JWT 使用**独立的签名密钥** `ADMIN_JWT_SECRET`，与用户 JWT 的 RSA 密钥对完全隔离
- 管理员 JWT 的 `iss` 为 `promiselink-gateway-admin`，`aud` 为 `promiselink-admin-client`，与用户 JWT 区分
- 管理员 API Key 与用户 API Key（`X-API-Key`）使用不同的请求头字段（`X-Admin-API-Key`）

#### 6.5.2 双因素认证流程

管理员接口要求**同时**携带 API Key 和 JWT，缺一不可：

```http
POST /api/v1/admin/license/revoke HTTP/1.1
Host: api.promiselink.com
X-Admin-API-Key: pl_admin_xxx
Authorization: Bearer <admin_jwt>
X-Request-ID: 550e8400-e29b-41d4-a716-446655440000
Content-Type: application/json
```

**认证中间件流程**（`AdminAuthMiddleware`）：

```
请求到达 /api/v1/admin/*
    │
    ▼
[1. 验证 Admin API Key]
    读取 X-Admin-API-Key 头
    与环境变量 ADMIN_API_KEY 比对（常数时间比较，防时序攻击）
    ├── 不匹配 → 401 ADMIN_API_KEY_INVALID
    ├── 缺失 → 401 ADMIN_API_KEY_MISSING
    │
    ▼
[2. 验证 Admin JWT]
    解析 Authorization: Bearer <admin_jwt>
    使用 ADMIN_JWT_SECRET 验证签名
    ├── 签名无效 → 401 ADMIN_JWT_INVALID
    ├── 已过期 → 401 ADMIN_JWT_EXPIRED
    ├── iss != 'promiselink-gateway-admin' → 401 ADMIN_JWT_INVALID
    ├── aud != 'promiselink-admin-client' → 401 ADMIN_JWT_INVALID
    │
    ▼
[3. 检查管理员 CRL 黑名单]
    EXISTS Redis admin_jwt_blacklist:{jti}
    ├── 存在 → 401 ADMIN_JWT_REVOKED
    │
    ▼
[4. 注入管理员上下文]
    request.state.admin_id = admin_jwt.admin_id
    request.state.is_admin = True
    进入业务处理
```

#### 6.5.3 管理员 JWT 签发

管理员 JWT 通过独立的登录接口签发（不对外公开，仅限内网/VPN访问）：

```
POST /api/v1/admin/login (仅内网访问，Nginx 限制源IP)
Headers:
  X-Admin-API-Key: ${ADMIN_API_KEY}
Body: { "admin_id": "admin_001", "passphrase": "${ADMIN_PASSPHRASE}" }

[网关处理]
    ├── 验证 admin_api_key
    ├── 验证 admin_id + passphrase（环境变量预配置）
    ├── 签发 admin_jwt (RS256, TTL=30分钟)
    └── 返回 admin_jwt
```

**管理员 JWT Payload**：

```json
{
  "admin_id": "admin_001",
  "role": "admin",
  "jti": "admin-jwt-uuid-xxx",
  "iat": 1718037056,
  "exp": 1718038856,
  "iss": "promiselink-gateway-admin",
  "aud": "promiselink-admin-client"
}
```

| 字段 | 说明 |
|------|------|
| admin_id | 管理员标识 |
| role | 固定为 `admin` |
| jti | JWT唯一ID（用于管理员CRL吊销） |
| exp | 过期时间（iat + 1800s，30分钟TTL） |
| iss | `promiselink-gateway-admin`（区别于用户JWT） |
| aud | `promiselink-admin-client`（区别于用户JWT） |

#### 6.5.4 管理员接口清单

| 方法 | 路径 | 用途 | 风险等级 |
|------|------|------|----------|
| POST | `/api/v1/admin/login` | 管理员登录签发JWT | 高（仅内网） |
| POST | `/api/v1/admin/license/revoke` | 吊销许可证 | 高 |
| GET | `/api/v1/admin/usage` | 查看全平台用量统计 | 中 |
| GET | `/api/v1/admin/users` | 查看用户列表与状态 | 中 |
| POST | `/api/v1/admin/keys/disable` | 禁用API Key池中的Key | 高 |
| POST | `/api/v1/admin/keys/enable` | 启用API Key池中的Key | 高 |
| POST | `/api/v1/admin/users/ban` | 封禁用户 | 高 |
| POST | `/api/v1/admin/jwt/revoke` | 吊销指定用户JWT | 高 |

**管理员权限范围**：
- 吊销许可证（用户退款/违规）
- 查看全平台用量统计与单用户用量明细
- 管理 API Key 池（启用/禁用/查看健康状态）
- 封禁/解封用户账户
- 吊销指定用户的 JWT（强制下线）

#### 6.5.5 管理员接口安全加固

| 措施 | 实现 |
|------|------|
| **网络隔离** | `/api/v1/admin/*` 路径在 Nginx 层限制源 IP（仅允许运维内网/VPN） |
| **双因素认证** | admin_api_key + admin_jwt，缺一不可 |
| **独立密钥** | 管理员 JWT 使用独立签名密钥 ADMIN_JWT_SECRET |
| **短TTL** | 管理员 JWT TTL=30分钟（用户JWT为15分钟，但管理员令牌更短更严格） |
| **独立CRL** | Redis `admin_jwt_blacklist:{jti}`，管理员JWT吊销独立管理 |
| **审计日志** | 所有管理员操作记录 `audit_logs`，action 前缀 `admin_`，含 admin_id |
| **速率限制** | 管理员接口独立限流：10 req/min per admin（比用户更严格） |
| **登录保护** | admin/login 接口失败5次锁定1小时，记录 IP |

**Nginx 管理员路径 IP 白名单配置**：

```nginx
location /api/v1/admin/ {
    # 仅允许运维内网IP访问
    allow 10.0.0.0/8;          # 内网
    allow 192.168.0.0/16;       # 内网
    allow <运维公网IP>;          # 运维VPN出口IP
    deny all;
    
    proxy_pass http://gateway:8000;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
}
```

#### 6.5.6 管理员环境变量

在 §10.2 环境变量清单中新增以下配置：

```bash
# ── 管理员认证 (P0-4) ──
ADMIN_API_KEY=your-admin-api-key-min-32-chars    # 管理员API Key
ADMIN_JWT_SECRET=your-admin-jwt-secret-min-32-chars  # 管理员JWT签名密钥
ADMIN_ID=admin_001                                # 管理员标识
ADMIN_PASSPHRASE=your-admin-passphrase            # 管理员登录口令
ADMIN_JWT_TTL=1800                                # 管理员JWT有效期(秒，默认30分钟)
ADMIN_LOGIN_MAX_FAILURES=5                        # 登录失败锁定阈值
ADMIN_LOGIN_LOCK_DURATION=3600                    # 锁定时长(秒)
```

### 6.6 JWT Payload 结构

```json
{
  "user_id": "u_abc123",
  "license_key": "PL-PRO-A1B2-C3D4-E5F6",
  "plan_type": "pro",
  "device_fingerprint": "sha256:abc123def456...",
  "jti": "550e8400-e29b-41d4-a716-446655440000",
  "iat": 1718037056,
  "exp": 1718037956,
  "iss": "promiselink-gateway",
  "aud": "promiselink-client"
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| user_id | string | 用户ID |
| license_key | string | 许可证Key |
| plan_type | string | `pro`/`trial` |
| device_fingerprint | string | 设备指纹（I-4防破解） |
| jti | string | JWT唯一ID（用于CRL吊销） |
| iat | int | 签发时间（Unix时间戳） |
| exp | int | 过期时间（Unix时间戳，iat+900s） |
| iss | string | 签发方 |
| aud | string | 接收方 |

---

## 7. 用量计费设计

### 7.1 计费维度

| 调用类型 | 计费单位 | 计费来源 | 早鸟版配额 | 常规版配额 |
|----------|----------|----------|------------|------------|
| LLM | Token | LLM响应usage字段 | 50万Token/月 | 100万Token/月 |
| ASR | 次 | 请求计数 | 200次/月 | 500次/月 |
| TTS | 次 | 请求计数 | 200次/月 | 500次/月 |
| OCR | 次 | 请求计数 | 100次/月 | 300次/月 |

### 7.2 配额管理

#### 7.2.1 月度配额重置

```
定时任务（每月1日 00:00 UTC 执行）:
    │
    ▼
[1. 重置当月配额]
    UPDATE licenses SET
      quota_used_tokens = 0,
      quota_used_asr = 0,
      quota_used_tts = 0,
      quota_used_ocr = 0,
      quota_reset_at = NOW() + INTERVAL '1 month',
      updated_at = NOW()
    WHERE status = 'active'
    │
    ▼
[2. 归档上月用量]
    INSERT INTO monthly_usage (user_id, license_key, year_month, total_tokens, ...)
    SELECT user_id, license_key, TO_CHAR(NOW() - INTERVAL '1 month', 'YYYY-MM'),
           quota_used_tokens, ...
    FROM licenses WHERE status = 'active'
    │
    ▼
[3. 清理Redis缓存]
    DEL quota:cache:{user_id}:{last_month}
    │
    ▼
[4. 生成账单]
    FOR each active user:
        生成月度账单 (PDF/JSON)
        发送用量报告邮件
```

#### 7.2.2 红黄绿灯三态

| 状态 | 触发条件 | UI表现 | 网关行为 |
|------|----------|--------|----------|
| 🟢 绿灯 | 用量 < 80% | 正常使用 | 放行所有请求 |
| 🟡 黄灯 | 80% ≤ 用量 < 100% | 提示"本月AI调用接近上限" | 放行 + 响应头 `X-Quota-Warning: yellow` |
| 🔴 红灯 | 用量 ≥ 100% | 拒绝AI调用，降级提示 | 拒绝AI调用，返回 402 QUOTA_EXCEEDED |

**状态灯计算**（基于Token用量，其他类型独立计算）：

```
percentage = quota_used_tokens / quota_limit_tokens × 100

IF percentage < 80:
    traffic_light = 'green'
ELIF percentage < 100:
    traffic_light = 'yellow'
ELSE:
    traffic_light = 'red'
```

**状态变更告警**：

```
当 traffic_light 从 green → yellow:
    发送用户通知 (小程序消息推送)
    记录审计日志

当 traffic_light 从 yellow → red:
    发送用户通知 (小程序消息推送 + 邮件)
    记录审计日志
    触发运维告警 (钉钉)
```

### 7.3 超额处理

**硬限制（默认）**：
- LLM Token超限 → 拒绝所有LLM调用，返回 402 QUOTA_EXCEEDED
- ASR/TTS/OCR 次数超限 → 拒绝对应类型调用，其他类型不受影响

**软限制（可选，未来演进）**：
- 超额后降级到更便宜的模型（如 deepseek-chat → deepseek-lite）
- 超额后降低速率限制（100 req/min → 20 req/min）
- 需用户在设置中开启"超额降级"开关

### 7.4 用量记录流程

```
AI调用完成
    │
    ▼
[1. 解析LLM响应usage]
    usage = {
      input_tokens: 150,
      output_tokens: 80,
      total_tokens: 230
    }
    │
    ▼
[2. 计算成本]
    cost_cny = total_tokens × provider_price_per_token
    # DeepSeek: ¥0.001/1K tokens
    # Moka AI: ¥0.002/1K tokens
    │
    ▼
[3. 异步记录用量] (不阻塞响应)
    INSERT INTO usage_records (
      request_id, user_id, license_key,
      request_type, provider, model, key_id,
      input_tokens, output_tokens, total_tokens,
      duration_ms, cost_cny, status_code, success
    ) VALUES (...)
    │
    ▼
[4. 更新许可证配额] (原子操作)
    UPDATE licenses SET
      quota_used_tokens = quota_used_tokens + ?,
      updated_at = NOW()
    WHERE license_key = ?
    RETURNING quota_used_tokens, quota_limit_tokens
    │
    ▼
[5. 更新月度汇总]
    UPSERT INTO monthly_usage
    SET total_tokens = total_tokens + ?,
        total_cost_cny = total_cost_cny + ?,
        request_count = request_count + 1,
        last_updated_at = NOW()
    WHERE user_id = ? AND year_month = ?
    │
    ▼
[6. 更新Redis缓存]
    HINCRBY quota:cache:{user_id}:{year_month} tokens_used ?
    EXPIRE quota:cache:{user_id}:{year_month} 60
    │
    ▼
[7. 检查状态灯变更]
    new_percentage = quota_used_tokens / quota_limit_tokens
    IF 状态灯变更:
        触发告警 + 通知
```

### 7.5 账单生成

**月度账单内容**：

```json
{
  "bill_id": "bill_2026_06_u_abc123",
  "user_id": "u_abc123",
  "license_key": "PL-PRO-A1B2-C3D4-E5F6",
  "period": "2026-06",
  "summary": {
    "total_tokens": 420000,
    "total_cost_cny": 0.42,
    "request_count": 380,
    "traffic_light_final": "yellow"
  },
  "breakdown": {
    "llm": { "tokens": 380000, "cost_cny": 0.38, "requests": 320 },
    "asr": { "count": 45, "cost_cny": 0.02, "requests": 45 },
    "tts": { "count": 12, "cost_cny": 0.01, "requests": 12 },
    "ocr": { "count": 3, "cost_cny": 0.01, "requests": 3 }
  },
  "quota": {
    "tokens_limit": 500000,
    "tokens_used": 420000,
    "utilization": 0.84
  },
  "generated_at": "2026-07-01T00:00:00Z"
}
```

---

## 8. 中继服务设计

### 8.1 请求流程

```
小程序/本地Docker 请求到达网关
    │
    ▼
[1. 中间件链处理]
    RequestID → JWT验证 → 许可验证 → 限流 → 审计
    │
    ▼
[2. 路由判断]
    ├── /api/v1/pro/relay/llm|asr|tts|ocr → AIProxy (直连LLM)
    └── /api/v1/pro/business/* → RelayRouter (WSS中继到本地Docker)
    │
    ▼
[3a. AIProxy流程] (AI调用)
    ├── 配额检查 (BillingService)
    ├── Key池选择 (APIKeyPool)
    ├── 转发至LLM API (流式SSE)
    ├── 流式响应转发客户端
    └── 异步记录用量 (BillingService)
    │
    ▼
[3b. RelayRouter流程] (业务请求中继)
    ├── 查询Redis ws_connections:{user_id}
    │   └── 不存在 → 503 LOCAL_SERVICE_DISCONNECTED
    ├── 通过WSS发送请求至本地Docker
    │   {type:"request", request_id, payload:{method, path, headers, body}}
    ├── 等待响应 (超时30s)
    │   {type:"response", request_id, payload:{status, body}}
    └── 返回HTTP响应给客户端
```

### 8.2 流式响应（SSE）

**LLM流式响应处理**：

```
客户端请求 POST /api/v1/pro/relay/llm (stream=true)
    │
    ▼
[网关接收请求]
    设置响应头:
      Content-Type: text/event-stream
      Cache-Control: no-cache
      Connection: keep-alive
      X-Accel-Buffering: no  (禁用Nginx缓冲)
    │
    ▼
[网关转发至LLM API] (stream=true)
    使用 httpx.AsyncClient 流式接收
    │
    ▼
[逐token转发]
    FOR each chunk in LLM响应流:
        解析chunk: {choices:[{delta:{content:"张"}}]}
        组装SSE事件:
            event: token
            data: {"content":"张","index":0}
        立即flush到客户端
    │
    ▼
[流结束]
    解析最终usage: {usage:{input_tokens:150, output_tokens:80}}
    发送结束事件:
        event: done
        data: {"usage":{...},"billing":{...}}
    │
    ▼
[异步记录用量]
    BillingService.record_usage(...)
```

**SSE事件格式**：

| 事件 | data内容 | 说明 |
|------|----------|------|
| `token` | `{"content":"张","index":0}` | 单个token |
| `error` | `{"code":"...","message":"..."}` | 流中错误 |
| `done` | `{"usage":{...},"billing":{...}}` | 流结束 |

### 8.3 超时处理

**超时配置**：

| 阶段 | 超时时间 | 处理 |
|------|----------|------|
| 客户端→网关 | 30s | Nginx `proxy_read_timeout 30s` |
| 网关→LLM API | 30s | httpx `timeout=30.0` |
| 网关→本地Docker (WSS) | 30s | 等待response消息 |
| Key池探活 | 5s | httpx `timeout=5.0` |

**超时处理流程**：

```
LLM API调用超时 (30s):
    │
    ▼
[1. 取消请求]
    取消httpx请求
    │
    ▼
[2. 更新Key健康分]
    APIKeyPool.update_health(key_id, -0.25)
    │
    ▼
[3. 重试]
    选择新Key重试 (最多2次)
    │
    ▼
[4. 重试仍失败]
    返回 504 UPSTREAM_TIMEOUT
    记录审计日志
```

### 8.4 错误处理与Provider降级

**LLM错误降级策略**：

```
LLM调用失败
    │
    ▼
[1. 错误分类]
    ├── 400 (请求错误) → 不重试，返回400
    ├── 401 (Key无效) → 标记Key disabled，重试其他Key
    ├── 429 (限流) → Key冷却60s，重试其他Key
    ├── 5xx (服务端错误) → Key健康分-0.30，连续3次熔断，重试其他Key
    ├── 超时 → Key健康分-0.25，重试其他Key
    └── 网络错误 → Key健康分-0.20，重试其他Key
    │
    ▼
[2. Key池重试]
    最多重试3次（不同Key）
    │
    ▼
[3. Provider降级]
    所有同Provider Key失败:
    ├── 尝试备用Provider (deepseek → moka_ai)
    ├── 降级模型 (deepseek-chat → deepseek-lite)
    └── 返回降级响应 + 响应头 X-Degraded: true
    │
    ▼
[4. 全部失败]
    返回 503 NO_AVAILABLE_KEY
    响应体:
    {
      "error": {
        "code": "NO_AVAILABLE_KEY",
        "message": "AI服务暂时不可用，请稍后重试",
        "details": {
          "retry_after": 60,
          "alternative": "基础功能仍可用，AI功能稍后恢复"
        }
      }
    }
```

### 8.5 WebSocket中继协议

#### 8.5.1 连接建立

```
本地Docker relay_client → WSS连接 wss://gw.promiselink.ai/relay
    │
    ▼
[握手阶段]
    携带:
      Authorization: Bearer <jwt>
      X-Device-Fingerprint: sha256:...
    │
    ▼
[网关验证]
    ├── JWT验证 (RS256签名)
    ├── 许可证状态检查
    ├── 设备指纹匹配
    └── 限流检查 (单IP最大50连接)
    │
    ▼
[建立连接]
    创建 connection_id (UUID)
    Redis HSET ws_connections:{user_id} {connection_id} {session_id}
    创建 relay_sessions 记录
    发送 {type:"connected", connection_id, heartbeat_interval:30}
```

#### 8.5.2 消息格式

**请求消息**（网关→本地Docker）：

```json
{
  "type": "request",
  "request_id": "550e8400-e29b-41d4-a716-446655440000",
  "payload": {
    "method": "POST",
    "path": "/api/v1/events",
    "headers": {"Content-Type": "application/json"},
    "body": {"content": "今天和张总吃了午饭"},
    "timeout_ms": 30000
  }
}
```

**响应消息**（本地Docker→网关）：

```json
{
  "type": "response",
  "request_id": "550e8400-e29b-41d4-a716-446655440000",
  "payload": {
    "status": 200,
    "headers": {"Content-Type": "application/json"},
    "body": {"event_id": "evt_xxx", "entities": [...]}
  }
}
```

**心跳消息**：

```json
// 本地Docker → 网关 (每30s)
{"type": "ping", "timestamp": 1718037056}

// 网关 → 本地Docker
{"type": "pong", "timestamp": 1718037056}
```

**控制消息**：

```json
// 网关 → 本地Docker (许可证吊销)
{"type": "license_revoked", "reason": "user_refund"}

// 网关 → 本地Docker (JWT即将过期)
{"type": "token_expiring", "expires_in": 300, "refresh_url": "/api/v1/pro/license/verify"}
```

#### 8.5.3 心跳与重连

| 参数 | 值 | 说明 |
|------|----|------|
| 心跳间隔 | 30s | relay_client定时发送ping |
| 超时判定 | 60s无pong | 网关判定连接断开 |
| 重连策略 | 指数退避 | 1s→2s→4s→8s→16s→30s（上限） |
| 重连上限 | 无限 | 持续重连直到网关恢复或许可证过期 |

**断线处理**：

```
WSS连接断开:
    │
    ▼
[网关侧]
    Redis HDEL ws_connections:{user_id} {connection_id}
    UPDATE relay_sessions SET status='disconnected', disconnected_at=NOW()
    清理待处理请求 (返回503给小程序)
    │
    ▼
[本地Docker侧]
    relay_client检测到断线
    指数退避重连
    重连成功后重新建立映射
```

---

## 9. 安全设计

### 9.1 传输安全

| 层级 | 措施 | 配置 |
|------|------|------|
| CDN层 | Cloudflare TLS 1.3 | I-5 DDoS防护 |
| 反向代理 | Nginx TLS 1.2+ | 证书: Let's Encrypt (自动续期) |
| 加密算法 | ECDHE-ECDSA-AES256-GCM-SHA384 | 强加密套件 |
| HSTS | max-age=31536000; includeSubDomains | 强制HTTPS |
| WSS | wss:// 协议 | WebSocket over TLS |

**Nginx TLS配置**：

```nginx
ssl_protocols TLSv1.2 TLSv1.3;
ssl_ciphers ECDHE-ECDSA-AES256-GCM-SHA384:ECDHE-RSA-AES256-GCM-SHA384;
ssl_prefer_server_ciphers off;
ssl_session_cache shared:SSL:10m;
ssl_session_timeout 10m;
add_header Strict-Transport-Security "max-age=31536000; includeSubDomains" always;
```

### 9.2 认证安全

**双因素认证**（I-4 防破解增强）：

| 因素 | 实现 | 说明 |
|------|------|------|
| API Key | `X-API-Key` 头 | 网关客户端预共享密钥 |
| JWT (RS256) | `Authorization: Bearer` 头 | 非对称签名，私钥签发公钥验证 |
| 设备指纹 | `X-Device-Fingerprint` 头 | SHA256(硬件特征)，绑定许可证 |

**JWT安全措施**：

| 措施 | 实现 |
|------|------|
| 非对称签名 | RS256，私钥仅网关持有，公钥可分发验证 |
| 短TTL | access_token 15分钟，refresh_token 7天 |
| 唯一标识 | jti (UUID) 用于CRL吊销 |
| CRL黑名单 | Redis `jwt_blacklist:{jti}`，TTL=JWT剩余有效期 |
| 设备绑定 | JWT含device_fingerprint，每次请求验证匹配 |

**密钥管理**：

| 密钥 | 用途 | 存储位置 | 轮换策略 |
|------|------|----------|----------|
| RSA私钥 | JWT签名 | 环境变量 + Docker Secret | 每90天轮换 |
| RSA公钥 | JWT验证 | 环境变量 | 随私钥轮换 |
| API加密密钥 | API Key池加密 | 环境变量 | 每180天轮换 |
| PG密码 | 数据库访问 | Docker Secret | 每90天轮换 |
| Redis密码 | 缓存访问 | 环境变量 | 每90天轮换 |

### 9.3 数据安全

**数据最小化原则**（B-3 阻断项修复）：

| 数据类别 | 是否记录 | 说明 |
|----------|----------|------|
| 请求/响应body | ❌ 禁止 | 业务内容不落盘 |
| LLM prompt/响应 | ❌ 禁止 | AI内容仅过内存 |
| 音频/图片内容 | ❌ 禁止 | 媒体内容仅过内存 |
| request_id | ✅ 记录 | 请求追踪 |
| user_id | ✅ 记录 | 计费/审计 |
| provider/model | ✅ 记录 | 计费/监控 |
| tokens数 | ✅ 记录 | 计费 |
| status_code | ✅ 记录 | 监控 |
| timestamp | ✅ 记录 | 审计 |
| latency_ms | ✅ 记录 | 性能监控 |

**网关内存数据生命周期**：

- AI请求/响应在网关进程内存中停留时间：**< 请求处理时长**（通常<2秒）
- 请求响应完成后，Python垃圾回收立即释放引用
- 网关**不启用**任何内存缓存存储AI内容
- 网关进程**不生成core dump**，生产环境禁用debug模式

**PII脱敏**：

- LLM prompt中的电话/邮箱已脱敏（`138****1234`格式）
- 网关日志严禁记录PII明文
- 审计日志metadata字段不含业务内容

### 9.4 防刷设计

#### 9.4.1 速率限制（I-6 防刷）

| 维度 | 限制 | 实现 |
|------|------|------|
| 单用户 | 100 req/min | Redis `rate_limit:{user_id}:{minute}` |
| 单用户 | 1000 req/hour | Redis `rate_limit:{user_id}:hourly` |
| 单IP | 200 req/min | Nginx `limit_req` |
| 单IP | 50 WebSocket连接 | Nginx `limit_conn` |
| 全局 | 5000 req/min | Nginx全局限流 |

**用户级限流算法**（滑动窗口）：

```
请求到达:
    key = "rate_limit:{user_id}:{minute}"  # 如 rate_limit:u_abc:202606171800
    current = Redis INCR(key)
    IF current == 1:
        Redis EXPIRE(key, 60)
    IF current > 100:
        返回 429 RATE_LIMIT_EXCEEDED
        响应头: X-RateLimit-Limit: 100
                X-RateLimit-Remaining: 0
                X-RateLimit-Reset: 60
```

#### 9.4.2 异常用量检测（I-6 防刷）

| 检测规则 | 阈值 | 处理 |
|----------|------|------|
| 单用户小时Token消耗 | > 10万Token | 标记异常 + 告警 |
| 单用户分钟请求数 | > 100 | 限流（429） |
| 单用户ASR频次 | > 10次/min | 限流 |
| 单IP注册数 | > 5个/天 | 告警 + 人工审核 |
| Key池异常消耗 | 单Key RPM > 限制的90% | 告警 |

**异常处理流程**：

```
检测到异常用量:
    │
    ▼
[1. 记录异常事件]
    audit_log(action='anomaly_detected', metadata={rule, threshold, actual})
    │
    ▼
[2. 触发告警]
    钉钉/邮件通知运维
    │
    ▼
[3. 自动降级] (严重异常)
    IF 单用户1小时消耗 > 20万Token:
        临时降低该用户限流至 20 req/min
        发送用户通知
    │
    ▼
[4. 人工审核] (疑似滥用)
    运维审核用户行为
    必要时吊销许可证
```

#### 9.4.3 DDoS防护（I-5）

| 防护层 | 措施 |
|--------|------|
| Cloudflare | 免费版DDoS防护 + CDN缓存 |
| Nginx | `limit_req` 限流 + `limit_conn` 连接数限制 |
| FastAPI | 用户级速率限制中间件 |
| 监控 | 5xx错误率突增告警 |

### 9.5 安全审计

**审计日志记录范围**：

| 事件 | action | 记录内容 |
|------|--------|----------|
| 许可证激活 | `license_activate` | user_id, license_key, device_fingerprint, ip |
| 许可证吊销 | `license_revoke` | license_key, reason, admin_id |
| JWT吊销 | `jwt_revoke` | jti, user_id, reason |
| 配额超限 | `quota_exceeded` | user_id, license_key, quota_type |
| Key熔断 | `key_circuit_open` | key_id, provider, consecutive_failures |
| 异常用量 | `anomaly_detected` | user_id, rule, threshold, actual |
| 登录失败 | `auth_failed` | user_id, ip, reason |
| 权限拒绝 | `permission_denied` | user_id, resource, reason |

---

## 10. 部署设计

### 10.1 Docker Compose 配置

**文件路径**：`gateway/docker-compose.yml`

```yaml
version: '3.8'

services:
  gateway:
    build:
      context: .
      dockerfile: Dockerfile
    container_name: pl-gateway
    # P0-1 安全修复: 不对外暴露8000端口，仅通过Nginx反代访问
    # gateway 只在 gateway_net 内部网络可达，由 nginx 容器代理 443→8000
    # 删除 ports 字段，避免直接绑定宿主机端口，防止绕过 Nginx 的限流/TLS/WAF
    environment:
      - GATEWAY_ENV=production
      - GATEWAY_SECRET_KEY=${GATEWAY_SECRET_KEY}
      - JWT_PRIVATE_KEY_PATH=/run/secrets/jwt_private_key
      - JWT_PUBLIC_KEY_PATH=/run/secrets/jwt_public_key
      - DATABASE_URL=postgresql://promiselink:${PG_PASSWORD}@postgres:5432/gateway
      - REDIS_URL=redis://:${REDIS_PASSWORD}@redis:6379/0
      - API_KEY_ENCRYPTION_KEY=${API_KEY_ENCRYPTION_KEY}
      - DEEPSEEK_API_KEY_1=${DEEPSEEK_API_KEY_1}
      - DEEPSEEK_API_KEY_2=${DEEPSEEK_API_KEY_2}
      - MOKA_AI_API_KEY_1=${MOKA_AI_API_KEY_1}
      - MOKA_AI_API_KEY_2=${MOKA_AI_API_KEY_2}
      - CLOUDFLARE_API_TOKEN=${CLOUDFLARE_API_TOKEN}
      - SENTRY_DSN=${SENTRY_DSN}
    secrets:
      - jwt_private_key
      - jwt_public_key
    depends_on:
      postgres:
        condition: service_healthy
      redis:
        condition: service_healthy
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8000/api/v1/pro/health"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 40s
    logging:
      driver: json-file
      options:
        max-size: "100m"
        max-file: "10"
    networks:
      - gateway_net

  postgres:
    image: postgres:16-alpine
    container_name: pl-postgres
    environment:
      - POSTGRES_DB=gateway
      - POSTGRES_USER=promiselink
      - POSTGRES_PASSWORD=${PG_PASSWORD}
    volumes:
      - gateway_pg_data:/var/lib/postgresql/data
      - ./sql/init:/docker-entrypoint-initdb.d  # 初始化SQL
    restart: unless-stopped
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U promiselink -d gateway"]
      interval: 10s
      timeout: 5s
      retries: 5
    logging:
      driver: json-file
      options:
        max-size: "50m"
        max-file: "5"
    networks:
      - gateway_net

  redis:
    image: redis:7-alpine
    container_name: pl-redis
    command: >
      redis-server
      --requirepass ${REDIS_PASSWORD}
      --maxmemory 512mb
      --maxmemory-policy volatile-lru
      --appendonly yes
      --appendfsync everysec
    # P0-3 安全修复: 使用 volatile-lru 替代 allkeys-lru
    # 仅淘汰设置了 TTL 的 Key，保护无 TTL 的持久化数据
    # JWT 黑名单 Key (jwt_blacklist:{jti}) 必须设置 TTL（=JWT剩余有效期）
    # 这样 JWT 黑名单不会被 LRU 淘汰，确保吊销机制有效
    volumes:
      - gateway_redis_data:/data
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "redis-cli", "-a", "${REDIS_PASSWORD}", "ping"]
      interval: 10s
      timeout: 5s
      retries: 5
    logging:
      driver: json-file
      options:
        max-size: "50m"
        max-file: "5"
    networks:
      - gateway_net

  nginx:
    image: nginx:alpine
    container_name: pl-nginx
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - ./nginx/gateway.conf:/etc/nginx/conf.d/default.conf:ro
      - ./nginx/nginx.conf:/etc/nginx/nginx.conf:ro
      - ./certs:/etc/nginx/certs:ro
      - ./logs/nginx:/var/log/nginx
    depends_on:
      - gateway
    restart: unless-stopped
    logging:
      driver: json-file
      options:
        max-size: "50m"
        max-file: "10"
    networks:
      - gateway_net

  prometheus:
    image: prom/prometheus:latest
    container_name: pl-prometheus
    volumes:
      - ./prometheus/prometheus.yml:/etc/prometheus/prometheus.yml:ro
      - ./prometheus/alerts.yml:/etc/prometheus/alerts.yml:ro
      - gateway_prometheus_data:/prometheus
    command:
      - '--config.file=/etc/prometheus/prometheus.yml'
      - '--storage.tsdb.retention.time=30d'
    restart: unless-stopped
    networks:
      - gateway_net

  grafana:
    image: grafana/grafana:latest
    container_name: pl-grafana
    environment:
      - GF_SECURITY_ADMIN_PASSWORD=${GRAFANA_PASSWORD}
    volumes:
      - gateway_grafana_data:/var/lib/grafana
    ports:
      - "3001:3000"  # 仅内网访问
    depends_on:
      - prometheus
    restart: unless-stopped
    networks:
      - gateway_net

  backup:
    image: postgres:16-alpine
    container_name: pl-backup
    environment:
      - PGHOST=postgres
      - PGUSER=promiselink
      - PGPASSWORD=${PG_PASSWORD}
      - PGDATABASE=gateway
    volumes:
      - ./backups:/backups
      - ./scripts/backup.sh:/backup.sh:ro
    entrypoint: /bin/sh
    command: /backup.sh
    depends_on:
      - postgres
    restart: unless-stopped
    networks:
      - gateway_net

secrets:
  jwt_private_key:
    file: ./secrets/jwt_private_key.pem
  jwt_public_key:
    file: ./secrets/jwt_public_key.pem

volumes:
  gateway_pg_data:
  gateway_redis_data:
  gateway_prometheus_data:
  gateway_grafana_data:

networks:
  gateway_net:
    driver: bridge
```

### 10.2 环境变量清单

**文件路径**：`gateway/.env.example`

```bash
# ═══════════════════════════════════════════════════════════════
# PromiseLink 网关环境变量
# ═══════════════════════════════════════════════════════════════

# ── 基础配置 ──
GATEWAY_ENV=production                    # production / staging / development
GATEWAY_HOST=0.0.0.0
GATEWAY_PORT=8000
GATEWAY_SECRET_KEY=your-gateway-secret-key-min-32-chars

# ── JWT签名 (RS256, I-4防破解) ──
# 私钥用于签发JWT，公钥用于验证
# 生成: openssl genrsa -out jwt_private_key.pem 2048
#       openssl rsa -in jwt_private_key.pem -pubout -out jwt_public_key.pem
JWT_PRIVATE_KEY_PATH=/run/secrets/jwt_private_key
JWT_PUBLIC_KEY_PATH=/run/secrets/jwt_public_key
JWT_ACCESS_TOKEN_TTL=900                  # 15分钟
JWT_REFRESH_TOKEN_TTL=604800              # 7天
JWT_ISSUER=promiselink-gateway
JWT_AUDIENCE=promiselink-client

# ── 数据库 (PostgreSQL) ──
DATABASE_URL=postgresql://promiselink:password@postgres:5432/gateway
PG_PASSWORD=your-strong-pg-password
PG_POOL_SIZE=20
PG_MAX_OVERFLOW=10
PG_POOL_TIMEOUT=30

# ── Redis ──
REDIS_URL=redis://:password@redis:6379/0
REDIS_PASSWORD=your-redis-password
REDIS_MAX_CONNECTIONS=50

# ── API Key加密 ──
API_KEY_ENCRYPTION_KEY=your-api-key-encryption-key-32bytes

# ── LLM API Keys (DeepSeek) ──
DEEPSEEK_API_KEY_1=sk-deepseek-xxx-1
DEEPSEEK_API_KEY_2=sk-deepseek-xxx-2
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_PRICE_PER_1K_TOKENS=0.001        # ¥0.001/1K tokens

# ── LLM API Keys (Moka AI) ──
MOKA_AI_API_KEY_1=sk-moka-xxx-1
MOKA_AI_API_KEY_2=sk-moka-xxx-2
MOKA_AI_BASE_URL=https://api.moka.ai/v1
MOKA_AI_PRICE_PER_1K_TOKENS=0.002

# ── API Key池配置 ──
KEY_POOL_HEALTH_CHECK_INTERVAL=30         # 健康检查间隔(秒)
KEY_POOL_COOLDOWN_DURATION=60             # 429冷却时间(秒)
KEY_POOL_CIRCUIT_DURATION=300             # 熔断时间(秒)
KEY_POOL_CIRCUIT_THRESHOLD=3              # 熔断阈值(连续失败次数)
KEY_POOL_PROBE_TIMEOUT=5                  # 探活超时(秒)

# ── 速率限制 (I-6防刷) ──
RATE_LIMIT_USER_PER_MINUTE=100            # 单用户每分钟请求数
RATE_LIMIT_USER_PER_HOUR=1000             # 单用户每小时请求数
RATE_LIMIT_IP_PER_MINUTE=200              # 单IP每分钟请求数
RATE_LIMIT_ANOMALY_TOKENS_PER_HOUR=100000 # 异常用量阈值(Token/小时)

# ── 中继配置 ──
RELAY_HEARTBEAT_INTERVAL=30               # 心跳间隔(秒)
RELAY_HEARTBEAT_TIMEOUT=60                # 心跳超时(秒)
RELAY_REQUEST_TIMEOUT=30                  # 请求超时(秒)
RELAY_MAX_CONNECTIONS_PER_IP=50           # 单IP最大WSS连接数

# ── AI调用超时 ──
LLM_REQUEST_TIMEOUT=30                    # LLM请求超时(秒)
LLM_MAX_RETRIES=3                         # 最大重试次数
ASR_MAX_AUDIO_SIZE_MB=25
TTS_MAX_TEXT_LENGTH=500
OCR_MAX_IMAGE_SIZE_MB=10

# ── 监控 (I-9) ──
SENTRY_DSN=https://xxx@sentry.io/xxx
PROMETHEUS_METRICS_PATH=/metrics
LOG_LEVEL=INFO                            # DEBUG / INFO / WARNING / ERROR
LOG_FORMAT=json                           # json / text

# ── Cloudflare (I-5 DDoS防护) ──
CLOUDFLARE_API_TOKEN=your-cf-api-token
CLOUDFLARE_ZONE_ID=your-zone-id
CLOUDFLARE_SSL_VERIFY=true

# ── Grafana ──
GRAFANA_PASSWORD=your-grafana-admin-password

# ── 备份 (I-10) ──
BACKUP_SCHEDULE=0 2 * * *                 # 每日凌晨2点(cron)
BACKUP_RETENTION_DAYS=7                   # 备份保留天数
BACKUP_PATH=/backups
```

### 10.3 数据库初始化

**文件路径**：`gateway/sql/init/01_schema.sql`

包含第3章所有表的CREATE TABLE语句，按依赖顺序：
1. `users`
2. `licenses`
3. `api_key_pool`
4. `usage_records`
5. `monthly_usage`
6. `relay_sessions`
7. `audit_logs`

**文件路径**：`gateway/sql/init/02_indexes.sql`

包含所有索引创建语句。

**文件路径**：`gateway/sql/init/03_seed_data.sql`

```sql
-- ═══════════════════════════════════════════════════════════════
-- ⚠️ P0-2 安全警告 ⚠️
-- 禁止将真实 API Key 明文写入本 SQL 文件！
-- 真实 Key 必须从环境变量加载（DEEPSEEK_API_KEY_1 等），见 §10.2
-- 种子数据仅用于初始化 Key 池结构，加密后的 Key 由部署脚本注入
-- ═══════════════════════════════════════════════════════════════

-- 初始化API Key池
-- Key 值从环境变量加载，使用 AES-256-GCM 加密后写入 api_key_encrypted 字段
-- ENC(${ENV_VAR}) 为伪代码：实际由部署脚本 seed_api_keys.py 读取环境变量并加密
-- 部署脚本路径: gateway/scripts/seed_api_keys.py
-- 环境变量来源: gateway/.env (生产环境通过 Docker Secret / Vault 注入)
INSERT INTO api_key_pool (key_id, provider, api_key_encrypted, weight, rpm_limit, tpm_limit, models_supported, base_url) VALUES
('key-deepseek-1', 'deepseek', ENC(${DEEPSEEK_API_KEY_1}), 100, 60, 100000, '["deepseek-chat","deepseek-coder"]', 'https://api.deepseek.com'),
('key-deepseek-2', 'deepseek', ENC(${DEEPSEEK_API_KEY_2}), 100, 60, 100000, '["deepseek-chat","deepseek-coder"]', 'https://api.deepseek.com'),
('key-moka-1', 'moka_ai', ENC(${MOKA_AI_API_KEY_1}), 80, 60, 100000, '["moka-chat","moka-vision","moka-tts"]', 'https://api.moka.ai/v1'),
('key-moka-2', 'moka_ai', ENC(${MOKA_AI_API_KEY_2}), 80, 60, 100000, '["moka-chat","moka-vision","moka-tts"]', 'https://api.moka.ai/v1');

-- 初始化管理员账户（仅staging环境）
-- INSERT INTO users (user_id, nickname, status) VALUES ('u_admin', 'Admin', 'active');
```

**Key 加载与加密流程**（P0-2 安全修复）：

1. **环境变量注入**：真实 API Key 通过 `.env` 文件或 Docker Secret 注入容器环境变量（`DEEPSEEK_API_KEY_1` 等），不硬编码于任何代码或 SQL 文件
2. **部署脚本加密**：`gateway/scripts/seed_api_keys.py` 读取环境变量，使用 `API_KEY_ENCRYPTION_KEY` 进行 AES-256-GCM 加密后写入数据库
3. **运行时解密**：网关服务启动时从数据库读取加密 Key，使用 `API_KEY_ENCRYPTION_KEY` 解密后驻留内存
4. **审计要求**：禁止将含真实 Key 的 SQL 文件提交至 Git；`.env` 文件必须加入 `.gitignore`

**禁止行为**：
- ❌ 在 SQL 文件中写入 `ENC('sk-deepseek-真实Key')` 形式的明文 Key
- ❌ 在代码中硬编码 API Key 字符串
- ❌ 将 `.env` 文件提交至版本控制系统
- ❌ 在日志、审计日志、错误信息中输出 API Key 明文

**Alembic迁移**（推荐用于生产）：

```
gateway/alembic/
├── alembic.ini
├── env.py
└── versions/
    ├── 001_create_users.py
    ├── 002_create_licenses.py
    ├── 003_create_api_key_pool.py
    ├── 004_create_usage_records.py
    ├── 005_create_monthly_usage.py
    ├── 006_create_relay_sessions.py
    └── 007_create_audit_logs.py
```

### 10.4 Redis缓存配置

**Redis配置要点**：

| 配置项 | 值 | 说明 |
|--------|----|------|
| maxmemory | 512mb | 内存上限 |
| maxmemory-policy | volatile-lru | P0-3修复：仅淘汰带TTL的Key，保护JWT黑名单等持久数据 |
| appendonly | yes | AOF持久化（I-10） |
| appendfsync | everysec | 每秒fsync（性能与安全平衡） |
| requirepass | 强密码 | 认证 |
| timeout | 0 | 不主动断开空闲连接 |
| tcp-keepalive | 60 | TCP保活 |

**P0-3 安全修复说明 — Redis 淘汰策略**：

原配置 `allkeys-lru` 会在内存不足时淘汰任意 Key（包括无 TTL 的持久化数据），导致 JWT 黑名单（`jwt_blacklist:{jti}`）可能被淘汰，从而使已吊销的 JWT 重新生效，构成安全风险。

修复方案改为 `volatile-lru`：
- **仅淘汰设置了 TTL 的 Key**：内存不足时，Redis 只从设置了过期时间的 Key 中按 LRU 策略淘汰
- **无 TTL 的 Key 受保护**：如 `ws_connections`、`key_pool:state`、`health_check:status` 等持久化数据不会被淘汰
- **JWT 黑名单 Key 必须设置 TTL**：`jwt_blacklist:{jti}` 的 TTL = JWT 剩余有效期（见 §3.7、§6.4），既保证吊销机制有效，又能在 JWT 过期后自动清理

**JWT 黑名单 TTL 设置要求**（强制）：
- 吊销 JWT 时：`SET jwt_blacklist:{jti} "revoked" EX <jwt_remaining_ttl>`
- TTL 计算：`jwt_remaining_ttl = jwt.exp - NOW()`
- 若 JWT 已过期，无需加入黑名单（过期 JWT 本身即无效）
- 监控指标：`gateway_jwt_blacklist_size`（Grafana 仪表盘）

**Redis数据持久化策略**（I-10）：

| 数据类型 | 持久化方式 | RPO | 说明 |
|----------|------------|-----|------|
| ws_connections | AOF | ≤1秒 | 连接映射，重启后客户端重连 |
| jwt_blacklist | AOF | ≤1秒 | CRL黑名单 |
| key_pool_state | AOF | ≤1秒 | Key池运行时状态 |
| rate_limit:* | 不持久化 | - | 限流计数器（重启重置可接受） |
| license:cache | 不持久化 | - | 许可证缓存（从PG重建） |
| quota:cache | 不持久化 | - | 用量缓存（从PG重建） |

### 10.5 监控端点

#### 10.5.1 Prometheus指标（I-9）

**指标暴露端点**：`GET /metrics`

| 指标名 | 类型 | 标签 | 说明 |
|--------|------|------|------|
| `gateway_requests_total` | Counter | method, path, status | 请求总数 |
| `gateway_request_duration_seconds` | Histogram | method, path | 请求延迟 |
| `gateway_active_ws_connections` | Gauge | - | 活跃WSS连接数 |
| `gateway_ai_calls_total` | Counter | provider, model, type, status | AI调用总数 |
| `gateway_ai_call_duration_seconds` | Histogram | provider, model | AI调用延迟 |
| `gateway_key_pool_active_keys` | Gauge | provider | 可用Key数 |
| `gateway_key_pool_circuit_open` | Gauge | provider, key_id | 熔断状态(0/1) |
| `gateway_key_pool_health_score` | Gauge | key_id | Key健康分 |
| `gateway_quota_usage_ratio` | Gauge | user_id | 用户配额使用率 |
| `gateway_jwt_validations_total` | Counter | result | JWT验证结果 |
| `gateway_rate_limit_hits_total` | Counter | user_id, type | 限流触发次数 |
| `gateway_db_connections` | Gauge | - | PG连接池使用 |
| `gateway_redis_operations_total` | Counter | operation | Redis操作数 |

#### 10.5.2 健康检查端点

| 端点 | 用途 | 检查内容 |
|------|------|----------|
| `GET /api/v1/pro/health` | 综合健康 | DB+Redis+Key池+LLM可达性 |
| `GET /health/live` | 存活探针 | 进程存活 |
| `GET /health/ready` | 就绪探针 | DB+Redis连接正常 |

#### 10.5.3 告警规则（I-9）

**文件路径**：`gateway/prometheus/alerts.yml`

| 告警名 | 条件 | 严重度 | 通知方式 |
|--------|------|--------|----------|
| GatewayDown | `up{job="gateway"} == 0` for 1m | Critical | 钉钉+电话 |
| HighErrorRate | `rate(gateway_requests_total{status=~"5.."}[5m]) > 0.01` | Critical | 钉钉 |
| WSSConnectionsHigh | `gateway_active_ws_connections > 500` | Warning | 钉钉 |
| AICallSuccessLow | `rate(gateway_ai_calls_total{status="success"}[5m]) / rate(gateway_ai_calls_total[5m]) < 0.99` | Warning | 钉钉 |
| KeyPoolLow | `gateway_key_pool_active_keys < 2` | Critical | 钉钉+电话 |
| LLMLatencyHigh | `histogram_quantile(0.95, gateway_ai_call_duration_seconds) > 2` | Warning | 钉钉 |
| QuotaAnomaly | `rate(gateway_quota_usage_ratio[1h]) > 0.5` | Warning | 钉钉 |
| DBConnectionsHigh | `gateway_db_connections > 16` | Warning | 钉钉 |
| RedisMemoryHigh | `redis_memory_used / redis_memory_max > 0.8` | Warning | 钉钉 |
| CertExpiringSoon | `probe_ssl_earliest_cert_expiry < 14` | Warning | 钉钉+邮件 |
| CertExpired | `probe_ssl_earliest_cert_expiry < 7` | Critical | 钉钉+电话 |

### 10.6 备份策略（I-10）

**备份脚本**：`gateway/scripts/backup.sh`

```bash
#!/bin/sh
# 每日凌晨2点执行 (cron: 0 2 * * *)
# 备份PG + Redis AOF

BACKUP_DIR="/backups"
DATE=$(date +%Y%m%d_%H%M%S)
RETENTION_DAYS=7

# PG备份
pg_dump -h postgres -U promiselink gateway | gzip > "${BACKUP_DIR}/gateway_pg_${DATE}.sql.gz"

# Redis备份 (触发BGSAVE后复制AOF文件)
redis-cli -a ${REDIS_PASSWORD} BGSAVE
sleep 10
cp /data/appendonly.aof "${BACKUP_DIR}/gateway_redis_${DATE}.aof"

# 清理过期备份
find ${BACKUP_DIR} -name "gateway_pg_*.sql.gz" -mtime +${RETENTION_DAYS} -delete
find ${BACKUP_DIR} -name "gateway_redis_*.aof" -mtime +${RETENTION_DAYS} -delete

# 上传到对象存储 (可选)
# aws s3 cp ${BACKUP_DIR}/ s3://promiselink-backups/gateway/ --recursive
```

**备份策略表**：

| 数据 | 备份方式 | 频率 | 保留 | RTO | RPO |
|------|----------|------|------|-----|-----|
| PG (用户/许可证/用量) | pg_dump + gzip | 每日2:00 | 7天 | 1小时 | 24小时 |
| Redis (连接映射/CRL) | AOF + BGSAVE | 每日2:00 | 7天 | 5分钟 | 1秒 |
| 网关配置 | 环境变量备份 | 每次变更 | 永久 | 5分钟 | 0 |
| 网关代码 | Git仓库 | 每次提交 | 永久 | 10分钟 | 0 |

**灾难恢复流程**：

```
网关VPS故障:
    │
    ▼
[1. 启动新VPS]
    部署Docker Compose
    │
    ▼
[2. 恢复PG]
    恢复最新pg_dump备份
    gunzip -c gateway_pg_YYYYMMDD.sql.gz | psql -h postgres -U promiselink gateway
    │
    ▼
[3. 恢复Redis]
    恢复AOF文件
    cp gateway_redis_YYYYMMDD.aof /data/appendonly.aof
    重启Redis
    │
    ▼
[4. 恢复配置]
    恢复环境变量
    恢复TLS证书
    │
    ▼
[5. 启动网关]
    docker-compose up -d
    │
    ▼
[6. 验证]
    健康检查通过
    relay_client自动重连
    用户无感知
```

### 10.7 CI/CD Pipeline（I-9）

**文件路径**：`.github/workflows/gateway-ci.yml`

```yaml
name: Gateway CI/CD

on:
  push:
    paths:
      - 'gateway/**'
      - '.github/workflows/gateway-ci.yml'
  pull_request:
    paths:
      - 'gateway/**'

jobs:
  test:
    runs-on: ubuntu-latest
    services:
      postgres:
        image: postgres:16-alpine
        env:
          POSTGRES_PASSWORD: test
        ports: ['5432:5432']
      redis:
        image: redis:7-alpine
        ports: ['6379:6379']
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.11'
      - name: Install dependencies
        run: |
          cd gateway
          pip install -r requirements.txt
          pip install -r requirements-test.txt
      - name: Lint
        run: cd gateway && ruff check .
      - name: Type check
        run: cd gateway && mypy .
      - name: Unit tests
        run: cd gateway && pytest tests/unit/ -v --cov
      - name: Integration tests
        run: cd gateway && pytest tests/integration/ -v
        env:
          DATABASE_URL: postgresql://postgres:test@localhost:5432/gateway_test
          REDIS_URL: redis://localhost:6379/0

  build:
    needs: test
    if: github.ref == 'refs/heads/main'
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Build Docker image
        run: docker build -t pl-gateway ./gateway
      - name: Push to GHCR
        run: |
          echo ${{ secrets.GITHUB_TOKEN }} | docker login ghcr.io -u ${{ github.actor }} --password-stdin
          docker tag pl-gateway ghcr.io/${{ github.repository }}/gateway:${{ github.sha }}
          docker push ghcr.io/${{ github.repository }}/gateway:${{ github.sha }}

  deploy-staging:
    needs: build
    if: github.ref == 'refs/heads/main'
    runs-on: ubuntu-latest
    steps:
      - name: Deploy to staging
        run: |
          ssh staging-server "cd /opt/pl-gateway && docker-compose pull && docker-compose up -d"
```

---

## 11. 错误码定义

### 11.1 错误码命名规范

格式：`<DOMAIN>_<ERROR_TYPE>`

| 域 | 说明 |
|----|------|
| `LICENSE_` | 许可证相关 |
| `JWT_` | JWT认证相关 |
| `QUOTA_` | 配额相关 |
| `RATE_LIMIT_` | 速率限制相关 |
| `KEY_POOL_` | API Key池相关 |
| `RELAY_` | 中继相关 |
| `UPSTREAM_` | 上游服务（LLM API）相关 |
| `GATEWAY_` | 网关内部错误 |
| `VALIDATION_` | 请求校验相关 |

### 11.2 完整错误码表

#### 11.2.1 认证类错误 (401)

| HTTP | error.code | message | 触发条件 | 客户端处理 |
|------|-----------|---------|----------|------------|
| 401 | `JWT_INVALID` | JWT无效 | 签名错误/格式错误 | 重新激活许可 |
| 401 | `JWT_EXPIRED` | JWT已过期 | exp < NOW() | 使用refresh_token刷新 |
| 401 | `JWT_REVOKED` | JWT已被吊销 | jti在CRL黑名单 | 重新激活许可 |
| 401 | `JWT_MISSING` | 缺少JWT | 未携带Authorization头 | 提供JWT |
| 401 | `API_KEY_INVALID` | API Key无效 | X-API-Key错误 | 检查API Key |

#### 11.2.2 授权类错误 (403)

| HTTP | error.code | message | 触发条件 | 客户端处理 |
|------|-----------|---------|----------|------------|
| 403 | `LICENSE_INACTIVE` | 许可证未激活 | status != active | 联系客服 |
| 403 | `LICENSE_EXPIRED` | 许可证已过期 | expires_at < NOW() | 续费 |
| 403 | `LICENSE_CANCELLED` | 许可证已取消 | status = cancelled | 重新购买 |
| 403 | `LICENSE_SUSPENDED` | 许可证已暂停 | status = suspended | 联系客服 |
| 403 | `DEVICE_FINGERPRINT_MISMATCH` | 设备指纹不匹配 | 设备未绑定 | 在已绑定设备使用 |
| 403 | `DEVICE_LIMIT_EXCEEDED` | 超过设备绑定数 | max_devices超限 | 解绑旧设备 |
| 403 | `PERMISSION_DENIED` | 权限不足 | 越权访问 | 检查权限 |

#### 11.2.3 配额类错误 (402)

| HTTP | error.code | message | 触发条件 | 客户端处理 |
|------|-----------|---------|----------|------------|
| 402 | `QUOTA_EXCEEDED` | 本月AI额度已用完 | Token用量≥100% | 等待下月重置或升级 |
| 402 | `ASR_QUOTA_EXCEEDED` | ASR次数已用完 | ASR次数≥100% | 等待下月重置 |
| 402 | `TTS_QUOTA_EXCEEDED` | TTS次数已用完 | TTS次数≥100% | 等待下月重置 |
| 402 | `OCR_QUOTA_EXCEEDED` | OCR次数已用完 | OCR次数≥100% | 等待下月重置 |

#### 11.2.4 限流类错误 (429)

| HTTP | error.code | message | 触发条件 | 客户端处理 |
|------|-----------|---------|----------|------------|
| 429 | `RATE_LIMIT_EXCEEDED` | 请求过于频繁 | 单用户>100 req/min | 等待60秒 |
| 429 | `IP_RATE_LIMIT_EXCEEDED` | IP请求过于频繁 | 单IP>200 req/min | 等待60秒 |
| 429 | `PROVIDER_RATE_LIMITED` | LLM服务商限流 | LLM API返回429 | 自动重试（Key池切换） |
| 429 | `LICENSE_ACTIVATE_TOO_FREQUENT` | 激活请求过于频繁 | 同license_key>5次/小时 | 等待1小时 |

#### 11.2.5 Key池类错误 (503)

| HTTP | error.code | message | 触发条件 | 客户端处理 |
|------|-----------|---------|----------|------------|
| 503 | `NO_AVAILABLE_KEY` | AI服务暂时不可用 | 所有Key不可用 | 等待60秒重试 |
| 503 | `ALL_KEYS_CIRCUIT_OPEN` | 所有Key已熔断 | 所有Key熔断中 | 等待5分钟重试 |
| 503 | `KEY_POOL_DEGRADED` | Key池降级运行 | 部分Key不可用 | 正常使用（已自动切换） |

#### 11.2.6 中继类错误 (503)

| HTTP | error.code | message | 触发条件 | 客户端处理 |
|------|-----------|---------|----------|------------|
| 503 | `LOCAL_SERVICE_DISCONNECTED` | 本地服务未连接 | 无活跃WSS连接 | 检查本地Docker |
| 503 | `LOCAL_SERVICE_TIMEOUT` | 本地服务响应超时 | 30s无响应 | 重试 |
| 503 | `RELAY_SESSION_EXPIRED` | 中继会话已过期 | session过期 | 重新建立连接 |

#### 11.2.7 上游服务错误 (502/504)

| HTTP | error.code | message | 触发条件 | 客户端处理 |
|------|-----------|---------|----------|------------|
| 502 | `UPSTREAM_ERROR` | 上游服务错误 | LLM API 5xx | 自动重试 |
| 504 | `UPSTREAM_TIMEOUT` | 上游服务超时 | LLM API 30s超时 | 自动重试 |
| 502 | `UPSTREAM_NETWORK_ERROR` | 上游网络错误 | 连接LLM API失败 | 自动重试 |

#### 11.2.8 请求校验错误 (400)

| HTTP | error.code | message | 触发条件 | 客户端处理 |
|------|-----------|---------|----------|------------|
| 400 | `VALIDATION_ERROR` | 请求参数错误 | 字段校验失败 | 修正参数 |
| 400 | `INVALID_LICENSE_KEY_FORMAT` | 许可证Key格式错误 | 格式不匹配 | 检查Key格式 |
| 400 | `INVALID_DEVICE_FINGERPRINT` | 设备指纹格式错误 | 格式不匹配 | 检查指纹格式 |
| 400 | `INVALID_AUDIO_FORMAT` | 音频格式不支持 | 非mp3/wav/m4a | 转换格式 |
| 400 | `AUDIO_TOO_LARGE` | 音频文件过大 | >25MB | 压缩音频 |
| 400 | `AUDIO_DURATION_INVALID` | 音频时长无效 | <5s或>60s | 重新录制 |
| 400 | `INVALID_IMAGE_FORMAT` | 图片格式不支持 | 非jpg/png | 转换格式 |
| 400 | `IMAGE_TOO_LARGE` | 图片文件过大 | >10MB | 压缩图片 |
| 400 | `TEXT_TOO_LONG` | 文本过长 | >500字符 | 缩短文本 |

#### 11.2.9 资源不存在错误 (404)

| HTTP | error.code | message | 触发条件 | 客户端处理 |
|------|-----------|---------|----------|------------|
| 404 | `LICENSE_NOT_FOUND` | 许可证不存在 | license_key不存在 | 检查Key |
| 404 | `ROUTE_NOT_FOUND` | 路由不存在 | 路径错误 | 检查URL |
| 404 | `USER_NOT_FOUND` | 用户不存在 | user_id不存在 | 重新激活 |

#### 11.2.10 冲突错误 (409)

| HTTP | error.code | message | 触发条件 | 客户端处理 |
|------|-----------|---------|----------|------------|
| 409 | `LICENSE_ALREADY_ACTIVATED` | 许可证已被激活 | 其他用户已激活 | 联系客服 |
| 409 | `DEVICE_ALREADY_BOUND` | 设备已绑定 | 设备指纹已绑定其他许可 | 解绑或更换设备 |

#### 11.2.11 网关内部错误 (500)

| HTTP | error.code | message | 触发条件 | 客户端处理 |
|------|-----------|---------|----------|------------|
| 500 | `GATEWAY_INTERNAL_ERROR` | 网关内部错误 | 未预期异常 | 重试，联系客服 |
| 500 | `DATABASE_ERROR` | 数据库错误 | PG操作失败 | 重试 |
| 500 | `REDIS_ERROR` | 缓存错误 | Redis操作失败 | 重试 |
| 500 | `ENCRYPTION_ERROR` | 加密错误 | API Key解密失败 | 联系运维 |

#### 11.2.12 网关不可用 (503)

| HTTP | error.code | message | 触发条件 | 客户端处理 |
|------|-----------|---------|----------|------------|
| 503 | `GATEWAY_UNHEALTHY` | 网关不健康 | 关键组件不可用 | 稍后重试 |
| 503 | `GATEWAY_MAINTENANCE` | 网关维护中 | 维护模式 | 等待维护完成 |

### 11.3 错误响应示例

**配额超限**：

```json
{
  "request_id": "550e8400-e29b-41d4-a716-446655440000",
  "success": false,
  "data": null,
  "error": {
    "code": "QUOTA_EXCEEDED",
    "message": "本月AI额度已用完",
    "details": {
      "quota_type": "tokens",
      "quota_limit": 500000,
      "quota_used": 500000,
      "reset_at": "2026-07-01T00:00:00Z",
      "upgrade_url": "https://promiselink.com/upgrade"
    }
  }
}
```

**Key池不可用**：

```json
{
  "request_id": "550e8400-e29b-41d4-a716-446655440000",
  "success": false,
  "data": null,
  "error": {
    "code": "NO_AVAILABLE_KEY",
    "message": "AI服务暂时不可用，请稍后重试",
    "details": {
      "retry_after": 60,
      "alternative": "基础功能仍可用，AI功能稍后恢复",
      "incident_id": "INC-2026-06-17-001"
    }
  }
}
```

**速率限制**：

```json
{
  "request_id": "550e8400-e29b-41d4-a716-446655440000",
  "success": false,
  "data": null,
  "error": {
    "code": "RATE_LIMIT_EXCEEDED",
    "message": "请求过于频繁",
    "details": {
      "limit": 100,
      "window_seconds": 60,
      "retry_after": 45
    }
  }
}
```

响应头：

```
HTTP/1.1 429 Too Many Requests
X-RateLimit-Limit: 100
X-RateLimit-Remaining: 0
X-RateLimit-Reset: 1718037100
Retry-After: 45
```

---

## 12. 附录

### 12.1 文件结构规划

```
gateway/
├── alembic/                          # 数据库迁移
│   ├── versions/
│   └── env.py
├── sql/
│   ├── init/                         # 初始化SQL
│   │   ├── 01_schema.sql
│   │   ├── 02_indexes.sql
│   │   └── 03_seed_data.sql
│   └── migrations/                   # 手动迁移脚本
├── src/
│   ├── __init__.py
│   ├── main.py                       # FastAPI应用入口
│   ├── config.py                     # 配置加载
│   ├── dependencies.py               # 依赖注入
│   ├── middleware/                    # 中间件
│   │   ├── request_id.py
│   │   ├── jwt_auth.py
│   │   ├── license_verify.py
│   │   ├── rate_limit.py
│   │   └── audit_log.py
│   ├── api/                          # API路由
│   │   ├── v1/
│   │   │   ├── license.py            # 许可证接口
│   │   │   ├── usage.py              # 用量接口
│   │   │   ├── relay.py              # 中继接口
│   │   │   └── health.py             # 健康检查
│   │   └── admin/                    # 管理接口
│   ├── services/                     # 业务服务
│   │   ├── license_service.py
│   │   ├── billing_service.py
│   │   ├── api_key_pool.py
│   │   ├── ai_proxy.py
│   │   ├── relay_router.py
│   │   └── metrics_service.py
│   ├── models/                       # 数据模型
│   │   ├── database.py               # PG连接
│   │   ├── redis_client.py           # Redis连接
│   │   └── tables.py                 # SQLAlchemy模型
│   ├── schemas/                      # Pydantic模型
│   │   ├── license.py
│   │   ├── usage.py
│   │   ├── relay.py
│   │   └── errors.py
│   ├── core/                         # 核心工具
│   │   ├── jwt_handler.py            # JWT签发/验证
│   │   ├── crypto.py                 # 加密/解密
│   │   ├── exceptions.py             # 自定义异常
│   │   └── error_codes.py            # 错误码定义
│   └── utils/                        # 工具函数
│       ├── device_fingerprint.py
│       └── audit_logger.py
├── tests/
│   ├── unit/
│   ├── integration/
│   └── e2e/
├── nginx/
│   ├── gateway.conf
│   └── nginx.conf
├── prometheus/
│   ├── prometheus.yml
│   └── alerts.yml
├── scripts/
│   ├── backup.sh
│   ├── generate_jwt_keys.sh
│   └── seed_api_keys.py
├── secrets/                          # (gitignore)
│   ├── jwt_private_key.pem
│   └── jwt_public_key.pem
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
├── requirements-test.txt
├── .env.example
└── README.md
```

### 12.2 关键依赖清单

**文件路径**：`gateway/requirements.txt`

```
# Web框架
fastapi==0.110.0
uvicorn[standard]==0.27.0
python-multipart==0.0.9

# 数据库
sqlalchemy[asyncio]==2.0.25
asyncpg==0.29.0
alembic==1.13.1

# Redis
redis[hiredis]==5.0.1

# HTTP客户端
httpx==0.26.0

# JWT
pyjwt[crypto]==2.8.0

# 加密
cryptography==42.0.2

# 配置
pydantic-settings==2.1.0
python-dotenv==1.0.0

# 监控
prometheus-client==0.19.0
sentry-sdk[fastapi]==1.40.0

# 日志
structlog==24.1.0

# 工具
python-jose[cryptography]==3.3.0
```

### 12.3 与基础版的集成点

| 集成点 | 基础版位置 | 网关位置 | 协议 |
|--------|------------|----------|------|
| 配置项 | `src/promiselink/config.py` | `gateway/src/config.py` | 环境变量 |
| relay_client | `src/promiselink/services/relay_client.py` (Phase 1) | `gateway/src/services/relay_router.py` | WSS |
| AI调用 | `src/promiselink/services/llm_client.py` (改造) | `gateway/src/services/ai_proxy.py` | HTTPS |
| 媒体服务 | `src/promiselink/services/{asr,tts,ocr}_service.py` | `gateway/src/api/v1/relay.py` | HTTPS |

### 12.4 性能基线（Phase 0验收）

| 指标 | 目标 | 验证方法 |
|------|------|----------|
| 网关健康检查延迟 | < 100ms | GET /api/v1/pro/health |
| JWT验证延迟 | < 10ms | 1000次验证平均 |
| Key池选择延迟 | < 5ms | 1000次选择平均 |
| LLM代理额外延迟 | < 200ms | 网关延迟 - 直连LLM延迟 |
| WSS连接建立 | < 500ms | 握手完成时间 |
| 中继请求转发延迟 | < 50ms | 网关→本地Docker往返 |
| 网关QPS | > 100 | Locust压测 |
| 并发WSS连接 | > 500 | 压测 |

### 12.5 Phase 0 验收检查清单

- [ ] 网关Docker Compose可启动，所有容器健康
- [ ] PG初始化SQL执行成功，表结构正确
- [ ] Redis AOF持久化启用
- [ ] Nginx TLS配置正确，HTTPS/WSS可访问
- [ ] Cloudflare DDoS防护已配置
- [ ] API Key池初始化（4个Key：2 DeepSeek + 2 Moka AI）
- [ ] POST /api/v1/pro/license/activate 激活流程通过
- [ ] POST /api/v1/pro/license/verify 验证流程通过（含设备指纹）
- [ ] GET /api/v1/pro/usage 用量查询通过
- [ ] POST /api/v1/pro/relay/llm LLM代理通过（流式+非流式）
- [ ] POST /api/v1/pro/relay/asr ASR代理通过
- [ ] POST /api/v1/pro/relay/tts TTS代理通过
- [ ] POST /api/v1/pro/relay/ocr OCR代理通过
- [ ] GET /api/v1/pro/health 健康检查通过
- [ ] Key池轮询/熔断/冷却/恢复逻辑测试通过
- [ ] JWT签发(RS256)/验证/刷新/吊销流程通过
- [ ] 用户级速率限制生效（100 req/min）
- [ ] 异常用量检测告警触发
- [ ] 红黄绿灯状态正确切换
- [ ] 配额超限返回402错误
- [ ] Prometheus指标暴露正常
- [ ] Grafana仪表盘可访问
- [ ] 告警规则配置完成
- [ ] PG备份脚本可执行
- [ ] Redis AOF备份可恢复
- [ ] CI/CD pipeline全绿
- [ ] 网关日志仅记录元数据（不记body）
- [ ] Sentry错误追踪集成
- [ ] 所有错误码按§11定义返回

### 12.6 参考文档

- `docs/spec/PRD_Pro_Edition_v1.md` v1.0 — 专业版PRD
- `docs/architecture/Pro_Edition_Architecture.md` v1.1 — 专业版架构设计（B-1/B-2/B-3已修复）
- `docs/planning/Pro_Edition_Implementation_Plan.md` v1.0 — 实现计划
- `docs/planning/Pro_Edition_Review_Report.md` — P2 Review报告（78/100）
- `docs/architecture/PromiseLink_技术设计_v1.md` §8.7 — 网关中继协议
- `docs/architecture/edition_architecture.md` — 版本对比和安全模型

### 12.7 变更记录

| 版本 | 日期 | 变更内容 |
|------|------|----------|
| v1.0 | 2026-06-17 | 初始版本，P3技术设计阶段交付，覆盖Phase 0云端AI网关全部技术设计 |
| v1.1 | 2026-06-17 | P6安全审查阻断项修复：修复5项P0阻断项（gateway端口暴露、种子数据明文Key、Redis淘汰策略、管理员接口认证、许可证激活user_id绑定），详见 §13 |

---

## 13. P6安全审查阻断项修复记录

> **审查日期**：2026-06-17
> **审查阶段**：P6 安全审查
> **阻断项数量**：5项 P0
> **修复状态**：✅ 全部修复完成

### 13.1 修复清单总览

| 编号 | 阻断项 | 风险等级 | 修复位置 | 修复状态 |
|------|--------|----------|----------|----------|
| P0-1 | gateway 8000端口对外暴露 | P0 | §10.1 docker-compose.yml | ✅ 已修复 |
| P0-2 | 种子数据SQL明文Key模式 | P0 | §10.3 03_seed_data.sql | ✅ 已修复 |
| P0-3 | Redis allkeys-lru淘汰策略可淘汰JWT黑名单 | P0 | §10.1 redis配置、§10.4 | ✅ 已修复 |
| P0-4 | 管理员接口认证机制未定义 | P0 | §6.4、§6.5（新增） | ✅ 已修复 |
| P0-5 | 许可证激活接口允许客户端任意指定user_id | P0 | §4.2、§4.3.1、§6.1 | ✅ 已修复 |

### 13.2 P0-1: gateway端口暴露

**问题**：`docker-compose.yml` 中 gateway 服务配置 `ports: - "8000:8000"`，将网关 8000 端口直接绑定到宿主机，攻击者可绕过 Nginx 的 TLS 终止、限流、WAF 防护直接访问网关。

**修复方案**：
- 删除 gateway 服务的 `ports` 配置，不再绑定宿主机端口
- gateway 仅在 `gateway_net` 内部 Docker 网络中可达
- 外部访问统一通过 Nginx 的 443 端口（HTTPS/WSS）反代至 gateway:8000
- 所有 TLS 终止、限流、IP 白名单均在 Nginx 层生效

**修复位置**：§10.1 Docker Compose 配置，gateway 服务定义

### 13.3 P0-2: 种子数据明文Key

**问题**：§10.3 种子数据 SQL 中使用 `ENC('sk-deepseek-xxx-1')` 伪代码模式，虽为占位符但易被误解为可写入真实 Key，存在 Key 泄露风险。

**修复方案**：
- 将 SQL 中的 Key 引用改为环境变量引用：`ENC(${DEEPSEEK_API_KEY_1})`
- 明确说明 `ENC(${ENV_VAR})` 为伪代码，实际由部署脚本 `seed_api_keys.py` 读取环境变量并加密
- 添加安全警告：禁止将真实 API Key 明文写入 SQL 文件
- 定义 Key 加载与加密流程：环境变量注入 → 部署脚本加密 → 运行时解密
- 列出禁止行为清单（硬编码、提交.env、日志输出Key等）

**修复位置**：§10.3 数据库初始化，03_seed_data.sql

### 13.4 P0-3: Redis淘汰策略

**问题**：Redis 配置 `maxmemory-policy allkeys-lru`，内存不足时会淘汰任意 Key（包括无 TTL 的持久化数据），可能导致 JWT 黑名单（`jwt_blacklist:{jti}`）被淘汰，使已吊销的 JWT 重新生效。

**修复方案**：
- 将 `maxmemory-policy` 从 `allkeys-lru` 改为 `volatile-lru`
- `volatile-lru` 仅淘汰设置了 TTL 的 Key，保护无 TTL 的持久化数据
- 强制要求 JWT 黑名单 Key 必须设置 TTL（= JWT 剩余有效期）
- 既保证吊销机制有效，又能在 JWT 过期后自动清理黑名单

**修复位置**：§10.1 Docker Compose redis 配置、§10.4 Redis缓存配置

### 13.5 P0-4: 管理员接口认证

**问题**：§6.4 吊销流程中引用了 `/api/v1/admin/*` 管理员接口，但未定义认证机制，存在越权风险。

**修复方案**：
- 新增 §6.5 管理员认证机制章节（原§6.5顺延为§6.6）
- 定义管理员账户体系：`admin_api_key` + `admin_jwt` 双因素认证
- 管理员 API Key 存储在环境变量 `ADMIN_API_KEY`
- 管理员 JWT 使用独立签名密钥 `ADMIN_JWT_SECRET`（与用户 JWT 隔离）
- 管理员 JWT 的 `iss`/`aud` 与用户 JWT 区分
- 定义认证中间件流程（AdminAuthMiddleware）
- 定义管理员接口清单与权限范围
- 安全加固：Nginx IP 白名单、独立 CRL、短 TTL（30分钟）、严格限流、登录保护
- 新增管理员环境变量配置

**修复位置**：§6.4 吊销流程、§6.5 管理员认证机制（新增）

### 13.6 P0-5: 许可证激活user_id绑定

**问题**：§4.3.1 许可证激活接口允许客户端在请求体中传入 `user_id`，攻击者可获取他人 license_key 后用自己的 user_id 抢先绑定，导致受害者无法激活。

**修复方案**：
- 激活接口认证方式从 "API Key" 改为 "API Key + JWT"
- 用户必须先注册登录，携带已认证的 JWT
- 请求体中删除 `user_id` 字段
- `user_id` 由网关从 JWT payload 中提取（`jwt.user_id`）
- 客户端若在请求体中传入 `user_id` 则忽略并记录审计日志
- `license_key` 与 `user_id` 首次绑定时记录，不可更改
- 更新 §6.1 激活流程：新增步骤[0] JWT验证与user_id提取，步骤[4] 防抢绑校验

**修复位置**：§4.2 接口清单、§4.3.1 激活接口、§6.1 激活流程

### 13.7 修复验证检查清单

- [ ] P0-1: 确认 gateway 服务无 `ports` 配置，仅 Nginx 暴露 443
- [ ] P0-1: 确认从宿主机无法直接访问 `localhost:8000`
- [ ] P0-2: 确认 03_seed_data.sql 中无明文 Key
- [ ] P0-2: 确认 seed_api_keys.py 从环境变量读取 Key
- [ ] P0-2: 确认 .env 在 .gitignore 中
- [ ] P0-3: 确认 Redis 配置为 `volatile-lru`
- [ ] P0-3: 确认 JWT 黑名单 Key 写入时设置 TTL
- [ ] P0-4: 确认 /api/v1/admin/* 路径需双因素认证
- [ ] P0-4: 确认 Nginx 对 admin 路径配置 IP 白名单
- [ ] P0-4: 确认管理员 JWT 使用独立签名密钥
- [ ] P0-5: 确认激活接口请求体无 user_id 字段
- [ ] P0-5: 确认 user_id 从 JWT 提取
- [ ] P0-5: 确认 license_key 绑定后不可更改

---

*文档结束 | PromiseLink专业版Phase 0技术设计 v1.1 | P3技术设计阶段 | P6安全审查阻断项已修复*
