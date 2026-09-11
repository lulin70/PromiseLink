# W5 实施阶段阻塞项跟踪（B-1 ~ B-9）

> **版本**: v1.1
> **日期**: 2026-09-10
> **依据**: 四角色第二次独立复审产出的 P1 阻塞项清单（2026-09-09/10 会话）
> **原则**: 每项必须附真实证据（命令 + 输出 + 测试名）；`pending` 项不得在证据缺失时标为 `done`（Anti-ghost）。
> **状态图例**: `done` 完成并有证据 / `partial` 部分完成（列明剩余） / `pending` 未开始 / `n/a` 不适用
> **本轮更新 (v1.1, 2026-09-10)**: B-2 由 `pending` 翻转为 `done`；B-1 / E2E / B-8 / B-9 维持 `pending`；见 §5。
> **本轮更新 (v1.2, 2026-09-11)**: E2E real-user 真实化翻转为 `done`（scripts/e2e/e2e_w5_real_user.py 14/14 PASS，w5_manifest_validator exit=0）；见 §6。B-1 / B-8 / B-9 维持 `pending`。

## 1. 阻塞项总览

| # | 阻塞项 | 状态 | 证据（测试 / 命令 / 文件） |
|---|---|---|---|
| B-1 | W4 baseline 缺失（不得伪造，由 W4 evaluator 真实运行产生） | pending | `docs/evidence/README.md` 已如实记录不可用事实 |
| B-2 | Anti-ghost 校验真实化 | done | `scripts/quality/check_w5_antighost.py` 已升级为真实 runner；5/5 control point 真实激活；manifest 落盘 `docs/evidence/w5_antighost/manifest.json` 经 `w5_manifest_validator.py` 校验通过；详见 §5 |
| B-E2E | W5 真实用户 E2E 真实化（覆盖 Test Plan §13 14 个场景） | done | `scripts/e2e/e2e_w5_real_user.py` 14/14 PASS（E-W5-01~14）；manifest 落盘 `docs/e2e_evidence/w5_e2e/manifest.json` 经 `w5_manifest_validator.py` 校验 exit=0；详见 §6 |
| B-3 | candidate token 契约冻结（14 字段 / key_version 字符串 / resource 字段名统一） | done | `tests/w5/test_canonical_json_vectors.py` 25 项全绿；`W5_CANDIDATE_TOKEN_FIELDS` 单一来源（`src/promiselink/core/auth.py`） |
| B-4 | token 签发（issue_candidate_token + hex nonce） | done | `tests/test_w5_candidate_token_api.py::test_candidates_issue_token_and_operation_row` |
| B-5 | operation 持久化（EntityCorrection 共享事实源：token_hash / digest / resolver / score / space / 状态机） | done | `src/promiselink/services/w5_operation_service.py`；`test_candidates_issue_token_and_operation_row` 断言全部 W5 字段落库 |
| B-6 | 候选生成服务端化（synonym/difflib + 确定性排序 + digest） | done | `generate_entity_candidates` / `generate_todo_candidates`；`test_candidates_issue_token_and_operation_row`（rank/method/language_pair 断言） |
| B-7 | candidate_token API 边界（two-phase preflight + replay precedence + 零写入） | done | `tests/test_w5_candidate_token_api.py` 19 项 × 3 次连跑全绿（T-W5-02~16 映射见该文件 docstring） |
| B-8 | migration parity（SQLite/PostgreSQL + round-trip + ORM 对齐） | partial | SQLite round-trip PASS（upgrade head → 约束探针 → downgrade → re-upgrade）；`score_audit_logs` parity 缺口已补（`w5a_score_audit_logs`）；**PostgreSQL 实库矩阵未跑**（需 CI `dual_db` service） |
| B-9 | 四角色第三次复审 + Implementation Authorization | pending | 全部 `pending`；push/release/deploy 禁令维持 |

## 2. B-7 实施记录（2026-09-10）

### 2.1 交付物

| 文件 | 内容 |
|---|---|
| `src/promiselink/core/auth.py` | `issue_candidate_token`（hex nonce，避免 base64url 首字符触发 `_W5_ID_RE` 假阳性）/ `verify_candidate_token`（format→version→key→signature→scope→digest→resolver/score/space→TTL 顺序；`allow_expired_for_replay` 支撑 completed-replay 优先于 TTL）/ `candidate_token_hash`（SHA-256，仅存哈希不存原文） |
| `src/promiselink/services/w5_operation_service.py` | 服务端候选生成（synonym/difflib，score desc + id asc 确定性排序）、`compute_candidate_digest`、operation 创建（`action='issued'` 占位）/ `find_operation_by_token_hash` / `claim_operation`（CAS：issued→pending）/ `complete_operation`（白名单 result_summary） |
| `src/promiselink/api/v1/event_pipeline_api.py` | `GET /events/{id}/entities/{eid}/candidates`、`GET /events/{id}/entities/{eid}/todos/candidates?source_todo_id=`；`correct_event` 两阶段化：Phase 1 全量 preflight（token 验证 + 候选重算 + digest 比对 + operation 查询，任一失败零写入）→ Phase 2 per-user 锁内 claim→mutate→audit→complete→`commit_with_retry` |
| `src/promiselink/models/entity_correction.py` | `operation_key` 逐行唯一默认（消除 legacy 行唯一索引冲突）；scope XOR 约束修正（entity/todo 严格互斥 + promise/association 豁免 + todo issued/rejected 允许 selected_todo_id 为空） |
| `src/promiselink/services/entity_correction_service.py` | legacy 审计行补 operation_key / operation_status（ignore→rejected，其余→confirmed）/ completed_at |
| `src/promiselink/alembic/versions/w5_entity_correction_double_scope.py` | action CHECK 增加 'issued'（PG drop+NOT VALID 重建；SQLite batch 重建）；scope_xor 同步修正 |
| `src/promiselink/alembic/versions/w5a_add_score_audit_logs_table.py` | 补齐 score_audit_logs 迁移缺口（此前仅靠 create_all，与准入契约矛盾） |

### 2.2 安全语义闭环

- 非法 token（篡改/跨用户/跨事件/跨资源/digest 漂移/resolver/score/space 不匹配）→ HTTP 400 `CANDIDATE_TOKEN_INVALID`，且**零业务写入**（preflight 先于全部 mutation；T-W5-15 断言行数不变）。
- 首次提交已过 TTL → HTTP 410 `CANDIDATE_TOKEN_EXPIRED`（T-W5-03）。
- 已完成 operation 的 replay → HTTP 200 + 原持久化 result_summary，`replayed=true`，不重复 merge/audit；confirm 后 reject 同 token 不得逆转事实（T-W5-10/11/14）。
- 并发双 confirm → 单事实结果 + 至多一行审计（per-user lock 序列化 + CAS，T-W5-12）。
- 客户端提交的 candidate IDs / score / method 仅作兼容，服务端重算候选集并校验 selected ∈ 集合（T-W5-16 及 `test_selected_outside_candidate_set_rejected`）。
- 原始 token 与 HMAC secret 不落库；仅存 `token_hash`。

### 2.3 本轮顺带修复（回归暴露的真问题）

| 问题 | 修复 |
|---|---|
| `_candidate_token_error` 重复定义（auth.py） | 去重 |
| embedding `_cache_key` 引用不存在的 `_use_api`/`self.model`/`self.dimensions`（前轮引入、未被测试暴露） | 改用 `_provider`/`_model`/派生 dimensions；`EMBEDDING_PROVIDER_ALLOWLIST` 收敛 |
| embedding cache `user_scope="default"` 硬编码 | keyword-only `user_scope` 参数；生产调用方（semantic_search index_entity/index_event/search）显式传真实 user_id；默认 "global" 仅限系统级内容 |
| EntityResolution 生产路径复用 `"default"` 索引桶 | `resolve()` 增加 `session_id` 传递；extractor 以 event_id 为作用域 |
| legacy Entity/Todo 查询缺 event 绑定（可跨事件操作） | `Entity.source_event_id`/`Todo.source_event_id` 纳入查询 |
| `test_credit_score` 悬空 FK（旧 fixture FK 关闭时侥幸通过） | 测试数据改用 `_make_event_and_entity` 真实建实体（断言未动） |
| nonce 用 base64url 可能以 `-`/`_` 开头，被 `_W5_ID_RE` 假阳性拒绝（~9% 概率 flake） | 改 hex nonce（首字符恒为数字） |
| 严格 FK（conftest 改造）暴露的悬空 `source_event_id`/`related_entity_id` 测试数据（implicit_feedback / todo_generation_enhanced / nudge_generator） | 测试数据真实化或去持久化（断言语义不变） |
| `_index_loaded` 断言停留在 W4 bool 结构 | 断言更新为 W5 `(user_id, session_id)` 集合语义 |

### 2.4 本轮回归证据（2026-09-10，分批全量）

- 范围：`tests/` 全部 94 个根测试文件 + `tests/{w5,golden,api,e2e}/` 子目录（`tests/test_e2e_real_user_scenarios.py` 按既有约定排除）。
- 结果（修复后）：约 **2171 passed / 79 skipped / 0 failed**；分批明细：334 + 382 + 253(修复3) + 200 + 431 + 349(修复2) + 68 + 94 + 60，skip 均为 golden LLM 模式（`GOLDEN_RUN_LLM=1` 成本控制）与既有 skip。
- 命令形态：`pytest <files> -q -p no:cacheprovider --no-cov -o addopts="" --tb=no -rf`。
- 说明：全仓单进程跑 `--maxfail=1`（pyproject addopts 门禁）+ L-V4514-001 sandbox 后台挂起问题，采用分批前台执行；修复项全部单文件复验通过。

## 3. B-8 剩余工作（唯一 partial 项）

- [ ] PostgreSQL 实库 upgrade/downgrade/parity 矩阵（CI `dual_db` service 就绪后执行）
- [ ] `alembic check` 在迁移后实库上通过（本地旧库为伪差异源，已确认非门禁项）
- [ ] 历史行（W3 legacy rows）在 PG 上的 NOT VALID 约束兼容性验证

## 4. 复核纪律

- 本表由 Implementation 阶段维护；每次状态翻转必须同步更新证据列。
- 四角色第三次复审以本表为输入；任何 `pending`/`partial` 项存在即维持 Implementation Authorization `blocked`。
- 禁令不变：B-9 完成前不 push、不 release、不 deployment。

## 5. B-2 实施记录（2026-09-10，v1.1）

### 5.1 目标

消除 B-2 "Anti-ghost 校验真实化"。此前 `scripts/quality/check_w5_antighost.py` 仅产出 honest-pending 占位输出，违反 Test Plan §16.1 / §16.2 与 Manifest Schema v1 的 "control points 必须真激活" 契约。本轮将 runner 升级为真实执行路径，所有 5 个 control point 必须由 production 代码自然触发，缺一即 EXIT 5。

### 5.2 交付物

| 文件 | 内容 |
|---|---|
| `src/promiselink/core/activation.py`（新） | 模块级 call counter 体系：5 个 control point（issue_candidate_token / verify_candidate_token / multilingual_resolver / embedding_space_isolation / operation_state_machine）+ threading.Lock + `record()` / `reset_counters()` / `snapshot()` / `required_control_points()` API；模块→control_point 映射元数据 |
| `src/promiselink/core/auth.py`（改） | 接入点 1：`issue_candidate_token` 末尾（成功路径）`record("issue_candidate_token")`；接入点 2：`verify_candidate_token` 末尾（仅成功路径，避免重放侧放大计数）`record("verify_candidate_token")`；`try/except` 防御性写入，observability 永不阻塞 production |
| `src/promiselink/services/w5_operation_service.py`（改） | 接入点 3：`claim_operation` CAS 成功分支（`rowcount == 1`）`record("operation_state_machine")`，覆盖 issued → pending 真状态机 |
| `src/promiselink/services/embedding_provider.py`（改） | 接入点 4：`_cache_key` 末尾 `record("embedding_space_isolation")`，覆盖 profile_version+provider+model+dimension+embedding_space+user_scope+content digest 命名空间路径 |
| `src/promiselink/services/entity_resolution.py`（改） | 接入点 5：`EntityResolutionEngine.resolve` 顶部（logger 之后）`record("multilingual_resolver")`，覆盖 synonym / difflib / cross-language 真路径 |
| `scripts/quality/check_w5_antighost.py`（重写） | 从 skeleton 升级为真实 runner：reset → 5 步 synthetic probe 真跑 production 函数 → snapshot → PII scan（11 位手机/loose mobile/email 三类 regex）→ 构建 manifest（schema_version=w5-evidence-v1）→ 落盘 → 二次 PII scan → subprocess 调 `w5_manifest_validator.py` 外部校验 → required control point 全激活才 EXIT 0；auto-inject `src/` 到 `sys.path` 让脚本可直接运行；`--ci / --strict-markers / --manifest / --control-points` CLI 完整 |
| `docs/evidence/w5_antighost/manifest.json`（生成） | runner 真跑产物（schema_version=w5-evidence-v1 / validator_version=w5-manifest-validator-v1 / commit_sha=9c2bddbe387a8abadb58ef126b9ebb6c0b0a43ad / migration_head=4 heads / counts={pass:5,fail:0} / pii_scan_result=pass / _diagnostic.missing_required_points=[]） |

### 5.3 runner 退出码契约

| 退出码 | 含义 |
|---|---|
| 0 | 全部 required control point 真实激活 + PII pass + validator 接受 |
| 2 | PENDING：保留给下游任务（与 skeleton 一致） |
| 3 | manifest artifact 缺失/写盘失败 |
| 4 | PII 命中 或 validator reject |
| 5 | 必需 control point 未全部激活（counter==0） |

### 5.4 真实证据（2026-09-10）

| 维度 | 命令 / 产物 | 结果 |
|---|---|---|
| 5 步 synthetic probe 真跑 | `CANDIDATE_TOKEN_SECRET_V1="…"` `.venv/bin/python scripts/quality/check_w5_antighost.py --ci --strict-markers --manifest docs/evidence/w5_antighost/manifest.json` | EXIT=0；counts.pass=5/5 |
| 必需 control point 全激活 | manifest `_diagnostic.missing_required_points` | `[]`（5 项 snapshot count==1） |
| PII 扫描 | runner 内部 `_scan_pii` 三类 regex（11 位手机/loose mobile/email）+ manifest 落盘后二次扫描 | pii_scan_result=pass，pii_hit_patterns=`[]` |
| Validator 校验 | subprocess 调 `scripts/quality/w5_manifest_validator.py docs/evidence/w5_antighost/manifest.json` | exit 0（"manifest ... accepted"） |
| Migration head 真实解析 | runner `_migration_head()` 解析 alembic revisions 拓扑 | `d4e5f6a7b8c9,f3a4b5c6d7e8,w5_entity_correction_double_scope,w5a_score_audit_logs`（4 head 与 `alembic heads` 一致） |
| Config digest 真实计算 | runner `_config_digest()` 对 W5 相关 8 个 config 关键词哈希 | `26354799cc9fecf29116d88d40912156c1b76a97d0cc3c75d37e1a59a6120a83`（SHA-256 / 64-hex） |
| Embedding profile match | `_diagnostic.control_points.__probe_*` 时间戳 + metrics.embedding_profile_match.value=1 | 全部阈值通过 |
| 回归回归 | `pytest tests/ -q ... --ignore=tests/test_e2e_real_user_scenarios.py` | **2073 passed / 79 skipped / 0 failed**（activation hooks 5 处 try/except 写入，未引入副作用） |

### 5.5 反幻觉防线

- 所有 5 个 hook 均包裹在 `try/except Exception: pass`，observability 故障永不破坏 production 路径（runner 的 cycle 不会进入 production）。
- counter reset 在 runner 进程内 `reset_counters()` 起点执行；production 调用方不会因 runner 误清零而漏报（runner 通过 `subprocess` 跑 production 函数于独立会话内）。
- `verify_candidate_token` hook 仅 success-only，避免重放攻击场景下人为放大计数（counter 反映真实业务成功）。
- runner 退出码 5 是 anti-ghost 的 fail-closed 门禁：任何一个 required control point 未激活即拒绝出 manifest。

### 5.6 B-2 → 下游解锁

- ✅ Anti-ghost 路径打通 → manifest schema 路径打通 → E2E real-user 黑盒可复用同一 manifest schema。
- ⏭️ 下一步：B-2 改动本地 commit（不 push）→ 真实化 `scripts/e2e/e2e_w5_real_user.py` → 产出 `docs/evidence/w5_e2e/manifest.json`（w5-e2e command allowlist 入口）→ B-1 W4 baseline 由 W4 evaluator 真实运行 → B-8 PG dual_db 矩阵 → B-9 四角色第三次复审 → Implementation Authorization。

## 6. E2E real-user 真实化实施记录（2026-09-11，v1.2）

### 6.1 目标

消除 B-E2E "W5 真实用户 E2E 真实化"。覆盖 Test Plan §13 列出的 14 个真实用户黑盒场景（E-W5-01~14），每个场景独立 SQLite + `dependency_overrides` 注入 user_id + `httpx.ASGITransport` 真实黑盒，禁用 `process_event_background` 后台流水线，产出 `docs/e2e_evidence/w5_e2e/manifest.json` 并由 `w5_manifest_validator.py` 校验。

### 6.2 交付物

| 文件 | 内容 |
|---|---|
| `scripts/e2e/e2e_w5_real_user.py`（新） | 14 个 SCENARIOS 列表 + `--case` 单点冒烟；强制环境变量开启 W5（CROSS_LANGUAGE_ENABLED / TODO / EMBEDDING / ROLLOUT_PERCENT=100 / CANDIDATE_TOKEN_SECRET_V1 / SYNONYM_DICT_PATH）；每个场景独立 `create_async_engine("sqlite+aiosqlite:///{db_path}")` + `Base.metadata.create_all` + `PRAGMA foreign_keys=ON`；`dependency_overrides[get_current_user_id] = lambda: USER_ID` 黑盒；`httpx.ASGITransport(app=app)`；pre-create Entity/Todo（不依赖真实 pipeline 抽取）；`_build_manifest` 落盘 `docs/e2e_evidence/w5_e2e/manifest.json`（schema_version=w5-evidence-v1，command="w5-e2e"），单字符串 `migration_head` 来自 `alembic heads`，`metrics` 为 dict 结构；E-W5-04 用 `now=past` 触发 TTL 410；E-W5-08 直接解码 token envelope 取出服务端 `operation_key` |
| `data/e2e_w5_synonyms.json`（新） | E2E 专用同义词覆盖：CJK↔Latin 人名/公司名映射，保证 synonym/difflib 路径命中（SYNONYM_MATCH_SCORE=0.95） |
| `src/promiselink/services/w5_operation_service.py`（改） | `generate_entity_candidates` 调用 `load_synonyms(dict_path)` 接受 `synonym_dict_path` 参数（默认空 → 加载 seeds，保持原行为；E2E 通过 `SYNONYM_DICT_PATH` 注入覆盖） |
| `docs/e2e_evidence/w5_e2e/manifest.json`（生成） | runner 真跑产物（schema_version=w5-evidence-v1 / validator_version=w5-manifest-validator-v1 / command="w5-e2e" / counts={pass:14,fail:0} / pii_scan_result=pass） |

### 6.3 runner 退出码契约

| 退出码 | 含义 |
|---|---|
| 0 | 14 个场景全 PASS + PII pass + validator 接受 |
| 4 | PII 命中 或 validator reject |
| 5 | 必需场景未全部通过 |

### 6.4 真实证据（2026-09-11）

| 维度 | 命令 / 产物 | 结果 |
|---|---|---|
| 14 场景全跑 | `.venv/bin/python scripts/e2e/e2e_w5_real_user.py` | `结果：PASS=14 FAIL=0 SKIP=0` |
| Manifest 落盘 | runner `_build_manifest` 写 `docs/e2e_evidence/w5_e2e/manifest.json` | 已生成；schema_version=w5-evidence-v1，command="w5-e2e" |
| Validator 校验 | runner 末尾 `subprocess.check_call(["python", "scripts/quality/w5_manifest_validator.py", manifest])` | `validator exit: 0` |
| 单点冒烟 | `.venv/bin/python scripts/e2e/e2e_w5_real_user.py --case E-W5-01` | PASS |
| Migration head 真实解析 | runner `_migration_head()` 调 `alembic heads` 取首行 revision id | 真实值（按 `alembic heads` 拓扑） |

### 6.5 E2E 真实化 → 下游解锁

- ✅ E2E 真实用户黑盒打通 → 14 场景全绿 → manifest 落盘并 validator 接受 → 可支撑 PRD "真实 API/UI E2E" 准入契约。
- ⏭️ 下一步：B-1 W4 baseline 由 W4 evaluator 真实运行 → B-8 PG dual_db upgrade/downgrade/parity 矩阵 → B-9 四角色第三次复审邀请 → 全部 approved → Implementation Authorization。push / release / deployment 禁令在 B-9 完成前维持。
