#!/usr/bin/env bash
# =============================================================================
# PromiseLink 基础版 一键安装脚本
# =============================================================================
# 适用人群：技术人员/自托管用户/开源社区
# 自动完成：环境检查→venv创建→依赖安装→前端构建→数据库迁移→配置检查→健康验证
#
# 许可证：MPL 2.0 — 详见 LICENSE 文件
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

# 项目根目录（脚本所在目录的上一级）
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

cd "$PROJECT_ROOT"

# ── 工具函数 ──

print_title() {
    echo ""
    echo -e "${COLOR_TITLE}╔══════════════════════════════════════════════╗${COLOR_RESET}"
    echo -e "${COLOR_TITLE}║   PromiseLink 基础版 安装向导                 ║${COLOR_RESET}"
    echo -e "${COLOR_TITLE}║   AI 驱动的关系管理 · 开源版 (MPL 2.0)        ║${COLOR_RESET}"
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
    echo -e "${COLOR_ERROR}安装失败。请检查错误信息后重试。${COLOR_RESET}"
    exit 1
}

# ── Python 命令探测 ──
# macOS 等系统默认 python3 可能是 3.9，优先寻找 3.11/3.12/3.13。
detect_python() {
    local candidates=("python3.13" "python3.12" "python3.11")
    for cmd in "${candidates[@]}"; do
        if command -v "$cmd" &>/dev/null; then
            echo "$cmd"
            return 0
        fi
    done
    if command -v python3 &>/dev/null; then
        echo "python3"
        return 0
    fi
    echo ""
}

# ── 步骤 1: 检查 Python 环境 ──

check_python() {
    print_step "【1/8】检查 Python 环境..."

    PYTHON_CMD=$(detect_python)
    if [[ -z "$PYTHON_CMD" ]]; then
        die "未找到 Python3，请先安装 Python 3.11 或更高版本。
     下载地址：https://www.python.org/downloads/"
    fi

    PYTHON_VERSION=$($PYTHON_CMD -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}')")
    if ! $PYTHON_CMD -c "
import sys
if sys.version_info < (3, 11):
    print('ERROR')
    sys.exit(1)
" 2>/dev/null; then
        die "Python 版本过低（当前 $PYTHON_VERSION ），需要 3.11+ 。
     下载地址：https://www.python.org/downloads/"
    fi

    print_ok "Python $PYTHON_VERSION （命令：$PYTHON_CMD ）"
}

# ── 步骤 2: 检查 Node.js 环境 ──

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

# ── 步骤 3: 创建虚拟环境 ──

create_venv() {
    print_step "【3/8】创建 Python 虚拟环境..."

    VENV_DIR="$PROJECT_ROOT/.venv"

    if [[ -d "$VENV_DIR" ]]; then
        print_info "虚拟环境已存在，跳过创建。"
    else
        if $PYTHON_CMD -m venv "$VENV_DIR"; then
            print_ok "虚拟环境创建完成: $VENV_DIR"
        else
            die "虚拟环境创建失败，请检查 Python venv 模块是否可用。"
        fi
    fi

    # 激活虚拟环境
    # shellcheck disable=SC1091
    source "$VENV_DIR/bin/activate"
    print_ok "已激活虚拟环境"
}

# ── 步骤 4: 安装 Python 依赖 ──

install_python_deps() {
    print_step "【4/8】安装 Python 依赖..."

    print_info "正在安装依赖包，可能需要几分钟，请耐心等待..."

    if pip install --upgrade pip -q && pip install -e ".[dev]" -q 2>&1 | tail -5; then
        print_ok "Python 依赖安装完成"
    else
        die "Python 依赖安装失败，请检查网络连接后重试。"
    fi
}

# ── 步骤 5: 构建前端 ──

build_frontend() {
    if [[ "${SKIP_FRONTEND:-1}" == "1" ]]; then
        print_step "【5/8】跳过前端构建（未检测到 Node.js）"
        return
    fi

    print_step "【5/8】构建前端界面..."

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

# ── 步骤 6: 数据库迁移 ──

run_migrations() {
    print_step "【6/8】初始化数据库..."

    mkdir -p "$PROJECT_ROOT/data"

    if python3 -m alembic upgrade head 2>&1 | tail -5; then
        print_ok "数据库迁移完成"
    else
        print_warn "数据库迁移出错，可能需要手动检查。"
        print_info  "可手动运行：python3 -m alembic upgrade head"
    fi
}

# ── 步骤 7: 配置检查 ──

configure_env() {
    print_step "【7/8】配置环境文件..."

    if [[ ! -f "$PROJECT_ROOT/.env" ]]; then
        print_info "未找到 .env，从模板创建..."
        cp "$PROJECT_ROOT/.env.basic.example" "$PROJECT_ROOT/.env"
        print_ok "已创建 .env 文件"
    else
        print_ok ".env 文件已存在"
    fi

    # 检查 SECRET_KEY 是否为默认值
    if grep -q "SECRET_KEY=change-me-in-production" "$PROJECT_ROOT/.env" 2>/dev/null; then
        print_warn "检测到默认 SECRET_KEY，正在生成随机密钥..."
        NEW_KEY=$(python3 -c "import secrets; print(secrets.token_urlsafe(32))")
        # 兼容 macOS sed 和 GNU sed
        if [[ "$(uname)" == "Darwin" ]]; then
            sed -i '' "s|SECRET_KEY=change-me-in-production|SECRET_KEY=${NEW_KEY}|" "$PROJECT_ROOT/.env"
        else
            sed -i "s|SECRET_KEY=change-me-in-production|SECRET_KEY=${NEW_KEY}|" "$PROJECT_ROOT/.env"
        fi
        print_ok "已自动生成随机 SECRET_KEY"
    fi

    # 检查 LLM_API_KEY
    if grep -q "LLM_API_KEY=sk-your-key-here" "$PROJECT_ROOT/.env" 2>/dev/null; then
        print_warn "LLM_API_KEY 未配置（仍为默认值）"
        print_info  "AI 功能将不可用，请编辑 .env 设置 LLM_API_KEY"
        print_info  "推荐：Moka AI (https://moka-ai.com) 或 DeepSeek (新用户有免费额度)"
    else
        print_ok "LLM_API_KEY 已配置"
    fi
}

# ── 步骤 8: 健康验证 ──

verify_installation() {
    print_step "【8/8】验证安装..."

    # 验证 Python 包可导入
    if python3 -c "import promiselink; print(f'PromiseLink v{promiselink.__version__}')" 2>/dev/null; then
        print_ok "PromiseLink 包导入成功"
    else
        die "PromiseLink 包导入失败，请检查依赖安装。"
    fi

    # 验证数据库可连接
    if python3 -c "
import asyncio
from promiselink.database import async_engine_factory
from sqlalchemy import text

async def check():
    engine = async_engine_factory()
    async with engine.connect() as conn:
        await conn.execute(text('SELECT 1'))
    await engine.dispose()
    print('DB_OK')

asyncio.run(check())
" 2>/dev/null; then
        print_ok "数据库连接正常"
    else
        print_warn "数据库连接验证失败，请检查数据库配置。"
    fi

    print_done "安装验证完成！"
}

# ── 主流程 ──

main() {
    print_title

    check_python
    check_node
    create_venv
    install_python_deps
    build_frontend
    run_migrations
    configure_env
    verify_installation

    echo ""
    echo -e "${COLOR_OK}╔══════════════════════════════════════════════╗${COLOR_RESET}"
    echo -e "${COLOR_OK}║   ✓ PromiseLink 基础版安装完成！              ║${COLOR_RESET}"
    echo -e "${COLOR_OK}╚══════════════════════════════════════════════╝${COLOR_RESET}"
    echo ""
    echo -e "${COLOR_INFO}下一步：${COLOR_RESET}"
    echo -e "${COLOR_INFO}  1. 编辑 .env，配置 LLM_API_KEY（如尚未配置）${COLOR_RESET}"
    echo -e "${COLOR_INFO}  2. 启动服务：bash scripts/start.sh${COLOR_RESET}"
    echo -e "${COLOR_INFO}  3. 访问 API 文档：http://localhost:8000/docs${COLOR_RESET}"
    echo -e "${COLOR_INFO}  4. 访问前端界面：http://localhost:8000/${COLOR_RESET}"
    echo ""
}

main "$@"
