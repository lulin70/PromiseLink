import { View, Text, Button } from '@tarojs/components'
import Taro from '@tarojs/taro'
import { getUserId, logout } from '../../services/auth'
import './index.scss'

// Basic edition "我的" (Mine) page
// Shows user info, Pro upgrade entry, and logout
export default function MinePage() {
  const userId = getUserId()

  function handleLogout() {
    logout()
    Taro.reLaunch({ url: '/pages/index/index' })
  }

  function handleProUpgrade() {
    // Redirect to Pro edition info page
    window.open('https://promiselink.com/pro', '_blank')
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
        <View className='mine-menu-item'>
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
