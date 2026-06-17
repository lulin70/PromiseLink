# PromiseLink 专业版 Phase 0 测试计划 — 云端AI网关

> **版本**: v1.0
> **日期**: 2026-06-17
> **生命周期阶段**: P7 测试计划
> **对应技术设计**: `docs/architecture/Pro_Edition_Tech_Design_Phase0.md` v1.0
> **对应PRD**: `docs/spec/PRD_Pro_Edition_v1.md` v1.0
> **对应架构**: `docs/architecture/Pro_Edition_Architecture.md` v1.1
> **对应实现计划**: `docs/planning/Pro_Edition_Implementation_Plan.md` v1.0 (Phase 0)
> **基础版版本**: v0.5.4 (成熟度 92/100)
> **测试负责人**: QA团队

---

## 0. 文档定位与读者

本文档是 PromiseLink 专业版 **Phase 0 云端AI网关** 的测试计划文档，面向：
- **测试工程师**：按本文档编写和执行测试用例
- **后端开发**：按本文档编写单元测试，理解验收标准
- **DevOps**：按本文档配置CI/CD测试流水线
- **架构师**：审查测试覆盖度与验收标准

**测试铁律**：
1. ❌ **不修改断言来通过测试** — 测试是契约，失败即缺陷
2. ❌ **不为通过测试而mock核心逻辑** — 核心业务路径必须真实执行
3. ✅ **测试覆盖正常+边界+错误场景** — 三态全覆盖
4. ✅ **E2E测试模拟真实用户** — 不依赖内部实现细节
5. ✅ **发布前必须做模拟真实用户使用的测试** — 用户规则3要求

---

## 1. 测试策略

### 1.1 测试目标

- 验证云端AI网关4大核心职责（AI代理、许可验证、用量计费、中继转发）功能正确
- 验证API Key池管理算法（加权轮询、健康检查、冷却/熔断/恢复）可靠性
- 验证许可验证流程（激活、JWT签发/验证/刷新/吊销、设备指纹绑定）安全性
- 验证用量计费（配额管理、红黄绿灯三态、月度重置）准确性
- 验证中继服务（LLM/ASR/TTS/OCR代理、SSE流式、Provider降级）稳定性
- 验证安全机制（RS256签名、CRL黑名单、速率限制、防刷）有效性
- 验证性能指标达标（P95<3秒、QPS>100、并发WSS>500）
- **模拟真实用户使用的E2E测试**（用户规则3要求）

### 1.2 测试金字塔

```
                    △
                   / \
                  / E \  ← E2E测试 (10%) — 模拟真实用户完整业务流程
                 / 2 E \
                /───────\
               /         \
              / 集成测试  \  ← 集成测试 (20%) — 模块间协作、完整流程
             /    (20%)   \
            /───────────────\
           /                 \
          /    单元测试        \  ← 单元测试 (70%) — 函数/类级别
         /       (70%)         \
        /─────────────────────────\
```

### 1.3 测试工具栈

| 工具 | 用途 | 版本 |
|------|------|------|
| **pytest** | 测试框架 | >=7.4 |
| **pytest-asyncio** | 异步测试支持 | >=0.23 |
| **httpx** | HTTP客户端（API测试） | >=0.26 |
| **pytest-cov** | 覆盖率统计 | >=4.1 |
| **pytest-mock** | Mock工具 | >=3.12 |
| **fakeredis** | Redis Mock（单元测试） | >=2.20 |
| **testcontainers** | PG/Redis容器（集成测试） | >=4.0 |
| **locust** | 性能压测 | >=2.20 |
| **websockets** | WSS客户端测试 | >=12.0 |
| **respx** | httpx Mock（LLM API模拟） | >=0.20 |
| **ruff** | 代码检查 | >=0.1 |
| **mypy** | 类型检查 | >=1.8 |

### 1.4 覆盖率目标

| 维度 | 目标 | 说明 |
|------|------|------|
| **单元测试覆盖率** | ≥80% | 行覆盖率+分支覆盖率 |
| **集成测试覆盖率** | ≥60% | 核心流程覆盖 |
| **E2E测试覆盖率** | 100% | 5个核心场景全通过 |
| **关键模块覆盖率** | ≥90% | APIKeyPool/LicenseService/BillingService/AIProxy |

### 1.5 测试环境

**本地Docker Compose环境**：

```yaml
# tests/docker-compose.test.yml
version: '3.8'
services:
  postgres-test:
    image: postgres:16-alpine
    environment:
      POSTGRES_DB: gateway_test
      POSTGRES_USER: test
      POSTGRES_PASSWORD: test
    ports: ['5433:5432']  # 避免与开发环境冲突
    tmpfs: /var/lib/postgresql/data  # 内存盘加速

  redis-test:
    image: redis:7-alpine
    ports: ['6380:6379']  # 避免与开发环境冲突
    tmpfs: /data
```

**环境分层**：

| 环境 | 用途 | 数据 | 清理策略 |
|------|------|------|----------|
| **单元测试** | 函数级测试 | Mock数据 | 每用例清理 |
| **集成测试** | 模块协作测试 | Docker容器 | 每测试类清理 |
| **E2E测试** | 完整流程测试 | 模拟真实数据 | 每场景清理 |
| **性能测试** | 压力测试 | 大量模拟数据 | 每轮次清理 |
| **Staging** | 预发布验证 | 脱敏数据 | 每周清理 |

### 1.6 测试目录结构

```
gateway/tests/
├── conftest.py                    # 全局fixtures
├── unit/                          # 单元测试
│   ├── conftest.py
│   ├── test_api_key_pool.py       # API Key池管理器
│   ├── test_license_service.py    # 许可验证服务
│   ├── test_billing_service.py    # 用量计费服务
│   ├── test_relay_router.py       # 中继服务
│   ├── test_ai_proxy.py           # AI代理层
│   ├── test_jwt_handler.py        # JWT处理
│   ├── test_crypto.py             # 加密/解密
│   ├── test_middleware.py         # 中间件
│   └── test_schemas.py            # 数据模型校验
├── integration/                   # 集成测试
│   ├── conftest.py
│   ├── test_activate_verify_relay.py
│   ├── test_key_pool_failover.py
│   ├── test_quota_exhaustion.py
│   ├── test_concurrent_requests.py
│   └── test_db_transaction.py
├── e2e/                           # E2E测试
│   ├── conftest.py
│   ├── test_scenario1_license_activate.py
│   ├── test_scenario2_voice_assistant.py
│   ├── test_scenario3_quota_management.py
│   ├── test_scenario4_key_pool_recovery.py
│   └── test_scenario5_license_renewal.py
├── performance/                   # 性能测试
│   ├── locustfile_llm.py
│   ├── locustfile_concurrent.py
│   └── locustfile_stability.py
├── security/                      # 安全测试
│   ├── test_jwt_forgery.py
│   ├── test_api_key_leak.py
│   ├── test_rate_limit_bypass.py
│   └── test_sql_injection.py
└── fixtures/                      # 测试数据
    ├── licenses.json
    ├── api_keys.json
    ├── audio_samples/
    └── image_samples/
```

---

## 2. 单元测试计划

### 2.1 API Key池管理器 (`APIKeyPool`)

**测试文件**: `tests/unit/test_api_key_pool.py`
**测试目标**: 验证加权轮询、健康检查、冷却/熔断/恢复、并发安全
**覆盖率目标**: ≥95%

#### 2.1.1 加权轮询算法测试

| 用例ID | 场景 | 输入 | 预期结果 | 优先级 |
|--------|------|------|----------|--------|
| UT-KP-001 | 单Key选择 | 1个active Key | 返回该Key | P0 |
| UT-KP-002 | 多Key加权轮询 | 3个Key，weight=100/80/60 | 选择概率≈权重比 | P0 |
| UT-KP-003 | 健康分影响权重 | Key1 health=0.95, Key2 health=0.50 | Key1被选概率更高 | P0 |
| UT-KP-004 | RPM影响权重 | Key1 rpm=20/60, Key2 rpm=45/60 | Key1 effective_weight更高 | P1 |
| UT-KP-005 | 权重计算公式 | base×health×(1-rpm/limit) | 公式正确 | P0 |
| UT-KP-006 | 1000次选择分布 | 3个Key，1000次选择 | 实际分布≈理论分布(±5%) | P1 |

**测试代码示例**：

```python
async def test_weighted_round_robin_distribution():
    """UT-KP-006: 验证加权轮询选择分布"""
    pool = APIKeyPool(redis=fake_redis, pg=test_session)
    await pool.add_key(Key(key_id="k1", provider="deepseek", weight=100, health_score=1.0))
    await pool.add_key(Key(key_id="k2", provider="deepseek", weight=80, health_score=1.0))
    await pool.add_key(Key(key_id="k3", provider="moka_ai", weight=60, health_score=1.0))

    selections = {"k1": 0, "k2": 0, "k3": 0}
    for _ in range(1000):
        key = await pool.select_key(provider="deepseek")  # k3是moka_ai应排除
        if key.key_id in ["k1", "k2"]:
            selections[key.key_id] += 1

    # k1:k2 = 100:80 = 55.6%:44.4%
    total = selections["k1"] + selections["k2"]
    assert abs(selections["k1"] / total - 100/180) < 0.05  # ±5%容差
    assert abs(selections["k2"] / total - 80/180) < 0.05
```

#### 2.1.2 健康检查测试

| 用例ID | 场景 | 输入 | 预期结果 | 优先级 |
|--------|------|------|----------|--------|
| UT-KP-010 | 成功请求提升健康分 | health=0.80, 请求成功 | health=0.85 (上限1.00) | P0 |
| UT-KP-011 | 429降低健康分 | health=1.00, 429响应 | health=0.80 (-0.20) | P0 |
| UT-KP-012 | 5xx降低健康分 | health=1.00, 5xx响应 | health=0.70 (-0.30) | P0 |
| UT-KP-013 | 超时降低健康分 | health=1.00, 超时 | health=0.75 (-0.25) | P0 |
| UT-KP-014 | 网络错误降低健康分 | health=1.00, 网络错误 | health=0.80 (-0.20) | P1 |
| UT-KP-015 | 健康分下限保护 | health=0.10, 5xx响应 | health=0.00 (不下溢) | P0 |
| UT-KP-016 | 健康分上限保护 | health=0.98, 成功 | health=1.00 (不上溢) | P0 |
| UT-KP-017 | 探活成功提升健康分 | health=0.70, 探活成功 | health=0.80 (+0.10) | P1 |
| UT-KP-018 | 探活失败保持健康分 | health=0.70, 探活失败 | health=0.70 (不变) | P1 |

#### 2.1.3 冷却/熔断/恢复测试

| 用例ID | 场景 | 输入 | 预期结果 | 优先级 |
|--------|------|------|----------|--------|
| UT-KP-020 | 429触发冷却 | 收到429响应 | status=rate_limited, cooldown_until=NOW+60s | P0 |
| UT-KP-021 | 冷却期间不选Key | Key在冷却期 | 该Key被过滤，不选中 | P0 |
| UT-KP-022 | 冷却到期可探活 | cooldown_until<NOW | 触发探活请求 | P0 |
| UT-KP-023 | 冷却到期探活成功 | 探活返回2xx | status=active, health+0.10 | P0 |
| UT-KP-024 | 冷却到期探活失败 | 探活返回5xx | cooldown_until延长60s | P0 |
| UT-KP-025 | 连续3次5xx触发熔断 | consecutive_failures=3 | status=circuit_open, circuit_opened_at=NOW | P0 |
| UT-KP-026 | 熔断期间不选Key | Key在熔断期 | 该Key被过滤 | P0 |
| UT-KP-027 | 熔断5分钟后可探活 | circuit_opened_at<NOW-5min | 触发探活 | P0 |
| UT-KP-028 | 熔断恢复探活成功 | 探活返回2xx | status=active, failures=0, health=0.50 | P0 |
| UT-KP-029 | 熔断恢复探活失败 | 探活返回5xx | circuit_opened_at重置 | P0 |
| UT-KP-030 | 管理员禁用Key | 手动设置disabled | status=disabled, 永不选中 | P1 |

#### 2.1.4 并发安全测试

| 用例ID | 场景 | 输入 | 预期结果 | 优先级 |
|--------|------|------|----------|--------|
| UT-KP-040 | 并发选择Key | 100并发请求 | 无重复选择同一Key超RPM限制 | P0 |
| UT-KP-041 | 并发健康分更新 | 10并发更新同一Key | health_score最终值正确（无竞态） | P0 |
| UT-KP-042 | 并发熔断触发 | 3并发5xx响应 | consecutive_failures正确递增 | P0 |
| UT-KP-043 | RPM计数原子性 | 100并发请求 | current_rpm计数准确 | P0 |

#### 2.1.5 边界场景测试

| 用例ID | 场景 | 输入 | 预期结果 | 优先级 |
|--------|------|------|----------|--------|
| UT-KP-050 | 空Key池 | 无Key | 返回None / 抛出NoAvailableKey | P0 |
| UT-KP-051 | 所有Key不可用 | 所有Key熔断/冷却 | 返回503 NO_AVAILABLE_KEY | P0 |
| UT-KP-052 | 单Key池 | 仅1个active Key | 始终返回该Key | P0 |
| UT-KP-053 | Key的RPM超限 | current_rpm>=rpm_limit | 该Key被过滤 | P0 |
| UT-KP-054 | Key的TPM超限 | current_tpm+estimated>tpm_limit | 该Key被过滤 | P1 |
| UT-KP-055 | 指定provider无Key | 请求anthropic但无该provider Key | 返回None | P1 |
| UT-KP-056 | 重试次数限制 | 3次重试全失败 | 返回503，不再重试 | P0 |

---

### 2.2 许可验证服务 (`LicenseService`)

**测试文件**: `tests/unit/test_license_service.py`
**测试目标**: 验证激活流程、JWT签发/验证、设备指纹绑定、CRL黑名单、刷新流程
**覆盖率目标**: ≥95%

#### 2.2.1 激活流程测试

| 用例ID | 场景 | 输入 | 预期结果 | 优先级 |
|--------|------|------|----------|--------|
| UT-LIC-001 | 正常激活 | 有效license_key + 有效设备指纹 | 200, 返回license+tokens+relay_config | P0 |
| UT-LIC-002 | license_key格式错误 | "INVALID-KEY" | 400 INVALID_LICENSE_KEY_FORMAT | P0 |
| UT-LIC-003 | license_key不存在 | "PL-PRO-XXXX-YYYY-ZZZZ"（未注册） | 404 LICENSE_NOT_FOUND | P0 |
| UT-LIC-004 | 设备指纹格式错误 | "abc123"（非sha256格式） | 400 INVALID_DEVICE_FINGERPRINT | P0 |
| UT-LIC-005 | 许可证已过期 | status=expired | 410 LICENSE_EXPIRED | P0 |
| UT-LIC-006 | 许可证已取消 | status=cancelled | 410 LICENSE_CANCELLED | P0 |
| UT-LIC-007 | 许可证已暂停 | status=suspended | 403 LICENSE_SUSPENDED | P1 |
| UT-LIC-008 | expires_at<NOW自动过期 | expires_at过期但status仍active | UPDATE status=expired, 410 LICENSE_EXPIRED | P0 |
| UT-LIC-009 | 已被其他用户激活 | user_id不匹配 | 409 LICENSE_ALREADY_ACTIVATED | P0 |
| UT-LIC-010 | 首次激活绑定设备 | device_fingerprint IS NULL | 绑定设备，status=active | P0 |
| UT-LIC-011 | 设备指纹不匹配 | 已绑定设备A，请求设备B | 403 DEVICE_FINGERPRINT_MISMATCH | P0 |
| UT-LIC-012 | 超过最大设备数 | max_devices=1, 已绑定1台 | 409 DEVICE_LIMIT_EXCEEDED | P0 |
| UT-LIC-013 | 激活请求过于频繁 | 同Key 5次/小时 | 429 LICENSE_ACTIVATE_TOO_FREQUENT | P1 |
| UT-LIC-014 | 激活成功签发JWT | 正常激活 | JWT包含user_id/license_key/device_fingerprint/jti | P0 |
| UT-LIC-015 | 激活成功签发refresh_token | 正常激活 | refresh_token TTL=7天 | P0 |
| UT-LIC-016 | 激活记录审计日志 | 正常激活 | audit_logs表新增license_activate记录 | P1 |

#### 2.2.2 JWT签发和验证测试

| 用例ID | 场景 | 输入 | 预期结果 | 优先级 |
|--------|------|------|----------|--------|
| UT-LIC-020 | RS256签发JWT | 合法payload | JWT用私钥签名，header.alg=RS256 | P0 |
| UT-LIC-021 | RS256验证JWT | 合法JWT | 公钥验证通过，返回payload | P0 |
| UT-LIC-022 | JWT签名无效 | 篡改payload | 401 JWT_INVALID | P0 |
| UT-LIC-023 | JWT格式错误 | "invalid.jwt" | 401 JWT_INVALID | P0 |
| UT-LIC-024 | JWT已过期 | exp<NOW | 401 JWT_EXPIRED | P0 |
| UT-LIC-025 | JWT在CRL黑名单 | jti在Redis jwt_blacklist | 401 JWT_REVOKED | P0 |
| UT-LIC-026 | 缺少Authorization头 | 无Bearer token | 401 JWT_MISSING | P0 |
| UT-LIC-027 | JWT的jti唯一 | 多次签发 | 每次jti不同（UUID） | P0 |
| UT-LIC-028 | JWT TTL=15分钟 | 正常签发 | exp=iat+900 | P0 |
| UT-LIC-029 | JWT包含必要字段 | 正常签发 | 含user_id/license_key/plan_type/device_fingerprint/jti/iat/exp/iss/aud | P0 |
| UT-LIC-030 | HS256签名被拒绝 | 用HS256伪造 | 401 JWT_INVALID（仅接受RS256） | P0 |

#### 2.2.3 设备指纹绑定测试

| 用例ID | 场景 | 输入 | 预期结果 | 优先级 |
|--------|------|------|----------|--------|
| UT-LIC-040 | 首次绑定设备 | device_fingerprint IS NULL | 绑定成功，device_bound_at=NOW | P0 |
| UT-LIC-041 | 同设备重复激活 | 相同device_fingerprint | 正常通过（幂等） | P0 |
| UT-LIC-042 | 不同设备激活 | 不同device_fingerprint | 403 DEVICE_FINGERPRINT_MISMATCH | P0 |
| UT-LIC-043 | max_devices=2绑定2台 | 2台不同设备 | 均绑定成功 | P1 |
| UT-LIC-044 | 超过max_devices | 已绑定2台，请求第3台 | 409 DEVICE_LIMIT_EXCEEDED | P0 |
| UT-LIC-045 | 设备指纹格式校验 | "sha256:"+64位hex | 格式校验通过 | P0 |
| UT-LIC-046 | 设备指纹格式错误 | "md5:abc123" | 400 INVALID_DEVICE_FINGERPRINT | P0 |

#### 2.2.4 CRL黑名单测试

| 用例ID | 场景 | 输入 | 预期结果 | 优先级 |
|--------|------|------|----------|--------|
| UT-LIC-050 | JWT加入CRL | 吊销JWT | Redis jwt_blacklist:{jti}存在 | P0 |
| UT-LIC-051 | CRL TTL=JWT剩余有效期 | 吊销JWT | TTL=exp-NOW | P0 |
| UT-LIC-052 | CRL中的JWT被拒绝 | jti在CRL | 401 JWT_REVOKED | P0 |
| UT-LIC-053 | CRL过期自动清理 | TTL到期 | Redis键自动删除 | P1 |
| UT-LIC-054 | 管理员吊销许可证 | 调用revoke | 所有活跃JWT加入CRL | P0 |
| UT-LIC-055 | 吊销后WSS断开 | 吊销许可证 | 发送license_revoked消息+关闭连接 | P0 |

#### 2.2.5 刷新流程测试

| 用例ID | 场景 | 输入 | 预期结果 | 优先级 |
|--------|------|------|----------|--------|
| UT-LIC-060 | 无感刷新（剩余<5min） | expires_in<300 | 签发新JWT，旧JWT加入CRL | P0 |
| UT-LIC-061 | 无感刷新（剩余>5min） | expires_in>300 | 不刷新，返回当前JWT | P0 |
| UT-LIC-062 | refresh_token刷新 | 合法refresh_token | 签发新access+新refresh | P0 |
| UT-LIC-063 | refresh_token过期 | refresh_token exp<NOW | 401 JWT_EXPIRED，需重新激活 | P0 |
| UT-LIC-064 | refresh_token在CRL | 已吊销的refresh_token | 401 JWT_REVOKED | P0 |
| UT-LIC-065 | 刷新后旧JWT失效 | 刷新成功 | 旧access_token加入CRL | P0 |

---

### 2.3 用量计费服务 (`BillingService`)

**测试文件**: `tests/unit/test_billing_service.py`
**测试目标**: 验证配额检查、用量记录、月度重置、红黄绿灯三态
**覆盖率目标**: ≥95%

#### 2.3.1 配额检查测试

| 用例ID | 场景 | 输入 | 预期结果 | 优先级 |
|--------|------|------|----------|--------|
| UT-BIL-001 | 正常配额检查 | used=125000, limit=500000 (25%) | traffic_light=green, 放行 | P0 |
| UT-BIL-002 | 接近上限（80%） | used=400000, limit=500000 (80%) | traffic_light=yellow, 放行+警告头 | P0 |
| UT-BIL-003 | 超限（100%） | used=500000, limit=500000 (100%) | traffic_light=red, 402 QUOTA_EXCEEDED | P0 |
| UT-BIL-004 | 超限（>100%） | used=550000, limit=500000 (110%) | traffic_light=red, 402 | P0 |
| UT-BIL-005 | 边界值（79.99%） | used=399950, limit=500000 | traffic_light=green | P0 |
| UT-BIL-006 | 边界值（80.00%） | used=400000, limit=500000 | traffic_light=yellow | P0 |
| UT-BIL-007 | 边界值（99.99%） | used=499950, limit=500000 | traffic_light=yellow | P0 |
| UT-BIL-008 | 边界值（100.00%） | used=500000, limit=500000 | traffic_light=red | P0 |
| UT-BIL-009 | ASR配额独立检查 | ASR used=200, limit=200 | 402 ASR_QUOTA_EXCEEDED | P0 |
| UT-BIL-010 | TTS配额独立检查 | TTS used=200, limit=200 | 402 TTS_QUOTA_EXCEEDED | P0 |
| UT-BIL-011 | OCR配额独立检查 | OCR used=100, limit=100 | 402 OCR_QUOTA_EXCEEDED | P0 |
| UT-BIL-012 | LLM超限不影响ASR | LLM超限，ASR未超 | LLM拒绝，ASR放行 | P0 |

#### 2.3.2 用量记录测试

| 用例ID | 场景 | 输入 | 预期结果 | 优先级 |
|--------|------|------|----------|--------|
| UT-BIL-020 | 记录LLM用量 | input=150, output=80 | usage_records新增，total=230 | P0 |
| UT-BIL-021 | 更新许可证配额 | tokens=230 | quota_used_tokens+=230（原子操作） | P0 |
| UT-BIL-022 | 更新月度汇总 | tokens=230, cost=0.00023 | monthly_usage UPSERT | P0 |
| UT-BIL-023 | 更新Redis缓存 | tokens=230 | quota:cache HINCRBY | P1 |
| UT-BIL-024 | 成本计算-DeepSeek | 230 tokens | cost=230×0.001/1000=0.00023 | P0 |
| UT-BIL-025 | 成本计算-Moka AI | 230 tokens | cost=230×0.002/1000=0.00046 | P0 |
| UT-BIL-026 | 异步记录不阻塞响应 | 用量记录 | 响应时间不受影响 | P1 |
| UT-BIL-027 | 记录ASR用量 | 1次ASR | quota_used_asr+=1 | P0 |
| UT-BIL-028 | 记录TTS用量 | 1次TTS | quota_used_tts+=1 | P0 |
| UT-BIL-029 | 记录OCR用量 | 1次OCR | quota_used_ocr+=1 | P0 |
| UT-BIL-030 | 失败请求不记录用量 | LLM返回5xx | 不更新quota_used | P0 |

#### 2.3.3 月度重置测试

| 用例ID | 场景 | 输入 | 预期结果 | 优先级 |
|--------|------|------|----------|--------|
| UT-BIL-040 | 月初重置配额 | 每月1日00:00 UTC | quota_used_*=0, quota_reset_at+1month | P0 |
| UT-BIL-041 | 归档上月用量 | 重置时 | monthly_usage新增上月记录 | P0 |
| UT-BIL-042 | 清理Redis缓存 | 重置时 | DEL quota:cache:{user_id}:{last_month} | P1 |
| UT-BIL-043 | 生成月度账单 | 重置时 | 账单JSON生成，含breakdown | P1 |
| UT-BIL-044 | 重置不影响历史记录 | 重置后 | usage_records历史保留 | P0 |
| UT-BIL-045 | 重置任务幂等 | 重复执行 | 不重复重置（幂等检查） | P0 |

#### 2.3.4 红黄绿灯三态测试

| 用例ID | 场景 | 输入 | 预期结果 | 优先级 |
|--------|------|------|----------|--------|
| UT-BIL-050 | green→yellow变更 | 用量从79%→81% | 触发用户通知+审计日志 | P0 |
| UT-BIL-051 | yellow→red变更 | 用量从99%→101% | 触发用户通知+邮件+钉钉告警 | P0 |
| UT-BIL-052 | green→red跳变 | 用量从50%→110%（单次大请求） | 直接触发red告警 | P1 |
| UT-BIL-053 | yellow响应头 | traffic_light=yellow | 响应头 X-Quota-Warning: yellow | P0 |
| UT-BIL-054 | red拒绝AI调用 | traffic_light=red | 返回402 QUOTA_EXCEEDED | P0 |
| UT-BIL-055 | red不拒绝非AI调用 | traffic_light=red | /api/v1/pro/usage 仍可访问 | P1 |
| UT-BIL-056 | 重置后red→green | 月初重置 | traffic_light=green | P0 |

---

### 2.4 中继服务 (`RelayRouter` + `AIProxy`)

**测试文件**: `tests/unit/test_relay_router.py`, `tests/unit/test_ai_proxy.py`
**测试目标**: 验证LLM/ASR/TTS/OCR中继、Provider降级、SSE流式响应
**覆盖率目标**: ≥90%

#### 2.4.1 LLM中继测试

| 用例ID | 场景 | 输入 | 预期结果 | 优先级 |
|--------|------|------|----------|--------|
| UT-RLY-001 | 正常LLM请求（非流式） | stream=false | 200, 返回content+usage+billing | P0 |
| UT-RLY-002 | 正常LLM请求（流式） | stream=true | 200, SSE流式响应 | P0 |
| UT-RLY-003 | LLM请求超时 | LLM API 30s无响应 | 504 UPSTREAM_TIMEOUT, 重试 | P0 |
| UT-RLY-004 | LLM 5xx错误 | LLM API返回500 | 重试其他Key, 3次失败返回502 | P0 |
| UT-RLY-005 | LLM 429限流 | LLM API返回429 | Key冷却60s, 切换其他Key | P0 |
| UT-RLY-006 | LLM网络错误 | 连接LLM API失败 | 重试其他Key | P0 |
| UT-RLY-007 | 请求体校验失败 | messages为空 | 400 VALIDATION_ERROR | P0 |
| UT-RLY-008 | max_tokens超限 | max_tokens=99999 | 400 VALIDATION_ERROR | P1 |
| UT-RLY-009 | temperature超范围 | temperature=3.0 | 400 VALIDATION_ERROR | P1 |
| UT-RLY-010 | messages超50条 | 51条消息 | 400 VALIDATION_ERROR | P1 |
| UT-RLY-011 | 无可用Key | 所有Key熔断 | 503 NO_AVAILABLE_KEY | P0 |
| UT-RLY-012 | 重试3次后放弃 | 3个Key全失败 | 503 NO_AVAILABLE_KEY | P0 |

#### 2.4.2 ASR/TTS/OCR中继测试

| 用例ID | 场景 | 输入 | 预期结果 | 优先级 |
|--------|------|------|----------|--------|
| UT-RLY-020 | 正常ASR请求 | mp3音频(8.5s) | 200, 返回text+duration+billing | P0 |
| UT-RLY-021 | ASR音频格式不支持 | .avi文件 | 400 INVALID_AUDIO_FORMAT | P0 |
| UT-RLY-022 | ASR音频过大 | 30MB音频 | 400 AUDIO_TOO_LARGE | P0 |
| UT-RLY-023 | ASR音频时长不足 | 3秒音频 | 400 AUDIO_DURATION_INVALID | P0 |
| UT-RLY-024 | ASR音频时长超限 | 65秒音频 | 400 AUDIO_DURATION_INVALID | P0 |
| UT-RLY-025 | ASR配额超限 | ASR used=200 | 402 ASR_QUOTA_EXCEEDED | P0 |
| UT-RLY-026 | 正常TTS请求 | text="你好" | 200, audio/mpeg二进制 | P0 |
| UT-RLY-027 | TTS文本过长 | 501字符 | 400 TEXT_TOO_LONG | P0 |
| UT-RLY-028 | TTS配额超限 | TTS used=200 | 402 TTS_QUOTA_EXCEEDED | P0 |
| UT-RLY-029 | 正常OCR请求 | jpg图片(名片) | 200, 返回structured+raw_text | P0 |
| UT-RLY-030 | OCR图片格式不支持 | .gif文件 | 400 INVALID_IMAGE_FORMAT | P0 |
| UT-RLY-031 | OCR图片过大 | 15MB图片 | 400 IMAGE_TOO_LARGE | P0 |
| UT-RLY-032 | OCR配额超限 | OCR used=100 | 402 OCR_QUOTA_EXCEEDED | P0 |

#### 2.4.3 Provider降级测试

| 用例ID | 场景 | 输入 | 预期结果 | 优先级 |
|--------|------|------|----------|--------|
| UT-RLY-040 | DeepSeek全失败降级Moka | DeepSeek所有Key失败 | 切换Moka AI, X-Degraded: true | P0 |
| UT-RLY-041 | 模型降级 | deepseek-chat失败 | 降级deepseek-lite | P1 |
| UT-RLY-042 | 所有Provider失败 | DeepSeek+Moka全失败 | 503 NO_AVAILABLE_KEY | P0 |
| UT-RLY-043 | 降级响应标记 | 发生降级 | 响应头 X-Degraded: true | P0 |
| UT-RLY-044 | 降级不影响计费 | 降级到Moka | 按Moka价格计费 | P1 |

#### 2.4.4 SSE流式响应测试

| 用例ID | 场景 | 输入 | 预期结果 | 优先级 |
|--------|------|------|----------|--------|
| UT-RLY-050 | SSE事件格式 | stream=true | event:token + event:done | P0 |
| UT-RLY-051 | token事件内容 | 单token | {"content":"张","index":0} | P0 |
| UT-RLY-052 | done事件内容 | 流结束 | {"usage":{...},"billing":{...}} | P0 |
| UT-RLY-053 | error事件 | 流中错误 | event:error + {"code","message"} | P0 |
| UT-RLY-054 | 响应头正确 | stream=true | Content-Type: text/event-stream | P0 |
| UT-RLY-055 | 禁用Nginx缓冲 | stream=true | X-Accel-Buffering: no | P1 |
| UT-RLY-056 | 流式逐token转发 | 100 token响应 | 每token立即flush | P1 |
| UT-RLY-057 | 流式用量记录 | 流结束 | 异步记录usage | P0 |
| UT-RLY-058 | 客户端断开连接 | 流式中断 | 取消上游请求，释放资源 | P0 |

---

## 3. 集成测试计划

**测试文件**: `tests/integration/`
**测试目标**: 验证模块间协作、完整流程、数据一致性
**环境**: Docker Compose (PG + Redis + Gateway)

### 3.1 完整激活→验证→中继流程

| 用例ID | 场景 | 步骤 | 预期结果 | 优先级 |
|--------|------|------|----------|--------|
| IT-001 | 完整LLM调用链 | 激活→验证→LLM中继 | 全流程200, 用量正确记录 | P0 |
| IT-002 | 完整ASR调用链 | 激活→验证→ASR中继 | 全流程200, ASR计数+1 | P0 |
| IT-003 | 完整TTS调用链 | 激活→验证→TTS中继 | 全流程200, TTS计数+1 | P0 |
| IT-004 | 完整OCR调用链 | 激活→验证→OCR中继 | 全流程200, OCR计数+1 | P0 |
| IT-005 | JWT无感刷新链 | 激活→等待JWT<5min→验证→自动刷新 | 新JWT签发，旧JWT失效 | P0 |
| IT-006 | refresh_token刷新链 | 激活→access过期→refresh→新access | 刷新成功 | P0 |

### 3.2 Key池故障→降级流程

| 用例ID | 场景 | 步骤 | 预期结果 | 优先级 |
|--------|------|------|----------|--------|
| IT-010 | 单Key 429切换 | 请求→Key1返回429→切换Key2 | 请求成功，Key1冷却 | P0 |
| IT-011 | 单Key 5xx熔断 | Key1连续3次5xx→熔断→切换Key2 | 请求成功，Key1熔断5min | P0 |
| IT-012 | 所有DeepSeek失败降级Moka | DeepSeek全熔断→降级Moka | 请求成功，X-Degraded: true | P0 |
| IT-013 | 所有Key失败 | 所有Key熔断 | 503 NO_AVAILABLE_KEY | P0 |
| IT-014 | Key冷却后恢复 | Key1冷却60s→探活成功→恢复 | Key1重新可用 | P0 |
| IT-015 | Key熔断后恢复 | Key1熔断5min→探活成功→恢复 | Key1重新可用 | P0 |

### 3.3 配额耗尽→拒绝流程

| 用例ID | 场景 | 步骤 | 预期结果 | 优先级 |
|--------|------|------|----------|--------|
| IT-020 | LLM配额耗尽 | 持续请求直到100%→再请求 | 402 QUOTA_EXCEEDED | P0 |
| IT-021 | 黄灯警告 | 请求到80%→继续请求 | 放行+X-Quota-Warning: yellow | P0 |
| IT-022 | 红灯拒绝 | 请求到100%→再请求 | 402 QUOTA_EXCEEDED | P0 |
| IT-023 | ASR配额耗尽不影响LLM | ASR用完→请求LLM | LLM正常 | P0 |
| IT-024 | 月初重置恢复 | 模拟月初→请求 | 配额重置，可正常使用 | P0 |
| IT-025 | 状态变更告警 | green→yellow→red | 每次变更触发通知+审计 | P0 |

### 3.4 并发请求处理

| 用例ID | 场景 | 步骤 | 预期结果 | 优先级 |
|--------|------|------|----------|--------|
| IT-030 | 100并发LLM请求 | 100并发请求 | 全部成功或合理限流 | P0 |
| IT-031 | 并发Key选择无冲突 | 100并发选Key | 无Key超RPM限制 | P0 |
| IT-032 | 并发用量记录 | 100并发记录 | quota_used准确（无竞态） | P0 |
| IT-033 | 并发激活同一Key | 2并发激活同Key | 1成功1失败(409) | P0 |
| IT-034 | 限流触发 | 101 req/min | 第101个返回429 | P0 |

### 3.5 数据库事务一致性

| 用例ID | 场景 | 步骤 | 预期结果 | 优先级 |
|--------|------|------|----------|--------|
| IT-040 | 激活事务原子性 | 激活中途失败 | 数据无部分写入 | P0 |
| IT-041 | 用量记录+配额更新原子性 | 记录用量 | 两者同时成功或同时失败 | P0 |
| IT-042 | 月度重置事务 | 重置中途失败 | 数据无部分重置 | P0 |
| IT-043 | 并发配额更新 | 100并发更新 | quota_used准确 | P0 |
| IT-044 | FOR UPDATE行锁 | 并发激活同Key | 串行化处理 | P0 |

---

## 4. E2E测试计划（模拟真实用户）

**测试文件**: `tests/e2e/`
**测试目标**: 模拟真实用户完整业务流程，验证系统可用性
**环境**: 完整Docker Compose (Gateway + PG + Redis + Nginx + Mock LLM)
**原则**: 不依赖内部实现细节，从用户视角验证

### 场景1: 许总激活专业版

**文件**: `tests/e2e/test_scenario1_license_activate.py`

**用户故事**: 许总购买专业版后，输入license_key激活，获取relay_token，发起第一个LLM请求验证可用。

| 步骤 | 操作 | 预期结果 | 验证点 |
|------|------|----------|--------|
| 1.1 | 准备：数据库插入测试license_key `PL-PRO-TEST-0001-0001` | license状态active, 未绑定设备 | DB查询验证 |
| 1.2 | 调用 `POST /api/v1/pro/license/activate` | 200, 返回license+tokens+relay_config | response.success=true |
| 1.3 | 验证响应包含access_token | access_token非空, JWT格式 | JWT可解析 |
| 1.4 | 验证响应包含refresh_token | refresh_token非空 | - |
| 1.5 | 验证响应包含relay_config | relay_gateway_url, heartbeat_interval | - |
| 1.6 | 调用 `POST /api/v1/pro/license/verify` | 200, valid=true, quota.traffic_light=green | - |
| 1.7 | 调用 `POST /api/v1/pro/relay/llm` (非流式) | 200, content非空, usage.total_tokens>0 | billing.monthly_status=green |
| 1.8 | 调用 `GET /api/v1/pro/usage` | 200, quota.tokens.used>0 | - |
| 1.9 | 验证数据库usage_records新增记录 | 记录数+1 | DB查询验证 |
| 1.10 | 验证licenses.quota_used_tokens增加 | 增量=usage.total_tokens | DB查询验证 |

**验收标准**: 全部10步通过，端到端延迟<5秒

### 场景2: 语音助手完整流程

**文件**: `tests/e2e/test_scenario2_voice_assistant.py`

**用户故事**: 许总使用语音助手，语音输入"今天和张总吃了午饭"，系统完成ASR→LLM→TTS全流程。

| 步骤 | 操作 | 预期结果 | 验证点 |
|------|------|----------|--------|
| 2.1 | 准备：激活license，获取JWT | 激活成功 | - |
| 2.2 | 上传音频文件调用 `POST /api/v1/pro/relay/asr` | 200, text非空 | text包含"张总" |
| 2.3 | 验证ASR计费 | asr_used+1 | usage接口验证 |
| 2.4 | 用ASR结果作为LLM输入，调用 `POST /api/v1/pro/relay/llm` | 200, content非空 | content是合理回复 |
| 2.5 | 验证LLM计费 | tokens_used增加 | usage接口验证 |
| 2.6 | 用LLM结果调用 `POST /api/v1/pro/relay/tts` | 200, audio/mpeg二进制 | Content-Type正确 |
| 2.7 | 验证TTS计费 | tts_used+1 | usage接口验证 |
| 2.8 | 验证完整流程延迟 | <10秒 | 端到端计时 |
| 2.9 | 验证数据库3条usage_records | asr+llm+tts各1条 | DB查询验证 |

**验收标准**: 全流程成功，延迟<10秒，3类计费独立准确

### 场景3: 配额管理

**文件**: `tests/e2e/test_scenario3_quota_management.py`

**用户故事**: 许总持续使用AI功能，从绿灯→黄灯→红灯，验证配额管理全流程。

| 步骤 | 操作 | 预期结果 | 验证点 |
|------|------|----------|--------|
| 3.1 | 准备：激活license，配额limit=1000 tokens（测试用小配额） | traffic_light=green | - |
| 3.2 | 发起LLM请求消耗800 tokens (80%) | traffic_light=yellow | usage接口验证 |
| 3.3 | 验证响应头包含 `X-Quota-Warning: yellow` | 响应头存在 | - |
| 3.4 | 继续请求消耗200 tokens (100%) | traffic_light=red | - |
| 3.5 | 再次发起LLM请求 | 402 QUOTA_EXCEEDED | error.code正确 |
| 3.6 | 验证ASR仍可用（独立配额） | 200 | ASR不受LLM影响 |
| 3.7 | 验证usage接口仍可访问 | 200, traffic_light=red | 非AI调用不拒绝 |
| 3.8 | 模拟月初重置（手动触发或调整时间） | traffic_light=green | - |
| 3.9 | 重置后发起LLM请求 | 200 | 配额恢复 |

**验收标准**: 三态切换正确，独立配额隔离，重置恢复

### 场景4: Key池故障恢复

**文件**: `tests/e2e/test_scenario4_key_pool_recovery.py`

**用户故事**: LLM API出现429限流，系统自动切换Key，用户无感知。所有Key故障时优雅降级。

| 步骤 | 操作 | 预期结果 | 验证点 |
|------|------|----------|--------|
| 4.1 | 准备：2个DeepSeek Key (Key1, Key2) | 均active | - |
| 4.2 | Mock Key1的LLM API返回429 | Key1收到429 | - |
| 4.3 | 发起LLM请求 | 200 (自动切换Key2) | 响应成功 |
| 4.4 | 验证Key1状态 | rate_limited, cooldown_until=NOW+60s | DB/Redis验证 |
| 4.5 | 验证Key2被使用 | last_used_at更新 | DB验证 |
| 4.6 | Mock Key2也返回429 | 所有Key限流 | - |
| 4.7 | 发起LLM请求 | 503 NO_AVAILABLE_KEY | error.code正确 |
| 4.8 | 等待60s后Key1冷却到期 | 探活成功→active | - |
| 4.9 | 再次发起LLM请求 | 200 (Key1恢复) | 响应成功 |
| 4.10 | 验证审计日志记录Key切换 | audit_logs有key_rate_limited记录 | DB验证 |

**验收标准**: 故障自动切换，用户无感知，恢复后自动可用

### 场景5: 许可过期续费

**文件**: `tests/e2e/test_scenario5_license_renewal.py`

**用户故事**: 许总的许可即将过期，系统提醒，许总续费后新许可生效。

| 步骤 | 操作 | 预期结果 | 验证点 |
|------|------|----------|--------|
| 5.1 | 准备：激活license，expires_at=NOW+7天 | 许可有效 | - |
| 5.2 | 调用verify接口 | 200, valid=true | - |
| 5.3 | 调整expires_at=NOW-1天（模拟过期） | - | DB更新 |
| 5.4 | 调用verify接口 | 403 LICENSE_EXPIRED | error.code正确 |
| 5.5 | 发起LLM请求 | 403 LICENSE_EXPIRED | - |
| 5.6 | 续费：更新expires_at=NOW+30天, status=active | - | DB更新 |
| 5.7 | 重新激活（同设备） | 200, 新JWT签发 | - |
| 5.8 | 调用verify接口 | 200, valid=true | - |
| 5.9 | 发起LLM请求 | 200 | 许可恢复 |
| 5.10 | 验证旧JWT已加入CRL | 旧JWT返回401 JWT_REVOKED | - |

**验收标准**: 过期拒绝，续费恢复，旧token失效

---

## 5. 性能测试计划

**测试文件**: `tests/performance/`
**测试工具**: Locust
**测试目标**: 验证性能指标达标

### 5.1 API响应时间基线

| 用例ID | 接口 | 并发 | 目标P95 | 目标P99 | 备注 |
|--------|------|------|---------|---------|------|
| PT-001 | GET /api/v1/pro/health | 10 | <100ms | <200ms | 健康检查 |
| PT-002 | POST /api/v1/pro/license/verify | 50 | <200ms | <500ms | JWT验证 |
| PT-003 | GET /api/v1/pro/usage | 50 | <300ms | <500ms | 用量查询 |
| PT-004 | POST /api/v1/pro/relay/llm (非流式) | 20 | <3s | <5s | LLM代理 |
| PT-005 | POST /api/v1/pro/relay/llm (流式TTFB) | 20 | <1.5s | <3s | 首token延迟 |
| PT-006 | POST /api/v1/pro/relay/asr | 10 | <5s | <8s | ASR代理 |
| PT-007 | POST /api/v1/pro/relay/tts | 10 | <3s | <5s | TTS代理 |
| PT-008 | POST /api/v1/pro/relay/ocr | 10 | <5s | <8s | OCR代理 |

### 5.2 并发测试（100并发）

| 用例ID | 场景 | 并发数 | 持续时间 | 目标 | 验证点 |
|--------|------|--------|----------|------|--------|
| PT-010 | 100并发LLM请求 | 100 | 5min | 成功率≥99% | 无5xx错误 |
| PT-011 | 100并发verify请求 | 100 | 5min | P95<200ms | JWT验证性能 |
| PT-012 | 50并发WSS连接 | 50 | 10min | 全部稳定 | 无断连 |
| PT-013 | 100并发用量查询 | 100 | 5min | P95<300ms | 查询性能 |
| PT-014 | 混合并发（LLM+ASR+TTS） | 100 | 10min | 成功率≥99% | 资源隔离 |

### 5.3 压力测试（逐步加压到500并发）

| 用例ID | 场景 | 并发阶梯 | 持续时间 | 目标 | 验证点 |
|--------|------|----------|----------|------|--------|
| PT-020 | LLM逐步加压 | 50→100→200→500 | 每级5min | 找到瓶颈 | QPS峰值 |
| PT-021 | WSS连接逐步加压 | 50→100→200→500 | 每级5min | >500连接 | 连接稳定性 |
| PT-022 | 突发流量 | 0→500瞬间 | 1min | 优雅降级 | 限流生效 |
| PT-023 | Key池压力 | 持续高并发 | 30min | 熔断恢复正常 | Key池稳定 |

### 5.4 长时间稳定性测试（24小时）

| 用例ID | 场景 | 持续时间 | 目标 | 验证点 |
|--------|------|----------|------|--------|
| PT-030 | 24小时持续请求 | 24h | 成功率≥99.9% | 无内存泄漏 |
| PT-031 | 24小时WSS连接 | 24h | 无意外断连 | 心跳稳定 |
| PT-032 | 24小时Key池运行 | 24h | 自动恢复正常 | 熔断冷却正确 |
| PT-033 | 24小时内存监控 | 24h | 内存增长<10% | 无泄漏 |
| PT-034 | 24小时PG连接池 | 24h | 连接数稳定 | 无连接泄漏 |

### 5.5 性能测试Locust脚本示例

```python
# tests/performance/locustfile_llm.py
from locust import HttpUser, task, between

class GatewayUser(HttpUser):
    wait_time = between(1, 3)

    def on_start(self):
        """激活获取JWT"""
        response = self.client.post("/api/v1/pro/license/activate", json={
            "license_key": "PL-PRO-TEST-0001-0001",
            "user_id": "u_test_001",
            "device_fingerprint": "sha256:" + "a"*64
        })
        self.jwt = response.json()["data"]["tokens"]["access_token"]

    @task(10)
    def llm_request(self):
        """LLM请求"""
        self.client.post("/api/v1/pro/relay/llm",
            headers={"Authorization": f"Bearer {self.jwt}"},
            json={
                "provider": "deepseek",
                "model": "deepseek-chat",
                "messages": [{"role": "user", "content": "你好"}],
                "max_tokens": 100
            }
        )

    @task(3)
    def verify_license(self):
        """验证许可"""
        self.client.post("/api/v1/pro/license/verify",
            headers={"Authorization": f"Bearer {self.jwt}"},
            json={"device_fingerprint": "sha256:" + "a"*64}
        )

    @task(1)
    def query_usage(self):
        """查询用量"""
        self.client.get("/api/v1/pro/usage",
            headers={"Authorization": f"Bearer {self.jwt}"}
        )
```

---

## 6. 安全测试计划

**测试文件**: `tests/security/`
**测试目标**: 验证安全机制有效性，与P6安全审查对齐
**原则**: 模拟攻击者视角，验证防护有效性

### 6.1 JWT伪造测试

| 用例ID | 场景 | 攻击方式 | 预期结果 | 优先级 |
|--------|------|----------|----------|--------|
| ST-001 | HS256伪造JWT | 用HS256签名，密钥猜测 | 401 JWT_INVALID（仅RS256） | P0 |
| ST-002 | 篡改JWT payload | 修改user_id | 401 JWT_INVALID（签名不匹配） | P0 |
| ST-003 | 过期JWT重放 | 使用过期JWT | 401 JWT_EXPIRED | P0 |
| ST-004 | CRL中的JWT重放 | 使用已吊销JWT | 401 JWT_REVOKED | P0 |
| ST-005 | 伪造jti | 篡改jti绕过CRL | 401 JWT_INVALID（签名失败） | P0 |
| ST-006 | 无签名JWT | alg=none | 401 JWT_INVALID | P0 |
| ST-007 | 弱密钥暴力破解 | 尝试常见密钥 | RS256非对称，私钥不可猜测 | P1 |
| ST-008 | 跨用户JWT | 用A的JWT访问B资源 | 403（user_id不匹配） | P0 |

### 6.2 API Key泄露测试

| 用例ID | 场景 | 攻击方式 | 预期结果 | 优先级 |
|--------|------|----------|----------|--------|
| ST-010 | 无API Key访问 | 不带X-API-Key | 401 API_KEY_INVALID | P0 |
| ST-011 | 错误API Key | 错误的X-API-Key | 401 API_KEY_INVALID | P0 |
| ST-012 | API Key在URL中 | ?api_key=xxx | 拒绝（仅接受Header） | P1 |
| ST-013 | API Key在日志中 | 检查日志 | 日志不含API Key明文 | P0 |
| ST-014 | API Key加密存储 | 检查DB | api_key_encrypted字段已加密 | P0 |
| ST-015 | API Key传输加密 | 抓包 | HTTPS传输，无明文 | P0 |

### 6.3 速率限制绕过测试

| 用例ID | 场景 | 攻击方式 | 预期结果 | 优先级 |
|--------|------|----------|----------|--------|
| ST-020 | 超限请求 | 101 req/min | 第101个返回429 | P0 |
| ST-021 | IP轮换绕过 | 多IP访问 | 用户级限流仍生效 | P0 |
| ST-022 | 分布式请求 | 多机器并发 | 用户级限流（Redis）生效 | P0 |
| ST-023 | 修改X-Forwarded-For | 伪造IP | Nginx识别真实IP（Cloudflare） | P1 |
| ST-024 | 慢速攻击 | 慢速发送请求 | 连接超时限制 | P1 |
| ST-025 | WSS连接数绕过 | 51个连接/IP | 第51个拒绝 | P0 |

### 6.4 SQL注入测试

| 用例ID | 场景 | 攻击方式 | 预期结果 | 优先级 |
|--------|------|----------|----------|--------|
| ST-030 | license_key注入 | `' OR '1'='1` | 400 INVALID_LICENSE_KEY_FORMAT | P0 |
| ST-031 | user_id注入 | `'; DROP TABLE--` | 400 VALIDATION_ERROR | P0 |
| ST-032 | device_fingerprint注入 | `sha256:' OR 1=1--` | 400 INVALID_DEVICE_FINGERPRINT | P0 |
| ST-033 | 参数化查询验证 | 检查代码 | 全部使用SQLAlchemy参数化 | P0 |
| ST-034 | ORDER BY注入 | ?sort=name;DROP | 参数校验拒绝 | P1 |

### 6.5 其他安全测试

| 用例ID | 场景 | 攻击方式 | 预期结果 | 优先级 |
|--------|------|----------|----------|--------|
| ST-040 | XSS注入 | messages含`<script>` | LLM处理，不执行 | P1 |
| ST-041 | 路径遍历 | `../../../etc/passwd` | 400 VALIDATION_ERROR | P0 |
| ST-042 | 文件上传攻击 | 恶意mp3文件 | 400 INVALID_AUDIO_FORMAT | P0 |
| ST-043 | 大文件DoS | 100MB音频 | 400 AUDIO_TOO_LARGE | P0 |
| ST-044 | TLS强制 | HTTP访问 | 301重定向HTTPS | P0 |
| ST-045 | HSTS头 | 检查响应头 | Strict-Transport-Security存在 | P1 |
| ST-046 | CORS配置 | 跨域请求 | 仅允许指定域名 | P1 |
| ST-047 | 敏感头泄露 | 检查响应头 | 无Server/X-Powered-By | P1 |
| ST-048 | 日志不含PII | 检查日志 | 无电话/邮箱明文 | P0 |
| ST-049 | 审计日志完整 | 检查audit_logs | 关键操作全记录 | P0 |
| ST-050 | 异常用量检测 | 10万Token/小时 | 触发告警+降级 | P0 |

---

## 7. 测试用例清单

### 7.1 单元测试用例

| ID | 类型 | 模块 | 场景 | 优先级 | 预期结果 |
|----|------|------|------|--------|----------|
| UT-KP-001 | 单元 | APIKeyPool | 单Key选择 | P0 | 返回该Key |
| UT-KP-002 | 单元 | APIKeyPool | 多Key加权轮询 | P0 | 选择概率≈权重比 |
| UT-KP-003 | 单元 | APIKeyPool | 健康分影响权重 | P0 | 高健康分Key优先 |
| UT-KP-004 | 单元 | APIKeyPool | RPM影响权重 | P1 | 低RPM Key优先 |
| UT-KP-005 | 单元 | APIKeyPool | 权重计算公式 | P0 | 公式正确 |
| UT-KP-006 | 单元 | APIKeyPool | 1000次选择分布 | P1 | 分布≈理论值 |
| UT-KP-010 | 单元 | APIKeyPool | 成功提升健康分 | P0 | +0.05 |
| UT-KP-011 | 单元 | APIKeyPool | 429降低健康分 | P0 | -0.20 |
| UT-KP-012 | 单元 | APIKeyPool | 5xx降低健康分 | P0 | -0.30 |
| UT-KP-013 | 单元 | APIKeyPool | 超时降低健康分 | P0 | -0.25 |
| UT-KP-014 | 单元 | APIKeyPool | 网络错误降健康分 | P1 | -0.20 |
| UT-KP-015 | 单元 | APIKeyPool | 健康分下限保护 | P0 | 不下溢0.00 |
| UT-KP-016 | 单元 | APIKeyPool | 健康分上限保护 | P0 | 不上溢1.00 |
| UT-KP-017 | 单元 | APIKeyPool | 探活成功提升 | P1 | +0.10 |
| UT-KP-018 | 单元 | APIKeyPool | 探活失败保持 | P1 | 不变 |
| UT-KP-020 | 单元 | APIKeyPool | 429触发冷却 | P0 | rate_limited+60s |
| UT-KP-021 | 单元 | APIKeyPool | 冷却期不选Key | P0 | 被过滤 |
| UT-KP-022 | 单元 | APIKeyPool | 冷却到期探活 | P0 | 触发探活 |
| UT-KP-023 | 单元 | APIKeyPool | 冷却探活成功 | P0 | active+health+0.10 |
| UT-KP-024 | 单元 | APIKeyPool | 冷却探活失败 | P0 | 延长60s |
| UT-KP-025 | 单元 | APIKeyPool | 3次5xx触发熔断 | P0 | circuit_open |
| UT-KP-026 | 单元 | APIKeyPool | 熔断期不选Key | P0 | 被过滤 |
| UT-KP-027 | 单元 | APIKeyPool | 熔断5min后探活 | P0 | 触发探活 |
| UT-KP-028 | 单元 | APIKeyPool | 熔断探活成功 | P0 | active+health=0.50 |
| UT-KP-029 | 单元 | APIKeyPool | 熔断探活失败 | P0 | 重置5min |
| UT-KP-030 | 单元 | APIKeyPool | 管理员禁用Key | P1 | disabled |
| UT-KP-040 | 单元 | APIKeyPool | 并发选择Key | P0 | 无超RPM |
| UT-KP-041 | 单元 | APIKeyPool | 并发健康分更新 | P0 | 无竞态 |
| UT-KP-042 | 单元 | APIKeyPool | 并发熔断触发 | P0 | 计数正确 |
| UT-KP-043 | 单元 | APIKeyPool | RPM计数原子性 | P0 | 计数准确 |
| UT-KP-050 | 单元 | APIKeyPool | 空Key池 | P0 | 返回None |
| UT-KP-051 | 单元 | APIKeyPool | 所有Key不可用 | P0 | 503 |
| UT-KP-052 | 单元 | APIKeyPool | 单Key池 | P0 | 始终该Key |
| UT-KP-053 | 单元 | APIKeyPool | RPM超限过滤 | P0 | 被过滤 |
| UT-KP-054 | 单元 | APIKeyPool | TPM超限过滤 | P1 | 被过滤 |
| UT-KP-055 | 单元 | APIKeyPool | 无指定provider | P1 | 返回None |
| UT-KP-056 | 单元 | APIKeyPool | 重试次数限制 | P0 | 3次后503 |
| UT-LIC-001 | 单元 | LicenseService | 正常激活 | P0 | 200+tokens |
| UT-LIC-002 | 单元 | LicenseService | Key格式错误 | P0 | 400 |
| UT-LIC-003 | 单元 | LicenseService | Key不存在 | P0 | 404 |
| UT-LIC-004 | 单元 | LicenseService | 指纹格式错误 | P0 | 400 |
| UT-LIC-005 | 单元 | LicenseService | 许可过期 | P0 | 410 |
| UT-LIC-006 | 单元 | LicenseService | 许可取消 | P0 | 410 |
| UT-LIC-007 | 单元 | LicenseService | 许可暂停 | P1 | 403 |
| UT-LIC-008 | 单元 | LicenseService | 自动过期 | P0 | UPDATE+410 |
| UT-LIC-009 | 单元 | LicenseService | 已被激活 | P0 | 409 |
| UT-LIC-010 | 单元 | LicenseService | 首次绑定设备 | P0 | 绑定成功 |
| UT-LIC-011 | 单元 | LicenseService | 指纹不匹配 | P0 | 403 |
| UT-LIC-012 | 单元 | LicenseService | 超设备数 | P0 | 409 |
| UT-LIC-013 | 单元 | LicenseService | 激活频繁 | P1 | 429 |
| UT-LIC-014 | 单元 | LicenseService | 签发JWT | P0 | JWT含字段 |
| UT-LIC-015 | 单元 | LicenseService | 签发refresh | P0 | TTL=7天 |
| UT-LIC-016 | 单元 | LicenseService | 审计日志 | P1 | 记录新增 |
| UT-LIC-020 | 单元 | LicenseService | RS256签发 | P0 | alg=RS256 |
| UT-LIC-021 | 单元 | LicenseService | RS256验证 | P0 | 验证通过 |
| UT-LIC-022 | 单元 | LicenseService | 签名无效 | P0 | 401 |
| UT-LIC-023 | 单元 | LicenseService | 格式错误 | P0 | 401 |
| UT-LIC-024 | 单元 | LicenseService | JWT过期 | P0 | 401 |
| UT-LIC-025 | 单元 | LicenseService | CRL黑名单 | P0 | 401 |
| UT-LIC-026 | 单元 | LicenseService | 缺少Auth头 | P0 | 401 |
| UT-LIC-027 | 单元 | LicenseService | jti唯一 | P0 | 每次不同 |
| UT-LIC-028 | 单元 | LicenseService | TTL=15min | P0 | exp=iat+900 |
| UT-LIC-029 | 单元 | LicenseService | 必要字段 | P0 | 全包含 |
| UT-LIC-030 | 单元 | LicenseService | HS256拒绝 | P0 | 401 |
| UT-LIC-040 | 单元 | LicenseService | 首次绑定 | P0 | 绑定成功 |
| UT-LIC-041 | 单元 | LicenseService | 同设备重复 | P0 | 幂等 |
| UT-LIC-042 | 单元 | LicenseService | 不同设备 | P0 | 403 |
| UT-LIC-043 | 单元 | LicenseService | max_devices=2 | P1 | 均成功 |
| UT-LIC-044 | 单元 | LicenseService | 超max_devices | P0 | 409 |
| UT-LIC-045 | 单元 | LicenseService | 指纹格式校验 | P0 | 通过 |
| UT-LIC-046 | 单元 | LicenseService | 指纹格式错误 | P0 | 400 |
| UT-LIC-050 | 单元 | LicenseService | JWT加入CRL | P0 | Redis存在 |
| UT-LIC-051 | 单元 | LicenseService | CRL TTL | P0 | =剩余有效期 |
| UT-LIC-052 | 单元 | LicenseService | CRL拒绝 | P0 | 401 |
| UT-LIC-053 | 单元 | LicenseService | CRL过期清理 | P1 | 自动删除 |
| UT-LIC-054 | 单元 | LicenseService | 管理员吊销 | P0 | JWT全CRL |
| UT-LIC-055 | 单元 | LicenseService | 吊销断WSS | P0 | 发消息+关闭 |
| UT-LIC-060 | 单元 | LicenseService | 无感刷新 | P0 | 新JWT+旧CRL |
| UT-LIC-061 | 单元 | LicenseService | 不需刷新 | P0 | 返回当前 |
| UT-LIC-062 | 单元 | LicenseService | refresh刷新 | P0 | 新access+refresh |
| UT-LIC-063 | 单元 | LicenseService | refresh过期 | P0 | 401 |
| UT-LIC-064 | 单元 | LicenseService | refresh在CRL | P0 | 401 |
| UT-LIC-065 | 单元 | LicenseService | 旧JWT失效 | P0 | 加入CRL |
| UT-BIL-001 | 单元 | BillingService | 正常配额 | P0 | green |
| UT-BIL-002 | 单元 | BillingService | 接近上限 | P0 | yellow |
| UT-BIL-003 | 单元 | BillingService | 超限 | P0 | red+402 |
| UT-BIL-004 | 单元 | BillingService | 超限>100% | P0 | red+402 |
| UT-BIL-005 | 单元 | BillingService | 边界79.99% | P0 | green |
| UT-BIL-006 | 单元 | BillingService | 边界80% | P0 | yellow |
| UT-BIL-007 | 单元 | BillingService | 边界99.99% | P0 | yellow |
| UT-BIL-008 | 单元 | BillingService | 边界100% | P0 | red |
| UT-BIL-009 | 单元 | BillingService | ASR配额 | P0 | 402 |
| UT-BIL-010 | 单元 | BillingService | TTS配额 | P0 | 402 |
| UT-BIL-011 | 单元 | BillingService | OCR配额 | P0 | 402 |
| UT-BIL-012 | 单元 | BillingService | LLM超限不影响ASR | P0 | ASR放行 |
| UT-BIL-020 | 单元 | BillingService | 记录LLM用量 | P0 | total=230 |
| UT-BIL-021 | 单元 | BillingService | 更新配额 | P0 | 原子操作 |
| UT-BIL-022 | 单元 | BillingService | 月度汇总 | P0 | UPSERT |
| UT-BIL-023 | 单元 | BillingService | Redis缓存 | P1 | HINCRBY |
| UT-BIL-024 | 单元 | BillingService | DeepSeek成本 | P0 | 0.00023 |
| UT-BIL-025 | 单元 | BillingService | Moka成本 | P0 | 0.00046 |
| UT-BIL-026 | 单元 | BillingService | 异步不阻塞 | P1 | 响应快 |
| UT-BIL-027 | 单元 | BillingService | ASR用量 | P0 | +1 |
| UT-BIL-028 | 单元 | BillingService | TTS用量 | P0 | +1 |
| UT-BIL-029 | 单元 | BillingService | OCR用量 | P0 | +1 |
| UT-BIL-030 | 单元 | BillingService | 失败不记录 | P0 | 不更新 |
| UT-BIL-040 | 单元 | BillingService | 月初重置 | P0 | 归零 |
| UT-BIL-041 | 单元 | BillingService | 归档上月 | P0 | monthly_usage |
| UT-BIL-042 | 单元 | BillingService | 清理缓存 | P1 | DEL |
| UT-BIL-043 | 单元 | BillingService | 生成账单 | P1 | JSON |
| UT-BIL-044 | 单元 | BillingService | 历史保留 | P0 | 不删除 |
| UT-BIL-045 | 单元 | BillingService | 幂等重置 | P0 | 不重复 |
| UT-BIL-050 | 单元 | BillingService | green→yellow | P0 | 通知+审计 |
| UT-BIL-051 | 单元 | BillingService | yellow→red | P0 | 通知+邮件+钉钉 |
| UT-BIL-052 | 单元 | BillingService | green→red | P1 | 直接red |
| UT-BIL-053 | 单元 | BillingService | yellow响应头 | P0 | X-Quota-Warning |
| UT-BIL-054 | 单元 | BillingService | red拒绝AI | P0 | 402 |
| UT-BIL-055 | 单元 | BillingService | red不拒非AI | P1 | usage可访问 |
| UT-BIL-056 | 单元 | BillingService | 重置red→green | P0 | green |
| UT-RLY-001 | 单元 | AIProxy | 正常LLM非流式 | P0 | 200 |
| UT-RLY-002 | 单元 | AIProxy | 正常LLM流式 | P0 | SSE |
| UT-RLY-003 | 单元 | AIProxy | LLM超时 | P0 | 504+重试 |
| UT-RLY-004 | 单元 | AIProxy | LLM 5xx | P0 | 重试+502 |
| UT-RLY-005 | 单元 | AIProxy | LLM 429 | P0 | 冷却+切换 |
| UT-RLY-006 | 单元 | AIProxy | LLM网络错误 | P0 | 重试 |
| UT-RLY-007 | 单元 | AIProxy | 请求体校验 | P0 | 400 |
| UT-RLY-008 | 单元 | AIProxy | max_tokens超限 | P1 | 400 |
| UT-RLY-009 | 单元 | AIProxy | temperature超范围 | P1 | 400 |
| UT-RLY-010 | 单元 | AIProxy | messages超50条 | P1 | 400 |
| UT-RLY-011 | 单元 | AIProxy | 无可用Key | P0 | 503 |
| UT-RLY-012 | 单元 | AIProxy | 重试3次放弃 | P0 | 503 |
| UT-RLY-020 | 单元 | AIProxy | 正常ASR | P0 | 200+text |
| UT-RLY-021 | 单元 | AIProxy | ASR格式不支持 | P0 | 400 |
| UT-RLY-022 | 单元 | AIProxy | ASR过大 | P0 | 400 |
| UT-RLY-023 | 单元 | AIProxy | ASR时长不足 | P0 | 400 |
| UT-RLY-024 | 单元 | AIProxy | ASR时长超限 | P0 | 400 |
| UT-RLY-025 | 单元 | AIProxy | ASR配额超限 | P0 | 402 |
| UT-RLY-026 | 单元 | AIProxy | 正常TTS | P0 | audio/mpeg |
| UT-RLY-027 | 单元 | AIProxy | TTS文本过长 | P0 | 400 |
| UT-RLY-028 | 单元 | AIProxy | TTS配额超限 | P0 | 402 |
| UT-RLY-029 | 单元 | AIProxy | 正常OCR | P0 | structured |
| UT-RLY-030 | 单元 | AIProxy | OCR格式不支持 | P0 | 400 |
| UT-RLY-031 | 单元 | AIProxy | OCR过大 | P0 | 400 |
| UT-RLY-032 | 单元 | AIProxy | OCR配额超限 | P0 | 402 |
| UT-RLY-040 | 单元 | AIProxy | DeepSeek降级Moka | P0 | X-Degraded |
| UT-RLY-041 | 单元 | AIProxy | 模型降级 | P1 | lite |
| UT-RLY-042 | 单元 | AIProxy | 全Provider失败 | P0 | 503 |
| UT-RLY-043 | 单元 | AIProxy | 降级标记 | P0 | X-Degraded |
| UT-RLY-044 | 单元 | AIProxy | 降级计费 | P1 | 按Moka |
| UT-RLY-050 | 单元 | AIProxy | SSE事件格式 | P0 | token+done |
| UT-RLY-051 | 单元 | AIProxy | token事件 | P0 | content+index |
| UT-RLY-052 | 单元 | AIProxy | done事件 | P0 | usage+billing |
| UT-RLY-053 | 单元 | AIProxy | error事件 | P0 | code+message |
| UT-RLY-054 | 单元 | AIProxy | 响应头 | P0 | text/event-stream |
| UT-RLY-055 | 单元 | AIProxy | 禁Nginx缓冲 | P1 | X-Accel-Buffering |
| UT-RLY-056 | 单元 | AIProxy | 逐token转发 | P1 | 立即flush |
| UT-RLY-057 | 单元 | AIProxy | 流式用量记录 | P0 | 异步记录 |
| UT-RLY-058 | 单元 | AIProxy | 客户端断开 | P0 | 取消上游 |

### 7.2 集成测试用例

| ID | 类型 | 模块 | 场景 | 优先级 | 预期结果 |
|----|------|------|------|--------|----------|
| IT-001 | 集成 | 全链路 | LLM调用链 | P0 | 全流程200 |
| IT-002 | 集成 | 全链路 | ASR调用链 | P0 | 全流程200 |
| IT-003 | 集成 | 全链路 | TTS调用链 | P0 | 全流程200 |
| IT-004 | 集成 | 全链路 | OCR调用链 | P0 | 全流程200 |
| IT-005 | 集成 | 全链路 | JWT无感刷新 | P0 | 新JWT+旧CRL |
| IT-006 | 集成 | 全链路 | refresh刷新 | P0 | 新access |
| IT-010 | 集成 | Key池 | 单Key 429切换 | P0 | 切换成功 |
| IT-011 | 集成 | Key池 | 单Key 5xx熔断 | P0 | 熔断+切换 |
| IT-012 | 集成 | Key池 | DeepSeek降级Moka | P0 | X-Degraded |
| IT-013 | 集成 | Key池 | 所有Key失败 | P0 | 503 |
| IT-014 | 集成 | Key池 | 冷却后恢复 | P0 | Key可用 |
| IT-015 | 集成 | Key池 | 熔断后恢复 | P0 | Key可用 |
| IT-020 | 集成 | 配额 | LLM配额耗尽 | P0 | 402 |
| IT-021 | 集成 | 配额 | 黄灯警告 | P0 | 放行+警告头 |
| IT-022 | 集成 | 配额 | 红灯拒绝 | P0 | 402 |
| IT-023 | 集成 | 配额 | ASR不影响LLM | P0 | LLM正常 |
| IT-024 | 集成 | 配额 | 月初重置 | P0 | 恢复 |
| IT-025 | 集成 | 配额 | 状态变更告警 | P0 | 通知+审计 |
| IT-030 | 集成 | 并发 | 100并发LLM | P0 | 成功或限流 |
| IT-031 | 集成 | 并发 | 并发选Key | P0 | 无超RPM |
| IT-032 | 集成 | 并发 | 并发用量记录 | P0 | 准确 |
| IT-033 | 集成 | 并发 | 并发激活 | P0 | 1成功1失败 |
| IT-034 | 集成 | 并发 | 限流触发 | P0 | 429 |
| IT-040 | 集成 | 事务 | 激活原子性 | P0 | 无部分写入 |
| IT-041 | 集成 | 事务 | 用量原子性 | P0 | 同成功失败 |
| IT-042 | 集成 | 事务 | 重置原子性 | P0 | 无部分重置 |
| IT-043 | 集成 | 事务 | 并发配额更新 | P0 | 准确 |
| IT-044 | 集成 | 事务 | FOR UPDATE锁 | P0 | 串行化 |

### 7.3 E2E测试用例

| ID | 类型 | 场景 | 优先级 | 预期结果 |
|----|------|------|--------|----------|
| E2E-1 | E2E | 许总激活专业版 | P0 | 10步全通过 |
| E2E-2 | E2E | 语音助手完整流程 | P0 | 全流程<10s |
| E2E-3 | E2E | 配额管理三态 | P0 | 三态切换正确 |
| E2E-4 | E2E | Key池故障恢复 | P0 | 自动切换+恢复 |
| E2E-5 | E2E | 许可过期续费 | P0 | 过期拒绝+续费恢复 |

### 7.4 性能测试用例

| ID | 类型 | 场景 | 优先级 | 预期结果 |
|----|------|------|--------|----------|
| PT-001~008 | 性能 | API响应基线 | P0 | P95达标 |
| PT-010~014 | 性能 | 100并发 | P0 | 成功率≥99% |
| PT-020~023 | 性能 | 压力测试 | P1 | 找到瓶颈 |
| PT-030~034 | 性能 | 24小时稳定 | P1 | 成功率≥99.9% |

### 7.5 安全测试用例

| ID | 类型 | 场景 | 优先级 | 预期结果 |
|----|------|------|--------|----------|
| ST-001~008 | 安全 | JWT伪造 | P0 | 全部拒绝 |
| ST-010~015 | 安全 | API Key泄露 | P0 | 全部防护 |
| ST-020~025 | 安全 | 限流绕过 | P0 | 限流生效 |
| ST-030~034 | 安全 | SQL注入 | P0 | 全部拒绝 |
| ST-040~050 | 安全 | 其他安全 | P0 | 全部防护 |

### 7.6 测试用例统计

| 类型 | 用例数 | P0 | P1 | 预估工时 |
|------|--------|----|----|----------|
| 单元测试 | 156 | 128 | 28 | 8人日 |
| 集成测试 | 29 | 29 | 0 | 4人日 |
| E2E测试 | 5 | 5 | 0 | 3人日 |
| 性能测试 | 19 | 13 | 6 | 3人日 |
| 安全测试 | 36 | 30 | 6 | 3人日 |
| **合计** | **245** | **205** | **40** | **21人日** |

---

## 8. 测试自动化

### 8.1 CI/CD集成方案

**文件路径**: `.github/workflows/gateway-ci.yml`

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
  lint-typecheck:
    runs-on: ubuntu-latest
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
      - name: Lint (ruff)
        run: cd gateway && ruff check .
      - name: Type check (mypy)
        run: cd gateway && mypy .

  unit-test:
    runs-on: ubuntu-latest
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
      - name: Run unit tests
        run: cd gateway && pytest tests/unit/ -v --cov=src --cov-report=xml --cov-report=term
      - name: Upload coverage
        uses: codecov/codecov-action@v4
        with:
          file: gateway/coverage.xml
          fail_ci_if_error: true

  integration-test:
    runs-on: ubuntu-latest
    services:
      postgres:
        image: postgres:16-alpine
        env:
          POSTGRES_DB: gateway_test
          POSTGRES_USER: test
          POSTGRES_PASSWORD: test
        ports: ['5432:5432']
        options: >-
          --health-cmd pg_isready
          --health-interval 10s
          --health-timeout 5s
          --health-retries 5
      redis:
        image: redis:7-alpine
        ports: ['6379:6379']
        options: >-
          --health-cmd "redis-cli ping"
          --health-interval 10s
          --health-timeout 5s
          --health-retries 5
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
      - name: Run integration tests
        run: cd gateway && pytest tests/integration/ -v
        env:
          DATABASE_URL: postgresql://test:test@localhost:5432/gateway_test
          REDIS_URL: redis://localhost:6379/0

  e2e-test:
    runs-on: ubuntu-latest
    needs: [unit-test, integration-test]
    services:
      postgres:
        image: postgres:16-alpine
        env:
          POSTGRES_DB: gateway_e2e
          POSTGRES_USER: test
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
      - name: Run E2E tests
        run: cd gateway && pytest tests/e2e/ -v
        env:
          DATABASE_URL: postgresql://test:test@localhost:5432/gateway_e2e
          REDIS_URL: redis://localhost:6379/0

  security-test:
    runs-on: ubuntu-latest
    needs: [unit-test]
    services:
      postgres:
        image: postgres:16-alpine
        env:
          POSTGRES_DB: gateway_security
          POSTGRES_USER: test
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
      - name: Run security tests
        run: cd gateway && pytest tests/security/ -v
        env:
          DATABASE_URL: postgresql://test:test@localhost:5432/gateway_security
          REDIS_URL: redis://localhost:6379/0

  build:
    needs: [lint-typecheck, unit-test, integration-test, e2e-test, security-test]
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
```

### 8.2 测试报告生成

**pytest配置** (`gateway/pytest.ini`):

```ini
[pytest]
asyncio_mode = auto
testpaths = tests
python_files = test_*.py
python_classes = Test*
python_functions = test_*
addopts =
    -v
    --tb=short
    --strict-markers
    --cov=src
    --cov-report=term-missing
    --cov-report=html:reports/coverage
    --cov-report=xml:reports/coverage.xml
    --cov-fail-under=80
    --html=reports/report.html
    --self-contained-html
    --alluredir=reports/allure
markers =
    unit: 单元测试
    integration: 集成测试
    e2e: E2E测试
    performance: 性能测试
    security: 安全测试
    slow: 慢测试
```

**测试命令**:

```bash
# 全部测试
pytest

# 仅单元测试
pytest tests/unit/ -m unit

# 仅集成测试
pytest tests/integration/ -m integration

# 仅E2E测试
pytest tests/e2e/ -m e2e

# 仅安全测试
pytest tests/security/ -m security

# 性能测试（手动触发）
pytest tests/performance/ -m performance --slow

# 生成报告
pytest --html=reports/report.html --cov=src --cov-report=html
```

### 8.3 覆盖率报告

**覆盖率目标**:

| 模块 | 目标 | 当前 |
|------|------|------|
| `src/services/api_key_pool.py` | ≥95% | - |
| `src/services/license_service.py` | ≥95% | - |
| `src/services/billing_service.py` | ≥95% | - |
| `src/services/ai_proxy.py` | ≥90% | - |
| `src/services/relay_router.py` | ≥90% | - |
| `src/core/jwt_handler.py` | ≥95% | - |
| `src/core/crypto.py` | ≥95% | - |
| `src/middleware/` | ≥90% | - |
| `src/api/v1/` | ≥85% | - |
| **整体** | **≥80%** | - |

**覆盖率报告查看**:

```bash
# 生成HTML报告
pytest --cov=src --cov-report=html:reports/coverage

# 查看报告
open reports/coverage/index.html
```

### 8.4 测试数据管理

**Fixtures目录**: `tests/fixtures/`

| 文件 | 用途 | 说明 |
|------|------|------|
| `licenses.json` | 测试许可证数据 | 含active/expired/cancelled等状态 |
| `api_keys.json` | 测试API Key数据 | 含active/rate_limited/circuit_open状态 |
| `audio_samples/` | ASR测试音频 | mp3/wav/m4a各2个 |
| `image_samples/` | OCR测试图片 | 名片/文档各2个 |
| `jwt_keys/` | 测试RSA密钥对 | 私钥+公钥 |

**Fixture示例** (`tests/conftest.py`):

```python
import pytest
import pytest_asyncio
from fakeredis import aioredis as fakeredis
from testcontainers.postgres import PostgresContainer

@pytest.fixture
async def fake_redis():
    """单元测试用Mock Redis"""
    redis = fakeredis.FakeRedis()
    yield redis
    await redis.flushall()

@pytest.fixture
async def test_db():
    """集成测试用PG容器"""
    with PostgresContainer("postgres:16-alpine") as pg:
        yield pg.get_connection_url()

@pytest.fixture
def test_license_key():
    """测试用license_key"""
    return "PL-PRO-TEST-0001-0001"

@pytest.fixture
def test_device_fingerprint():
    """测试用设备指纹"""
    return "sha256:" + "a" * 64

@pytest.fixture
def test_jwt_keys():
    """测试用RSA密钥对"""
    # 从fixtures/jwt_keys/加载
    pass
```

---

## 9. 验收标准

### 9.1 功能验收标准

| 验收项 | 标准 | 验证方法 |
|--------|------|----------|
| 单元测试覆盖率 | ≥80% | pytest --cov报告 |
| 关键模块覆盖率 | ≥95% | APIKeyPool/LicenseService/BillingService |
| 集成测试通过率 | 100% | pytest tests/integration/ |
| E2E测试通过率 | 100% | 5个场景全通过 |
| 安全测试通过率 | 100% | P0用例全通过 |

### 9.2 性能验收标准

| 指标 | 目标 | 验证方法 |
|------|------|----------|
| 健康检查延迟 | P95 < 100ms | Locust压测 |
| JWT验证延迟 | P95 < 200ms | Locust压测 |
| LLM代理P95 | < 3秒 | Locust压测 |
| LLM流式TTFB | P95 < 1.5秒 | Locust压测 |
| 网关QPS | > 100 | Locust压测 |
| 并发WSS连接 | > 500 | Locust压测 |
| 24小时稳定性 | 成功率≥99.9% | 长时间压测 |
| 内存增长 | <10% | 24小时监控 |

### 9.3 安全验收标准

| 验收项 | 标准 | 验证方法 |
|--------|------|----------|
| JWT伪造防护 | 全部拒绝 | 安全测试 |
| SQL注入防护 | 全部拒绝 | 安全测试 |
| 速率限制 | 100 req/min生效 | 安全测试 |
| API Key加密 | 存储加密 | 代码审查 |
| PII不落盘 | 日志无PII | 日志审查 |
| 无P0/P1漏洞 | 0个 | 安全测试 |

### 9.4 发布前检查清单

**发布前必须完成**（用户规则3要求）：

- [ ] 所有单元测试通过（≥80%覆盖率）
- [ ] 所有集成测试通过（100%）
- [ ] 所有E2E测试通过（100%，5个场景）
- [ ] 所有安全测试通过（P0用例100%）
- [ ] 性能测试达标（P95<3秒，QPS>100）
- [ ] 24小时稳定性测试通过
- [ ] **模拟真实用户使用的E2E测试通过**（5个场景）
- [ ] CI/CD pipeline全绿
- [ ] 代码审查通过（ruff+mypy无错误）
- [ ] 文档更新完成（API文档+部署文档）
- [ ] 监控告警配置完成
- [ ] 备份策略验证通过
- [ ] 灾难恢复演练通过

### 9.5 测试铁律检查

- [ ] **未修改断言来通过测试** — 所有断言基于需求，非实现
- [ ] **未为通过测试而mock核心逻辑** — 核心业务路径真实执行
- [ ] **测试覆盖正常+边界+错误场景** — 三态全覆盖
- [ ] **E2E测试模拟真实用户** — 从用户视角验证
- [ ] **发布前做了模拟真实用户使用的测试** — 5个E2E场景

---

## 10. 风险与缓解

### 10.1 测试风险

| 风险 | 概率 | 影响 | 缓解措施 |
|------|------|------|----------|
| LLM API不稳定导致测试flaky | 高 | 中 | Mock LLM API，仅E2E用真实API |
| 并发测试竞态问题 | 中 | 高 | 充分mock+多次重试验证 |
| 性能测试环境差异 | 中 | 中 | 标准化Docker环境，记录基线 |
| 24小时测试成本高 | 低 | 低 | 分批次执行，CI夜间任务 |
| 安全测试遗漏 | 中 | 高 | 参考OWASP Top10，外部审计 |

### 10.2 测试依赖风险

| 依赖 | 风险 | 缓解 |
|------|------|------|
| DeepSeek API | 限流/不可用 | Mock + 预留真实API配额 |
| Moka AI API | 限流/不可用 | Mock + 预留真实API配额 |
| PostgreSQL | 版本差异 | Docker固定16-alpine |
| Redis | 版本差异 | Docker固定7-alpine |

---

## 11. 附录

### 11.1 测试用例命名规范

```
{类型}-{模块}-{序号}

类型：
- UT: Unit Test (单元测试)
- IT: Integration Test (集成测试)
- E2E: End-to-End Test
- PT: Performance Test (性能测试)
- ST: Security Test (安全测试)

模块：
- KP: API Key Pool
- LIC: License Service
- BIL: Billing Service
- RLY: Relay/AIProxy
```

### 11.2 测试数据准备脚本

**文件路径**: `gateway/scripts/seed_test_data.py`

```python
"""初始化测试数据"""
import asyncio
from src.models.database import engine
from src.models.tables import License, ApiKey, User
from src.core.crypto import encrypt_api_key

async def seed():
    async with engine.begin() as conn:
        # 创建测试用户
        # 创建测试许可证（各种状态）
        # 创建测试API Key池
        pass

if __name__ == "__main__":
    asyncio.run(seed())
```

### 11.3 参考文档

- `docs/architecture/Pro_Edition_Tech_Design_Phase0.md` v1.0 — P3技术设计
- `docs/architecture/Pro_Edition_Architecture.md` v1.1 — 专业版架构
- `docs/spec/PRD_Pro_Edition_v1.md` v1.0 — 专业版PRD
- `docs/planning/Pro_Edition_Implementation_Plan.md` v1.0 — 实现计划
- `docs/planning/Pro_Edition_Review_Report.md` — P2 Review报告
- `docs/design/Test_Plan_v1.md` v5.1 — 基础版测试计划（参考风格）

### 11.4 变更记录

| 版本 | 日期 | 变更内容 |
|------|------|----------|
| v1.0 | 2026-06-17 | 初始版本，P7测试计划阶段交付，覆盖Phase 0云端AI网关全部测试设计 |

---

*文档结束 | PromiseLink专业版Phase 0测试计划 v1.0 | P7测试计划阶段*
