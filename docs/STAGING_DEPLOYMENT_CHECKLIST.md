# PromiseLink Staging 部署清单

> 创建时间: 2026-07-06
> 更新时间: 2026-07-07 (Phase 6 完成 — CI 镜像部署 + E2E 全通过)
> 目标服务器: 47.116.219.15
> 目标域名: www.promiselink.cn
> 版本: v0.8.0-rc2

## ⚠️ 已知阻塞: ICP 备案

**状态**: www.promiselink.cn 未完成 ICP 备案，阿里云在网络层拦截域名访问

**影响**:
- HTTP 访问 (http://www.promiselink.cn) → 返回阿里云"未备案"拦截页面
- HTTPS 访问 (https://www.promiselink.cn) → TLS 握手被 `Connection reset by peer`
- 服务器本身完全正常 (IP 直连可用)

**验证**: `curl http://47.116.219.15/api/v1/health` 正常返回，证明服务器配置无误

**解决方案 (待决策)**:
1. 完成 ICP 备案 (需营业执照，1-3 周)
2. 迁移服务器到香港/新加坡 (无需 ICP)
3. 临时使用 IP 直连 (当前 E2E 验证方案)

**当前 E2E 验证**: 使用 `E2E_BASE_URL=http://47.116.219.15` (nginx 已配置 HTTP API 代理)

## 前置条件

### 已完成
- [x] DNS A 记录已添加 (www.promiselink.cn → 47.116.219.15)
- [x] docker-compose.prod.yml 已就绪 (ghcr.io 镜像 + nginx + certbot, bind mount, 127.0.0.1 端口绑定)
- [x] nginx/conf.d/default.conf 已配置 (HTTP→HTTPS 重定向 + 反向代理, SSL 路径 live/www.promiselink.cn/)
- [x] deploy-prod.sh 部署脚本 (含备份、健康检查、自动回滚 + DB 恢复)
- [x] .env.prod.example 配置模板
- [x] scripts/ops/init-ssl.sh SSL 证书初始化脚本 (幂等, 含证书有效性检查)
- [x] CI/CD build-and-push job (.github/workflows/ci.yml, push to main 自动触发)
- [x] 后端测试零 skip: 1823 passed / 0 failed / 0 skipped

### 待执行 (Staging 后处理)
- [ ] SSH 私钥轮换 (当前密钥曾暴露, staging 验证后立即轮换)
- [ ] WeChat AppSecret 轮换 (同上)
- [ ] GitHub Secrets 配置 (STAGING_SSH_KEY、STAGING_HOST 等, 用于 CI 自动部署)
- [ ] SSH 防火墙限制 ( staging 期间限制源 IP 或改非标端口, 不依赖密钥轮换)

## Staging 部署步骤

### Phase 0: 确认 CI 镜像已构建 (在本地执行)

```bash
# 0.1 确认 commit 4916e9d 已推送到 origin/main
git log --oneline origin/main -1

# 0.2 检查 GitHub Actions build-and-push job 状态
gh run list --workflow=ci.yml --limit=3
# 确认 build-and-push job 为 success

# 0.3 验证镜像存在 (可选, 需要 docker login ghcr.io)
docker pull ghcr.io/lulin70/promiselink:0.8.0-rc2
# 如果镜像不存在, 等待 CI 完成或手动构建
```

### Phase 1: 服务器初始化 (在 47.116.219.15 上执行)

```bash
# 1.1 登录服务器
ssh root@47.116.219.15

# 1.2 创建部署目录 (bind mount 路径, 与 docker-compose.prod.yml 一致)
mkdir -p /opt/promiselink/{data,backups,certbot/{conf,www}}
cd /opt/promiselink

# 1.3 安装 Docker (如未安装)
curl -fsSL https://get.docker.com | sh
systemctl enable --now docker

# 1.4 防火墙开放端口 (仅 80/443, SSH 端口保留但建议限制源 IP)
firewall-cmd --permanent --add-port=80/tcp
firewall-cmd --permanent --add-port=443/tcp
firewall-cmd --reload

# 1.5 (推荐) 限制 SSH 源 IP (不依赖密钥轮换的独立缓解措施)
# firewall-cmd --permanent --add-rich-rule='rule family="ipv4" source address="<your-ip>" service name="ssh" accept'
# firewall-cmd --permanent --remove-service=ssh
# firewall-cmd --reload
```

### Phase 2: 配置文件上传 (在本地执行)

```bash
# 2.1 上传部署文件
cd /Users/lin/trae_projects/PromiseLink
scp docker-compose.prod.yml root@47.116.219.15:/opt/promiselink/
scp -r nginx/ root@47.116.219.15:/opt/promiselink/
scp scripts/ops/init-ssl.sh root@47.116.219.15:/opt/promiselink/
scp scripts/ops/deploy-prod.sh root@47.116.219.15:/opt/promiselink/

# 2.2 创建 .env.prod (在服务器上执行, 不要上传)
ssh root@47.116.219.15
cd /opt/promiselink
cat > .env.prod << EOF
APP_ENV=production
SECRET_KEY=$(python3 -c "import secrets; print(secrets.token_urlsafe(32))")
POC_SECRET=$(python3 -c "import secrets; print(secrets.token_urlsafe(16))")
LLM_PROVIDER=moka_ai
LLM_API_KEY=<填入真实 Moka AI API Key>
LLM_TIMEOUT=60
LLM_MAX_RETRIES=5
LLM_MAX_TOKENS=4000
LOG_LEVEL=INFO
CORS_ORIGINS=["https://www.promiselink.cn","https://promiselink.cn"]
APP_EDITION=basic
EOF
chmod 600 .env.prod

# 2.3 记录 POC_SECRET (后续 E2E 测试需要)
grep POC_SECRET .env.prod
```

### Phase 3: SSL 证书初始化 (在服务器上执行)

```bash
# 3.1 确认 DNS 已生效
dig www.promiselink.cn +short
# 应返回 47.116.219.15

# 3.2 获取 SSL 证书 (幂等, 重复运行会跳过)
cd /opt/promiselink
chmod +x init-ssl.sh
./init-ssl.sh www.promiselink.cn admin@promiselink.cn

# 脚本会:
#   0. 检查证书是否已存在且有效 (>30天), 是则跳过
#   1. 停止 nginx (释放 80 端口)
#   2. certbot standalone 模式获取证书 (签发到 live/www.promiselink.cn/)
#   3. 启动完整 docker-compose stack
#   4. 验证 HTTPS 健康检查
```

### Phase 4: 部署应用 (在本地或服务器上执行)

```bash
# 4.1 使用 deploy-prod.sh 部署 (推荐, 含备份+回滚+DB恢复)
cd /Users/lin/trae_projects/PromiseLink
./scripts/ops/deploy-prod.sh 47.116.219.15 root 0.8.0-rc2

# 或在服务器上直接部署
ssh root@47.116.219.15
cd /opt/promiselink
VERSION=0.8.0-rc2 REGISTRY_OWNER=lulin70 docker compose -f docker-compose.prod.yml pull
VERSION=0.8.0-rc2 REGISTRY_OWNER=lulin70 docker compose -f docker-compose.prod.yml up -d --remove-orphans
```

### Phase 5: 验证

```bash
# 5.1 健康检查 (通过 IP — 域名因 ICP 备案被拦截)
curl -sf http://47.116.219.15/api/v1/health | jq .
# 服务器本地 HTTPS 验证 (确认 SSL 证书有效)
ssh root@47.116.219.15 "curl -sf https://localhost/api/v1/health --resolve www.promiselink.cn:443:127.0.0.1"

# 5.2 容器状态
ssh root@47.116.219.15 "docker compose -f /opt/promiselink/docker-compose.prod.yml ps"
# 预期: promiselink-api (healthy), promiselink-nginx (Up), promiselink-certbot (Up)

# 5.3 功能验证 (登录 + 创建事件)
POC_SECRET=$(ssh root@47.116.219.15 "grep POC_SECRET /opt/promiselink/.env.prod" | cut -d= -f2)
curl -X POST http://47.116.219.15/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d "{\"user_id\":\"staging-test-user\",\"poc_secret\":\"${POC_SECRET}\"}"

# 5.4 确认 API 端口不暴露公网 (应连接超时或拒绝)
curl -sf --connect-timeout 3 http://47.116.219.15:8000/ && echo "WARNING: API port exposed!" || echo "OK: API port not exposed"
```

**Phase 5 验证结果 (2026-07-06)**:
- ✅ 健康检查: API healthy, 版本 0.8.0-rc2
- ✅ 容器状态: 3 容器全部 Up (api healthy, nginx, certbot)
- ✅ 登录功能: JWT token 正常签发
- ✅ API 端口隔离: 8000 端口绑定 127.0.0.1，不暴露公网
- ⚠️ 域名访问: ICP 备案未完成，域名被阿里云拦截 (见上方"已知阻塞")
- ✅ IP 直连: http://47.116.219.15/api/* 正常工作 (nginx 配置 HTTP API 代理)

### Phase 6: CI 镜像部署 + E2E 全通过 (2026-07-07)

**根因修复**: QueuePool 耗尽导致 500 错误
- 问题: Pipeline 步骤在 LLM 调用期间持有 DB session (最长 300s)，QueuePool (15 连接) 在并发 pipeline 下耗尽
- 修复: SQLite 引擎从 `AsyncAdaptedQueuePool` 改为 `NullPool` (commit 0d5bfe2)
- 效果: 每次会话创建新连接，用完即关，无连接池耗尽风险

**部署方式**: CI 构建镜像直接部署 (不再使用 volume mount 补丁)
- 镜像: `ghcr.io/lulin70/promiselink:0.8.0-rc2` (CI build ID de0c315dcdc7)
- 包含 3 项修复: NullPool (database.py) + commit_with_retry (events.py) + TRUSTED_PROXIES CIDR (dependencies.py)
- 验证: `docker run --rm ghcr.io/lulin70/promiselink:0.8.0-rc2 sh -c 'grep -c NullPool /app/src/promiselink/database.py'` → 4

**E2E 测试结果 (2026-07-07, CI 镜像)**:
- Pipeline E2E: 6/6 PASSED ✅ (132.65s)
- POC 综合: 24/24 PASSED ✅ (95.67s)
- 本地单元测试: 55/55 PASSED ✅ (8.50s)
- CI 核心任务: security ✓ / test (3.11) ✓ / frontend ✓ / build-and-push ✓
- CI E2E 任务: X (预期失败 — CI 使用假 LLM_API_KEY, 需后续添加 LLM mock)

### Phase 7: 前端部署 + 完整用户旅程验证 (2026-07-07)

**部署内容**: 前端静态文件部署到 nginx，实现完整系统跑通
- 上传: `frontend/dist/*` → `/opt/promiselink/frontend/` (Taro H5 构建产物)
- docker-compose: nginx 服务增加 volume 挂载 `/opt/promiselink/frontend:/usr/share/nginx/html:ro`
- nginx 配置: HTTP/HTTPS `/` 服务前端静态文件，`/api/` 代理后端，`try_files $uri $uri/ /index.html` 支持 SPA 路由
- HTTP 不再强制跳转 HTTPS (ICP 拦截域名，IP 直连需 HTTP)

**完整用户旅程验证** (登录 → 创建事件 → Pipeline → 结果展示):
- 登录: JWT token 正常签发 ✓
- 事件创建: event_id=6939fa24... ✓
- Pipeline 完成: 13s (Moka AI LLM) ✓
- 结果: 1 人脉 (王总) + 1 承诺 (明天发送技术方案) + 3 待办 (合作信号/承诺/关注) ✓

**E2E 测试结果 (2026-07-07, 前端部署后)**:
- 后端 Pipeline E2E: 6/6 PASSED ✅ (61.15s)
- 后端 POC 综合: 24/24 PASSED ✅ (138.70s)
- 前端 Playwright (auth+home): 12/12 PASSED ✅ (49.5s)
- 前端 Playwright (events+input+todos+navigation): 27/27 PASSED ✅ (3.3m)
- **总计: 69/69 PASSED ✅**

**访问方式**:
- IP 直连: `http://47.116.219.15/` (前端 + API，ICP 备案期间可用)
- 域名: `https://www.promiselink.cn/` (ICP 备案完成后可用，当前被拦截)

## Staging E2E 测试

部署成功后, 执行真实用户场景 E2E 测试:

```bash
# 获取 POC_SECRET
POC_SECRET=$(ssh root@47.116.219.15 "grep POC_SECRET /opt/promiselink/.env.prod" | cut -d= -f2)

# 注意: 因 ICP 备案阻塞，使用 IP 直连而非域名
# nginx 已配置 HTTP /api/ 代理 (不重定向 HTTPS)，支持 E2E 测试

# E2E 测试 1: 真实 LLM Pipeline E2E (6 个用例, ~2min)
E2E_BASE_URL=http://47.116.219.15 \
POC_SECRET=${POC_SECRET} \
.venv/bin/python -m pytest tests/test_real_pipeline_e2e.py -v --tb=short

# E2E 测试 2: POC 综合测试 (24 个用例, 安全/压力/用户旅程, ~2min)
E2E_BASE_URL=http://47.116.219.15 \
POC_SECRET=${POC_SECRET} \
.venv/bin/python -m pytest tests/test_poc_comprehensive.py -v --tb=short -m "not skip"
```

**E2E 测试结果汇总**:
- 2026-07-07 (NullPool 修复后, CI 镜像):
  - Pipeline E2E: 6/6 PASSED ✅ (132.65s)
  - POC 综合: 24/24 PASSED ✅ (95.67s)
- 2026-07-06 (Volume mount 补丁):
  - Pipeline E2E: 3/6 PASSED (QueuePool 耗尽)
  - POC 综合: 18/24 PASSED (QueuePool 耗尽 + UnboundLocalError + 超时)
- 修复内容:
  1. NullPool 替代 QueuePool (database.py) — 根因修复
  2. commit_with_retry (events.py) — SQLite 锁重试
  3. TRUSTED_PROXIES CIDR (dependencies.py) — rate limiter 信任 nginx
  4. wait_for_pipeline 超时 90s→180s — LLM 处理可达 76s
  5. wait_for_pipeline event=None 初始化 — 修复 UnboundLocalError

## 回滚方案

如果 staging 部署失败或发现问题:

```bash
# 自动回滚 (deploy-prod.sh 已内置, 含 DB 恢复)
# 手动回滚:
ssh root@47.116.219.15
cd /opt/promiselink
PREV_VERSION=$(cat .last-known-good 2>/dev/null | rev | cut -d: -f1 | rev)
VERSION=${PREV_VERSION:-latest} REGISTRY_OWNER=lulin70 docker compose -f docker-compose.prod.yml up -d

# 数据库回滚 (bind mount 路径, 与 compose 一致)
LATEST_BACKUP=$(ls -t /opt/promiselink/backups/pre_deploy_*.db.gz | head -1)
gunzip -c "$LATEST_BACKUP" > /opt/promiselink/data/promiselink.db
docker compose -f docker-compose.prod.yml restart promiselink-api
```

## 安全注意事项

1. **.env.prod 权限**: 必须设置为 `chmod 600 .env.prod`, 仅 root 可读
2. **SSH 密钥**: staging 验证后立即轮换 (当前密钥曾暴露)
3. **SSH 防火墙**: staging 期间限制 SSH 源 IP (独立于密钥轮换的缓解措施)
4. **WeChat AppSecret**: staging 验证后立即轮换
5. **防火墙**: 仅开放 80/443 端口, API 端口绑定 127.0.0.1 不暴露公网
6. **日志**: LOG_LEVEL=INFO (非 DEBUG), 确保日志中不包含 PII 或密钥
7. **容器安全**: 所有容器 cap_drop: [ALL] + no-new-privileges
8. **日志轮转**: docker-compose 配置 json-file max-size=10m max-file=3
