import { useEffect, useState, useRef, useCallback } from 'react'
import { View, Text, ScrollView, Input, Button } from '@tarojs/components'
import Taro from '@tarojs/taro'
import './index.scss'

// ── Types ──

interface UsageSummary {
  total_users: number
  active_users: number
  total_calls: number
  today_calls: number
  month_calls: number
  service_breakdown: {
    llm: number
    asr: number
    tts: number
    ocr: number
  }
}

interface UserUsageItem {
  license_key: string
  user_id: string
  plan_type: string
  status: string
  quota_limit_tokens: number
  quota_used_tokens: number
  quota_limit_asr: number
  quota_used_asr: number
  quota_limit_tts: number
  quota_used_tts: number
  quota_limit_ocr: number
  quota_used_ocr: number
  llm_calls: number
  asr_calls: number
  tts_calls: number
  ocr_calls: number
  total_calls: number
  traffic_light: string
}

interface UserUsageList {
  page: number
  page_size: number
  total: number
  total_pages: number
  items: UserUsageItem[]
}

interface HealthStatus {
  status: string
  version: string
  timestamp: string
  components: {
    api_key_pool: {
      status: string
      total_keys: number
      active_keys: number
      circuit_open_count: number
      providers?: Record<string, {
        total_keys: number
        active_keys: number
        circuit_open: number
        rate_limited: number
        avg_health: number
      }>
    }
    redis: string
    database: string
  }
}

// ── API helpers ──

const ADMIN_API_BASE = '/api/v1/admin'

function getAdminKey(): string {
  return localStorage.getItem('promiselink_admin_key') || ''
}

function setAdminKey(key: string): void {
  localStorage.setItem('promiselink_admin_key', key)
}

async function adminRequest<T>(path: string): Promise<T> {
  const adminKey = getAdminKey()
  if (!adminKey) {
    throw new Error('未设置管理员密钥')
  }
  const url = `${ADMIN_API_BASE}${path}`
  const res = await fetch(url, {
    method: 'GET',
    headers: {
      'X-Admin-Key': adminKey,
    },
  })
  if (res.status === 401) {
    throw new Error('管理员密钥无效')
  }
  if (!res.ok) {
    const text = await res.text().catch(() => 'Unknown error')
    throw new Error(`API Error ${res.status}: ${text}`)
  }
  const json = await res.json()
  if (json.success && json.data) {
    return json.data as T
  }
  throw new Error(json.error?.message || 'API returned no data')
}

async function exportCsv(): Promise<void> {
  const adminKey = getAdminKey()
  if (!adminKey) {
    Taro.showToast({ title: '未设置管理员密钥', icon: 'error' })
    return
  }
  try {
    Taro.showLoading({ title: '导出中...' })
    const res = await fetch(`${ADMIN_API_BASE}/usage/export`, {
      method: 'GET',
      headers: { 'X-Admin-Key': adminKey },
    })
    if (!res.ok) {
      throw new Error(`Export failed: ${res.status}`)
    }
    const blob = await res.blob()
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `usage_export_${new Date().toISOString().slice(0, 10)}.csv`
    a.click()
    URL.revokeObjectURL(url)
    Taro.showToast({ title: '导出成功', icon: 'success' })
  } catch (err) {
    Taro.hideLoading()
    Taro.showToast({ title: '导出失败', icon: 'error' })
  }
}

// ── Traffic light helper ──

function trafficLightText(light: string): string {
  if (light === 'green') return '正常'
  if (light === 'yellow') return '接近上限'
  return '已超限'
}

// ── Component ──

export default function AdminUsage() {
  const [adminKey, setAdminKeyState] = useState('')
  const [keyInput, setKeyInput] = useState('')
  const [showKeyInput, setShowKeyInput] = useState(false)
  const [summary, setSummary] = useState<UsageSummary | null>(null)
  const [userList, setUserList] = useState<UserUsageList | null>(null)
  const [health, setHealth] = useState<HealthStatus | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [page, setPage] = useState(1)
  const [sortBy, setSortBy] = useState('total_calls')
  const [order, setOrder] = useState<'asc' | 'desc'>('desc')
  const [lastRefresh, setLastRefresh] = useState('')
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null)

  // Load admin key from storage on mount
  useEffect(() => {
    const stored = getAdminKey()
    if (stored) {
      setAdminKeyState(stored)
      setKeyInput(stored)
    } else {
      setShowKeyInput(true)
    }
  }, [])

  const loadData = useCallback(async () => {
    if (!adminKey) return
    try {
      setLoading(true)
      setError('')
      const [sum, users, hl] = await Promise.all([
        adminRequest<UsageSummary>('/usage/summary'),
        adminRequest<UserUsageList>(`/usage/users?page=${page}&page_size=20&sort_by=${sortBy}&order=${order}`),
        adminRequest<HealthStatus>('/health').catch(() => null),
      ])
      setSummary(sum)
      setUserList(users)
      if (hl) setHealth(hl)
      setLastRefresh(new Date().toLocaleTimeString('zh-CN'))
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err)
      setError(msg)
      if (msg.includes('密钥') || msg.includes('401')) {
        setShowKeyInput(true)
      }
    } finally {
      setLoading(false)
    }
  }, [adminKey, page, sortBy, order])

  // Load data when admin key is set
  useEffect(() => {
    if (adminKey) {
      loadData()
    }
  }, [adminKey, loadData])

  // Auto-refresh every 30 seconds
  useEffect(() => {
    if (!adminKey) return
    timerRef.current = setInterval(() => {
      loadData()
    }, 30000)
    return () => {
      if (timerRef.current) {
        clearInterval(timerRef.current)
      }
    }
  }, [adminKey, loadData])

  function handleSaveKey() {
    if (!keyInput.trim()) {
      Taro.showToast({ title: '请输入密钥', icon: 'error' })
      return
    }
    setAdminKey(keyInput.trim())
    setAdminKey(keyInput.trim())
    setShowKeyInput(false)
  }

  function handleLogout() {
    localStorage.removeItem('promiselink_admin_key')
    setAdminKey('')
    setKeyInput('')
    setShowKeyInput(true)
    setSummary(null)
    setUserList(null)
    setHealth(null)
  }

  function handleSort(field: string) {
    if (sortBy === field) {
      setOrder(order === 'asc' ? 'desc' : 'asc')
    } else {
      setSortBy(field)
      setOrder('desc')
    }
    setPage(1)
  }

  // ── Admin Key Input Screen ──
  if (showKeyInput || !adminKey) {
    return (
      <View className='page-admin-usage'>
        <View className='admin-login-card'>
          <Text className='admin-login-title'>桥接监控仪表盘</Text>
          <Text className='admin-login-subtitle'>请输入管理员密钥</Text>
          <View className='form-group'>
            <Input
              className='admin-input'
              type='password'
              value={keyInput}
              onInput={e => setKeyInput(e.detail.value)}
              placeholder='X-Admin-Key'
            />
          </View>
          <Button className='admin-login-btn' onClick={handleSaveKey}>
            进 入
          </Button>
        </View>
      </View>
    )
  }

  return (
    <View className='page-admin-usage'>
      {/* Header */}
      <View className='admin-header'>
        <View className='admin-header-left'>
          <Text className='admin-header-title'>桥接监控仪表盘</Text>
          <Text className='admin-header-sub'>
            {lastRefresh ? `最后刷新: ${lastRefresh}` : '加载中...'}
          </Text>
        </View>
        <View className='admin-header-right'>
          <Text className='refresh-btn' onClick={() => loadData()}>
            {loading ? '刷新中...' : '刷新'}
          </Text>
          <Text className='logout-btn' onClick={handleLogout}>退出</Text>
        </View>
      </View>

      <ScrollView scrollY className='admin-content'>
        {/* Error */}
        {error && (
          <View className='error-banner'>
            <Text>{error}</Text>
          </View>
        )}

        {/* Summary Cards */}
        {summary && (
          <View className='summary-section'>
            <View className='summary-cards'>
              <View className='summary-card'>
                <Text className='card-number'>{summary.total_users}</Text>
                <Text className='card-label'>总用户数</Text>
              </View>
              <View className='summary-card'>
                <Text className='card-number accent'>{summary.active_users}</Text>
                <Text className='card-label'>活跃用户</Text>
              </View>
              <View className='summary-card'>
                <Text className='card-number'>{summary.today_calls}</Text>
                <Text className='card-label'>今日调用</Text>
              </View>
              <View className='summary-card'>
                <Text className='card-number accent'>{summary.month_calls}</Text>
                <Text className='card-label'>本月调用</Text>
              </View>
            </View>

            {/* Service breakdown */}
            <View className='service-breakdown'>
              <Text className='breakdown-title'>服务调用分布</Text>
              <View className='breakdown-items'>
                <View className='breakdown-item'>
                  <Text className='breakdown-label'>LLM</Text>
                  <Text className='breakdown-value'>{summary.service_breakdown.llm}</Text>
                </View>
                <View className='breakdown-item'>
                  <Text className='breakdown-label'>ASR</Text>
                  <Text className='breakdown-value'>{summary.service_breakdown.asr}</Text>
                </View>
                <View className='breakdown-item'>
                  <Text className='breakdown-label'>TTS</Text>
                  <Text className='breakdown-value'>{summary.service_breakdown.tts}</Text>
                </View>
                <View className='breakdown-item'>
                  <Text className='breakdown-label'>OCR</Text>
                  <Text className='breakdown-value'>{summary.service_breakdown.ocr}</Text>
                </View>
              </View>
            </View>
          </View>
        )}

        {/* Health Status */}
        {health && (
          <View className='health-section'>
            <Text className='section-title'>网关健康状态</Text>
            <View className='health-cards'>
              <View className={`health-card health-${health.components.api_key_pool.status}`}>
                <Text className='health-card-label'>Key池</Text>
                <Text className='health-card-value'>
                  {health.components.api_key_pool.active_keys}/{health.components.api_key_pool.total_keys}
                </Text>
                <Text className='health-card-status'>{health.components.api_key_pool.status}</Text>
              </View>
              <View className={`health-card health-${health.components.redis}`}>
                <Text className='health-card-label'>Redis</Text>
                <Text className='health-card-status'>{health.components.redis}</Text>
              </View>
              <View className={`health-card health-${health.components.database}`}>
                <Text className='health-card-label'>数据库</Text>
                <Text className='health-card-status'>{health.components.database}</Text>
              </View>
            </View>
            {health.components.api_key_pool.providers && (
              <View className='providers-list'>
                {Object.entries(health.components.api_key_pool.providers).map(([name, info]) => (
                  <View key={name} className='provider-item'>
                    <Text className='provider-name'>{name}</Text>
                    <Text className='provider-info'>
                      活跃 {info.active_keys}/{info.total_keys} · 健康 {info.avg_health}
                    </Text>
                    {info.circuit_open > 0 && (
                      <Text className='provider-warning'>熔断 {info.circuit_open}</Text>
                    )}
                  </View>
                ))}
              </View>
            )}
          </View>
        )}

        {/* User Usage Table */}
        {userList && (
          <View className='table-section'>
            <View className='table-header'>
              <Text className='section-title'>用户用量列表 ({userList.total})</Text>
              <Text className='export-btn' onClick={exportCsv}>导出CSV</Text>
            </View>

            {/* Table */}
            <View className='usage-table'>
              {/* Header row */}
              <View className='table-row table-row-header'>
                <Text className='col-key'>许可证密钥</Text>
                <Text className='col-user'>用户</Text>
                <Text className='col-num sortable' onClick={() => handleSort('llm')}>LLM {sortBy === 'llm' ? (order === 'asc' ? '↑' : '↓') : ''}</Text>
                <Text className='col-num sortable' onClick={() => handleSort('asr')}>ASR {sortBy === 'asr' ? (order === 'asc' ? '↑' : '↓') : ''}</Text>
                <Text className='col-num sortable' onClick={() => handleSort('tts')}>TTS {sortBy === 'tts' ? (order === 'asc' ? '↑' : '↓') : ''}</Text>
                <Text className='col-num sortable' onClick={() => handleSort('ocr')}>OCR {sortBy === 'ocr' ? (order === 'asc' ? '↑' : '↓') : ''}</Text>
                <Text className='col-num sortable' onClick={() => handleSort('total_calls')}>总计 {sortBy === 'total_calls' ? (order === 'asc' ? '↑' : '↓') : ''}</Text>
                <Text className='col-light'>状态</Text>
              </View>
              {/* Data rows */}
              {userList.items.length === 0 ? (
                <View className='table-empty'>
                  <Text>暂无数据</Text>
                </View>
              ) : (
                userList.items.map((item, idx) => (
                  <View key={item.license_key} className={`table-row ${idx % 2 === 1 ? 'row-alt' : ''}`}>
                    <Text className='col-key'>{item.license_key}</Text>
                    <Text className='col-user'>{item.user_id || '-'}</Text>
                    <Text className='col-num'>{item.llm_calls}</Text>
                    <Text className='col-num'>{item.asr_calls}</Text>
                    <Text className='col-num'>{item.tts_calls}</Text>
                    <Text className='col-num'>{item.ocr_calls}</Text>
                    <Text className='col-num'>{item.total_calls}</Text>
                    <View className='col-light'>
                      <View className={`traffic-light light-${item.traffic_light}`}>
                        <Text className='light-text'>{trafficLightText(item.traffic_light)}</Text>
                      </View>
                    </View>
                  </View>
                ))
              )}
            </View>

            {/* Pagination */}
            {userList.total_pages > 1 && (
              <View className='pagination'>
                <Text
                  className={`page-btn ${page <= 1 ? 'disabled' : ''}`}
                  onClick={() => page > 1 && setPage(page - 1)}
                >上一页</Text>
                <Text className='page-info'>{page} / {userList.total_pages}</Text>
                <Text
                  className={`page-btn ${page >= userList.total_pages ? 'disabled' : ''}`}
                  onClick={() => page < userList.total_pages && setPage(page + 1)}
                >下一页</Text>
              </View>
            )}
          </View>
        )}

        {/* Loading */}
        {loading && !summary && (
          <View className='loading-state'>
            <Text>加载中...</Text>
          </View>
        )}
      </ScrollView>
    </View>
  )
}
