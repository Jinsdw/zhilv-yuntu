/**
 * 8.3.1 规划页：目的地与偏好输入（按 DESIGN.md 3.2 组件树组装）。
 * v2 山海拾光：Hero 杂志式首屏 + 快捷城市胶囊 + 分区表单卡片。
 * 生成成功后写入 sessionStorage 快照并跳转结果页。
 */

import { useState } from 'react'

import { Alert, App as AntdApp, Card, Flex, Form, Tag, Typography, theme } from 'antd'
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
  const { token } = theme.useToken()
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
    <Flex vertical gap={28}>
      {/* Hero：杂志式首屏 */}
      <div className="zl-hero" style={{ padding: '44px 48px' }}>
        <Flex vertical gap={14}>
          <Tag
            color="gold"
            style={{
              alignSelf: 'flex-start',
              borderRadius: 999,
              paddingInline: 14,
              fontSize: 12,
            }}
          >
            多 Agent 协同 · 高德地图 · 天气 · 预算
          </Tag>
          <Typography.Title
            level={1}
            className="zl-serif zl-ink"
            style={{ marginBottom: 0, fontSize: 40, lineHeight: 1.25 }}
          >
            把想去的远方，
            <br />
            排成一天天的好日子。
          </Typography.Title>
          <Typography.Paragraph
            type="secondary"
            style={{ marginBottom: 0, fontSize: 15, maxWidth: 560 }}
          >
            输入目的地、日期与偏好，AI 自动生成每日行程、地图点位、天气与预算，
            还能随时导出为 Markdown 或 PDF。
          </Typography.Paragraph>
          <Flex wrap gap={8} align="center" style={{ marginTop: 8 }}>
            <Typography.Text type="secondary" style={{ fontSize: 13 }}>
              沉淀城市快捷填入
            </Typography.Text>
            {PRESET_CITIES.map((city, index) => (
              <Tag
                key={city}
                bordered
                style={{
                  cursor: 'pointer',
                  borderRadius: 999,
                  paddingInline: 14,
                  paddingBlock: 4,
                  fontSize: 13,
                  background: index % 2 === 0 ? 'rgba(192,71,47,0.10)' : 'rgba(232,163,61,0.16)',
                  color: token.colorPrimary,
                  borderColor: 'rgba(192,71,47,0.22)',
                }}
                onClick={() => fillPreset(city)}
              >
                {city}
              </Tag>
            ))}
          </Flex>
        </Flex>
      </div>

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
        className="zl-paper-card"
        styles={{ body: { padding: 28 } }}
      >
        <Flex vertical gap={4} style={{ marginBottom: 20 }}>
          <Typography.Text type="secondary" style={{ fontSize: 12, letterSpacing: '0.1em' }}>
            PLAN YOUR TRIP
          </Typography.Text>
          <Typography.Title level={3} className="zl-serif" style={{ marginBottom: 0 }}>
            开始规划
          </Typography.Title>
          <Typography.Paragraph type="secondary" style={{ marginBottom: 0, fontSize: 13 }}>
            先定下目的地与日期，再把节奏、预算和偏好交给我们。
          </Typography.Paragraph>
        </Flex>
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
