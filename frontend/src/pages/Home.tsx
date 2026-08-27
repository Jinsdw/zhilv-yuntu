import { Alert, App as AntdApp, Card, Flex, Tag, Typography } from 'antd'

/** 沉淀城市（后端城市分级 A 级）：点击可快捷填入表单 */
const PRESET_CITIES = ['北京', '大理', '成都', '西安', '厦门', '三亚']

/**
 * 规划页（8.3.1）：目的地与偏好输入。
 * 当前为项目初始化骨架，表单组件按 DESIGN.md 3.2 的组件树在 8.3 接入。
 */
export default function Home() {
  const { message } = AntdApp.useApp()

  return (
    <Flex vertical gap={24}>
      <Flex vertical gap={8}>
        <Typography.Title level={2} style={{ marginBottom: 0 }}>
          规划你的下一次旅行
        </Typography.Title>
        <Typography.Paragraph type="secondary" style={{ marginBottom: 0 }}>
          输入目的地、日期与偏好，AI 自动生成每日行程、地图点位、天气与预算。
        </Typography.Paragraph>
      </Flex>

      <Card
        title="行程规划表单"
        extra={<Tag color="processing">骨架阶段</Tag>}
        styles={{ body: { padding: 20 } }}
      >
        <Flex vertical gap={12}>
          <Alert
            type="info"
            showIcon
            message="当前为项目初始化阶段（8.1）"
            description="表单、生成进度与结果展示将在后续阶段接入，此处先落地布局骨架与交互规范。"
          />
          <Typography.Text type="secondary">
            沉淀城市可直接体验本地攻略，点击快捷填入：
          </Typography.Text>
          <Flex wrap gap={8}>
            {PRESET_CITIES.map((city) => (
              <Tag
                key={city}
                color="cyan"
                style={{ cursor: 'pointer', paddingInline: 12, paddingBlock: 4 }}
                onClick={() => message.info(`即将填入 ${city}（表单 8.3 接入）`)}
              >
                {city}
              </Tag>
            ))}
          </Flex>
        </Flex>
      </Card>
    </Flex>
  )
}