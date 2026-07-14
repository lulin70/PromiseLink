# PromiseLink 技术设计文档

> ⚠️ **废弃内容说明（2026-07-12 更新）**：本文档 §8.6.3a "托管 PoC 部署"相关内容（`docker-compose.hosted-poc.yml`、云端部署命令等）已废弃并删除。基础版禁止云端部署（硬约束），必须在用户本地运行（localhost:8000）。云端服务器仅部署专业版网关 + 官网静态文件。详见：PromiseLink-Pro `docs/deployment/DEPLOYMENT_COMPLIANCE_CHECKLIST.md`

> **版本**: v3.2
> **日期**: 2026-06-17
> **对应PRD**: v5.2
> **架构师**: CarryMem团队
> **变更说明**: v3.2: §8.7.4 AI调用路径升级为三场景模型（基础版离线/专业版浏览器/专业版小程序）+专业版身份验证流程（JWT 5步验证+隐私声明）+§8.7.6新增Open Core模型说明（基础版MPL 2.0开源/专业版闭源/开源是隐私技术保证）

---

## 1. 设计原则

### 1.1 核心原则

1. **互动驱动，关系是互动的产物** — 互动记录是一切数据的源头，Entity/Association/Todo都从互动推导而来。核心闭环：互动记录→关注提取→承诺识别→帮助建议→反馈追踪
2. **AI的知识，不是用户的负担** — 画像/分类/路由规则作为AI提取和推理的参考，用户只需确认
3. **可配置优于硬编码** — 分类法/角色标签/会议类型存储为配置文件，支持行业定制
4. **与CarryMem解耦** — PromiseLink是独立服务，通过协议接口消费CarryMem能力，不直接依赖其内部实现

### 1.2 与CarryMem的边界

```
CarryMem（AI记忆层）          PromiseLink（商务关系引擎）
├── 个人偏好/决策/纠正        ├── 事件/实体/关联/Todo
├── 规则引擎（forbid/avoid）  ├── 关联发现引擎
├── SQLite本地存储            ├── SQLite（个人版长期方案，定制版用PG+Redis）
└── Python API + MCP          └── HTTP REST API

集成点（单向消费）：
PromiseLink → CarryMemAdapter → CarryMem.recall_memories()
                                CarryMem.match_rules()
                                CarryMem.declare()

不做的：
❌ PromiseLink不把CarryMem当存储层
❌ PromiseLink不调用CarryMem.classify_and_remember()
❌ CarryMem不感知PromiseLink的数据模型
```

---

## 2. 系统架构

### 2.1 整体架构

```
┌──────────────────────────────────────────────────────────┐
│              名片小程序（许总团队，主入口）                    │
│  扫名片 / 名片夹 / 🆕关系助手(H5) / 🆕今日日程 / 🆕待办    │
│  ┌─────────────────────────────────────────────────────┐ │
│  │ PromiseLink H5页面（专业版，WebView内嵌）              │ │
│  │  查询画像 / 语音录入 / TTS播报 / 快速记录              │ │
│  └──────────────────────┬──────────────────────────────┘ │
└─────────────────────────┼────────────────────────────────┘
                          │ HTTP API
                          ▼
┌──────────────────────────────────────────────────────────┐
│                   PromiseLink API Gateway                    │
│              (FastAPI + 认证 + 限流 + 日志)                │
└──────────────────────┬───────────────────────────────────┘
                       │
          ┌────────────┼────────────┼────────────┐
          ▼            ▼            ▼            ▼
┌──────────────┐ ┌──────────┐ ┌──────────────┐ ┌──────────────┐
│ Event Ingest │ │ Query    │ │ Todo         │ │ Insight      │
│ Service      │ │ Service  │ │ Service      │ │ Engine       │
│              │ │          │ │              │ │              │
│ · 接收事件   │ │ · 搜索   │ │ · 生成       │ │ · 动态评分   │
│ · 语义路由   │ │ · 过滤   │ │ · 追踪       │ │ · 隐式反馈   │
│ · 实体抽取   │ │ · 图谱   │ │ · 提醒       │ │ · 优先级排序 │
│ · 关联发现   │ │ · 画像   │ │ · 反馈闭环   │ │              │
└──────┬───────┘ └──────────┘ └──────────────┘ └──────────────┘
       │
       ▼
┌──────────────────────────────────────────────────────────┐
│                    数据层                                   │
│  SQLite (Event/Entity/Association/Todo) — 个人版长期方案       │
│  PostgreSQL+Redis — 仅定制版（销售团队多用户场景）              │
│  YAML配置 (分类法/角色标签/会议类型)                         │
└──────────────────────────────────────────────────────────┘
       │
       │ 可选（Protocol接口，优雅降级）
       ▼
┌──────────────────────────────────────────────────────────┐
│               CarryMemAdapter（协议接口）                   │
│  · recall_memories() → 获取用户偏好/规则                    │
│  · match_rules() → 匹配行为规则                             │
│  · is_available() → False时优雅降级                         │
└──────────────────────────────────────────────────────────┘
```

### 2.2 服务拆分

| 服务 | 职责 | 核心API | 依赖 |
|------|------|---------|------|
| **Event Ingest** | 事件接入+处理 | `POST /events`, `GET /events/{id}` | PG, Redis, LLM |
| **Query** | 查询+搜索+图谱 | `GET /entities`, `GET /associations` | PG, Redis |
| **Todo** | Todo生成+追踪 | `GET /todos`, `PATCH /todos/{id}` | PG, Redis |
| **Insight Engine** | 动态优先级+反馈学习 | `GET /todos?sort=smart`, `POST /todos/{id}/complete` | PG, Redis |
| **Mini** | 小程序专用接口 | `GET /mini/today`, `GET /mini/person/{id}`, `GET /mini/person/{id}/tts` | PG, Redis, TTS |
| **Notify** | 推送通知 | 微信服务号模板消息, APNs/FCM | Redis, 微信API |

专业版 五个服务部署在同一FastAPI进程中，通过模块边界隔离。定制版 可拆分为独立微服务。

### 2.3 前端架构

```
专业版（快速验证）：
  许总名片小程序
  ├── 原生页面：语音录入/今日日程（核心交互走原生，不走H5）
  │   ├── wx.startRecord → ASR → PromiseLink API（语音录入）
  │   ├── 微信同声传译插件 → TTS播报（会前速览）
  │   └── 名片扫描 → 直接调用 POST /api/v1/events (card_save)
  └── WebView → PromiseLink H5页面（仅只读查询场景）
      ├── 技术栈：Vue3 + Vant UI 3.x（兼容微信WebView）
      ├── 通信：临时授权码模式（非明文token）
      ├── 能力：查询画像/关系图谱/数据管理
      └── 限制：不负责语音录入和TTS（由小程序原生处理）

定制版（深度整合）：
  许总名片小程序
  ├── 原生页面：今日日程/待办提醒/人物速览/语音录入/TTS播报
  ├── 微信API：wx.startRecord → ASR → PromiseLink API
  ├── 微信API：微信同声传译插件 → TTS播报
  └── 名片扫描 → 直接调用 POST /api/v1/events (card_save)
```

> **架构决策（7角色审核共识）**：专业版语音录入和TTS播报走小程序原生页面，不走H5 WebView。
> 理由：①微信同声传译插件仅支持小程序原生，H5无法调用 ②语音录入链路复杂（H5→postMessage→小程序→录音→ASR→回调），错误处理困难 ③许总核心场景"开车听简介"需要<3秒响应，WebView冷启动3-5秒不可接受

**专业版 H5与小程序通信协议（临时授权码模式）**：

```javascript
// 小程序端：打开WebView时使用临时授权码（非明文token）
async function openPromiseLinkH5(action, personId) {
  // 1. 请求服务端生成一次性授权码（60秒有效）
  const ticket = await request({
    url: '/api/v1/auth/ticket',
    method: 'POST',
    data: { action, person_id: personId }
  })
  
  // 2. URL传递ticket而非token
  wx.navigateTo({
    url: `/pages/webview/webview?ticket=${ticket.code}`
  })
}

// H5端：用ticket换取真实token
async function initFromTicket() {
  const ticket = parseUrlParams().ticket
  // ticket单次使用，换取access_token
  const auth = await fetch('/api/v1/auth/exchange', {
    method: 'POST',
    body: JSON.stringify({ ticket })
  })
  const { access_token } = await auth.json()
  sessionStorage.setItem('_t', access_token) // 存内存不存localStorage
}

// H5端：需要录音时，跳转小程序原生页面（非postMessage桥接）
function startVoiceInput() {
  wx.miniProgram.navigateTo({
    url: `/pages/voice-input/voice-input?from=h5`
  })
}

// H5端：请求TTS播报，跳转小程序原生页面
function requestTTS(personId) {
  wx.miniProgram.navigateTo({
    url: `/pages/tts-player/tts-player?person_id=${personId}`
  })
}
```

**H5↔原生页面数据同步协议**：

```javascript
// 方案：onShow生命周期 + Storage共享（专业版最简方案）
// 原生页面录音/操作完成后：
wx.setStorageSync('_promiselink_sync', {
  timestamp: Date.now(),
  action: 'voice_input',     // voice_input | tts_complete
  event_id: 'evt_abc',       // 新创建的事件ID
  entity_ids: ['ent_123']    // 影响的实体ID列表
})
wx.navigateBack()

// H5端：监听页面可见性变化，检测同步标记
document.addEventListener('visibilitychange', () => {
  if (document.visibilityState === 'visible') {
    const sync = wx.getStorageSync('_promiselink_sync')
    if (sync && sync.timestamp > lastSyncTime) {
      lastSyncTime = sync.timestamp
      wx.removeStorageSync('_promiselink_sync')
      refreshData(sync.entity_ids)  // 增量刷新受影响的实体
    }
  }
})

// 定制版升级：EventChannel双向通信
// const eventChannel = wx.getOpenerEventChannel()
// eventChannel.emit('dataChanged', { event_id: 'evt_abc' })
```

**TTS播报内容模板与隐私保护**：

```python
class TTSScriptComposer:
    PRIORITY_ORDER = [
        ("basic", True, 5),       # "{姓名}，{公司}{职位}" — 必选，5秒
        ("relation", True, 3),     # 关系阶段 — 必选，3秒
        ("preference", False, 2),  # 沟通偏好 — 可选，2秒
        ("last_contact", False, 8),# 上次交流1句要点 — 可选，8秒
        ("suggestion", False, 10), # 建议话题1-2个 — 可选，10秒
        ("risk", True, 2),         # 风险提示 — 必选(如有)，2秒
    ]
    MAX_DURATION = 30  # 秒

    def compose(self, person: Entity, privacy_level: str = "standard") -> str:
        parts = []
        remaining = self.MAX_DURATION
        
        for field, required, est_seconds in self.PRIORITY_ORDER:
            if remaining <= 0 and not required:
                break
            text = self._render_field(person, field, privacy_level)
            if text:
                parts.append(text)
                remaining -= est_seconds
        
        return "。".join(parts) + "。"

    def _render_field(self, person, field, privacy_level):
        props = person.properties
        if field == "basic":
            return f"{person.name}，{props.get('company', '')}{props.get('title', '')}"
        elif field == "relation":
            stage = props.get('relationship', {}).get('strength', '')
            return f"关系阶段：{self._humanize_stage(stage)}" if stage else None
        elif field == "preference":
            ch = props.get('communication', {}).get('preferred_channel', '')
            return f"偏好{ch}沟通" if ch else None
        elif field == "last_contact":
            if privacy_level == "strict":
                return "上次交流要点已隐藏"
            return props.get('relationship', {}).get('next_hook')
        elif field == "suggestion":
            if privacy_level == "strict":
                return None
            hook = props.get('relationship', {}).get('next_hook')
            return f"建议：{hook}" if hook else None
        elif field == "risk":
            return None  # 定制版: 竞对风险提示
```

**隐私分级播报**：

| 级别 | 播报内容 | 适用场景 |
|------|----------|----------|
| basic | 姓名+公司+职位+关系阶段 | 周围有人/公共场合 |
| standard | basic+沟通偏好+上次要点+建议 | 独处/车内 |
| strict | 姓名+公司+职位+关系阶段(隐藏细节) | 敏感环境 |

**微信推送分级策略**：

```python
class PushContentPolicy:
    LEVELS = {
        "brief": {
            "title": "今日会议 {time}",
            "body": "与{name}会面，点击查看准备清单 >",
            "sensitive_in_push": False
        },
        "standard": {
            "title": "今日会议 {time}",
            "body": "与{name}会面。{company}{title}。点击查看详情 >",
            "sensitive_in_push": False
        },
    }
    
    def render(self, event, user_pref):
        level = user_pref.get("push_detail_level", "brief")
        template = self.LEVELS[level]
        return template["title"].format(**event), template["body"].format(**event)
```

> **安全原则**：微信服务号推送不包含关系阶段、交流要点、建议话题等敏感信息，仅展示时间和姓名，详情需打开小程序查看。

**TTS音频缓存策略**：

```python
class TTSCacheManager:
    # 缓存key: hash(person_id + properties版本 + privacy_level)
    # 缓存介质: Redis (专业版) → OSS+CDN (定制版)
    CACHE_TTL = 3600  # 1小时

    async def get_or_generate(self, person_id: str, privacy_level: str) -> bytes:
        cache_key = await self._build_cache_key(person_id, privacy_level)
        audio = await redis.get(cache_key)
        if audio:
            return audio

        person = await db.get_entity(person_id)
        script = TTSScriptComposer().compose(person, privacy_level)
        audio = await tts_provider.synthesize(script)

        await redis.setex(cache_key, self.CACHE_TTL, audio)
        return audio

    async def _build_cache_key(self, person_id: str, privacy_level: str) -> str:
        person = await db.get_entity(person_id)
        props_hash = hashlib.md5(
            json.dumps(person.properties, sort_keys=True).encode()
        ).hexdigest()[:8]
        return f"tts:{person_id}:{props_hash}:{privacy_level}"

    async def invalidate(self, person_id: str):
        # 画像更新时，清除该人物所有缓存
        async for key in redis.scan_iter(f"tts:{person_id}:*"):
            await redis.delete(key)
```

**TTS URL签名（防泄露）**：

```python
async def generate_tts_url(person_id: str, user_id: str) -> str:
    exp = int(time.time()) + 300  # 5分钟有效
    payload = f"{person_id}:{user_id}:{exp}"
    sig = hmac.new(TTS_SECRET_KEY, payload.encode(), hashlib.sha256).hexdigest()[:16]
    return f"/api/v1/mini/person/{person_id}/tts?sig={sig}&exp={exp}"
```

**TTS降级策略**：

```python
class TTSFallbackChain:
    PROVIDERS = [
        WechatTTSProvider(),      # 优先：微信同声传译插件
        TextFallbackProvider(),   # 降级：纯文字展示（无音频）
    ]

    async def speak(self, person_id: str, privacy_level: str) -> TTSResult:
        for provider in self.PROVIDERS:
            try:
                result = await provider.generate(person_id, privacy_level)
                if result.success:
                    return result
            except Exception as e:
                logger.warning(f"TTS provider {provider} failed: {e}")
                continue
        return TTSResult(success=False, fallback_text=script)
```

**备选方案：PromiseLink自建小程序（Taro框架）【v2.3新增】**
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

触发条件（满足任一）：
  - 许总团队2周内无法启动前端开发
  - 数字名片API对接超3周无结论
  - 需要独立目标用户测试环境

技术栈：
  - Taro 3.x + Vue3 + NutUI 4.x（微信小程序）
  - 或原生微信小程序（更轻量）

核心页面（MVP 5页）：
  1. 首页：今天需要回应的连接 + 最近值得推进
  2. 录入页：语音录入(ASR) + 文字录入 + 名片扫描
  3. 人物详情：关系推进卡（12模块）
  4. Todo列表：待办 + 已完成 + 等待对方回应
  5. 设置：账号/隐私/导出/删除

与后端API完全兼容（零改动）
开发周期：2-3周 MVP

---

## 3. 数据模型

### 3.1 核心表

```sql
-- 事件表
CREATE TABLE events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    event_type VARCHAR(20) NOT NULL,  -- card_save|meeting|call|manual
    source VARCHAR(50) NOT NULL,      -- iamhere|recording_r1|manual
    title VARCHAR(200) NOT NULL,
    timestamp TIMESTAMPTZ NOT NULL,
    raw_text TEXT NOT NULL,
    metadata JSONB DEFAULT '{}',
    input_scope VARCHAR(30) DEFAULT 'relationship_interaction',  -- 输入分类（v2.3新增）
    input_scope_confidence FLOAT DEFAULT 1.0,                   -- 分类置信度（v2.3新增）
    user_id UUID NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX idx_events_user_timestamp ON events(user_id, timestamp DESC);
CREATE INDEX idx_events_input_scope ON events(input_scope) WHERE input_scope IS NOT NULL;  -- v2.3新增索引

-- 实体表
CREATE TABLE entities (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    entity_type VARCHAR(20) NOT NULL,  -- person|organization|technology|project|attribute
    name VARCHAR(100) NOT NULL,
    aliases TEXT[] DEFAULT '{}',
    properties JSONB DEFAULT '{}',     -- 扩展画像存这里（含concern/promise/contribution + 定制版的resource/demand）
    company VARCHAR(100),              -- 高频查询列（从properties提取）
    title VARCHAR(100),                -- 高频查询列
    city VARCHAR(50),                  -- 高频查询列
    industry VARCHAR(50),              -- 高频查询列
    source_events UUID[] DEFAULT '{}',
    user_id UUID NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX idx_entities_user_type ON entities(user_id, entity_type);
CREATE INDEX idx_entities_properties ON entities USING gin(properties);
CREATE INDEX idx_entities_company ON entities(user_id, company) WHERE company IS NOT NULL;
CREATE INDEX idx_entities_city ON entities(user_id, city) WHERE city IS NOT NULL;
CREATE INDEX idx_entities_industry ON entities(user_id, industry) WHERE industry IS NOT NULL;
CREATE INDEX idx_entities_title ON entities(user_id, title) WHERE title IS NOT NULL;

-- 列索引同步触发器（properties变更时自动同步提取列）
CREATE OR REPLACE FUNCTION sync_entity_columns()
RETURNS TRIGGER AS $$
BEGIN
  NEW.company := NEW.properties->>'company';
  NEW.title := NEW.properties->>'title';
  NEW.city := NEW.properties->>'city';
  NEW.industry := NEW.properties->>'industry';
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER entities_sync_columns
  BEFORE INSERT OR UPDATE ON entities
  FOR EACH ROW EXECUTE FUNCTION sync_entity_columns();

-- 关联表
CREATE TABLE associations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source_entity UUID REFERENCES entities(id),
    target_entity UUID REFERENCES entities(id),
    relation_type VARCHAR(30) NOT NULL,
    role_tag JSONB DEFAULT '{}',       -- {layer, role, level}
    strength FLOAT DEFAULT 0.5,
    evidence UUID[] DEFAULT '{}',
    status VARCHAR(10) DEFAULT 'active',
    user_id UUID NOT NULL,
    discovered_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX idx_assoc_source ON associations(source_entity);
CREATE INDEX idx_assoc_target ON associations(target_entity);

-- Todo表
-- 语义：因为某次互动(原因)，对某个实体(对象)，维护某段关系(目标)
-- v2.0：Todo类型从资源视角改为关系视角
--   opportunity → cooperation_signal（合作信号：对方释放的合作意向）
--   risk → risk（保留：关系风险预警）
--   context → care（关注点：对方正在关心什么）
--   action → promise（承诺：我答应过什么）
--   pending_confirm → followup（跟进：待确认/待反馈）
--   resource_maint → help（帮助：我能为他做什么）
CREATE TABLE todos (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    todo_type VARCHAR(25) NOT NULL,  -- cooperation_signal|risk|care|promise|followup|help
    title VARCHAR(200) NOT NULL,
    description TEXT,
    source_event UUID REFERENCES events(id),          -- 为什么产生（可选，系统提醒无来源事件）
    evidence_event_id UUID REFERENCES events(id),     -- 证据来源事件（用于溯源，v2.4新增）
    target_entities UUID[] DEFAULT '{}',               -- 对谁做（可多人）
    target_association UUID REFERENCES associations(id), -- 维护哪段关系（可选）
    status VARCHAR(15) DEFAULT 'pending',
    due_date TIMESTAMPTZ,
    action_type VARCHAR(25) DEFAULT 'my_promise',  -- v2.4修正：6种(my_promise|their_promise|my_followup|mutual_action|system_reminder|unclear)
    promisor_id UUID REFERENCES entities(id),            -- v2.3新增：承诺人ID
    beneficiary_id UUID REFERENCES entities(id),          -- v2.3新增：受益人ID
    confirmation_status VARCHAR(15) DEFAULT 'pending',   -- v2.3新增：pending|confirmed|rejected|unclear
    evidence_quote TEXT,                                  -- v2.3新增：证据原文
    user_id UUID NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    completed_rank INTEGER,                              -- v2.6新增：完成序号（隐式反馈用）
    dynamic_score FLOAT,                                 -- v2.6新增：动态优先级分
    score_calculated_at TIMESTAMPTZ                      -- v2.6新增：评分时间
);
CREATE INDEX idx_todos_user_status ON todos(user_id, status);
CREATE INDEX idx_todos_source_event ON todos(source_event);
CREATE INDEX idx_todos_target_association ON todos(target_association);
CREATE INDEX idx_todos_dynamic_score ON todos(user_id, dynamic_score DESC) WHERE dynamic_score IS NOT NULL;  -- v2.6新增索引

-- 关系推进卡表（v2.3新增，P0必须）
CREATE TABLE relationship_briefs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL,
    person_id UUID NOT NULL REFERENCES entities(id),
    current_stage VARCHAR(30) NOT NULL DEFAULT 'new_connection',
    stage_reason TEXT,
    latest_interaction_id UUID REFERENCES events(id),
    next_node TEXT,
    next_node_condition TEXT,
    paused_reason TEXT,
    confirmed_by_user BOOLEAN DEFAULT FALSE,
    version INTEGER NOT NULL DEFAULT 1,                   -- 乐观锁版本号（v2.4新增）
    concerns JSONB DEFAULT '[]',
    need_insights JSONB DEFAULT '[]',
    contributions JSONB DEFAULT '[]',
    pending_promises JSONB DEFAULT '[]',
    feedback_records JSONB DEFAULT '[]',
    cooperation_direction_candidate TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX idx_briefs_user ON relationship_briefs(user_id);
CREATE INDEX idx_briefs_person ON relationship_briefs(person_id);
CREATE UNIQUE INDEX idx_briefs_user_person ON relationship_briefs(user_id, person_id);
```

#### 3.1a PII字段安全策略（v2.4新增，BLK-1 P0阻塞修复）

**evidence_quote 字段安全处理流程**：

```
LLM原始输出 → sanitize_llm_input()清洗 → 存储到evidence_quote(TEXT)
                                          ↓
                                    API返回前脱敏处理
                                          ↓
                              phone/email/id_card → ***掩码
```

实现要点：
1. **存储前**：调用 `promiselink.core.text_utils.sanitize_llm_input()` 清洗注入风险
2. **存储时**：不建全文索引（避免敏感信息泄露到搜索结果）
3. **返回前**：API层调用新的 `redact_pii_from_text()` 函数脱敏
4. **导出时**：同样执行脱敏（CSV/JSON导出均适用）

新增工具函数位置：`src/promiselink/core/text_utils.py`

```python
import re

def redact_pii_from_text(text: str) -> str:
    """Redact PII from text for API responses."""
    if not text:
        return text
    # phone: 138****1234
    text = re.sub(r'(\d{3})\d{4}(\d{4})', r'\1****\2', text)
    # email: ***@domain.com
    text = re.sub(r'\b(\w?)\w*?(@\w+\.\w+)', r'***\1\2', text)
    # id_card: **************1234 (保留后4位)
    text = re.sub(r'(\d{14})\d{4}', r'\1********', text)
    return text
```

**PII检测正则规则（redact_pii_from_text实现依据）**：

| PII类型 | 正则模式 | 掩码规则 | 示例 |
|---------|---------|---------|------|
| 手机号(中国大陆) | `1[3-9]\d{9}` | 前3后4中间**** | 138****1234 |
| 邮箱 | `[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}` | 用户名部分*** | ***@example.com |
| 身份证号 | `\d{17}[\dXx]` | 前6后4中间****** | **************1234 |
| 银行卡号 | `\d{16,19}` | 前4后4中间**** | **** **** **** 1234 |
| 微信号 | `[a-zA-Z][-a-zA-Z0-9_]{5,19}` | 第2位后*** | w*** |
| 地址中的门牌号 | `(\w+路)\d+号` | 号码替换为**号 | 科技路**号 |

**注意事项**：
- 正则匹配在text_utils.py中实现，单元测试必须覆盖每种PII类型
- 脱敏仅在API返回层执行，存储层保留原文（已加密）
- 导出功能(CSV/JSON)同样执行脱敏

### 3.2 Person实体扩展画像

Person的`properties` JSONB字段按需丰富，不强制填充：

```json
{
  "company": "XX科技",
  "title": "供应链总监",
  "city": "深圳",
  "industry": "工业互联网",
  "seniority": "P9专家",
  "communication": {
    "preferred_channel": "phone",
    "response_speed": "fast"
  },
  "decision": {
    "power": "final_decision_maker",
    "style": "data_driven"
  },
  "concern": ["华南区代工厂对接", "供应链数字化转型"],
  "promise": ["发送活动方案", "引荐物流专家"],
  "contribution": ["提供了3个代工厂联系方式", "分享了行业白皮书"],
  "relationship_stage": "new_connection",  // v2.3新增：替代原strength字段
  "relationship": {                          // v2.3重构：关系推进卡结构
    "stage": "new_connection",
    "stage_reason": "首次记录互动",
    "paused_reason": null,
    "confirmed_by_user": false,
    "next_node": "了解对方关心什么",
    "next_node_condition": "已识别对方至少1个关注点",
    "updated_at": "2026-06-04T12:00:00+08:00"
  }
}
```

> **v2.0字段说明**：
> - **concern** `[]`：对方正在关心什么（从互动中提取，需用户确认）
> - **promise** `[]`：我答应过对方什么（承诺兑现闭环的核心）
> - **contribution** `[]`：我为对方做过什么（帮助记录，利他闭环）
> - **resource/demand**字段保留但PoC阶段不启用，定制版资源经营能力开放后使用

**关键设计**：字段名和枚举值存储为配置，不是硬编码。AI根据附录A的参考框架提取，用户确认即可。**敏感结论必须用户确认才能持久化**（v2.0新增约束）。

### 3.3 Association角色标签

```json
{
  "layer": "GOVERNANCE",
  "role": "investor",
  "level": 2,
  "confidence": 0.85,
  "status": "provisional"
}
```

**关键设计**：角色分类法存储为YAML配置文件，不同行业可替换。

---

## 4. 引擎设计

### 4.1 事件处理管线

```
Event Ingest Pipeline (v2.3):
  Input(raw_text, event_type, source)
    │
    ├─ Step 0: input_scope分类 【v2.3新增】
    │   └─ InputClassifier.classify(raw_text, event_type)
    │       返回 {scope, confidence, reason}
    │       规则兜底：特定关键词触发默认分类
    │       partner_feedback/internal_review → 终止（不进入后续管线）
    │
    │   **安全约束 SC-01（v2.4新增，BLK-2 P0阻塞修复）**：
    │   - API端 `POST /api/v1/events` 的 input_scope 字段：
    │     - 如果客户端传 "auto" 或不传 → 服务端调用 InputClassifier.classify()
    │     - 如果客户端传具体值 → 仅作为 hint，服务端仍以 classify() 结果为准
    │     - 如果客户端传非法值（不在8种枚举内）→ 返回 400 Bad Request
    │     - **永远不以客户端传入值作为最终 scope**
    │
    │   校验逻辑伪代码：
    │   ```python
    │   VALID_SCOPES = {
    │       "relationship_interaction", "identity_update", "meeting_minutes",
    │       "partner_feedback", "internal_review", "resource_inquiry",
    │       "care_expression", "cooperation_signal"
    │   }
    │
    │   def resolve_input_scope(client_scope: str | None, raw_text: str, event_type: str) -> dict:
    │       # 非法值校验
    │       if client_scope and client_scope not in VALID_SCOPES and client_scope != "auto":
    │           raise HTTPException(400, f"Invalid input_scope: {client_scope}")
    │       # 永远以服务端classify()结果为准
    │       result = InputClassifier.classify(raw_text, event_type)
    │       return result  # {scope, confidence, reason}
    │   ```
    │
    ├─ Step 1: 语义路由（v2.3改造：接收scope参数）
    │   └─ 根据(event_type + input_scope)选择处理管线
    │       identity → 只更新人物基础信息（不抽取关注/承诺）
    │       relationship_interaction → 完整管线
    │       meeting_minutes → 完整管线（承诺证据来源）
    │
    ├─ Step 2: LLM实体抽取（不变）
    │   └─ 从raw_text中抽取Person/Organization/Topic/Project
    │   └─ Person自动填充properties（基础信息+AI推断的沟通偏好/决策画像）
    │   └─ 抽取结果标记confidence，低置信度进入人工确认队列
    │
    ├─ Step 3: 实体归一（不变）
    │   └─ 判断新抽取的Person是否与已有Entity重复
    │   └─ 5步算法：精确匹配→别名匹配→模糊匹配→上下文匹配→人工确认
    │   └─ 合并时保留更丰富的properties
    │
    ├─ Step 4: 关联发现（不变）
    │   └─ 共现分析（同事件出现→strength+0.1）
    │   └─ 类型推断（同公司→colleague，同行业→competitor）
    │   └─ 角色标签推荐（根据职级/行业推断role_tag）
    │
    ├─ Step 5: Todo生成 【v2.3重大改造】
    │   └─ 接收scope参数
    │   └─ 按 scope 规则过滤：
    │     - partner_feedback/internal_review → 不生成Todo
    │     - 单场会议 ≤3条（按urgency排序截断）
    │   └─ Promise 双向解析（action_type/promisor/beneficiary）
    │   └─ 对方承诺(their_promise) → 不进我的Todo列表
    │   └─ 根据互动内容+关联类型生成不同性质的Todo
    │       meeting → 🟢承诺(promise) + 🔵关注(care) + 🟡合作信号(cooperation_signal)
    │       call → 🟢跟进(followup)
    │       card_save → 🔵关注(care)
    │       v2.0核心闭环：互动记录→关注提取→承诺识别→帮助建议→反馈追踪
    │
    ├─ Step 6: 存储（不变）
    ├─ Step 7: 关联发现（不变）
    │
    └─ Step 8: 更新RelationshipBrief 【v2.3新增】
        └─ 创建或更新关系推进卡
            - 更新current_stage（如有变化建议）
            - 追加concerns/need_insights/contributions
            - 记录latest_interaction_id
```

### 4.2 LLM调用策略

```python
class LLMStrategy:
    def extract_entities(self, raw_text: str, event_type: str) -> ExtractResult:
        prompt = self._build_extract_prompt(raw_text, event_type)
        result = self.llm.generate(prompt, max_tokens=2000)
        return self._parse_extract_result(result)

    def infer_role_tag(self, person: Entity) -> RoleTag:
        prompt = f"根据以下信息推断角色分类：{person.properties}"
        result = self.llm.generate(prompt, max_tokens=200)
        return self._parse_role_tag(result)

    def generate_todos(self, event: Event, entities: List[Entity]) -> List[Todo]:
        prompt = self._build_todo_prompt(event, entities)
        result = self.llm.generate(prompt, max_tokens=1000)
        return self._parse_todos(result)
```

**上下文窗口处理**：
- ≤3万字：整段送入LLM
- 3-15万字：滑动窗口（最近3万字+关键实体摘要）
- >15万字：先摘要后处理

**成本控制**：
- 单用户每日Token上限500K
- 超限降级为规则引擎（不调用LLM，基于关键词匹配生成基础Todo）

### 4.3 关联发现算法

```python
class AssociationEngine:
    def discover(self, event: Event, entities: List[Entity]) -> List[Association]:
        associations = []
        for entity in entities:
            existing = self._find_related(entity)
            for related in existing:
                score = self._calculate_strength(entity, related, event)
                role_tag = self._infer_role_tag(entity)
                associations.append(Association(
                    source_entity=entity.id,
                    target_entity=related.id,
                    relation_type=self._infer_relation(entity, related),
                    role_tag=role_tag,
                    strength=score,
                    evidence=[event.id]
                ))
        return associations

    def _calculate_strength(self, a, b, event) -> float:
        base = 0.3
        if self._same_company(a, b): base += 0.2
        if self._same_industry(a, b): base += 0.1
        if self._co_occurrence_count(a, b) > 3: base += 0.15
        return min(base, 1.0)

    def _same_city(self, a: Entity, b: Entity) -> bool:
        city_a = self._get_city(a)
        city_b = self._get_city(b)
        if not city_a or not city_b:
            return False
        return self._normalize_city(city_a) == self._normalize_city(city_b)

    def _get_city(self, entity: Entity) -> str:
        props = entity.properties
        return (props.get("contact_info", {}).get("city")
                or props.get("company_city")
                or props.get("residence_city")
                or "")

    def _normalize_city(self, city: str) -> str:
        CITY_ALIASES = {
            "北京市": "北京", "Beijing": "北京", "BJ": "北京",
            "上海市": "上海", "Shanghai": "上海", "SH": "上海",
            "深圳市": "深圳", "Shenzhen": "深圳", "SZ": "深圳",
            "广州市": "广州", "Guangzhou": "广州", "GZ": "广州",
            "杭州市": "杭州", "Hangzhou": "杭州", "HZ": "杭州",
        }
        return CITY_ALIASES.get(city.strip(), city.strip())
```

**主题网络视角（对外沟通语言，v2.4新增）**：

| 内部术语 | 用户理解 | 说明 |
|----------|---------|------|
| Association | 主题互通 | 两个实体间的关系 |
| Topic Tag | 主题 | 跨事件的共同话题 |
| Entity Graph | 主题网络 | 所有人×所有主题的全景图 |
| Co-occurrence | 同场出现 | 同一场会议中出现 |

专业版 Plus 可视化增强：
- D3.js force-directed graph（力导向图）
- 节点 = 人物 + 话题（两种不同颜色/形状）
- 边 = 关系类型（粗细=confidence）
- 点击人物 → 展开其推进卡
- 点击话题 → 列出涉及此话题的所有会议和人物

### 4.4 实体归一5步算法（P0补齐）

```python
from rapidfuzz import fuzz

class EntityResolutionEngine:
    AUTO_MERGE_THRESHOLD = 0.85
    CONFIRM_THRESHOLD = 0.70

    async def resolve(self, new_entity: dict, user_id: str) -> ResolutionResult:
        candidates = await self._find_candidates(new_entity, user_id)

        for step_name, step_fn in [
            ("exact_match", self._step_exact),
            ("alias_match", self._step_alias),
            ("fuzzy_match", self._step_fuzzy),
            ("context_match", self._step_context),
        ]:
            for candidate in candidates:
                confidence, matched_fields = step_fn(new_entity, candidate)
                if confidence >= self.AUTO_MERGE_THRESHOLD:
                    return ResolutionResult(
                        action=ResolutionAction.MERGE,
                        target=candidate,
                        confidence=confidence,
                        matched_step=step_name,
                        matched_fields=matched_fields,
                        explanation=f"{step_name}: 置信度{confidence:.2f}，自动合并",
                    )
                if confidence >= self.CONFIRM_THRESHOLD:
                    return ResolutionResult(
                        action=ResolutionAction.CONFIRM,
                        target=candidate,
                        confidence=confidence,
                        matched_step=step_name,
                        matched_fields=matched_fields,
                        explanation=f"{step_name}: 置信度{confidence:.2f}，需人工确认",
                    )

        return ResolutionResult(
            action=ResolutionAction.CREATE,
            target=None,
            confidence=0.0,
            matched_step="new_entity",
            matched_fields={},
            explanation="无匹配候选，创建新实体",
        )

    def _step_exact(self, new: dict, existing: Entity) -> tuple:
        if new["name"].lower().strip() == existing.name.lower().strip():
            company_match = (new.get("company", "").lower().strip()
                           == (existing.company or "").lower().strip())
            score = 1.0 if company_match else 0.85
            fields = {"name": 1.0, "company": 1.0 if company_match else 0.5}
            return score, fields
        return 0.0, {}

    def _step_alias(self, new: dict, existing: Entity) -> tuple:
        if new["name"].strip() in existing.aliases:
            company_match = new.get("company", "").lower() == (existing.company or "").lower()
            score = 0.95 if company_match else 0.80
            fields = {"name": 0.95, "alias": True, "company": 1.0 if company_match else 0.5}
            return score, fields
        return 0.0, {}

    def _step_fuzzy(self, new: dict, existing: Entity) -> tuple:
        name_sim = fuzz.token_sort_ratio(new["name"], existing.name) / 100
        if name_sim < 0.70:
            return 0.0, {}
        company_sim = fuzz.token_sort_ratio(
            new.get("company", ""), existing.company or ""
        ) / 100
        title_sim = fuzz.token_sort_ratio(
            new.get("title", ""), existing.title or ""
        ) / 100
        score = name_sim * 0.5 + company_sim * 0.3 + title_sim * 0.2
        fields = {"name": name_sim, "company": company_sim, "title": title_sim}
        return min(score, 0.90), fields

    def _step_context(self, new: dict, existing: Entity) -> tuple:
        context_score = 0.0
        fields = {}
        if self._same_company_name(new.get("company"), existing.company):
            context_score += 0.3
            fields["company"] = 1.0
        if self._same_city_name(new.get("city"), existing.city):
            context_score += 0.2
            fields["city"] = 1.0
        if self._overlapping_industries(new, existing):
            context_score += 0.1
            fields["industry"] = 0.8
        return context_score, fields


class ResolutionResult:
    def __init__(self, action, target, confidence, matched_step, matched_fields, explanation):
        self.action = action
        self.target = target
        self.confidence = confidence
        self.matched_step = matched_step
        self.matched_fields = matched_fields
        self.explanation = explanation
```

### 4.5 匹配算法（v2.0：分阶段启用策略）

> **v2.0定位校准**：匹配逻辑从"资源匹配"转为"关系经营"。PoC先做承诺兑现闭环，不启用六维匹配；专业版启用care维度；定制版完整六维匹配。

#### 4.5.1 PoC阶段：承诺兑现闭环（不启用六维匹配）

PoC阶段的核心不是"匹配谁有什么资源"，而是"我答应过谁什么，该兑现了"。

```python
class PromiseFulfillmentEngine:
    """PoC阶段核心引擎：承诺兑现闭环"""

    async def process_interaction(self, event: Event, entities: List[Entity]) -> List[Todo]:
        todos = []

        # Step 1: 关注提取 → care Todo
        concerns = await self._extract_concerns(event, entities)
        for concern in concerns:
            todos.append(Todo(
                todo_type="care",
                title=f"关注：{concern.person.name}正在关心{concern.topic}",
                target_entities=[concern.person.id],
                status="pending",
            ))

        # Step 2: 承诺识别 → promise Todo
        promises = await self._extract_promises(event, entities)
        for promise in promises:
            todos.append(Todo(
                todo_type="promise",
                title=f"兑现承诺：{promise.description}",
                target_entities=[promise.person.id],
                due_date=promise.suggested_deadline,
                status="pending",
            ))

        # Step 3: 帮助建议 → help Todo
        helps = await self._suggest_helps(event, entities)
        for help_item in helps:
            todos.append(Todo(
                todo_type="help",
                title=f"帮助：{help_item.description}",
                target_entities=[help_item.person.id],
                status="pending",
            ))

        # Step 4: 合作信号 → cooperation_signal Todo
        signals = await self._detect_cooperation_signals(event, entities)
        for signal in signals:
            todos.append(Todo(
                todo_type="cooperation_signal",
                title=f"合作信号：{signal.description}",
                target_entities=[signal.person.id],
                status="pending",
            ))

        return todos

    async def _extract_concerns(self, event, entities) -> list:
        """从互动中提取对方关注点，需用户确认"""
        prompt = f"从以下互动记录中提取对方正在关心什么（非用户自己的需求）：\n{event.raw_text}"
        result = await self.llm.generate(prompt, max_tokens=500)
        return self._parse_concerns(result, entities)

    async def _extract_promises(self, event, entities) -> list:
        """从互动中提取用户做出的承诺，需用户确认"""
        prompt = f"从以下互动记录中提取说话人答应对方做的事：\n{event.raw_text}"
        result = await self.llm.generate(prompt, max_tokens=500)
        return self._parse_promises(result, entities)

    async def _suggest_helps(self, event, entities) -> list:
        """基于对方关注点，建议用户可以提供的帮助"""
        helps = []
        for entity in entities:
            concerns = entity.properties.get("concern", [])
            if concerns:
                helps.append(HelpSuggestion(
                    person=entity,
                    description=f"基于{entity.name}的关注点，考虑能否提供帮助",
                ))
        return helps

    async def _detect_cooperation_signals(self, event, entities) -> list:
        """识别对方释放的合作意向（仅标记，不自动撮合）"""
        prompt = f"从以下互动记录中识别对方是否释放了合作意向信号：\n{event.raw_text}"
        result = await self.llm.generate(prompt, max_tokens=300)
        return self._parse_signals(result, entities)
```

#### 4.5.2 专业版：启用care维度（关注点匹配）

专业版在承诺闭环基础上，新增care维度匹配——当两个人的关注点有交集时，提示"值得关心"。

```python
class CareMatchEngine:
    """专业版：关注点匹配引擎"""

    async def find_care_overlap(self, person_a: Entity, person_b: Entity) -> dict:
        concerns_a = set(person_a.properties.get("concern", []))
        concerns_b = set(person_b.properties.get("concern", []))
        overlap = concerns_a & concerns_b

        if not overlap:
            return {"overlap": False, "shared_concerns": []}

        return {
            "overlap": True,
            "shared_concerns": list(overlap),
            "suggestion": f"{person_a.name}和{person_b.name}都关注{', '.join(overlap[:3])}，值得关心",
        }

    async def find_worth_caring(self, user_id: str, days: int = 14) -> list:
        """找出最近值得关心的人：有未兑现承诺或长期未互动"""
        results = []

        # 未兑现的承诺
        pending_promises = await self.db.find_todos(
            user_id=user_id, todo_type="promise", status="pending"
        )
        results.extend([{"entity_id": p.target_entities[0], "reason": f"承诺未兑现：{p.title}"} for p in pending_promises])

        # 长期未互动
        stale_relations = await self.db.find_stale_relations(user_id, days=days)
        results.extend([{"entity_id": r.entity_id, "reason": f"{days}天未联系"} for r in stale_relations])

        return results
```

#### 4.5.3 定制版：完整六维匹配（callability降级为参考维度）

定制版启用完整六维匹配，但callability维度从20%降权为10%（因为利他逻辑下"可调用"不是首要目标），新增care_overlap维度10%。

```python
class OpportunityMatcher:
    WEIGHTS_PHASE2 = {
        "keyword_overlap": 0.20,
        "industry_alignment": 0.15,
        "care_overlap": 0.10,          # v2.0新增：关注点交集
        "topic_similarity": 0.15,
        "llm_semantic": 0.10,
        "history_collaboration": 0.10,
        "callability": 0.10,           # v2.0降权：从20%→10%
        "promise_fulfillment": 0.10,   # v2.0新增：承诺兑现率
    }

    SENSITIVITY_LEVELS = {
        "matchable": True,
        "no_match": False,
    }

    async def calculate_match_score(self, todo: Todo, person: Entity) -> dict:
        if not self._check_sensitivity(person):
            return {"total_score": 0.0, "dimensions": {}, "match_reason": "资源标记为不可匹配", "filtered": True}

        d1 = self._keyword_overlap(todo, person)
        d2 = self._industry_alignment(todo, person)
        d3 = self._care_overlap(todo, person)
        d4 = await self._topic_similarity(todo, person)
        d5 = await self._llm_semantic_judge(todo, person)
        d6 = self._history_collaboration(todo, person)
        d7 = self._callability(todo, person)
        d8 = self._promise_fulfillment(todo, person)

        W = self.WEIGHTS_PHASE2
        total = (
            d1 * W["keyword_overlap"]
            + d2 * W["industry_alignment"]
            + d3 * W["care_overlap"]
            + d4 * W["topic_similarity"]
            + d5 * W["llm_semantic"]
            + d6 * W["history_collaboration"]
            + d7 * W["callability"]
            + d8 * W["promise_fulfillment"]
        )

        return {
            "total_score": total,
            "dimensions": {
                "keyword_overlap": d1,
                "industry_alignment": d2,
                "care_overlap": d3,
                "topic_similarity": d4,
                "llm_semantic": d5,
                "history_collaboration": d6,
                "callability": d7,
                "promise_fulfillment": d8,
            },
            "match_reason": self._generate_reason(d1, d2, d3, d4, d5, d6, d7, d8),
        }

    def _care_overlap(self, todo: Todo, person: Entity) -> float:
        """v2.0新增：关注点交集匹配"""
        todo_concerns = set(getattr(todo, "concerns", []))
        person_concerns = set(person.properties.get("concern", []))
        if not todo_concerns or not person_concerns:
            return 0.0
        intersection = todo_concerns & person_concerns
        return len(intersection) / max(len(todo_concerns), len(person_concerns))

    def _promise_fulfillment(self, todo: Todo, person: Entity) -> float:
        """v2.0新增：承诺兑现率"""
        promises = person.properties.get("promise", [])
        contributions = person.properties.get("contribution", [])
        if not promises:
            return 0.5  # 无承诺记录，中性评分
        return min(1.0, len(contributions) / len(promises))

    def _check_sensitivity(self, person: Entity) -> bool:
        sensitivity = person.properties.get("resource_sensitivity", "matchable")
        return self.SENSITIVITY_LEVELS.get(sensitivity, True)

    def _callability(self, todo: Todo, person: Entity) -> float:
        resources = person.properties.get("resource", [])
        if not resources:
            return 0.0
        demand_keywords = set(getattr(todo, "keywords", []))
        if not demand_keywords:
            return 0.3
        matched = sum(1 for r in resources if set(r.get("tags", [])) & demand_keywords)
        return min(1.0, matched / max(len(resources), 1))

    def _keyword_overlap(self, todo: Todo, person: Entity) -> float:
        todo_kw = set(todo.keywords)
        person_kw = set(person.properties.get("keywords", []))
        if not todo_kw or not person_kw:
            return 0.0
        intersection = todo_kw & person_kw
        union = todo_kw | person_kw
        return len(intersection) / len(union)

    def _industry_alignment(self, todo: Todo, person: Entity) -> float:
        todo_domain = getattr(todo, "domain_l1", None)
        person_industry = person.properties.get("industry")
        if not todo_domain or not person_industry:
            return 0.0
        if todo_domain == person_industry:
            return 1.0
        related = self.config.get("related_industries", {}).get(todo_domain, [])
        return 0.5 if person_industry in related else 0.0

    async def _topic_similarity(self, todo: Todo, person: Entity) -> float:
        todo_vec = getattr(todo, "topic_vector", None)
        person_vec = person.properties.get("topic_vector")
        if todo_vec is None or person_vec is None:
            return 0.0
        return self._cosine_similarity(todo_vec, person_vec)

    async def _llm_semantic_judge(self, todo: Todo, person: Entity) -> float:
        sanitized = self._sanitize_for_llm(todo, person)
        response = await self.llm.generate(
            f"判断商机与人物的匹配度(0-1)：{json.dumps(sanitized, ensure_ascii=False)}",
            max_tokens=10,
        )
        try:
            return max(0.0, min(1.0, float(response.strip())))
        except ValueError:
            return 0.5

    def _history_collaboration(self, todo: Todo, person: Entity) -> float:
        count = self._get_collaboration_count(todo, person)
        if count == 0: return 0.0
        if count == 1: return 0.3
        if count <= 3: return 0.6
        return 1.0

    def _sanitize_for_llm(self, todo: Todo, person: Entity) -> dict:
        return {
            "todo": {"description": todo.description, "keywords": todo.keywords},
            "person": {
                "company": person.company,
                "title": person.title,
                "industry": person.properties.get("industry"),
            },
        }

    def _generate_reason(self, d1, d2, d3, d4, d5, d6, d7, d8) -> str:
        reasons = []
        if d2 >= 0.5: reasons.append("同行业")
        if d1 >= 0.3: reasons.append("关键词相关")
        if d3 >= 0.3: reasons.append("关注点交集")
        if d6 >= 0.3: reasons.append("有过合作")
        if d4 >= 0.5: reasons.append("话题相关")
        if d8 >= 0.5: reasons.append("承诺兑现良好")
        return "·".join(reasons) if reasons else "潜在关联"

    @staticmethod
    def _cosine_similarity(a, b) -> float:
        dot = sum(x * y for x, y in zip(a, b))
        norm_a = sum(x * x for x in a) ** 0.5
        norm_b = sum(x * x for x in b) ** 0.5
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return dot / (norm_a * norm_b)
```

### 4.6 Todo状态机（P0补齐）

```python
from enum import Enum
from datetime import datetime

class TodoStatus(str, Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    DONE = "done"
    DISMISSED = "dismissed"
    SNOOZED = "snoozed"

VALID_TRANSITIONS = {
    "pending": ["in_progress", "dismissed", "snoozed"],
    "in_progress": ["done", "dismissed", "pending"],
    "snoozed": ["pending"],
    "done": [],
    "dismissed": [],
}

class TodoStateMachine:
    async def transition(self, todo: Todo, new_status: str, snoozed_until=None) -> Todo:
        if new_status not in VALID_TRANSITIONS.get(todo.status, []):
            raise InvalidTransitionError(
                f"Cannot transition from {todo.status} to {new_status}"
            )

        old_status = todo.status
        todo.status = new_status
        todo.updated_at = datetime.utcnow()

        if new_status == "snoozed" and snoozed_until:
            await self._schedule_recovery(todo.id, old_status, snoozed_until)

        await self._log_transition(todo, old_status, new_status)
        return todo

    async def _schedule_recovery(self, todo_id: str, original_status: str, until: datetime):
        await self.db.execute("""
            INSERT INTO snooze_schedules (todo_id, original_status, recover_at)
            VALUES (:todo_id, :original_status, :recover_at)
        """, {"todo_id": todo_id, "original_status": original_status, "recover_at": until})

    async def recover_expired_snoozes(self):
        rows = await self.db.fetch_all("""
            SELECT ss.todo_id, ss.original_status
            FROM snooze_schedules ss
            WHERE ss.recover_at <= :now
        """, {"now": datetime.utcnow()})

        for row in rows:
            todo = await self.db.get_todo(row["todo_id"])
            if todo and todo.status == "snoozed":
                todo.status = row["original_status"]
                todo.updated_at = datetime.utcnow()
                await self.db.update(todo)
            await self.db.execute(
                "DELETE FROM snooze_schedules WHERE todo_id = :tid",
                {"tid": row["todo_id"]},
            )
```

**SQL DDL补充**：

```sql
-- Todo状态CHECK约束
ALTER TABLE todos ADD CONSTRAINT todo_status_check
    CHECK (status IN ('pending', 'in_progress', 'done', 'dismissed', 'snoozed'));

-- v2.0: Todo类型CHECK约束（关系视角）
ALTER TABLE todos ADD CONSTRAINT todo_type_check
    CHECK (todo_type IN ('cooperation_signal', 'risk', 'care', 'promise', 'followup', 'help'));

-- v2.3: Todo action_type CHECK约束（Promise双向动作）
ALTER TABLE todos ADD CONSTRAINT todo_action_type_check
    CHECK (action_type IN ('my_promise','their_promise','my_followup','mutual_action','system_reminder','unclear'));

-- Event.raw_text长度限制
ALTER TABLE events ADD CONSTRAINT raw_text_length_check
    CHECK (octet_length(raw_text) <= 512000);

-- snooze_schedule表
CREATE TABLE snooze_schedules (
    todo_id UUID PRIMARY KEY REFERENCES todos(id) ON DELETE CASCADE,
    original_status VARCHAR(15) NOT NULL,
    recover_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX idx_snooze_recover_at ON snooze_schedules(recover_at);
```

### 4.6b RelationshipStage状态机（v2.3新增）

> **核心原则**：关系阶段不可仅由AI自动升级，必须用户确认（RS-01硬编码规则）。

```python
from enum import Enum

class RelationshipStage(str, Enum):
    """关系推进卡7阶段枚举"""
    NEW_CONNECTION = "new_connection"                    # 新认识
    UNDERSTANDING_NEEDS = "understanding_needs"          # 了解需求
    VALUE_RESPONSE = "value_response"                    # 价值回应
    COOPERATION_EXPLORATION = "cooperation_exploration"  # 合作探索
    INTENT_CONFIRMED = "intent_confirmed"                # 意向确认
    EXECUTION = "execution"                              # 执行合作
    REVIEW = "review"                                    # 复盘回顾（终态）

STAGE_TRANSITIONS = {
    # PoC启用的前3阶段
    "new_connection": ["understanding_needs"],
    "understanding_needs": ["value_response", "new_connection"],  # 可退回
    "value_response": ["cooperation_exploration", "understanding_needs"],
    # 后续阶段（PoC不启用但定义完整）
    "cooperation_exploration": ["intent_confirmed", "value_response"],
    "intent_confirmed": ["execution", "cooperation_exploration"],
    "execution": ["review", "intent_confirmed"],
    "review": [],  # 终态，不可转移
}

# RS-01硬编码规则：用户确认强制
def can_auto_advance(stage: str) -> bool:
    """阶段不可仅由AI自动升级，必须用户确认"""
    return False  # 永远返回False，强制用户确认

class RelationshipStageStateMachine:
    """关系阶段状态机"""

    def __init__(self, brief_id: str):
        self.brief_id = brief_id
        self.current_stage = RelationshipStage.NEW_CONNECTION

    def can_transition_to(self, target_stage: RelationshipStage) -> tuple[bool, str]:
        """检查是否可以转移到目标阶段"""
        allowed = STAGE_TRANSITIONS.get(self.current_stage.value, [])
        if target_stage.value in allowed:
            return True, f"允许从 {self.current_stage.value} 转移到 {target_stage.value}"
        return False, f"不允许从 {self.current_stage.value} 转移到 {target_stage.value}"

    def transition(self, target_stage: RelationshipStage, confirmed_by_user: bool = False) -> None:
        """
        执行阶段转移
        - confirmed_by_user=True：用户主动确认，允许转移
        - confirmed_by_user=False：AI建议，需检查can_auto_advance
        """
        if not confirmed_by_user and not can_auto_advance(self.current_stage.value):
            raise ValueError(f"阶段 {self.current_stage.value} 需要用户确认才能升级")

        can, reason = self.can_transition_to(target_stage)
        if not can:
            raise ValueError(reason)

        old_stage = self.current_stage
        self.current_stage = target_stage
        return {
            "brief_id": self.brief_id,
            "old_stage": old_stage.value,
            "new_stage": target_stage.value,
            "confirmed_by_user": confirmed_by_user,
            "transitioned_at": datetime.utcnow().isoformat(),
        }
```

**PATCH /stage 乐观锁实现（v2.4新增，Arch+Coder Review完善）**：

```python
# StageUpdateRequest schema（含version字段）
class StageUpdateRequest(BaseModel):
    stage: str                          # 目标阶段
    reason: Optional[str] = None        # 变更原因
    version: int                        # 乐观锁版本号（客户端读取时携带）

# PATCH /api/v1/persons/{id}/relationship-brief/stage — 乐观锁实现
@patch("/persons/{person_id}/relationship-brief/stage")
async def update_stage(person_id: UUID, req: StageUpdateRequest):
    brief = await brief_service.get_by_person(user_id, person_id)

    # 乐观锁校验
    if brief.version != req.version:
        raise HTTPException(
            status_code=409,
            detail={
                "error": "OPTIMISTIC_LOCK_CONFLICT",
                "message": "关系推进卡已被其他请求更新，请刷新后重试",
                "current_version": brief.version,
            }
        )

    # 更新阶段 + version自增
    updated = await brief_service.update_stage(
        brief_id=brief.id,
        new_stage=req.stage,
        stage_reason=req.reason,
        new_version=brief.version + 1,
    )
    return updated
```

### 4.7 关联强度时间衰减函数（P1补齐）

```python
import math

def time_decay_weight(last_interaction: datetime, lam: float = 0.01) -> float:
    now = datetime.utcnow()
    if last_interaction >= now:
        return 1.0
    days = (now - last_interaction).days
    return math.exp(-lam * days)

ASSOCIATION_TYPE_BASE = {
    "colleague": 0.6,
    "friend": 0.5,
    "business_partner": 0.5,
    "acquaintance": 0.3,
    "same_city": 0.2,
    "same_industry": 0.2,
    "co_occurrence": 0.3,
}

ASSOCIATION_TYPE_DECAY_FLOOR = {
    "colleague": 0.3,
    "friend": 0.25,
    "investor": 0.4,
    "mentor": 0.35,
}

def calculate_association_strength(
    assoc_type: str,
    evidence_count: int,
    last_interaction: datetime,
    frequency: int,
    lam: float = 0.01,
) -> float:
    base = ASSOCIATION_TYPE_BASE.get(assoc_type, 0.3)
    evidence_bonus = min(evidence_count * 0.05, 0.3)
    decay = time_decay_weight(last_interaction, lam)
    floor = ASSOCIATION_TYPE_DECAY_FLOOR.get(assoc_type, 0.1)
    frequency_bonus = min(frequency * 0.02, 0.15)
    raw = (base + evidence_bonus + frequency_bonus) * decay
    return max(raw, floor)
```

### 4.8 PoC存储方案：SQLite

```python
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

def create_db_engine(stage: str = "poc"):
    if stage == "poc":
        db_path = os.environ.get("PROMISELINK_DB_PATH", "promiselink_poc.db")
        db_key = os.environ.get("PROMISELINK_DB_KEY")
        if db_key:
            engine = create_engine(
                f"sqlite+pysqlcipher://:{db_key}@/{db_path}"
            )
        else:
            engine = create_engine(f"sqlite:///{db_path}")
    elif stage == "phase1":
        db_url = os.environ["DATABASE_URL"]
        engine = create_engine(db_url, pool_size=20, max_overflow=10)
    return engine
```

**SQLite兼容性workaround**：

| PG特性 | SQLite替代 | 定制版迁移 |
|--------|-----------|-----------|
| JSONB+GIN | JSON(无索引)+Python内存过滤 | 迁移到JSONB+GIN |
| ENUM | TEXT+CHECK | 迁移到PG ENUM |
| pg_trgm全文搜索 | FTS5虚拟表 | 迁移到pg_trgm |
| pgvector | Python cosine_similarity | 迁移到pgvector |
| RETURNING | SELECT last_insert_rowid() | 无需改 |

> **注意**：个人版长期使用SQLite，上述PG特性仅在定制版（销售团队）中需要迁移。

### 4.9 AI输出语言规则（v2.0新增）

> **核心原则**：PromiseLink是个人商务关系经营助手，AI是辅助工具，不是决策者。AI的输出必须尊重用户对真实关系的掌控权，避免越界推断和冒犯性建议。

#### 4.9.1 AI不应该做的事

| ❌ 禁止行为 | 原因 |
|------------|------|
| 自动判定对方掌握何种资源 | 信息不够且易冒犯——"他有什么资源"应由用户自己判断 |
| 自动建议用户索取资源 | 违背首期利他逻辑——先帮助，后连接 |
| 自动将两个人撮合 | 缺少双方同意——撮合需要双方意愿确认 |
| 自动发送微信或邮件 | 用户必须掌控触达——系统只提醒，不代行 |
| 自动推断人格、禁忌、利益关系 | 错误会伤害真实关系——这类判断只能由人做 |
| 把推测写成确定事实 | 必须区分AI推测与用户确认——未确认的结论标注"待确认" |

#### 4.9.2 AI应该做的事

| ✅ 允许行为 | 要求 |
|------------|------|
| 从一句话识别联系人 | 支持用户修正 |
| 提取对方关注点 | 必须由用户确认后才持久化 |
| 提取用户承诺 | 必须由用户确认后才持久化 |
| 提议提醒时间 | 用户可修改 |
| 生成温和回应建议 | 用户编辑后使用 |
| 基于历史互动提示"值得关心" | 提供依据，不做判断 |
| 识别潜在合作信号 | 只作为提示，不作为事实 |

#### 4.9.3 输出语言规则：正确/错误示例

**❌ 错误示例**（旧版资源视角）：

> 王主任拥有社区资源，建议调用。

问题：①"拥有社区资源"是AI推断，非用户确认 ②"建议调用"是索取逻辑 ③语气确定，无确认空间

**✅ 正确示例**（v2.0关系视角）：

> 王主任此前提到社区长者活动的运营需求。你已答应发送方案，建议先兑现承诺；如果她反馈积极，再进一步了解是否适合开展试点合作。

优点：①基于用户确认的关注点 ②先兑现承诺（利他） ③"如果…再进一步"是条件建议，非确定判断 ④合作是自然结果，非主动撮合

**❌ 错误示例**（自动推断人格）：

> 张总性格强势，不喜欢被催促，建议低频接触。

问题：AI不应推断人格特征，错误判断会伤害真实关系

**✅ 正确示例**（基于观察的行为记录）：

> 张总近3次互动均由你主动发起，回复间隔平均5天。建议考虑合适的联系频率。

优点：①基于事实数据，非人格推断 ②"建议考虑"留有用户判断空间

#### 4.9.4 输出标记规范

AI输出中涉及推断性内容时，必须使用以下标记：

| 标记 | 含义 | 示例 |
|------|------|------|
| `[待确认]` | AI提取但未经用户确认 | "对方关注：社区运营 `[待确认]`" |
| `[AI推测]` | AI基于上下文推断 | "可能适合合作 `[AI推测]`" |
| `[用户确认]` | 已由用户确认的内容 | "对方关注：社区运营 `[用户确认]`" |

**持久化规则**：只有`[用户确认]`标记的内容才能写入Entity.properties或Todo的正式字段。`[待确认]`内容存储在临时确认队列，超时7天自动清除。

### 4.10 洞察引擎设计（v2.6新增）

> **设计背景**：基于与DeepSeek的架构讨论，PromiseLink的智能从"被动记录"升级为"主动服务"。洞察引擎是这一升级的核心模块，负责动态优先级排序和隐式反馈学习。

#### 4.10.1 动态评分器（PriorityScorer）

PoC阶段实现二维简化模型：

```python
class PriorityScorer:
    """
    动态优先级评分器
    PoC: Score = 0.4 × urgency + 0.6 × importance
    专业版: Score = w1×urgency + w2×importance + w3×dependency + w4×context
    """

    WEIGHTS_POC = {"urgency": 0.4, "importance": 0.6}

    async def score(self, todo: Todo, brief: RelationshipBrief | None = None) -> float:
        urgency = self._calc_urgency(todo)
        importance = self._calc_importance(todo, brief)
        return (self.WEIGHTS_POC["urgency"] * urgency
                + self.WEIGHTS_POC["importance"] * importance)

    def _calc_urgency(self, todo: Todo) -> float:
        """紧急性：截止时间指数衰减"""
        if not todo.due_date:
            # 无截止时间：极缓慢衰减，避免被"雪藏"
            days_since_created = (now() - todo.created_at).days
            return max(0.1, 0.5 * math.exp(-0.01 * days_since_created))
        hours_left = max(0, (todo.due_date - now()).total_seconds() / 3600)
        if hours_left <= 0:
            return 1.0  # 已逾期，最高紧急
        return min(1.0, math.exp(-0.05 * hours_left) + 0.1)

    def _calc_importance(self, todo: Todo, brief: RelationshipBrief | None) -> float:
        """重要性：基于关系权重"""
        if brief and brief.brief_data:
            score = brief.brief_data.get("score", 0)
            return min(1.0, score / 100.0)
        return 0.3  # 默认中等偏低
```

专业版扩展维度：

| 维度 | 算法 | 数据来源 | 产品层级 |
|------|------|---------|---------|
| 紧急性 | 截止时间指数衰减 | Todo.due_date | PoC |
| 重要性 | 关系权重+业务价值标签 | Brief.score + 用户标记 | PoC |
| 依赖性 | 全图谱路径分析（阻塞检测+间接依赖） | Association图谱+Todo promise链 | 专业版 |
| 场景匹配 | Event表驱动（未来24h会议关联） | Event(meeting/call)+Entity | 专业版 |

#### 4.10.1a 专业版四维评分器详细设计（v2.7新增）

权重配置演进：
```python
# PoC (v4.5)
WEIGHTS_POC = {"urgency": 0.4, "importance": 0.6, "dependency": 0.0, "context": 0.0}

# 专业版 (v4.6)
WEIGHTS_PHASE1 = {"urgency": 0.3, "importance": 0.35, "dependency": 0.2, "context": 0.15}
```

**维度3：依赖性（dependency）— 全图谱路径分析**

```python
class DependencyAnalyzer:
    """
    依赖性分析器 — 专业版新增
    从Association图谱中提取承诺依赖链，检测阻塞关系
    """

    MAX_DEPTH = 3  # 最大依赖链深度

    async def compute_dependency_score(self, todo: Todo, session) -> float:
        """计算Todo的依赖性得分 (0.0~1.0)"""
        if todo.todo_type not in ("promise", "help"):
            return 0.0  # 只有承诺和帮助类Todo有依赖性

        # Step 1: 构建承诺依赖图
        dep_graph = await self._build_promise_dependency_graph(todo.user_id, session)

        # Step 2: 检测该Todo的阻塞链
        blocking_chains = self._find_blocking_chains(todo, dep_graph)

        if not blocking_chains:
            return 0.0

        # Step 3: 计算依赖性得分
        score = 0.0
        for chain in blocking_chains:
            depth = len(chain)
            blocked_count = self._count_blocked_todos(chain[-1], dep_graph)
            score += (1.0 / depth) * min(1.0, blocked_count * 0.3)

        return min(1.0, score)

    async def _build_promise_dependency_graph(self, user_id: str, session) -> dict:
        """构建承诺依赖图：有向图，边表示"X的完成是Y的前置条件"

        节点: Todo ID
        边: Todo A → Todo B 表示 "A完成后B才能推进"
        """
        # 查询所有pending的promise/help类型Todo
        result = await session.execute(
            select(Todo).where(
                Todo.user_id == user_id,
                Todo.status == "pending",
                Todo.todo_type.in_(["promise", "help"]),
            )
        )
        todos = result.scalars().all()

        # 构建依赖边：如果两个Todo关联同一个Entity，
        # 且一个是my_promise，另一个是their_promise，
        # 则my_promise是their_promise的前置条件
        graph = {}  # {todo_id: [dependent_todo_ids]}
        entity_todos = {}  # {entity_id: [todos]}

        for t in todos:
            if t.related_entity_id:
                entity_todos.setdefault(str(t.related_entity_id), []).append(t)

        for entity_id, entity_todo_list in entity_todos.items():
            my_promises = [t for t in entity_todo_list
                          if t.action_type == "my_promise"]
            their_promises = [t for t in entity_todo_list
                             if t.action_type == "their_promise"]

            # 我的承诺是对方承诺的前置条件
            for mp in my_promises:
                for tp in their_promises:
                    graph.setdefault(str(mp.id), []).append(str(tp.id))

        return graph

    def _find_blocking_chains(self, todo: Todo, graph: dict) -> list[list[str]]:
        """BFS查找从该Todo出发的阻塞链"""
        chains = []
        todo_id = str(todo.id)

        # 如果该Todo被其他Todo依赖，说明有人在等
        visited = set()
        queue = [[todo_id]]

        while queue:
            chain = queue.pop(0)
            current = chain[-1]

            if len(chain) > self.MAX_DEPTH:
                continue

            dependents = graph.get(current, [])
            for dep_id in dependents:
                if dep_id not in visited:
                    visited.add(dep_id)
                    new_chain = chain + [dep_id]
                    chains.append(new_chain)
                    queue.append(new_chain)

        return chains

    def _count_blocked_todos(self, todo_id: str, graph: dict) -> int:
        """计算被该Todo阻塞的Todo数量"""
        count = 0
        visited = set()
        queue = [todo_id]

        while queue:
            current = queue.pop(0)
            for dep_id in graph.get(current, []):
                if dep_id not in visited:
                    visited.add(dep_id)
                    count += 1
                    queue.append(dep_id)

        return count
```

**维度4：场景匹配（context_match）— Event表驱动**

```python
class ContextMatcher:
    """
    场景匹配器 — 专业版新增
    基于Event表中的即将到来的会议/通话，临时提升相关Todo优先级
    """

    CONTEXT_WINDOW_HOURS = 24  # 场景匹配窗口：未来24小时

    async def compute_context_score(self, todo: Todo, session) -> float:
        """计算Todo的场景匹配得分 (0.0~1.0)"""
        if not todo.related_entity_id:
            return 0.0  # 无关联Entity的Todo不参与场景匹配

        # Step 1: 查找未来24h内的meeting/call事件
        now = datetime.now(timezone.utc)
        window_end = now + timedelta(hours=self.CONTEXT_WINDOW_HOURS)

        result = await session.execute(
            select(Event).where(
                Event.user_id == todo.user_id,
                Event.event_type.in_(["meeting", "call"]),
                Event.status == "completed",
                Event.created_at >= now,  # 近期创建的事件
            )
        )
        upcoming_events = result.scalars().all()

        if not upcoming_events:
            return 0.0

        # Step 2: 查找这些事件关联的Entity
        event_ids = [str(e.id) for e in upcoming_events]
        result = await session.execute(
            select(Entity).where(
                Entity.source_event_id.in_(event_ids),
            )
        )
        upcoming_entities = result.scalars().all()
        upcoming_entity_ids = {str(e.id) for e in upcoming_entities}

        # Step 3: 检查Todo关联的Entity是否在即将见面列表中
        if str(todo.related_entity_id) not in upcoming_entity_ids:
            return 0.0

        # Step 4: 计算场景匹配得分
        # 找到最近的匹配事件时间
        min_hours = self.CONTEXT_WINDOW_HOURS
        for event in upcoming_events:
            # 用事件关联的Entity匹配
            entity_ids_for_event = [
                str(e.id) for e in upcoming_entities
                if str(e.source_event_id) == str(event.id)
            ]
            if str(todo.related_entity_id) in entity_ids_for_event:
                hours_until = max(0, (event.created_at - now).total_seconds() / 3600)
                min_hours = min(min_hours, hours_until)

        # 线性衰减：越近得分越高
        context_score = max(0.0, 1.0 - min_hours / self.CONTEXT_WINDOW_HOURS)
        return round(context_score, 4)
```

**四维评分器整合**

```python
class PriorityScorerV2(PriorityScorer):
    """专业版四维评分器 — 继承PoC二维评分器，扩展依赖性和场景匹配"""

    WEIGHTS = {"urgency": 0.3, "importance": 0.35, "dependency": 0.2, "context": 0.15}

    def __init__(self):
        super().__init__()
        self.dependency_analyzer = DependencyAnalyzer()
        self.context_matcher = ContextMatcher()

    async def score_with_context(
        self, todo: Todo, session, brief=None
    ) -> PriorityScore:
        """四维评分（需要session用于图谱查询）"""
        urgency = self._calc_urgency(todo.due_date, datetime.now(timezone.utc))
        importance = self._calc_importance(todo.todo_type)
        dependency = await self.dependency_analyzer.compute_dependency_score(todo, session)
        context = await self.context_matcher.compute_context_score(todo, session)

        score = (
            self.WEIGHTS["urgency"] * urgency
            + self.WEIGHTS["importance"] * importance
            + self.WEIGHTS["dependency"] * dependency
            + self.WEIGHTS["context"] * context
        )

        return PriorityScore(
            score=round(min(1.0, max(0.0, score)), 4),
            urgency=round(urgency, 4),
            importance=round(importance, 4),
            breakdown={
                "urgency_raw": urgency,
                "importance_raw": importance,
                "dependency_raw": dependency,
                "context_raw": context,
                "weights": self.WEIGHTS,
            },
        )
```

#### 4.10.2 隐式反馈收集器（ImplicitFeedbackCollector）

PoC阶段实现：零额外交互，通过观察完成顺序学习。

```python
class ImplicitFeedbackCollector:
    """
    隐式反馈收集器
    原理：用户完成Todo的顺序 = 真实优先级信号
    """

    async def on_todo_completed(self, todo: Todo, completed_rank: int):
        """Todo完成时调用，记录完成序号"""
        todo.completed_rank = completed_rank
        await self._update_person_weight(todo)

    async def _update_person_weight(self, todo: Todo):
        """根据完成顺序调整关系权重"""
        # 获取该Todo关联的Person
        person = await self._get_target_person(todo)
        if not person:
            return

        # 完成序号越靠前，权重提升越大
        if todo.completed_rank and todo.completed_rank <= 3:
            boost = 0.05  # 前3名完成，显著提权
        elif todo.completed_rank and todo.completed_rank <= 10:
            boost = 0.02  # 前10名完成，轻微提权
        else:
            boost = 0.0   # 后续完成，不调整

        if boost > 0:
            await self._adjust_brief_score(person, boost)

    async def daily_rebalance(self):
        """每日重平衡：根据全天的完成顺序重新计算权重"""
        # 获取今日所有完成的Todo，按completed_rank排序
        # 如果某人的Todo总是被提前完成，提升该人的关系权重
        # 如果某人的Todo总是被延后完成，降低该人的关系权重
        pass
```

专业版扩展：长按Todo → "以后少提醒"按钮（负反馈信号）

#### 4.10.3 Todo模型扩展

```python
# Todo模型新增字段
class Todo:
    # ... existing fields ...
    completed_rank: int | None = None  # 完成序号（v2.6新增，隐式反馈用）
    dynamic_score: float | None = None  # 动态优先级分（v2.6新增，排序用）
    score_calculated_at: datetime | None = None  # 评分时间（v2.6新增）
```

API变更：
- `GET /api/v1/todos?sort=smart` — 按动态评分排序（默认）
- `GET /api/v1/todos?sort=due_date` — 按截止时间排序
- `POST /api/v1/todos/{id}/complete` — 完成时自动记录completed_rank

### 4.11 数据接入层设计（v2.6新增）

> **设计背景**：Pipeline是source-agnostic的，数据接入层负责将不同数据源转换为统一的Event格式。所有adapter的输出都是`Event(event_type, raw_text, source)`，Pipeline零改动。

#### 4.11.1 DataSourceAdapter接口

```python
from abc import ABC, abstractmethod

class DataSourceAdapter(ABC):
    """数据源适配器接口"""

    @abstractmethod
    async def fetch_new_events(self, user_id: str, since: datetime) -> list[EventCreate]:
        """拉取新事件"""
        ...

    @abstractmethod
    async def authenticate(self, user_id: str, credentials: dict) -> bool:
        """认证数据源"""
        ...

class ManualInputAdapter(DataSourceAdapter):
    """手动输入（已有）"""
    async def fetch_new_events(self, user_id, since):
        return []  # 手动输入通过API直接创建

class VoiceAdapter(DataSourceAdapter):
    """语音输入（已有，F-50 NLU）"""
    async def fetch_new_events(self, user_id, since):
        return []  # 语音输入通过Voice API直接创建

class EmailAdapter(DataSourceAdapter):
    """邮件解析（专业版）

    设计原则：原子事件+溯源边
    - 邮件原文作为完整Event存储（raw_text归档）
    - 承诺/待办拆解为原子化Todo（source_event_id链回原始邮件）
    - 一封邮件一个Event，Todo的action_type区分方向
    """
    async def fetch_new_events(self, user_id, since):
        # 专业版: IMAP/Exchange API → Event
        # 需要OAuth授权
        ...

class CalendarAdapter(DataSourceAdapter):
    """日历同步（定制版）"""
    async def fetch_new_events(self, user_id, since):
        # 定制版: CalDAV/Exchange → Event
        ...
```

#### 4.11.2 邮件场景数据流

```
原始邮件（3个承诺埋在长文中）
    │
    ▼
EmailAdapter → Event(raw_text=邮件全文, source="email:imap:msg_123")
    │
    ▼ Pipeline处理（零改动）
    │
    ├── Todo #1: "给张总发产品报价" (source_event_id → Event, action_type=my_promise)
    ├── Todo #2: "确认下周三会议时间" (source_event_id → Event, action_type=my_promise)
    └── Todo #3: "回复李总的技术方案" (source_event_id → Event, action_type=their_promise)
    │
    ▼ 关联发现（零改动）
    │
    └── Association: 张总 ↔ 李总 [topic_overlap: 产品报价]
```

#### 4.11.3 微信生态约束

| 方案 | 可行性 | 阶段 |
|------|--------|------|
| 小程序内交互 | ✅ 已实现 | PoC |
| 企业微信API | ✅ 需企业微信环境 | 专业版 |
| 用户转发到小程序 | ✅ 长按转发 | 专业版 |
| 个人微信消息API | ❌ 不开放 | 不规划 |

PoC阶段聚焦降低输入摩擦，语音输入（F-50）是最低摩擦方式。

### 4.12 向量化语义引擎设计（v2.8新增）

> **设计背景**：对应PRD v4.7 §1.7.7向量化语义能力，实现F-57语义搜索和F-58关联发现增强。结构化匹配无法发现语义相似但字面不同的关联，向量化能力让系统理解"意思相近"而非仅"字面相同"。

#### 4.12.1 EmbeddingProvider

通过Moka AI API调用text-embedding-3-small模型，完全兼容OpenAI SDK，只需替换base_url和api_key。

- 批量embedding接口（最多2048条/批）
- 缓存策略：相同文本不重复调用API

```python
from openai import AsyncOpenAI

class EmbeddingProvider:
    def __init__(self):
        self.client = AsyncOpenAI(
            base_url="https://api.moka-ai.com/v1",
            api_key=settings.moka_api_key,
        )
        self.model = "text-embedding-3-small"
        self._cache = {}  # text -> embedding

    async def embed(self, text: str) -> list[float]:
        if text in self._cache:
            return self._cache[text]
        response = await self.client.embeddings.create(
            model=self.model, input=text
        )
        embedding = response.data[0].embedding
        self._cache[text] = embedding
        return embedding

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        # Check cache first
        uncached = [(i, t) for i, t in enumerate(texts) if t not in self._cache]
        if uncached:
            response = await self.client.embeddings.create(
                model=self.model, input=[t for _, t in uncached]
            )
            for (orig_idx, text), data in zip(uncached, response.data):
                self._cache[text] = data.embedding
        return [self._cache[t] for t in texts]
```

#### 4.12.2 SemanticSearchEngine

语义搜索引擎，支持自然语言查询Entity和Event。

- 语义搜索接口：`search(query, user_id, top_k)` → `list[SearchResult]`
- 搜索范围：Entity + Event
- 相似度计算：余弦相似度（sqlite-vec内置）

```python
from dataclasses import dataclass

@dataclass
class SearchResult:
    target_type: str   # "entity" | "event"
    target_id: str
    score: float       # cosine similarity
    metadata: dict     # 实体/事件的摘要信息

class SemanticSearchEngine:
    def __init__(self, provider: EmbeddingProvider, db_path: str):
        self.provider = provider
        self.db_path = db_path

    async def search(self, query: str, user_id: str, top_k: int = 10) -> list[SearchResult]:
        query_embedding = await self.provider.embed(query)
        # sqlite-vec vector search
        results = await self._vector_search(query_embedding, user_id, top_k)
        return results

    async def index_entity(self, entity_id: str, text: str, user_id: str):
        embedding = await self.provider.embed(text)
        await self._store_embedding("entity", entity_id, embedding, user_id)

    async def index_event(self, event_id: str, text: str, user_id: str):
        embedding = await self.provider.embed(text)
        await self._store_embedding("event", event_id, embedding, user_id)
```

#### 4.12.3 sqlite-vec存储设计

与PoC部署模型一致，零额外依赖。定制版迁移至PostgreSQL时切换为pgvector。

**向量表（常规表）**：

```sql
CREATE TABLE vector_embeddings (
    id TEXT PRIMARY KEY,
    target_type TEXT NOT NULL,  -- "entity" | "event"
    target_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    embedding BLOB NOT NULL,    -- API模式768维/本地降级384维float32序列化
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX idx_vector_user_type ON vector_embeddings(user_id, target_type);
```

**sqlite-vec虚拟表（向量检索）**：

```sql
CREATE VIRTUAL TABLE vec_entities USING vec0(
    embedding float[384],  -- PoC使用本地模型384维
    entity_id TEXT
);
```

**迁移路径**：定制版 → pgvector时，BLOB → `vector(768)` 列类型（PoC本地模式为384维BLOB），SQL查询语法从sqlite-vec函数替换为pgvector的 `<=>` 操作符。

#### 4.12.4 关联发现增强（F-58）

在`AssociationDiscoveryEngine._discover_supply_demand`中增加语义相似度，补充结构化匹配的不足。

- 当结构化匹配得分为0时，用embedding余弦相似度补充
- 语义匹配阈值：`cosine_similarity > 0.7` 才计入
- 混合得分公式：`final_score = 0.7 × structured_score + 0.3 × semantic_score`

```python
# 在 AssociationDiscoveryEngine 中增强
async def _discover_supply_demand(self, entity_a, entity_b, user_id):
    # 1. 结构化匹配（已有逻辑）
    structured_score = self._calc_structured_match(entity_a, entity_b)

    # 2. 语义相似度补充
    semantic_score = 0.0
    if structured_score < 0.3:  # 结构化匹配不足时启用语义补充
        text_a = self._build_entity_text(entity_a)
        text_b = self._build_entity_text(entity_b)
        emb_a = await self.embedding_provider.embed(text_a)
        emb_b = await self.embedding_provider.embed(text_b)
        cosine_sim = self._cosine_similarity(emb_a, emb_b)
        if cosine_sim > 0.7:  # 语义匹配阈值
            semantic_score = cosine_sim

    # 3. 混合得分
    final_score = 0.7 * structured_score + 0.3 * semantic_score
    return final_score
```

#### 4.12.5 Pipeline集成点

在现有Pipeline中嵌入向量化处理：

**Step 5.5（新增）：Entity extraction后自动生成embedding并存储**

```
Step 5: Entity extraction
    ↓
Step 5.5 (新增): Embedding generation
    - 对每个提取的Entity，组合concern+capability+basic信息
    - 调用EmbeddingProvider.embed()生成向量
    - 存储到vector_embeddings表和vec_entities虚拟表
    ↓
Step 6: Association discovery
```

**Step 11.5（新增）：Association discovery中使用语义相似度增强**

```
Step 11: Association discovery
    ↓
Step 11.5 (新增): Semantic similarity enhancement
    - 在_discover_supply_demand中调用语义相似度
    - 结构化匹配不足时启用embedding余弦相似度补充
    - 混合得分：0.7 × structured + 0.3 × semantic
    ↓
Step 12: Todo generation
```

### 4.13 F-67 RelationshipBrief关系推进卡前端对接（v3.0新增）

后端已完成RelationshipBrief全链路实现，本节记录前端对接所需的修复与对齐工作。

**后端已实现**：
- RelationshipBrief模型12模块（关系阶段、互动统计、关注事项、承诺追踪等）
- 聚合API：`GET /persons/{id}/relationship-brief`
- Pipeline step_12：Event处理完成后自动更新RelationshipBrief

**前端需修复**：

1. **API路径修正**：
   - ❌ 当前：`/relationship_briefs/${id}`
   - ✅ 正确：`/persons/${id}/relationship-brief`

2. **类型定义对齐**：
   - ❌ 当前：`concern: { tag: string; detail: string }`
   - ✅ 正确：`concern: { category: string; detail: string }`

3. **去除Mock回退**：前端代码中存在Mock数据兜底逻辑，需移除，确保使用真实API响应

**数据流**：

```
Event录入
    ↓
Pipeline step_12
    ↓
RelationshipBrief更新（12模块全量计算）
    ↓
聚合API GET /persons/{id}/relationship-brief
    ↓
前端展示
```

**无新增后端模块**，纯前端对接修复。

### 4.14 F-68 Promise兑现状态追踪（v3.0新增）

#### 4.14.1 数据模型扩展

Todo表新增字段：

```sql
ALTER TABLE todos ADD COLUMN fulfillment_status VARCHAR(15) NOT NULL DEFAULT 'pending'
    CHECK (fulfillment_status IN ('pending', 'fulfilled', 'overdue', 'expired'));
ALTER TABLE todos ADD COLUMN fulfilled_at TIMESTAMP;
ALTER TABLE todos ADD COLUMN overdue_notified_at TIMESTAMP;
```

**fulfillment_status与Todo.status正交设计**：
- `status`：任务执行状态（pending/in_progress/completed/cancelled/snoozed）
- `fulfillment_status`：承诺兑现语义（pending/fulfilled/overdue/expired）
- 两者独立变化：一个completed的Todo，其fulfillment_status可以是fulfilled或expired

#### 4.14.2 Pipeline变更

**step_05_promise扩展**：
- 新增due_date提取逻辑（从互动内容中识别承诺截止日期）
- 新增fulfillment_status初始化（默认pending）

**step_08_notification扩展**：
- 新增`promise_due_reminder`类型：承诺即将到期提醒
- 新增`overdue_alert`类型：承诺已逾期提醒

#### 4.14.3 安全约束

- **my_promise**（我给别人的承诺）：系统可自动标记overdue（基于due_date判断）
- **their_promise**（别人给我的承诺）：必须用户手动标记（避免误判对方失信）
- 任何fulfillment_status变更均记录操作日志

#### 4.14.4 新增模块

| 模块 | 职责 |
|------|------|
| PromiseBoardService | 承诺看板双视图（my_promise/their_promise），支持按fulfillment_status筛选 |
| FulfillmentTracker | 兑现状态追踪，定时扫描due_date并更新fulfillment_status |

**明确不实现**：关系信用分（定制版再评估）

### 4.15 F-69 智能跟进提醒（v3.0新增）

#### 4.15.1 数据模型

**reminder_preferences表**：

```sql
CREATE TABLE reminder_preferences (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL,
    daily_limit INTEGER NOT NULL DEFAULT 5,         -- 每日提醒上限
    silent_start TIME NOT NULL DEFAULT '22:00',     -- 静默时段开始
    silent_end TIME NOT NULL DEFAULT '08:00',       -- 静默时段结束
    enabled_types TEXT NOT NULL DEFAULT 'promise_due,followup,stage_suggestion,dormant_contact',  -- 启用的提醒类型
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(user_id)
);
```

**reminder_logs表**：

```sql
CREATE TABLE reminder_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL,
    reminder_type VARCHAR(30) NOT NULL,              -- promise_due/followup/stage_suggestion/dormant_contact
    target_entity_id INTEGER,                        -- 关联的Entity
    target_todo_id INTEGER,                          -- 关联的Todo
    content TEXT NOT NULL,                           -- 提醒内容
    sent_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    user_action VARCHAR(20),                         -- dismissed/acted/snoozed
    FOREIGN KEY (target_entity_id) REFERENCES entities(id),
    FOREIGN KEY (target_todo_id) REFERENCES todos(id)
);
```

#### 4.15.2 核心算法

**提醒时机计算**：

```
提醒时机 = f(承诺到期, 关系阶段, 互动间隔, 优先级评分)
```

- 承诺到期：due_date临近时触发promise_due提醒
- 关系阶段：stage变化时触发stage_suggestion提醒
- 互动间隔：长时间无互动触发dormant_contact提醒
- 优先级评分：综合多维度计算提醒优先级，高优先级优先发送

#### 4.15.3 疲劳度控制

- 默认每日上限：≤5条/日
- 静默时段：22:00-08:00（不发送提醒，次日08:00后补发）
- 用户可自定义daily_limit和静默时段
- FatigueController在发送前检查当日已发送数量和当前时段

#### 4.15.4 调度架构

采用APScheduler后台定时任务（PoC轻量方案）：

```python
from apscheduler.schedulers.background import BackgroundScheduler

scheduler = BackgroundScheduler()

# 每日08:00执行提醒扫描
scheduler.add_job(reminder_engine.scan_and_send, 'cron', hour=8, minute=0)

# 每小时检查承诺到期
scheduler.add_job(reminder_engine.check_promise_due, 'interval', hours=1)

# 每日检查沉寂联系人
scheduler.add_job(reminder_engine.check_dormant_contacts, 'cron', hour=9, minute=0)
```

定制版迁移至Celery+Redis分布式任务队列。

#### 4.15.5 提醒类型

| 类型 | 触发条件 | 示例 |
|------|----------|------|
| promise_due | 承诺due_date临近（默认提前1天） | "你答应张总周五前发方案，明天就到期了" |
| followup | 互动后N天未跟进（默认3天） | "3天前和李总聊过合作，是否需要跟进？" |
| stage_suggestion | 关系阶段可推进时 | "与王总的关系已到acquaintance，建议主动邀约推进" |
| dormant_contact | 长时间无互动（默认30天） | "已30天未与赵总联系，关系可能冷却" |

#### 4.15.6 新增模块

| 模块 | 职责 |
|------|------|
| ReminderEngine | 提醒引擎，扫描触发条件并生成提醒 |
| FatigueController | 疲劳度控制器，控制每日提醒数量和静默时段 |

### 5.1 协议接口

```python
from typing import Protocol, runtime_checkable, List, Dict, Optional

@runtime_checkable
class MemoryProvider(Protocol):
    def check_health(self) -> tuple: ...
    def recall_preferences(self, user_id: str) -> Dict: ...
    def match_rules(self, user_id: str, context: str) -> List[str]: ...
    def declare_memory(self, user_id: str, memory: Dict) -> bool: ...
    def update_rule(self, user_id: str, rule_id: str, action: str) -> bool: ...

class CarryMemMemoryProvider:
    def __init__(self, carrymem_instance=None):
        self._cm = carrymem_instance

    def check_health(self) -> tuple:
        if not self._cm:
            return ("disabled", None)
        try:
            self._cm.recall_memories(query="health_check", limit=1)
            return ("available", None)
        except Exception as e:
            return ("error", str(e))

    def recall_preferences(self, user_id: str) -> Dict:
        if self.check_health()[0] != "available":
            return {}
        try:
            result = self._cm.recall_memories(
                query=f"type:user_preference",
                limit=10
            )
            return {r['content']: r.get('confidence', 0.5) for r in result}
        except Exception:
            return {}

    def match_rules(self, user_id: str, context: str) -> List[str]:
        if self.check_health()[0] != "available":
            return []
        try:
            result = self._cm.match_rules(
                task_description=context,
                user_id=user_id
            )
            return [r.get('action', '') for r in result]
        except Exception:
            return []

    def declare_memory(self, user_id: str, memory: Dict) -> bool:
        if self.check_health()[0] != "available":
            return False
        try:
            self._cm.declare(user_id=user_id, content=memory)
            return True
        except Exception:
            return False

    def update_rule(self, user_id: str, rule_id: str, action: str) -> bool:
        if self.check_health()[0] != "available":
            return False
        try:
            self._cm.add_rule(user_id=user_id, rule_id=rule_id, action=action)
            return True
        except Exception:
            return False

class NullMemoryProvider:
    def check_health(self) -> tuple:
        return ("disabled", None)
    def recall_preferences(self, user_id: str) -> Dict:
        return {}
    def match_rules(self, user_id: str, context: str) -> List[str]:
        return []
    def declare_memory(self, user_id: str, memory: Dict) -> bool:
        return False
    def update_rule(self, user_id: str, rule_id: str, action: str) -> bool:
        return False
```

### 5.2 使用方式

```python
class PromiseLinkApp:
    def __init__(self, memory_provider: MemoryProvider = None):
        self.memory = memory_provider or NullMemoryProvider()

    def process_event(self, event: Event):
        entities = self.extract_entities(event)
        if self.memory.check_health()[0] == "available":
            prefs = self.memory.recall_preferences(event.user_id)
            entities = self._apply_preferences(entities, prefs)
        todos = self.generate_todos(event, entities)
        return entities, todos
```

**关键**：PromiseLink的所有核心功能在`NullMemoryProvider`下依然可用，CarryMem只是增强。

#### 5.2a CarryMem "终身"能力技术路径（v2.4新增）

**当前状态（PoC）**：
- NullMemoryProvider（空实现，无持久化）
- FileMemoryProvider（本地文件，单机）

**专业版目标**：
- 基础偏好记忆（用户确认的stage变更、手动标记的重要人物）
- 规则记忆（用户自定义的分类规则、忽略列表）

**定制版完整集成**：
- 7种记忆类型全部启用
- 自动晋升机制（5种来源 → tier升级）
- 数据生命周期治理（遗忘曲线：7d/30d/60d/90d衰减）
- 跨设备同步（可选）

**数据导出（提前到专业版）**：
```
GET /api/v1/data/export?format=json|csv
```
- 包含：entities + events + todos + relationship_briefs
- PII字段自动脱敏
- 支持 GDPR 式"数据携带权"

---

## 6. 配置化设计

### 6.1 分类法配置

```yaml
# config/taxonomy/default.yaml
person_profile:
  dimensions:
    - name: basic
      fields: [company, title, city, industry, seniority]
      phase: 1
    - name: communication
      fields: [preferred_channel, response_speed]
      phase: 1
    - name: decision
      fields: [power, style]
      phase: 1
      enums:
        power: [final_decision_maker, core_influencer, process_executor, information_gatekeeper]
        style: [data_driven, relationship_trust, authority_directive, risk_averse, intuitive_innovative]
    - name: resources
      fields: [personal_resources, organizational_resources]
      phase: 1
    - name: relationship
      fields: [strength, maintenance_frequency, next_hook]
      phase: 1
      enums:
        strength: [card_only, wechat_interact, met_alone, trust_endorsed, interest_alliance, shared_hardship]
        maintenance_frequency: [weekly, monthly, quarterly, project_based]
    - name: boundaries
      fields: [taboo_topics, sensitive_info]
      phase: 2
    - name: career
      fields: [peak_moments, background]
      phase: 2

role_classification:
  layers: [GOVERNANCE, PROFESSIONAL, MARKET, SERVICE]
  roles:
    GOVERNANCE: [shareholder, investor, strategic_partner]
    PROFESSIONAL: [expert, committee_member, staff, special_force]
    MARKET: [grid_leader, city_partner, venture_partner, media_expert]
    SERVICE: [service_provider, fan, customer, member, partner]
  levels: [1, 2, 3]
  auto_recommend_rules:
    - condition: "title contains 总监/VP/CXO and company_type = investment"
      recommend: {layer: GOVERNANCE, role: investor, confidence: high}
    - condition: "title contains 专家/首席"
      recommend: {layer: PROFESSIONAL, role: expert, confidence: medium}
    - condition: "default"
      recommend: {layer: SERVICE, role: customer, confidence: low}

meeting_types:
  - id: project_kickoff
    output: [A, D]
  - id: weekly_sync
    output: [A]
  - id: retrospective
    output: [C, A]
  - id: decision_making
    output: [B, A]
  - id: brainstorming
    output: [D, A]
  - id: one_on_one
    output: [A, C]
  - id: info_sync
    output: [A]
  - id: expert_review
    output: [B, D]
  - id: partner_recruitment
    output: [B, D]
  - id: grid_meeting
    output: [B, A]
  - id: product_demo
    output: [B]
```

### 6.2 行业定制

```yaml
# config/taxonomy/manufacturing.yaml  (制造业定制)
role_classification:
  roles:
    MARKET: [grid_leader, city_partner, venture_partner, media_expert, factory_owner]
    # 新增 factory_owner 角色
```

---

## 7. API设计

### 7.1 核心端点

```
POST   /api/v1/events              # 提交事件
GET    /api/v1/events/{id}          # 查看事件详情

GET    /api/v1/entities             # 搜索实体
GET    /api/v1/entities/{id}        # 实体详情（含画像）
PATCH  /api/v1/entities/{id}        # 修正实体信息

GET    /api/v1/associations         # 查询关联
GET    /api/v1/entities/{id}/graph  # 实体关联图谱

GET    /api/v1/todos                # Todo列表
PATCH  /api/v1/todos/{id}           # 更新Todo状态
POST   /api/v1/todos/{id}/feedback  # Todo反馈闭环

GET    /api/v1/digest/morning       # 早间简报
GET    /api/v1/digest/evening       # 晚间汇总

# v2.3 P0 新增API
POST   /api/v1/events              # body新增可选 input_scope 字段（覆盖自动分类）
GET    /api/v1/persons/{id}/relationship-brief   # 获取关系推进卡
PATCH  /api/v1/persons/{id}/relationship-brief/stage  # 用户确认阶段变更
GET    /api/v1/dashboard/today      # 今日Dashboard（需要回应的连接）
GET    /api/v1/todos?view=my-responses  # 我的待回应任务（含等待对方回应视图）
POST   /api/v1/contributions        # 记录已提供的帮助/回应
POST   /api/v1/feedbacks             # 记录反馈与下一步
```

#### 7.2 日视图API（F-49, 专业版，v2.4新增）

```
GET /api/v1/dashboard/day-view?date=YYYY-MM-DD

Response:
{
  "date": "2026-06-04",
  "meeting_groups": [
    {
      "event_id": "uuid",
      "title": "供应链优化方案讨论",
      "time": "09:00-10:30",
      "participants": [
        {"entity_id": "uuid", "name": "张总", "avatar": null}
      ],
      "todo_count": 2,
      "key_topics": ["供应链", "成本优化"]
    },
    ...
  ],
  "total_meetings": 4,
  "total_pending_todos": 7
}
```

实现方式：
- events 表按 `user_id + date(timestamp)` GROUP BY
- 每个 event 关联 entities（通过 event_entities 中间表或 properties）
- 每个 event 关联 todos（通过 event_id 外键）
- 关键词从 `event.title` + LLM抽取的 topics 中获取
- 复用现有 PaginatedResponse 格式

### 7.1b 小程序专用API

```
GET    /api/v1/mini/today            # 今天要见的人（日历+近期事件关联）
GET    /api/v1/mini/person/{id}      # 人物速览（简介+关系+交流要点+TTS音频URL）
GET    /api/v1/mini/person/{id}/tts  # 人物简介语音播报（返回audio stream）
POST   /api/v1/mini/voice-input      # 语音录入（接收audio→ASR→事件处理）
```

**小程序today接口响应示例**：

```json
GET /api/v1/mini/today

{
  "date": "2026-06-02",
  "meetings": [
    {
      "time": "14:00",
      "title": "与张总讨论智慧园区项目",
      "person": {
        "id": "ent_xyz789",
        "name": "张总",
        "company": "XX科技",
        "title": "供应链总监",
        "relation_strength": "met_alone",
        "preferred_channel": "phone",
        "last_contact_summary": "聊了新项目预算",
        "tts_url": "/api/v1/mini/person/ent_xyz789/tts"
      }
    }
  ],
  "pending_todos": [
    {
      "id": "todo_def456",
      "title": "约张总饭局细聊",
      "due_date": "2026-06-09",
      "target_entity_name": "张总"
    }
  ],
  "maintenance_reminders": [
    {
      "entity_name": "李总",
      "reason": "2周未联系",
      "suggested_action": "发微信问候"
    }
  ]
}
```

### 7.1c TTS语音播报

```python
class TTSService:
    def __init__(self):
        self.provider = None  # 可配置：微信同声传译 / 讯飞 / Azure

    async def generate_person_brief(self, entity: Entity) -> bytes:
        text = self._compose_brief(entity)
        audio = await self.provider.synthesize(text)
        return audio

    def _compose_brief(self, entity: Entity) -> str:
        props = entity.properties
        parts = [
            f"{entity.name}，{props.get('company', '')}{props.get('title', '')}。",
            f"关系阶段：{props.get('relationship', {}).get('strength', '未知')}。",
        ]
        if props.get('communication', {}).get('preferred_channel'):
            parts.append(f"偏好{props['communication']['preferred_channel']}沟通。")
        if props.get('relationship', {}).get('next_hook'):
            parts.append(f"下次建议：{props['relationship']['next_hook']}。")
        return "".join(parts)
```

**TTS选型**：

| 方案 | 优点 | 缺点 | 产品层级 |
|------|------|------|---------|
| 微信同声传译插件 | 小程序原生支持，免费 | 音质一般 | 专业版 |
| 讯飞语音合成 | 音质好，中文优化 | 商业授权 | 定制版 |
| Azure TTS | 多语言，音质最佳 | 成本高 | 定制版 |

#### 7.1c-plus 语音交互技术方案（v2.4新增）

**ASR（语音转文字）**：

- **方案A（推荐）**：微信小程序原生 `<voice>` 组件 + 微信同声传译插件
  - 优点：免费、无需自建服务、微信生态原生
  - 缺点：依赖微信平台
- **方案B**：OpenAI Whisper local（本地模型）
  - 优点：隐私友好、离线可用
  - 缺点：模型较大(~150MB)、手机性能要求高

**TTS（文字转语音）**：

- **方案A（推荐）**：微信小程序原生 `<audio>` + 预合成音频
  - 推进卡内容预合成为MP3，小程序播放
  - 优点：简单可控、离线可用
- **方案B**：Edge-TTS / Azure TTS
  - 优点：自然度高、多音色
  - 缺点：需要网络、有API费用

**PoC Mock验证（Sprint 3, 0.5天）**：
```
POST /api/v1/tts/mock → 返回固定文本的TTS音频URL
```
- 验证数据流：Todo文本 → TTS服务 → 音频URL → 小程序播放
- 不依赖真实TTS服务，仅验证链路通畅

### 7.2 事件提交示例

```json
POST /api/v1/events
{
  "event_type": "meeting",
  "source": "manual",
  "title": "与张总讨论智慧园区项目",
  "timestamp": "2026-06-02T14:00:00+08:00",
  "raw_text": "今天和张总聊了新项目预算，他提到华南区有3个代工厂可以对接，下周约饭局细聊",
  "metadata": {
    "meeting_type": "decision_making",
    "duration_minutes": 45
  }
}
```

**响应**：

```json
{
  "event_id": "evt_abc123",
  "entities_extracted": [
    {
      "id": "ent_xyz789",
      "name": "张总",
      "entity_type": "person",
      "properties": {
        "company": "XX科技",
        "title": "供应链总监",
        "industry": "工业互联网",
        "decision": {"power": "final_decision_maker"},
        "concern": ["华南区代工厂对接"],
        "promise": ["下周约饭局细聊"],
        "contribution": [],
        "relationship": {
          "strength": "met_alone",
          "next_hook": "下周约饭局细聊"
        }
      },
      "confidence": 0.85
    }
  ],
  "todos_generated": [
    {
      "id": "todo_def456",
      "todo_type": "promise",
      "title": "兑现承诺：约张总饭局细聊智慧园区项目",
      "source_event": "evt_abc123",
      "target_entities": ["ent_xyz789"],
      "target_association": "assoc_001",
      "due_date": "2026-06-09",
      "status": "pending"
    },
    {
      "id": "todo_ghi789",
      "todo_type": "care",
      "title": "关注：张总正在关心华南区代工厂对接",
      "source_event": "evt_abc123",
      "target_entities": ["ent_xyz789"],
      "due_date": null,
      "status": "pending"
    },
    {
      "id": "todo_jkl012",
      "todo_type": "cooperation_signal",
      "title": "合作信号：张总提到3个代工厂可对接",
      "source_event": "evt_abc123",
      "target_entities": ["ent_xyz789"],
      "due_date": null,
      "status": "pending"
    }
  ]
}
```

---

## 8. 技术选型

| 组件 | 选型 | 理由 |
|------|------|------|
| API框架 | FastAPI | 异步、自动文档、类型校验 |
| 数据库 | PostgreSQL 15 | JSONB支持、GIN索引、成熟稳定 |
| 缓存 | Redis 7 | 会话、限流、热数据缓存 |
| LLM | Moka AI (Claude Sonnet) | 中文理解能力强、成本可控 |
| 配置 | YAML | 可读性好、支持行业定制 |
| 部署 | Docker Compose | 开发阶段简单，生产可升级K8s |
| CarryMem集成 | Protocol接口 | 优雅降级、可测试、可替换 |
| 认证 | JWT (RS256) | 非对称加密、临时授权码模式 |

### 8.0.1 API认证方案

```python
from fastapi import Depends, HTTPException, Security
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
import jwt

security = HTTPBearer()

AUTH_CONFIG = {
    "access_token_ttl": 900,      # 15分钟
    "refresh_token_ttl": 604800,  # 7天
    "ticket_ttl": 60,             # 临时授权码60秒
    "algorithm": "RS256",
}

async def verify_token(credentials: HTTPAuthorizationCredentials = Security(security)):
    token = credentials.credentials
    try:
        payload = jwt.decode(token, PUBLIC_KEY, algorithms=["RS256"])
        if await redis.get(f"blacklist:{payload['jti']}"):
            raise HTTPException(status_code=401, detail="Token revoked")
        return payload['user_id']
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")

async def generate_ticket(user_id: str, action: str, person_id: str = None) -> str:
    code = secrets.token_urlsafe(32)
    await redis.setex(
        f"ticket:{code}", AUTH_CONFIG["ticket_ttl"],
        json.dumps({"user_id": user_id, "action": action, "person_id": person_id})
    )
    return code

async def exchange_ticket(ticket: str) -> str:
    data = await redis.getdel(f"ticket:{ticket}")
    if not data:
        raise HTTPException(status_code=401, detail="Invalid or expired ticket")
    payload = json.loads(data)
    access_token = jwt.encode({
        "user_id": payload["user_id"],
        "exp": datetime.utcnow() + timedelta(seconds=AUTH_CONFIG["access_token_ttl"]),
        "jti": str(uuid4())
    }, PRIVATE_KEY, algorithm="RS256")
    return access_token
```

**速率限制**：

| 端点类型 | 限制 | 说明 |
|----------|------|------|
| 全局 | 1000请求/小时/IP | 防滥用 |
| 认证接口 | 10请求/分钟/IP | 防暴力破解 |
| 事件上报 | 100请求/小时/用户 | 防刷数据 |
| TTS播报 | 20请求/小时/用户 | 控制成本 |

### 8.0.2 专业版资源预估

| 配置项 | 最低配置(PoC) | 推荐配置(100用户) |
|--------|-------------|-------------------|
| CPU | 4核 | 8核 |
| 内存 | 8GB | 16GB |
| 磁盘 | 100GB SSD | 500GB SSD (IOPS≥3000) |
| 网络 | 10Mbps | 下行50Mbps+上行10Mbps |

**内存分配(推荐配置)**：
- FastAPI应用: 2GB
- PostgreSQL shared_buffers: 6GB
- Redis: 4GB（含TTS音频缓存）
- OS+其他: 4GB

**数据增长预估(100活跃用户/年)**：
- Events: ~50K条 → 50MB
- Entities: ~10K条 → 100MB (含JSONB)
- Associations: ~30K条 → 30MB
- Todos: ~20K条 → 20MB
- 总计: ~200MB/年数据 + 日志/备份 ~50GB/年

**瓶颈分析**：
- LLM API调用延迟: Claude Sonnet平均3-5s/次
- PostgreSQL写入峰值: 会议纪要处理时每秒10+ INSERT
- Redis连接池: 默认10连接，需调整为50+

### 8.0.3 安全配置

**传输安全**：
- 强制HTTPS（HSTS: max-age=31536000）
- TLS 1.3+
- 微信小程序→API通信走微信安全通道

**JWT密钥管理**：
```bash
# 密钥生成（仅初始化时执行一次）
openssl genrsa -out private.pem 2048
openssl rsa -in private.pem -pubout -out public.pem
chmod 600 private.pem  # 仅owner可读

# 环境变量注入（禁止硬编码）
JWT_PRIVATE_KEY_PATH=/secrets/jwt_private.pem
JWT_KEY_PASSWORD=<from_vault>  # 可选：密钥文件密码

# 密钥轮换：每90天，grace period 7天（新旧密钥同时有效）
```

**Refresh Token机制**：
```python
# Access Token: 15分钟TTL
# Refresh Token: 7天TTL，存储在Redis
POST /api/v1/auth/refresh
Headers: Authorization: Bearer <refresh_token>
Response: { "access_token": "...", "expires_in": 900 }

# Token撤销（登出）
POST /api/v1/auth/logout
→ 将access_token的jti加入Redis黑名单
→ 删除该用户所有refresh_token
```

**审计日志**：
- 认证失败记录（IP+UA+时间）
- Token撤销记录
- 敏感操作审计（查看画像/修改实体/导出数据）

**JWT认证规范（v2.4安全加固）**：

Token格式：Bearer <JWT>
签名算法：HS256 (cryptography库)
Payload结构：
{
  "sub": user_id (UUID),
  "iat": 签发时间,
  "exp": 过期时间 (默认24h),
  "role": "user" (预留扩展)
}

安全约束：
- Secret Key ≥ 256位随机值（启动时校验非默认值）
- Token黑名单机制（登出时写入Redis, TTL = token剩余有效期）
- Refresh Token旋转（每次刷新生成新token，旧token立即失效）
- 跨域CORS仅允许配置的Origin列表（不使用 *）

**威胁模型摘要（STRIDE简化版）**：

| 威胁类型 | 场景 | 缓解措施 | 当前状态 |
|---------|------|---------|---------|
| Spoofing | 伪造用户身份 | JWT + 微信OAuth | ✅ 已实现 |
| Tampering | 篡改请求数据 | HTTPS + 签名校验 | ⚠️ PoC HTTP需升级 |
| Repudiation | 否认操作 | 操作审计日志(Audit Logger) | 📋 专业版 |
| Information Disclosure | PII泄露 | AES-256-GCM + redact_pii | ✅ 已实现 |
| Denial of Service | LLM调用耗尽资源 | Rate Limit + 超时 | ⚠️ 基础实现 |
| Elevation of Privilege | 越权访问 | user_id强制过滤 | ✅ 已实现 |

PoC阶段重点关注：S/I/D三项（身份伪造、信息泄露、越权访问）
专业版补充：T(防篡改HTTPS) + R(操作审计日志) + D(完整Rate Limit)

### 8.0.4 备份策略

| 组件 | 全量备份 | 增量备份 | 保留策略 |
|------|----------|----------|----------|
| PostgreSQL | 每日3:00 AM | WAL归档每小时 | 30天全量+7天增量 |
| Redis | RDB每6小时 | AOF everysec | 3天（TTS缓存可丢失） |
| 配置文件 | Git版本控制 | — | 永久 |

### 8.0.5 监控指标

```yaml
必须监控(P0):
  - redis_memory_usage > 80% → 告警
  - pg_connection_pool > 90% → 告警
  - api_p95_latency > 3s → 告警
  - jwt_blacklist_miss_rate > 1% → 告警

P0 业务指标（v2.4新增，DevOps建议）：
  metrics:
    - name: input_scope_classification_duration_seconds
      type: histogram
      help: "Input scope classification latency"
    - name: todos_generated_total
      type: counter
      help: "Total todos generated (by event, for noise detection)"
      labels: [event_id, action_type]
    - name: relationship_brief_query_duration_seconds
      type: histogram
      help: "Relationship brief query latency"
    - name: relationship_stage_transitions_total
      type: counter
      help: "Stage transition count (by from_stage, to_stage)"

建议监控(P1):
  - tts_cache_hit_rate < 70% → 优化提示
  - llm_api_failure_rate > 5% → 降级规则引擎
  - entity_column_sync_mismatch > 0 → 修复触发器
  - disk_iops_usage > 80% → 扩容提示
```

### 8.0.6 数据库迁移策略（Alembic）

> **7角色架构评审共识**：数据库迁移策略是P3 Gate的必要条件，必须在P8前确定。

**技术选型**：Alembic（SQLAlchemy官方迁移工具）

```python
# alembic.ini 核心配置
[alembic]
script_location = alembic
sqlalchemy.url = postgresql://promiselink:***@localhost:5432/promiselink

# env.py 关键配置
from promiselink.models import Base
target_metadata = Base.metadata

# 支持多环境
def run_migrations_online():
    engine = create_engine(get_db_url()) # 个人版=SQLite(长期方案), 定制版=PG
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()
```

**迁移版本管理**：

| 版本号 | 迁移脚本 | API版本 | 变更内容 |
|--------|---------|---------|---------|
| 001 | `001_initial_schema.py` | v1.0 | 初始4表（events/entities/associations/todos） |
| 002 | `002_todo_types_v2.py` | v1.2 | Todo类型DDL重命名（CHECK约束更新） |
| 003 | `003_concern_promise_contribution.py` | v1.2 | entities.properties新增concern/promise/contribution结构 |
| 004 | `004_snooze_schedules.py` | v1.2 | 新增snooze_schedules表 |
| 005 | `005_entity_extract_columns.py` | v1.2 | entities表新增company/title/city/industry提取列+触发器 |

**迁移铁律**：

1. **每个迁移必须可回滚**：`downgrade()` 必须完整实现
2. **破坏性变更只能在新主版本**：删列/改类型必须走API v2
3. **定制版迁移是一次性全量迁移**：个人版SQLite→定制版PG，不走Alembic增量，使用 `sqlite3 .dump` + 迁移脚本
4. **迁移前必须备份**：自动化脚本先执行 `pg_dump` 再 `alembic upgrade`
5. **零停机迁移**：新增列用DEFAULT值，不锁表；删列分两步（先标记deprecated→下个主版本删除）

**定制版迁移方案**（个人版无需迁移，SQLite长期方案）：

```bash
# Step 1: 导出SQLite数据
sqlite3 promiselink_poc.db .dump > /tmp/promiselink_dump.sql

# Step 2: 转换SQL方言（SQLite→PostgreSQL）
python3 scripts/migrate_sqlite_to_pg.py /tmp/promiselink_dump.sql > /tmp/promiselink_pg.sql

# Step 3: 创建PG数据库并执行Alembic初始迁移
createdb promiselink
alembic upgrade head

# Step 4: 导入数据（跳过已由Alembic创建的表结构）
psql promiselink < /tmp/promiselink_pg_data_only.sql

# Step 5: 验证数据完整性
python3 scripts/verify_migration.py --source sqlite --target postgresql
```

### 8.0.7 结构化日志规范

> **7角色架构评审P0缺口补齐**：结构化日志是P8核心算法调试的必要基础设施。

**技术选型**：structlog（JSON结构化输出）+ 标准logging兼容层

```python
# src/promiselink/core/logging.py
import structlog
import logging
import uuid
from contextvars import ContextVar

# 请求级上下文变量
request_id_var: ContextVar[str] = ContextVar("request_id", default="")
user_id_var: ContextVar[str] = ContextVar("user_id", default="")

def configure_logging(log_level: str = "INFO", json_output: bool = True):
    """配置结构化日志"""
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,     # 合并上下文变量
            structlog.processors.add_log_level,           # 添加日志级别
            structlog.processors.TimeStamper(fmt="iso"),  # ISO 8601时间戳
            structlog.processors.StackInfoRenderer(),     # 堆栈信息
            structlog.processors.format_exc_info,         # 异常信息
            structlog.processors.UnicodeDecoder(),        # Unicode解码
            structlog.processors.JSONRenderer()           # if json_output else ConsoleRenderer()
            if json_output
            else structlog.dev.ConsoleRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, log_level.upper(), logging.INFO)
        ),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )

def get_logger(name: str = "promiselink") -> structlog.stdlib.BoundLogger:
    """获取带模块名的logger"""
    return structlog.get_logger(name)

# FastAPI中间件：注入request_id
from starlette.middleware.base import BaseHTTPMiddleware

class RequestIdMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        req_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))
        request_id_var.set(req_id)
        response = await call_next(request)
        response.headers["X-Request-ID"] = req_id
        return response
```

**日志格式规范**：

```json
{
  "timestamp": "2026-06-03T10:30:00.123456+08:00",
  "level": "info",
  "event": "entity_resolved",
  "request_id": "550e8400-e29b-41d4-a716-446655440000",
  "user_id": "usr_abc123",
  "module": "promiselink.services.entity_resolution",
  "function": "resolve_entity",
  "entity_id": "ent_xyz789",
  "similarity_score": 0.88,
  "decision": "auto_merge",
  "duration_ms": 45
}
```

**必填字段**：

| 字段 | 类型 | 说明 |
|------|------|------|
| timestamp | string | ISO 8601，含时区 |
| level | string | debug/info/warning/error/critical |
| event | string | 事件名称（动词+名词，如entity_resolved） |
| request_id | string | 请求唯一ID，跨服务传递 |
| user_id | string | 当前用户ID |

**可选字段（按模块）**：

| 模块 | 专用字段 |
|------|---------|
| LLM调用 | model, prompt_tokens, completion_tokens, duration_ms, provider, fallback_used |
| 实体归一 | entity_id, similarity_score, decision, matched_fields, conflict_fields |
| 匹配引擎 | todo_type, match_score, dimensions, threshold |
| 事件处理 | event_id, event_type, pipeline_stage, status |
| 认证 | auth_method, token_type, ip_hash |

**日志脱敏规则**：

| 字段类型 | 脱敏方式 | 示例 |
|---------|---------|------|
| 手机号 | 保留前3后4 | 138****5678 |
| 邮箱 | 保留首字母+@后 | z***@zhiyuan-ai.com |
| 身份证 | 保留前3后4 | 110***********1234 |
| 银行卡 | 保留后4 | ****5678 |
| 姓名 | 保留姓 | 张** |
| LLM原始prompt | 不记录到日志 | 仅记录token数 |

**PoC阶段日志配置**：

```yaml
# config/logging.yml
version: 1
disable_existing_loggers: false
formatters:
  json:
    class: pythonjsonlogger.jsonlogger.JsonFormatter
    format: "%(timestamp)s %(level)s %(name)s %(message)s"
  console:
    format: "%(asctime)s [%(levelname)s] %(name)s: %(message)s"

handlers:
  console:
    class: logging.StreamHandler
    formatter: console
    level: DEBUG
  file:
    class: logging.handlers.RotatingFileHandler
    filename: logs/promiselink.log
    maxBytes: 10485760  # 10MB
    backupCount: 5
    formatter: json
    level: INFO

loggers:
  promiselink:
    level: DEBUG
    handlers: [console, file]
    propagate: false
  promiselink.services.llm_client:
    level: INFO
    handlers: [console, file]
  promiselink.services.entity_resolution:
    level: DEBUG
    handlers: [console, file]
```

---

### 8.0.8 统一错误处理与降级策略

> **7角色架构评审P0缺口补齐**：统一错误处理是P8核心算法开发的质量保障。

**异常类层次结构**：

```python
# src/promiselink/core/exceptions.py
from typing import Optional

class PromiseLinkError(Exception):
    """PromiseLink基础异常"""
    def __init__(self, message: str, code: str, details: Optional[dict] = None):
        self.message = message
        self.code = code
        self.details = details or {}
        super().__init__(message)

# ── 业务异常 ──
class BusinessError(PromiseLinkError):
    """业务逻辑异常基类"""

class EntityNotFoundError(BusinessError):
    """实体不存在"""
    def __init__(self, entity_id: str):
        super().__init__(
            message=f"Entity not found: {entity_id}",
            code="ENTITY_NOT_FOUND",
            details={"entity_id": entity_id}
        )

class InvalidTodoTypeError(BusinessError):
    """无效的Todo类型"""
    def __init__(self, todo_type: str):
        super().__init__(
            message=f"Invalid todo_type: {todo_type}",
            code="INVALID_TODO_TYPE",
            details={"todo_type": todo_type, "valid_types": [
                "promise", "help", "care", "followup", "cooperation_signal", "risk"
            ]}
        )

class DuplicateEntityError(BusinessError):
    """实体已存在（归一冲突）"""
    def __init__(self, entity_id: str, conflict_id: str):
        super().__init__(
            message=f"Entity conflict: {entity_id} vs {conflict_id}",
            code="DUPLICATE_ENTITY",
            details={"entity_id": entity_id, "conflict_id": conflict_id}
        )

# ── LLM异常 ──
class LLMError(PromiseLinkError):
    """LLM调用基础异常"""

class LLMTimeoutError(LLMError):
    """请求超时"""
    def __init__(self, provider: str, timeout: int):
        super().__init__(
            message=f"LLM timeout: {provider} after {timeout}s",
            code="LLM_TIMEOUT",
            details={"provider": provider, "timeout": timeout}
        )

class LLMRateLimitError(LLMError):
    """速率限制"""
    def __init__(self, provider: str):
        super().__init__(
            message=f"LLM rate limit: {provider}",
            code="LLM_RATE_LIMIT",
            details={"provider": provider}
        )

class LLMQuotaExceeded(LLMError):
    """配额耗尽"""
    def __init__(self, provider: str):
        super().__init__(
            message=f"LLM quota exceeded: {provider}",
            code="LLM_QUOTA_EXCEEDED",
            details={"provider": provider}
        )

class LLMResponseParseError(LLMError):
    """响应解析失败"""
    def __init__(self, raw_response: str, parse_error: str):
        super().__init__(
            message=f"LLM response parse error: {parse_error}",
            code="LLM_PARSE_ERROR",
            details={"parse_error": parse_error}
            # 注意：不记录raw_response到details，可能含PII
        )

# ── 基础设施异常 ──
class InfrastructureError(PromiseLinkError):
    """基础设施异常基类"""

class DatabaseError(InfrastructureError):
    """数据库异常"""
    def __init__(self, operation: str, original_error: str):
        super().__init__(
            message=f"Database error during {operation}",
            code="DATABASE_ERROR",
            details={"operation": operation}
        )

class CarryMemUnavailableError(InfrastructureError):
    """CarryMem不可用"""
    def __init__(self):
        super().__init__(
            message="CarryMem unavailable, using NullMemoryProvider",
            code="CARRYMEM_UNAVAILABLE",
        )
```

**降级决策矩阵**：

| 故障场景 | 检测条件 | 降级策略 | 用户影响 | 恢复条件 |
|---------|---------|---------|---------|---------|
| LLM Provider A超时 | 单次>30s | 切换Provider B | 无感知 | Provider A恢复 |
| LLM全部不可用 | 3次重试+3个Provider均失败 | 规则降级（关键词提取） | 实体提取精度降低 | 任一Provider恢复 |
| LLM配额耗尽 | LLMQuotaExceeded异常 | 规则降级+告警 | 同上 | 配额重置 |
| 数据库连接失败 | 连接池耗尽/超时 | 503 Service Unavailable | 服务不可用 | 数据库恢复 |
| CarryMem不可用 | 连接超时>5s | NullMemoryProvider | 无记忆增强 | CarryMem恢复 |
| 实体归一置信度低 | similarity<0.6 | 标记need_confirm | 需用户手动确认 | 无（设计如此） |
| 匹配阈值未命中 | match_score<threshold | 不生成Todo | 无推荐 | 阈值调整 |

**FastAPI全局异常处理器**：

```python
# src/promiselink/core/error_handlers.py
from fastapi import Request
from fastapi.responses import JSONResponse
import structlog

logger = structlog.get_logger("promiselink.error_handler")

async def promiselink_error_handler(request: Request, exc: PromiseLinkError) -> JSONResponse:
    """PromiseLink业务异常统一处理"""
    logger.error(
        "business_error",
        code=exc.code,
        message=exc.message,
        details=exc.details,
        path=str(request.url),
    )
    status_map = {
        "ENTITY_NOT_FOUND": 404,
        "INVALID_TODO_TYPE": 422,
        "DUPLICATE_ENTITY": 409,
        "LLM_TIMEOUT": 504,
        "LLM_RATE_LIMIT": 429,
        "LLM_QUOTA_EXCEEDED": 503,
        "LLM_PARSE_ERROR": 502,
        "DATABASE_ERROR": 503,
        "CARRYMEM_UNAVAILABLE": 200,  # 降级而非报错
    }
    status = status_map.get(exc.code, 500)
    return JSONResponse(
        status_code=status,
        content={
            "error": {
                "code": exc.code,
                "message": exc.message,
                "request_id": request_id_var.get(""),
                "is_ai_inference": exc.details.get("is_ai_inference", False),
            }
        },
    )

async def unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
    """未处理异常兜底"""
    logger.exception(
        "unhandled_error",
        error_type=type(exc).__name__,
        error_message=str(exc),
        path=str(request.url),
    )
    return JSONResponse(
        status_code=500,
        content={
            "error": {
                "code": "INTERNAL_ERROR",
                "message": "An unexpected error occurred",
                "request_id": request_id_var.get(""),
            }
        },
    )
```

**熔断器规范**（专业版实现，PoC仅记录）：

```python
# PoC阶段：简单计数器
class SimpleCircuitBreaker:
    """PoC阶段简易熔断器"""
    def __init__(self, failure_threshold: int = 5, reset_timeout: int = 60):
        self.failure_count = 0
        self.failure_threshold = failure_threshold
        self.reset_timeout = reset_timeout
        self.last_failure_time = None
        self.state = "closed"  # closed/open/half_open

    def record_failure(self):
        self.failure_count += 1
        self.last_failure_time = time.time()
        if self.failure_count >= self.failure_threshold:
            self.state = "open"
            logger.warning("circuit_breaker_open", threshold=self.failure_threshold)

    def record_success(self):
        self.failure_count = 0
        self.state = "closed"

    def is_available(self) -> bool:
        if self.state == "closed":
            return True
        if self.state == "open":
            if time.time() - self.last_failure_time > self.reset_timeout:
                self.state = "half_open"
                return True
            return False
        return True  # half_open
```

---

## 8.5 触达通道设计

> **核心问题**：用户在外拜访/开会时，如何收到AI的行动建议？这是产品闭环的"最后一公里"。

### 8.5.1 场景-通道矩阵

| 用户状态 | 需要什么 | 时间窗口 | 触达通道 |
|----------|----------|----------|----------|
| 会前（即将见某人） | 关系画像+沟通建议 | 会前15-60分钟 | 微信服务号推送 |
| 会中（正在开会） | 不打扰，静默采集 | 全程 | 无推送（后台记录） |
| 会后（刚结束） | 快速录入+行动项 | 会后5-30分钟 | 微信小程序卡片 |
| 日常（碎片时间） | 维护提醒+早晚报 | 早晨/晚间 | 微信服务号 |

### 8.5.2 专业版触达方案

**通道1：微信服务号模板消息（核心通道）**

```python
class WechatNotifyChannel:
    async def send_prep_reminder(self, user_id: str, entity: Entity, event: Event):
        template = {
            "touser": user_openid,
            "template_id": "PREP_REMINDER",
            "data": {
                "person": entity.name,
                "company": entity.properties.get("company", ""),
                "relation": entity.properties.get("relationship", {}).get("strength", ""),
                "last_contact": "聊了新项目预算",
                "suggestion": "可提华南区代工厂对接"
            }
        }
        await self._send_template(template)

    async def send_todo_due(self, user_id: str, todo: Todo):
        ...

    async def send_morning_digest(self, user_id: str, digest: dict):
        ...
```

**通道2：手机推送通知（APNs/FCM）**

- 用于紧急提醒（风险预警、即将到期Todo）
- 点击通知→打开微信小程序

**通道3：微信小程序卡片（许总已有名片小程序）**

- 名片小程序内嵌PromiseLink入口
- 查看关系画像、确认行动建议、快速录入

### 8.5.3 触发时机

| 触发条件 | 推送内容 | 通道 | 优先级 |
|----------|----------|------|--------|
| 日历事件前15-60分钟 | 会前准备清单 | 微信服务号 | 高 |
| 事件提交后30秒内 | AI生成的行动建议 | 微信服务号 | 中 |
| Todo到期日当天9:00 | 到期提醒 | 推送通知 | 高 |
| 关联强度衰减阈值 | 维护提醒 | 微信服务号 | 低 |
| 每日7:30 | 早间简报 | 微信服务号 | 低 |
| 每日21:00 | 晚间汇总 | 微信服务号 | 低 |

### 8.5.4 定制版触达扩展

| 通道 | 场景 | 依赖 |
|------|------|------|
| 录音卡屏幕/语音播报 | 会前快速提醒 | 许总硬件支持 |
| Apple Watch/智能手环 | 会前震动提醒 | WatchOS/WearOS开发 |
| 邮件日报 | 非微信用户 | SMTP服务 |

### 8.5.5 触达架构

```
PromiseLink API
    │
    ├─ NotificationService
    │   ├── ChannelRouter（根据用户偏好选择通道）
    │   │   ├── WechatChannel（微信服务号模板消息）
    │   │   ├── PushChannel（APNs/FCM）
    │   │   └── EmailChannel（定制版）
    │   │
    │   ├── TriggerEngine（触发时机判断）
    │   │   ├── CalendarTrigger（日历事件→会前提醒）
    │   │   ├── TodoDueTrigger（Todo到期→到期提醒）
    │   │   ├── DecayTrigger（关联衰减→维护提醒）
    │   │   └── DigestTrigger（定时→早晚报）
    │   │
    │   └── RateLimiter（防打扰：同一用户每小时≤3条，每日≤10条）
    │
    └─ 用户偏好（可配置通道/频率/静默时段）
```

---

## 8.6 部署架构与数据主权

> **对应PRD**: §1.5 部署模型与数据主权
> **核心决策**: PoC本地优先（零云成本+数据不出本机），专业版云端托管（规模化+集中运维），前端始终以微信小程序为主入口，不开发原生APP。

### 8.6.1 为什么不做原生APP

LLM推理必须走云端，手机只是展示层。微信小程序已覆盖PromiseLink全部核心交互（语音录入/ TTS播报/名片扫描/推送通知），原生APP无增量价值，且获客成本高（下载APP vs 扫码即用）、开发成本高（双端 vs 单端）。

### 8.6.2 阶段递进式部署架构

```
自助PoC（用户电脑）          托管PoC（云服务器2C4G）        专业版（云服务器）           定制版（功能扩展）
┌─────────────────┐         ┌─────────────────────┐     ┌─────────────────┐         ┌─────────────────┐
│ Docker单机       │         │ Docker Compose       │     │ Docker单机/Compose│         │ Docker Compose   │
│ ├─ FastAPI       │         │ ├─ FastAPI           │     │ ├─ FastAPI       │  扩展   │ ├─ FastAPI       │
│ ├─ SQLite        │         │ ├─ SQLite            │     │ ├─ SQLite        │ ──────→ │ ├─ SQLite        │
│ └─ NullMemory    │         │ ├─ Nginx(反代+TLS)   │     │ └─ CarryMem(opt) │         │ └─ CarryMem     │
│                  │         │ └─ NullMemory        │     │                  │         │                  │
└─────────────────┘         └─────────────────────┘     └─────────────────┘         └─────────────────┘
     ↕ localhost:8000             ↕ 域名+HTTPS                ↕ API                       ↕ API
┌─────────────────┐         ┌─────────────────────┐     ┌─────────────────┐         ┌─────────────────┐
│ Swagger UI      │         │ 名片小程序            │     │ 名片小程序        │         │ 独立小程序+Web   │
│ (开发测试用)     │         │ ├─ 原生(语音/TTS)    │     │ ├─ 原生(语音/TTS) │         │ ├─ 原生+Web     │
│                 │         │ └─ H5(查询/管理)     │     │ └─ H5(查询/管理)  │         │ └─ 全功能       │
└─────────────────┘         └─────────────────────┘     └─────────────────┘         └─────────────────┘
     迁移                        打磨                       扩展
  (自助→托管可选)            (托管PoC→专业版)           (专业版→定制版)

定制版（销售团队，独立分支）
┌─────────────────────┐
│ Docker Compose       │
│ ├─ FastAPI           │
│ ├─ PostgreSQL 15     │  ← 多用户并发才需要
│ ├─ Redis 7           │  ← 多用户缓存才需要
│ └─ 多租户隔离        │
└─────────────────────┘
```

### 8.6.3 PoC部署方案（Docker单机）

```yaml
# docker-compose.poc.yml
version: "3.8"
services:
  promiselink-api:
    build: .
    ports:
      - "8000:8000"
    environment:
      - PROMISELINK_STAGE=poc
      - PROMISELINK_DB_PATH=/data/promiselink_poc.db
      - LLM_API_KEY=${LLM_API_KEY}
      - LLM_BASE_URL=${LLM_BASE_URL}
    volumes:
      - ./data:/data
    restart: unless-stopped
```

**PoC启动命令**：
```bash
docker compose -f docker-compose.poc.yml up -d
# API: http://localhost:8000
# Swagger: http://localhost:8000/docs
```

**PoC数据位置**：`./data/promiselink_poc.db`（SQLite文件，用户完全控制）

### 8.6.3a 托管PoC部署模式（v2.9新增）

> **适用场景**：用户无本地Docker环境，或需要微信小程序直接访问，或希望零运维上手体验。

**架构描述**：云服务器(2C4G) + Docker Compose + Nginx反向代理 + HTTPS(Let's Encrypt) + SQLite + 微信小程序接入。

```yaml
# docker-compose.hosted-poc.yml
version: "3.8"
services:
  nginx:
    image: nginx:alpine
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - ./nginx/conf.d:/etc/nginx/conf.d
      - ./certbot/conf:/etc/letsencrypt
      - ./certbot/www:/var/www/certbot
    depends_on:
      - promiselink-api
    restart: always

  certbot:
    image: certbot/certbot
    volumes:
      - ./certbot/conf:/etc/letsencrypt
      - ./certbot/www:/var/www/certbot
    entrypoint: "/bin/sh -c 'trap exit TERM; while :; do certbot renew; sleep 12h & wait $${!}; done;'"

  promiselink-api:
    build: .
    expose:
      - "8000"
    environment:
      - PROMISELINK_STAGE=poc
      - PROMISELINK_DB_PATH=/data/promiselink_poc.db
      - LLM_API_KEY=${LLM_API_KEY}     # 由我们托管管理
      - LLM_BASE_URL=${LLM_BASE_URL}
    volumes:
      - ./data:/data
    restart: always
```

**Nginx反向代理配置**：
```nginx
# nginx/conf.d/promiselink.conf
server {
    listen 80;
    server_name promiselink.example.com;
    location /.well-known/acme-challenge/ {
        root /var/www/certbot;
    }
    location / {
        return 301 https://$host$request_uri;
    }
}

server {
    listen 443 ssl;
    server_name promiselink.example.com;

    ssl_certificate /etc/letsencrypt/live/promiselink.example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/promiselink.example.com/privkey.pem;

    # 微信小程序安全域名要求
    add_header Strict-Transport-Security "max-age=31536000" always;

    location / {
        proxy_pass http://promiselink-api:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

**托管PoC启动命令**：
```bash
# 首次部署：申请证书
docker compose -f docker-compose.hosted-poc.yml up -d nginx certbot
# 证书签发后重启Nginx启用HTTPS
docker compose -f docker-compose.hosted-poc.yml restart nginx
```

**自助PoC vs 托管PoC对比**：

| 维度 | 自助PoC | 托管PoC |
|------|---------|---------|
| 部署位置 | 用户本地电脑 | 云服务器(2C4G) |
| 访问方式 | localhost:8000（HTTP） | 域名+HTTPS（如 promiselink.example.com） |
| 运维责任 | 用户自行维护 | 我们负责服务器运维+数据备份 |
| 成本 | 零（用户自有设备） | 云服务器费用（~100元/月） |
| 数据存储 | 本地SQLite，用户完全控制 | 云端SQLite，我们负责备份 |
| TLS/HTTPS | 不需要（本地访问） | 必须（微信小程序要求+安全传输） |
| 域名 | 不需要 | 需要公网域名+ICP备案 |
| LLM Key | 用户自行配置 | 我们托管管理 |
| 小程序接入 | ❌ 不支持（localhost不可达） | ✅ 支持（域名+HTTPS满足微信要求） |
| 数据备份 | 用户自行负责 | 我们每日自动备份SQLite文件 |

**与自助PoC的关键差异**：
1. **公网IP+域名**：必须拥有公网IP和已备案域名，微信小程序要求HTTPS安全域名
2. **HTTPS强制**：Let's Encrypt自动证书签发+自动续期，Nginx终止TLS
3. **Nginx反向代理**：负责TLS终止、请求转发、安全头注入
4. **LLM Key托管**：由我们统一管理API Key，用户无需自行配置
5. **数据备份**：我们每日自动备份SQLite文件至对象存储，用户可随时下载

### 8.6.4 专业版部署方案（Docker Compose）

```yaml
# docker-compose.phase1.yml
version: "3.8"
services:
  promiselink-api:
    build: .
    ports:
      - "8000:8000"
    environment:
      - PROMISELINK_STAGE=phase1
      - DATABASE_URL=postgresql://promiselink:${PG_PASSWORD}@postgres:5432/promiselink
      - REDIS_URL=redis://redis:6379/0
      - LLM_API_KEY=${LLM_API_KEY}
      - JWT_PRIVATE_KEY_PATH=/secrets/jwt_rsa
    depends_on:
      - postgres
      - redis
    volumes:
      - ./secrets:/secrets:ro
    restart: always

  postgres:
    image: postgres:15
    environment:
      - POSTGRES_DB=promiselink
      - POSTGRES_USER=promiselink
      - POSTGRES_PASSWORD=${PG_PASSWORD}
    volumes:
      - pg_data:/var/lib/postgresql/data
    restart: always

  redis:
    image: redis:7-alpine
    volumes:
      - redis_data:/data
    restart: always

volumes:
  pg_data:
  redis_data:
```

### 8.6.5 数据主权技术实现

| 原则 | 技术实现 | 阶段 |
|------|---------|------|
| 用户数据所有权 | 所有核心表含user_id字段，查询强制WHERE user_id=? | PoC+ |
| 数据可携带 | /api/v1/export 全量JSON导出 | 定制版 |
| 数据可删除 | /api/v1/account/delete 级联删除+账号注销 | 专业版 |
| 数据最小化 | 仅接收文本输入，raw_text≤500KB | PoC+ |
| 处理透明 | Todo含source_event+match_reason | PoC+ |
| 私密助手 | 无RBAC、无跨用户查询、无resource_permissions表 | PoC+ |

**PoC阶段数据安全**：
- SQLite文件存储在用户本地，数据不出本机
- LLM调用仅发送脱敏文本（_sanitize_for_llm过滤姓名/电话/地址）
- 无公网暴露（localhost:8000）

**专业版+数据安全**：
- PostgreSQL user_id行级隔离（Row Level Security）
- JWT认证+临时授权码（非明文token）
- LLM调用HTTPS加密传输
- 自动每日备份（pg_dump加密压缩）

### 8.6.6 数据库方案与定制版迁移

**核心优势**：SQLAlchemy抽象层使数据库切换零代码改动。

```python
# 个人版：SQLite长期方案，无需迁移
# PROMISELINK_STAGE=poc → SQLite（个人版始终使用SQLite）

# 定制版迁移（销售团队场景，独立分支）
# PROMISELINK_STAGE=custom → PostgreSQL + Redis
```

**个人版SQLite长期方案**（2026-06-11决策变更）：

| 迁移项 | 个人版 | 定制版 | 改动量 |
|--------|-------|--------|--------|
| 数据库 | SQLite（长期方案） | PG连接字符串 | 1行配置 |
| 缓存 | 内存dict | Redis URL | 1行配置 |
| 认证中间件 | API Key/PoC Secret | JWT RS256+多租户 | 中间件替换 |
| CarryMem | NullMemory | 可选接入 | 配置切换 |
| 前端 | Swagger UI | 小程序 | 新增，API不变 |
| 数据 | 不迁移 | SQLite→PG一次性脚本 | ~100行 |

> **决策理由**：PromiseLink是个人产品，单用户无并发场景，SQLite处理百万行无压力。PG/Redis增加成本和复杂度但无收益。仅在销售团队定制版中按需引入。

#### 8.6.6a 定制版迁移路径（销售团队场景，独立分支）

> **场景**：销售团队定制版需要多用户并发，需将SQLite数据迁移到PostgreSQL，同时切换Docker Compose配置。此迁移仅在定制版分支中执行，不影响个人版。

**迁移步骤**（5步，预计停机时间<10分钟）：

```bash
# Step 1: SQLite数据导出
sqlite3 /data/promiselink_poc.db .dump > /tmp/promiselink_dump.sql

# Step 2: 转换SQL方言（SQLite→PostgreSQL兼容性）
python3 scripts/migrate_sqlite_to_pg.py /tmp/promiselink_dump.sql > /tmp/promiselink_pg.sql
# 主要转换：
#   - AUTOINCREMENT → SERIAL
#   - TEXT → TEXT (保持不变，PG兼容)
#   - BOOLEAN代用(INTEGER 0/1) → BOOLEAN
#   - datetime('now') → NOW()
#   - REMOVE PRAGMA/INDEX IF NOT EXISTS等SQLite特有语法

# Step 3: 导入PostgreSQL
docker compose -f docker-compose.phase1.yml up -d postgres redis
sleep 5  # 等待PG就绪
# 先执行Alembic初始迁移创建表结构
alembic upgrade head
# 再导入数据（跳过已由Alembic创建的表结构，仅导入数据行）
psql $DATABASE_URL < /tmp/promiselink_pg.sql

# Step 4: 切换Docker Compose文件
docker compose -f docker-compose.hosted-poc.yml down
docker compose -f docker-compose.phase1.yml up -d

# Step 5: DNS切换（零停机）
# 在专业版服务健康检查通过后，切换DNS A记录指向新服务
# TTL设为60秒，等待旧DNS缓存过期（最多5分钟）
curl -f https://promiselink.example.com/health || echo "HEALTH CHECK FAILED"
```

**零停机策略**：
- Step 4~5之间，Nginx保留并指向新FastAPI实例
- DNS切换前，新服务已通过健康检查
- 切换期间旧连接自然过期，新请求路由到专业版

**回滚方案**：
1. DNS回退：将A记录指回原IP（TTL 60s，1分钟内生效）
2. SQLite恢复：从备份恢复 `promiselink_poc.db`
3. 重启托管PoC：`docker compose -f docker-compose.hosted-poc.yml up -d`
4. 验证回滚：`curl -f https://promiselink.example.com/health`

**迁移检查清单**：

| 检查项 | 验证方法 | 通过标准 |
|--------|----------|----------|
| 数据完整性 | 对比源SQLite与目标PG记录数 | 各表行数一致 |
| API可用性 | `curl /health` + 核心API调用 | 200 OK |
| 小程序连通 | 微信开发者工具请求域名 | HTTPS正常响应 |
| 认证切换 | API Key→JWT | 旧Key失效，新Token正常 |
| 数据备份 | pg_dump验证 | 备份文件可恢复 |

---

## 8.7 网关中继架构（专业版）

### 8.7.1 架构概览

**三层产品模型**：

| 层级 | 名称 | 部署方式 | 前端 | AI调用 | 数据存储 |
|------|------|----------|------|--------|----------|
| L1 | 基础版 | 本地Docker | Taro H5 | 用户自带API Key | 本地SQLite |
| L2 | 专业版 | 本地Docker + 网关中继 | 微信小程序 | 网关代理DeepSeek | 本地SQLite |
| L3 | 定制版 | 云端部署 | 微信小程序+多端 | 云端AI服务 | PG + Redis + 多租户 |

**架构图**：

```
┌──────────────────┐     WebSocket(WSS)     ┌──────────────────┐     HTTPS      ┌──────────────────┐
│  用户家用PC       │ ◄════════════════════► │  云VPS网关        │ ◄════════════► │  微信小程序        │
│  ┌────────────┐  │     长连接(出站)        │  ┌────────────┐  │                │  ┌────────────┐  │
│  │ 本地Docker  │  │                        │  │ 中继路由器  │  │                │  │ Taro H5    │  │
│  │ FastAPI    │  │                        │  │ AI代理      │  │                │  │ +原生组件   │  │
│  │ SQLite     │  │                        │  │ 计数限流    │  │                │  └────────────┘  │
│  │ relay_     │  │                        │  └────────────┘  │                └──────────────────┘
│  │  client    │  │                        │  ┌────────────┐  │
│  └────────────┘  │                        │  │ DeepSeek   │  │
└──────────────────┘                        │  │ API代理    │  │
                                            │  └────────────┘  │
                                            └──────────────────┘
```

**核心设计原则**：
- 网关不存业务数据，只做**加密转发 + AI代理 + 计数限流**
- 用户PC主动出站连接网关（无需公网IP、无需端口映射）
- 网关是无状态中继，可随时替换/重启

### 8.7.2 基础版 vs 专业版 Docker区别

**基础版Docker组成**：

```
基础版 Docker
├── FastAPI (业务API)
├── SQLite (数据存储)
├── 本地Embedding (text-embedding-3-small / 本地降级)
└── Taro H5前端 (静态文件，Nginx托管)
```

**专业版Docker组成**：

> **关键设计**：relay_client 是 **FastAPI进程内的嵌入式模块**（embedded module），**不是独立容器**。当环境变量 `RELAY_GATEWAY_URL` 设置时，relay_client 作为 FastAPI 的后台 asyncio Task 自动启动；未设置时（基础版），relay_client 不启动。

```
专业版 Docker（与基础版相同的单容器）
├── FastAPI (业务API)
│   └── 🆕 relay_client（嵌入式模块，后台asyncio Task）
│       ├── 自动重连（指数退避）
│       ├── 心跳维持（30s ping）
│       └── AI调用走网关代理（非本地Key）
├── SQLite (数据存储)
├── 本地Embedding
└── Taro H5前端
```

**启动逻辑**：
- `RELAY_GATEWAY_URL` 已设置 → FastAPI启动时自动创建 `relay_client` 后台asyncio Task，建立WSS连接
- `RELAY_GATEWAY_URL` 未设置（基础版）→ relay_client不启动，AI调用走本地API Key

**Docker Compose差异表**：

| 服务 | 基础版 | 专业版 | 说明 |
|------|--------|--------|------|
| `promiselink-api` | ✅ | ✅ | FastAPI业务服务（专业版内含relay_client后台Task） |
| `promiselink-web` | ✅ | ✅ | Nginx托管H5前端 |
| 环境变量 `RELAY_GATEWAY_URL` | 无 | `https://gateway.promiselink.cn` | 设置即启用relay_client后台Task（WSS连接到 `/api/v1/pro/relay/ws`） |
| 环境变量 `RELAY_USER_TOKEN` | 无 | JWT签名token | 用户身份凭证 |
| 环境变量 `AI_MODE` | `local` | `relay` | AI调用模式 |
| 环境变量 `DEEPSEEK_API_KEY` | 用户自填 | 无（网关代理） | API Key存储位置 |

> **注意**：专业版**不新增独立容器**，relay_client作为FastAPI进程内模块运行，共享同一容器资源，零额外部署开销。

### 8.7.3 网关中继协议

**WebSocket长连接**：
- 方向：用户PC **主动连**网关（出站连接，无需公网IP）
- 协议：`wss://gateway.promiselink.cn/relay`
- 认证：连接时携带 `user_token`（JWT签名），网关验证后建立映射

**消息格式**：

```json
// 请求（小程序→网关→本地Docker）
{
  "type": "request",
  "request_id": "uuid-v4",
  "user_token": "jwt-signed-token",
  "payload": {
    "method": "POST",
    "path": "/api/v1/events",
    "headers": {"Content-Type": "application/json"},
    "body": {"content": "今天和张总吃了午饭，聊了新项目合作"}
  }
}

// 响应（本地Docker→网关→小程序）
{
  "type": "response",
  "request_id": "uuid-v4",
  "user_token": "jwt-signed-token",
  "payload": {
    "status": 200,
    "body": {"event_id": "xxx", "entities": [...]}
  }
}

// 心跳
{
  "type": "ping",
  "request_id": null,
  "user_token": null,
  "payload": null
}
```

**路由机制**：
- 网关维护 `user_token → WebSocket connection` 映射表（内存，不持久化）
- 收到小程序请求 → 查映射表 → 转发到对应用户PC的WebSocket连接
- 用户PC离线 → 返回 `503 Service Unavailable` 给小程序

**心跳与重连**：

| 参数 | 值 | 说明 |
|------|----|------|
| 心跳间隔 | 30s | relay_client定时发送ping |
| 超时判定 | 60s无pong | 网关判定连接断开，清除映射 |
| 重连策略 | 指数退避 | 1s → 2s → 4s → 8s → 16s → 30s（上限） |
| 重连上限 | 无限 | 持续重连直到网关恢复 |

### 8.7.4 AI调用路径

**三场景AI路径模型**：

| 场景 | 用户状态 | 入口 | AI后端 | Key来源 | 网络要求 |
|------|----------|------|--------|---------|----------|
| 场景1 | 纯基础版 | 浏览器局域网 | 本地模型/自带Key | 用户自备 | 完全离线可用 |
| 场景2 | 已开通专业版 + 在家用浏览器 | 浏览器局域网 | 云端AI（我方Key） | 网关代理 | 需联网验证身份 |
| 场景3 | 已开通专业版 + 出门用小程序 | 微信小程序 | 云端AI（我方Key） | 网关代理 | 正常路径 |

**场景1：纯基础版 → 完全离线**

```
浏览器(H5) → 本地Docker(FastAPI) → 用户自带API Key / 本地模型 → 返回
```

- 无需联网，所有AI调用走本地Key或本地推理
- 不经过网关，不消耗我方AI额度
- 隐私最大化：数据不离开用户局域网

**场景2：已开通专业版 + 在家用浏览器 → 网关代理AI**

```
浏览器(H5) → 本地Docker(FastAPI)
                    ↓
          检测到专业版身份（JWT已激活）
                    ↓
          标注"AI调用"请求头 X-AI-Call: true
                    ↓
          relay_client → 中继网关(AI代理) → Moka AI API → 返回
                    ↓
          本地Docker组装响应 → 浏览器
```

- 家中浏览器通过局域网访问本地Docker，AI调用经网关代理
- 身份已激活，无需重复验证（JWT缓存有效期内）
- 享受专业版AI额度，网关统一计数限流

**场景3：已开通专业版 + 出门用小程序 → 正常路径**

```
微信小程序 → 中继网关 → 本地Docker(业务逻辑)
                              ↓
                    标注"AI调用"请求头 X-AI-Call: true
                              ↓
                    中继网关(AI代理) → DeepSeek API → 返回
                              ↓
                    本地Docker组装响应 → 中继网关 → 微信小程序
```

- 出门场景，小程序经网关中继访问本地Docker
- AI调用同样经网关代理，与场景2共享AI额度池
- 网关统一计数限流，用户体验一致

**关键流程**：
1. 小程序发请求 → 网关转发到本地Docker
2. 本地Docker处理业务逻辑，遇到需要AI的步骤
3. 本地Docker向网关发AI调用请求（`X-AI-Call: true`标记）
4. 网关代理调用DeepSeek API，返回结果给本地Docker
5. 本地Docker组装完整响应，经网关返回小程序

#### 专业版身份验证流程

**JWT验证5步流程**：

```
步骤1: 用户开通 → 授权确认 → 激活专业版身份
步骤2: 用户登录/同步 → 本地Docker获取JWT → 存储
步骤3: 每次AI调用 → relay_client携带JWT → 网关 /auth/verify 验证
步骤4: 网关验证通过 → 缓存JWT（有效期内存） → 放行AI请求
步骤5: JWT即将过期 → relay_client自动刷新 → 无感续期
```

**JWT payload结构**：

```json
{
  "user_id": "u_xxx",
  "plan_type": "pro",
  "exp": 1718123456,
  "iat": 1718037056
}
```

**隐私声明**：

> ⚠️ **联网仅验证授权身份，不传关系数据**
>
> 专业版身份验证过程中，网络传输仅包含JWT令牌（用户ID+授权状态+有效期），**不传输任何关系数据、事件记录、实体信息或AI对话内容**。业务数据始终存储在用户本地Docker中，网关仅做加密转发，不解析、不存储业务payload。

**网关AI计数限流**：

```python
# 网关AI计数逻辑（伪代码）
class AICounter:
    def check_and_deduct(self, user_id: str, estimated_tokens: int) -> CounterResult:
        remaining = self.get_monthly_remaining(user_id)
        if remaining < estimated_tokens:
            return CounterResult(allowed=False, status="red")
        self.deduct(user_id, estimated_tokens)
        if remaining - estimated_tokens < WARNING_THRESHOLD:
            return CounterResult(allowed=True, status="yellow")
        return CounterResult(allowed=True, status="green")
```

**用户可见状态（不暴露Token数）**：

| 状态 | 含义 | UI表现 |
|------|------|--------|
| 🟢 绿灯 | 本月额度充足 | 正常使用 |
| 🟡 黄灯 | 额度即将用尽 | 提示"本月AI调用接近上限" |
| 🔴 红灯 | 额度已用尽 | 拒绝AI调用，降级提示"本月AI额度已用完，基础功能仍可使用" |

### 8.7.5 网关高可用与降级

**降级策略**：

```
网关正常:
  小程序 ←→ 网关 ←→ 本地Docker    （专业版完整功能）

网关故障:
  自动降级 → 局域网H5访问          （基础版功能）
  ┌─────────────────────────────────────┐
  │ relay_client检测网关断连            │
  │   → 启动本地AI Key（如有配置）      │
  │   → 开放局域网H5访问端口           │
  │   → 推送通知用户切换H5访问          │
  └─────────────────────────────────────┘

网关恢复:
  relay_client自动重连 → 无缝切换回专业版模式
```

**降级行为明细**：

| 事件 | relay_client行为 | 用户感知 |
|------|------------------|----------|
| 网关断连 | 检测超时→标记offline | 小程序显示"服务暂时不可用" |
| 网关offline | 切换本地AI Key（如有） | H5可继续使用AI功能 |
| 网关offline | 开放局域网H5端口 | 用户可通过浏览器访问 |
| 网关恢复 | 自动重连→切换回relay模式 | 小程序自动恢复，无需操作 |

**JWT刷新失败降级策略**：

专业版依赖JWT与网关维持身份认证，JWT刷新失败时需有明确的降级路径，避免用户完全无法使用AI功能。

```
JWT正常生命周期:
  获取JWT → 缓存本地 → 过期前5分钟自动刷新 → 继续使用

JWT刷新失败:
  ┌──────────────────────────────────────────────────────┐
  │ 1. JWT过期前5分钟尝试刷新                              │
  │ 2. 刷新失败：重试3次（间隔1s/2s/4s）                   │
  │ 3. 3次均失败：降级为基础版模式（使用本地API Key，如已配置）│
  │ 4. 降级后每5分钟尝试重新验证                           │
  │ 5. 重新验证成功：自动切回专业版模式                     │
  │ 6. 降级期间UI显示"当前使用本地AI，部分功能受限"提示      │
  └──────────────────────────────────────────────────────┘
```

**JWT刷新失败降级行为明细**：

| 阶段 | relay_client行为 | 用户感知 |
|------|------------------|----------|
| JWT过期前5分钟 | 主动发起刷新请求 | 无感知 |
| 刷新失败第1次 | 1秒后重试 | 无感知 |
| 刷新失败第2次 | 2秒后重试 | 无感知 |
| 刷新失败第3次 | 4秒后重试 | 无感知 |
| 3次均失败 | 降级为基础版模式（本地API Key） | UI提示"当前使用本地AI，部分功能受限" |
| 降级期间 | 每5分钟尝试重新验证网关身份 | 后台静默进行 |
| 重新验证成功 | 自动切回专业版模式（网关代理AI） | 提示"已恢复专业版模式"，UI提示消失 |
| 无本地API Key | AI功能不可用 | UI提示"网络异常，AI功能暂不可用" |

### 8.7.6 安全约束

**数据不落地原则**：

| 数据类型 | 网关是否存储 | 说明 |
|----------|-------------|------|
| 业务数据（事件/实体/关联/Todo） | ❌ 不存储 | 仅透传，网关不解析payload |
| user_token → connection映射 | ✅ 内存存储 | 连接断开即清除，不持久化 |
| AI调用计数 | ✅ 持久化 | user_id → 本月已用Token数 |
| AI响应内容 | ❌ 不存储 | 透传后丢弃 |

**传输安全**：
- WebSocket使用 **WSS加密**（TLS 1.2+）
- 网关域名配置合法证书（Let's Encrypt / 商业证书）

**身份认证**：
- `user_token` 使用 **JWT签名**，防伪造
- JWT payload: `{user_id, plan_type, exp, iat}`
- 网关验证JWT签名 + 过期时间，拒绝非法token

**API Key隔离**：
- AI调用经网关代理，本地Docker **不直接暴露** DeepSeek API Key
- 网关持有DeepSeek API Key，本地Docker只发"AI调用请求"
- 基础版用户自带Key存本地，专业版Key由网关统一管理

**Open Core模型与隐私保证**：

| 层级 | 开源状态 | 许可证 | 包含组件 |
|------|----------|--------|----------|
| 基础版 | ✅ 开源 | MPL 2.0 | 本地Docker全部代码（FastAPI+5步引擎+数据模型+H5前端） |
| 专业版 | 🔒 闭源 | 商业许可 | 中继网关+微信小程序+云端AI代理 |

> 🔑 **开源是隐私声明的技术保证**
>
> 基础版以 MPL 2.0 开源，用户可自行审计以下关键行为：
> - 本地Docker **不会**在用户不知情的情况下向外部发送数据
> - AI调用路径明确：基础版仅走本地Key，专业版经网关代理时仅传输JWT+AI请求
> - 所有数据存储在本地SQLite，无隐藏外传逻辑
>
> 专业版闭源组件（网关/小程序）运行在服务端，不接触用户原始业务数据，仅做加密转发。用户可对照开源基础版代码验证"数据不落地"承诺的完整性。

---

## 9. 交付阶段实现范围

### 9.0 PoC（3周，验证核心假设）

**目标**：验证AI能否从互动记录提取关注点+识别承诺+生成帮助建议，形成承诺兑现闭环

**定位**：个人商务关系经营助手——先成就关系，再促成合作

| 模块 | 范围 | 说明 |
|------|------|------|
| 事件接入 | card_save + meeting + manual 3管线 | 名片扫描、会议纪要、自由文本 |
| 实体抽取 | Person + Organization | 不含Topic/Event |
| 实体归一 | 5步算法 | 无人工确认UI |
| 关联发现 | 共现+类型推断 | 不含角色标签 |
| Todo生成 | 6种类型（care/promise/help/followup/cooperation_signal/risk） | v2.0关系视角 |
| 关注提取 | JSONB concern字段 | AI提取→用户确认→持久化 |
| 承诺识别 | JSONB promise字段 | AI提取→用户确认→持久化 |
| 帮助记录 | JSONB contribution字段 | 用户手动记录或AI建议→确认 |
| 匹配算法 | **暂不启用六维匹配** | PoC做承诺兑现闭环（PromiseFulfillmentEngine） |
| AI输出规则 | §4.9 AI输出语言规则 | 推断标记+确认机制 |
| 前端 | API + Swagger UI | 无小程序 |
| 部署 | Docker单机 | 无Redis(内存缓存) |
| 认证 | API Key | 无JWT |
| CarryMem | NullMemoryProvider | 不接入 |

**PoC退出条件**（v2.0：产品指标为主）：

技术指标（通过线）：
1. 实体抽取准确率≥90%（100条样本）
2. 实体归一误合并率<5%
3. 端到端延迟：名片→Todo<5秒，会议→Todo<60秒

产品指标（成功判断）：
4. 愿意录入至少5次真实互动的用户比例≥70%
5. 对方关注点提取确认率≥70%
6. 用户承诺提取确认率≥80%
7. 提醒后用户完成承诺/帮助行动比例≥50%
8. 完成后填写反馈比例≥50%
9. 用户认为产品使自己更不易失约≥70%
10. 4周持续使用率≥60%
11. 愿意进入体验的用户≥3位

### 9.1 专业版MVP核心（PoC后4周）

1. **事件接入**：4管线（card_save/meeting/call/manual）
2. **实体抽取**：LLM提取Person/Organization/Topic
3. **实体归一**：5步算法+人工确认
4. **关联发现**：共现+类型推断+角色标签推荐
5. **Todo生成**：6种类型（care/promise/help/followup/cooperation_signal/risk）+状态追踪
6. **Person画像**：专业版维度（基础+沟通+决策+concern/promise/contribution+关系）
7. **关注提取**：concern JSONB + AI提取→用户确认
8. **承诺识别**：promise JSONB + AI提取→用户确认
9. **帮助记录**：contribution JSONB + AI建议→用户确认
10. **双向价值关系卡**：Person详情页"关系"Tab（替代原"资源供给卡"）
11. **care维度匹配**：关注点交集匹配（CareMatchEngine）
12. **值得关心提醒**：未兑现承诺+长期未互动
13. **资源透支提醒**：语言改为"先反馈或先提供价值"
14. **早间简报+晚间汇总**
15. **名片小程序**：原生页面(今日日程/语音录入/TTS播报) + H5(画像查询/数据管理)
16. **推送通知**：微信服务号+APNs/FCM+防打扰策略
17. **CSV导入**：冷启动刚需（从MVP-Plus提前）
18. **TTS播报**：微信同声传译插件+隐私分级（从MVP-Plus提前）
19. **认证**：JWT RS256+临时授权码+Refresh Token
20. **AI输出规则**：§4.9全部实施（推断标记+确认机制+语言规则）

### 9.2 专业版Plus（核心后2-3周）

21. 关系图谱可视化（H5）
22. 模糊查找与交叉检索
23. 日程管理（仅本地日程，不含外部同步）
24. 安全校验与敏感词过滤
25. 数据导出
26. 文本会议纪要录入支持
27. 合作档案Excel导入（仅目标用户）

### 9.3 定制版（持续迭代——资源经营能力）

- Resource/Demand/MatchOpportunity拆为独立表
- 完整八维匹配算法（含callability降权+care_overlap+promise_fulfillment）
- 引荐话术生成
- 日历双向同步（Apple/Google/企业微信/飞书）
- 录音卡深度集成（恒智易R1）
- 竞对预警/风险提示
- 图数据库(Neo4j)替代关联表
- 向量语义搜索(pgvector)
- Watch/邮件/录音卡触达通道
- 小程序原生页面替代H5
- TTS升级：讯飞/Azure
- 外部数据源（LinkedIn/企查查）
- 操作历史记录（非RBAC审计）
- 合作结果复用
- 关系冷却和透支保护

**明确排除**（私密助手不需要，各阶段均不规划）：
- ❌ RBAC权限模型 / 资源授权共享 / 团队协作
- ❌ 他人可提供资源匹配（只能匹配自己人脉的供给）
- ❌ 多租户隔离 / 企业管理看板
- ❌ 跨项目/跨团队资源撮合
- ❌ resource_permissions表 / 跨用户资源访问控制
- ❌ AI自动判定对方资源 / AI自动建议索取 / AI自动撮合 / AI自动发送消息

---

#### 9.3a v2.4代码改动量精确估计（v2.4新增，Coder建议）

总代码改动量：**~400-500行**新增/修改（比之前估计的300-400行多）

| 文件 | 改动量 | 说明 |
|------|--------|------|
| `input_classifier.py` | ~80行新文件 | InputClassifier类+8种scope枚举 |
| `todo_generator.py`修改 | ~60行 | _extract_promises重写+截断逻辑 |
| `relationship_brief.py` | ~120行新文件 | model+service+API |
| `relationship_stage_machine.py` | ~80行新文件 | 7阶段枚举+状态机+乐观锁 |
| `text_utils.py`(redact_pii) | ~30行新增 | redact_pii_from_text()函数 |
| `day_view API` | ~50行新文件 | 日视图API端点 |
| 各文件import/配置调整 | ~80行 | 新模块注册+路由配置 |

## 10. 与CarryMem解耦的验证清单

| 检查项 | 验证方法 | 通过标准 |
|--------|----------|----------|
| PromiseLink可独立启动 | 不安装CarryMem，启动PromiseLink API | 所有核心API可用 |
| NullMemoryProvider降级 | 配置memory_provider=null | 功能不缺失，仅缺少偏好增强 |
| CarryMem升级不影响PromiseLink | CarryMem API变更后 | PromiseLink仅需修改Adapter，核心逻辑不变 |
| PromiseLink数据模型独立 | 检查import | 无`from carrymem import`在核心模块中 |
| 可独立测试 | pytest without CarryMem | 测试覆盖率≥80% |

---

## 11. 技术启发：Understand-Anything对PromiseLink的架构借鉴

> **参考项目**：[Lum1104/Understand-Anything](https://github.com/Lum1104/Understand-Anything) (44.8K★)
> **核心定位**：代码知识图谱驱动的AI学习与开发平台
> **关键理念**："Graphs that teach, not graphs that impress"

### 11.1 架构对映

Understand-Anything处理的是**代码实体**（文件/函数/类）及其**依赖关系**（调用/继承/引用），PromiseLink处理的是**商务实体**（人物/组织/话题）及其**关联关系**（共现/合作/引荐）。两者本质都是**实体-关系图谱+AI语义增强**。

| UA概念 | PromiseLink对映 | 差异 |
|--------|--------------|------|
| 代码文件 | 人物/组织实体 | EL实体有画像属性 |
| 函数调用关系 | 共现/合作关联 | EL关联有强度和角色 |
| 依赖图 | 关系图谱 | EL图谱有时间维度 |
| Diff影响分析 | 关系变化影响分析 | EL需考虑隐私 |
| .agentic上下文导出 | 会前简报包 | EL需TTS/推送多格式 |
| 角色自适应UI | 用户角色适配 | EL按商务角色而非技术角色 |

### 11.2 启发1：会前简报包（专业版实现）

**UA做法**：将代码库上下文打包为`.agentic`文件，AI工具加载后获得100%准确的项目上下文。

**PromiseLink借鉴**：会前简报包 = 目标人物的所有关联上下文一次生成、多处复用。

```python
class PreMeetingBriefingPack:
    def generate(self, person_id: str, user_id: str) -> dict:
        person = self.db.get_entity(person_id)
        associations = self.db.get_associations(person_id)
        recent_events = self.db.get_recent_events(person_id, days=90)
        active_todos = self.db.get_active_todos(person_id)
        upcoming = self.db.get_upcoming_meetings(person_id)

        return {
            "person_summary": self._summarize_person(person),
            "relationship_snapshot": self._snapshot_relations(associations),
            "recent_timeline": self._build_timeline(recent_events),
            "action_items": self._format_todos(active_todos),
            "upcoming_meetings": self._format_meetings(upcoming),
            "tts_script_basic": TTSScriptComposer().compose(person, "basic"),
            "tts_script_standard": TTSScriptComposer().compose(person, "standard"),
            "push_summary": PushContentPolicy().render_brief(person),
        }

    def _summarize_person(self, person: Entity) -> dict:
        return {
            "name": person.name,
            "company": person.company,
            "title": person.title,
            "relationship_stage": person.properties.get("relationship", {}).get("strength"),
            "preferred_channel": person.properties.get("communication", {}).get("preferred_channel"),
            "last_contact_days": self._days_since_last_contact(person.id),
        }

    def _snapshot_relations(self, associations: list) -> list:
        return [
            {
                "target": a.target_entity.name,
                "type": a.association_type,
                "role": a.properties.get("role"),
                "strength": a.properties.get("strength"),
            }
            for a in associations[:10]
        ]
```

**复用场景**：

| 消费方 | 使用字段 | 格式 |
|--------|----------|------|
| TTS播报 | tts_script_basic/standard | 音频流 |
| 小程序卡片 | person_summary + action_items | JSON→UI |
| 微信推送 | push_summary | 模板消息 |
| H5画像页 | 全部 | JSON→Vue组件 |
| 早间简报 | person_summary + upcoming_meetings | 模板消息 |

**缓存策略**：简报包生成后缓存1小时（与TTS缓存同步失效），画像更新时清除。

### 11.3 启发2：关系图谱交互设计（专业版Plus实现）

**UA做法**：力导向图 + 点击节点展开详情 + 社区聚类 + Guided Tour。

**PromiseLink借鉴**：

```
图谱节点设计：
  人物节点：圆形，大小=关联数量，颜色=关系阶段(新认识→深合作)
  组织节点：方形，大小=人物数量
  话题节点：菱形

图谱边设计：
  粗细=关联强度(1-5)
  颜色=关联类型(合作=蓝/引荐=绿/竞争=红)
  虚线=AI推断的潜在关联

交互设计：
  点击人物 → 展开画像卡片(右侧抽屉)
  拖拽人物 → 调整布局
  双击组织 → 展开组织内所有人物
  右键 → 快速操作(发微信/添加Todo/语音播报)

社区聚类：
  自动发现"供应链圈""投资圈""校友圈"
  同圈人物用背景色区分

Guided Tour（按关系亲疏导览）：
  "这是您最亲密的5位合作伙伴..."
  "这3位是最近2周未联系的，建议关注..."
  "这2位之间有您不知道的共同联系人..."
```

**技术选型**：D3.js force-directed graph（专业版H5）→ 小程序Canvas（定制版原生）。

### 11.4 启发3：关系变化影响分析（定制版实现）

**UA做法**：代码diff→受影响函数→可视化影响范围。

**PromiseLink借鉴**：实体属性变化→受影响关联和Todo→生成影响报告。

```python
class RelationshipImpactAnalyzer:
    def analyze_change(self, change_event: dict) -> dict:
        entity_id = change_event["entity_id"]
        change_type = change_event["change_type"]

        affected_associations = self._find_affected_associations(entity_id, change_type)
        affected_todos = self._find_affected_todos(entity_id, change_type)
        new_opportunities = self._discover_opportunities(entity_id, change_type)
        risks = self._assess_risks(entity_id, change_type)

        return {
            "change": change_event,
            "affected_associations": affected_associations,
            "affected_todos": affected_todos,
            "new_opportunities": new_opportunities,
            "risks": risks,
            "recommended_actions": self._generate_actions(
                affected_associations, affected_todos, new_opportunities, risks
            ),
        }

    def _discover_opportunities(self, entity_id, change_type):
        if change_type == "company_change":
            new_company = self.db.get_entity(entity_id).company
            return self.db.find_path_to_company(entity_id, new_company)
        return []
```

**典型场景**：

| 变化事件 | 影响分析 | 建议行动 |
|----------|----------|----------|
| 张总跳槽A→B | A公司3条关联降级，B公司2条新关联 | 更新画像+重新评估A关系+发现B新机会 |
| 王总3个月未联系 | 关联强度衰减，遗忘曲线下降 | 推送维护提醒+推荐话题 |
| 李总引荐赵总 | 新关联+2跳路径发现 | 自动建立关联+生成跟进Todo |

### 11.5 启发4：角色自适应UI（定制版实现）

**UA做法**：初级开发者看简化视图，PM看业务流程，资深工程师看完整依赖。

**PromiseLink借鉴**：不同商务角色看到不同粒度。

| 用户角色 | 视图特征 | 默认功能 |
|----------|----------|----------|
| 老板/高管 | 极简：关键人物+风险提示+行动建议 | 今日日程+TTS播报+推送 |
| 销售经理 | 标准：完整画像+沟通偏好+商机评分 | 画像查询+名片扫描+Todo |
| BD/商务 | 网络：关系路径+资源网络+推荐话题 | 关系图谱+路径搜索+引荐请求 |
| 助理/秘书 | 执行：日程管理+会议安排+信息录入 | 日程+录入+数据管理 |

**实现方式**：用户首次使用时选择角色，后续可切换。角色影响默认视图、推送频率、TTS播报详细度。

### 11.6 启发5：向量语义搜索（定制版实现）

**UA做法**：向量化索引+自然语言问答。

**PromiseLink借鉴**：

```python
class SemanticSearchEngine:
    def __init__(self):
        self.embedder = EmbeddingProvider()  # text-embedding-3-small
        self.vector_store = pgvector  # PostgreSQL pgvector扩展

    async def search(self, query: str, user_id: str, top_k: int = 10) -> list:
        query_embedding = await self.embedder.embed(query)
        results = await self.db.execute("""
            SELECT e.*, 
                   1 - (e.embedding <=> $1) as similarity
            FROM entities e
            WHERE e.user_id = $2
            ORDER BY e.embedding <=> $1
            LIMIT $3
        """, query_embedding, user_id, top_k)
        return results

    async def search_events(self, query: str, user_id: str) -> list:
        query_embedding = await self.embedder.embed(query)
        return await self.db.execute("""
            SELECT ev.*, 
                   1 - (ev.embedding <=> $1) as similarity
            FROM events ev
            WHERE ev.user_id = $2
              AND ev.embedding IS NOT NULL
            ORDER BY ev.embedding <=> $1
            LIMIT 10
        """, query_embedding, user_id)
```

**查询示例**：
- "上次和张总聊代工厂的事" → 语义匹配 → 定位3月15日会议纪要
- "谁认识华为的人" → 关系路径搜索 → 张总→李总→华为王总（2跳）
- "最近有什么合作机会" → 商机匹配度排序 → Top 5建议

**技术选型**：PostgreSQL pgvector扩展（定制版），无需额外引入向量数据库。

### 11.7 启发6：商业域映射（定制版实现）

**UA做法**：domain-analyzer Agent从代码中提取业务域、流程和步骤。

**PromiseLink借鉴**：从零散事件中识别商业域和业务流程。

```
事件流：
  "和张总聊了代工厂" 
  "李总提到供应链优化"
  "赵总推荐了3个供应商"
  ↓ domain-analyzer ↓
商业域：供应链管理
  流程：供应商寻源 → 评估筛选 → 合作对接
  关键人物：张总(决策)、李总(评估)、赵总(引荐)
  待完成步骤：评估筛选（当前卡点）
```

**与YAML配置化分类法的关系**：§6的角色分类和会议类型是**预定义的分类法**，商业域映射是**从数据中自动发现**的分类法。两者互补——预定义保证一致性，自动发现捕捉意外。

### 11.8 启发优先级与阶段分配

| 启发 | 价值 | 难度 | 实现阶段 | 依赖 |
|------|------|------|----------|------|
| 会前简报包 | ⭐⭐⭐⭐⭐ | 低 | **专业版** | TTSScriptComposer |
| 关系图谱交互 | ⭐⭐⭐⭐ | 中 | 专业版Plus | D3.js |
| 关系变化影响分析 | ⭐⭐⭐⭐ | 高 | 定制版 | 事件历史+关联强度计算 |
| 角色自适应UI | ⭐⭐⭐ | 中 | 定制版 | 用户角色配置 |
| 向量语义搜索 | ⭐⭐⭐ | 高 | 定制版 | pgvector扩展 |
| 商业域映射 | ⭐⭐ | 高 | 定制版 | 大量事件数据+LLM |

---

## 12. 变更记录

| 版本 | 日期 | 变更内容 | 作者 |
|------|------|----------|------|
| v2.6 | 2026-06-06 | 新增洞察引擎层+数据接入层架构：①§2.1架构图新增Insight Engine服务②§2.2服务拆分表新增Insight Engine行③§3.1 todos表DDL新增completed_rank/dynamic_score/score_calculated_at字段+索引④§4.10新增洞察引擎设计（动态评分器PriorityScorer+隐式反馈收集器ImplicitFeedbackCollector+Todo模型扩展+API变更）⑤§4.11新增数据接入层设计（DataSourceAdapter接口+邮件场景数据流+微信生态约束） | CarryMem团队 |
| v2.7 | 2026-06-06 | Phase 1动态优先级四维演进：①§4.10.1a新增Phase 1四维评分器详细设计（依赖性全图谱路径分析+场景匹配Event表驱动）②依赖性算法：有向依赖图+阻塞链检测+3跳间接依赖+dependency_score=Σ(1/depth)×blocked_weight③场景匹配算法：未来24h meeting/call扫描+Entity匹配+context_score=max(0,1-hours/24)④权重配置Phase1(0.3/0.35/0.2/0.15) | CarryMem团队 |
| v3.2 | 2026-06-11 | §8.7.4 AI调用路径升级为三场景模型+专业版身份验证流程+§8.7.6 Open Core模型：①§8.7.4 AI调用路径从双路径升级为三场景模型（场景1:纯基础版→浏览器局域网→本地模型/自带Key→完全离线；场景2:已开通专业版+在家用浏览器→浏览器局域网→云端AI我方Key→身份已激活；场景3:已开通专业版+出门用小程序→微信小程序→云端AI我方Key→正常路径）②§8.7.4新增专业版身份验证流程子节（JWT验证5步流程:开通→登录同步→/auth/verify→缓存JWT→自动刷新+JWT payload结构+隐私声明:联网仅验证授权身份不传关系数据）③§8.7.6安全约束新增Open Core模型与隐私保证（基础版开源MPL 2.0代码可审计+专业版闭源中继网关/小程序/云端AI+开源是隐私声明的技术保证） | CarryMem团队 |
| v3.1 | 2026-06-11 | 网关中继架构（专业版）设计：①§8.7.1架构概览（三层产品模型L1基础版/L2专业版/L3定制版+用户PC←WSS→云VPS网关←HTTPS→微信小程序架构图+网关不存业务数据只做加密转发+AI代理+计数限流）②§8.7.2基础版vs专业版Docker区别（专业版新增relay_client+Docker Compose差异表）③§8.7.3网关中继协议（WebSocket长连接出站+request/response/ping消息格式+user_token路由映射+30s心跳+60s超时+指数退避重连）④§8.7.4 AI调用路径（基础版本地Key vs 专业版网关代理DeepSeek+X-AI-Call标记+绿灯/黄灯/红灯状态不暴露Token数）⑤§8.7.5网关高可用与降级（网关故障自动降级基础版H5+本地AI Key回退+网关恢复自动重连）⑥§8.7.6安全约束（数据不落地+WSS加密+JWT签名防伪造+API Key隔离） | CarryMem团队 |
| v3.0 | 2026-06-11 | F-67/F-68/F-69三大功能设计：①§4.13新增F-67 RelationshipBrief关系推进卡前端对接（API路径修正/类型定义对齐/去除Mock回退/数据流说明）②§4.14新增F-68 Promise兑现状态追踪（Todo新增fulfillment_status/fulfilled_at/overdue_notified_at字段+fulfillment_status与status正交设计+step_05/step_08 Pipeline扩展+my_promise自动overdue/their_promise手动标记安全约束+PromiseBoardService+FulfillmentTracker模块+明确不实现关系信用分）③§4.15新增F-69智能跟进提醒（reminder_preferences表+reminder_logs表+提醒时机算法+疲劳度控制≤5条/日+静默时段22:00-08:00+APScheduler调度架构+4种提醒类型+ReminderEngine+FatigueController模块） | CarryMem团队 |
| v2.9 | 2026-06-09 | 托管PoC部署模式设计：①§8.6.2部署架构图更新为双路径（自助PoC+托管PoC）②§8.6.3a新增托管PoC部署模式（云服务器2C4G+Docker Compose+Nginx反向代理+Let's Encrypt HTTPS+SQLite+微信小程序接入）③新增自助PoC vs 托管PoC对比表（部署位置/访问方式/运维责任/成本/数据存储/TLS/域名）④§8.6.6新增托管PoC→Phase1迁移路径（SQLite导出→SQL方言转换→PG导入→docker-compose切换→DNS切换+零停机+回滚方案） | CarryMem团队 |
| v2.8 | 2026-06-06 | 向量化语义能力设计（对应PRD v4.7）：①§4.12新增向量化语义引擎设计（5子节）②§4.12.1 EmbeddingProvider（Moka AI API+text-embedding-3-small+API模式768维/本地降级384维+缓存策略+批量接口）③§4.12.2 SemanticSearchEngine（语义搜索接口+SearchResult+余弦相似度）④§4.12.3 sqlite-vec存储设计（vector_embeddings表+vec_entities虚拟表+Phase2迁移pgvector路径）⑤§4.12.4 关联发现增强F-58（混合得分0.7×structured+0.3×semantic+阈值0.7）⑥§4.12.5 Pipeline集成点（Step5.5 Entity embedding+Step11.5语义相似度增强） | CarryMem团队 |
| v1.0 | 2026-06-02 | 初始版本：4表数据模型+5步引擎+CarryMem解耦+YAML配置化+API设计 | CarryMem团队 |
| v1.1 | 2026-06-02 | 小程序整合：§2.1架构图+§2.2 Mini/Notify服务+§2.3前端架构+H5通信协议+TTS服务 | CarryMem团队 |
| v1.2 | 2026-06-02 | 7角色审核P0修复：①临时授权码模式替代明文token②语音录入/TTS走小程序原生③TTS播报模板+隐私分级④微信推送分级⑤PG列索引+CarryMem协议补充+JWT认证+资源预估 | CarryMem团队 |
| v1.3 | 2026-06-02 | 7角色审核P1修复：①JWT密钥管理+Refresh Token+审计日志②H5↔原生数据同步协议(Storage+onShow)③TTS缓存策略(Redis+URL签名+降级链)④PG列索引同步触发器⑤§9 PoC/Phase1/Phase2三阶段划分+退出条件⑥备份策略+监控指标+数据增长预估 | CarryMem团队 |
| v1.4 | 2026-06-02 | Understand-Anything技术启发：①§11新增6项架构借鉴②会前简报包(PreMeetingBriefingPack)一次生成多处复用③关系图谱交互设计(D3.js力导向图+社区聚类+Guided Tour)④关系变化影响分析(RelationshipImpactAnalyzer)⑤角色自适应UI(4种商务角色)⑥向量语义搜索(pgvector)⑦商业域映射(domain-analyzer)⑧启发优先级与阶段分配 | CarryMem团队 |
| v1.5 | 2026-06-02 | WorkBuddy审阅+7角色共识修订：①§4.4实体归一5步算法补齐(EntityResolutionEngine+4步阈值+ResolutionResult)②§4.5商机匹配度五维算法补齐(OpportunityMatcher+keyword/industry/topic/llm/history)③§4.6 Todo状态机补齐(5状态+VALID_TRANSITIONS+snooze定时恢复+snooze_schedules表)④§4.7关联强度时间衰减函数补齐(λ=0.01指数衰减+类型基础分+衰减下限)⑤§4.8 PoC存储方案SQLite(SQLAlchemy+兼容性workaround表)⑥§4.3 same_city推断逻辑补齐(城市别名归一化)⑦raw_text 500KB CHECK约束⑧5项文档矛盾对齐 |
| v1.6 | 2026-06-02 | 李总资源匹配建议+定位校准（7角色共识修订）：①§4.5五维→六维匹配算法（新增callability可调用度维度权重20%）②§4.5新增资源敏感度2级过滤③§3.1 entities表properties增加resource/demand④§3.1 todos表todo_type新增🟡🟣⑤§9 PoC目标增加"识别资源线索"⑥§9 Phase1增加5项资源功能⑦§9 Phase2移除RBAC/多租户，新增向量搜索/操作历史⑧§9新增"明确排除"清单 | CarryMem团队 |
| v1.7 | 2026-06-02 | 部署模型与数据主权决策（7角色共识）：①新增§8.6部署架构与数据主权章节②§8.6.1明确"不做原生APP"决策③§8.6.2阶段递进式部署架构图（PoC本地→Phase1云端→Phase2集群）④§8.6.3 PoC Docker单机部署方案+docker-compose.poc.yml⑤§8.6.4 Phase1 Docker Compose部署方案+docker-compose.phase1.yml⑥§8.6.5数据主权6原则技术实现表+PoC/Phase1数据安全方案⑦§8.6.6 PoC→Phase1迁移方案（SQLAlchemy零改动+迁移脚本） | CarryMem团队 |
| v2.1 | 2026-06-03 | 7角色架构评审补齐：①§8.0.6新增数据库迁移策略（Alembic+5条铁律+PoC→Phase1迁移方案+迁移版本管理表）②API版本管理策略详见API_Design §8（v1.3） | CarryMem团队 |
| v2.5 | 2026-06-04 | 文档一致性Bugfix（3项）：①BLK-3修复：todos表action_type DEFAULT值从self_commitment修正为my_promise，CHECK约束同步更新为6种新枚举值②F-49 API路径对齐：PRD中day-view端点从/api/v1/events/day-view统一为/api/v1/dashboard/day-view（与技术设计一致）③PATCH /stage乐观锁完善：relationship_briefs表DDL新增version字段(INTEGER NOT NULL DEFAULT 1)，伪代码补充完整StageUpdateRequest schema+version校验+409冲突响应+version自增逻辑 | DevSquad Coder+Arch |
| v2.4 | 2026-06-04 | 融入许总PoC反馈+Security 2项P0阻塞修复+7角色全员Review意见采纳：①§3.1a新增PII字段安全策略（evidence_quote脱敏+redact_pii_from_text）②Step0 InputClassifier增加SC-01安全约束（服务端强制校验input_scope）③§7.2新增日视图API（F-49, day-view端点）④§4.3关联发现引擎增加主题网络视角（术语映射表+D3.js可视化）⑤§5.2a新增CarryMem终身能力技术路径（Phase1/Phase2规划+数据导出）⑥§7.1c-plus新增语音交互技术方案（ASR/TTS选型+PoC Mock验证）⑦todos表DDL增加evidence_event_id字段（证据溯源）⑧RelationshipBrief PATCH /stage API增加乐观锁（updated_at校验）⑨监控章节增加4项P0业务指标（histogram/counter）⑩§9.3a新增代码改动量精确估计（~400-500行分文件明细） | DevSquad 7角色 |
| v2.3 | 2026-06-04 | 李总v1.2建议融合修订：①§3.1数据模型新增relationship_briefs表+events.input_scope+todos双向字段+entities.relationship_stage ②§4.1管线新增Step0 input_scope分类器+Step8 RelationshipBrief更新 ③新增RelationshipStage状态机（7阶段枚举+转换规则+RS-01用户确认强制）④§7.1新增6个P0 API端点 ⑤§2.3新增自建小程序备选方案(Taro) ⑥Promise双向动作模型技术实现 | DevSquad PM+Arch |
| v2.2 | 2026-06-03 | 7角色架构评审P0缺口补齐：①§8.0.7新增结构化日志规范（structlog+JSON格式+必填/可选字段+脱敏规则+PoC日志配置）②§8.0.8新增统一错误处理与降级策略（异常类层次+降级决策矩阵+FastAPI全局异常处理器+熔断器规范） | CarryMem团队 |
| v2.0 | 2026-06-03 | 定位演化共识修订——从"资源经营"到"关系经营"（林总审定+李总3版建议整合）：①§1.1核心闭环从"事件驱动"改为"互动驱动"，闭环更新为"互动记录→关注提取→承诺识别→帮助建议→反馈追踪"②§3.1 Todo类型DDL全面更新（opportunity→cooperation_signal, context→care, action→promise, pending_confirm→followup, resource_maint→help, risk保留）+todo_type VARCHAR(25)+CHECK约束③§3.2 Person.properties新增concern/promise/contribution三个JSONB字段（替代原resources字段，resource/demand保留供Phase2）④§4.1 Step5 Todo生成改为关系视角⑤§4.5匹配算法改为分阶段策略：PoC承诺兑现闭环(PromiseFulfillmentEngine)→Phase1 care维度匹配(CareMatchEngine)→Phase2完整八维匹配(callability降权20%→10%+新增care_overlap 10%+promise_fulfillment 10%)⑥§4.9新增AI输出语言规则（6项禁止行为+7项允许行为+正确/错误示例+输出标记规范[待确认]/[AI推测]/[用户确认]+持久化规则）⑦§7.2 API响应示例更新（todo_nature→todo_type, resources→concern/promise/contribution）⑧§9 PoC退出条件改为产品指标为主（8项产品指标+3项技术指标）⑨§9 Phase1新增care维度匹配+双向价值关系卡+AI输出规则实施⑩§9 Phase2新增Resource/Demand独立表+八维匹配+引荐话术+合作结果复用+关系冷却保护⑪§9明确排除新增AI越界行为 | CarryMem团队 |
