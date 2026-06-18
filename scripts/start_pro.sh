#!/usr/bin/env bash
# =============================================================================
# PromiseLink 专业版 启动脚本
# =============================================================================
# 启动前自动检查许可证密钥与网关连接状态
# 友好的中文提示，适合非技术人员使用
#
# 许可证：GNU AGPL v3 — 详见 LICENSE 文件
# =============================================================================
set -euo pipefail

# ── 莫兰迪色系（柔和色调）──
COLOR_TITLE='\033[38;5;95m'      # 柔紫
COLOR_STEP='\033[38;5;96m'       # 莫兰迪紫
COLOR_OK='\033[38;5;108m'        # 莫兰迪绿
COLOR_WARN='\033[38;5;137m'      # 莫兰迪黄
COLOR_ERROR='\033[38;5;131m'     # 莫兰迪红
COLOR_INFO='\033[38;5;102m'      # 莫兰迪灰
COLOR_RESET='\033[0m'

# 默认网关地址
DEFAULT_GATEWAY_URL="https://gateway.promiselink.cn"

# 项目根目录
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_ROOT"

# ── 工具函数 ──

print_title() {
    echo ""
    echo -e "${COLOR_TITLE}╔══════════════════════════════════════════════╗${COLOR_RESET}"
    echo -e "${COLOR_TITLE}║   PromiseLink 专业版 启动中...                ║${COLOR_RESET}"
    echo -e "${COLOR_TITLE}║   AI 驱动的关系管理 · 云端增强版              ║${COLOR_RESET}"
    echo -e "${COLOR_TITLE}╚══════════════════════════════════════════════╝${COLOR_RESET}"
    echo ""
}

print_step() {
    echo -e "${COLOR_STEP}▶ $1${COLOR_RESET}"
}

print_ok() {
    echo -e "${COLOR_OK}  ✓ $1${COLOR_RESET}"
}

print_warn() {
    echo -e "${COLOR_WARN}  ⚠ $1${COLOR_RESET}"
}

print_error() {
    echo -e "${COLOR_ERROR}  ✗ $1${COLOR_RESET}"
}

print_info() {
    echo -e "${COLOR_INFO}  ℹ $1${COLOR_RESET}"
}

die() {
    print_error "$1"
    echo ""
    exit 1
}

# ── 读取 .env 配置 ──

read_env_var() {
    local key="$1"
    local default="${2:-}"
    local value
    value=$(grep "^${key}=" "$PROJECT_ROOT/.env" 2>/dev/null | head -1 | cut -d'=' -f2- || echo "")
    if [[ -z "$value" ]]; then
        echo "$default"
    else
        echo "$value"
    fi
}

# ── 步骤 1: 检查 .env 文件 ──

check_env_file() {
    print_step "【1/4】检查配置文件..."

    if [[ ! -f "$PROJECT_ROOT/.env" ]]; then
        die "未找到 .env 配置文件
     请先运行安装脚本：bash scripts/install_pro.sh"
    fi
    print_ok "配置文件存在"
}

# ── 步骤 2: 检查许可证密钥 ──

check_license() {
    print_step "【2/4】检查许可证密钥..."

    local license_key
    license_key=$(read_env_var "PRO_LICENSE_KEY" "")

    if [[ -z "$license_key" ]]; then
        die "未配置许可证密钥
     请先运行安装脚本：bash scripts/install_pro.sh"
    fi

    # 基本格式校验
    if [[ ! "$license_key" =~ ^PL-PRO-[A-Z0-9]{4}-[A-Z0-9]{4}-[A-Z0-9]{4}$ ]]; then
        print_warn "许可证密钥格式异常（期望 PL-PRO-XXXX-XXXX-XXXX）"
        echo -ne "${COLOR_STEP}  是否继续启动？(y/N): ${COLOR_RESET}"
        read -r confirm </dev/tty
        if [[ ! "$confirm" =~ ^[Yy]$ ]]; then
            die "已取消启动"
        fi
    else
        print_ok "许可证密钥: ${license_key:0:12}****"
    fi
}

# ── 步骤 3: 检查网关连接 ──

check_gateway() {
    print_step "【3/4】检查网关连接..."

    local gateway_url
    gateway_url=$(read_env_var "RELAY_GATEWAY_URL" "$DEFAULT_GATEWAY_URL")

    print_info "网关地址: $gateway_url"

    # 使用 Python 检查网关连通性（避免依赖 curl）
    if python3 -c "
import urllib.request, sys
try:
    resp = urllib.request.urlopen('${gateway_url}/api/v1/pro/health', timeout=5)
    sys.exit(0 if resp.status == 200 else 1)
except Exception:
    sys.exit(1)
" 2>/dev/null; then
        print_ok "网关连接正常"
    else
        print_warn "无法连接网关，请检查网络连接"
        print_info  "服务仍可启动，AI 功能将在网关恢复后自动可用"
        print_info  "网关地址: $gateway_url"
    fi
}

# ── 步骤 4: 启动服务 ──

start_service() {
    print_step "【4/4】启动 PromiseLink 专业版服务..."

    # 创建数据目录
    mkdir -p "$PROJECT_ROOT/data"

    # 确定端口和主机
    local port host
    port=$(read_env_var "API_PORT" "8000")
    host=$(read_env_var "API_HOST" "0.0.0.0")

    # 允许命令行参数覆盖
    PORT="${PORT:-$port}"
    HOST="${HOST:-$host}"

    echo ""
    echo -e "${COLOR_INFO}  ──────────────────────────────────────${COLOR_RESET}"
    echo -e "${COLOR_STEP}  访问地址:${COLOR_RESET} ${COLOR_OK}http://localhost:${PORT}${COLOR_RESET}"
    echo -e "${COLOR_STEP}  API 文档:${COLOR_RESET} ${COLOR_OK}http://localhost:${PORT}/docs${COLOR_RESET}"
    echo -e "${COLOR_INFO}  ──────────────────────────────────────${COLOR_RESET}"
    echo ""
    echo -e "${COLOR_INFO}  按 Ctrl+C 可停止服务${COLOR_RESET}"
    echo ""

    exec python3 -m uvicorn promiselink.main:app --host "$HOST" --port "$PORT" "$@"
}

# ── 主流程 ──

main() {
    print_title

    check_env_file
    check_license
    check_gateway
    start_service
}

main "$@"
