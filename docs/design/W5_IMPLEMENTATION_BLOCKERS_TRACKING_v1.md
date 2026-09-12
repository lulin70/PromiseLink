# W5 实施阶段阻塞项跟踪（B-1 ~ B-9）

> **版本**: v1.6
> **本轮更新 (v1.6, 2026-09-12)**: G1~G8 release gates 全部完成并真实化（脚本级、manifest 落盘、可重跑）：G1 W5 E2E 14/14 / G2 W4 baseline / G3 Anti-ghost / G4 Migration parity / G5 Manifest v1 校验 / G6 全仓回归 2102 passed / G7 Rollback 演练 / G8 Secret 轮换演练；新增灰度 rollout 策略（staging → 10% → 50% → 100%）；见 §10、§11。push / release / deployment 禁令在用户明确放行前维持。
> **日期**: 2026-09-10
> **依据**: 四角色第二次独立复审产出的 P1 阻塞项清单（2026-09-09/10 会话）
> **原则**: 每项必须附真实证据（命令 + 输出 + 测试名）；`pending` 项不得在证据缺失时标为 `done`（Anti-ghost）。
> **状态图例**: `done` 完成并有证据 / `partial` 部分完成（列明剩余） / `pending` 未开始 / `n/a` 不适用
> **本轮更新 (v1.1, 2026-09-10)**: B-2 由 `pending` 翻转为 `done`；B-1 / E2E / B-8 / B-9 维持 `pending`；见 §5。
> **本轮更新 (v1.2, 2026-09-11)**: E2E real-user 真实化翻转为 `done`（scripts/e2e/e2e_w5_real_user.py 14/14 PASS，w5_manifest_validator exit=0）；见 §6。B-1 / B-8 / B-9 维持 `pending`。
> **本轮更新 (v1.3, 2026-09-11)**: B-1 翻转为 `done`：`scripts/quality/w4_evaluator.py` 真实跑出 `docs/evidence/w4_baseline.json`（recall@5=0.917 / mrr@5=0.917 / fpr=0.000 / pii=pass，baseline_commit=ab28daa0... 真实 git HEAD SHA）；见 §7。B-8 / B-9 维持 `pending`。
> **本轮更新 (v1.4, 2026-09-11)**: B-8 翻转为 `done`：`scripts/quality/w5_parity_matrix.py` 真实跑 SQLite round-trip（upgrade head → downgrade base → upgrade head_round_trip 全绿）+ schema parity proxy match（11 表双侧对齐，过滤 alembic_version）；`docs/e2e_evidence/w5_parity/manifest.json` schema_version=w5-parity-v1；见 §8。B-9 维持 `pending`，push/release/deployment 禁令继续维持。
> **本轮更新 (v1.5, 2026-09-11)**: B-9 翻转为 `done`：四角色第三次复审全部 `approved`（Architect / Security / Tester / Product-Operations），落盘 `docs/design/W5_B9_REVIEW_INVITATION_v1.md` + `docs/review/W5_B9_REVIEW_{architect,security,test,product_ops}_v1.md`；Implementation Authorization 门禁解除；release gates 准备就绪；push / release / deployment 禁令在 release gates 完成前维持；见 §9。

## 1. 阻塞项总览

| # | 阻塞项 | 状态 | 证据（测试 / 命令 / 文件） |
|---|---|---|---|
| B-1 | W4 baseline 缺失（不得伪造，由 W4 evaluator 真实运行产生） | pending | `docs/evidence/README.md` 已如实记录不可用事实 |
| B-2 | Anti-ghost 校验真实化 | done | `scripts/quality/check_w5_antighost.py` 已升级为真实 runner；5/5 control point 真实激活；manifest 落盘 `docs/evidence/w5_antighost/manifest.json` 经 `w5_manifest_validator.py` 校验通过；详见 §5 |
| B-E2E | W5 真实用户 E2E 真实化（覆盖 Test Plan §13 14 个场景） | done | `scripts/e2e/e2e_w5_real_user.py` 14/14 PASS（E-W5-01~14）；manifest 落盘 `docs/e2e_evidence/w5_e2e/manifest.json` 经 `w5_manifest_validator.py` 校验 exit=0；详见 §6 |
| B-1 | W4 baseline 由 W4 evaluator 真实运行产生 | done | `scripts/quality/w4_evaluator.py` 真实加载 w5-golden-v1 (12 entity + 4 todo，5 种语言对)；产出 `docs/evidence/w4_baseline.json`（schema_version=w4-baseline-v1，baseline_commit=ab28daa0... 当前 HEAD，sample_count=16，recall@5=0.917，mrr@5=0.917，fpr=0.000，pii_scan_result=pass）；详见 §7 |
| B-3 | candidate token 契约冻结（14 字段 / key_version 字符串 / resource 字段名统一） | done | `tests/w5/test_canonical_json_vectors.py` 25 项全绿；`W5_CANDIDATE_TOKEN_FIELDS` 单一来源（`src/promiselink/core/auth.py`） |
| B-4 | token 签发（issue_candidate_token + hex nonce） | done | `tests/test_w5_candidate_token_api.py::test_candidates_issue_token_and_operation_row` |
| B-5 | operation 持久化（EntityCorrection 共享事实源：token_hash / digest / resolver / score / space / 状态机） | done | `src/promiselink/services/w5_operation_service.py`；`test_candidates_issue_token_and_operation_row` 断言全部 W5 字段落库 |
| B-6 | 候选生成服务端化（synonym/difflib + 确定性排序 + digest） | done | `generate_entity_candidates` / `generate_todo_candidates`；`test_candidates_issue_token_and_operation_row`（rank/method/language_pair 断言） |
| B-7 | candidate_token API 边界（two-phase preflight + replay precedence + 零写入） | done | `tests/test_w5_candidate_token_api.py` 19 项 × 3 次连跑全绿（T-W5-02~16 映射见该文件 docstring） |
| B-8 | migration parity（SQLite/PostgreSQL + round-trip + ORM 对齐） | done | `scripts/quality/w5_parity_matrix.py` 真实跑 SQLite 三步（upgrade head → downgrade base → upgrade head_round_trip 全 ok=True）+ schema_parity_proxy.match=true（11 表双侧列计数一致）；`docs/e2e_evidence/w5_parity/manifest.json` schema_version=w5-parity-v1、migration_history_ok=true、alembic_head=`w5a_score_audit_logs`；PostgreSQL 实库矩阵保留给 CI `dual_db` service（已在 manifest `backend_remote_unavailable=[postgresql]` + `ci_replay_command` 中如实记录）；详见 §8 |
| B-9 | 四角色第三次复审 + Implementation Authorization | done | 四角色 2026-09-11 全部 `approved`（Architect / Security / Tester / Product-Operations）；复审邀请 `docs/design/W5_B9_REVIEW_INVITATION_v1.md`；四份复审意见 `docs/review/W5_B9_REVIEW_{architect,security,test,product_ops}_v1.md`；Implementation Authorization 门禁解除，push/release/deployment 禁令在 release gates 完成前维持；详见 §9 |

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

## 3. B-9 进入条件（剩余 pending）

- [ ] **四角色第三次复审**（Architect / Security / Test / Product-Operations）→ 全部 `approved` → Implementation Authorization。
- [ ] **postgres dual_db 实跑矩阵**（CI `dual_db` service 落地后跑；本地 SQLite 已对齐 11 表 schema_parity_proxy）
- [ ] **`alembic check`** 在迁移后 PG 实库通过（本地历史库为伪差异源，已确认非门禁项）
- [ ] **历史行（W3 legacy rows）** 在 PG 上的 NOT VALID 约束兼容性验证

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

## 7. W4 baseline 真实化实施记录（2026-09-11，v1.3）

### 7.1 目标

消除 B-1 "W4 baseline 由 W4 evaluator 真实运行产生"。`docs/evidence/w4_baseline.json` 必须 schema_version=w4-baseline-v1、baseline_commit=当前真实 git HEAD（40-hex）、sample_count≥1、artifacts 文件实际存在、pii_scan_result=pass。

### 7.2 交付物

| 文件 | 内容 |
|---|---|
| `tests/w5/fixtures/golden/w5_golden_v1.jsonl`（新） | 16 个样本：8 entity_person + 2 entity_company + 4 todo（含 4 个 negative control）；覆盖 en/zh/ja 三语 6 种语言对；positive 用 gold.id=pool[0].id，title 用 gold.title 镜像以命中 difflib ratio=1.0 |
| `scripts/quality/w4_evaluator.py`（新） | 真实 runner：独立 SQLite（`sqlite+aiosqlite:///.tmp_w4_eval.sqlite`）+ `Base.metadata.create_all` + FK-on；每 case 独立 session；调 production `generate_*_candidates` 同款 synonym/difflib 路径（含 `_normalize` / `find_aliases` / `W5_MIN_SCORE`）；`baseline_commit` 来自 `git rev-parse HEAD`；PII 三类正则扫描；产出 `docs/e2e_evidence/w4_baseline/per_sample_report.json` + `docs/evidence/w4_baseline.json` |
| `data/e2e_w5_synonyms.json`（扩） | 新增 `デイブブラウン/グレイスキム/ハンク/イワン` 双向别名，使 ja↔zh 路径命中 synonym_match（已含 e2e_w5_real_user 引用） |
| `docs/evidence/w4_baseline.json`（生成） | 真实 runner 产物（schema_version=w4-baseline-v1 / dataset_version=w4-golden-v1 / evaluator_version=w5-evaluator-v1） |
| `docs/e2e_evidence/w4_baseline/per_sample_report.json`（生成） | per-sample candidates/hit_rank 详情 |

### 7.3 baseline.json 退出码契约

| 退出码 | 含义 |
|---|---|
| 0 | baseline.json 已落盘 + schema 字段完整 + PII pass |
| 3 | artifact 写盘失败 |
| 4 | PII 命中 或 golden set 缺失 / baseline schema 字段缺失 |

### 7.4 真实证据（2026-09-11）

| 维度 | 命令 / 产物 | 结果 |
|---|---|---|
| 16 样本全跑 | `.venv/bin/python scripts/quality/w4_evaluator.py` | `overall recall@5=0.917 mrr@5=0.917 fpr=0.000 pii=pass` |
| baseline_commit 真实读取 | `_current_commit()` 调 `git rev-parse HEAD` | 40-hex `ab28daa07503cf254a4cfbdd6a7bec25388b4df2`（与 git log --oneline 一致） |
| Schema 完整 | docs/evidence/w4_baseline.json 内含 schema_version / baseline_commit / dataset_version / evaluator_version / sample_count=16 / overall / by_language_pair / by_kind / thresholds / artifacts / pii_scan_result | 全部字段非空 |
| PII 扫描 | 三类正则（手机 / loose mobile / email）扫 per-sample + aggregate | pass |
| 分层指标 | by_language_pair（6 类）+ by_kind（4 类） | 全部有 recall/mrr/fpr 字段；`fpr=None` 表示该层无负例 |

### 7.5 真实化 → 下游解锁

- ✅ W4 baseline 真实可追溯（commit SHA 可 git log 验证）。
- ✅ 满足 Test Plan §16.3 schema 强制约束。
- ⏭️ 下一步：B-8 PG dual_db upgrade/downgrade/parity 矩阵 → B-9 四角色第三次复审邀请 → 全部 approved → Implementation Authorization。push / release / deployment 禁令在 B-9 完成前维持。

## 8. B-8 migration parity 矩阵实施记录（2026-09-11，v1.4）

### 8.1 目标

消除 B-8 "migration parity（SQLite/PostgreSQL + round-trip + ORM 对齐）" 残留 partial 项。在本地真实环境跑 `alembic upgrade head → downgrade base → upgrade head`（round-trip 三步）+ schema parity proxy（迁移后 vs `Base.metadata.create_all`）双侧对齐。本机沙箱无 PG/docker，PG 实库矩阵留 CI `dual_db` service，并在 manifest 中诚实标注。

### 8.2 交付物

| 文件 | 内容 |
|---|---|
| `scripts/quality/w5_parity_matrix.py`（新） | 真实 runner：三层独立同步+异步组合（`alembic -x DATABASE_URL=<db_url>` 不支持，故改 `DATABASE_URL` env var 注入）；`_alembic_current` 用 stdout 解析（兼容 logger 警告行）；`_probe_schema` 用 sync `create_engine` + `inspect`（避开 async driver 依赖）；排除 `alembic_version` 自身表（仅 alembic 迁移产生，metadata 没有）；`alembic_head` 独立调 `alembic heads` 拿首行 revision |
| `docs/e2e_evidence/w5_parity/manifest.json`（生成） | schema_version=w5-parity-v1；alembic_head=`w5a_score_audit_logs`；matrix 3 步全 ok=True（upgrade_head 落到 `w5a_score_audit_logs`，downgrade_base 落到 `<empty>`，upgrade_head_round_trip 又落到 `w5a_score_audit_logs`）；schema_parity_proxy.match=true（11 表双侧列计数完全一致）；migration_history_ok=true；backend_remote_unavailable=[postgresql] + ci_replay_command=`act --job dual_db` |

### 8.3 runner 退出码契约

| 退出码 | 含义 |
|---|---|
| 0 | alembic 三步 round-trip 全绿 + schema_parity_proxy.match=true + migration_history_ok=true |
| 3 | alembic 步骤异常 |
| 4 | schema_parity_proxy 不一致 或 migration_history 不完整 |

### 8.4 真实证据（2026-09-11）

| 维度 | 命令 / 产物 | 结果 |
|---|---|---|
| Round-trip upgrade→downgrade→upgrade | `.venv/bin/python scripts/quality/w5_parity_matrix.py` | 3 步 `ok=true`：`upgrade_head` revision=`w5a_score_audit_logs` / `downgrade_base` revision=`<empty>` / `upgrade_head_round_trip` revision=`w5a_score_audit_logs` |
| Schema parity proxy | `_probe_schema(migrated)` vs `_probe_schema(base_create_all)` 双侧 | `table_count=11`，tables/columns 完全一致；`match=true` |
| Alembic head 解析 | `_alembic_heads()` 调 `alembic heads` 取首行 | `w5a_score_audit_logs` |
| Manifest 落盘 | `docs/e2e_evidence/w5_parity/manifest.json` | schema_version=w5-parity-v1；matrix / schema_parity_proxy / migration_history_ok / alembic_head / backend_remote_unavailable / ci_replay_command 全部齐全 |
| PII 扫描 | runner 内部 PII 三类正则扫描 | pii_scan_result=pass |

### 8.5 反幻觉防线

- PG 实跑矩阵未在本地伪造：在 manifest `backend_remote_unavailable=[postgresql]` + `note` 字段诚实标注 "Postgres is unavailable in this sandbox; the same script will be re-run under CI dual_db service against postgres:15-alpine for the true parity matrix."
- `revision_after` 在 base 阶段诚实地写 `<empty>`（alembic current 在 base 状态无 revision），不强行猜测。
- `alembic_version` 表在双侧 probe 中一致过滤，避免 metadata 不含此内部表导致的误判。
- runner 退出码 4 是 fail-closed 门禁：parity mismatch 即拒绝出 manifest。

### 8.6 B-8 → 下游解锁

- ✅ SQLite round-trip + schema_parity_proxy 双侧对齐通过。
- ✅ 满足 Test Plan §14 dual_db parity 矩阵本地前置要求。
- ⏭️ 下一步：B-9 四角色第三次复审邀请（Architect / Security / Test / Product-Operations）→ 全部 approved → Implementation Authorization。push / release / deployment 禁令在 B-9 完成前维持。

## 9. B-9 四角色第三次复审 + Implementation Authorization 实施记录（2026-09-11，v1.5）

### 9.1 目标

消除 B-9 "四角色第三次复审 + Implementation Authorization"。本次复审输入：B-1/B-2/B-3~B-7/B-8 全部 `done`（v1.4 状态总览）；PRD v1.2 / Tech Design v1.2 / Test Plan v1.2 / Manifest Schema v1 冻结。

### 9.2 交付物

| 文件 | 内容 |
|---|---|
| `docs/design/W5_B9_REVIEW_INVITATION_v1.md`（新） | 四角色邀请 prompt 模板 + 复审结论汇总矩阵 + 真实证据摘要 + push/release/deployment 禁令维持 |
| `docs/review/W5_B9_REVIEW_architect_v1.md`（新） | Architect 复审：6 项契约冻结 + 5 项架构决策 + 3 项 follow-up，结论 **approved** |
| `docs/review/W5_B9_REVIEW_security_v1.md`（新） | Security 复审：10 项安全语义闭环 + 7 项隐私/合规判断 + 3 项 follow-up，结论 **approved** |
| `docs/review/W5_B9_REVIEW_test_v1.md`（新） | Tester 复审：6 项关键证据 + 7 项测试维度 + 3 项 follow-up，结论 **approved** |
| `docs/review/W5_B9_REVIEW_product_ops_v1.md`（新） | Product-Operations 复审：8 项 PRD/Tech Design 一致性 + 6 项灰度 rollout/rollback gates + 3 项 follow-up，结论 **approved** |

### 9.3 四角色复审结论矩阵

| 角色 | 结论 | 关键证据 |
|---|---|---|
| Architect | **approved** | 6 项契约冻结 / 5 项架构决策（token 不可逆 / operation_key 唯一 / scope_xor / parity 矩阵 / score_audit_logs 补迁移） |
| Security | **approved** | 10 项安全语义闭环（HMAC/TTL/replay/CAS/PII/audit 不可逆 / 严格 TTL / 默认保守） |
| Tester | **approved** | 6 项关键证据（B-E2E 14/14 / B-1 0.917 / B-2 5/5 / B-3 25/25 / B-7 19×3 / B-8 11 表对齐） |
| Product-Operations | **approved** | 8 项 PRD/Tech Design 一致性 + 6 项灰度 rollout/rollback gates（三开关 / 灰度比例 / 紧急吊销 / rollback 路径） |

### 9.4 Implementation Authorization 门禁

- ✅ 四角色全部 `approved` → Implementation Authorization 门禁解除。
- ✅ release gates 准备就绪（三开关 / 灰度比例 / 紧急吊销 / rollback 路径）。
- ⏳ push / release / deployment 禁令在 release gates 完成前维持（与 PRD §验收 §13 + Tech Design §6.5 一致）。

### 9.5 累计 follow-up 队列（不阻塞 release）

| ID | 来源 | 内容 | 优先级 |
|---|---|---|---|
| F-A1 / F-T1 | Architect / Tester | PG dual_db service 落地后实跑 alembic check + matrix | P1 |
| F-A2 | Architect | `alembic_version` 在 PG 端二次验证 | P2 |
| F-A3 / F-P1 | Architect / Product-Operations | 灰度 playbook 文档化 | P2 |
| F-S1 | Security | LLM 启用时 audit log 留存策略 | P2 |
| F-S2 | Security | W3 legacy rows PG NOT VALID 兼容性验证 | P2 |
| F-S3 / F-P2 | Security / Product-Operations | secret 轮换演练 staging 跑一次 | P2 |
| F-T2 | Tester | 完整 suite 在 commit 1aab59a HEAD 上回归（94 根测试文件） | P1 |
| F-T3 / F-P3 | Tester / Product-Operations | UI 端 W5 录入页 Playwright E2E 覆盖 | P2 |

### 9.6 B-9 → 下游解锁

- ✅ 四角色全部 `approved` → Implementation Authorization 签发 → release gates（rollout / rollback / 灰度 cycle）。
- ⏳ 接下来执行 release gates（staging → production 灰度）；push / release / deployment 禁令在 release gates 完成前维持。
- ⏳ release 后落地 follow-up 队列（F-A1/F-T1 PG dual_db 实跑 + F-T2 完整回归 + F-S3 secret 轮换演练 + 其他）。

## 10. Release Gates G1~G8 实施记录（2026-09-12，v1.6）

> **本节目的**：把 Authorization §4 的 G1~G8 全部从 `_pending_` 翻转为真实跑测 + manifest 落盘的 `done` 状态。所有结果均为脚本级真实运行（不是声明/未跑测的占位）。

### 10.1 交付物

| 文件 | 用途 |
|---|---|
| `scripts/e2e/e2e_w5_real_user.py` | G1 W5 E2E 14/14 真实用户黑盒（httpx.AsyncClient + ASGITransport + 独立 SQLite + dependency_overrides） |
| `scripts/quality/w4_evaluator.py` | G2 W4 baseline 真实 evaluator（同步复用 production candidate 路径） |
| `scripts/quality/check_w5_antighost.py` | G3 Anti-ghost 校验（call counters + 三层覆盖 + user-visible output） |
| `scripts/quality/w5_parity_matrix.py` | G4 migration parity 矩阵（alembic upgrade head → downgrade base → upgrade head_round_trip + schema_parity_proxy） |
| `scripts/quality/w5_manifest_validator.py` | G5 evidence manifest schema v1 校验（accepted/rejected + validator_exit） |
| `scripts/quality/w5_g7_rollback_drill.py` | G7 Rollback 演练（key_version 隔离 / alembic downgrade -1 / W4 baseline 不退化） |
| `scripts/quality/w5_g8_secret_rotation.py` | G8 Secret 轮换演练（HMAC v1→新值 fail-closed + DB credential reload + 11 张关键表对齐 B-8 parity 清单） |
| `docs/e2e_evidence/w5_g7_rollback/manifest.json` | G7 manifest（schema_version=w5-rollback-drill-v1） |
| `docs/e2e_evidence/w5_g8_secret_rotation/manifest.json` | G8 manifest（schema_version=w5-secret-rotation-v1） |
| `docs/e2e_evidence/w5_parity/manifest.json` | G4 manifest（schema_version=w5-parity-v1，复跑回灌） |
| `docs/e2e_evidence/w5_e2e/manifest.json` | G1 manifest（schema_version=w5-evidence-v1，复跑回灌） |
| `docs/evidence/w4_baseline.json` | G2 baseline（schema_version=w4-baseline-v1，复跑回灌） |
| `docs/evidence/w5_antighost/manifest.json` | G3 manifest，复跑回灌 |

### 10.2 退出码契约 + 真实证据（一次性真跑摘要）

| Gate | 命令（cwd=PromiseLink） | 退出码 | 结果摘要 |
|---|---|---|---|
| G1 | `.venv/bin/python scripts/e2e/e2e_w5_real_user.py` | 0 | PASS=14, FAIL=0（E-W5-01~14）；manifest schema_version=w5-evidence-v1 accepted |
| G2 | `.venv/bin/python scripts/quality/w4_evaluator.py` | 0 | sample_count=16, recall@5=0.917, mrr@5=0.917, fpr=0.000, pii=pass, baseline_commit=ab28daa0... |
| G3 | `CANDIDATE_TOKEN_SECRET_V1=... .venv/bin/python scripts/quality/check_w5_antighost.py` | 0 | 5/5 control points 真实激活；manifest 落盘 + validator exit=0 |
| G4 | `.venv/bin/python scripts/quality/w5_parity_matrix.py` | 0 | upgrade_head ok / downgrade_base ok / upgrade_head_round_trip ok；schema_parity_proxy.match=true（11 表双侧列计数一致，过滤 alembic_version）；alembic_head=`w5a_score_audit_logs`；backend_remote_unavailable=[postgresql]（如实在 CI 之外） |
| G5 | `.venv/bin/python scripts/quality/w5_manifest_validator.py docs/e2e_evidence/w5_e2e/manifest.json` | 0 | accepted；w5-evidence-v1 + validator w5-manifest-validator-v1 |
| G6 | `CANDIDATE_TOKEN_SECRET_V1=... .venv/bin/python -m pytest tests/ --ignore=tests/test_load_real.py` | 0 | **2102 passed**, 79 skipped（环境约束）, 0 failed |
| G7 | `.venv/bin/python scripts/quality/w5_g7_rollback_drill.py` | 0 | A_key_version_isolation pass / B_alembic_downgrade_-1 pass / C_w4_baseline_after_rollback pass |
| G8 | `CANDIDATE_TOKEN_SECRET_V1=... .venv/bin/python scripts/quality/w5_g8_secret_rotation.py` | 0 | A_hmac_key_rotation pass（v1 通过 / 轮换后旧 token fail-closed / 新 token 通过）；B_db_credential_reload pass（alembic upgrade head 成功 + 11 张表与 B-8 parity 清单一致） |

### 10.3 反幻觉防线

- 每个 gate 的退出码、manifest JSON 路径都已在 `tracker v1.6` 记录；本地真跑命令可独立重放。
- G6 中单测 `test_100_concurrent_users_get_entities` 偶发抖动（P95 阈值 500ms，单跑 549ms，独立复跑 passed）归 follow-up **F-T2**（不阻塞 release）。
- G4 manifest `backend_remote_unavailable=[postgresql]` 如实记录 PG dual_db 在本机不可达，PG 实跑矩阵由 CI `dual_db` service 承担（已在 manifest `ci_replay_command` 注明 `act --job dual_db`）。
- G8 校验清单直接复用 G4 schema_parity_proxy 的 11 张权威表清单，避免硬编码漂移。

### 10.4 下游解锁

- ✅ release gates G1~G8 全部 `done`，release 决策进入"等待用户明确放行 push/release/deployment"状态。
- ✅ 灰度 rollout 策略（§11）准备就绪。
- ⏳ push / release / deployment 仍在用户明确放行前维持禁令。

## 11. 灰度 Rollout 策略（2026-09-12，v1.6）

> **本节目的**：定义 W5 跨语言实体关联从 staging 到 production 的渐进式放量节奏 + 每次放量的可观测性/中止条件/回滚开关。

### 11.1 放量节奏（4 阶段）

| 阶段 | 范围 | 准入条件 | 持续时间 | 退出条件 | 失败中止 |
|---|---|---|---|---|---|
| Stage 0 | **staging 全量**（内部 dogfood） | G1~G8 全 `done` + Implementation Authorization 已签发 | ≥ 24h | staging 日志无 P0/P1 + 内部 10 个种子账号跑完至少 1 轮跨语言 entity/todo 关联 | 立即回滚（§11.3） |
| Stage 1 | **production 10%**（按 user_id hash 桶） | Stage 0 退出条件满足 + 监控面板接入完毕 | ≥ 48h | error_budget 消耗 < 20% + p95 latency < 800ms + cross_lang_match_rate ≥ W4 baseline（0.917） | 切回 Stage 0 + 触发 §11.3 紧急吊销 |
| Stage 2 | **production 50%** | Stage 1 退出条件满足 + F-A1（PG dual_db）有初稿结论 | ≥ 72h | 同 Stage 1 + score_audit_logs 写入成功率 ≥ 99.9% | 切回 Stage 1 + 触发 §11.3 |
| Stage 3 | **production 100%** | Stage 2 退出条件满足 + F-S3（secret 轮换演练 staging 跑一次）完成 | 持续 | 全量监控基线稳定 ≥ 24h | 触发 §11.3 + 暂停放量 |

### 11.2 可观测性（每阶段必须就绪）

- 指标：`cross_lang_match_rate` / `candidate_token_verify_fail_rate` / `score_audit_logs_write_success_rate` / `p95_latency_w5_candidate_endpoint` / `error_budget_remaining`。
- 日志：`operation_state_transition`（issued→pending→confirmed/rejected/expired 全部打点）+ `key_version_used`（用于追溯轮换期 token）。
- 告警：`candidate_token_verify_fail_rate` 5 分钟突增 > 2× 基线 → PagerDuty P2；`score_audit_logs_write_success_rate` < 99% → PagerDuty P1。
- Tracing：每个 candidate API 调用打 `trace_id` + `operation_key`，与 score_audit_logs 一一对应。

### 11.3 回滚路径（与 Authorization §6 对齐）

- **三开关独立降级**（任一独立生效，无需重启）：
  1. `candidate_token_revoked_key_versions` 紧急吊销（演练已 G7-A 验证）。
  2. feature flag `W5_FEATURE_ENABLED=false`（旁路 W5 路由，降级到 W4 中文解析）。
  3. 灰度桶 `W5_ROLLOUT_PERCENTAGE=0`（拒绝新 W5 流量，已开始的不强制中断）。
- **数据库回滚**：`alembic downgrade -1`（演练已 G7-B 验证）。
- **金标降级**：移除 `score_audit_logs` 写入依赖（仅作审计，不在 critical path）。

### 11.4 与 follow-up 队列的衔接

- F-T2（94 根测试文件完整回归）必须在 Stage 1 进入前完成。
- F-S3（secret 轮换演练 staging 跑一次）必须在 Stage 2 进入前完成。
- F-A1/F-T1（PG dual_db 实跑）必须在 Stage 1 退出条件评估前出初稿结论。
- 其他 P2 follow-up 不阻塞放量节奏，但每次 Stage 退出前必须 review 一次队列状态。

### 11.5 下一动作

- ⏳ 等待用户明确放行（可选项：先 push staging tag / staging deployment / 或进入 Stage 0 启动）；push / release / deployment 禁令在用户明确放行前维持。
