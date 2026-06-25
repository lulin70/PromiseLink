import { PropsWithChildren, useEffect, useState } from 'react'
import { View, Text, Image } from '@tarojs/components'
import Taro from '@tarojs/taro'
import { getEventDetail } from './services/api'
import { isLoggedIn } from './services/auth'
import Guide from './components/Guide/Guide'
import homeIcon from './icons/home.png'
import homeActiveIcon from './icons/home-active.png'
import eventsIcon from './icons/events.png'
import eventsActiveIcon from './icons/events-active.png'
import peopleIcon from './icons/people.png'
import peopleActiveIcon from './icons/people-active.png'
import todoIcon from './icons/todo.png'
import todoActiveIcon from './icons/todo-active.png'
import promiseIcon from './icons/promise.png'
import promiseActiveIcon from './icons/promise-active.png'
import './app.scss'

const GUIDE_STORAGE_KEY = 'guide_shown'

// Desktop navigation items (mirrors tabBar config in app.config.ts)
const NAV_ITEMS = [
  { path: '/pages/index/index', label: '首页', icon: homeIcon, activeIcon: homeActiveIcon },
  { path: '/pages/events/index', label: '事件', icon: eventsIcon, activeIcon: eventsActiveIcon },
  { path: '/pages/entities/index', label: '人脉', icon: peopleIcon, activeIcon: peopleActiveIcon },
  { path: '/pages/todos/index', label: '待办', icon: todoIcon, activeIcon: todoActiveIcon },
  { path: '/pages/promises/index', label: '承诺', icon: promiseIcon, activeIcon: promiseActiveIcon },
]

// Event type labels for detail summary
const EVENT_TYPE_LABELS: Record<string, string> = {
  manual: '手动录入',
  meeting: '会议',
  call: '电话',
  wechat_forward: '微信转发',
  email: '邮件',
  card_save: '名片',
}

function getCurrentPath(): string {
  if (typeof window === 'undefined') return ''
  return window.location.pathname
}

// Detect desktop viewport (≥1024px)
function useIsDesktop(): boolean {
  const [isDesktop, setIsDesktop] = useState(() =>
    typeof window !== 'undefined' ? window.innerWidth >= 1024 : false
  )
  useEffect(() => {
    const handler = () => setIsDesktop(window.innerWidth >= 1024)
    window.addEventListener('resize', handler)
    return () => window.removeEventListener('resize', handler)
  }, [])
  return isDesktop
}

// Desktop vertical sidebar navigation
function DesktopSidebar() {
  const [activePath, setActivePath] = useState(getCurrentPath())

  useEffect(() => {
    const handler = () => setActivePath(getCurrentPath())
    window.addEventListener('popstate', handler)
    // Poll for path changes (Taro H5 uses pushState which doesn't fire popstate)
    const interval = setInterval(handler, 400)
    return () => {
      window.removeEventListener('popstate', handler)
      clearInterval(interval)
    }
  }, [])

  const handleNav = (path: string) => {
    setActivePath(path)
    Taro.switchTab({ url: path })
  }

  return (
    <View className='pl-sidebar'>
      <View className='pl-sidebar-brand'>
        <Text className='pl-brand-text'>PromiseLink</Text>
        <Text className='pl-brand-edition'>基础版</Text>
      </View>
      <View className='pl-nav'>
        {NAV_ITEMS.map(item => {
          const isActive = activePath.includes(item.path)
          return (
            <View
              key={item.path}
              className={`pl-nav-item ${isActive ? 'active' : ''}`}
              onClick={() => handleNav(item.path)}
            >
              <Image className='pl-nav-icon' src={isActive ? item.activeIcon : item.icon} />
              <Text className='pl-nav-label'>{item.label}</Text>
            </View>
          )
        })}
      </View>
      <View className='pl-pro-guide'>
        <Text className='pl-pro-guide-title'>升级专业版</Text>
        <Text className='pl-pro-guide-desc'>解锁语音录入、邮件同步、OCR名片扫描等高级功能</Text>
        <View
          className='pl-pro-guide-btn'
          onClick={() => window.open('https://promiselink.com/pro', '_blank')}
        >
          <Text className='pl-pro-guide-btn-text'>了解详情</Text>
        </View>
      </View>
    </View>
  )
}

// Desktop right detail column - shows contextual summary based on current route
function DesktopDetailBar() {
  const [routePath, setRoutePath] = useState(getCurrentPath())
  const [summary, setSummary] = useState<{ title: string; rows: { label: string; value: string }[] } | null>(null)
  const [loading, setLoading] = useState(false)

  // Poll for route changes (Taro H5 uses pushState which doesn't fire popstate)
  useEffect(() => {
    const handler = () => setRoutePath(getCurrentPath())
    window.addEventListener('popstate', handler)
    const interval = setInterval(handler, 400)
    return () => {
      window.removeEventListener('popstate', handler)
      clearInterval(interval)
    }
  }, [])

  // Load contextual summary based on current route params
  useEffect(() => {
    let cancelled = false
    async function loadSummary() {
      setSummary(null)
      setLoading(false)

      // Use Taro.getCurrentInstance().router to read current route + params
      const instance = Taro.getCurrentInstance()
      const path = instance.router?.path || ''
      const params = instance.router?.params || {}

      // Event detail page: show event summary
      if (path.includes('/pages/events/detail') && params.id) {
        setLoading(true)
        try {
          const detail = await getEventDetail(params.id)
          if (cancelled) return
          setSummary({
            title: detail.title,
            rows: [
              { label: '类型', value: EVENT_TYPE_LABELS[detail.event_type] || detail.event_type },
              { label: '状态', value: detail.status },
              { label: '时间', value: new Date(detail.timestamp).toLocaleString('zh-CN') },
              { label: '人脉', value: `${detail.related_entities?.length || 0} 人` },
              { label: '待办', value: `${detail.related_todos?.length || 0} 条` },
            ],
          })
        } catch {
          // Auth or network error - fall through to empty state
        } finally {
          if (!cancelled) setLoading(false)
        }
      }
    }
    loadSummary()
    return () => { cancelled = true }
  }, [routePath])

  return (
    <View className='pl-detail'>
      {summary ? (
        <View className='pl-detail-content'>
          <Text className='pl-detail-title'>{summary.title}</Text>
          {summary.rows.map((row, i) => (
            <View key={i} className='pl-detail-row'>
              <Text className='pl-detail-label'>{row.label}</Text>
              <Text className='pl-detail-value'>{row.value}</Text>
            </View>
          ))}
        </View>
      ) : loading ? (
        <View className='pl-detail-empty'>
          <Text className='pl-detail-empty-text'>加载中...</Text>
        </View>
      ) : (
        <View className='pl-detail-empty'>
          <Text className='pl-detail-empty-text'>选择一项查看详情摘要</Text>
        </View>
      )}
    </View>
  )
}

function App({ children }: PropsWithChildren) {
  const isDesktop = useIsDesktop()
  const [guideVisible, setGuideVisible] = useState(false)

  // Hide native TabBar on desktop, show on mobile
  useEffect(() => {
    try {
      if (isDesktop) {
        Taro.hideTabBar?.({ animation: false })
      } else {
        Taro.showTabBar?.({ animation: false })
      }
    } catch {
      // TabBar API may not be ready on first render; CSS handles fallback
    }
  }, [isDesktop])

  // Show first-time guide once logged in (token present) and not shown before.
  // Token is written by child pages (login), so we poll until login is detected
  // or until we find the guide was already completed.
  useEffect(() => {
    if (guideVisible) return

    let active = true
    let interval: ReturnType<typeof setInterval> | null = null

    function shouldKeepPolling(): boolean {
      if (!active) return false
      let shown = false
      try {
        shown = !!Taro.getStorageSync(GUIDE_STORAGE_KEY)
      } catch {
        shown = false
      }
      if (shown) return false
      if (isLoggedIn()) {
        setGuideVisible(true)
        return false
      }
      return true
    }

    if (!shouldKeepPolling()) {
      return () => { active = false }
    }

    interval = setInterval(() => {
      if (!shouldKeepPolling() && interval) {
        clearInterval(interval)
      }
    }, 800)

    return () => {
      active = false
      if (interval) clearInterval(interval)
    }
  }, [guideVisible])

  function handleGuideClose() {
    setGuideVisible(false)
  }

  return (
    <View className={`pl-app ${isDesktop ? 'pl-desktop' : ''}`}>
      {isDesktop && <DesktopSidebar />}
      <View className='pl-app-content'>
        {children}
      </View>
      {isDesktop && <DesktopDetailBar />}
      <Guide visible={guideVisible} onClose={handleGuideClose} />
    </View>
  )
}

export default App
