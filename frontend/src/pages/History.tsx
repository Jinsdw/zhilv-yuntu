import { Button, Empty, Flex, Typography } from 'antd'
import { useNavigate } from 'react-router-dom'

import { ROUTES } from '@/router/routes'

/**
 * 历史页（8.3.3）：历史行程列表。
 * 筛选 / 分页 / 删除按 DESIGN.md 3.4 的组件树在 8.3 接入。
 */
export default function History() {
  const navigate = useNavigate()

  return (
    <Flex vertical align="center" justify="center" style={{ minHeight: '60vh' }} gap={8}>
      <Empty
        image={Empty.PRESENTED_IMAGE_SIMPLE}
        description={
          <Typography.Text type="secondary">暂无历史记录，生成过的行程会保存在这里。</Typography.Text>
        }
      >
        <Button type="primary" onClick={() => navigate(ROUTES.home)}>
          去规划行程
        </Button>
      </Empty>
    </Flex>
  )
}