import { useState } from 'react'
import { View, Text } from '@tarojs/components'
import Taro from '@tarojs/taro'
import './Guide.scss'

interface GuideProps {
  visible: boolean
  onClose: () => void
}

interface GuideStep {
  title: string
  body: string
  hint?: string
}

const GUIDE_STEPS: GuideStep[] = [
  {
    title: '欢迎使用 PromiseLink',
    body: 'AI 驱动的个人商务关系经营助手。把每一次交流沉淀为人脉、待办与承诺，让关系经营有迹可循。',
  },
  {
    title: '两栏布局',
    body: '左栏为导航菜单（首页、事件、人脉、待办、承诺、我的），右侧展示主要内容。点击列表项可进入详情页。',
    hint: '建议在桌面端（宽度 ≥ 1024px）体验完整的两栏布局。',
  },
  {
    title: '记录交流',
    body: '点击首页的“录入”按钮（或右下角加号），即可记录一次重要交流，支持自然语言描述。',
  },
  {
    title: 'AI 解析',
    body: '录入后，AI 会自动从内容中提取人脉、待办与承诺，并归集到对应栏目，无需手动整理。',
    hint: '可在录入后的校正面板中调整 AI 的解析结果。',
  },
]

const STORAGE_KEY = 'guide_shown'

export default function Guide({ visible, onClose }: GuideProps) {
  const [step, setStep] = useState(0)

  if (!visible) return null

  // Defensive: never show if already completed before (e.g. another tab)
  try {
    if (Taro.getStorageSync(STORAGE_KEY)) {
      return null
    }
  } catch {
    // ignore storage read errors
  }

  const current = GUIDE_STEPS[step]
  const isLast = step === GUIDE_STEPS.length - 1

  function finish() {
    try {
      Taro.setStorageSync(STORAGE_KEY, true)
    } catch {
      // ignore storage write errors
    }
    setStep(0)
    onClose()
  }

  function handleNext() {
    if (isLast) {
      finish()
    } else {
      setStep(prev => prev + 1)
    }
  }

  function handlePrev() {
    if (step > 0) setStep(prev => prev - 1)
  }

  return (
    <View className='pl-guide-overlay'>
      <View className='pl-guide-card'>
        <View className='pl-guide-header'>
          <Text className='pl-guide-step-label'>第 {step + 1} 步 / 共 {GUIDE_STEPS.length} 步</Text>
          <Text className='pl-guide-skip' onClick={finish}>跳过</Text>
        </View>

        <View className='pl-guide-body'>
          <Text className='pl-guide-title'>{current.title}</Text>
          <Text className='pl-guide-text'>{current.body}</Text>
          {current.hint ? <Text className='pl-guide-hint'>{current.hint}</Text> : null}
        </View>

        <View className='pl-guide-dots'>
          {GUIDE_STEPS.map((_, idx) => (
            <View
              key={idx}
              className={`pl-guide-dot ${idx === step ? 'active' : ''}`}
            />
          ))}
        </View>

        <View className='pl-guide-actions'>
          {step > 0 ? (
            <View className='pl-guide-btn pl-guide-btn-ghost' onClick={handlePrev}>
              <Text className='pl-guide-btn-text'>上一步</Text>
            </View>
          ) : null}
          <View className='pl-guide-btn pl-guide-btn-primary' onClick={handleNext}>
            <Text className='pl-guide-btn-text'>{isLast ? '开始使用' : '下一步'}</Text>
          </View>
        </View>
      </View>
    </View>
  )
}
