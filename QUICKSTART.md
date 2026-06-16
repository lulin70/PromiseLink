# PromiseLink 快速开始

## 前置条件

- Python 3.11+
- LLM API Key（推荐 DeepSeek / Moka AI / OpenAI）

## 快速启动

### 1. 安装依赖

```bash
cd PromiseLink
pip install -e ".[dev]"
```

### 2. 配置环境变量

```bash
cp .env.basic.example .env
```

编辑 `.env`，至少配置：

```env
LLM_API_KEY=sk-your-key-here
LLM_BASE_URL=https://api.moka-ai.com/v1
LLM_MODEL=moka/claude-sonnet-4-6
```

> 开发环境下 `SECRET_KEY` 会自动生成随机密钥，无需手动配置。

### 3. 启动服务

```bash
python -m uvicorn promiselink.main:app --host 0.0.0.0 --port 8000
```

或使用一键启动脚本：

```bash
bash scripts/start.sh
```

### 4. 访问

- API 文档：http://localhost:8000/docs
- 健康检查：http://localhost:8000/api/v1/health
- 前端界面：http://localhost:8000

## 核心功能

### 录入互动记录

```bash
curl -X POST http://localhost:8000/api/v1/events \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <token>" \
  -d '{
    "event_type": "meeting",
    "source": "manual",
    "title": "与李总讨论合作",
    "raw_text": "今天上午和李总讨论了新项目的合作方案..."
  }'
```

### 查看 Todo

```bash
curl http://localhost:8000/api/v1/todos \
  -H "Authorization: Bearer <token>"
```

### 承诺追踪

```bash
curl http://localhost:8000/api/v1/promises?view=my-promises \
  -H "Authorization: Bearer <token>"
```

## 配置参考

| 环境变量 | 默认值 | 说明 |
|----------|--------|------|
| `APP_EDITION` | `basic` | 版本：basic（基础版）或 pro（专业版） |
| `SECRET_KEY` | 自动生成 | JWT 签名密钥，生产环境必须配置 |
| `POC_SECRET` | `promiselink2026` | PoC 登录密码 |
| `LLM_API_KEY` | 空 | LLM API 密钥 |
| `LLM_BASE_URL` | `https://api.moka-ai.com/v1` | LLM API 地址 |
| `LLM_MODEL` | `moka/claude-sonnet-4-6` | LLM 模型名称 |
| `DATABASE_URL` | `sqlite:///./data/promiselink.db` | 数据库连接 |
| `LOG_LEVEL` | `INFO` | 日志级别 |

## FAQ

**Q: 启动报错 "secret_key must be changed"？**
A: 非 development 环境必须设置 `SECRET_KEY`。生成方法：`python -c "import secrets; print(secrets.token_urlsafe(32))"`

**Q: 如何切换到专业版？**
A: 设置环境变量 `APP_EDITION=pro`，重启服务即可启用语音、邮件同步等专业功能。

**Q: 忘记 PoC 密码怎么办？**
A: 在 `.env` 中修改 `POC_SECRET` 的值，重启服务生效。
