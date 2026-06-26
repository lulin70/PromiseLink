import { View, Text } from '@tarojs/components'
import { navigateToTodoDetail } from '../../services/navigation'
import './index.scss'

interface TodoLinkProps {
  todoId: string
  title: string
  dueDate?: string
  status?: string
  todoType?: string
}

const STATUS_LABELS: Record<string, string> = {
  pending: '待处理',
  done: '已完成',
  dismissed: '已忽略',
  in_progress: '进行中',
  snoozed: '已暂缓',
}

function formatDueDate(dueDate?: string): string {
  if (!dueDate) return ''
  const d = new Date(dueDate)
  const month = d.getMonth() + 1
  const day = d.getDate()
  return `${month}/${day}`
}

export default function TodoLink({ todoId, title, dueDate, status }: TodoLinkProps) {
  return (
    <View
      className='todo-link-card'
      onClick={(e) => {
        e.stopPropagation()
        navigateToTodoDetail(todoId)
      }}
    >
      <View className='todo-link-icon'>
        <Text className='todo-link-icon-text'>√</Text>
      </View>
      <View className='todo-link-info'>
        <Text className='todo-link-title'>{title}</Text>
        <View className='todo-link-meta'>
          {status && <Text className='todo-link-status'>{STATUS_LABELS[status] || status}</Text>}
          {dueDate && <Text className='todo-link-due'>截止 {formatDueDate(dueDate)}</Text>}
        </View>
      </View>
      <Text className='todo-link-arrow'>›</Text>
    </View>
  )
}
