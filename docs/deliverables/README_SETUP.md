# PromiseLink 安装指南

> **本文档已整合到 [QUICKSTART.md](../../QUICKSTART.md)**
>
> 请访问 [QUICKSTART.md](../../QUICKSTART.md) 获取最新的快速启动指南，包括：
> - 前置条件
> - 依赖安装
> - 环境变量配置（LLM_PROVIDER 预设）
> - 服务启动
> - 核心功能使用
> - 配置参考
> - FAQ

## 快速启动

```bash
# 1. 安装依赖
cd PromiseLink
pip install -e ".[dev]"

# 2. 配置环境变量
cp .env.basic.example .env
# 编辑 .env 填入 LLM_API_KEY

# 3. 启动服务（本地直接运行，无需Docker）
bash scripts/start.sh
# 或
python -m uvicorn promiselink.main:app --host 0.0.0.0 --port 8000

# 4. 访问
# API 文档：http://localhost:8000/docs
# 前端界面：http://localhost:8000
```

## 一键安装

```bash
bash scripts/install.sh
```

详见 [QUICKSTART.md](../../QUICKSTART.md) 和 [scripts/install.sh](../../scripts/install.sh)。
