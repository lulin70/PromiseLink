#!/usr/bin/env bash
# =============================================================================
# PromiseLink 专业版 一键安装脚本
# =============================================================================
# 适用人群：非技术人员（无需任何技术背景）
# 只需输入许可证密钥，脚本自动完成全部安装与配置
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

# 项目根目录（脚本所在目录的上一级）
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

cd "$PROJECT_ROOT"

# ── 工具函数 ──

print_title() {
    echo ""
    echo -e "${COLOR_TITLE}╔══════════════════════════════════════════════╗${COLOR_RESET}"
    echo -e "${COLOR_TITLE}║   PromiseLink 专业版 安装向导                 ║${COLOR_RESET}"
    echo -e "${COLOR_TITLE}║   AI 驱动的关系管理 · 云端增强版              ║${COLOR_RESET}"
    echo -e "${COLOR_TITLE}╚══════════════════════════════════════════════╝${COLOR_RESET}"
    echo ""
}

print_step() {
    echo ""
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

print_done() {
    echo ""
    echo -e "${COLOR_OK}  $1${COLOR_RESET}"
}

die() {
    print_error "$1"
    echo ""
    echo -e "${COLOR_ERROR}安装失败。如果需要帮助，请联系客服。${COLOR_RESET}"
    exit 1
}

# ── 步骤 1: 环境检查 ──

check_python() {
    print_step "【1/8】检查 Python 环境..."

    if ! command -v python3 &>/dev/null; then
        die "未找到 Python3，请先安装 Python 3.11 或更高版本。
     下载地址：https://www.python.org/downloads/"
    fi

    PYTHON_VERSION=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}')")
    python3 -c "
import sys
if sys.version_info < (3, 11):
    print('ERROR')
    sys.exit(1)
" 2>/dev/null || die "Python 版本过低（当前 $PYTHON_VERSION），需要 3.11+。
     下载地址：https://www.python.org/downloads/"

    print_ok "Python $PYTHON_VERSION"
}

check_node() {
    print_step "【2/8】检查 Node.js 环境..."

    if ! command -v node &>/dev/null; then
        print_warn "未找到 Node.js，将跳过前端构建。"
        print_info  "如需前端界面，请安装 Node.js 18+：https://nodejs.org/"
        SKIP_FRONTEND=1
        return
    fi

    NODE_VERSION=$(node -v 2>/dev/null || echo "unknown")
    print_ok "Node.js $NODE_VERSION"
    SKIP_FRONTEND=0
}

# ── 步骤 3: 安装 Python 依赖 ──

install_python_deps() {
    print_step "【3/8】安装 Python 依赖..."

    print_info "正在安装依赖包，可能需要几分钟，请耐心等待..."

    if python3 -m pip install -e ".[dev]" -q 2>&1 | tail -5; then
        print_ok "Python 依赖安装完成"
    else
        die "Python 依赖安装失败，请检查网络连接后重试。"
    fi
}

# ── 步骤 4: 构建前端 ──

build_frontend() {
    if [[ "${SKIP_FRONTEND:-1}" == "1" ]]; then
        print_step "【4/8】跳过前端构建（未检测到 Node.js）"
        return
    fi

    print_step "【4/8】构建前端界面..."

    if [[ ! -d "$PROJECT_ROOT/frontend" ]]; then
        print_warn "未找到 frontend 目录，跳过前端构建。"
        return
    fi

    cd "$PROJECT_ROOT/frontend"

    print_info "安装前端依赖（首次可能较慢）..."
    if npm install -q 2>&1 | tail -3; then
        print_ok "前端依赖安装完成"
    else
        print_warn "前端依赖安装失败，跳过前端构建。"
        cd "$PROJECT_ROOT"
        return
    fi

    print_info "构建 H5 前端..."
    if npm run build:h5 -q 2>&1 | tail -3; then
        print_ok "前端构建完成"
    else
        print_warn "前端构建失败，不影响后端使用。"
    fi

    cd "$PROJECT_ROOT"
}

# ── 步骤 5: 数据库迁移 ──

run_migrations() {
    print_step "【5/8】初始化数据库..."

    mkdir -p "$PROJECT_ROOT/data"

    if python3 -m alembic upgrade head 2>&1 | tail -5; then
        print_ok "数据库迁移完成"
    else
        print_warn "数据库迁移出错，可能需要手动检查。"
        print_info  "可手动运行：python3 -m alembic upgrade head"
    fi
}

# ── 步骤 6: 输入并验证许可证密钥 ──

prompt_license_key() {
    print_step "【6/8】输入许可证密钥..."

    echo -e "${COLOR_INFO}  请输入您的 PromiseLink 专业版许可证密钥${COLOR_RESET}"
    echo -e "${COLOR_INFO}  格式：PL-PRO-XXXX-XXXX-XXXX（X 为大写字母或数字）${COLOR_RESET}"
    echo ""

    while true; do
        echo -ne "${COLOR_STEP}  请输入许可证密钥: ${COLOR_RESET}"
        read -r LICENSE_KEY </dev/tty

        if [[ -z "$LICENSE_KEY" ]]; then
            print_warn "许可证密钥不能为空，请重新输入。"
            continue
        fi

        # 基本格式校验
        if [[ ! "$LICENSE_KEY" =~ ^PL-PRO-[A-Z0-9]{4}-[A-Z0-9]{4}-[A-Z0-9]{4}$ ]]; then
            print_warn "格式不正确，正确格式为 PL-PRO-XXXX-XXXX-XXXX"
            print_info  "请检查后重新输入（注意大写字母和连字符）"
            continue
        fi

        # 验证许可证密钥（调用网关 API）
        print_info "正在验证许可证密钥..."
        if verify_license_key "$LICENSE_KEY"; then
            print_ok "许可证密钥验证通过！"
            break
        else
            print_warn "许可证密钥验证失败，请检查后重新输入。"
            print_info  "如需帮助请联系客服。"
        fi
    done
}

verify_license_key() {
    local key="$1"
    local gateway="${RELAY_GATEWAY_URL:-$DEFAULT_GATEWAY_URL}"
    local verify_url="${gateway}/api/v1/pro/health"

    # 先检查网关连通性
    if ! python3 -c "
import sys
import urllib.request
import urllib.error
import json

try:
    req = urllib.request.Request('${verify_url}', method='GET')
    with urllib.request.urlopen(req, timeout=10) as resp:
        if resp.status != 200:
            print('GATEWAY_ERROR')
            sys.exit(1)
except urllib.error.URLError:
    print('NETWORK_ERROR')
    sys.exit(1)
except Exception:
    print('UNKNOWN_ERROR')
    sys.exit(1)
" 2>/dev/null; then
        print_warn "无法连接到网关 ($gateway)"
        echo -ne "${COLOR_STEP}  是否跳过在线验证继续安装？(y/N): ${COLOR_RESET}"
        read -r skip_verify </dev/tty
        if [[ "$skip_verify" =~ ^[Yy]$ ]]; then
            print_info "跳过在线验证，稍后可在启动时验证。"
            return 0
        fi
        return 1
    fi

    # 调用网关激活接口验证许可证密钥
    if ! python3 -c "
import sys
import urllib.request
import urllib.error
import json
import hashlib

license_key = '${key}'
gateway = '${gateway}'
device_fp = 'sha256:' + hashlib.sha256(license_key.encode()).hexdigest()

payload = json.dumps({
    'license_key': license_key,
    'device_fingerprint': device_fp,
}).encode('utf-8')

req = urllib.request.Request(
    gateway + '/api/v1/pro/license/activate',
    data=payload,
    headers={
        'Content-Type': 'application/json',
        'X-API-Key': license_key,
    },
    method='POST'
)

try:
    with urllib.request.urlopen(req, timeout=15) as resp:
        if resp.status == 200:
            data = json.loads(resp.read().decode('utf-8'))
            if data.get('success') or data.get('data', {}).get('tokens'):
                print('OK')
                sys.exit(0)
    print('VERIFY_FAILED')
    sys.exit(1)
except urllib.error.HTTPError as e:
    if e.code in (401, 403):
        print('AUTH_FAILED')
    elif e.code == 404:
        print('LICENSE_NOT_FOUND')
    else:
        print('HTTP_ERROR:' + str(e.code))
    sys.exit(1)
except Exception as e:
    print('ERROR:' + str(e)[:100])
    sys.exit(1)
" 2>/dev/null; then
        return 1
    fi
    return 0
}

# ── 步骤 7: 配置 .env 文件 ──

configure_env() {
    print_step "【7/8】配置环境文件..."

    local env_file="$PROJECT_ROOT/.env"
    local gateway_url="${RELAY_GATEWAY_URL:-$DEFAULT_GATEWAY_URL}"

    # 如果 .env 不存在，从模板创建
    if [[ ! -f "$env_file" ]]; then
        if [[ -f "$PROJECT_ROOT/.env.basic.example" ]]; then
            cp "$PROJECT_ROOT/.env.basic.example" "$env_file"
            print_info "从模板创建 .env 文件"
        else
            touch "$env_file"
            print_info "创建新的 .env 文件"
        fi
    fi

    # 更新或添加专业版配置项
    update_env_var "APP_EDITION" "pro" "$env_file"
    update_env_var "AI_MODE" "relay" "$env_file"
    update_env_var "RELAY_GATEWAY_URL" "$gateway_url" "$env_file"
    update_env_var "PRO_LICENSE_KEY" "$LICENSE_KEY" "$env_file"

    # 生成随机 SECRET_KEY（如果还是默认值）
    if grep -q "SECRET_KEY=change-me-in-production" "$env_file" 2>/dev/null; then
        local secret_key
        secret_key=$(python3 -c "import secrets; print(secrets.token_urlsafe(32))")
        update_env_var "SECRET_KEY" "$secret_key" "$env_file"
        print_info "已生成随机安全密钥"
    fi

    print_ok ".env 配置完成"
    print_info "网关地址: $gateway_url"
    print_info "许可证密钥: ${LICENSE_KEY:0:12}****"
}

update_env_var() {
    local key="$1"
    local value="$2"
    local file="$3"

    # 转义 value 中的特殊字符用于 sed
    local escaped_value
    escaped_value=$(printf '%s\n' "$value" | sed 's/[&/\]/\\&/g')

    if grep -q "^${key}=" "$file" 2>/dev/null; then
        # 替换已有行
        sed -i.bak "s|^${key}=.*|${key}=${escaped_value}|" "$file"
    else
        # 追加新行
        echo "${key}=${value}" >> "$file"
    fi
    rm -f "${file}.bak"
}

# ── 步骤 8: 创建启动脚本 ──

create_start_script() {
    print_step "【8/8】创建启动脚本..."

    local start_script="$PROJECT_ROOT/scripts/start_pro.sh"

    cat > "$start_script" << 'START_EOF'
#!/usr/bin/env bash
# =============================================================================
# PromiseLink 专业版 启动脚本（自动生成）
# =============================================================================
set -euo pipefail

COLOR_TITLE='\033[38;5;95m'
COLOR_STEP='\033[38;5;96m'
COLOR_OK='\033[38;5;108m'
COLOR_WARN='\033[38;5;137m'
COLOR_ERROR='\033[38;5;131m'
COLOR_INFO='\033[38;5;102m'
COLOR_RESET='\033[0m'

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_ROOT"

echo ""
echo -e "${COLOR_TITLE}╔══════════════════════════════════════════════╗${COLOR_RESET}"
echo -e "${COLOR_TITLE}║   PromiseLink 专业版 启动中...                ║${COLOR_RESET}"
echo -e "${COLOR_TITLE}╚══════════════════════════════════════════════╝${COLOR_RESET}"
echo ""

# 检查 .env 文件
if [[ ! -f "$PROJECT_ROOT/.env" ]]; then
    echo -e "${COLOR_ERROR}✗ 未找到 .env 配置文件${COLOR_RESET}"
    echo -e "${COLOR_INFO}  请先运行安装脚本：bash scripts/install_pro.sh${COLOR_RESET}"
    exit 1
fi

# 检查许可证密钥
LICENSE_KEY=$(grep "^PRO_LICENSE_KEY=" "$PROJECT_ROOT/.env" 2>/dev/null | cut -d'=' -f2- || echo "")
if [[ -z "$LICENSE_KEY" ]]; then
    echo -e "${COLOR_ERROR}✗ 未配置许可证密钥${COLOR_RESET}"
    echo -e "${COLOR_INFO}  请先运行安装脚本：bash scripts/install_pro.sh${COLOR_RESET}"
    exit 1
fi
echo -e "${COLOR_OK}✓ 许可证密钥: ${LICENSE_KEY:0:12}****${COLOR_RESET}"

# 检查网关地址
GATEWAY_URL=$(grep "^RELAY_GATEWAY_URL=" "$PROJECT_ROOT/.env" 2>/dev/null | cut -d'=' -f2- || echo "")
if [[ -z "$GATEWAY_URL" ]]; then
    echo -e "${COLOR_WARN}⚠ 未配置网关地址，使用默认地址${COLOR_RESET}"
    GATEWAY_URL="https://gateway.promiselink.cn"
fi
echo -e "${COLOR_OK}✓ 网关地址: $GATEWAY_URL${COLOR_RESET}"

# 检查网关连通性
echo ""
echo -e "${COLOR_STEP}▶ 检查网关连接...${COLOR_RESET}"
if python3 -c "
import urllib.request, sys
try:
    urllib.request.urlopen('${GATEWAY_URL}/api/v1/pro/health', timeout=5)
    sys.exit(0)
except Exception:
    sys.exit(1)
" 2>/dev/null; then
    echo -e "${COLOR_OK}  ✓ 网关连接正常${COLOR_RESET}"
else
    echo -e "${COLOR_WARN}  ⚠ 无法连接网关，请检查网络${COLOR_RESET}"
    echo -e "${COLOR_INFO}  服务仍可启动，AI 功能将在网关恢复后自动可用${COLOR_RESET}"
fi

# 创建数据目录
mkdir -p "$PROJECT_ROOT/data"

# 确定端口
PORT="${PORT:-8000}"
HOST="${HOST:-0.0.0.0}"

echo ""
echo -e "${COLOR_STEP}▶ 启动 PromiseLink 专业版服务...${COLOR_RESET}"
echo ""
echo -e "${COLOR_INFO}  访问地址: http://localhost:${PORT}${COLOR_RESET}"
echo -e "${COLOR_INFO}  API 文档: http://localhost:${PORT}/docs${COLOR_RESET}"
echo -e "${COLOR_INFO}  按 Ctrl+C 停止服务${COLOR_RESET}"
echo ""

python3 -m uvicorn promiselink.main:app --host "$HOST" --port "$PORT" "$@"
START_EOF

    chmod +x "$start_script"
    print_ok "启动脚本已创建: scripts/start_pro.sh"
}

# ── 完成提示 ──

show_completion() {
    print_done "══════════════════════════════════════════════"
    echo ""
    echo -e "${COLOR_OK}  🎉 PromiseLink 专业版安装完成！${COLOR_RESET}"
    echo ""
    echo -e "${COLOR_INFO}  ──────────────────────────────────────${COLOR_RESET}"
    echo -e "${COLOR_STEP}  启动方式：${COLOR_RESET}"
    echo -e "${COLOR_OK}    bash scripts/start_pro.sh${COLOR_RESET}"
    echo ""
    echo -e "${COLOR_STEP}  访问地址：${COLOR_RESET}"
    echo -e "${COLOR_OK}    http://localhost:8000${COLOR_RESET}"
    echo ""
    echo -e "${COLOR_STEP}  API 文档：${COLOR_RESET}"
    echo -e "${COLOR_OK}    http://localhost:8000/docs${COLOR_RESET}"
    echo -e "${COLOR_INFO}  ──────────────────────────────────────${COLOR_RESET}"
    echo ""
    echo -e "${COLOR_INFO}  如遇问题，请检查：${COLOR_RESET}"
    echo -e "${COLOR_INFO}    1. 网络连接是否正常${COLOR_RESET}"
    echo -e "${COLOR_INFO}    2. 许可证密钥是否有效${COLOR_RESET}"
    echo -e "${COLOR_INFO}    3. 端口 8000 是否被占用${COLOR_RESET}"
    echo ""
}

# ── 主流程 ──

main() {
    print_title

    print_info "本向导将自动完成专业版安装与配置"
    print_info "您只需准备好许可证密钥即可"

    check_python
    check_node
    install_python_deps
    build_frontend
    run_migrations
    prompt_license_key
    configure_env
    create_start_script
    show_completion
}

main "$@"
