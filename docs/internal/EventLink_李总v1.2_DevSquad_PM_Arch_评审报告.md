# PromiseLink 李总v1.2建议 — PM+Architect 联合深度评审报告

> **报告编号**: DS-REV-2026-012
> **评审方法**: DevSquad MultiAgentDispatcher（Mock模式 + 人工深度分析）
> **参与角色**: Product Manager + Architect（Consensus共识模式）
> **评审日期**: 2026-06-04
> **输入材料**:
> - 李总v1.2原文：`docs/external/for_李总/PromiseLink_PoC技术整改与产品演进建议_v1.2_融合分形宇宙外部合作SOP .md`
> - WORKBUDDY定稿：`docs/external/for_team/PromiseLink_李总v1.2审阅_产品定位定稿_2026-06-04.md`
> - 当前PRD：`docs/spec/PRD_V1.md` (v4.0)
> - 技术设计：`docs/architecture/PromiseLink_技术设计_v1.md` (v2.2)
> - 源代码：`src/promiselink/` 全部模块

---

## 一、执行摘要

### 1.1 总体评价

| 维度 | PM评分 | Arch评分 | 共识 |
|------|--------|----------|------|
| **文档质量** | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | **优秀** — 基于真实PoC数据，问题定位精准 |
| **建议可行性** | ⭐⭐⭐⭐ | ⭐⭐⭐ | **良好** — P0五项可行，部分中后期建议需裁剪 |
| **与现有架构兼容性** | — | ⭐⭐⭐ | **中等** — 需要适度重构但不伤筋骨 |
| **PoC阶段适配度** | ⭐⭐⭐⭐ | ⭐⭐⭐ | **良好** — 核心建议聚焦解决已暴露问题 |

### 1.2 核心结论

**李总v1.2是PromiseLink目前收到的最有价值的外部建议文档。** 其核心价值不在于引入SOP全流程，而在于：

1. 用**真实PoC错误数据**（7事件→24条Todo、承诺错配、资料混流）验证了产品设计的薄弱环节
2. 提出了**结构化的解决方案**（input_scope分类、Promise双向动作、Todo降噪），而非泛泛的建议
3. 明确了**首期边界**（只做关系回应闭环，不做合作执行SOP），避免了范围蔓延
4. 与WORKBUDDY定稿文档的结论**高度一致**（5项P0、商机匹配暂停、定位不变）

---

## 二、逐项评审：PM视角

### 2.1 产品定位一致性检查

**评审项**：v1.2建议是否偏离"AI驱动的个人商务关系经营助手"定位？

| 检查点 | v1.2表述 | 是否偏离 | 判定 |
|--------|----------|----------|------|
| 核心原则 | "先成就关系，再促成合作；让每一次连接，都有回应" | ❌ 不偏离 | ✅ 完全一致 |
| 首期闭环 | Interaction→Concern→NeedInsight→Promise→Contribution→Todo→Feedback→RelationshipStage | ❌ 不偏离 | ✅ 利他优先 |
| SOP借鉴声明 | "首期不能把整个SOP都做成产品功能" | ❌ 不偏离 | ✅ 自我约束清晰 |
| 数据主权 | 未在v1.2中弱化数据主权 | ❌ 不偏离 | ✅ 默认继承 |
| 商机匹配 | §14.1明确"暂停" | ❌ 不偏离 | ✅ 与定位一致 |

**PM判定：✅ 采纳（无修改）**

> **理由**：v1.2全文未出现"资源匹配平台""撮合""价值评分"等偏移关键词。新增的NeedInsight和RelationshipStage都是围绕"关系经营"展开，而非"资源发现"。李总在§0明确写了产品核心原则，与PRD v4.0定位完全对齐。

### 2.2 NeedInsight vs 现有Care Todo重叠分析

**评审项**：NeedInsight是否应该作为独立模型，还是与现有Care Todo合并？

| 对比维度 | Care Todo（现有） | NeedInsight（v1.2新增） |
|----------|-------------------|------------------------|
| 定义 | "对方正在关心什么"（明确表达） | "对方可能需要解决的问题"（AI推断） |
| 来源 | 用户原话/明确提及 | 基于Concern的推理 |
| 生命周期 | → 可生成Todo | → 不生成Todo，仅候选 |
| 确认要求 | 用户确认后持久化 | 用户确认后才转Contribution/Promise |
| 示例 | "许总重视数据主权" | "合作前需要确认数据控制权" |

**重叠度分析**：

```
Care Todo (现有)          NeedInsight (v1.2)
    │                           │
    │  "对方关心X"               │  "对方可能需要解决Y"
    │  (事实提取)                 │  (推断生成)
    │         │                   │         │
    │         ▼                   │         ▼
    │   [关注] Todo ──────────────┘   进关系推进卡(不进Todo)
    │   (当前: 直接进Todo)             (v1.2: 先存候选)
```

**PM判定：✅ 有条件采纳（独立模型，但PoC轻量实现）**

> **理由**：
> - **必须区分**：Care是"对方说了什么"，NeedInsight是"对方可能需要什么"。混在一起会导致用户把AI推测当事实。
> - **WORKBUDDY定稿已确认**：NeedInsight作为P1项（轻量实现，存在RelationshipBrief JSONB，不做独立表）。
> - **工作量估计**：0.5-1天（PoC阶段存JSONB字段，Phase1再拆独立表）。
> - **条件**：NI-03规则必须严格执行——"NeedInsight不直接生成Todo"，否则又回到24条噪音的老路。

### 2.3 7阶段RelationshipStage vs PoC复杂度

**评审项**：7个阶段是否对PoC来说过于复杂？

| 阶段 | 英文值 | PoC是否需要 | 理由 |
|------|--------|-------------|------|
| 1 | `new_connection` | ✅ 是 | 初次记录互动时的默认状态 |
| 2 | `understanding_needs` | ✅ 是 | 已识别对方关注点后自然进入 |
| 3 | `value_response` | ✅ 是 | 用户确认并执行帮助/承诺 |
| 4 | `cooperation_exploration` | ⚠️ 边缘 | PoC可能触及，但非必须 |
| 5 | `intent_confirmed` | ❌ 否 | 需要双方正式确认，PoC太早 |
| 6 | `execution` | ❌ 否 | 执行协同属于Phase2 |
| 7 | `review` | ❌ 否 | 复盘属于Phase2 |

**PM判定：✅ 有条件采纳（PoC用3阶段，保留7阶段枚举定义）**

> **理由**：
> - PoC阶段用户关系数量有限（种子用户3-5人），前3阶段足够覆盖。
> - 但**枚举值应一次性定义完整**，避免后续数据库迁移。
> - RS-01规则（"阶段不可仅由AI自动升级"）是关键保护——必须硬编码到业务逻辑中。
> - **工作量估计**：0.5天（Person表加stage字段 + 简单校验逻辑）。

### 2.4 8种input_scope是否过度设计

**评审项**：8种input_scope分类对PoC是否过度？

| input_scope | PoC实际使用频率 | 是否必需 | 判定 |
|------------|-----------------|----------|------|
| `identity` | 高（名片扫描） | ✅ 必需 | 只更新身份，不生成Todo |
| `relationship_interaction` | 高（会议录入） | ✅ 必需 | 核心管线入口 |
| `meeting_minutes` | 中（纪要导入） | ✅ 必需 | 承诺证据来源 |
| `partner_feedback` | 低（李总建议本身） | ✅ 必需 | **防止污染的关键** |
| `internal_review` | 低（团队评审） | ✅ 必需 | **防止污染的关键** |
| `intent_document` | 极低（LOI等） | ⚠️ 可延后 | Phase1再做 |
| `execution_record` | 极低 | ❌ 暂不需要 | Phase2 |
| `result_record` | 极低 | ❌ 暂不需要 | Phase2 |

**PM判定：✅ 采纳（6种即可覆盖PoC，后2种预留枚举值）**

> **理由**：
> - 这不是过度设计，而是**解决PoC最严重问题的必要手段**。§1.3明确列出"输入材料混流"为当前最严重问题之一。
> - WORKBUDDY定稿评估为P0第1项（1天工作量），投入产出比极高。
> - 实现方式：在event_pipeline.py Step 1（语义路由）之前插入一个轻量分类器（可以是LLM调用或规则引擎）。
> - **关键收益**：一旦分类器到位，product_feedback和internal_review自动被路由到正确路径，不再污染关系卡。

### 2.5 首页改版价值评估

**评审项**：首页从"5区域"改为"今天需要我回应的连接 + 最近值得推进的连接"的价值？

| 维度 | 当前PRD §5.8.1首页 | 李总v1.2建议首页 |
|------|---------------------|------------------|
| 结构 | 顶部搜索 + 近期事件 + 优先Todo + 人脉推荐 + 底部导航 | "今天需要我回应" + "最近值得推进" |
| 核心信息 | 信息密度高，功能全 | 聚焦行动，降低认知负荷 |
| 目标用户 | 功能探索型用户 | 行动导向型用户（许总） |
| 开发成本 | 许总团队可能已开始 | 返工风险 |

**PM判定：✅ 有条件采纳（取决于许总团队前端进展）**

> **理由**：
> - 从产品逻辑上，新设计更符合"让每一次连接，都有回应"的核心Slogan。
> - 但WORKBUDDY定稿已标注风险："确认许总团队前端进展再定"。
> - **建议方案**：如果许总团队尚未开始首页开发→直接采用新设计；如果已开始→评估返工成本，可考虑双版本并行（旧版先上线，新版Sprint2切换）。
> - **工作量估计**：前端1-2天（如从零开始），返工0.5-1天（如已有原型）。

### 2.6 "暂停商机匹配"的商业判断

**评审项**：§14.1明确暂停商机匹配引擎——这个商业判断是否正确？

| 角度 | 分析 | 结论 |
|------|------|------|
| 定位一致性 | "关系经营助手" ≠ "资源撮合平台" | ✅ 暂停正确 |
| PoC数据支撑 | 7个事件输出24条Todo，其中仅4条合作信号 | ✅ 数据不足，无法验证匹配算法 |
| 用户信任 | 过早推出匹配功能会引发"你在利用我的关系"疑虑 | ✅ 暂停有利于建立信任 |
| 竞争差异化 | 市场上CRM/撮合工具很多，"关系回应助手"是空白 | ✅ 差异化策略正确 |
| 后续路径 | v1.2 §17.2明确了重新启用的条件阈值（≥30次回应记录等） | ✅ 不是永久放弃，是有条件推迟 |

**PM判定：✅ 采纳（强烈支持，无条件）**

> **理由**：这是v1.2中最具战略价值的建议之一。WORKBUDDY定稿、PRD v4.0、技术设计v2.2三方已经达成共识。暂停商机匹配不是能力不足，而是**产品纪律**——先证明"我能帮你认真回应每一个连接"，再谈"我能帮你发现合作机会"。

### 2.7 与WORKBUDDY定稿文档的差异分析

| 差异项 | 李总v1.2原文 | WORKBUDDY定稿 | 差异性质 | 处理建议 |
|--------|-------------|---------------|----------|----------|
| NeedInsight实现 | §7.1列为P0对象（独立表） | 定稿列为P1（存RelationshipBrief JSONB） | **实现粒度差异** | 以定稿为准（PoC轻量） |
| input_scope数量 | 8种 | 定稿提到8种+增加self_reflection/public_info=10种 | **枚举值差异** | 合并为统一清单，PoC用6种 |
| Promise责任类型 | 5种(self_commitment/counterparty/joint/approval/unclear) | 定稿提到5种(my_promise/their_promise/my_followup/mutual/system) | **命名差异** | 以v1.2为准（更准确描述商务场景） |
| TTS降级建议 | §14.1"TTS轻量演示即可" | 定稿明确"TTS/语音对许总不降级" | **场景差异** | **以定稿为准**（许总TTS是刚需） |
| Sprint时间估算 | Sprint1约3天+Sprint2约3天+Sprint3不定 | 总计P0约5天 | **估算一致** | 取保守估计（5-7天） |
| CooperationType | §2.3定义7种+建议首期仅候选 | 定稿列为P2（Phase1做） | **优先级一致** | 无冲突 |

**PM判定：✅ 整体高度一致，4处微小差异均已识别并有处理方案**

---

## 三、逐项评审：Architect视角

### 3.1 新增数据模型影响范围评估

**评审项**：v1.2建议的新增对象对现有数据模型的影响？

#### 3.1.1 NeedInsight

| 维度 | 评估 |
|------|------|
| **建议形态** | 独立表 need_insights（§7.3完整DDL） |
| **PoC可行形态** | 存入 RelationshipBrief JSONB 字段（WORKBUDDY定稿建议） |
| **对现有代码影响** | entity_extractor.py 需新增 NeedInsight 抽取逻辑；todo_generator.py 需确保 NI 不进入 Todo 流水线 |
| **迁移风险** | 低（PoC用JSONB，Phase1建独立表时数据迁移简单） |
| **工作量** | 0.5-1天（PoC JSONB方案） |

#### 3.1.2 RelationshipBrief（关系推进卡）

| 维度 | 评估 |
|------|------|
| **建议形态** | 独立表 relationship_briefs（§7.3完整DDL，11个字段） |
| **必要性** | **P0必须** — 这是前台核心页面数据源 |
| **对现有代码影响** | 新增 model + API route + service 层；event_pipeline.py 需在Step 5后追加"更新推进卡"步骤 |
| **关联关系** | person_id FK → entities 表；latest_interaction_id FK → events 表 |
| **迁移风险** | 低（全新表，不影响现有数据） |
| **工作量** | 1.5-2天（model + API + pipeline集成） |

#### 3.1.3 RelationshipStage（关系阶段）

| 维度 | 评估 |
|------|------|
| **建议形态** | 7阶段枚举 + Person.properties.stage 或 relationship_briefs.current_stage |
| **最佳实现位置** | **relationship_briefs.current_stage**（不在Person上，因为一个Person可能有多个关系推进卡？不，实际上是一个Person对应一个Stage） |
| **修正建议**：放在 **Entity.properties.relationship_stage** 更合理（复用现有Entity表，无需新建关联） |
| **状态机复杂度**：7阶段 × 单向前进为主 + 允许退回 = 约15条合法转换路径 |
| **工作量** | 0.5天（枚举定义 + 校验函数 + API端点） |

#### 3.1.4 Contribution / Feedback

| 维量 | 评估 |
|------|------|
| **Contribution** | PoC可作为 Todo 的子类型或 properties 字段；Phase1 再独立 |
| **Feedback** | 已有 Todo.feedback 字段（useful/not_useful）；可扩展为独立记录 |
| **工作量** | 各0.5天（PoC轻量方案） |

#### 3.1.5 Promise 重构（双向动作）

| 维度 | 评估 |
|------|------|
| **当前实现** | todo_generator.py 的 GeneratedTodo 只有 to_person（单向） |
| **v1.2要求** | 5种 action_type + promisor_person_id + beneficiary_person_id |
| **改动范围** | Todo model 新增3字段；todo_generator.py _extract_promises 重写；prompt 模板更新 |
| **复杂度**：中等（核心逻辑变更，但影响面可控） |
| **工作量** | 1-1.5天 |

**Arch总体判定：✅ 有条件采纳（数据模型增量可接受，但需严格控制新增表数量）**

> **Arch建议的PoC数据模型变更清单**：
> ```
> 新增表（1个）:
>   - relationship_briefs     [P0, 必须]
>
> 现有表变更（3个）:
>   - entities.properties      新增 relationship_stage 字段 [P0]
>   - todos                    新增 action_type/promisor/beneficiary [P0]
>   - events.metadata          新增 input_scope 字段 [P0]
>
> 延后到Phase1（4个）:
>   - need_insights            独立表（PoC用JSONB）
>   - contributions            独立表（PoC用JSONB）
>   - feedbacks                独立表（PoC复用todos.feedback）
>   - cooperation_types        枚举定义（PoC只用候选字段）
> ```

### 3.2 input_scope 分类器对Pipeline的改动量

**当前 Pipeline 流程**（event_pipeline.py）：
```
Input → Step1:语义路由(event_type) → Step2:实体抽取 → Step3:归一 → Step4:Todo生成 → Step5:存储 → Step6:关联发现 → Step7:完成
```

**改造后流程**：
```
Input → Step0:input_scope分类(新增) → Step1:语义路由(event_type+scope) → Step2:实体抽取(scope过滤) → ... → Step4:Todo生成(scope规则) → ...
```

| 改动点 | 文件 | 改动内容 | 改动量 |
|--------|------|----------|--------|
| 新增 Step0 | event_pipeline.py | 在 process_event_with_short_transactions() 中，Step 1之前插入 classify_input_scope() 调用 | ~30行 |
| 分类器实现 | services/input_classifier.py（新文件） | LLM调用 or 规则分类，返回 scope + confidence | ~80行 |
| Scope传递 | event_pipeline.py | 将 scope 传入 extractor 和 generator | ~20行 |
| Generator过滤 | todo_generator.py | 根据 scope 决定是否生成 Todo（partner_feedback/internal_review 不生成） | ~25行 |
| Schema更新 | events.py (API) | 接受可选 input_scope 参数 | ~10行 |

**Arch判定：✅ 采纳（总改动量约165行新增代码，分散在3个文件+1个新文件）**

> **风险评估**：低。这是一个典型的"前置过滤器"模式，不改变现有pipeline的后半段逻辑。最大风险是 LLM 分类的准确性（目标≥95%），可通过规则兜底（特定关键词触发默认分类）来缓解。

### 3.3 RelationshipStage 状态机设计评估

**v1.2建议的7阶段 + 6条变更规则**：

```
new_connection → understanding_needs → value_response → cooperation_exploration → intent_confirmed → execution → review
                                                                                     ↑                              |
                                                                                     └──── 退回/暂停 ←──────────────┘
```

**Arch设计评估**：

| 设计要素 | v1.2建议 | Arch评估 | 建议 |
|----------|----------|----------|------|
| 阶段数量 | 7个 | **偏多** | PoC用3个，定义保留7个枚举值 |
| 变更方向 | 主要单向前进 | ✅ 合理 | 符合关系推进的自然规律 |
| 自动升级 | 禁止（RS-01） | ✅ 正确 | 必须用户确认，防止AI越权 |
| 退回机制 | 允许（RS-04） | ✅ 必要 | 关系可能倒退（如对方失联） |
| 暂停标记 | 支持 | ✅ 实用 | paused_reason 字段 |
| 阶段依据 | stage_reason 文本 | ⚠️ 弱类型 | 建议增加 evidence_event_id 关联 |
| 实现方式 | 未指定 | — | 推荐 Python Enum + 状态机类（类似现有 TodoStateMachine） |

**参考现有代码**：`todo_state_machine.py` 已有成熟的状态机实现模式（VALID_TRANSITIONS字典 + transition()方法），RelationshipStage可直接复用此模式。

```python
# 建议的实现骨架（复用 todo_state_machine.py 模式）
class RelationshipStage(str, Enum):
    NEW_CONNECTION = "new_connection"
    UNDERSTANDING_NEEDS = "understanding_needs"
    VALUE_RESPONSE = "value_response"
    # ... 后续阶段

STAGE_TRANSITIONS = {
    "new_connection": ["understanding_needs"],  # 只能前进
    "understanding_needs": ["value_response", "new_connection"],  # 可退回
    # ...
}
```

**Arch判定：✅ 有条件采纳（复用现有状态机模式，3阶段起步）**

> **工作量估计**：0.5天

### 3.4 Promise 双向动作模型实现复杂度

**当前代码**（todo_generator.py `_extract_promises()`）：
```python
# 当前只提取 content + to_person（单向）
generated.append(GeneratedTodo(
    todo_type="promise",
    title=f"[承诺] {p.get('to_person', '')} — {content[:20]}",
    properties={
        "to_person": p.get("to_person"),
        "source_text": p.get("source_text"),
    },
))
```

**v1.2要求的Schema**：
```json
{
  "action_type": "self_commitment",  // 5种之一
  "promisor_person_id": "person_lin",  // 新增
  "beneficiary_person_id": "person_xu",  // 新增
  "content": "准备 PoC 演示",
  "evidence_quote": "...",
  "confirmation_status": "pending"
}
```

**改动分析**：

| 改动项 | 文件 | 内容 | 复杂度 |
|--------|------|------|--------|
| Todo Model | models/todo.py | 新增 action_type, promisor_id, beneficiary_id 列 | 低 |
| Prompt模板 | prompts/todo_generation.py | TEMPLATE_11 重写，要求 LLM 返回双向结构 | 中 |
| Extractor | todo_generator.py | _extract_promises() 解析新字段 | 中 |
| Todo降噪 | todo_generator.py | generate_todos() 中根据 action_type 过滤（对方承诺不进我的Todo） | 中 |
| API | api/v1/todos.py | 新增"等待对方回应"视图 | 低 |
| 测试 | test_todo_generator.py | 新增双向动作测试case | 低 |

**关键技术难点**：LLM 准确区分 promisor 和 beneficiary。这是 PoC 中"制作PoC被归为许总承诺"错误的根源。

**缓解方案**：
1. Prompt 中明确要求区分"说话人答应"vs"对方答应"（上下文角色分析）
2. 增加 confidence 阈值（<0.7 标记为 unclear，不生成正式 Todo）
3. 用户确认环节（所有 promise 默认 requires_confirmation=True）

**Arch判定：✅ 采纳（复杂度中等，但解决的是核心痛点）**

> **工作量估计**：1-1.5天

### 3.5 对现有代码库的具体影响

#### 3.5.1 event_pipeline.py 影响矩阵

| Pipeline Step | 当前行为 | v1.2改造后 | 影响等级 |
|---------------|----------|-----------|----------|
| Step 0 (新增) | 无 | input_scope 分类 | 🟢 新增 |
| Step 1: 语义路由 | 按 event_type 选模板 | event_type + input_scope 双维度路由 | 🟡 修改 |
| Step 2: 实体抽取 | 抽取 Person/Org | 不变（scope 不影响抽取） | 🔴 无变化 |
| Step 3: 归一 | 5步算法 | 不变 | 🔴 无变化 |
| Step 4: Todo生成 | 6种类型全生成 | 按 scope 规则过滤 + Promise 双向 + Todo 降噪 | 🟡 **重大修改** |
| Step 5: 存储 | MemoryProvider | 不变 | 🔴 无变化 |
| Step 6: 关联发现 | 增量关联 | 不变 | 🔴 无变化 |
| Step 7: 完成 | 标记 completed | 新增：更新 RelationshipBrief | 🟢 新增 |

**总结**：7个Step中，1个新增、2个修改、4个不变。**架构侵入性低**。

#### 3.5.2 todo_generator.py 影响矩阵

| 方法 | 当前 | v1.2改造 | 影响 |
|------|------|----------|------|
| `generate_todos()` | 主调度 | 新增 scope 参数，传入分类结果 | 🟡 |
| `_extract_promises()` | 单向promise | 重写为双向动作解析 | 🟡 **重大** |
| `_extract_cares()` | care 提取 | 可能拆分出 `_extract_need_insights()` | 🟡 |
| `_generate_typed_todo()` | 通用typed | 增加 scope 过滤逻辑 | 🟢 |
| `_persist_todo()` | 持久化 | 新增 action_type/promisor/beneficiary 字段 | 🟢 |
| `_is_duplicate_todo()` | 去重 | 不变 | 🔴 |

#### 3.5.3 entity_extractor.py 影响矩阵

| 方法 | 当前 | v1.2改造 | 影响 |
|------|------|----------|------|
| `extract_from_event()` | 主流程 | 可能根据 scope 跳过某些抽取（如 identity 只更新基础信息） | 🟢 |
| `_extract_conversation()` | 对话抽取 | 新增 NeedInsight 抽取（可在本方法内或独立方法） | 🟡 |
| `_person_to_resolution_data()` | 属性映射 | properties 新增 relationship_stage 占位 | 🟢 |

### 3.6 PoC 阶段可行性评估（时间 + 风险）

#### 时间估算

| 任务 | Arch估算 | PM估算 | 共识估算 | 依赖 |
|------|---------|--------|----------|------|
| Sprint 0: 冻结方向 + 回归测试集 | 2天 | 2天 | **2天** | 无 |
| input_scope 分类器 | 1天 | 1天 | **1天** | Sprint 0 完成 |
| Promise 双向动作重构 | 1.5天 | 1天 | **1.5天** | input_scope 完成 |
| Todo 降噪规则 | 0.5天 | 0.5天 | **0.5天** | Promise 重构完成 |
| RelationshipBrief 推进卡 | 2天 | 2天 | **2天** | 以上全部完成 |
| RelationshipStage（3阶段起步） | 0.5天 | 0.5天 | **0.5天** | 可与推进卡并行 |
| NeedInsight（JSONB轻量） | 1天 | 1天 | **1天** | 可与Promise并行 |
| 集成测试 + 修复 | 1天 | 1天 | **1天** | 所有功能完成 |
| **总计** | **9.5天** | **9天** | **~10天（2周Sprint）** | — |

> 注：李总v1.2原文估算 Sprint 1 约3天 + Sprint 2 约3天 = 6天开发时间，不含Sprint 0和测试。加上缓冲，**2周（10个工作日）是安全的PoC迭代周期**。

#### 风险矩阵

| 风险 | 概率 | 影响 | 缓解措施 | 责任人 |
|------|------|------|----------|--------|
| LLM 分类准确率 <95% | 中 | 高 | 规则兜底 + 人工确认队列 | Arch |
| Promise 双向识别仍然不准 | 中 | 高 | 强制 confirmation + confidence 阈值 | Arch + PM |
| 范围蔓延（想做更多SOP功能） | 高 | 中 | 严格 Gate 条件（§18） | PM |
| SQLite 性能（新增查询） | 低 | 低 | PoC数据量小，无需优化 | Arch |
| 前端进度不确定 | 中 | 中 | 推进卡先用 Swagger UI 展示 | PM |
| 许总对改版不满意 | 低 | 高 | 保持向后兼容，新旧并存 | PM |

**Arch总体可行性判定：✅ 可行（2周PoC迭代，风险可控）**

---

## 四、综合评审：逐项裁决表

### 4.1 P0 — PoC 必须做

| # | 建议项 | 来源章节 | PM裁决 | Arch裁决 | **共识** | 工作量 | 理由 |
|---|--------|----------|--------|----------|----------|--------|------|
| P0-1 | **input_scope 输入分类器** | §8 | ✅ 采纳 | ✅ 采纳 | **✅ 采纳** | 1天 | 解决PoC最严重问题（资料混流），改动量小（~165行），前置过滤器模式风险低 |
| P0-2 | **Promise 双向动作模型** | §9 | ✅ 采纳 | ✅ 采纳 | **✅ 采纳** | 1.5天 | 解决"制作PoC归为许总承诺"核心错误，是可信度基石 |
| P0-3 | **Todo 降噪规则** | §9.3 | ✅ 采纳 | ✅ 采纳 | **✅ 采纳** | 0.5天 | 7事件→24条Todo不可接受，单场≤3条规则清晰可执行 |
| P0-4 | **RelationshipBrief 关系推进卡** | §6 | ✅ 采纳 | ✅ 采纳 | **✅ 采纳** | 2天 | 前台核心页面，没有它用户看不到"关系全貌"，独立表影响小 |
| P0-5 | **RelationshipStage 关系阶段（3阶段起步）** | §5.2 | ✅ 有条件 | ✅ 有条件 | **✅ 有条件采纳** | 0.5天 | 7阶段定义一次写完，PoC启用前3阶段，复用现有状态机模式 |

**P0 总计：5.5 天**（与 WORKBUDDY 定稿的 5 天估算基本一致）

### 4.2 P1 — PoC 建议做

| # | 建议项 | 来源章节 | PM裁决 | Arch裁决 | **共识** | 工作量 | 理由 |
|---|--------|----------|--------|----------|----------|--------|------|
| P1-1 | **NeedInsight 轻量实现（JSONB）** | §5.1 | ✅ 有条件 | ✅ 有条件 | **✅ 有条件采纳** | 1天 | 区分"对方关心"和"对方可能需要"是认知跃迁，但PoC用JSONB不够独立表 |
| P1-2 | **首页改版** | §6.3 / §12.2 | ✅ 有条件 | ✅ 有条件 | **✅ 有条件采纳** | 1-2天 | 取决于许总团队前端进展；新产品逻辑上更优 |
| P1-3 | **AI 输出 Schema 更新（含 cooperation_stage_suggestion）** | §11.2 | ✅ 采纳 | ✅ 采纳 | **✅ 采纳** | 0.5天 | LLM prompt 模板更新，影响 entity_extraction + todo_generation |
| P1-4 | **敏感洞察推送过滤** | §11.3 / NI-06 | ✅ 采纳 | ✅ 采纳 | **✅ 采纳** | 0.5天 | notification_service 加一行 sensitivity 过滤，安全刚需 |
| P1-5 | **主 Slogan 更新** | §15 | ✅ 采纳 | — | **✅ 采纳** | 0.1天 | PRD 文档更新，"让每一次连接，都有回应。" |

**P1 总计：3-4 天**（可与 P0 部分并行）

### 4.3 P2 — Phase 1 做

| # | 建议项 | 来源章节 | PM裁决 | Arch裁决 | **共识** | 理由 |
|---|--------|----------|--------|----------|----------|------|
| P2-1 | **CooperationType 候选（7种合作关系）** | §2.3 | ✅ 暂缓 | ✅ 暂缓 | **✅ 暂缓** | 等 ≥5 段关系进入 cooperation_exploration 后再启用 |
| P2-2 | **Contribution / Feedback 独立记录** | §7.2 | ✅ 暂缓 | ✅ 暂缓 | **✅ 暂缓** | Phase1 从 JSONB 迁移到独立表 |
| P2-3 | **结果复盘功能（review 阶段）** | §4.3 | ✅ 暂缓 | ✅ 暂缓 | **✅ 暂缓** | 需要多轮合作完成后才有意义 |
| P2-4 | **BilateralAction 双方行动清单** | §2.4/SOP-3 | ✅ 暂缓 | ✅ 暂缓 | **✅ 暂缓** | 进入 execution 阶段后再开发 |
| P2-5 | **意图文档处理（LOI等）** | §8.2 | ✅ 暂缓 | ✅ 暂缓 | **✅ 暂缓** | 目前无真实 LOI 数据 |
| P2-6 | **执行记录 / 结果记录** | §8.2 | ✅ 暂缓 | ✅ 暂缓 | **✅ 暂缓** | 属于合作执行层，Phase2 |

### 4.4 明确拒绝 / 不采纳

| # | 建议项 | 来源 | PM裁决 | Arch裁决 | **共识** | 拒绝理由 |
|---|--------|------|--------|----------|----------|----------|
| R-1 | **TTS 降级为"轻量演示"** | §14.1 | ❌ 拒绝 | ❌ 拒绝 | **❌ 拒绝** | 许总眼神不好+开车场景，TTS是刚需不是增强。见 WORKBUDDY 定稿 §5.1 |
| R-2 | **首期开发结算/对账系统** | §2.6/SOP-3 | ❌ 拒绝 | ❌ 拒绝 | **❌ 拒绝** | 李总自己也说"不应进入首期"，且与"私密助手"定位冲突 |
| R-3 | **首期开发渠道活码/标签系统** | §3/SOP-3 | ❌ 拒绝 | ❌ 拒绝 | **❌ 拒绝** | 运营执行系统，个人用户不需要 |
| R-4 | **7阶段全部启用UI展示** | §5.2 | ⚠️ 有条件 | ⚠️ 有条件 | **⚠️ 有条件拒绝** | PoC 启用前3阶段，后4阶段仅保留枚举定义不在 UI 展示 |

---

## 五、PM+Arch 共识结论

### 5.1 战略共识

1. **李总v1.2的方向完全正确**。其核心洞察——"一次连接需要被回应，一段关系需要被推进"——与 PromiseLink 的产品定位完美契合。
2. **5项P0建议构成最小可行改进集**，恰好解决PoC暴露的全部严重问题（混流、噪音、错配、缺全貌）。
3. **"暂停商机匹配"是正确的战略决策**，应作为PoC Gate的硬性前提条件。
4. **SOP借鉴应有明确边界**：只引入"阶段思维"和"节点意识"，不搬入组织型流程（建群、结算、专委会）。

### 5.2 技术共识

1. **数据模型增量可控**：PoC只需新增1张表（relationship_briefs）+ 3张表各增少量字段。
2. **Pipeline改造安全**：前置过滤器模式（input_scope）不破坏现有7步管线架构。
3. **状态机复用现有模式**：RelationshipStage 直接复用 todo_state_machine.py 的 VALID_TRANSITIONS 模式。
4. **2周迭代周期可行**：10个工作日完成P0+关键P1，风险可控。

### 5.3 需要特别注意的风险

1. **LLM 准确性是最大变量**：input_scope 分类和 Promise 双向识别都依赖 LLM 理解能力，必须有 fallback 到规则的降级策略。
2. **前端进度是不确定因素**：如果许总团队尚未开始首页开发，应立即按 v1.2 新设计启动。
3. **范围蔓延压力**：v1.2 文档很长（19章节），团队容易陷入"这也很有价值"的陷阱。必须严格执行 §18 Gate 条件。

---

## 六、给李总的回复建议

### 6.1 回复基调

**感谢 + 认同 + 明确行动计划 + 1处保留意见**

### 6.2 建议回复框架

```
李总您好，

感谢您花时间撰写这份详尽的v1.2建议文档。我们已完成PM+Architect联合深度评审，
结论如下：

【整体评价】
v1.2是目前我们收到的外部建议中质量最高的一份。您用真实PoC数据（7事件→24条Todo、
承诺归属错误、资料混流）精准地指出了产品薄弱环节，并提出结构化解决方案。
特别是"先分类再提取"的思路和"关系推进卡"的概念，直接解决了我们当前最头疼的问题。

【采纳决定】
✅ 全面采纳您的5项P0建议：
  1. input_scope 输入分类器（解决混流问题）
  2. Promise 双向动作模型（解决承诺错配问题）
  3. Todo 降噪规则（解决噪音问题）
  4. RelationshipBrief 关系推进卡（解决缺少全貌的问题）
  5. RelationshipStage 关系阶段（3阶段起步）

✅ 同意暂停商机匹配引擎（这与我们的内部判断一致）

✅ 同意首期只引入SOP的"阶段思维"和"节点意识"，不做全量执行

【1处保留意见】
关于TTS"轻量演示即可"的建议，我们需要保留不同意见。
我们的首位种子用户（许总）有视力障碍且高频使用车载场景，
TTS语音播报对他来说是核心使用路径而非增强功能。
我们会在其他方面控制PoC范围来平衡这个决策。

【下一步】
- 本周：冻结方向，建立回归测试集（您的PoC错误数据将作为核心回归用例）
- 下周：开始Sprint 1开发（input_scope + Promise双向 + Todo降噪）
- 2周后：Sprint 2（推进卡 + 关系阶段 + 集成测试）
- Sprint 3：种子用户验证

预计2周后可以请您 reviewing 我们的改进效果。

林总 & PromiseLink 团队
2026-06-04
```

### 6.3 关键沟通要点

| 要点 | 怎么说 | 为什么 |
|------|--------|--------|
| 肯定SOP价值但不照搬 | "引入阶段思维，不做全量执行" | 让李总感觉被尊重，同时管理期望 |
| TTS保留意见 | 说明许总的特殊需求 | 李总能理解用户场景差异 |
| 明确时间表 | 2周+2周+验证 | 专业感，显示执行力 |
| 邀请后续reviewing | "2周后请您reviewing" | 建立持续合作关系 |

---

## 七、附录

### 附录A：v1.2 建议与现有代码映射速查表

| v1.2概念 | 现有代码对应 | 变更类型 | 优先级 |
|----------|-------------|----------|--------|
| input_scope | event_pipeline.py Step 1 语义路由 | 前置新增 Step 0 | P0 |
| Concern | todo_generator.py _extract_cares() | 已有，需增加不过滤规则 | P0 |
| NeedInsight | **无** | 新增 _extract_need_insights() | P1 |
| Promise(双向) | todo_generator.py _extract_promises() | **重写**：增加action_type/promisor/beneficiary | P0 |
| Contribution | **无**（help Todo 部分覆盖） | 新增或扩展 help 类型 | P1 |
| Feedback | todos.feedback 字段 | 已有，扩展为独立记录 | P2 |
| RelationshipBrief | **无** | **新增独立表** | P0 |
| RelationshipStage | entities.properties.relationship（strength字段） | **新增** stage 字段替代 strength | P0-P1 |
| CooperationType | **无** | 延后 | P2 |
| BilateralAction | **无** | 延后 | P2 |

### 附录B：PoC 回归测试用例（基于v1.2 §1.3 错误列表）

| # | 错误场景 | 输入 | 期望行为 | 验收标准 |
|---|----------|------|----------|----------|
| REG-01 | 承诺归属错误 | 会议记录含"制作PoC" | 不归为许总承诺，归为林总或 unclear | Promise责任人准确率 ≥90% |
| REG-02 | 输入材料混流 | 李总产品建议文档 | 进入 Product Feedback 库，不生成关系 Todo | 内部评审进入关系卡 = 0 |
| REG-03 | Todo 噪音过多 | 7个事件原始输入 | 输出 ≤3 条正式 Todo | 单场会议正式 Todo ≤3 |
| REG-04 | 关联价值偏弱 | 多次会议共现 | 关联强度有合理衰减 | 关联强度 >0 的比例合理 |
| REG-05 | 旧语义残留 | 含"商机""资源"关键词 | AI输出不含撮合语言 | 禁止输出词命中 = 100% |

### 附录C：术语对照表

| v1.2 术语 | 现有代码术语 | 映射关系 |
|------------|-------------|----------|
| Interaction | Event (event_type=meeting/call/manual) | 直接映射 |
| Concern | Todo (todo_type=care) | 部分映射（Care是关注，Concern更强调"对方"视角） |
| NeedInsight | **无** | 全新 |
| Promise | Todo (todo_type=promise) | 需扩展为双向 |
| Contribution | Todo (todo_type=help) | 部分映射 |
| Feedback | Todo.feedback 字段 | 部分映射 |
| RelationshipBrief | **无** | 全新 |
| RelationshipStage | Entity.properties.relationship.strength | 替换/扩展 |
| input_scope | Event.event_type | 增强（新增分类维度） |
| CooperationType | **无** | 全新（后置） |

---

> **报告生成方法**：DevSquad MultiAgentDispatcher（Mock模式）+ PM/Arch 双角色深度人工分析  
> **共识达成方式**：逐项投票 + 冲突讨论 + 最终一致裁定  
> **下次评审触发条件**：Sprint 2 完成后 / 种子用户验证后 / 李总收到回复后
