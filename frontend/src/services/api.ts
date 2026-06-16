// PromiseLink API service layer
// All API calls go through this module

import { getToken, getSavedSecret, getUserId, directLogin, removeToken } from './auth'

const API_BASE = '/api/v1'

interface RequestOptions {
  method: 'GET' | 'POST' | 'PATCH' | 'DELETE'
  path: string
  body?: unknown
  params?: Record<string, string | number | undefined>
  _retryCount?: number
}

async function request<T>({ method, path, body, params, _retryCount = 0 }: RequestOptions): Promise<T> {
  const url = new URL(`${API_BASE}${path}`, window.location.origin)
  if (params) {
    Object.entries(params).forEach(([key, value]) => {
      if (value !== undefined && value !== '') {
        url.searchParams.set(key, String(value))
      }
    })
  }

  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
  }
  const token = getToken()
  if (token) {
    headers['Authorization'] = `Bearer ${token}`
  }

  const res = await fetch(url.toString(), {
    method,
    headers,
    body: body ? JSON.stringify(body) : undefined,
  })

  // Handle 401: token expired → clear stale token → auto re-login with saved credentials → retry once
  if (res.status === 401 && _retryCount === 0) {
    console.warn('[API] Token expired (401), clearing stale token and attempting re-login...')
    removeToken() // Clear invalid token first
    const secret = getSavedSecret()
    if (secret) {
      const newToken = await directLogin(secret, getUserId())
      if (newToken) {
        console.warn('[API] Re-login success, retrying request...')
        return request({ method, path, body, params, _retryCount: 1 })
      }
      console.warn('[API] Re-login failed (secret may be wrong or server down)')
    } else {
      console.warn('[API] No saved credentials, cannot auto re-login')
    }
  }

  // Handle 429: rate limited → wait 2s → retry once
  if (res.status === 429 && _retryCount === 0) {
    console.warn('[API] Rate limited, waiting 2s...')
    await new Promise(resolve => setTimeout(resolve, 2000))
    return request({ method, path, body, params, _retryCount: 1 })
  }

  if (!res.ok) {
    const errorText = await res.text().catch(() => 'Unknown error')
    throw new Error(`API Error ${res.status}: ${errorText}`)
  }

  // 204 No Content has no body
  if (res.status === 204) {
    return undefined as T
  }

  return res.json()
}

// ── Auth ──

export interface LoginResponse {
  access_token: string
  token_type: string
  user_id: string
}

export async function login(pocSecret: string, userId: string = 'poc-user'): Promise<LoginResponse> {
  return request<LoginResponse>({
    method: 'POST',
    path: '/auth/login',
    body: { user_id: userId, poc_secret: pocSecret },
  })
}

// ── Events ──

export interface EventCreateRequest {
  event_type: string
  source: string
  title?: string
  raw_text?: string
  metadata?: Record<string, unknown>
}

export interface EventEntityRef {
  id: string
  name: string
}

export interface EventResponse {
  id: string
  user_id: string
  event_type: string
  title: string
  status: string
  input_scope?: string
  timestamp: string
  created_at: string
  entities?: EventEntityRef[]
}

export interface EventCreateResponse extends EventResponse {
  pipeline_status: string
  entity_count: number
  todo_count: number
}

export interface EventTodoRef {
  id: string
  todo_type: string
  title: string
  status: string
}

export interface EventDetailResponse extends EventResponse {
  raw_text?: string
  event_metadata?: Record<string, unknown>
  pipeline?: string | null
  processed_at?: string | null
  related_todos?: EventTodoRef[]
}

export interface PaginatedResponse<T> {
  items: T[]
  total: number
  limit: number
  offset: number
}

export async function createEvent(rawText: string, eventType: string = 'manual'): Promise<EventCreateResponse> {
  return request<EventResponse>({
    method: 'POST',
    path: '/events',
    body: {
      event_type: eventType,
      source: 'h5-frontend',
      raw_text: rawText,
    },
  })
}

export async function uploadEventFile(file: File, eventType: string): Promise<EventCreateResponse> {
  const formData = new FormData()
  formData.append('file', file)
  formData.append('event_type', eventType)

  const url = new URL(`${API_BASE}/events/upload`, window.location.origin)
  const headers: Record<string, string> = {}
  const token = getToken()
  if (token) {
    headers['Authorization'] = `Bearer ${token}`
  }
  // Note: do NOT set Content-Type; browser sets it with boundary for multipart/form-data

  const res = await fetch(url.toString(), {
    method: 'POST',
    headers,
    body: formData,
  })

  if (!res.ok) {
    const errorText = await res.text().catch(() => 'Unknown error')
    throw new Error(`API Error ${res.status}: ${errorText}`)
  }

  return res.json()
}

export async function getEvents(limit: number = 20, offset: number = 0, search?: string): Promise<PaginatedResponse<EventResponse>> {
  return request<PaginatedResponse<EventResponse>>({
    method: 'GET',
    path: '/events',
    params: { limit, offset, search },
  })
}

export async function getEventDetail(eventId: string): Promise<EventDetailResponse> {
  return request<EventDetailResponse>({
    method: 'GET',
    path: `/events/${eventId}`,
  })
}

export async function retryEvent(eventId: string): Promise<EventResponse> {
  return request<EventResponse>({
    method: 'POST',
    path: `/events/${eventId}/retry`,
  })
}

export async function acceptDegradedEvent(eventId: string): Promise<EventResponse> {
  return request<EventResponse>({
    method: 'POST',
    path: `/events/${eventId}/accept-degraded`,
  })
}

// P0: Delete event
export async function deleteEvent(eventId: string): Promise<void> {
  return request<void>({
    method: 'DELETE',
    path: `/events/${eventId}`,
  })
}

// P1: Batch create events
export interface BatchEventCreateItem {
  event_type: string
  source: string
  title?: string
  raw_text?: string
  metadata?: Record<string, unknown>
}

export interface BatchEventCreateResponse {
  created: EventCreateResponse[]
  failed: Array<{ index: number; error: string }>
  total_requested: number
  total_created: number
}

export async function batchCreateEvents(events: BatchEventCreateItem[]): Promise<BatchEventCreateResponse> {
  return request<BatchEventCreateResponse>({
    method: 'POST',
    path: '/events/batch',
    body: { events },
  })
}

// ── Todos ──

export interface TodoResponse {
  id: string
  user_id: string
  todo_type: string
  title: string
  description?: string
  related_entity_id?: string
  related_entity_name?: string
  priority: number
  priority_override?: string
  priority_source: string
  status: string
  due_date?: string
  source_event_id?: string
  source_event_title?: string
  source_event_date?: string
  created_at?: string
  action_type?: string
  fulfillment_status?: string
}

export async function getTodos(
  status?: string,
  limit: number = 50,
  offset: number = 0,
  sort_by: string = 'urgency',
  search?: string,
  todo_type?: string
): Promise<PaginatedResponse<TodoResponse>> {
  return request<PaginatedResponse<TodoResponse>>({
    method: 'GET',
    path: '/todos',
    params: { status, limit, offset, sort_by, search, todo_type },
  })
}

export async function updateTodoStatus(todoId: string, status: string): Promise<TodoResponse> {
  return request<TodoResponse>({
    method: 'PATCH',
    path: `/todos/${todoId}`,
    body: { status },
  })
}

export async function dismissTodo(todoId: string): Promise<TodoResponse> {
  return request<TodoResponse>({
    method: 'PATCH',
    path: `/todos/${todoId}`,
    body: { status: 'dismissed' },
  })
}

// P0: Delete todo
export async function deleteTodo(todoId: string): Promise<void> {
  return request<void>({
    method: 'DELETE',
    path: `/todos/${todoId}`,
  })
}

// P2: Get todo detail
export interface TodoDetailResponse extends TodoResponse {
  properties?: Record<string, unknown> | null
  snoozed_until?: string | null
  completed_at?: string | null
}

export async function getTodoDetail(todoId: string): Promise<TodoDetailResponse> {
  return request<TodoDetailResponse>({
    method: 'GET',
    path: `/todos/${todoId}`,
  })
}

// ── Entities ──

export interface EntityResponse {
  id: string
  user_id: string
  entity_type: string
  name: string
  canonical_name: string
  aliases?: string[]
  properties?: Record<string, unknown>
  confidence: number
  status: string
  created_at?: string
}

export interface EntityDetailResponse extends EntityResponse {
  source_event_id?: string
  updated_at?: string
}

export async function getEntities(
  search?: string,
  limit: number = 50,
  offset: number = 0
): Promise<PaginatedResponse<EntityResponse>> {
  return request<PaginatedResponse<EntityResponse>>({
    method: 'GET',
    path: '/entities',
    params: { search, limit, offset },
  })
}

export async function getEntityDetail(entityId: string): Promise<EntityDetailResponse> {
  return request<EntityDetailResponse>({
    method: 'GET',
    path: `/entities/${entityId}`,
  })
}

export async function updateEntity(
  entityId: string,
  data: { name?: string; aliases?: string[]; properties?: Record<string, unknown> }
): Promise<EntityDetailResponse> {
  return request<EntityDetailResponse>({
    method: 'PATCH',
    path: `/entities/${entityId}`,
    body: data,
  })
}

// P0: Delete entity
export async function deleteEntity(entityId: string): Promise<void> {
  return request<void>({
    method: 'DELETE',
    path: `/entities/${entityId}`,
  })
}

export interface EntityHistoryEvent {
  id: string
  event_type: string
  title: string
  timestamp: string
  status: string
  raw_text_preview?: string
}

export interface EntityHistoryTodo {
  id: string
  todo_type: string
  title: string
  priority: number
  status: string
  created_at?: string
}

export interface EntityHistoryAssociation {
  id: string
  association_type: string
  target_entity_name: string
  strength: number
}

export interface EntityHistoryResponse {
  entity: EntityDetailResponse
  events: EntityHistoryEvent[]
  todos: EntityHistoryTodo[]
  associations: EntityHistoryAssociation[]
}

export async function getEntityHistory(entityId: string): Promise<EntityHistoryResponse> {
  return request<EntityHistoryResponse>({
    method: 'GET',
    path: `/entities/${entityId}/history`,
  })
}

// ── Dormant Contacts (F-E3) ──

export interface DormantContactItem {
  entity_id: string
  name: string
  company?: string
  dormant_days: number
  reactivation_score: number
  last_interaction?: string
  last_event_summary?: string
  reason: string
  icebreaker_topic: string
  pending_their_promises: number
  relationship_stage: string
}

export interface DormantContactsResponse {
  items: DormantContactItem[]
  total: number
  limit: number
  min_days: number
}

export async function getDormantContacts(limit: number = 10, minDays: number = 60): Promise<DormantContactsResponse> {
  return request<DormantContactsResponse>({
    method: 'GET',
    path: '/entities/dormant',
    params: { limit, min_days: minDays },
  })
}

// ── Credit Score (F-E5) ──

export interface CreditScoreResponse {
  entity_id: string
  name: string
  score: number
  grade: string
  breakdown: {
    my_fulfillment_rate: number
    their_fulfillment_rate: number
    interaction_consistency: number
    total_interactions: number
  }
}

export async function getCreditScore(entityId: string): Promise<CreditScoreResponse> {
  return request<CreditScoreResponse>({
    method: 'GET',
    path: `/entities/${entityId}/credit-score`,
  })
}

// ── Promises ──

export interface PromiseItem {
  todo_id: string
  entity_id?: string
  entity_name?: string
  action_type: string
  description?: string
  due_date?: string
  fulfillment_status: string
  confirmation_status?: string
  created_at?: string
  source_event_id?: string
  source_event_title?: string
  source_event_date?: string
}

export interface PromiseListResponse {
  items: PromiseItem[]
  total: number
  offset: number
  limit: number
}

export interface PromiseStatsResponse {
  total: number
  my_promises: Record<string, number>
  their_promises: Record<string, number>
  fulfillment_rate: number
}

export async function getPromises(
  view: string = 'my-promises',
  status?: string,
  offset: number = 0,
  limit: number = 20,
  search?: string
): Promise<PromiseListResponse> {
  return request<PromiseListResponse>({
    method: 'GET',
    path: '/promises',
    params: { view, status, offset, limit, search },
  })
}

export async function getPromiseStats(): Promise<PromiseStatsResponse> {
  return request<PromiseStatsResponse>({
    method: 'GET',
    path: '/promises/stats',
  })
}

export async function updatePromiseStatus(todoId: string, fulfillmentStatus: string): Promise<void> {
  return request<void>({
    method: 'PATCH',
    path: `/promises/${todoId}/fulfillment`,
    body: { fulfillment_status: fulfillmentStatus },
  })
}

// ── Confirmations (F-E1) ──

export interface ConfirmationItem {
  todo_id: string
  todo_type: string
  title: string
  description?: string
  action_type?: string
  due_date?: string
  confirmation_status: string
  evidence_quote?: string
}

export async function getPendingConfirmations(eventId?: string): Promise<ConfirmationItem[]> {
  return request<ConfirmationItem[]>({
    method: 'GET',
    path: '/todos/pending-confirmations',
    params: eventId ? { event_id: eventId } : undefined,
  })
}

export interface ConfirmRequest {
  confirmation_status: string
  description?: string
  due_date?: string
}

export async function confirmTodo(todoId: string, req: ConfirmRequest): Promise<{ todo_id: string; confirmation_status: string; status: string }> {
  return request<{ todo_id: string; confirmation_status: string; status: string }>({
    method: 'PATCH',
    path: `/todos/${todoId}/confirm`,
    body: req,
  })
}

// ── Nudge Draft (F-E2) ──

export interface NudgeDraftResponse {
  todo_id: string
  nudge_text: string
  is_fallback: boolean
}

export async function getNudgeDraft(todoId: string): Promise<NudgeDraftResponse> {
  return request<NudgeDraftResponse>({
    method: 'GET',
    path: `/promises/${todoId}/nudge-draft`,
  })
}

// ── Dashboard ──

export interface DayViewSummary {
  total_events: number
  total_todos: number
  overdue_todos: number
  pending_promises: number
  upcoming_meetings: number
}

export interface DayViewEventItem {
  id: string
  event_type: string
  title: string
  time?: string
  status: string
  input_scope?: string
  entities: string[]
  todo_count: number
}

export interface DayViewTodoItem {
  id: string
  title: string
  todo_type: string
  action_type?: string
  status: string
  due_date?: string
  related_person?: string
  is_overdue: boolean
}

export interface DayViewResponse {
  date: string
  date_label: string
  events: DayViewEventItem[]
  todos: DayViewTodoItem[]
  summary: DayViewSummary
  adjacent_dates: {
    previous_day: string
    next_day: string
  }
}

export async function getDashboard(date?: string): Promise<DayViewResponse> {
  return request<DayViewResponse>({
    method: 'GET',
    path: '/dashboard/day-view',
    params: date ? { date } : undefined,
  })
}

// ── Supply-Demand (F-E4) ──

export interface SupplyDemandMatch {
  demander_name: string
  demander_company?: string
  demand_text: string
  supplier_name?: string
  supplier_company?: string
  supply_text?: string
  match_score: number
  match_reason: string
}

export interface SupplyDemandResponse {
  matches: SupplyDemandMatch[]
  total: number
}

export async function getSupplyDemand(limit: number = 5): Promise<SupplyDemandResponse> {
  return request<SupplyDemandResponse>({
    method: 'GET',
    path: '/dashboard/supply-demand',
    params: { limit },
  })
}

// ── F-G1: Relationship Health Diagnostic ──

export interface HealthItem {
  entity_id: string
  name: string
  company?: string
  stage: string
  stage_label: string
  stage_color: string
  health_score: number
  health_level: string  // "healthy" | "attention" | "at_risk"
  interaction_count: number
  last_interaction?: string
  days_since_last?: number
  pending_todos: number
  pending_promises: number
  suggestion: string
}

export interface RelationshipHealthResponse {
  total_entities: number
  healthy_count: number
  attention_count: number
  at_risk_count: number
  items: HealthItem[]
  summary_text: string
}

export async function getRelationshipHealth(limit: number = 20): Promise<RelationshipHealthResponse> {
  return request<RelationshipHealthResponse>({
    method: 'GET',
    path: '/dashboard/relationship-health',
    params: { limit },
  })
}

// ── F-G2: Relationship Stage ──

export interface StageSuggestion {
  target_stage: string
  target_stage_label: string
  target_stage_color: string
  reason: string
  action_hint: string
  requires_confirmation: boolean
}

export interface StageInfoResponse {
  entity_id: string
  name: string
  current_stage: string
  current_stage_label: string
  current_stage_color: string
  current_stage_desc: string
  stage_order: number
  suggestion: StageSuggestion | null
}

export async function getStageInfo(entityId: string): Promise<StageInfoResponse> {
  return request<StageInfoResponse>({
    method: 'GET',
    path: `/entities/${entityId}/stage-info`,
  })
}

// ── F-G3: Care Reminders ──

export interface CareReminderItem {
  entity_id: string
  name: string
  company?: string
  concern_category: string
  concern_detail: string
  care_type: string           // "personal" | "business" | "mixed"
  relevance_score: number
  source_event_title?: string
  days_since_mentioned: number
  suggested_action: string
  care_icon: string
}

export interface CareRemindersResponse {
  total: number
  personal_items: CareReminderItem[]
  business_items: CareReminderItem[]
  summary_text: string
}

export async function getCareReminders(limit: number = 10): Promise<CareRemindersResponse> {
  return request<CareRemindersResponse>({
    method: 'GET',
    path: '/dashboard/care-reminders',
    params: { limit },
  })
}

// ── Scheduled Events (预定日程) ──

export interface ParticipantItem {
  name: string
  entity_id?: string
  company?: string
}

export interface ScheduledEventCreateRequest {
  scheduled_at: string
  topic: string
  participants?: ParticipantItem[]
  location?: string
  event_type?: string
  reminder_at?: string
  metadata?: Record<string, unknown>
}

export interface ScheduledEventResponse {
  id: string
  user_id: string
  scheduled_at: string
  topic: string
  participants?: ParticipantItem[]
  location?: string
  event_type: string
  status: string
  linked_event_id?: string
  cancel_reason?: string
  reminder_at?: string
  metadata?: Record<string, unknown>
  created_at: string
  updated_at: string
  recorded_at?: string
}

export interface RecordRequest {
  raw_text: string
  event_type?: string
}

export interface RecordResponse {
  scheduled_event_id: string
  event_id: string
  pipeline_status: string
}

export interface CancelRequest {
  cancel_reason?: string
}

export async function getScheduledEvents(
  status?: string,
  scheduled_from?: string,
  scheduled_to?: string,
  limit: number = 50,
  offset: number = 0,
): Promise<PaginatedResponse<ScheduledEventResponse>> {
  return request<PaginatedResponse<ScheduledEventResponse>>({
    method: 'GET',
    path: '/scheduled-events',
    params: { status: status, scheduled_from, scheduled_to, limit, offset },
  })
}

export async function getScheduledEventDetail(id: string): Promise<ScheduledEventResponse> {
  return request<ScheduledEventResponse>({
    method: 'GET',
    path: `/scheduled-events/${id}`,
  })
}

export async function recordScheduledEvent(id: string, data: RecordRequest): Promise<RecordResponse> {
  return request<RecordResponse>({
    method: 'POST',
    path: `/scheduled-events/${id}/record`,
    body: data,
  })
}

export async function cancelScheduledEvent(id: string, data?: CancelRequest): Promise<ScheduledEventResponse> {
  return request<ScheduledEventResponse>({
    method: 'POST',
    path: `/scheduled-events/${id}/cancel`,
    body: data || {},
  })
}

// P1: Create scheduled event
export async function createScheduledEvent(data: ScheduledEventCreateRequest): Promise<ScheduledEventResponse> {
  return request<ScheduledEventResponse>({
    method: 'POST',
    path: '/scheduled-events',
    body: data,
  })
}

// P2: Update scheduled event
export async function updateScheduledEvent(
  id: string,
  data: Partial<ScheduledEventCreateRequest>
): Promise<ScheduledEventResponse> {
  return request<ScheduledEventResponse>({
    method: 'PATCH',
    path: `/scheduled-events/${id}`,
    body: data,
  })
}

// P2: Delete scheduled event
export async function deleteScheduledEvent(id: string): Promise<void> {
  return request<void>({
    method: 'DELETE',
    path: `/scheduled-events/${id}`,
  })
}

// ── Dashboard Range View (P1) ──

export interface RangeViewEventItem {
  id: string
  event_type: string
  title: string
  timestamp?: string
  status: string
}

export interface RangeViewTodoItem {
  id: string
  todo_type: string
  title: string
  status: string
  due_date?: string
}

export interface RangeViewResponse {
  range_start: string
  range_end: string
  label: string
  total_events: number
  total_todos: number
  events: RangeViewEventItem[]
  todos: RangeViewTodoItem[]
}

export async function getDashboardRangeView(startDate: string, endDate: string): Promise<RangeViewResponse> {
  return request<RangeViewResponse>({
    method: 'GET',
    path: '/dashboard/range-view',
    params: { start_date: startDate, end_date: endDate },
  })
}

// ── Morning Brief (P1) ──

export interface MorningBriefResponse {
  date: string
  greeting: string
  pending_promises: number
  pending_cares: number
  overdue_todos: number
  today_events: number
  today_todos: number
  key_persons: string[]
  summary_text: string
}

export async function getMorningBrief(): Promise<MorningBriefResponse> {
  return request<MorningBriefResponse>({
    method: 'GET',
    path: '/dashboard/morning-brief',
  })
}

// ── Aggregated Relationship Brief (P1) ──

export interface BriefModuleItem {
  module_name: string
  display_name: string
  icon: string
  has_data: boolean
  summary: string
  detail?: unknown
  priority?: string
}

export interface RelationshipBriefAggregatedResponse {
  id: string
  person_entity_id: string
  person_name?: string
  person_company?: string
  relationship_stage: string
  stage_label: string
  stage_color: string
  stage_icon: string
  strength_score: number
  strength_label: string
  last_interaction_date?: string
  last_interaction_summary?: string
  interaction_freq_summary?: string
  modules: BriefModuleItem[]
  suggested_actions: string[]
  version: number
  last_updated_at?: unknown
}

export async function getAggregatedRelationshipBrief(entityId: string): Promise<RelationshipBriefAggregatedResponse> {
  return request<RelationshipBriefAggregatedResponse>({
    method: 'GET',
    path: `/persons/${entityId}/relationship-brief/aggregated`,
  })
}

// ── Demand Input (P1) ──

export interface ExtractedDemand {
  tag: string
  detail: string
  related_entity_id?: string
}

export interface DemandInputResponse {
  status: string
  demand_id: string
  extracted: ExtractedDemand
}

export async function createDemand(text: string, source: string = 'text'): Promise<DemandInputResponse> {
  return request<DemandInputResponse>({
    method: 'POST',
    path: '/demands',
    body: { text, source },
  })
}

// ── Data Export (P1) ──

export async function exportData(userId: string): Promise<Record<string, unknown>> {
  return request<Record<string, unknown>>({
    method: 'GET',
    path: `/export/${userId}`,
  })
}

// ── Reminders (P1) ──

export interface ReminderItem {
  todo_id: string
  todo_type: string
  title: string
  description?: string
  priority: number
  dynamic_score?: number
  due_date?: string
  reminder_type: string
  related_entity_id?: string
}

export interface DailyReminderResponse {
  items: ReminderItem[]
  total_pending: number
  fatigue_remaining: number
  is_quiet_hours: boolean
}

export async function getDailyReminders(): Promise<DailyReminderResponse> {
  return request<DailyReminderResponse>({
    method: 'GET',
    path: '/reminders/daily',
  })
}

export interface ReminderActionResponse {
  todo_id: string
  action: string
  new_status: string
}

export async function actionReminder(todoId: string, action: string, snoozeHours?: number): Promise<ReminderActionResponse> {
  return request<ReminderActionResponse>({
    method: 'POST',
    path: `/reminders/${todoId}/action`,
    body: { action, snooze_hours: snoozeHours },
  })
}

// ── Credit Scores List (P2) ──

export interface CreditScoreListResponse {
  items: CreditScoreResponse[]
  total: number
}

export async function getCreditScores(minInteractions: number = 2, limit: number = 20): Promise<CreditScoreListResponse> {
  return request<CreditScoreListResponse>({
    method: 'GET',
    path: '/entities/credit-scores',
    params: { min_interactions: minInteractions, limit },
  })
}

// ── Stage Map (P2) ──

export interface StageMapItem {
  value: string
  label: string
  color: string
  icon: string
  description: string
  order: number
}

export interface StageMapResponse {
  stages: StageMapItem[]
}

export async function getStageMap(): Promise<StageMapResponse> {
  return request<StageMapResponse>({
    method: 'GET',
    path: '/entities/stage-map',
  })
}

// ── Relationship Briefs List (P2) ──

export interface RelationshipBriefResponse {
  id: string
  user_id: string
  person_entity_id: string
  relationship_stage: string
  brief_data: Record<string, unknown>
  version: number
  last_updated_at?: unknown
  created_at?: unknown
}

export async function getRelationshipBriefs(
  stage?: string,
  limit: number = 50,
  offset: number = 0
): Promise<PaginatedResponse<RelationshipBriefResponse>> {
  return request<PaginatedResponse<RelationshipBriefResponse>>({
    method: 'GET',
    path: '/relationship-briefs',
    params: { stage, limit, offset },
  })
}

export async function updateRelationshipBrief(
  briefId: string,
  data: { notes?: string; brief_data_partial?: Record<string, unknown>; expected_version: number }
): Promise<RelationshipBriefResponse> {
  return request<RelationshipBriefResponse>({
    method: 'PATCH',
    path: `/relationship-briefs/${briefId}`,
    body: data,
  })
}

// ── Reminder Preferences (P2) ──

export interface ReminderPreferenceResponse {
  user_id: string
  preferred_times: string[]
  fatigue_threshold: number
  quiet_hours_start: string
  quiet_hours_end: string
}

export async function getReminderPreferences(): Promise<ReminderPreferenceResponse> {
  return request<ReminderPreferenceResponse>({
    method: 'GET',
    path: '/reminders/preferences',
  })
}

export async function updateReminderPreferences(data: {
  preferred_times?: string[]
  fatigue_threshold?: number
  quiet_hours_start?: string
  quiet_hours_end?: string
}): Promise<ReminderPreferenceResponse> {
  return request<ReminderPreferenceResponse>({
    method: 'PATCH',
    path: '/reminders/preferences',
    body: data,
  })
}
