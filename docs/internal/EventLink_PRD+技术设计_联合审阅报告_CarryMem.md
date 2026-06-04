# EventLink PRD v3.3 + 技术设计 v1.3 联合审阅报告

**日期**：2026-06-02
**审阅方**：CarryMem团队（产品舵手）
**审阅对象**：
- PRD v3.3（`docs/spec/PRD_V1.md`，约2100行，9章节，48个AC）
- 技术设计 v1.3（`docs/architecture/EventLink_技术设计_v1.md`，约1297行）

---

## 📌 TL;DR

- PRD v3.3从v1.0到v3.3经历20+次修订、7角色+客户双评审，产品维度完成度极高
- 技术设计v1.3在CarryMem解耦、小程序通信、TTS链路等工程细节做得扎实
- **最关键缺口**：两份文档之间存在5处矛盾，技术设计缺4个核心算法实现，PRD缺CarryMem集成接口声明
- **Slogan建议**：主"见面只是开始" + 副"下次联系的理由，我们给你找好了"
- 下一步：补算法代码→对齐矛盾→PoC开发

---

## 🎯 核心结论卡片

| 项目 | 内容 |
|------|------|
| 推荐方案 | 优先补齐技术设计的4个P0算法缺口，对齐PRD与技术设计的5处矛盾 |
| 优先级 | P0（不补齐无法进入PoC开发） |
| 预期影响 | 补齐后PoC开发可正常启动，预计额外3-4天工作量 |
| 资源需求 | CarryMem团队1人，3-4天 |
| 风险等级 | 中（算法缺口不补会导致PoC期间反复返工） |

---

## 一、PRD v3.3 亮点（值得肯定的部分）

### 1. 管线化处理（4管线语义路由）

card_save/meeting/call/manual四条管线，不同延迟要求、不同输出Schema。解决了名片秒级响应和会议深度分析之间的矛盾。

| 管线 | 延迟P95 | 输出深度 | 触发方式 |
|------|---------|---------|---------|
| card_save | <1s | 轻量（实体+关联） | 名片扫码 |
| meeting | <5s | 深度（实体+关联+话题+Todo） | 会议记录上传 |
| call | <3s | 要点（实体+关键话题+Todo） | 通话记录 |
| manual | <2s | 补全（实体补全） | 手动输入 |

这是从单条通用管道到专用管线的正确演化，工程上合理。

### 2. Todo替代Alert——从"告诉你"到"帮你做"

| 维度 | 我的设计（Alert） | PRD（Todo） |
|------|-------------------|------------|
| 类型 | opportunity/risk/context 3种 | ⚪🔴🔵🟢 4种 |
| 性质 | 全部信息型 | 信息型(⚪🔴🔵) + 行动型(🟢) |
| 状态 | 新建/dismissed 二态 | pending→in_progress→done/dismissed/snoozed |
| 行动 | 无 | actions字段 + 建议文案 |
| 延期 | 不支持 | snoozed + due_date |

snoozed（延期）和行动型Todo让产品从"信息推送器"变成了"行动推进器"。

### 3. 实体归一5步级联算法

精确匹配→别名扩展→上下文相似度→置信度分级→HITL确认。三档策略清晰：

| 置信度 | 动作 | 例子 |
|--------|------|------|
| ≥0.85 | 自动合并 | 同名+同公司 |
| [0.70, 0.85) | 待确认 | 同名+不同公司+同行业 |
| <0.70 | 新建 | 同名+无上下文关联 |

### 4. 分期交付+量化退出条件

| 阶段 | 时长 | 用户规模 | 关键退出条件 |
|------|------|---------|-------------|
| PoC | 3周 | ≤5人 | LLM抽取≥90%、归一误合并<5%、F1>0.65 |
| Phase1 | 6周 | ≤100人 | DAU≥30持续2周、TTS使用率≥40% |
| Phase2 | 持续 | 1000+人 | 按Phase1数据决定 |

这是投资人级别的产品思维——每个阶段都有可量化的Go/No-Go判断。

### 5. 触达通道设计

3通道（名片小程序+H5 / 微信服务号 / APNs+FCM）× 5级推送优先级 × 防打扰策略。特别是针对许总"开车去拜访"场景的TTS语音播报（极简/完整两级），是真实用户反馈驱动的功能。

### 6. 文档工程纪律

48个验收标准全部可量化可测试，变更记录精确到每个版本改了什么，7角色+客户双评审机制。从v1.0到v3.3的20+次修订全程可追溯。

---

## 二、技术设计 v1.3 亮点（PRD没有的工程细节）

### 1. CarryMem解耦设计（最关键）

Protocol接口定义了5个方法：

```python
class CarryMemProvider(Protocol):
    async def check_health(self) -> bool: ...
    async def recall_preferences(self, user_id: str) -> list: ...
    async def match_rules(self, user_id: str, context: dict) -> list: ...
    async def declare_memory(self, user_id: str, entry: dict) -> None: ...
    async def update_rule(self, user_id: str, rule: dict) -> None: ...
```

NullMemoryProvider确保"EventLink所有核心功能在CarryMem未部署时依然可用"。这解决了PRD审阅中"集成接口缺失"的问题。

### 2. PG列索引同步触发器

properties JSONB高频查询字段（company/title/city/industry）提取为独立列+触发器自动同步。这是实际写代码才会想到的优化。

### 3. 小程序+H5通信协议

临时授权码模式（非明文token）、Storage+onShow数据同步、语音/TTS跳原生页面不走WebView桥接。踩过微信小程序坑才写得出的设计。

### 4. TTS播报完整方案

TTSScriptComposer模板+隐私分级+缓存策略+URL签名+降级链。PRD只说了"TTS播报"，这里把整个链路画出来了。

### 5. 运维细节

JWT密钥轮换90天、审计日志、PG备份策略、内存分配（API 256MB/Worker 512MB/Scheduler 256MB）、监控告警阈值。

---

## 三、技术设计的关键缺失（必须补的）

### 缺失1：实体归一5步算法——只有名字没有代码（P0）

§4.1 Step 3写了"5步算法"但没给实现。需要补：

```python
class EntityResolutionEngine:
    """实体归一引擎——5步级联算法"""
    
    async def resolve(
        self, new_entity: Entity, existing: List[Entity]
    ) -> ResolutionResult:
        # Step 1: 精确匹配（name完全相同，大小写不敏感）
        exact = self._exact_match(new_entity, existing)
        if exact and self._context_confirm(new_entity, exact):
            return ResolutionResult(
                action=ResolutionAction.MERGE,
                target=exact, confidence=1.0
            )
        
        # Step 2: 别名匹配（new.name in existing.aliases 或反之）
        alias = self._alias_match(new_entity, existing)
        if alias:
            return ResolutionResult(
                action=ResolutionAction.MERGE,
                target=alias, confidence=0.95
            )
        
        # Step 3: 模糊匹配（edit_distance / jaro_winkler ≥ 阈值）
        fuzzy = self._fuzzy_match(new_entity, existing, threshold=0.85)
        if fuzzy:
            confidence = self._compute_confidence(new_entity, fuzzy)
            if confidence >= 0.85:
                return ResolutionResult(
                    action=ResolutionAction.MERGE,
                    target=fuzzy, confidence=confidence
                )
            elif confidence >= 0.70:
                return ResolutionResult(
                    action=ResolutionAction.CONFIRM,
                    target=fuzzy, confidence=confidence
                )
        
        # Step 4: 上下文匹配（company+title+city组合）
        context = self._context_match(new_entity, existing)
        if context:
            confidence = self._compute_confidence(new_entity, context)
            if confidence >= 0.85:
                return ResolutionResult(
                    action=ResolutionAction.MERGE,
                    target=context, confidence=confidence
                )
            elif confidence >= 0.70:
                return ResolutionResult(
                    action=ResolutionAction.CONFIRM,
                    target=context, confidence=confidence
                )
        
        # Step 5: 新建
        return ResolutionResult(
            action=ResolutionAction.CREATE,
            target=None, confidence=0.0
        )
```

### 缺失2：商机匹配度五维算法——完全没提（P0）

PRD F-05定义了五维打分法，技术设计的`_calculate_strength`只有4行简陋代码（base 0.3 + same_company 0.2 + same_industry 0.1 + co_occurrence 0.15），这连PRD的关联强度都算不对。

需要补：

```python
class OpportunityMatcher:
    """商机匹配度——五维打分法"""
    
    async def calculate_match_score(
        self,
        todo: Todo,
        person: Entity,
        context: MatchContext,
    ) -> float:
        """
        五维加权打分，满分1.0
        - D1 关键词重叠 (0.30): 核心需求词+行业术语的匹配度
        - D2 行业一致性 (0.25): 领域分类L1是否一致
        - D3 话题语义相似度 (0.20): 话题标签余弦相似度
        - D4 LLM语义判断 (0.15): GPT判断关联语义
        - D5 历史合作 (0.05): 过往合作记录
        总权重: 0.95（预留0.05扩展）
        """
        scores = {}
        
        # D1: 关键词重叠
        scores["keyword"] = self._keyword_overlap(
            todo.keywords, person.keywords
        )  # Jaccard similarity
        
        # D2: 行业一致性
        scores["industry"] = 1.0 if (
            todo.domain_l1 == person.domain_l1
        ) else 0.0
        
        # D3: 话题语义相似度
        scores["topic"] = self._topic_cosine_similarity(
            todo.topic_vector, person.topic_vector
        )
        
        # D4: LLM语义判断
        scores["llm"] = await self._llm_semantic_judge(
            todo, person
        )
        
        # D5: 历史合作
        scores["history"] = self._history_score(
            person.id, context
        )
        
        # 加权求和
        weights = {
            "keyword": 0.30,
            "industry": 0.25,
            "topic": 0.20,
            "llm": 0.15,
            "history": 0.05,
        }
        total = sum(
            scores[k] * weights[k] for k in weights
        )
        
        return min(total, 1.0)
```

### 缺失3：话题标签数据结构+余弦相似度算法（P1）

PRD §5.5定义了话题标签体系（仅meeting/call管线提取），技术设计没有任何数据结构。

需要补：

```python
# 话题标签表
class TopicTag(Base):
    __tablename__ = "topic_tags"
    
    id: Mapped[str]  # UUID
    event_id: Mapped[str]  # 关联事件
    tag_name: Mapped[str]  # 标签名（如"SaaS定价策略"）
    tag_vector: Mapped[list]  # embedding向量（1536维）
    source_pipeline: Mapped[str]  # meeting / call
    confidence: Mapped[float]  # 提取置信度
    created_at: Mapped[datetime]

# 余弦相似度
def cosine_similarity(v1: list, v2: list) -> float:
    """计算两个向量的余弦相似度"""
    dot = sum(a * b for a, b in zip(v1, v2))
    norm1 = sum(a * a for a in v1) ** 0.5
    norm2 = sum(b * b for b in v2) ** 0.5
    if norm1 == 0 or norm2 == 0:
        return 0.0
    return dot / (norm1 * norm2)
```

### 缺失4：领域分类YAML配置（P1）

PRD §5.4方案D（L1预定义18个领域+L2动态扩展），技术设计没有对应配置。

需要补：

```yaml
# configs/domain_taxonomy.yaml
version: "1.0"
description: "领域分类体系——方案D"

L1_domains:
  D01: 互联网/软件
  D02: 金融/投资
  D03: 制造业
  D04: 教育/培训
  D05: 医疗/健康
  D06: 房地产/建筑
  D07: 零售/消费
  D08: 能源/环保
  D09: 交通/物流
  D10: 传媒/内容
  D11: 法律/咨询
  D12: 农业/食品
  D13: 政府/公共事务
  D14: 硬件/半导体
  D15: 文化/娱乐
  D16: 旅游/酒店
  D17: 电信/通信
  D18: 其他

L2_rules:
  min_frequency: 5  # 至少出现5次才可升级为L2
  max_L2_per_domain: 20
  approval: auto  # auto=自动 / manual=人工确认
```

### 缺失5：Todo状态机（P0）

技术设计的todos表status是VARCHAR(15)但没定义合法值和流转规则。

需要补：

```sql
-- 方案A: PostgreSQL ENUM
CREATE TYPE todo_status AS ENUM (
    'pending', 'in_progress', 'done', 'dismissed', 'snoozed'
);

ALTER TABLE todos ALTER COLUMN status TYPE todo_status
    USING status::todo_status;

-- 合法流转
-- pending → in_progress / dismissed / snoozed
-- in_progress → done / dismissed / pending
-- snoozed → pending (定时恢复)
-- done / dismissed 为终态

-- snoozed到期自动恢复
CREATE TABLE todo_snooze_schedule (
    todo_id VARCHAR(36) PRIMARY KEY,
    snoozed_until TIMESTAMPTZ NOT NULL,
    original_status VARCHAR(15) NOT NULL DEFAULT 'pending'
);
```

```python
# 定时恢复逻辑
class SnoozeRecoveryScheduler:
    """定时扫描snoozed→pending恢复"""
    
    async def recover_expired_snoozes(self):
        now = datetime.utcnow()
        expired = await self.db.execute(
            select(TodoSnoozeSchedule)
            .where(TodoSnoozeSchedule.snoozed_until <= now)
        )
        for snooze in expired:
            await self.db.execute(
                update(Todo)
                .where(Todo.id == snooze.todo_id)
                .values(status=snooze.original_status)
            )
            await self.db.delete(snooze)
```

### 缺失6：same_city关联推断逻辑（P1）

PRD v1.3加了same_city关联类型，技术设计没有。

需要补：

```python
def _infer_same_city(
    self, entity_a: Entity, entity_b: Entity
) -> Tuple[bool, float]:
    """
    推断same_city关联。
    来源优先级：
    1. 名片JSON city字段（置信度0.9）
    2. 公司地址推断（置信度0.7）
    3. LLM从会议记录推断（置信度0.5）
    4. 用户手动录入（置信度1.0）
    
    区分三种城市类型：
    - company_city: 公司所在城市
    - residence_city: 居住地
    - visited_city: 到访城市（来自会议记录）
    
    仅company_city和residence_city用于same_city关联，
    visited_city不触发（出差见过一面不算同城）
    """
    # 获取城市信息（从properties JSONB提取）
    city_a = self._get_city(entity_a, priority=["company_city", "residence_city"])
    city_b = self._get_city(entity_b, priority=["company_city", "residence_city"])
    
    if not city_a or not city_b:
        return False, 0.0
    
    if city_a["city"] == city_b["city"]:
        # 取较低置信度
        confidence = min(city_a["confidence"], city_b["confidence"])
        return True, confidence
    
    return False, 0.0
```

### 缺失7：关联强度时间衰减函数（P1）

PRD术语表提了"时间衰减λ=0.01"，技术设计没有实现。

需要补：

```python
def time_decay_weight(
    last_interaction: datetime,
    reference_time: datetime = None,
    lam: float = 0.01,
) -> float:
    """
    指数时间衰减函数
    λ=0.01 时：
    - 7天: 0.93  → 1.0档
    - 30天: 0.74 → 0.8档
    - 90天: 0.41 → 0.4档
    - 180天: 0.17 → 0.2档
    - 365天: 0.03 → 0.1档
    """
    if reference_time is None:
        reference_time = datetime.utcnow()
    
    days = (reference_time - last_interaction).days
    if days < 0:
        return 1.0
    
    return math.exp(-lam * days)

def calculate_association_strength(
    base: float,
    evidence_count: int,
    last_interaction: datetime,
    frequency: int = 1,
) -> float:
    """
    关联强度 = base × evidence_boost × time_decay × frequency_factor
    """
    # 证据加成（每次交互+0.05，上限0.3）
    evidence_boost = min(0.3, evidence_count * 0.05)
    
    # 时间衰减
    decay = time_decay_weight(last_interaction)
    
    # 频率因子（高频交互额外加成）
    frequency_factor = min(1.5, 1.0 + frequency * 0.1)
    
    return min(1.0, (base + evidence_boost) * decay * frequency_factor)
```

### 缺失8：离线策略（P2）

PRD §5.10定义了离线能力矩阵，技术设计没有前端离线方案。对许总"开车去拜访"场景是刚需。

PoC阶段可以不补，但Phase1之前必须补。

### 缺失9：EventLink→CarryMem写入映射表（P2）

技术设计有CarryMemProvider协议，但只定义了`declare_memory`一个方法。需要明确：

| EventLink产出 | 写入CarryMem记忆类型 | 调用方法 |
|--------------|---------------------|---------|
| 新实体 | fact_declaration | declare_memory |
| 新关联 | relationship | declare_memory |
| 用户确认归一 | decision | declare_memory |
| 用户忽略Todo | user_preference → 规则引擎 | update_rule |
| 商机匹配结果 | decision | declare_memory |

---

## 四、PRD和技术设计需要对齐的矛盾点

| # | 矛盾点 | PRD说法 | 技术设计说法 | 建议对齐方案 |
|---|--------|---------|-------------|-------------|
| 1 | **存储策略** | §5.12提到Redis+PG+ES三层 | §1.2明确"PostgreSQL + Redis"，PoC用Docker单机无Redis | PoC用SQLite（CarryMem哲学），Phase1用PG+Redis，ES推迟到Phase2 |
| 2 | **关联强度** | 术语表提"时间衰减λ=0.01" | §4.3的算法没有时间衰减 | 补时间衰减函数（见缺失7） |
| 3 | **商机匹配度** | F-05五维打分法 | 完全没有 | 必须补（见缺失2） |
| 4 | **Event.raw_text长度** | PRD说≤500KB | 技术设计TEXT无长度限制 | 补CHECK约束或应用层校验 |
| 5 | **CarryMem协议** | 技术设计recall_memories用硬编码字符串匹配 | 应该用CarryMem的filter API | 改为调用CarryMem SDK的filter方法 |

### 存储策略详细建议

**PoC阶段（3周）**：SQLite + 内存缓存
- 理由：PoC验证AI能力，不是验证基础设施
- 零新依赖，和CarryMem一致
- 单机Docker部署

**Phase1阶段（6周）**：PostgreSQL + Redis
- PG替换SQLite，支持多用户并发
- Redis缓存热数据和会话
- 仍然不用ES，PG的GIN索引够用

**Phase2阶段**：视数据量决定是否引入ES
- 全文搜索量级上来后再考虑
- 先用PG的pg_trgm扩展兜底

---

## 五、PRD需要改进的点

### 1. 补CarryMem集成接口章节（P0）

技术设计做了Protocol接口，但PRD没有引用。PRD至少要声明：
- "技术设计文档§5定义了与CarryMem的解耦接口"
- "EventLink在CarryMem未部署时通过NullMemoryProvider降级运行"
- "CarryMem部署后，EventLink通过Protocol接口消费偏好、规则，写入事实、决策"

### 2. 存储策略统一声明（P0）

PRD需要在架构图下方明确：
- PoC：SQLite（CarryMem哲学，零新依赖）
- Phase1：PostgreSQL + Redis
- Phase2：按需引入ES

### 3. LLM成本估算（P1）

补典型场景的token/费用测算：

| 场景 | 每日量 | 每次Token | 日消耗 | 月费用(GPT-4o-mini) |
|------|--------|----------|--------|---------------------|
| 名片处理 | 5张 | ~500 | 2,500 | ~$0.4 |
| 会议处理 | 1场 | ~5,000 | 5,000 | ~$0.8 |
| 通话处理 | 2次 | ~2,000 | 4,000 | ~$0.6 |
| 关联发现 | 触发式 | ~1,000 | 2,000 | ~$0.3 |
| Todo生成 | 触发式 | ~800 | 1,600 | ~$0.25 |
| **合计** | | | **~15,100** | **~$2.35/月/用户** |

### 4. 关联强度公式（P1）

术语表提了λ=0.01但没给完整公式。建议补一个简化版：

> strength = (base + min(0.3, evidence × 0.05)) × e^(-λ × days_since_last) × min(1.5, 1 + frequency × 0.1)
>
> 其中base由关联类型决定：alumni=0.5, ex_colleague=0.5, same_city=0.3, tech_overlap=0.4, deal_link=0.6, risk_link=0.7, supply_chain=0.5, competitor=0.4

---

## 六、技术设计需要补的优先级清单

| # | 缺失项 | 优先级 | 估算工作量 | 理由 |
|---|--------|--------|-----------|------|
| 1 | 实体归一5步算法核心代码 | P0 | 2天 | PoC核心功能，不补无法开发 |
| 2 | 商机匹配度五维算法 | P0 | 1天 | F-05核心算法，PRD已定义但技术设计未实现 |
| 3 | Todo状态机（CHECK+流转+定时恢复） | P0 | 0.5天 | 数据完整性保障 |
| 4 | 话题标签数据结构+余弦相似度算法 | P1 | 1天 | F-05第三维依赖 |
| 5 | 领域分类YAML配置+L2动态扩展逻辑 | P1 | 1天 | F-05第二维依赖 |
| 6 | same_city推断逻辑 | P1 | 0.5天 | PRD v1.3新增关联类型 |
| 7 | 关联强度时间衰减函数 | P1 | 0.5天 | PRD术语表已定义λ=0.01 |
| 8 | LLM prompt模板（至少PoC用的3个） | P1 | 1天 | 4条管线的核心驱动 |
| 9 | 离线策略（前端） | P2 | 2天 | Phase1前必须补 |
| 10 | EventLink→CarryMem写入映射表 | P2 | 0.5天 | Phase2集成时需要 |

**总估算**：P0约3.5天，P1约4天，P2约2.5天

---

## 七、Slogan建议

### 现有Slogan的问题

- "让重要的人，不止停留在微信里"——功能描述，不是情绪钩子。用户读到会想"嗯有道理"但不会心动
- "每次见面，都不白费"——负面表述（避免损失），不是正面渴望

核心问题：**描述产品做什么，而不是用户为什么要用。**

### 商务人士的真正痛点

1. "见过了，但没下文"——最常见的挫败感
2. "该找谁，想不起来"——遗忘恐惧
3. "想跟进，没理由"——最直接，许总场景

### 建议Slogan

**主Slogan**：
> **见面只是开始。**

5个字，短，有力度。重新定义"见面"——不是终点，是起点。用户会自己想"对，然后呢？"

**副Slogan**：
> **下次联系的理由，我们给你找好了。**

回答了"然后呢"，直接指向核心能力（Todo/行动建议）。

**组合效果**：
> 见面只是开始。下次联系的理由，我们给你找好了。

| | 现有 | 建议 |
|---|---|---|
| 主slogan | 让重要的人，不止停留在微信里 | 见面只是开始 |
| 副slogan | 每次见面，都不白费 | 下次联系的理由，我们给你找好了 |
| 情绪反应 | "嗯有道理" | "对，然后呢？"→"哦，帮我找好了" |
| 行动暗示 | 弱（描述状态） | 强（指向行动） |
| 产品指向 | 模糊 | 精准（Todo/行动建议） |
| 表述方式 | 正面+负面混合 | 全正面 |

---

## ✅ 行动清单

| # | 行动 | 负责方 | 时间窗 |
|---|------|--------|--------|
| 1 | 补实体归一5步算法核心代码 | CarryMem团队 | PoC启动前 |
| 2 | 补商机匹配度五维算法 | CarryMem团队 | PoC启动前 |
| 3 | 补Todo状态机（SQL ENUM+流转+定时恢复） | CarryMem团队 | PoC启动前 |
| 4 | PRD补CarryMem集成接口声明 | 产品侧 | 本周 |
| 5 | PRD与技术设计存储策略对齐 | 产品+架构 | 本周 |
| 6 | 补话题标签+领域分类数据结构 | CarryMem团队 | Phase1前 |
| 7 | 补same_city推断+时间衰减算法 | CarryMem团队 | Phase1前 |
| 8 | Slogan更新（"见面只是开始"） | 产品侧 | 品牌物料制作前 |

---

## ⚠️ 待确认 / 假设 / Non-goals

### 待确认
- PoC是否用SQLite？（建议：是，和CarryMem一致）
- same_city的城市信息来源优先级？（名片字段 > 公司地址 > LLM推断 > 手动）
- Person画像数据存在Entity.properties JSONB还是独立profile表？
- LLM prompt模板用GPT-4o-mini还是支持本地模型？

### 假设
- 技术设计v1.3中的CarryMemProvider协议是最终版本，不会大幅调整
- PoC阶段不需要离线功能
- ES推迟到Phase2再评估

### Non-goals
- 本审阅不涉及UI/UX设计评审
- 不涉及许总团队前端架构评审
- 不涉及部署运维方案评审

---

## 📚 数据来源 & 成员产出索引

- PRD v3.3：`./docs/spec/PRD_V1.md`
- 技术设计 v1.3：`./docs/architecture/EventLink_技术设计_v1.md`
- CarryMem团队EventLink设计（基准对比）：`./WorkBuddy/20260320114823/ai-memory/CarryMem_EventLink_事件驱动关联发现_产品设计.md`
- 内部评审报告目录：`./docs/internal/`

---

> 本报告由产品战略团队 AI 协作生成，重要决策请由产品负责人审定。
