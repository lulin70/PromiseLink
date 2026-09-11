# W5 B-9 四角色第三次复审邀请 + 证据摘要（Implementation Authorization 门禁）

> **版本**: v1.0
> **日期**: 2026-09-11
> **触发**: B-1/B-2/B-3~B-7/B-8 全部 `done`（v1.4 状态总览），push/release/deployment 禁令待四角色 `approved` 才解除。
> **本次复审范围**: W5 跨语言实体关联（PRD v1.2 / Tech Design v1.2 / Test Plan v1.2 / 实施清单 v1.3 / 阻塞项跟踪 v1.4）

## 1. 复审角色与职责

| 角色 | 触发关键词 | 本次重点 |
|---|---|---|
| **Architect** | architecture, design, parity, migration, schema | B-8 migration parity 矩阵架构判断；candidate token 14 字段契约；operation state machine（issued → pending → confirmed/rejected/expired）；HMAC-SHA256 / hex nonce / `compare_digest` 常量时间比较 |
| **Security** | security, HMAC, nonce, replay, audit, PII, privacy | token 安全语义闭环（跨用户/跨事件/跨资源/digest 漂移/TTL/replay/并发 claim CAS）；token 仅存 `token_hash`；PII 三类正则（手机/loose mobile/email）；audit 与 replay 不可逆 |
| **Tester** | test, e2e, recall, mrr, fpr, coverage | B-E2E 14 场景 14/14 PASS；B-1 W4 baseline recall@5=0.917 / mrr@5=0.917 / fpr=0.000 / pii=pass；B-2 anti-ghost 5 control points 真实激活；B-7 19 项 × 3 连跑全绿 |
| **Product-Operations** | PRD, rollout, rollback, gate, deploy | PRD §验收 14 场景；Tech Design §6 阈值与上限；release gates（rollout/rollback/灰度）；evidence manifest 校验（schema v1 / validator v1）；push/release/deployment 禁令维持 |

## 2. 复审邀请 prompt 模板

### 2.1 Architect 复审邀请

```text
你是 PromiseLink W5 跨语言实体关联的架构师复审官。本次为第三次复审（前两次：2026-09-09 / 2026-09-10 产出 P1 阻塞项 B-1~B-9）。

请按以下顺序独立检查：
1) W5-CJ-v1 candidate token 契约冻结（14 字段 / version / key_version / scope_type / digest / resolver / score / embedding_space / issued_at / expires_at / nonce）
2) HMAC-SHA256 签名 + hex nonce + compare_digest 常量时间比较（auth.py）
3) Operation 状态机：issued → pending → confirmed | rejected | expired（w5_operation_service.py）
4) Two-phase correction flow：Phase 1 preflight 零写入 → Phase 2 claim→mutate→audit→complete
5) B-8 迁移矩阵：SQLite round-trip + schema_parity_proxy match=true + alembic head=w5a_score_audit_logs
6) Embedding cache 命名空间：profile_version + provider + model + dimension + embedding_space + user_scope + content digest

证据：
- docs/spec/PRD_跨语言实体关联_W5_v1.md (v1.2)
- docs/design/TECH_DESIGN_跨语言实体关联_W5_v1.md (v1.2)
- docs/design/W5_IMPLEMENTATION_BLOCKERS_TRACKING_v1.md (v1.4)
- docs/design/W5_IMPLEMENTATION_READINESS_CHECKLIST_v1.md
- docs/e2e_evidence/w5_parity/manifest.json (B-8)
- docs/e2e_evidence/w5_e2e/manifest.json (B-E2E)
- docs/evidence/w4_baseline.json (B-1)
- docs/evidence/w5_antighost/manifest.json (B-2)
- commit 1aab59a (HEAD) / 404100e / ab28daa / a92a5f4

复审结论必须为下列其一：
- approved：所有架构决策与契约经得起 P1 阻塞项验证，可进入 Implementation Authorization
- approved_with_notes：原则通过但列出 N 项 follow-up（不得阻塞 release，但需在 release 前完成）
- blocked：列出具体阻塞项（架构层面）

请在 docs/review/W5_B9_REVIEW_architect_v1.md 落盘你的复审意见，附证据指针。
```

### 2.2 Security 复审邀请

```text
你是 PromiseLink W5 跨语言实体关联的安全复审官。本次为第三次复审。

请按以下顺序独立检查：
1) Token 签发：HMAC-SHA256 / key_version 字符串 / hex nonce（避免 base64url 首字符触发假阳性） / SHA-256 token_hash 仅存哈希
2) Token 验证顺序：format → version → key → signature → scope → digest → resolver/score/space → TTL
3) Two-phase preflight 零写入（preflight 失败不修改业务数据；T-W5-15 断言）
4) TTL 失效 410 CANDIDATE_TOKEN_EXPIRED（T-W5-03）
5) Replay 优先：已完成 operation 的 replay 返回 200 + 原 result_summary，不重复 merge/audit（T-W5-10/11/14）
6) 并发 CAS：双 confirm 单事实结果 + 至多一行审计（T-W5-12）
7) 服务端重算候选 + selected ∈ 集合校验（拒绝客户端伪造 candidate IDs / score / method，T-W5-16）
8) PII 三类正则扫描（手机 11 位 / loose mobile / email）— w5_antighost + w5_e2e + w4_evaluator 三处 runner 全部 pass
9) Audit 不可逆：confirm 后 reject 同 token 不得逆转事实
10) secret_key / candidate_token_secret_v1 默认值不得用于生产（allow_insecure_key 默认 False）

证据：
- src/promiselink/core/auth.py (issue_candidate_token / verify_candidate_token / candidate_token_hash)
- src/promiselink/services/w5_operation_service.py (claim_operation CAS / complete_operation 白名单)
- src/promiselink/api/v1/event_pipeline_api.py (Phase 1 preflight → Phase 2 lock→mutate→audit→complete)
- src/promiselink/models/entity_correction.py (operation_key 唯一索引 / scope_xor 约束)
- tests/test_w5_candidate_token_api.py (19 项 × 3 连跑全绿)
- tests/test_security_comprehensive.py / test_text_utils_pii.py

复审结论：
- approved / approved_with_notes / blocked

请在 docs/review/W5_B9_REVIEW_security_v1.md 落盘。
```

### 2.3 Tester 复审邀请

```text
你是 PromiseLink W5 跨语言实体关联的测试复审官。本次为第三次复审。

请按以下顺序独立检查：
1) B-E2E：scripts/e2e/e2e_w5_real_user.py 14 场景 14/14 PASS（E-W5-01~14，schema_version=w5-evidence-v1）
2) B-1：scripts/quality/w4_evaluator.py 16 样本 recall@5=0.917 / mrr@5=0.917 / fpr=0.000 / pii=pass / baseline_commit=真实 HEAD
3) B-2：scripts/quality/check_w5_antighost.py 5 control points 真实激活 + counts.pass=5/5 + pii_scan_result=pass + validator exit=0
4) B-3：tests/w5/test_canonical_json_vectors.py 25 项全绿（14 字段 / version / key_version 契约）
5) B-7：tests/test_w5_candidate_token_api.py 19 项 × 3 次连跑全绿（T-W5-02~16）
6) B-8：scripts/quality/w5_parity_matrix.py SQLite round-trip 3 步全绿 + schema_parity_proxy.match=true + 11 表双侧对齐
7) Manifest schema v1 校验：w5_antighost / w5_e2e 三处均经 w5_manifest_validator 校验 exit=0
8) Anti-Ghost 防线：runner exit 5 是 fail-closed 门禁；任何 required control point 未激活即拒绝出 manifest

证据：
- docs/e2e_evidence/w5_e2e/manifest.json (B-E2E, 14/14)
- docs/e2e_evidence/w5_parity/manifest.json (B-8)
- docs/e2e_evidence/w4_baseline/per_sample_report.json (B-1)
- docs/evidence/w4_baseline.json (B-1)
- docs/evidence/w5_antighost/manifest.json (B-2)
- tests/w5/test_canonical_json_vectors.py / tests/w5/test_candidate_token_api.py
- docs/design/TEST_PLAN_跨语言实体关联_W5_v1.md (§13 14 场景 / §16.2 / §16.3 / §14 dual_db)

复审结论：
- approved / approved_with_notes / blocked

请在 docs/review/W5_B9_REVIEW_test_v1.md 落盘。
```

### 2.4 Product-Operations 复审邀请

```text
你是 PromiseLink W5 跨语言实体关联的产品-运营复审官。本次为第三次复审。

请按以下顺序独立检查：
1) PRD v1.2 §验收 14 场景与 E-W5-01~14 映射一致；用户故事、边界条件、跨语言实体/待办关联语义与 PRD 一致
2) Tech Design v1.2 §6 阈值与上限：
   - cross_language_embedding_min_score=0.78 / confirm_score=0.86 / todo_confirm_score=0.88
   - cross_language_embedding_candidate_limit=100 / timeout_ms=500
   - cross_language_rejection_cooldown_days=30
   - candidate_token_ttl_seconds=600 / max_ttl_seconds=600
3) Release gates：
   - 灰度比例由 cross_language_rollout_percent 控制（0~100），E2E 默认 100
   - cross_language_llm_fallback_enabled 默认 False（生产默认关闭 LLM 降级）
   - 推/拉门禁：cross_language_enabled + cross_language_todo_enabled + cross_language_embedding_enabled 三开关均须显式开启
4) Evidence manifest 校验（schema v1 / validator v1）覆盖所有 release-evidence（antighost + e2e + parity + baseline）
5) push / release / deployment 禁令：在四角色全部 approved 前不得执行；当前 B-9 进行中
6) Rollback 路径：cross_language_* 三开关 + candidate_token_revoked_key_versions（紧急吊销）

证据：
- docs/spec/PRD_跨语言实体关联_W5_v1.md
- docs/design/TECH_DESIGN_跨语言实体关联_W5_v1.md
- src/promiselink/config.py (cross_language_* / candidate_token_* 配置项)
- docs/design/Deployment_Guide.md (rollback 章节)
- docs/design/W5_EVIDENCE_MANIFEST_SCHEMA_v1.json (schema v1 冻结)
- scripts/quality/w5_manifest_validator.py (validator v1)

复审结论：
- approved / approved_with_notes / blocked

请在 docs/review/W5_B9_REVIEW_product_ops_v1.md 落盘。
```

## 3. 复审结论汇总矩阵

| 角色 | 邀请日期 | 复审文件 | 结论 | 决议日期 |
|---|---|---|---|---|
| Architect | 2026-09-11 | [W5_B9_REVIEW_architect_v1.md](file:///Users/lin/trae_projects/PromiseLink/docs/review/W5_B9_REVIEW_architect_v1.md) | **approved** | 2026-09-11 |
| Security | 2026-09-11 | [W5_B9_REVIEW_security_v1.md](file:///Users/lin/trae_projects/PromiseLink/docs/review/W5_B9_REVIEW_security_v1.md) | **approved** | 2026-09-11 |
| Tester | 2026-09-11 | [W5_B9_REVIEW_test_v1.md](file:///Users/lin/trae_projects/PromiseLink/docs/review/W5_B9_REVIEW_test_v1.md) | **approved** | 2026-09-11 |
| Product-Operations | 2026-09-11 | [W5_B9_REVIEW_product_ops_v1.md](file:///Users/lin/trae_projects/PromiseLink/docs/review/W5_B9_REVIEW_product_ops_v1.md) | **approved** | 2026-09-11 |

> **Implementation Authorization 门禁状态：✅ 全部通过**。四角色全部 `approved`，可进入 Implementation Authorization 签发 + release gates。

## 4. 当前真实证据摘要（用于复审参考）

### 4.1 commits（HEAD → 父）

| Commit | 内容 | 状态 |
|---|---|---|
| 1aab59a | w5(b-8): dual_db migration parity matrix | 本轮 |
| 404100e | w5(b-1): W4 baseline 真实化 | 前轮 |
| ab28daa | w5(e2e): real-user 14/14 PASS + manifest validator exit=0 | 前轮 |
| a92a5f4 | feat(w5): B-2 anti-ghost real runner + activation counter hooks | 前轮 |
| 9c2bddb | docs(spec): W5 PRD v1.2 review revisions + roadmap/plan index sync | 前轮 |

### 4.2 真实证据（命令 / 产物 / 结果）

| 阻塞项 | 命令 / 产物 | 结果 |
|---|---|---|
| B-E2E | `.venv/bin/python scripts/e2e/e2e_w5_real_user.py` | `PASS=14 FAIL=0 SKIP=0` |
| B-1 | `.venv/bin/python scripts/quality/w4_evaluator.py` | `recall@5=0.917 mrr@5=0.917 fpr=0.000 pii=pass` |
| B-2 | `.venv/bin/python scripts/quality/check_w5_antighost.py --ci --strict-markers` | `counts.pass=5/5 validator exit=0` |
| B-3 | `pytest tests/w5/test_canonical_json_vectors.py -q` | `25 passed` |
| B-7 | `pytest tests/test_w5_candidate_token_api.py -q` | `19 passed × 3 连跑全绿` |
| B-8 | `.venv/bin/python scripts/quality/w5_parity_matrix.py` | `EXIT=0 matrix 3 步全绿 parity.match=true` |

### 4.3 交付物清单（与 PRD v1.2 §验收 对齐）

- `docs/spec/PRD_跨语言实体关联_W5_v1.md` v1.2
- `docs/design/TECH_DESIGN_跨语言实体关联_W5_v1.md` v1.2
- `docs/design/TEST_PLAN_跨语言实体关联_W5_v1.md` v1.2
- `docs/design/W5_EVIDENCE_MANIFEST_SCHEMA_v1.json` schema v1
- `docs/design/W5_IMPLEMENTATION_READINESS_CHECKLIST_v1.md` v1.3
- `docs/design/W5_IMPLEMENTATION_BLOCKERS_TRACKING_v1.md` v1.4（B-1/B-2/B-3~B-7/B-8 done；B-9 pending）
- `docs/evidence/w5_antighost/manifest.json`（B-2，schema=w5-evidence-v1）
- `docs/evidence/w4_baseline.json`（B-1，schema=w4-baseline-v1）
- `docs/e2e_evidence/w5_e2e/manifest.json`（B-E2E，schema=w5-evidence-v1）
- `docs/e2e_evidence/w5_parity/manifest.json`（B-8，schema=w5-parity-v1）
- `docs/e2e_evidence/w4_baseline/per_sample_report.json`（B-1）
- `tests/w5/fixtures/golden/w5_golden_v1.jsonl`（16 样本）
- `data/e2e_w5_synonyms.json`（E2E/w4 共享同义词覆盖）

## 5. push / release / deployment 禁令维持

B-9 四角色第三次复审未完成前，禁止以下操作：

- ❌ 推送分支（`git push`）
- ❌ 创建 release tag
- ❌ 部署到 staging / production
- ❌ 修改 W5 冻结契约（PRD v1.2 / Tech Design v1.2 / Test Plan v1.2 / Manifest Schema v1）

## 6. 下一步（复审完成后）

- 全部 `approved`（含 `approved_with_notes` notes 完成）→ 进入 Implementation Authorization 签发 → release gates（灰度 rollout / rollback 演练）
- 任一 `blocked` → 在该角色复审文件中标记阻塞项，由对应 P 阻塞位维护（B-9 进入条件 §3 列表）