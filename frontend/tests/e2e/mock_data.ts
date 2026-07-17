import { Page } from '@playwright/test'

/**
 * 基础版 E2E 测试 API mock fixture
 *
 * 设计目标（对应用户硬约束："没有数据创造数据，系统有问题优化系统"）：
 *   拦截所有 /api/v1/** 请求，返回确定性的测试数据，
 *   消除所有"后端无数据"类 test.skip。
 *
 * 使用方式：
 *   import { setupMockApi, injectLoginState } from './mock_data'
 *   test.beforeEach(async ({ page }) => {
 *     await injectLoginState(page)
 *     await setupMockApi(page)
 *     await page.goto('/pages/events/index')
 *   })
 *
 * 数据设计原则：
 *   - 覆盖所有 skip 场景：事件/待办/人脉/承诺/预定日程/提醒/AI 解析
 *   - 关联关系完整：事件 → 人脉 → 待办 → 承诺 互相引用
 *   - 状态覆盖：pending/done/dismissed/scheduled/recorded/cancelled
 */

// ─────────────────────────────────────────────────────────────────────────────
// 测试数据常量
// ─────────────────────────────────────────────────────────────────────────────

export const MOCK_USER_ID = 'e2e_test_user'
export const MOCK_TOKEN = 'mock-e2e-token'

export const MOCK_ENTITY_ID = 'entity-0001'
export const MOCK_ENTITY_ID_2 = 'entity-0002'
export const MOCK_EVENT_ID = 'event-0001'
export const MOCK_TODO_ID = 'todo-0001'
export const MOCK_PROMISE_TODO_ID = 'todo-0002'
export const MOCK_SCHEDULED_EVENT_ID = 'se-0001'
export const MOCK_SCHEDULED_EVENT_ID_2 = 'se-0002'
export const MOCK_SCHEDULED_EVENT_ID_3 = 'se-0003'

const now = new Date()
const todayStr = now.toISOString().split('T')[0]
const tomorrowStr = new Date(now.getTime() + 86400000).toISOString().split('T')[0]
const yesterdayStr = new Date(now.getTime() - 86400000).toISOString().split('T')[0]
const lastWeekStr = new Date(now.getTime() - 7 * 86400000).toISOString()

// ─────────────────────────────────────────────────────────────────────────────
// Mock 数据
// ─────────────────────────────────────────────────────────────────────────────

const mockEntity = {
  id: MOCK_ENTITY_ID,
  user_id: MOCK_USER_ID,
  name: '王晓明',
  entity_type: 'person',
  canonical_name: '王晓明',
  aliases: ['小明', '王总'],
  confidence: 0.95,
  status: 'active',
  properties: { company: '阿里云', title: '产品总监', phone: '13800138000', email: 'wangxm@aliyun.com' },
  created_at: lastWeekStr,
  updated_at: yesterdayStr,
}

const mockEntity2 = {
  id: MOCK_ENTITY_ID_2,
  user_id: MOCK_USER_ID,
  name: '张总',
  entity_type: 'person',
  canonical_name: '张总',
  aliases: ['老张'],
  confidence: 0.88,
  status: 'active',
  properties: { company: '腾讯', title: 'CTO', phone: '13900139000', email: 'zhang@tencent.com' },
  created_at: lastWeekStr,
  updated_at: yesterdayStr,
}

const mockEvent = {
  id: MOCK_EVENT_ID,
  user_id: MOCK_USER_ID,
  title: '与王晓明讨论产品合作方案',
  event_type: 'meeting',
  raw_text: '今天下午和王晓明开会讨论了产品合作方案，他答应下周三前发邮件给我详细方案，我需要准备技术评估材料',
  // status='completed' 触发 CorrectionPanel 渲染（input 页），
  // 同时让 events 列表/详情页正常显示已解析状态
  status: 'completed',
  pipeline: 'completed',
  processed_at: yesterdayStr,
  timestamp: yesterdayStr,
  created_at: yesterdayStr,
  source: 'manual',
  related_entities: [
    { id: MOCK_ENTITY_ID, name: '王晓明', entity_type: 'person', company: '阿里云', title: '产品总监', status: 'active', confidence: 0.95 },
  ],
  related_todos: [
    {
      id: MOCK_TODO_ID,
      title: '准备技术评估材料',
      todo_type: 'action',
      action_type: null,
      priority: 3,
      status: 'pending',
      due_date: tomorrowStr,
      related_entity_id: MOCK_ENTITY_ID,
    },
    {
      id: MOCK_PROMISE_TODO_ID,
      title: '王晓明答应下周三前发邮件给我详细方案',
      todo_type: 'promise',
      action_type: 'their_promise',
      priority: 3,
      status: 'pending',
      due_date: tomorrowStr,
      related_entity_id: MOCK_ENTITY_ID,
      confirmation_status: 'pending',
      evidence_quote: '他答应下周三前发邮件给我详细方案',
    },
  ],
  related_associations: [
    { id: 'assoc-0001', source_entity_name: '王晓明', target_entity_name: '张总', association_type: 'colleague', strength: 0.7 },
  ],
}

const mockEvent2 = {
  id: 'event-0002',
  user_id: MOCK_USER_ID,
  title: '与张总的技术评审会议',
  event_type: 'meeting',
  raw_text: '昨天和张总开了技术评审会议，讨论了架构设计方案',
  status: 'processed',
  timestamp: yesterdayStr,
  created_at: yesterdayStr,
  source: 'manual',
  related_entities: [
    { id: MOCK_ENTITY_ID_2, name: '张总', entity_type: 'person', company: '腾讯', title: 'CTO', status: 'active', confidence: 0.88 },
  ],
  related_todos: [],
}

const mockTodo = {
  id: MOCK_TODO_ID,
  user_id: MOCK_USER_ID,
  title: '准备技术评估材料',
  todo_type: 'action',
  priority: 3,
  priority_source: 'ai',
  status: 'pending',
  due_date: tomorrowStr,
  source_event_id: MOCK_EVENT_ID,
  source_event_title: '与王晓明讨论产品合作方案',
  source_event_date: yesterdayStr,
  related_entity_id: MOCK_ENTITY_ID,
  related_entity_name: '王晓明',
  created_at: yesterdayStr,
  updated_at: yesterdayStr,
}

const mockPromiseTodo = {
  id: MOCK_PROMISE_TODO_ID,
  user_id: MOCK_USER_ID,
  title: '王晓明答应下周三前发邮件给我详细方案',
  todo_type: 'promise',
  action_type: 'their_promise',
  priority: 3,
  priority_source: 'ai',
  status: 'pending',
  fulfillment_status: 'pending',
  due_date: tomorrowStr,
  source_event_id: MOCK_EVENT_ID,
  source_event_title: '与王晓明讨论产品合作方案',
  source_event_date: yesterdayStr,
  related_entity_id: MOCK_ENTITY_ID,
  related_entity_name: '王晓明',
  created_at: yesterdayStr,
  updated_at: yesterdayStr,
}

// PromiseItem 契约（frontend/src/services/api.ts）：
//   { todo_id, entity_id?, entity_name?, action_type, description?, due_date?,
//     fulfillment_status, confirmation_status?, created_at?, source_event_id?, source_event_title?, source_event_date? }
// 注意：与 Todo 不同，PromiseItem 用 todo_id（非 id）、description（非 title）、fulfillment_status（非 status）
const mockPromiseItem = {
  todo_id: MOCK_PROMISE_TODO_ID,
  entity_id: MOCK_ENTITY_ID,
  entity_name: '王晓明',
  action_type: 'their_promise',
  description: '王晓明答应下周三前发邮件给我详细方案',
  due_date: tomorrowStr,
  fulfillment_status: 'pending',
  confirmation_status: 'pending',
  created_at: yesterdayStr,
  source_event_id: MOCK_EVENT_ID,
  source_event_title: '与王晓明讨论产品合作方案',
  source_event_date: yesterdayStr,
}

const mockScheduledEventPending = {
  id: MOCK_SCHEDULED_EVENT_ID,
  user_id: MOCK_USER_ID,
  topic: '每周项目同步会',
  scheduled_at: tomorrowStr + 'T10:00:00',
  event_type: 'meeting',
  status: 'pending',
  participants: [],
  location: '会议室A',
  created_at: yesterdayStr,
  updated_at: yesterdayStr,
}

const mockScheduledEventOverdue = {
  id: MOCK_SCHEDULED_EVENT_ID_2,
  user_id: MOCK_USER_ID,
  topic: '客户拜访 - 阿里云',
  scheduled_at: yesterdayStr + 'T14:00:00',
  event_type: 'meeting',
  status: 'overdue',
  participants: [],
  location: '阿里云总部',
  created_at: lastWeekStr,
  updated_at: yesterdayStr,
}

const mockScheduledEventRecorded = {
  id: MOCK_SCHEDULED_EVENT_ID_3,
  user_id: MOCK_USER_ID,
  topic: '团队周会',
  scheduled_at: yesterdayStr + 'T09:00:00',
  event_type: 'meeting',
  status: 'recorded',
  participants: [],
  location: '会议室B',
  recorded_at: yesterdayStr,
  linked_event_id: MOCK_EVENT_ID,
  created_at: lastWeekStr,
  updated_at: yesterdayStr,
}

const mockScheduledEventCancelled = {
  id: 'se-0004',
  user_id: MOCK_USER_ID,
  topic: '已取消的会议',
  scheduled_at: tomorrowStr + 'T15:00:00',
  event_type: 'meeting',
  status: 'cancelled',
  participants: [],
  location: '会议室C',
  cancel_reason: '时间冲突',
  created_at: lastWeekStr,
  updated_at: yesterdayStr,
}

// ─────────────────────────────────────────────────────────────────────────────
// injectLoginState — 注入登录态（绕过 UI 登录）
// ─────────────────────────────────────────────────────────────────────────────

export async function injectLoginState(
  page: Page,
  token: string = MOCK_TOKEN,
  userId: string = MOCK_USER_ID,
  options: { showGuide?: boolean } = {},
): Promise<void> {
  // 用 addInitScript 在每次页面导航前注入 localStorage，确保跨页面导航后状态不丢失
  // （page.evaluate 设的 localStorage 在 page.goto 全页面重载时可能因执行上下文切换而丢失）
  const showGuide = options.showGuide ?? false
  await page.addInitScript((args) => {
    localStorage.setItem('promiselink_token', args.t)
    localStorage.setItem('promiselink_user_id', args.u)
    if (args.showGuide) {
      // Guide 测试：移除 guide_shown，让 Guide 组件轮询检测到未展示过 → 自动弹出
      localStorage.removeItem('guide_shown')
    } else {
      // 非 Guide 测试：标记 Guide 已展示，避免引导 overlay 干扰操作
      // 注意：Taro H5 的 setStorageSync 把数据包装为 {"data": value} JSON 格式存储，
      // 直接 localStorage.setItem('guide_shown', 'true') 无法被 Taro.getStorageSync 读取，
      // 必须用 JSON.stringify({data: true}) 格式（见 node_modules/@tarojs/taro-h5/dist/api/storage/index.js）
      localStorage.setItem('guide_shown', JSON.stringify({ data: true }))
    }
  }, { t: token, u: userId, showGuide })
  // 首次导航触发 addInitScript 执行
  await page.goto('/pages/index/index', { waitUntil: 'domcontentloaded' })
}

// ─────────────────────────────────────────────────────────────────────────────
// setupMockApi — 拦截所有 /api/v1/** 请求，返回 mock 数据
// ─────────────────────────────────────────────────────────────────────────────

export async function setupMockApi(page: Page): Promise<void> {
  // 状态化 mock：记录 todo/scheduled_event 的运行时状态变更，
  // 让 PATCH/POST 后的 GET 能返回更新后的状态（模拟真实后端行为）。
  // 这是消除"系统有问题就优化系统"原则下 mock 的必要改进——
  // 不是测试妥协，而是让 mock 真实反映后端语义。
  const todoState: Record<string, { status: string; snoozed_until?: string | null; completed_at?: string | null; fulfillment_status?: string }> = {
    [MOCK_TODO_ID]: { status: 'pending', snoozed_until: null, completed_at: null },
    [MOCK_PROMISE_TODO_ID]: { status: 'pending', snoozed_until: null, completed_at: null, fulfillment_status: 'pending' },
  }
  // confirmationStatus 跟踪承诺 todo 的确认状态（pending/confirmed/rejected）
  // confirmTodo API 调用后，GET /events/{id} 的 related_todos 需反映最新 confirmation_status
  const confirmationStatus: Record<string, string> = {
    [MOCK_PROMISE_TODO_ID]: 'pending',
  }
  const scheduledState: Record<string, { status: string }> = {
    [MOCK_SCHEDULED_EVENT_ID]: { status: 'pending' },
    [MOCK_SCHEDULED_EVENT_ID_2]: { status: 'overdue' },
    [MOCK_SCHEDULED_EVENT_ID_3]: { status: 'recorded' },
    ['se-0004']: { status: 'cancelled' },
  }

  await page.route('**/api/v1/**', (route) => {
    const url = route.request().url()
    const method = route.request().method()

    // ── Auth ──────────────────────────────────────────────────────────────
    if (url.includes('/auth/login') && method === 'POST') {
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ access_token: MOCK_TOKEN, token_type: 'bearer', user_id: MOCK_USER_ID }),
      })
    }

    // ── Events ─────────────────────────────────────────────────────────────
    if (url.match(/\/events\/[^/]+\/retry/) && method === 'POST') {
      return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ status: 'processing' }) })
    }
    if (url.match(/\/events\/[^/]+\/accept-degraded/) && method === 'POST') {
      return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ status: 'accepted' }) })
    }
    if (url.match(/\/events\/[^/]+\/correct/) && method === 'POST') {
      return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ success: true }) })
    }
    if (url.match(/\/events\/[^/]+$/) && method === 'DELETE') {
      return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ deleted: true }) })
    }
    if (url.match(/\/events\/[^/]+$/) && method === 'GET') {
      const id = url.match(/\/events\/([^/]+)$/)?.[1]
      // 动态构建 related_todos：从 confirmationStatus map 读取最新 confirmation_status，
      // 让 confirmTodo 后重新 GET /events/{id} 能返回更新后的状态，
      // 触发前端 isPendingConfirm=false → .pending-confirm-status 元素消失
      const dynamicRelatedTodos = mockEvent.related_todos.map(todo => {
        if (todo.id === MOCK_PROMISE_TODO_ID && confirmationStatus[todo.id]) {
          return { ...todo, confirmation_status: confirmationStatus[todo.id] }
        }
        return todo
      })
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ ...mockEvent, id: id || MOCK_EVENT_ID, related_todos: dynamicRelatedTodos }),
      })
    }
    if (url.includes('/events') && method === 'GET') {
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          items: [mockEvent, mockEvent2],
          total: 2,
          limit: 50,
          offset: 0,
        }),
      })
    }
    if (url.includes('/events') && (method === 'POST' || method === 'PUT')) {
      // EventCreateResponse: { id, pipeline_status: 'pending' } — input 页据此轮询 GET /events/{id}
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ id: MOCK_EVENT_ID, pipeline_status: 'pending', status: 'pending' }),
      })
    }

    // ── Todos ──────────────────────────────────────────────────────────────
    if (url.includes('/todos/pending-confirmations') && method === 'GET') {
      // getPendingConfirmations() 返回 ConfirmationItem[]（数组，非 { items } 包装）
      // ConfirmationItem: { todo_id, todo_type, title, description?, action_type?, due_date?, ... }
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify([
          {
            todo_id: MOCK_PROMISE_TODO_ID,
            todo_type: 'promise',
            title: '王晓明答应下周三前发邮件给我详细方案',
            description: '王晓明答应下周三前发邮件给我详细方案',
            action_type: 'their_promise',
            due_date: tomorrowStr,
            source_event_id: MOCK_EVENT_ID,
            related_entity_id: MOCK_ENTITY_ID,
            related_entity_name: '王晓明',
          },
        ]),
      })
    }
    if (url.match(/\/todos\/[^/]+\/confirm$/) && method === 'PATCH') {
      const id = url.match(/\/todos\/([^/]+)\/confirm$/)?.[1]
      // 前端 confirmTodo(id, { confirmation_status: 'confirmed' | 'rejected' }) → PATCH /todos/{id}/confirm
      // 同步更新 confirmationStatus map，让后续 GET /events/{id} 返回的 related_todos 反映最新状态
      let newConfirmationStatus = 'confirmed'
      try {
        const body = route.request().postDataJSON() as { confirmation_status?: string } | null
        if (body?.confirmation_status) newConfirmationStatus = body.confirmation_status
      } catch { /* 默认 confirmed */ }
      if (id) {
        confirmationStatus[id] = newConfirmationStatus
        if (todoState[id]) todoState[id].status = newConfirmationStatus === 'confirmed' ? 'done' : 'dismissed'
      }
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          todo_id: id || MOCK_PROMISE_TODO_ID,
          confirmation_status: newConfirmationStatus,
          status: newConfirmationStatus === 'confirmed' ? 'done' : 'dismissed',
        }),
      })
    }
    if (url.match(/\/todos\/[^/]+\/dismiss$/) && method === 'POST') {
      const id = url.match(/\/todos\/([^/]+)\/dismiss$/)?.[1]
      if (id && todoState[id]) todoState[id].status = 'dismissed'
      return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ success: true }) })
    }
    if (url.match(/\/todos\/[^/]+$/) && method === 'DELETE') {
      return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ deleted: true }) })
    }
    if (url.match(/\/todos\/[^/]+$/) && method === 'PATCH') {
      const id = url.match(/\/todos\/([^/]+)$/)?.[1]
      // 从请求 body 解析目标状态（前端 updateTodoStatus(id, status) 传 status 字段）
      let newStatus = 'done'
      try {
        const body = route.request().postDataJSON() as { status?: string } | null
        if (body?.status) newStatus = body.status
      } catch { /* 默认 done */ }
      if (id && todoState[id]) {
        todoState[id].status = newStatus
        if (newStatus === 'done') todoState[id].completed_at = new Date().toISOString()
      }
      const base = id === MOCK_PROMISE_TODO_ID ? mockPromiseTodo : mockTodo
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          ...base,
          id: id || MOCK_TODO_ID,
          status: newStatus,
          completed_at: newStatus === 'done' ? new Date().toISOString() : null,
        }),
      })
    }
    if (url.match(/\/todos\/[^/]+$/) && method === 'GET') {
      const id = url.match(/\/todos\/([^/]+)$/)?.[1]
      const base = id === MOCK_PROMISE_TODO_ID ? mockPromiseTodo : mockTodo
      const state = (id && todoState[id]) || { status: base.status, completed_at: null, snoozed_until: null }
      // 对承诺 todo，返回最新的 fulfillment_status（PATCH /promises/{id}/fulfillment 后同步）
      const fulfillmentStatus = (id === MOCK_PROMISE_TODO_ID && state.fulfillment_status) ? state.fulfillment_status : (base as typeof mockPromiseTodo).fulfillment_status
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          ...base,
          id: id || MOCK_TODO_ID,
          status: state.status,
          completed_at: state.completed_at ?? null,
          snoozed_until: state.snoozed_until ?? null,
          ...(fulfillmentStatus ? { fulfillment_status: fulfillmentStatus } : {}),
        }),
      })
    }
    if (url.includes('/todos') && method === 'GET') {
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          items: [mockTodo, mockPromiseTodo],
          total: 2,
          limit: 50,
          offset: 0,
        }),
      })
    }

    // ── Entities ───────────────────────────────────────────────────────────
    if (url.includes('/entities/dormant') && method === 'GET') {
      return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ items: [], total: 0 }) })
    }
    if (url.includes('/entities/credit-scores') && method === 'GET') {
      return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ items: [], total: 0 }) })
    }
    if (url.includes('/entities/stage-map') && method === 'GET') {
      return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ stages: [] }) })
    }
    if (url.match(/\/entities\/[^/]+\/history$/) && method === 'GET') {
      const id = url.match(/\/entities\/([^/]+)\/history$/)?.[1]
      const entity = id === MOCK_ENTITY_ID_2 ? mockEntity2 : mockEntity
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          entity: { ...entity, id: id || MOCK_ENTITY_ID },
          events: [
            {
              id: mockEvent.id,
              event_type: mockEvent.event_type,
              title: mockEvent.title,
              timestamp: mockEvent.timestamp,
              status: mockEvent.status,
              raw_text_preview: mockEvent.raw_text.slice(0, 60),
            },
          ],
          todos: [
            {
              id: mockTodo.id,
              todo_type: mockTodo.todo_type,
              title: mockTodo.title,
              priority: mockTodo.priority,
              status: todoState[MOCK_TODO_ID]?.status || mockTodo.status,
              created_at: mockTodo.created_at,
            },
            {
              id: mockPromiseTodo.id,
              todo_type: mockPromiseTodo.todo_type,
              title: mockPromiseTodo.title,
              priority: mockPromiseTodo.priority,
              status: todoState[MOCK_PROMISE_TODO_ID]?.status || mockPromiseTodo.status,
              created_at: mockPromiseTodo.created_at,
            },
          ],
          associations: [],
        }),
      })
    }
    if (url.match(/\/entities\/[^/]+\/credit-score$/) && method === 'GET') {
      const id = url.match(/\/entities\/([^/]+)\/credit-score$/)?.[1]
      const entity = id === MOCK_ENTITY_ID_2 ? mockEntity2 : mockEntity
      // 完整 CreditScoreResponse 结构（与 frontend/src/services/api.ts 一致）
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          entity_id: id || MOCK_ENTITY_ID,
          name: entity.name,
          score: 85,
          grade: 'A',
          breakdown: {
            my_fulfillment_rate: 0.9,
            their_fulfillment_rate: 0.8,
            interaction_consistency: 0.7,
            total_interactions: 5,
          },
        }),
      })
    }
    if (url.match(/\/entities\/[^/]+\/stage-info$/) && method === 'GET') {
      const id = url.match(/\/entities\/([^/]+)\/stage-info$/)?.[1]
      const entity = id === MOCK_ENTITY_ID_2 ? mockEntity2 : mockEntity
      // 完整 StageInfoResponse 结构（与 frontend/src/services/api.ts 一致）
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          entity_id: id || MOCK_ENTITY_ID,
          name: entity.name,
          current_stage: 'active',
          current_stage_label: '活跃',
          current_stage_color: '#A0B0C4',
          current_stage_desc: '近期保持稳定联系',
          stage_order: 2,
          suggestion: {
            target_stage: 'deepen',
            target_stage_label: '深化',
            reason: '可主动分享行业洞察深化关系',
            action_hint: '邀约深度交流',
          },
        }),
      })
    }
    if (url.match(/\/entities\/[^/]+$/) && method === 'DELETE') {
      return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ deleted: true }) })
    }
    if (url.match(/\/entities\/[^/]+$/) && method === 'PATCH') {
      return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ ...mockEntity, updated_at: new Date().toISOString() }) })
    }
    if (url.match(/\/entities\/[^/]+$/) && method === 'GET') {
      const id = url.match(/\/entities\/([^/]+)$/)?.[1]
      const entity = id === MOCK_ENTITY_ID_2 ? mockEntity2 : mockEntity
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          ...entity,
          id: id || MOCK_ENTITY_ID,
          associated_events: [mockEvent],
          associated_todos: [mockTodo],
        }),
      })
    }
    if (url.includes('/entities') && method === 'GET') {
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          items: [mockEntity, mockEntity2],
          total: 2,
          limit: 50,
          offset: 0,
        }),
      })
    }

    // ── Promises ───────────────────────────────────────────────────────────
    // PromiseStatsResponse: { total, my_promises: {pending,fulfilled,overdue,expired}, their_promises: {...}, fulfillment_rate }
    if (url.includes('/promises/stats') && method === 'GET') {
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          total: 1,
          my_promises: { pending: 0, fulfilled: 0, overdue: 0, expired: 0 },
          their_promises: { pending: 1, fulfilled: 0, overdue: 0, expired: 0 },
          fulfillment_rate: 0,
        }),
      })
    }
    if (url.match(/\/promises\/[^/]+\/fulfillment$/) && method === 'PATCH') {
      // updatePromiseStatus(todoId, fulfillmentStatus) → PATCH /promises/{id}/fulfillment, returns void
      const id = url.match(/\/promises\/([^/]+)\/fulfillment$/)?.[1]
      let newFulfillmentStatus = 'fulfilled'
      try {
        const body = route.request().postDataJSON() as { fulfillment_status?: string } | null
        if (body?.fulfillment_status) newFulfillmentStatus = body.fulfillment_status
      } catch { /* 默认 fulfilled */ }
      // 同步 todoState：让承诺详情页 loadDetail 重新 GET /todos/{id} 时返回更新后的 fulfillment_status
      if (id && todoState[id]) {
        todoState[id].fulfillment_status = newFulfillmentStatus
        todoState[id].status = newFulfillmentStatus === 'fulfilled' ? 'done' : newFulfillmentStatus
      }
      return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ todo_id: id || MOCK_PROMISE_TODO_ID, fulfillment_status: newFulfillmentStatus }) })
    }
    if (url.match(/\/promises\/[^/]+\/nudge-draft$/) && method === 'GET') {
      // NudgeDraftResponse: { todo_id, nudge_text, is_fallback }
      const id = url.match(/\/promises\/([^/]+)\/nudge-draft$/)?.[1]
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          todo_id: id || MOCK_PROMISE_TODO_ID,
          nudge_text: '您好，上次提到的产品合作方案进展如何？期待您的回复，谢谢！',
          is_fallback: false,
        }),
      })
    }
    if (url.includes('/promises') && method === 'GET') {
      // PromiseListResponse: { items: PromiseItem[], total, offset, limit }
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          items: [mockPromiseItem],
          total: 1,
          limit: 20,
          offset: 0,
        }),
      })
    }

    // ── Scheduled Events ───────────────────────────────────────────────────
    if (url.match(/\/scheduled-events\/[^/]+\/record$/) && method === 'POST') {
      const id = url.match(/\/scheduled-events\/([^/]+)\/record$/)?.[1]
      if (id && scheduledState[id]) scheduledState[id].status = 'recorded'
      return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ ...mockScheduledEventPending, status: 'recorded' }) })
    }
    if (url.match(/\/scheduled-events\/[^/]+\/cancel$/) && method === 'POST') {
      const id = url.match(/\/scheduled-events\/([^/]+)\/cancel$/)?.[1]
      if (id && scheduledState[id]) scheduledState[id].status = 'cancelled'
      return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ ...mockScheduledEventPending, status: 'cancelled' }) })
    }
    if (url.match(/\/scheduled-events\/[^/]+$/) && method === 'DELETE') {
      return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ deleted: true }) })
    }
    if (url.match(/\/scheduled-events\/[^/]+$/) && method === 'PATCH') {
      return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ ...mockScheduledEventPending, updated_at: new Date().toISOString() }) })
    }
    if (url.match(/\/scheduled-events\/[^/]+$/) && method === 'GET') {
      const id = url.match(/\/scheduled-events\/([^/]+)$/)?.[1]
      const base = id === MOCK_SCHEDULED_EVENT_ID_2 ? mockScheduledEventOverdue
        : id === MOCK_SCHEDULED_EVENT_ID_3 ? mockScheduledEventRecorded
        : id === 'se-0004' ? mockScheduledEventCancelled
        : mockScheduledEventPending
      const state = (id && scheduledState[id]) || { status: base.status }
      return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ ...base, id: id || MOCK_SCHEDULED_EVENT_ID, status: state.status }) })
    }
    if (url.match(/\/scheduled-events\/[^/]+$/) && method === 'POST') {
      return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ ...mockScheduledEventPending, id: 'se-new-' + Date.now() }) })
    }
    if (url.includes('/scheduled-events') && method === 'GET') {
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          items: [
            { ...mockScheduledEventPending, status: scheduledState[MOCK_SCHEDULED_EVENT_ID]?.status || 'pending' },
            { ...mockScheduledEventOverdue, status: scheduledState[MOCK_SCHEDULED_EVENT_ID_2]?.status || 'overdue' },
            { ...mockScheduledEventRecorded, status: scheduledState[MOCK_SCHEDULED_EVENT_ID_3]?.status || 'recorded' },
            { ...mockScheduledEventCancelled, status: scheduledState['se-0004']?.status || 'cancelled' },
          ],
          total: 4,
          limit: 50,
          offset: 0,
        }),
      })
    }

    // ── Dashboard ──────────────────────────────────────────────────────────
    // DayViewResponse 契约 (api.ts L719-729) 要求 date/date_label/events/todos/summary/adjacent_dates
    // 前端 index.tsx 直接读取 dashboard.summary.total_events 等，缺 summary 会触发 TypeError 导致
    // Index 组件崩溃 → webpack-dev-server 错误 overlay 拦截所有点击 → 隐私删除 modal 等交互全部失效
    if (url.includes('/dashboard/day-view') && method === 'GET') {
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          date: todayStr,
          date_label: '今日',
          events: [mockEvent],
          todos: [mockTodo],
          promises: [mockPromiseTodo],
          summary: {
            total_events: 1,
            total_todos: 1,
            overdue_todos: 0,
            pending_promises: 1,
            upcoming_meetings: 0,
          },
          adjacent_dates: {
            previous_day: yesterdayStr,
            next_day: tomorrowStr,
          },
        }),
      })
    }
    if (url.includes('/dashboard/range-view') && method === 'GET') {
      return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ items: [], total: 0 }) })
    }
    if (url.includes('/dashboard/morning-brief') && method === 'GET') {
      return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ summary: '今日有 1 个待办', todos: [mockTodo] }) })
    }
    // SupplyDemandResponse (api.ts L752-755): { matches: SupplyDemandMatch[], total }
    // 前端 setSdMatches(res.matches) 直接传入 sdMatches state，line 293 sdMatches.length 不做 ?.
    // 防护，若 matches 缺失则 TypeError: Cannot read properties of undefined (reading 'length')
    if (url.includes('/dashboard/supply-demand') && method === 'GET') {
      return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ matches: [], total: 0 }) })
    }
    // RelationshipHealthResponse (api.ts L784-791): { total_entities, healthy_count, attention_count, at_risk_count, items, summary_text }
    if (url.includes('/dashboard/relationship-health') && method === 'GET') {
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          total_entities: 0,
          healthy_count: 0,
          attention_count: 0,
          at_risk_count: 0,
          items: [],
          summary_text: '',
        }),
      })
    }
    // CareRemindersResponse (api.ts L846-851): { total, personal_items, business_items, summary_text }
    if (url.includes('/dashboard/care-reminders') && method === 'GET') {
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          total: 0,
          personal_items: [],
          business_items: [],
          summary_text: '',
        }),
      })
    }

    // ── Relationship Briefs ────────────────────────────────────────────────
    if (url.includes('/relationship-brief/aggregated') && method === 'GET') {
      return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ entity: mockEntity, relationship_stage: 'active', modules: [] }) })
    }
    if (url.includes('/relationship-briefs') && method === 'GET') {
      return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ items: [], total: 0 }) })
    }

    // ── Reminders ──────────────────────────────────────────────────────────
    // BatchReminderActionResponse: { success: [{todo_id, new_status}], failed: [{todo_id, error}] }
    if (url.includes('/reminders/batch-action') && method === 'POST') {
      let newStatus = 'done'
      try {
        const body = route.request().postDataJSON() as { action?: string; todo_ids?: string[] } | null
        const action = body?.action
        if (action === 'completed') newStatus = 'done'
        else if (action === 'snoozed') newStatus = 'snoozed'
        else if (action === 'dismissed') newStatus = 'dismissed'
        // 同步 todoState
        if (body?.todo_ids) {
          for (const tid of body.todo_ids) {
            if (todoState[tid]) {
              todoState[tid].status = newStatus
              if (newStatus === 'done') todoState[tid].completed_at = new Date().toISOString()
            }
          }
        }
      } catch { /* ignore */ }
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          success: [{ todo_id: MOCK_TODO_ID, new_status: newStatus }],
          failed: [],
        }),
      })
    }
    if (url.match(/\/reminders\/[^/]+\/action$/) && method === 'POST') {
      // actionReminder(todoId, action, snoozeHours?) — 推迟时更新 todo 状态为 snoozed
      const id = url.match(/\/reminders\/([^/]+)\/action$/)?.[1]
      try {
        const body = route.request().postDataJSON() as { action?: string; snooze_hours?: number } | null
        if (id && todoState[id] && body?.action === 'snoozed') {
          todoState[id].status = 'snoozed'
          if (body.snooze_hours) {
            const snoozeMs = body.snooze_hours * 3600 * 1000
            todoState[id].snoozed_until = new Date(Date.now() + snoozeMs).toISOString()
          }
        }
      } catch { /* ignore */ }
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ todo_id: id || MOCK_TODO_ID, action: 'completed', new_status: 'done' }),
      })
    }
    // ReminderPreferenceResponse: { user_id, preferred_times: string[], fatigue_threshold: number, quiet_hours_start, quiet_hours_end }
    if (url.includes('/reminders/preferences') && method === 'GET') {
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          user_id: MOCK_USER_ID,
          preferred_times: ['09:00', '20:00'],
          fatigue_threshold: 10,
          quiet_hours_start: '22:00',
          quiet_hours_end: '08:00',
        }),
      })
    }
    if (url.includes('/reminders/preferences') && method === 'PATCH') {
      let patched: { preferred_times?: string[]; fatigue_threshold?: number; quiet_hours_start?: string; quiet_hours_end?: string } = {}
      try {
        patched = route.request().postDataJSON() as typeof patched
      } catch { /* ignore */ }
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          user_id: MOCK_USER_ID,
          preferred_times: patched.preferred_times || ['09:00', '20:00'],
          fatigue_threshold: patched.fatigue_threshold ?? 10,
          quiet_hours_start: patched.quiet_hours_start || '22:00',
          quiet_hours_end: patched.quiet_hours_end || '08:00',
        }),
      })
    }
    // DailyReminderResponse: { items: ReminderItem[], total_pending, fatigue_remaining, is_quiet_hours }
    // ReminderItem: { todo_id, todo_type, title, description?, priority, dynamic_score?, due_date?, reminder_type, related_entity_id? }
    if (url.includes('/reminders/daily') && method === 'GET') {
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          items: [
            {
              todo_id: MOCK_TODO_ID,
              todo_type: mockTodo.todo_type,
              title: mockTodo.title,
              description: '准备技术评估材料以推进合作',
              priority: 2,
              dynamic_score: 80,
              due_date: mockTodo.due_date,
              reminder_type: 'followup',
              related_entity_id: MOCK_ENTITY_ID,
            },
            {
              todo_id: MOCK_PROMISE_TODO_ID,
              todo_type: mockPromiseTodo.todo_type,
              title: mockPromiseTodo.title,
              description: '王晓明承诺下周三前发邮件方案',
              priority: 3,
              dynamic_score: 75,
              due_date: mockPromiseTodo.due_date,
              reminder_type: 'promise_due',
              related_entity_id: MOCK_ENTITY_ID,
            },
          ],
          total_pending: 2,
          fatigue_remaining: 8,
          is_quiet_hours: false,
        }),
      })
    }

    // ── Privacy / Export ───────────────────────────────────────────────────
    // PrivacyDataSummary 契约 (api.ts L1179-1182): { user_id, counts: Record<string, number> }
    // mine/index.tsx renderSummaryText() 通过 Object.entries(summary.counts) 遍历，
    // 若 counts 缺失会触发 Object.entries(undefined) → TypeError → modal 渲染崩溃
    if (url.includes('/privacy/data-summary') && method === 'GET') {
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          user_id: MOCK_USER_ID,
          counts: {
            events: 2,
            todos: 2,
            promises: 1,
            entities: 2,
            associations: 3,
            scheduled_events: 1,
            reminder_logs: 5,
            score_audit_logs: 0,
            relationship_briefs: 2,
          },
        }),
      })
    }
    // PrivacyDeleteResponse 契约 (api.ts L1173-1177): { deleted: Record<string, number>, audit_id, deleted_at }
    if (url.includes('/privacy/user-data') && method === 'DELETE') {
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          deleted: { events: 2, todos: 2, promises: 1, entities: 2, associations: 3 },
          audit_id: 'audit-test-001',
          deleted_at: new Date().toISOString(),
        }),
      })
    }
    if (url.match(/\/export\/[^/]+$/) && method === 'GET') {
      return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ download_url: '#', expires_at: tomorrowStr }) })
    }

    // ── Demands ────────────────────────────────────────────────────────────
    if (url.includes('/demands') && method === 'POST') {
      return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ id: 'demand-001', status: 'created' }) })
    }

    // ── Persons (relationship-brief) ───────────────────────────────────────
    if (url.includes('/persons/') && url.includes('/relationship-brief')) {
      return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ entity: mockEntity, relationship_stage: 'active', modules: [] }) })
    }

    // ── Health ─────────────────────────────────────────────────────────────
    if (url.includes('/health')) {
      return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ status: 'healthy' }) })
    }

    // ── 兜底 ───────────────────────────────────────────────────────────────
    return route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ items: [], total: 0 }),
    })
  })
}
