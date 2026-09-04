/**
 * 8.3.4 高级选项折叠：每日预算上限 / 每日景点上限 / 餐标 / 景点室内外类型 / 备注
 * 注意：备注字段后端 TripRequest 暂无对应属性（schema 8.1 建立），
 * 当前仅在正式请求时忽略该字段，保留输入供后续接入（见 TripPlannerForm 提交逻辑）。
 */

import { Checkbox, Flex, Form, Input, InputNumber, Typography } from 'antd'

export default function AdvancedCollapse() {
  return (
    <Flex vertical gap={0}>
      <Flex wrap gap={24}>
        <Form.Item name="daily_budget" label="每日预算上限（元）" style={{ marginBottom: 16 }}>
          <InputNumber min={0} placeholder="不限" style={{ width: 160 }} />
        </Form.Item>
        <Form.Item name="max_places_per_day" label="每日最多景点数" style={{ marginBottom: 16 }}>
          <InputNumber min={1} max={10} precision={0} style={{ width: 160 }} />
        </Form.Item>
        <Form.Item
          name="restaurant_budget_per_meal"
          label="每餐餐饮预算（元）"
          style={{ marginBottom: 16 }}
        >
          <InputNumber min={0} precision={0} style={{ width: 160 }} />
        </Form.Item>
      </Flex>

      <Flex wrap gap={24} style={{ marginBottom: 16 }}>
        <Form.Item name="include_indoor" valuePropName="checked" style={{ marginBottom: 0 }}>
          <Checkbox>包含室内景点</Checkbox>
        </Form.Item>
        <Form.Item name="include_outdoor" valuePropName="checked" style={{ marginBottom: 0 }}>
          <Checkbox>包含室外景点</Checkbox>
        </Form.Item>
        <Typography.Text type="secondary" style={{ alignSelf: 'center', fontSize: 12 }}>
          室内/室外类型跟随行程默认建议，可在此手动指定
        </Typography.Text>
      </Flex>

      <Form.Item name="note" label="备注" style={{ marginBottom: 0 }}>
        <Input.TextArea
          rows={2}
          maxLength={200}
          showCount
          placeholder="补充说明或特殊需求，如“尽量避开周一闭馆的景点”（暂未发送至后端）"
        />
      </Form.Item>
    </Flex>
  )
}
