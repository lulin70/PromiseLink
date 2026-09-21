import { View, Text, Image, Button } from '@tarojs/components'
import Taro from '@tarojs/taro'
import { useEffect, useRef, useState } from 'react'
import './index.scss'

// ②（2026-09-21）：原先只有 4 态，且 `activated` 永远不可达 —— 网关只会回
// pending/matched/expired，终止状态只落在中继日志里，表现为「配不上且不知原因」。
interface PairStatus {
  status: 'pending' | 'matched' | 'activated' | 'expired' | 'rejected'
  rejected_kind?: 'invalid' | 'occupied' | 'not_found' | string
  license_key?: string
  user_id?: string
}

// 凭据被拒的三类归因 → 文案 + 下一步动作。凭据被拒（rejected）与配对码到期
// （expired）是两件事，文案与视觉都必须分开，否则会把用户引向错误的操作。
const REJECTED_HINT: Record<string, string> = {
  not_found: '网关没有找到这把许可证。请在小程序「我的 → 专业版激活」确认账号已开通专业版，再回来重新配对。',
  occupied: '这把许可证已绑定到其他账号或设备。请先在小程序中解绑原设备；如需协助请联系客服。',
  invalid: '这把许可证当前不可用（可能已过期、被停用或已退还）。请在小程序中确认许可证状态，或联系客服。',
}

export default function PairPage() {
  const [code, setCode] = useState<string>('')
  const [qrUrl, setQrUrl] = useState<string>('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [pairStatus, setPairStatus] = useState<PairStatus | null>(null)
  const pollTimer = useRef<ReturnType<typeof setInterval> | null>(null)

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
    if (pollTimer.current) clearInterval(pollTimer.current)
    // ②（2026-09-21）：只在真正的终态停止轮询。原先 matched 就停，而
    // "激活成功/被拒"都发生在 matched 之后 —— 于是页面永远停在「正在激活...」。
    // 若在 matched 后停轮询，rejected 就永远不可能被看到。
    const TERMINAL = ['activated', 'rejected', 'expired']
    pollTimer.current = setInterval(async () => {
      try {
        const res = await Taro.request({
          url: `${BASIC_API}/api/v1/pair/status?code=${pairCode}`,
          method: 'GET',
        })
        const data = (res.data as any)
        if (data?.status && (data.status === 'matched' || TERMINAL.includes(data.status))) {
          setPairStatus(data)
          if (TERMINAL.includes(data.status) && pollTimer.current) {
            clearInterval(pollTimer.current)
            pollTimer.current = null
          }
        }
      } catch {
        // ignore polling errors
      }
    }, 3000)
  }

  useEffect(() => {
    initPair()
    return () => {
      if (pollTimer.current) clearInterval(pollTimer.current)
    }
  }, [])

  const statusText: Record<string, string> = {
    pending: '等待小程序扫码配对...',
    matched: '配对成功！正在激活...',
    activated: '激活成功！',
    expired: '配对码已过期，请重新生成',
    rejected: '许可证未能激活',
  }

  const statusClass: Record<string, string> = {
    pending: 'status-pending',
    matched: 'status-success',
    activated: 'status-success',
    expired: 'status-expired',
    rejected: 'status-rejected',
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

            {/* 凭据被拒：给出下一步动作，且不回显任何许可证内容 */}
            {pairStatus?.status === 'rejected' && (
              <View className='pair-rejected-guide'>
                <Text className='pair-rejected-hint'>
                  {REJECTED_HINT[pairStatus.rejected_kind || 'invalid'] || REJECTED_HINT.invalid}
                </Text>
              </View>
            )}

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
