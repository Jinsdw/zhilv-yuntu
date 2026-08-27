import { useMemo } from 'react'

import { ConfigProvider } from 'antd'
import { RouterProvider } from 'react-router-dom'

import { router } from './router'
import { buildTheme } from './theme'
import { ThemeProvider, useThemeMode } from './theme/ThemeContext'

/** 主题随明暗模式动态切换的应用主体 */
function ThemedApp() {
  const { dark } = useThemeMode()
  const theme = useMemo(() => buildTheme(dark), [dark])

  return (
    <ConfigProvider theme={theme}>
      <RouterProvider router={router} />
    </ConfigProvider>
  )
}

export default function App() {
  return (
    <ThemeProvider>
      <ThemedApp />
    </ThemeProvider>
  )
}