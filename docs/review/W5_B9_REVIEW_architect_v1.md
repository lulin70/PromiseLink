# W5 Architect 第三次复审意见（Implementation Authorization 输入）

> **角色**: Architect
> **日期**: 2026-09-11
> **邀请函**: docs/design/W5_B9_REVIEW_INVITATION_v1.md §2.1
> **证据基线**: commit 1aab59a (HEAD) / W5_IMPLEMENTATION_BLOCKERS_TRACKING_v1.md v1.4

## A. 契约冻结复审

| 契约点 | 现状 | 评价 |
|---|---|---|
| W5-CJ-v1 candidate token 14 字段 | `src/promiselink/core/auth.py` `W5_CANDIDATE_TOKEN_FIELDS` 单一来源；25 canonical JSON vector 测试全绿 | ✅ 与 Tech Design §3.1 一致 |
| HMAC-SHA256 + hex nonce + `compare_digest` | `issue_candidate_token` / `verify_candidate_token`；nonce hex 保证首字符恒为数字（消除 base64url 假阳性 flake） | ✅ 与 Tech Design §3.2 一致 |
| Operation 状态机 issued → pending → confirmed/rejected/expired | `w5_operation_service.py` `claim_operation` CAS（issued→pending）+ `complete_operation` 白名单 result_summary | ✅ 与 Tech Design §4.2 一致 |
| Two-phase correction | Phase 1 preflight 零写入 → Phase 2 lock→mutate→audit→complete | ✅ 与 PRD §验收 §7 一致 |
| Embedding cache namespace | profile_version + provider + model + dimension + embedding_space + user_scope + content digest | ✅ 与 Tech Design §6.3 一致；`B-2 anti-ghost` 已实证激活 |
| Migration parity | SQLite upgrade→downgrade→upgrade round-trip 3 步全绿 + schema_parity_proxy 11 表双侧列计数对齐 | ✅ 与 Test Plan §14 dual_db 一致；PG 实库矩阵保留给 CI dual_db service |

## B. 架构决策判断

1. **token 不可逆语义**：已完成 operation 的 replay 走 `allow_expired_for_replay` + `verify_candidate_token` 优先于 TTL，且服务端的 token_hash 是 SHA-256 不可逆。✅ 已闭环。
2. **operation_key 唯一索引**：解决 legacy 行唯一索引冲突（`models/entity_correction.py` migration w5_entity_correction_double_scope）。✅ 与 PRD §验收 §10 一致。
3. **scope_xor 约束**：entity/todo 严格互斥；promise/association 豁免；todo issued/rejected 允许 selected_todo_id 为空。✅ 与 Tech Design §4.3 一致。
4. **score_audit_logs 补迁移**：`w5a_score_audit_logs` 已补齐 create_all 与迁移路径的 parity 缺口。✅ 与 Test Plan §16.3 schema 强制一致。
5. **B-8 迁移矩阵**：本地 SQLite 11 表双侧对齐；PG 留 CI dual_db（manifest 已诚实标注 `backend_remote_unavailable=[postgresql]`）。✅ 反幻觉防线已立。

## C. 已知 follow-up（不阻塞 release）

- F-A1：PG 实库 `alembic check` 验证待 CI dual_db service 落地（CI 服务已规划，B-9 进入条件 §3 列）。
- F-A2：`alembic_version` 双侧过滤需在 CI dual_db PG 端二次验证（与 F-A1 同源）。
- F-A3：cross_language_* 三开关的灰度 rollout playbook 需在 PRD 配套 ops 文档中固化（与 release gates 一同发布）。

## D. Architect 结论

**approved**

理由：六项契约冻结点全部对齐；四类架构决策（token 不可逆 / operation_key 唯一索引 / scope_xor / parity 矩阵）证据齐全；三项 follow-up 列入 release 前 follow-up 队列，不阻塞本次 Implementation Authorization。

进入 Implementation Authorization 等待 Security / Tester / Product-Operations 三角色结论。

---
**Architect 签名**: role=architect, mock_mode=true, scratchpad=W5_B9_ARCH_2026-09-11