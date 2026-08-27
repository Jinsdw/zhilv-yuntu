import { Button, Result } from 'antd'
import { useNavigate } from 'react-router-dom'

import { ROUTES } from '@/router/routes'

/** 404 兜底页 */
export default function NotFound() {
  const navigate = useNavigate()

  return (
    <Result
      status="404"
      title="404"
      subTitle="页面不存在或已被移动。"
      extra={
        <Button type="primary" onClick={() => navigate(ROUTES.home)}>
          返回首页
        </Button>
      }
    />
  )
}