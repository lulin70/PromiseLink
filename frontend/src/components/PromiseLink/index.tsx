import { View, Text } from '@tarojs/components'
import { navigateToPromiseDetail } from '../../services/navigation'
import './index.scss'

interface PromiseLinkProps {
  todoId: string
  description?: string
  title?: string
  dueDate?: string
  fulfillmentStatus?: string
  actionType?: string
}

const STATUS_LABELS: Record<string, string> = {
  pending: '待兑现',
  fulfilled: '已兑现',
  overdue: '已逾期',
  broken: '已违背',
}

const STATUS_COLORS: Record<string, string> = {
  pending: '#C4C0A0',
  fulfilled: '#A0C4A8',
  overdue: '#C4A7A0',
  broken: '#8c8c8c',
}

function formatDueDate(dueDate?: string): string {
  if (!dueDate) return ''
  const d = new Date(dueDate)
  const month = d.getMonth() + 1
  const day = d.getDate()
  return `${month}/${day}`
}

export default function PromiseLink({
  todoId,
  description,
  title,
  dueDate,
  fulfillmentStatus,
  actionType,
}: PromiseLinkProps) {
  const displayText = description || title || '未命名承诺'
  return (
    <View
      className='promise-link-card'
      onClick={(e) => {
        e.stopPropagation()
        navigateToPromiseDetail(todoId)
      }}
    >
      <View className='promise-link-icon'>
        <Text className='promise-link-icon-text'>🤝</Text>
      </View>
      <View className='promise-link-info'>
        <Text className='promise-link-text'>{displayText}</Text>
        <View className='promise-link-meta'>
          {actionType && (
            <Text className='promise-link-action'>
              {actionType === 'my_promise' ? '我的承诺' : '对方承诺'}
            </Text>
          )}
          {fulfillmentStatus && (
            <Text
              className='promise-link-status'
              style={{ color: STATUS_COLORS[fulfillmentStatus] || '#999' }}
            >
              {STATUS_LABELS[fulfillmentStatus] || fulfillmentStatus}
            </Text>
          )}
          {dueDate && <Text className='promise-link-due'>截止 {formatDueDate(dueDate)}</Text>}
        </View>
      </View>
      <Text className='promise-link-arrow'>›</Text>
    </View>
  )
}
