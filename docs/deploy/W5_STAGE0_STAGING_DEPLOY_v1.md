# W5 Stage 0 — staging deployment 剧本

> **目的**：在 staging 主机上把 `v1.0-rc1` 启动起来，进入灰度 §11.1 Stage 0 阶段。
> **范围**：本剧本不在本机执行；本机只产出可执行的 staging 部署脚本 + smoke test，由用户在 staging 主机或 CI 触发。
> **退出条件（Stage 0 ≥ 24h）**：staging 日志无 P0/P1 + 内部 10 个种子账号跑完至少 1 轮跨语言 entity/todo 关联。

## 1. 前置条件（staging 主机）

| 项 | 期望 | 验证命令 |
|---|---|---|
| docker | ≥ 24.x | `docker --version` |
| docker compose | v2（`docker compose ...` 不是 `docker-compose`） | `docker compose version` |
| 端口 8000 / 5432 / 6379 未被占用 | free | `ss -ltn 'sport = :8000 or sport = :5432 or sport = :6379'` |
| `.env` 已就位（参考 `.env.example`） | 必填 `POSTGRES_PASSWORD` / `SECRET_KEY` / `CANDIDATE_TOKEN_SECRET_V1` | `cat .env` |
| 已 clone repo | 在 staging work dir | `git rev-parse HEAD` 应等于 `bea0b1f` 或 v1.0-rc1 tag |

## 2. 部署步骤

```bash
# A. 同步代码到 v1.0-rc1
cd /opt/promiselink  # 或 staging work dir
git fetch --tags
git checkout v1.0-rc1
git rev-parse HEAD   # 必须是 v1.0-rc1 的 commit SHA = bea0b1ff62ea230a9b05044727e9ac827ebc07fc

# B. 准备 .env（如果没有）
test -f .env || cp .env.example .env
# 编辑 .env 填入真实 POSTGRES_PASSWORD / SECRET_KEY / CANDIDATE_TOKEN_SECRET_V1
chmod 600 .env

# C. 启动 full stack（app + postgres + redis，绑定 --profile full）
docker compose --profile full up -d --build

# D. 等待健康
docker compose --profile full ps
# promiselink-postgres  status=healthy
# promiselink-redis     status=healthy
# promiselink-api       running（uvicorn 监听 0.0.0.0:8000）

# E. 数据库迁移（容器内执行）
docker compose --profile full exec promiselink \
  bash -lc 'export DATABASE_URL=postgresql+asyncpg://promiselink:$POSTGRES_PASSWORD@postgres:5432/promiselink && alembic upgrade head'
# 期望输出：Running upgrade ... -> w5a_score_audit_logs (head)

# F. 健康检查
curl -sf http://localhost:8000/api/v1/health
# 期望：{"status":"ok",...}
```

## 3. Stage 0 smoke test（10 个种子账号 × 1 轮跨语言关联）

```bash
# 用 staging 的测试种子数据
docker compose --profile full exec promiselink \
  bash -lc 'export DATABASE_URL=postgresql+asyncpg://promiselink:$POSTGRES_PASSWORD@postgres:5432/promiselink && CANDIDATE_TOKEN_SECRET_V1=$CANDIDATE_TOKEN_SECRET_V1 .venv/bin/python scripts/e2e/e2e_w5_real_user.py'
# 期望：14/14 PASS（与 G1 同样的脚本；只是数据库换成 PG）

# 额外跑一次 anti-ghost 与 manifest validator（确保部署后没退化）
docker compose --profile full exec promiselink \
  bash -lc 'CANDIDATE_TOKEN_SECRET_V1=$CANDIDATE_TOKEN_SECRET_V1 .venv/bin/python scripts/quality/check_w5_antighost.py'
docker compose --profile full exec promiselink \
  bash -lc '.venv/bin/python scripts/quality/w5_manifest_validator.py docs/e2e_evidence/w5_e2e/manifest.json'
```

## 4. Stage 0 退出条件 + evidence 回传

满足下列全部条件后即可视为 Stage 0 done，可进入 Stage 1（production 10%）：

| 条件 | 验证命令 | 期望 |
|---|---|---|
| 无 P0/P1 日志 | `docker compose --profile full logs --no-color \| grep -iE 'error\|exception\|p0\|p1' \| head -20` | 无 critical error |
| E2E 14/14 PASS | （脚本见 §3） | PASS=14, FAIL=0 |
| Anti-ghost manifest accepted | （脚本见 §3） | exit=0 |
| cross_lang_match_rate ≥ 0.917 | 待 W5 监控面板就绪 | ≥ W4 baseline |
| p95 latency < 800ms | 监控面板 | < 800ms |

evidence 回传：
- 把 §3 三个脚本的 stdout 贴到 `docs/e2e_evidence/w5_stage0_staging/manifest.json`（schema_version=w5-stage0-v1）
- 把 staging host / commit / 时间戳 落进 tracker §10 末尾

## 5. 回滚路径（Stage 0 内任一步可触发）

| 触发条件 | 动作 |
|---|---|
| E2E 不绿或 P0/P1 日志 | `docker compose --profile full down` 立即停机 + 通知 |
| 监控异常但服务可起 | `W5_FEATURE_ENABLED=false docker compose --profile full up -d` 降级 W4 |
| schema 异常 | `docker compose --profile full exec promiselink bash -lc '... alembic downgrade -1'` 回滚一个 revision |

## 6. 不做的事

- 不进 production（要等 Stage 0 退出条件满足 + 用户再次放行）
- 不改 §3 锁定契约
- 不在 staging host 跑 `git push` / `git tag`（只 `fetch` + `checkout`）