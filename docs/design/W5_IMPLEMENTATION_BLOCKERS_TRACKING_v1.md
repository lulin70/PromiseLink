# W5 实施阶段阻塞项跟踪（B-1 ~ B-9）

> **版本**: v1.0
> **日期**: 2026-09-10
> **依据**: 四角色第二次独立复审产出的 P1 阻塞项清单（2026-09-09/10 会话）
> **原则**: 每项必须附真实证据（命令 + 输出 + 测试名）；`pending` 项不得在证据缺失时标为 `done`（Anti-ghost）。
> **状态图例**: `done` 完成并有证据 / `partial` 部分完成（列明剩余） / `pending` 未开始 / `n/a` 不适用

## 1. 阻塞项总览

| # | 阻塞项 | 状态 | 证据（测试 / 命令 / 文件） |
|---|---|---|---|
| B-1 | W4 baseline 缺失（不得伪造，由 W4 evaluator 真实运行产生） | pending | `docs/evidence/README.md` 已如实记录不可用事实 |
| B-2 | Anti-ghost 校验真实化 | pending | `scripts/quality/check_w5_antighost.py` 仍为 honest pending 输出 |
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
