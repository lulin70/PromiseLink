# EventLink 技术方案概览

> **2026-05-31 · 技术版 · V3.0**

## 系统架构

```
┌─────────────────────────────────────────────────────┐
│                   客户端层 (Client)                  │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐          │
│  │IAMHERE   │  │录音卡App  │  │Web仪表盘  │          │
│  │小程序    │  │(R1配套)  │  │(后续)    │          │
│  └─────┬────┘  └─────┬────┘  └─────┬────┘          │
│        │ HTTP/HTTPS      │             │              │
└────────┼─────────────────┼─────────────┘              │
         │                 │                            │
         ▼                 ▼                            │
┌─────────────────────────────────────────────────────┐
│                API Gateway (FastAPI)                 │
│  • JWT 认证  • 限流 (100 req/min)  • 日志审计        │
└─────────────────────┬───────────────────────────────┘
                      │
        ┌─────────────┼─────────────┐
        ▼             ▼             ▼
┌──────────────┐ ┌──────────┐ ┌──────────────┐
│ Event 接收   │ │ 实体抽取  │ │ 提醒查询     │
│ & 标准化     │ │ 服务      │ │ & 推送       │
│              │ │          │ │              │
│ POST /events │ │ LLM/规则  │ │ GET /alerts  │
│              │ │ 引擎     │ │ WebSocket    │
└──────┬───────┘ └────┬─────┘ └──────┬───────┘
       │               │               │
       ▼               ▼               ▼
┌─────────────────────────────────────────────────────┐
│                   核心引擎层                          │
│                                                     │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐          │
│  │实体归一   │→│ 关联发现  │→│ 提醒生成  │          │
│  │Engine    │  │ Engine   │  │ Engine   │          │
│  └──────────┘  └──────────┘  └──────────┘          │
│       ↑              ↑                           │
│  ┌────┴────┐   ┌────┴────┐                       │
│  │实体图谱  │   │规则引擎  │                       │
│  │NetworkX │   │Remind_* │                       │
│  └─────────┘   └─────────┘                       │
└─────────────────────┬───────────────────────────────┘
                      │
                      ▼
┌─────────────────────────────────────────────────────┐
│                    存储层                             │
│  PostgreSQL 15  │  Redis 7  │  MinIO (对象存储)      │
└─────────────────────────────────────────────────────┘
```

---

## 数据模型

### Event（事件）

```python
@dataclass
class Event:
    id: str                    # UUID v4
    event_type: str            # card_scan | meeting | call | manual
    source: str               # iamhere | recording_r1 | tencent_meeting
    title: str
    timestamp: datetime        # ISO 8601
    raw_text: str              # 原始内容
    entities: List[Entity]     # 抽取出的实体
    metadata: dict            # 扩展字段
```

### Entity（实体）

```python
@dataclass
class Entity:
    id: str                   # ent_uuid
    entity_type: str          # person | organization | technology | project | attribute
    name: str                 # 显示名称
    aliases: List[str]        # ["李总", "李明", "老李"]
    properties: dict          # {company, title, skills, ...}
    source_events: List[str]  # 来源事件ID列表
    created_at: datetime
    updated_at: datetime
```

### Association（关联）

```python
@dataclass
class Association:
    id: str                   # assoc_uuid
    source_entity: str        # 源实体ID
    target_entity: str        # 目标实体ID
    relation_type: str        # alumni | ex_colleague | competitor |
                              # tech_overlap | deal_link | risk_link | supply_chain
    strength: float           # 0.0 ~ 1.0 (关联强度)
    evidence: List[str]       # 支撑证据 [event_id, ...]
    discovered_at: datetime
    status: str               # active | stale | dismissed
```

### Alert（提醒）

```python
@dataclass
class Alert:
    id: str                   # alert_uuid
    alert_type: str           # opportunity | risk | context
    priority: str             # high | medium | low
    title: str
    detail: str
    suggestion: str           # 行动建议
    related_association: str  # 关联ID
    user_feedback: str        # useful | not_useful | dismissed | null
    created_at: datetime
    read_at: Optional[datetime]
```

---

## 核心 API 接口

### 上报事件

```http
POST /api/v1/events
Authorization: Bearer {token}
Content-Type: application/json

{
  "event_type": "card_scan",
  "source": "iamhere_digital_card",
  "title": "查看了李明的数字名片",
  "timestamp": "2026-05-31T14:00:00Z",
  "raw_text": "{\"name\":\"李明\",\"company\":\"XX科技\",\"title\":\"CTO\",\"skills\":[\"IoT\",\"边缘计算\"]}",
  "metadata": {
    "scanner_user_id": "user_001",
    "card_id": "card_12345"
  }
}

Response 201:
{
  "event_id": "evt_a1b2c3d4",
  "status": "processing",
  "estimated_completion": "5s"
}
```

### 查询今日提醒

```http
GET /api/v1/alerts/today?limit=10&type=opportunity,risk
Authorization: Bearer {token}

Response 200:
{
  "alerts": [
    {
      "id": "alert_x1y2z3",
      "type": "risk",
      "priority": "high",
      "title": "竞对关系预警",
      "detail": "您接触的AA科技与BB科技存在直接竞争",
      "suggestion": "沟通时注意信息边界",
      "association_id": "assoc_m5n6p7",
      "created_at": "2026-05-31T14:05:00Z"
    }
  ],
  "summary": {
    "total": 5,
    "by_type": {"opportunity": 3, "risk": 1, "context": 1},
    "unread_count": 2
  }
}
```

### 用户反馈

```http
POST /api/v1/alerts/{alert_id}/feedback
Authorization: Bearer {token}

{"feedback": "useful"}  // | "not_useful" | "dismissed"

Response 200:
{"status": "recorded", "thank_you": "反馈已记录，将优化推荐质量"}
```

---

## 核心算法流程

### 实体归一（Entity Resolution）

```
输入: 新实体 candidate = Entity(name="李总", company="XX科技")

Step 1: 精确匹配
  → SELECT * FROM entities WHERE name = '李总' AND company = 'XX科技'
  → 命中? → 返回已有实体 (confidence=1.0)

Step 2: 别名扩展查找
  → 别名字典: {"李总" → ["李明", "LM"], "李明" → ["李总", "老李"]}
  → 展开为候选集: [Entity(name="李明"), Entity(name="LM")]

Step 3: 上下文相似度
  → 对每个候选计算:
    • 公司名称匹配? (+0.3)
    • 职位/技能重叠? (+0.2)
    • 时间窗口内共现于同一Event? (+0.3)
    • 其他属性相似度? (+0.2)
  → 加权得分 > 0.85 → 视为同一人

Step 4: 不确定则标记 pending
  → confidence ∈ [0.7, 0.85] → 记录待确认
  → confidence < 0.7 → 创建新实体
```

### 关联发现（Association Discovery）

```
输入: 新事件 event (含实体列表 [e1, e2, e3])

对每对实体组合 (ei, ej):
  1. 检查是否已有关联?
     → 已有且 active → 更新 strength 和 timestamp
     → 已有但 stale → 重新评估是否激活

  2. 发现新关联:
     a) 共现频率分析
        → count(ei, ej co-occurred in last N events) / N
        → frequency_score = min(freq / threshold, 1.0)

     b) 类型推断 (基于实体属性)
        → ei.company == ej.company → ex_colleague (strength += 0.4)
        → ei.skills ∩ ej.skills ≠ ∅ → tech_overlap (strength += 0.3)
        → 竞品数据库匹配 → competitor (strength += 0.5)

     c) 时间衰减
        → strength *= exp(-λ * Δt)  (λ=0.01, 最近30天权重高)

     d) 过滤
        → strength > 0.3 → 保留
        → strength ≤ 0.3 → 丢弃

  3. 生成提醒 (仅对 high-value 关联)
     → new association && strength > 0.6 → 生成 Alert
     → risk type (competitor/risk_link) → 高优先级推送
     → opportunity type → 每日摘要聚合
```

---

## 技术栈

| 组件 | 选型 | 理由 |
|------|------|------|
| **API框架** | FastAPI (Python 3.11+) | 异步高性能，自动OpenAPI文档 |
| **数据校验** | Pydantic v2 | 类型安全，自动序列化 |
| **图算法** | NetworkX + igraph | 成熟图库，支持多跳查询 |
| **实体抽取** | OpenAI / Moka AI API | GPT-4o-mini 或 Claude Sonnet |
| **降级方案** | spaCy + 自定义词典 | 无API时规则引擎兜底 |
| **主数据库** | PostgreSQL 15 | JSONB支持，复杂查询能力强 |
| **缓存** | Redis 7 | 热点实体缓存，Session存储 |
| **任务队列** | Celery + Redis | 异步处理长耗时任务(LLM调用) |
| **对象存储** | MinIO / AWS S3 | 录音文件、附件存储 |
| **部署** | Docker Compose → K8s | 开发便捷，生产可扩展 |
| **监控** | Prometheus + Grafana | 指标采集和可视化 |

---

## 部署架构

```
开发环境 (PoC阶段):
  ┌─────────────────────────────┐
  │  Docker Compose (单机)      │
  │  ├── api (FastAPI)         │
  │  ├── worker (Celery)        │
  │  ├── postgres (PG15)        │
  │  ├── redis (Redis 7)        │
  │  └── minio (对象存储)       │
  └─────────────────────────────┘
  启动命令: docker compose up -d
  占用资源: <2GB RAM, <2核CPU

生产环境 (正式上线):
  ┌─────────────────────────────────────┐
  │  Kubernetes Cluster                  │
  │  ├── API: 3 replicas (HPA)          │
  │  ├── Worker: 5+ replicas            │
  │  ├── PostgreSQL: 主从 + PITR备份    │
  │  ├── Redis Sentinel (高可用)        │
  │  └── CDN + WAF (安全防护)           │
  └─────────────────────────────────────┘
  SLA: 99.9% 可用性
  P99延迟: API <500ms, 关联发现 <2s
```

---

## 安全设计

| 维度 | 方案 |
|------|------|
| **传输加密** | TLS 1.3 (强制HSTS) |
| **认证** | JWT (access_token:15min, refresh_token:7d) |
| **授权** | RBAC (admin/member/viewer) + 数据行级隔离 |
| **数据加密** | AES-256-GCM 字段级加密 (敏感属性) |
| **API Key** | 操作系统钥匙串存储 (Keychain/Credential Manager) |
| **审计日志** | 所有写操作记录 (操作人/IP/时间/内容) |
| **合规** | 支持数据导出(GDPR Art.20) / 删除(Art.17) / 撤回同意 |

---

## PoC 技术验证计划

### Week 1: 数据接入验证

**目标**: 名片JSON能否正确解析并产生实体

```
输入样例:
{
  "name": "李明",
  "company": "XX科技有限公司",
  "title": "CTO",
  "phone": "138****8888",
  "skills": ["IoT", "边缘计算", "传感器网络"],
  "education": "浙江大学 硕士 2010"
}

预期输出:
✅ Entity(id="ent_001", type="person", name="李明")
✅ Entity(id="ent_002", type="organization", name="XX科技有限公司")
✅ Entity(id="ent_003", type="technology", name="IoT")
✅ Entity(id="ent_004", type="technology", name="边缘计算")
✅ 解析耗时 < 200ms
```

**验收标准**: 20张名片全部正确解析，准确率 >95%

---

### Week 2: 关联发现验证

**目标**: 多张名片之间能否发现有意义的关系

```
测试数据集:
  - 30张名片 (覆盖 10-15 个人 + 8-10 家公司 + 多个技能标签)
  - 人为预埋 5-8 个真实关联:
    • 同事关系 (2对)
    • 竞争关系 (2对公司)
    • 技能互补 (2对)
    • 校友关系 (1对)

评估指标:
  ┌──────────────────┬─────────┬──────────┐
  │ 指标              │ 目标值   │ 说明      │
  ├──────────────────┼─────────┼──────────┤
  │ Precision@5      │ >70%    │ Top5中有价值│
  │ Recall@10        │ >60%    │ 预埋关联找回率│
  │ F1 Score         │ >0.65   │ 综合指标   │
  │ 平均延迟          │ <2s     │ 单次关联发现│
  └──────────────────┴─────────┴──────────┘
```

**交付物**:
- [ ] Postman API 测试集合 (可直接运行)
- [ ] 关联结果可视化 (Graphviz DOT 图)
- [ ] 性能基准报告 (延迟/吞吐量/内存)

---

### Week 3: 端到端演示

**目标**: 从名片录入到提醒展示的完整链路

```
演示流程 (录制屏幕或现场Demo):

1. 打开 IAMHERE 小程序测试页面
2. 点击"查看李明名片"按钮
3. 后台: POST /api/v1/events → 返回 event_id
4. 后台: 异步处理 (实体抽取 → 归一 → 关联发现)
5. 前端: 轮询 GET /api/v1/alerts/today
6. 展示: 弹出提醒卡片 "🔴 竞对预警: 李明的公司与..."
7. 点击: 展开详情 (关联强度、证据来源)
8. 反馈: 点击 👍 有用 / 👎 无关

关键指标:
  ✅ 端到端延迟 < 10s (从点击到看到提醒)
  ✅ UI 流畅无卡顿
  ✅ 错误处理优雅 (网络异常时提示清晰)
```

---

## 下一步

如果您认可这个技术方案：

1. **提供样例数据** → 我开始搭建 PoC 环境
2. **Week 1** → 给您看数据解析效果
3. **Week 2** → 给您看关联发现结果
4. **Week 3** → 端到端 Demo 演示

**技术问题随时可以深入讨论。期待您的反馈！**

---

> 林总 (CarryMem) · 2026-05-31
