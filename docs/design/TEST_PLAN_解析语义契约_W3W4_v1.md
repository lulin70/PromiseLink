# 测试计划 — 纠偏回流（W3）与实体规范化（W4）

> **版本**: v1.0
> **日期**: 2026-09-05
> **PRD**: [PRD_解析语义契约_W3W4_v1.md](../spec/PRD_解析语义契约_W3W4_v1.md) · **技术设计**: [TECH_DESIGN_解析语义契约_W3W4_v1.md](TECH_DESIGN_解析语义契约_W3W4_v1.md)

---

## 1. 测试策略总览

| 层 | 对象 | 方式 | 触发 |
|---|---|---|---|
| 单元 | EntityCorrection 模型 / record_correction / cleanup / synonym_dict / difflib_step / frequent_contact_scanner | pytest，纯函数 + AsyncSession fixture | 每次推送 |
| 契约 | EntityCorrection 4 字段必填 / PII 零命中 / 聚合零原文 | pytest，正则 + DB 查询 | 每次推送 |
| 集成 | correct_event 5 类纠偏全埋点 + 事务原子性（failure 注入） + Step10b 入 pipeline | pytest，session rollback 注入 | 每次推送 |
| 回归 | 全量既有套件（实体合并、纠偏、关联、黄金集、W1/W2） | pytest | 每次推送 |
| e2e | 真实用户场景（同名纠偏、规范化候选、共现 3/2/91 天） | `scripts/e2e/e2e_w3_w4_real_user.py` + 真 LLM | 发布前手动 |

---

## 2. 单元测试清单

### 2.1 W3 单元

| # | 用例 | 断言 |
|---|---|---|
| **U-W3-01** | `EntityCorrection` 模型 create + 字段必填 | 4 字段 nullable 行为符合 schema；CHECK 约束拒绝未知 `correction_type`/`action` |
| **U-W3-02** | `record_correction` 自动 redact 5 类 PII | 输入含手机/邮箱/身份证/银行卡/微信号 → 落库后正则零命中 |
| **U-W3-03** | `record_correction` 不 commit（事务托管） | 调用后 session 仍在 uncommitted 状态；显式 commit 后才可查 |
| **U-W3-04** | `correct_event` 5 类分支均埋点 | mock 5 类纠偏各跑一次 → `entity_corrections` 表对应 `correction_type` 行数对得上 |
| **U-W3-05** | `cleanup_entity_corrections(180)` 边界 | created_at=now-181d 删；now-179d 保留；now 保留 |
| **U-W3-06** | cleanup 幂等 | 同一秒两次连续调用 → 第二次删 0 行 |
| **U-W3-07** | 聚合端点零原文 | 制造 5 条 entity_corrections（含手机号原文） → `/aggregations` 响应字段集 ⊆ {correction_type, action, count, last_seen} |
| **U-W3-08** | `GET /entity-corrections` 跨用户隔离 | 用户 A 写的记录，用户 B 调 `/entity-corrections` 返空 |
| **U-W3-09** | 日志键值白名单 | `correction_recorded` log call kwargs 仅含 {event_id, correction_type, action, entity_id, user_id, contract_version} |
| **U-W3-10** | 事务原子性（failure 注入） | 在人脉 select_existing 之后注入 IntegrityError → 后续 4 类纠偏全部回滚；EntityCorrection 表对应行未持久化 |

### 2.2 W4 单元

| # | 用例 | 断言 |
|---|---|---|
| **U-W4-01** | `load_synonyms` 首次启动写文件 | `data/synonyms.json` 不存在 → 创建且内容等于种子；二次启动读回 |
| **U-W4-02** | `find_person_aliases` 正向 + 反向 | `find_person_aliases("张三", {"张三":["老张"]})` → `["老张"]`；`find_person_aliases("老张", ...)` → `["张三"]` |
| **U-W4-03** | `_step_synonym` 命中 0.97 | 同义表含 "张三" ↔ "老张"；新 entity name="老张" → confidence=0.97 |
| **U-W4-04** | `_step_synonym` 未命中 0.0 | 同义表无 "王五" → confidence=0.0 |
| **U-W4-05** | `_step_difflib_fuzzy` ≥0.80 命中 | "林晚秋" vs "林晚秋" → 1.0；"张三" vs "张三丰" → 0.80 |
| **U-W4-06** | `_step_difflib_fuzzy` <0.80 不命中 | "张三" vs "李四" → 0.0 |
| **U-W4-07** | **规范化零自动合并**（D3 硬边界） | 制造 100 条 entity + synonym 命中 5 条 → 解析完成后 `Entity.query.count()` 不变；状态不进入 merged |
| **U-W4-08** | `scan_frequent_contacts` 3/90 天命中 | 制造 3 对实体 × 3 个不同事件（90 天内） → `frequent_contact.count >= 3` |
| **U-W4-09** | `scan_frequent_contacts` 2 次不命中 | 仅 2 对 → `frequent_contact` 字段不存在 |
| **U-W4-10** | `scan_frequent_contacts` 跨 91 天不命中 | 3 对但时间跨度 91 天 → 不触发 |
| **U-W4-11** | `scan_frequent_contacts` 同事件去重 | 同一事件被 pipeline 重复处理 5 次 → 共现 count 仍为 1 |
| **U-W4-12** | `scan_frequent_contacts` 跨用户隔离 | user A 的事件不参与 user B 的扫描 |
| **U-W4-13** | `co_occurrence_threshold` 配置可改 | settings.co_occurrence_threshold=5 时 3 次共现不触发；改回 3 时触发 |
| **U-W4-14** | `Step10b_FrequentContactScan` 入 pipeline | 制造 3/90 天场景跑完整 pipeline → Event.status=completed 且两端 `frequent_contact` 字段命中 |

---

## 3. 集成测试清单

### 3.1 W3 集成（基于 v1 既有 fixtures 复用）

`tests/test_entity_correction_integration.py`：

| # | 用例 | 复用 |
|---|---|---|
| **I-W3-01** | 4 类纠偏一次提交全部埋点 | `setup_completed_event_with_data`（v5.6 fixture） |
| **I-W3-02** | 同事务回滚：人脉 select_existing 阶段注入 IntegrityError | 业务数据全回滚 + EntityCorrection 行不存在 |
| **I-W3-03** | 业务写入成功但记录阶段失败（如 unique 冲突） | 业务数据写入但整体回滚（EntityCorrection 失败不能让部分业务生效） |
| **I-W3-04** | 180 天 cleanup worker 端到端 | 后台任务 mock 时钟 → 制造 181 天前记录 → 验证删除 |

### 3.2 W4 集成

`tests/test_entity_normalization_w4.py`：

| # | 用例 | 复用 |
|---|---|---|
| **I-W4-01** | synonym 命中 → CONFIRM（action 字段断言） | 已有 `test_entity_resolution.py` 风格 fixture |
| **I-W4-02** | difflib 命中 → CONFIRM | 同上 |
| **I-W4-03** | rapidfuzz 命中 0.85+ 仍走 MERGE（不破坏现有逻辑） | 已有 `test_auto_merge` 风格 |
| **I-W4-04** | Step10b 跑完整 pipeline | `tests/test_event_pipeline.py` 风格 |
| **I-W4-05** | `GET /entities/{id}/frequent-contacts` 200 | `tests/test_api_entities_*.py` 风格 |

### 3.3 跨模块集成

`tests/test_w3_w4_integration.py`：

| # | 用例 | 断言 |
|---|---|---|
| **IX-W3W4-01** | 纠偏 select_existing 后共现统计用合并后的实体 | 制造 2 个同名 entity + 4 个共同事件 → user 选 select_existing → 后续 Step10b 共现扫描使用 target entity |
| **IX-W3W4-02** | EntityCorrection 落库后 180 天 cleanup 不影响 brief | 纠偏记录 + brief 数据独立存储；cleanup 不动 brief |
| **IX-W3W4-03** | 同义表用户级热加载 | 修改 `data/synonyms.json` → 重启服务 → 命中 |

---

## 4. e2e — 真实用户场景（发布前必跑）

`scripts/e2e/e2e_w3_w4_real_user.py`：

| 场景 | 步骤 | 断言 |
|---|---|---|
| **E-W3-01 同名候选 → 选已有** | 用户 A 录「和林晚秋会面」，pipeline 抽 2 个候选（青梧科技 / 望津物流） → POST `/correct` select_existing | `event_correction_log` 1 行 selected_entity_id=青梧 id；候选未选中的 entity 未新增 event 关联 |
| **E-W3-02 同名候选 → 创建新** | 同上场景 → POST `/correct` create_new（new_company="新公司"） | 新 entity 创建；旧候选 event_ids 未变；entity_correction.action='create_new' |
| **E-W3-03 同名候选 → 忽略** | 同上场景 → POST `/correct` ignore | 该 extracted entity.status='deleted'；event 仍保存成功；entity_correction.action='ignore' |
| **E-W3-04 事件详情纠偏** | 录会议纪要 → 改关联类型 + 补承诺 + 改待办 | `EventCorrectResponse` 5 字段更新；entity_correction 4 行（entity+todo+promise+association）；TS 类型断言通过 |
| **E-W3-05 聚合视图** | E-W3-01/02/03 跑完后 GET `/aggregations?days=1` | 返回 `{entity, select_existing/count:1, entity/create_new/count:1, entity/ignore/count:1}`；零原文字段 |
| **E-W4-01 同义词规范化建议** | 用户 A 已有「沈书白 / 澄海生物」 → 录「沈书白老师」（同义表含别名） | EntityResolution 命中 synonym_match 0.97；action=CONFIRM；DB entity 数不变；ResolutionResult.explanation 含 "synonym" |
| **E-W4-02 difflib 80% 命中** | 用户录「陈子昂」（已有「陈子昂」实体） | 命中 difflib_match 0.99 → CONFIRM；user 拒绝后 entity 数不变 |
| **E-W4-03 3/90 天高频共现** | 录 3 个不同事件：A+B 共现 | 3 个 event pipeline 跑完 → `GET /entities/A/frequent-contacts` 含 B + count=3 + last_seen |
| **E-W4-04 2 次不触发** | 录 2 个事件：A+B 共现 | Step10b 跑完 → A.properties.frequent_contact 不存在或 count<3 |
| **E-W4-05 跨 91 天不触发** | 录 3 个事件：A+B 共现，最后一个 91 天前 | Step10b 跑完 → 不触发 |
| **E-W4-06 同事件去重** | 同一事件被 retry 3 次 | 共现 count=1；不重复触发 |
| **E-W4-07 跨用户隔离** | 用户 A 录事件 + 用户 B 同名 entity | user A `/aggregations` 仅自己；user B 的 entity 不出现在 A 候选 |

---

## 5. 门禁与退出标准

| 门禁 | 标准 |
|---|---|
| **G1 实现完成** | U-W3-01..10、U-W4-01..14 全绿；I-W3-01..04、I-W4-01..05 全绿 |
| **G2 合入门禁** | ruff 0；mypy 0；全量回归 0 failed（基线 2035+ passed）；契约哈希不变；CHANGELOG/TECH_DEBT 同步 |
| **G3 发布门禁** | §4 e2e 7+ 场景全过 + 证据归档 `docs/e2e_evidence/w3w4_e2e/`；`contract-consistency` CI job PASS |
| **G4 文档同步** | CHANGELOG v1.1.x 新条目；TECH_DEBT 新增 TD-B16 (W3+W4 经验)；ROADMAP B4/L4 状态更新 |

---

## 6. 角色分工（DevSquad）

- **测试**：U/I/IX 全套用例设计；G3 e2e 脚本开发；BASELINE 裁决流程
- **编码**：W3/W4 全套实现；FR-W3-1 模型迁移；FR-W4-1/2/3/4/5 全组件
- **安全**：U-W3-02/07/08 PII 扫描；U-W4-07 规范化零自动合并红线；聚合零原文审计
- **运维**：U-W3-05/06 180d worker；U-W4-13 阈值配置；CI job 接线
- **PM**：§4 e2e 场景以真实用户旅程为准（同名候选 / 规范化候选 / 共现触发与不触发）
- **架构师**：FR-W3-2 事务原子性；FR-W4-3 规范化门槛设计
- **UI**：FR-W3-6 前端类型补字段（零 UI 改动）

---

## 7. 门禁与发布收尾检查清单

- [ ] `EntityCorrection` 表迁移在 SQLite + PostgreSQL 双库跑通
- [ ] 180d cleanup 在空库和有库分别不报错
- [ ] 同义词字典文件首次启动自动创建
- [ ] 共现 Step10b 跑全 pipeline 不破坏既有 step
- [ ] ruff 0
- [ ] mypy 0（如有引入新协议类型）
- [ ] 全量回归 0 failed
- [ ] 契约文档哈希未漂移
- [ ] e2e 真实用户场景全过
- [ ] 证据归档 `docs/e2e_evidence/w3w4_e2e/`
- [ ] CHANGELOG + TECH_DEBT + ROADMAP 同步
- [ ] 推送到 main 并触发 CI
