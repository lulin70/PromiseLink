import { useState, useEffect } from 'react'
import { View, Text, Input, Textarea, Button, Picker, RadioGroup, Radio } from '@tarojs/components'
import Taro from '@tarojs/taro'
import {
  correctEvent, getEntities,
  EventDetailResponse,
  EntityResponse,
  EventAssociationRef,
  CorrectedEntityItem, CorrectedTodoItem, CorrectedPromiseItem, CorrectedAssociationItem,
} from '../../services/api'
import './index.scss'

// I7: CorrectionPanel extracted from input/index.tsx to reduce file size.
// This component owns all correction state and UI for the 4-zone
// (people / relation / todo / promise) correction flow.

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

// P0 §5.18 v5.6: relationship correction type options
const RELATIONSHIP_TYPES = [
  { value: 'ex_colleague', label: '前同事' },
  { value: 'alumni', label: '校友' },
  { value: 'partner', label: '合作伙伴' },
  { value: 'investor', label: '投资关系' },
  { value: 'customer', label: '客户' },
  { value: 'supplier', label: '供应商' },
  { value: 'friend', label: '朋友' },
  { value: 'same_city', label: '同城' },
  { value: 'custom', label: '自定义' },
]

const RELATIONSHIP_TYPE_LABELS: Record<string, string> = {
  ex_colleague: '前同事',
  alumni: '校友',
  partner: '合作伙伴',
  investor: '投资关系',
  customer: '客户',
  supplier: '供应商',
  friend: '朋友',
  same_city: '同城',
}

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

interface CorrectionPanelProps {
  eventId: string
  parsedDetail: EventDetailResponse
  onCorrected: () => void
  onError: (msg: string) => void
}

export default function CorrectionPanel({
  eventId,
  parsedDetail,
  onCorrected,
  onError,
}: CorrectionPanelProps) {
  const [entityCorrections, setEntityCorrections] = useState<Record<string, EntityCorrectionState>>({})
  const [entityCandidates, setEntityCandidates] = useState<Record<string, EntityResponse[]>>({})
  const [candidateLoading, setCandidateLoading] = useState<string | null>(null)
  const [todoEdits, setTodoEdits] = useState<Record<string, TodoEditState>>({})
  const [newTodos, setNewTodos] = useState<TodoEditState[]>([])
  const [promiseCorrections, setPromiseCorrections] = useState<Record<string, PromiseCorrectionState>>({})
  const [correcting, setCorrecting] = useState(false)
  const [activeZone, setActiveZone] = useState<'people' | 'relation' | 'todo' | 'promise'>('people')

  // P0 §5.18 v5.6: promise add (手动补录承诺)
  const [showAddPromise, setShowAddPromise] = useState(false)
  const [newPromiseContent, setNewPromiseContent] = useState('')
  const [newPromiseType, setNewPromiseType] = useState<'my_promise' | 'their_promise'>('my_promise')
  const [newPromiseDue, setNewPromiseDue] = useState('')
  const [newPromises, setNewPromises] = useState<CorrectedPromiseItem[]>([])

  // P0 §5.18 v5.6: relationship correction (关系纠偏)
  const [correctedAssociations, setCorrectedAssociations] = useState<CorrectedAssociationItem[]>([])
  const [editingAssocIndex, setEditingAssocIndex] = useState<number | null>(null)
  const [pendingRelType, setPendingRelType] = useState<string | null>(null)
  const [customRelType, setCustomRelType] = useState('')

  // Initialize correction state from parsed detail (called once on mount)
  useEffect(() => {
    const entCorr: Record<string, EntityCorrectionState> = {}
    for (const ent of parsedDetail.related_entities || []) {
      entCorr[ent.id] = { action: 'pending' }
    }
    setEntityCorrections(entCorr)

    const todoEditsInit: Record<string, TodoEditState> = {}
    for (const todo of parsedDetail.related_todos || []) {
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

    const promCorr: Record<string, PromiseCorrectionState> = {}
    for (const todo of parsedDetail.related_todos || []) {
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
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // ── Entity correction handlers ──
  async function searchEntityCandidates(entity: { id: string; name: string }) {
    setCandidateLoading(entity.id)
    try {
      const res = await getEntities(entity.name, 20, 0)
      const candidates = (res.items || []).filter(e => e.id !== entity.id)
      setEntityCandidates(prev => ({ ...prev, [entity.id]: candidates }))
    } catch {
      setEntityCandidates(prev => ({ ...prev, [entity.id]: [] }))
    } finally {
      setCandidateLoading(null)
    }
  }

  function setEntityAction(entityId: string, action: EntityCorrectionState['action']) {
    setEntityCorrections(prev => ({ ...prev, [entityId]: { ...prev[entityId], action } }))
  }

  function setEntitySelected(entityId: string, selectedId: string) {
    setEntityCorrections(prev => ({ ...prev, [entityId]: { ...prev[entityId], selected_entity_id: selectedId } }))
  }

  function setEntityNewField(entityId: string, field: 'new_name' | 'new_company' | 'new_title', value: string) {
    setEntityCorrections(prev => ({ ...prev, [entityId]: { ...prev[entityId], [field]: value } }))
  }

  // ── Todo correction handlers ──
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

  // ── Promise correction handlers ──
  function setPromiseAction(promiseId: string, action: PromiseCorrectionState['action']) {
    setPromiseCorrections(prev => ({ ...prev, [promiseId]: { ...prev[promiseId], action } }))
  }

  function setPromiseField(promiseId: string, field: 'content' | 'due_date' | 'promise_type', value: string) {
    setPromiseCorrections(prev => ({
      ...prev,
      [promiseId]: { ...prev[promiseId], [field]: value, action: 'modify' },
    }))
  }

  // ── Promise add handlers (P0 §5.18 v5.6: 手动补录承诺) ──
  function handleAddPromise() {
    if (!newPromiseContent.trim()) return
    const newPromise: CorrectedPromiseItem = {
      id: null,
      content: newPromiseContent.trim(),
      promise_type: newPromiseType,
      due_date: newPromiseDue || undefined,
      action: 'add',
    }
    setNewPromises(prev => [...prev, newPromise])
    setShowAddPromise(false)
    setNewPromiseContent('')
    setNewPromiseDue('')
  }

  function removeNewPromise(index: number) {
    setNewPromises(prev => prev.filter((_, i) => i !== index))
  }

  // ── Relationship correction handlers (P0 §5.18 v5.6: 关系纠偏) ──
  function findEntityIdByName(name: string): string | undefined {
    return (parsedDetail.related_entities || []).find(e => e.name === name)?.id
  }

  function applyAssocCorrection(assoc: EventAssociationRef, relationshipType: string) {
    const sourceEntityId = findEntityIdByName(assoc.source_entity_name)
    const targetEntityId = findEntityIdByName(assoc.target_entity_name)
    if (!sourceEntityId || !targetEntityId) {
      onError('无法定位关系实体 ID')
      return
    }
    setCorrectedAssociations(prev => {
      const filtered = prev.filter(
        ca => !(ca.source_entity_id === sourceEntityId && ca.target_entity_id === targetEntityId)
      )
      return [...filtered, {
        source_entity_id: sourceEntityId,
        target_entity_id: targetEntityId,
        relationship_type: relationshipType,
        action: 'modify' as const,
      }]
    })
  }

  // ── Submit corrections ──
  async function handleCorrectSubmit() {
    try {
      setCorrecting(true)
      onError('')

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
      // P0 §5.18 v5.6: manually added promises
      for (const np of newPromises) {
        corrected_promises.push(np)
      }

      const correctResult = await correctEvent(eventId, {
        corrected_entities,
        corrected_todos,
        corrected_promises,
        corrected_associations: correctedAssociations,
      })
      Taro.showToast({ title: '纠偏已保存', icon: 'success' })
      // I3: navigate to event detail page, delay to ensure toast is visible
      setTimeout(() => {
        Taro.navigateTo({ url: `/pages/events/detail?id=${correctResult.event_id}` })
      }, 1500)
      onCorrected()
    } catch (err) {
      onError(err instanceof Error ? err.message : '纠偏提交失败')
    } finally {
      setCorrecting(false)
    }
  }

  const entities = parsedDetail.related_entities || []
  const associations = parsedDetail.related_associations || []
  const todos = (parsedDetail.related_todos || []).filter(t => t.action_type !== 'my_promise' && t.action_type !== 'their_promise')
  const promises = (parsedDetail.related_todos || []).filter(t => t.action_type === 'my_promise' || t.action_type === 'their_promise')

  return (
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
                          {corr.selected_entity_id === c.id && <Text className='check-mark'>√</Text>}
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
          {associations.map((a, idx) => {
            const sourceId = findEntityIdByName(a.source_entity_name)
            const targetId = findEntityIdByName(a.target_entity_name)
            const correction = correctedAssociations.find(
              ca => ca.source_entity_id === sourceId && ca.target_entity_id === targetId
            )
            const displayType = correction?.relationship_type || a.association_type
            const displayLabel = RELATIONSHIP_TYPE_LABELS[displayType] || ASSOC_TYPE_LABELS[displayType] || displayType
            const isEditing = editingAssocIndex === idx
            return (
              <View key={a.id} className='assoc-card'>
                <View className='assoc-flow'>
                  <Text className='assoc-name'>{a.source_entity_name}</Text>
                  <Text className='assoc-arrow'>→</Text>
                  <Text className='assoc-type'>{displayLabel}</Text>
                  <Text className='assoc-arrow'>→</Text>
                  <Text className='assoc-name'>{a.target_entity_name}</Text>
                </View>
                <Text className='assoc-strength'>强度: {Math.round(a.strength * 100)}%</Text>
                {correction && <Text className='status-badge status-new' style={{ marginTop: '4px', display: 'inline-block' }}>已修改</Text>}
                {!isEditing && (
                  <View className='todo-actions' style={{ marginTop: '8px' }}>
                    <Button className='corr-btn corr-btn-secondary' size='mini'
                      onClick={() => { setEditingAssocIndex(idx); setPendingRelType(null); setCustomRelType('') }}
                    >改</Button>
                  </View>
                )}
                {isEditing && (
                  <View className='new-entity-form' style={{ background: '#F5F0EB', padding: '12px', borderRadius: '8px', marginTop: '8px' }}>
                    <Picker mode='selector' range={RELATIONSHIP_TYPES.map(r => r.label)}
                      onChange={e => {
                        const selected = RELATIONSHIP_TYPES[Number(e.detail.value)]
                        if (selected.value === 'custom') {
                          setPendingRelType('custom')
                        } else {
                          applyAssocCorrection(a, selected.value)
                          setEditingAssocIndex(null)
                          setPendingRelType(null)
                        }
                      }}
                    >
                      <View className='picker-value'><Text>选择关系类型</Text><Text className='picker-arrow'>▼</Text></View>
                    </Picker>
                    {pendingRelType === 'custom' && (
                      <View style={{ marginTop: '8px' }}>
                        <Input className='form-input' placeholder='自定义关系类型' value={customRelType}
                          onInput={e => setCustomRelType(e.detail.value)}
                        />
                        <View className='todo-actions' style={{ marginTop: '8px' }}>
                          <Button className='corr-btn corr-btn-primary' size='mini'
                            onClick={() => {
                              if (customRelType.trim()) {
                                applyAssocCorrection(a, customRelType.trim())
                                setEditingAssocIndex(null)
                                setPendingRelType(null)
                                setCustomRelType('')
                              }
                            }}
                          >保存</Button>
                        </View>
                      </View>
                    )}
                    <View className='todo-actions' style={{ marginTop: '8px' }}>
                      <Button className='corr-btn corr-btn-link' size='mini'
                        onClick={() => { setEditingAssocIndex(null); setPendingRelType(null); setCustomRelType('') }}
                      >取消</Button>
                    </View>
                  </View>
                )}
              </View>
            )
          })}
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

          {/* P0 §5.18 v5.6: 手动补录的承诺 */}
          {newPromises.map((np, idx) => (
            <View key={`new-promise-${idx}`} className='promise-card'>
              <View className='promise-header'>
                <View className={`promise-badge ${np.promise_type === 'their_promise' ? 'their' : 'mine'}`}>
                  <Text>{np.promise_type === 'their_promise' ? '对方承诺' : '我的承诺'}</Text>
                </View>
                <Text className='status-badge status-new'>新增</Text>
              </View>
              <Text className='promise-title'>{np.content}</Text>
              {np.due_date && <Text className='assoc-strength'>截止: {np.due_date}</Text>}
              <View className='promise-actions'>
                <Button className='corr-btn corr-btn-ignore' size='mini'
                  onClick={() => removeNewPromise(idx)}
                >移除</Button>
              </View>
            </View>
          ))}

          {/* P0 §5.18 v5.6: + 添加承诺 */}
          {showAddPromise && (
            <View className='new-entity-form' style={{ background: '#F5F0EB', padding: '12px', borderRadius: '8px', marginTop: '12px' }}>
              <Textarea
                className='form-input'
                placeholder='输入承诺内容，如：我答应李总介绍投资方'
                value={newPromiseContent}
                onInput={e => setNewPromiseContent(e.detail.value)}
                maxlength={500}
                style={{ width: '100%', minHeight: '60px', boxSizing: 'border-box' }}
              />
              <View className='todo-fields' style={{ marginTop: '8px' }}>
                <View className='todo-field'>
                  <Text className='field-label'>方向</Text>
                  <RadioGroup onChange={e => setNewPromiseType(e.detail.value as 'my_promise' | 'their_promise')}>
                    <Radio value='my_promise' checked={newPromiseType === 'my_promise'} color='#7B9EA8'>我答应</Radio>
                    <Radio value='their_promise' checked={newPromiseType === 'their_promise'} color='#7B9EA8'>对方答应</Radio>
                  </RadioGroup>
                </View>
                <View className='todo-field'>
                  <Text className='field-label'>截止时间</Text>
                  <Picker mode='date' value={newPromiseDue}
                    onChange={e => setNewPromiseDue(e.detail.value)}
                  >
                    <View className='picker-value'><Text>{newPromiseDue || '选择日期'}</Text><Text className='picker-arrow'>▼</Text></View>
                  </Picker>
                </View>
              </View>
              <View className='todo-actions' style={{ marginTop: '8px' }}>
                <Button className='corr-btn corr-btn-primary' size='mini'
                  onClick={handleAddPromise}
                >保存</Button>
                <Button className='corr-btn corr-btn-link' size='mini'
                  onClick={() => { setShowAddPromise(false); setNewPromiseContent(''); setNewPromiseDue('') }}
                >取消</Button>
              </View>
            </View>
          )}
          <Button className='add-btn' onClick={() => setShowAddPromise(true)}>+ 添加承诺</Button>
        </View>
      )}

      {/* 确认并保存 */}
      <Button
        className='correct-submit-btn'
        onClick={handleCorrectSubmit}
        loading={correcting}
        disabled={correcting}
      >
        {correcting ? '保存中...' : '确认并保存'}
      </Button>
    </View>
  )
}
