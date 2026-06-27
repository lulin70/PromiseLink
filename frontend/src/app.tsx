import { PropsWithChildren, useEffect, useState } from 'react'
import { View, Text, Image } from '@tarojs/components'
import Taro from '@tarojs/taro'
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
      <View
        className={`pl-nav-item pl-nav-mine ${activePath.includes('/pages/mine') ? 'active' : ''}`}
        onClick={() => Taro.navigateTo({ url: '/pages/mine/index' })}
      >
        <View className='pl-nav-mine-avatar'>
          <Text className='pl-nav-mine-text'>我</Text>
        </View>
        <Text className='pl-nav-label'>我的</Text>
      </View>
    </View>
  )
}

// DesktopDetailBar removed (Q1): the right-side detail column was only fetching
// real data on the event detail page, showing placeholder text on all other pages.
// Removed to simplify the desktop layout to 2-column (sidebar + content).

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
      <Guide visible={guideVisible} onClose={handleGuideClose} />
    </View>
  )
}

export default App
