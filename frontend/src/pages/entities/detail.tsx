import { useEffect, useState } from 'react'
import { View, Text, ScrollView } from '@tarojs/components'
import Taro, { useRouter } from '@tarojs/taro'
import {
  getEntityDetail,
  getEntityHistory,
  EntityDetailResponse,
  EntityHistoryResponse,
} from '../../services/api'
import { isLoggedIn } from '../../services/auth'
import { navigateBack } from '../../services/navigation'
import EventLink from '../../components/EventLink'
import TodoLink from '../../components/TodoLink'
import PromiseLink from '../../components/PromiseLink'
import './detail.scss'

const ENTITY_TYPE_MAP: Record<string, string> = {
  person: '人物',
  organization: '组织',
  location: '地点',
  other: '其他',
}

const INTERNAL_KEYS = new Set([
  'source_event_id', 'event_ids', 'sensitivity', 'raw_confidence',
  'extraction_method', 'merge_source', 'merge_history', 'event_keywords', 'event_topics',
])

const FIELD_LABEL_MAP: Record<string, string> = {
  company: '公司',
  title: '职位',
  phone: '电话',
  email: '邮箱',
  school: '学校',
  concern: '关注点',
  contribution: '贡献',
  capability: '能力',
  city: '城市',
  industry: '行业',
  wechat: '微信',
  address: '地址',
  birthday: '生日',
  notes: '备注',
  department: '部门',
  role: '角色',
}

function filterInternalFields(properties: Record<string, unknown>): Record<string, unknown> {
  const filtered: Record<string, unknown> = {}
  for (const [key, val] of Object.entries(properties)) {
    if (INTERNAL_KEYS.has(key)) continue
    filtered[key] = val
  }
  return filtered
}

function formatFieldValue(val: unknown): string {
  if (typeof val === 'object' && val !== null) {
    return JSON.stringify(val, null, 0).replace(/[{}"]/g, '').replace(/:/g, ': ').replace(/,/g, ', ')
  }
  return String(val)
}

export default function EntityDetailPage() {
  const router = useRouter()
  const [detail, setDetail] = useState<EntityDetailResponse | null>(null)
  const [history, setHistory] = useState<EntityHistoryResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  useEffect(() => {
    if (!isLoggedIn()) {
      Taro.redirectTo({ url: '/pages/index/index' })
      return
    }
    const entityId = router.params.id
    if (!entityId) {
      setError('缺少人脉ID')
      setLoading(false)
      return
    }
    loadDetail(entityId)
  }, [])

  async function loadDetail(entityId: string) {
    try {
      setLoading(true)
      setError('')
      const [detailData, historyData] = await Promise.all([
        getEntityDetail(entityId),
        getEntityHistory(entityId).catch(() => null),
      ])
      setDetail(detailData)
      setHistory(historyData)
    } catch (err) {
      const msg = err instanceof Error ? err.message : '加载失败'
      setError(msg)
    } finally {
      setLoading(false)
    }
  }

  // Separate todos into promises and regular todos
  const promises = history?.todos.filter(t => t.todo_type === 'promise') || []
  const regularTodos = history?.todos.filter(t => t.todo_type !== 'promise') || []

  return (
    <View className='page-entity-detail'>
      <View className='detail-header'>
        <View className='back-btn' onClick={navigateBack}>
          <Text>‹ 返回</Text>
        </View>
        <Text className='header-title'>人脉详情</Text>
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
            <Text className='info-title'>{detail.name}</Text>
            <View className='info-meta'>
              <View className='meta-tag'>
                <Text>{ENTITY_TYPE_MAP[detail.entity_type] || detail.entity_type}</Text>
              </View>
              <Text className='meta-date'>
                置信度 {(detail.confidence * 100).toFixed(0)}%
              </Text>
            </View>
            {detail.canonical_name !== detail.name && (
              <View className='info-row'>
                <Text className='info-label'>标准名</Text>
                <Text className='info-value'>{detail.canonical_name}</Text>
              </View>
            )}
            {detail.aliases && detail.aliases.length > 0 && (
              <View className='info-row'>
                <Text className='info-label'>别名</Text>
                <Text className='info-value'>{detail.aliases.join(', ')}</Text>
              </View>
            )}
            {detail.properties &&
              Object.entries(filterInternalFields(detail.properties)).map(([key, val]) => (
                <View className='info-row' key={key}>
                  <Text className='info-label'>{FIELD_LABEL_MAP[key] || key}</Text>
                  <Text className='info-value'>{formatFieldValue(val)}</Text>
                </View>
              ))}
          </View>

          {/* Related events */}
          {history && history.events.length > 0 && (
            <View className='section-card'>
              <Text className='section-title'>相关事件 ({history.events.length})</Text>
              {history.events.slice(0, 10).map(evt => (
                <EventLink
                  key={evt.id}
                  eventId={String(evt.id)}
                  title={evt.title}
                  timestamp={evt.timestamp}
                  eventType={evt.event_type}
                />
              ))}
            </View>
          )}

          {/* Related todos */}
          {regularTodos.length > 0 && (
            <View className='section-card'>
              <Text className='section-title'>关联待办 ({regularTodos.length})</Text>
              {regularTodos.slice(0, 10).map(todo => (
                <TodoLink
                  key={todo.id}
                  todoId={String(todo.id)}
                  title={todo.title}
                  status={todo.status}
                  todoType={todo.todo_type}
                />
              ))}
            </View>
          )}

          {/* Related promises */}
          {promises.length > 0 && (
            <View className='section-card'>
              <Text className='section-title'>关联承诺 ({promises.length})</Text>
              {promises.slice(0, 10).map(todo => (
                <PromiseLink
                  key={todo.id}
                  todoId={String(todo.id)}
                  title={todo.title}
                />
              ))}
            </View>
          )}

          {/* Related associations */}
          {history && history.associations.length > 0 && (
            <View className='section-card'>
              <Text className='section-title'>关联人脉 ({history.associations.length})</Text>
              {history.associations.slice(0, 10).map(assoc => (
                <View key={assoc.id} className='assoc-item'>
                  <Text className='assoc-name'>{assoc.target_entity_name}</Text>
                  <Text className='assoc-type'>{assoc.association_type}</Text>
                </View>
              ))}
            </View>
          )}

          {/* Empty state */}
          {history &&
            history.events.length === 0 &&
            history.todos.length === 0 &&
            history.associations.length === 0 && (
            <View className='empty-associations'>
              <Text>暂无关联数据</Text>
            </View>
          )}
        </ScrollView>
      )}
    </View>
  )
}
