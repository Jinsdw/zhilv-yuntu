/**
 * 8.3.4 偏好关键词字段：偏好 / 排除 两组标签输入（Select mode="tags"）
 */

import { Flex, Form, Select, Typography } from 'antd'

export default function KeywordsField() {
  return (
    <Flex wrap gap={24}>
      <Form.Item
        name="preferred_keywords"
        label="偏好关键词"
        style={{ marginBottom: 16, minWidth: 280 }}
      >
        <Select
          mode="tags"
          placeholder="如：历史、亲子、拍照、美食"
          tokenSeparators={[',', '，']}
          allowClear
        />
      </Form.Item>

      <Form.Item
        name="excluded_keywords"
        label="排除关键词"
        style={{ marginBottom: 16, minWidth: 280 }}
      >
        <Select
          mode="tags"
          placeholder="如：爬山、人多"
          tokenSeparators={[',', '，']}
          allowClear
        />
      </Form.Item>

      <Typography.Text type="secondary" style={{ alignSelf: 'center', fontSize: 12 }}>
        回车或逗号分隔多个关键词
      </Typography.Text>
    </Flex>
  )
}