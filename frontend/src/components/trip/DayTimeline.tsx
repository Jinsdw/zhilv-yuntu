/**
 * 8.3.5 每日行程时间轴：Timeline + PlaceCard 组合（9:00-11:00 等时段）。
 * v2 山海拾光：日期徽章 + 时间节点强化旅行日记感。
 */

import { Empty, Flex, Tag, Timeline, Typography, theme } from 'antd'

import type { ItineraryDay } from '@/types'
import { formatDateCN, formatMinutes, formatMoney } from '@/utils/format'

import FoodStayPanel from './FoodStayPanel'
import PlaceCard from './PlaceCard'

interface DayTimelineProps {
  day: ItineraryDay
}

export default function DayTimeline({ day }: DayTimelineProps) {
  const { token } = theme.useToken()
  const hasItems = day.items?.length > 0
  const hasFoodStay = Boolean(day.breakfast || day.lunch || day.dinner || day.hotel)

  return (
    <Flex vertical gap={16}>
      {/* 日期徽章 + 当日摘要 */}
      <Flex wrap gap={12} align="center">
        <Flex
          vertical
          align="center"
          justify="center"
          style={{
            minWidth: 56,
            padding: '8px 12px',
            borderRadius: 14,
            background: 'linear-gradient(135deg, rgba(192,71,47,0.14), rgba(232,163,61,0.18))',
            color: token.colorPrimary,
          }}
        >
          <Typography.Text strong className="num zl-serif" style={{ fontSize: 18, lineHeight: 1.2 }}>
            {day.day_number}
          </Typography.Text>
          <Typography.Text style={{ fontSize: 11 }}>第天</Typography.Text>
        </Flex>
        <Flex vertical gap={4} style={{ minWidth: 0 }}>
          <Flex wrap gap={8} align="center">
            {day.day_theme ? (
              <Tag color="gold" bordered={false} style={{ borderRadius: 999, paddingInline: 12 }}>
                {day.day_theme}
              </Tag>
            ) : null}
            <Typography.Text strong className="zl-serif" style={{ fontSize: 16 }}>
              {formatDateCN(day.itinerary_date)}
            </Typography.Text>
          </Flex>
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
            {day.total_duration > 0 ? `游览 ${formatMinutes(day.total_duration)}` : ''}
            {day.total_distance ? ` · 约 ${day.total_distance} 公里` : ''}
            {day.daily_cost > 0 ? ` · 当日费用 ${formatMoney(day.daily_cost)}` : ''}
          </Typography.Text>
        </Flex>
      </Flex>

      {hasItems ? (
        <Timeline
          items={day.items.map((item) => ({
            children: (
              <div>
                <Flex gap={8} align="baseline" style={{ marginBottom: 6 }}>
                  <Typography.Text strong className="num" style={{ color: token.colorPrimary, fontSize: 13 }}>
                    {item.start_time}
                  </Typography.Text>
                  <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                    - {item.end_time}
                  </Typography.Text>
                </Flex>
                <PlaceCard item={item} />
              </div>
            ),
          }))}
        />
      ) : (
        !hasFoodStay && <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="当天暂无安排" />
      )}

      <FoodStayPanel day={day} />

      {day.daily_tips?.length > 0 && (
        <Typography.Paragraph type="secondary" style={{ fontSize: 12, marginBottom: 0 }}>
          小贴士：{day.daily_tips.join('；')}
        </Typography.Paragraph>
      )}
    </Flex>
  )
}
