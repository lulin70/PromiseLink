import { useEffect, useState } from 'react'
import { View, Text, ScrollView, Input } from '@tarojs/components'
import { getTodos, updateTodoStatus, dismissTodo, deleteTodo, login as apiLogin, TodoResponse } from '../../services/api'
import { isLoggedIn, setToken, setUserId, saveLoginCredentials } from '../../services/auth'
import { navigateToEntity, navigateToEvent, navigateToTodoDetail } from '../../services/navigation'
import Taro from '@tarojs/taro'
import './index.scss'

const STATUS_TABS = [
  { value: '', label: '全部' },
  { value: 'pending', label: '待处理' },
  { value: 'done', label: '已完成' },
  { value: 'dismissed', label: '已忽略' },
  { value: 'snoozed', label: '已推迟' },
]

const TYPE_TABS = [
  { value: '', label: '全部' },
  { value: 'care', label: '关注' },
  { value: 'followup', label: '跟进' },
  { value: 'cooperation_signal', label: '合作' },
  { value: 'risk', label: '风险' },
]

const TYPE_COLORS: Record<string, string> = {
  care: '#A0B0C4',
  followup: '#C4C0A0',
  cooperation_signal: '#B8C4C0',
  risk: '#C4A7A0',
  promise: '#A0C4A8',
}

const PRIORITY_MAP: Record<number, { label: string; color: string }> = {
  1: { label: '紧急', color: '#C4A7A0' },
  2: { label: '高', color: '#fa8c16' },
  3: { label: '中', color: '#7B9EA8' },
  4: { label: '低', color: '#999' },
  5: { label: '低', color: '#d9d9d9' },
}

export default function TodosPage() {
  const [todos, setTodos] = useState<TodoResponse[]>([])
  const [activeTab, setActiveTab] = useState(0)
  const [activeTypeTab, setActiveTypeTab] = useState(0)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  // Inline login state
  const [showLogin, setShowLogin] = useState(false)
  const [loginSecret, setLoginSecret] = useState('')
  const [loginLoading, setLoginLoading] = useState(false)
  const [loginError, setLoginError] = useState('')
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
  }, [activeTab, activeTypeTab, searchQuery])

  async function handleInlineLogin() {
    if (!loginSecret.trim()) { setLoginError('请输入PoC密钥'); return }
    try {
      setLoginLoading(true); setLoginError('')
      const res = await apiLogin(loginSecret.trim())
      setToken(res.access_token)
      setUserId(res.user_id || 'poc-user')
      saveLoginCredentials(loginSecret.trim())
      setShowLogin(false)
      loadTodos()
    } catch (err: unknown) {
      setLoginError('登录失败: ' + (err instanceof Error ? err.message : String(err)))
    } finally { setLoginLoading(false) }
  }

  if (showLogin) {
    return (
      <View className='page-login-inline'>
        <View className='login-card'>
          <Text className='login-title'>需要登录</Text>
          <View className='form-group'>
            <Text className='label'>PoC 密钥</Text>
            <Input className='input' type='safe-password' value={loginSecret} onInput={e => setLoginSecret(e.detail.value)} placeholder='请输入 PoC Secret' />
          </View>
          {loginError ? <Text className='error-text'>{loginError}</Text> : null}
          <View className={`login-btn ${loginLoading?'loading':''}`} onClick={loginLoading?undefined:handleInlineLogin}>
            <Text className='login-btn-text'>{loginLoading?'登录中...':'登 录'}</Text>
          </View>
        </View>
      </View>
    )
  }

  async function loadTodos() {
    try {
      setLoading(true)
      setError('')
      const status = STATUS_TABS[activeTab].value || undefined
      const todo_type = TYPE_TABS[activeTypeTab].value || undefined
      const res = await getTodos(status, 50, 0, 'urgency', searchQuery || undefined, todo_type)
      // "全部"标签下排除承诺类型（承诺有专门页面）
      const filtered = todo_type ? res.items : res.items.filter(t => t.todo_type !== 'promise')
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

      {/* Status Tabs */}
      <View className='tabs'>
        {STATUS_TABS.map((tab, idx) => (
          <View
            key={tab.value}
            className={`tab ${activeTab === idx ? 'active' : ''}`}
            onClick={() => setActiveTab(idx)}
          >
            <Text>{tab.label}</Text>
          </View>
        ))}
      </View>

      {/* Type Tabs */}
      <View className='tabs type-tabs'>
        {TYPE_TABS.map((tab, idx) => (
          <View
            key={tab.value}
            className={`tab type-tab ${activeTypeTab === idx ? 'active' : ''}`}
            onClick={() => setActiveTypeTab(idx)}
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
                    <Text className='type-badge-text'>{TYPE_TABS.find(t => t.value === todo.todo_type)?.label || todo.todo_type}</Text>
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
