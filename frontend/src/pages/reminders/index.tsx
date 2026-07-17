import { useEffect, useMemo, useState } from 'react'
import { View, Text, ScrollView, Input, Checkbox } from '@tarojs/components'
import Taro from '@tarojs/taro'
import {
  getDailyReminders,
  batchActionReminders,
  getReminderPreferences,
  updateReminderPreferences,
  DailyReminderResponse,
  ReminderItem,
  ReminderPreferenceResponse,
} from '../../services/api'
import { isLoggedIn } from '../../services/auth'
import LoginGate from '../../components/LoginGate'
import './index.scss'

// 4 级优先级分组（1.3 提醒页核心信息架构）
const PRIORITY_GROUPS = [
  { value: 1, label: 'P0 紧急', desc: '今日必须处理' },
  { value: 2, label: 'P1 重要', desc: '今日优先处理' },
  { value: 3, label: 'P2 一般', desc: '今日可处理' },
  { value: 4, label: 'P3 低优', desc: '有空再处理' },
]

const REMINDER_TYPE_LABELS: Record<string, string> = {
  promise_due: '承诺到期',
  followup: '跟进',
  stage_suggestion: '阶段建议',
  dormant_contact: '久未联系',
  scheduled_due: '日程到期',
}

export default function RemindersPage() {
  const [data, setData] = useState<DailyReminderResponse | null>(null)
  const [pref, setPref] = useState<ReminderPreferenceResponse | null>(null)
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [showPref, setShowPref] = useState(false)
  const [prefDraft, setPrefDraft] = useState<ReminderPreferenceResponse | null>(null)
  const [savingPref, setSavingPref] = useState(false)
  const [showLogin, setShowLogin] = useState(false)

  useEffect(() => {
    if (!isLoggedIn()) {
      setShowLogin(true)
      setLoading(false)
      return
    }
    loadAll()
  }, [])

  async function loadAll() {
    try {
      setLoading(true)
      setError('')
      const [d, p] = await Promise.all([
        getDailyReminders(),
        getReminderPreferences().catch(() => null),
      ])
      setData(d)
      setPref(p)
      setPrefDraft(p)
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err)
      if (msg.includes('401')) {
        setShowLogin(true)
      } else {
        setError(msg)
      }
    } finally {
      setLoading(false)
    }
  }

  // 按优先级分组
  const groups = useMemo(() => {
    const byPriority: Record<number, ReminderItem[]> = { 1: [], 2: [], 3: [], 4: [] }
    for (const item of data?.items || []) {
      const p = item.priority >= 1 && item.priority <= 4 ? item.priority : 4
      byPriority[p].push(item)
    }
    return byPriority
  }, [data])

  const hasSelected = selected.size > 0

  function toggleSelect(todoId: string, checked: boolean) {
    setSelected(prev => {
      const next = new Set(prev)
      if (checked) next.add(todoId)
      else next.delete(todoId)
      return next
    })
  }

  function selectAllInGroup(priority: number, checked: boolean) {
    setSelected(prev => {
      const next = new Set(prev)
      for (const item of groups[priority] || []) {
        if (checked) next.add(item.todo_id)
        else next.delete(item.todo_id)
      }
      return next
    })
  }

  async function handleBatchAction(
    action: 'completed' | 'snoozed' | 'dismissed',
    snoozeHours?: number,
  ) {
    if (!hasSelected) return
    const ids = Array.from(selected)
    try {
      Taro.showLoading({ title: '处理中...' })
      const res = await batchActionReminders(ids, action, snoozeHours)
      Taro.hideLoading()
      const failCount = res.failed.length
      Taro.showToast({
        title: failCount === 0 ? `成功 ${res.success.length} 条` : `成功 ${res.success.length}，失败 ${failCount}`,
        icon: failCount === 0 ? 'success' : 'none',
      })
      setSelected(new Set())
      await loadAll()
    } catch (err: unknown) {
      Taro.hideLoading()
      Taro.showToast({ title: '操作失败', icon: 'error' })
    }
  }

  async function handleSingleAction(
    todoId: string,
    action: 'completed' | 'snoozed' | 'dismissed',
    snoozeHours?: number,
  ) {
    try {
      Taro.showLoading({ title: '处理中...' })
      await batchActionReminders([todoId], action, snoozeHours)
      Taro.hideLoading()
      Taro.showToast({ title: '已处理', icon: 'success' })
      await loadAll()
    } catch {
      Taro.hideLoading()
      Taro.showToast({ title: '操作失败', icon: 'error' })
    }
  }

  async function handleSnoozeWithHours(ids: string[]) {
    // 弹出输入框获取 snooze_hours（Taro H5 editable 模式，参考 todos/detail.tsx 模式）
    const modalOpts = {
      title: '推迟提醒',
      content: '24',
      editable: true,
      placeholderText: '请输入推迟小时数（默认 24）',
      confirmText: '推迟',
      cancelText: '取消',
    }
    const res = await Taro.showModal(modalOpts as Parameters<typeof Taro.showModal>[0])
    if (!res.confirm) return
    const hours = parseInt((res as { content?: string }).content || '24', 10) || 24
    if (isNaN(hours) || hours < 1 || hours > 168) {
      Taro.showToast({ title: '请输入 1-168 之间的数字', icon: 'none' })
      return
    }
    try {
      Taro.showLoading({ title: '处理中...' })
      const r = await batchActionReminders(ids, 'snoozed', hours)
      Taro.hideLoading()
      Taro.showToast({ title: `推迟 ${r.success.length} 条`, icon: 'success' })
      setSelected(new Set())
      await loadAll()
    } catch {
      Taro.hideLoading()
      Taro.showToast({ title: '推迟失败', icon: 'error' })
    }
  }

  async function savePref() {
    if (!prefDraft) return
    try {
      setSavingPref(true)
      const updated = await updateReminderPreferences({
        preferred_times: prefDraft.preferred_times,
        fatigue_threshold: prefDraft.fatigue_threshold,
        quiet_hours_start: prefDraft.quiet_hours_start,
        quiet_hours_end: prefDraft.quiet_hours_end,
      })
      setPref(updated)
      setPrefDraft(updated)
      Taro.showToast({ title: '已保存', icon: 'success' })
    } catch {
      Taro.showToast({ title: '保存失败', icon: 'error' })
    } finally {
      setSavingPref(false)
    }
  }

  function updatePrefDraft(field: keyof ReminderPreferenceResponse, value: string | number | string[]) {
    if (!prefDraft) return
    setPrefDraft({ ...prefDraft, [field]: value })
  }

  function updatePreferredTimes(text: string) {
    // 逗号分隔，例如 "09:00, 20:00"
    const times = text.split(',').map(t => t.trim()).filter(Boolean)
    updatePrefDraft('preferred_times', times)
  }

  // ── Login redirect ──
  if (showLogin) {
    return (
      <LoginGate
        showBackHomeButton
        subtitle='请先登录以查看今日提醒'
      />
    )
  }

  return (
    <View className='page-reminders'>
      <View className='header'>
        <Text className='header-title'>今日提醒</Text>
        <Text
          className={`pref-toggle ${showPref ? 'active' : ''}`}
          onClick={() => setShowPref(!showPref)}
        >
          {showPref ? '收起偏好' : '提醒偏好'}
        </Text>
      </View>

      {/* 提醒偏好面板（1.1 设置页核心项） */}
      {showPref && prefDraft && (
        <View className='pref-panel'>
          <View className='pref-row'>
            <Text className='pref-label'>提醒时间</Text>
            <Input
              className='pref-input'
              type='text'
              value={prefDraft.preferred_times.join(', ')}
              onInput={e => updatePreferredTimes(e.detail.value)}
              placeholder='09:00, 20:00'
            />
          </View>
          <View className='pref-row'>
            <Text className='pref-label'>每日上限</Text>
            <Input
              className='pref-input'
              type='number'
              value={String(prefDraft.fatigue_threshold)}
              onInput={e => {
                const n = parseInt(e.detail.value, 10)
                if (!isNaN(n)) updatePrefDraft('fatigue_threshold', n)
              }}
            />
          </View>
          <View className='pref-row'>
            <Text className='pref-label'>免打扰起</Text>
            <Input
              className='pref-input'
              type='text'
              value={prefDraft.quiet_hours_start}
              onInput={e => updatePrefDraft('quiet_hours_start', e.detail.value)}
              placeholder='22:00'
            />
          </View>
          <View className='pref-row'>
            <Text className='pref-label'>免打扰止</Text>
            <Input
              className='pref-input'
              type='text'
              value={prefDraft.quiet_hours_end}
              onInput={e => updatePrefDraft('quiet_hours_end', e.detail.value)}
              placeholder='08:00'
            />
          </View>
          <View className='pref-actions'>
            <View className='pref-btn pref-btn-ghost' onClick={() => { setPrefDraft(pref); setShowPref(false) }}>
              <Text>取消</Text>
            </View>
            <View className={`pref-btn pref-btn-primary ${savingPref ? 'disabled' : ''}`} onClick={savingPref ? undefined : savePref}>
              <Text>{savingPref ? '保存中...' : '保存'}</Text>
            </View>
          </View>
        </View>
      )}

      {/* 状态条 */}
      {data && (
        <View className='stats-bar'>
          <View className='stat-item'>
            <Text className='stat-num'>{data.total_pending}</Text>
            <Text className='stat-label'>待处理</Text>
          </View>
          <View className='stat-item'>
            <Text className='stat-num'>{data.fatigue_remaining}</Text>
            <Text className='stat-label'>剩余配额</Text>
          </View>
          <View className={`stat-item ${data.is_quiet_hours ? 'stat-quiet' : ''}`}>
            <Text className='stat-num'>{data.is_quiet_hours ? '是' : '否'}</Text>
            <Text className='stat-label'>免打扰</Text>
          </View>
        </View>
      )}

      {/* 加载中 */}
      {loading && (
        <View className='loading'>
          <Text>加载中...</Text>
        </View>
      )}

      {/* 错误 */}
      {error && !loading && (
        <View className='error-container'>
          <Text className='error-text'>{error}</Text>
          <View className='retry-btn' onClick={loadAll}><Text>重试</Text></View>
        </View>
      )}

      {/* 提醒列表（4 级优先级分组） */}
      {!loading && !error && data && (
        <ScrollView scrollY className='reminder-list'>
          {data.items.length === 0 && (
            <View className='empty-state'>
              <Text className='empty-icon'>✓</Text>
              <Text className='empty-title'>今日无待处理提醒</Text>
              <Text className='empty-desc'>所有提醒已处理，或已耗尽今日提醒配额</Text>
            </View>
          )}

          {PRIORITY_GROUPS.map(group => {
            const items = groups[group.value] || []
            if (items.length === 0) return null
            const groupSelectedCount = items.filter(i => selected.has(i.todo_id)).length
            const groupAllSelected = groupSelectedCount === items.length
            return (
              <View key={group.value} className={`priority-group priority-${group.value}`}>
                <View className='group-header'>
                  <Checkbox
                    value={String(group.value)}
                    checked={groupAllSelected}
                    onClick={() => selectAllInGroup(group.value, !groupAllSelected)}
                  />
                  <Text className='group-label'>{group.label}</Text>
                  <Text className='group-desc'>{group.desc}</Text>
                  <Text className='group-count'>{items.length}</Text>
                </View>
                {items.map(item => {
                  const isSelected = selected.has(item.todo_id)
                  return (
                    <View key={item.todo_id} className={`reminder-card ${isSelected ? 'selected' : ''}`}>
                      <View className='card-main'>
                        <Checkbox
                          value={item.todo_id}
                          checked={isSelected}
                          onClick={() => toggleSelect(item.todo_id, !isSelected)}
                        />
                        <View className='card-content'>
                          <View className='card-title-row'>
                            <Text className='card-title'>{item.title}</Text>
                            <Text className='card-type-tag'>{REMINDER_TYPE_LABELS[item.reminder_type] || item.reminder_type}</Text>
                          </View>
                          {item.description && <Text className='card-desc'>{item.description}</Text>}
                          <View className='card-meta'>
                            {item.due_date && (
                              <Text className='meta-due'>到期 {new Date(item.due_date).toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })}</Text>
                            )}
                            {item.dynamic_score !== null && item.dynamic_score !== undefined && (
                              <Text className='meta-score'>分数 {item.dynamic_score.toFixed(0)}</Text>
                            )}
                          </View>
                        </View>
                      </View>
                      <View className='card-actions'>
                        <View className='action-btn action-complete' onClick={() => handleSingleAction(item.todo_id, 'completed')}>
                          <Text>完成</Text>
                        </View>
                        <View className='action-btn action-snooze' onClick={() => handleSnoozeWithHours([item.todo_id])}>
                          <Text>推迟</Text>
                        </View>
                        <View className='action-btn action-dismiss' onClick={() => handleSingleAction(item.todo_id, 'dismissed')}>
                          <Text>忽略</Text>
                        </View>
                      </View>
                    </View>
                  )
                })}
              </View>
            )
          })}
        </ScrollView>
      )}

      {/* 底部批量操作栏 */}
      {hasSelected && (
        <View className='batch-bar'>
          <View className='batch-info'>
            <Text className='batch-count'>已选 {selected.size} 条</Text>
            <Text className='batch-clear' onClick={() => setSelected(new Set())}>取消</Text>
          </View>
          <View className='batch-actions'>
            <View className='batch-btn batch-complete' onClick={() => handleBatchAction('completed')}>
              <Text>批量完成</Text>
            </View>
            <View className='batch-btn batch-snooze' onClick={() => handleSnoozeWithHours(Array.from(selected))}>
              <Text>批量推迟</Text>
            </View>
            <View className='batch-btn batch-dismiss' onClick={() => handleBatchAction('dismissed')}>
              <Text>批量忽略</Text>
            </View>
          </View>
        </View>
      )}
    </View>
  )
}
