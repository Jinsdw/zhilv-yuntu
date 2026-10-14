/**
 * 8.3.1 规划页：目的地与偏好输入（按 DESIGN.md 3.2 组件树组装）。
 * v2 山海拾光：Hero 杂志式首屏 + 快捷城市胶囊 + 分区表单卡片。
 * 生成成功后写入 sessionStorage 快照并跳转结果页。
 */

import { useRef, useState } from 'react'

import { Alert, App as AntdApp, Card, Flex, Form, Tag, Typography, theme } from 'antd'
import { useNavigate } from 'react-router-dom'

import TripPlannerForm, { type TripFormValues } from '@/components/trip/TripPlannerForm'
import type { LiveDayItem, LiveStreamState } from '@/components/trip/LiveGenerationPanel'
import { PRESET_CITIES } from '@/constants/options'
import { ROUTES } from '@/router/routes'
import { ApiError, tripApi } from '@/services/api'
import type { PreviewCandidate, StreamEvent, TripPreviewResponse, TripRequest, TripResponse } from '@/types'
import { toErrorMessage } from '@/utils/error'
import { writeTripSnapshot } from '@/utils/snapshot'

export default function Home() {
  const { message } = AntdApp.useApp()
  const navigate = useNavigate()
  const { token } = theme.useToken()
  const [form] = Form.useForm<TripFormValues>()
  const [generating, setGenerating] = useState(false)
  const [cityError, setCityError] = useState<string | null>(null)
  /** 12.1 方案 A：预览候选图（生成等待期展示，失败不阻断） */
  const [preview, setPreview] = useState<TripPreviewResponse | null>(null)
  /** 12.2 方案 B：SSE 流式实时状态（事件驱动） */
  const [liveStream, setLiveStream] = useState<LiveStreamState | null>(null)
  /** 图片墙去重：preview 种子与 poi 事件按 分类+名称 合并 */
  const seenRef = useRef<Set<string>>(new Set())

  const appendCandidates = (items: PreviewCandidate[]) => {
    const fresh = items.filter((candidate) => {
      const key = `${candidate.category}-${candidate.name}`
      if (seenRef.current.has(key)) return false
      seenRef.current.add(key)
      return true
    })
    if (fresh.length === 0) return
    setLiveStream((prev) =>
      prev ? { ...prev, candidates: [...prev.candidates, ...fresh] } : prev,
    )
  }

  const handleStreamEvent = (event: StreamEvent) => {
    switch (event.type) {
      case 'status':
        setLiveStream((prev) =>
          prev
            ? {
                ...prev,
                stage: event.stage,
                message: event.message,
                progress: event.progress,
                // 13.5.2 day_generating：记录当前生成中的天，供「第 N/M 天生成中」文案
                currentDay:
                  event.stage === 'day_generating' && event.day_number && event.total_days
                    ? { day_number: event.day_number, total_days: event.total_days }
                    : prev.currentDay,
              }
            : prev,
        )
        break
      case 'poi':
        appendCandidates(event.items)
        break
      case 'draft':
        setLiveStream((prev) =>
          prev ? { ...prev, draft: { days: event.days, highlights: event.highlights } } : prev,
        )
        break
      case 'day': {
        // 13.5.1 day 事件累积：draft → enriched 原地升级；enriched 从整份 ItineraryDay 取地点链
        const item: LiveDayItem =
          event.state === 'enriched' && event.day
            ? {
                day_number: event.day_number,
                state: 'enriched',
                theme: event.day.day_theme ?? event.theme ?? null,
                places: event.day.items.map((it) => it.place.name),
                day_summary: event.day_summary ?? null,
              }
            : {
                day_number: event.day_number,
                state: 'draft',
                theme: event.theme ?? null,
                places: event.places ?? [],
                day_summary: event.day_summary ?? null,
              }
        setLiveStream((prev) => {
          if (!prev) return prev
          const existing = prev.days.find((d) => d.day_number === item.day_number)
          const merged = existing
            ? { ...item, day_summary: item.day_summary ?? existing.day_summary }
            : item
          const days = existing
            ? prev.days.map((d) => (d.day_number === item.day_number ? merged : d))
            : [...prev.days, merged].sort((a, b) => a.day_number - b.day_number)
          return {
            ...prev,
            days,
            currentDay: null,
            // 13.5.2 天完成后清空 currentDay，避免面板误显示「生成中」（等待下一天 day_generating 状态）
            message: `第 ${event.day_number}/${event.total_days} 天已完成`,
            progress: Math.min(95, Math.round(45 + (event.day_number / event.total_days) * 50)),
          }
        })
        break
      }
      default:
        break
    }
  }

  const startPreview = (request: TripRequest) => {
    tripApi
      .preview(request)
      .then((res) => {
        setPreview(res)
        appendCandidates(res.candidates)
      })
      .catch(() => setPreview(null))
  }

  const navigateToResult = (trip: TripResponse, request: TripRequest) => {
    writeTripSnapshot({ trip, request })
    navigate(ROUTES.result, { state: { trip, request } })
  }

  const handleGenerate = async (request: TripRequest) => {
    setGenerating(true)
    setCityError(null)
    setPreview(null)
    seenRef.current = new Set()
    setLiveStream({ candidates: [], stage: 'init', message: '正在连接生成服务…', progress: 0, draft: null, days: [], currentDay: null })
    // 12.1 预览并行拉取：流式开始前先出图；失败静默降级
    startPreview(request)

    try {
      // 12.2 优先走 SSE 流式：status/poi/draft/day 逐帧更新实时面板（13.5.1 day 事件累积渲染）
      const trip: TripResponse = await tripApi.generateStream(request, handleStreamEvent)
      navigateToResult(trip, request)
      return
    } catch (error) {
      if (error instanceof ApiError && error.code === 'CITY_NOT_SUPPORTED') {
        setCityError(toErrorMessage(error, '该目的地暂不支持，请尝试具体城市'))
      } else {
        if (error instanceof ApiError && error.isNetworkError) {
          // 12.2.8 流式通道失败 → 降级为普通 generate（不重复提示业务错误）
          message.warning('实时生成通道不可用，已切换为普通模式')
          try {
            const trip: TripResponse = await tripApi.generate(request)
            navigateToResult(trip, request)
            return
          } catch (fallbackError) {
            if (fallbackError instanceof ApiError && fallbackError.code === 'CITY_NOT_SUPPORTED') {
              setCityError(toErrorMessage(fallbackError, '该目的地暂不支持，请尝试具体城市'))
            } else {
              message.error(toErrorMessage(fallbackError, '生成失败，请稍后重试'))
            }
            setLiveStream(null)
            setGenerating(false)
            return
          }
        }
        message.error(toErrorMessage(error, '生成失败，请稍后重试'))
      }
      setLiveStream(null)
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
            共赴山海，不负时光。
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
          previewCandidates={preview?.candidates}
          liveStream={liveStream}
          form={form}
          onSubmit={handleGenerate}
          onReset={() => setCityError(null)}
        />
      </Card>
    </Flex>
  )
}
