/**
 * 8.3.1 规划页：目的地与偏好输入（按 DESIGN.md 3.2 组件树组装）。
 * 生成成功后写入 sessionStorage 快照并跳转结果页。
 */

import { useState } from 'react'

import { Alert, App as AntdApp, Card, Flex, Form, Tag, Typography } from 'antd'
import { useNavigate } from 'react-router-dom'

import TripPlannerForm, { type TripFormValues } from '@/components/trip/TripPlannerForm'
import { PRESET_CITIES } from '@/constants/options'
import { ROUTES } from '@/router/routes'
import { ApiError, tripApi } from '@/services/api'
import type { TripRequest, TripResponse } from '@/types'
import { toErrorMessage } from '@/utils/error'
import { writeTripSnapshot } from '@/utils/snapshot'

export default function Home() {
  const { message } = AntdApp.useApp()
  const navigate = useNavigate()
  const [form] = Form.useForm<TripFormValues>()
  const [generating, setGenerating] = useState(false)
  const [cityError, setCityError] = useState<string | null>(null)

  const handleGenerate = async (request: TripRequest) => {
    setGenerating(true)
    setCityError(null)
    try {
      const trip: TripResponse = await tripApi.generate(request)
      writeTripSnapshot({ trip, request })
      navigate(ROUTES.result, { state: { trip, request } })
    } catch (error) {
      // C 级目的地（省级等不受支持）内联提示，其余错误 toast
      if (error instanceof ApiError && error.code === 'CITY_NOT_SUPPORTED') {
        setCityError(toErrorMessage(error, '该目的地暂不支持，请尝试具体城市'))
      } else {
        message.error(toErrorMessage(error, '生成失败，请稍后重试'))
      }
      setGenerating(false)
    }
  }

  const fillPreset = (city: string) => {
    form.setFieldsValue({ destination: city })
    message.success(`已填入 ${city}，可调整日期与偏好后生成`)
  }

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

      {cityError && (
        <Alert
          type="error"
          showIcon
          message="目的地暂不支持"
          description={cityError}
          closable
          onClose={() => setCityError(null)}
        />
      )}

      <Card
        title="行程规划表单"
        extra={
          <Flex wrap gap={4} align="center">
            <Typography.Text type="secondary" style={{ fontSize: 12, marginRight: 4 }}>
              沉淀城市快捷填入：
            </Typography.Text>
            {PRESET_CITIES.map((city) => (
              <Tag
                key={city}
                color="cyan"
                style={{ cursor: 'pointer', paddingInline: 10, paddingBlock: 2 }}
                onClick={() => fillPreset(city)}
              >
                {city}
              </Tag>
            ))}
          </Flex>
        }
        styles={{ body: { padding: 24 } }}
      >
        <TripPlannerForm
          busy={generating}
          form={form}
          onSubmit={handleGenerate}
          onReset={() => setCityError(null)}
        />
      </Card>
    </Flex>
  )
}