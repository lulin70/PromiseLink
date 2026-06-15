# PromiseLink 基础版 P0+P1 功能增强规格

> **版本**: v1.0
> **日期**: 2026-06-12
> **来源**: 公众号草稿 + 头脑风暴Top 5用例对照分析
> **状态**: 待实施
> **前置文档**: PRD_核心.md v4.8, brainstorm-ai-usecases-2026-06-11.md, article-wechat-draft-2026-06-11.md

---

## 1. 变更概述

基于公众号草稿和头脑风暴文档的场景描述，对比当前基础版实现，确定以下增强项：

| 编号 | 功能 | 来源 | 当前状态 | 目标 |
|------|------|------|---------|------|
| F-E1 | 承诺确认/修正交互 | Top2承诺语义提取 | Pipeline全自动，无确认环节 | 提取后展示卡片，用户可确认/修正 |
| F-E2 | 对方承诺逾期催促话术 | Top1双向追踪闭环 | 逾期仅标记，无话术生成 | 逾期时自动生成温和催促消息草稿 |
| F-E3 | 静默联系人活化引擎 | Top5静默活化 | 仅dormant检测(90天) | 扫描+评分+Top N清单+破冰方案 |
| F-E4 | 供需匹配Dashboard展示 | 公众号供需匹配 | 后端engine有，前端无展示 | Dashboard新增供需匹配卡片 |
| F-E5 | Per-person关系信用分 | Top1闭环最后缺口 | 仅全局fulfillment_rate | 每个联系人有独立信用评分 |
| F-E6 | 承诺页面"对方承诺"Tab验证 | 用户反馈 | 代码有Tab但可能数据不显示 | 确保双视图正常工作 |

---

## 2. F-E1: 承诺确认/修正交互

### 2.1 用户故事

> 作为商务人士，AI提取出承诺后，我希望看到提取结果并确认或修正，而不是系统直接入库，So that 确保每条承诺的准确性，避免错误信息影响我的判断。

### 2.2 交互流程

```
用户录入事件 → Pipeline处理 → AI提取承诺 → 【新增】展示确认卡片 → 用户操作:
  ├─ ✅ 确认: 标记confirmation_status=CONFIRMED, 入库
  ├─ ✏️ 修正: 编辑action_type/description/due_date, 再确认
  └─ ❌ 拒绝: 标记confirmation_status=REJECTED, 不入库
```

### 2.3 后端变更

**新增API**:

```
GET /api/v1/events/{event_id}/pending-confirmations
  返回该事件中所有 confirmation_status=PENDING/AUTO_SET 的promise类型Todo

PATCH /api/v1/todos/{todo_id}/confirm
  Body: { confirmation_status: "confirmed" | "rejected", description?: string, due_date?: datetime }
  更新确认状态和可选修正内容
```

**Pipeline变更**:

- Step05 (PromiseBidirectionalHandler) 输出的promise类型Todo默认 `confirmation_status=AUTO_SET`（当前已如此）
- 新增：不立即标记为最终态，等待用户确认后才参与信用分计算

### 2.4 前端变更

**录入页 (input/index.tsx)**:
- Pipeline完成后，若存在待确认的promise Todo，展示确认卡片列表
- 每张卡片包含: action_type标签、描述文本、截止时间、原文引用
- 操作按钮: [确认] [修改] [删除]

**承诺页 (promises/index.tsx)**:
- 新增状态筛选选项: "待确认"
- AUTO_SET状态的承诺以特殊样式展示（虚线边框+黄色提示）

### 2.5 数据模型变更

```python
# Todo.confirmation_status 枚举扩展使用说明:
#   PENDING:    用户手动创建的待办
#   CONFIRMED:  用户确认了AI提取的结果
#   REJECTED:   用户拒绝了AI提取的结果
#   AUTO_SET:   AI自动提取/生成，尚未被用户确认（默认值）
```

（字段已存在，无需DDL变更）

### 2.6 验收标准

- AC: 录入事件后，promise类Todo在确认前以"待确认"状态展示
- AC: 用户可一键确认/逐条确认批量确认
- AC: 用户可修正描述、截止时间后再确认
- AC: 已拒绝的Todo不计入统计和提醒
- AC: 确认后的Todo才计入关系信用分

---

## 3. F-E2: 对方承诺逾期催促话术

### 3.1 用户故事

> 当对方承诺我的事项逾期未兑现时，我希望系统能帮我生成一条温和的催促消息，而不是让我自己想措辞，So that 我能得体地跟进而不破坏关系。

### 3.2 触发条件

```
their_promise 类型 Todo 且 fulfillment_status=overdue 或 pending + due_date < today
```

### 3.3 NLG模板设计

**新增Intent: gentle_nudge**

```python
TEMPLATE_GENTLE_NUDGE = """
你是一个商务关系助手。对方之前答应了一件事但还没兑现。
请生成一条温和、得体的催促消息。要求：
1. 不施加压力，不给对方造成不适感
2. 可以自然地提及之前的约定
3. 给对方一个台阶下（可能是忙忘了）
4. 控制在50字以内
5. 语气友好但不卑微

上下文：
- 对方姓名: {entity_name}
- 对方承诺内容: {promise_description}
- 承诺时间: {promise_due_date}
- 距今已过: {overdue_days}天
- 你们的关系阶段: {relationship_stage}
"""
```

### 3.4 后端变更

**nlg_service.py**:
- 新增 `generate_gentle_nudge(todo_id)` 方法
- 调用LLM生成催促话术
- 结果缓存到Todo的 `nlg_draft` 字段（JSONB）

**promises.py API**:
- GET /promises/{todo_id}/nudge-draft — 获取/生成催促话术
- 若已有缓存则直接返回，否则调用NLG生成

### 3.5 前端变更

**承诺页 (promises/index.tsx)**:
- their_promise + overdue 状态的卡片上，增加 [生成催促消息] 按钮
- 点击后弹出对话框展示生成的催促话术
- 提供 [复制] 按钮（复制到剪贴板）
- 明确标注: "此消息仅供参考，发送前请自行调整"

### 3.6 设计约束

- **绝不自动发送** — 只生成草稿供参考
- **用户必须主动触发** — 不在列表页自动展示催促话术
- **每次生成可能不同** — LLM有随机性，多次点击可获取不同版本

### 3.7 验收标准

- AC: 逾期their_promise卡片上有[催促消息]入口
- AC: 点击后在2-5秒内返回催促话术
- AC: 话术长度<100字，语气温和
- AC: 支持一键复制
- AC: 无任何自动发送行为

---

## 4. F-E3: 静默联系人活化引擎

### 4.1 用户故事

> 我的通讯录里有60%以上的联系人超过两个月没互动了。我希望系统告诉我哪些人最值得重新连接，并给我一个联系理由，So that 沉睡的人脉被重新唤醒。

### 4.2 核心算法: 活化潜力评分

```python
def calc_reactivation_score(entity) -> float:
    """
    多维度评分 (0-100):
    
    维度1: 关系深度 (30%)
      - 历史事件数: 越多说明曾经关系越深
      - 关系阶段最高值: 曾经到达的阶段越高越好
      - 承诺交互数: 有过承诺往来的关系更值得维系
    
    维度2: 资源互补性 (25%)
      - capability × concern 匹配度
      - 有明确的demand/capability记录
    
    维度3: 时间衰减 (20%)
      - 最后一次互动距今天数（60天=满分线性递减）
      - 不用90天dormant阈值，用60天更积极
    
    维度4: 互动质量 (15%)
      - Pipeline处理完整度
      - 信息丰富度（properties填充率）
    
    维度5: 近期信号 (10%)
      - 是否有未完成的their_promise（对方欠你的）
      - 是否有cooperation_signal
    """
```

### 4.3 后端变更

**新增API**:

```
GET /api/v1/entities/dormant?limit=10&min_days=60
  参数:
    limit: 返回数量 (默认10)
    min_days: 最少静默天数 (默认60)
  返回:
    items: [
      {
        entity_id, name, company,
        dormant_days,           # 静默天数
        reactivation_score,     # 活化潜力评分 0-100
        last_interaction,       # 最后互动时间
        last_event_summary,     # 最后互动摘要
        reason,                 # 推荐理由 (文本)
        icebreaker_topic,       # 破冰话题建议 (文本)
        pending_their_promises, # 对方未兑现的承诺数
        relationship_stage,     # 当前关系阶段
      }
    ]
```

**dormant_scanner.py (新模块)**:
- 扫描所有person实体
- 计算每个实体的last_interaction_time
- 过滤 > min_days 的实体
- 计算reactivation_score
- 生成reason和icebreaker_topic（基于concern/event_topics）
- 按score降序返回

### 4.4 前端变更

**方案A (推荐): 在人脉页集成**
- 人脉页顶部增加 [发现沉睡人脉] 按钮/入口
- 点击展开活化清单（Modal或新页面）
- 每条包含: 姓名+公司+静默天数+评分+推荐理由+[一键生成破冰消息]

**方案B: 独立页面**
- Tab栏新增第6个Tab "发现" (基础版暂不加Tab)

> 基础版采用方案A，专业版可升级为方案B。

### 4.5 破冰话题生成

**NLG模板**:

```python
TEMPLATE_ICEBREAKER = """
根据以下信息，生成一句简短自然的破冰开场白（30字以内）:
- 对方姓名: {name}
- 最后一次互动: {last_event_summary}
- 对方关心的话题: {concerns}
- 共同话题/关联: {common_topics}
- 距上次互动: {days_ago}天

要求: 自然、不刻意、像老朋友打招呼。
"""
```

### 4.6 验收标准

- AC: 能扫描出>60天未互动的联系人
- AC: 按活化潜力评分排序
- AC: 每条结果包含推荐理由和破冰话题
- AC: 支持一键生成破冰消息并复制
- AC: 响应时间<3秒（含NLG生成）

---

## 5. F-E4: 供需匹配Dashboard展示

### 5.1 用户故事

> 我的人脉里有人需要融资、有人在看项目、有人认识LP。这些信息散落在各处，我希望在首页一眼就能看到谁需要什么、谁能提供什么，So that 发现潜在的合作机会。

### 5.2 展示位置

**首页 (index) Dashboard → 新增卡片区域**

在现有4个汇总卡片下方，新增:

```
┌─────────────────────────────────────┐
│ 🔗 供需匹配机会                      │
├─────────────────────────────────────┤
│ 张伟 需要: 数据中台供应商             │
│   → 李明 可提供: 技术架构能力        │
│   匹配度: 高                        │
├─────────────────────────────────────┤
│ 王芳 需要: HR管理系统                │
│   (暂无匹配供给方)                    │
└─────────────────────────────────────┘
```

### 5.3 后端变更

**dashboard.py**:
- day-view响应新增 `supply_demand_matches` 字段
- 调用AssociationDiscoveryEngine的supply_demand匹配逻辑
- 格式化为前端可直接展示的结构

**新增API**:

```
GET /api/v1/dashboard/supply-demand
  返回当前用户的所有供需匹配对:
  matches: [
    {
      demander: { name, company, demand_text },
      supplier: { name, company, supply_text },
      match_score,
      match_reason,
    }
  ]
```

### 5.4 前端变更

**Dashboard (index.tsx)**:
- 新增 SupplyDemandMatch 组件
- 展示Top 5匹配对
- 点击可跳转到对应的人脉详情
- 无匹配时显示"暂未发现供需匹配机会"

### 5.5 验收标准

- AC: Dashboard展示供需匹配卡片
- AC: 显示需求方+供给方+匹配原因
- AC: 点击可跳转详情
- AC: 无匹配时优雅降级（不报错）
- AC: 性能: 不显著影响Dashboard加载速度

---

## 6. F-E5: Per-person关系信用分

### 6.1 用户故事

> 我想看到每个人的"靠谱程度"——我答应他的事都兑现了吗？他答应我的事呢？这个分数帮助我判断谁更值得深度合作，So that 把精力投入到最值得的关系上。

### 6.2 评分模型

```python
class EntityCreditScore:
    """Per-entity relationship credit score (0-100)"""
    
    def calculate(self, entity_id) -> dict:
        """
        my_fulfillment_rate = fulfilled_my_promises / total_my_promises
        their_fulfillment_rate = fulfilled_their_promises / total_their_promises
        
        score = (
            my_fulfillment_rate * 40 +      # 我守承诺的能力 (40%)
            their_fulfillment_rate * 35 +   # 对方守信程度 (35%)
            interaction_consistency * 15 +  # 互动规律性 (15%)
            response_timeliness * 10         # 回应及时性 (10%)
        )
        
        grade:
          90-100: A+ (高度可信)
          80-89:  A  (值得信赖)
          70-79:  B  (基本可靠)
          60-69:  C  (需观察)
          <60:    D  (风险较高)
        """
```

### 6.3 后端变更

**新增API**:

```
GET /api/v1/entities/{entity_id}/credit-score
  返回: { score, grade, breakdown: {...}, history: [...] }

GET /api/v1/entities/credit-scores?sort_by=score&min_interactions=2
  返回所有有足够交互数据的实体信用分排名
```

**credit_score.py (新模块)**:
- 计算逻辑
- 缓存策略（实体更新时失效）
- 历史趋势（最近N次计算的score变化）

### 6.4 前端变更

**人脉详情弹窗 (entities/index.tsx)**:
- 新增"信用分"展示区域
- 显示分数+等级+A/B/C/D色标
- 可展开查看详细分解

**人脉列表 (entities/index.tsx)**:
- 可选按信用分排序
- 信用分以小徽章形式展示在人名旁

### 6.5 设计约束

- **只给自己看** — 信用分是个人参考工具，不对外暴露
- **中性表述** — 用"A/B/C/D"等级而非"靠谱/不靠谱"
- **最少交互要求** — 至少2次以上互动才计算（避免偶然数据偏差）
- **可忽略** — 用户可选择不看此指标

### 6.6 验收标准

- AC: 实体详情页展示信用分
- AC: 分数计算正确（可人工验算几组数据）
- AC: 少于2次互动的实体不显示信用分
- AC: 支持按信用分排序
- AC: 信用分随新承诺兑现实时更新

---

## 7. F-E6: 承诺页面双视图验证

### 7.1 问题

用户反映"画面上承诺只能看到自己的，看不到对方待兑现"。

### 7.2 分析

代码层面已实现:
- 后端: promises.py 支持 `view=my-promises` 和 `view=their-promises` 参数
- 前端: promises/index.tsx 有VIEW_TABS数组定义两个Tab
- 统计栏: 显示 their_promises.pending 数量

可能问题:
1. 前端Tab切换后loadData()未正确传递view参数
2. API返回their_promise数据为空（确实没有their_promise类型的Todo）
3. CSS样式问题导致第二个Tab不可见或不可点击

### 7.3 修复措施

1. 确认API调用参数传递正确
2. 确认their_promise类型Todo确实存在于数据库中
3. 确保"对方的承诺"Tab视觉上明显可切换
4. 如果数据为空，显示友好的空状态提示而非空白

### 7.4 验收标准

- AC: "我的承诺"Tab显示my_promise类型Todo
- AC: "对方的承诺"Tab显示their_promise类型Todo
- AC: 统计栏数字与实际数据一致
- AC: Tab切换流畅无闪烁

---

## 8. 实施计划

| 阶段 | 功能 | 预估工作量 | 依赖 |
|------|------|-----------|------|
| Phase 1 | F-E6: 双视图验证修复 | 0.5h | 无 |
| Phase 1 | F-E1: 承诺确认交互 | 2h (后端1h + 前端1h) | F-E6 |
| Phase 1 | F-E2: 催促话术生成 | 1.5h (后端1h + 前端0.5h) | 无 |
| Phase 2 | F-E3: 静默活化引擎 | 3h (后端2h + 前端1h) | 无 |
| Phase 2 | F-E4: 供需匹配展示 | 1.5h (后端1h + 前端0.5h) | 无 |
| Phase 2 | F-E5: 关系信用分 | 2h (后端1.5h + 前端0.5h) | 无 |

**总计**: 约10.5小时，建议分2-3个实施周期完成。

---

## 9. 风险与约束

| 风险 | 影响 | 缓解措施 |
|------|------|---------|
| NLG生成延迟影响体验 | F-E2/F-E3依赖LLM | 异步生成+loading状态；超时降级为模板话术 |
| 活化评分维度过多导致复杂 | F-E3 | 先用简化版3维（关系深度+时间衰减+资源互补） |
| 信用分引起用户敏感 | F-E5 | 默认关闭，用户设置中开启；中性表述 |
| 确认环节增加操作成本 | F-E1 | 提供"全部确认"快捷操作；可设置跳过确认 |
