# Edition Architecture — PromiseLink 基础版/专业版架构

## 1. 版本对比

| 功能 | 基础版 (Basic) | 专业版 (Pro) |
|------|:---:|:---:|
| 事件录入 (手动/文件上传) | ✅ | ✅ |
| 实体抽取与归一 | ✅ | ✅ |
| Todo 生成与状态机 | ✅ | ✅ |
| 承诺双向追踪 | ✅ | ✅ |
| 仪表盘 (日视图) | ✅ | ✅ |
| 关系简报 | ✅ | ✅ |
| 需求输入 | ✅ | ✅ |
| 数据导出 | ✅ | ✅ |
| 预定日程 | ✅ | ✅ |
| 提醒 | ✅ | ✅ |
| 语音助手 (ASR/NLU) | ❌ | ✅ |
| 语音查询 | ❌ | ✅ |
| 媒体处理 (ASR/TTS/OCR) | ❌ | ✅ |
| 邮件同步 | ❌ | ✅ |
| 微信转发 | ❌ | ✅ |
| CSV 批量导入 | ❌ | ✅ |
| 隐私数据管理 | ❌ | ✅ |

## 2. 安全模型

**核心原则：安全靠服务凭证，不靠代码隐藏。**

- 基础版和专业版使用同一套代码库，通过 `APP_EDITION` 配置区分
- Pro-only 路由在应用启动时条件注册，basic 模式下路由不存在（返回 404）
- 所有 API 均需认证（JWT），版本控制不替代认证授权
- 敏感操作（数据删除等）有二次确认机制

## 3. 实现细节

### 3.1 APP_EDITION 配置

```python
# config.py
app_edition: str = "basic"  # "basic" or "pro"
```

- 通过环境变量 `APP_EDITION` 设置
- `field_validator` 确保值只能是 "basic" 或 "pro"
- 默认为 "basic"

### 3.2 条件路由注册

```python
# main.py
# Basic routes — always registered
app.include_router(health.router, ...)
app.include_router(auth.router, ...)
# ... 其他基础路由

# Pro-only routes — only when app_edition == "pro"
if settings.app_edition == "pro":
    from promiselink.api.v1 import voice, voice_query, media, ...
    app.include_router(voice.router, ...)
    # ... 其他专业版路由
```

- Pro-only 路由使用延迟导入（lazy import），basic 模式下不加载相关模块
- 路由不存在时返回标准 404，不暴露版本信息

### 3.3 测试隔离

Pro-only 功能的测试使用 `pytest.mark.skipif` 装饰器：

```python
pytestmark = pytest.mark.skipif(
    os.environ.get("APP_EDITION", "basic") != "pro",
    reason="XXX API is a Pro-only feature",
)
```

## 4. 托管 PoC 四层防护

| 层级 | 措施 | 说明 |
|------|------|------|
| L1 路由层 | 条件注册 | basic 模式下 Pro 路由不存在 |
| L2 认证层 | JWT + PoC Secret | 所有 API 需认证 |
| L3 网络层 | 反向代理 | 仅暴露必要端口 |
| L4 数据层 | 用户隔离 | 所有查询强制 user_id 过滤 |
