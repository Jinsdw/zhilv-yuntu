/**
 * 8.3.4 风格偏好字段：Segmented 旅行风格 + Select 预算等级 + Select 天气偏好
 * 选项文本集中在 constants/options.ts，组件内不散落枚举文案。
 */

import { Flex, Form, Segmented, Select } from 'antd'

import {
  BUDGET_LEVEL_OPTIONS,
  TRAVEL_STYLE_OPTIONS,
  WEATHER_PREFERENCE_OPTIONS,
} from '@/constants/options'

export default function StyleField() {
  return (
    <Flex wrap gap={32} align="flex-start">
      <Form.Item name="travel_style" label="旅行节奏" style={{ marginBottom: 16 }}>
        <Segmented options={TRAVEL_STYLE_OPTIONS} />
      </Form.Item>

      <Form.Item name="budget_level" label="预算等级" style={{ marginBottom: 16 }}>
        <Select options={BUDGET_LEVEL_OPTIONS} style={{ width: 140 }} />
      </Form.Item>

      <Form.Item name="weather_preference" label="天气偏好" style={{ marginBottom: 16 }}>
        <Select options={WEATHER_PREFERENCE_OPTIONS} style={{ width: 140 }} />
      </Form.Item>
    </Flex>
  )
}