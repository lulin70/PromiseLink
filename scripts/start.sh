#!/usr/bin/env bash
# PromiseLink 一键启动脚本（含默认密钥检测）
set -e

echo "🚀 PromiseLink 启动脚本"
echo "========================"

# 检查是否已安装
if ! python3 -c "import promiselink" 2>/dev/null; then
    echo "⚠️  未检测到 promiselink，正在安装..."
    pip install -e ".[dev]" -q
fi

# 检查 .env 文件
if [ ! -f .env ]; then
    echo "⚙️  未找到 .env，从模板创建..."
    cp .env.basic.example .env
    echo "⚠️  请编辑 .env 文件，至少配置 LLM_API_KEY"
fi

# 检测默认密钥
if grep -q "SECRET_KEY=change-me-in-production" .env 2>/dev/null; then
    echo "⚠️  检测到默认 SECRET_KEY"
    echo "   开发环境将自动生成随机密钥（重启后 token 失效）"
    echo "   生产环境请务必修改：python -c \"import secrets; print(secrets.token_urlsafe(32))\""
fi

# 检测 LLM_API_KEY
if grep -q "LLM_API_KEY=sk-your-key-here" .env 2>/dev/null || \
   grep -q "LLM_API_KEY=$" .env 2>/dev/null || \
   grep -q "LLM_API_KEY=$" .env 2>/dev/null; then
    echo "⚠️  LLM_API_KEY 未配置，AI 功能将不可用"
    echo "   请在 .env 中设置 LLM_API_KEY"
fi

# 创建数据目录
mkdir -p data

# 确定端口
PORT=${PORT:-8000}
HOST=${HOST:-0.0.0.0}

echo ""
echo "🌐 启动服务: http://${HOST}:${PORT}"
echo "📖 API 文档: http://${HOST}:${PORT}/docs"
echo ""

python3 -m uvicorn promiselink.main:app --host "$HOST" --port "$PORT" "$@"
