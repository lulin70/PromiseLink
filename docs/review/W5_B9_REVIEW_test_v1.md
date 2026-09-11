# W5 Tester 第三次复审意见（Implementation Authorization 输入）

> **角色**: Tester
> **日期**: 2026-09-11
> **邀请函**: docs/design/W5_B9_REVIEW_INVITATION_v1.md §2.3
> **证据基线**: commit 1aab59a (HEAD) / W5_IMPLEMENTATION_BLOCKERS_TRACKING_v1.md v1.4

## A. 关键证据复审

| 阻塞项 | runner / 测试 | 命令 / 产物 | 结果 | 评价 |
|---|---|---|---|---|
| B-E2E | `scripts/e2e/e2e_w5_real_user.py` | `python scripts/e2e/e2e_w5_real_user.py` | `PASS=14 FAIL=0 SKIP=0` + manifest 落盘 + validator exit=0 | ✅ 14 场景 14/14 |
| B-1 | `scripts/quality/w4_evaluator.py` | `python scripts/quality/w4_evaluator.py` | `recall@5=0.917 mrr@5=0.917 fpr=0.000 pii=pass`；baseline_commit=真实 git HEAD | ✅ 16 样本 |
| B-2 | `scripts/quality/check_w5_antighost.py` | `python scripts/quality/check_w5_antighost.py --ci --strict-markers` | `counts.pass=5/5` + `_diagnostic.missing_required_points=[]` + validator exit=0 | ✅ 5 control points 真实激活 |
| B-3 | `tests/w5/test_canonical_json_vectors.py` | `pytest tests/w5/test_canonical_json_vectors.py -q` | `25 passed` | ✅ 14 字段 / version / key_version |
| B-7 | `tests/test_w5_candidate_token_api.py` | `pytest tests/test_w5_candidate_token_api.py -q` | `19 passed × 3 次连跑全绿`（T-W5-02~16） | ✅ Two-phase + replay + TTL + CAS |
| B-8 | `scripts/quality/w5_parity_matrix.py` | `python scripts/quality/w5_parity_matrix.py` | `EXIT=0`；matrix 3 步全绿 + `schema_parity_proxy.match=true` | ✅ SQLite round-trip + 11 表双侧对齐 |

## B. 测试维度判断

1. **真实化（Anti-ghost）**：B-2 anti-ghost runner 与 production code 用同一函数路径（5 个 hook 全部包裹 try/except 防副作用）；counter snapshot 在独立 session 内 reset，不污染 production。✅
2. **黑盒真实用户**：B-E2E 14 场景用 `httpx.AsyncClient + ASGITransport + 独立 SQLite + dependency_overrides`；禁用 `process_event_background` 后台流水线。✅
3. **baseline 真实可追溯**：B-1 `baseline_commit` 来自 `git rev-parse HEAD`（40-hex 真实 SHA），与 git log --oneline 一致。✅
4. **schema parity 双侧对齐**：B-8 `migrated` vs `base_create_all` 11 表双侧列计数完全一致；`alembic_version` 在双侧一致过滤。✅
5. **PII 防御**：PII 三类正则（手机 11 位 / loose mobile / email）在 `w5_antighost` + `w5_e2e` + `w4_evaluator` 三处 runner 全部 pass，零漏报。✅
6. **Manifest schema v1 校验**：`w5_antighost` + `w5_e2e` + `w5_parity` 三处均经 `w5_manifest_validator` 校验 exit=0。✅
7. **测试铁律**（weiransoft v2.8.4）：
   - 无 status-code-only 反模式（每个测试断言 ≥ 2 个维度）
   - 无 hard-coded sleep（pipeline 通过状态机主动等待）
   - 无 shared mutable state（每个场景独立 SQLite + Base.metadata.create_all）

## C. 已知 follow-up（不阻塞 release）

- F-T1：PG dual_db service 落地后追加实跑矩阵（与 F-A1 同源）。
- F-T2：与 W3/W4 既有回归（94 个根测试文件）集成跑一次完整 suite 在 commit 1aab59a HEAD 上（验证 B-7/B-8 改动无回归）。
- F-T3：UI 端 W5 录入页 E2E（Playwright）覆盖（与 F-P3 同源）。

## D. Tester 结论

**approved**

理由：六项关键证据（B-E2E / B-1 / B-2 / B-3 / B-7 / B-8）全部 PASS 且与 PRD §验收 / Test Plan §13-§16 完全对齐；三项 follow-up 列入 release 前 follow-up 队列，不阻塞 Implementation Authorization。

进入 Implementation Authorization 等待 Architect（✅ approved）/ Security（✅ approved）/ Product-Operations 三角色结论。

---
**Tester 签名**: role=tester, mock_mode=true, scratchpad=W5_B9_TEST_2026-09-11