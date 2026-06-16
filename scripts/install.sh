#!/usr/bin/env bash
# PromiseLink 一键安装脚本
set -e

echo "🔧 PromiseLink 安装脚本"
echo "========================"

# 检查 Python 版本
if ! command -v python3 &> /dev/null; then
    echo "❌ 未找到 python3，请先安装 Python 3.11+"
    exit 1
fi

PYTHON_VERSION=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
echo "✅ Python 版本: $PYTHON_VERSION"

# 检查 Python 版本 >= 3.11
python3 -c "
import sys
if sys.version_info < (3, 11):
    print('❌ Python 版本需要 3.11+')
    sys.exit(1)
"

# 安装依赖
echo ""
echo "📦 安装依赖..."
pip install -e ".[dev]"

# 创建数据目录
echo ""
echo "📁 创建数据目录..."
mkdir -p data

# 检查 .env 文件
if [ ! -f .env ]; then
    echo ""
    echo "⚙️  创建默认配置文件..."
    cp .env.basic.example .env
    echo "⚠️  请编辑 .env 文件，至少配置 LLM_API_KEY"
fi

echo ""
echo "✅ 安装完成！"
echo ""
echo "下一步："
echo "  1. 编辑 .env，配置 LLM_API_KEY"
echo "  2. 运行 bash scripts/start.sh 启动服务"
