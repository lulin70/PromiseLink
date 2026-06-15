# PromiseLink「预定日程」功能 — 五角色设计评审报告

> 评审日期: 2026-06-15
> 评审范围: ScheduledEvent 独立模型、录入转换流程、过期提醒、前端交互、API 设计
> 基于代码: PromiseLink 后端 (src/promiselink/) + 前端 (frontend/src/)

---

## 一、各角色评审发现

### 1. 架构师评审

#### 1.1 ScheduledEvent 模型设计

**建议字段:**

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | UUID | PK | 主键 |
| user_id | UUID | NOT NULL, INDEX | 用户隔离 |
| scheduled_at | TIMESTAMP | NOT NULL, INDEX | 预定时间 |
| topic | VARCHAR(200) | NOT NULL | 日程主题 |
| participants | JSONB/JSON | | 参与者信息列表 `[{"name":"张总","entity_id":"...","company":"..."}]` |
| location | VARCHAR(200) | NULLABLE | 地点 |
| event_type | VARCHAR(20) | NOT NULL, DEFAULT 'meeting' | 预定的事件类型 (meeting/call/manual) |
| status | VARCHAR(20) | NOT NULL, DEFAULT 'pending' | pending/recorded/cancelled/overdue |
| linked_event_id | UUID | FK→events.id, NULLABLE | 录入后关联的 Event ID |
| cancel_reason | TEXT | NULLABLE | 取消原因 |
| reminder_at | TIMESTAMP | NULLABLE | 提醒时间 |
| metadata_ | JSONB/JSON | NULLABLE | 扩展元数据 |
| created_at | TIMESTAMP | NOT NULL, DEFAULT now() | 创建时间 |
| updated_at | TIMESTAMP | NOT NULL, DEFAULT now() | 更新时间 |
| recorded_at | TIMESTAMP | NULLABLE | 录入时间 |

**约束与索引:**
```sql
CHECK (status IN ('pending', 'recorded', 'cancelled', 'overdue'))
CHECK (event_type IN ('meeting', 'call', 'manual'))
CHECK (scheduled_at IS NOT NULL)
INDEX idx_se_user_status (user_id, status)
INDEX idx_se_user_scheduled (user_id, scheduled_at)
INDEX idx_se_user_overdue (user_id, status, scheduled_at)  -- 过期查询优化
```

**关键设计决策:**
- `participants` 使用 JSONB 而非关联表 — 预定阶段人物可能尚未入库（没有 entity_id），JSONB 更灵活
- `linked_event_id` 可为 NULL — 录入前无关联 Event；录入后建立单向关联
- `status` 含 `overdue` — 与 Event 模型的 status 语义不同，ScheduledEvent 的 overdue 表示"已过期未录入"
- `event_type` 限定为 meeting/call/manual — 预定日程不可能是 card_save/wechat_forward/email

#### 1.2 API 设计

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | /scheduled-events | 创建预定日程 |
| GET | /scheduled-events | 列表查询 (支持 status/scheduled_at 范围筛选) |
| GET | /scheduled-events/{id} | 详情 |
| PATCH | /scheduled-events/{id} | 更新 (修改时间/参与者等) |
| DELETE | /scheduled-events/{id} | 删除 (仅 pending 状态) |
| POST | /scheduled-events/{id}/record | 录入 → 创建 Event + 触发管线 |
| POST | /scheduled-events/{id}/cancel | 取消预定 |

**录入转换 API 详细设计:**

```
POST /scheduled-events/{id}/record
Request Body:
{
  "raw_text": "今天和张总讨论了新项目合作方案...",
  "event_type": "meeting",           // 可覆盖预定时的类型
  "additional_participants": [...]   // 可补充实际参与者
}
Response:
{
  "scheduled_event_id": "...",
  "event_id": "...",                 // 新创建的 Event
  "pipeline_status": "pending"
}
```

**转换逻辑 (事务内):**
1. 校验 ScheduledEvent 状态为 pending/overdue
2. 创建 Event 记录 (event_type=请求值, raw_text=请求值, source='scheduled_record', metadata_ 包含 scheduled_event_id)
3. 更新 ScheduledEvent: status='recorded', linked_event_id=新Event.id, recorded_at=now()
4. 提交事务
5. 触发 Event 管线 (background task)

#### 1.3 数据流: ScheduledEvent → Event 转换

```
创建预定日程 (ScheduledEvent, status=pending)
    │
    ├─ 到达 scheduled_at → 后台定时任务标记 status=overdue
    │
    ├─ 用户点击「录入」→ POST /scheduled-events/{id}/record
    │   ├─ 创建 Event (source='scheduled_record')
    │   ├─ 更新 ScheduledEvent.status = 'recorded'
    │   ├─ ScheduledEvent.linked_event_id = Event.id
    │   └─ 触发 13 步管线
    │
    └─ 用户点击「取消」→ POST /scheduled-events/{id}/cancel
        └─ ScheduledEvent.status = 'cancelled'
```

**与现有模型的集成:**
- Event 新增 source 值 `scheduled_record`，但不需要修改 VALID_TYPES
- Event.metadata_ 增加 `scheduled_event_id` 字段用于回溯
- Entity.source_event_id 仍指向 Event.id（不变）
- Todo.source_event_id 仍指向 Event.id（不变）

#### 1.4 数据库迁移策略

1. 新建 `scheduled_events` 表 (Alembic migration)
2. 清理 entity_extractor.py 中 CONVERSATION_TYPES 的 `"schedule"` — 移除，因为 schedule 不再走 Event 管线
3. 前端 input/index.tsx 中 `EVENT_TYPES` 移除 `schedule` 选项 — 预定日程走独立入口
4. 前端 events/index.tsx 中 `DATE_FILTERS` 的 `upcoming` 改为查询 ScheduledEvent API
5. 无需迁移现有 Event 数据 — 因为之前 schedule 类型提交就失败了，不存在脏数据

**风险点:**
- SQLite 的 JSONB 兼容性 — 已有 IS_SQLITE 判断机制，沿用即可
- 并发写入 — ScheduledEvent 写入量远小于 Event，不需要 pipeline_lock

---

### 2. 产品经理评审

#### 2.1 用户旅程完整性

**核心旅程:**
```
创建预定 → 等待提醒 → 到期提醒 → 录入实际内容 → 查看解析结果
```

**分支旅程:**
- 创建预定 → 计划变更 → 修改时间/参与者
- 创建预定 → 会议取消 → 取消预定 (可选填原因)
- 创建预定 → 忘记录入 → 过期提醒 → 录入
- 创建预定 → 忘记录入 → 多次过期提醒 → 最终录入或取消

**缺失场景:**
1. **重复日程** — 每周例会等周期性日程，MVP 不支持，Phase 2 考虑
2. **日程冲突检测** — 同一时段多个预定，MVP 不做，Phase 2 考虑
3. **从人物详情页创建预定** — "与张总的下次互动"，Phase 2

#### 2.2 边界情况与错误场景

| 场景 | 处理策略 |
|------|----------|
| 预定时间已过才创建 | 允许创建，立即标记 overdue |
| 录入时 raw_text 为空 | 前端校验阻止，后端返回 400 |
| 录入后想修改内容 | 修改的是 Event（已有机制），不影响 ScheduledEvent |
| 已录入的日程想取消 | 不允许，录入后 Event 已产生，走 Event 删除流程 |
| 已取消的日程想恢复 | MVP 不支持，需重新创建 |
| 同一预定重复点录入 | 后端幂等校验：status 非 pending/overdue 时返回 409 |
| 参与者名字与已有 Entity 匹配 | 录入时在 metadata 中记录，管线解析时自动做 entity resolution |

#### 2.3 MVP vs Phase 2 优先级

**MVP (必须):**
- ScheduledEvent CRUD
- 录入转换 (创建 Event + 触发管线)
- 取消预定 (含取消原因)
- 过期标记 + 基础提醒
- 前端「预定日程」筛选切换数据源

**Phase 2 (增强):**
- 周期性日程
- 日程冲突检测
- 从 Entity 详情页创建预定
- 智能建议预定 (基于互动频率)
- 已取消日程恢复
- 日程与日历同步 (CalDAV/iCal)

---

### 3. 安全专家评审

#### 3.1 数据隔离

- **user_id 强制过滤**: 所有 ScheduledEvent 查询必须带 `WHERE user_id = current_user_id`，与现有 Event/Entity/Todo 一致
- **API 层**: 沿用 `get_current_user_id` 依赖注入，所有端点强制校验
- **linked_event_id 跨用户风险**: 录入时创建的 Event 自动使用当前 user_id，不存在跨用户关联风险

#### 3.2 输入校验

| 字段 | 校验规则 |
|------|----------|
| topic | max_length=200, 不允许纯空白 |
| participants | JSON Schema 校验: 数组, 每项 name 必填, entity_id 可选 UUID |
| scheduled_at | 必须是合法 ISO 时间戳 |
| cancel_reason | max_length=500 |
| raw_text (录入) | max 500KB, 与 Event 一致 |
| event_type | 枚举白名单: meeting/call/manual |

**XSS 防护:**
- topic、participants[].name、cancel_reason 存储前做 HTML 转义
- 前端渲染时使用 Text 组件 (Taro 默认转义)

#### 3.3 授权检查

- **创建**: 已登录用户 (Bearer token)
- **读取**: 仅自己的 ScheduledEvent
- **更新/删除**: 仅 status=pending 的记录
- **录入**: 仅 status=pending/overdue 的记录
- **取消**: 仅 status=pending/overdue 的记录
- **速率限制**: 沿用 rate_limit_dependency，创建预定限 10次/分钟

#### 3.4 敏感数据处理

- participants 中可能包含手机号、邮箱 — 存入 JSONB，不单独建列
- 取消原因可能包含敏感信息 — 与 ScheduledEvent 同生命周期删除
- 录入后 raw_text 进入 Event，受 Event 已有的隐私保护机制约束

---

### 4. 测试专家评审

#### 4.1 测试策略

| 层级 | 覆盖范围 | 工具 |
|------|----------|------|
| 单元测试 | 模型约束、状态转换、API schema 校验 | pytest |
| 集成测试 | ScheduledEvent→Event 转换 + 管线触发 | pytest + AsyncSession |
| API 测试 | CRUD + record + cancel 端点 | FastAPI TestClient |
| E2E 测试 | 完整用户旅程: 创建→提醒→录入→查看结果 | scripts/e2e/ |

#### 4.2 关键测试场景

**模型层:**
1. ScheduledEvent status 约束: 非 pending/recorded/cancelled/overdue 值应被拒绝
2. linked_event_id 外键: 指向不存在的 Event 应失败
3. participants JSON 格式校验

**API 层:**
4. 创建预定日程 — 正常流程
5. 创建预定日程 — 缺少必填字段返回 422
6. 创建预定日程 — event_type 非法值返回 400
7. 列表查询 — 按 status 筛选
8. 列表查询 — 按 scheduled_at 范围筛选
9. 列表查询 — 仅返回当前用户的记录
10. 录入 — 正常流程 (创建 Event + 更新 ScheduledEvent)
11. 录入 — status 非 pending/overdue 返回 409
12. 录入 — raw_text 为空返回 400
13. 录入 — 触发管线 (验证 background task 被调用)
14. 取消 — 正常流程
15. 取消 — 已录入的日程返回 409
16. 删除 — 仅 pending 状态可删除
17. 跨用户访问 — 返回 404

**集成测试:**
18. 录入后 Event 的 metadata 包含 scheduled_event_id
19. 录入后管线完整执行 (13步)
20. 录入后 Entity.source_event_id 正确指向新 Event
21. 过期标记定时任务正确运行

**E2E 测试:**
22. 用户创建预定 → 到期 → 收到提醒 → 点击录入 → 填写内容 → 查看解析结果
23. 用户创建预定 → 取消 → 确认取消原因 → 日程消失
24. 用户创建预定 → 忘记录入 → 过期提醒 → 录入

#### 4.3 与现有管线的集成测试点

- 录入创建的 Event 是否正确走完 13 步管线
- 管线中 entity_extractor 对 source='scheduled_record' 的 Event 是否正常处理
- 录入的 Event 产生的 Todo 是否正确关联 source_event_id
- ReminderLog 是否正确记录预定日程的提醒

#### 4.4 边界测试

- scheduled_at 在过去 — 允许创建，立即 overdue
- participants 为空数组 — 允许 (可能只记录自己的日程)
- 同一时间大量预定 — 性能测试
- 录入时 Event 创建失败 — ScheduledEvent 状态回滚
- 管线执行中删除 ScheduledEvent — linked_event_id 的 SET NULL 行为

---

### 5. UI 设计师评审

#### 5.1 日程卡片布局

```
┌─────────────────────────────────────┐
│ 📅 明天 14:00                        │
│ ─────────────────────────────────── │
│ 与张总讨论新项目合作                    │
│ 👤 张总(ABC科技) · 📍 望京SOHO        │
│                                     │
│ ┌─────────┐  ┌──────────┐           │
│ │  📝 录入  │  │ ✕ 取消预定 │           │
│ └─────────┘  └──────────┘           │
└─────────────────────────────────────┘
```

**过期状态卡片:**
```
┌─────────────────────────────────────┐
│ 🔴 已过期 · 昨天 14:00               │
│ ─────────────────────────────────── │
│ 与张总讨论新项目合作                    │
│ 👤 张总(ABC科技)                      │
│                                     │
│ ┌─────────┐  ┌──────────┐           │
│ │  📝 录入  │  │ ✕ 取消预定 │           │
│ └─────────┘  └──────────┘           │
└─────────────────────────────────────┘
```

**已录入卡片:**
```
┌─────────────────────────────────────┐
│ ✅ 已录入 · 06/15 14:00              │
│ ─────────────────────────────────── │
│ 与张总讨论新项目合作                    │
│ 👤 张总(ABC科技)                      │
│                                     │
│ ┌──────────────┐                    │
│ │ 查看解析结果 → │                    │
│ └──────────────┘                    │
└─────────────────────────────────────┘
```

**已取消卡片:**
```
┌─────────────────────────────────────┐
│ ── 已取消 · 06/14 14:00              │
│ ─────────────────────────────────── │
│ 与张总讨论新项目合作                    │
│ 取消原因: 对方临时出差                   │
└─────────────────────────────────────┘
```

#### 5.2 按钮放置与视觉层级

| 状态 | 主操作 | 次操作 | 视觉权重 |
|------|--------|--------|----------|
| pending | 「录入」(蓝色实心) | 「取消预定」(灰色文字) | 录入突出 |
| overdue | 「录入」(红色实心+脉冲动画) | 「取消预定」(灰色文字) | 录入紧急 |
| recorded | 「查看解析结果」(蓝色文字) | — | 低权重 |
| cancelled | — | — | 灰色/删除线 |

#### 5.3 状态指示器

| 状态 | 图标 | 颜色 | 标签 |
|------|------|------|------|
| pending | 📅 | 蓝色 #1890FF | "待录入" |
| overdue | 🔴 | 红色 #FF4D4F | "已过期" |
| recorded | ✅ | 绿色 #52C41A | "已录入" |
| cancelled | ── | 灰色 #8C8C8C | "已取消" |

#### 5.4 录入导航流程

```
日程卡片「录入」按钮
    │
    ▼
跳转录入页 (/pages/input/index)
    │
    ├─ 自动填充:
    │   · event_type = 预定时指定的类型 (meeting/call/manual)
    │   · raw_text 预填: "与{参与者}的{event_type_label}：{topic}"
    │   · 页面标题改为 "录入: {topic}"
    │
    ├─ URL 参数: /pages/input/index?scheduled_event_id=xxx
    │
    └─ 提交时:
        · 调用 POST /scheduled-events/{id}/record (非 POST /events)
        · 提交成功后返回日程列表页
```

**前端改动点:**
1. input/index.tsx 新增 `scheduled_event_id` URL 参数处理
2. 当有 `scheduled_event_id` 时，切换为"录入模式":
   - 事件类型锁定为预定时指定的类型
   - raw_text 预填模板
   - 提交调用 `recordScheduledEvent()` API
3. events/index.tsx 的 `upcoming` 筛选改为调用 `GET /scheduled-events`

---

## 二、共识结论

### 已达成共识的设计决策

| # | 决策项 | 结论 |
|---|--------|------|
| 1 | ScheduledEvent 独立模型 | ✅ 独立表，与 Event 解耦，通过 linked_event_id 单向关联 |
| 2 | participants 字段类型 | ✅ JSONB 数组，非关联表。支持未入库人物 |
| 3 | 录入转换机制 | ✅ POST /scheduled-events/{id}/record，事务内创建 Event + 更新 ScheduledEvent |
| 4 | 录入后 Event 的 source | ✅ source='scheduled_record'，metadata 包含 scheduled_event_id |
| 5 | 取消原因 | ✅ 可选填写，cancel_reason 字段 |
| 6 | 过期标记 | ✅ status='overdue'，后台定时任务扫描 |
| 7 | 提醒集成 | ✅ 复用 ReminderPreference，新增 reminder_type='scheduled_due' |
| 8 | 前端数据源切换 | ✅ "预定日程"筛选改为查询 ScheduledEvent API |
| 9 | 前端录入入口 | ✅ 日程卡片「录入」→ 跳转 input 页 (带 scheduled_event_id 参数) |
| 10 | entity_extractor 清理 | ✅ 从 CONVERSATION_TYPES 移除 "schedule" |
| 11 | Event.VALID_TYPES | ✅ 不新增 "schedule"，预定日程不走 Event 创建流程 |
| 12 | 已录入日程不可取消 | ✅ 录入后 Event 已产生，走 Event 管理流程 |

---

## 三、已确认决策（原待确认问题）

| # | 问题 | 决策 | 理由 |
|---|------|------|------|
| 1 | 过期提醒频率 | **首次过期立即+之后每天** | 确保用户第一时间知道过期，持续提醒避免遗忘 |
| 2 | 已取消日程保留 | **保留30天后自动清理** | 平衡可查性与存储，30天足够回溯 |
| 3 | 录入页是否允许修改事件类型 | **允许修改** | 实际可能是电话而非会议，需灵活调整 |
| 4 | 预定日程是否出现在首页 Dashboard | **Dashboard也展示** | 今日/近期预定是高频关注信息，应首屏可见 |
| 5 | participants中entity_id的匹配时机 | **两者都尝试** | 创建时预匹配提升体验，录入时管线再次匹配确保准确 |

---

## 四、推荐实施顺序

### Phase 0: 修复当前 Bug (1天)
1. 从前端 EVENT_TYPES 移除 `schedule` 选项 (或标记为 disabled)
2. 从 entity_extractor.py CONVERSATION_TYPES 移除 `"schedule"`
3. 前端 "预定日程" 筛选标签临时隐藏或改为空状态提示

### Phase 1: ScheduledEvent 核心 (3-5天)
1. 创建 ScheduledEvent 模型 + Alembic migration
2. 实现 CRUD API (POST/GET/PATCH/DELETE)
3. 实现录入转换 API (POST /{id}/record)
4. 实现取消 API (POST /{id}/cancel)
5. 后台定时任务: 过期标记
6. 单元测试 + API 测试

### Phase 2: 前端适配 (2-3天)
1. 前端新增 ScheduledEvent API 调用函数
2. 修改 input/index.tsx 支持录入模式
3. 修改 events/index.tsx "预定日程" 筛选切换数据源
4. 日程卡片 UI (四种状态)
5. 取消预定弹窗 (含取消原因输入)

### Phase 3: 提醒集成 (1-2天)
1. ReminderLog 新增 reminder_type='scheduled_due'
2. 定时提醒任务集成 ReminderPreference (疲劳阈值/静默时段)
3. 前端提醒展示

### Phase 4: E2E 验证 (1天)
1. 完整用户旅程 E2E 测试
2. 模拟真实用户场景测试
3. 性能测试 (大量预定日程)

---

## 附录: 与现有代码的接口变更清单

### 后端变更

| 文件 | 变更类型 | 说明 |
|------|----------|------|
| models/scheduled_event.py | 新增 | ScheduledEvent 模型 |
| models/__init__.py | 修改 | 导出 ScheduledEvent |
| api/v1/scheduled_events.py | 新增 | ScheduledEvent API 端点 |
| main.py | 修改 | 注册 scheduled_events router |
| services/entity_extractor.py | 修改 | CONVERSATION_TYPES 移除 "schedule" |
| alembic/versions/xxx_add_scheduled_events.py | 新增 | 数据库迁移 |
| models/reminder.py | 修改 | reminder_type_check 新增 'scheduled_due' |

### 前端变更

| 文件 | 变更类型 | 说明 |
|------|----------|------|
| services/api.ts | 修改 | 新增 ScheduledEvent API 函数 |
| pages/input/index.tsx | 修改 | 支持录入模式 (scheduled_event_id 参数) |
| pages/events/index.tsx | 修改 | "预定日程"筛选切换数据源 |
| pages/input/index.scss | 修改 | 录入模式样式 |
| pages/events/index.scss | 修改 | 日程卡片样式 |
