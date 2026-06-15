# PromiseLink 文档更新 v4.2/v2.3 — 全员Review会议材料

> **日期**：2026-06-04
> **版本**：PRD v4.2 + 技术设计 v2.3
> **触发**：李总v1.2建议融合 + DevSquad PM+Arch联合评审共识

---

## 一、变更概述

### 1.1 变更范围总览

| 维度 | 变更前 | 变更后 | 变更量 |
|------|--------|--------|--------|
| PRD版本 | v4.0 | **v4.2** | 10项增量更新 |
| 技术设计版本 | v2.2 | **v2.3** | 7项增量更新 |
| 新增功能定义 | 43项(F-01~F-43) | **48项(+F-44~F-48)** | +5项P0 |
| 新增数据表 | 4张 | **5张(+relationship_briefs)** | +1张 |
| 现有表字段变更 | 0张 | **3张(events/todos/entities)** | +11字段 |
| Pipeline步骤 | 7步 | **8步(+Step0+Step8)** | +2步 |
| API端点 | ~15个 | **+6个P0端点** | +6个 |
| Non-goals | 4项 | **8项** | +4项 |
| PoC退出条件 | 11项(3技术+8产品) | **14项(+3产品)** | +3项 |

### 1.2 变更驱动力

```
李总v1.2建议（外部输入）
    ↓
DevSquad PM+Arch 联合评审（内部消化）
    ↓
P0五项共识（筛选后的核心改进）
    ↓
PRD v4.2 + 技术设计 v2.3（文档落地）
    ↓
【当前阶段】全员Review达成共识（待完成）
    ↓
实施（预计2周/10工作日）
```

---

## 二、P0 五项详细变更说明

### P0-1: input_scope 输入分类器

**问题**：PoC把产品反馈、内部评审混入关系Todo，导致数据污染。

**方案**：
- 在Pipeline入口新增 Step 0 分类器
- 8种scope枚举，PoC启用前6种
- `partner_feedback` 和 `internal_review` 终止管线，不生成关系数据

**涉及文件**：
- PRD: §3.1 F-44 功能定义
- 技术设计: §3.1 events表新增字段 + §4.1 Step 0 + InputClassifier服务
- 代码: event_pipeline.py, services/input_classifier.py(新)

**工作量**：1天

**风险**：LLM分类准确率目标≥95%，需规则兜底

---

### P0-2: Promise 双向动作模型

**问题**："制作PoC"被错误归为许总承诺（实际是林总的承诺）。

**方案**：
- Todo模型新增 action_type/promisor_id/beneficiary_id/confirmation_status/evidence_quote
- 5种责任类型：self_commitment/their_promise/my_followup/mutual_action/system_reminder
- 对方承诺不进我的Todo，显示为"等待对方回应"

**涉及文件**：
- PRD: §3.1 F-45 功能定义
- 技术设计: §3.1 todos表新增字段 + §4.1 Step 5改造 + Prompt模板更新
- 代码: todo_generator.py(_extract_promises重写), models/todo.py, prompts/todo_generation.py

**工作量**：1.5天

**风险**：LLM准确区分promisor和beneficiary是最大技术难点

---

### P0-3: Todo 降噪规则

**问题**：7个事件输出24条Todo，用户无法判断重点。

**方案**：
- 单场会议默认≤3条正式Todo（按urgency排序截断）
- Concern/NeedInsight/Contribution不自动生成Todo
- 仅用户确认后的Promise才生成首页优先Todo

**涉及文件**：
- PRD: §3.1 F-46 功能定义
- 技术设计: §4.1 Step 5 过滤逻辑
- 代码: todo_generator.py(generate_todos添加截断逻辑)

**工作量**：0.5天

**风险**：低，纯业务逻辑

---

### P0-4: RelationshipBrief 关系推进卡

**问题**：缺少关系全貌页面，用户看不到"对方关心什么→我承诺了什么→下一步是什么"。

**方案**：
- 新增 relationship_briefs 独立表（17个字段）
- 12模块标准视图（当前阶段/最近交流/对方关注/需求洞察/我方可提供帮助等）
- API: GET /persons/{id}/relationship-brief + PATCH /stage

**涉及文件**：
- PRD: §3.1 F-47 功能定义 + §5.8首页设计
- 技术设计: §3.1 新增DDL + §7.1 新增API + §4.1 Step 8
- 代码: models/relationship_brief.py(新), api/v1/relationship_briefs.py(新), services/brief_service.py(新)

**工作量**：2天

**风险**：低，全新模块不影响现有功能

---

### P0-5: RelationshipStage 关系阶段

**问题**：只有"多久没联系"，没有"关系走到哪一步"。

**方案**：
- 7阶段枚举一次性定义完整（避免后续迁移）
- PoC仅启用前3阶段(new_connection → understanding_needs → value_response)
- RS-01硬编码：阶段不可仅由AI自动升级，必须用户确认
- 复用现有todo_state_machine.py的VALID_TRANSITIONS模式

**涉及文件**：
- PRD: §3.1 F-48 功能定义
- 技术设计: §4.6b RelationshipStage状态机(新增章节) + entities.properties更新
- 代码: services/relationship_stage_machine.py(新), api/v1/stages.py(新或集成)

**工作量**：0.5天

**风险**：低，复用已有模式

---

## 三、其他重要变更

### 3.1 Slogan 更新

| 场景 | 旧Slogan | 新Slogan |
|------|---------|---------|
| 产品内部/小程序启动页 | 让重要的人，不止停留在微信里 | **让每一次连接，都有回应。** |
| 路演PPT封面/对外传播 | （同上） | 保持旧slogan（更有画面感） |

理由：新slogan更精准描述产品核心动作（"回应"），旧slogan传播力更强。

### 3.2 F-05 商机匹配度暂停

- 从PoC必做(✅)改为移至Phase2(❌)
- Phase2重新启用条件：≥30次回应记录 / ≥20条稳定能力 / ≥10个明确需求
- 这是**产品纪律**的体现，不是能力不足

### 3.3 Non-goals 补充

新增4项明确排除：
1. 商机匹配引擎（首期暂停）
2. 关系图谱作为主展示（推进卡为主）
3. 竞对风险主动推送（Phase2+）
4. 批量名片商机发现（与定位冲突）

### 3.4 首页改版

从"5区域信息展示型"改为"双核心区域回应驱动型"：
- 区域1：今天需要我回应的连接
- 区域2：最近值得推进的连接
- 移除人脉推荐（与定位冲突）

### 3.5 自建小程序前端备选方案

**触发条件**（满足任一即启动）：
1. 许总团队确认2周内无法启动前端开发
2. 数字名片API对接评估超过3周无结论
3. 种子用户测试需要独立前端环境

**技术栈**：Taro 3.x + Vue3 + NutUI 4.x
**MVP 5页**：首页 / 录入 / 人物详情(推进卡) / Todo列表 / 设置
**开发周期**：2-3周

### 3.6 PoC退出条件增强

新增3项产品指标：
- 承诺兑现闭环验证率 ≥50%（替代原"资源线索确认率"）
- 4周持续使用率 ≥60%
- 输入分类准确率 ≥95%
- 承诺责任人识别准确率 ≥90%

---

## 四、决策点清单（需Review确认）

### 必须决策（Blocking）

| # | 决策项 | 选项A（推荐） | 选项B | 风险 |
|---|--------|-------------|-------|------|
| D-1 | **P0五项全部采纳？** | ✅ 全部采纳 | 部分延后 | 延后影响PoC闭环验证 |
| D-2 | **RelationshipStage启用几个阶段？** | PoC用3阶段 | PoC用5阶段 | 5阶段对种子用户过复杂 |
| D-3 | **自建小程序是否现在启动？** | 先准备方案，等触发条件 | 立即并行开发 | 资源分散 |
| D-4 | **TTS保持全量还是降级？** | 全量（许总刚需） | 降级为轻量演示 | 许总体验受损 |
| D-5 | **给李总的回复是否按此口径？** | 四段式（感谢+采纳+保留TTS+时间表） | 调整措辞 | 沟通效果 |

### 建议决策（非Blocking，可会后确认）

| # | 决策项 | 推荐方案 | 备注 |
|---|--------|---------|------|
| D-6 | NeedInsight独立表 vs JSONB | PoC用JSONB，Phase1拆表 | WORKBUDDY定稿已确认 |
| D-7 | input_scope用LLM还是规则引擎 | LLM为主+规则兜底 | 准确性优先 |
| D-8 | 推进卡先用Swagger UI还是等小程序 | Swagger UI先验证API | 不阻塞后端开发 |
| D-9 | Sprint排期 | Sprint0(2天冻结)+Sprint1(5天P0)+Sprint2(5天推进卡+阶段)+验证 | 李总原文估算一致 |

---

## 五、待确认事项（Open Questions）

| # | 问题 | 提出者 | 影响 | 建议 |
|---|------|--------|------|------|
| Q-1 | 许总团队前端进展如何？是否已开始首页开发？ | WORKBUDDY定稿 | 决定首页改版时机 | 需本周内确认 |
| Q-2 | 陈宇欣团队名片API开发时间表？ | WORKBUDDY定稿 | 影响数据导入策略 | 通过许总推动 |
| Q-3 | PoC首批种子用户每人每周产生多少记录？ | 产品侧 | 影响性能容量规划 | 保守估计3-5条/周 |
| Q-4 | 许总是否认同杀手场景"别忘了我已经知道的"？ | 产品侧 | 影响价值主张表述 | 已在WORKBUDDY定稿中确认 |
| Q-5 | 是否需要同时更新 CarryMem 的记忆类型配置？ | 架构侧 | NeedInsight是否纳入CarryMem | 建议：暂不，PromiseLink先独立验证 |

---

## 六、实施计划草案

```
Week 1 (2026-06-04 ~ 06-10):
├── Day 1-2:   Sprint 0 - 冻结方向 + 回归测试集建立
│               · 基于v1.2 §1.3 的5个PoC错误构建回归用例
│               · 确认API契约不变（仅增量新增）
│
├── Day 3-4:   Sprint 1 Part A - input_scope + Promise双向
│               · InputClassifier 服务实现
│               · todo_generator.py _extract_promises() 重写
│               · Prompt 模板更新
│
├── Day 5:     Sprint 1 Part B - Todo降噪
│               · generate_todos() 截断逻辑
│               · scope 过滤规则
│
└── Day 6-7:   集成测试 + 修复

Week 2 (2026-06-11 ~ 06-17):
├── Day 8-9:   Sprint 2 Part A - RelationshipBrief 推进卡
│               · relationship_briefs 表 + Model + Service
│               · API 端点实现
│               · Pipeline Step 8 集成
│
├── Day 10:    Sprint 2 Part B - RelationshipStage
│               · 状态机实现
│               · entities.properties 更新
│               · 阶段确认 API
│
├── Day 11-12: Dashboard API + 首页数据聚合
│
├── Day 13:    集成测试 + E2E回归验证
│
└── Day 14:    代码走查 + 文档同步 + 给李总发回复

Week 3 (可选):
└── Sprint 3: 种子用户真实数据验证
```

---

## 七、相关文档索引

| 文档 | 路径 | 状态 |
|------|------|------|
| PRD v4.2（本次更新） | `docs/spec/PRD_V1.md` | ✅ 已更新 |
| 技术设计 v2.3（本次更新） | `docs/architecture/PromiseLink_技术设计_v1.md` | ✅ 已更新 |
| 李总v1.2原文 | `docs/external/for_李总/PromiseLink_PoC技术整改与产品演进建议_v1.2_融合分形宇宙外部合作SOP .md` | 输入参考 |
| WORKBUDDY定稿 | `docs/external/for_team/PromiseLink_李总v1.2审阅_产品定位定稿_2026-06-04.md` | 输入参考 |
| DevSquad评审报告 | `docs/internal/PromiseLink_李总v1.2_DevSquad_PM_Arch_评审报告.md` | ✅ 已生成 |
| **本Review材料** | `docs/internal/PromiseLink_文档更新v4.2_v2.3_全员Review会议材料.md` | 📝 本文档 |

---

> **下一步**：请各角色审阅上述变更，在Review会议上对D-1~D-9决策点投票。达成共识后立即启动Sprint 0。
