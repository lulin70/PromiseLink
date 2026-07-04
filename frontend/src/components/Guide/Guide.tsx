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
    title: '场景一：刚见完一位朋友',
    body: '与朋友喝完咖啡，打开 PromiseLink，把刚才聊到的内容用一段话记下来——谁说了什么、约定了什么、需要跟进什么。',
    hint: '不用纠结格式，自然语言即可，AI 会帮你整理。',
  },
  {
    title: '场景二：让 AI 帮你拆解',
    body: '录入后，AI 自动从你的描述中识别出"提到的人""需要做的待办""双方承诺"，并归到对应栏目。你只需在校正面板里确认或微调。',
    hint: '解析结果支持纠偏：人选错了可以重选，待办可以改截止时间。',
  },
  {
    title: '场景三：每天打开就知道做什么',
    body: '早上打开 App，首页"今日提醒"会按优先级告诉你今天该联系谁、跟进哪些事。批量处理几条，关系经营就不再"靠记忆"。',
    hint: '可在"我的 → 提醒偏好"里设置提醒时间和免打扰时段。',
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
