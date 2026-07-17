import { useEffect, useState } from 'react'
import { View, Text, ScrollView } from '@tarojs/components'
import { getTodos, updateTodoStatus, dismissTodo, deleteTodo, TodoResponse } from '../../services/api'
import { isLoggedIn } from '../../services/auth'
import { navigateToEntity, navigateToEvent, navigateToTodoDetail } from '../../services/navigation'
import Taro from '@tarojs/taro'
import LoginGate from '../../components/LoginGate'
import './index.scss'

// action_type 维度 Tab（2.2 改进：用 followup_needed 替代提案的 my_followup）
// 架构师审议：现有 action_type 枚举为 my_promise/their_promise/help_provided/care_expression/cooperation_signal/followup_needed
const ACTION_TYPE_TABS = [
  { value: '', label: '全部' },
  { value: 'my_promise', label: '我的承诺' },
  { value: 'their_promise', label: '等待回应' },
  { value: 'followup_needed', label: '跟进事项' },
  { value: 'done', label: '已完成' },
]

const TYPE_COLORS: Record<string, string> = {
  care: '#A0B0C4',
  followup: '#C4C0A0',
  cooperation_signal: '#B8C4C0',
  risk: '#C4A7A0',
  promise: '#A0C4A8',
}

const TYPE_LABELS: Record<string, string> = {
  care: '关注',
  followup: '跟进',
  cooperation_signal: '合作',
  risk: '风险',
  promise: '承诺',
  help: '帮助',
}

const PRIORITY_MAP: Record<number, { label: string; color: string }> = {
  1: { label: '紧急', color: '#C4A7A0' },
  2: { label: '高', color: '#C4B0A0' },
  3: { label: '中', color: '#A0B0C4' },
  4: { label: '低', color: '#999' },
  5: { label: '低', color: '#d9d9d9' },
}

export default function TodosPage() {
  const [todos, setTodos] = useState<TodoResponse[]>([])
  const [activeTab, setActiveTab] = useState(0)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  // Inline login state
  const [showLogin, setShowLogin] = useState(false)
  const [searchQuery, setSearchQuery] = useState('')

  useEffect(() => {
    if (!isLoggedIn()) {
      setShowLogin(true)
      setLoading(false)
      return
    }
    const timer = setTimeout(() => {
      loadTodos()
    }, 300)
    return () => clearTimeout(timer)
  }, [activeTab, searchQuery])

  if (showLogin) {
    return (
      <LoginGate
        title='需要登录'
        onLoginSuccess={() => {
          setShowLogin(false)
          loadTodos()
        }}
      />
    )
  }

  async function loadTodos() {
    try {
      setLoading(true)
      setError('')
      const tabValue = ACTION_TYPE_TABS[activeTab].value
      // "已完成" Tab 用 status='done' 过滤；其余 Tab 取全部非完成态后前端按 action_type 过滤
      const status = tabValue === 'done' ? 'done' : undefined
      const res = await getTodos(status, 50, 0, 'urgency', searchQuery || undefined, undefined)
      let filtered = res.items
      if (tabValue && tabValue !== 'done') {
        // action_type 前端过滤（API 暂不支持 action_type 参数）
        filtered = res.items.filter(t => t.action_type === tabValue)
      }
      // 按动态优先级分数排序（高分在前）
      filtered = [...filtered].sort((a, b) => (b.dynamic_score ?? 0) - (a.dynamic_score ?? 0))
      setTodos(filtered)
    } catch (err) {
      const msg = err instanceof Error ? err.message : '加载失败'
      // 401: token无效，显示登录表单让用户重新登录
      if (msg.includes('401')) {
        setShowLogin(true)
        setError('')
      } else {
        setError(msg)
      }
    } finally {
      setLoading(false)
    }
  }

  async function handleMarkDone(todoId: string) {
    try {
      await updateTodoStatus(todoId, 'done')
      loadTodos()
    } catch (err) {
      Taro.showToast({ title: '操作失败', icon: 'error' })
    }
  }

  async function handleDismiss(todoId: string) {
    try {
      await dismissTodo(todoId)
      setTodos(prev => prev.filter(t => t.id !== todoId))
    } catch (err) {
      Taro.showToast({ title: '操作失败', icon: 'error' })
    }
  }

  async function handleDeleteTodo(todoId: string) {
    try {
      const res = await Taro.showModal({
        title: '确认删除',
        content: '确认删除此待办？',
        confirmText: '删除',
        cancelText: '取消',
        confirmColor: '#C4A7A0',
      })
      if (!res.confirm) return
      await deleteTodo(todoId)
      Taro.showToast({ title: '已删除', icon: 'success' })
      setTodos(prev => prev.filter(t => t.id !== todoId))
    } catch (err) {
      Taro.showToast({ title: '删除失败', icon: 'error' })
    }
  }

  function getPriorityInfo(priority: number) {
    return PRIORITY_MAP[priority] || { label: '未知', color: '#999' }
  }

  return (
    <View className='page-todos'>
      <View className='header'>
        <Text className='header-title'>待办事项</Text>
      </View>

      {/* action_type Tabs（2.2 改进：单行 5 维度） */}
      <View className='tabs'>
        {ACTION_TYPE_TABS.map((tab, idx) => (
          <View
            key={tab.value}
            className={`tab ${activeTab === idx ? 'active' : ''}`}
            onClick={() => setActiveTab(idx)}
          >
            <Text>{tab.label}</Text>
          </View>
        ))}
      </View>

      {/* Search Bar */}
      <View className='search-bar'>
        <input
          className='search-input'
          type='text'
          placeholder='搜索待办...'
          value={searchQuery}
          onInput={(e) => setSearchQuery(e.currentTarget.value)}
        />
      </View>

      {loading && <View className='loading'><Text>加载中...</Text></View>}
      {error && <View className='error'><Text>{error}</Text></View>}

      <ScrollView scrollY className='todo-list'>
        {todos.length === 0 && !loading && (
          <View className='empty'><Text>暂无待办</Text></View>
        )}
        {todos.map(todo => {
          const pri = getPriorityInfo(todo.priority)
          return (
            <View key={todo.id} className='todo-card'>
              <View className='todo-main'>
                <View className='todo-header'>
                  <View className='priority-badge' style={{ background: pri.color }}>
                    <Text className='priority-text'>{pri.label}</Text>
                  </View>
                  <View className='type-badge' style={{ background: TYPE_COLORS[todo.todo_type] || '#ccc' }}>
                    <Text className='type-badge-text'>{TYPE_LABELS[todo.todo_type] || todo.todo_type}</Text>
                  </View>
                </View>
                <Text
                  className='todo-title'
                  onClick={(e) => {
                    e.stopPropagation()
                    navigateToTodoDetail(todo.id)
                  }}
                >
                  {todo.title}
                </Text>
                {todo.description && (
                  <Text className='todo-desc'>{todo.description}</Text>
                )}
                {todo.related_entity_id && todo.related_entity_name && (
                  <View className='todo-entity-row'>
                    <Text className='todo-entity-label'>关联:</Text>
                    <Text
                      className='entity-link'
                      onClick={(e) => {
                        e.stopPropagation()
                        navigateToEntity(todo.related_entity_id!, todo.related_entity_name)
                      }}
                    >
                      {todo.related_entity_name}
                    </Text>
                  </View>
                )}
                {todo.source_event_id && (
                  <Text
                    className='source-event-link'
                    onClick={(e) => { e.stopPropagation(); navigateToEvent(todo.source_event_id!) }}
                  >
                    来源: {todo.source_event_date ? `${todo.source_event_date} ` : ''}{todo.source_event_title || '查看事件'}
                  </Text>
                )}
                {todo.due_date && (
                  <Text className='todo-due'>截止: {todo.due_date}</Text>
                )}
              </View>
              <View className='todo-actions'>
                {todo.status !== 'done' && todo.status !== 'dismissed' && (
                  <>
                    <View
                      className='delete-btn'
                      onClick={() => handleDeleteTodo(todo.id)}
                    >
                      <Text>删除</Text>
                    </View>
                    <View
                      className='dismiss-btn'
                      onClick={() => handleDismiss(todo.id)}
                    >
                      <Text>忽略</Text>
                    </View>
                    <View
                      className='done-btn'
                      onClick={() => handleMarkDone(todo.id)}
                    >
                      <Text>√ 完成</Text>
                    </View>
                  </>
                )}
                {todo.status === 'done' && (
                  <Text className='done-label'>已完成</Text>
                )}
                {todo.status === 'dismissed' && (
                  <Text className='dismissed-label'>已忽略</Text>
                )}
                {todo.status === 'snoozed' && (
                  <Text className='snoozed-label'>已推迟</Text>
                )}
              </View>
            </View>
          )
        })}
      </ScrollView>
    </View>
  )
}
