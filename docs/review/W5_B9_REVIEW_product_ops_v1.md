# W5 Product-Operations 第三次复审意见（Implementation Authorization 输入）

> **角色**: Product-Operations
> **日期**: 2026-09-11
> **邀请函**: docs/design/W5_B9_REVIEW_INVITATION_v1.md §2.4
> **证据基线**: commit 1aab59a (HEAD) / W5_IMPLEMENTATION_BLOCKERS_TRACKING_v1.md v1.4

## A. PRD / Tech Design 一致性

| 维度 | PRD v1.2 | Tech Design v1.2 | 实施状态 |
|---|---|---|---|
| 用户故事（跨语言实体/待办关联） | §1 4 角色 × 4 场景 | §3 14 字段契约 | ✅ B-E2E 14/14 |
| 验收 14 场景 | §验收 §1-§14 | §6 阈值 | ✅ B-E2E E-W5-01~14 |
| 阈值：min_score=0.78 / confirm=0.86 / todo_confirm=0.88 | PRD §性能预算 | Tech Design §6.3 | ✅ `config.py` 全部对齐 |
| TTL：candidate_token_ttl=600s / max_ttl=600s | PRD §验收 §8 | Tech Design §3.4 | ✅ |
| 候选上限：candidate_limit=100 / timeout=500ms | PRD §性能预算 | Tech Design §6.3 | ✅ |
| 冷却：rejection_cooldown_days=30 | PRD §验收 §10 | Tech Design §6.3 | ✅ |
| 状态机：issued/pending/confirmed/rejected/expired | PRD §验收 §7 | Tech Design §4.2 | ✅ T-W5-02~16 |
| Embedding namespace 7 字段 | PRD §技术约束 | Tech Design §6.3 | ✅ B-2 anti-ghost |

## B. 灰度 rollout / rollback gates

1. **三开关显式控制**：`cross_language_enabled` / `cross_language_todo_enabled` / `cross_language_embedding_enabled`（生产默认全 False，避免误开）。✅
2. **灰度比例**：`cross_language_rollout_percent`（0~100），E2E 默认 100（全量黑盒验证）。✅
3. **LLM fallback 默认关闭**：`cross_language_llm_fallback_enabled: bool = False`（主路径异常时不引入非确定性）。✅
4. **紧急吊销**：`candidate_token_revoked_key_versions` 支持 key 轮换时吊销旧 key。✅
5. **Rollback 路径**：三开关可独立降级（关 todo / 关 embedding / 整体关）；旧 key 吊销不影响历史 operation 的 replay（operation 状态机独立）。✅
6. **Evidence manifest 校验**：`w5-evidence-v1` schema + `w5-manifest-validator-v1` 三处（antighost / e2e / parity）校验 exit=0。✅

## C. push / release / deployment 禁令维持

B-9 进行中（Architect ✅ approved / Security ✅ approved / Tester ✅ approved / Product-Operations ✅ approved — **见下结论**），本角色确认禁令维持：

- ❌ 推送分支（`git push`）
- ❌ 创建 release tag
- ❌ 部署到 staging / production
- ❌ 修改 W5 冻结契约（PRD v1.2 / Tech Design v1.2 / Test Plan v1.2 / Manifest Schema v1）

四角色全部 `approved` 后进入 Implementation Authorization 签发 → release gates（灰度 rollout / rollback 演练）。

## D. 已知 follow-up（不阻塞 release）

- F-P1：灰度 playbook 文档化（PRD 配套 ops 章节）— 与 release gates 一同发布。
- F-P2：secret 轮换演练（`candidate_token_revoked_key_versions`）在 staging 跑一次 — 与 F-S3 同源。
- F-P3：UI 端 W5 录入页 E2E（Playwright）覆盖 — 与 F-T3 同源。

## E. Product-Operations 结论

**approved**

理由：八项 PRD / Tech Design 一致性维度全部对齐；六项灰度 rollout / rollback gates 全部就位；本角色确认 push / release / deployment 禁令在四角色全部 `approved` 后解除；三项 follow-up 列入 release 前 follow-up 队列，与 F-A/F-S/F-T 协同执行。

进入 Implementation Authorization 等待最终签发。

---
**Product-Operations 签名**: role=product_ops, mock_mode=true, scratchpad=W5_B9_PO_2026-09-11