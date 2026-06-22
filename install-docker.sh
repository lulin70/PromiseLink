#!/usr/bin/env bash
# =============================================================================
# PromiseLink 基础版 一键安装脚本
# =============================================================================
# 用法：
#   chmod +x install.sh
#   ./install.sh
#
# 功能：
#   1. 检查 Docker 和 Docker Compose 是否安装
#   2. 创建 .env.basic 配置文件
#   3. 提示用户输入 LLM_API_KEY
#   4. 自动生成随机 SECRET_KEY
#   5. 创建数据目录
#   6. 构建并启动容器
#   7. 等待健康检查通过
#   8. 打印访问地址
# =============================================================================

set -euo pipefail

# ---- 颜色定义 ----
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# ---- 辅助函数 ----
info()    { echo -e "${BLUE}[INFO]${NC} $*"; }
success() { echo -e "${GREEN}[OK]${NC} $*"; }
warn()    { echo -e "${YELLOW}[WARN]${NC} $*"; }
error()   { echo -e "${RED}[ERROR]${NC} $*"; exit 1; }

# ---- 项目根目录 ----
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

ENV_FILE=".env.basic"
ENV_EXAMPLE=".env.basic.example"
COMPOSE_FILE="docker-compose.basic.yml"

# =============================================================================
# 1. 检查前置依赖
# =============================================================================
info "检查前置依赖..."

if ! command -v docker &> /dev/null; then
    error "Docker 未安装。请先安装 Docker: https://docs.docker.com/get-docker/"
fi

if ! docker info &> /dev/null; then
    error "Docker 未运行。请先启动 Docker。"
fi

# 检查 docker compose（v2 插件）或 docker-compose（v1 独立版）
if docker compose version &> /dev/null 2>&1; then
    COMPOSE_CMD="docker compose"
elif command -v docker-compose &> /dev/null; then
    COMPOSE_CMD="docker-compose"
else
    error "Docker Compose 未安装。请先安装 Docker Compose: https://docs.docker.com/compose/install/"
fi

success "Docker 和 Docker Compose 已就绪 ($COMPOSE_CMD)"

# =============================================================================
# 2. 创建 .env.basic 配置文件
# =============================================================================
if [ -f "$ENV_FILE" ]; then
    info "配置文件 $ENV_FILE 已存在，跳过创建"
else
    if [ ! -f "$ENV_EXAMPLE" ]; then
        error "找不到模板文件 $ENV_EXAMPLE，请确认项目完整性"
    fi
    cp "$ENV_EXAMPLE" "$ENV_FILE"
    success "已从模板创建 $ENV_FILE"
fi

# =============================================================================
# 3. 提示用户输入 LLM_API_KEY
# =============================================================================
# 检查 .env.basic 中是否已有有效的 LLM_API_KEY
CURRENT_KEY=$(grep -E "^LLM_API_KEY=" "$ENV_FILE" 2>/dev/null | cut -d'=' -f2- || true)

if [ -z "$CURRENT_KEY" ] || [ "$CURRENT_KEY" = "sk-your-key-here" ] || [ "$CURRENT_KEY" = "" ]; then
    echo ""
    warn "LLM_API_KEY 尚未配置"
    echo -e "${YELLOW}请输入您的 LLM API Key:${NC}"
    echo -e "${YELLOW}  推荐方案:${NC}"
    echo -e "${YELLOW}    1. DeepSeek — https://platform.deepseek.com (新用户有免费额度)${NC}"
    echo -e "${YELLOW}    2. Moka AI  — https://moka-ai.com${NC}"
    echo -e "${YELLOW}    3. OpenAI   — https://platform.openai.com${NC}"
    echo -e "${YELLOW}  费用参考: 日均10条交互约 ¥0.1-0.5${NC}"
    echo -e "${YELLOW}API Key:${NC}"
    read -r USER_KEY

    if [ -z "$USER_KEY" ]; then
        warn "未输入 API Key，服务启动后 LLM 功能将不可用"
        warn "您可以稍后编辑 $ENV_FILE 手动配置"
    else
        # 更新 .env.basic 中的 LLM_API_KEY
        if grep -q "^LLM_API_KEY=" "$ENV_FILE"; then
            sed -i.bak "s|^LLM_API_KEY=.*|LLM_API_KEY=${USER_KEY}|" "$ENV_FILE" && rm -f "${ENV_FILE}.bak"
        else
            echo "LLM_API_KEY=${USER_KEY}" >> "$ENV_FILE"
        fi
        success "LLM_API_KEY 已配置"
    fi
else
    success "LLM_API_KEY 已配置"
fi

# =============================================================================
# 4. 生成随机 SECRET_KEY
# =============================================================================
CURRENT_SECRET=$(grep -E "^SECRET_KEY=" "$ENV_FILE" 2>/dev/null | cut -d'=' -f2- || true)

if [ -z "$CURRENT_SECRET" ] || [ "$CURRENT_SECRET" = "change-me-in-production" ]; then
    GENERATED_SECRET=$(python3 -c "import secrets; print(secrets.token_urlsafe(32))" 2>/dev/null || openssl rand -base64 32 | tr -d '\n')
    if grep -q "^SECRET_KEY=" "$ENV_FILE"; then
        sed -i.bak "s|^SECRET_KEY=.*|SECRET_KEY=${GENERATED_SECRET}|" "$ENV_FILE" && rm -f "${ENV_FILE}.bak"
    else
        echo "SECRET_KEY=${GENERATED_SECRET}" >> "$ENV_FILE"
    fi
    success "已自动生成随机 SECRET_KEY"
else
    success "SECRET_KEY 已配置"
fi

# =============================================================================
# 5. 创建数据目录
# =============================================================================
mkdir -p data
success "数据目录 ./data 已就绪"

# =============================================================================
# 6. 构建并启动容器
# =============================================================================
info "构建并启动 PromiseLink 基础版..."
$COMPOSE_CMD -f "$COMPOSE_FILE" up -d --build

# =============================================================================
# 7. 等待健康检查通过
# =============================================================================
info "等待服务启动（健康检查）..."
MAX_WAIT=120
WAITED=0
INTERVAL=5

while [ $WAITED -lt $MAX_WAIT ]; do
    if curl -sf http://localhost:8000/api/v1/health > /dev/null 2>&1; then
        echo ""
        success "PromiseLink 基础版已成功启动！"
        echo ""
        echo -e "  ${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
        echo -e "  ${GREEN}  PromiseLink 基础版已就绪${NC}"
        echo -e "  ${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
        echo -e "  ${BLUE}  访问地址:${NC}  http://localhost:8000"
        echo -e "  ${BLUE}  API 文档:${NC}  http://localhost:8000/docs"
        echo -e "  ${BLUE}  健康检查:${NC}  http://localhost:8000/api/v1/health"
        echo ""
        echo -e "  ${YELLOW}  常用命令:${NC}"
        echo "    查看日志:  $COMPOSE_CMD -f $COMPOSE_FILE logs -f"
        echo "    停止服务:  $COMPOSE_CMD -f $COMPOSE_FILE down"
        echo "    重启服务:  $COMPOSE_CMD -f $COMPOSE_FILE restart"
        echo ""
        exit 0
    fi
    sleep $INTERVAL
    WAITED=$((WAITED + INTERVAL))
    echo -n "."
done

echo ""
warn "服务启动超时（${MAX_WAIT}秒），请检查日志："
echo "  $COMPOSE_CMD -f $COMPOSE_FILE logs -f"
exit 1
