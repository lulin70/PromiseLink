# 测试计划 — 跨语言实体关联（W5）

> **版本**: v1.2  
> **日期**: 2026-09-08  
> **状态**: DevSquad 复核修订版，待最终签署批准；未通过准入不得进入实现  
> **PRD**: [PRD_跨语言实体关联_W5_v1.md](../spec/PRD_跨语言实体关联_W5_v1.md)  
> **技术设计**: [TECH_DESIGN_跨语言实体关联_W5_v1.md](TECH_DESIGN_跨语言实体关联_W5_v1.md)  
> **父规划**: [ONTOLOGY_SEMANTIC_CONTRACT_PLAN.md](../planning/ONTOLOGY_SEMANTIC_CONTRACT_PLAN.md)

---

## 1. 测试目标与实施门禁

W5 测试计划把 PRD/技术设计中的安全边界转换为可执行测试资产，覆盖：

1. 多语言抽取契约与 W1/W2 中文回归。
2. 中英日语言识别、三语字典、alias family 与跨语言候选解析。
3. 服务端签名 `candidate_token` 的绑定、过期、篡改、重放和幂等。
4. W3 `EntityCorrection` 审计、alias 写回、拒绝冷却和同事务回滚。
5. embedding space metadata、cache namespace、失败降级和主库事实源边界。
6. Todo L5 的候选、确认/拒绝、审计、冷却及“不触发实体合并”约束。
7. 双用户隔离、SQLite/PostgreSQL 双数据库、反幽灵和真实用户 E2E。
8. 灰度、回滚、指标、告警与发布前证据归档。

**硬门禁**：测试计划通过 DevSquad 复核前，不创建 W5 生产实现；所有准入测试、双数据库核心矩阵、反幽灵检查和发布前真实用户 E2E 全部通过前，不得合入、推送或部署 W5。

## 2. 测试计划准入与批准门

### 2.1 测试可执行前置条件

1. **接口契约冻结**：实现前必须在技术设计或 API schema 中登记候选生成、实体确认/拒绝、Todo 确认/拒绝的实际路由、HTTP 方法、请求/响应字段、错误码和幂等语义。测试不得通过猜测路由或仅检查 HTTP 状态码替代业务断言。
2. **事实模型冻结**：必须登记 `candidate_token` 的 canonical serialization、HMAC 密钥来源、TTL/时钟策略、token hash、candidate digest、operation key、消费状态、唯一约束以及 confirm/reject 并发时的事务隔离策略。Entity 与 Todo 均由既有 `EntityCorrection` 承载上述 operation/audit 事实，按 `correction_type` 与 `source_todo_id` 区分 scope；不得引入独立的 W5 Todo correction 表。
3. **Todo 事实模型冻结**：必须明确 `source_todo_id`、目标 Todo candidate IDs、确认后的唯一关联字段、Todo correction 的审计字段、冷却 pair、重复提交返回原结果的规则；不得以 EntityCorrection 中不存在的字段作为测试前提。
4. **数据库矩阵可运行**：SQLite 与 PostgreSQL 必须由独立 fixture 显式选择；禁止 `tests/conftest.py` 全局覆盖 `DATABASE_URL`。SQLite 必须开启外键约束，PostgreSQL 必须执行真实 `alembic upgrade head`，两者均不得使用 `Base.metadata.create_all` 代替 migration 验证。
5. **环境可观测**：每轮测试输出数据库 dialect、migration head、embedding provider/model/dimension/space/profile、配置开关和 commit SHA；连接串中的密码必须脱敏，日志和报告不得包含 PII。
6. **严格收集门禁**：注册本计划使用的 pytest markers；CI 使用 `--strict-markers`、禁止 `--continue-on-collection-errors`，collection error、无测试收集、意外 skip/xfail 均非零退出。
7. **真实入口可验证**：candidate resolver、token verifier、Todo resolver、space gate、cooldown、metrics、灰度控制必须由生产 API/pipeline 触发；单独调用内部 helper 不能替代集成/E2E 证据。
8. **证据可归档**：实现阶段先创建证据 manifest schema 和脱敏检查器；manifest 缺失、命令/commit/config/db/结果字段不完整时，发布门禁失败。

在上述条件未完成前，允许继续修订文档和测试设计，但禁止 W5 生产代码、空测试文件或 `skip/xfail` 占位资产进入仓库。

### 2.2 复核签署表（待签署）

| 角色 | 复核重点 | 结论 | 签署状态 |
|---|---|---|---|
| 架构师 | 事实源、事务、双数据库、migration、接口边界 | 已提出阻断项，待修订复核 | pending |
| 安全专家 | token、IDOR、PII、客户端越权、LLM 脱敏 | 已提出阻断项，待修订复核 | pending |
| 测试专家 | 可执行夹具、并发幂等、严格收集、E2E、指标 | 已提出阻断项，待修订复核 | pending |
| 产品/运维 | 用户旅程、灰度、回滚、告警、证据 | 已提出阻断项，待修订复核 | pending |

批准条件：四类角色均明确 `approved`，且不存在未关闭的 P0/P1；本表在下一轮 DevSquad 复核后更新，不以文档作者自签代替独立复核。

---
### 2.2 四角色 P1/P2 关闭矩阵（文档闭环）

| 评审角色 | P1/P2 主题 | 关闭证据 | 当前状态 |
|---|---|---|---|
| 架构师 | Entity/Todo 共用 operation schema、状态机、双库 migration 序列 | PRD §4.2.5、§8.1；技术设计 §3.1.2 | `closed-docs` |
| 安全专家 | Token Protocol、密钥轮换/撤销、零写错误契约、PII/evidence policy | PRD §4.2.4、§4.2.5、§8.2；技术设计 §3.1.1 | `closed-docs` |
| 测试专家 | manifest schema/validator、golden 最小样本、W4 baseline、真实用户 E2E | PRD §8.2；本计划 §5.4、§16.2 | `closed-docs` |
| 产品/运维 | Todo 用户状态流、灰度/RACI、告警阈值、回滚证据 | PRD §4.6.1、§8.3；本计划 §10、§11 | `closed-docs` |

`closed-docs` 只表示文档 P1/P2 已完成闭环，不表示实现、测试执行或发布批准。四角色正式签署、双库真实 migration、真实用户 E2E、Anti-ghost、指标告警演练仍是后续准入门禁；在这些门禁通过前保持 `Implementation=blocked`。


| 层级 | 覆盖对象 | 运行方式 | 触发 | 阻塞级别 |
|---|---|---|---|---|
| 契约/单元 | 抽取字段、语言标签、字典、解析动作、阈值、token、embedding metadata | `pytest tests/w5/ -m unit` | 每次 PR | 阻塞 |
| 安全单元 | IDOR、伪造候选、properties 写入、PII、日志、LLM 脱敏 | `pytest tests/w5/ -m security` | 每次 PR | 阻塞 |
| 集成 | Engine、纠偏 API、merge、Todo、审计与事务 | `pytest tests/w5/ -m integration` | 每次 PR | 阻塞 |
| 双数据库 | SQLite 与 PostgreSQL 同一测试矩阵 | `pytest tests/w5/ -m dual_db` | PR/发布候选 | 阻塞 |
| 回归 | W1/W2/W3/W4 既有套件与中文黄金集 | 现有全量 pytest | 每次 PR | 阻塞 |
| 性能 | candidate API、embedding、pipeline 增量 | `pytest tests/w5/test_w5_performance.py -m performance` | PR/发布候选 | 发布候选阻塞 |
| 反幽灵 | 模块真实调用、计数器/入口、无死代码、无隐式 fallback | 静态扫描 + 集成/E2E | PR/发布候选 | 阻塞 |
| E2E | 合成用户真实旅程、灰度/回滚、异常恢复 | `scripts/e2e/e2e_w5_real_user.py` | 发布前手动 + CI nightly | 阻塞 |
| LLM 黄金集 | multilingual 抽取和 Recall/MRR | `golden-baseline.yml` 手动/定时 | 手动/夜间 | 发布候选阻塞，普通 PR 不阻塞 |

所有测试必须使用合成数据；禁止把真实姓名、公司、手机号、邮箱或原始长文本写入 git、日志、测试报告或证据目录。

---

## 3. 测试资产与目录映射

实现阶段必须创建并维护以下测试资产；本测试计划阶段不提前创建生产代码或空测试文件：

```text
tests/w5/
├── test_multilingual_extraction_contract.py
├── test_language_detection.py
├── test_cross_language_dictionary.py
├── test_cross_language_resolution.py
├── test_embedding_space_gate.py
├── test_cross_language_cooldown.py
├── test_candidate_api_contract.py
├── test_cross_language_correction_transaction.py
├── test_todo_resolution_multilingual.py
├── test_w5_security_and_pii.py
├── test_w5_degradation.py
├── test_w5_metrics.py
├── test_w5_sqlite.py
├── test_w5_postgresql.py
├── test_w5_performance.py
└── e2e/
    └── test_w5_real_user.py

scripts/e2e/e2e_w5_real_user.py
docs/e2e_evidence/w5_e2e/
```

测试文件必须由独立测试角色维护；生产代码作者不得以删除、`skip`、`xfail`、放宽断言或只检查 HTTP 状态码的方式绕过失败。

---

## 4. Fixture、数据和环境基线

### 4.1 合成数据

统一使用稳定的 synthetic fixture：

- 人名至少 10 组中/英/日 family，例如 `synthetic_person_001`。
- 公司至少 5 组中/英/日 family，例如 `synthetic_company_001`。
- 手机、邮箱使用明显伪造格式；测试报告中不得输出完整 PII。
- 每个 fixture 明确 `user_id`、`event_id`、`entity_id`、`todo_id`，禁止依赖数据库自增或测试执行顺序。
- 同一语义样本提供正例、负例、灰区和跨用户冲突样本。

### 4.2 Session 与用户隔离

- 默认每个用例使用独立数据库事务，并在结束后清理。
- Engine 必须按请求生命周期创建，或显式按 `user_id` 分区；测试必须交错执行用户 A/B 请求。
- 断言不仅检查 SQL 查询过滤，还检查内存 index、alias cache、candidate cache 和 embedding cache 不含另一用户 ORM 对象或结果。
- 所有 candidate API 在服务端重新读取主数据库并校验 user/status/type。

### 4.3 SQLite/PostgreSQL fixture 与 migration

当前共享测试 fixture 将 `DATABASE_URL` 强制为 SQLite；这会使 CI 中 PostgreSQL 服务未被真正覆盖。准入实现前必须：

1. 移除或隔离该全局覆盖，改为 `db_backend` 参数化 fixture 显式选择 `sqlite` 或 `postgresql`；测试进程启动后不得通过修改环境变量在同一进程动态切换 backend。
2. SQLite 使用临时文件或内存数据库，连接建立时显式执行 `PRAGMA foreign_keys=ON`，并断言该 pragma 生效；不得用关闭外键来规避 PostgreSQL 约束差异。
3. PostgreSQL 使用 CI service `postgres:16-alpine`，连接串来自环境变量；连接目标必须在测试报告中脱敏归档。
4. 两种 backend 均先执行真实 `alembic upgrade head`，再创建 session；禁止 `Base.metadata.create_all` 作为 W5 初始化方式。
5. 同一测试 ID 由参数化矩阵在两种数据库运行，不能只复制一份“状态码测试”。
6. 报告分别归档 `sqlite` 与 `postgresql` 结果、migration head 和失败分类；任一数据库失败均阻塞。
7. PostgreSQL 是发布验证的优先数据库；SQLite 仍作为本地离线和前端 E2E 兼容矩阵保留。

`src/promiselink/database.py` 的 `IS_SQLITE` 等导入期常量不得作为单进程切换依据；测试应通过独立进程或独立 session/engine 完成 backend 矩阵。

### 4.4 配置基线

默认配置必须验证为安全关闭：

```text
cross_language_enabled=false
cross_language_todo_enabled=false
cross_language_embedding_enabled=false
cross_language_rollout_percent=0
cross_language_embedding_provider=local
cross_language_embedding_model=all-MiniLM-L6-v2
cross_language_embedding_dimension=384
cross_language_embedding_space=local/all-MiniLM-L6-v2/384
cross_language_embedding_profile_version=w5-v1
cross_language_candidate_token_ttl_seconds=600
cross_language_rejection_cooldown_days=30
```

测试必须覆盖开关关闭、白名单开启、百分比灰度、立即回滚四种配置状态。

---

## 5. 契约、语言与字典测试

### 5.1 多语言抽取契约

| ID | 场景 | 必须断言 |
|---|---|---|
| C-W5-01 | 英文正例 | `name` 保留原文；`language=en`；`canonical_zh` 按黄金标注输出 |
| C-W5-02 | 日文正例 | 平假名/片假名姓名保留；`language=ja`；`canonical_zh` 按黄金标注输出 |
| C-W5-03 | 中文旧 payload | 缺失新字段仍通过，旧行为不变 |
| C-W5-04 | 负例/不可靠翻译 | `canonical_zh=None`；不得猜测或自动写 alias |
| C-W5-05 | aliases 类型错误 | 安全降级为缺省值或明确契约错误，不写入实体 alias |
| C-W5-06 | 未知字段 | 不破坏旧字段解析；进入既有 degraded 路径 |
| C-W5-07 | 原文保护 | 任何抽取、确认、merge 后 `name` 原文不被覆盖 |
| C-W5-08 | 契约 hash | 新字段进入 W1 contract hash；旧中文黄金集无回归 |

### 5.2 语言检测

覆盖英文、中文、平假名、片假名、中英混合、中日混合、仅汉字、显式 hint 覆盖自动判断。断言：

- 仅汉字返回 `zh_or_ja_unknown`，不得强行判定 `ja`。
- 混合文本返回 `mixed`，不能把 mixed 作为身份唯一依据。
- 显式 hint 优先，但非法 hint 不得放宽候选 scope。

### 5.3 三语字典与 alias family

覆盖：

- 中↔英、 中↔日、 英↔日正向/反向查找。
- `person` 与 `company` 类型隔离。
- 全局 seed 只读；用户确认学习结果按 `user_id` 隔离。
- 重复 alias 去重、方向归一、未知 family 不合并。
- 负例相似字符串不产生候选。
- 字典命中结果必须 `confirm_only=true`，不得修改数据库。

### 5.4 Multilingual golden set 与可审计评估

W5 黄金集必须以合成样本 JSON/JSONL 固化并纳入版本控制；每条样本至少包含：

```json
{
  "case_id": "w5-en-001",
  "language_direction": "en_to_zh",
  "input_text": "synthetic text only",
  "source_entity_id": "synthetic_entity_source_001",
  "gold_entity_id": "synthetic_entity_gold_001",
  "gold_candidate_ids": ["synthetic_entity_gold_001"],
  "gold_canonical_zh": "synthetic label or null",
  "entity_type": "person",
  "expected_action": "confirm",
  "is_negative": false
}
```

规范：

- `gold_entity_id`、candidate IDs 和 source IDs 必须是稳定合成 ID，不能用名称字符串代替真值。
- 按 `en_to_zh`、`zh_to_en`、`ja_to_zh`、`zh_to_ja`、`en_to_ja`、`ja_to_en`、person/company、positive/negative 分层报告。
- Recall@5 = 命中真值候选的样本数 / 有真值候选的样本数；MRR@5 = 命中样本的 `1/rank` 平均值，未命中记 0；false-positive rate = 负例中返回任意候选的样本数 / 负例样本数。
- Todo Recall@5 使用同样公式，但真值为 `gold_todo_id`，并单独按有/无时间信息分层。
- 报告必须包含样本总数、各分层分母、命中数、均值、失败 case_id 和基线 commit；分母为 0 的分层必须失败而不是显示为通过。
- 黄金集 evaluator 必须返回非零退出码阻断门禁；不得以 `skipif`、`xfail` 或“LLM 不可用”掩盖发布候选失败。普通 PR 可只运行确定性 mock/local 子集，但发布候选必须运行完整准入集。

**最小版本化样本与 W4 baseline**：发布候选至少包含 12 条实体样本（六个 language direction 各 1 条正例，另含 person/company 与 2 条 negative）和 4 条 Todo 样本（有时间/无时间各两条，至少覆盖 en↔zh、ja↔zh）；样本文件版本为 `w5-golden-v1`，所有 ID 为 synthetic。W4 baseline 固定引用 `docs/evidence/w4_baseline.json`、baseline commit `W4_BASELINE_COMMIT`（发布前由 evaluator 写入实际 40-hex SHA）、dataset version `w4-golden-v1`、evaluator `w5-evaluator-v1`；若该 artifact、commit 或 evaluator version 缺失，发布门禁失败。比较规则为同一分层和同一分母：W5 中文 Recall/MRR/FPR 不得低于 W4 baseline，允许误差不超过 0.01；跨语言 Entity Recall@5 ≥ 0.80、MRR@5 ≥ 0.70、FPR ≤ 0.10，Todo Recall@5 ≥ 0.75。


## 6. 跨语言候选解析与安全边界

每个跨语言测试都必须断言：

```text
action == CONFIRM
confirm_only == true
action != MERGE
active_entity_count 不因候选生成变化
```

| ID | 场景 | 必须断言 |
|---|---|---|
| R-W5-01 | 三语字典命中 | 返回 family 候选，method 正确，零写入 |
| R-W5-02 | accepted alias 命中 | 仅返回候选，未确认前不写 alias |
| R-W5-03 | embedding 高分 | 高于 confirm 阈值仍只能 CONFIRM |
| R-W5-04 | embedding 灰区 | 标记 ambiguous；按配置进入 fallback 或安全降级 |
| R-W5-05 | embedding 低分 | 不推荐候选 |
| R-W5-06 | provider timeout | 不扩大候选；返回 safe degradation |
| R-W5-07 | dimension mismatch | 拒绝比较；不得截断/补零 |
| R-W5-08 | model/provider mismatch | 拒绝比较；不得静默 fallback |
| R-W5-09 | LLM fallback 成功 | 即使置信度 1.0 仍 CONFIRM |
| R-W5-10 | LLM fallback 失败 | 无候选或需人工创建，不伪造确认 |
| R-W5-11 | cooldown 命中 | 同一 pair 不推荐；不修改审计事实 |
| R-W5-12 | cooldown 过期 | 允许重新产生候选 |
| R-W5-13 | 不同 user | 不返回另一用户候选 |
| R-W5-14 | 不同 entity type | person/company 不互相匹配 |
| R-W5-15 | inactive/merged entity | 不作为可确认候选 |
| R-W5-16 | LLM 高分绕过尝试 | 最终决策层拒绝 MERGE |

W4 的同语言 exact/rapidfuzz 自动合并基线必须另行断言不被 W5 破坏；跨语言标记一旦成立，不得回落到自动合并路径。

---

## 7. Candidate token 生命周期测试

服务端 token 的 W5-CJ-v1 canonical payload 必须按固定顺序绑定：`version`、`key_version`、`user_id`、`event_id`、`scope_type`、`extracted_entity_id`/`source_todo_id`、`candidate_digest`、`operation_key`、`resolver_version`、`score_version`、`embedding_space`、`issued_at`、`expires_at`、`nonce`。字符串使用 UTF-8 + Unicode NFC，时间使用 UTC RFC3339，候选数组按服务端 rank 顺序，数字使用 RFC 8785 确定性表示；固定字段顺序优先于通用 key 排序。签名为 HMAC-SHA256 的 256 位值，以 64 个小写十六进制字符表示，外部 envelope 固定为 `base64url(canonical_payload_bytes || "." || ASCII(signature_hex))`，客户端只能原样携带。

| ID | 场景 | 结果 |
|---|---|---|
| T-W5-01 | 合法签名 | 可确认/拒绝 |
| T-W5-02 | 签名篡改 | `candidate_token_invalid`（HTTP 400），零业务写入 |
| T-W5-03 | 首次提交已过期的有效 token | `candidate_token_expired`（HTTP 410），零业务写入 |
| T-W5-04 | 跨 user | `candidate_token_invalid`（HTTP 400），零业务写入 |
| T-W5-05 | 跨 event | `candidate_token_invalid`（HTTP 400），零业务写入 |
| T-W5-06 | 跨 extracted entity/todo | `candidate_token_invalid`（HTTP 400），零业务写入 |
| T-W5-07 | candidate digest 变化 | `candidate_token_invalid`（HTTP 400），零业务写入 |
| T-W5-08 | resolver/score version 不匹配 | `candidate_token_invalid`（HTTP 400），零业务写入 |
| T-W5-09 | embedding space 不匹配 | `candidate_token_invalid`（HTTP 400），零业务写入 |
| T-W5-10 | nonce/token 重放 | 返回原结果，不重复业务写入 |
| T-W5-11 | 已完成 operation 在 TTL 后合法重放 | 仍返回持久化原结果，不返回 `candidate_token_expired`，不重复业务写入 |
| T-W5-12 | 并发 confirm | 只有一个事实结果，最多一条 audit |
| T-W5-13 | 并发 reject | 幂等返回，不重复 cooldown/audit |
| T-W5-14 | confirm 后 reject 重放 | 返回已完成结果，不反向改变事实 |
| T-W5-15 | 错误 token | entity、alias、todo、audit 均零写入 |
| T-W5-16 | 客户端伪造 candidate IDs/score/method | 服务端忽略不可信字段 |

### 7.1 Token 与持久化幂等事实模型

在创建 `tests/w5/test_candidate_api_contract.py` 前，技术设计和 migration 必须冻结以下最小事实字段；W5 不新增独立 Todo correction 表，Entity 与 Todo 均由既有 `EntityCorrection`（按 `correction_type` 区分）承载 operation/audit 事实；这些字段不得只存在于内存、JWT claims 或客户端：

| 事实 | 最小要求 |
|---|---|
| token identity | `token_hash` 或等价不可逆标识；禁止持久化原始 token |
| candidate binding | `candidate_digest`、resolver/score version、embedding space、user/event/extracted entity 或 Todo scope |
| operation identity | 服务端生成的 `operation_key`，并按业务 scope 建唯一约束 |
| lifecycle | `issued/expires`、`pending/confirmed/rejected` 或等价消费状态、完成时间 |
| result replay | 已完成操作的 canonical result 摘要，可安全重放且不再次写业务事实；最小实例固定为 `{"candidate_rank":int,"method":str,"score":float,"language_pair":"xx_yy"}` 四个字段，禁止写入候选原始 ID 列表、原始姓名/邮箱/手机号或长文本 |
| concurrency | confirm/reject 的行锁或等价 compare-and-set 语义；同一 operation 只有一个终态 |
| audit link | Entity/Todo correction audit 与 operation key 的可追溯关联；Entity 与 Todo 均落在既有 `EntityCorrection`，以 `correction_type` 和 `source_todo_id` 区分 scope |

测试必须先验证 migration、唯一约束和 rollback，再验证 API。若实现选择不新增表，必须明确现有模型如何承载上述字段，以及实体纠偏与 Todo 纠偏如何避免 scope 碰撞。

### 7.2 Candidate API 黑盒契约

实现阶段必须冻结并登记实际 API 路由；本计划使用以下逻辑契约，不预设具体路径：

```text
candidate generation: 只读，返回 candidates、candidate_token、confirm_only、resolver/score/space metadata
entity resolution:    只接受 token + confirm/reject action；服务端重算/重读候选并执行事务
Todo resolution:      只接受 Todo token + confirm/reject action；只更新 Todo 事实并执行 Todo audit
```

黑盒测试必须断言业务结果：active entity/Todo 数、alias、correction audit、cooldown、operation 状态和 idempotent replay；只返回 2xx 不算通过。客户端提交的 `candidate_entity_ids`、score、method、explanation、cooldown、space 等非授权字段必须被忽略或拒绝。

### 7.3 HMAC secret 生命周期

测试必须覆盖：

- secret 由受控服务端 provider 提供；原始 secret 不写数据库、日志、manifest 或响应。
- token payload 绑定 `key_version`；签名验证使用 constant-time comparison。
- key rotation 后，旧 key 仅在既有 token TTL 窗口内有效；签名有效、scope 正确但首次提交超过 `expires_at` 返回 `candidate_token_expired`（HTTP 410）；撤销、篡改、错误 key version 或其他格式/绑定问题返回 `candidate_token_invalid`（HTTP 400）。
- emergency revocation 通过 key-version denylist 立即失效；所有失败路径均零业务写入；已完成 operation 的合法重放仍按持久化结果 replay。

## 8. 纠偏、事务与安全测试

### 8.1 审计和 alias

- confirm 写入 `correction_type=entity`、`action=select_existing`。
- reject 写入 `correction_type=entity`、`action=ignore`。
- Todo confirm/reject 分别写入 `correction_type=todo` 对应事实。
- `canonical_zh` 只有人工确认且 token 校验成功后才可作为 alias 候选。
- 抽取、候选生成、embedding 命中均不得自动写 alias。
- 全局种子不得写入用户数据；用户学习不得污染其他用户。

### 8.2 事务原子性

| 场景 | 断言 |
|---|---|
| merge 成功 + audit 成功 | 主库事实、alias、audit 一起提交 |
| merge 失败 | alias、audit、关联迁移全部回滚 |
| audit 写失败 | merge、alias、cooldown 全部回滚 |
| alias 唯一约束冲突 | 整体回滚，可安全重试 |
| 并发 confirm/reject | 结果确定、无重复 audit |
| 向量索引失败 | 主库事实提交；向量作为派生数据可重建 |

测试不得声称独立向量 SQLite 连接与主数据库组成分布式原子事务；只验证主库先提交、派生索引失败可恢复。

### 8.3 PII、IDOR 与客户端越权测试

- `original_extracted_text` 和 `original_canonical_name` 按 W3 redaction 规则处理。
- 日志、metrics、trace、token 错误响应不得包含原始长文本、手机号、邮箱或完整候选 properties。
- 客户端写入 `Entity.properties` 的 cooldown/score/space/alias 字段必须被拒绝或忽略。
- 伪造其他用户实体 ID、event ID、todo ID、candidate token 必须 fail-closed。
- LLM fallback 只接收脱敏短字段和候选 ID，不接收手机号、邮箱、原始长文本。
- 使用 PII regex、日志白名单和响应字段白名单扫描测试产物，命中数必须为 0。

---

## 9. Embedding space、缓存与降级测试

### 9.1 Metadata 与 cache namespace

每个持久向量必须具备：

```text
provider
model
dimension
embedding_space
profile_version
created_at
```

缓存 key 必须包含 user scope、provider、model、dimension、space、profile version 和内容 digest。测试覆盖：

- 完整 metadata 可用。
- 任一 metadata 缺失即拒绝召回。
- API/local、不同 model、dimension、space、profile 互不命中缓存。
- 用户 A/B embedding cache 不串用。
- 内容相同但 namespace 不同产生不同 key。

### 9.2 安全降级

- provider timeout、模型不可用、维度不一致、向量索引不可用时，返回无候选/需人工确认。
- 不允许 API 失败后静默切换到不同 space 的 local embedding。
- 不允许截断、补零或强制 cosine 比较不兼容向量。
- 主数据库实体、Todo、audit 正确性不得依赖派生向量索引。
- safe degradation 记录计数和原因，但不记录 PII。

---

## 10. Todo L5 测试

覆盖中英日 Todo：明确日期、相对日期、`next week`/`下周`/日文相似表达、时区、±7 天模糊窗口和无时间信息。

必须断言：

1. Todo candidate 使用服务端签名 token，绑定 user/event/todo/digest/resolver/score/space/TTL。
2. `cross_language_todo_enabled=false` 时不产生跨语言自动路径。
3. confirm-only；确认后只更新 Todo 关联，不触发 Entity merge。
4. reject 写 `correction_type=todo`、`action=ignore`，并参与 Todo cooldown。
5. Todo 文本不得写入 Entity.aliases。
6. 无时间信息不能仅凭文本自动关联。
7. token 过期、篡改、重放与实体候选使用相同 fail-closed/幂等语义。
8. 双用户 Todo 候选不得串 scope。

---

## 11. 指标、灰度、回滚与告警演练

测试必须验证以下指标可被触发、带正确 scope、且无 PII：

```text
w5_cross_language_candidate_token_issued
w5_cross_language_candidate_token_invalid
w5_cross_language_confirm_idempotent
w5_cross_language_reject_idempotent
w5_cross_language_todo_candidate_token_issued
w5_cross_language_todo_confirmations
w5_cross_language_todo_rejections
w5_cross_language_todo_cooldown_suppressed
w5_cross_language_audit_write_failures
w5_cross_language_entity_resolution_cross_scope_blocked
w5_cross_language_vector_metadata_rejected
w5_cross_language_vector_fallback_blocked
w5_cross_language_primary_db_truth_conflicts
w5_cross_language_rollout_users
w5_cross_language_safe_degrades
w5_cross_language_embedding_latency_ms
w5_cross_language_candidate_count
```

演练顺序：

```text
rollout_percent=0
→ cross_language_todo_enabled=false
→ cross_language_embedding_enabled=false
→ cross_language_enabled=false
```

回滚后必须验证旧中文 W4 功能、既有审计、已确认 alias 和主库实体事实仍可用；不得删除审计或已确认 alias。告警必须覆盖：跨语言 MERGE、跨 scope 阻断异常、token invalid/replay 激增、audit 写失败、metadata 拒绝、主库/向量冲突、safe degradation 超阈值和 active entity 异常变化。

---

### 11.1 RACI、告警阈值与灰度批准

| 活动 | R | A | C | I |
|---|---|---|---|---|
| schema/migration/Token Protocol | 架构、测试 | 架构 | 安全、运维 | 产品、编码 |
| golden/W4 baseline | 测试 | 测试 | 架构、产品 | 运维、编码 |
| 真实用户 E2E | 测试、UI | 产品 | 安全、运维、架构 | 编码 |
| 灰度提量 | 运维 | 产品 | 架构、安全、测试 | 编码、UI |
| 告警与回滚 | 运维 | 运维 | 安全、架构、产品 | 测试、编码、UI |
| evidence retention | 运维 | 测试 | 安全 | 产品、架构 |

灰度阶段为 `0% → allowlist → 1% → 5% → 25% → 100%`；每次提量需四角色批准、双库 manifest/W4 baseline 通过且无未关闭 P1/P2。任一跨语言 `MERGE`、跨 scope 写入、PII/secret 命中、audit write failure 为 P0 立即回滚；token invalid 5 分钟占比 >5% 或较前小时 3 倍、truth conflict >0、metadata rejected >1%、confirm/reject 5xx >1%、safe degrade >10% 为 P1 paging；p95 超预算 20% 或 cooldown suppressed 较基线 3 倍为 P2 ticket。回滚固定为 rollout=0、关闭 Todo、关闭 embedding、关闭 W5；保存触发前后 30 分钟脱敏 metrics、manifest、配置/migration head、命令和批准记录。


SQLite 与 PostgreSQL 均必须执行以下场景：

- schema 初始化与现有 migration head。
- UUID、UTC 时间、JSON/JSONB、aliases、EntityCorrection。
- candidate token 校验、TTL、冷却审计读取。
- confirm/reject 事务回滚与并发重放。
- 主库/派生向量不一致后的安全降级。
- 双用户隔离、空值、缺失字段、inactive/merged 状态。
- Todo token、Todo audit、Todo cooldown。

PostgreSQL 测试不得被默认 SQLite 环境变量覆盖；CI 必须输出数据库类型和连接目标作为证据。

---

### 12.1 双数据库 migration 执行序列

每个 SQLite/PostgreSQL job 必须按以下顺序执行并在 manifest 留痕：

1. Preflight：固定 commit/config digest，读取 current head，SQLite 显式执行并断言 `PRAGMA foreign_keys=ON`。
2. Real migration：临时 SQLite 与真实 PostgreSQL 16 分别执行 `alembic upgrade head`，禁止 `create_all()` 替代。
3. Schema verify：校验 EntityCorrection 扩展字段、唯一约束、索引、旧 W3/W4 数据兼容和 schema digest。
4. Core matrix：运行相同的 UUID、UTC、JSON/JSONB、token replay、confirm/reject、Todo audit/cooldown、事务原子性。
5. Rollback drill：在 disposable 数据库验证 downgrade/恢复；已确认事实不得被破坏。
6. Evidence：独立记录 dialect、old/new head、命令、退出码、结果计数和脱敏日志；任一序列失败即阻断。

### 12.2 Manifest validator 契约

manifest 使用 `schema_version=w5-evidence-v1`，必须包含 `commit_sha`、`command`、UTC `started_at/finished_at`、`database_backend`、`migration_head`、无 secret 的 `config_digest`、`embedding_profile`、`sample_count`、pass/fail/skip/xfail counts、metric value/threshold/comparator、relative artifact paths、`pii_scan_result` 与 `validator_version`。validator 必须校验 JSON schema、真实 commit/backend/head、计数和分母一致、时间合法、artifact 不越出 evidence root、PII/secret 扫描为 pass，并以非零退出码拒绝缺失/篡改/不一致 manifest；不得自动补字段。

证据只存合成 ID 和脱敏摘要。原始 token、secret、完整输入文本和 PII 禁止落盘；测试角色拥有 evidence owner，运维负责归档 ACL，默认保留 180 天，发布/回滚证据延续至下一 W5 版本后 30 天，安全 hold 优先。


## 13. 真实用户 E2E（发布前必跑）

脚本：`scripts/e2e/e2e_w5_real_user.py`。测试数据和账号均为合成数据，发布候选至少在 SQLite、PostgreSQL 各跑一轮。

| ID | 用户旅程 | 关键断言 |
|---|---|---|
| E-W5-01 | 英文实体 → 中文补录 → 候选 | 候选出现；confirm-only；active entity 数不变 |
| E-W5-02 | 人工确认 | token 校验成功；alias 双向追加；一条 entity audit；只保留一个 active entity |
| E-W5-03 | 人工拒绝 | 不 merge；`action=ignore`；后续冷却抑制同 pair |
| E-W5-04 | 首次提交已过期的有效 token | 返回 `candidate_token_expired`（HTTP 410）；零业务写入 |
| E-W5-05 | token 篡改 | 返回 `candidate_token_invalid`（HTTP 400）；零业务写入 |
| E-W5-06 | token 重放 | 返回既有结果；不重复 merge/alias/cooldown/audit |
| E-W5-07 | embedding provider 不可用 | 安全降级；旧功能仍可用 |
| E-W5-08 | dimension mismatch | 拒绝比较；不 fallback 到其他 space |
| E-W5-09 | LLM fallback timeout | 无伪造候选；事件仍可保存 |
| E-W5-10 | 中英日 Todo | 候选、confirm-only、Todo audit 全链路通过 |
| E-W5-11 | Todo reject | cooldown 生效；不写 Entity.aliases；不 merge |
| E-W5-12 | 双用户交错 | 候选、cache、audit、Todo 全部隔离 |
| E-W5-13 | 灰度开启/关闭 | 白名单用户可用，非白名单保持关闭 |
| E-W5-14 | 回滚 | W4 中文解析、实体、Todo、审计继续正常 |

每轮归档：命令、commit SHA、配置摘要（密钥脱敏）、数据库类型、测试摘要、服务日志脱敏摘录、metrics 摘要、截图或 API 响应摘要。证据目录为 `docs/e2e_evidence/w5_e2e/`。

---

## 14. 反幽灵门禁

W5 实现阶段必须提供唯一 runner：`scripts/quality/check_w5_antighost.py`。runner 只能通过公开 API/pipeline 触发真实入口，并输出 JSON 证据；禁止通过直接导入内部 helper 把计数器“刷绿”。CI 命令固定为：

```bash
set -o pipefail
python3 scripts/quality/check_w5_antighost.py --strict --manifest docs/e2e_evidence/w5_e2e/anti_ghost_manifest.json
```

runner 必须映射并真实触发 candidate token、Todo resolver、embedding-space gate、cooldown、metrics 和 rollout switch；每项至少包含 production entrypoint、调用计数/指标证据、结果断言和 PII 扫描结果。必须以失败用例证明以下路径会阻塞：`candidate_set_id` 替代签名 token、客户端控制 candidate/score/cooldown/alias、API/local 跨 space fallback、跨语言 `MERGE`、无 metadata 向量召回、Todo first-substring-wins 绕过 resolver。文件存在、单元测试通过或内部函数可调用均不能替代真实入口证据。

---

## 15. 性能与质量退出标准

发布候选必须满足：

| 指标 | 门槛 |
|---|---:|
| Candidate API p95 | `< 800 ms` |
| 稳态 embedding p95 | `< 500 ms` |
| 解析 pipeline 全链 p95（含 W5 `_step_cross_language`） | `< 1500 ms`（中文 `< 1200 ms`，跨语言 `< 1500 ms`；冷启动/LLM fallback 不计入） |
| multilingual Recall@5 | `≥ 0.80` |
| MRR@5 | `≥ 0.70` |
| false-positive rate | `≤ 10%` |
| Todo Recall@5 | `≥ 0.75` |
| 跨语言自动 MERGE | `0` |
| PII 日志/报告命中 | `0` |
| 双用户隔离 | `100%` |
| 双数据库核心矩阵 | `100%` |
| W4 中文基线 | 不下降 |
| skip/xfail 掩盖失败 | `0` |

性能测试必须在无 coverage instrumentation 的独立 job 运行，并记录硬件、数据库、embedding provider/model/space 和样本规模；不能只报告平均值。

---

## 16. CI、证据与发布门禁

### 16.1 CI job 与严格退出码

实现阶段 CI 至少拆分以下可审计 job；每个 job 必须在无测试、collection error、失败、意外 skip/xfail、阈值不达标时返回非零：

| Job | 数据库/范围 | 必须执行 |
|---|---|---|
| `w5-contract-unit` | SQLite | `tests/w5` 契约、语言、字典、space、token 单元；`--strict-markers` |
| `w5-integration-sqlite` | SQLite migration | W5 集成、事务、Todo、安全、反幽灵真实入口 |
| `w5-integration-postgresql` | PostgreSQL migration | 与 SQLite 相同的核心矩阵，不能只跑 smoke |
| `w5-golden` | mock/local + 发布候选完整 evaluator | 多语言 Recall/MRR/FPR、Todo Recall、中文 baseline |
| `w5-e2e` | SQLite/PostgreSQL 独立进程 | 真实 API 用户旅程、灰度、回滚、异常恢复 |
| `w5-performance` | PostgreSQL 优先、无 coverage | p95、样本规模和环境元数据 |
| `w5-anti-ghost` | 真实生产入口 | runner、反例阻塞验证、调用证据和 PII 扫描 |

pytest 全局配置必须移除 `--continue-on-collection-errors`；W5 job 显式使用 `--strict-markers --maxfail=1`，发布 job 额外使用 `-ra` 并解析 skip/xfail 报告。任何 `pytest` 无 test collected、collection error、未声明 skip/xfail 或 evaluator 输出缺少门槛字段均失败。

### 16.2 证据 manifest 与脱敏要求

每个 SQLite/PostgreSQL/E2E/性能/黄金/反幽灵 job 输出一份 JSON manifest，至少包含：

```text
schema_version
commit_sha
command
started_at/finished_at
database_backend
migration_head
config_digest（不含 secret）
embedding_profile
sample_count
pass/fail/skip/xfail counts
metric summary and thresholds
artifact paths
pii_scan_result
```

manifest 由 CI 校验 schema、commit、数据库 backend、命令和结果计数；缺失字段、密钥/PII 命中、结果与日志不一致时阻塞。证据只保存脱敏日志、摘要和合成 IDs，不保存原始 token、HMAC secret 或完整输入文本。`result_summary` 序列化后必须等于白名单最小实例 `{"candidate_rank":int,"method":str,"score":float,"language_pair":"xx_yy"}` 的超集；任何额外字段、保存的原始姓名/邮箱/手机号或长文本、客户端提交的非白名单字段均视为违规，manifest validator 以非零退出码拒绝。


### 16.3 真实用户 E2E 黑盒边界与异常恢复

E2E 只通过公开 API/UI 和真实服务进程操作；不得导入内部 resolver、直接写数据库或 mock token verifier。每个旅程除成功路径外，必须覆盖：

- 用户取消确认、刷新页面、重复点击 confirm/reject。
- 网络超时、服务端 5xx、响应丢失后的安全重试。
- 无候选、多个候选、候选过期、候选已被其他请求消费。
- provider timeout、向量 metadata 被拒绝、LLM fallback 不可用。
- UI 恢复后再次读取服务端 operation/result，而不是依赖前端内存状态。

E2E 通过标准是数据库事实、审计和指标均符合预期；不能只验证页面文字或 HTTP status。SQLite 与 PostgreSQL 必须由独立进程分别启动并使用各自 migration，不能在同一进程热切换数据库。

### G1：准入资产完成
- 测试目录、fixture 设计、双数据库矩阵、E2E 证据格式和退出标准明确。
- PRD、技术设计、测试计划状态一致。

### G2：实现前反幽灵与数据库门禁

- SQLite/PostgreSQL fixture 可分别运行。
- PostgreSQL 不再被测试全局环境覆盖为 SQLite。
- 反幽灵扫描和失败样例已验证会阻塞。
- token、CONFIRM-only、主库事实源和安全降级测试资产可执行。

### G3：合入门禁

- W5 单元、集成、安全、双数据库和 W1-W4 回归全绿。
- `ruff` 0、`mypy` 0、contract consistency PASS。
- 全量测试 0 failure、0 skip/xfail 掩盖失败、覆盖率不低于现有 CI 门槛。
- 安全扫描、PII 扫描和反幽灵报告全绿。

### G4：发布门禁

- §13 全部真实用户 E2E 场景在 SQLite/PostgreSQL 各通过一轮。
- 灰度开启、关闭、回滚与告警演练通过。
- 性能、Recall/MRR、中文回归和零自动 merge 指标达标。
- 证据归档至 `docs/e2e_evidence/w5_e2e/`。
- CHANGELOG、PRD、技术设计、测试计划、父规划和规格索引同步。

**任一 G2/G3/G4 失败，W5 不得 push、deploy 或发布。**

---

## 17. DevSquad 角色分工与复核输出

- **架构师**：确认 fixture、主库/向量边界、事务和双数据库矩阵可执行。
- **产品经理**：确认真实用户旅程、Todo L5 范围、灰度和回滚验收。
- **安全专家**：确认 token/IDOR/PII/客户端越权/LLM 脱敏测试完整。
- **测试专家**：维护测试资产、断言质量、并发幂等、无 skip/xfail 门禁。
- **编码角色**：只在测试计划获批且准入资产完成后实现生产代码与测试。
- **运维角色**：接线 CI、PostgreSQL service、性能 job、metrics/告警和证据归档。
- **UI 角色**：验证 CorrectionPanel 候选展示、confirm-only 状态和 token 只携带不解释的前端契约。

当前生命周期状态：

```text
PRD                approved / blocked until Test Plan approval
Technical Design   approved / blocked until Test Plan approval
Test Plan          v1.2 pending final DevSquad sign-off
Implementation     blocked
Verification       not started
Release            not started
Deployment         not started
```
