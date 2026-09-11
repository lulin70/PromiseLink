# W5 Security 第三次复审意见（Implementation Authorization 输入）

> **角色**: Security
> **日期**: 2026-09-11
> **邀请函**: docs/design/W5_B9_REVIEW_INVITATION_v1.md §2.2
> **证据基线**: commit 1aab59a (HEAD) / W5_IMPLEMENTATION_BLOCKERS_TRACKING_v1.md v1.4

## A. 安全语义闭环（10 项）

| # | 项 | 现状 | 评价 |
|---|---|---|---|
| 1 | HMAC-SHA256 / key_version / hex nonce / SHA-256 token_hash | `auth.py` `issue_candidate_token` / `verify_candidate_token` / `candidate_token_hash`；hex nonce 首字符恒为数字 | ✅ |
| 2 | 验证顺序：format → version → key → signature → scope → digest → resolver/score/space → TTL | `auth.py` `verify_candidate_token`；T-W5-02~16 19 项 × 3 连跑全绿 | ✅ |
| 3 | Two-phase preflight 零写入 | `event_pipeline_api.py` `correct_event` Phase 1 全量 preflight；T-W5-15 断言行数不变 | ✅ |
| 4 | TTL 失效 410 | T-W5-03 `now=past` 触发 `CANDIDATE_TOKEN_EXPIRED` HTTP 410 | ✅ |
| 5 | Replay 优先 | `verify_candidate_token` `allow_expired_for_replay=True` 路径返回原 result_summary；T-W5-10/11/14 | ✅ |
| 6 | 并发 CAS 双 confirm 单事实 | `claim_operation` rowcount==1 CAS + per-user lock；T-W5-12 至多一行审计 | ✅ |
| 7 | 服务端重算 + selected ∈ 集合 | `generate_*_candidates` 服务端 synonym/difflib；T-W5-16 + `test_selected_outside_candidate_set_rejected` | ✅ |
| 8 | PII 三类正则扫描（手机 11 位 / loose mobile / email） | `w5_antighost` + `w5_e2e` + `w4_evaluator` 三处 runner 全部 pii_scan_result=pass | ✅ |
| 9 | Audit 不可逆 | `complete_operation` 白名单 result_summary；confirm 后 reject 同 token 不得逆转 | ✅ |
| 10 | secret_key 默认值不得用于生产 | `allow_insecure_key: bool = False`（默认 False）；candidate_token_secret_v1 默认空 | ✅ |

## B. 隐私 / 合规判断

- **PII 加密**：`pii_encryption_key` 独立配置；空时回退到 `secret_key`（最小依赖）。✅
- **token 不可逆**：仅存 `token_hash = SHA-256(token)`，HMAC secret 永不入库。✅
- **TTL 严格上限**：`candidate_token_ttl_seconds=600` / `max_ttl_seconds=600`（不允许放宽）。✅
- **跨用户/跨事件/跨资源验证**：token envelope 含 user_id / event_id / scope_type；任一不匹配 → HTTP 400 `CANDIDATE_TOKEN_INVALID`，零写入。✅
- **重放窗口**：replay 优先级高于 TTL，但仅限已完成 operation；issued/pending 状态不接受 replay。✅
- **吊销机制**：`candidate_token_revoked_key_versions` 支持 key 轮换时的紧急吊销。✅
- **LLM fallback 默认关闭**：`cross_language_llm_fallback_enabled: bool = False`，避免在主路径异常时引入非确定性。✅

## C. 已知 follow-up（不阻塞 release）

- F-S1：与第三方 LLM 交互时的 audit log 完整化（当前 LLM 默认未启用，但若启用需在 ops 文档中固化 LLM 输入/输出留存策略）。
- F-S2：`alembic_version` 历史行（W3 legacy rows）在 PG NOT VALID 约束兼容性验证（与 CI dual_db 落地同源）。
- F-S3：secret 轮换演练（`candidate_token_revoked_key_versions`）需要在 staging 跑一次。

## D. Security 结论

**approved**

理由：10 项安全语义闭环全部验证；三类隐私/合规判断（不可逆 / 严格 TTL / 默认保守）与 PRD §验收 §9 / Tech Design §6 一致；3 项 follow-up 列入 release 前 follow-up 队列（与 release gates 同步执行），不阻塞 Implementation Authorization。

进入 Implementation Authorization 等待 Architect（✅ approved）/ Tester / Product-Operations 三角色结论。

---
**Security 签名**: role=security, mock_mode=true, scratchpad=W5_B9_SEC_2026-09-11