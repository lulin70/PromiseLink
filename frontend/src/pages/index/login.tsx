import { useState } from 'react'
import { View, Text, Input, Button } from '@tarojs/components'
import { login } from '../../services/api'
import { setToken, setUserId, isLoggedIn } from '../../services/auth'
import Taro from '@tarojs/taro'
import './login.scss'

export default function Login() {
  const [secret, setSecret] = useState('')
  const [userId, setUserIdState] = useState('poc-user')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  if (isLoggedIn()) {
    Taro.switchTab({ url: '/pages/index/index' })
    return null
  }

  async function handleLogin() {
    if (!secret) {
      setError('请输入 PoC 密钥')
      return
    }
    try {
      setLoading(true)
      setError('')
      const res = await login(secret, userId)
      setToken(res.access_token)
      setUserId(res.user_id)
      Taro.switchTab({ url: '/pages/index/index' })
    } catch (err) {
      setError(err instanceof Error ? err.message : '登录失败')
    } finally {
      setLoading(false)
    }
  }

  return (
    <View className='page-login'>
      <View className='login-card'>
        <Text className='login-title'>PromiseLink</Text>
        <Text className='login-subtitle'>基础版 · 本地部署</Text>

        <View className='form-group'>
          <Text className='label'>用户 ID</Text>
          <Input
            className='input'
            value={userId}
            onInput={e => setUserIdState(e.detail.value)}
            placeholder='poc-user'
          />
        </View>

        <View className='form-group'>
          <Text className='label'>PoC 密钥</Text>
          <Input
            className='input'
            type='password'
            value={secret}
            onInput={e => setSecret(e.detail.value)}
            placeholder='请输入 PoC Secret'
          />
        </View>

        {error && <Text className='error-text'>{error}</Text>}

        <Button
          className='login-btn'
          onClick={handleLogin}
          loading={loading}
          disabled={loading}
        >
          登 录
        </Button>
      </View>
    </View>
  )
}
