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

---

## 6. UI 架构 (UI Architecture)

> **变更日期**: 2026-06-18
> **设计目标**: 基础版与专业版面向不同使用场景（PC宽屏办公 vs 手机移动外出），UI架构独立设计、独立部署，不共享前端代码。

### 6.1 两版 UI 定位差异

| 维度 | 基础版 UI | 专业版 UI |
|------|-----------|-----------|
| **使用场景** | 家用电脑办公桌前 | 出门在外随手记录 |
| **目标设备** | 桌面浏览器（PC/Mac） | 微信小程序（手机） |
| **屏幕尺寸** | 宽屏 ≥1024px | 竖屏 375px（iPhone基准） |
| **布局** | 三栏布局（导航/列表/详情） | 单栏布局（卡片堆叠） |
| **技术栈** | Taro H5 + React | Taro 微信小程序 + React |
| **构建产物** | `dist/` 静态文件 | `weapp/` 微信小程序包 |
| **部署方式** | 后端 StaticFiles 挂载 | 微信开发者工具上传 |
| **访问入口** | `http://localhost:8000/` | 微信内搜索/扫码 |
| **代码位置** | `PromiseLink/frontend/`（公开 repo） | `PromiseLink-Pro/miniapp/`（私有 repo） |

### 6.2 基础版 UI（电脑宽屏）

**设计原则**：充分利用宽屏空间，信息密度高，适合长时间深度操作。

**三栏布局**：
```
┌─────────┬──────────────────┬──────────────────────┐
│ 左栏     │ 中栏               │ 右栏                  │
│ 导航     │ 列表               │ 详情                  │
│         │                   │                      │
│ 仪表盘   │ 事件列表           │ 事件详情              │
│ 事件     │ ├─ 待确认          │ ├─ 人脉              │
│ 人脉     │ ├─ 已处理          │ ├─ 待办              │
│ 待办     │ └─ 已归档          │ ├─ 承诺              │
│ 承诺     │                   │ └─ 关联跳转            │
│ 预定日程  │                   │                      │
│ 设置     │                   │                      │
└─────────┴──────────────────┴──────────────────────┘
   200px        320px              剩余空间（≥504px）
```

**响应式断点**：
- `≥1024px`：三栏布局（默认）
- `768px-1023px`：两栏布局（导航折叠为顶部菜单，列表+详情）
- `<768px`：单栏布局（不推荐，提示用户使用宽屏或切换专业版小程序）

**技术栈**：
- **框架**: Taro 4.x + React 18
- **构建目标**: H5
- **UI组件**: 自研 Morandi 色系组件（避免刺眼emoji）
- **状态管理**: React Context + useReducer
- **路由**: Taro Router（hash 模式）

**代码组织**（`PromiseLink/frontend/`）：
```
frontend/
├── src/
│   ├── pages/              # 页面组件
│   │   ├── Dashboard/      # 仪表盘
│   │   ├── Events/         # 事件列表+详情
│   │   ├── Contacts/       # 人脉
│   │   ├── Todos/          # 待办
│   │   ├── Promises/       # 承诺
│   │   └── Schedules/      # 预定日程
│   ├── components/         # 通用组件
│   ├── services/           # API 调用封装
│   ├── styles/             # Morandi 色系样式
│   └── app.tsx             # 入口
├── package.json
└── config/                 # Taro 构建配置
```

**构建流程**：
```bash
cd PromiseLink/frontend
npm install
npm run build:h5    # 产物输出到 frontend/dist/
```

**部署方式**：
- 构建产物 `frontend/dist/` 由后端 FastAPI StaticFiles 自动挂载
- 启动后端服务后，访问 `http://localhost:8000/` 即加载 H5 前端
- 无需独立 Web 服务器，前后端同源部署

**后端挂载代码**（参考）：
```python
# main.py
from fastapi.staticfiles import StaticFiles
app.mount("/", StaticFiles(directory="frontend/dist", html=True), name="frontend")
```

### 6.3 专业版 UI（手机竖屏）

**设计原则**：单手操作友好，卡片化信息展示，适合碎片化快速记录。

**单栏布局**：
```
┌─────────────────┐
│ 顶部导航栏        │
│ ├─ 返回          │
│ ├─ 标题          │
│ └─ 更多操作       │
├─────────────────┤
│                 │
│ 卡片1            │
│ ├─ 标题          │
│ ├─ 摘要          │
│ └─ 操作按钮       │
│                 │
│ 卡片2            │
│ ├─ 标题          │
│ ├─ 摘要          │
│ └─ 操作按钮       │
│                 │
│ ...             │
├─────────────────┤
│ 底部 Tab 栏      │
│ ├─ 首页          │
│ ├─ 录入          │
│ ├─ 人脉          │
│ └─ 我的          │
└─────────────────┘
```

**响应式适配**：
- 基准宽度 375px（iPhone 12/13/14）
- 大屏手机（≥414px）：卡片间距增大，字号微调
- iPad 微信小程序：自动适配，不专门优化

**技术栈**：
- **框架**: Taro 4.x + React 18
- **构建目标**: 微信小程序（weapp）
- **UI组件**: 自研 Morandi 色系组件（与基础版共享设计语言，不共享代码）
- **状态管理**: Taro Storage + React Context
- **网络**: `Taro.request` 调用网关中继 API

**代码组织**（`PromiseLink-Pro/miniapp/`）：
```
miniapp/
├── src/
│   ├── pages/
│   │   ├── Index/          # 首页（今日安排）
│   │   ├── Record/         # 录入（语音/文字/转发）
│   │   ├── Contacts/       # 人脉
│   │   ├── Todos/          # 待办
│   │   ├── Promises/       # 承诺
│   │   ├── Schedules/      # 预定日程
│   │   ├── Profile/        # 我的（套餐/用量/设置）
│   │   └── Install/        # 一键安装引导
│   ├── components/
│   ├── services/           # 网关 API 调用封装
│   ├── styles/
│   └── app.tsx
├── project.config.json     # 微信开发者工具配置
└── package.json
```

**构建流程**：
```bash
cd PromiseLink-Pro/miniapp
npm install
npm run build:weapp    # 产物输出到 miniapp/dist/weapp/
# 然后用微信开发者工具打开 dist/weapp/ 上传
```

**部署方式**：
- 构建产物通过微信开发者工具上传至微信平台
- 用户在微信内搜索"PromiseLink"或扫码打开
- 小程序请求经网关中继路由到用户本地 Docker
- 不需要应用商店审核，但需微信平台小程序审核

### 6.4 代码组织对比

| 维度 | 基础版 frontend/ | 专业版 miniapp/ |
|------|------------------|-----------------|
| **repo 位置** | `PromiseLink`（公开） | `PromiseLink-Pro`（私有） |
| **框架** | Taro H5 | Taro 微信小程序 |
| **共享代码** | 无（设计语言共享，代码不共享） | 无 |
| **API 调用** | 直接调用本地后端 `http://localhost:8000/api/v1/*` | 调用网关 `wss://gateway.promiselink.com/api/v1/pro/business/*` |
| **认证** | 本地 JWT（首次登录后缓存） | 微信 openid + 网关 JWT |
| **离线可用** | ✅ 完全离线可用 | ❌ 依赖网关中继 |

### 6.5 构建与部署流程

**基础版一键启动**（`scripts/start.sh` 包含前端构建）：
```bash
# 1. 环境检查
# 2. 数据库迁移
# 3. 前端构建
cd frontend && npm install && npm run build:h5 && cd ..
# 4. 后端启动（自动挂载 frontend/dist/）
python -m promiselink.main
```

**专业版一键安装**（`scripts/install_pro.sh`）：
```bash
# 1. 下载小程序（用户扫码）
# 2. 输入邀请码激活
# 3. 下载本地 Docker 安装包
# 4. Docker 自动启动 + 连接网关
# 5. 小程序前端代码由微信平台分发，无需用户构建
```

### 6.6 设计语言一致性

尽管两版 UI 代码独立，但共享统一的设计语言，确保用户跨端体验一致：

| 设计元素 | 规范 | 说明 |
|----------|------|------|
| **主色** | Morandi 色系（低饱和度） | 避免刺眼emoji，舒适视觉 |
| **字号** | 基础版 14-16px / 专业版 13-15px | 适配屏幕差异 |
| **卡片圆角** | 8px | 统一视觉风格 |
| **间距** | 8/16/24px 三级 | 统一节奏感 |
| **图标** | SVG 线性图标 | 不使用 emoji |
| **状态色** | 蓝（待确认）/ 绿（已完成）/ 灰（已忽略） | 统一状态语义 |

### 6.7 跨端跳转与数据一致性

- **用户账号体系**：基础版本地账号与专业版微信 openid 通过网关 `user_id` 绑定，数据共享同一 SQLite 数据库
- **跨端数据同步**：用户在基础版 H5 录入的数据，专业版小程序实时可见（同一本地 Docker 后端）
- **跨端跳转**：基础版 H5 不跳转小程序（PC场景无需）；专业版小程序不跳转 H5（手机场景无需）；两版通过数据一致性实现"跨端无缝"，而非 UI 跳转
