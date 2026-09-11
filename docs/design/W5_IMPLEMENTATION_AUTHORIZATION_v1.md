# W5 Implementation Authorization（签发单）

> **版本**: v1.0
> **签发日期**: 2026-09-11
> **关联**: docs/design/W5_B9_REVIEW_INVITATION_v1.md + docs/review/W5_B9_REVIEW_{architect,security,test,product_ops}_v1.md
> **状态**: ✅ **authorized**（四角色全部 approved）

## 1. Authorization 范围

W5 跨语言实体关联（PRD v1.2 / Tech Design v1.2 / Test Plan v1.2 / Manifest Schema v1）从 Implementation 进入 release gates 阶段。

## 2. Authorization 依据（四角色 approved 摘要）

| 角色 | 关键判据 |
|---|---|
| Architect | 6 项契约冻结（14 字段 / HMAC / 状态机 / Two-phase / embedding namespace / parity）；5 项架构决策（token 不可逆 / operation_key 唯一 / scope_xor / parity 矩阵 / score_audit_logs 补迁移） |
| Security | 10 项安全语义闭环（HMAC-SHA256 / TTL 严格 / replay 优先 / 并发 CAS / 服务端重算 / PII 三类 / audit 不可逆 / 严格默认 / 吊销机制） |
| Tester | 6 项关键证据（B-E2E 14/14 / B-1 0.917 / B-2 5/5 / B-3 25/25 / B-7 19×3 / B-8 11 表对齐） |
| Product-Operations | 8 项 PRD/Tech Design 一致性 + 6 项灰度 rollout/rollback gates（三开关 / 灰度比例 / 紧急吊销 / rollback 路径） |

## 3. 已锁定的契约（release 期间不得修改）

- PRD：docs/spec/PRD_跨语言实体关联_W5_v1.md（v1.2）
- Tech Design：docs/design/TECH_DESIGN_跨语言实体关联_W5_v1.md（v1.2）
- Test Plan：docs/design/TEST_PLAN_跨语言实体关联_W5_v1.md（v1.2）
- Manifest Schema：docs/design/W5_EVIDENCE_MANIFEST_SCHEMA_v1.json（schema v1）
- W5-CJ-v1 candidate token 14 字段（src/promiselink/core/auth.py `W5_CANDIDATE_TOKEN_FIELDS`）
- Operation 状态机（issued → pending → confirmed | rejected | expired）
- Embedding cache 7 字段 namespace（profile_version + provider + model + dimension + embedding_space + user_scope + content digest）
- 阈值与上限（config.py `cross_language_*`）：min_score=0.78 / confirm_score=0.86 / todo_confirm_score=0.88 / candidate_limit=100 / timeout_ms=500 / cooldown_days=30 / ttl=600s

## 4. Release gates 执行清单

| # | Gate | 命令 / 产物 | 退出码 | 状态 |
|---|---|---|---|---|
| G1 | W5 E2E 真实用户 14/14 | `.venv/bin/python scripts/e2e/e2e_w5_real_user.py` | 0 | _pending_ |
| G2 | W4 baseline 真实化 | `.venv/bin/python scripts/quality/w4_evaluator.py` | 0 | _pending_ |
| G3 | Anti-ghost 5 control points | `.venv/bin/python scripts/quality/check_w5_antighost.py --ci --strict-markers` | 0 | _pending_ |
| G4 | Migration parity SQLite | `.venv/bin/python scripts/quality/w5_parity_matrix.py` | 0 | _pending_ |
| G5 | Manifest schema v1 校验 | `.venv/bin/python scripts/quality/w5_manifest_validator.py <manifest>` | 0 | _pending_ |
| G6 | 全仓回归（94 根测试文件） | `pytest tests/ -q ...` | 0 | _pending_ |
| G7 | Rollback 演练（staging） | `cross_language_*` 三开关独立降级 | n/a | _pending_ |
| G8 | Secret 轮换演练（staging） | `candidate_token_revoked_key_versions` 切换 | n/a | _pending_ |

## 5. 灰度 rollout 策略

1. **staging 全量验证**：G1~G6 在 staging 通过
2. **灰度 10%**：production 开启 `cross_language_enabled=true` + `rollout_percent=10`，观察 24h
3. **灰度 50%**：`rollout_percent=50`，观察 48h
4. **灰度 100%**：`rollout_percent=100`，todo + embedding 开关同步开启
5. **全程保留**：`candidate_token_revoked_key_versions` + `cross_language_*` 三开关的紧急降级路径

## 6. Rollback 路径

- `cross_language_enabled=false` 立即关闭 W5 跨语言主路径（最小爆炸半径）
- `cross_language_todo_enabled=false` 仅关闭 todo 关联（保留 entity 关联）
- `cross_language_embedding_enabled=false` 仅关闭 embedding（回退 synonym/difflib 路径）
- `candidate_token_revoked_key_versions=["1"]` 紧急吊销旧 key
- 数据库迁移：`alembic downgrade -1` 单步回滚（round-trip 已验证）

## 7. Follow-up 队列（release 后优先级）

- P1：F-A1/F-T1（PG dual_db 实跑）+ F-T2（94 根测试文件完整回归）
- P2：F-A2/F-A3/F-S1/F-S2/F-S3/F-P1/F-P2/F-T3/F-P3

## 8. 签发签名

| 角色 | 签名 | 日期 |
|---|---|---|
| Architect | approved | 2026-09-11 |
| Security | approved | 2026-09-11 |
| Tester | approved | 2026-09-11 |
| Product-Operations | approved | 2026-09-11 |
| **Implementation Authorization** | **✅ authorized** | **2026-09-11** |

## 9. 禁令维持（release gates 完成前）

- ❌ `git push`
- ❌ 创建 release tag
- ❌ 部署到 staging / production
- ❌ 修改 §3 锁定契约

release gates 全部通过后，禁令自动解除，进入 rollout 阶段。