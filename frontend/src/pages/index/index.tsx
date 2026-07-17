import { useEffect, useState } from 'react'
import { View, Text, ScrollView, Button } from '@tarojs/components'
import Taro from '@tarojs/taro'
import { getDashboard, DayViewResponse, SupplyDemandMatch, getSupplyDemand, RelationshipHealthResponse, getRelationshipHealth, CareRemindersResponse, getCareReminders, exportData, getDailyReminders, DailyReminderResponse } from '../../services/api'
import { isLoggedIn, getUserId } from '../../services/auth'
import { navigateToEvent } from '../../services/navigation'
import LoginGate from '../../components/LoginGate'
import './index.scss'

export default function Index() {
  const [dashboard, setDashboard] = useState<DayViewResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  // Login inline state
  const [showLogin, setShowLogin] = useState(false)
  // F-E4: Supply-demand matching
  const [sdMatches, setSdMatches] = useState<SupplyDemandMatch[]>([])
  // F-G1: Relationship Health Diagnostic
  const [healthData, setHealthData] = useState<RelationshipHealthResponse | null>(null)
  // F-G3: Care Reminders
  const [careData, setCareData] = useState<CareRemindersResponse | null>(null)
  const [showAllCare, setShowAllCare] = useState(false)
  // F-69: Daily Reminders summary bar (1.3 提醒页入口)
  const [reminderData, setReminderData] = useState<DailyReminderResponse | null>(null)

  useEffect(() => {
    if (!isLoggedIn()) {
      setShowLogin(true)
      setLoading(false)
      return
    }
    loadDashboard()
  }, [])

  async function loadDashboard() {
    try {
      setLoading(true)
      setError('')
      const data = await getDashboard()
      setDashboard(data)
      // F-E4: Also load supply-demand matches (non-blocking)
      getSupplyDemand(5).then(res => setSdMatches(res.matches)).catch(() => {})
      // F-G1: Load relationship health (non-blocking)
      getRelationshipHealth(20).then(setHealthData).catch(() => {})
      // F-G3: Load care reminders (non-blocking)
      getCareReminders(10).then(setCareData).catch(() => {})
      // F-69: Load daily reminders summary (non-blocking, for 1.3 提醒页入口)
      getDailyReminders().then(setReminderData).catch(() => {})
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err)
      console.error('[Dashboard] Load failed:', msg)
      // If 401, show login form
      if (msg.includes('401') || msg.includes('credentials')) {
        setShowLogin(true)
        setError('')
      } else {
        setError(msg)
      }
    } finally {
      setLoading(false)
    }
  }

  async function handleExportData() {
    try {
      const userId = getUserId()
      if (!userId) {
        Taro.showToast({ title: '请先登录', icon: 'error' })
        return
      }
      Taro.showLoading({ title: '导出中...' })
      const data = await exportData(userId)
      Taro.hideLoading()
      // Create downloadable JSON
      const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' })
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = `promiselink-export-${new Date().toISOString().slice(0, 10)}.json`
      a.click()
      URL.revokeObjectURL(url)
      Taro.showToast({ title: '导出成功', icon: 'success' })
    } catch (err) {
      Taro.hideLoading()
      Taro.showToast({ title: '导出失败', icon: 'error' })
    }
  }

  // ── Inline Login Form ──
  if (showLogin) {
    return (
      <LoginGate
        showUserIdField
        subtitle='基础版 · 本地部署'
        onLoginSuccess={() => {
          setShowLogin(false)
          loadDashboard()
        }}
      />
    )
  }

  // ── Dashboard Content ──
  function retryLoad() {
    loadDashboard()
  }

  return (
    <View className='page-index'>
      <View className='header'>
        <Text className='header-title'>PromiseLink</Text>
        <Text className='header-date'>{dashboard?.date_label || '今日'}</Text>
      </View>

      {/* Loading state */}
      {loading && (
        <View className='loading'>
          <Text>加载中...</Text>
        </View>
      )}

      {/* Error state with retry */}
      {error && !loading && !showLogin && (
        <View className='error-container'>
          <Text className='error-text'>{error}</Text>
          <Button size='mini' onClick={retryLoad}>重试</Button>
          {error.includes('401') && (
            <Button size='mini' onClick={() => setShowLogin(true)} style={{marginLeft:'10px'}}>重新登录</Button>
          )}
        </View>
      )}

      {/* Dashboard content */}
      {!loading && !error && !showLogin && dashboard && (
        <ScrollView scrollY className='content'>
          {/* Summary Cards */}
          <View className='summary-cards'>
            <View className='card'>
              <Text className='card-number'>{dashboard.summary.total_events ?? 0}</Text>
              <Text className='card-label'>今日事件</Text>
            </View>
            <View className='card'>
              <Text className='card-number'>{dashboard.summary.total_todos ?? 0}</Text>
              <Text className='card-label'>待办事项</Text>
            </View>
            <View className='card'>
              <Text className='card-number accent'>{dashboard.summary.overdue_todos ?? 0}</Text>
              <Text className='card-label'>已逾期</Text>
            </View>
            <View className='card' onClick={() => Taro.switchTab({ url: '/pages/promises/index' })}>
              <Text className='card-number'>{dashboard.summary.pending_promises ?? 0}</Text>
              <Text className='card-label'>待兑现承诺</Text>
            </View>
          </View>

          {/* Quick Input */}
          <View className='section'>
            <View className='quick-input' onClick={() => Taro.navigateTo({ url: '/pages/input/index' })}>
              <Text className='quick-input-placeholder'>快速录入事件、待办、承诺...</Text>
            </View>
          </View>

          {/* F-69 今日提醒摘要条（1.3 提醒页入口） */}
          {reminderData && reminderData.total_pending > 0 && (
            <View className='section'>
              <View
                className='reminder-summary-bar'
                onClick={() => Taro.navigateTo({ url: '/pages/reminders/index' })}
              >
                <View className='reminder-summary-info'>
                  <Text className='reminder-summary-title'>今日提醒</Text>
                  <Text className='reminder-summary-desc'>
                    {reminderData.total_pending} 条待处理 · 剩余配额 {reminderData.fatigue_remaining}
                  </Text>
                </View>
                <Text className='reminder-summary-arrow'>查看 ›</Text>
              </View>
            </View>
          )}

          {/* Data Export */}
          <View className='section'>
            <View className='export-btn' onClick={handleExportData}>
              <Text className='export-btn-text'>导出数据</Text>
            </View>
          </View>

          {/* Today's Events */}
          <View className='section'>
            <Text className='section-title'>今日事件 ({dashboard.events?.length ?? 0})</Text>
            {(dashboard.events?.length ?? 0) === 0 ? (
              <View className='empty'><Text>暂无事件，点击右下角按钮添加</Text></View>
            ) : (
              dashboard.events.map(event => (
                <View key={event.id} className='event-item' onClick={() => navigateToEvent(event.id)}>
                  <View className='event-left'>
                    {event.time ? <Text className='event-time'>{event.time}</Text> : null}
                  </View>
                  <View className='event-right'>
                    <Text className='event-title'>{event.title}</Text>
                    {(event.entities?.length ?? 0) > 0 && (
                      <Text className='event-entities'>{event.entities.join(', ')}</Text>
                    )}
                    {event.todo_count > 0 && (
                      <Text className='event-todo-count'>{event.todo_count}个待办</Text>
                    )}
                  </View>
                </View>
              ))
            )}
          </View>

          {/* Today's Todos */}
          <View className='section'>
            <Text className='section-title'>今日待办 ({dashboard.todos?.length ?? 0})</Text>
            {(dashboard.todos?.length ?? 0) === 0 ? (
              <View className='empty'><Text>暂无待办</Text></View>
            ) : (
              dashboard.todos.map(todo => (
                <View key={todo.id} className={`todo-item ${todo.is_overdue ? 'overdue' : ''}`} onClick={() => Taro.switchTab({ url: '/pages/todos/index' })}>
                  <View className='todo-info'>
                    <Text className='todo-title'>{todo.title}</Text>
                    {todo.related_person && (
                      <Text className='todo-person'>@ {todo.related_person}</Text>
                    )}
                  </View>
                  <View className='todo-meta'>
                    {todo.due_date && <Text className='todo-due'>{todo.due_date}</Text>}
                    {todo.is_overdue && <Text className='todo-overdue-badge'>逾期</Text>}
                  </View>
                </View>
              ))
            )}
          </View>

          {/* F-E4: Supply-Demand Matching */}
          {sdMatches.length > 0 && (
            <View className='section sd-section'>
              <Text className='section-title sd-title'>供需匹配机会 ({sdMatches.length})</Text>
              {sdMatches.map((m, idx) => (
                <View key={idx} className='sd-card'>
                  <View className='sd-match-header'>
                    <Text className='sd-demander'>{m.demander_name}</Text>
                    <Text className='sd-arrow'>需要</Text>
                    <Text className='sd-supplier'>{m.supplier_name || '可提供'}</Text>
                  </View>
                  <Text className='sd-demand-text'>{m.demand_text}</Text>
                  {m.supply_text && <Text className='sd-supply-text'>→ {m.supply_text}</Text>}
                  <Text className='sd-reason'>{m.match_reason}</Text>
                </View>
              ))}
            </View>
          )}

          {/* F-G1: Relationship Health Diagnostic */}
          {healthData && healthData.total_entities > 0 && (
            <View className='section health-section'>
              <View className='health-header'>
                <Text className='health-title'>关系健康度</Text>
                <View className='health-badges'>
                  <Text className={`badge badge-healthy`}>健康 {healthData.healthy_count}</Text>
                  <Text className={`badge badge-attention`}>关注 {healthData.attention_count}</Text>
                  <Text className={`badge badge-risk`}>风险 {healthData.at_risk_count}</Text>
                </View>
              </View>
              <Text className='health-summary'>{healthData.summary_text}</Text>
              <View className='health-list'>
                {healthData.items
                  .sort((a, b) => a.health_score - b.health_score)
                  .slice(0, 5)
                  .map((item) => (
                  <View
                    key={item.entity_id}
                    className={`health-card health-${item.health_level}`}
                    onClick={() => Taro.switchTab({ url: '/pages/entities/index' })}
                  >
                    <View className='health-card-top'>
                      <Text className='health-name'>{item.name}</Text>
                      <View className='health-score-badge' style={{ backgroundColor: item.stage_color }}>
                        <Text className='health-score-text'>{item.health_score.toFixed(0)}</Text>
                      </View>
                    </View>
                    <Text className='health-stage'>{item.stage_label}</Text>
                    <Text className='health-suggestion'>{item.suggestion}</Text>
                  </View>
                ))}
              </View>
            </View>
          )}

          {/* F-G3: Care Reminders */}
          {careData && careData.total > 0 && (
            <View className='section care-section'>
              <View className='care-header'>
                <Text className='care-title'>关怀提醒</Text>
                {(careData.personal_items.length + careData.business_items.length) > 3 && (
                  <Text className='care-toggle' onClick={() => setShowAllCare(!showAllCare)}>
                    {showAllCare ? '收起' : `查看全部 (${careData.total})`}
                  </Text>
                )}
              </View>
              <Text className='care-summary'>{careData.summary_text}</Text>
              <View className='care-list'>
                {/* Personal care items */}
                {(showAllCare ? careData.personal_items : careData.personal_items.slice(0, 3)).map((item, idx) => (
                  <View key={'p-' + item.entity_id + idx} className='care-card care-personal' onClick={() => Taro.switchTab({ url: '/pages/entities/index' })}>
                    <View className='care-card-top'>
                      <Text className='care-icon'>{item.care_icon}</Text>
                      <View className='care-info'>
                        <Text className='care-name'>{item.name}</Text>
                        <Text className='care-detail'>{item.concern_detail}</Text>
                      </View>
                    </View>
                    <Text className='care-action'>{item.suggested_action}</Text>
                    <Text className='care-meta'>提及于{item.days_since_mentioned}天前</Text>
                  </View>
                ))}
                {/* Business concern items */}
                {careData.business_items.length > 0 && (
                  <>
                    <Text className='care-subsection-label'>商务关注</Text>
                    {(showAllCare ? careData.business_items : careData.business_items.slice(0, 2)).map((item, idx) => (
                      <View key={'b-' + item.entity_id + idx} className='care-card care-business' onClick={() => Taro.switchTab({ url: '/pages/entities/index' })}>
                        <View className='care-card-top'>
                          <Text className='care-icon'>{item.care_icon}</Text>
                          <View className='care-info'>
                            <Text className='care-name'>{item.name}</Text>
                            <Text className='care-detail'>{item.concern_detail}</Text>
                          </View>
                        </View>
                        <Text className='care-action'>{item.suggested_action}</Text>
                        <Text className='care-meta'>提及于{item.days_since_mentioned}天前</Text>
                      </View>
                    ))}
                  </>
                )}
              </View>
            </View>
          )}
        </ScrollView>
      )}

      {/* Empty state when not loading and no data */}
      {!loading && !error && !showLogin && !dashboard && (
        <View className='empty' style={{paddingTop: '100px'}}>
          <Text>暂无数据</Text>
        </View>
      )}

      {/* FAB Input Button */}
      {!showLogin && (
        <View className='fab-btn' onClick={() => Taro.navigateTo({ url: '/pages/input/index' })}>
          <Text className='fab-icon'>+</Text>
        </View>
      )}
    </View>
  )
}
