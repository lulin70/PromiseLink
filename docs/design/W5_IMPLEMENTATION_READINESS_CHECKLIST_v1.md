# W5 实现准入就绪检查表（Pre-Implementation Readiness Checklist）

> **版本**: v1.0
> **日期**: 2026-09-09
> **依据**: Test Plan v1.2 §2.1、§4.3、§16.1；DevSquad 四角色复审结论（架构师/安全/测试/产品运维均 approved）
> **目的**: 把 3 项已下沉的前置项与 W5 准入前的所有必做动作固化为可校验条目；任一项未完成，Implementation 保持 blocked。

## 0. 适用与约束

- 本清单覆盖进入 Implementation 阶段之前的全部准备工作，**不含生产代码、空测试文件或 skip/xfail 占位**。
- 每项需提供证据文件路径与完成日期；未达 `done` 状态不得签署 Implementation Authorization。
- 四角色对清单的最终复核与 [Test Plan v1.2 §2.2 复核签署表](file:///Users/lin/trae_projects/PromiseLink/docs/design/TEST_PLAN_跨语言实体关联_W5_v1.md) 的 approved 状态绑定。

## 1. 已通过项（DevSquad 复核闭环）

| # | 项 | 证据 | 状态 |
|---|---|---|---|
| 1.1 | PRD v1.2 文档闭环 | `docs/spec/PRD_跨语言实体关联_W5_v1.md` | done |
| 1.2 | Tech Design v1.2 文档闭环 | `docs/design/TECH_DESIGN_跨语言实体关联_W5_v1.md` | done |
| 1.3 | Test Plan v1.2 文档闭环 | `docs/design/TEST_PLAN_跨语言实体关联_W5_v1.md` | done |
| 1.4 | 架构师独立签署 | 复审纪要（pending 文档） | done |
| 1.5 | 安全专家独立签署 | 复审纪要（pending 文档） | done |
| 1.6 | 测试专家独立签署 | 复审纪要（pending 文档） | done |
| 1.7 | 产品/运维独立签署 | 复审纪要（pending 文档） | done |
| 1.8 | W5-CJ-v1 固定字段顺序与 envelope 一致性 | PRD §4.2.4 / Tech Design §3.1 / Test Plan §7 | done |
| 1.9 | HTTP 400 vs HTTP 410 区分与 replay 优先语义 | 三份文档一致 | done |

## 2. 前置项落地（2026-09-09 本轮补齐）

| # | 项 | 修改位置 | 状态 |
|---|---|---|---|
| 2.1 | 解析 pipeline 全链 p95 预算：中文 <1200ms / 跨语言 <1500ms | Tech Design §12.1 / Test Plan §15 | done |
| 2.2 | `result_summary` 最小白名单实例：`{"candidate_rank":int,"method":str,"score":float,"language_pair":"xx_yy"}` | Test Plan §7.1 / §16.2 | done |
| 2.3 | 准入测试改造基线（conftest + pyproject） | 本文件 §3 | todo（实施准入阶段首项） |

## 3. 准入测试改造基线（实施准入首项必做，不写生产代码）

### 3.1 `tests/conftest.py`

**当前问题**：

- L11–L12：模块加载即强制 `DATABASE_URL=sqlite://`，会覆盖 CI 服务环境变量。
- L40–L43：`PRAGMA foreign_keys=OFF`，与 Test Plan §4.3 矛盾。
- L46–L47：`Base.metadata.create_all`，与 Test Plan §4.3"真实 alembic migration"矛盾。

**改造目标**（实现准入阶段必须完成）：

| 子项 | 目标 | 验收 |
|---|---|---|
| 3.1.1 | 移除 `os.environ["DATABASE_URL"] = "sqlite://"` 全局覆盖；保留可选 `TEST_MODE=true` 作为离线标识 | PostgreSQL CI service 不再被静默替换为 SQLite |
| 3.1.2 | `db_session` fixture 改为参数化 `db_backend`（`sqlite`/`postgresql`），按 `pytest -m dual_db` 显式选择 | 不在同进程动态切换 backend |
| 3.1.3 | SQLite fixture 连接建立时执行 `PRAGMA foreign_keys=ON`，并在测试内断言 pragma 生效 | 通过 `PRAGMA foreign_keys;` 查询返回 1 |
| 3.1.4 | 双 backend 均先执行 `alembic upgrade head` 再创建 session；禁止 `create_all` 替代 migration | manifest 落 `migration_head` |
| 3.1.5 | PostgreSQL fixture 连接串来自环境变量，敏感字段（密码/host）脱敏后写入 manifest | manifest validator 通过 PII 扫描 |

### 3.2 `pyproject.toml`

**当前问题**：

- L101：`addopts` 含 `--continue-on-collection-errors`，违反 Test Plan §2.1.6 / §16.1。
- L102–L104：仅注册 `slow` 一个 marker，缺 W5 markers 与 `--strict-markers`。

**改造目标**：

| 子项 | 目标 | 验收 |
|---|---|---|
| 3.2.1 | 移除 `--continue-on-collection-errors`；保留 coverage 参数 | collection error 直接非零退出 |
| 3.2.2 | 注册 W5 markers：`unit`/`security`/`integration`/`dual_db`/`performance`/`e2e`/`antighost` | `pytest --strict-markers` 通过 |
| 3.2.3 | W5 CI job（`w5-contract-unit`、`w5-integration-sqlite`、`w5-integration-postgresql`、`w5-golden`、`w5-e2e`、`w5-performance`、`w5-anti-ghost`）显式追加 `--strict-markers --maxfail=1` | CI 失败非零退出码 |
| 3.2.4 | 发布候选 job 额外追加 `-ra` 并解析 skip/xfail 报告 | 无声明 skip/xfail 即失败 |

### 3.3 共同验证

- `pytest --strict-markers -m "not (dual_db or e2e)"` 在 SQLite 路径全绿；
- `pytest --strict-markers -m dual_db` 在 PostgreSQL service 路径核心矩阵全绿；
- 任一 collection error、skip/xfail 漏报或 backend 误覆盖必须非零退出。

## 4. W5 准入资产待建（实现准入后逐项落地，但不写生产代码）

| # | 资产 | 路径 / 命令 | 阻塞级别 |
|---|---|---|---|
| 4.1 | `tests/w5/` 测试目录骨架（仅目录与 `__init__.py`，不创建空测试文件） | `tests/w5/` | 仅占位 |
| 4.2 | manifest schema JSON 文件（已在 `docs/design/W5_EVIDENCE_MANIFEST_SCHEMA_v1.json` 留初版，需冻结 `validator_version=w5-manifest-validator-v1`） | `docs/design/W5_EVIDENCE_MANIFEST_SCHEMA_v1.json` | 阻塞 |
| 4.3 | `scripts/quality/check_w5_antighost.py` runner（仅骨架 + import + argparse） | `scripts/quality/check_w5_antighost.py` | 阻塞 |
| 4.4 | `scripts/e2e/e2e_w5_real_user.py` 真实用户 E2E 脚本（仅骨架 + 启动参数 + 合成数据生成） | `scripts/e2e/e2e_w5_real_user.py` | 阻塞 |
| 4.5 | `docs/evidence/w4_baseline.json` 由 W4 evaluator 实际运行写入（不得预生成） | `docs/evidence/w4_baseline.json` | 阻塞 |
| 4.6 | Multilingual golden set `w5-golden-v1`：12 entity + 4 todo 样本 JSONL | `tests/w5/fixtures/golden/w5_golden_v1.jsonl` | 阻塞 |
| 4.7 | SQLite/PostgreSQL CI service 与 manifest 收集钩子 | `.github/workflows/ci.yml` + W5 jobs | 阻塞 |

## 5. 灰度 cycle 定义（产品/运维 P2，落入 PRD §8.3）

| 子项 | 目标 | 验收 |
|---|---|---|
| 5.1 | 灰度观察周期长度 | 至少 7 天 |
| 5.2 | 灰度最低流量门槛 | ≥1k 候选请求/天 |
| 5.3 | 灰度提量批准前置 | 上一周期无未关闭 P1/P2 + 双库 manifest + W4 baseline 通过 |
| 5.4 | 灰度暂停/回滚条件 | 任一 P0（跨语言 MERGE / 跨 scope / PII / audit 写失败）立即回滚并 paging |

## 6. Implementation Authorization 签署条件

- §3 准入改造全部 `done`；
- §4 准入资产除 4.5 外全部 `done`（4.5 由 W4 evaluator 真实运行产生，不预生成）；
- §5 灰度 cycle 定义补一行入 PRD §8.3；
- 四角色在 Test Plan v1.2 §2.2 复核签署表内再次确认 `approved`；
- 文档同步：CHANGELOG、PRD §10、Tech Design §17、Test Plan §17 状态行更新为 `Implementation=authorized`；
- 否则 Implementation 保持 `blocked`。

## 7. 关联文档

- [PRD v1.2](../spec/PRD_跨语言实体关联_W5_v1.md)
- [Tech Design v1.2](../design/TECH_DESIGN_跨语言实体关联_W5_v1.md)
- [Test Plan v1.2](../design/TEST_PLAN_跨语言实体关联_W5_v1.md)
- [Ontology Semantic Contract Plan](../planning/ONTOLOGY_SEMANTIC_CONTRACT_PLAN.md)
- [W5 Evidence Manifest Schema v1](../design/W5_EVIDENCE_MANIFEST_SCHEMA_v1.json)