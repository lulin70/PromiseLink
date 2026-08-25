# 事件解析管线可靠性设计方案（13 步整理 + LLM 分级重试）

* 日期：2026-08-16

* 状态：P1（LLM 分级重试 flash→pro + 分级 timeout）已实现（2026-08-16）；单测见 tests/test\_llm\_client.py（42 用例）；P2/P3 见 §5 建议清单

* 关联：commit 975e40c（LLM 空 content 修复）；docs/design/Duplicate\_Entity\_Manual\_Handling\_2026-08-16.md

## 1. 13 步管线现状整理

管线定义：src/promiselink/services/event\_pipeline.py；关键性分级：step\_13\_complete.py（CRITICAL\_STEPS）。

| #  | 步骤                         | LLM                | 关键性 | 失败影响      | 现有降级策略                                                                  |
| -- | -------------------------- | ------------------ | --- | --------- | ----------------------------------------------------------------------- |
| 01 | VerifyEvent（验证/标题/scope）   | 分类规则优先，LLM 兜底      | 关键  | 事件 failed | 规则命中即不调 LLM（classify\_rule\_hit）                                        |
| 02 | ExtractEntities（实体提取+解析合并） | ✅ Template 2       | 关键  | 事件 failed | LLM 失败→0 人提取→failed（无降级，靠 retry）                                        |
| 03 | SemanticEmbedding（事件向量）    | 否（本地 embedding）    | 非关键 | 跳过        | 语义搜索缺失该事件                                                               |
| 04 | TodoGeneration（待办生成）       | ✅ Template 3/11/12 | 关键  | 事件 failed | LLM 失败→规则兜底提取 promise/care 关键词（\_PROMISE\_KEYWORDS 等）；全部被去重=成功（975e40c） |
| 05 | PromiseAnalysis（承诺双向）      | ✅                  | 关键  | 事件 failed | 规则匹配兜底（rule\_based\_match）                                              |
| 06 | ResourceOveruse（资源滥用）      | 否                  | 非关键 | 跳过        | 无该提醒                                                                    |
| 07 | PriorityScoring            | 否                  | 非关键 | 默认分       | —                                                                       |
| 08 | Notification               | 否                  | 非关键 | 无通知       | wechat\_not\_configured 静默                                              |
| 09 | MemoryStorage              | 否                  | 非关键 | 跳过        | null\_memory\_store\_skipped                                            |
| 10 | AssociationDiscovery       | 否（规则+图计算）          | 非关键 | 无新关联      | 跳过 merged/deleted 墓碑（975e40c）                                           |
| 11 | AssociationTodos（关联→待办）    | 否（规则）              | 非关键 | 无关联待办     | 事务内防重（975e40c）                                                          |
| 12 | RelationshipBrief（关系简报）    | ✅                  | 非关键 | 简报缺失      | 事件仍 completed/degraded                                                  |
| 13 | CompleteEvent              | 否                  | —   | —         | 关键步失败→failed；否则 degraded\_completed                                     |

**结论**：用户可感知的"解析失败"（事件红色 failed）只来自 4 个关键步（01/02/04/05），其中 02 实体提取是最高风险点（无降级路径）；04/05 已有规则兜底，实际失败概率低。

## 2. 失败根因分析（基于 2026-08-16 真实日志）

| 根因                                                | 证据                                                                                                  | 占比判断                        | 状态                                                                |
| ------------------------------------------------- | --------------------------------------------------------------------------------------------------- | --------------------------- | ----------------------------------------------------------------- |
| **空 content**（推理模型 reasoning 耗尽 max\_tokens=4000） | tokens\_used=5114、finish\_reason=length、content=""、`conversation_extraction_failed: Empty response` | **主因**（当日 3 次 step02 失败均此因） | ✅ 已修复（975e40c）：抛 LLMEmptyContentError → 重试翻倍 max\_tokens（上限 8192） |
| **缓存污染**（空响应被 Redis/内存缓存 24h）                     | 同 prompt 二次事件必失败                                                                                    | 放大器                         | ✅ 已修复：空内容不写缓存 + 命中脏条目删除                                           |
| timeout                                           | 当日无（最长 34s < 60s）                                                                                   | 低；pro 模型可能触发                | 需按模型分级（见 §4）                                                      |
| JSON 格式漂移                                         | 偶发（extract\_json\_from\_text 三级兜底已较强）                                                               | 低                           | P2 结构化输出                                                          |

**回答用户问题**：

1. "改用 deepseek-v4-pro 能否提升提取效果？"——能提升（pro 指令遵循与结构化输出更稳、reasoning 更可控），但**不能确保 100%**；且 pro 更慢（长文本可能超 60s timeout）更贵，全量切换性价比低。
2. "flash 失败后重试升级 pro 能否确保成功？"——**可行且推荐**（分级重试/escalation 是标准模式），将失败率从"重试仍可能同因失败"降为"换更强模型后大概率成功"；残余失败由 degraded 状态 + 已有"重新处理"按钮兜底，不能承诺绝对成功。
3. "是 timeout 问题吗？"——**不是**。实测失败均为空 content（reasoning 耗尽），34s 远小于 60s timeout。

## 3. "重新解析"现状

后端与前端**均已存在**，无需新建：

* 后端：`POST /api/v1/events/{event_id}/retry`（event\_pipeline\_api.py:174），仅 failed/awaiting\_retry 可用；重置为 pending 后**全量重跑 13 步**

* 前端：事件列表"重新处理"按钮（events/index.tsx:455，failed 状态显示）；录入页 awaiting\_retry 降级选择（input/index.tsx:666）

全量重跑的安全性（已具备）：实体 exact/fuzzy 合并幂等（不产生重复人脉）+ 待办跨事件去重（不产生重复待办）——2026-08-16 e2e 已验证。代价是重复消耗已成功步骤的 LLM 调用（一次约 4-6 次 LLM 请求）。

**建议维持全量重跑**（简单可靠），续跑优化列为 P3（管线目前无步骤级断点快照，引入复杂度不值得）。

## 4. LLM 分级重试设计（P1，本期推荐实现）

### 4.1 配置

```
# .env
LLM_MODEL=deepseek-v4-flash            # 首选（快/便宜）
LLM_FALLBACK_MODEL=deepseek-v4-pro     # 升级重试用（不配则不升级）
LLM_FALLBACK_AFTER_ATTEMPTS=3          # 第 3 次尝试起用 fallback 模型
LLM_TIMEOUT=60                         # flash 超时
LLM_FALLBACK_TIMEOUT=120               # pro 超时（推理更深）
```

### 4.2 LLMClient 改动（src/promiselink/services/llm\_client.py）

* `Settings` 增加 4 个字段（含默认值，向后兼容）

* `_call_with_retry` 循环中：

  * `attempt >= fallback_after_attempts 且 fallback_model 已配置` → 本次请求 model 切为 fallback、timeout 切为 fallback\_timeout

  * 与既有空 content 翻倍逻辑叠加：attempt1 flash(4000) → attempt2 flash(8000) → attempt3 pro(8000+) → attempt4 pro(8192)

  * fallback 成功结果缓存在主模型 key 下，同 prompt 后续请求直接命中，避免重复升级成本

* 日志：`llm_call_completed` 增加 `tier` 字段（primary/fallback），便于统计升级触发率与增益

### 4.3 成本控制

* pro 仅在 flash 连续 2 次失败后启用，正常流量成本不变

* 升级触发率进入 admin 监控（bridge/admin API 现有指标体系追加 `llm_fallback_rate`）

### 4.4 可观测性（P1 同批）

* 事件维度：`events.failed_steps` 前端已有；追加失败原因人话翻译（"AI 提取超时/返回异常，已自动重试 N 次"）展示于事件详情与"解析失败"卡片，消除用户困惑

* LLM 维度：按 (step, error\_code) 统计失败率，日志结构化字段已具备

## 5. 建议清单（优先级汇总）

| 级别 | 项                                                                | 状态/工作量                   |
| -- | ---------------------------------------------------------------- | ------------------------ |
| P0 | 空 content 抛错重试 + max\_tokens 翻倍 + 缓存防污染                          | ✅ 已完成（975e40c），单测 5 例    |
| P1 | LLM 分级重试（flash→pro）+ 分级 timeout                                  | 本方案 §4，约 1 天含测试          |
| P1 | 解析失败原因人话展示（事件详情/列表卡片）                                            | 前端小改 + failed\_steps 映射表 |
| P2 | DeepSeek `response_format=json_object` 结构化输出（Template 2/3/11/12） | 提示词需微调；进一步压低 JSON 漂移     |
| P2 | max\_tokens 基线从 4000 提至 6000（reasoning 预算前移）                     | 配置项验证后调整                 |
| P3 | 失败步骤级续跑（断点快照）                                                    | 复杂度高收益小，暂缓               |
| P3 | 04/05 步 LLM 失败时明确标注"规则兜底结果"（UI 角标）                               | 待确认产品口径                  |

## 6. 测试计划（P1 项）

### 6.1 单元测试（tests/test\_llm\_client.py 追加）

| 用例                                 | 断言                                 |
| ---------------------------------- | ---------------------------------- |
| attempt<3 用 flash；attempt≥3 切 pro  | post payload 的 model 字段按序变化        |
| 未配置 fallback\_model                | 全程 flash，不报错                       |
| pro 请求 timeout 用 fallback\_timeout | 请求超时参数 120                         |
| 升级后成功                              | 返回内容正确、tier=fallback 记日志           |
| 缓存 key 模型隔离                        | flash 命中不误用 pro 缓存（现逻辑天然满足，加防回归断言） |

### 6.2 E2E

* 构造长 reasoning 文本录入 → 观察 tier 升级 → 事件 completed

* 人为只配 pro（flash 故障模拟：错误 key 分环境）→ 全量走 pro 成功

### 6.3 观测验收

* 本地跑 20 次录入（含长/短/模糊文本），事件 failed 率 = 0、fallback 触发率有日志可查

