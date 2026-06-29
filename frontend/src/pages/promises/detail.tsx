import { useEffect, useState } from 'react'
import { View, Text, ScrollView } from '@tarojs/components'
import Taro, { useRouter } from '@tarojs/taro'
import { getPromiseDetail, updatePromiseStatus, TodoDetailResponse } from '../../services/api'
import { isLoggedIn } from '../../services/auth'
import { navigateBack } from '../../services/navigation'
import EventLink from '../../components/EventLink'
import EntityLink from '../../components/EntityLink'
import './detail.scss'

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

export default function PromiseDetailPage() {
  const router = useRouter()
  const [detail, setDetail] = useState<TodoDetailResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [actionLoading, setActionLoading] = useState(false)

  useEffect(() => {
    if (!isLoggedIn()) {
      Taro.reLaunch({ url: '/pages/index/index' })
      return
    }
    const todoId = router.params.id
    if (!todoId) {
      setError('缺少承诺ID')
      setLoading(false)
      return
    }
    loadDetail(todoId)
  }, [])

  async function loadDetail(todoId: string) {
    try {
      setLoading(true)
      setError('')
      const data = await getPromiseDetail(todoId)
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
      await updatePromiseStatus(detail.id, newStatus)
      Taro.showToast({ title: '操作成功', icon: 'success' })
      await loadDetail(detail.id)
    } catch (err) {
      Taro.showToast({ title: '操作失败', icon: 'error' })
    } finally {
      setActionLoading(false)
    }
  }

  const fulfillmentStatus = detail?.fulfillment_status || 'pending'
  const isUnconfirmed = detail?.confirmation_status === 'pending' || detail?.confirmation_status === 'auto_set'

  return (
    <View className='page-promise-detail'>
      <View className='detail-header'>
        <View className='back-btn' onClick={navigateBack}>
          <Text>‹ 返回</Text>
        </View>
        <Text className='header-title'>承诺详情</Text>
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
            <Text className='info-title'>{detail.title || detail.description || '未命名承诺'}</Text>
            <View className='info-meta'>
              {detail.action_type && (
                <View className='meta-tag'>
                  <Text>{detail.action_type === 'my_promise' ? '我的承诺' : '对方承诺'}</Text>
                </View>
              )}
              <View
                className='status-badge'
                style={{ background: STATUS_COLORS[fulfillmentStatus] + '20', color: STATUS_COLORS[fulfillmentStatus] }}
              >
                <Text>{STATUS_LABELS[fulfillmentStatus] || fulfillmentStatus}</Text>
              </View>
              {isUnconfirmed && (
                <View className='meta-tag' style={{ background: '#f0ece6', color: '#C4C0A0' }}>
                  <Text>待确认</Text>
                </View>
              )}
            </View>
            {detail.description && detail.title && (
              <View className='raw-text-section'>
                <Text className='section-label'>承诺内容</Text>
                <Text className='raw-text'>{detail.description}</Text>
              </View>
            )}
            {detail.evidence_quote && (
              <View className='raw-text-section'>
                <Text className='section-label'>证据原文</Text>
                <Text className='raw-text'>"{detail.evidence_quote}"</Text>
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
          {(fulfillmentStatus === 'pending' || fulfillmentStatus === 'overdue') && (
            <View className='action-bar'>
              <View
                className={`action-btn danger ${actionLoading ? 'disabled' : ''}`}
                onClick={() => !actionLoading && handleStatusChange('broken')}
              >
                <Text>已违背</Text>
              </View>
              <View
                className={`action-btn primary ${actionLoading ? 'disabled' : ''}`}
                onClick={() => !actionLoading && handleStatusChange('fulfilled')}
              >
                <Text>√ 已兑现</Text>
              </View>
            </View>
          )}

          {(fulfillmentStatus === 'fulfilled' || fulfillmentStatus === 'broken') && (
            <View className='action-bar'>
              <View
                className={`action-btn secondary ${actionLoading ? 'disabled' : ''}`}
                onClick={() => !actionLoading && handleStatusChange('pending')}
              >
                <Text>恢复待兑现</Text>
              </View>
            </View>
          )}
        </ScrollView>
      )}
    </View>
  )
}
