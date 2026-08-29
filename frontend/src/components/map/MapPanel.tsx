/**
 * 8.4 地图面板：AmapTripMap 地图 + 天筛选 + 图例 + 点位列表 Drawer。
 * 数据来自 Result 页传入的 days。
 */

import { useState } from 'react'

import { EnvironmentOutlined, UnorderedListOutlined } from '@ant-design/icons'
import { Button, Card, Drawer, Empty, Flex, Segmented, Typography, theme } from 'antd'

import AmapTripMap, { DAY_COLORS } from '@/components/AmapTripMap'
import type { ItineraryDay } from '@/types'

interface MapPanelProps {
  /** 每日行程（含点位坐标） */
  days: ItineraryDay[]
}

/** 天 → 配色（与 AmapTripMap.DAY_COLORS / 后端 DAY_COLORS 一致） */
function colorOf(dayNumber: number): string {
  return DAY_COLORS[(dayNumber - 1) % DAY_COLORS.length]
}

export default function MapPanel({ days }: MapPanelProps) {
  const { token } = theme.useToken()
  /** 选中天数：默认第一天（不再提供「全部」视图） */
  const [activeDay, setActiveDay] = useState<number>(() => days[0]?.day_number ?? 0)
  const [drawerOpen, setDrawerOpen] = useState(false)
  const [focusPlaceId, setFocusPlaceId] = useState<string | null>(null)

  const dayOptions = days.map((d) => ({ label: `第 ${d.day_number} 天`, value: d.day_number }))
  const visibleDays = activeDay === 0 ? [] : days.filter((d) => d.day_number === activeDay)

  if (days.length === 0) {
    return (
      <Card title={<Flex align="center" gap={8}><EnvironmentOutlined />行程地图</Flex>}>
        <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无行程点位" />
      </Card>
    )
  }

  return (
    <Card
      title={
        <Flex align="center" gap={8}>
          <EnvironmentOutlined />
          行程地图
        </Flex>
      }
      extra={
        <Button size="small" icon={<UnorderedListOutlined />} onClick={() => setDrawerOpen(true)}>
          点位列表
        </Button>
      }
    >
      <Flex vertical gap={12}>
        {/* 天筛选 */}
        <Flex wrap gap={12} justify="space-between" align="center">
          <Segmented
            size="small"
            value={activeDay}
            options={dayOptions}
            onChange={(value) => {
              setActiveDay(Number(value))
              setFocusPlaceId(null)
            }}
          />
        </Flex>

        {/* 地图 */}
        <AmapTripMap
          days={days}
          activeDay={activeDay}
          focusPlaceId={focusPlaceId}
          onPlaceClick={setFocusPlaceId}
          brandColor={token.colorPrimary}
        />

        {/* 图例：起点 / 终点 / 途经景点 */}
        <Flex wrap gap={12} align="center">
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
            图例：
          </Typography.Text>
          <Flex gap={4} align="center">
            <span style={{ width: 10, height: 10, borderRadius: '50%', background: '#52c41a', display: 'inline-block' }} />
            <Typography.Text style={{ fontSize: 12 }}>起点</Typography.Text>
          </Flex>
          <Flex gap={4} align="center">
            <span style={{ width: 10, height: 10, borderRadius: '50%', background: '#f5222d', display: 'inline-block' }} />
            <Typography.Text style={{ fontSize: 12 }}>终点</Typography.Text>
          </Flex>
          <Flex gap={4} align="center">
            <span style={{ width: 10, height: 10, borderRadius: '50%', background: colorOf(activeDay), display: 'inline-block' }} />
            <Typography.Text style={{ fontSize: 12 }}>途经景点</Typography.Text>
          </Flex>
        </Flex>
      </Flex>

      {/* 点位列表抽屉：点击点位定位到地图并打开信息窗体 */}
      <Drawer title="行程点位" placement="right" width={320} open={drawerOpen} onClose={() => setDrawerOpen(false)}>
        <Flex vertical gap={8}>
          {visibleDays.flatMap((day) =>
            day.items.map((item, index) => {
              const placeId = item.place.place_id
              const active = focusPlaceId === placeId
              return (
                <div
                  key={placeId}
                  onClick={() => setFocusPlaceId(placeId)}
                  style={{
                    display: 'flex',
                    gap: 10,
                    alignItems: 'flex-start',
                    padding: '8px 10px',
                    borderRadius: 8,
                    cursor: 'pointer',
                    background: active ? token.colorPrimaryBg : token.colorFillTertiary,
                    outline: active ? `1px solid ${token.colorPrimary}` : 'none',
                  }}
                >
                  <span
                    style={{
                      flexShrink: 0,
                      width: 20,
                      height: 20,
                      borderRadius: '50%',
                      background: colorOf(day.day_number),
                      color: '#fff',
                      fontSize: 11,
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'center',
                      marginTop: 2,
                    }}
                  >
                    {index + 1}
                  </span>
                  <div style={{ minWidth: 0 }}>
                    <div
                      style={{
                        fontSize: 13,
                        fontWeight: 500,
                        overflow: 'hidden',
                        textOverflow: 'ellipsis',
                        whiteSpace: 'nowrap',
                      }}
                    >
                      {item.place.name}
                    </div>
                    <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                      第 {day.day_number} 天 · {item.start_time} - {item.end_time}
                    </Typography.Text>
                  </div>
                </div>
              )
            }),
          )}
        </Flex>
      </Drawer>
    </Card>
  )
}
