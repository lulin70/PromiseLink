# Monitoring — PromiseLink 监控配置

> **注意**: 此目录下的 Prometheus 和 Alertmanager 配置适用于**基础版和专业版**。
>
> **基础版**已包含 `/api/v1/metrics` 端点（Prometheus 格式），提供 HTTP 请求计数、响应时间直方图、事件处理指标等。
> 基础版用户也可通过 `/api/v1/health` 端点和应用日志进行健康检查。

## 文件说明

| 文件 | 用途 |
|------|------|
| `prometheus.yml` | Prometheus 抓取配置（`/api/v1/metrics`） |
| `alerts.yml` | 告警规则（服务宕机/高错误率/慢响应） |

## 启用方式

Prometheus 已在 `main.py` 中通过 `prometheus-client` 集成，指标端点 `/api/v1/metrics` 默认开放（无认证便于抓取）。

配置 Prometheus 抓取：
```yaml
# prometheus.yml
scrape_configs:
  - job_name: 'promiselink'
    scrape_interval: 15s
    static_configs:
      - targets: ['localhost:8000']
    metrics_path: '/api/v1/metrics'
```

## 健康检查

所有版本用户均可使用以下方式监控：

```bash
# 基础健康检查
curl http://localhost:8000/api/v1/health

# 数据库连通性检查（需认证）
curl -H "Authorization: Bearer <token>" http://localhost:8000/api/v1/health/db

# 完整健康检查（需认证）
curl -H "Authorization: Bearer <token>" http://localhost:8000/api/v1/health/full

# Prometheus 指标
curl http://localhost:8000/api/v1/metrics

# 查看应用日志
tail -f logs/promiselink.log
```
