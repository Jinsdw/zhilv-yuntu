import { CompassOutlined } from '@ant-design/icons'
import { Button, Flex, Typography, theme } from 'antd'
import { useNavigate } from 'react-router-dom'

import { ROUTES } from '@/router/routes'

/** 404 兜底页：旅行迷路主题 */
export default function NotFound() {
  const navigate = useNavigate()
  const { token } = theme.useToken()

  return (
    <Flex vertical align="center" justify="center" gap={12} style={{ minHeight: '55vh', textAlign: 'center' }}>
      <Flex
        align="center"
        justify="center"
        style={{
          width: 72,
          height: 72,
          borderRadius: 24,
          background: 'linear-gradient(135deg, #C0472F, #E8A33D)',
          color: '#fff',
          fontSize: 30,
          boxShadow: '0 8px 24px rgba(192,71,47,0.3)',
        }}
      >
        <CompassOutlined />
      </Flex>
      <Typography.Text strong className="zl-serif" style={{ fontSize: 22, color: token.colorText }}>
        404 · 迷路了
      </Typography.Text>
      <Typography.Text type="secondary" style={{ maxWidth: 380 }}>
        这个页面像没打通的航线一样不存在，或者已经被移动到别处了。
      </Typography.Text>
      <Button type="primary" size="large" style={{ borderRadius: 999, marginTop: 8 }} onClick={() => navigate(ROUTES.home)}>
        返回规划首页
      </Button>
    </Flex>
  )
}
