/**
 * 地图面板占位：正式 AmapTripMap 组件在 8.4（高德 JS API 集成）接入。
 * 面板结构先落位（点位列表 Drawer 由 8.4 填充），避免结果页后续返工。
 */

import { EnvironmentOutlined } from '@ant-design/icons'
import { Alert, Card, Flex, theme } from 'antd'

interface MapPanelProps {
  /** 可展示的点位（8.4 接入后使用） */
  places?: Array<{ name: string; coordinate: { latitude: number; longitude: number } }>
}

export default function MapPanel(_props: MapPanelProps) {
  const { token } = theme.useToken()

  return (
    <Card
      title={
        <Flex align="center" gap={8}>
          <EnvironmentOutlined />
          地图
        </Flex>
      }
    >
      <Flex
        align="center"
        justify="center"
        style={{ minHeight: 260, borderRadius: 12, background: token.colorFillTertiary }}
      >
        <Alert
          type="info"
          showIcon
          message="地图可视化将在 8.4 接入"
          description="届时展示景点标记、路线规划与信息窗体（高德 JavaScript API）。"
        />
      </Flex>
    </Card>
  )
}