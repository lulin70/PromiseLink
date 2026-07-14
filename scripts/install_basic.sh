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

# 检测操作系统（用于给出针对性提示与引导链接）
detect_os() {
    case "$(uname -s)" in
        Darwin)               echo "macOS" ;;
        MINGW*|MSYS*|CYGWIN*) echo "Windows" ;;
        Linux)                echo "Linux" ;;
        *)                    echo "未知系统" ;;
    esac
}
CURRENT_OS="$(detect_os)"

echo "============================================================"
echo "  PromiseLink 基础版安装程序（种子客户专用）"
echo "  检测到系统：$CURRENT_OS"
echo "============================================================"
echo ""
echo "本脚本将为你完成以下操作："
echo "  1. 检查 Docker 运行环境"
echo "  2. 输入专业版许可证密钥"
echo "  3. 配置云端网关连接"
echo "  4. 生成配置文件并启动服务"
echo "  5. 验证服务运行与健康状态"
echo ""
echo "如任何一步卡住，可随时联系 support@promiselink.cn 获取协助。"
echo ""

# 1. 检查 Docker
info "第 1 步：检查 Docker 运行环境..."
if ! command -v docker &> /dev/null; then
    # 根据系统给出对应的 Docker 图文安装引导链接
    DOCKER_GUIDE_URL="https://www.docker.com/products/docker-desktop"
    if [ "$CURRENT_OS" = "Linux" ]; then
        DOCKER_GUIDE_URL="https://docs.docker.com/engine/install/"
    fi

    cat << EOF

${RED}[ERROR]${NC} 未检测到 Docker，安装暂时无法继续。

PromiseLink 基础版需要 Docker 运行环境。别担心，只需按下面 4 步操作：

  你的系统：${CURRENT_OS}

  第 1 步｜打开 Docker 下载页面（含图文安装指引）：
    ${DOCKER_GUIDE_URL}

  第 2 步｜下载对应你系统的 Docker Desktop 安装包，双击安装
           （macOS 拖到 Applications；Windows 按向导下一步即可）

  第 3 步｜安装完成后，启动 Docker Desktop
           （菜单栏 / 任务栏出现鲸鱼图标，且状态为「running」即代表已就绪）

  第 4 步｜等待 Docker 完全启动后，重新运行本脚本：
           bash install_basic.sh

  仍遇到问题？把终端报错截图发到 support@promiselink.cn，我们会帮你排查。
EOF
    exit 1
fi

if ! docker info &> /dev/null; then
    cat << EOF

${RED}[ERROR]${NC} Docker 已安装但尚未运行。

请先启动 Docker Desktop：
  ${CURRENT_OS} 系统：在「应用程序 / 开始菜单」中找到 Docker 并打开，
  等待菜单栏 / 任务栏的鲸鱼图标变为稳定状态（约 10-30 秒），
  然后重新运行本脚本：bash install_basic.sh

  如启动失败，可参考：https://docs.docker.com/desktop/troubleshoot/overview/
EOF
    exit 1
fi
info "Docker 已就绪 ✓"

# 2. 询问许可证密钥
echo ""
info "第 2 步：输入专业版许可证密钥"
echo "请输入您收到的专业版许可证密钥（格式如 PL-PRO-xxxx-xxxx-xxxx）："
read -r LICENSE_KEY

if [[ ! "$LICENSE_KEY" =~ ^PL-PRO-[a-zA-Z0-9]{4}-[a-zA-Z0-9]{4}-[a-zA-Z0-9]{4,}$ ]]; then
    cat << EOF

${RED}[ERROR]${NC} 许可证密钥格式不正确。

  正确格式应为：PL-PRO-xxxx-xxxx-xxxx（每组 x 为字母或数字）
  你输入的是：$LICENSE_KEY

  请检查邮件或卡片上收到的密钥后重新运行本脚本。
  如未收到密钥或格式有疑问，请联系 support@promiselink.cn。
EOF
    exit 1
fi
info "许可证密钥已确认 ✓"

# 3. 询问网关地址（通常用默认值）
echo ""
info "第 3 步：配置云端网关地址"
echo "云端网关地址（直接回车使用默认值即可，一般无需修改）："
echo "  $DEFAULT_GATEWAY_URL"
read -r GATEWAY_URL
GATEWAY_URL="${GATEWAY_URL:-$DEFAULT_GATEWAY_URL}"
info "网关地址: $GATEWAY_URL ✓"

# 4. 创建安装目录 + 生成配置
echo ""
info "第 4 步：准备安装目录与配置文件"
info "安装目录: $INSTALL_DIR"
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

# 5. 拉取镜像并启动
echo ""
info "第 5 步：拉取镜像并启动服务"
info "正在下载 Docker 镜像（首次约 200MB，请耐心等待，期间请勿关闭终端）..."
docker pull "$DEFAULT_IMAGE"

info "镜像下载完成，正在启动 PromiseLink 基础版..."
docker compose up -d

# 等待健康检查
echo ""
info "正在等待服务就绪（最多 60 秒，看到 ✓ 即代表启动成功）..."
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
