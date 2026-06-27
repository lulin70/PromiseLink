import { useState, useEffect, useCallback, useRef, type ChangeEvent } from 'react'
import { View, Text, Textarea, Button, Picker, Input } from '@tarojs/components'
import {
  createEvent, uploadEventFile, getEventDetail, getPendingConfirmations,
  confirmTodo, retryEvent, acceptDegradedEvent, recordScheduledEvent,
  getScheduledEventDetail, createDemand,
  EventCreateResponse, ConfirmationItem,
} from '../../services/api'
import { isLoggedIn } from '../../services/auth'
import Taro, { useRouter } from '@tarojs/taro'
import CorrectionPanel from './CorrectionPanel'
import './index.scss'

// I7: Correction logic extracted to ./CorrectionPanel.tsx.
// Polling race condition is protected via pollRef + mountedRef.

const EVENT_TYPES = [
  { value: 'manual', label: '手动录入' },
  { value: 'meeting', label: '会议' },
  { value: 'call', label: '电话' },
  { value: 'wechat_forward', label: '微信转发' },
]

const EVENT_TYPE_LABELS: Record<string, string> = {
  manual: '手动录入',
  meeting: '会议',
  call: '电话',
  wechat_forward: '微信转发',
}

interface EventDetail {
  id: string
  status: string
  pipeline?: string | null
  processed_at?: string | null
}

export default function InputPage() {
  const router = useRouter()
  const scheduledEventId = router.params.scheduled_event_id || ''

  const [rawText, setRawText] = useState('')
  const [eventType, setEventType] = useState(0)
  const [participants, setParticipants] = useState('')
  const [eventTime, setEventTime] = useState(new Date().toISOString().slice(0, 16))
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [result, setResult] = useState<EventCreateResponse | null>(null)
  const [polling, setPolling] = useState(false)
  const [pollTimeout, setPollTimeout] = useState(false)
  const [eventDetail, setEventDetail] = useState<EventDetail | null>(null)
  // F-E1: Confirmation state
  const [pendingConfirmations, setPendingConfirmations] = useState<ConfirmationItem[]>([])
  const [confirmLoading, setConfirmLoading] = useState<string | null>(null)
  const [editingId, setEditingId] = useState<string | null>(null)
  const [editDesc, setEditDesc] = useState('')
  // File upload state
  const [inputMode, setInputMode] = useState<'text' | 'file'>('text')
  const [selectedFile, setSelectedFile] = useState<string | null>(null)
  // P1: Demand mode state
  const [inputTab, setInputTab] = useState<'event' | 'demand'>('event')
  const [demandText, setDemandText] = useState('')
  const [demandLoading, setDemandLoading] = useState(false)
  const [demandResult, setDemandResult] = useState<{ tag: string; detail: string; related_entity_id?: string } | null>(null)

  // Scheduled event record mode state
  const [isRecordMode, setIsRecordMode] = useState(false)
  const [scheduledTopic, setScheduledTopic] = useState('')

  // ── Parsed result for correction panel ──
  const [parsedDetail, setParsedDetail] = useState<import('../../services/api').EventDetailResponse | null>(null)
  const [corrected, setCorrected] = useState(false)

  // Load scheduled event info if in record mode
  useEffect(() => {
    if (!scheduledEventId) return
    async function loadScheduledEvent() {
      try {
        const se = await getScheduledEventDetail(scheduledEventId)
        if (se.status !== 'pending' && se.status !== 'overdue') {
          setError('该预定日程已录入或已取消')
          return
        }
        setIsRecordMode(true)
        setScheduledTopic(se.topic)
        const typeIdx = EVENT_TYPES.findIndex(t => t.value === se.event_type)
        if (typeIdx >= 0) setEventType(typeIdx)
        const participantNames = (se.participants || [])
          .map(p => p.name)
          .filter(Boolean)
          .join('、')
        const typeLabel = EVENT_TYPE_LABELS[se.event_type] || se.event_type
        const prefix = participantNames
          ? `与${participantNames}的${typeLabel}：${se.topic}\n`
          : `${typeLabel}：${se.topic}\n`
        setRawText(prefix)
        if (participantNames) setParticipants(participantNames)
      } catch (err) {
        setError('加载预定日程失败')
      }
    }
    loadScheduledEvent()
  }, [scheduledEventId])

  if (!isLoggedIn()) {
    Taro.redirectTo({ url: '/pages/index/login' })
    return null
  }

  // I7: polling race condition protection — pollRef tracks the latest request,
  // stale responses are discarded; mountedRef prevents setState after unmount.
  const pollRef = useRef(0)
  const mountedRef = useRef(true)
  // P2: max polling attempts to avoid infinite polling (60 * 2s = 2 minutes)
  const pollCountRef = useRef(0)
  const MAX_POLL_ATTEMPTS = 60
  // Native file input ref (Taro H5 does not support chooseMessageFile)
  const fileInputRef = useRef<HTMLInputElement>(null)

  // Poll for pipeline completion
  const pollEventDetail = useCallback(async (eventId: string) => {
    const current = ++pollRef.current
    try {
      const detail = await getEventDetail(eventId)
      // Race guard: discard stale response (newer request issued or component unmounted)
      if (current !== pollRef.current || !mountedRef.current) {
        return false
      }
      setEventDetail({
        id: detail.id,
        status: detail.status,
        pipeline: detail.pipeline ?? null,
        processed_at: detail.processed_at ?? null,
      })

      if (detail.status === 'completed' || detail.status === 'failed' || detail.status === 'awaiting_retry' || detail.status === 'degraded_completed') {
        setPolling(false)
        if (detail.status === 'completed' || detail.status === 'degraded_completed') {
          // Load full parsed result (entities / associations / todos)
          // degraded_completed means non-critical steps failed but core data is usable
          setParsedDetail(detail)
          try {
            const confirmations = await getPendingConfirmations(eventId)
            // Re-validate after await (a newer request or unmount may have occurred)
            if (current !== pollRef.current || !mountedRef.current) {
              return true
            }
            if (confirmations.length > 0) {
              setPendingConfirmations(confirmations)
            }
          } catch {
            // Silently fail - confirmations are optional
          }
        }
        return true
      }
      return false
    } catch {
      return false
    }
  }, [])

  // I7: mark unmount to prevent subsequent setState and invalidate in-flight polls
  useEffect(() => {
    mountedRef.current = true
    return () => {
      mountedRef.current = false
      pollRef.current++
    }
  }, [])

  useEffect(() => {
    if (!polling || !result) return

    // Reset poll counter and timeout state for a new polling session
    pollCountRef.current = 0
    setPollTimeout(false)

    const timer = setInterval(async () => {
      // P2: stop polling after MAX_POLL_ATTEMPTS to avoid infinite loop
      pollCountRef.current += 1
      if (pollCountRef.current >= MAX_POLL_ATTEMPTS) {
        clearInterval(timer)
        setPolling(false)
        setPollTimeout(true)
        return
      }
      const done = await pollEventDetail(result.id)
      if (done) {
        clearInterval(timer)
      }
    }, 2000)

    return () => {
      clearInterval(timer)
      // Cancel in-flight polling (new event submitted or polling stopped)
      pollRef.current++
    }
  }, [polling, result, pollEventDetail])

  async function handleSubmit() {
    if (!rawText.trim()) {
      setError('请输入内容')
      return
    }
    try {
      setLoading(true)
      setError('')
      setResult(null)
      setEventDetail(null)
      setParsedDetail(null)
      setCorrected(false)
      setPollTimeout(false)

      if (isRecordMode && scheduledEventId) {
        const res = await recordScheduledEvent(scheduledEventId, {
          raw_text: rawText.trim(),
          event_type: EVENT_TYPES[eventType].value,
        })
        setResult({
          id: res.event_id,
          user_id: '',
          event_type: EVENT_TYPES[eventType].value,
          source: 'scheduled_record',
          title: scheduledTopic,
          timestamp: new Date().toISOString(),
          status: 'pending',
          created_at: new Date().toISOString(),
          pipeline_status: res.pipeline_status,
          entity_count: 0,
          todo_count: 0,
        })
        setPolling(true)
        setTimeout(() => pollEventDetail(res.event_id), 1500)
      } else {
        const res = await createEvent(rawText.trim(), EVENT_TYPES[eventType].value)
        setResult(res)
        if (res.pipeline_status === 'pending' || res.status === 'pending') {
          setPolling(true)
          setTimeout(() => pollEventDetail(res.id), 1500)
        }
      }
      setRawText('')
    } catch (err) {
      setError(err instanceof Error ? err.message : '提交失败')
    } finally {
      setLoading(false)
    }
  }

  function handleFileUpload() {
    // Trigger native file input click (Taro H5 does not support chooseMessageFile)
    fileInputRef.current?.click()
  }

  async function handleFileSelected(e: ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0]
    if (!file) return

    // Reset input value to allow selecting the same file again
    if (fileInputRef.current) fileInputRef.current.value = ''

    // Validate extension
    const ext = file.name.toLowerCase().split('.').pop()
    if (ext !== 'txt' && ext !== 'md') {
      setError('仅支持 .txt 和 .md 格式文件')
      return
    }

    // Validate size (1MB)
    if (file.size > 1_048_576) {
      setError('文件大小超过 1MB 限制')
      return
    }

    if (file.size === 0) {
      setError('文件不能为空')
      return
    }

    try {
      setSelectedFile(file.name)
      setLoading(true)
      setError('')
      setResult(null)
      setEventDetail(null)
      setParsedDetail(null)
      setCorrected(false)
      setPollTimeout(false)

      const res = await uploadEventFile(file, EVENT_TYPES[eventType].value)
      setResult(res)
      setSelectedFile(null)

      if (res.pipeline_status === 'pending' || res.status === 'pending') {
        setPolling(true)
        setTimeout(() => pollEventDetail(res.id), 1500)
      }
    } catch (err) {
      setSelectedFile(null)
      setError(err instanceof Error ? err.message : '文件上传失败')
    } finally {
      setLoading(false)
    }
  }

  function handleReset() {
    setResult(null)
    setEventDetail(null)
    setPolling(false)
    setError('')
    setPendingConfirmations([])
    setEditingId(null)
    setSelectedFile(null)
    setParsedDetail(null)
    setCorrected(false)
  }

  async function handleDemandSubmit() {
    if (!demandText.trim()) {
      setError('请输入需求内容')
      return
    }
    try {
      setDemandLoading(true)
      setError('')
      const res = await createDemand(demandText.trim())
      setDemandResult(res.extracted)
      setDemandText('')
    } catch (err) {
      setError(err instanceof Error ? err.message : '需求录入失败')
    } finally {
      setDemandLoading(false)
    }
  }

  // F-E1: Confirm a pending promise
  async function handleConfirm(todoId: string) {
    try {
      setConfirmLoading(todoId)
      const desc = editingId === todoId ? editDesc : undefined
      await confirmTodo(todoId, { confirmation_status: 'confirmed', description: desc })
      setPendingConfirmations(prev => prev.filter(c => c.todo_id !== todoId))
      setEditingId(null)
    } catch (err) {
      console.error('确认失败:', err)
    } finally {
      setConfirmLoading(null)
    }
  }

  // F-E1: Reject a pending promise
  async function handleReject(todoId: string) {
    try {
      setConfirmLoading(todoId)
      await confirmTodo(todoId, { confirmation_status: 'rejected' })
      setPendingConfirmations(prev => prev.filter(c => c.todo_id !== todoId))
      setEditingId(null)
    } catch (err) {
      console.error('拒绝失败:', err)
    } finally {
      setConfirmLoading(null)
    }
  }

  function startEdit(item: ConfirmationItem) {
    setEditingId(item.todo_id)
    setEditDesc(item.description || '')
  }

  function getPipelineStatusText(): string {
    if (!eventDetail) return '已提交，等待处理...'
    switch (eventDetail.status) {
      case 'completed': return '处理完成'
      case 'failed': return '处理失败'
      case 'processing': return '正在分析中...'
      case 'pending': return '排队处理中...'
      case 'awaiting_retry': return 'AI 处理受限，请选择操作'
      case 'degraded_completed': return '已简化处理完成'
      default: return `状态: ${eventDetail.status}`
    }
  }

  function getPipelineStatusIcon(): string {
    if (!eventDetail) return '...'
    switch (eventDetail.status) {
      case 'completed': return '√'
      case 'failed': return '×'
      case 'processing': return '...'
      case 'awaiting_retry': return '!'
      case 'degraded_completed': return '!'
      default: return '...'
    }
  }

  return (
    <View className='page-input'>
      <View className='header'>
        <View className='header-back' onClick={() => Taro.navigateBack({ delta: 1 })}>
          <Text className='back-arrow'>&lt;</Text>
        </View>
        <Text className='header-title'>{isRecordMode ? `录入: ${scheduledTopic}` : '事件录入'}</Text>
      </View>

      {!result ? (
        <View className='content'>
          {/* Input Tab: Event / Demand */}
          <View className='input-tab-toggle'>
            <View
              className={`input-tab ${inputTab === 'event' ? 'active' : ''}`}
              onClick={() => setInputTab('event')}
            >
              <Text>事件录入</Text>
            </View>
            <View
              className={`input-tab ${inputTab === 'demand' ? 'active' : ''}`}
              onClick={() => setInputTab('demand')}
            >
              <Text>需求</Text>
            </View>
          </View>

          {inputTab === 'demand' ? (
            /* Demand Input Mode */
            <View className='form-section'>
              <Text className='section-label'>需求内容</Text>
              <Textarea
                className='text-input'
                value={demandText}
                onInput={e => setDemandText(e.detail.value)}
                placeholder='输入一句话需求，如：我需要找一个靠谱的装修团队、想了解融资渠道...'
                maxlength={2000}
                autoFocus
              />
              <Text className='char-count'>{demandText.length}/2000</Text>
              {error && (
                <View className='error-msg'>
                  <Text>× {error}</Text>
                </View>
              )}
              <Button
                className='submit-btn'
                onClick={handleDemandSubmit}
                loading={demandLoading}
                disabled={demandLoading || !demandText.trim()}
              >
                {demandLoading ? '提交中...' : '提交需求'}
              </Button>
              {demandResult && (
                <View className='demand-result-card'>
                  <Text className='demand-result-title'>需求已录入</Text>
                  <View className='demand-result-row'>
                    <Text className='demand-result-label'>标签</Text>
                    <Text className='demand-result-value'>{demandResult.tag}</Text>
                  </View>
                  <View className='demand-result-row'>
                    <Text className='demand-result-label'>详情</Text>
                    <Text className='demand-result-value'>{demandResult.detail}</Text>
                  </View>
                  {demandResult.related_entity_id && (
                    <View className='demand-result-row'>
                      <Text className='demand-result-label'>关联人脉</Text>
                      <Text className='demand-result-value'>已关联</Text>
                    </View>
                  )}
                  <Button
                    className='reset-btn'
                    onClick={() => setDemandResult(null)}
                    style={{ marginTop: '16px' }}
                  >
                    继续录入
                  </Button>
                </View>
              )}
              <View className='tips'>
                <Text className='tips-title'>需求录入提示</Text>
                <Text className='tips-item'>· 一句话描述你的需求，系统自动提取标签</Text>
                <Text className='tips-item'>· 提到人名会自动关联到已有联系人</Text>
                <Text className='tips-item'>· 需求会记录在人脉档案中，方便供需匹配</Text>
              </View>
            </View>
          ) : (
          <View>
            {/* ── 顶部: 事件类型选择 ── */}
            <View className='form-section'>
              <Text className='section-label'>事件类型</Text>
              <View className='event-type-grid'>
                {EVENT_TYPES.map((t, idx) => (
                  <View
                    key={t.value}
                    className={`event-type-btn ${eventType === idx ? 'active' : ''}`}
                    onClick={() => setEventType(idx)}
                  >
                    <Text>{t.label}</Text>
                  </View>
                ))}
              </View>
            </View>

            {/* Input Mode Toggle */}
            <View className='mode-toggle'>
              <View
                className={`mode-btn ${inputMode === 'text' ? 'active' : ''}`}
                onClick={() => setInputMode('text')}
              >
                <Text>文本输入</Text>
              </View>
              <View
                className={`mode-btn ${inputMode === 'file' ? 'active' : ''}`}
                onClick={() => setInputMode('file')}
              >
                <Text>文件上传</Text>
              </View>
            </View>

            {/* ── 中部: 大文本框 ── */}
            {inputMode === 'text' && (
              <View className='form-section'>
                <Text className='section-label'>内容</Text>
                <Textarea
                  className='text-input'
                  value={rawText}
                  onInput={e => setRawText(e.detail.value)}
                  placeholder='记录一次重要交流...'
                  maxlength={50000}
                  autoFocus
                />
                <Text className='char-count'>{rawText.length}/50000</Text>
              </View>
            )}

            {/* File Upload Mode */}
            {inputMode === 'file' && (
              <View className='form-section'>
                <Text className='section-label'>上传文件</Text>
                <input
                  ref={fileInputRef}
                  type='file'
                  accept='.txt,.md'
                  style={{ display: 'none' }}
                  onChange={handleFileSelected}
                />
                <View className='file-upload-area' onClick={handleFileUpload}>
                  {selectedFile ? (
                    <View className='file-selected'>
                      <Text className='file-icon'>文</Text>
                      <Text className='file-name'>{selectedFile}</Text>
                    </View>
                  ) : (
                    <View className='file-hint'>
                      <Text className='file-hint-icon'>文</Text>
                      <Text className='file-hint-text'>点击选择文件或拖拽到此处</Text>
                      <Text className='file-hint-ext'>支持 .txt、.md 格式</Text>
                    </View>
                  )}
                </View>
              </View>
            )}

            {/* ── 底部: 参与者 + 时间 ── */}
            {inputMode === 'text' && (
              <View className='form-section bottom-section'>
                <View className='bottom-row'>
                  <View className='bottom-field'>
                    <Text className='field-label'>参与者 (可选)</Text>
                    <Input
                      className='field-input'
                      value={participants}
                      onInput={e => setParticipants(e.detail.value)}
                      placeholder='如：张总、李总'
                    />
                  </View>
                  <View className='bottom-field'>
                    <Text className='field-label'>时间</Text>
                    <View style={{ display: 'flex', gap: '8px' }}>
                      <Picker
                        mode='date'
                        value={eventTime.slice(0, 10)}
                        onChange={e => setEventTime(e.detail.value + eventTime.slice(10))}
                      >
                        <View className='picker-value'>
                          <Text>{eventTime.slice(0, 10)}</Text>
                          <Text className='picker-arrow'>▼</Text>
                        </View>
                      </Picker>
                      <Picker
                        mode='time'
                        value={eventTime.slice(11, 16)}
                        onChange={e => setEventTime(eventTime.slice(0, 11) + e.detail.value)}
                      >
                        <View className='picker-value'>
                          <Text>{eventTime.slice(11, 16)}</Text>
                          <Text className='picker-arrow'>▼</Text>
                        </View>
                      </Picker>
                    </View>
                  </View>
                </View>
              </View>
            )}

            {/* Error */}
            {error && (
              <View className='error-msg'>
                <Text>× {error}</Text>
              </View>
            )}

            {/* ── 提交按钮: 记录并解析 ── */}
            {inputMode === 'text' && (
              <Button
                className='submit-btn'
                onClick={handleSubmit}
                loading={loading}
                disabled={loading || !rawText.trim()}
              >
                {loading ? '提交中...' : '记录并解析'}
              </Button>
            )}

            {/* Upload progress indicator (file mode) */}
            {inputMode === 'file' && loading && (
              <View className='upload-loading'>
                <Text className='upload-loading-text'>文件上传中...</Text>
              </View>
            )}

            {/* Tips */}
            <View className='tips'>
              <Text className='tips-title'>录入提示</Text>
              <Text className='tips-item'>· 支持自然语言输入，系统会自动提取人名、待办、承诺</Text>
              <Text className='tips-item'>· 提及时间会自动识别，如"明天"、"下周五"</Text>
              <Text className='tips-item'>· 承诺类内容会自动标记，如"我答应..."、"他说会..."</Text>
              <Text className='tips-item'>· 文件上传支持 .txt 和 .md 格式</Text>
            </View>
          </View>
          )}
        </View>
      ) : (
        /* ── 解析结果 + 纠偏视图 ── */
        <View className='content'>
          <View className='result-card'>
            <View className='result-header'>
              <Text className='result-icon'>{getPipelineStatusIcon()}</Text>
              <View className='result-info'>
                <Text className='result-title'>{getPipelineStatusText()}</Text>
                <Text className='result-event-type'>
                  {EVENT_TYPES.find(t => t.value === result.event_type)?.label}
                </Text>
              </View>
            </View>

            {/* Polling indicator */}
            {polling && (
              <View className='polling-indicator'>
                <Text className='polling-text'>正在处理，请稍候...</Text>
              </View>
            )}

            {/* P2: Polling timeout notice */}
            {pollTimeout && !polling && (
              <View className='polling-indicator'>
                <Text className='polling-text'>处理时间较长，请稍后在列表中查看结果</Text>
              </View>
            )}

            {/* LLM degradation confirmation */}
            {eventDetail?.status === 'awaiting_retry' && (
              <View className='degradation-card'>
                <Text className='degradation-title'>AI 处理受限</Text>
                <Text className='degradation-desc'>
                  AI 服务暂时不可用，事件未能完整处理。您可以选择：
                </Text>
                <View className='degradation-actions'>
                  <Button
                    className='degradation-btn retry-btn'
                    onClick={async () => {
                      if (!result) return
                      try {
                        await retryEvent(result.id)
                        setEventDetail(null)
                        setPolling(true)
                      } catch (e) {
                        Taro.showToast({ title: '重试失败', icon: 'error' })
                      }
                    }}
                  >重新处理</Button>
                  <Button
                    className='degradation-btn accept-btn'
                    onClick={async () => {
                      if (!result) return
                      try {
                        await acceptDegradedEvent(result.id)
                        setEventDetail({ ...eventDetail, status: 'degraded_completed' })
                      } catch (e) {
                        Taro.showToast({ title: '操作失败', icon: 'error' })
                      }
                    }}
                  >接受简化结果</Button>
                </View>
              </View>
            )}

            {/* Initial submitted state */}
            {!eventDetail && !polling && (
              <View className='extraction-results'>
                <View className='result-row'>
                  <Text className='result-label'>事件标题</Text>
                  <Text className='result-value'>{result.title}</Text>
                </View>
                <View className='result-row'>
                  <Text className='result-label'>状态</Text>
                  <Text className='result-value'>{result.pipeline_status}</Text>
                </View>
              </View>
            )}
          </View>

          {/* ── 4区解析结果展示 + 纠偏 (extracted to CorrectionPanel) ── */}
          {eventDetail?.status === 'completed' && parsedDetail && !corrected && (
            <CorrectionPanel
              eventId={result.id}
              parsedDetail={parsedDetail}
              onCorrected={() => setCorrected(true)}
              onError={setError}
            />
          )}

          {/* 纠偏完成提示 */}
          {corrected && (
            <View className='corrected-banner'>
              <Text className='corrected-text'>√ 纠偏已保存，解析结果已更新</Text>
            </View>
          )}

          {/* F-E1: Pending Confirmation Cards (legacy, for non-completed or fallback) */}
          {pendingConfirmations.length > 0 && !parsedDetail && (
            <View className='confirmation-section'>
              <Text className='confirmation-title'>
                AI识别到 {pendingConfirmations.length} 条承诺待确认
              </Text>
              {pendingConfirmations.map(item => (
                <View key={item.todo_id} className='confirmation-card'>
                  <View className='conf-card-header'>
                    <View className={`conf-action-badge ${item.action_type === 'their_promise' ? 'their' : ''}`}>
                      <Text>{item.action_type === 'their_promise' ? '对方承诺' : '我的承诺'}</Text>
                    </View>
                    {item.confirmation_status === 'auto_set' && (
                      <Text className='conf-auto-tag'>系统识别</Text>
                    )}
                  </View>
                  <Text className='conf-desc'>{item.title}{item.description ? ': ' + item.description : ''}</Text>
                  {item.evidence_quote && (
                    <Text className='conf-evidence'>"{item.evidence_quote}"</Text>
                  )}
                  {item.due_date && (
                    <Text className='conf-due'>截止: {new Date(item.due_date).toLocaleDateString('zh-CN')}</Text>
                  )}
                  {editingId === item.todo_id ? (
                    <View className='conf-edit-area'>
                      <Input
                        className='conf-edit-input'
                        value={editDesc}
                        onInput={e => setEditDesc(e.detail.value)}
                        placeholder='修改描述内容'
                      />
                    </View>
                  ) : null}
                  <View className='conf-actions'>
                    <Button
                      className='conf-btn conf-btn-confirm'
                      size='mini'
                      loading={confirmLoading === item.todo_id}
                      onClick={() => handleConfirm(item.todo_id)}
                    >
                      确认
                    </Button>
                    <Button
                      className='conf-btn conf-btn-edit'
                      size='mini'
                      onClick={() => startEdit(item)}
                    >
                      修改
                    </Button>
                    <Button
                      className='conf-btn conf-btn-reject'
                      size='mini'
                      loading={confirmLoading === item.todo_id}
                      onClick={() => handleReject(item.todo_id)}
                    >
                      拒绝
                    </Button>
                  </View>
                </View>
              ))}
            </View>
          )}

          {/* Action Buttons */}
          <View className='result-actions'>
            <Button
              className='reset-btn'
              onClick={handleReset}
            >
              继续录入
            </Button>
            {eventDetail?.status === 'completed' && (
              <Button
                className='view-todos-btn'
                onClick={() => Taro.switchTab({ url: '/pages/todos/index' })}
              >
                查看待办
              </Button>
            )}
            {eventDetail?.status === 'completed' && (
              <Button
                className='view-events-btn'
                onClick={() => Taro.switchTab({ url: '/pages/events/index' })}
              >
                查看事件
              </Button>
            )}
          </View>
        </View>
      )}
    </View>
  )
}
