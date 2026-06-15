# PromiseLink 第一轮：PRD v3.2 + 技术设计 v1.1 审核 — 7角色审核报告

> **审核轮次**: 第一轮：PRD v3.2 + 技术设计 v1.1 审核
> **审核日期**: 2026-06-02
> **审核对象**: PRD v3.2 + 技术设计 v1.1
> **共识结论**: 不通过
> **平均评分**: 0.0/10
> **通过率**: 4/7

---

## 架构师 (architect)

# PromiseLink 架构师审核意见

## 一、关键问题（P0/P1）

### P0-1：H5-小程序通信协议存在严重安全漏洞

**问题定位**：§2.3 前端架构 - Phase 1 通信协议

**问题描述**：
```javascript
// 小程序端：打开WebView时传递上下文
wx.navigateTo({
  url: `/pages/webview/webview?token=${token}&person_id=${personId}&action=profile`
})
```
token通过URL参数明文传递，存在三大安全风险：
1. **日志泄露**：URL会被记录在WebView访问日志、微信后台日志中
2. **中间人攻击**：URL参数可被代理服务器截获
3. **跨域风险**：H5页面若存在XSS漏洞，token可被JS读取

**改进方案**：
```javascript
// 方案A：postMessage双向握手（推荐）
// 小程序端
wx.navigateTo({ url: '/pages/webview/webview' })
webview.onReady(() => {
  webview.postMessage({ type: 'auth', token: encrypted_token })
})

// H5端
wx.miniProgram.onMessage(e => {
  if (e.type === 'auth') {
    sessionStorage.setItem('_t', e.token)
  }
})

// 方案B：临时授权码模式（更安全）
// 1. 小程序请求服务端生成一次性code
// 2. URL传递code而非token
// 3. H5首次加载用code换token
```

**优先级**：P0 - 必须在Phase 1实施前解决，否则存在数据泄露风险

---

### P0-2：PostgreSQL JSONB索引策略不足以应对关联暴增场景

**问题定位**：§3.1 数据模型 - entities表定义

**问题描述**：
```sql
CREATE INDEX idx_entities_properties ON entities USING gin(properties);
```
当单个用户积累5000+实体、10万+关联后，GIN索引会面临：
1. **写入性能退化**：每次properties更新需重建整个JSONB索引
2. **查询膨胀**：`properties @> '{"company":"XX科技"}'` 需全表扫描GIN索引
3. **内存压力**：GIN索引元组占用空间是原数据的3-5倍

**数据推演**：
- 单用户1年扫描2000张名片 → 2000 entities
- 每人平均关联5个实体 → 10000 associations
- properties平均1KB → GIN索引需15MB/用户
- 100并发用户查询 → 1.5GB内存占用

**改进方案**：
```sql
-- 方案A：拆分高频查询字段（推荐Phase 1实施）
ALTER TABLE entities 
  ADD COLUMN company VARCHAR(100),
  ADD COLUMN title VARCHAR(100),
  ADD COLUMN city VARCHAR(50),
  ADD COLUMN industry VARCHAR(50);

CREATE INDEX idx_entities_company ON entities(user_id, company) WHERE company IS NOT NULL;
CREATE INDEX idx_entities_city ON entities(user_id, city) WHERE city IS NOT NULL;

-- properties仅存低频字段（decision/resources/relationship）
-- 查询：WHERE company='XX科技' 走B-tree，比GIN快10倍

-- 方案B：引入图数据库（Phase 2考虑）
-- Neo4j/AgenGraph专为关系查询优化
-- 迁移策略：PG存基础数据，图库存关联关系
```

**验证方案**：
```python
# 性能基准测试脚本
import time, psycopg2
conn = psycopg2.connect(...)

# 测试1：GIN索引查询
start = time.time()
cur.execute("SELECT * FROM entities WHERE properties @> '{"company":"XX科技"}'")
gin_time = time.time() - start

# 测试2：B-tree索引查询
start = time.time()
cur.execute("SELECT * FROM entities WHERE company='XX科技'")
btree_time = time.time() - start

assert btree_time < gin_time * 0.1, "B-tree应比GIN快10倍"
```

**优先级**：P0 - 必须在Phase 1完成前引入列索引，否则100+用户并发时P95延迟>5s

---

### P1-1：服务拆分与Phase 1同进程部署存在架构风险

**问题定位**：§2.2 服务拆分

**问题描述**：
> "Phase 1 五个服务部署在同一FastAPI进程中，通过模块边界隔离。Phase 2 可拆分为独立微服务。"

这种"先单体后拆分"策略存在三大风险：
1. **循环依赖陷阱**：同进程模块间易出现`Ingest → Todo → Query → Ingest`的循环引用
2. **事务边界模糊**：跨模块调用无法回滚，例如`Todo生成失败但Entity已落库`
3. **重构成本高**：Phase 2拆分时需改造所有跨模块调用为HTTP/RPC

**改进方案**：
```python
# 方案：Phase 1即采用"内部RPC"模式（伪微服务）
# 1. 所有跨模块调用通过内部RPC接口
class InternalRPC:
    async def call_service(self, service: str, method: str, **kwargs):
        # Phase 1：进程内直接调用
        return await getattr(SERVICE_REGISTRY[service], method)(**kwargs)
        
        # Phase 2：改为HTTP调用（代码无需修改）
        # return await http_client.post(f"{SERVICE_URL}/{method}", json=kwargs)

# 2. 强制接口契约
class TodoService:
    @rpc_endpoint
    async def generate(self, event_id: UUID, entities: List[UUID]) -> List[TodoDTO]:
        # 只能通过DTO传参，禁止传ORM对象
        ...

# 3. 事务通过消息队列解耦
@transactional
async def process_event(event: Event):
    entities = await extract_entities(event)  # 本地事务
    await mq.publish("entity.extracted", entities)  # 异步触发Todo生成
```

**验证清单**：
- [ ] 所有跨模块调用都通过RPC接口（禁止直接import其他模块的service）
- [ ] 接口参数/返回值都是DTO（禁止传递ORM对象）
- [ ] 长事务改为事件驱动（Ingest完成→MQ→Todo生成）

**优先级**：P1 - 建议Phase 1即实施，否则Phase 2重构成本翻倍

---

### P1-2：CarryMem解耦设计的协议接口存在遗漏

**问题定位**：§5.1 协议接口

**问题描述**：
`MemoryProvider` Protocol定义了3个方法：
```python
def is_available(self) -> bool
def recall_preferences(self, user_id: str) -> Dict
def match_rules(self, user_id: str, context: str) -> List[str]
```

但缺少关键能力：
1. **声明记忆**：PromiseLink生成的Todo需反哺CarryMem（如"用户确认了XX是竞对"）
2. **纠正反馈**：用户驳回AI推断时（如"这不是竞对"），需更新CarryMem规则
3. **健康检查**：`is_available()`仅返回bool，无法区分"未启用"vs"连接超时"vs"版本不兼容"

**改进方案**：
```python
from enum import Enum
from typing import Optional

class MemoryStatus(Enum):
    AVAILABLE = "available"
    DISABLED = "disabled"
    TIMEOUT = "timeout"
    VERSION_MISMATCH = "version_mismatch"

@runtime_checkable
class MemoryProvider(Protocol):
    def check_health(self) -> tuple[MemoryStatus, Optional[str]]:
        """返回(状态, 错误详情)"""
        ...
    
    def recall_preferences(self, user_id: str) -> Dict:
        ...
    
    def match_rules(self, user_id: str, context: str) -> List[str]:
        ...
    
    def declare_memory(self, user_id: str, memory: Dict) -> bool:
        """向CarryMem声明新记忆"""
        ...
    
    def update_rule(self, user_id: str, rule_id: str, action: str) -> bool:
        """更新规则（如forbid/avoid）"""
        ...

# 使用示例
class TodoService:
    def generate(self, event: Event):
        todos = self._ai_generate(event)
        
        # 用户确认竞对关系后，声明给CarryMem
        if user_confirmed_competitor:
            self.memory.declare_memory(
                user_id=event.user_id,
                memory={
                    "type": "competitor_relation",
                    "entities": [a.id, b.id],
                    "confidence": 1.0,
                    "source": "user_confirmed"
                }
            )
```

**优先级**：P1 - 建议Phase 1补充，否则CarryMem只能单向消费无法闭环

---

## 二、改进建议

### P2-1：Todo语义模型存在歧义

**问题定位**：§3.1 数据模型 - Todo表

**问题描述**：
> "语义：因为某个事件(原因)，对某个实体(对象)，维护某段关系(目标)"

但实际字段设计存在矛盾：
```sql
source_event UUID,               -- 为什么产生（可选，系统提醒无来源事件）
target_entities UUID[],          -- 对谁做（可多人）
target_association UUID,         -- 维护哪段关系（可选）
```

**场景冲突**：
- 场景A："扫描张总名片，发现他和李总都认识王总" → `target_entities=[张总,李总]`，但`target_association`指向哪个？
- 场景B："每日提醒：李总2周未联系" → `source_event=NULL`，但关系从何而来？

**改进方案**：
```sql
-- 方案：拆分为两种Todo类型
-- 类型1：关系型Todo（单个关系维护）
CREATE TABLE relationship_todos (
    id UUID PRIMARY KEY,
    source_event UUID,                    -- 触发事件（可NULL）
    target_association UUID NOT NULL,     -- 必填：明确维护哪段关系
    person_a UUID NOT NULL,               -- 关系端点A
    person_b UUID NOT NULL,               -- 关系端点B
    action_type VARCHAR(20),              -- 破冰/跟进/引荐
    ...
);

-- 类型2：任务型Todo（多实体协同）
CREATE TABLE task_todos (
    id UUID PRIMARY KEY,
    source_event UUID NOT NULL,           -- 必填：来自哪个会议/通话
    involved_entities UUID[] NOT NULL,    -- 参与人列表
    task_description TEXT,
    assignee UUID,                        -- 谁负责执行
    ...
);
```

**优先级**：P2 - 建议Phase 1重新设计，否则查询逻辑复杂且易出错

---

### P2-2：TTS服务过渡方案缺少降级策略

**问题定位**：PRD §1.5.2 旅程二 - 环节B+（会前语音播报）

**问题描述**：
> "系统 → TTS读出人物简介：'张总，XX科技供应链总监...'"

设计方案：Phase 1用微信同声传译插件，Phase 2切讯飞/Azure。但缺少：
1. **插件失效降级**：微信插件若限流/故障，如何回退？
2. **跨端兼容性**：iOS/Android微信版本差异导致插件不可用？
3. **离线场景**：电梯/地铁无网络时无法播报？

**改进方案**：
```python
class TTSService:
    def __init__(self):
        self.providers = [
            WechatTTSProvider(),      # 优先
            LocalCacheTTSProvider(),  # 降级1：预生成的常用话术音频
            TextFallbackProvider()    # 降级2：纯文本展示
        ]
    
    async def speak(self, text: str) -> TTSResult:
        for provider in self.providers:
            try:
                result = await provider.generate(text)
                if result.success:
                    return result
            except Exception as e:
                logger.warning(f"{provider} failed: {e}")
                continue
        
        # 最终降级：纯文本
        return TTSResult(success=False, fallback_text=text)

# 预生成常用话术
COMMON_TEMPLATES = [
    "关系阶段：{stage}。偏好：{channel}。上次：{last_topic}。建议：{suggestion}。"
]
# 启动时预生成100条音频缓存至本地
```

**优先级**：P2 - 建议Phase 1实施，否则许总核心场景不可用时无回退

---

### P2-3：事件处理管线缺少幂等性设计

**问题定位**：§4.1 事件处理管线

**问题描述**：
> "Step 2: LLM实体抽取 → Step 3: 实体归一 → Step 4: 关联发现 → Step 5: Todo生成"

若Step 3失败重试，Step 2的LLM调用会重复执行，导致：
1. **成本浪费**：单次事件重试3次→LLM调用费用×3
2. **数据重复**：Step 2已落库的Entity未回滚，重试后产生duplicate

**改进方案**：
```python
# 方案：基于event_id的幂等性缓存
class EventPipeline:
    async def process(self, event: Event):
        cache_key = f"pipeline:{event.id}"
        
        # Step 2：LLM抽取（幂等）
        entities = await redis.get(cache_key + ":entities")
        if not entities:
            entities = await llm_extract(event)
            await redis.setex(cache_key + ":entities", 3600, entities)
        
        # Step 3：实体归一（可重试）
        try:
            unified = await entity_unify(entities)
        except Exception:
            # 重试时直接读缓存，不重复调用LLM
            raise
        
        # Step 4-5：原子事务
        async with db.transaction():
            assocs = await discover_associations(unified)
            todos = await generate_todos(event, assocs)
            await db.commit()
```

**优先级**：P2 - 建议Phase 1实施，否则故障重试成本高昂

---

### P3-1：日程同步方案存在技术盲区

**问题定位**：PRD §2.8 US-27 日程表双向对接

**问题描述**：
> "支持Apple Calendar和Google Calendar(Android)两种日历源"

技术挑战：
1. **Apple Calendar**：iOS无公开API读取系统日历，只能通过`EventKit`框架在原生App中访问
2. **跨平台兼容**：Android的Google Calendar和国内手机的"日历"（小米/华为定制）API不同
3. **授权复杂度**：需用户手动授予日历读写权限，转化率<30%

**建议调整**：
```yaml
Phase 1（最小可行方案）：
  - 仅支持手动导入日历事件（用户复制粘贴会议标题）
  - 或通过企业微信/飞书API读取日历（需企业授权）

Phase 2（原生能力）：
  - iOS：开发原生小程序插件，用EventKit读取日历
  - Android：接入Google Calendar API（需OAuth2）
  - 国内手机：放弃系统日历，对接企业应用日历

Phase 3（主动性方案）：
  - 邮件解析：扫描用户邮箱中的会议邀请邮件
  - 会议平台集成：对接腾讯会议/飞书会议的Webhook
```

**优先级**：P3 - 建议Phase 1降级为手动导入，原生日历同步延后至Phase 2

---

### P3-2：通知架构缺少优先级队列

**问题定位**：§2.2 服务拆分 - Notify服务

**问题描述**：
> "Notify: 推送通知 - 微信服务号模板消息, APNs/FCM"

当单用户一天产生50+Todo时，推送风暴会导致：
1. **用户疲劳**：早上收到20条通知，全部忽略
2. **触达失效**：重要提醒淹没在噪音中
3. **微信限流**：服务号模板消息单日上限100条/用户

**改进方案**：
```python
class NotifyService:
    PRIORITY_RULES = {
        "meeting_in_1h": (priority=1, channel="push+sms"),    # 会前1小时：最高优先级
        "todo_overdue": (priority=2, channel="push"),         # 逾期Todo：高优先级
        "new_opportunity": (priority=3, channel="digest"),    # 新商机：合并到每日简报
        "background_info": (priority=4, channel="silent")     # 背景信息：静默通知
    }
    
    async def send(self, user_id: str, notifications: List[Notification]):
        # 1. 按优先级分组
        grouped = self._group_by_priority(notifications)
        
        # 2. P1/P2实时推送，P3/P4合并到简报
        for p1 in grouped[1]:
            await self._push_realtime(p1)
        
        # 3. 限流保护
        daily_count = await redis.incr(f"notify:{user_id}:daily")
        if daily_count > 20:
            # 超限后仅保留P1，其余延迟到第二天
            grouped = {1: grouped[1]}
```

**优先级**：P3 - 建议Phase 2实施，Phase 1先控制总推送量<10条/天

---

## 三、整体评估

### 架构健壮性：7/10

**优点**：
- ✅ 事件驱动架构清晰，Event→Entity→Association→Todo链路完整
- ✅ CarryMem解耦设计理念正确，Protocol接口思路可行
- ✅ 配置化设计（YAML分类法）灵活性好，支持行业定制

**不足**：
- ❌ **H5-小程序通信**存在严重安全漏洞（P0）
- ❌ **PG索引策略**无法支撑10万+关联查询（P0）
- ⚠️ **服务拆分**Phase 1同进程部署埋下重构隐患（P1）
- ⚠️ **CarryMem协议**缺少声明/纠正接口（P1）

### 性能可扩展性：6/10

**优点**：
- ✅ Redis缓存层设计到位
- ✅ LLM调用有成本控制和降级策略

**不足**：
- ❌ **JSONB索引**会成为瓶颈，需补充列索引（P0）
- ⚠️ **关联发现算法**时间复杂度O(n²)，5000实体时需25M次比较（P2优化空间）
- ⚠️ **通知推送**无优先级队列，易触发微信限流（P3）

### 安全性与可靠性：5/10

**优点**：
- ✅ 事件幂等性有考虑（虽未实施）
- ✅ Todo反馈闭环设计完整

**不足**：
- ❌ **token明文传递**严重违反安全基本原则（P0）
- ⚠️ **事务边界模糊**，跨模块调用无回滚机制（P1）
- ⚠️ **TTS降级**缺失，核心场景不可用时无回退（P2）

### 可维护性：7/10

**优点**：
- ✅ 配置化设计降低代码侵入
- ✅ Protocol接口思路可复用

**不足**：
- ⚠️ **Todo语义模型**存在歧义，需重构（P2）
- ⚠️ **同进程部署**为Phase 2重构埋雷（P1）

---

## 四、审核结论

### 综合评分：6.5/10

**结论**：**有条件通过，需修复P0问题后重审**

### 必须修复项（Phase 1开发前）：
1. ✅ 重新设计H5-小程序通信协议（postMessage双向握手或临时授权码）
2. ✅ 补充PG列索引（company/city/industry），保留JSONB索引仅存低频字段
3. ✅ 完善CarryMem Protocol接口（补充declare_memory/update_rule/check_health）

### 建议改进项（Phase 1开发中）：
4. ✅ 采用内部RPC模式部署五服务（为Phase 2拆分铺路）
5. ✅ 重构Todo表为relationship_todos + task_todos双表
6. ✅ 实现事件处理管线幂等性（Redis缓存LLM结果）

### 可延后项（Phase 2考虑）：
7. ⏸️ 引入图数据库优化关联查询
8. ⏸️ 通知优先级队列+合并推送策略
9. ⏸️ 日程同步降级为手动导入（原生能力延后）

---

**最终建议**：修复P0-1/P0-2两个核心问题后，可进入Phase 1开发。P1问题建议在开发首周完成架构调整，否则Phase 2重构成本将远超预期。

---

## 产品经理 (product-manager)

# 产品经理审核意见

## 一、关键问题（P0/P1）

### P0 - 必须解决

**P0-1: 产品定位与slogan存在认知断层**

**问题位置**: §1.1 产品愿景

**具体问题**: 
- slogan"让重要的人，不止停留在微信里"传达的是"从微信走向线下行动"，但产品核心价值是"关系经营助手"，两者没有直接关联
- 用户第一反应可能是"又一个通讯录管理工具"，无法立即理解"AI合作关系经营"的差异化价值
- 与竞品Notion AI、飞书多维表格的slogan对比，缺乏行动导向和情感共鸣

**改进建议**:
```
建议A（强调行动）: "每次见面，都不白费"
建议B（强调智能）: "AI帮你记住，该联系谁"
建议C（强调价值）: "把人脉，变成合作"

产品定位微调: "AI驱动的商务关系经营助手" → 增加"驱动"强调主动性
```

**P0-2: 旅程二环节B+移动场景设计不完整**

**问题位置**: §1.5.2 旅程二 - 环节B+

**具体问题**:
1. **缺少会中记录的替代方案**: 文档假设用户100%使用录音卡，但许总可能遇到：
   - 对方不同意录音的场景
   - 录音卡电量耗尽
   - 机密谈话禁止录音设备
   
2. **TTS播报内容过长**: "张总，XX科技供应链总监。关系阶段：单独见过面..."预计需要20-30秒，开车场景下用户无法等待完整播报

3. **语音录入后的确认机制缺失**: 用户说完"今天和张总聊了新项目预算"后，系统直接提交AI处理，万一用户口误或环境噪音干扰，无法撤回

**改进建议**:
```yaml
环节B+补充设计:
  会中记录替代方案:
    - 快捷笔记模板: "见了[谁] 聊了[话题] 下次[行动]"
    - 语音备忘录: 调用微信录音，会后再转文字
    - 拍照记录: 拍白板/PPT，后台OCR提取要点
  
  TTS播报分级:
    - 极简版(5秒): "张总，供应链总监，上次聊新项目"
    - 完整版(30秒): 点击"详细"后播放
    - 视觉辅助: 同时显示文字，支持边听边看
  
  语音录入确认:
    - 转文字后弹出3秒预览: "识别为: 今天和张总..."
    - 用户可选: ✓提交 / ✗重录 / ✎编辑
```

**P0-3: 名片小程序合并决策的用户流程断裂**

**问题位置**: §1.3 核心价值主张（三层架构图）

**具体问题**:
1. **入口混乱**: 用户在"名片小程序"扫描名片后，需要手动点击"关系助手"才能看到PromiseLink功能，增加了一次操作成本
2. **数据孤岛风险**: 名片夹与PromiseLink的实体库如何同步？如果用户在名片夹修改了联系方式，PromiseLink能否感知？
3. **心智模型冲突**: 名片小程序的心智是"静态通讯录"，PromiseLink的心智是"动态关系网"，两者合并后用户可能困惑"我到底是在管理名片还是在经营关系？"

**改进建议**:
```
方案A（推荐）- 无缝整合:
  扫名片后立即展示:
    ├─ 基础信息（来自名片OCR）
    ├─ 🆕 AI发现的关联关系（自动弹出，无需点击）
    └─ 🆕 建议行动（置顶显示）
  
  数据同步策略:
    - 名片夹作为"展示层"，PromiseLink实体库作为"存储层"
    - 用户修改名片信息 → 自动同步到PromiseLink
    - PromiseLink发现新关联 → 实时推送到名片夹
  
  统一心智模型:
    - 改名片夹为"人脉库"
    - 名片扫描→人脉录入→关系发现→行动建议（线性流程）
```

---

### P1 - 重要问题

**P1-1: 许总"眼神不好喜欢听语音"需求未充分体现**

**问题位置**: §1.5.2 旅程二 - 环节B+ 会前场景

**具体问题**:
1. **TTS播报仅限于人物简介**: 文档中只提到播报"张总，XX科技供应链总监..."，但许总更需要的是**待办事项的播报**，比如"今天下午3点要见张总，记得确认华南区代工厂名单"
2. **缺少全局语音导航**: 许总可能想问"今天要见几个人？""有没有紧急待办？"，但文档未设计语音交互能力
3. **播报优先级不明确**: 如果今天有5个会议，系统应该先播报哪个？

**改进建议**:
```yaml
语音交互增强(F-19 TTS播报设计扩展):
  播报范围:
    - 今日日程播报: "今天有3个会议，最近的是下午2点..."
    - 待办事项播报: "有2个紧急待办，第一个是..."
    - 人物速览播报: "张总，上次见面聊了...，建议今天..."
  
  语音命令支持:
    - "今天日程" → 播报当天所有会议
    - "下一个待办" → 播报最近待办
    - "张总是谁" → 播报人物画像
    - "提醒我3点打电话" → 创建语音待办
  
  播报优先级算法:
    - 时间紧急度: 1小时内会议 > 今日会议 > 本周会议
    - 重要性: 决策者会议 > 日常同步
    - 用户偏好: 学习用户最常问的内容，优先播报
```

**P1-2: Phase 1三通道推送策略存在冗余风险**

**问题位置**: §4.3 推送通知策略

**具体问题**:
1. **微信服务号+小程序卡片可能重复推送**: 用户可能同时收到"服务号模板消息"和"小程序卡片提醒"，造成打扰
2. **APNs/FCM在iOS微信环境下可能失效**: 微信小程序无法直接调用系统通知，需要用户授权"允许通知"，但文档未说明授权失败时的降级方案
3. **防打扰策略（每小时≤3条）过于粗放**: 如果用户3小时内有5个会议，系统可能漏推2个会前提醒

**改进建议**:
```yaml
推送策略优化:
  通道优先级:
    - 会前提醒(高优): 服务号模板消息（必达）
    - 日常Todo(中优): 小程序卡片 or 应用内消息
    - 新发现关联(低优): 每日简报合并推送
  
  防打扰策略细化:
    - 会前提醒不受频次限制（但只推1次）
    - 紧急待办（截止时间<1小时）不受限制
    - 普通Todo合并为每日早晚2次推送
    - 新发现关联仅合并到早报
  
  降级方案:
    - APNs授权失败 → 自动切换到服务号推送
    - 服务号推送失败 → 记录到应用内消息中心
    - 用户关闭所有推送 → 仅显示应用内红点提醒
```

**P1-3: MVP-Core 7功能优先级需要调整**

**问题位置**: §3.1 MVP-Core功能清单

**具体问题**:
1. **F-06 Todo生成引擎优先级过高**: 在没有足够实体和关联数据时，Todo质量会很差，应该先做F-01~F-05，积累数据后再做F-06
2. **F-19 TTS播报设计放在MVP-Plus不合理**: 这是许总的核心需求，应该提前到MVP-Core
3. **F-21 CSV导入功能缺失**: 许总团队有大量存量联系人，如果没有CSV导入，冷启动会非常痛苦

**改进建议**:
```
MVP-Core优先级调整:
  Week 1-2:
    - F-01 事件上报接口
    - F-02 实体抽取服务
    - F-03 实体归一引擎
    - F-21 CSV导入功能（新增）★
  
  Week 2-3:
    - F-04 关联发现引擎
    - F-05 商机匹配度计算
    - F-19 TTS播报设计（提前）★
    - F-06 Todo生成引擎
  
  理由:
    - CSV导入是许总冷启动的刚需，必须Week 1支持
    - TTS播报是许总的核心使用场景，必须Week 2支持
    - Todo生成依赖前5个功能，放在Week 3更合理
```

---

## 二、改进建议（P2/P3）

### P2 - 重要改进

**P2-1: 产品方向"侧重人而非知识"在技术设计中未体现**

**问题**: 技术设计§5.5话题标签体系用了250+个标签，这是典型的"知识管理"思维，与"侧重人"的产品方向矛盾

**建议**: 
```yaml
话题标签简化为3层:
  L1 (6个大类): 技术/业务/资源/资本/市场/战略
  L2 (30个细分): 例如 技术→AI/IoT/Blockchain
  L3 (用户自定义): 例如 AI→大模型训练/推理优化
  
数据结构调整:
  - 删除预定义的250+标签库
  - 改为动态生成: LLM从会议纪要提取关键词 → 自动归类到L1/L2 → 用户确认后固化
  - 强调"这个人关心什么话题"，而不是"这个话题的知识图谱"
```

**P2-2: 防打扰策略未考虑用户主动触发场景**

**问题**: "每小时≤3条"只限制了系统推送，但用户可能主动刷新"今日日程"10次，每次都触发关联发现，造成服务器压力

**建议**:
```yaml
请求频率限制:
  - 查询类API: 每分钟≤10次（超过后返回缓存结果）
  - 事件上报: 每小时≤30次（防止恶意刷数据）
  - TTS播报: 每小时≤5次（超过后提示"您已超过播报次数"）
  
缓存策略:
  - "今日日程"缓存5分钟
  - 人物画像缓存10分钟
  - 关联关系缓存30分钟（除非有新事件触发更新）
```

### P3 - 可选优化

**P3-1: 新用户引导可以更具象化**

**建议**: 旅程一的引导页从"≤3屏"改为"1个视频+1个示例"
```
- 15秒动画: 扫名片→发现关联→收到行动建议
- 示例数据: 预置3个虚拟联系人，让用户立即看到关联效果
- 跳过按钮: 老用户可以直接开始使用
```

**P3-2: 关联发现的证据链可视化不足**

**建议**: US-22"关联发现的证据链查看"应该补充交互设计
```
展示方式:
  - 时间线视图: A(1月会议)→B(2月名片)→发现关联
  - 关系图谱: A-[同事]-C-[投资]-B，点击节点展开详情
  - 置信度标注: 每个推理步骤显示置信度分数
```

---

## 三、整体评估

### 优点
1. ✅ **产品定位清晰**: "AI合作关系经营助手"差异化明确，避开了传统CRM的红海
2. ✅ **用户旅程完整**: 三条旅程覆盖了冷启动、日常使用、数据管理全链路
3. ✅ **技术架构合理**: 事件驱动+实体归一+关联发现的三层引擎设计扎实
4. ✅ **MVP范围克制**: Phase 1聚焦核心闭环，避免过度设计

### 不足
1. ❌ **slogan与定位脱节**: "让重要的人，不止停留在微信里"无法传达核心价值
2. ❌ **许总场景覆盖不足**: TTS播报、语音交互、会中记录的设计不完整
3. ❌ **推送策略过于简化**: 防打扰规则可能导致重要提醒被漏推
4. ❌ **优先级需要调整**: CSV导入和TTS播报应该提前到MVP-Core

### 风险提示
1. **🔴 高风险**: 名片小程序合并后的用户心智模型冲突，可能导致用户困惑流失
2. **🟡 中风险**: 三通道推送可能造成重复打扰，影响用户体验
3. **🟢 低风险**: Phase 1功能较少，可能无法充分验证产品价值假设

---

## 四、最终结论

**综合评分**: **7.5/10**

**评分理由**:
- **产品定位(8/10)**: 清晰但slogan需要优化
- **用户旅程(7/10)**: 完整但许总场景设计不够深入
- **功能设计(8/10)**: 合理但优先级需要调整
- **技术可行性(9/10)**: 架构扎实，实现路径清晰
- **商业价值(6/10)**: 需要更多数据验证付费意愿

**审核结论**: **有条件通过，需修改P0问题后重新评审**

**建议修改内容**:
1. ✏️ 优化slogan，建议采用"每次见面，都不白费"
2. ✏️ 补充环节B+的会中记录替代方案和TTS播报分级设计
3. ✏️ 调整MVP-Core优先级，将CSV导入和TTS播报提前
4. ✏️ 完善名片小程序合并后的用户流程，避免心智模型冲突

**下一步行动**:
1. 产品经理修改PRD v3.2 → v3.3
2. 与许总团队确认TTS播报和语音交互的详细需求
3. UI设计师补充移动端交互原型
4. 开发团队评估技术实现难度和工期

---

**审核人**: Kiro AI (Product Manager Role)  
**审核日期**: 2026-06-02  
**下次评审**: PRD v3.3修改完成后

---

## 安全专家 (security)

# 安全专家审核意见

## 关键问题（P0/P1）

### P0 - 必须解决

**1. 小程序WebView token传递存在严重安全风险**

**位置**: 技术设计 §6.3 "小程序端：打开WebView时传递上下文"
```javascript
wx.navigateTo({
  url: `/pages/webview/webview?token=${token}&person_id=${personId}`
})
```

**问题**:
- Token明文拼接在URL中，会被记录在浏览器历史、服务器日志、代理服务器日志
- WebView页面可通过JavaScript读取URL参数，存在XSS窃取风险
- 如果H5页面被第三方iframe嵌入，token可能泄露

**改进方案**:
```javascript
// 方案1：使用一次性临时票据（推荐）
// 小程序端
const ticket = await requestTempTicket(token, person_id); // 60秒有效
wx.navigateTo({
  url: `/pages/webview/webview?ticket=${ticket}`
});

// H5端
const realToken = await exchangeTicket(ticket); // ticket单次使用后失效
sessionStorage.setItem('auth_token', realToken); // 存储在内存

// 方案2：使用postMessage桥接
wx.navigateTo({ url: '/pages/webview/webview' });
webview.postMessage({ 
  type: 'init', 
  token: encrypt(token), // 至少加密传输
  person_id: person_id 
});
```

**优先级**: P0 - 当前设计会导致token泄露，必须修改

---

**2. 录音数据传输和存储缺乏加密设计**

**位置**: PRD §1.5.2 "会中（录音卡静默采集）" + 技术设计缺失加密方案

**问题**:
- 录音卡（恒智易R1）采集的音频文件可能包含商业机密、客户隐私
- 文档未说明音频→文本转写过程中的数据流向（是否上传第三方ASR服务？）
- 转写后的文本存储在PostgreSQL的`events.raw_text`字段，未说明是否加密
- 如果使用云端ASR（如阿里/讯飞），音频文件会离开用户环境

**改进方案**:
```yaml
录音数据安全方案:
  采集阶段:
    - 录音卡本地存储启用AES-256加密
    - 传输到手机使用TLS 1.3 + 证书固定
  
  转写阶段:
    - 优先使用端侧ASR模型（如Whisper小型模型）
    - 如必须云端转写：
      a. 用户明确授权（"此次会议使用云端转写"）
      b. 音频文件临时加密上传（服务端不落盘）
      c. 转写完成后立即删除音频
      d. 在隐私政策中披露ASR服务商
  
  存储阶段:
    - raw_text字段使用列级加密（PostgreSQL pgcrypto）
    - 加密密钥存储在独立KMS（AWS KMS/Azure Key Vault）
    - 备份数据必须加密
```

**SQL示例**:
```sql
-- 列级加密
CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- 存储时加密
INSERT INTO events (raw_text) 
VALUES (pgp_sym_encrypt('敏感会议内容', '${KMS_KEY}'));

-- 读取时解密
SELECT pgp_sym_decrypt(raw_text::bytea, '${KMS_KEY}') 
FROM events WHERE id = '...';
```

**优先级**: P0 - 涉及录音数据，属于敏感个人信息，必须加密

---

**3. 微信服务号推送包含关系画像存在隐私泄露风险**

**位置**: PRD §1.5.2 "会前（开车/走路去拜访）"
```
系统 → 微信服务号推送会前提醒（提前15-60分钟）
     → 包含：对方姓名/公司/关系阶段/上次交流要点/建议话题
```

**问题**:
- 微信推送是明文传输到微信服务器，可能被微信读取
- 推送内容会显示在锁屏通知栏，周围人可见
- "关系阶段：单独见过面"、"建议：可提华南区代工厂对接"等信息泄露可能影响商务关系

**改进方案**:
```yaml
分级推送策略:
  公开级（锁屏可见）:
    - 标题: "今日会议提醒"
    - 内容: "15:00 与张总会面"  # 仅时间+姓氏
  
  敏感级（需打开App查看）:
    - 推送仅包含"点击查看会前准备"按钮
    - 点击后跳转到小程序，展示完整画像
    - 小程序内启用生物识别认证（Face ID/指纹）
  
  用户可配置:
    - 设置 → 隐私 → 推送敏感度（完整/简略/仅提醒）
    - 默认"简略"模式
```

**示例推送文案**:
```
❌ 不安全:
"15:00与张总会面。关系阶段：单独见过面。上次聊了新项目预算。建议可提华南区代工厂对接。"

✅ 安全:
标题: "今日会议 15:00"
内容: "与张总会面，点击查看准备清单 >"
```

**优先级**: P0 - 当前设计会在锁屏通知泄露敏感关系信息

---

**4. TTS语音播报存在信息泄露风险**

**位置**: PRD §1.5.2 "用户 → 点击🔊语音播报"
```
系统 → TTS读出人物简介："张总，XX科技供应链总监。关系阶段：单独见过面。
       偏好电话沟通。上次聊了新项目预算。建议：可提华外南区代工厂对接。"
```

**问题**:
- 许总在开车/走路场景使用，周围可能有同事、客户、陌生人
- 语音播报的商业关系信息（预算金额、资源对接）可能被他人听到
- 无法像屏幕一样快速隐藏信息

**改进方案**:
```yaml
安全播报设计:
  前置检查:
    - 播放前弹窗确认："周围环境安全吗？将播放敏感信息"
    - 提供"仅播放基本信息"选项（姓名+公司+上次见面时间）
  
  播报控制:
    - 默认音量50%（避免外放过大）
    - 支持随时暂停/快进
    - 敏感字段（金额、资源名称）播报时降低音量或跳过
  
  分级播报内容:
    - L1基础: 姓名+公司+职位
    - L2关系: 关系阶段+沟通偏好
    - L3敏感: 具体合作内容+建议话题（需确认）
  
  隐私模式:
    - 设置 → 启用"隐私播报模式"
    - 敏感信息替换为代号（"上次聊了项目A的预算"）
```

**播报脚本示例**:
```
✅ 安全播报:
"即将拜访张总，XX科技供应链总监。您们上个月单独见过面。
他偏好电话沟通。敏感信息已隐藏，请打开屏幕查看详情。"
```

**优先级**: P0 - 语音泄露风险高于屏幕显示，必须增加控制

---

### P1 - 重要问题

**5. PostgreSQL数据库缺乏行级安全策略（RLS）**

**位置**: 技术设计 §3.1 核心表定义

**问题**:
- 所有表都包含`user_id`字段，但未启用PostgreSQL的行级安全（Row Level Security）
- 如果应用层权限校验被绕过（SQL注入、权限漏洞），攻击者可跨用户查询
- 多租户场景下，数据隔离完全依赖应用层逻辑

**改进方案**:
```sql
-- 启用行级安全
ALTER TABLE entities ENABLE ROW LEVEL SECURITY;
ALTER TABLE events ENABLE ROW LEVEL SECURITY;
ALTER TABLE associations ENABLE ROW LEVEL SECURITY;
ALTER TABLE todos ENABLE ROW LEVEL SECURITY;

-- 创建策略（仅能访问自己的数据）
CREATE POLICY user_isolation_policy ON entities
FOR ALL
TO app_user
USING (user_id = current_setting('app.current_user_id')::uuid);

CREATE POLICY user_isolation_policy ON events
FOR ALL
TO app_user
USING (user_id = current_setting('app.current_user_id')::uuid);

-- 应用层设置user_id
-- 在每次数据库连接时执行
SET app.current_user_id = '${authenticated_user_id}';
```

**优先级**: P1 - 纵深防御的重要一层，防止应用层绕过

---

**6. API认证机制设计不足**

**位置**: 技术设计 §2.1 "FastAPI + 认证"，但未详细说明认证方案

**问题**:
- 文档仅提到"认证"但未说明具体方案（JWT? OAuth2? API Key?）
- Token刷新机制未定义
- Token撤销机制未说明（用户登出后如何失效？）
- 缺少速率限制的具体参数

**改进方案**:
```yaml
认证方案:
  Token类型: JWT (RS256签名，非对称加密)
  
  Token内容:
    access_token:
      - 有效期: 15分钟
      - payload: { user_id, exp, iat, jti }
    refresh_token:
      - 有效期: 7天
      - 存储在Redis，支持主动撤销
  
  刷新机制:
    - POST /api/v1/auth/refresh
    - 使用refresh_token换取新的access_token
    - 每次刷新生成新的refresh_token（旧的立即失效）
  
  撤销机制:
    - 用户登出时将refresh_token加入黑名单（Redis）
    - access_token依赖短有效期自然失效
  
  速率限制:
    - 全局: 1000请求/小时/IP
    - 认证接口: 10请求/分钟/IP（防暴力破解）
    - 事件上报: 100请求/小时/用户（防滥用）
```

**FastAPI实现**:
```python
from fastapi import Depends, HTTPException, Security
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

security = HTTPBearer()

async def verify_token(credentials: HTTPAuthorizationCredentials = Security(security)):
    token = credentials.credentials
    try:
        payload = jwt.decode(token, PUBLIC_KEY, algorithms=["RS256"])
        # 检查是否在黑名单
        if await redis.get(f"blacklist:{payload['jti']}"):
            raise HTTPException(status_code=401, detail="Token revoked")
        return payload['user_id']
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
```

**优先级**: P1 - 认证是整个系统的安全基础

---

**7. GDPR/个人信息保护法合规性不足**

**位置**: PRD §1.4 "隐私承诺" 仅提及但未详细设计

**问题**:
- 缺少明确的数据删除机制（Right to be Forgotten）
- 数据导出格式（F-20）未包含完整的个人数据范围
- 未说明数据保留期限
- 缺少跨境数据传输的合规声明

**改进方案**:
```yaml
合规功能清单:
  F-50 用户数据删除（Right to Erasure）:
    - 用户可申请删除账户
    - 删除范围：
      a. 账户信息
      b. 所有events/entities/associations/todos
      c. LLM调用日志（含个人数据部分）
      d. 备份数据（30天内完成删除）
    - 保留部分：
      a. 财务记录（法律要求保留7年）
      b. 安全日志（哈希后的user_id，保留90天）
    - 删除确认：
      a. 需二次验证（短信/邮箱验证码）
      b. 7天冷静期（可撤销）
      c. 删除完成后发送确认邮件
  
  F-51 数据可携带性（Data Portability）:
    - 导出包含全部个人数据：
      a. 账户信息
      b. 所有events（含raw_text明文）
      c. 所有entities及画像
      d. 所有associations
      e. 所有todos
      f. 操作日志（最近90天）
    - 导出格式：JSON（机器可读） + HTML（人类可读）
  
  F-52 数据处理透明度:
    - 实体详情页显示"数据来源"标签
      （来自哪个event，AI推断置信度）
    - LLM调用记录可审计（脱敏后保留30天）
  
  F-53 数据保留策略:
    - 活跃用户：无限期保留
    - 非活跃用户（180天未登录）：
      a. 发送数据保留提醒邮件
      b. 365天未登录：数据归档（只读）
      c. 730天未登录：自动删除
  
  F-54 跨境传输声明:
    - 如使用海外LLM API（OpenAI/Claude）：
      a. 用户首次使用时明确告知
      b. 提供"仅国内处理"选项（使用国内LLM）
      c. 隐私政策中披露数据流向国家/地区
```

**隐私政策示例条款**:
```
我们如何处理您的数据：
1. 数据存储：您的数据存储在[AWS香港/阿里云上海]
2. AI处理：会议纪要使用[Moka AI Claude/国内LLM]分析，数据[会/不会]离开中国大陆
3. 保留期限：活跃账户无限期，非活跃账户2年后自动删除
4. 您的权利：随时导出或删除数据（设置→隐私→数据管理）
```

**优先级**: P1 - 合规性问题可能导致法律风险

---

**8. 敏感信息上传脱敏功能设计不完善（US-25）**

**位置**: PRD §2.8 US-25

**问题**:
- 仅依赖前端识别敏感信息，容易被绕过
- 未说明如何处理用户拒绝脱敏但仍上传的情况
- 打码后的内容"不参与AI分析"可能影响关联发现准确性

**改进方案**:
```yaml
多层脱敏策略:
  前端识别（第一层）:
    - 规则引擎: 正则匹配（金额/手机/身份证/银行卡）
    - 高亮提示用户
  
  后端验证（第二层）:
    - 即使用户选择"不脱敏"，后端再次检测
    - 检测到高风险信息（如身份证号）强制脱敏
    - 记录用户选择日志（审计用）
  
  LLM处理（第三层）:
    - System Prompt包含"禁止输出原始敏感信息"
    - 返回结果再次过滤
  
  脱敏算法:
    - 金额: "约XX万元" 或 "[金额已隐藏]"
    - 人名: 保留姓氏 "张**"
    - 手机: "138****5678"
    - 银行卡: "尾号5678"
  
  用户控制:
    - 设置 → 安全 → 敏感信息脱敏级别
      [ ] 关闭（自负风险）
      [x] 标准（默认，遮蔽关键位）
      [ ] 严格（完全隐藏）
```

**优先级**: P1 - 防止商业机密泄露到LLM服务商

---

## 改进建议（P2/P3）

### P2 - 重要改进

**9. 缺少审计日志**

**建议**: 增加操作审计表，记录敏感操作（删除实体、修改关联、导出数据）
```sql
CREATE TABLE audit_logs (
    id UUID PRIMARY KEY,
    user_id UUID NOT NULL,
    action VARCHAR(50) NOT NULL,  -- delete_entity, export_data
    target_type VARCHAR(20),      -- entity, association
    target_id UUID,
    ip_address INET,
    user_agent TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX idx_audit_user_time ON audit_logs(user_id, created_at DESC);
```

---

**10. 密码/凭证管理未提及**

**建议**: 补充密码策略
- 最短8位，包含大小写+数字+特殊字符
- 使用bcrypt/argon2加密存储（cost≥12）
- 支持双因素认证（2FA via TOTP）
- 密码重置链接1小时有效，单次使用

---

**11. 会话管理不完善**

**建议**:
- 同一用户最多5个并发会话（防账号共享）
- 支持查看活跃会话列表（设备/IP/最后活跃时间）
- 支持远程登出功能

---

### P3 - 可选优化

**12. 敏感字段数据库查询监控**

**建议**: 使用PostgreSQL的`pg_stat_statements`监控查询，告警异常查询（如全表扫描`raw_text`）

---

**13. 前端CSP（Content Security Policy）**

**建议**: H5页面设置严格的CSP头，防止XSS
```
Content-Security-Policy: 
  default-src 'self'; 
  script-src 'self' 'unsafe-inline'; 
  connect-src 'self' https://api.promiselink.com;
  img-src 'self' data:;
```

---

**14. 依赖库安全扫描**

**建议**: CI/CD集成依赖扫描工具（Snyk/Dependabot），自动检测已知漏洞

---

## 整体评估

### 评分: 5.5/10

**评分说明**:
- ✅ **架构设计合理** (+2): 事件驱动、服务拆分、配置化设计都很好
- ✅ **功能完整性高** (+1.5): PRD覆盖完整用户旅程，技术设计可落地
- ❌ **安全设计严重不足** (-4): Token传递、录音加密、TTS泄露、推送隐私问题都是P0级别
- ⚠️ **合规性欠考虑** (-2): GDPR/个保法的删除权、数据导出、跨境传输均未设计
- ⚠️ **数据库安全弱** (-1): 缺少行级安全、审计日志、列加密
- ✅ **降级设计优秀** (+1): CarryMem解耦、LLM降级策略设计良好

### 是否同意通过: ❌ **不同意，需修订后重审**

**必须解决才能通过**:
1. ✅ 修改小程序token传递方案（改用临时票据）
2. ✅ 补充录音数据加密设计（传输+存储）
3. ✅ 优化微信推送内容（分级推送，敏感信息需打开App查看）
4. ✅ TTS播报增加隐私保护（播放前确认+分级播报）
5. ✅ 补充GDPR合规功能（数据删除、导出、保留策略）
6. ✅ 启用PostgreSQL行级安全（RLS）
7. ✅ 完善API认证方案（JWT细节+速率限制）

**建议优先处理**:
8. ⚪ 增加审计日志（删除、导出等敏感操作）
9. ⚪ 完善US-25脱敏功能（后端二次校验）

---

## 最终建议

这是一个很有商业潜力的产品，技术架构设计合理，但**安全和隐私保护设计严重不足**。考虑到产品定位于商务人士（高净值用户，敏感数据多），安全问题可能导致：
1. **信任危机**：一次泄露事故会摧毁产品口碑
2. **法律风险**：违反《个人信息保护法》可能面临高额罚款
3. **商业损失**：企业客户（Phase 2目标）对安全性要求极高

**建议**：将上述P0/P1问题纳入MVP-Core，而非MVP-Plus。安全不是功能，是基础设施。在解决这些问题后，我很乐意重新审核并给出更高评分。

---

## 测试专家 (tester)

### 测试专家审核意见

#### 关键问题（P0/P1）

**P0-1: 旅程二环节B+缺少端到端测试的边界条件定义**
- **问题位置**: PRD §1.5.2 环节B+，技术设计缺少对应测试策略
- **具体问题**: 
  - 录音卡录音失败、网络中断、转写服务不可用等异常场景未定义测试用例
  - TTS播报被微信限流、用户快速切换人物导致播报队列冲突的并发测试缺失
  - 小程序-H5通信中postMessage丢失、超时、重复发送的可靠性测试未覆盖
- **改进建议**:
  ```yaml
  E2E测试场景-外出拜访完整链路:
    前置条件:
      - 录音卡已配对并在线
      - 小程序已授权位置、麦克风权限
      - 今日日程中已有预约
    
    正常路径:
      Step1: 会前准备
        - 微信服务号推送到达(验证时间窗口: 提前15-60分钟)
        - 打开小程序 → 今日日程加载<3秒
        - 点击人物 → TTS播报启动<3秒
        - 播报内容完整性验证(与预期脚本diff<5%)
      
      Step2: 会中录音
        - 录音卡后台录音(验证录音文件生成)
        - 转写延迟<会议时长*1.5
      
      Step3: 会后处理
        - PromiseLink API接收会议文本<10秒
        - 生成行动项<30秒
        - 微信服务号推送到达<60秒
      
      Step4: 语音补录
        - 小程序语音录入→转文本<5秒
        - PromiseLink处理→推送结果<60秒
    
    异常路径:
      - 录音卡离线: 小程序应提示手动录入
      - 转写服务超时(>5分钟): 标记为待处理队列
      - TTS播放中用户退出: 记录播放进度，下次恢复
      - postMessage超时(>3秒): H5展示降级UI(文字显示)
      - 网络中断: 本地缓存待同步，恢复后自动重试
    
    性能基准:
      - TTS冷启动<3秒 (P95<5秒)
      - 语音录入→AI→推送全链路<60秒 (P95<90秒)
      - 小程序加载今日日程<3秒 (包含画像数据)
  ```

**P0-2: TTS播报内容验证缺少自动化手段**
- **问题位置**: US-28, F-37
- **具体问题**: 
  - "播报完整人物简介<30秒"仅定义了时长，未定义内容完整性和准确性的验证方法
  - 语音合成质量(发音、停顿、语气)无法通过自动化测试验证
  - 多语言场景(英文名字、公司名)的播报准确性无验证方案
- **改进建议**:
  ```python
  # 分层验证策略
  
  # L1: 文本生成验证(自动化100%)
  def test_tts_script_generation():
      person = create_test_person(
          name="张伟", company="XX科技", title="供应链总监",
          relationship_stage="met_alone",
          last_interaction="讨论了新项目预算",
          suggested_topics=["华南区代工厂对接"]
      )
      script = generate_tts_script(person)
      
      assert "张伟" in script
      assert "XX科技" in script
      assert "供应链总监" in script
      assert "关系阶段" in script
      assert "上次交流" in script or "最近话题" in script
      assert "建议" in script or "可以" in script
      assert len(script) >= 50  # 最少50字
      assert len(script) <= 300  # 最多300字(避免超时)
  
  # L2: 音频时长验证(自动化100%)
  def test_tts_duration():
      script = "张总，XX科技供应链总监。关系阶段：单独见过面。上次聊了新项目预算。建议：可提华南区代工厂对接。"
      audio_file = tts_engine.synthesize(script)
      duration = get_audio_duration(audio_file)
      
      # 中文约5字/秒，英文约150词/分钟
      expected_duration = len(script) / 5
      assert duration < 30  # 硬性要求
      assert abs(duration - expected_duration) < 5  # 合理范围
  
  # L3: 内容准确性抽检(人工50样本)
  def test_tts_accuracy_sampling():
      """
      每周随机抽取50个真实用户的TTS播报:
      1. 人工听音频，记录错误类型:
         - 人名读错(如"张伟"读成"张维")
         - 公司名读错(如"迪卡侬"读成"迪卡农")
         - 停顿不当(如"单独/见过面"误读为"单独见/过面")
         - 关键信息遗漏
      2. 错误率阈值: <2% (即50个样本中<1个错误)
      3. 高频错误自动加入纠正词典
      """
      pass
  
  # L4: 用户反馈闭环(被动收集)
  # 播报结束后展示"内容是否准确？"反馈按钮
  # 不准确时让用户标注具体错误点
  ```

**P1-1: H5-小程序postMessage异步通信的超时和重试机制未定义**
- **问题位置**: 技术设计 §2.3 Phase 1 H5与小程序通信协议
- **具体问题**:
  - postMessage是异步的，没有ACK确认机制
  - 小程序录音完成后回传文本，H5如何判断是否收到？
  - 如果postMessage因微信环境限制失败，用户看到的是什么？
- **改进建议**:
  ```javascript
  // 集成测试用例
  describe('H5-Miniprogram Communication', () => {
    test('正常流程：H5请求录音 -> 小程序返回文本', async () => {
      // 1. H5发送录音请求
      const requestId = generateUUID()
      wx.miniProgram.postMessage({
        type: 'start_recording',
        requestId,
        timeout: 60000  // 60秒超时
      })
      
      // 2. 设置超时监听
      const result = await waitForMessage(
        { type: 'recording_result', requestId },
        { timeout: 65000 }  // 比请求超时多5秒
      )
      
      expect(result.text).toBeDefined()
      expect(result.text.length).toBeGreaterThan(0)
    })
    
    test('异常流程：录音超时', async () => {
      const requestId = generateUUID()
      wx.miniProgram.postMessage({ type: 'start_recording', requestId })
      
      await expect(
        waitForMessage({ type: 'recording_result', requestId }, { timeout: 5000 })
      ).rejects.toThrow('录音请求超时')
      
      // 验证H5展示降级UI
      expect(screen.getByText('录音超时，请使用文字输入')).toBeVisible()
    })
    
    test('异常流程：postMessage失败', () => {
      // Mock微信环境不可用
      wx.miniProgram.postMessage = jest.fn(() => { throw new Error('not in miniprogram') })
      
      // 验证H5自动降级为纯文字输入模式
      const { getByPlaceholderText } = render(<RecordingInput />)
      expect(getByPlaceholderText('输入会议要点')).toBeVisible()
      expect(screen.queryByText('点击录音')).toBeNull()
    })
  })
  
  // 可靠性保障实现
  class MessageBridge {
    constructor() {
      this.pendingRequests = new Map()  // requestId -> {resolve, reject, timer}
    }
    
    sendToMiniprogram(message, timeout = 60000) {
      const requestId = generateUUID()
      message.requestId = requestId
      
      return new Promise((resolve, reject) => {
        const timer = setTimeout(() => {
          this.pendingRequests.delete(requestId)
          reject(new Error(`Message timeout: ${message.type}`))
        }, timeout)
        
        this.pendingRequests.set(requestId, { resolve, reject, timer })
        
        try {
          wx.miniProgram.postMessage(message)
        } catch (error) {
          clearTimeout(timer)
          this.pendingRequests.delete(requestId)
          reject(error)
        }
      })
    }
    
    onMessageFromMiniprogram(message) {
      const pending = this.pendingRequests.get(message.requestId)
      if (pending) {
        clearTimeout(pending.timer)
        this.pendingRequests.delete(message.requestId)
        pending.resolve(message)
      }
    }
  }
  ```

**P1-2: 通知推送的防打扰策略边界测试不足**
- **问题位置**: F-19, F-42
- **具体问题**:
  - "22:00-8:00静默时段"与"会前1小时紧急提醒"冲突时的优先级未定义
  - 用户在开会时(日历显示忙碌)收到其他Todo提醒是否合理？
  - 同一Todo在不同时间窗口多次提醒的去重逻辑未明确
- **改进建议**:
  ```python
  # 防打扰策略测试矩阵
  
  @pytest.mark.parametrize("scenario,expected", [
      # (当前时间, 用户日历状态, Todo类型, 优先级, 是否推送, 推送时间)
      ("23:00", "free", "action", "high", False, "次日8:00"),  # 静默时段
      ("7:30", "busy", "action", "urgent", True, "立即"),  # 会前紧急提醒打破静默
      ("14:00", "in_meeting", "context", "low", False, "会议结束后"),  # 会中不打扰
      ("10:00", "free", "action", "high", True, "立即"),  # 正常推送
      ("21:30", "free", "action", "high", False, "次日8:00"),  # 接近静默时段延迟
      ("8:05", "free", "action", "high", False, None),  # 同一Todo 24h内已推送过
  ])
  def test_notification_delivery_strategy(scenario, expected):
      current_time, calendar_status, todo_type, priority, should_send, send_time = scenario, *expected
      
      user = create_test_user(notification_settings={
          "silent_hours": {"start": "22:00", "end": "8:00"},
          "respect_calendar": True
      })
      
      todo = create_test_todo(type=todo_type, priority=priority)
      
      result = notification_engine.should_send(
          user=user,
          todo=todo,
          current_time=current_time,
          calendar_status=calendar_status
      )
      
      assert result.should_send == should_send
      if send_time:
          assert result.scheduled_time == send_time
  
  # 重复推送去重测试
  def test_notification_deduplication():
      user = create_test_user()
      todo = create_test_todo(id="todo-123")
      
      # 第一次推送成功
      assert notification_engine.send(user, todo) == True
      
      # 24小时内重复推送被拦截
      with freeze_time("2026-06-02 10:00"):
          assert notification_engine.send(user, todo) == False
      
      # 24小时后可以再次推送
      with freeze_time("2026-06-03 10:01"):
          assert notification_engine.send(user, todo) == True
  ```

**P1-3: 录音卡→ASR→PromiseLink端到端链路的容错测试缺失**
- **问题位置**: PRD §1.5.2 环节B，技术设计未覆盖
- **具体问题**:
  - 录音卡与手机蓝牙断连后重连，录音数据完整性如何保障？
  - ASR转写失败(如方言、噪音环境)时，用户如何感知和补救？
  - PromiseLink API接收到空文本或乱码时的降级处理未定义
- **改进建议**:
  ```python
  # 端到端容错测试套件
  
  class TestRecordingCardE2E:
      def test_happy_path(self):
          """完整正常流程"""
          # 1. 录音卡录音
          recording = recording_card.start_recording()
          time.sleep(180)  # 模拟3分钟会议
          audio_file = recording_card.stop_recording()
          
          # 2. ASR转写
          transcript = asr_service.transcribe(audio_file)
          assert len(transcript) > 100  # 至少有实质内容
          
          # 3. PromiseLink处理
          response = promiselink_api.post_event({
              "event_type": "call",
              "raw_text": transcript,
              "source": "recording_r1"
          })
          assert response.status_code == 200
          
          # 4. 验证结果
          time.sleep(30)  # 等待后台处理
          todos = promiselink_api.get_todos(status="pending")
          assert len(todos) > 0
      
      def test_bluetooth_disconnect_recovery(self):
          """蓝牙断连恢复测试"""
          recording = recording_card.start_recording()
          time.sleep(60)
          
          # 模拟蓝牙断连
          recording_card.disconnect()
          time.sleep(30)
          
          # 重连并继续录音
          recording_card.reconnect()
          time.sleep(60)
          audio_file = recording_card.stop_recording()
          
          # 验证音频文件完整性
          assert audio_file.duration >= 120  # 至少2分钟
          assert not has_gaps(audio_file)  # 无明显断点
      
      def test_asr_poor_quality_audio(self):
          """ASR低质量音频测试"""
          # 使用噪音环境录音样本
          audio_file = load_test_audio("noisy_meeting.wav")
          transcript = asr_service.transcribe(audio_file)
          
          # ASR应返回置信度
          assert transcript.confidence < 0.5
          
          # PromiseLink应标记为低质量
          response = promiselink_api.post_event({
              "event_type": "call",
              "raw_text": transcript.text,
              "metadata": {"asr_confidence": transcript.confidence}
          })
          
          # 验证生成的Todo带有质量警告
          todos = promiselink_api.get_todos(source_event=response.json()["event_id"])
          assert any("转写质量较低" in t["description"] for t in todos)
      
      def test_promiselink_empty_text_handling(self):
          """PromiseLink空文本处理"""
          response = promiselink_api.post_event({
              "event_type": "call",
              "raw_text": "",
              "source": "recording_r1"
          })
          
          # 应返回422而非500
          assert response.status_code == 422
          assert "raw_text不能为空" in response.json()["detail"]
      
      def test_promiselink_malformed_text_handling(self):
          """PromiseLink乱码文本处理"""
          response = promiselink_api.post_event({
              "event_type": "call",
              "raw_text": "��无效字符��",
              "source": "recording_r1"
          })
          
          # 应返回200但标记为失败
          assert response.status_code == 200
          assert response.json()["status"] == "failed"
          assert "文本解析失败" in response.json()["error"]
  ```

#### 改进建议（P2/P3）

**P2-1: CarryMem NullMemoryProvider降级场景缺少功能对比测试**
- **问题位置**: 技术设计 §5.2
- **改进建议**: 补充A/B对比测试，量化CarryMem启用前后的差异
  ```python
  @pytest.mark.parametrize("memory_provider", [
      NullMemoryProvider(),
      CarryMemMemoryProvider(mock_carrymem_instance)
  ])
  def test_feature_parity_with_without_carrymem(memory_provider):
      """验证核心功能在降级模式下依然可用"""
      app = PromiseLinkApp(memory_provider=memory_provider)
      
      event = create_test_event(event_type="meeting", raw_text="...")
      entities, todos = app.process_event(event)
      
      # 核心功能不依赖CarryMem
      assert len(entities) > 0
      assert len(todos) > 0
      
      # CarryMem增强功能的差异
      if isinstance(memory_provider, NullMemoryProvider):
          # 降级模式：无个性化推荐
          assert not any("基于您的偏好" in t.description for t in todos)
      else:
          # 正常模式：有个性化推荐
          assert any("基于您的偏好" in t.description for t in todos)
  ```

**P2-2: 性能基准缺少负载测试**
- **问题位置**: PRD中多处定义了延迟要求(如<3秒、<60秒)，但未定义并发负载下的表现
- **改进建议**:
  ```python
  # 性能基准测试
  
  def test_tts_concurrency():
      """TTS并发测试：10个用户同时请求播报"""
      users = [create_test_user() for _ in range(10)]
      
      start = time.time()
      results = asyncio.run(asyncio.gather(*[
          tts_service.synthesize(generate_test_script(u)) for u in users
      ]))
      duration = time.time() - start
      
      # 所有请求在10秒内完成
      assert duration < 10
      # P95延迟<5秒
      assert percentile(results, 95) < 5
  
  def test_event_ingestion_throughput():
      """事件接入吞吐量测试"""
      events = [create_test_event() for _ in range(100)]
      
      start = time.time()
      results = [api.post_event(e) for e in events]
      duration = time.time() - start
      
      # 100个事件在30秒内全部接收
      assert duration < 30
      assert all(r.status_code == 200 for r in results)
  ```

**P3-1: E2E测试场景可补充边缘案例**
- 建议补充场景:
  - 用户开车途中网络从4G切换到WiFi，H5页面是否无感切换
  - 用户在播报到一半时接到来电，恢复后是否从断点继续
  - 用户同时打开多个小程序页面，语音录入的结果是否正确路由

#### 整体评估

**评分: 7.5/10**

**评估理由**:

**优势**:
1. PRD和技术设计整体结构完整，用户旅程定义清晰
2. 功能拆分合理，验收标准大部分可量化
3. 系统架构设计考虑了与CarryMem的解耦和降级，技术路线务实

**不足**:
1. **端到端测试场景不够具体**(P0)：旅程二环节B+是核心场景，但测试设计不够细化，缺少异常路径和性能基准的可操作性定义
2. **语音相关测试策略薄弱**(P0)：TTS播报和语音录入是差异化功能，但验证手段不足，尤其是内容准确性的自动化测试缺失
3. **跨系统通信可靠性测试不足**(P1)：H5-小程序postMessage、录音卡-手机蓝牙、ASR-PromiseLink等多个集成点的容错测试未覆盖
4. **性能测试基准缺少并发和负载定义**(P2)：<3秒、<60秒等指标未说明是单用户还是并发场景

**通过条件**:
必须解决P0级别问题(端到端测试设计、TTS验证策略、H5通信可靠性)后才能进入开发。P1级别问题(防打扰边界测试、录音卡容错)建议在MVP-Core阶段完成。

**是否同意通过**: ❌ **暂不通过，需补充P0问题的测试设计细节后重新审核**

---

## 开发者 (solo-coder)

### 开发者审核意见

## 关键问题（P0/P1）

### P0-1: Mini服务API设计不符合RESTful规范

**位置**: 技术设计 §2.2, §7.1

**问题**:
1. `/mini/today` 混合了多种资源（日程+待办），应拆分为：
   - `GET /mini/todos?status=pending&due_date=today`
   - `GET /mini/calendar/events?date=today`

2. `/mini/person/{id}/tts` 是动作而非资源，应改为：
   - `POST /mini/person/{id}/audio-profile`（生成TTS音频）
   - 或使用查询参数 `GET /mini/person/{id}?format=audio`

3. `/mini/voice-input` 应该是 `POST /events`，通过 `event_type=voice_note` 区分

**改进建议**:
```python
# 推荐设计
GET  /api/v1/mini/calendar?date=today&include=todos
POST /api/v1/mini/person/{id}/speech  # 请求TTS
POST /api/v1/events  # 统一入口，body中指定source=voice
```

**优先级**: P0 - RESTful违规会导致API难以维护和扩展

---

### P0-2: TTS在H5 WebView中实现路径不明确

**位置**: PRD §1.5.2 环节B+, 技术设计 §2.3

**问题**:
1. 微信同声传译插件**仅支持小程序原生**，无法在H5 WebView中调用
2. 技术设计中未说明H5端TTS的降级方案
3. Phase 1的H5页面如何实现TTS播报？

**改进建议**:
```javascript
// Phase 1 方案：H5通过postMessage请求小程序原生TTS
// H5端
wx.miniProgram.postMessage({ 
  type: 'tts_request', 
  text: person.profile_summary,
  person_id: person.id
})

// 小程序端监听并调用wx.plugin.getPlugin('WechatSI')
onMessage(data => {
  if (data.type === 'tts_request') {
    const plugin = wx.plugin.getPlugin('WechatSI')
    plugin.textToSpeech({ content: data.text })
  }
})
```

**优先级**: P0 - 许总核心场景（开车听简介）依赖此功能

---

### P0-3: 语音录入链路复杂度高，错误处理缺失

**位置**: 技术设计 §2.3, §7.1

**问题**:
1. H5 → postMessage → 小程序 → wx.startRecord → ASR → 回调H5 这条链路涉及4次跨域通信，任何一步失败都会中断
2. 缺少超时处理（录音无响应、ASR失败）
3. 缺少降级方案（ASR不可用时的备选）

**改进建议**:
```javascript
// 增加超时和重试机制
class VoiceInputHandler {
  async startRecording(maxRetry = 2) {
    for (let i = 0; i < maxRetry; i++) {
      try {
        const result = await this._recordWithTimeout(30000) // 30s超时
        return result
      } catch (e) {
        if (i === maxRetry - 1) {
          // 最终降级：打开文字输入框
          return this._fallbackToTextInput()
        }
        await sleep(1000 * (i + 1))
      }
    }
  }
  
  _recordWithTimeout(ms) {
    return Promise.race([
      this._wxStartRecord(),
      new Promise((_, reject) => 
        setTimeout(() => reject('timeout'), ms)
      )
    ])
  }
}
```

**优先级**: P0 - 移动端核心交互，必须保证可用性

---

### P1-1: H5端Vue3+Vant UI选型与小程序WebView兼容性风险

**位置**: 技术设计 §2.3

**问题**:
1. 微信WebView基于X5内核（Android）和WKWebView（iOS），部分CSS特性支持度低
2. Vant UI 4.x 依赖现代CSS特性（container queries, :has()），在旧版微信中可能失效
3. Vue3 Composition API在WebView调试困难

**改进建议**:
1. **降级Vant至3.x**（兼容性更好）或**替换为vant-weapp小程序原生组件**
2. **构建时增加CSS兼容性检查**：
```javascript
// vite.config.js
export default {
  css: {
    postcss: {
      plugins: [
        autoprefixer({ 
          overrideBrowserslist: ['iOS >= 10', 'Chrome >= 53'] // 对标微信WebView
        })
      ]
    }
  }
}
```
3. **增加WebView环境检测**：
```javascript
const isWechatWebview = /micromessenger/i.test(navigator.userAgent)
if (isWechatWebview && !window.wx) {
  // 引入jweixin-1.6.0.js
}
```

**优先级**: P1 - 影响Phase 1主要交互，需尽早验证

---

### P1-2: NotificationService的ChannelRouter缺少用户偏好持久化

**位置**: 技术设计 §8

**问题**:
1. 设计中提到"读取用户偏好"但未说明偏好来源（CarryMem? User表？）
2. 用户修改偏好后如何持久化？
3. 如果CarryMem不可用，偏好从哪里读取？

**改进建议**:
```sql
-- 增加用户偏好表
CREATE TABLE user_notification_preferences (
    user_id UUID PRIMARY KEY,
    preferred_channel VARCHAR(20) DEFAULT 'wechat', -- wechat|apns|fcm|email
    quiet_hours JSONB DEFAULT '{"start":"22:00","end":"08:00"}',
    todo_reminder_enabled BOOLEAN DEFAULT TRUE,
    daily_digest_time TIME DEFAULT '08:00',
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- ChannelRouter逻辑
class ChannelRouter:
    def select_channel(self, user_id: UUID) -> NotificationChannel:
        prefs = db.query(UserNotificationPreferences).get(user_id)
        if not prefs:
            prefs = self._get_default_prefs()
        
        # CarryMem可用时，叠加记忆层规则
        if self.memory.is_available():
            rules = self.memory.match_rules(user_id, "notification")
            prefs = self._merge_rules(prefs, rules)
        
        return self._resolve_channel(prefs)
```

**优先级**: P1 - 影响通知送达率，Phase 1必须可用

---

### P1-3: 实体归一5步算法LLM调用成本高，降级策略不足

**位置**: 技术设计 §4.3

**问题**:
1. Step 4 LLM语义相似度计算，每次归一判断消耗200-500 tokens
2. 高频场景（批量导入500条联系人）会产生巨额成本
3. LLM失败时算法直接终止，缺少降级路径

**改进建议**:
```python
class EntityResolutionEngine:
    def resolve(self, new_entity: Entity) -> Optional[UUID]:
        # Step 1-3: 规则引擎（无成本）
        exact_match = self._exact_match(new_entity)
        if exact_match: return exact_match
        
        alias_match = self._alias_match(new_entity)
        if alias_match: return alias_match
        
        fuzzy_candidates = self._fuzzy_match(new_entity, threshold=0.8)
        if len(fuzzy_candidates) == 1: 
            return fuzzy_candidates[0]
        
        # Step 4: LLM仅在有多个候选时调用
        if len(fuzzy_candidates) > 1:
            try:
                best = self._llm_semantic_match(new_entity, fuzzy_candidates)
                if best.confidence >= 0.85:
                    return best.entity_id
            except LLMError:
                # 降级：返回编辑距离最小的候选
                return self._fallback_edit_distance(new_entity, fuzzy_candidates)
        
        # Step 5: 人工确认队列
        if fuzzy_candidates:
            self._enqueue_manual_review(new_entity, fuzzy_candidates)
        
        return None  # 创建新实体
```

**优先级**: P1 - 批量导入场景必须可用，成本可控

---

## 改进建议（P2/P3）

### P2-1: YAML配置热更新机制缺失

**位置**: 技术设计 §6

**问题**: 设计中未说明YAML配置变更后如何生效（重启？定时拉取？）

**建议**:
```python
class ConfigLoader:
    def __init__(self):
        self._configs = {}
        self._last_modified = {}
        self._watch_thread = threading.Thread(target=self._watch_files)
        self._watch_thread.start()
    
    def _watch_files(self):
        while True:
            for file in self._config_files:
                mtime = os.path.getmtime(file)
                if mtime > self._last_modified.get(file, 0):
                    self._reload_config(file)
                    self._last_modified[file] = mtime
            time.sleep(60)  # 每分钟检查一次
```

**优先级**: P2 - 运维便利性

---

### P2-2: Phase 1五个服务的模块边界需明确定义

**位置**: 技术设计 §2.2

**问题**: "通过模块边界隔离"过于模糊，缺少具体实现

**建议**:
```python
# 使用FastAPI的子应用挂载
from fastapi import FastAPI

app = FastAPI()

# 各服务独立的子应用
event_app = FastAPI()
query_app = FastAPI()
todo_app = FastAPI()
mini_app = FastAPI()

# 挂载到主应用
app.mount("/api/v1/events", event_app)
app.mount("/api/v1/query", query_app)
app.mount("/api/v1/todos", todo_app)
app.mount("/api/v1/mini", mini_app)

# 依赖注入保证模块解耦
@event_app.post("/")
async def create_event(
    event_service: EventService = Depends(get_event_service)
):
    pass
```

**优先级**: P2 - 代码组织清晰度

---

### P3-1: 缺少API限流和认证细节

**位置**: 技术设计 §2.1

**问题**: API Gateway提到"限流"但未说明策略

**建议**:
```python
from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address)

@app.post("/api/v1/events")
@limiter.limit("100/minute")  # 每用户每分钟100次
async def create_event():
    pass
```

**优先级**: P3 - 生产环境必要，但不影响PoC

---

## 整体评估

### 评分：7.5/10

**优点**:
1. ✅ 事件驱动架构清晰，实体归一算法完整
2. ✅ 与CarryMem解耦设计合理，Protocol接口优雅
3. ✅ 配置化设计灵活，支持行业定制
4. ✅ 数据模型设计合理，JSONB扩展画像避免频繁schema变更

**主要问题**:
1. ❌ Mini服务API设计不RESTful（P0）
2. ❌ TTS实现路径不明确，H5方案缺失（P0）
3. ❌ 语音录入链路错误处理不足（P0）
4. ⚠️ H5技术栈兼容性风险（P1）
5. ⚠️ 通知偏好持久化缺失（P1）
6. ⚠️ LLM成本控制不足（P1）

### 审核结论：**有条件通过**

需在开发前完成以下工作：
1. **必须重新设计Mini服务API**（P0-1）
2. **必须明确TTS在H5中的实现方案**（P0-2，建议Phase 1全部走小程序原生）
3. **必须补充语音录入的错误处理和降级**（P0-3）
4. **建议验证Vant UI在微信WebView中的兼容性**（P1-1，建议先做技术预研）
5. **建议增加用户偏好持久化表**（P1-2）

完成P0问题修复后可进入开发，P1问题可在第一周冲刺中解决。

---

## 运维工程师 (devops)

# 运维工程师审核意见

## 关键问题（P0/P1）

### P0 - 必须解决

**P0-1: Phase 1 资源预估严重不足**
- **问题位置**: §8.1 部署架构，"Phase 1 Docker Compose单机部署"
- **问题描述**: 
  - 文档未提供5服务同进程的资源需求量化数据
  - 仅说"2核4G可跑通PoC"，但未考虑：
    - LLM调用的并发峰值（Moka AI Claude Sonnet token处理）
    - PostgreSQL并发连接数（默认100连接，4GB内存下可能不够）
    - Redis内存占用（缓存+会话+限流数据）
    - 语音转文本的临时文件存储（raw_text≤500KB限制下，峰值磁盘IO）
- **改进建议**:
  ```yaml
  # 建议在技术设计中增加资源预估表
  phase1_minimum_requirements:
    cpu: 4核（2核LLM推理 + 1核PG + 1核应用层）
    memory: 8GB（2GB FastAPI + 3GB PG shared_buffers + 2GB Redis + 1GB OS）
    disk: 100GB SSD（20GB数据 + 50GB日志 + 30GB备份缓冲）
    network: 10Mbps上行（TTS音频流 + 微信推送）
    
  phase1_recommended_for_100users:
    cpu: 8核
    memory: 16GB
    disk: 500GB SSD
    
  bottleneck_analysis:
    - LLM API调用延迟（Claude Sonnet平均3-5s/次）
    - PostgreSQL写入峰值（会议纪要processing时每秒10+ INSERT）
    - Redis连接池耗尽（默认10连接，需调整为50+）
  ```

**P0-2: 缺少PostgreSQL高可用和故障恢复方案**
- **问题位置**: §8.3 数据备份
- **问题描述**:
  - 仅提及"pg_dump每日全量 + WAL归档"，但未说明：
    - WAL归档的存储位置（本地？对象存储？）
    - RTO/RPO目标（文档未定义，用户核心数据丢失风险）
    - 单点故障：PG主库宕机后，恢复时间>1小时不可接受
  - Phase 1单机部署，数据库崩溃=服务全毁
- **改进建议**:
  ```yaml
  # Phase 1 最小可用方案
  backup_strategy:
    full_backup:
      frequency: daily_at_02:00
      retention: 7_days
      storage: local_disk + rsync_to_remote_nfs
    wal_archive:
      enabled: true
      archive_command: "rsync %p backup_server:/pg_wal/%f"
      retention: 7_days
    rto: 30_minutes  # 从备份恢复的目标时间
    rpo: 15_minutes  # 最多丢失15分钟数据（WAL归档间隔）
    
  disaster_recovery_drill:
    frequency: monthly
    steps:
      - stop_pg
      - restore_from_backup
      - replay_wal
      - verify_data_integrity
      - document_actual_rto
  
  # Phase 2 高可用方案（建议提前规划）
  ha_options:
    - patroni + etcd（自动故障切换）
    - pg_auto_failover（简化版HA）
    - 云厂商RDS（托管HA，但成本高）
  ```

**P0-3: 外部依赖故障降级策略不完整**
- **问题位置**: §4.2 LLM调用策略，§6.2 TTS服务集成
- **问题描述**:
  - LLM降级仅提"超限降级为规则引擎"，但未定义：
    - Moka AI Claude Sonnet API故障时的降级路径（是否有备用LLM？）
    - 规则引擎的实体抽取准确率（文档说"不调用LLM，基于关键词匹配"，准确率多少？）
  - TTS服务依赖3个外部API（微信同声传译/讯飞/Azure），但未说明：
    - 优先级顺序（哪个是主用？哪个是备用？）
    - 故障切换逻辑（API超时阈值？重试次数？）
    - 全部失败时的用户体验（返回静默错误？还是提示"播报服务不可用"？）
- **改进建议**:
  ```python
  # LLM降级策略
  class LLMFallbackStrategy:
      primary: MokaAI_Claude_Sonnet
      fallback_chain:
        - OpenAI_GPT4o_mini（成本更低，速度更快）
        - Rule_Based_Extractor（准确率60%，但0成本）
      
      timeout_config:
        moka_api: 10s
        openai_api: 8s
        rule_engine: 1s
      
      circuit_breaker:
        failure_threshold: 3_consecutive_errors
        recovery_timeout: 60s
  
  # TTS降级策略
  class TTSFallbackStrategy:
      primary: WechatTTS（最佳音质，但限微信环境）
      fallback_1: XunfeiTTS（通用性好，1000次/天免费）
      fallback_2: AzureTTS（付费，无限制）
      
      failure_handling:
        - timeout: 5s
        - retry: 2次（间隔1s）
        - all_failed: 返回文本+提示"播报服务暂不可用"
  ```

**P0-4: 微信服务号限流和故障处理缺失**
- **问题位置**: §6.3 微信触达通道
- **问题描述**:
  - 微信服务号模板消息有官方限流（10万次/天，单用户100次/天）
  - 文档未说明超限后的处理逻辑：
    - 用户每日触发30+ Todo，模板消息触顶怎么办？
    - 微信API故障时（HTTP 500/超时），重试机制是什么？
  - 用户反馈"漏推送"时，无法定位是API故障还是限流导致
- **改进建议**:
  ```python
  # 微信推送限流控制
  class WechatNotifyRateLimiter:
      limits:
        per_user_daily: 50次（低于官方100次，留缓冲）
        global_daily: 80000次（低于官方10万，留20%缓冲）
      
      priority_queue:
        P0: 会前提醒（15分钟前）
        P1: Todo到期提醒
        P2: 新关联发现
        P3: 每日简报
      
      over_limit_handling:
        - 低优先级消息静默丢弃（记录日志）
        - 高优先级消息fallback到应用内通知
        - 每日凌晨重置计数器
      
      api_failure_handling:
        - timeout: 5s
        - retry: 3次（指数退避：1s, 2s, 4s）
        - circuit_breaker: 10次连续失败后，1小时内不再调用
        - fallback: 应用内通知 + 短信（仅P0级）
  ```

### P1 - 重要问题

**P1-1: 日志和监控方案过于简略**
- **问题位置**: §8.4 监控与告警
- **问题描述**:
  - 仅提Prometheus指标列表，但未说明：
    - 日志收集方案（stdout？文件？ELK？Loki？）
    - 日志格式标准（JSON？plain text？包含trace_id吗？）
    - 日志保留策略（本地磁盘会被撑爆）
  - 告警规则不完整：
    - 缺少"LLM API调用失败率>10%"告警
    - 缺少"微信推送失败率>20%"告警
    - 缺少"PostgreSQL慢查询>2s"告警
- **改进建议**:
  ```yaml
  # 日志方案
  logging_stack:
    phase1_minimum:
      - FastAPI日志输出到stdout（JSON格式）
      - Docker logs自动rotate（max-size: 100m, max-file: 3）
      - 通过 docker logs 查询（适用于单机部署）
    
    phase2_production:
      - Promtail收集容器日志 → Loki存储 → Grafana查询
      - 保留期：7天热数据 + 30天冷归档
    
    log_format:
      level: INFO
      format: json
      fields:
        - timestamp
        - level
        - service
        - trace_id（关键：用于链路追踪）
        - user_id
        - event_id
        - message
        - error_stack（如果有）
  
  # 告警增强
  additional_alerts:
    - name: llm_api_failure_rate
      expr: rate(llm_api_errors[5m]) / rate(llm_api_requests[5m]) > 0.1
      severity: critical
      
    - name: wechat_push_failure_rate
      expr: rate(wechat_push_errors[5m]) / rate(wechat_push_total[5m]) > 0.2
      severity: warning
      
    - name: postgres_slow_query
      expr: pg_stat_statements_mean_time > 2000
      severity: warning
      
    - name: redis_memory_usage
      expr: redis_memory_used_bytes / redis_memory_max_bytes > 0.8
      severity: warning
  ```

**P1-2: Phase 2微服务拆分路径不清晰**
- **问题位置**: §8.2 Phase 2扩展方案
- **问题描述**:
  - 文档说"可拆分为独立微服务"，但未给出：
    - 拆分的触发条件（用户量多少？QPS多少？）
    - 数据库拆分方案（Event/Entity/Todo是否要分库？）
    - 服务间通信方式（HTTP？gRPC？消息队列？）
    - 事务一致性如何保证（跨服务写入Entity+Association+Todo）
- **改进建议**:
  ```yaml
  # 拆分决策矩阵
  split_triggers:
    user_count: 1000+
    qps: Event Ingest >50 QPS
    database_size: >100GB
    team_size: 后端团队≥3人
  
  # 拆分方案
  microservices_architecture:
    services:
      - name: event-ingest
        responsibility: 接收事件+语义路由
        database: events表（独立库）
        expose: POST /events, GET /events/{id}
        
      - name: entity-graph
        responsibility: 实体归一+关联发现
        database: entities + associations表（独立库）
        expose: gRPC EntityService
        
      - name: todo-tracker
        responsibility: Todo生成+追踪
        database: todos表（独立库）
        expose: GET /todos, PATCH /todos/{id}
        
      - name: notify-gateway
        responsibility: 推送通知（微信+短信）
        database: 无（Redis缓存）
        expose: 消息队列消费者
    
    communication:
      sync: gRPC（Entity查询）
      async: RabbitMQ（Event处理完成后，发消息给Todo服务）
      
    transaction_handling:
      - Event Ingest写入Event表后，发MQ消息
      - Entity-Graph消费消息，处理后发MQ给Todo
      - Todo消费消息，生成Todo
      - 使用Saga模式处理跨服务事务（补偿机制）
  ```

**P1-3: 名片小程序H5页面部署和版本管理未定义**
- **问题位置**: §2.3 前端架构，§8.1 部署架构
- **问题描述**:
  - H5页面"独立部署的SPA"，但未说明：
    - 部署在哪里？（Nginx静态服务？CDN？小程序云开发？）
    - 如何做版本管理？（前端代码更新后，老版本小程序WebView缓存怎么办？）
    - 如何做灰度发布？（20%用户先用新版，出问题快速回滚）
  - 前后端联调：H5页面调用PromiseLink API，跨域如何处理？
- **改进建议**:
  ```yaml
  # H5部署方案
  h5_deployment:
    phase1_minimum:
      - Nginx静态托管（与PromiseLink API同一台服务器）
      - URL: https://promiselink.example.com/h5/
      - CORS配置：允许小程序域名访问API
      
    phase2_cdn:
      - 静态资源上传到腾讯云COS/阿里云OSS
      - 配置CDN加速
      - URL: https://cdn.promiselink.com/h5/v1.2.3/
      
    version_management:
      - 每次发布打tag: v1.2.3
      - HTML/JS/CSS文件名带hash: main.abc123.js
      - 小程序WebView URL动态配置（后端返回最新版本号）
      - 老版本保留7天（兼容未更新的小程序）
      
    rollback_strategy:
      - 发现问题后，修改后端返回的version指向上一版本
      - 用户重新打开小程序自动加载旧版H5
      - 回滚时间<5分钟
  ```

## 改进建议（P2/P3）

### P2 - 重要改进

**P2-1: Redis单点故障风险**
- Redis用于缓存+会话+限流，单点宕机影响所有功能
- 建议：Phase 2引入Redis Sentinel（3节点哨兵模式，自动故障切换）

**P2-2: PostgreSQL连接池配置建议**
- 文档未提及`max_connections`和应用层连接池配置
- 建议：
  ```python
  # SQLAlchemy连接池配置
  engine = create_engine(
      DATABASE_URL,
      pool_size=20,  # 常驻连接
      max_overflow=10,  # 峰值额外连接
      pool_timeout=30,  # 获取连接超时
      pool_recycle=3600,  # 1小时回收连接（避免PG服务端超时）
  )
  ```

**P2-3: TTS音频流传输优化**
- 语音播报场景，用户可能在4G网络下，音频加载慢
- 建议：TTS音频文件上传到CDN，返回CDN链接而非直传Base64

**P2-4: 敏感数据脱敏**
- Event表的`raw_text`可能包含金额/项目代号，日志不应明文记录
- 建议：日志中`raw_text`字段自动脱敏（仅保留前50字符+...）

### P3 - 可选优化

**P3-1: 数据库索引优化建议**
- `entities.properties` JSONB字段已建GIN索引，但未说明常用查询路径
- 建议补充：`CREATE INDEX idx_entities_company ON entities((properties->>'company'))`

**P3-2: Prometheus指标补充**
- 建议增加业务指标：
  - `promiselink_entity_merge_auto_count`（自动合并实体数，监控归一引擎效果）
  - `promiselink_todo_completion_rate`（Todo完成率，监控产品价值）

**P3-3: 开发环境Docker Compose配置**
- 建议提供`docker-compose.dev.yml`，包含：
  - PostgreSQL + Redis + Adminer（数据库GUI）
  - 自动挂载代码目录（热重载）

## 整体评估

### 评分：**7.0/10**

**优点：**
1. ✅ 架构设计清晰，事件驱动模型合理
2. ✅ 与CarryMem解耦设计优秀（Protocol接口 + 优雅降级）
3. ✅ 配置化设计思路正确（YAML配置分类法/角色标签）
4. ✅ LLM调用策略考虑了成本控制（Token上限 + 降级）
5. ✅ 数据模型设计合理（Event/Entity/Association/Todo）

**缺陷：**
1. ❌ **资源预估严重不足**，"2核4G可跑通PoC"不可信
2. ❌ **缺少高可用方案**，单点故障风险高
3. ❌ **外部依赖降级策略不完整**，LLM/TTS/微信API故障时用户体验差
4. ❌ **监控和日志方案过于简略**，生产环境故障排查困难
5. ⚠️ **Phase 2拆分路径不清晰**，未来扩展性存疑

### 审核结论：**有条件通过，需补充P0问题后方可进入开发**

**必须补充内容（阻塞开发）：**
1. P0-1: 补充Phase 1资源预估表（CPU/内存/磁盘/网络）
2. P0-2: 补充PostgreSQL备份恢复SOP文档（RTO/RPO明确）
3. P0-3: 补充LLM/TTS/微信API的故障降级决策树
4. P0-4: 补充微信推送限流控制和优先级队列设计

**建议补充内容（不阻塞开发，但Phase 1上线前必须完成）：**
1. P1-1: 补充日志收集方案和告警规则清单
2. P1-2: 补充Phase 2微服务拆分的触发条件和技术方案
3. P1-3: 补充H5页面部署和版本管理方案

---

**总结建议**：该设计在产品逻辑和数据模型上是优秀的，但在运维层面存在明显短板。建议开发团队：
1. 先做一次**压力测试**（模拟100用户并发使用），实测资源消耗
2. 准备一份**故障演练手册**（PG宕机/LLM超时/微信限流，分别如何处理）
3. 部署前做一次**备份恢复演练**（从pg_dump恢复数据，验证RTO是否<30分钟）

完成以上补充后，可进入开发阶段。

---

## UI/UX设计师 (ui-designer)

# UI/UX设计师审核意见

## 关键问题（P0/P1）

### P0 - 必须解决

**P0-1: Phase 1 H5内嵌体验存在致命缺陷**
- **位置**: PRD §1.5.2 环节B+，技术设计 §2.3
- **问题**: WebView内嵌H5的语音录入需要通过postMessage桥接，这会导致：
  - 双重交互延迟（小程序→H5→API→返回），用户感知卡顿
  - 许总"刚结束会议，还在外面"场景下，语音录入需要4步：打开小程序→等待WebView加载→点击录音→等待桥接响应，远超"≤2步到达核心功能"承诺
  - WebView加载速度不可控（3-5秒冷启动），与"<3秒响应"目标冲突
- **建议**: 
  - Phase 1直接在小程序原生实现语音录入页面，不走H5
  - H5仅保留"查询画像+TTS播报"两个只读场景
  - 或明确标注Phase 1语音录入≥5秒延迟的现实预期

**P0-2: "今日日程"信息密度与会前速览需求不匹配**
- **位置**: PRD §1.5.2 环节B+ "会前（开车/走路去拜访）"
- **问题**: 
  - 文档未定义"今日日程"页面的具体信息架构
  - 许总"眼神不好"需求下，在3.5寸小屏上快速扫视，需要极简信息密度
  - 当天有5场会议时，如何保证"<10秒会前速览"？每场会议需要展示哪些核心信息？
- **建议**:
  ```
  今日日程信息架构（移动端）：
  ┌────────────────────────────────┐
  │ 14:00 | 张伟 · XX科技           │ ← 时间+姓名+公司（18pt粗体）
  │ 🟢 供应链总监 | 单独见过面      │ ← 关系阶段标签（14pt）
  │ [🔊播报] [💬微信] [☎️电话]     │ ← 快捷操作（大按钮，48pt高度）
  ├────────────────────────────────┤
  │ 16:30 | 李明 · YY投资           │
  │ 🟡 投资经理 | 仅名片交换        │
  │ [🔊播报] [💬微信] [☎️电话]     │
  └────────────────────────────────┘
  
  展开详情（点击姓名）：
  - 上次交流要点（1句话，20字以内）
  - 建议话题（2-3个标签）
  - 关联关系（校友/前同事，1条）
  ```
  - 默认只展示最精简信息，详情需点击
  - 按钮尺寸≥44pt（Apple Human Interface Guidelines最小触摸目标）

**P0-3: TTS播报内容未定义，"<30秒播报完整人物简介"无法验收**
- **位置**: PRD §1.5.2 环节B+ "会前"，US-16
- **问题**: 
  - 示例仅展示一句话："张总，XX科技供应链总监。关系阶段：单独见过面。偏好电话沟通。上次聊了新项目预算。建议：可提华南区代工厂对接。"
  - 实际数据中Person.properties包含10+字段，如何取舍？
  - 播报顺序是什么？（基本信息→关系阶段→沟通偏好→上次要点→建议话题？）
  - 如何控制播报时长在30秒内？
- **建议**:
  ```
  TTS播报内容模板（优先级递减）：
  1. 基本信息（必选）："{姓名}，{公司}{职位}"（5秒）
  2. 关系阶段（必选）："{relationship.strength枚举值转自然语言}"（3秒）
  3. 沟通偏好（可选）："{communication.preferred_channel}沟通"（2秒）
  4. 上次要点（可选）：从最近1次事件提取1句核心要点（8秒）
  5. 建议话题（可选）：从关联关系中提取1-2个破冰话题（10秒）
  6. 风险提示（必选，如有）：竞对关系警告（2秒）
  
  总时长控制：28-30秒
  截断规则：如4+5超时，优先保留4
  ```
  - 需要在技术设计中定义TTS内容生成算法

### P1 - 重要

**P1-1: 语音录入交互流程缺失状态指示**
- **位置**: PRD §1.5.2 环节B+ "会后"
- **问题**: 
  - 用户"直接语音录入"后，系统需要：ASR→API调用→AI处理→推送结果，整个流程可能60秒
  - 文档未定义各阶段的状态指示：
    - 录音中？（波形动画？倒计时？）
    - 转写中？（进度条？预估时间？）
    - AI处理中？（"正在生成行动建议"？）
    - 处理失败？（重试入口？）
- **建议**:
  ```
  语音录入交互流程：
  1. 长按录音按钮 → 波形动画+倒计时（最长60秒）
  2. 松手 → "正在识别..."菊花转+预估5秒
  3. 识别完成 → 显示文本+[确认]/[重录]按钮
  4. 点击确认 → "AI处理中...预计30秒" 进度条
  5. 处理完成 → 跳转到行动建议页
  
  异常处理：
  - 识别失败 → "识别失败，请重试"Toast + [重录]按钮
  - API超时 → "处理超时，稍后查看" Toast + 记录到待办队列
  ```

**P1-2: 微信服务号模板消息信息密度过高**
- **位置**: PRD §1.5.2 环节D "每日早晨自动化"，§3.1 F-19触达推送
- **问题**: 
  - 微信服务号模板消息仅支持196字（中文约98字），需要展示：
    - 今日待办Top 5（每条≥15字）= 75字
    - 新发现关联数（10字）
    - 今日会议清单（每场≥20字，3场=60字）
  - 总计≥145字，但未考虑模板消息的固定字段（标题+跳转按钮）
  - "一目了然"与字数限制冲突
- **建议**:
  ```
  微信服务号模板消息精简方案：
  【今日简报】
  · 待办3项（🟢2 ⚪1）
  · 新关联2条
  · 会议2场：14:00张伟/16:30李明
  → 点击查看详情
  
  （共60字，留136字给微信模板固定字段）
  
  或分两条推送：
  1. 早8:00 今日会议准备（仅会议清单）
  2. 早9:00 每日待办摘要（Todo+关联）
  ```

**P1-3: 许总"眼神不好"的无障碍设计不完整**
- **位置**: PRD §1.5.2 环节B+，US-16
- **问题**: 
  - 文档仅提到"喜欢听语音"，但未定义视觉无障碍支持：
    - 字体大小可调节？（iOS动态字体？）
    - 高对比度模式？（WCAG AA级对比度4.5:1？）
    - 按钮间距是否足够大？（防误触）
    - 是否支持VoiceOver/TalkBack？
- **建议**:
  ```
  无障碍设计规范（优先级递减）：
  P0:
  - 全局字号≥16pt（可通过系统设置放大至20pt）
  - 核心按钮高度≥48pt，间距≥8pt
  - 所有交互元素对比度≥4.5:1（文字）、≥3:1（图标）
  
  P1:
  - 支持iOS动态字体（UIFontTextStyle）
  - 提供"大字模式"开关（全局+30%字号）
  - 重要信息支持TTS朗读（不限会前准备）
  
  P2:
  - 高对比度主题（黑底白字）
  - VoiceOver适配（所有按钮添加accessibilityLabel）
  ```

**P1-4: "移动端操作≤2步到达核心功能"的导航设计缺失**
- **位置**: PRD §1.5.2 环节B+，验收标准
- **问题**: 
  - 小程序底部Tab数量未定义（名片夹/关系助手/今日日程/待办/我的 = 5个？）
  - "≤2步到达核心功能"未举例验证：
    - 语音录入：打开小程序→点击Tab→点击录音 = 3步？
    - 查看今日会议：打开小程序→点击Tab = 2步？
    - 标记Todo完成：打开小程序→点击Tab→滑动卡片→点击完成 = 4步？
  - Phase 1 H5内嵌会增加步骤（打开小程序→点击Tab→等待WebView加载→操作）
- **建议**:
  ```
  导航设计（4 Tab精简方案）：
  1. 今日（首页）
     - 今日会议列表（默认页）
     - 快速录入入口（右上角+按钮，Floating Action Button）
     
  2. 待办
     - 按性质分组（🟢行动/⚪机会/🔵背景）
     - 滑动卡片标记完成（1步操作）
     
  3. 名片夹
     - 最近联系人
     - 搜索入口
     
  4. 我的
     - 设置/数据管理
  
  2步到达验证：
  - 查看今日会议：打开→默认显示（1步）
  - 语音录入：打开→点击+按钮（2步）
  - 标记Todo：打开→切换Tab（2步，卡片默认展开）
  - 查看人物画像：打开→点击会议中的姓名（2步）
  ```

---

## 改进建议

### P2 - 改进

**P2-1: TTS播报控制交互不完整**
- **位置**: PRD §1.5.2 环节B+ "会前"
- **问题**: 播放/暂停/重播的控制方式未定义
- **建议**:
  ```
  TTS播报控制设计：
  - 播放中：显示波形动画+[暂停]按钮
  - 暂停后：[继续]按钮（从当前位置继续）
  - 播放完毕：[重播]按钮
  - 进度指示：文字版同步高亮当前播报段落
  - 后台播放：锁屏状态继续播报（iOS Control Center控制）
  ```

**P2-2: WebView加载速度优化方案缺失**
- **位置**: 技术设计 §2.3 "Phase 1 H5与小程序通信协议"
- **问题**: 
  - 冷启动3-5秒与"<3秒响应"目标冲突
  - 未定义优化方案
- **建议**:
  ```
  WebView加载优化方案：
  1. 小程序启动时预加载WebView（后台隐藏iframe）
  2. H5采用SSR（Server-Side Rendering）减少白屏时间
  3. 关键CSS内联，非关键资源懒加载
  4. 使用CDN加速静态资源
  5. 骨架屏占位（首屏<1秒展示框架）
  
  降级方案：
  - 若WebView加载>3秒，显示"加载中"提示+[取消]按钮
  - 用户可取消返回小程序原生页面
  ```

**P2-3: 语音识别结果确认交互不友好**
- **位置**: PRD §1.5.2 环节B+ "会后"
- **问题**: 
  - "语音转文本"后，用户如何确认识别正确？
  - 识别错误时，是重新录音还是文字修改？
- **建议**:
  ```
  识别结果确认交互：
  1. 显示识别文本（可编辑文本框）
  2. 底部按钮组：
     - [重录]：清空重来
     - [编辑]：切换到键盘输入模式
     - [确认]：提交API
  3. 常见错误提示：
     - 识别到空白 → "未识别到内容，请重试"
     - 识别到无关内容 → "内容似乎不相关，确认提交？"
  ```

**P2-4: Phase 1→Phase 2体验升级点不清晰**
- **位置**: PRD §1.4 三层架构，审核问题8
- **问题**: 
  - 文档说Phase 1是H5，Phase 2是原生，但具体升级点仅提到"语音录入需小程序原生桥接"
  - 用户为什么要从Phase 1升级到Phase 2？
- **建议**:
  ```
  Phase 1→Phase 2体验升级对比：
  
  核心功能延迟：
  - 语音录入：5秒 → 2秒（去除WebView桥接）
  - 页面打开：3秒 → <1秒（原生渲染）
  - TTS启动：3秒 → 1秒（去除WebView加载）
  
  新增能力：
  - 离线缓存：无 → 有（最近50条联系人本地缓存）
  - 后台播报：不支持 → 支持（锁屏继续TTS）
  - 系统集成：无 → 有（通讯录/日历双向同步）
  - 手势操作：有限 → 丰富（滑动标记完成/长按预览）
  
  在PRD §1.4明确标注此对比表
  ```

### P3 - 可选

**P3-1: 会前速览的可视化设计缺失**
- **建议**: 补充"今日日程"页面的线框图或高保真设计稿

**P3-2: 暗色模式支持未考虑**
- **建议**: 补充暗色模式配色方案（遵循iOS/Android系统设置）

**P3-3: 横屏适配未定义**
- **建议**: 明确是否支持横屏（建议Phase 1锁定竖屏）

---

## 整体评估

### 评分：**6.5/10**

#### 优点：
1. ✅ 产品定位清晰，"让重要的人，不止停留在微信里"直击痛点
2. ✅ 用户旅程完整，从冷启动到日常维护覆盖全流程
3. ✅ TTS播报+语音录入符合许总"眼神不好"的核心需求
4. ✅ 触达通道设计合理（微信服务号+小程序卡片）

#### 关键缺陷：
1. ❌ **Phase 1 H5内嵌方案与"≤2步到达核心功能"承诺冲突**（P0）
2. ❌ **"今日日程"信息架构缺失，无法验证"<10秒会前速览"**（P0）
3. ❌ **TTS播报内容未定义，"<30秒播报完整人物简介"无法验收**（P0）
4. ❌ **语音录入交互流程不完整，缺少状态指示和异常处理**（P1）
5. ❌ **无障碍设计不完整，仅依赖TTS无法满足"眼神不好"需求**（P1）

### 审核结论：**不同意通过，需解决3个P0问题后重新审核**

#### 必须补充的设计产物：
1. **"今日日程"页面线框图**（标注信息密度、字号、按钮尺寸）
2. **TTS播报内容生成算法文档**（包含播报脚本模板、时长控制规则）
3. **语音录入完整交互流程图**（包含所有状态节点和异常分支）
4. **Phase 1技术方案调整**：
   - 方案A：小程序原生实现语音录入，H5仅保留只读功能
   - 方案B：明确标注Phase 1延迟预期（5秒），不承诺"≤2步"
5. **无障碍设计规范文档**（字号/对比度/按钮尺寸/VoiceOver适配）

#### 建议优先级：
- **Week 1**: 解决P0-1/P0-2/P0-3（调整Phase 1技术方案+补充页面设计）
- **Week 2**: 解决P1-1/P1-2/P1-3（完善交互流程+优化触达方案+无障碍设计）
- **Week 3**: 解决P1-4/P2系列（导航设计+性能优化）

---

## 附加建议

### 关于WCAG合规性
如PRD要求，全面的无障碍验证需要：
1. 使用VoiceOver/TalkBack进行真实场景测试
2. 色盲模拟工具验证色彩区分度
3. 第三方无障碍专家评估

建议在Phase 2引入专业无障碍测试团队，Phase 1先满足基础对比度和字号要求。

---

## 共识汇总

- **共识结论**: 不通过
- **平均评分**: 0.0/10
- **通过率**: 4/7

### P0 必须解决的问题
1. 会前提醒（15分钟前）
2. - 全局字号≥16pt（可通过系统设置放大至20pt）

### P1 重要问题
1. Todo到期提醒
2. - 支持iOS动态字体（UIFontTextStyle）
