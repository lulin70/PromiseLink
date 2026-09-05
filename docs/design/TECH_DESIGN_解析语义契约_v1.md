# 技术设计 — 解析语义契约与黄金基准集（W1+W2）

> **版本**: v1.0
> **日期**: 2026-09-05
> **PRD**: [PRD_解析语义契约_v1.md](../spec/PRD_解析语义契约_v1.md)（已批准，裁决②双层 CI）
> **门禁**: DevSquad 七角色评审（本文档末尾评分）

---

## 1. 事实基础（查证于代码库，2026-09-05）

| # | 事实 | 位置 |
|---|---|---|
| F1 | 实体属性 Pydantic schema：`EntityProperties`/`BasicInfo`/`ConcernItem`/`CapabilityItem` | `src/promiselink/schemas/entity_properties.py` |
| F2 | ORM 模型：`Event` / `Entity` / `Todo`（Promise 复用 todos 表逻辑视图） | `src/promiselink/models/{event,entity,todo}.py` |
| F3 | 解析 prompt 模板 ×2（名片/会话），内嵌 concern/capability 受控词表各 10 词 | `src/promiselink/prompts/entity_extraction.py` |
| F4 | 解析输出结构 dataclass：`ExtractionResult`（persons/keywords/summary/events/confidence_level/requires_confirmation） | `src/promiselink/services/entity_extractor.py:63` |
| F5 | 输入分类枚举 `InputScope` 8 类 | `src/promiselink/services/input_scope_classifier.py:23` |
| F6 | CI jobs：test / playwright-ui / frontend / security / build-and-push | `.github/workflows/ci.yml` |
| F7 | 日志风格：`logger.info("event_name", **kv)` 结构化键值 | `entity_extractor.py` 等 |

## 2. 架构决策

| # | 决策 | 理由 |
|---|---|---|
| D1 | **契约权威源 = 五个代码事实**（F1-F5），文档由脚本生成 | 单一事实源防漂移（TD-044 教训）；五源覆盖 Ontology 五节 |
| D2 | **契约版本 = 运行时内容哈希**（sha256 前 12 位，对五源规范化后计算），不落独立文件 | 无第三处状态可漂移；运行时计算 <10ms |
| D3 | **黄金集 LLM 模式不走 pipeline 入库**，直接 `LLMClient` + prompt 模板 → 结构 diff | pipeline 需 DB/全量依赖；基准只测「文本→结构」这一契约核心 |
| D4 | **push 层 CI = Mock 模式**（用例合法性 + 期望结构 schema 校验 + 契约哈希 diff），零 LLM 成本 | 裁决②「每次推送」与成本的正解 |
| D5 | 契约哈希注入 `extract_started` 日志（F7 风格加一键值） | NFR：一行改动，可对齐排查 |

## 3. 组件设计

### 3.1 `scripts/generate_semantic_contract.py`（FR-1）

```
输入（五源，全部 import 真实代码）：
  S1 schemas.entity_properties.*      → §属性
  S2 models.{event,entity,todo} 列定义 → §概念（Class）+ §属性(存储字段)
  S3 prompts.entity_extraction 受控词表 → §约束（正则解析「受控词表」行）
  S4 services.input_scope_classifier.InputScope → §枚举
  S5 services.entity_extractor.ExtractionResult → §概念(输出契约)
处理：
  各源 → 规范化文本（字段名:类型:排序）→ sha256_12 = contract_version
  模板渲染 Markdown，生成段包 <!-- generated:do-not-edit:v={hash} --> 包裹
输出：
  stdout（默认，供 CI diff）或 -o 覆盖写入 docs/spec/PARSING_SEMANTIC_CONTRACT.md 的生成段
```

人工「语义说明」段：文档中 `<!-- human-section -->` 标记区间，脚本覆盖时保留。

### 3.2 `docs/spec/PARSING_SEMANTIC_CONTRACT.md`（FR-2）

结构：元信息（版本=哈希）→ §1 概念 → §2 属性 → §3 关系 → §4 约束 → §5 枚举 → §6 语义说明（人工）。关系节由 S2 外键/关联 + S4 映射表生成。

### 3.3 `tests/golden/`（FR-4）

```
tests/golden/
  cases/
    must_extract/*.json   (≥15)
    must_not/*.json       (≥5)
    ambiguous/*.json      (≥10)
  case_schema.py          # GoldenCase Pydantic 模型（用例合法性）
  test_golden_baseline.py # 跑器
  synthetic_names.py      # 虚构名池（PII 红线：只用虚构名）
```

GoldenCase schema：`{id, layer, input_text, expected: {persons[], todos[], promises[], must_not_extract: bool, expect_confirmation: bool}}`。`ambiguous` 层断言 `requires_confirmation=True`（对齐 F4），不断言唯一答案。

### 3.4 跑器（FR-5，D3/D4）

- **Mock 模式**（默认）：校验全部用例过 `GoldenCase` 模型 + `expected` 可被 `EntityProperties` 校验 + 契约哈希与文档一致 → CI push 层
- **LLM 模式**（`GOLDEN_RUN_LLM=1`）：`LLMClient` + `TEMPLATE_2_CONVERSATION_EXTRACTION` 逐条解析 → 字段级 diff 报告（ persons 数 / 姓名 / concern / capability / confidence_level）；通过率写入 `tests/golden/BASELINE.md`
- 层级通过率独立统计；`ambiguous` 层只看 `requires_confirmation` 命中率

### 3.5 CI job（FR-3，双层）

```yaml
# push 层（加进现有 test workflow，<30s）
contract-consistency:
  steps:
    - run: python scripts/generate_semantic_contract.py > /tmp/contract.md
    - run: diff /tmp/contract.md docs/spec/PARSING_SEMANTIC_CONTRACT.md

# 基准层：workflow_dispatch + schedule(weekly)，GOLDEN_RUN_LLM=1，结果 artifact 归档
```

### 3.6 日志字段（FR-6，D2/D5）

`entity_extractor.extract_started` 增加 `contract_version=<hash>`；哈希计算函数放 `promiselink/core/contract.py`（供脚本与运行时共用，避免双实现）。

## 4. 数据流（e2e 视角）

```
录入文本 ─→ EntityExtractor(含 contract_version 日志) ─→ ExtractionResult
                ↑ prompt(受控词表=S3)                        │
契约文档 ←── 生成脚本 ←── S1-S5 代码事实 ──────────────────┘
    ↑ CI diff（push 层）        黄金集 diff（基准层）
```

## 5. 风险与对策

| 风险 | 对策 |
|---|---|
| 受控词表正则解析脆弱（S3 是中文自由文本） | 词表行改为代码常量（prompt 模板用 format 注入），既稳定又消除 prompt 内重复 |
| LLM 基准波动导致 CI 基准层假失败 | 基准层不阻塞合入（informational），基线对比报告人工裁决 |
| 生成脚本 import 模型触发 DB 连接 | 只 import 模型类不建 engine；models 模块无副作用导入（已验证 import 路径） |

## 6. 七角色门禁评分

| 角色 | 意见 | 评分 |
|---|---|---|
| 架构师 | D2 运行时哈希优于版本文件（零漂移）；3.5 词表常量化是隐藏收益 | 9 |
| PM | 范围收敛不越界（不改解析行为）；M1-M4 对齐 PRD | 9 |
| 安全 | 虚构名池 + PII 扫描进 CI；LLM 模式显式 opt-in 已设计 | 9 |
| 测试 | ambiguous 断言 requires_confirmation 对齐 F4 事实；基准层 informational 不阻塞正确 | 9 |
| 编码 | 组件粒度合适；contract.py 共用避免双实现 | 9 |
| 运维 | push 层 <30s 可达（纯 import+哈希+diff）；job 归属 test workflow 合理 | 9 |
| UI | 零 UI 变更，确认无影响 | 9 |

**门禁结论：PASS（7/7），进入测试计划与实现。**
