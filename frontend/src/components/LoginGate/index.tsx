import { useState } from 'react'
import { View, Text, Input } from '@tarojs/components'
import Taro from '@tarojs/taro'
import { login as apiLogin } from '../../services/api'
import { setToken, setUserId, saveLoginCredentials } from '../../services/auth'
import './index.scss'

interface LoginGateProps {
  /** Callback after successful login (e.g., reload page data) */
  onLoginSuccess?: () => void
  /** Card title (default: "PromiseLink") */
  title?: string
  /** Card subtitle (e.g., "基础版 · 本地部署") */
  subtitle?: string
  /** Show user ID input field (index page uses 2 fields; others use 1) */
  showUserIdField?: boolean
  /** Show "返回首页登录" button instead of login form (reminders mode) */
  showBackHomeButton?: boolean
  /** Default user ID value */
  defaultUserId?: string
}

/**
 * Shared login gate component — replaces 5 inline login forms.
 * ICP_READY_CHECKLIST 5.14: Extract inline login form to shared component.
 *
 * Variants:
 * - Full form with userId + secret (index page)
 * - Full form with secret only (entities/todos/promises pages)
 * - Back-to-home button only (reminders page)
 */
export default function LoginGate({
  onLoginSuccess,
  title = 'PromiseLink',
  subtitle,
  showUserIdField = false,
  showBackHomeButton = false,
  defaultUserId = 'poc-user',
}: LoginGateProps) {
  const [secret, setSecret] = useState('')
  const [userId, setUserIdInput] = useState(defaultUserId)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  async function handleLogin() {
    if (!secret.trim()) {
      setError(showUserIdField ? '请输入 PoC 密钥' : '请输入PoC密钥')
      return
    }
    try {
      setLoading(true)
      setError('')
      const res = await apiLogin(secret.trim(), showUserIdField ? userId.trim() : undefined)
      setToken(res.access_token)
      setUserId(res.user_id || userId)
      saveLoginCredentials(secret.trim())
      onLoginSuccess?.()
    } catch (err: unknown) {
      setError('登录失败: ' + (err instanceof Error ? err.message : String(err)))
    } finally {
      setLoading(false)
    }
  }

  function handleBackHome() {
    Taro.reLaunch({ url: '/pages/index/index' })
  }

  if (showBackHomeButton) {
    return (
      <View className='login-gate-redirect'>
        <View className='login-card'>
          <Text className='login-title'>{title}</Text>
          {subtitle && <Text className='login-subtitle'>{subtitle}</Text>}
          <View className='login-btn' onClick={handleBackHome}>
            <Text className='login-btn-text'>返回首页登录</Text>
          </View>
        </View>
      </View>
    )
  }

  return (
    <View className='login-gate'>
      <View className='login-card'>
        <Text className='login-title'>{title}</Text>
        {subtitle && <Text className='login-subtitle'>{subtitle}</Text>}

        {showUserIdField && (
          <View className='form-group'>
            <Text className='label'>用户 ID</Text>
            <Input
              className='input'
              value={userId}
              onInput={e => setUserIdInput(e.detail.value)}
              placeholder='poc-user'
            />
          </View>
        )}

        <View className='form-group'>
          <Text className='label'>PoC 密钥</Text>
          <Input
            className='input'
            type='safe-password'
            value={secret}
            onInput={e => setSecret(e.detail.value)}
            placeholder='请输入 PoC Secret'
          />
        </View>

        {error ? <Text className='error-text'>{error}</Text> : null}

        <View
          className={`login-btn ${loading ? 'loading' : ''}`}
          onClick={loading ? undefined : handleLogin}
        >
          <Text className='login-btn-text'>{loading ? '登录中...' : '登 录'}</Text>
        </View>
      </View>
    </View>
  )
}
