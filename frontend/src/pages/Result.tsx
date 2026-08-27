import { Button, Empty, Flex, Typography } from 'antd'
import { useNavigate } from 'react-router-dom'

import { ROUTES } from '@/router/routes'

/**
 * 结果页（8.3.2）：行程方案展示。
 * 时间轴 / 地图 / 天气 / 预算面板按 DESIGN.md 3.3 的组件树在 8.3 接入。
 */
export default function Result() {
  const navigate = useNavigate()

  return (
    <Flex vertical align="center" justify="center" style={{ minHeight: '60vh' }} gap={8}>
      <Empty
        image={Empty.PRESENTED_IMAGE_SIMPLE}
        description={
          <Typography.Text type="secondary">还没有行程方案，先去规划页生成一份吧。</Typography.Text>
        }
      >
        <Button type="primary" onClick={() => navigate(ROUTES.home)}>
          去规划行程
        </Button>
      </Empty>
    </Flex>
  )
}