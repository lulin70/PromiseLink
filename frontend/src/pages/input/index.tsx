import { useState, useEffect, useCallback } from 'react'
import { View, Text, Textarea, Button, Picker, Input } from '@tarojs/components'
import {
  createEvent, uploadEventFile, getEventDetail, getPendingConfirmations,
  confirmTodo, retryEvent, acceptDegradedEvent, recordScheduledEvent,
  getScheduledEventDetail, createDemand, getEntities, correctEvent,
  EventCreateResponse, ConfirmationItem, EventDetailResponse,
  EventEntityDetail, EventAssociationRef, EventTodoRef,
  CorrectedEntityItem, CorrectedTodoItem, CorrectedPromiseItem,
  EntityResponse,
} from '../../services/api'
import { isLoggedIn } from '../../services/auth'
import Taro, { useRouter } from '@tarojs/taro'
import './index.scss'

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

const ASSOC_TYPE_LABELS: Record<string, string> = {
  alumni: '校友',
  ex_colleague: '前同事',
  same_city: '同城',
  competitor: '竞争',
  tech_overlap: '技术重叠',
  deal_link: '交易关联',
  risk_link: '风险关联',
  supply_chain: '供应链',
  co_occurrence: '共同出现',
  topic_overlap: '话题重叠',
  supply_demand: '供需匹配',
  industry_chain: '产业链',
}

interface EventDetail {
  id: string
  status: string
  pipeline?: string | null
  processed_at?: string | null
}

// ── 纠偏状态类型 ──
interface EntityCorrectionState {
  action: 'select_existing' | 'create_new' | 'ignore' | 'pending'
  selected_entity_id?: string
  new_name?: string
  new_company?: string
  new_title?: string
}

interface TodoEditState {
  title: string
  description?: string
  due_date?: string
  priority: number
  related_entity_id?: string
  deleted?: boolean
  edited?: boolean
}

interface PromiseCorrectionState {
  action: 'confirm' | 'ignore' | 'modify' | 'pending'
  content?: string
  due_date?: string
  promise_type?: 'my_promise' | 'their_promise'
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

  // ── 解析结果 + 纠偏状态 ──
  const [parsedDetail, setParsedDetail] = useState<EventDetailResponse | null>(null)
  const [entityCorrections, setEntityCorrections] = useState<Record<string, EntityCorrectionState>>({})
  const [entityCandidates, setEntityCandidates] = useState<Record<string, EntityResponse[]>>({})
  const [candidateLoading, setCandidateLoading] = useState<string | null>(null)
  const [todoEdits, setTodoEdits] = useState<Record<string, TodoEditState>>({})
  const [newTodos, setNewTodos] = useState<TodoEditState[]>([])
  const [promiseCorrections, setPromiseCorrections] = useState<Record<string, PromiseCorrectionState>>({})
  const [correcting, setCorrecting] = useState(false)
  const [corrected, setCorrected] = useState(false)
  const [activeZone, setActiveZone] = useState<'people' | 'relation' | 'todo' | 'promise'>('people')

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

  // Poll for pipeline completion
  const pollEventDetail = useCallback(async (eventId: string) => {
    try {
      const detail = await getEventDetail(eventId)
      setEventDetail({
        id: detail.id,
        status: detail.status,
        pipeline: (detail as Record<string, unknown>).pipeline as string | null ?? null,
        processed_at: (detail as Record<string, unknown>).processed_at as string | null ?? null,
      })

      if (detail.status === 'completed' || detail.status === 'failed' || detail.status === 'awaiting_retry') {
        setPolling(false)
        if (detail.status === 'completed') {
          // 加载完整解析结果（含实体/关联/待办详情）
          setParsedDetail(detail)
          // 初始化纠偏状态
          initCorrections(detail)
          try {
            const confirmations = await getPendingConfirmations(eventId)
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

  useEffect(() => {
    if (!polling || !result) return

    const timer = setInterval(async () => {
      const done = await pollEventDetail(result.id)
      if (done) {
        clearInterval(timer)
      }
    }, 2000)

    return () => clearInterval(timer)
  }, [polling, result, pollEventDetail])

  // 初始化纠偏状态
  function initCorrections(detail: EventDetailResponse) {
    const entCorr: Record<string, EntityCorrectionState> = {}
    for (const ent of detail.related_entities || []) {
      entCorr[ent.id] = { action: 'pending' }
    }
    setEntityCorrections(entCorr)

    const todoEditsInit: Record<string, TodoEditState> = {}
    for (const todo of detail.related_todos || []) {
      if (todo.action_type !== 'my_promise' && todo.action_type !== 'their_promise') {
        todoEditsInit[todo.id] = {
          title: todo.title,
          description: todo.description,
          due_date: todo.due_date,
          priority: todo.priority || 3,
          related_entity_id: todo.related_entity_id,
        }
      }
    }
    setTodoEdits(todoEditsInit)
    setNewTodos([])

    const promCorr: Record<string, PromiseCorrectionState> = {}
    for (const todo of detail.related_todos || []) {
      if (todo.action_type === 'my_promise' || todo.action_type === 'their_promise') {
        promCorr[todo.id] = {
          action: 'pending',
          content: todo.description,
          due_date: todo.due_date,
          promise_type: todo.action_type as 'my_promise' | 'their_promise',
        }
      }
    }
    setPromiseCorrections(promCorr)
    setCorrected(false)
  }

  // 搜索人脉候选
  async function searchEntityCandidates(entity: EventEntityDetail) {
    setCandidateLoading(entity.id)
    try {
      const res = await getEntities(entity.name, 20, 0)
      // 过滤掉当前提取的实体本身
      const candidates = (res.items || []).filter(e => e.id !== entity.id)
      setEntityCandidates(prev => ({ ...prev, [entity.id]: candidates }))
    } catch {
      setEntityCandidates(prev => ({ ...prev, [entity.id]: [] }))
    } finally {
      setCandidateLoading(null)
    }
  }

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
      setEntityCorrections({})
      setEntityCandidates({})
      setTodoEdits({})
      setNewTodos([])
      setPromiseCorrections({})
      setCorrected(false)

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

  async function handleFileUpload() {
    try {
      const chooseRes = await Taro.chooseMessageFile({
        count: 1,
        type: 'file',
        extension: ['.txt', '.md'],
      })
      const file = chooseRes.tempFiles[0]
      setSelectedFile(file.name)

      setLoading(true)
      setError('')
      setResult(null)
      setEventDetail(null)

      const res = await uploadEventFile(file as unknown as File, EVENT_TYPES[eventType].value)
      setResult(res)
      setSelectedFile(null)

      if (res.pipeline_status === 'pending' || res.status === 'pending') {
        setPolling(true)
        setTimeout(() => pollEventDetail(res.id), 1500)
      }
    } catch (err) {
      setSelectedFile(null)
      if (err instanceof Error && err.message.includes('cancel')) return
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
    setEntityCorrections({})
    setEntityCandidates({})
    setTodoEdits({})
    setNewTodos([])
    setPromiseCorrections({})
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

  // ── 纠偏: 人脉 ──
  function setEntityAction(entityId: string, action: EntityCorrectionState['action']) {
    setEntityCorrections(prev => ({ ...prev, [entityId]: { ...prev[entityId], action } }))
  }

  function setEntitySelected(entityId: string, selectedId: string) {
    setEntityCorrections(prev => ({ ...prev, [entityId]: { ...prev[entityId], selected_entity_id: selectedId } }))
  }

  function setEntityNewField(entityId: string, field: 'new_name' | 'new_company' | 'new_title', value: string) {
    setEntityCorrections(prev => ({ ...prev, [entityId]: { ...prev[entityId], [field]: value } }))
  }

  // ── 纠偏: 待办 ──
  function updateTodoEdit(todoId: string, field: keyof TodoEditState, value: string | number | boolean) {
    setTodoEdits(prev => ({
      ...prev,
      [todoId]: { ...prev[todoId], [field]: value, edited: true },
    }))
  }

  function deleteTodo(todoId: string) {
    setTodoEdits(prev => ({ ...prev, [todoId]: { ...prev[todoId], deleted: true } }))
  }

  function addNewTodo() {
    setNewTodos(prev => [...prev, { title: '', priority: 3, edited: true }])
  }

  function updateNewTodo(index: number, field: keyof TodoEditState, value: string | number) {
    setNewTodos(prev => prev.map((t, i) => i === index ? { ...t, [field]: value } : t))
  }

  function removeNewTodo(index: number) {
    setNewTodos(prev => prev.filter((_, i) => i !== index))
  }

  // ── 纠偏: 承诺 ──
  function setPromiseAction(promiseId: string, action: PromiseCorrectionState['action']) {
    setPromiseCorrections(prev => ({ ...prev, [promiseId]: { ...prev[promiseId], action } }))
  }

  function setPromiseField(promiseId: string, field: 'content' | 'due_date' | 'promise_type', value: string) {
    setPromiseCorrections(prev => ({
      ...prev,
      [promiseId]: { ...prev[promiseId], [field]: value, action: 'modify' },
    }))
  }

  // ── 确认并保存 ──
  async function handleCorrectSubmit() {
    if (!result) return
    try {
      setCorrecting(true)
      setError('')

      const corrected_entities: CorrectedEntityItem[] = []
      for (const [entId, corr] of Object.entries(entityCorrections)) {
        if (corr.action === 'pending') continue
        corrected_entities.push({
          extracted_entity_id: entId,
          action: corr.action,
          selected_entity_id: corr.selected_entity_id,
          new_name: corr.new_name,
          new_company: corr.new_company,
          new_title: corr.new_title,
        })
      }

      const corrected_todos: CorrectedTodoItem[] = []
      for (const [todoId, edit] of Object.entries(todoEdits)) {
        if (edit.deleted) {
          corrected_todos.push({ id: todoId, title: edit.title, priority: edit.priority, action: 'delete' })
        } else if (edit.edited) {
          corrected_todos.push({
            id: todoId,
            title: edit.title,
            description: edit.description,
            due_date: edit.due_date,
            priority: edit.priority,
            related_entity_id: edit.related_entity_id,
            action: 'edit',
          })
        }
      }
      for (const nt of newTodos) {
        if (!nt.title.trim()) continue
        corrected_todos.push({
          title: nt.title,
          description: nt.description,
          due_date: nt.due_date,
          priority: nt.priority,
          related_entity_id: nt.related_entity_id,
          action: 'add',
        })
      }

      const corrected_promises: CorrectedPromiseItem[] = []
      for (const [promId, corr] of Object.entries(promiseCorrections)) {
        if (corr.action === 'pending') continue
        corrected_promises.push({
          id: promId,
          content: corr.content,
          due_date: corr.due_date,
          promise_type: corr.promise_type,
          action: corr.action,
        })
      }

      await correctEvent(result.id, { corrected_entities, corrected_todos, corrected_promises })
      setCorrected(true)
      Taro.showToast({ title: '纠偏已保存', icon: 'success' })
    } catch (err) {
      setError(err instanceof Error ? err.message : '纠偏提交失败')
    } finally {
      setCorrecting(false)
    }
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
    if (!eventDetail) return '⏳'
    switch (eventDetail.status) {
      case 'completed': return '✅'
      case 'failed': return '❌'
      case 'processing': return '🔄'
      case 'awaiting_retry': return '🔔'
      case 'degraded_completed': return '⚠️'
      default: return '⏳'
    }
  }

  const entities = parsedDetail?.related_entities || []
  const associations = parsedDetail?.related_associations || []
  const todos = (parsedDetail?.related_todos || []).filter(t => t.action_type !== 'my_promise' && t.action_type !== 'their_promise')
  const promises = (parsedDetail?.related_todos || []).filter(t => t.action_type === 'my_promise' || t.action_type === 'their_promise')

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
                  <Text>✗ {error}</Text>
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
                  maxlength={5000}
                  autoFocus
                />
                <Text className='char-count'>{rawText.length}/5000</Text>
              </View>
            )}

            {/* File Upload Mode */}
            {inputMode === 'file' && (
              <View className='form-section'>
                <Text className='section-label'>上传文件</Text>
                <View className='file-upload-area' onClick={handleFileUpload}>
                  {selectedFile ? (
                    <View className='file-selected'>
                      <Text className='file-icon'>📄</Text>
                      <Text className='file-name'>{selectedFile}</Text>
                    </View>
                  ) : (
                    <View className='file-hint'>
                      <Text className='file-hint-icon'>📁</Text>
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
                  </View>
                </View>
              </View>
            )}

            {/* Error */}
            {error && (
              <View className='error-msg'>
                <Text>✗ {error}</Text>
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
                <Text className='upload-loading-text'>📤 文件上传中...</Text>
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
                <Text className='polling-text'>🔄 正在处理，请稍候...</Text>
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

          {/* ── 4区解析结果展示 + 纠偏 ── */}
          {eventDetail?.status === 'completed' && parsedDetail && !corrected && (
            <View className='parsed-zones'>
              {/* Zone Tabs */}
              <View className='zone-tabs'>
                <View className={`zone-tab ${activeZone === 'people' ? 'active' : ''}`} onClick={() => setActiveZone('people')}>
                  <Text>人脉 ({entities.length})</Text>
                </View>
                <View className={`zone-tab ${activeZone === 'relation' ? 'active' : ''}`} onClick={() => setActiveZone('relation')}>
                  <Text>关系 ({associations.length})</Text>
                </View>
                <View className={`zone-tab ${activeZone === 'todo' ? 'active' : ''}`} onClick={() => setActiveZone('todo')}>
                  <Text>待办 ({todos.length})</Text>
                </View>
                <View className={`zone-tab ${activeZone === 'promise' ? 'active' : ''}`} onClick={() => setActiveZone('promise')}>
                  <Text>承诺 ({promises.length})</Text>
                </View>
              </View>

              {/* 人脉区 */}
              {activeZone === 'people' && (
                <View className='zone-content'>
                  <View className='zone-header'>
                    <Text className='zone-title'>人脉纠偏</Text>
                    <Text className='zone-hint'>AI 提取的人脉，可选择已有/新建/忽略</Text>
                  </View>
                  {entities.length === 0 && (
                    <View className='zone-empty'><Text>未提取到人脉</Text></View>
                  )}
                  {entities.map(ent => {
                    const corr = entityCorrections[ent.id] || { action: 'pending' }
                    const candidates = entityCandidates[ent.id] || []
                    return (
                      <View key={ent.id} className='entity-card'>
                        <View className='entity-info'>
                          <Text className='entity-name'>{ent.name}</Text>
                          {ent.company && <Text className='entity-meta'>{ent.company}</Text>}
                          {ent.title && <Text className='entity-meta'>{ent.title}</Text>}
                          <Text className='entity-confidence'>置信度: {Math.round(ent.confidence * 100)}%</Text>
                        </View>

                        {corr.action === 'pending' && (
                          <View className='entity-actions'>
                            <Button className='corr-btn corr-btn-primary' size='mini'
                              onClick={() => searchEntityCandidates(ent)}
                            >查找已有</Button>
                            <Button className='corr-btn corr-btn-secondary' size='mini'
                              onClick={() => {
                                setEntityAction(ent.id, 'create_new')
                                setEntityNewField(ent.id, 'new_name', ent.name)
                                setEntityNewField(ent.id, 'new_company', ent.company || '')
                                setEntityNewField(ent.id, 'new_title', ent.title || '')
                              }}
                            >新建/编辑</Button>
                            <Button className='corr-btn corr-btn-ignore' size='mini'
                              onClick={() => setEntityAction(ent.id, 'ignore')}
                            >忽略</Button>
                          </View>
                        )}

                        {/* 候选列表 */}
                        {corr.action === 'pending' && candidates.length > 0 && (
                          <View className='candidate-list'>
                            <Text className='candidate-title'>候选人脉 ({candidates.length})</Text>
                            {candidates.map(c => {
                              const props = c.properties as Record<string, unknown> | undefined
                              const basic = props?.basic as Record<string, unknown> | undefined
                              return (
                                <View
                                  key={c.id}
                                  className={`candidate-item ${corr.selected_entity_id === c.id ? 'selected' : ''}`}
                                  onClick={() => {
                                    setEntitySelected(ent.id, c.id)
                                    setEntityAction(ent.id, 'select_existing')
                                  }}
                                >
                                  <View className='candidate-info'>
                                    <Text className='candidate-name'>{c.name}</Text>
                                    {basic?.company && <Text className='candidate-meta'>{String(basic.company)}</Text>}
                                    {basic?.title && <Text className='candidate-meta'>{String(basic.title)}</Text>}
                                  </View>
                                  {corr.selected_entity_id === c.id && <Text className='check-mark'>✓</Text>}
                                </View>
                              )
                            })}
                          </View>
                        )}
                        {corr.action === 'pending' && candidates.length === 0 && candidateLoading === ent.id && (
                          <View className='candidate-list'><Text className='candidate-title'>搜索中...</Text></View>
                        )}

                        {/* 新建/编辑表单 */}
                        {corr.action === 'create_new' && (
                          <View className='new-entity-form'>
                            <Input className='form-input' placeholder='姓名'
                              value={corr.new_name || ''}
                              onInput={e => setEntityNewField(ent.id, 'new_name', e.detail.value)}
                            />
                            <Input className='form-input' placeholder='公司'
                              value={corr.new_company || ''}
                              onInput={e => setEntityNewField(ent.id, 'new_company', e.detail.value)}
                            />
                            <Input className='form-input' placeholder='职位'
                              value={corr.new_title || ''}
                              onInput={e => setEntityNewField(ent.id, 'new_title', e.detail.value)}
                            />
                            <Button className='corr-btn corr-btn-primary' size='mini'
                              onClick={() => setEntityAction(ent.id, 'pending')}
                            >取消</Button>
                          </View>
                        )}

                        {/* 状态标记 */}
                        {corr.action === 'select_existing' && (
                          <View className='corr-status'>
                            <Text className='status-badge status-merged'>已合并到: {candidates.find(c => c.id === corr.selected_entity_id)?.name || '已选'}</Text>
                            <Button className='corr-btn corr-btn-link' size='mini'
                              onClick={() => setEntityAction(ent.id, 'pending')}
                            >重选</Button>
                          </View>
                        )}
                        {corr.action === 'create_new' && (
                          <View className='corr-status'>
                            <Text className='status-badge status-new'>将新建/更新</Text>
                          </View>
                        )}
                        {corr.action === 'ignore' && (
                          <View className='corr-status'>
                            <Text className='status-badge status-ignored'>已忽略</Text>
                            <Button className='corr-btn corr-btn-link' size='mini'
                              onClick={() => setEntityAction(ent.id, 'pending')}
                            >恢复</Button>
                          </View>
                        )}
                      </View>
                    )
                  })}
                </View>
              )}

              {/* 关系区 */}
              {activeZone === 'relation' && (
                <View className='zone-content'>
                  <View className='zone-header'>
                    <Text className='zone-title'>关系网络</Text>
                    <Text className='zone-hint'>AI 发现的实体间关联</Text>
                  </View>
                  {associations.length === 0 && (
                    <View className='zone-empty'><Text>未发现关联关系</Text></View>
                  )}
                  {associations.map(a => (
                    <View key={a.id} className='assoc-card'>
                      <View className='assoc-flow'>
                        <Text className='assoc-name'>{a.source_entity_name}</Text>
                        <Text className='assoc-arrow'>→</Text>
                        <Text className='assoc-type'>{ASSOC_TYPE_LABELS[a.association_type] || a.association_type}</Text>
                        <Text className='assoc-arrow'>→</Text>
                        <Text className='assoc-name'>{a.target_entity_name}</Text>
                      </View>
                      <Text className='assoc-strength'>强度: {Math.round(a.strength * 100)}%</Text>
                    </View>
                  ))}
                </View>
              )}

              {/* 待办区 */}
              {activeZone === 'todo' && (
                <View className='zone-content'>
                  <View className='zone-header'>
                    <Text className='zone-title'>待办纠偏</Text>
                    <Text className='zone-hint'>可编辑/删除/新增待办</Text>
                  </View>
                  {todos.length === 0 && newTodos.length === 0 && (
                    <View className='zone-empty'><Text>未生成待办</Text></View>
                  )}
                  {todos.map(todo => {
                    const edit = todoEdits[todo.id] || { title: todo.title, priority: todo.priority || 3 }
                    if (edit.deleted) {
                      return (
                        <View key={todo.id} className='todo-card deleted'>
                          <Text className='todo-deleted-text'>已删除: {edit.title}</Text>
                          <Button className='corr-btn corr-btn-link' size='mini'
                            onClick={() => updateTodoEdit(todo.id, 'deleted', false)}
                          >恢复</Button>
                        </View>
                      )
                    }
                    return (
                      <View key={todo.id} className='todo-card'>
                        <Input className='form-input todo-title-input' value={edit.title}
                          onInput={e => updateTodoEdit(todo.id, 'title', e.detail.value)}
                        />
                        <Input className='form-input' placeholder='描述 (可选)' value={edit.description || ''}
                          onInput={e => updateTodoEdit(todo.id, 'description', e.detail.value)}
                        />
                        <View className='todo-fields'>
                          <View className='todo-field'>
                            <Text className='field-label'>优先级</Text>
                            <Picker mode='selector' range={['P1', 'P2', 'P3', 'P4', 'P5']}
                              value={edit.priority - 1}
                              onChange={e => updateTodoEdit(todo.id, 'priority', Number(e.detail.value) + 1)}
                            >
                              <View className='picker-value'><Text>P{edit.priority}</Text><Text className='picker-arrow'>▼</Text></View>
                            </Picker>
                          </View>
                          <View className='todo-field'>
                            <Text className='field-label'>截止日期</Text>
                            <Picker mode='date' value={edit.due_date ? edit.due_date.slice(0, 10) : ''}
                              onChange={e => updateTodoEdit(todo.id, 'due_date', e.detail.value)}
                            >
                              <View className='picker-value'><Text>{edit.due_date ? edit.due_date.slice(0, 10) : '无'}</Text><Text className='picker-arrow'>▼</Text></View>
                            </Picker>
                          </View>
                        </View>
                        <View className='todo-actions'>
                          <Button className='corr-btn corr-btn-ignore' size='mini'
                            onClick={() => deleteTodo(todo.id)}
                          >删除</Button>
                        </View>
                      </View>
                    )
                  })}
                  {/* 新增待办 */}
                  {newTodos.map((nt, idx) => (
                    <View key={`new-${idx}`} className='todo-card new-todo'>
                      <Input className='form-input todo-title-input' placeholder='新待办标题' value={nt.title}
                        onInput={e => updateNewTodo(idx, 'title', e.detail.value)}
                      />
                      <Input className='form-input' placeholder='描述 (可选)' value={nt.description || ''}
                        onInput={e => updateNewTodo(idx, 'description', e.detail.value)}
                      />
                      <View className='todo-fields'>
                        <View className='todo-field'>
                          <Text className='field-label'>优先级</Text>
                          <Picker mode='selector' range={['P1', 'P2', 'P3', 'P4', 'P5']}
                            value={nt.priority - 1}
                            onChange={e => updateNewTodo(idx, 'priority', Number(e.detail.value) + 1)}
                          >
                            <View className='picker-value'><Text>P{nt.priority}</Text><Text className='picker-arrow'>▼</Text></View>
                          </Picker>
                        </View>
                        <View className='todo-field'>
                          <Text className='field-label'>截止日期</Text>
                          <Picker mode='date' value={nt.due_date ? nt.due_date.slice(0, 10) : ''}
                            onChange={e => updateNewTodo(idx, 'due_date', e.detail.value)}
                          >
                            <View className='picker-value'><Text>{nt.due_date ? nt.due_date.slice(0, 10) : '无'}</Text><Text className='picker-arrow'>▼</Text></View>
                          </Picker>
                        </View>
                      </View>
                      <View className='todo-actions'>
                        <Button className='corr-btn corr-btn-ignore' size='mini'
                          onClick={() => removeNewTodo(idx)}
                        >移除</Button>
                      </View>
                    </View>
                  ))}
                  <Button className='add-btn' onClick={addNewTodo}>+ 添加待办</Button>
                </View>
              )}

              {/* 承诺区 */}
              {activeZone === 'promise' && (
                <View className='zone-content'>
                  <View className='zone-header'>
                    <Text className='zone-title'>承诺纠偏</Text>
                    <Text className='zone-hint'>确认/忽略/修改 AI 提取的承诺</Text>
                  </View>
                  {promises.length === 0 && (
                    <View className='zone-empty'><Text>未提取到承诺</Text></View>
                  )}
                  {promises.map(p => {
                    const corr = promiseCorrections[p.id] || { action: 'pending' }
                    return (
                      <View key={p.id} className='promise-card'>
                        <View className='promise-header'>
                          <View className={`promise-badge ${p.action_type === 'their_promise' ? 'their' : 'mine'}`}>
                            <Text>{p.action_type === 'their_promise' ? '对方承诺' : '我的承诺'}</Text>
                          </View>
                          {corr.action !== 'pending' && (
                            <Text className={`status-badge ${corr.action === 'confirm' ? 'status-merged' : corr.action === 'ignore' ? 'status-ignored' : 'status-new'}`}>
                              {corr.action === 'confirm' ? '已确认' : corr.action === 'ignore' ? '已忽略' : '已修改'}
                            </Text>
                          )}
                        </View>
                        <Text className='promise-title'>{p.title}</Text>
                        {p.evidence_quote && <Text className='promise-evidence'>"{p.evidence_quote}"</Text>}

                        {corr.action === 'modify' && (
                          <View className='promise-edit-form'>
                            <Input className='form-input' placeholder='承诺内容' value={corr.content || ''}
                              onInput={e => setPromiseField(p.id, 'content', e.detail.value)}
                            />
                            <View className='todo-fields'>
                              <View className='todo-field'>
                                <Text className='field-label'>类型</Text>
                                <Picker mode='selector' range={['我的承诺', '对方承诺']}
                                  value={corr.promise_type === 'their_promise' ? 1 : 0}
                                  onChange={e => setPromiseField(p.id, 'promise_type', Number(e.detail.value) === 1 ? 'their_promise' : 'my_promise')}
                                >
                                  <View className='picker-value'><Text>{corr.promise_type === 'their_promise' ? '对方承诺' : '我的承诺'}</Text><Text className='picker-arrow'>▼</Text></View>
                                </Picker>
                              </View>
                              <View className='todo-field'>
                                <Text className='field-label'>截止日期</Text>
                                <Picker mode='date' value={corr.due_date ? corr.due_date.slice(0, 10) : ''}
                                  onChange={e => setPromiseField(p.id, 'due_date', e.detail.value)}
                                >
                                  <View className='picker-value'><Text>{corr.due_date ? corr.due_date.slice(0, 10) : '无'}</Text><Text className='picker-arrow'>▼</Text></View>
                                </Picker>
                              </View>
                            </View>
                          </View>
                        )}

                        {corr.action === 'pending' && (
                          <View className='promise-actions'>
                            <Button className='corr-btn corr-btn-primary' size='mini'
                              onClick={() => setPromiseAction(p.id, 'confirm')}
                            >确认</Button>
                            <Button className='corr-btn corr-btn-secondary' size='mini'
                              onClick={() => setPromiseAction(p.id, 'modify')}
                            >修改</Button>
                            <Button className='corr-btn corr-btn-ignore' size='mini'
                              onClick={() => setPromiseAction(p.id, 'ignore')}
                            >忽略</Button>
                          </View>
                        )}
                        {corr.action !== 'pending' && (
                          <Button className='corr-btn corr-btn-link' size='mini'
                            onClick={() => setPromiseAction(p.id, 'pending')}
                          >重置</Button>
                        )}
                      </View>
                    )
                  })}
                </View>
              )}

              {/* 确认并保存 */}
              {error && (
                <View className='error-msg'><Text>✗ {error}</Text></View>
              )}
              <Button
                className='correct-submit-btn'
                onClick={handleCorrectSubmit}
                loading={correcting}
                disabled={correcting}
              >
                {correcting ? '保存中...' : '确认并保存'}
              </Button>
            </View>
          )}

          {/* 纠偏完成提示 */}
          {corrected && (
            <View className='corrected-banner'>
              <Text className='corrected-text'>✓ 纠偏已保存，解析结果已更新</Text>
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
