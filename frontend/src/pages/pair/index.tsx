import { View, Text, Image, Button } from '@tarojs/components'
import Taro, { useEffect, useState } from '@tarojs/taro'
import { useRouter } from '@tarojs/router'
import './index.scss'

interface PairStatus {
  status: 'pending' | 'matched' | 'activated' | 'expired'
  license_key?: string
  user_id?: string
}

export default function PairPage() {
  const router = useRouter()
  const [code, setCode] = useState<string>('')
  const [qrUrl, setQrUrl] = useState<string>('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [pairStatus, setPairStatus] = useState<PairStatus | null>(null)
  const [gatewayUrl, setGatewayUrl] = useState('')

  const BASIC_API = 'http://127.0.0.1:8000'

  async function initPair() {
    setLoading(true)
    setError('')
    try {
      const res = await Taro.request({
        url: `${BASIC_API}/api/v1/pair/init`,
        method: 'POST',
      })
      const data = (res.data as any)
      if (data.success) {
        setCode(data.device_pair_code)
        setQrUrl(data.qr_content)
        setGatewayUrl(data.gateway_url)
        startPolling(data.device_pair_code)
      } else {
        setError(data.error || '生成配对码失败')
      }
    } catch (e: any) {
      setError('无法连接本地服务，请确保基础版正在运行')
    } finally {
      setLoading(false)
    }
  }

  function startPolling(pairCode: string) {
    const timer = setInterval(async () => {
      try {
        const res = await Taro.request({
          url: `${BASIC_API}/api/v1/pair/status?code=${pairCode}`,
          method: 'GET',
        })
        const data = (res.data as any)
        if (data?.status === 'matched' || data?.status === 'activated') {
          setPairStatus(data)
          clearInterval(timer)
        } else if (data?.status === 'expired') {
          setPairStatus({ status: 'expired' })
          clearInterval(timer)
        }
      } catch {
        // ignore polling errors
      }
    }, 3000)
  }

  useEffect(() => {
    initPair()
  }, [])

  const statusText = {
    pending: '等待小程序扫码配对...',
    matched: '配对成功！正在激活...',
    activated: '激活成功！',
    expired: '配对码已过期，请重新生成',
  }

  const statusClass = {
    pending: 'status-pending',
    matched: 'status-success',
    activated: 'status-success',
    expired: 'status-error',
  }

  return (
    <View className='pair-page'>
      <View className='pair-header'>
        <Text className='pair-title'>配对电脑端</Text>
        <Text className='pair-subtitle'>用微信小程序扫描下方二维码，快速连接本地服务</Text>
      </View>

      <View className='pair-card'>
        {loading && <Text className='pair-loading'>正在生成配对码...</Text>}

        {error && (
          <View className='pair-error'>
            <Text>{error}</Text>
            <Button className='pair-retry-btn' onClick={initPair}>重试</Button>
          </View>
        )}

        {!loading && !error && code && (
          <>
            {/* 配对码 */}
            <View className='pair-code-section'>
              <Text className='pair-code-label'>配对码</Text>
              <Text className='pair-code'>{code}</Text>
              <Text className='pair-code-hint'>或打开微信小程序搜索 PromiseLink</Text>
            </View>

            {/* 二维码 */}
            {qrUrl && (
              <View className='pair-qr-section'>
                <View className='pair-qr-wrapper'>
                  {/* 使用 QR Server 生成二维码图片 */}
                  <Image
                    className='pair-qr-image'
                    src={`https://api.qrserver.com/v1/create-qr-code/?size=200x200&data=${encodeURIComponent(qrUrl)}`}
                    mode='aspectFit'
                  />
                </View>
                <Text className='pair-qr-hint'>微信扫描上方二维码</Text>
              </View>
            )}

            {/* 状态 */}
            <View className={`pair-status ${pairStatus ? statusClass[pairStatus.status] : 'status-pending'}`}>
              <Text>{pairStatus ? statusText[pairStatus.status] : statusText.pending}</Text>
              {pairStatus?.status === 'activated' && (
                <Text className='pair-success-hint'>本地服务已连接！可在小程序中使用高级功能。</Text>
              )}
            </View>

            {/* 重新生成 */}
            <Button className='pair-refresh-btn' onClick={initPair}>
              重新生成配对码
            </Button>
          </>
        )}
      </View>

      <View className='pair-footer'>
        <Text className='pair-footer-text'>
          配对成功后，小程序将自动连接本地基础版服务
        </Text>
      </View>
    </View>
  )
}
