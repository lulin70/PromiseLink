import { useEffect, useState, useRef } from 'react'
import { View, Text, ScrollView } from '@tarojs/components'
import Taro from '@tarojs/taro'
import { getEvents, getEventDetail, retryEvent, updateTodoStatus, dismissTodo, deleteEvent, confirmTodo, getScheduledEvents, cancelScheduledEvent, createScheduledEvent, EventResponse, EventDetailResponse, ScheduledEventResponse } from '../../services/api'
import { isLoggedIn } from '../../services/auth'
import { navigateToEntity } from '../../services/navigation'
import { NAV_EVENTS } from '../../services/navigation'
import './index.scss'

const DATE_FILTERS = [
  { value: 'today', label: '今天' },
  { value: 'week', label: '本周' },
  { value: 'month', label: '本月' },
  { value: 'upcoming', label: '预定日程' },
  { value: 'all', label: '全部' },
]

function getDateRange(filter: string): { start: string; end: string } | null {
  const now = new Date()
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate())
  const start = today.toISOString().split('T')[0]

  switch (filter) {
    case 'today': {
      const end = new Date(today.getTime() + 86400000 - 1)
      return { start, end: end.toISOString().split('T')[0] }
    }
    case 'week': {
      const dayOfWeek = today.getDay() || 7
      const weekStart = new Date(today.getTime() - (dayOfWeek - 1) * 86400000)
      const weekEnd = new Date(weekStart.getTime() + 6 * 86400000)
      return {
        start: weekStart.toISOString().split('T')[0],
        end: weekEnd.toISOString().split('T')[0],
      }
    }
    case 'month': {
      const monthStart = new Date(now.getFullYear(), now.getMonth(), 1)
      const monthEnd = new Date(now.getFullYear(), now.getMonth() + 1, 0)
      return {
        start: monthStart.toISOString().split('T')[0],
        end: monthEnd.toISOString().split('T')[0],
      }
    }
    default:
      return null
  }
}

function formatEventTime(timestamp: string): string {
  const d = new Date(timestamp)
  const now = new Date()
  const month = d.getMonth() + 1
  const day = d.getDate()
  const hour = String(d.getHours()).padStart(2, '0')
  const minute = String(d.getMinutes()).padStart(2, '0')
  if (d.getFullYear() !== now.getFullYear()) {
    return `${d.getFullYear()}/${month}/${day} ${hour}:${minute}`
  }
  return `${month}/${day} ${hour}:${minute}`
}

const EVENT_TYPE_LABELS: Record<string, string> = {
  manual: '手动',
  meeting: '会议',
  call: '电话',
  wechat_forward: '微信',
  email: '邮件',
  card_save: '名片',
}

export default function EventsPage() {
  const [events, setEvents] = useState<EventResponse[]>([])
  const [scheduledEvents, setScheduledEvents] = useState<ScheduledEventResponse[]>([])
  const [activeFilter, setActiveFilter] = useState(0)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [expandedId, setExpandedId] = useState<string | null>(null)
  const [expandedDetail, setExpandedDetail] = useState<EventDetailResponse | null>(null)
  const [retryingId, setRetryingId] = useState<string | null>(null)
  const [searchQuery, setSearchQuery] = useState('')
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  // P1: Create scheduled event state
  const [showCreateSchedule, setShowCreateSchedule] = useState(false)
  const [scheduleTopic, setScheduleTopic] = useState('')
  const [scheduleDate, setScheduleDate] = useState('')
  const [scheduleTime, setScheduleTime] = useState('')
  const [scheduleParticipants, setScheduleParticipants] = useState('')
  const [scheduleLocation, setScheduleLocation] = useState('')
  const [creatingSchedule, setCreatingSchedule] = useState(false)

  useEffect(() => {
    if (!isLoggedIn()) {
      Taro.redirectTo({ url: '/pages/index/index' })
      return
    }
    if (debounceRef.current) {
      clearTimeout(debounceRef.current)
    }
    debounceRef.current = setTimeout(() => {
      loadEvents()
    }, 300)
    return () => {
      if (debounceRef.current) {
        clearTimeout(debounceRef.current)
      }
    }
  }, [activeFilter, searchQuery])

  // Listen for cross-tab navigation to open a specific event detail
  const pendingNavId = useRef<string | null>(null)

  useEffect(() => {
    const handler = (data: { eventId: string }) => {
      pendingNavId.current = data.eventId
      setActiveFilter(4) // Switch to "全部" filter so the event is visible
    }
    Taro.eventCenter.on(NAV_EVENTS.OPEN_EVENT_DETAIL, handler)
    return () => {
      Taro.eventCenter.off(NAV_EVENTS.OPEN_EVENT_DETAIL, handler)
    }
  }, [])

  // After events load, expand the pending navigation target
  useEffect(() => {
    if (pendingNavId.current && events.length > 0) {
      const targetId = pendingNavId.current
      pendingNavId.current = null
      setExpandedId(targetId)
      getEventDetail(targetId).then(setExpandedDetail).catch(() => setExpandedDetail(null))
    }
  }, [events])

  async function loadEvents() {
    try {
      setLoading(true)
      setError('')
      const filterValue = DATE_FILTERS[activeFilter].value

      if (filterValue === 'upcoming') {
        // Load scheduled events from the dedicated API
        const res = await getScheduledEvents(undefined, undefined, undefined, 50, 0)
        // Show pending and overdue first, then recorded, exclude cancelled
        const active = res.items
          .filter(se => se.status !== 'cancelled')
          .sort((a, b) => {
            // pending/overdue before recorded
            const statusOrder: Record<string, number> = { overdue: 0, pending: 1, recorded: 2 }
            const sa = statusOrder[a.status] ?? 3
            const sb = statusOrder[b.status] ?? 3
            if (sa !== sb) return sa - sb
            return new Date(a.scheduled_at).getTime() - new Date(b.scheduled_at).getTime()
          })
        setScheduledEvents(active)
        setEvents([])
      } else {
        const res = await getEvents(50, 0, searchQuery || undefined)
        let filtered = res.items

        const range = getDateRange(filterValue)
        if (range) {
          filtered = filtered.filter(e => {
            const localDate = new Date(e.timestamp)
            const d = `${localDate.getFullYear()}-${String(localDate.getMonth() + 1).padStart(2, '0')}-${String(localDate.getDate()).padStart(2, '0')}`
            return d >= range.start && d <= range.end
          })
        }
        // Sort by timestamp descending (newest first)
        filtered.sort((a, b) => new Date(b.timestamp).getTime() - new Date(a.timestamp).getTime())
        setEvents(filtered)
        setScheduledEvents([])
      }
    } catch (err) {
      const msg = err instanceof Error ? err.message : '加载失败'
      setError(msg)
    } finally {
      setLoading(false)
    }
  }

  async function handleExpand(eventId: string) {
    if (expandedId === eventId) {
      setExpandedId(null)
      setExpandedDetail(null)
      return
    }
    setExpandedId(eventId)
    try {
      const detail = await getEventDetail(eventId)
      setExpandedDetail(detail)
    } catch {
      setExpandedDetail(null)
    }
  }

  async function handleRetry(eventId: string) {
    try {
      setRetryingId(eventId)
      await retryEvent(eventId)
      Taro.showToast({ title: '已重新处理', icon: 'success' })
      // Refresh detail
      const detail = await getEventDetail(eventId)
      setExpandedDetail(detail)
      // Also refresh list
      loadEvents()
    } catch (err) {
      Taro.showToast({ title: '重试失败', icon: 'error' })
    } finally {
      setRetryingId(null)
    }
  }

  async function handleDeleteEvent(eventId: string) {
    try {
      const res = await Taro.showModal({
        title: '确认删除',
        content: '确认删除此事件？',
        confirmText: '删除',
        cancelText: '取消',
        confirmColor: '#ff4d4f',
      })
      if (!res.confirm) return
      await deleteEvent(eventId)
      Taro.showToast({ title: '已删除', icon: 'success' })
      setExpandedId(null)
      setExpandedDetail(null)
      loadEvents()
    } catch (err) {
      Taro.showToast({ title: '删除失败', icon: 'error' })
    }
  }

  async function handleCreateSchedule() {
    if (!scheduleTopic.trim() || !scheduleDate || !scheduleTime) {
      Taro.showToast({ title: '请填写主题和时间', icon: 'error' })
      return
    }
    try {
      setCreatingSchedule(true)
      const scheduledAt = new Date(`${scheduleDate}T${scheduleTime}:00+08:00`).toISOString()
      const participants = scheduleParticipants
        ? scheduleParticipants.split(/[,，、]/).map(name => ({ name: name.trim() }))
        : []
      await createScheduledEvent({
        scheduled_at: scheduledAt,
        topic: scheduleTopic.trim(),
        participants,
        location: scheduleLocation.trim() || undefined,
        event_type: 'meeting',
      })
      Taro.showToast({ title: '已创建预定日程', icon: 'success' })
      setShowCreateSchedule(false)
      setScheduleTopic('')
      setScheduleDate('')
      setScheduleTime('')
      setScheduleParticipants('')
      setScheduleLocation('')
      // Switch to upcoming tab and refresh
      setActiveFilter(3)
    } catch (err) {
      Taro.showToast({ title: '创建失败', icon: 'error' })
    } finally {
      setCreatingSchedule(false)
    }
  }

  return (
    <View className='page-events'>
      <View className='header'>
        <Text className='header-title'>事件列表</Text>
        <View className='header-action' onClick={() => Taro.navigateTo({ url: '/pages/input/index' })}>
          <Text className='add-icon'>+</Text>
        </View>
      </View>

      {/* Date Filter Tabs */}
      <View className='filter-tabs'>
        {DATE_FILTERS.map((filter, idx) => (
          <View
            key={filter.value}
            className={`filter-tab ${activeFilter === idx ? 'active' : ''}`}
            onClick={() => setActiveFilter(idx)}
          >
            <Text>{filter.label}</Text>
          </View>
        ))}
      </View>

      {/* Search Bar */}
      <View className='search-bar'>
        <input
          className='search-input'
          type='text'
          placeholder='搜索事件...'
          value={searchQuery}
          onInput={(e) => setSearchQuery(e.currentTarget.value)}
        />
      </View>

      {loading && (
        <View className='loading'>
          <Text>加载中...</Text>
        </View>
      )}

      {error && (
        <View className='error-container'>
          <Text className='error-text'>{error}</Text>
        </View>
      )}

      <ScrollView scrollY className='event-list'>
        {!loading && events.length === 0 && scheduledEvents.length === 0 && (
          <View className='empty'>
            <Text>暂无事件</Text>
            <Text className='empty-hint'>点击右上角 + 录入新事件</Text>
          </View>
        )}

        {/* Scheduled Event Cards (预定日程) */}
        {activeFilter === 3 && (
          <View className='create-schedule-btn' onClick={() => setShowCreateSchedule(true)}>
            <Text>+ 新建预定日程</Text>
          </View>
        )}
        {scheduledEvents.map(se => (
          <View
            key={se.id}
            className={`event-card scheduled-card status-${se.status}`}
          >
            <View className='event-card-main'>
              <View className='event-card-left'>
                <Text className='event-time'>{formatEventTime(se.scheduled_at)}</Text>
              </View>
              <View className='event-card-right'>
                <View className='event-title-row'>
                  <Text className='event-title'>{se.topic}</Text>
                  <View className={`schedule-status status-${se.status}`}>
                    <Text>{se.status === 'overdue' ? '已过期' : se.status === 'recorded' ? '已录入' : '待录入'}</Text>
                  </View>
                </View>
                <View className='event-meta'>
                  <Text className='event-type-tag'>{EVENT_TYPE_LABELS[se.event_type] || se.event_type}</Text>
                  {se.participants && se.participants.length > 0 && (
                    <View className='event-entities'>
                      {se.participants.map((p, idx) => (
                        <Text key={idx} className='entity-link'>{p.name}</Text>
                      ))}
                    </View>
                  )}
                  {se.location && <Text className='se-location'>{se.location}</Text>}
                </View>
              </View>
            </View>
            {/* Action buttons for pending/overdue */}
            {(se.status === 'pending' || se.status === 'overdue') && (
              <View className='scheduled-actions'>
                <View
                  className='action-btn record-btn'
                  onClick={() => Taro.navigateTo({ url: `/pages/input/index?scheduled_event_id=${se.id}` })}
                >
                  <Text>录入</Text>
                </View>
                <View
                  className='action-btn cancel-btn'
                  onClick={async () => {
                    try {
                      await cancelScheduledEvent(se.id)
                      Taro.showToast({ title: '已取消预定', icon: 'success' })
                      loadEvents()
                    } catch {
                      Taro.showToast({ title: '取消失败', icon: 'error' })
                    }
                  }}
                >
                  <Text>取消预定</Text>
                </View>
              </View>
            )}
            {/* Recorded: link to event */}
            {se.status === 'recorded' && se.linked_event_id && (
              <View className='scheduled-actions'>
                <View
                  className='action-btn view-event-btn'
                  onClick={() => {
                    setActiveFilter(4) // Switch to "全部" to find the event
                    setTimeout(() => handleExpand(se.linked_event_id!), 500)
                  }}
                >
                  <Text>查看录入详情</Text>
                </View>
              </View>
            )}
          </View>
        ))}

        {events.map(event => (
          <View
            key={event.id}
            className={`event-card ${expandedId === event.id ? 'expanded' : ''}`}
            onClick={() => handleExpand(event.id)}
          >
            <View className='event-card-main'>
              <View className='event-card-left'>
                <Text className='event-time'>{formatEventTime(event.timestamp)}</Text>
              </View>
              <View className='event-card-right'>
                <View className='event-title-row'>
                  <Text className='event-title'>{event.title || '未命名事件'}</Text>
                  {event.status !== 'completed' && event.status !== 'degraded_completed' && (
                    <View className={`event-status status-${event.status === 'failed' || event.status === 'awaiting_retry' ? 'failed' : 'processing'}`}>
                      <Text>{event.status === 'failed' || event.status === 'awaiting_retry' ? '解析失败' : '解析中'}</Text>
                    </View>
                  )}
                </View>
                <View className='event-meta'>
                  <Text className='event-type-tag'>{EVENT_TYPE_LABELS[event.event_type] || event.event_type}</Text>
                  {event.entities && event.entities.length > 0 && (
                    <View className='event-entities'>
                      {event.entities.map(ent => (
                        <Text
                          key={ent.id}
                          className='entity-link'
                          onClick={(e) => {
                            e.stopPropagation()
                            navigateToEntity(ent.id, ent.name)
                          }}
                        >
                          {ent.name}
                        </Text>
                      ))}
                    </View>
                  )}
                </View>
              </View>
              <Text className='expand-arrow'>{expandedId === event.id ? '▲' : '▼'}</Text>
            </View>

            {expandedId === event.id && expandedDetail && (
              <View className='event-detail'>
                {expandedDetail.raw_text && (
                  <View className='detail-row'>
                    <Text className='detail-label'>原始内容</Text>
                    <Text className='detail-value'>{expandedDetail.raw_text}</Text>
                  </View>
                )}
                <View className='detail-row'>
                  <Text className='detail-label'>解析状态</Text>
                  <View className='status-row'>
                    <Text className='detail-value'>
                      {(expandedDetail.status === 'completed' || expandedDetail.status === 'degraded_completed') ? '已解析' : expandedDetail.status === 'failed' || expandedDetail.status === 'awaiting_retry' ? '解析失败' : '解析中'}
                    </Text>
                    {(expandedDetail.status === 'failed' || expandedDetail.status === 'awaiting_retry') && (
                      <Text
                        className={`retry-btn ${retryingId === expandedDetail.id ? 'retrying' : ''}`}
                        onClick={() => handleRetry(expandedDetail.id)}
                      >
                        {retryingId === expandedDetail.id ? '处理中...' : '重新处理'}
                      </Text>
                    )}
                  </View>
                </View>
                <View className='detail-row'>
                  <Text className='detail-label'>创建时间</Text>
                  <Text className='detail-value'>{new Date(expandedDetail.created_at).toLocaleString('zh-CN')}</Text>
                </View>
                {/* Delete button */}
                <View className='detail-row'>
                  <Text
                    className='delete-event-btn'
                    onClick={(e) => {
                      e.stopPropagation()
                      handleDeleteEvent(expandedDetail.id)
                    }}
                  >
                    🗑 删除此事件
                  </Text>
                </View>
                {expandedDetail.related_todos && expandedDetail.related_todos.length > 0 && (
                  <View className='detail-row detail-section'>
                    <Text className='detail-label'>相关待办 ({expandedDetail.related_todos.length})</Text>
                    <View className='related-todos'>
                      {expandedDetail.related_todos.map(todo => {
                        const isPendingConfirm = todo.confirmation_status === 'pending' || todo.confirmation_status === 'auto_set'
                        const actionLabel = todo.action_type === 'my_promise' ? '我的承诺' : todo.action_type === 'their_promise' ? '对方承诺' : ''
                        return (
                          <View key={todo.id} className={`related-todo-item ${isPendingConfirm ? 'pending-confirm-item' : ''}`}>
                            <View className='related-todo-header'>
                              <Text className='related-todo-title'>{todo.title}</Text>
                              {actionLabel && <Text className='todo-action-tag'>{actionLabel}</Text>}
                            </View>
                            {isPendingConfirm && todo.evidence_quote && (
                              <Text className='evidence-quote'>"{todo.evidence_quote}"</Text>
                            )}
                            <View className='related-todo-actions'>
                              {isPendingConfirm ? (
                                <>
                                  <Text className='related-todo-status pending-confirm-status'>待确认</Text>
                                  <Text className='related-todo-btn confirm-btn' onClick={(e) => {
                                    e.stopPropagation()
                                    confirmTodo(todo.id, { confirmation_status: 'confirmed' }).then(() => {
                                      if (expandedDetail) getEventDetail(expandedDetail.id).then(setExpandedDetail)
                                    })
                                  }}>确认</Text>
                                  <Text className='related-todo-btn reject-btn' onClick={(e) => {
                                    e.stopPropagation()
                                    confirmTodo(todo.id, { confirmation_status: 'rejected' }).then(() => {
                                      if (expandedDetail) getEventDetail(expandedDetail.id).then(setExpandedDetail)
                                    })
                                  }}>忽略</Text>
                                </>
                              ) : (
                                <>
                                  <Text className='related-todo-status'>{todo.status === 'done' ? '已完成' : todo.status === 'dismissed' ? '已忽略' : '待处理'}</Text>
                                  {todo.status === 'pending' && (
                                    <>
                                      <Text className='related-todo-btn done-btn' onClick={(e) => {
                                        e.stopPropagation()
                                        updateTodoStatus(todo.id, 'done').then(() => {
                                          if (expandedDetail) getEventDetail(expandedDetail.id).then(setExpandedDetail)
                                        })
                                      }}>完成</Text>
                                      <Text className='related-todo-btn dismiss-btn' onClick={(e) => {
                                        e.stopPropagation()
                                        dismissTodo(todo.id).then(() => {
                                          if (expandedDetail) getEventDetail(expandedDetail.id).then(setExpandedDetail)
                                        })
                                      }}>忽略</Text>
                                    </>
                                  )}
                                </>
                              )}
                            </View>
                          </View>
                        )
                      })}
                    </View>
                  </View>
                )}
              </View>
            )}
          </View>
        ))}
      </ScrollView>

      {/* Create Scheduled Event Modal */}
      {showCreateSchedule && (
        <View className='modal-overlay' onClick={() => setShowCreateSchedule(false)}>
          <View className='modal-content create-schedule-modal' onClick={e => e.stopPropagation()}>
            <View className='modal-header'>
              <Text className='modal-title'>新建预定日程</Text>
              <Text className='modal-close' onClick={() => setShowCreateSchedule(false)}>✕</Text>
            </View>
            <View className='modal-body'>
              <View className='form-group'>
                <Text className='form-label'>主题 *</Text>
                <input
                  className='form-input'
                  type='text'
                  placeholder='如：与张总讨论合作'
                  value={scheduleTopic}
                  onInput={e => setScheduleTopic(e.currentTarget.value)}
                />
              </View>
              <View className='form-group'>
                <Text className='form-label'>日期 *</Text>
                <input
                  className='form-input'
                  type='date'
                  value={scheduleDate}
                  onInput={e => setScheduleDate(e.currentTarget.value)}
                />
              </View>
              <View className='form-group'>
                <Text className='form-label'>时间 *</Text>
                <input
                  className='form-input'
                  type='time'
                  value={scheduleTime}
                  onInput={e => setScheduleTime(e.currentTarget.value)}
                />
              </View>
              <View className='form-group'>
                <Text className='form-label'>参与者</Text>
                <input
                  className='form-input'
                  type='text'
                  placeholder='用逗号分隔多人'
                  value={scheduleParticipants}
                  onInput={e => setScheduleParticipants(e.currentTarget.value)}
                />
              </View>
              <View className='form-group'>
                <Text className='form-label'>地点</Text>
                <input
                  className='form-input'
                  type='text'
                  placeholder='如：望京SOHO'
                  value={scheduleLocation}
                  onInput={e => setScheduleLocation(e.currentTarget.value)}
                />
              </View>
              <View
                className={`submit-schedule-btn ${creatingSchedule ? 'loading' : ''}`}
                onClick={creatingSchedule ? undefined : handleCreateSchedule}
              >
                <Text>{creatingSchedule ? '创建中...' : '创建预定'}</Text>
              </View>
            </View>
          </View>
        </View>
      )}
    </View>
  )
}
