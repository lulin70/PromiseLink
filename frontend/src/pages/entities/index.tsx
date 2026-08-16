import { useEffect, useState } from 'react'
import { View, Text, Input, ScrollView } from '@tarojs/components'
import { getEntities, getEntityDetail, getEntityHistory, EntityResponse, EntityDetailResponse, EntityHistoryResponse, DormantContactItem, getDormantContacts, CreditScoreResponse, getCreditScore, StageInfoResponse, getStageInfo, dismissTodo, updateEntity, deleteEntity, confirmEntity, mergeEntities, getDuplicateGroups, DuplicateGroup } from '../../services/api'
import { isLoggedIn } from '../../services/auth'
import { NAV_EVENTS, navigateToEvent, navigateToEntityDetail } from '../../services/navigation'
import Taro from '@tarojs/taro'
import LoginGate from '../../components/LoginGate'
import './index.scss'

export default function EntitiesPage() {
  const [entities, setEntities] = useState<EntityResponse[]>([])
  const [search, setSearch] = useState('')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [detailVisible, setDetailVisible] = useState(false)
  const [detail, setDetail] = useState<EntityDetailResponse | null>(null)
  // Inline login
  const [showLogin, setShowLogin] = useState(false)
  // F-E3: Dormant contacts state
  const [showDormant, setShowDormant] = useState(false)
  const [dormantContacts, setDormantContacts] = useState<DormantContactItem[]>([])
  const [dormantLoading, setDormantLoading] = useState(false)
  const [dormantTotal, setDormantTotal] = useState(0)
  // F-E5: Credit score state
  const [creditScore, setCreditScore] = useState<CreditScoreResponse | null>(null)
  // F-G2: Stage info state
  const [stageInfo, setStageInfo] = useState<StageInfoResponse | null>(null)
  // Cross-navigation: entity history state
  const [entityHistory, setEntityHistory] = useState<EntityHistoryResponse | null>(null)
  // Duplicate handling (design 2026-08-16): filter + duplicates banner + merge modal
  const [statusFilter, setStatusFilter] = useState<'all' | 'provisional'>('all')
  const [duplicateGroups, setDuplicateGroups] = useState<DuplicateGroup[]>([])
  const [showDuplicates, setShowDuplicates] = useState(false)
  const [mergeVisible, setMergeVisible] = useState(false)
  const [mergePeer, setMergePeer] = useState<EntityResponse | null>(null)
  const [mergeSearch, setMergeSearch] = useState('')
  const [mergeKeepCurrent, setMergeKeepCurrent] = useState(true)
  const [merging, setMerging] = useState(false)

  useEffect(() => {
    if (!isLoggedIn()) { setShowLogin(true); setLoading(false); return }
    loadEntities()
  }, [])

  // Listen for cross-tab navigation events
  useEffect(() => {
    const handler = (data: { entityId: string; entityName?: string }) => {
      handleEntityTap(data.entityId)
    }
    Taro.eventCenter.on(NAV_EVENTS.OPEN_ENTITY_DETAIL, handler)
    return () => {
      Taro.eventCenter.off(NAV_EVENTS.OPEN_ENTITY_DETAIL, handler)
    }
  }, [])

  if (showLogin) {
    return (
      <LoginGate
        title='需要登录'
        onLoginSuccess={() => {
          setShowLogin(false)
          loadEntities()
        }}
      />
    )
  }

  async function loadEntities(searchVal?: string, status?: 'all' | 'provisional') {
    try {
      setLoading(true)
      setError('')
      const effectiveStatus = status || statusFilter
      const res = await getEntities(
        searchVal || undefined,
        50,
        0,
        effectiveStatus === 'provisional' ? 'provisional' : undefined
      )
      setEntities(res.items)
      loadDuplicateGroups()
    } catch (err) {
      const msg = err instanceof Error ? err.message : '加载失败'
      if (msg.includes('401')) { setShowLogin(true); setError('') }
      else { setError(msg) }
    } finally {
      setLoading(false)
    }
  }

  async function loadDuplicateGroups() {
    try {
      const res = await getDuplicateGroups()
      setDuplicateGroups(res.groups)
    } catch {
      setDuplicateGroups([])
    }
  }

  function handleFilterChange(next: 'all' | 'provisional') {
    setStatusFilter(next)
    loadEntities(search || undefined, next)
  }

  // AC1.3/AC1.4: confirm provisional entity (optimistic, rollback on failure)
  async function handleConfirmEntity(entityId: string) {
    const prev = entities
    setEntities(cur => cur.map(e => e.id === entityId ? { ...e, status: 'confirmed' } : e))
    try {
      await confirmEntity(entityId)
      loadDuplicateGroups()
    } catch (err) {
      setEntities(prev)
      Taro.showToast({ title: '确认失败', icon: 'error' })
    }
  }

  function handleSearch(val: string) {
    setSearch(val)
    loadEntities(val)
  }

  async function handleEntityTap(entityId: string) {
    try {
      const data = await getEntityDetail(entityId)
      setDetail(data)
      // F-E5: Load credit score (non-blocking)
      getCreditScore(entityId).then(setCreditScore).catch(() => {})
      // F-G2: Load stage info (non-blocking)
      getStageInfo(entityId).then(setStageInfo).catch(() => {})
      // Cross-navigation: Load entity history (non-blocking)
      getEntityHistory(entityId).then(setEntityHistory).catch(() => {})
      setDetailVisible(true)
    } catch (err) {
      Taro.showToast({ title: '加载详情失败', icon: 'error' })
    }
  }

  function closeDetail() {
    setDetailVisible(false)
    setDetail(null)
    setCreditScore(null)
    setStageInfo(null)
    setEntityHistory(null)
  }

  // F-E3: Load dormant contacts
  async function handleShowDormant() {
    try {
      setShowDormant(true)
      setDormantLoading(true)
      const res = await getDormantContacts(10, 1)  // min_days=1 for PoC (show all inactive)
      setDormantContacts(res.items)
      setDormantTotal(res.total)
    } catch (err) {
      console.error('加载沉睡人脉失败:', err)
    } finally {
      setDormantLoading(false)
    }
  }

  function closeDormant() {
    setShowDormant(false)
  }

  const ENTITY_TYPE_MAP: Record<string, string> = {
    person: '人物',
    organization: '组织',
    location: '地点',
    other: '其他',
  }

  // Internal fields that should not be shown to users
  const INTERNAL_KEYS = new Set([
    'source_event_id', 'event_ids', 'sensitivity', 'raw_confidence',
    'extraction_method', 'merge_source', 'merge_history', 'event_keywords', 'event_topics',
  ])

  // Field name Chinese mapping
  const FIELD_LABEL_MAP: Record<string, string> = {
    company: '公司',
    title: '职位',
    phone: '电话',
    email: '邮箱',
    school: '学校',
    schools: '学校',
    concern: '关注点',
    promise: '承诺',
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
    basic: '基本信息',
    demand: '需求',
    resource: '资源',
    tech_stack: '技术栈',
    work_history: '工作经历',
  }

  // Editing state for entity properties
  const [editingField, setEditingField] = useState<string | null>(null)
  const [editingValue, setEditingValue] = useState('')

  function filterInternalFields(properties: Record<string, unknown>): Record<string, unknown> {
    const filtered: Record<string, unknown> = {}
    for (const [key, val] of Object.entries(properties)) {
      if (INTERNAL_KEYS.has(key)) continue
      if (typeof val === 'object' && val !== null && !Array.isArray(val)) {
        const nested: Record<string, unknown> = {}
        for (const [nk, nv] of Object.entries(val as Record<string, unknown>)) {
          if (!INTERNAL_KEYS.has(nk)) nested[nk] = nv
        }
        filtered[key] = nested
      } else {
        filtered[key] = val
      }
    }
    return filtered
  }

  function formatFieldValue(val: unknown): string {
    if (typeof val === 'object' && val !== null) {
      return JSON.stringify(val, null, 0).replace(/[{}"]/g, '').replace(/:/g, ': ').replace(/,/g, ', ')
    }
    return String(val)
  }

  async function handleSaveField(fieldKey: string) {
    if (!detail) return
    try {
      const newProperties = { ...detail.properties, [fieldKey]: editingValue }
      const updated = await updateEntity(detail.id, { properties: newProperties })
      setDetail(updated)
      setEditingField(null)
      setEditingValue('')
    } catch (err) {
      Taro.showToast({ title: '保存失败', icon: 'error' })
    }
  }

  function startEditing(fieldKey: string, currentValue: string) {
    setEditingField(fieldKey)
    setEditingValue(currentValue)
  }

  async function handleDeleteEntity() {
    if (!detail) return
    try {
      const res = await Taro.showModal({
        title: '确认删除',
        content: '确认删除此人脉？相关待办和关联也会被删除',
        confirmText: '删除',
        cancelText: '取消',
        confirmColor: '#C4A7A0',
      })
      if (!res.confirm) return
      await deleteEntity(detail.id)
      Taro.showToast({ title: '已删除', icon: 'success' })
      closeDetail()
      loadEntities()
    } catch (err) {
      Taro.showToast({ title: '删除失败', icon: 'error' })
    }
  }

  // ── Manual merge (US-2, design 2026-08-16) ──

  const [mergeCandidates, setMergeCandidates] = useState<EntityResponse[]>([])

  function openMergeModal() {
    setMergeVisible(true)
    setMergePeer(null)
    setMergeSearch('')
    setMergeKeepCurrent(true)
    setMergeCandidates([])
  }

  async function handleMergeSearch(val: string) {
    setMergeSearch(val)
    if (!detail || !val.trim()) { setMergeCandidates([]); return }
    try {
      const res = await getEntities(val.trim(), 20)
      setMergeCandidates(res.items.filter(e => e.id !== detail.id))
    } catch {
      setMergeCandidates([])
    }
  }

  async function handleMergeConfirm() {
    if (!detail || !mergePeer) return
    const targetName = mergeKeepCurrent ? detail.name : mergePeer.name
    const sourceName = mergeKeepCurrent ? mergePeer.name : detail.name
    try {
      const res = await Taro.showModal({
        title: '确认合并（不可撤销）',
        content: `将「${sourceName}」并入「${targetName}」？对方的历史事件、待办、关联都会转移到保留档案`,
        confirmText: '合并',
        cancelText: '取消',
        confirmColor: '#C4A7A0',
      })
      if (!res.confirm) return
      setMerging(true)
      const targetId = mergeKeepCurrent ? detail.id : mergePeer.id
      const sourceId = mergeKeepCurrent ? mergePeer.id : detail.id
      const result = await mergeEntities(targetId, sourceId)
      Taro.showToast({
        title: `已合并（待办迁移 ${result.migrated.todos} 项）`,
        icon: 'success',
      })
      setMergeVisible(false)
      closeDetail()
      loadEntities()
    } catch (err) {
      Taro.showToast({ title: '合并失败', icon: 'error' })
    } finally {
      setMerging(false)
    }
  }

  return (
    <View className='page-entities'>
      <View className='header'>
        <Text className='header-title'>人脉</Text>
      </View>

      {/* Search Bar */}
      <View className='search-bar'>
        <Input
          className='search-input'
          value={search}
          onInput={e => handleSearch(e.detail.value)}
          placeholder='搜索人名、公司...'
        />
      </View>

      {/* AC1.2: status filter chips */}
      <View className='entity-filter-bar'>
        <View
          className={`filter-chip ${statusFilter === 'all' ? 'active' : ''}`}
          onClick={() => handleFilterChange('all')}
        >
          <Text>全部</Text>
        </View>
        <View
          className={`filter-chip ${statusFilter === 'provisional' ? 'active' : ''}`}
          onClick={() => handleFilterChange('provisional')}
        >
          <Text>待确认</Text>
        </View>
      </View>

      {/* F-E3: Dormant Contacts Entry */}
      <View className='dormant-entry' onClick={handleShowDormant}>
        <Text className='dormant-entry-icon'>搜</Text>
        <Text className='dormant-entry-text'>发现沉睡人脉</Text>
        <Text className='dormant-entry-desc'>找出值得重新联系的人</Text>
      </View>

      {/* AC3.2: suspected duplicates banner */}
      {duplicateGroups.length > 0 && (
        <View className='duplicates-banner'>
          <View className='duplicates-banner-head' onClick={() => setShowDuplicates(!showDuplicates)}>
            <Text className='duplicates-banner-text'>
              发现 {duplicateGroups.length} 组疑似重复人脉（同名）
            </Text>
            <Text className='duplicates-banner-arrow'>{showDuplicates ? '收起' : '展开'}</Text>
          </View>
          {showDuplicates && duplicateGroups.map((group, gi) => (
            <View key={gi} className='duplicates-group'>
              <Text className='duplicates-group-name'>{group.name}</Text>
              {group.entities.map(e => (
                <View key={e.id} className='duplicates-group-member'>
                  <View className='duplicates-member-info'>
                    <Text className='duplicates-member-name'>{e.name}</Text>
                    <Text className='duplicates-member-meta'>
                      {[e.company, e.title].filter(Boolean).join(' · ') || '暂无公司信息'}
                    </Text>
                  </View>
                  <Text
                    className='duplicates-member-open'
                    onClick={() => handleEntityTap(e.id)}
                  >
                    处理
                  </Text>
                </View>
              ))}
            </View>
          ))}
        </View>
      )}

      {loading && <View className='loading'><Text>加载中...</Text></View>}
      {error && <View className='error'><Text>{error}</Text></View>}

      <ScrollView scrollY className='entity-list'>
        {entities.length === 0 && !loading && (
          <View className='empty'><Text>暂无人脉记录</Text></View>
        )}
        {entities.map(entity => (
          <View
            key={entity.id}
            className='entity-card'
            onClick={() => handleEntityTap(entity.id)}
          >
            <View className='entity-avatar'>
              <Text className='avatar-text'>
                {entity.name.charAt(0)}
              </Text>
            </View>
            <View className='entity-info'>
              <View className='entity-name-row'>
                <Text className='entity-name'>{entity.name}</Text>
                {entity.status === 'provisional' && (
                  <Text className='provisional-badge'>待确认</Text>
                )}
              </View>
              <Text className='entity-type'>
                {ENTITY_TYPE_MAP[entity.entity_type] || entity.entity_type}
              </Text>
              {entity.properties?.['company'] ? (
                <Text className='entity-company'>
                  {String(entity.properties['company'])}
                </Text>
              ) : null}
            </View>
            {entity.status === 'provisional' ? (
              <Text
                className='confirm-btn'
                onClick={(e) => {
                  e.stopPropagation()
                  handleConfirmEntity(entity.id)
                }}
              >
                确认
              </Text>
            ) : (
              <Text className='entity-arrow'>›</Text>
            )}
          </View>
        ))}
      </ScrollView>

      {/* Detail Modal */}
      {detailVisible && detail && (
        <View className='modal-overlay' onClick={closeDetail}>
          <View className='modal-content' onClick={e => e.stopPropagation()}>
            <View className='modal-header'>
              <Text className='modal-title'>{detail.name}</Text>
              <Text className='modal-close' onClick={closeDetail}>×</Text>
            </View>
            <View className='modal-body'>
              {/* AC2.4: merged entity — redirect hint */}
              {detail.status === 'merged' && (
                <View className='merged-notice'>
                  <Text className='merged-notice-text'>
                    此档案已并入另一档案（保留完整历史）
                  </Text>
                  {Boolean(detail.properties?.['merged_into']) && (
                    <Text
                      className='merged-notice-link'
                      onClick={() => handleEntityTap(String(detail.properties?.['merged_into']))}
                    >
                      查看保留档案 ›
                    </Text>
                  )}
                </View>
              )}
              <View className='detail-row'>
                <Text className='detail-label'>类型</Text>
                <Text className='detail-value'>
                  {ENTITY_TYPE_MAP[detail.entity_type] || detail.entity_type}
                </Text>
              </View>
              {detail.canonical_name !== detail.name && (
                <View className='detail-row'>
                  <Text className='detail-label'>标准名</Text>
                  <Text className='detail-value'>{detail.canonical_name}</Text>
                </View>
              )}
              {detail.aliases && detail.aliases.length > 0 && (
                <View className='detail-row'>
                  <Text className='detail-label'>别名</Text>
                  <Text className='detail-value'>{detail.aliases.join(', ')}</Text>
                </View>
              )}
              {detail.properties && Object.entries(filterInternalFields(detail.properties)).map(([key, val]) => {
                const displayValue = formatFieldValue(val)
                const isEditing = editingField === key
                return (
                  <View key={key} className='detail-row'>
                    <Text className='detail-label'>{FIELD_LABEL_MAP[key] || key}</Text>
                    {isEditing ? (
                      <View className='detail-edit-row'>
                        <Input
                          className='detail-edit-input'
                          value={editingValue}
                          onInput={e => setEditingValue(e.detail.value)}
                          autoFocus
                        />
                        <Text className='detail-edit-save' onClick={() => handleSaveField(key)}>保存</Text>
                        <Text className='detail-edit-cancel' onClick={() => setEditingField(null)}>取消</Text>
                      </View>
                    ) : (
                      <Text
                        className='detail-value detail-value-editable'
                        onClick={() => startEditing(key, displayValue)}
                      >
                        {displayValue}
                      </Text>
                    )}
                  </View>
                )
              })}
              <View className='detail-row'>
                <Text className='detail-label'>置信度</Text>
                <Text className='detail-value'>{(detail.confidence * 100).toFixed(0)}%</Text>
              </View>

              {/* Confirm provisional entity */}
              {detail.status === 'provisional' && (
                <View className='detail-row'>
                  <Text
                    className='confirm-detail-btn'
                    onClick={(e) => {
                      e.stopPropagation()
                      handleConfirmEntity(detail.id).then(() => {
                        getEntityDetail(detail.id).then(setDetail).catch(() => {})
                      })
                    }}
                  >
                    确认为正式人脉
                  </Text>
                </View>
              )}

              {/* Merge duplicates entry (active entities only) */}
              {detail.status !== 'merged' && (
                <View className='detail-row'>
                  <Text
                    className='merge-entry-btn'
                    onClick={(e) => {
                      e.stopPropagation()
                      openMergeModal()
                    }}
                  >
                    合并重复人脉
                  </Text>
                </View>
              )}

              {/* Delete entity button */}
              <View className='detail-row'>
                <Text
                  className='delete-entity-btn'
                  onClick={(e) => {
                    e.stopPropagation()
                    handleDeleteEntity()
                  }}
                >
                  删除此人脉
                </Text>
              </View>

              {/* View full detail button */}
              <View className='detail-row'>
                <Text
                  className='view-detail-btn'
                  onClick={(e) => {
                    e.stopPropagation()
                    if (detail) navigateToEntityDetail(detail.id)
                  }}
                >
                  查看完整详情 ›
                </Text>
              </View>

              {/* F-E5: Credit Score */}
              {creditScore && (
                <View className='credit-score-section'>
                  <View className='credit-header'>
                    <Text className='credit-label'>关系信用分</Text>
                    <View className={`credit-grade grade-${creditScore.grade.replace('+', 'p')}`}>
                      <Text>{creditScore.grade}</Text>
                    </View>
                  </View>
                  <View className='credit-score-bar'>
                    <View
                      className='credit-fill'
                      style={{ width: `${Math.min(100, creditScore.score)}%` }}
                    />
                  </View>
                  <Text className='credit-number'>{creditScore.score.toFixed(1)}</Text>
                  <View className='credit-breakdown'>
                    <Text>我守承诺: {(creditScore.breakdown.my_fulfillment_rate * 100).toFixed(0)}%</Text>
                    <Text>对方守信: {(creditScore.breakdown.their_fulfillment_rate * 100).toFixed(0)}%</Text>
                    <Text>互动次数: {creditScore.breakdown.total_interactions}</Text>
                  </View>
                </View>
              )}

              {/* F-G2: Relationship Stage */}
              {stageInfo && (
                <View className='stage-section'>
                  <View className='stage-header'>
                    <Text className='stage-label'>关系阶段</Text>
                    <View
                      className='stage-current-badge'
                      style={{ backgroundColor: stageInfo.current_stage_color }}
                    >
                      <Text className='stage-current-text'>{stageInfo.current_stage_label}</Text>
                    </View>
                  </View>
                  <Text className='stage-desc'>{stageInfo.current_stage_desc}</Text>

                  {/* Suggestion card */}
                  {stageInfo.suggestion && (
                    <View className='stage-suggestion'>
                      <Text className='suggestion-reason'>→ {stageInfo.suggestion.target_stage_label}: {stageInfo.suggestion.reason}</Text>
                      <Text className='suggestion-hint'>提示：{stageInfo.suggestion.action_hint}</Text>
                    </View>
                  )}
                </View>
              )}

              {/* Related Events */}
              {entityHistory && entityHistory.events.length > 0 && (
                <View className='detail-section'>
                  <Text className='section-title'>相关事件 ({entityHistory.events.length})</Text>
                  {entityHistory.events.slice(0, 5).map(evt => (
                    <View key={evt.id} className='related-item' onClick={() => { navigateToEvent(evt.id); closeDetail() }}>
                      <Text className='related-item-title'>{evt.title}</Text>
                      <Text className='related-item-meta'>{new Date(evt.timestamp).toLocaleDateString('zh-CN')}</Text>
                    </View>
                  ))}
                </View>
              )}

              {/* Related Todos */}
              {entityHistory && entityHistory.todos.length > 0 && (
                <View className='detail-section'>
                  <Text className='section-title'>相关待办 ({entityHistory.todos.length})</Text>
                  {entityHistory.todos.slice(0, 5).map(todo => (
                    <View key={todo.id} className='related-item'>
                      <Text className='related-item-title'>{todo.title}</Text>
                      <View className='related-item-right'>
                        <Text className='related-item-meta'>{todo.status === 'done' ? '已完成' : todo.status === 'pending' ? '待处理' : todo.status}</Text>
                        {todo.status === 'pending' && (
                          <Text
                            className='dismiss-btn'
                            onClick={(e) => {
                              e.stopPropagation()
                              dismissTodo(todo.id).then(() => {
                                if (detail) getEntityHistory(detail.id).then(setEntityHistory)
                              })
                            }}
                          >
                            忽略
                          </Text>
                        )}
                      </View>
                    </View>
                  ))}
                </View>
              )}

              {/* Related Associations */}
              {entityHistory && entityHistory.associations.length > 0 && (
                <View className='detail-section'>
                  <Text className='section-title'>关联人脉 ({entityHistory.associations.length})</Text>
                  {entityHistory.associations.slice(0, 5).map(assoc => (
                    <View key={assoc.id} className='related-item'>
                      <Text className='related-item-title'>{assoc.target_entity_name}</Text>
                      <Text className='related-item-meta'>{assoc.association_type}</Text>
                    </View>
                  ))}
                </View>
              )}
            </View>
          </View>
        </View>
      )}

      {/* F-E3: Dormant Contacts Modal */}
      {showDormant && (
        <View className='dormant-modal-overlay' onClick={closeDormant}>
          <View className='dormant-modal-content' onClick={e => e.stopPropagation()}>
            <View className='dormant-modal-header'>
              <Text className='dormant-modal-title'>发现沉睡人脉</Text>
              <Text className='dormant-modal-close' onClick={closeDormant}>×</Text>
            </View>

            {dormantLoading ? (
              <View className='dormant-loading'><Text>正在扫描...</Text></View>
            ) : dormantContacts.length === 0 ? (
              <View className='dormant-empty'>
                <Text className='dormant-empty-icon'>—</Text>
                <Text className='dormant-empty-text'>暂无沉睡联系人</Text>
                <Text className='dormant-empty-hint'>你的人脉都保持活跃状态，做得很好！</Text>
              </View>
            ) : (
              <>
                <Text className='dormant-summary'>发现 {dormantTotal} 位值得重新联系的人</Text>
                <ScrollView scrollY className='dormant-list'>
                  {dormantContacts.map(dc => (
                    <View key={dc.entity_id} className='dormant-card'>
                      <View className='dormant-card-top'>
                        <View className='dormant-avatar'>
                          <Text>{dc.name.charAt(0)}</Text>
                        </View>
                        <View className='dormant-info'>
                          <Text className='dormant-name'>{dc.name}</Text>
                          {dc.company && <Text className='dormant-company'>{dc.company}</Text>}
                        </View>
                        <View className={`dormant-score score-${dc.reactivation_score >= 70 ? 'high' : dc.reactivation_score >= 40 ? 'mid' : 'low'}`}>
                          <Text>{dc.reactivation_score.toFixed(0)}</Text>
                        </View>
                      </View>
                      <View className='dormant-meta'>
                        <Text>静默 {dc.dormant_days} 天</Text>
                        {dc.pending_their_promises > 0 && <Text> · 对方有{dc.pending_their_promises}条未兑现承诺</Text>}
                      </View>
                      <Text className='dormant-reason'>{dc.reason}</Text>
                      <View className='dormant-icebreaker'>
                        <Text className='ice-label'>破冰话术:</Text>
                        <Text className='ice-text'>{dc.icebreaker_topic}</Text>
                      </View>
                    </View>
                  ))}
                </ScrollView>
              </>
            )}
          </View>
        </View>
      )}

      {/* Manual Merge Modal (US-2) */}
      {mergeVisible && detail && (
        <View className='modal-overlay' onClick={() => setMergeVisible(false)}>
          <View className='modal-content merge-modal' onClick={e => e.stopPropagation()}>
            <View className='modal-header'>
              <Text className='modal-title'>合并重复人脉</Text>
              <Text className='modal-close' onClick={() => setMergeVisible(false)}>×</Text>
            </View>
            <View className='modal-body'>
              {/* Step 1: search and select the peer entity */}
              {!mergePeer && (
                <>
                  <Text className='merge-step-label'>
                    第 1 步：搜索要合并的另一个人脉档案
                  </Text>
                  <Input
                    className='merge-search-input'
                    value={mergeSearch}
                    onInput={e => handleMergeSearch(e.detail.value)}
                    placeholder='输入人名搜索...'
                  />
                  <ScrollView scrollY className='merge-candidates'>
                    {mergeCandidates.map(c => (
                      <View key={c.id} className='merge-candidate' onClick={() => setMergePeer(c)}>
                        <Text className='merge-candidate-name'>{c.name}</Text>
                        <Text className='merge-candidate-meta'>
                          {[c.properties?.['company'], c.properties?.['title']]
                            .filter(Boolean).join(' · ') || '暂无公司信息'}
                        </Text>
                      </View>
                    ))}
                    {mergeSearch && mergeCandidates.length === 0 && (
                      <Text className='merge-no-result'>未找到匹配的人脉</Text>
                    )}
                  </ScrollView>
                </>
              )}

              {/* Step 2: compare and choose keep direction */}
              {mergePeer && (
                <>
                  <Text className='merge-step-label'>第 2 步：选择保留哪个档案</Text>
                  <View className='merge-compare'>
                    <View
                      className={`merge-option ${mergeKeepCurrent ? 'selected' : ''}`}
                      onClick={() => setMergeKeepCurrent(true)}
                    >
                      <Text className='merge-option-name'>{detail.name}（当前）</Text>
                      <Text className='merge-option-meta'>
                        {[detail.properties?.['company'], detail.properties?.['title']]
                          .filter(Boolean).join(' · ') || '暂无公司信息'}
                      </Text>
                      {mergeKeepCurrent && <Text className='merge-option-tag'>保留</Text>}
                    </View>
                    <View
                      className={`merge-option ${!mergeKeepCurrent ? 'selected' : ''}`}
                      onClick={() => setMergeKeepCurrent(false)}
                    >
                      <Text className='merge-option-name'>{mergePeer.name}</Text>
                      <Text className='merge-option-meta'>
                        {[mergePeer.properties?.['company'], mergePeer.properties?.['title']]
                          .filter(Boolean).join(' · ') || '暂无公司信息'}
                      </Text>
                      {!mergeKeepCurrent && <Text className='merge-option-tag'>保留</Text>}
                    </View>
                  </View>
                  <Text className='merge-hint'>
                    保留档案继承双方属性（冲突以保留方为准），被并档案的历史事件、待办、关联全部转移。合并后不可撤销。
                  </Text>
                  <View className='merge-actions'>
                    <Text className='merge-cancel' onClick={() => setMergePeer(null)}>上一步</Text>
                    <Text
                      className={`merge-submit ${merging ? 'disabled' : ''}`}
                      onClick={() => { if (!merging) handleMergeConfirm() }}
                    >
                      {merging ? '合并中...' : '确认合并'}
                    </Text>
                  </View>
                </>
              )}
            </View>
          </View>
        </View>
      )}
    </View>
  )
}
