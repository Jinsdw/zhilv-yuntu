/**
 * 8.3.4 行程日期字段：DatePicker.RangePicker（start/end 互校验，过去日期禁止选择）
 * 表单内使用 dayjs 值，提交时由 TripPlannerForm 统一转为 ISO 字符串。
 */

import { Form } from 'antd'
import DatePicker from 'antd/es/date-picker'
import dayjs, { type Dayjs } from 'dayjs'

export default function DateRangeField() {
  return (
    <Form.Item
      name="dateRange"
      label="行程日期"
      rules={[{ required: true, message: '请选择行程日期' }]}
    >
      <DatePicker.RangePicker
        style={{ width: '100%' }}
        disabledDate={(date: Dayjs) => date.isBefore(dayjs().startOf('day'))}
        allowClear={false}
      />
    </Form.Item>
  )
}