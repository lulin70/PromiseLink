import { useEffect, useState, useRef } from 'react'
import { View, Text, ScrollView, Input } from '@tarojs/components'
import { getPromises, getPromiseStats, login as apiLogin, PromiseItem, PromiseStatsResponse, getPendingConfirmations, getNudgeDraft, updatePromiseStatus, confirmTodo } from '../../services/api'
import { isLoggedIn, setToken, setUserId, saveLoginCredentials } from '../../services/auth'
import { navigateToEntity, navigateToEvent } from '../../services/navigation'
import Taro from '@tarojs/taro'
import './index.scss'

const VIEW_TABS = [
  { value: 'my-promises', label: '我的承诺' },
  { value: 'their-promises', label: '对方的承诺' },
]

const STATUS_FILTERS = [
  { value: '', label: '全部' },
  { value: 'pending', label: '待兑现' },
  { value: 'fulfilled', label: '已兑现' },
  { value: 'overdue', label: '已逾期' },
  { value: 'broken', label: '已违背' },
]

const STATUS_COLORS: Record<string, string> = {
  pending: '#faad14',
  fulfilled: '#52c41a',
  overdue: '#ff4d4f',
  broken: '#8c8c8c',
}

const STATUS_LABELS: Record<string, string> = {
  pending: '待兑现',
  fulfilled: '已兑现',
  overdue: '已逾期',
  broken: '已违背',
}

export default function PromisesPage() {
  const [promises, setPromises] = useState<PromiseItem[]>([])
  const [stats, setStats] = useState<PromiseStatsResponse | null>(null)
  const [activeView, setActiveView] = useState(0)
  const [activeStatus, setActiveStatus] = useState(0)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  // Inline login
  const [showLogin, setShowLogin] = useState(false)
  const [loginSecret, setLoginSecret] = useState('')
  const [loginLoading, setLoginLoading] = useState(false)
  const [loginError, setLoginError] = useState('')
  // F-E2: Nudge draft popup state
  const [nudgeTodoId, setNudgeTodoId] = useState<string | null>(null)
  const [nudgeText, setNudgeText] = useState('')
  const [nudgeLoading, setNudgeLoading] = useState(false)
  const [nudgeCopied, setNudgeCopied] = useState(false)
  const [searchQuery, setSearchQuery] = useState('')
  const [pendingConfirmCount, setPendingConfirmCount] = useState(0)
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  useEffect(() => {
    if (!isLoggedIn()) { setShowLogin(true); setLoading(false); return }
    if (debounceRef.current) clearTimeout(debounceRef.current)
    debounceRef.current = setTimeout(() => {
      loadData()
    }, 300)
    return () => { if (debounceRef.current) clearTimeout(debounceRef.current) }
  }, [activeView, activeStatus, searchQuery])

  async function handleInlineLogin() {
    if (!loginSecret.trim()) { setLoginError('请输入PoC密钥'); return }
    try {
      setLoginLoading(true); setLoginError('')
      const res = await apiLogin(loginSecret.trim())
      setToken(res.access_token); setUserId(res.user_id || 'poc-user')
      saveLoginCredentials(loginSecret.trim()); setShowLogin(false); loadData()
    } catch (err: unknown) { setLoginError('登录失败: ' + (err instanceof Error ? err.message : String(err))) }
    finally { setLoginLoading(false) }
  }

  // F-E2: Generate nudge draft
  async function handleNudge(todoId: string) {
    try {
      setNudgeTodoId(todoId)
      setNudgeLoading(true)
      setNudgeCopied(false)
      const res = await getNudgeDraft(todoId)
      setNudgeText(res.nudge_text)
    } catch (err) {
      setNudgeText('生成失败，请稍后重试')
    } finally {
      setNudgeLoading(false)
    }
  }

  // F-E2: Copy nudge text to clipboard
  async function handleCopyNudge() {
    try {
      await Taro.setClipboardData({ data: nudgeText })
      setNudgeCopied(true)
      setTimeout(() => setNudgeCopied(false), 2000)
    } catch {
      // Clipboard API may not be available in all environments
    }
  }

  function closeNudge() {
    setNudgeTodoId(null)
    setNudgeText('')
  }

  if (showLogin) {
    return (
      <View className='page-login-inline'>
        <View className='login-card'>
          <Text className='login-title'>需要登录</Text>
          <View className='form-group'>
            <Text className='label'>PoC 密钥</Text>
            <Input className='input' type='password' value={loginSecret} onInput={e => setLoginSecret(e.detail.value)} placeholder='请输入 PoC Secret' />
          </View>
          {loginError ? <Text className='error-text'>{loginError}</Text> : null}
          <View className={`login-btn ${loginLoading?'loading':''}`} onClick={loginLoading?undefined:handleInlineLogin}>
            <Text className='login-btn-text'>{loginLoading?'登录中...':'登 录'}</Text>
          </View>
        </View>
      </View>
    )
  }

  async function loadData() {
    try {
      setLoading(true)
      setError('')
      const status = STATUS_FILTERS[activeStatus].value || undefined

      const view = VIEW_TABS[activeView].value
      const [promiseRes, statsRes, pendingItems] = await Promise.all([
        getPromises(view, status, 0, 20, searchQuery || undefined),
        getPromiseStats(),
        getPendingConfirmations(),
      ])
      // Show all promises including unconfirmed, but mark them
      setPromises(promiseRes.items)
      setStats(statsRes)
      setPendingConfirmCount(pendingItems.length)
    } catch (err) {
      const msg = err instanceof Error ? err.message : '加载失败'
      if (msg.includes('401')) { setShowLogin(true); setError('') }
      else { setError(msg) }
    } finally {
      setLoading(false)
    }
  }

  return (
    <View className='page-promises'>
      <View className='header'>
        <Text className='header-title'>承诺追踪</Text>
      </View>

      {/* Stats Summary */}
      {stats && (
        <View className='stats-bar'>
          <View className='stat-item'>
            <Text className='stat-number'>{stats.total}</Text>
            <Text className='stat-label'>总承诺</Text>
          </View>
          <View className='stat-item'>
            <Text className='stat-number accent'>{stats.my_promises.pending || 0}</Text>
            <Text className='stat-label'>我待兑现</Text>
          </View>
          <View className='stat-item'>
            <Text className='stat-number'>{stats.their_promises.pending || 0}</Text>
            <Text className='stat-label'>对方待兑现</Text>
          </View>
          <View className='stat-item'>
            <Text className='stat-number success'>{(stats.fulfillment_rate * 100).toFixed(0)}%</Text>
            <Text className='stat-label'>兑现率</Text>
          </View>
        </View>
      )}

      {/* Pending confirmation hint */}
      {pendingConfirmCount > 0 && (
        <View className='confirm-hint-bar' onClick={() => Taro.switchTab({ url: '/pages/events/index' })}>
          <Text className='confirm-hint-text'>{pendingConfirmCount}条承诺待确认，请在事件详情或下方确认或忽略</Text>
          <Text className='confirm-hint-arrow'>→</Text>
        </View>
      )}

      {/* View Tabs with count badges */}
      <View className='view-tabs'>
        {VIEW_TABS.map((tab, idx) => {
          const count = idx === 0
            ? (stats?.my_promises.pending || 0) + (stats?.my_promises.fulfilled || 0) + (stats?.my_promises.overdue || 0) + (stats?.my_promises.broken || 0)
            : (stats?.their_promises.pending || 0) + (stats?.their_promises.fulfilled || 0) + (stats?.their_promises.overdue || 0) + (stats?.their_promises.broken || 0)
          return (
            <View
              key={tab.value}
              className={`view-tab ${activeView === idx ? 'active' : ''} ${idx === 1 ? 'their-tab' : ''}`}
              onClick={() => setActiveView(idx)}
            >
              <Text>{tab.label}</Text>
              {count > 0 && (
                <View className='tab-badge'>
                  <Text className='tab-badge-text'>{count}</Text>
                </View>
              )}
            </View>
          )
        })}
      </View>

      {/* Status Filters */}
      <ScrollView scrollX className='status-filters'>
        {STATUS_FILTERS.map((filter, idx) => (
          <View
            key={filter.value}
            className={`status-filter ${activeStatus === idx ? 'active' : ''}`}
            onClick={() => setActiveStatus(idx)}
          >
            <Text>{filter.label}</Text>
          </View>
        ))}
      </ScrollView>

      {/* Search Bar */}
      <View className='search-bar'>
        <input
          className='search-input'
          type='text'
          placeholder='搜索承诺...'
          value={searchQuery}
          onInput={(e) => setSearchQuery(e.currentTarget.value)}
        />
      </View>

      {loading && <View className='loading'><Text>加载中...</Text></View>}
      {error && <View className='error'><Text>{error}</Text></View>}

      <ScrollView scrollY className='promise-list'>
        {promises.length === 0 && !loading && (
          <View className='empty'>
            <Text className='empty-icon'>{activeView === 0 ? '📋' : '🤝'}</Text>
            <Text className='empty-text'>
              {activeView === 0 ? '暂无我的承诺记录' : '暂无对方承诺记录'}
            </Text>
            <Text className='empty-hint'>
              {activeView === 0
                ? '录入互动时AI会自动识别你的承诺'
                : '当对方在交流中做出承诺时，AI会自动记录'}
            </Text>
          </View>
        )}
        {promises.map(promise => {
          const isUnconfirmed = promise.confirmation_status === 'pending' || promise.confirmation_status === 'auto_set'
          return (
          <View key={promise.todo_id} className={`promise-card ${isUnconfirmed ? 'unconfirmed' : ''}`}>
            {isUnconfirmed && (
              <View className='ai-confirm-banner'>
                <Text className='ai-confirm-text'>AI生成，待用户确认</Text>
                <View className='ai-confirm-btns'>
                  <Text className='ai-confirm-btn confirm-btn' onClick={(e) => {
                    e.stopPropagation()
                    confirmTodo(promise.todo_id, { confirmation_status: 'confirmed' }).then(() => loadData())
                  }}>确认</Text>
                  <Text className='ai-confirm-btn ignore-btn' onClick={(e) => {
                    e.stopPropagation()
                    confirmTodo(promise.todo_id, { confirmation_status: 'rejected' }).then(() => loadData())
                  }}>忽略</Text>
                </View>
              </View>
            )}
            <View className='promise-header'>
              <View
                className='status-badge'
                style={{ background: STATUS_COLORS[promise.fulfillment_status] || '#999' }}
              >
                <Text className='status-text'>
                  {STATUS_LABELS[promise.fulfillment_status] || promise.fulfillment_status}
                </Text>
              </View>
              <Text className='promise-action'>
                {promise.action_type === 'my_promise' ? '我的承诺' : '对方承诺'}
              </Text>
            </View>
            {promise.description && (
              <Text className='promise-desc'>{promise.description}</Text>
            )}
            {promise.entity_id && promise.entity_name && (
              <View className='promise-entity-row'>
                <Text className='promise-entity-label'>关联:</Text>
                <Text
                  className='entity-link'
                  onClick={(e) => {
                    e.stopPropagation()
                    navigateToEntity(promise.entity_id!, promise.entity_name)
                  }}
                >
                  {promise.entity_name}
                </Text>
              </View>
            )}
            {promise.source_event_id && (
              <Text
                className='source-event-link'
                onClick={(e) => { e.stopPropagation(); navigateToEvent(promise.source_event_id!) }}
              >
                来源: {promise.source_event_date ? `${promise.source_event_date} ` : ''}{promise.source_event_title || '查看事件'}
              </Text>
            )}
            <View className='promise-footer'>
              {promise.due_date && (
                <Text className='promise-due'>截止: {new Date(promise.due_date).toLocaleDateString('zh-CN')}</Text>
              )}
              {promise.created_at && (
                <Text className='promise-date'>
                  {new Date(promise.created_at).toLocaleDateString('zh-CN')}
                </Text>
              )}
              {/* Status action buttons */}
              {promise.fulfillment_status === 'pending' && (
                <View className='promise-action-btns'>
                  <Text className='action-btn fulfill-btn' onClick={(e) => {
                    e.stopPropagation()
                    updatePromiseStatus(promise.todo_id, 'fulfilled').then(() => loadData())
                  }}>已兑现</Text>
                  <Text className='action-btn broken-btn' onClick={(e) => {
                    e.stopPropagation()
                    updatePromiseStatus(promise.todo_id, 'broken').then(() => loadData())
                  }}>已违背</Text>
                </View>
              )}
              {promise.fulfillment_status === 'overdue' && (
                <View className='promise-action-btns'>
                  <Text className='action-btn fulfill-btn' onClick={(e) => {
                    e.stopPropagation()
                    updatePromiseStatus(promise.todo_id, 'fulfilled').then(() => loadData())
                  }}>已兑现</Text>
                  <Text className='action-btn broken-btn' onClick={(e) => {
                    e.stopPropagation()
                    updatePromiseStatus(promise.todo_id, 'broken').then(() => loadData())
                  }}>已违背</Text>
                </View>
              )}
              {(promise.fulfillment_status === 'fulfilled' || promise.fulfillment_status === 'broken') && (
                <View className='promise-action-btns'>
                  <Text className='action-btn revert-btn' onClick={(e) => {
                    e.stopPropagation()
                    updatePromiseStatus(promise.todo_id, 'pending').then(() => loadData())
                  }}>待兑现</Text>
                </View>
              )}
              {/* F-E2: Nudge button for their_promise */}
              {promise.action_type === 'their_promise' && (promise.fulfillment_status === 'pending' || promise.fulfillment_status === 'overdue') && (
                <Text className='action-btn nudge-action-btn' onClick={(e) => {
                  e.stopPropagation()
                  handleNudge(promise.todo_id)
                }}>
                  {nudgeLoading && nudgeTodoId === promise.todo_id ? '生成中...' : '催促'}
                </Text>
              )}
            </View>
          </View>
        )})}
      </ScrollView>

      {/* F-E2: Nudge Draft Popup */}
      {nudgeTodoId && (
        <View className='nudge-popup' onClick={closeNudge}>
          <View className='nudge-popup-content' onClick={e => e.stopPropagation()}>
            <View className='nudge-popup-header'>
              <Text className='nudge-popup-title'>催促消息草稿</Text>
              <Text className='nudge-popup-close' onClick={closeNudge}>✕</Text>
            </View>
            {nudgeLoading ? (
              <View className='nudge-loading'><Text>AI正在生成话术，请稍候...</Text></View>
            ) : (
              <>
                <View className='nudge-text-area'>
                  <Text className='nudge-text'>{nudgeText}</Text>
                </View>
                <Text className='nudge-disclaimer'>此消息仅供参考，发送前请自行调整</Text>
                <View className='nudge-popup-actions'>
                  <View
                    className={`nudge-copy-btn ${nudgeCopied ? 'copied' : ''}`}
                    onClick={handleCopyNudge}
                  >
                    <Text>{nudgeCopied ? '已复制' : '复制消息'}</Text>
                  </View>
                  <View className='nudge-close-btn' onClick={closeNudge}>
                    <Text>关闭</Text>
                  </View>
                </View>
              </>
            )}
          </View>
        </View>
      )}
    </View>
  )
}
