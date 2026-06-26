# PromiseLink 发布阻塞问题修复计划

> 建立日期：2026-06-26  
> 评估依据：[PromiseLink_Project_Evaluation_2026-06-26.md](./PromiseLink_Project_Evaluation_2026-06-26.md)  
> 执行原则：文档先行 → 代码严谨 → 测试充分 → 直接推送 Git（不经 PR）  
> 责任团队：DevSquad 多角色协作（architect / security / tester / solo-coder / devops）

---

## 1. 共识决策（项目组已确认）

| 决策项 | 共识结论 | 理由 |
|---|---|---|
| Pro 路由挂载方式 | 在 `gateway/main.py` 中通过 `include_router` 挂载所有 pro-api 路由 | 单一入口简化部署，Dockerfile 不需改动 |
| pro-api 导入路径 | 创建 `pro_services` 与 `pro_api` 包的 `__init__.py`；pro-api 内部统一从 `pro_services` 引入 | 物理隔离基础版与专业版代码，符合 Repo_Split_Decision |
| pyproject.toml 打包 | `packages = ["gateway", "pro-api", "pro-services", "pro-models"]` | 确保 pip install 后专业版模块可用 |
| miniapp 敏感信息 | JWT 短期内存 + refresh；relay token 用 Taro 加密存储（`setStorageSync` 的 salted hash） | 小程序环境无 httpOnly cookie，需在客户端层加密 |
| miniapp TypeScript | 修复所有源码类型错误；将 `tsc --noEmit` 加入 CI 阻塞 | 类型安全是发布前最低要求 |
| 基础版 JWT 存储 | 改用短期 access token (15min) + refresh token (httpOnly cookie) | 降低 XSS 泄露影响 |
| CI 非阻塞步骤 | 全部移除 `|| true` 与 `continue-on-error` | 门禁必须真实阻塞才能防回归 |
| 文档陈旧引用 | 全量清理 PROJECT_STATUS/README/CHANGELOG 中对已删除模块的引用 | 文档与代码一致性是外部第一印象 |
| Git 推送策略 | 直接 push 到 main（用户授权） | 用户明确要求不用 PR |

---

## 2. P0 问题（阻塞发布）

### P0-1: PromiseLink-Pro 集成断裂

**现象**：
- `gateway/main.py` 仅注册 gateway 路由（health/license/usage/relay/admin），未挂载任何 pro-api 路由。
- `pyproject.toml` 中 `packages = ["gateway"]`，pro-api/pro-services/pro-models 不会被 pip 打包。
- pro-api 大量 `from promiselink.services.xxx`（如 `asr_service`/`tts_service`/`ocr_service`/`email_adapter`/`wechat_forward_adapter`）引用已拆分到 pro-services 的模块，生产环境 pip 安装基础版后会 ImportError。

**修复方案**：
1. 在 `pro-api/`、`pro-services/`、`pro-models/` 添加 `__init__.py`。
2. 修改 pro-api 中所有 `from promiselink.services.xxx` 为 `from pro_services.xxx`（对应 asr/tts/ocr/email_adapter/wechat_forward_adapter/nlu_intent_classifier/nlg_service/voice_query_service）。
3. 在 `gateway/main.py` 中添加 pro-api 路由注册（条件性：仅当 pro-api 可导入时挂载，避免基础版环境崩溃）。
4. 修改 `pyproject.toml` 的 `packages` 列表。

**验收标准**：
- `python -c "import pro_api; import pro_services"` 成功。
- `python -c "from gateway.main import app; assert any('voice' in str(r.path) for r in app.routes)"` 通过。
- `pip install -e .` 后 `python -m pytest pro-tests/ -x` 全绿。
- Docker 构建镜像后 `curl http://localhost:8001/api/v1/pro/health` 返回 healthy。

**责任角色**：architect + solo-coder + tester

---

### P0-2: PromiseLink-miniapp 敏感信息存储整改

**现象**：
- `src/utils/auth.ts` 将 JWT 存 `Taro.setStorageSync(TOKEN_KEY, token)`（等价 localStorage）。
- `src/utils/proAuth.ts` 将 license key、relay token、refresh token、device fingerprint 全部明文存 storage。

**修复方案**：
1. JWT 改为内存变量（模块级 `let accessToken: string | null = null`），仅在刷新时写入；启动时通过 refresh token 自动换取。
2. refresh token 使用 Taro 加密存储：`Taro.setStorageSync` + 应用级 salt + base64（小程序无 crypto API 时的降级方案；如 `wx.getStorageInfoSync` 可获取加密能力则用之）。
3. relay token 同上处理。
4. license key 不再持久化（每次启动由用户输入或刷新机制获取）。
5. device fingerprint 维持明文（非敏感信息，仅用于设备识别）。

**验收标准**：
- `grep -r "setStorageSync" src/utils/auth.ts src/utils/proAuth.ts` 不再出现明文 token 存储。
- 启动后无 token 时能通过 refresh 自动登录。
- Jest 单测覆盖 token 刷新与清除逻辑。

**责任角色**：security + solo-coder + tester

---

### P0-3: PromiseLink-miniapp TypeScript 错误清零

**现象**：
- `npx tsc --noEmit` 在项目源码层存在约 40+ 类型错误。
- 主要集中在：
  - `src/data/mockContacts.ts`：`tag` 属性不存在于 `{ category: string; detail: string; }` 类型。
  - `src/components/VoiceAssistant/index.tsx`：`Todo` 类型缺少 `priority`/`due_date`；`result` 为 unknown；`use_client_tts` 属性不存在。
  - `src/app.tsx`：未使用的 React import。

**修复方案**：
1. 扩展 `Todo` 类型定义，添加 `priority?: number` 与 `due_date?: string`。
2. 修正 `mockContacts.ts` 的 contact 类型，将 `tag` 改为 `category`/`detail` 或扩展类型。
3. 为 VoiceAssistant 中的 `result` 添加类型断言或显式类型。
4. 删除未使用的 import。
5. 在 `package.json` 添加 `"typecheck": "tsc --noEmit"` 脚本。

**验收标准**：
- `npx tsc --noEmit` 退出码 0（忽略 node_modules 内部错误）。
- 新增 `npm run typecheck` 脚本可在 CI 中调用。

**责任角色**：solo-coder + tester

---

## 3. P1 问题（1-2 周内）

### P1-1: PromiseLink 基础版文档清理

**修复**：
- `docs/PROJECT_STATUS.md`：删除对 `media.py`、`voice.py`、`asr_service.py` 等已删除模块的引用。
- `README.md`、`CHANGELOG.md`：更新测试数（1353 passed / 25 skipped）、mypy 状态（0 errors）。
- 删除 `archive/` 目录或移至 `docs/archive/` 归档。

### P1-2: PromiseLink 基础版 CI 门禁收紧

**修复**：
- `.github/workflows/ci.yml`：移除 e2e 步骤的 `|| true`；移除 frontend 的 `|| true`；bandit 改为阻塞。
- `frontend` job 中 `npx tsc --noEmit` 与 `npm run build:h5` 改为阻塞。

### P1-3: PromiseLink 基础版前端 JWT 存储

**修复**：
- `frontend/src/services/auth.ts`：移除 localStorage 中的 token 持久化；改用内存 + refresh token cookie。
- 后端 `/auth/login` 返回 refresh token via Set-Cookie httpOnly。

### P1-4: PromiseLink-Pro API Key Pool 合并

**修复**：
- 删除 `gateway/services/api_key_pool.py` 或 `api_key_pool_manager.py` 二选一。
- 保留接口更完整、被 main.py 引用的那个。

### P1-5: PromiseLink-Pro mypy 16 错误修复 + InMemoryLicenseService 接口对齐

**修复**：
- `jwt_handler.py:258-259`：修复 None 赋值。
- `api/v1/usage.py:26,48`：修复 Any 返回与 UnifiedResponse 类型。
- `api/v1/relay.py:44,247,418`：修复 AsyncIterator 类型断言。
- `api/v1/license.py:39,131,132,154,176`：修复 LicenseService 接口与 ActivationResult 索引。
- `main.py:86,208,230,294`：修复方法赋值与 Optional 类型。
- **【补充修复】** `gateway/tests/_helpers.py` `InMemoryLicenseService` 接口对齐：
  - `activate_license` 返回类型由 `dict[str, Any]` 改为 `ActivationResult` dataclass（与生产 `LicenseService` 一致）。
  - `verify_license(token_payload, device_fingerprint)` 重命名为 `verify_relay_token(token, *, expected_device_fingerprint=None)` 返回 `VerificationResult`。
  - `refresh_token(token)` 重命名为 `refresh_relay_token(token)` 返回 `tuple[str, str]`。
  - 同步 `api/v1/license.py` verify 端点：从 Authorization 头取原始 token，调用 `service.verify_relay_token(token, expected_device_fingerprint=body.device_fingerprint)`，由 `VerificationResult` 构建响应。
  - 理由：消除"开发用 dict、生产用 dataclass"的双轨接口，遵循"测试优先使用真实组件"原则，避免幽灵 API 调用。

### P1-6: PromiseLink-Pro LICENSE 版权方统一

**修复**：
- `LICENSE` 中 "PromiseLink Team" 改为 "CarryMem Team"（与 README 一致），或反之统一为 "PromiseLink Team"。

### P1-7: PromiseLink-Pro 邮件密码与媒体上传校验

**修复**：
- `pro-services/email_adapter.py`：邮件密码从环境变量读取，不写入 config。
- `pro-api/media.py`：上传时校验 MIME 白名单（image/jpeg, image/png, audio/wav 等）与大小上限（10MB）。

---

## 4. P2-P3 问题（2-4 周内）

### P2-1: 基础版 core/wechat.py 未实现 ⚠️ 【经审查撤销】

**原计划**：删除 `core/wechat.py`（基础版不包含微信功能，已迁至 pro-services）。

**审查结论（2026-06-26）**：撤销删除。基础版 `src/promiselink/core/wechat.py` 提供 `WeChatOAuthService.code_to_session()`，被 `api/v1/auth.py:73` 的 `/auth/wechat/login` 端点调用，用于微信小程序 OAuth 登录（小程序前端 `wx.login()` → 后端换 openid → 签发 JWT）。这是与专业版 `pro_services/wechat_forward_adapter.py`（微信消息转发适配器）完全不同的功能。基础版需保留 OAuth 登录以支持小程序用户认证。

**P2-1 状态**：撤销，不删除。

### P2-2: PromiseLink-Pro LLM 响应缓存 ⚠️ 【经审查推迟】

**原计划**：在 `relay_service.py` 中添加 LRU + TTL 缓存（基于 prompt hash）。

**审查结论（2026-06-26）**：推迟至发布后。理由：(1) LLM 响应常含 temperature > 0 的非确定性，缓存相同 prompt 的响应可能不符合用户预期；(2) 缓存失效策略复杂（模型升级、用户上下文变化）；(3) 非发布阻断项，符合"避免过度设计"原则。发布后基于真实流量数据决策。

**P2-2 状态**：推迟。

### P3-1: 临时文件清理 ✅ 完成

**修复**：
- 基础版：删除 `.promiselink.pid`（`debug_batch.py` 已在 .gitignore 中，archive/ 已在 P1-1 删除）。
- Pro：清理 3 个 `.DS_Store` 文件（根目录 + docs/archive + docs/external）。
- miniapp：`.taro` 已在 .gitignore 中，无需清理。
- 验证：三个仓库的 .gitignore 均已覆盖 `.DS_Store`、`*.tmp`、`*.bak`、`.promiselink.pid`，新文件不会被跟踪。

### P3-2: miniapp 幽灵组件清理 ✅ 完成

**修复**：经全量 grep 审计，发现 **7 个**零引用组件（原计划 4 个，实际更多）：
- `CapabilityTags` (57 行)
- `CooperationSignals` (100 行)
- `NetworkGraph` (78 行)
- `PromiseTracker` (77 行)
- `RelationshipScore` (40 行) — 含关联测试 `RelationshipScore.test.tsx` 一并删除
- `RiskAlert` (79 行)
- `StageFlow` (57 行)

合计 **488 行死代码** 已删除。保留的 6 个组件（ContactCard/EventCard/Guide/QuickAction/TodoCard/VoiceAssistant）均有真实页面引用。

**验证**：`npm test` 8/8 通过；`npx tsc --noEmit` 源码 0 错误（仅 node_modules 框架类型警告）。

---

## 5. 执行顺序

```
P0-1 (Pro 集成) ──┐
P0-2 (miniapp 存储) ──┼── 并行 ──┐
P0-3 (miniapp tsc) ──┘           │
                                  ├── 回归测试 ── Git Push
P1-1 ~ P1-7 (顺序) ──────────────┤
P2-P3 (清理) ────────────────────┘
```

---

## 6. 验收门禁

| 门禁 | 标准 | 验证命令 |
|---|---|---|
| 基础版测试 | 0 failure | `cd PromiseLink && pytest tests/ -x` |
| Pro 测试 | 0 failure | `cd PromiseLink-Pro && pytest pro-tests/ gateway/tests/ -x` |
| miniapp 单测 | 0 failure | `cd PromiseLink-miniapp && CI=true npm test` |
| miniapp tsc | 0 error | `cd PromiseLink-miniapp && npx tsc --noEmit` |
| miniapp 构建 | 成功 | `cd PromiseLink-miniapp && npm run build:h5` |
| 基础版 mypy | 0 error | `cd PromiseLink && mypy src/promiselink` |
| Pro mypy | 0 error | `cd PromiseLink-Pro && mypy gateway` |
| Pro 路由挂载 | 通过 | `python -c "from gateway.main import app; ..."` |

---

## 7. 变更记录

| 日期 | 任务 | 状态 | 提交 |
|---|---|---|---|
| 2026-06-26 | 计划文档建立 | 完成 | - |
