# 测试计划 — 解析语义契约与黄金基准集（W1+W2）

> **版本**: v1.0
> **日期**: 2026-09-05
> **PRD**: [PRD_解析语义契约_v1.md](../spec/PRD_解析语义契约_v1.md) · **技术设计**: [TECH_DESIGN_解析语义契约_v1.md](../design/TECH_DESIGN_解析语义契约_v1.md)

---

## 1. 测试策略总览

| 层 | 对象 | 方式 | 触发 |
|---|---|---|---|
| 单元 | contract.py 哈希 / 生成脚本各节渲染 | pytest，纯函数断言 | 每次推送 |
| 契约 | 契约文档与五源一致性 | 生成脚本 diff | 每次推送（CI push 层） |
| 基准-Mock | 黄金集用例合法性与结构可解析性 | pytest tests/golden（无 LLM） | 每次推送 |
| 基准-LLM | 真实解析 vs 黄金标注字段级 diff | GOLDEN_RUN_LLM=1 | 手动 / 每周（informational） |
| 回归 | 全量既有套件 | pytest | 每次推送 |
| e2e | 模拟真实用户录入 → 契约校验 | 见 §4 | 发布前手动 |

## 2. 单元测试清单（contract.py + 生成脚本）

| # | 用例 | 断言 |
|---|---|---|
| U1 | 哈希稳定性 | 同输入两次计算哈希一致 |
| U2 | 哈希敏感性 | 修改 EntityProperties 任一字段名 → 哈希变化 |
| U3 | 哈希覆盖五源 | 仅改受控词表 → 哈希变化；仅改 InputScope → 哈希变化 |
| U4 | 生成段机器标记 | 输出含 `generated:do-not-edit` 与哈希 |
| U5 | 人工段保留 | 文档含 human-section 标记时重生成，人工内容不丢 |
| U6 | 渲染五节齐全 | 概念/属性/关系/约束/枚举五节标题存在 |
| U7 | 受控词表常量注入 | prompt 渲染后词表与常量一致（20 词） |

## 3. 黄金集测试设计

### 3.1 三分层验收口径

| 层 | 断言 | 通过口径 |
|---|---|---|
| must_extract | persons≥1 且指定字段命中 | 字段级 diff 全绿 |
| must_not | persons==0 且无 todo/promise 产出 | 全绿 |
| ambiguous | requires_confirmation==True（对齐 ExtractionResult 事实） | 命中率 ≥ 基线 |

### 3.2 合成数据规范（PII 红线）

- 人名：`synthetic_names.py` 虚构名池（如"陈子昂""林晚秋"——非真实公众人物组合）
- 公司/电话/邮箱：明显伪造格式（`example-corp-01`、`138-0000-0001`）
- CI security job 复用现有扫描 + 新增 golden 目录 PII 关键词扫描（手机号/邮箱正则零命中，0000/1234 段白名单）

### 3.3 基线管理

- 首次 LLM 全量跑 → 结果记入 `tests/golden/BASELINE.md`（整体/分层通过率 + 日期 + DeepSeek 版本）
- 之后每次 LLM 基准与 BASELINE 对比：下降字段在报告中高亮，由人工裁决是否接受（模型升级的正常波动）或回退 prompt

## 4. e2e — 模拟真实用户录入走契约校验（发布前必跑）

```
场景：用户在录入页粘贴一段 5 人会议纪要 → 保存事件 → pipeline 完整执行
校验：
  E1 日志含 contract_version 且与契约文档一致
  E2 解析产出可被 EntityProperties 校验（契约核心闭环）
  E3 多候选人脉场景触发 requires_confirmation（纠偏入口可达）
  E4 4 类详情页互跳数据完整（关联未断）
执行方式：本地起基础版（localhost:8000）+ 浏览器脚本模拟录入；不依赖 Pro 网关
归档：截图 + 日志摘录 → docs/e2e_evidence/semantic_contract_w1w2/
```

## 5. 门禁与退出标准

| 门禁 | 标准 |
|---|---|
| G1 实现完成 | U1-U7 全绿；golden Mock 模式全绿 |
| G2 合入门禁 | ruff 0；全量回归 0 failed（基线 2035+ passed）；CI push 层 contract-consistency PASS |
| G3 发布门禁 | §4 e2e 四项全过 + 证据归档；BASELINE.md 首次落档 |
| G4 文档同步 | CHANGELOG 新增条目；PRD/技术设计/测试计划状态字段更新 |

## 6. 角色分工（DevSquad）

- 测试：§2/§3 用例设计与 BASELINE 裁决流程
- 编码：contract.py / 生成脚本 / 跑器实现
- 安全：PII 扫描规则与红线复核
- 运维：CI job 接线与耗时验证
- PM：e2e 场景以真实用户旅程为准（§4 已按 §5.18 录入流程设计）
