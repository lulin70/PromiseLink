#!/bin/bash
# =============================================================================
# PromiseLink 基础版一键安装脚本（种子客户专用）
#
# 用途：让非技术用户在自己的电脑上启动 PromiseLink 基础版，
#       配置专业版 relay 自动连接云端网关，实现"数据在本地+手机小程序访问"。
#
# 使用方法：
#   bash install_basic.sh
#
# 前置条件：
#   - Docker Desktop 已安装并运行
#   - 已获得专业版许可证密钥（PL-PRO-xxxx-xxxx-xxxx 格式）
#
# 部署架构：
#   用户电脑（本脚本）         云端网关              手机微信小程序
#   ┌─────────────────┐       ┌──────────┐         ┌──────────┐
#   │ 基础版 Docker    │ ─WSS→ │ 网关     │ ←HTTP── │ 小程序   │
#   │ localhost:8000  │       │ gateway. │         │ 扫码预览 │
#   │ SQLite 数据     │       │ promisel │         └──────────┘
#   └─────────────────┘       │ ink.cn   │
#                             └──────────┘
# =============================================================================
set -e

# 默认配置：网关地址优先读环境变量，否则用正式域名
# ICP 备案完成前，用户运行脚本时可手动输入临时地址
DEFAULT_GATEWAY_URL="${GATEWAY_URL:-https://gateway.promiselink.cn}"
DEFAULT_IMAGE="ghcr.io/lulin70/promiselink:0.8.0"
INSTALL_DIR="${PROMISELINK_INSTALL_DIR:-$HOME/promiselink}"

# 颜色输出
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

info()  { echo -e "${GREEN}[INFO]${NC} $1"; }
warn()  { echo -e "${YELLOW}[WARN]${NC} $1"; }
error() { echo -e "${RED}[ERROR]${NC} $1"; exit 1; }

echo "============================================================"
echo "  PromiseLink 基础版安装程序（种子客户专用）"
echo "============================================================"
echo ""

# 1. 检查 Docker
info "检查 Docker 环境..."
if ! command -v docker &> /dev/null; then
    error "未检测到 Docker。请先安装 Docker Desktop：
  macOS:  https://www.docker.com/products/docker-desktop
  Windows: https://www.docker.com/products/docker-desktop
安装后启动 Docker Desktop，再重新运行本脚本。"
fi

if ! docker info &> /dev/null; then
    error "Docker 未运行。请启动 Docker Desktop 后再运行本脚本。"
fi
info "Docker 已就绪 ✓"

# 2. 询问许可证密钥
echo ""
echo "请输入您的专业版许可证密钥（PL-PRO-xxxx-xxxx-xxxx 格式）："
read -r LICENSE_KEY

if [[ ! "$LICENSE_KEY" =~ ^PL-PRO-[a-zA-Z0-9]{4}-[a-zA-Z0-9]{4}-[a-zA-Z0-9]{4,}$ ]]; then
    error "许可证密钥格式不正确。应为 PL-PRO-xxxx-xxxx-xxxx 格式。
请检查您收到的密钥，或联系 support@promiselink.cn 获取。"
fi
info "许可证密钥已确认 ✓"

# 3. 询问网关地址（通常用默认值）
echo ""
echo "云端网关地址（直接回车使用默认值 $DEFAULT_GATEWAY_URL）："
read -r GATEWAY_URL
GATEWAY_URL="${GATEWAY_URL:-$DEFAULT_GATEWAY_URL}"
info "网关地址: $GATEWAY_URL ✓"

# 4. 创建安装目录
echo ""
info "创建安装目录: $INSTALL_DIR"
mkdir -p "$INSTALL_DIR/data"
cd "$INSTALL_DIR"

# 5. 生成 .env 文件
info "生成配置文件 .env.basic..."
cat > .env.basic << EOF
# PromiseLink 基础版配置（自动生成）
# 生成时间: $(date)

# 基础配置
APP_ENV=production
DATABASE_URL=sqlite+aiosqlite:///data/promiselink.db
REDIS_ENABLED=false

# 自动生成一个强随机 SECRET_KEY
SECRET_KEY=$(python3 -c "import secrets; print(secrets.token_urlsafe(32))" 2>/dev/null || openssl rand -hex 32)

# PoC 登录密码（首次登录后请修改）
POC_SECRET=$(openssl rand -hex 8 2>/dev/null || echo "promiselink")

# 专业版 relay 配置（连接云端网关）
RELAY_GATEWAY_URL=$GATEWAY_URL
PRO_LICENSE_KEY=$LICENSE_KEY
RELAY_WSS_ENABLED=true
RELAY_LOCAL_API_URL=http://localhost:8000
EOF

echo ""
info "PoC 登录密码: $(grep POC_SECRET .env.basic | cut -d= -f2)"
warn "请妥善保存此密码，首次登录后请在设置中修改。"

# 6. 生成 docker-compose.yml
info "生成 docker-compose.yml..."
cat > docker-compose.yml << EOF
services:
  promiselink-api:
    image: $DEFAULT_IMAGE
    container_name: promiselink-api
    ports:
      - "8000:8000"
    env_file:
      - .env.basic
    environment:
      - APP_ENV=production
      - DATABASE_URL=sqlite+aiosqlite:///data/promiselink.db
      - REDIS_ENABLED=false
    volumes:
      - ./data:/data
    healthcheck:
      test: ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:8000/api/v1/health')"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 40s
    restart: unless-stopped
    logging:
      driver: json-file
      options:
        max-size: "10m"
        max-file: "3"
EOF

# 7. 拉取镜像并启动
echo ""
info "拉取 Docker 镜像（首次约 200MB，请耐心等待）..."
docker pull "$DEFAULT_IMAGE"

info "启动 PromiseLink 基础版..."
docker compose up -d

# 8. 等待健康检查
echo ""
info "等待服务启动（最多 60 秒）..."
HEALTH_OK=false
for i in $(seq 1 60); do
    if curl -sf http://localhost:8000/api/v1/health > /dev/null 2>&1; then
        info "服务已就绪 ✓ (${i}s)"
        HEALTH_OK=true
        break
    fi
    sleep 1
    printf "."
done
echo ""

if [ "$HEALTH_OK" != "true" ]; then
    error "服务启动失败。请查看日志：
  docker compose logs --tail=50

或联系 support@promiselink.cn 寻求帮助。"
fi

# 9. 检查 WSS 连接状态
echo ""
info "检查专业版 WSS 连接状态..."
sleep 3  # 给 WSS 一点时间建立连接
if docker compose logs --tail=20 2>&1 | grep -q "relay_wss_started"; then
    info "WSS 已连接云端网关 ✓"
elif docker compose logs --tail=20 2>&1 | grep -q "relay_wss_start_failed"; then
    warn "WSS 启动失败，请检查网络连接。本地功能仍可用，但小程序无法访问本地数据。"
    warn "查看详细日志: docker compose logs | grep relay_wss"
else
    warn "WSS 状态未确定，请稍后查看日志: docker compose logs | grep relay_wss"
fi

# 10. 完成提示
echo ""
echo "============================================================"
echo -e "${GREEN}  ✓ PromiseLink 基础版安装完成！${NC}"
echo "============================================================"
echo ""
echo "【本地访问】"
echo "  浏览器打开: http://localhost:8000"
echo "  PoC 登录密码: $(grep POC_SECRET .env.basic | cut -d= -f2)"
echo ""
echo "【手机小程序访问】"
echo "  1. 在 PC 上安装微信开发者工具："
echo "     https://developers.weixin.qq.com/miniprogram/dev/devtools/download.html"
echo "  2. 用 AppID wxa8704555bc066773 导入项目"
echo "  3. 点击'预览'生成二维码"
echo "  4. 手机微信扫码即可在小程序中访问本地数据"
echo ""
echo "【常用命令】"
echo "  查看日志:   docker compose logs -f"
echo "  停止服务:   docker compose down"
echo "  启动服务:   docker compose up -d"
echo "  查看状态:   docker compose ps"
echo ""
echo "【数据备份】"
echo "  数据存储在: $INSTALL_DIR/data/promiselink.db"
echo "  备份命令:   cp $INSTALL_DIR/data/promiselink.db ~/promiselink-backup-\$(date +%Y%m%d).db"
echo ""
echo "如有问题请联系: support@promiselink.cn"
echo "============================================================"
