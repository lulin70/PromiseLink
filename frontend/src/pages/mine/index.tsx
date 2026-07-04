import { View, Text, Button, Input } from '@tarojs/components'
import Taro from '@tarojs/taro'
import { useEffect, useState } from 'react'
import { getUserId, logout, isLoggedIn } from '../../services/auth'
import { getPrivacyDataSummary, deleteMyData, PrivacyDataSummary } from '../../services/api'
import './index.scss'

// 1.1 设置页核心项：隐私删除二次确认 + 提醒偏好入口 + 专业版功能提示
const DELETE_CONFIRM_PHRASE = 'DELETE'

export default function MinePage() {
  const [summary, setSummary] = useState<PrivacyDataSummary | null>(null)
  const [showDeleteModal, setShowDeleteModal] = useState(false)
  const [deletePhrase, setDeletePhrase] = useState('')
  const [deleting, setDeleting] = useState(false)

  useEffect(() => {
    if (!isLoggedIn()) {
      Taro.reLaunch({ url: '/pages/index/index' })
      return
    }
    // 非阻塞加载数据摘要（用于二次确认 modal 展示计数）
    getPrivacyDataSummary().then(setSummary).catch(() => {})
  }, [])

  const userId = getUserId()

  function handleLogout() {
    logout()
    Taro.reLaunch({ url: '/pages/index/index' })
  }

  function handleProUpgrade() {
    window.open('https://promiselink.cn/pro', '_blank')
  }

  function handleAbout() {
    Taro.showModal({
      title: '关于 PromiseLink',
      content: 'PromiseLink v0.8.0-rc2\n\nAI 驱动的个人商务关系经营助手\n基础版（AGPL v3）\n\n© 2026 PromiseLink',
      showCancel: false,
    })
  }

  async function handleExportData() {
    try {
      Taro.showLoading({ title: '导出中...' })
      const { exportData } = await import('../../services/api')
      const data = await exportData(userId)
      const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' })
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = `promiselink_export_${new Date().toISOString().slice(0, 10)}.json`
      a.click()
      URL.revokeObjectURL(url)
      Taro.showToast({ title: '导出成功', icon: 'success' })
    } catch {
      Taro.showToast({ title: '导出失败', icon: 'none' })
    } finally {
      Taro.hideLoading()
    }
  }

  // 1.3 提醒偏好快捷入口
  function handleReminderPref() {
    Taro.navigateTo({ url: '/pages/reminders/index' })
  }

  // 1.1 专业版功能入口 — 点击提示"专业版功能"
  function handleProFeatureToast(featureName: string) {
    Taro.showToast({ title: `${featureName} 为专业版功能`, icon: 'none' })
  }

  // 1.1 隐私数据删除二次确认 — 打开 modal
  function handleOpenDeleteModal() {
    setDeletePhrase('')
    setShowDeleteModal(true)
  }

  // 1.1 隐私数据删除二次确认 — 输入 DELETE 短语后执行
  async function handleConfirmDelete() {
    if (deletePhrase.trim() !== DELETE_CONFIRM_PHRASE) {
      Taro.showToast({ title: `请输入 ${DELETE_CONFIRM_PHRASE} 确认`, icon: 'none' })
      return
    }
    try {
      setDeleting(true)
      Taro.showLoading({ title: '删除中...' })
      const res = await deleteMyData(deletePhrase.trim())
      Taro.hideLoading()
      const totalDeleted = Object.values(res.deleted).reduce((s, n) => s + n, 0)
      Taro.showModal({
        title: '删除完成',
        content: `已删除 ${totalDeleted} 条数据。\n审计 ID：${res.audit_id}\n删除时间：${new Date(res.deleted_at).toLocaleString('zh-CN')}`,
        showCancel: false,
      })
      setShowDeleteModal(false)
      setDeletePhrase('')
      // 退出登录（数据已删，会话无效）
      logout()
      Taro.reLaunch({ url: '/pages/index/index' })
    } catch (err: unknown) {
      Taro.hideLoading()
      const msg = err instanceof Error ? err.message : '删除失败'
      Taro.showToast({ title: msg, icon: 'error' })
    } finally {
      setDeleting(false)
    }
  }

  function handleCancelDelete() {
    if (deleting) return
    setShowDeleteModal(false)
    setDeletePhrase('')
  }

  // 渲染数据摘要（用于二次确认 modal 顶部展示）
  function renderSummaryText(): string {
    if (!summary) return '数据加载中...'
    const parts: string[] = []
    const labelMap: Record<string, string> = {
      events: '事件',
      todos: '待办',
      entities: '人脉',
      promises: '承诺',
      associations: '关系',
      scheduled_events: '日程',
      reminder_logs: '提醒记录',
      score_audit_logs: '评分记录',
      relationship_briefs: '关系摘要',
    }
    for (const [k, v] of Object.entries(summary.counts)) {
      if (v > 0) parts.push(`${labelMap[k] || k} ${v}`)
    }
    return parts.length > 0 ? parts.join(' · ') : '当前账户无业务数据'
  }

  if (!isLoggedIn()) {
    return null
  }

  return (
    <View className='mine-page'>
      <View className='mine-header'>
        <View className='mine-avatar'>
          <Text className='mine-avatar-text'>{userId.charAt(0).toUpperCase()}</Text>
        </View>
        <View className='mine-user-info'>
          <Text className='mine-user-id'>{userId}</Text>
          <Text className='mine-user-edition'>基础版用户</Text>
        </View>
      </View>

      {/* 账户区 */}
      <View className='mine-section'>
        <View className='mine-section-title'>
          <Text>账户</Text>
        </View>
        <View className='mine-menu-item' onClick={handleProUpgrade}>
          <Text className='mine-menu-label'>升级专业版</Text>
          <Text className='mine-menu-arrow'>&gt;</Text>
        </View>
        <View className='mine-menu-item' onClick={handleReminderPref}>
          <Text className='mine-menu-label'>提醒偏好</Text>
          <Text className='mine-menu-arrow'>&gt;</Text>
        </View>
        <View className='mine-menu-item' onClick={handleExportData}>
          <Text className='mine-menu-label'>导出我的数据</Text>
          <Text className='mine-menu-arrow'>&gt;</Text>
        </View>
        <View className='mine-menu-item mine-menu-danger' onClick={handleOpenDeleteModal}>
          <Text className='mine-menu-label'>删除我的数据</Text>
          <Text className='mine-menu-arrow'>&gt;</Text>
        </View>
        <View className='mine-menu-item' onClick={handleAbout}>
          <Text className='mine-menu-label'>关于 PromiseLink</Text>
          <Text className='mine-menu-arrow'>&gt;</Text>
        </View>
      </View>

      {/* 专业版功能（入口可点击，提示"专业版功能"） */}
      <View className='mine-section'>
        <View className='mine-section-title'>
          <Text>专业版功能</Text>
        </View>
        <View
          className='mine-menu-item'
          onClick={() => handleProFeatureToast('语音录入')}
        >
          <Text className='mine-menu-label'>语音录入</Text>
          <Text className='mine-menu-tag'>Pro</Text>
        </View>
        <View
          className='mine-menu-item'
          onClick={() => handleProFeatureToast('邮件同步')}
        >
          <Text className='mine-menu-label'>邮件同步</Text>
          <Text className='mine-menu-tag'>Pro</Text>
        </View>
        <View
          className='mine-menu-item'
          onClick={() => handleProFeatureToast('OCR 名片扫描')}
        >
          <Text className='mine-menu-label'>OCR 名片扫描</Text>
          <Text className='mine-menu-tag'>Pro</Text>
        </View>
        <View
          className='mine-menu-item'
          onClick={() => handleProFeatureToast('CSV 批量导入')}
        >
          <Text className='mine-menu-label'>CSV 批量导入</Text>
          <Text className='mine-menu-tag'>Pro</Text>
        </View>
        <View
          className='mine-menu-item'
          onClick={() => handleProFeatureToast('微信小程序端')}
        >
          <Text className='mine-menu-label'>微信小程序端</Text>
          <Text className='mine-menu-tag'>Pro</Text>
        </View>
      </View>

      <View className='mine-logout'>
        <Button className='mine-logout-btn' onClick={handleLogout}>
          退出登录
        </Button>
      </View>

      {/* 1.1 隐私数据删除二次确认 Modal */}
      {showDeleteModal && (
        <View className='privacy-delete-modal-mask'>
          <View className='privacy-delete-modal'>
            <Text className='pd-modal-title'>确认删除全部数据</Text>
            <Text className='pd-modal-warning'>
              此操作将立即删除你的全部业务数据（事件、待办、人脉、承诺、关系等），不可恢复。
            </Text>
            <Text className='pd-modal-summary'>数据摘要：{renderSummaryText()}</Text>
            <Text className='pd-modal-instruction'>
              请输入 <Text className='pd-phrase'>{DELETE_CONFIRM_PHRASE}</Text> 以确认：
            </Text>
            <Input
              className='pd-modal-input'
              type='text'
              value={deletePhrase}
              onInput={e => setDeletePhrase(e.detail.value)}
              placeholder={DELETE_CONFIRM_PHRASE}
            />
            <View className='pd-modal-actions'>
              <View
                className={`pd-modal-btn pd-modal-btn-ghost ${deleting ? 'disabled' : ''}`}
                onClick={handleCancelDelete}
              >
                <Text>取消</Text>
              </View>
              <View
                className={`pd-modal-btn pd-modal-btn-danger ${deleting || deletePhrase.trim() !== DELETE_CONFIRM_PHRASE ? 'disabled' : ''}`}
                onClick={!deleting && deletePhrase.trim() === DELETE_CONFIRM_PHRASE ? handleConfirmDelete : undefined}
              >
                <Text>{deleting ? '删除中...' : '永久删除'}</Text>
              </View>
            </View>
            <Text className='pd-modal-audit-hint'>
              删除操作将记录审计日志，基础版不保留 30 天软删除（软删除为专业版功能）。
            </Text>
          </View>
        </View>
      )}
    </View>
  )
}
