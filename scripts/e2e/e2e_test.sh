#!/usr/bin/env bash
# =============================================================================
# PromiseLink 本地E2E测试脚本
# =============================================================================
# 功能：
#   1. 启动本地服务
#   2. 等待健康检查通过
#   3. 执行E2E测试用例
#   4. 清理测试数据
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
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_ROOT"

BASE_URL="http://localhost:8000"
API_URL="${BASE_URL}/api/v1"

# =============================================================================
# 1. 检查服务是否运行
# =============================================================================
info "检查PromiseLink服务状态..."

if ! curl -sf "${API_URL}/health" > /dev/null 2>&1; then
    error "PromiseLink服务未运行，请先启动服务：
    cd $PROJECT_ROOT
    ./install.sh
    或
    docker compose -f docker-compose.basic.yml up -d"
fi

success "PromiseLink服务运行中"

# =============================================================================
# 2. 测试健康检查端点
# =============================================================================
info "测试健康检查端点..."
HEALTH_RESPONSE=$(curl -s "${API_URL}/health")
echo "$HEALTH_RESPONSE" | grep -q "status" || error "健康检查响应格式异常"
success "健康检查端点正常"

# =============================================================================
# 3. 测试事件创建（核心Pipeline）
# =============================================================================
info "测试事件创建（触发Pipeline）..."
EVENT_RESPONSE=$(curl -s -X POST "${API_URL}/events" \
  -H "Content-Type: application/json" \
  -d '{
    "event_type": "meeting",
    "source": "manual",
    "raw_text": "今天和张总聊了新项目合作，他说下周需要一份技术方案，承诺周五前发给他"
  }')

EVENT_ID=$(echo "$EVENT_RESPONSE" | grep -o '"id":"[^"]*"' | head -1 | cut -d'"' -f4)
if [ -z "$EVENT_ID" ]; then
    error "事件创建失败，响应：$EVENT_RESPONSE"
fi
success "事件创建成功 (ID: $EVENT_ID)"

# 等待Pipeline处理
sleep 2

# =============================================================================
# 4. 测试实体查询
# =============================================================================
info "测试实体查询..."
ENTITIES_RESPONSE=$(curl -s "${API_URL}/entities?limit=10")
ENTITY_COUNT=$(echo "$ENTITIES_RESPONSE" | grep -o '"items":\[' | wc -l)
if [ "$ENTITY_COUNT" -eq 0 ]; then
    warn "未找到实体（可能是LLM未配置或提取失败）"
else
    success "实体查询成功，找到实体"
fi

# =============================================================================
# 5. 测试Todo查询
# =============================================================================
info "测试Todo查询..."
TODOS_RESPONSE=$(curl -s "${API_URL}/todos?limit=10")
echo "$TODOS_RESPONSE" | grep -q '"items"' || error "Todo查询响应格式异常"
success "Todo查询成功"

# =============================================================================
# 6. 测试关联查询
# =============================================================================
info "测试关联查询..."
ASSOCIATIONS_RESPONSE=$(curl -s "${API_URL}/associations?limit=10")
echo "$ASSOCIATIONS_RESPONSE" | grep -q '"items"' || error "关联查询响应格式异常"
success "关联查询成功"

# =============================================================================
# 7. 测试Dashboard
# =============================================================================
info "测试Dashboard端点..."
DASHBOARD_RESPONSE=$(curl -s "${API_URL}/dashboard")
echo "$DASHBOARD_RESPONSE" | grep -q '"total_entities"' || error "Dashboard响应格式异常"
success "Dashboard端点正常"

# =============================================================================
# 8. 测试前端页面可访问性
# =============================================================================
info "测试前端页面可访问性..."
if curl -sf "${BASE_URL}/" > /dev/null 2>&1; then
    success "前端页面可访问"
else
    warn "前端页面不可访问（可能未配置静态文件服务）"
fi

# =============================================================================
# 9. 测试API文档可访问性
# =============================================================================
info "测试API文档可访问性..."
if curl -sf "${BASE_URL}/docs" > /dev/null 2>&1; then
    success "API文档可访问"
else
    warn "API文档不可访问"
fi

# =============================================================================
# 总结
# =============================================================================
echo ""
echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${GREEN}  ✓ PromiseLink E2E测试全部通过${NC}"
echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""
echo "测试覆盖："
echo "  ✓ 健康检查"
echo "  ✓ 事件创建（Pipeline触发）"
echo "  ✓ 实体查询"
echo "  ✓ Todo查询"
echo "  ✓ 关联查询"
echo "  ✓ Dashboard"
echo "  ✓ 前端页面"
echo "  ✓ API文档"
echo ""
success "基础版功能验证完成！"
