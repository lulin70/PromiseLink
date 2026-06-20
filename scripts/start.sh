#!/usr/bin/env bash
# =============================================================================
# PromiseLink 基础版 一键启动脚本
# =============================================================================
# 功能：环境检查→数据库迁移→后台启动→健康检查→PID管理→日志轮转
# 用法：
#   bash scripts/start.sh              # 前台启动（默认）
#   bash scripts/start.sh --daemon     # 后台守护进程启动
#   bash scripts/start.sh --stop       # 停止服务
#   bash scripts/start.sh --status     # 查看服务状态
#   bash scripts/start.sh --restart    # 重启服务
#
# 许可证：GNU AGPL v3 — 详见 LICENSE 文件
# =============================================================================
set -euo pipefail

# ── 莫兰迪色系 ──
COLOR_TITLE='\033[38;5;95m'
COLOR_STEP='\033[38;5;96m'
COLOR_OK='\033[38;5;108m'
COLOR_WARN='\033[38;5;137m'
COLOR_ERROR='\033[38;5;131m'
COLOR_INFO='\033[38;5;102m'
COLOR_RESET='\033[0m'

# 项目根目录
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_ROOT"

# 运行时文件
PID_FILE="$PROJECT_ROOT/.promiselink.pid"
LOG_DIR="$PROJECT_ROOT/logs"
LOG_FILE="$LOG_DIR/promiselink.log"

# 默认配置
PORT="${PORT:-8000}"
HOST="${HOST:-0.0.0.0}"
HEALTH_TIMEOUT=30  # 健康检查超时秒数

# ── 工具函数 ──

print_step() { echo -e "${COLOR_STEP}▶ $1${COLOR_RESET}"; }
print_ok()   { echo -e "${COLOR_OK}  ✓ $1${COLOR_RESET}"; }
print_warn() { echo -e "${COLOR_WARN}  ⚠ $1${COLOR_RESET}"; }
print_error() { echo -e "${COLOR_ERROR}  ✗ $1${COLOR_RESET}"; }
print_info()  { echo -e "${COLOR_INFO}  ℹ $1${COLOR_RESET}"; }

die() {
    print_error "$1"
    exit 1
}

# ── 环境检查 ──

check_environment() {
    print_step "【1/4】环境检查..."

    # 检查 Python
    if ! command -v python3 &>/dev/null; then
        die "未找到 python3，请先运行 bash scripts/install.sh"
    fi

    # 检查 promiselink 包
    if ! python3 -c "import promiselink" 2>/dev/null; then
        print_warn "未检测到 promiselink 包，尝试激活虚拟环境..."
        if [[ -f "$PROJECT_ROOT/.venv/bin/activate" ]]; then
            # shellcheck disable=SC1091
            source "$PROJECT_ROOT/.venv/bin/activate"
            if python3 -c "import promiselink" 2>/dev/null; then
                print_ok "已激活虚拟环境"
            else
                die "promiselink 包未安装，请先运行 bash scripts/install.sh"
            fi
        else
            die "promiselink 包未安装且无虚拟环境，请先运行 bash scripts/install.sh"
        fi
    else
        print_ok "promiselink 包已就绪"
    fi

    # 检查 .env 文件
    if [[ ! -f "$PROJECT_ROOT/.env" ]]; then
        print_warn "未找到 .env，从模板创建..."
        cp "$PROJECT_ROOT/.env.basic.example" "$PROJECT_ROOT/.env"
        print_warn "请编辑 .env 配置 LLM_API_KEY"
    fi

    # 检查默认密钥
    if grep -q "SECRET_KEY=change-me-in-production" "$PROJECT_ROOT/.env" 2>/dev/null; then
        print_warn "检测到默认 SECRET_KEY，正在生成随机密钥..."
        NEW_KEY=$(python3 -c "import secrets; print(secrets.token_urlsafe(32))")
        if [[ "$(uname)" == "Darwin" ]]; then
            sed -i '' "s|SECRET_KEY=change-me-in-production|SECRET_KEY=${NEW_KEY}|" "$PROJECT_ROOT/.env"
        else
            sed -i "s|SECRET_KEY=change-me-in-production|SECRET_KEY=${NEW_KEY}|" "$PROJECT_ROOT/.env"
        fi
        print_ok "已自动生成随机 SECRET_KEY"
    fi

    # 检查 LLM_API_KEY
    if grep -q "LLM_API_KEY=sk-your-key-here" "$PROJECT_ROOT/.env" 2>/dev/null; then
        print_warn "LLM_API_KEY 未配置，AI 功能将不可用"
    fi

    # 创建数据/日志目录
    mkdir -p "$PROJECT_ROOT/data" "$LOG_DIR"

    print_ok "环境检查通过"
}

# ── 数据库迁移 ──

run_migrations() {
    print_step "【2/4】数据库迁移..."

    if python3 -m alembic upgrade head 2>&1 | tail -3; then
        print_ok "数据库迁移完成"
    else
        print_warn "数据库迁移有警告，继续启动..."
    fi
}

# ── 端口检查 ──

check_port() {
    if command -v lsof &>/dev/null; then
        if lsof -i :"$PORT" -t &>/dev/null; then
            local occupying_pid
            occupying_pid=$(lsof -i :"$PORT" -t 2>/dev/null | head -1)
            if [[ -n "$occupying_pid" ]]; then
                # 检查是否是自己的进程
                if [[ -f "$PID_FILE" ]] && [[ "$(cat "$PID_FILE")" == "$occupying_pid" ]]; then
                    print_warn "服务已在运行 (PID: $occupying_pid)"
                    exit 0
                else
                    die "端口 $PORT 已被进程 $occupying_pid 占用，请先停止该进程或修改 PORT 环境变量"
                fi
            fi
        fi
    fi
    print_ok "端口 $PORT 可用"
}

# ── 健康检查 ──

wait_for_health() {
    print_step "【4/4】健康检查..."

    local elapsed=0
    while [[ $elapsed -lt $HEALTH_TIMEOUT ]]; do
        if python3 -c "
import urllib.request
try:
    urllib.request.urlopen('http://127.0.0.1:$PORT/api/v1/health', timeout=2)
    exit(0)
except Exception:
    exit(1)
" 2>/dev/null; then
            print_ok "服务健康检查通过"
            return 0
        fi
        sleep 1
        elapsed=$((elapsed + 1))
    done

    print_warn "健康检查超时（${HEALTH_TIMEOUT}s），服务可能仍在启动中"
    print_info  "可手动检查：curl http://localhost:$PORT/api/v1/health"
    return 0  # 非致命，不阻止启动
}

# ── 启动服务 ──

start_foreground() {
    check_environment
    run_migrations
    check_port

    print_step "【3/4】启动服务（前台模式）..."
    echo -e "${COLOR_INFO}  地址: http://${HOST}:${PORT}${COLOR_RESET}"
    echo -e "${COLOR_INFO}  API 文档: http://${HOST}:${PORT}/docs${COLOR_RESET}"
    echo -e "${COLOR_INFO}  按 Ctrl+C 停止服务${COLOR_RESET}"
    echo ""

    exec python3 -m uvicorn promiselink.main:app --host "$HOST" --port "$PORT" "$@"
}

start_daemon() {
    check_environment
    run_migrations
    check_port

    print_step "【3/4】启动服务（守护进程模式）..."

    # 启动后台进程
    nohup python3 -m uvicorn promiselink.main:app --host "$HOST" --port "$PORT" \
        > "$LOG_FILE" 2>&1 &
    local pid=$!
    echo "$pid" > "$PID_FILE"

    print_ok "服务已启动 (PID: $pid)"
    print_info "日志文件: $LOG_FILE"

    # 等待健康检查
    wait_for_health

    echo ""
    echo -e "${COLOR_OK}╔══════════════════════════════════════════════╗${COLOR_RESET}"
    echo -e "${COLOR_OK}║   ✓ PromiseLink 服务已启动                    ║${COLOR_RESET}"
    echo -e "${COLOR_OK}╚══════════════════════════════════════════════╝${COLOR_RESET}"
    echo ""
    echo -e "${COLOR_INFO}地址: http://${HOST}:${PORT}${COLOR_RESET}"
    echo -e "${COLOR_INFO}API 文档: http://${HOST}:${PORT}/docs${COLOR_RESET}"
    echo -e "${COLOR_INFO}停止: bash scripts/start.sh --stop${COLOR_RESET}"
    echo -e "${COLOR_INFO}状态: bash scripts/start.sh --status${COLOR_RESET}"
    echo -e "${COLOR_INFO}日志: tail -f $LOG_FILE${COLOR_RESET}"
    echo ""
}

# ── 停止服务 ──

stop_service() {
    print_step "停止服务..."

    if [[ ! -f "$PID_FILE" ]]; then
        print_warn "未找到 PID 文件，服务可能未运行"
        # 尝试通过端口查找
        if command -v lsof &>/dev/null; then
            local pid
            pid=$(lsof -i :"$PORT" -t 2>/dev/null | head -1)
            if [[ -n "$pid" ]]; then
                print_info "通过端口发现进程 (PID: $pid)，正在停止..."
                kill "$pid" 2>/dev/null || true
                sleep 2
                if kill -0 "$pid" 2>/dev/null; then
                    print_warn "进程未响应，强制终止..."
                    kill -9 "$pid" 2>/dev/null || true
                fi
                print_ok "服务已停止"
            else
                print_info "端口 $PORT 上无运行进程"
            fi
        fi
        return 0
    fi

    local pid
    pid=$(cat "$PID_FILE")

    if kill -0 "$pid" 2>/dev/null; then
        print_info "正在停止进程 (PID: $pid)..."
        kill "$pid" 2>/dev/null || true

        # 等待进程退出（最多10秒）
        local waited=0
        while kill -0 "$pid" 2>/dev/null && [[ $waited -lt 10 ]]; do
            sleep 1
            waited=$((waited + 1))
        done

        if kill -0 "$pid" 2>/dev/null; then
            print_warn "进程未响应，强制终止..."
            kill -9 "$pid" 2>/dev/null || true
        fi
        print_ok "服务已停止"
    else
        print_warn "进程 $pid 已不存在"
    fi

    rm -f "$PID_FILE"
}

# ── 查看状态 ──

show_status() {
    echo -e "${COLOR_TITLE}PromiseLink 服务状态${COLOR_RESET}"
    echo "========================"

    if [[ -f "$PID_FILE" ]]; then
        local pid
        pid=$(cat "$PID_FILE")
        if kill -0 "$pid" 2>/dev/null; then
            print_ok "服务运行中 (PID: $pid)"
            print_info "端口: $PORT"
            print_info "日志: $LOG_FILE"

            # 健康检查
            if python3 -c "
import urllib.request
try:
    resp = urllib.request.urlopen('http://127.0.0.1:$PORT/api/v1/health', timeout=2)
    print(resp.read().decode())
except Exception:
    exit(1)
" 2>/dev/null; then
                print_ok "健康检查: 通过"
            else
                print_warn "健康检查: 失败（服务可能仍在启动）"
            fi
        else
            print_error "服务未运行（PID $pid 已不存在）"
            rm -f "$PID_FILE"
        fi
    else
        print_warn "服务未运行（无 PID 文件）"
        # 检查端口
        if command -v lsof &>/dev/null; then
            local pid
            pid=$(lsof -i :"$PORT" -t 2>/dev/null | head -1)
            if [[ -n "$pid" ]]; then
                print_warn "但端口 $PORT 被进程 $pid 占用（非本脚本启动）"
            fi
        fi
    fi
}

# ── 日志轮转（简单版：保留最近 5MB）──

rotate_logs() {
    if [[ -f "$LOG_FILE" ]]; then
        local size
        size=$(wc -c < "$LOG_FILE" 2>/dev/null || echo 0)
        if [[ $size -gt 5242880 ]]; then  # 5MB
            mv "$LOG_FILE" "${LOG_FILE}.$(date +%Y%m%d_%H%M%S).bak"
            gzip "${LOG_FILE}."*.bak 2>/dev/null || true
            # 保留最近 3 个归档
            ls -t "${LOG_FILE}."*.bak.gz 2>/dev/null | tail -n +4 | xargs rm -f 2>/dev/null || true
            print_info "日志已轮转"
        fi
    fi
}

# ── 主入口 ──

main() {
    local mode="${1:-start}"

    case "$mode" in
        --daemon|-d)
            rotate_logs
            start_daemon
            ;;
        --stop|-s)
            stop_service
            ;;
        --status)
            show_status
            ;;
        --restart|-r)
            stop_service
            sleep 2
            rotate_logs
            start_daemon
            ;;
        start|--start)
            start_foreground
            ;;
        *)
            echo "用法: bash scripts/start.sh [start|--daemon|--stop|--status|--restart]"
            echo ""
            echo "选项:"
            echo "  start (默认)    前台启动"
            echo "  --daemon, -d    后台守护进程启动"
            echo "  --stop, -s      停止服务"
            echo "  --status        查看服务状态"
            echo "  --restart, -r   重启服务"
            exit 1
            ;;
    esac
}

main "$@"
