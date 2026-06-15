import Taro from '@tarojs/taro'

// Event names
export const NAV_EVENTS = {
  OPEN_ENTITY_DETAIL: 'nav:open_entity_detail',
  OPEN_EVENT_DETAIL: 'nav:open_event_detail',
} as const

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
