/**
 * 8.3.2 结果页：行程方案展示（按 DESIGN.md 3.3 组件树组装）。
 * v2 山海拾光：行程封面 + 概览条 + 胶囊 Day 导航 + 两栏内容（时间线 / 天气预算）+ 地图。
 * 数据来源优先级：location.state（生成/编辑后跳转）→ URL ?trip_id=（历史回看，异步拉取）
 * → sessionStorage 快照（见 utils/snapshot.ts）。单日编辑成功后就地替换 trip 并更新快照。
 */

import { useEffect, useMemo, useState, type ReactNode } from 'react'

import {
  DownloadOutlined,
  EditOutlined,
  EnvironmentOutlined,
  HeartOutlined,
  LeftOutlined,
  ThunderboltOutlined,
  WalletOutlined,
} from '@ant-design/icons'
import {
  App as AntdApp,
  Button,
  Card,
  Dropdown,
  Empty,
  Flex,
  Spin,
  Tag,
  Typography,
  theme,
} from 'antd'
import { useLocation, useNavigate, useSearchParams } from 'react-router-dom'

import BudgetPanel from '@/components/budget/BudgetPanel'
import MapPanel from '@/components/map/MapPanel'
import DayTimeline from '@/components/trip/DayTimeline'
import EditDayModal from '@/components/trip/EditDayModal'
import WeatherPanel from '@/components/weather/WeatherPanel'
import { ROUTES } from '@/router/routes'
import { exportApi, tripApi } from '@/services/api'
import type { TripResponse } from '@/types'
import { toErrorMessage } from '@/utils/error'
import { formatDateCN, formatMoney } from '@/utils/format'
import { readTripSnapshot, writeTripSnapshot } from '@/utils/snapshot'

interface ResultLocationState {
  trip?: TripResponse
}

export default function Result() {
  const { message } = AntdApp.useApp()
  const navigate = useNavigate()
  const location = useLocation()
  const { token } = theme.useToken()
  const [searchParams] = useSearchParams()
  const urlTripId = searchParams.get('trip_id')

  const [trip, setTrip] = useState<TripResponse | null>(() => {
    return (location.state as ResultLocationState | null)?.trip ?? readTripSnapshot()?.trip ?? null
  })
  const [loading, setLoading] = useState(false)
  const [loadError, setLoadError] = useState(false)
  const [editingDay, setEditingDay] = useState<number | null>(null)
  const [editing, setEditing] = useState(false)
  const [exporting, setExporting] = useState(false)
  const [activeDay, setActiveDay] = useState<number>(1)

  const weatherList = useMemo(() => (trip?.days ?? []).map((day) => ({ date: day.itinerary_date, weather: day.weather })), [trip])

  // 当前展示天：始终落在合法范围内（编辑/换行程后自动收敛）
  const visibleDay = useMemo(() => {
    const days = trip?.days ?? []
    if (days.length === 0) return 0
    return days.some((d) => d.day_number === activeDay) ? activeDay : days[0].day_number
  }, [trip, activeDay])

  const visibleDayData = useMemo(
    () => (trip?.days ?? []).find((d) => d.day_number === visibleDay),
    [trip, visibleDay],
  )

  // 历史回看：URL 携带 trip_id 时，从后端拉取完整行程详情
  useEffect(() => {
    if (!urlTripId) return
    // 已有同 ID 的行程（如 state/快照命中）则无需重复拉取
    if (trip?.trip_id === urlTripId) return

    let cancelled = false
    // 切换历史行程时清空旧行程，避免短暂展示上一条数据
    setTrip(null)
    setLoading(true)
    setLoadError(false)
    tripApi
      .getTrip(urlTripId)
      .then((detail) => {
        if (cancelled) return
        setTrip(detail)
        writeTripSnapshot({ trip: detail, request: readTripSnapshot()?.request })
      })
      .catch((error) => {
        if (cancelled) return
        setLoadError(true)
        message.error(toErrorMessage(error, '加载历史行程失败'))
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [urlTripId, trip?.trip_id, message])

  if (loading && !trip) {
    return (
      <Flex vertical align="center" justify="center" gap={16} style={{ minHeight: '60vh' }}>
        <Spin size="large" />
        <Typography.Text type="secondary">正在加载历史行程详情…</Typography.Text>
      </Flex>
    )
  }

  if (loadError && !trip) {
    return (
      <Flex vertical align="center" justify="center" gap={8} style={{ minHeight: '60vh' }}>
        <Empty
          image={Empty.PRESENTED_IMAGE_SIMPLE}
          description={<Typography.Text type="secondary">历史行程加载失败，可能已被删除。</Typography.Text>}
        >
          <Button type="primary" onClick={() => navigate(ROUTES.history)}>
            返回历史记录
          </Button>
        </Empty>
      </Flex>
    )
  }

  if (!trip) {
    return (
      <Flex vertical align="center" justify="center" gap={8} style={{ minHeight: '60vh' }}>
        <Empty
          image={Empty.PRESENTED_IMAGE_SIMPLE}
          description={<Typography.Text type="secondary">还没有行程方案，先去规划页生成一份吧。</Typography.Text>}
        >
          <Button type="primary" onClick={() => navigate(ROUTES.home)}>
            去规划行程
          </Button>
        </Empty>
      </Flex>
    )
  }

  const applyTrip = (next: TripResponse) => {
    setTrip(next)
    const snapshot = readTripSnapshot()
    writeTripSnapshot({ trip: next, request: snapshot?.request })
  }

  const handleExport = async (format: 'markdown' | 'pdf') => {
    setExporting(true)
    try {
      await exportApi[format](trip.trip_id, `${trip.destination}-行程.${format === 'pdf' ? 'pdf' : 'md'}`)
      message.success('导出成功，已开始下载')
    } catch (error) {
      message.error(toErrorMessage(error, '导出失败'))
    } finally {
      setExporting(false)
    }
  }

  const handleEditSubmit = async (instruction: string) => {
    if (editingDay == null) return
    setEditing(true)
    try {
      const next = await tripApi.edit({ trip_id: trip.trip_id, day_number: editingDay, instruction })
      applyTrip(next)
      message.success(`第 ${editingDay} 天已更新`)
      setEditingDay(null)
    } catch (error) {
      message.error(toErrorMessage(error, '编辑失败，请稍后重试'))
    } finally {
      setEditing(false)
    }
  }

  const exportMenuItems = [
    { key: 'markdown', label: '导出 Markdown' },
    { key: 'pdf', label: '导出 PDF' },
  ]

  const stats: Array<{ key: string; label: string; value: string; icon: ReactNode; accent: string }> = [
    {
      key: 'days',
      label: '行程天数',
      value: `${trip.total_days} 天`,
      icon: <EnvironmentOutlined />,
      accent: token.colorPrimary,
    },
    {
      key: 'budget',
      label: '人均预算',
      value: formatMoney(trip.budget.budget_per_person),
      icon: <WalletOutlined />,
      accent: '#B7791F',
    },
    {
      key: 'rating',
      label: '综合评分',
      value: `${trip.overall_rating?.toFixed(1) ?? '—'} / 5`,
      icon: <ThunderboltOutlined />,
      accent: '#B7791F',
    },
  ]

  return (
    <Flex vertical gap={20}>
      {/* 行程封面 */}
      <div className="zl-hero" style={{ padding: '36px 40px' }}>
        <Flex wrap gap={20} justify="space-between" align="flex-start">
          <Flex vertical gap={10} style={{ minWidth: 260, flex: 1 }}>
            <Flex wrap gap={8} align="center">
              <Tag color="gold" style={{ borderRadius: 999, paddingInline: 12 }}>
                {trip.destination}
              </Tag>
              {trip.trip_name ? (
                <Typography.Text type="secondary" style={{ fontSize: 13 }}>
                  {trip.trip_name}
                </Typography.Text>
              ) : null}
            </Flex>
            <Typography.Title
              level={1}
              className="zl-serif zl-ink"
              style={{ marginBottom: 0, fontSize: 38, lineHeight: 1.25 }}
            >
              {trip.trip_name || `${trip.destination}行程`}
            </Typography.Title>
            <Typography.Text type="secondary" style={{ fontSize: 14 }}>
              {formatDateCN(trip.start_date)} 至 {formatDateCN(trip.end_date)} · 共 {trip.total_days} 天
            </Typography.Text>

            {/* 概览统计条 */}
            <Flex wrap gap={28} style={{ marginTop: 14 }}>
              {stats.map((stat) => (
                <Flex key={stat.key} gap={10} align="center">
                  <Flex
                    align="center"
                    justify="center"
                    style={{
                      width: 34,
                      height: 34,
                      borderRadius: 10,
                      background: `${stat.accent}1A`,
                      color: stat.accent,
                      fontSize: 16,
                    }}
                  >
                    {stat.icon}
                  </Flex>
                  <Flex vertical>
                    <Typography.Text type="secondary" style={{ fontSize: 11 }}>
                      {stat.label}
                    </Typography.Text>
                    <Typography.Text strong className="num" style={{ fontSize: 18 }}>
                      {stat.value}
                    </Typography.Text>
                  </Flex>
                </Flex>
              ))}
            </Flex>
          </Flex>

          <Flex gap={8} wrap style={{ flexShrink: 0 }}>
            <Button icon={<LeftOutlined />} onClick={() => navigate(ROUTES.home)}>
              返回规划
            </Button>
            <Button
              icon={<EditOutlined />}
              disabled={visibleDay === 0}
              onClick={() => setEditingDay(visibleDay)}
            >
              编辑当天
            </Button>
            <Dropdown
              menu={{ items: exportMenuItems, onClick: ({ key }) => void handleExport(key as 'markdown' | 'pdf') }}
              disabled={exporting}
            >
              <Button type="primary" icon={<DownloadOutlined />} loading={exporting}>
                导出
              </Button>
            </Dropdown>
          </Flex>
        </Flex>

        {/* 亮点与美食 */}
        {trip.trip_highlights?.length > 0 && (
          <Flex wrap gap={6} align="center" style={{ marginTop: 18 }}>
            <HeartOutlined style={{ color: token.colorPrimary }} />
            {trip.trip_highlights.slice(0, 5).map((hl) => (
              <Tag
                key={hl}
                bordered={false}
                style={{
                  marginInlineEnd: 0,
                  background: 'rgba(192,71,47,0.08)',
                  color: token.colorPrimary,
                  borderRadius: 999,
                  whiteSpace: 'normal',
                  wordBreak: 'break-word',
                  maxWidth: '100%',
                }}
              >
                {hl}
              </Tag>
            ))}
          </Flex>
        )}
      </div>

      {/* Day 导航条 */}
      {(trip.days?.length ?? 0) > 1 && (
        <Flex
          gap={10}
          wrap
          style={{
            overflowX: 'auto',
            paddingBottom: 4,
          }}
        >
          {(trip.days ?? []).map((day) => {
            const selected = day.day_number === visibleDay
            return (
              <Button
                key={day.day_number}
                size="large"
                onClick={() => setActiveDay(day.day_number)}
                style={{
                  flexShrink: 0,
                  borderRadius: 999,
                  paddingInline: 18,
                  borderColor: selected ? token.colorPrimary : undefined,
                  background: selected ? token.colorPrimary : 'transparent',
                  color: selected ? '#fff' : token.colorTextSecondary,
                  fontWeight: selected ? 600 : 400,
                }}
              >
                第 {day.day_number} 天 · {day.itinerary_date.slice(5)}
              </Button>
            )
          })}
        </Flex>
      )}

      {/* 当日时间线 + 天气预算 */}
      <Flex wrap gap={20} align="flex-start">
        <div style={{ flex: '1 1 420px', minWidth: 0 }}>
          {visibleDayData ? (
            <div className="zl-paper-card" style={{ padding: 24 }}>
              <DayTimeline day={visibleDayData} />
              <Button
                icon={<EditOutlined />}
                style={{ alignSelf: 'flex-start', marginTop: 16 }}
                onClick={() => setEditingDay(visibleDay)}
              >
                编辑第 {visibleDay} 天
              </Button>
            </div>
          ) : (
            <Card>
              <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无行程安排" />
            </Card>
          )}
        </div>
        <Flex vertical gap={20} style={{ flex: '1 1 360px', minWidth: 0 }}>
          <WeatherPanel list={weatherList} suggestions={trip.weather_suggestions} />
          <BudgetPanel budget={trip.budget} totalDays={trip.total_days} />
        </Flex>
      </Flex>

      {/* 行程地图 */}
      <MapPanel days={trip.days ?? []} />

      {/* 特殊需求与推荐美食 */}
      {(trip.special_needs_notes?.length ?? 0) > 0 || (trip.recommended_foods?.length ?? 0) > 0 ? (
        <div className="zl-paper-card" style={{ padding: 24 }}>
          <Flex wrap gap={28}>
            {trip.special_needs_notes?.length! > 0 && (
              <Flex vertical gap={8} style={{ flex: '1 1 300px', minWidth: 0 }}>
                <Typography.Text strong className="zl-serif" style={{ fontSize: 15 }}>
                  特殊需求保障
                </Typography.Text>
                <Flex wrap gap={6}>
                  {trip.special_needs_notes!.map((note) => (
                    <Tag
                      key={note}
                      color="orange"
                      style={{ marginInlineEnd: 0, whiteSpace: 'normal', wordBreak: 'break-word', maxWidth: '100%' }}
                    >
                      {note}
                    </Tag>
                  ))}
                </Flex>
              </Flex>
            )}
            {trip.recommended_foods?.length > 0 && (
              <Flex vertical gap={8} style={{ flex: '1 1 300px', minWidth: 0 }}>
                <Typography.Text strong className="zl-serif" style={{ fontSize: 15 }}>
                  推荐美食
                </Typography.Text>
                <Flex wrap gap={6}>
                  {trip.recommended_foods.slice(0, 8).map((food) => (
                    <Tag
                      key={food}
                      color="gold"
                      style={{ marginInlineEnd: 0, whiteSpace: 'normal', wordBreak: 'break-word', maxWidth: '100%' }}
                    >
                      {food}
                    </Tag>
                  ))}
                </Flex>
              </Flex>
            )}
          </Flex>
        </div>
      ) : null}

      {/* 行程贴士 */}
      {trip.trip_tips?.length > 0 && (
        <div className="zl-paper-card" style={{ padding: 24 }}>
          <Typography.Text strong className="zl-serif" style={{ fontSize: 15 }}>
            行程贴士
          </Typography.Text>
          {trip.trip_tips_grouped?.length ? (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 16, marginTop: 12 }}>
              {trip.trip_tips_grouped.map((group) => (
                <div
                  key={group.category}
                  style={{
                    borderBottom: '1px dashed rgba(192,71,47,0.18)',
                    paddingBottom: 12,
                  }}
                >
                  <Tag
                    color="gold"
                    bordered={false}
                    style={{ fontSize: 13, fontWeight: 600, marginBottom: 8 }}
                  >
                    {group.icon} {group.category}
                  </Tag>
                  <ul style={{ margin: '8px 0 0', paddingInlineStart: 20, color: 'inherit' }}>
                    {group.tips.map((tip, idx) => (
                      <li
                        key={`${group.category}-${idx}`}
                        style={{ marginBottom: 4, lineHeight: 1.7 }}
                      >
                        {tip}
                      </li>
                    ))}
                  </ul>
                </div>
              ))}
            </div>
          ) : (
            <ul style={{ margin: '12px 0 0', paddingInlineStart: 20, color: 'inherit' }}>
              {trip.trip_tips.map((tip) => (
                <li key={tip}>{tip}</li>
              ))}
            </ul>
          )}
        </div>
      )}

      {editingDay != null && (
        <EditDayModal
          open
          dayNumber={editingDay}
          dayTitle={trip.days?.find((d) => d.day_number === editingDay)?.day_theme ?? undefined}
          loading={editing}
          onCancel={() => setEditingDay(null)}
          onSubmit={handleEditSubmit}
        />
      )}
    </Flex>
  )
}
