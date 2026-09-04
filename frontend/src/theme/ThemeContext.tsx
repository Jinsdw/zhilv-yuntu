import { createContext, useContext, useEffect, useState, type ReactNode } from 'react'

interface ThemeModeContextValue {
  dark: boolean
  toggle: () => void
}

const ThemeModeContext = createContext<ThemeModeContextValue>({
  dark: false,
  toggle: () => undefined,
})

const STORAGE_KEY = 'zhilv-yuntu:theme'

/** 初始值：优先读 localStorage，其次跟随系统 prefers-color-scheme */
function readInitial(): boolean {
  const saved = localStorage.getItem(STORAGE_KEY)
  if (saved === 'dark' || saved === 'light') {
    return saved === 'dark'
  }
  return window.matchMedia('(prefers-color-scheme: dark)').matches
}

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [dark, setDark] = useState<boolean>(readInitial)

  useEffect(() => {
    localStorage.setItem(STORAGE_KEY, dark ? 'dark' : 'light')
    // 同步根节点 data-theme，驱动 global.css 的纸张/暖墨变量
    document.documentElement.setAttribute('data-theme', dark ? 'dark' : 'light')
  }, [dark])

  return (
    <ThemeModeContext.Provider value={{ dark, toggle: () => setDark((v) => !v) }}>
      {children}
    </ThemeModeContext.Provider>
  )
}

export function useThemeMode() {
  return useContext(ThemeModeContext)
}
