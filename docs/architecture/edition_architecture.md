# Edition Architecture — PromiseLink 基础版/专业版架构

> **版本**: v1.0
> **日期**: 2026-06-17
> **对应PRD**: v5.2
> **对应技术设计**: v3.2

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

**核心原则：安全靠服务凭证 + 仓库物理隔离，不靠代码隐藏。**

> ⚠️ **架构变更（2026-06-18）**：原方案"同代码库 + `APP_EDITION` 配置区分"已废弃，改为"双 repo + API 桥接"。详见 §5 仓库策略及 `Repo_Split_Decision.md`。

- 基础版和专业版**分属不同 repo**，物理隔离公开/私有代码（不再用 monorepo + 配置区分）
- 专业版代码（网关、专业版服务/路由）不在公开 repo 中，从根本上杜绝泄漏
- 所有 API 均需认证（JWT），版本控制不替代认证授权
- 敏感操作（数据删除等）有二次确认机制

## 3. 实现细节

> ⚠️ **过渡期说明（2026-06-18）**：以下 §3.1-§3.3 描述的是旧方案"同代码库 + `APP_EDITION` 配置区分"的实现细节。该方案已决定废弃（见 §5 仓库策略），专业版代码将迁出至私有 repo。迁移完成前，基础版 repo 仍保留 `APP_EDITION` 字段用于兼容；迁移完成后，公开 repo 中 `APP_EDITION` 固定为 `basic`，专业版路由代码不再存在于公开 repo。

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
| L1 路由层 | 仓库隔离 + 条件注册 | 专业版代码不在公开 repo；过渡期 basic 模式下 Pro 路由不注册 |
| L2 认证层 | JWT + PoC Secret | 所有 API 需认证 |
| L3 网络层 | 反向代理 | 仅暴露必要端口 |
| L4 数据层 | 用户隔离 | 所有查询强制 user_id 过滤 |

---

## 5. 仓库策略 (Repo Strategy)

> **变更日期**: 2026-06-18
> **决策文档**: `docs/architecture/Repo_Split_Decision.md`
> **依据**: `docs/external/for_team/PromiseLink_代码安全规范_2026-06-17.md` 铁律——不用 monorepo + .gitignore 隔离公开和私有代码

### 5.1 双 repo + API 桥接

**废弃** 旧方案"同代码库 + `APP_EDITION` 配置区分"。
**采用** 新方案"双 repo + API 桥接"。

| 维度 | 旧方案（废弃） | 新方案（采用） |
|------|---------------|---------------|
| 代码组织 | 单一 monorepo，配置区分 | 双 repo，物理隔离 |
| 公开/私有隔离 | `.gitignore` + 配置开关 | 独立仓库 + 访问权限 |
| 版本区分 | `APP_EDITION=basic/pro` | 不同 repo，不同代码集 |
| 专业版保护 | 路由不注册（返回 404） | 代码不在公开 repo 中 |
| 桥接方式 | 无（同进程） | `relay_client` ↔ 网关 API |

### 5.2 仓库清单

| 仓库 | 地址 | 可见性 | 许可证 | 内容 |
|------|------|--------|--------|------|
| **基础版** | `lulin70/PromiseLink` | 🌐 公开 | AGPL v3 | 基础版全部代码 + `relay_client` 公开子包 |
| **专业版** | `lulin70/PromiseLink-Pro` | 🔒 私有 | 商业许可 (Commercial) | 网关 + 小程序 + 专业版特有代码 |

### 5.3 代码归属

**基础版 repo（公开 AGPL v3）**：
- `src/promiselink/` — 基础版核心（事件管线、实体抽取、待办、承诺、仪表盘等）+ `relay_client.py`（公开子包）
- `frontend/` — Taro H5 前端
- `tests/` — 基础版测试
- `scripts/` — 安装/启动脚本
- 专业版服务模块（ASR/TTS/OCR/NLU/NLG/邮件/微信转发）和专业版路由（voice/media/email/wechat/csv/privacy）迁出至私有 repo

**专业版 repo（私有商业许可）**：
- `gateway/` — 云端 AI 网关（从公开 repo 迁入）
- `miniapp/` — 微信小程序
- `pro-services/` — 专业版服务模块（从 `src/promiselink/services/` 迁出）
- `pro-api/` — 专业版 API 路由（从 `src/promiselink/api/v1/` 迁出）
- `pro-config/` — 专业版配置覆盖

> 完整代码归属划分见 `Repo_Split_Decision.md` §3。

### 5.4 共享接口：relay_client ↔ gateway API

基础版与专业版通过 API 桥接，而非共享代码库：

```
基础版 (公开 repo)                    专业版 (私有 repo)
┌──────────────────────┐            ┌──────────────────────┐
│ 用户本地 Docker        │   WSS出站   │ 云端 AI 网关          │
│                      │  ────────> │                      │
│ relay_client ────────┼────────────┼─> 中继路由器           │
│ (公开子包)            │            │  AI代理层 ─> LLM API  │
│                      │  <─────────┼─ 许可验证/计费         │
│ 基础版业务逻辑         │   响应回传   │                      │
└──────────────────────┘            └──────────────────────┘
```

- **`relay_client`（基础版公开子包）**：随基础版 repo 开源，专业版用户本地 Docker 启用此模块连接网关
- **网关 API（专业版私有服务）**：独立云端服务，不公开代码
- **基础版核心（公开依赖）**：专业版本地部署通过 git submodule 或 pip 包引用基础版核心，叠加专业版模块

### 5.5 迁移计划摘要

| 阶段 | 内容 | 时间窗口 | 优先级 |
|------|------|----------|--------|
| Phase 1 | `gateway/` 迁移至私有 repo + git history 清理 | 1-2 天 | 🔴 立即执行 |
| Phase 2 | 专业版服务/路由模块迁出 + 基础版测试清理 | 3-5 天 | 🟡 公开发布前完成 |
| Phase 3 | 微信小程序整合至私有 repo | 1-2 天 | 🟢 专业版发布前完成 |

> 完整迁移计划及风险评估见 `Repo_Split_Decision.md` §5-§6。
