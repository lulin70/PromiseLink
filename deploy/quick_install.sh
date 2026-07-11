#!/usr/bin/env bash
# =============================================================================
# PromiseLink 一键安装脚本（专业版用户专用）
# =============================================================================
# 使用方法：
#   curl -fsSL https://promiselink.cn/install.sh | bash
#
# 自动完成：
#   1. 检查 Docker 环境
#   2. 克隆 PromiseLink 仓库
#   3. 配置 .env（预置网关地址，不设 License Key）
#   4. docker-compose up -d
#   5. 打开浏览器访问配对页面
#
# 适用人群：非技术人员，无需手动输入 License Key
# 许可证：MPL 2.0
# =============================================================================
set -euo pipefail

COLOR_TITLE='\033[38;5;95m'
COLOR_STEP='\033[38;5;96m'
COLOR_OK='\033[38;5;108m'
COLOR_WARN='\033[38;5;137m'
COLOR_ERROR='\033[38;5;131m'
COLOR_INFO='\033[38;5;102m'
COLOR_RESET='\033[0m'

INSTALL_DIR="$HOME/PromiseLink"
REPO_URL="https://github.com/lulin70/PromiseLink.git"
GATEWAY_URL="https://gateway.promiselink.cn"

print_title() {
    echo ""
    echo -e "${COLOR_TITLE}╔══════════════════════════════════════════════╗${COLOR_RESET}"
    echo -e "${COLOR_TITLE}║   PromiseLink 一键安装                       ║${COLOR_RESET}"
    echo -e "${COLOR_TITLE}║   AI 驱动的关系管理 · 专业版                  ║${COLOR_RESET}"
    echo -e "${COLOR_TITLE}╚══════════════════════════════════════════════╝${COLOR_RESET}"
    echo ""
}

print_step() { echo -e "\n${COLOR_STEP}▶ $1${COLOR_RESET}"; }
print_ok()   { echo -e "${COLOR_OK}  ✓ $1${COLOR_RESET}"; }
print_warn() { echo -e "${COLOR_WARN}  ⚠ $1${COLOR_RESET}"; }
print_error(){ echo -e "${COLOR_ERROR}  ✗ $1${COLOR_RESET}"; }
print_info() { echo -e "${COLOR_INFO}  ℹ $1${COLOR_RESET}"; }
die()        { print_error "$1"; echo -e "\n${COLOR_ERROR}安装失败。请联系客服微信或发邮件到 support@promiselink.cn${COLOR_RESET}"; exit 1; }

# ── Step 1: 检查 Docker ──
check_docker() {
    print_step "【1/5】检查 Docker 环境..."

    if ! command -v docker &>/dev/null; then
        print_warn "未检测到 Docker，正在尝试自动安装..."
        print_info  "macOS 用户也可手动安装：https://docs.docker.com/desktop/mac/install/"

        if [[ "$(uname)" == "Darwin" ]]; then
            if command -v brew &>/dev/null; then
                print_info "使用 Homebrew 安装 Docker Desktop..."
                brew install --cask docker || die "Docker 安装失败，请手动安装后重新运行此脚本。"
                print_ok "Docker Desktop 已安装，请打开 Docker Desktop 应用后重新运行此脚本。"
                exit 0
            else
                die "请先安装 Homebrew (https://brew.sh) 或手动安装 Docker Desktop。"
            fi
        elif [[ "$(uname)" == "Linux" ]]; then
            curl -fsSL https://get.docker.com | sh || die "Docker 安装失败。"
            sudo systemctl start docker
            sudo systemctl enable docker
            print_ok "Docker 已安装并启动"
        else
            die "不支持的操作系统，请手动安装 Docker。"
        fi
    fi

    if ! docker info &>/dev/null 2>&1; then
        die "Docker 未运行，请先启动 Docker Desktop（macOS）或 Docker 服务（Linux）。"
    fi

    print_ok "Docker 环境正常"
}

# ── Step 2: 克隆仓库 ──
clone_repo() {
    print_step "【2/5】下载 PromiseLink..."

    if [[ -d "$INSTALL_DIR/.git" ]]; then
        print_info "目录 $INSTALL_DIR 已存在，正在更新..."
        cd "$INSTALL_DIR"
        git pull --quiet || print_warn "更新失败，继续使用现有版本"
    else
        mkdir -p "$(dirname "$INSTALL_DIR")"
        git clone --depth 1 "$REPO_URL" "$INSTALL_DIR" || die "下载失败，请检查网络连接。"
        cd "$INSTALL_DIR"
    fi

    print_ok "代码下载完成: $INSTALL_DIR"
}

# ── Step 3: 配置 .env ──
configure_env() {
    print_step "【3/5】配置环境..."

    if [[ ! -f ".env" ]]; then
        cp .env.basic.example .env
        print_ok "已创建 .env 配置文件"
    else
        print_info ".env 已存在，跳过创建"
    fi

    # 预置网关地址（配对模式必需）
    if ! grep -q "RELAY_GATEWAY_URL=" .env 2>/dev/null; then
        echo "" >> .env
        echo "# ---- 专业版配置（一键安装自动生成）----" >> .env
        echo "RELAY_GATEWAY_URL=$GATEWAY_URL" >> .env
        echo "RELAY_WSS_ENABLED=true" >> .env
        print_ok "已预置网关地址"
    else
        print_info "网关地址已配置"
    fi

    # 生成随机 SECRET_KEY（如果仍是默认值）
    if grep -q "SECRET_KEY=CHANGE_ME" .env 2>/dev/null; then
        NEW_KEY=$(python3 -c "import secrets; print(secrets.token_urlsafe(32))" 2>/dev/null || openssl rand -base64 32)
        if [[ "$(uname)" == "Darwin" ]]; then
            sed -i '' "s|SECRET_KEY=CHANGE_ME.*|SECRET_KEY=${NEW_KEY}|" .env
        else
            sed -i "s|SECRET_KEY=CHANGE_ME.*|SECRET_KEY=${NEW_KEY}|" .env
        fi
        print_ok "已生成随机安全密钥"
    fi

    # 生成随机 POC_SECRET（如果仍是默认值）
    if grep -q "POC_SECRET=CHANGE_ME" .env 2>/dev/null; then
        NEW_POC=$(python3 -c "import secrets; print(secrets.token_urlsafe(16))" 2>/dev/null || openssl rand -base64 16)
        if [[ "$(uname)" == "Darwin" ]]; then
            sed -i '' "s|POC_SECRET=CHANGE_ME.*|POC_SECRET=${NEW_POC}|" .env
        else
            sed -i "s|POC_SECRET=CHANGE_ME.*|POC_SECRET=${NEW_POC}|" .env
        fi
        print_ok "已生成随机访问密码"
    fi
}

# ── Step 4: 启动 Docker ──
start_docker() {
    print_step "【4/5】启动服务..."

    if ! command -v docker-compose &>/dev/null; then
        COMPOSE_CMD="docker compose"
    else
        COMPOSE_CMD="docker-compose"
    fi

    $COMPOSE_CMD up -d --build 2>&1 | tail -10 || die "Docker 启动失败，请检查错误信息。"

    print_ok "服务已启动"
}

# ── Step 5: 打开配对页面 ──
open_pair_page() {
    print_step "【5/5】打开激活页面..."

    PAIR_URL="http://localhost:8000/pair"

    echo ""
    echo -e "${COLOR_OK}╔══════════════════════════════════════════════╗${COLOR_RESET}"
    echo -e "${COLOR_OK}║   ✓ PromiseLink 安装完成！                   ║${COLOR_RESET}"
    echo -e "${COLOR_OK}╚══════════════════════════════════════════════╝${COLOR_RESET}"
    echo ""
    echo -e "${COLOR_INFO}下一步：${COLOR_RESET}"
    echo -e "${COLOR_INFO}  1. 浏览器打开：${PAIR_URL}${COLOR_RESET}"
    echo -e "${COLOR_INFO}  2. 用微信「PromiseLink」小程序扫码配对${COLOR_RESET}"
    echo -e "${COLOR_INFO}  3. 配对成功后自动激活专业版${COLOR_RESET}"
    echo ""

    # 尝试自动打开浏览器
    if [[ "$(uname)" == "Darwin" ]]; then
        open "$PAIR_URL" 2>/dev/null || true
    elif command -v xdg-open &>/dev/null; then
        xdg-open "$PAIR_URL" 2>/dev/null || true
    fi

    echo -e "${COLOR_INFO}如需手动访问，请在浏览器输入：${PAIR_URL}${COLOR_RESET}"
    echo -e "${COLOR_INFO}安装目录：${INSTALL_DIR}${COLOR_RESET}"
    echo -e "${COLOR_INFO}配置文件：${INSTALL_DIR}/.env${COLOR_RESET}"
    echo ""
    echo -e "${COLOR_INFO}遇到问题？联系客服微信或发邮件到 support@promiselink.cn${COLOR_RESET}"
    echo ""
}

# ── 主流程 ──
main() {
    print_title

    check_docker
    clone_repo
    configure_env
    start_docker
    open_pair_page
}

main "$@"
