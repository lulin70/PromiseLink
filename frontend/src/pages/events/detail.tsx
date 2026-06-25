import { useEffect, useState } from 'react'
import { View, Text, ScrollView } from '@tarojs/components'
import Taro, { useRouter } from '@tarojs/taro'
import { getEventDetail, EventDetailResponse, EventTodoRef } from '../../services/api'
import { isLoggedIn } from '../../services/auth'
import { navigateBack } from '../../services/navigation'
import EntityLink from '../../components/EntityLink'
import TodoLink from '../../components/TodoLink'
import PromiseLink from '../../components/PromiseLink'
import './detail.scss'

const EVENT_TYPE_LABELS: Record<string, string> = {
  manual: '手动',
  meeting: '会议',
  call: '电话',
  wechat_forward: '微信',
  email: '邮件',
  card_save: '名片',
}

export default function EventDetailPage() {
  const router = useRouter()
  const [detail, setDetail] = useState<EventDetailResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  useEffect(() => {
    if (!isLoggedIn()) {
      Taro.redirectTo({ url: '/pages/index/index' })
      return
    }
    const eventId = router.params.id
    if (!eventId) {
      setError('缺少事件ID')
      setLoading(false)
      return
    }
    loadDetail(eventId)
  }, [])

  async function loadDetail(eventId: string) {
    try {
      setLoading(true)
      setError('')
      const data = await getEventDetail(eventId)
      setDetail(data)
    } catch (err) {
      const msg = err instanceof Error ? err.message : '加载失败'
      setError(msg)
    } finally {
      setLoading(false)
    }
  }

  // Separate todos into promises and regular todos
  const promises: EventTodoRef[] = []
  const regularTodos: EventTodoRef[] = []
  if (detail?.related_todos) {
    for (const todo of detail.related_todos) {
      if (todo.action_type === 'my_promise' || todo.action_type === 'their_promise') {
        promises.push(todo)
      } else {
        regularTodos.push(todo)
      }
    }
  }

  return (
    <View className='page-event-detail'>
      <View className='detail-header'>
        <View className='back-btn' onClick={navigateBack}>
          <Text>‹ 返回</Text>
        </View>
        <Text className='header-title'>事件详情</Text>
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

      {detail && (
        <ScrollView scrollY className='detail-body'>
          {/* Basic info */}
          <View className='info-card'>
            <Text className='info-title'>{detail.title || '未命名事件'}</Text>
            <View className='info-meta'>
              <View className='meta-tag'>
                <Text>{EVENT_TYPE_LABELS[detail.event_type] || detail.event_type}</Text>
              </View>
              <Text className='meta-date'>
                {new Date(detail.timestamp).toLocaleString('zh-CN')}
              </Text>
            </View>
            {detail.raw_text && (
              <View className='raw-text-section'>
                <Text className='section-label'>原始内容</Text>
                <Text className='raw-text'>{detail.raw_text}</Text>
              </View>
            )}
            <View className='info-row'>
              <Text className='info-label'>状态</Text>
              <Text className='info-value'>
                {detail.status === 'completed' || detail.status === 'degraded_completed'
                  ? '已解析'
                  : detail.status === 'failed' || detail.status === 'awaiting_retry'
                  ? '解析失败'
                  : '解析中'}
              </Text>
            </View>
          </View>

          {/* Related entities */}
          {detail.related_entities && detail.related_entities.length > 0 && (
            <View className='section-card'>
              <Text className='section-title'>关联人脉 ({detail.related_entities.length})</Text>
              {detail.related_entities.map(ent => (
                <EntityLink
                  key={ent.id}
                  entityId={ent.id}
                  name={ent.name}
                />
              ))}
            </View>
          )}

          {/* Related todos */}
          {regularTodos.length > 0 && (
            <View className='section-card'>
              <Text className='section-title'>关联待办 ({regularTodos.length})</Text>
              {regularTodos.map(todo => (
                <TodoLink
                  key={todo.id}
                  todoId={todo.id}
                  title={todo.title}
                  status={todo.status}
                />
              ))}
            </View>
          )}

          {/* Related promises */}
          {promises.length > 0 && (
            <View className='section-card'>
              <Text className='section-title'>关联承诺 ({promises.length})</Text>
              {promises.map(todo => (
                <PromiseLink
                  key={todo.id}
                  todoId={todo.id}
                  title={todo.title}
                  actionType={todo.action_type || undefined}
                />
              ))}
            </View>
          )}

          {/* Empty state for associations */}
          {(!detail.related_entities || detail.related_entities.length === 0) &&
            (!detail.related_todos || detail.related_todos.length === 0) && (
            <View className='empty-associations'>
              <Text>暂无关联数据</Text>
            </View>
          )}
        </ScrollView>
      )}
    </View>
  )
}
