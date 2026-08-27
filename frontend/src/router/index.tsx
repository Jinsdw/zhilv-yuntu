import { Suspense, lazy, type ReactNode } from 'react'

import { Navigate, createBrowserRouter } from 'react-router-dom'

import PageLoading from '@/components/PageLoading'
import AppLayout from '@/layouts/AppLayout'

const Home = lazy(() => import('@/pages/Home'))
const Result = lazy(() => import('@/pages/Result'))
const History = lazy(() => import('@/pages/History'))
const NotFound = lazy(() => import('@/pages/NotFound'))

/** 路由懒加载：模块加载期间展示整页加载态 */
function lazyPage(node: ReactNode) {
  return <Suspense fallback={<PageLoading />}>{node}</Suspense>
}

export const router = createBrowserRouter([
  {
    path: '/',
    element: <AppLayout />,
    children: [
      { index: true, element: <Navigate to="/home" replace /> },
      { path: 'home', element: lazyPage(<Home />) },
      { path: 'result', element: lazyPage(<Result />) },
      { path: 'history', element: lazyPage(<History />) },
      { path: '*', element: lazyPage(<NotFound />) },
    ],
  },
])