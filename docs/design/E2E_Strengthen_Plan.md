# PromiseLink E2E 测试加强方案

> **版本**: v1.0
> **日期**: 2026-07-01
> **生命周期阶段**: P7 测试计划
> **作者**: DevSquad 测试专家
> **适用范围**: 基础版（PromiseLink MPL）+ 专业版（PromiseLink-Pro 商业许可）
> **硬约束**: 发布前必须做模拟真实用户使用的测试（用户规则 3）

---

## 0. 文档定位

本文档是 PromiseLink 双版本 E2E 测试的加强方案，目标是**充分覆盖模拟用户在基础版和专业版 UI 界面上的所有操作**。文档先行、万事留痕（用户规则 2）。

---

## 1. 现有覆盖分析

### 1.1 基础版（PromiseLink）现有 E2E 脚本

| 脚本 | 大小 | 性质 | 运行方式 | CI 门禁 |
|------|------|------|----------|---------|
| `e2e_basic_test.py` | 9.7KB | 6 阶段 15 步，stdlib-only | 启动服务后 urllib 调用 | ✅ 是（15/0 通过） |
| `e2e_full_ui_test.py` | 32KB | 13 阶段全 UI 操作 | 启动服务后 urllib 调用 | 否 |
| `e2e_user_journey_extended.py` | 62KB | 8 大场景 42 个测试函数 | pytest + httpx + in-memory SQLite + LLM mock | 否 |
| `e2e_smoke_test.py` | 5.2KB | 烟雾测试 | 启动服务后调用 | 否 |
| `e2e_user_journey.py` / `e2e_full_user_journey.py` | 17KB/27KB | 用户旅程 | httpx | 否 |
| `user_journey_test.py` | - | 用户旅程（含 upload/associations） | httpx | 否 |
| `e2e_miniprogram.py` | 6KB | 小程序模拟 | 启动服务后调用 | 否 |

### 1.2 基础版用户操作覆盖矩阵

| 用户操作 | 对应 API | e2e_basic_test | e2e_full_ui_test | e2e_user_journey_extended | 缺口 |
|----------|----------|----------------|-------------------|---------------------------|------|
| 手动文本输入 | `POST /events` | ✅ | ✅ | ✅ | — |
| 事件录入（需求） | `POST /demands` | ❌ | ✅ | ❌ | basic_test 缺 |
| **文件上传 .txt/.md** | `POST /events/upload` | ❌ | ❌ | ❌ | **P0 缺口**（仅 user_journey_test/smoke 覆盖） |
| Todo 完成 | `PATCH /todos/{id}` status=done | ❌（仅 in_progress） | ✅ | ✅ | — |
| Todo 推迟（snoozed） | `PATCH /todos/{id}` status=snoozed | ❌ | ❌（仅 dismissed） | ❌ | **P1 缺口** |
| Todo 忽略（dismissed） | `PATCH /todos/{id}` status=dismissed | ❌ | ✅ | ✅（via confirm rejected） | — |
| Todo 确认（confirm/reject） | `PATCH /todos/{id}/confirm` | ❌ | ❌ | ✅ | — |
| 事件→人脉跳转 | `GET /events` → `GET /entities/{id}` | ❌ | ✅ | ❌ | — |
| 人脉→事件跳转 | `GET /entities/{id}/history` → `GET /events/{id}` | ❌ | ✅ | ❌ | — |
| 待办→事件跳转 | `GET /todos` → `GET /events/{source_event_id}` | ❌ | ✅ | ❌ | — |
| 承诺→人脉跳转 | `GET /promises` → `GET /entities/{id}` | ❌ | ✅ | ❌ | — |
| 承诺状态追踪 | `GET /promises`, `PATCH /promises/{id}/fulfillment` | ✅（list/stats） | ✅ | ✅ | — |
| 数据导出 | `GET /export/{user_id}` | ✅ | ✅ | ✅ | — |
| 仪表盘 | `GET /dashboard/day-view` | ✅ | ✅ | ✅ | — |
| 关系简报 | `GET /relationship-briefs` | ✅ | ❌ | ❌ | — |
| **关联发现** | `GET /associations`, `GET /associations/{id}` | ❌ | ❌ | ✅（仅 list） | **P1 缺口**（detail/筛选未测） |
| 监控指标 | `GET /metrics` | ❌ | ✅ | ❌ | — |
| 错误处理（401/404） | 多个 | ✅（401） | ✅ | ✅ | — |

**基础版核心缺口结论**：
1. **文件上传（.txt/.md）** 在 CI 门禁脚本和最全面脚本中均未覆盖 — 这是用户明确要求的操作
2. **Todo 推迟（snoozed）** 状态流转未单独验证
3. **关联发现（associations）** 的详情查询和筛选未在主脚本覆盖
4. 多个脚本存在重复，但缺少一个**统一、CI 友好、httpx 驱动、不依赖外部服务**的"真实用户操作全集"脚本

### 1.3 专业版（PromiseLink-Pro）现有测试现状

| 模块 | 路径 | 覆盖情况 |
|------|------|----------|
| gateway（LLM 中继网关） | `gateway/tests/e2e/` | ✅ 许可证生命周期、配额红黄绿灯（pytest + TestClient + MockTransport） |
| gateway 集成 | `pro-tests/test_e2e_integration.py` | ⚠️ 需启动 gateway(:8001)，仅测网关层，不测业务 |
| voice | `pro-tests/test_voice_api.py` | 单元/集成测试 |
| voice_query | `pro-tests/test_voice_query_api.py` | 单元/集成测试 |
| media（asr/tts/ocr/ocr-event） | `pro-tests/test_media_api.py` | 单元/集成测试 |
| email_sync | `pro-tests/test_email_adapter.py` | 单元测试（adapter 层） |
| wechat_forward | `pro-tests/test_wechat_forward_api.py` | 单元/集成测试 |
| import_csv | `pro-tests/test_import_csv_api.py` | 单元/集成测试 |
| privacy | （散落在各测试） | 部分覆盖 |
| **scripts/e2e/** | **不存在** | **完全缺失** |

**专业版核心缺口结论**：
1. **完全没有 `scripts/e2e/` 目录** — 无独立 E2E 测试套件
2. 现有 `pro-tests/` 是按模块的单元/集成测试，**缺少跨模块的真实用户旅程 E2E**
3. 专业版独有功能（语音、OCR、邮件同步、微信转发、CSV 导入、隐私 GDPR）**缺少端到端用户操作流测试**
4. 专业版前端（微信小程序）不在 PromiseLink-Pro 仓库内，无法做 UI 自动化；E2E 聚焦 API 层

---

## 2. 测试加强方案

### 2.1 设计原则

1. **httpx 异步客户端**调用 API（不使用浏览器自动化，除非已有 Playwright）
2. **CI 友好**：使用 in-memory SQLite + LLM mock，无需外部服务（GitHub Actions ubuntu-latest 可直接运行）
3. **UUID 格式 user_id**（如 `550e8400-e29b-41d4-a716-446655440000`）
4. **不修改现有通过的 `e2e_basic_test.py`**（CI 门禁脚本）
5. **模拟真实用户使用**（用户硬约束 3）— 按用户真实操作顺序组织测试
6. **三态覆盖**：正常 + 边界 + 错误

### 2.2 基础版新增 E2E 测试用例清单

新建脚本：`/Users/lin/trae_projects/PromiseLink/scripts/e2e/e2e_user_operations_full.py`

采用 `e2e_user_journey_extended.py` 的成熟模式（pytest + httpx.AsyncClient + ASGITransport + in-memory SQLite + LLM mock + 依赖覆盖）。

| 用例 ID | 优先级 | 用例名 | 覆盖操作 |
|---------|--------|--------|----------|
| B-P0-01 | P0 | test_file_upload_txt_creates_event | 上传 .txt 文件 → 创建事件 → 验证 source=file_upload |
| B-P0-02 | P0 | test_file_upload_md_strips_markdown | 上传 .md 文件 → 验证 markdown 被剥离 |
| B-P0-03 | P0 | test_file_upload_invalid_extension_rejected | 上传 .pdf → 422 ValidationError |
| B-P0-04 | P0 | test_file_upload_oversized_rejected | 上传 >1MB 文件 → 422 |
| B-P0-05 | P0 | test_file_upload_empty_rejected | 上传空文件 → 422 |
| B-P0-06 | P0 | test_todo_complete_flow | 创建 todo → 完成（done）→ 验证状态 |
| B-P0-07 | P0 | test_todo_defer_snoozed | 创建 todo → 推迟（snoozed）→ 验证状态 |
| B-P0-08 | P0 | test_todo_ignore_dismissed | 创建 todo → 忽略（dismissed）→ 验证状态 |
| B-P0-09 | P0 | test_todo_confirm_confirmed | 创建 pending todo → confirm confirmed → 验证 |
| B-P0-10 | P0 | test_todo_confirm_rejected_dismissed | 创建 pending todo → confirm rejected → 验证 dismissed |
| B-P0-11 | P0 | test_event_to_entity_navigation | 事件 → 关联人脉详情跳转 |
| B-P0-12 | P0 | test_entity_to_event_navigation | 人脉 → 关联事件跳转（via history） |
| B-P0-13 | P0 | test_todo_to_event_navigation | 待办 → 关联事件跳转（via source_event_id） |
| B-P0-14 | P0 | test_promise_to_entity_navigation | 承诺 → 关联人脉跳转 |
| B-P0-15 | P0 | test_association_list_and_filter | 关联发现列表 + 类型筛选 |
| B-P0-16 | P0 | test_association_detail_and_404 | 关联详情 + 不存在 404 |
| B-P0-17 | P0 | test_dashboard_day_view_with_data | 仪表盘日视图（有数据） |
| B-P0-18 | P0 | test_relationship_briefs_view | 关系简报查看 |
| B-P0-19 | P0 | test_data_export_structure | 数据导出结构完整性 |
| B-P1-01 | P1 | test_file_upload_with_event_type_param | 上传时指定 event_type 参数 |
| B-P1-02 | P1 | test_todo_invalid_status_transition | 非法状态转换拒绝 |
| B-P1-03 | P1 | test_association_isolation_between_users | 关联数据用户隔离 |
| B-P2-01 | P2 | test_file_upload_gbk_encoding | GBK 编码文件解码 |
| B-P2-02 | P2 | test_todo_confirm_invalid_status | confirm 非法 confirmation_status |

### 2.3 专业版新建 E2E 测试框架与用例清单

新建目录：`/Users/lin/trae_projects/PromiseLink-Pro/scripts/e2e/`
新建脚本：`/Users/lin/trae_projects/PromiseLink-Pro/scripts/e2e/e2e_pro_user_operations.py`

采用与基础版相同的模式（pytest + httpx + in-memory SQLite + LLM mock），并通过 `pro-tests/conftest.py` 的 `_register_pro_routers()` 机制挂载 pro_api 路由。

| 用例 ID | 优先级 | 用例名 | 覆盖操作 |
|---------|--------|--------|----------|
| P-P0-01 | P0 | test_voice_session_create_and_list | 语音会话创建 + 列表 |
| P-P0-02 | P0 | test_voice_query_schedule | 语音查询（日程） |
| P-P0-03 | P0 | test_voice_query_promise | 语音查询（承诺） |
| P-P0-04 | P0 | test_voice_query_relationship | 语音查询（关系） |
| P-P0-05 | P0 | test_wechat_forward_creates_event | 微信转发 → 创建事件 |
| P-P0-06 | P0 | test_csv_import_creates_entities | CSV 导入 → 创建人脉 |
| P-P0-07 | P0 | test_csv_import_invalid_header_rejected | CSV 无效表头拒绝 |
| P-P0-08 | P0 | test_privacy_data_summary | 隐私数据摘要 |
| P-P0-09 | P0 | test_privacy_export | 隐私导出 |
| P-P0-10 | P0 | test_privacy_delete_user_data | GDPR 删除全部用户数据 |
| P-P0-11 | P0 | test_media_tts_fallback | TTS 合成（fallback 路径） |
| P-P0-12 | P0 | test_media_asr_invalid_mime_rejected | ASR 非法 MIME 拒绝 |
| P-P0-13 | P0 | test_media_ocr_invalid_mime_rejected | OCR 非法 MIME 拒绝 |
| P-P0-14 | P0 | test_voice_session_delete_gdpr | 语音数据 GDPR 删除 |
| P-P1-01 | P1 | test_email_sync_invalid_host_rejected | 邮件同步非法 host（SSRF 防护） |
| P-P1-02 | P1 | test_voice_sessions_pagination | 语音会话分页 |
| P-P1-03 | P1 | test_csv_import_merge_existing | CSV 导入合并已有人脉 |
| P-P1-04 | P1 | test_privacy_delete_cascades_voice | GDPR 删除级联清理语音数据 |
| P-P2-01 | P2 | test_voice_chitchat_intent | 闲聊意图处理 |
| P-P2-02 | P2 | test_wechat_forward_empty_text_rejected | 微信转发空文本拒绝 |

### 2.4 优先级定义

- **P0（核心用户流程）**：用户每次使用都会触发的操作，必须 100% 覆盖。包括：文件上传、待办三态操作、跨页面跳转、关联发现、语音查询、微信转发、CSV 导入、隐私 GDPR。
- **P1（边界场景）**：参数组合、筛选、分页、数据隔离等非主路径但重要的场景。
- **P2（异常处理）**：非法输入、编码边缘、空值等错误路径。

---

## 3. 实施计划

### 3.1 已实施（本次）

1. ✅ 基础版新增 `e2e_user_operations_full.py`（P0 全部 19 用例，全部通过）
2. ✅ 专业版新建 `scripts/e2e/` 目录 + `conftest.py` + `e2e_pro_user_operations.py`（P0 全部 14 用例 + 1 个 P2 附带用例，共 15 个测试全部通过）
3. ✅ 本方案文档
4. ✅ 验证未修改 CI 门禁脚本 `e2e_basic_test.py`（git diff 为空）

**最终测试结果**：
- 基础版：`19 passed in 1.45s`
- 专业版：`15 passed in 1.53s`
- 合计 34 个新 E2E 测试全部通过，无需外部服务（in-memory SQLite + LLM/云服务 mock）

### 3.2 遗留项（后续迭代）

1. ⏳ 基础版 P1/P2 用例（边界场景、异常处理）
2. ⏳ 专业版 P1/P2 用例
3. ⏳ 将新脚本接入 GitHub Actions CI workflow（在 e2e_basic_test 之后运行）
4. ⏳ 专业版前端（微信小程序）UI 自动化测试（需小程序前端代码就位后补充）
5. ⏳ 性能压测（locust）— 超出本次 E2E 范围

### 3.3 运行方式

**基础版**：
```bash
cd /Users/lin/trae_projects/PromiseLink
python3 -m pytest scripts/e2e/e2e_user_operations_full.py -v --tb=short
```

**专业版**：
```bash
cd /Users/lin/trae_projects/PromiseLink-Pro
python3 -m pytest scripts/e2e/e2e_pro_user_operations.py -v --tb=short
```

两个脚本均使用 in-memory SQLite + LLM mock，**无需启动外部服务、无需真实 LLM API Key**，可直接在 GitHub Actions ubuntu-latest + PostgreSQL 环境运行。

---

## 4. 校验方法

按用户规则 2"考虑推进步骤与对应的校验方法"：

1. **语法校验**：`python3 -m py_compile <script>` 确保无语法错误
2. **导入校验**：`python3 -c "import ast; ast.parse(open(<script>).read())"` 确保 AST 可解析
3. **运行校验**：实际执行 pytest，确认全部 P0 用例通过
4. **覆盖校验**：对照第 2.2/2.3 节用例清单，逐项确认实现
5. **CI 兼容校验**：确认不依赖外部服务（无真实 LLM、无真实 IMAP、无真实微信）

---

## 5. 风险与缓解

| 风险 | 缓解措施 |
|------|----------|
| 专业版 pro_api 依赖 pro_models/pro_services 导入失败 | conftest 已有 try/except 跳过机制；测试用 skipif 容错 |
| LLM mock 不完整导致 NLU 分类失败 | voice_query 测试 mock NLUIntentClassifier.classify |
| 邮件同步需真实 IMAP | 仅测 SSRF host 白名单（P1），不连真实邮箱 |
| ASR/TTS/OCR 需真实云服务 | 仅测 MIME 校验和 fallback 路径，mock 云服务 |
