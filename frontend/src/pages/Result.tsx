/**
 * 8.3.2 结果页：行程方案展示（按 DESIGN.md 3.3 组件树组装）。
 * 数据优先读 location.state，刷新后回退 sessionStorage 快照（见 utils/snapshot.ts）。
 * 单日编辑成功后就地替换 trip 并更新快照。
 */

import { useMemo, useState } from 'react'

import {
  DownloadOutlined,
  EditOutlined,
  LeftOutlined,
} from '@ant-design/icons'
import {
  App as AntdApp,
  Button,
  Card,
  Descriptions,
  Dropdown,
  Empty,
  Flex,
  Tabs,
  Tag,
  Typography,
} from 'antd'
import { useLocation, useNavigate } from 'react-router-dom'

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

  const [trip, setTrip] = useState<TripResponse | null>(() => {
    return (location.state as ResultLocationState | null)?.trip ?? readTripSnapshot()?.trip ?? null
  })
  const [editingDay, setEditingDay] = useState<number | null>(null)
  const [editing, setEditing] = useState(false)
  const [exporting, setExporting] = useState(false)

  const weatherList = useMemo(() => (trip?.days ?? []).map((day) => ({ date: day.itinerary_date, weather: day.weather })), [trip])

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

  return (
    <Flex vertical gap={24}>
      {/* 概要头部：行程名 + 总览 + 导出 */}
      <Flex wrap gap={16} justify="space-between" align="flex-start">
        <Flex vertical gap={4}>
          <Typography.Title level={3} style={{ marginBottom: 0 }}>
            {trip.trip_name || `${trip.destination}行程`}
          </Typography.Title>
          <Typography.Text type="secondary">
            {trip.destination} · {formatDateCN(trip.start_date)} 至 {formatDateCN(trip.end_date)} · 共{' '}
            {trip.total_days} 天
          </Typography.Text>
        </Flex>

        <Flex gap={8} wrap>
          <Button icon={<LeftOutlined />} onClick={() => navigate(ROUTES.home)}>
            返回规划
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

      {/* 行程总览 */}
      <Card title="行程概览">
        <Flex vertical gap={12}>
          <Descriptions
            size="small"
            column={{ xs: 2, sm: 3, md: 4 }}
            items={[
              { key: 'destination', label: '目的地', children: trip.destination },
              { key: 'days', label: '行程天数', children: `${trip.total_days} 天` },
              { key: 'per-person', label: '人均预算', children: formatMoney(trip.budget.budget_per_person) },
              { key: 'rating', label: '综合评分', children: `${trip.overall_rating?.toFixed(1) ?? '—'} / 5` },
            ]}
          />
          {trip.trip_highlights?.length > 0 && (
            <Flex wrap gap={6} align="center">
              <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                行程亮点：
              </Typography.Text>
              {trip.trip_highlights.slice(0, 5).map((hl) => (
                <Tag key={hl} color="cyan" style={{ marginInlineEnd: 0 }}>
                  {hl}
                </Tag>
              ))}
            </Flex>
          )}
          {trip.special_needs_notes?.length > 0 && (
            <Flex wrap gap={6} align="center">
              <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                特殊需求保障：
              </Typography.Text>
              {trip.special_needs_notes.map((note) => (
                <Tag key={note} color="orange" style={{ marginInlineEnd: 0 }}>
                  {note}
                </Tag>
              ))}
            </Flex>
          )}
          {trip.recommended_foods?.length > 0 && (
            <Flex wrap gap={6} align="center">
              <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                推荐美食：
              </Typography.Text>
              {trip.recommended_foods.slice(0, 6).map((food) => (
                <Tag key={food} color="gold" style={{ marginInlineEnd: 0 }}>
                  {food}
                </Tag>
              ))}
            </Flex>
          )}
        </Flex>
      </Card>

      {/* 每日行程 + 编辑 */}
      <Card title="每日行程">
        <Tabs
          items={(trip.days ?? []).map((day) => ({
            key: String(day.day_number),
            label: `第 ${day.day_number} 天`,
            children: (
              <Flex vertical gap={12}>
                <DayTimeline day={day} />
                <Button
                  icon={<EditOutlined />}
                  style={{ alignSelf: 'flex-start' }}
                  onClick={() => setEditingDay(day.day_number)}
                >
                  编辑当天
                </Button>
              </Flex>
            ),
          }))}
        />
      </Card>

      {/* 天气与预算（两列布局，地图 8.4 接入后并入） */}
      <Flex wrap gap={24}>
        <div style={{ flex: '1 1 340px', minWidth: 0 }}>
          <WeatherPanel list={weatherList} suggestions={trip.weather_suggestions} />
        </div>
        <div style={{ flex: '1 1 420px', minWidth: 0 }}>
          <BudgetPanel budget={trip.budget} totalDays={trip.total_days} />
        </div>
      </Flex>

      <MapPanel days={trip.days ?? []} />

      {trip.trip_tips?.length > 0 && (
        <Card title="💡 行程贴士">
          {trip.trip_tips_grouped?.length ? (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
              {trip.trip_tips_grouped.map((group) => (
                <div
                  key={group.category}
                  style={{
                    borderBottom: '1px dashed #d9f2d9',
                    paddingBottom: 12,
                  }}
                >
                  <Tag
                    color="green"
                    style={{ fontSize: 13, fontWeight: 'bold', marginBottom: 8 }}
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
            <ul style={{ margin: 0, paddingInlineStart: 20, color: 'inherit' }}>
              {trip.trip_tips.map((tip) => (
                <li key={tip}>{tip}</li>
              ))}
            </ul>
          )}
        </Card>
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