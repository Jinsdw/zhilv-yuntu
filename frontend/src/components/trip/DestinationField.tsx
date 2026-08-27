/**
 * 8.3.4 目的地字段：AutoComplete 输入 + 城市分级 Tag（A/B/C 提示）
 * 城市分级为前端轻量预估（estimateCityLevel），最终以后端解析为准。
 */

import { Form, AutoComplete, Tag } from 'antd'
import { useWatch } from 'antd/es/form/Form'

import { CITY_LEVEL_META, COMMON_CITIES, estimateCityLevel } from '@/constants/options'

export default function DestinationField() {
  const destination = useWatch('destination', Form.useFormInstance()) as string | undefined

  const level = estimateCityLevel(destination ?? '')
  const levelMeta = CITY_LEVEL_META[level]

  return (
    <Form.Item
      name="destination"
      label="目的地"
      rules={[{ required: true, whitespace: true, message: '请输入目的地' }]}
      extra={
        destination ? (
          <span>
            <Tag color={levelMeta.color} style={{ marginInlineEnd: 4 }}>
              {levelMeta.label}
            </Tag>
            {levelMeta.hint}
          </span>
        ) : (
          '支持城市名，如“北京”“杭州”'
        )
      }
    >
      <AutoComplete
        options={COMMON_CITIES.map((city) => ({ value: city }))}
        placeholder="输入目的地，如：北京、大理、杭州"
        allowClear
        filterOption={(input, option) => String(option?.value ?? '').includes(input.trim())}
      />
    </Form.Item>
  )
}