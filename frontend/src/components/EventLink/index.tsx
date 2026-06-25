import { View, Text } from '@tarojs/components'
import { navigateToEventDetail } from '../../services/navigation'
import './index.scss'

interface EventLinkProps {
  eventId: string
  title: string
  timestamp?: string
  eventType?: string
}

const EVENT_TYPE_LABELS: Record<string, string> = {
  manual: '手动',
  meeting: '会议',
  call: '电话',
  wechat_forward: '微信',
  email: '邮件',
  card_save: '名片',
}

function formatEventDate(timestamp?: string): string {
  if (!timestamp) return ''
  const d = new Date(timestamp)
  const now = new Date()
  const month = d.getMonth() + 1
  const day = d.getDate()
  if (d.getFullYear() !== now.getFullYear()) {
    return `${d.getFullYear()}/${month}/${day}`
  }
  return `${month}/${day}`
}

export default function EventLink({ eventId, title, timestamp, eventType }: EventLinkProps) {
  return (
    <View
      className='event-link-card'
      onClick={(e) => {
        e.stopPropagation()
        navigateToEventDetail(eventId)
      }}
    >
      <View className='event-link-icon'>
        <Text className='event-link-icon-text'>日</Text>
      </View>
      <View className='event-link-info'>
        <Text className='event-link-title'>{title || '未命名事件'}</Text>
        <View className='event-link-meta'>
          {eventType && <Text className='event-link-type'>{EVENT_TYPE_LABELS[eventType] || eventType}</Text>}
          {timestamp && <Text className='event-link-date'>{formatEventDate(timestamp)}</Text>}
        </View>
      </View>
      <Text className='event-link-arrow'>›</Text>
    </View>
  )
}
