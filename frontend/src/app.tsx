import { PropsWithChildren, useEffect, useState } from 'react'
import { View, Text } from '@tarojs/components'
import Taro from '@tarojs/taro'
import './app.scss'

// Desktop navigation items (mirrors tabBar config in app.config.ts)
const NAV_ITEMS = [
  { path: '/pages/index/index', label: '首页', icon: '🏠' },
  { path: '/pages/events/index', label: '事件', icon: '📅' },
  { path: '/pages/entities/index', label: '人脉', icon: '👥' },
  { path: '/pages/todos/index', label: '待办', icon: '✓' },
  { path: '/pages/promises/index', label: '承诺', icon: '🤝' },
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
      </View>
      <View className='pl-nav'>
        {NAV_ITEMS.map(item => (
          <View
            key={item.path}
            className={`pl-nav-item ${activePath.includes(item.path) ? 'active' : ''}`}
            onClick={() => handleNav(item.path)}
          >
            <Text className='pl-nav-icon'>{item.icon}</Text>
            <Text className='pl-nav-label'>{item.label}</Text>
          </View>
        ))}
      </View>
    </View>
  )
}

function App({ children }: PropsWithChildren) {
  const isDesktop = useIsDesktop()

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

  return (
    <View className={`pl-app ${isDesktop ? 'pl-desktop' : ''}`}>
      {isDesktop && <DesktopSidebar />}
      <View className='pl-app-content'>
        {children}
      </View>
    </View>
  )
}

export default App
