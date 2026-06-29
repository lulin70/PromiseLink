import { View, Text, Button } from '@tarojs/components'
import Taro from '@tarojs/taro'
import { getUserId, logout, isLoggedIn } from '../../services/auth'
import './index.scss'

// 基础版"我的"页面
// 展示用户信息、专业版升级入口、数据导出、关于信息、退出登录
export default function MinePage() {
  if (!isLoggedIn()) {
    Taro.reLaunch({ url: '/pages/index/index' })
    return null
  }

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
      content: 'PromiseLink v0.7.0\n\nAI 驱动的个人商务关系经营助手\n基础版（AGPL v3）\n\n© 2026 PromiseLink',
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

      <View className='mine-section'>
        <View className='mine-section-title'>
          <Text>账户</Text>
        </View>
        <View className='mine-menu-item' onClick={handleProUpgrade}>
          <Text className='mine-menu-label'>升级专业版</Text>
          <Text className='mine-menu-arrow'>&gt;</Text>
        </View>
        <View className='mine-menu-item' onClick={handleExportData}>
          <Text className='mine-menu-label'>导出我的数据</Text>
          <Text className='mine-menu-arrow'>&gt;</Text>
        </View>
        <View className='mine-menu-item' onClick={handleAbout}>
          <Text className='mine-menu-label'>关于 PromiseLink</Text>
          <Text className='mine-menu-arrow'>&gt;</Text>
        </View>
      </View>

      <View className='mine-section'>
        <View className='mine-section-title'>
          <Text>专业版功能</Text>
        </View>
        <View className='mine-pro-features'>
          <Text className='mine-pro-feature'>· 语音录入</Text>
          <Text className='mine-pro-feature'>· 邮件同步</Text>
          <Text className='mine-pro-feature'>· OCR 名片扫描</Text>
          <Text className='mine-pro-feature'>· 微信小程序端</Text>
        </View>
      </View>

      <View className='mine-logout'>
        <Button className='mine-logout-btn' onClick={handleLogout}>
          退出登录
        </Button>
      </View>
    </View>
  )
}
