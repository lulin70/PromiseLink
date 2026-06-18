import Taro from '@tarojs/taro'

// Event names for cross-tab navigation (legacy, kept for backward compat)
export const NAV_EVENTS = {
  OPEN_ENTITY_DETAIL: 'nav:open_entity_detail',
  OPEN_EVENT_DETAIL: 'nav:open_event_detail',
} as const

// ── Cross-tab navigation (tab pages use switchTab + eventCenter) ──

// Navigate to entity detail (cross-tab)
export function navigateToEntity(entityId: string, entityName?: string) {
  // switchTab first, then trigger event after a short delay for page to render
  Taro.switchTab({ url: '/pages/entities/index' })
  setTimeout(() => {
    Taro.eventCenter.trigger(NAV_EVENTS.OPEN_ENTITY_DETAIL, { entityId, entityName })
  }, 300)
}

// Navigate to event detail (cross-tab)
export function navigateToEvent(eventId: string) {
  Taro.switchTab({ url: '/pages/events/index' })
  setTimeout(() => {
    Taro.eventCenter.trigger(NAV_EVENTS.OPEN_EVENT_DETAIL, { eventId })
  }, 300)
}

// ── Detail page navigation (non-tab pages use navigateTo) ──

// Navigate to event detail page
export function navigateToEventDetail(eventId: string) {
  Taro.navigateTo({ url: `/pages/events/detail?id=${eventId}` })
}

// Navigate to entity detail page
export function navigateToEntityDetail(entityId: string) {
  Taro.navigateTo({ url: `/pages/entities/detail?id=${entityId}` })
}

// Navigate to todo detail page
export function navigateToTodoDetail(todoId: string) {
  Taro.navigateTo({ url: `/pages/todos/detail?id=${todoId}` })
}

// Navigate to promise detail page
export function navigateToPromiseDetail(todoId: string) {
  Taro.navigateTo({ url: `/pages/promises/detail?id=${todoId}` })
}

// Navigate back to previous page
export function navigateBack() {
  Taro.navigateBack()
}
