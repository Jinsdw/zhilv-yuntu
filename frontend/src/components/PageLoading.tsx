import { Flex, Spin, Typography } from 'antd'

/** 路由懒加载的整页加载态 */
export default function PageLoading() {
  return (
    <Flex vertical align="center" justify="center" gap={16} style={{ minHeight: '55vh' }}>
      <Spin size="large" />
      <Typography.Text type="secondary">加载中...</Typography.Text>
    </Flex>
  )
}