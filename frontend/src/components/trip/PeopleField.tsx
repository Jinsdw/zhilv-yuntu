/**
 * 8.3.4 出行人数字段：InputNumber 人数 + 同行状态（儿童/老人/行动不便）
 */

import { Form, Flex, InputNumber, Switch, Typography } from 'antd'

/** 同行状态开关配置：name 对应 TripRequest 字段 */
const COMPANION_SWITCHES = [
  { name: 'with_kids', label: '携带儿童' },
  { name: 'with_elderly', label: '携带老人' },
  { name: 'has_disability', label: '行动不便' },
] as const

export default function PeopleField() {
  return (
    <Flex wrap gap={24} align="flex-start">
      <Form.Item name="travelers" label="出行人数" initialValue={2} style={{ marginBottom: 16 }}>
        <InputNumber min={1} max={20} precision={0} style={{ width: 120 }} />
      </Form.Item>

      <Form.Item label="同行状态" style={{ marginBottom: 16 }}>
        <Flex wrap gap={16}>
          {COMPANION_SWITCHES.map((item) => (
            <Flex key={item.name} align="center" gap={6}>
              <Form.Item name={item.name} valuePropName="checked" noStyle>
                <Switch size="small" />
              </Form.Item>
              <Typography.Text type="secondary" style={{ fontSize: 13 }}>
                {item.label}
              </Typography.Text>
            </Flex>
          ))}
        </Flex>
      </Form.Item>
    </Flex>
  )
}
