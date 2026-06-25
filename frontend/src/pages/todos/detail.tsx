import { useEffect, useState } from 'react'
import { View, Text, ScrollView } from '@tarojs/components'
import Taro, { useRouter } from '@tarojs/taro'
import { getTodoDetail, updateTodoStatus, dismissTodo, TodoDetailResponse } from '../../services/api'
import { isLoggedIn } from '../../services/auth'
import { navigateBack } from '../../services/navigation'
import EventLink from '../../components/EventLink'
import EntityLink from '../../components/EntityLink'
import './detail.scss'

const STATUS_TABS = [
  { value: 'pending', label: '待处理' },
  { value: 'done', label: '已完成' },
  { value: 'dismissed', label: '已忽略' },
]

const TYPE_LABELS: Record<string, string> = {
  care: '关注',
  followup: '跟进',
  cooperation_signal: '合作',
  risk: '风险',
  help: '求助',
  promise: '承诺',
}

const PRIORITY_MAP: Record<number, { label: string; color: string }> = {
  1: { label: '紧急', color: '#C4A7A0' },
  2: { label: '高', color: '#fa8c16' },
  3: { label: '中', color: '#7B9EA8' },
  4: { label: '低', color: '#999' },
  5: { label: '低', color: '#d9d9d9' },
}

export default function TodoDetailPage() {
  const router = useRouter()
  const [detail, setDetail] = useState<TodoDetailResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [actionLoading, setActionLoading] = useState(false)

  useEffect(() => {
    if (!isLoggedIn()) {
      Taro.redirectTo({ url: '/pages/index/index' })
      return
    }
    const todoId = router.params.id
    if (!todoId) {
      setError('缺少待办ID')
      setLoading(false)
      return
    }
    loadDetail(todoId)
  }, [])

  async function loadDetail(todoId: string) {
    try {
      setLoading(true)
      setError('')
      const data = await getTodoDetail(todoId)
      setDetail(data)
    } catch (err) {
      const msg = err instanceof Error ? err.message : '加载失败'
      setError(msg)
    } finally {
      setLoading(false)
    }
  }

  async function handleStatusChange(newStatus: string) {
    if (!detail) return
    try {
      setActionLoading(true)
      if (newStatus === 'dismissed') {
        await dismissTodo(detail.id)
      } else {
        await updateTodoStatus(detail.id, newStatus)
      }
      Taro.showToast({ title: '操作成功', icon: 'success' })
      await loadDetail(detail.id)
    } catch (err) {
      Taro.showToast({ title: '操作失败', icon: 'error' })
    } finally {
      setActionLoading(false)
    }
  }

  const pri = detail ? PRIORITY_MAP[detail.priority] || { label: '未知', color: '#999' } : null

  return (
    <View className='page-todo-detail'>
      <View className='detail-header'>
        <View className='back-btn' onClick={navigateBack}>
          <Text>‹ 返回</Text>
        </View>
        <Text className='header-title'>待办详情</Text>
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
            <Text className='info-title'>{detail.title}</Text>
            <View className='info-meta'>
              {detail.todo_type && (
                <View className='meta-tag'>
                  <Text>{TYPE_LABELS[detail.todo_type] || detail.todo_type}</Text>
                </View>
              )}
              {pri && (
                <View className='priority-badge' style={{ background: pri.color }}>
                  <Text>{pri.label}</Text>
                </View>
              )}
              <View className={`status-badge status-${detail.status}`}>
                <Text>{STATUS_TABS.find(s => s.value === detail.status)?.label || detail.status}</Text>
              </View>
            </View>
            {detail.description && (
              <View className='raw-text-section'>
                <Text className='section-label'>描述</Text>
                <Text className='raw-text'>{detail.description}</Text>
              </View>
            )}
            {detail.due_date && (
              <View className='info-row'>
                <Text className='info-label'>截止日期</Text>
                <Text className='info-value'>
                  {new Date(detail.due_date).toLocaleDateString('zh-CN')}
                </Text>
              </View>
            )}
            {detail.created_at && (
              <View className='info-row'>
                <Text className='info-label'>创建时间</Text>
                <Text className='info-value'>
                  {new Date(detail.created_at).toLocaleString('zh-CN')}
                </Text>
              </View>
            )}
          </View>

          {/* Source event */}
          {detail.source_event_id && (
            <View className='section-card source-section'>
              <Text className='section-title'>来源事件</Text>
              <EventLink
                eventId={detail.source_event_id}
                title={detail.source_event_title || '查看事件'}
                timestamp={detail.source_event_date}
              />
            </View>
          )}

          {/* Related entity */}
          {detail.related_entity_id && (
            <View className='section-card source-section'>
              <Text className='section-title'>关联人脉</Text>
              <EntityLink
                entityId={detail.related_entity_id}
                name={detail.related_entity_name || '查看人脉'}
              />
            </View>
          )}

          {/* Action buttons */}
          {detail.status === 'pending' && (
            <View className='action-bar'>
              <View
                className={`action-btn secondary ${actionLoading ? 'disabled' : ''}`}
                onClick={() => !actionLoading && handleStatusChange('dismissed')}
              >
                <Text>忽略</Text>
              </View>
              <View
                className={`action-btn primary ${actionLoading ? 'disabled' : ''}`}
                onClick={() => !actionLoading && handleStatusChange('done')}
              >
                <Text>√ 完成</Text>
              </View>
            </View>
          )}

          {(detail.status === 'done' || detail.status === 'dismissed') && (
            <View className='action-bar'>
              <View
                className={`action-btn primary ${actionLoading ? 'disabled' : ''}`}
                onClick={() => !actionLoading && handleStatusChange('pending')}
              >
                <Text>恢复待处理</Text>
              </View>
            </View>
          )}
        </ScrollView>
      )}
    </View>
  )
}
