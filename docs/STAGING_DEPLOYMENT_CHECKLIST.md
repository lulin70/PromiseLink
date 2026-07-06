# PromiseLink Staging 部署清单

> 创建时间: 2026-07-06
> 目标服务器: 47.116.219.15
> 目标域名: www.promiselink.cn
> 版本: v0.8.0-rc2

## 前置条件

### 已完成
- [x] DNS A 记录已添加 (www.promiselink.cn → 47.116.219.15)
- [x] docker-compose.prod.yml 已就绪 (使用 ghcr.io 镜像 + nginx + certbot)
- [x] nginx/conf.d/default.conf 已配置 (HTTP→HTTPS 重定向 + 反向代理)
- [x] deploy-prod.sh 部署脚本 (含备份、健康检查、自动回滚)
- [x] .env.prod.example 配置模板
- [x] scripts/ops/init-ssl.sh SSL 证书初始化脚本

### 待执行 (Staging 后处理)
- [ ] SSH 私钥轮换 (当前密钥曾暴露, staging 验证后立即轮换)
- [ ] WeChat AppSecret 轮换 (同上)
- [ ] GitHub Secrets 配置 (REGISTRY_OWNER、SSH_PRIVATE_KEY 等)

## Staging 部署步骤

### Phase 1: 服务器初始化 (在 47.116.219.15 上执行)

```bash
# 1.1 登录服务器
ssh root@47.116.219.15

# 1.2 创建部署目录
mkdir -p /opt/promiselink/{data,backups,certbot/{conf,www}}
cd /opt/promiselink

# 1.3 安装 Docker (如未安装)
curl -fsSL https://get.docker.com | sh
systemctl enable --now docker

# 1.4 防火墙开放端口
firewall-cmd --permanent --add-port=80/tcp
firewall-cmd --permanent --add-port=443/tcp
firewall-cmd --reload
```

### Phase 2: 配置文件上传 (在本地执行)

```bash
# 2.1 上传部署文件
cd /Users/lin/trae_projects/PromiseLink
scp docker-compose.prod.yml root@47.116.219.15:/opt/promiselink/
scp -r nginx/ root@47.116.219.15:/opt/promiselink/
scp scripts/ops/init-ssl.sh root@47.116.219.15:/opt/promiselink/
scp scripts/ops/deploy-prod.sh root@47.116.219.15:/opt/promiselink/

# 2.2 创建 .env.prod (在服务器上执行,不要上传)
ssh root@47.116.219.15
cd /opt/promiselink
cp .env.prod.example .env.prod  # 如果上传了模板
# 或手动创建:
cat > .env.prod << 'EOF'
APP_ENV=production
SECRET_KEY=$(python3 -c "import secrets; print(secrets.token_urlsafe(32))")
POC_SECRET=$(python3 -c "import secrets; print(secrets.token_urlsafe(16))")
LLM_PROVIDER=moka_ai
LLM_API_KEY=<your-moka-ai-api-key>
LLM_TIMEOUT=60
LLM_MAX_RETRIES=5
LLM_MAX_TOKENS=4000
LOG_LEVEL=INFO
CORS_ORIGINS=["https://www.promiselink.cn","https://promiselink.cn"]
APP_EDITION=basic
EOF
chmod 600 .env.prod
```

### Phase 3: SSL 证书初始化 (在服务器上执行)

```bash
# 3.1 确认 DNS 已生效
dig www.promiselink.cn +short
# 应返回 47.116.219.15

# 3.2 获取 SSL 证书
cd /opt/promiselink
chmod +x init-ssl.sh
./init-ssl.sh www.promiselink.cn admin@promiselink.cn

# 脚本会:
#   1. 停止 nginx (释放 80 端口)
#   2. certbot standalone 模式获取证书
#   3. 启动完整 docker-compose stack
#   4. 验证 HTTPS 健康检查
```

### Phase 4: 部署应用 (在本地或服务器上执行)

```bash
# 4.1 使用 deploy-prod.sh 部署 (推荐,含备份+回滚)
cd /Users/lin/trae_projects/PromiseLink
./scripts/ops/deploy-prod.sh 47.116.219.15 root 0.8.0-rc2

# 或在服务器上直接部署
ssh root@47.116.219.15
cd /opt/promiselink
VERSION=0.8.0-rc2 docker compose -f docker-compose.prod.yml pull
VERSION=0.8.0-rc2 docker compose -f docker-compose.prod.yml up -d --remove-orphans
```

### Phase 5: 验证

```bash
# 5.1 健康检查
curl -sf https://www.promiselink.cn/api/v1/health | jq .

# 5.2 HTTPS 证书验证
curl -vI https://www.promiselink.cn/ 2>&1 | grep -E "subject|issuer|SSL certificate"

# 5.3 容器状态
ssh root@47.116.219.15 "docker compose -f /opt/promiselink/docker-compose.prod.yml ps"

# 5.4 功能验证 (登录 + 创建事件)
curl -X POST https://www.promiselink.cn/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"user_id":"staging-test-user","poc_secret":"<your-poc-secret>"}'
```

## Staging E2E 测试

部署成功后,执行真实用户场景 E2E 测试:

```bash
# 在本地执行,指向 staging 环境
E2E_BASE_URL=https://www.promiselink.cn \
POC_SECRET=<your-poc-secret> \
.venv/bin/python -m pytest tests/test_real_pipeline_e2e.py -v --tb=short
```

## 回滚方案

如果 staging 部署失败或发现问题:

```bash
# 自动回滚 (deploy-prod.sh 已内置)
# 手动回滚:
ssh root@47.116.219.15
cd /opt/promiselink
PREV_VERSION=$(cat .last-known-good 2>/dev/null | rev | cut -d: -f1 | rev)
VERSION=${PREV_VERSION:-latest} docker compose -f docker-compose.prod.yml up -d

# 数据库回滚 (如有备份)
gunzip < /opt/promiselink/backups/pre_deploy_*.db.gz > /opt/promiselink/data/promiselink.db
docker compose -f docker-compose.prod.yml restart promiselink-api
```

## 安全注意事项

1. **.env.prod 权限**: 必须设置为 `chmod 600 .env.prod`,仅 root 可读
2. **SSH 密钥**: staging 验证后立即轮换 (当前密钥曾暴露)
3. **WeChat AppSecret**: staging 验证后立即轮换
4. **防火墙**: 仅开放 80/443 端口,SSH 端口建议改为非标准端口
5. **日志**: 确保日志中不包含 PII 或密钥信息 (LOG_LEVEL=INFO, 非 DEBUG)
