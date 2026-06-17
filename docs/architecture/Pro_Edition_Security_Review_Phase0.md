# PromiseLink 专业版 Phase 0 云端AI网关 — P6 安全审查报告

> **审查 ID**: PRO-GW-SEC-REVIEW-001
> **审查时间**: 2026-06-17
> **审查对象**: `docs/architecture/Pro_Edition_Tech_Design_Phase0.md` v1.0 (P3 技术设计)
> **审查范围**: Phase 0 云端AI网关全部组件（API Key池、许可验证、用量计费、中继、AI代理、数据层、部署）
> **生命周期阶段**: P6 安全审查 (Gate: P0 阻断项清零方可进入 P7 实现)
> **审查方法**: STRIDE 威胁建模 + OWASP Top 10 (2021) + 关键机制深审 + 合规审查
> **基础版版本**: v0.5.4 (成熟度 92/100)

---

## 0. 审查摘要

| 维度 | 结论 |
|------|------|
| **总体评价** | ⚠️ **有条件通过** (Conditional Pass) |
| **P0 阻断项** | **5 项** (必须修复后方可进入 P7) |
| **P1 风险项** | **12 项** (应在 P7 实现阶段修复) |
| **P2 建议项** | **9 项** (建议在 Phase 0 验收前修复) |
| **生命周期判定** | P6 安全审查 **有条件通过** → 修复 5 项 P0 阻断项后进入 P7 实现阶段 |

### 审查结论一句话

技术设计整体安全意识较强（RS256+设备指纹+CRL+数据最小化），但在**网络边界暴露、密钥管理实践、Redis 淘汰策略、管理员认证、许可证激活越权**五个方面存在 P0 级真实可利用安全问题，必须修复后方可进入实现阶段。

---

## 1. 威胁建模 (STRIDE)

### 1.1 STRIDE 分析总览

| 组件 | S 仿冒 | T 篡改 | R 抵赖 | I 信息泄露 | D 拒绝服务 | E 权限提升 |
|------|--------|--------|--------|------------|------------|------------|
| Cloudflare/Nginx | 🟢 | 🟢 | 🟡 | 🟡 | 🟢 | 🟢 |
| FastAPI 网关核心 | 🔴 | 🟡 | 🟡 | 🔴 | 🔴 | 🔴 |
| LicenseService | 🔴 | 🟡 | 🟡 | 🟢 | 🟡 | 🔴 |
| APIKeyPool | 🟡 | 🟢 | 🟢 | 🔴 | 🟡 | 🟢 |
| BillingService | 🟢 | 🟡 | 🔴 | 🟢 | 🟡 | 🟡 |
| RelayRouter (WSS) | 🟡 | 🟢 | 🟢 | 🟡 | 🟡 | 🟢 |
| AIProxy (SSE) | 🟢 | 🟢 | 🟢 | 🟡 | 🟡 | 🟢 |
| PostgreSQL | 🟢 | 🟡 | 🔴 | 🟡 | 🟡 | 🟡 |
| Redis | 🟡 | 🟡 | 🟢 | 🟢 | 🔴 | 🟡 |

图例: 🔴 高风险 / 🟡 中风险 / 🟢 低风险或已有缓解

### 1.2 Spoofing (仿冒) 详细分析

#### S-1 [P0] 网关 8000 端口对外暴露，可绕过 Nginx 全部前置防护

**证据**:
- `docker-compose.yml` 第 2090-2091 行: `ports: - "8000:8000"` 将 FastAPI 直接绑定到所有网络接口
- Nginx 提供的 TLS 终止、`limit_req` 限流(200 req/min)、`limit_conn`(50 连接/IP)、HSTS 全部位于 443 端口前置

**攻击路径**:
1. 攻击者直接访问 `http://<vps-ip>:8000/api/v1/pro/relay/llm`
2. 绕过 Nginx IP 级限流、连接数限制
3. 绕过 Cloudflare DDoS 防护
4. 直接对 FastAPI 发起高频请求，耗尽 Key 池 RPM/TPM 配额
5. 由于是 HTTP 明文，可在网络路径上窃取 JWT

**影响**: 绕过所有网络层防护，DoS + 凭证窃取

#### S-2 [P0] 许可证激活接口允许客户端任意指定 user_id

**证据**:
- §4.3.1 `POST /api/v1/pro/license/activate` 请求体包含 `user_id` 字段，由客户端提供
- §6.1 激活流程步骤 4 仅检查 `user_id IS NOT NULL AND user_id != 请求user_id`，未验证 user_id 的归属

**攻击路径**:
1. 攻击者获取他人泄漏的 `license_key`（如截图、分享）
2. 攻击者构造请求 `{license_key: "PL-PRO-xxxx", user_id: "u_attacker", device_fingerprint: "sha256:..."}`
3. 网关检查 `user_id IS NULL`（首次激活）→ 绑定攻击者的 user_id
4. 攻击者获得 JWT，合法用户反被锁定

**影响**: 许可证盗用、合法用户被抢占

#### S-3 [P1] 设备指纹由客户端生成，网关无法验证真实性

**证据**:
- §4.3.1 设备指纹格式 `^sha256:[a-f0-9]{64}$`，客户端任意生成即可
- §6.2 验证流程步骤 6 比较 `device_fingerprint != JWT中的device_fingerprint`，但两者都可由持有 JWT 的攻击者同时提供

**攻击路径**:
1. 攻击者窃取他人 JWT（如通过中间人、日志泄露）
2. 攻击者同时伪造 `X-Device-Fingerprint` 头匹配 JWT 中的指纹
3. 设备绑定形同虚设

**影响**: 设备绑定机制可被绕过，防破解能力下降

#### S-4 [P1] X-API-Key 预共享密钥机制不明

**证据**:
- §4.1.2 "API Key：通过 X-API-Key 头传递，网关侧预共享密钥"
- 文档未说明: 是否所有客户端共享同一 API Key？如何分发？如何轮换？

**风险**: 若所有客户端共享同一 API Key，一旦泄露（反编译小程序即可获取），任何人可仿冒客户端

#### S-5 [P1] JWT 算法混淆攻击未明确防护

**证据**:
- §6.2 验证流程步骤 2 "使用RSA公钥验证签名"，未明确强制 `alg=RS256`
- 若使用 `pyjwt` 默认行为，未指定 `algorithms=['RS256']` 时可能接受 `alg=none` 或将 RS256 公钥作为 HS256 密钥使用

**影响**: 若未强制算法，JWT 可被伪造

### 1.3 Tampering (篡改) 详细分析

#### T-1 [P1] 配额检查存在 TOCTOU 竞态

**证据**:
- §2.3.1 AI调用流程: `BillingService.check_quota()` 在请求前检查，`record_usage()` 在响应后异步记录
- §7.4 用量记录流程步骤 4 "更新许可证配额(原子操作)"，但检查与更新之间有时间差

**攻击路径**:
1. 用户剩余配额 100 Token
2. 用户并发发起 10 个请求，每个请求消耗 50 Token
3. 10 个请求同时通过 `check_quota`（都看到剩余 100）
4. 实际消耗 500 Token，超出配额 400 Token

**影响**: 配额可被绕过，AI 成本泄漏

#### T-2 [P2] 审计日志与业务数据同库，无不可篡改性

**证据**:
- §3.6.3 `audit_logs` 表与 `licenses`/`usage_records` 同在 PG gateway 库
- 备份保留仅 7 天，审计日志保留 180 天，PG 被攻破后无法恢复历史审计

**影响**: 管理员或攻击者可篡改审计日志而不留痕迹

#### T-3 [P2] Nginx 证书目录读写挂载

**证据**:
- `docker-compose.yml` 第 2188 行: `./certs:/etc/nginx/certs:ro` 证书只读 ✅
- 但 `./logs/nginx:/var/log/nginx` 读写挂载，若 Nginx 容器被攻破可篡改访问日志

### 1.4 Repudiation (抵赖) 详细分析

#### R-1 [P1] 异步记录用量可能在网关崩溃时丢失

**证据**:
- §7.4 步骤 3 "异步记录用量(不阻塞响应)"
- §8.2 SSE 流式响应中 `BillingService.record_usage(...)` 在流结束后异步执行

**攻击路径**:
1. 用户发起 LLM 调用，消耗 1000 Token
2. LLM 响应返回给用户
3. 网关在异步记录用量前崩溃
4. 用量未记录，用户实际消耗未计入配额

**影响**: 用量丢失，计费不准，可被利用进行"崩溃攻击"免费消耗 Token

#### R-2 [P1] JWT 吊销流程无法获取所有活跃 JWT 的 jti

**证据**:
- §6.4 吊销流程步骤 2 "查询 Redis ws_connections:{user_id} 获取所有活跃会话，获取会话关联的 jti 列表"
- 但 JWT 是无状态的，§6.5 JWT Payload 中有 jti，但文档未说明签发 JWT 时是否记录 jti 到服务端
- 若未记录，吊销流程无法获取所有已签发但未过期的 JWT

**影响**: 许可证吊销后，已签发的 JWT 仍可使用直至过期（最长 15 分钟）

### 1.5 Information Disclosure (信息泄露) 详细分析

#### I-1 [P0] 种子数据 SQL 中明文 API Key 模式

**证据**:
- §10.3 `03_seed_data.sql`:
  ```sql
  INSERT INTO api_key_pool (...) VALUES
  ('key-deepseek-1', 'deepseek', ENC('sk-deepseek-xxx-1'), ...);
  ```
- `ENC()` 是伪代码，实际需开发者手动加密后填入。开发者极易直接填入明文 Key 并提交到 Git

**攻击路径**:
1. 开发者按示例模式填入真实 Key `ENC('sk-real-key-here')`
2. 提交到 Git 仓库
3. Key 泄露（即使有 ENC() 包裹，实际值是明文）

**影响**: LLM API Key 泄露，直接经济损失

#### I-2 [P1] Sentry 可能捕获敏感请求体

**证据**:
- `docker-compose.yml` 第 2105 行: `SENTRY_DSN=${SENTRY_DSN}`
- `requirements.txt`: `sentry-sdk[fastapi]==1.40.0`
- 文档未说明 Sentry SDK 的 `before_send` 过滤配置

**风险**: Sentry SDK 默认可能捕获请求体，LLM prompt/响应（含业务数据）会上报到 Sentry

#### I-3 [P1] api_key_pool.last_error 字段可能泄露 Key 信息

**证据**:
- §3.3 `last_error TEXT` 存储最近错误信息
- LLM API 在 Key 无效时可能返回 `"Invalid API key: sk-deepseek-xxxx"`

**影响**: 错误信息中可能包含 Key 片段

#### I-4 [P1] Prometheus /metrics 暴露 user_id 标签

**证据**:
- §10.5.1 指标 `gateway_quota_usage_ratio` 标签含 `user_id`
- §10.5.1 指标 `gateway_rate_limit_hits_total` 标签含 `user_id`
- `/metrics` 端点未在接口清单(§4.2)中标注认证要求

**影响**: 任何访问 /metrics 的人可枚举所有 user_id 及其用量模式

#### I-5 [P2] 健康检查端点暴露运营敏感信息

**证据**:
- §4.3.8 `GET /api/v1/pro/health` 无认证，响应包含:
  - `active_keys: 3, total_keys: 4, circuit_open_count: 1` (Key 池状态)
  - `active_ws_connections: 42` (活跃用户数)
  - `requests_per_minute: 15, avg_response_ms: 850` (负载信息)

**影响**: 攻击者可侦察网关负载、Key 池规模，选择最佳攻击时机

#### I-6 [P2] Nginx access log 记录完整 URL

**证据**:
- Nginx 默认 access log 格式记录完整 URL 和 query string
- 若任何接口通过 query 传递敏感参数（如 `?license_key=...`），会记录到日志

### 1.6 Denial of Service (拒绝服务) 详细分析

#### D-1 [P0] Redis allkeys-lru 淘汰策略可淘汰 JWT 黑名单

**证据**:
- `docker-compose.yml` 第 2160 行: `--maxmemory-policy allkeys-lru`
- §3.7 Redis 数据结构中 `jwt_blacklist:{jti}` 存储吊销的 JWT，TTL=900s

**攻击路径**:
1. 网关内存压力大时，Redis 按 LRU 淘汰键
2. `jwt_blacklist:{jti}` 被淘汰
3. 已吊销的 JWT 重新生效
4. 被吊销用户（如退款用户）可继续使用

**影响**: 许可证吊销机制失效

#### D-2 [P1] WebSocket 连接耗尽

**证据**:
- §9.4.3 单 IP 50 连接限制
- 但未限制单用户的 WSS 连接数（仅 IP 维度）

**攻击路径**:
1. 攻击者使用分布式 IP（如代理池）
2. 每个 IP 建立 50 个 WSS 连接
3. 10 个 IP 即可建立 500 个连接，消耗网关内存

#### D-3 [P1] Key 池 RPM 耗尽影响其他用户

**证据**:
- §5.2 Key 池 RPM 限制 60 req/min/Key
- 用户级限流 100 req/min
- 4 个 Key 总 RPM = 240，但用户级限流总和可达 100 × N 用户

**攻击路径**:
1. 3 个恶意用户各以 100 req/min 速率调用
2. 总速率 300 req/min > Key 池总 RPM 240
3. Key 池迅速进入限流/熔断，影响合法用户

### 1.7 Elevation of Privilege (权限提升) 详细分析

#### E-1 [P0] 管理员接口认证机制未定义

**证据**:
- §6.4 吊销流程: "管理员调用内部接口 POST /api/v1/admin/license/revoke"
- §4.2 接口清单中未列出 `/api/v1/admin/*` 接口
- 文档未定义管理员账户体系、认证方式、权限分级

**攻击路径**:
1. 若管理员接口仅靠 `X-API-Key` 认证（与普通用户相同）
2. API Key 泄露（反编译小程序）= 任意用户可吊销他人许可证
3. 即使有独立管理员密钥，文档未说明其存储和分发

**影响**: 任意用户可吊销他人许可证（拒绝服务攻击）

#### E-2 [P1] 配额绕过通过 Redis 缓存不一致

**证据**:
- §7.4 步骤 6 "更新Redis缓存 HINCRBY quota:cache:{user_id}:{year_month}"
- Redis 缓存 TTL=60s，PG 是真实数据源
- 若 PG 更新失败但 Redis 已更新，数据不一致

#### E-3 [P2] users 表无角色字段

**证据**:
- §3.6.1 `users` 表仅有 `status: active/banned`，无 `role` 字段
- 管理员如何标识？若靠硬编码 user_id，不可审计

---

## 2. 安全控制审查 (OWASP Top 10 2021)

### A01 失效的访问控制 (Broken Access Control)

| # | 问题 | 严重度 | 证据位置 |
|---|------|--------|----------|
| A01-1 | gateway 8000 端口对外暴露，绕过 Nginx 访问控制 | P0 | docker-compose.yml L2090 |
| A01-2 | 管理员接口 `/api/v1/admin/*` 认证机制未定义 | P0 | §6.4, §4.2 |
| A01-3 | `POST /api/v1/pro/license/activate` 允许客户端任意指定 user_id | P0 | §4.3.1, §6.1 |
| A01-4 | `GET /api/v1/pro/usage` 未明确防 IDOR（请求者 user_id 与查询目标一致性） | P1 | §4.3.3 |
| A01-5 | `/metrics` 端点未标注认证要求，暴露 user_id 标签 | P1 | §10.5.1 |
| A01-6 | Grafana 端口 `3001:3000` 对外暴露（注释说"仅内网"但 Docker 默认对所有接口开放） | P2 | docker-compose.yml L2223 |

### A02 加密机制失效 (Cryptographic Failures)

| # | 问题 | 严重度 | 证据位置 |
|---|------|--------|----------|
| A02-1 | `03_seed_data.sql` 中 `ENC()` 伪代码，加密实现未定义，易导致明文 Key 入库 | P0 | §10.3 |
| A02-2 | `API_KEY_ENCRYPTION_KEY=your-api-key-encryption-key-32bytes` 示例非有效 32 字节密钥 | P1 | §10.2 |
| A02-3 | PG/Redis 内部通信未加密（Docker 网络内明文） | P1 | docker-compose.yml |
| A02-4 | 备份文件仅 gzip 压缩，未加密 | P1 | §10.6 backup.sh |
| A02-5 | `ssl_prefer_server_ciphers off` 允许客户端选择加密套件 | P2 | §9.1 |
| A02-6 | RSA 2048 位（NIST 建议 2030 年后升级 3072） | P2 | §9.2 |

### A03 注入 (Injection)

| # | 问题 | 严重度 | 证据位置 |
|---|------|--------|----------|
| A03-1 | SQL 注入风险低（SQLAlchemy + asyncpg 参数化）✅ | — | §3 |
| A03-2 | `audit_logs.metadata` JSONB 字段若拼接用户输入，需确认使用参数化 | P2 | §3.6.3 |
| A03-3 | `api_key_pool.last_error` 存储上游错误信息，若渲染到管理界面需转义 | P2 | §3.3 |

### A04 不安全设计 (Insecure Design)

| # | 问题 | 严重度 | 证据位置 |
|---|------|--------|----------|
| A04-1 | 设备指纹由客户端生成，网关无法验证真实性 | P1 | §4.3.1, §6.2 |
| A04-2 | refresh_token 未实现 rotation（每次刷新后旧 token 立即失效） | P1 | §6.3 |
| A04-3 | JWT 吊销流程依赖查询活跃 WSS 连接的 jti，但 JWT 无状态签发时未记录 jti | P1 | §6.4 |
| A04-4 | 配额检查与记录的 TOCTOU 竞态未用悲观锁或原子操作解决 | P1 | §7.4, §2.3.1 |
| A04-5 | WSS 连接映射 `ws_connections:{user_id}` 多设备场景未明确 | P2 | §3.7 |

### A05 安全配置错误 (Security Misconfiguration)

| # | 问题 | 严重度 | 证据位置 |
|---|------|--------|----------|
| A05-1 | Redis `allkeys-lru` 淘汰策略可淘汰 JWT 黑名单 | P0 | docker-compose.yml L2160 |
| A05-2 | gateway 8000 端口对外暴露 | P0 | docker-compose.yml L2090 |
| A05-3 | `latest` Docker 标签（prometheus/grafana/nginx）可能引入漏洞版本 | P2 | docker-compose.yml |
| A05-4 | `python-jose` 与 `pyjwt` 两个 JWT 库共存，易造成混淆 | P2 | requirements.txt |
| A05-5 | 备份脚本 `redis-cli -a ${REDIS_PASSWORD}` 在进程列表暴露密码 | P2 | §10.6 |

### A06 脆弱和过时的组件 (Vulnerable and Outdated Components)

| # | 问题 | 严重度 | 证据位置 |
|---|------|--------|----------|
| A06-1 | `prom/prometheus:latest`、`grafana/grafana:latest`、`nginx:alpine` 使用 latest 标签 | P2 | docker-compose.yml |
| A06-2 | 依赖版本固定 ✅，但需建立定期漏洞扫描机制 | P2 | requirements.txt |

### A07 身份验证失败 (Identification and Authentication Failures)

| # | 问题 | 严重度 | 证据位置 |
|---|------|--------|----------|
| A07-1 | JWT 验证未明确强制 `alg=RS256`，存在算法混淆风险 | P1 | §6.2 |
| A07-2 | JWT 验证未明确检查 `iss` 和 `aud` 字段 | P1 | §6.2 |
| A07-3 | license_key 激活无 CAPTCHA，5次/小时阈值仍允许长期暴力枚举 | P2 | §11.2.4 |
| A07-4 | refresh_token 7天 TTL 但无 rotation | P1 | §6.3 |
| A07-5 | `X-API-Key` 分发与轮换机制未定义 | P1 | §4.1.2 |

### A08 软件和数据完整性失败 (Software and Data Integrity Failures)

| # | 问题 | 严重度 | 证据位置 |
|---|------|--------|----------|
| A08-1 | CI/CD 部署未提及镜像签名验证 | P2 | §10.7 |
| A08-2 | `03_seed_data.sql` 完整性未验证（文件被篡改可注入恶意 Key） | P1 | §10.3 |
| A08-3 | 备份脚本未验证备份完整性（无校验和） | P2 | §10.6 |

### A09 安全日志和监控失败 (Security Logging and Monitoring Failures)

| # | 问题 | 严重度 | 证据位置 |
|---|------|--------|----------|
| A09-1 | 审计日志与业务数据同库，无 WORM/不可篡改性 | P1 | §3.6.3 |
| A09-2 | 审计日志保留 180 天，但备份仅 7 天，PG 被攻破后历史审计无法恢复 | P1 | §3.1, §10.6 |
| A09-3 | Sentry `before_send` 过滤配置未定义 | P1 | docker-compose.yml |
| A09-4 | 登录失败告警阈值未定义（如 5 次/分钟触发告警） | P2 | §9.5 |

### A10 服务端请求伪造 (SSRF)

| # | 问题 | 严重度 | 证据位置 |
|---|------|--------|----------|
| A10-1 | `api_key_pool.base_url` 由管理员配置，若管理员接口被攻破可改为内部地址 | P1 | §3.3 |
| A10-2 | `POST /api/v1/pro/relay/llm` 中 `model` 字段用户可控，若用于构造 URL 有 SSRF 风险 | P2 | §4.3.4 |
| A10-3 | RelayRouter 转发至本地 Docker，`payload.path` 用户可控，需确认白名单 | P1 | §8.5.2 |

---

## 3. 关键安全机制审查

### 3.1 JWT RS256 签名实现

| 审查项 | 状态 | 说明 |
|--------|------|------|
| 非对称签名 RS256 | ✅ 合规 | 私钥签发，公钥验证 |
| 私钥存储 | ✅ Docker Secret 挂载 | 不进入镜像层 |
| 短 TTL (15分钟) | ✅ 合规 | 降低泄露窗口 |
| jti 唯一标识 | ✅ 合规 | 用于 CRL 吊销 |
| **强制 alg=RS256** | ⚠️ **未明确** | §6.2 未说明验证时指定 `algorithms=['RS256']` |
| **验证 iss/aud** | ⚠️ **未明确** | Payload 含 iss/aud 但验证流程未提及检查 |
| **jti 服务端记录** | ❌ **缺失** | 吊销流程无法获取所有活跃 JWT 的 jti |
| RSA 密钥长度 | ⚠️ 2048 位 | NIST 建议 2030 年后升级 3072 |
| 密钥轮换 | ✅ 90天 | §9.2 |

**结论**: RS256 选型正确，但验证实现细节缺失三项关键检查（alg/iss/aud），且 jti 未服务端记录导致吊销机制存在缺口。

### 3.2 API Key 池管理安全性

| 审查项 | 状态 | 说明 |
|--------|------|------|
| Key 加密存储 | ✅ AES-256-GCM | §3.3 `api_key_encrypted` |
| 加权轮询 | ✅ 合理 | §5.2 |
| 健康检查+熔断 | ✅ 完备 | §5.3-5.5 |
| **Key 存储位置冗余** | ⚠️ **风险** | 同时存在于环境变量(L2100-2103)和 PG，增加泄露面 |
| **种子数据明文模式** | ❌ **P0** | §10.3 `ENC('sk-xxx')` 伪代码易致明文入库 |
| **last_error 泄露** | ⚠️ **风险** | 可能含 Key 片段 |
| **备份含加密 Key** | ⚠️ **风险** | 备份未加密，离线破解风险 |
| Key 轮换策略 | ❌ **缺失** | §9.2 提到加密密钥轮换，但 LLM API Key 本身无轮换计划 |

**结论**: Key 池算法设计完备，但密钥管理实践存在 P0 问题（种子数据明文模式）和多个 P1 风险。

### 3.3 设备指纹绑定安全性

| 审查项 | 状态 | 说明 |
|--------|------|------|
| 指纹格式校验 | ✅ `^sha256:[a-f0-9]{64}$` | §4.3.1 |
| **指纹生成方** | ❌ **客户端生成** | 网关无法验证真实性 |
| **指纹传输** | ⚠️ **HTTP 头** | `X-Device-Fingerprint` 头，与 JWT 中指纹比较，窃取 JWT 即可绕过 |
| max_devices 限制 | ✅ 默认 1 | §3.2 |
| **解绑/重绑机制** | ❌ **未定义** | 攻击者可解绑他人设备后绑定自己 |
| 指纹算法透明度 | ⚠️ 未说明采集哪些硬件特征 | 可能为 MAC 地址等易伪造特征 |

**结论**: 设备指纹机制设计存在根本缺陷——客户端生成 + HTTP 头传输，无法真正防破解。建议改为网关下发 nonce + 客户端用硬件特征签名返回的挑战-响应机制。

### 3.4 CRL 黑名单实现安全性

| 审查项 | 状态 | 说明 |
|--------|------|------|
| Redis 实现 | ✅ `jwt_blacklist:{jti}` | §3.7 |
| TTL 设置 | ✅ JWT 剩余有效期 | 自动清理 |
| **Redis 淘汰策略** | ❌ **P0** | `allkeys-lru` 可淘汰黑名单条目 |
| **jti 可枚举性** | ❌ **缺失** | 吊销流程无法获取所有活跃 JWT 的 jti |
| 吊销时效 | ⚠️ 最长 15 分钟 | 依赖 jti 记录，若缺失则无法立即吊销 |

**结论**: CRL 机制因 Redis 淘汰策略和 jti 记录缺失两个问题，无法保证吊销的即时性和可靠性。

### 3.5 SSE 流式响应安全性

| 审查项 | 状态 | 说明 |
|--------|------|------|
| Content-Type 设置 | ✅ `text/event-stream` | §8.2 |
| 禁用 Nginx 缓冲 | ⚠️ `X-Accel-Buffering: no` | 未同时设置 `proxy_buffering off` |
| **客户端断开处理** | ❌ **未定义** | 客户端断开后网关是否取消上游 LLM 请求？否则浪费 Token |
| **错误事件泄露** | ⚠️ **风险** | SSE `error` 事件可能含上游 LLM 错误详情 |
| 超时处理 | ✅ 30s | §8.3 |

### 3.6 速率限制绕过风险

| 审查项 | 状态 | 说明 |
|--------|------|------|
| 用户级限流 | ✅ 100 req/min | §9.4.1 |
| IP 级限流 | ✅ 200 req/min (Nginx) | §9.4.1 |
| **绕过 Nginx** | ❌ **P0** | 8000 端口暴露可直接访问 FastAPI |
| **Redis 故障 fail-open** | ⚠️ **风险** | Redis 故障时限流计数器失效，应 fail-closed |
| 滑动窗口实现 | ⚠️ 固定窗口 | `rate_limit:{user_id}:{minute}` 是固定窗口，临界点可 2x 突发 |

### 3.7 SQL 注入防护

| 审查项 | 状态 | 说明 |
|--------|------|------|
| ORM 使用 | ✅ SQLAlchemy + asyncpg | 参数化查询 |
| **动态查询审计** | ⚠️ **需确认** | 文档未展示具体查询代码，需确认无字符串拼接 |
| JSONB 字段 | ⚠️ 需确认 | `audit_logs.metadata` 若拼接需参数化 |

### 3.8 Redis 安全配置

| 审查项 | 状态 | 说明 |
|--------|------|------|
| 密码认证 | ✅ `requirepass` | docker-compose.yml |
| **TLS** | ❌ **缺失** | 内部通信明文 |
| **淘汰策略** | ❌ **P0** | `allkeys-lru` 可淘汰 JWT 黑名单 |
| AOF 持久化 | ✅ `appendonly yes` | §10.4 |
| **密码暴露** | ⚠️ **风险** | `redis-cli -a ${REDIS_PASSWORD}` 进程列表可见 |
| maxmemory | ✅ 512mb | §10.4 |
| 网络隔离 | ⚠️ 未配置 | Redis 端口未在 docker-compose 中暴露 ✅，但未明确 network 隔离 |

---

## 4. 数据安全审查

### 4.1 用户数据在网关的暴露面

| 数据项 | 存储位置 | 敏感度 | 保护措施 | 问题 |
|--------|----------|--------|----------|------|
| user_id | PG users, licenses, usage_records | 中 | — | 元数据，可接受 |
| wechat_openid | PG users | 高 | 明文存储 | ⚠️ 未加密 |
| email | PG users | 高 | 明文存储 | ⚠️ 未加密 |
| client_ip | PG relay_sessions | 中 | 明文存储 | 可接受（审计需要） |
| user_agent | PG relay_sessions | 低 | 明文存储 | 可接受 |
| license_key | PG licenses, JWT | 中 | 明文存储 | 可接受（凭证） |
| device_fingerprint | PG licenses, JWT | 中 | 明文存储 | 可接受 |
| **LLM prompt/响应** | ❌ 不存储 | 高 | 仅过内存 | ✅ 合规 |
| **音频/图片内容** | ❌ 不存储 | 高 | 仅过内存 | ✅ 合规 |
| **API Key (LLM)** | PG api_key_pool | 极高 | AES-256-GCM | ⚠️ 种子数据明文模式 |

### 4.2 LLM Provider 数据使用风险

| Provider | 数据留存 | 训练用途 | 数据驻留 | 风险 |
|----------|----------|----------|----------|------|
| DeepSeek | 不留存 ✅ | 不训练 ✅ | 中国大陆 ✅ | 低 |
| Moka AI | 不留存 ✅ | 不训练 ✅ | 中国大陆 ✅ | 低 |
| OpenAI (备选) | 30天留存 ⚠️ | 不训练 ✅ | 美国 ⚠️ | 中（跨境） |
| Anthropic (备选) | 30天留存 ⚠️ | 不训练 ✅ | 美国 ⚠️ | 中（跨境） |

**问题**: Provider 数据政策仅依赖厂商声明，无技术保证。建议在用户协议中明确"数据政策以 Provider 最新声明为准"。

### 4.3 日志中敏感数据保护

| 日志类型 | 记录内容 | 敏感数据保护 | 问题 |
|----------|----------|--------------|------|
| 网关应用日志 | 元数据 only | ✅ 不记 body | 合规 |
| Nginx access log | URL, IP, UA | ⚠️ 记录完整 URL | query 参数可能含敏感数据 |
| PG 慢查询日志 | SQL 语句 | ⚠️ 可能含参数值 | 需确认 `log_min_duration_statement` |
| Sentry | 异常堆栈 | ❌ 未定义过滤 | 可能捕获请求体 |
| Docker 容器日志 | stdout/stderr | ⚠️ 可能含敏感信息 | 需审查应用日志输出 |

### 4.4 数据库加密 (at rest)

| 维度 | 状态 | 说明 |
|------|------|------|
| PG 透明数据加密 (TDE) | ❌ 未配置 | 依赖 VPS 磁盘加密 |
| 备份文件加密 | ❌ 仅 gzip | 备份泄露即数据泄露 |
| VPS 磁盘加密 | ⚠️ 未明确 | 文档未提及 |
| 字段级加密 | ✅ API Key | AES-256-GCM |

### 4.5 传输加密 (in transit)

| 链路 | 加密 | 问题 |
|------|------|------|
| 客户端 ↔ Cloudflare | TLS 1.3 ✅ | — |
| Cloudflare ↔ Nginx | TLS ✅ | 需确认 Full (Strict) 模式 |
| Nginx ↔ FastAPI | HTTP ❌ | 本地回环，可接受但建议 mTLS |
| FastAPI ↔ PG | 未加密 ❌ | Docker 网络内明文 |
| FastAPI ↔ Redis | 未加密 ❌ | Docker 网络内明文 |
| FastAPI ↔ LLM API | HTTPS ✅ | — |

---

## 5. 合规审查

### 5.1 AGPL v3 许可证合规

| 审查项 | 状态 | 说明 |
|--------|------|------|
| Open Core 模型 | ✅ 合规 | 基础版开源，网关闭源独立服务 |
| **relay_client 许可证** | ⚠️ **需确认** | relay_client 随基础版 AGPL v3，但调用网关 API 是否触发传染？ |
| **小程序 WebView** | ⚠️ **需确认** | 专业版小程序嵌入基础版 H5（WebView），是否触发 AGPL？ |
| 网关 API 协议 | ⚠️ **需法律确认** | API 协议是否属于 AGPL 传染范围 |

**建议**: 由法律顾问确认 AGPL v3 在网络服务场景下的传染边界，特别是 relay_client 和 WebView 嵌入场景。

### 5.2 个人信息保护法 (PIPL) 合规

| 审查项 | 状态 | 说明 |
|--------|------|------|
| 个人信息收集 | ⚠️ | 收集 user_id, openid, email, IP, UA |
| **数据控制者/处理者角色** | ❌ **未明确** | PromiseLink 是控制者还是处理者？ |
| **知情同意机制** | ⚠️ | 隐私协议有第三方 AI 披露，但未提及 PIPL 专项同意 |
| **撤回同意机制** | ⚠️ | 提到 GDPR 端点，但 PIPL 有不同要求 |
| **数据本地化** | ✅ | 首选 Provider 数据驻留中国大陆 |
| **跨境传输** | ⚠️ | 备选 Provider (OpenAI/Anthropic) 涉及跨境，需安全评估 |
| **个人信息影响评估 (PIA)** | ❌ **未执行** | 处理个人信息应事先评估 |
| **数据泄露通知** | ❌ **未定义** | PIPL 要求泄露时通知用户和监管机构 |

### 5.3 数据本地化要求

| 数据类型 | 存储位置 | 合规 |
|----------|----------|------|
| 用户账户 (PG) | VPS（位置未明确） | ⚠️ 需确认在中国大陆 |
| LLM 调用 (DeepSeek/Moka) | 中国大陆 | ✅ |
| 备选 LLM (OpenAI/Anthropic) | 美国 | ⚠️ 跨境传输需安全评估 |
| 备份文件 | VPS 本地 | ⚠️ 需确认 VPS 位置 |

### 5.4 用户知情同意

| 审查项 | 状态 | 说明 |
|--------|------|------|
| 隐私协议 | ✅ | 含第三方 AI 披露条款 |
| **激活时弹窗同意** | ⚠️ **未明确** | 文档未描述激活流程的同意交互 |
| **未成年人保护** | ❌ **未提及** | PIPL 要求处理未成年人信息需监护人同意 |
| Cookie/追踪 | ✅ | 小程序场景不涉及 |

---

## 6. 安全测试计划

### 6.1 渗透测试场景

| # | 场景 | 目标 | 预期结果 |
|---|------|------|----------|
| PT-1 | 直接访问 8000 端口绕过 Nginx | 验证 A01-1 | 应被拒绝（端口不对外） |
| PT-2 | 伪造 user_id 激活他人 license_key | 验证 S-2 | 应被拒绝（user_id 需服务端生成） |
| PT-3 | JWT 算法混淆攻击 (alg=none/HS256) | 验证 S-5 | 应被拒绝（强制 RS256） |
| PT-4 | 并发请求绕过配额检查 | 验证 T-1 | 应被拒绝（原子操作） |
| PT-5 | Redis 内存压力下 JWT 黑名单淘汰 | 验证 D-1 | 黑名单不被淘汰（volatile-lru 或独立实例） |
| PT-6 | 管理员接口无认证访问 | 验证 E-1 | 应被拒绝（独立管理员认证） |
| PT-7 | 伪造设备指纹绕过绑定 | 验证 S-3 | 评估实际风险 |
| PT-8 | SSE 客户端断开后上游请求是否取消 | 验证 §3.5 | 应取消（节省 Token） |
| PT-9 | WSS 多设备连接场景 | 验证 A04-5 | 应有明确行为 |
| PT-10 | /metrics 端点未授权访问 | 验证 I-4 | 应需认证或移除 user_id 标签 |

### 6.2 安全自动化测试用例

```python
# tests/security/test_gateway_security.py (建议结构)

class TestGatewaySecurity:
    """P6 安全审查要求的自动化测试"""
    
    # P0 阻断项测试
    def test_port_8000_not_exposed(self):
        """PT-1: 8000 端口不应对外暴露"""
        # 验证 docker-compose 中 ports 配置
    
    def test_activate_license_rejects_client_user_id(self):
        """PT-2: 激活接口应拒绝客户端指定的 user_id"""
        # user_id 应由服务端从认证上下文生成
    
    def test_jwt_rejects_alg_none(self):
        """PT-3: JWT 应拒绝 alg=none"""
        # 构造 alg=none 的 JWT，验证被拒绝
    
    def test_jwt_rejects_hs256_with_rsa_key(self):
        """PT-3: JWT 应拒绝 HS256 算法混淆"""
        # 用 RSA 公钥作为 HS256 密钥签名，验证被拒绝
    
    def test_concurrent_quota_check_atomic(self):
        """PT-4: 并发配额检查应原子"""
        # 并发 10 个请求，验证不超额
    
    def test_jwt_blacklist_not_evicted(self):
        """PT-5: JWT 黑名单不应被 LRU 淘汰"""
        # 填充 Redis 至 maxmemory，验证 jwt_blacklist 仍存在
    
    def test_admin_endpoint_requires_admin_auth(self):
        """PT-6: 管理员接口需独立认证"""
        # 用普通 API Key 访问，验证被拒绝
    
    # P1 风险项测试
    def test_refresh_token_rotation(self):
        """验证 refresh_token rotation"""
        # 刷新后旧 refresh_token 应立即失效
    
    def test_jwt_validates_iss_aud(self):
        """验证 JWT 检查 iss 和 aud"""
    
    def test_sse_client_disconnect_cancels_upstream(self):
        """PT-8: 客户端断开应取消上游请求"""
    
    def test_metrics_requires_auth(self):
        """PT-10: /metrics 需认证"""
    
    def test_seed_data_no_plaintext_key(self):
        """验证种子数据无明文 Key"""
    
    def test_sentry_before_send_filters_body(self):
        """验证 Sentry 过滤请求体"""
    
    def test_backup_encrypted(self):
        """验证备份文件加密"""
```

### 6.3 安全监控告警规则

| 告警名 | 条件 | 严重度 | 通知方式 |
|--------|------|--------|----------|
| Port8000AccessDetected | 8000 端口收到非本地请求 | Critical | 钉钉+电话 |
| JwtAlgConfusionAttempt | JWT 验证失败且 alg != RS256 | Critical | 钉钉 |
| LicenseActivateUseridMismatch | 激活时 user_id 与认证上下文不一致 | Critical | 钉钉+电话 |
| QuotaBypassDetected | 单次请求后配额超限 > 10% | Critical | 钉钉 |
| JwtBlacklistMiss | 已吊销 JWT 验证通过 | Critical | 钉钉+电话 |
| AdminEndpointAuthFailed | 管理员接口认证失败 > 3次/min | Warning | 钉钉 |
| RefreshTokenReuseDetected | 旧 refresh_token 被使用 | Warning | 钉钉 |
| MetricsUnauthorizedAccess | /metrics 无认证访问 | Warning | 钉钉 |
| SentrySensitiveDataLeak | Sentry 上报含 request_body | Critical | 钉钉+电话 |
| RedisMemoryNearLimit | Redis 内存 > 90% | Warning | 钉钉 |
| KeyPoolAllCircuitOpen | 所有 Key 熔断 | Critical | 钉钉+电话 |
| AbnormalLicenseActivate | 单 IP 激活 > 5次/小时 | Warning | 钉钉 |

---

## 7. 风险评估

### 7.1 P0 风险（必须修复，阻断 P7 进入）

| # | 风险 | OWASP | 影响 | 修复建议 |
|---|------|-------|------|----------|
| **P0-1** | gateway 8000 端口对外暴露，绕过 Nginx 全部防护 | A01 | 绕过 TLS/限流/DDoS防护，凭证窃取 | `docker-compose.yml` 改为 `expose: - "8000"` 或 `ports: - "127.0.0.1:8000:8000"` |
| **P0-2** | 种子数据 SQL 中 `ENC()` 伪代码易致明文 Key 入库 | A02 | LLM API Key 泄露 | 提供独立的 `seed_api_keys.py` 脚本，运行时加密后写入 PG，SQL 文件不含 Key |
| **P0-3** | Redis `allkeys-lru` 淘汰策略可淘汰 JWT 黑名单 | A05 | 已吊销 JWT 重新生效 | 改为 `volatile-lru`（仅淘汰带 TTL 的键），或将 JWT 黑名单存独立 Redis 实例 |
| **P0-4** | 管理员接口 `/api/v1/admin/*` 认证机制未定义 | A01 | 任意用户可吊销他人许可证 | 定义独立管理员账户体系（独立密钥/IP白名单/mTLS），文档化认证流程 |
| **P0-5** | 许可证激活接口允许客户端任意指定 user_id | A01 | 许可证盗用 | user_id 应由服务端从认证上下文生成，不接受客户端传入 |

### 7.2 P1 风险（应该修复，P7 实现阶段完成）

| # | 风险 | OWASP | 影响 | 修复建议 |
|---|------|-------|------|----------|
| **P1-1** | JWT 验证未明确强制 alg/iss/aud | A07 | JWT 伪造 | 验证时显式指定 `algorithms=['RS256']`，检查 iss/aud |
| **P1-2** | refresh_token 未实现 rotation | A07 | Token 泄露后持续可用 | 每次刷新后旧 refresh_token 加入 CRL |
| **P1-3** | 设备指纹客户端生成，无法验证真实性 | A04 | 防破解机制失效 | 改为挑战-响应机制或接受风险并文档化 |
| **P1-4** | 配额检查 TOCTOU 竞态 | A04 | 配额绕过 | 使用 `SELECT ... FOR UPDATE` 或 Redis 原子计数 |
| **P1-5** | JWT 吊销流程无法获取所有活跃 jti | A04 | 吊销不即时 | 签发 JWT 时记录 jti 到 Redis（TTL=JWT TTL） |
| **P1-6** | Sentry 可能捕获请求体 | A09 | 业务数据泄露 | 配置 `before_send` 过滤 request_body |
| **P1-7** | /metrics 暴露 user_id 标签 | A01 | 用户枚举 | /metrics 加认证，或移除 user_id 标签改用 hash |
| **P1-8** | 审计日志与业务同库无不可篡改性 | A09 | 审计日志可篡改 | 独立日志服务器或 WORM 存储 |
| **P1-9** | 备份文件未加密 | A02 | 备份泄露即数据泄露 | 备份脚本增加 GPG/age 加密 |
| **P1-10** | PG/Redis 内部通信未加密 | A02 | Docker 网络嗅探 | 配置 PG/Redis TLS 或使用 Docker secrets 机制 |
| **P1-11** | api_key_pool.last_error 可能泄露 Key | A02 | Key 片段泄露 | last_error 脱敏处理，移除 Key 模式 |
| **P1-12** | RelayRouter 转发 path 用户可控需白名单 | A10 | SSRF/路径遍历 | 转发路径白名单校验 |

### 7.3 P2 风险（建议修复，Phase 0 验收前完成）

| # | 风险 | 修复建议 |
|---|------|----------|
| **P2-1** | 健康检查暴露运营敏感信息 | 拆分为 `/health`（无敏感信息）和 `/health/detail`（需认证） |
| **P2-2** | Nginx access log 记录完整 URL | 配置 `log_format` 过滤敏感 query 参数 |
| **P2-3** | `latest` Docker 标签 | 固定版本标签 |
| **P2-4** | RSA 2048 位 | 评估升级 3072 位 |
| **P2-5** | `ssl_prefer_server_ciphers off` | 改为 `on` 由服务端选择加密套件 |
| **P2-6** | Grafana 端口对外暴露 | 绑定 127.0.0.1 或通过 Nginx 反代 |
| **P2-7** | 备份脚本密码暴露在进程列表 | 使用 `REDISCLI_AUTH` 环境变量 |
| **P2-8** | `python-jose` 与 `pyjwt` 共存 | 统一使用一个 JWT 库 |
| **P2-9** | users.email/wechat_openid 未加密 | 字段级加密（与 PII 加密统一） |

---

## 8. 安全审查结论

### 8.1 总体评价

**⚠️ 有条件通过 (Conditional Pass)**

PromiseLink 专业版 Phase 0 云端AI网关技术设计整体体现了较强的安全意识：

**优点**:
1. ✅ RS256 非对称签名选型正确，优于 HS256
2. ✅ 数据最小化原则落实到位（网关不存业务 payload）
3. ✅ Key 池管理算法完备（加权轮询+健康检查+熔断+冷却）
4. ✅ 多层防护体系（Cloudflare + Nginx + FastAPI 中间件链）
5. ✅ 审计日志记录范围完整
6. ✅ 红黄绿灯配额机制设计合理
7. ✅ 隐私协议含第三方 AI 披露条款
8. ✅ 备份策略与灾难恢复流程文档化

**问题**:
1. ❌ 5 项 P0 阻断项必须修复（网络边界、密钥管理、Redis 策略、管理员认证、激活越权）
2. ⚠️ 12 项 P1 风险项需在 P7 实现阶段修复
3. ⚠️ 9 项 P2 建议项建议在 Phase 0 验收前修复

### 8.2 阻断项清单（P0，必须修复）

| # | 阻断项 | 修复要求 | 验证方法 |
|---|--------|----------|----------|
| **P0-1** | gateway 8000 端口对外暴露 | `docker-compose.yml` 改为 `expose` 或绑定 127.0.0.1 | `nmap <vps-ip> -p 8000` 应不可达 |
| **P0-2** | 种子数据 SQL 明文 Key 模式 | 提供独立 `seed_api_keys.py` 脚本，SQL 文件不含 Key | 审查 SQL 文件无 `sk-` 模式 |
| **P0-3** | Redis allkeys-lru 淘汰 JWT 黑名单 | 改为 `volatile-lru` 或独立实例 | 压力测试下黑名单不被淘汰 |
| **P0-4** | 管理员接口认证未定义 | 定义独立管理员认证（密钥/IP白名单/mTLS） | 文档化 + 自动化测试 |
| **P0-5** | 激活接口允许客户端指定 user_id | user_id 由服务端从认证上下文生成 | 测试客户端传 user_id 被忽略 |

### 8.3 建议项清单（P1/P2，非阻断）

- **P1 项**: 见 §7.2，需在 P7 实现阶段逐项修复并纳入代码审查
- **P2 项**: 见 §7.3，建议在 Phase 0 验收前完成

### 8.4 生命周期阶段判定

```
P6 安全审查 Gate 检查:
  ⚠️ 存在 5 项 P0 阻断项
  
判定: P6 有条件通过
      → 修复 5 项 P0 阻断项后 → 进入 P7 实现阶段
      → P0 修复需在 P7 启动前完成
      → P1 修复需在 P7 实现过程中完成
      → P2 修复需在 Phase 0 验收前完成
      → 建议阻断项修复时限: 3 个工作日内
```

### 8.5 修复后重审要求

P0 阻断项修复后需重新提交安全审查，确认：
1. 5 项 P0 阻断项均已修复并验证
2. 修复过程未引入新的安全问题
3. P1 项已有明确的实现计划（纳入 P7 任务清单）

---

## 附录 A: 审查方法与依据

### A.1 审查方法

1. **文档审查**: 通读 P3 技术设计文档（3031 行）+ P2 Review 报告 + 架构文档安全章节
2. **STRIDE 威胁建模**: 对 9 个组件逐项分析 6 类威胁
3. **OWASP Top 10 (2021)**: 对照 10 大类安全风险逐项审查
4. **关键机制深审**: 8 个关键安全机制的逐项验证
5. **合规审查**: AGPL v3 + PIPL + 数据本地化
6. **攻击路径推演**: 对每个 P0/P1 风险构造具体攻击路径

### A.2 审查依据

- OWASP Top 10 (2021): https://owasp.org/Top10/
- OWASP API Security Top 10 (2023)
- NIST SP 800-63B (数字身份指南)
- PIPL (《个人信息保护法》)
- AGPL v3 许可证
- JWT 最佳实践 (RFC 8725)

### A.3 审查范围限制

本次审查基于 P3 技术设计文档，**未审查实际代码**（代码尚未实现）。以下问题需在 P7 实现阶段通过代码审查进一步验证：
- SQL 查询是否全部参数化
- JWT 验证实现细节
- Sentry SDK 配置
- Nginx 完整配置
- 密钥管理实际实践

---

## 附录 B: P0 阻断项修复指引

### B.1 P0-1: 8000 端口暴露修复

```yaml
# docker-compose.yml 修复
gateway:
  # 修复前: ports: - "8000:8000"
  # 修复后:
  expose:
    - "8000"  # 仅对 Docker 网络内可见
  # 或绑定到本地:
  # ports:
  #   - "127.0.0.1:8000:8000"
```

### B.2 P0-2: 种子数据明文 Key 修复

```python
# scripts/seed_api_keys.py (独立脚本，不提交 Key)
import os
from cryptography.fernet import Fernet
from gateway.core.crypto import encrypt_api_key

# Key 从环境变量读取，不入 SQL 文件
keys = [
    {"provider": "deepseek", "key": os.environ["DEEPSEEK_API_KEY_1"], ...},
    ...
]

for k in keys:
    encrypted = encrypt_api_key(k["key"])  # AES-256-GCM
    # INSERT INTO api_key_pool ... VALUES (..., encrypted, ...)
```

### B.3 P0-3: Redis 淘汰策略修复

```yaml
# docker-compose.yml 修复
redis:
  command: >
    redis-server
    --requirepass ${REDIS_PASSWORD}
    --maxmemory 512mb
    --maxmemory-policy volatile-lru  # 修复: 仅淘汰带 TTL 的键
    --appendonly yes
    --appendfsync everysec
```

### B.4 P0-4: 管理员认证修复

```python
# 管理员接口需独立认证
@app.middleware("http")
async def admin_auth_middleware(request: Request, call_next):
    if request.url.path.startswith("/api/v1/admin/"):
        # 方案1: 独立管理员 API Key (不同于客户端)
        admin_key = request.headers.get("X-Admin-Key")
        if admin_key != os.environ["ADMIN_API_KEY"]:
            return JSONResponse(403, {"error": "Admin access required"})
        # 方案2: IP 白名单
        if request.client.host not in ADMIN_IP_WHITELIST:
            return JSONResponse(403, {"error": "IP not allowed"})
    return await call_next(request)
```

### B.5 P0-5: 激活接口 user_id 修复

```python
# 修复: user_id 由服务端生成，不接受客户端传入
@app.post("/api/v1/pro/license/activate")
async def activate_license(request: Request, body: LicenseActivateRequest):
    # 忽略 body.user_id，由服务端生成
    user_id = generate_user_id()  # 或从微信登录上下文获取
    # 验证 license_key + device_fingerprint
    # 绑定服务端生成的 user_id
```

---

*报告生成时间: 2026-06-17 | 审查 ID: PRO-GW-SEC-REVIEW-001 | P6 安全审查阶段*
