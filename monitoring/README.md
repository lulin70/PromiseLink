# Monitoring — PromiseLink 监控配置

> **注意**: 此目录下的 Prometheus 和 Alertmanager 配置为**专业版/定制版**功能。
>
> **基础版**（本地部署）不包含 metrics 端点，Prometheus 抓取会返回 404。
> 基础版用户可通过 `/api/v1/health` 端点和应用日志进行健康检查。

## 文件说明

| 文件 | 用途 | 适用版本 |
|------|------|----------|
| `prometheus.yml` | Prometheus 抓取配置（`/api/v1/metrics`） | 专业版/定制版 |
| `alerts.yml` | 告警规则（服务宕机/高错误率/慢响应） | 专业版/定制版 |

## 专业版启用方式

专业版需在 `main.py` 中集成 `prometheus-fastapi-instrumentator` 并注册 `/api/v1/metrics` 端点：

```python
from prometheus_fastapi_instrumentator import Instrumentator
Instrumentator().instrument(app).expose(app, endpoint="/api/v1/metrics")
```

## 基础版健康检查

基础版用户使用以下方式监控：

```bash
# 健康检查
curl http://localhost:8000/api/v1/health

# 查看应用日志
tail -f logs/promiselink.log
```
