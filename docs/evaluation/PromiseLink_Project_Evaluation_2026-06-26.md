# PromiseLink 项目整理评估报告

> 评估日期：2026-06-26  
> 评估范围：PromiseLink（基础版）、PromiseLink-Pro（专业版）、PromiseLink-miniapp（微信小程序）  
> 评估维度：架构 / 安全 / 测试 / 性能 / 可维护性 / 文档 / 集成  
> 评估原则：基于实际命令输出与代码证据，严格、准确、诚实，反对虚报。

---

## 1. 执行摘要

本次评估覆盖 PromiseLink 三仓库。结论：**基础版接近可用状态，专业版与小程序存在结构性集成与交付缺陷，尚未达到生产就绪标准。**

| 仓库 | 成熟度评分 | 关键状态 |
|---|---|---|
| PromiseLink（基础版） | 3.4 / 5 | 测试与 mypy 本地通过；CI 存在非阻塞步骤；前端 token 存储方式有安全隐患；文档部分陈旧。 |
| PromiseLink-Pro（专业版） | 2.4 / 5 | 网关未挂载 pro 路由；`pyproject.toml` 未打包 pro 模块；pro-api 依赖已拆分的基础版服务，生产环境会导入失败；CI 多项检查非阻塞。 |
| PromiseLink-miniapp（小程序） | 2.1 / 5 | TypeScript 源码类型错误多；E2E 未真正跑通；JWT/relay token 明文存 storage；构建成功但包体积过大。 |

**整体成熟度：2.7 / 5（可用但不稳定，专业版功能链断裂）。**

---

## 2. 各仓库评估详情

### 2.1 PromiseLink（基础版）

**实际验证命令**

```bash
cd /Users/lin/trae_projects/PromiseLink
python -m pytest tests/ -x --timeout=60
# 结果：1353 passed, 25 skipped

python -m mypy src/promiselink --ignore-missing-imports
# 结果：Success: no issues found in 111 source files

ruff check src/ tests/
# 结果：通过（仅 1 个 # noqa 格式警告）

npm run build:h5 --prefix frontend
# 结果：构建成功，8 个 Sass 弃用/资源大小警告
```

| 维度 | 评分 | 关键发现与证据 |
|---|---|---|
| 架构 | 4/5 | 目录分层清晰（`models/api/services/core`），最大模块 338 行，无显著 God Class。 |
| 安全 | 3/5 | 源码无已提交 secret；`.env*` 被 `.gitignore` 排除，但工作区存在真实 key；前端 `frontend/src/services/auth.ts` 将 JWT 与 user_id 存 `localStorage`，存在 XSS 泄露风险。 |
| 测试 | 4/5 | 1353 passed / 25 skipped / 0 failed，覆盖率 72%；但 `tests/test_phase1_integration.py` 中 embedding 测试依赖 `sentence-transformers`，缺失时会失败或访问真实网络。 |
| 性能 | 3/5 | 关联发现 `association_discovery.py` 为 O(N×M) 嵌套循环（上限 100），大数据量需关注；无显著 N+1。 |
| 可维护性 | 3/5 | 仅 1 处 TODO（`event_search_api.py:64`）、1 处 `NotImplementedError`（`core/wechat.py:75`）；`archive/`、`debug_batch.py`、`.promiselink.pid` 等过程文件未清理。 |
| 文档 | 3/5 | `VERSION`、`pyproject.toml`、`src/promiselink/__init__.py`、前端 `package.json` 版本一致为 `0.6.6`；但 `docs/PROJECT_STATUS.md`、`README.md`、`CHANGELOG.md` 仍引用已删除文件（`media.py`、`voice.py`、`asr_service.py` 等），测试数描述与实测不符。 |
| 集成 | 3/5 | `main.py` 注册 14 组路由，CI 覆盖 lint/mypy/pip-audit/test/coverage/e2e/Docker；但 e2e、frontend、bandit 步骤均使用 `|| true` 或 `continue-on-error: true`，不阻塞流水线。 |

**P0**：无  
**P1**：前端 JWT 存 localStorage；CI e2e/frontend/security 非阻塞；文档陈旧引用已删除模块  
**P2**：`core/wechat.py` 未实现；`archive/` 过程文件未清理  
**P3**：`.promiselink.pid` 等临时文件

---

### 2.2 PromiseLink-Pro（专业版）

**实际验证命令**

```bash
cd /Users/lin/trae_projects/PromiseLink-Pro
python -m pytest pro-tests/ -x --timeout=60
# 结果：264 passed, 1 skipped

python -m pytest gateway/tests/ -x --timeout=60
# 结果：317 passed

python -m mypy gateway --ignore-missing-imports
# 结果：16 errors in 5 files

ruff check gateway/ pro-api/ pro-services/
# 结果：通过
```

| 维度 | 评分 | 关键发现与证据 |
|---|---|---|
| 架构 | 3/5 | `gateway/pro-services/pro-api/pro-tests` 分层清晰；但 `gateway/services/api_key_pool.py` 与 `api_key_pool_manager.py` 重复实现；未看到三贤者/ConsensusEngine 实际使用。 |
| 安全 | 3/5 | 无已提交明文 secret；生产启动 `validate_production_settings` 会拒绝默认 secret；API Key 校验使用 `hmac.compare_digest`；邮件密码从 config 明文读取；媒体上传未前置校验 MIME/大小。 |
| 测试 | 3/5 | pro-tests 264 passed / 1 skipped；gateway/tests 317 passed。但 CI 中 pro-tests 因基础版仓库私有而 `continue-on-error: true`，非阻塞；mypy 16 处真实类型错误未阻塞。 |
| 性能 | 3/5 | LLM relay 有 30s 超时/重试、API Key 池有熔断/限流/健康分、用户级 100 req/min 限流；无 LLM 响应缓存，上传文件整体读入内存。 |
| 可维护性 | 2/5 | mypy 16 errors 暴露 `LicenseService` 接口不匹配等真问题；无 TODO/FIXME；pro-api/pro-services 缺少 `__init__.py`。 |
| 文档 | 3/5 | README、VERSION、`pyproject.toml` 版本一致为 `0.6.6`；但 `LICENSE` 版权方为 “PromiseLink Team” 而 README 写 “CarryMem Team”；README 要求 `pip install promiselink==0.6.6`，但 `pyproject.toml` 未声明该依赖。 |
| 集成 | 1/5 | **P0 级断裂**：`gateway/main.py` 仅注册 gateway 路由，未挂载 `pro-api`（voice/email/media/privacy/import_csv/wechat_forward）；`pyproject.toml` 中 `packages = ["gateway"]`，pro-api/pro-services 不会被 pip 打包；pro-api 大量 `from promiselink.services.xxx` 引用已拆分到 pro-services 的模块，生产 pip 安装基础版后将导入失败。 |

**P0**：pro 路由未在生产应用/Docker 挂载；`pyproject.toml` 未打包 pro 模块；pro-api 依赖基础版中已不存在的服务  
**P1**：两套 API Key Pool 重复实现；mypy 16 处真实类型错误；邮件密码明文配置；媒体上传缺少 MIME/大小校验；LICENSE 与 README 版权方不一致  
**P2**：无 LLM 响应缓存；CI 中 mypy/pro-tests/E2E/bandit 非阻塞  
**P3**：`.DS_Store`、缓存/覆盖率目录未清理

---

### 2.3 PromiseLink-miniapp（小程序）

**实际验证命令**

```bash
cd /Users/lin/trae_projects/PromiseLink-miniapp
CI=true npm test
# 结果：14 passed

npm run build:h5
# 结果：构建成功，多个 chunk 超过 244 KiB 警告

npx tsc --noEmit
# 结果：项目源码存在约 40+ 类型错误（mockContacts.ts tag 属性、VoiceAssistant 组件类型等）
```

| 维度 | 评分 | 关键发现与证据 |
|---|---|---|
| 架构 | 3/5 | Taro 目录规范，但 4 个组件零引用、relationship 页引入 2 个组件未渲染，存在幽灵组件。 |
| 安全 | 2/5 | `src/utils/auth.ts` 将 JWT 存 `Taro.setStorageSync`（等价 localStorage）；`src/utils/proAuth.ts` 将 license key、relay token、refresh token、device fingerprint 全部明文存 storage；API Key 通过环境变量读取，未硬编码。 |
| 测试 | 2/5 | Jest 14 passed；Playwright E2E 配置指向 `http://localhost:10086`，但测试用例可能因首页路由/状态而失败；CI 中 E2E 未真正跑通。 |
| 性能 | 2/5 | `build:h5` 产物约 4.5 MiB，12 个 JS chunk 超过 244 KiB；未启用懒加载/代码分割优化。 |
| 可维护性 | 2/5 | TypeScript 源码约 40+ 错误；代码中较多 `console.log`/`console.error`；有 ESLint/Stylelint 依赖但配置执行度不明。 |
| 文档 | 2/5 | 版本号一致为 `0.6.6`；无根 README；`README_DEV.md` 等内部文档可能过时。 |
| 集成 | 2/5 | API 集中在 `src/services/api.ts`，Pro 认证集中在 `src/utils/proAuth.ts`；与后端契约部分类型不匹配（`Todo` 缺少 `priority`/`due_date` 字段声明）。 |

**P0**：TypeScript 源码错误阻断严格 CI；敏感 token 明文存 storage  
**P1**：缺少有效的 lint/prettier 门禁；E2E 未跑通；包体积过大；存在幽灵组件  
**P2**：大量 `console` 日志；mock 数据类型与接口不匹配  
**P3**：README_DEV 等文档过时

---

## 3. 文档 / 版本一致性检查结果

| 检查项 | 基础版 | Pro | miniapp | 备注 |
|---|---|---|---|---|
| VERSION 文件 | 0.6.6 | 0.6.6 | 0.6.6 | 一致 |
| pyproject.toml / package.json | 0.6.6 | 0.6.6 | 0.6.6 | 一致 |
| README 版本声明 | 0.6.6 | 0.6.6 | 无根 README | 一致 |
| 文档引用已删除文件 | 有 | 有 | 无 | 需清理 |
| LICENSE / 版权方一致性 | - | 不一致 | - | PromiseLink Team vs CarryMem Team |
| pip install 版本 | 0.6.6 | 0.6.6 | - | README 正确，但 Pro pyproject 未声明依赖 |

---

## 4. CI/CD 检查

| 仓库 | lint | type check | security | unit test | E2E | build | 阻塞性 |
|---|---|---|---|---|---|---|---|
| PromiseLink | ruff 阻塞 | mypy 阻塞 | pip-audit 阻塞；bandit `|| true` | 阻塞 | `|| true` | frontend `|| true` | 部分非阻塞 |
| PromiseLink-Pro | ruff 阻塞 | mypy `|| true` + continue-on-error | pip-audit 阻塞；bandit `|| true` | gateway 阻塞；pro-tests continue-on-error | continue-on-error | Docker 阻塞 | 多项非阻塞 |
| PromiseLink-miniapp | 未配置有效门禁 | tsc 未在 CI 运行 | 无 | Jest 未在 CI 运行 | 未跑通 | build 通过 | 几乎无有效门禁 |

---

## 5. 幽灵功能 / 技术债

1. **PromiseLink-Pro pro-api/pro-services 未接入生产路径**：代码存在、测试存在，但 gateway 不挂载、Docker 不启动、pip 不打包，形成“有测试但零生产引用”的幽灵功能。
2. **PromiseLink-miniapp 零引用组件**：4 个组件被引入但页面未实际渲染。
3. **PromiseLink 基础版 `core/wechat.py:75` 抛 `NotImplementedError`**：占位未实现。
4. **PromiseLink 基础版 `archive/` 目录**：保留旧方案/草稿等过程文件。

---

## 6. 目录结构与临时文件

- **PromiseLink**：`archive/`、`debug_batch.py`、`.promiselink.pid`、`.DS_Store` 等过程/临时文件存在；`.gitignore` 已更新 `.promiselink.pid`。
- **PromiseLink-Pro**：`.DS_Store`、`.benchmarks`、`.pytest_cache`、`.mypy_cache`、`.ruff_cache` 等缓存目录存在；`.archives` 包含历史归档。
- **PromiseLink-miniapp**：`node_modules` 被忽略；`.taro` 缓存目录存在。

---

## 7. 成熟度评分汇总

| 仓库 | 架构 | 安全 | 测试 | 性能 | 可维护性 | 文档 | 集成 | 平均 |
|---|---|---|---|---|---|---|---|---|
| PromiseLink | 4 | 3 | 4 | 3 | 3 | 3 | 3 | **3.4** |
| PromiseLink-Pro | 3 | 3 | 3 | 3 | 2 | 3 | 1 | **2.4** |
| PromiseLink-miniapp | 3 | 2 | 2 | 2 | 2 | 2 | 2 | **2.1** |
| **整体** | 3.3 | 2.7 | 3.0 | 2.7 | 2.3 | 2.7 | 2.0 | **2.7** |

---

## 8. 下一步优先级建议

### 立即执行（P0，阻塞发布）

1. **修复 PromiseLink-Pro 集成断裂**
   - 在 `gateway/main.py` 中注册所有 `pro-api` 路由（voice/voice_query/media/email_sync/wechat_forward/import_csv/privacy）。
   - 修改 `pyproject.toml` 的 `packages` 包含 `pro-api`、`pro-services`、`pro-models`。
   - 解决 pro-api `from promiselink.services.xxx` 与 pro-services 拆分后的导入问题（统一从 `pro_services` 引入或创建兼容桥接）。
2. **PromiseLink-miniapp 敏感信息存储整改**
   - 将 JWT、relay token、refresh token、license key 移出 storage；必要时改用 httpOnly cookie 或小程序加密存储。
3. **PromiseLink-miniapp TypeScript 错误清零**
   - 修复源码类型错误，将 `npx tsc --noEmit` 加入 CI 并设为阻塞。

### 短期（P1，1-2 周内）

4. **统一 CI 门禁**
   - PromiseLink 基础版：移除 e2e/frontend/bandit 的 `|| true`。
   - PromiseLink-Pro：移除 mypy/pro-tests/E2E/bandit 的非阻塞标记；发布基础版到 PyPI 或设为 public 以解除依赖阻塞。
5. **修复 LICENSE / README 版权方不一致**；清理 `docs/PROJECT_STATUS.md`、README、CHANGELOG 中对已删除文件的引用。
6. **合并/删除 PromiseLink-Pro 重复的 API Key Pool 实现**，修复 mypy 16 处真实类型错误。
7. **PromiseLink 基础版前端 JWT 存储整改**：评估改为 httpOnly cookie 或短期 token + refresh 机制。

### 中期（P2-P3，2-4 周内）

8. **PromiseLink-Pro**：增加媒体上传 MIME 白名单/大小校验；评估邮件凭据加密；引入 LLM 响应缓存。
9. **PromiseLink-miniapp**：启用代码分割/懒加载降低包体积；清理幽灵组件与 `console` 日志；重写/补全 E2E。
10. **三仓库统一清理**：删除 `archive/`、`debug_batch.py`、`.DS_Store`、过时的 draft 文档；为 miniapp 补充根 README。

---

## 9. 结论

PromiseLink 基础版在代码质量与测试覆盖上已具备一定成熟度，但 CI 与文档细节仍需收紧。专业版是当前最大短板：**功能代码存在且测试通过，但无法通过生产镜像或 pip 包被用户实际调用**，属于典型的“幽灵功能”与交付链断裂。小程序则需要先解决类型安全、敏感信息存储与 E2E 验证，才能进入可发布状态。

**发布建议**：在解决 Pro 版路由挂载、打包声明、导入路径问题，以及 miniapp 敏感信息存储与 TypeScript 错误之前，不建议对外发布专业版与小程序。
