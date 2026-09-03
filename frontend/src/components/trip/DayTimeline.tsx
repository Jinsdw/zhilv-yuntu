/**
 * 8.3.5 每日行程时间轴：Timeline + PlaceCard 组合（9:00-11:00 等时段）。
 */

import { Empty, Flex, Tag, Timeline, Typography } from 'antd'

import type { ItineraryDay } from '@/types'
import { formatDateCN, formatMinutes, formatMoney } from '@/utils/format'

import FoodStayPanel from './FoodStayPanel'
import PlaceCard from './PlaceCard'

interface DayTimelineProps {
  day: ItineraryDay
}

export default function DayTimeline({ day }: DayTimelineProps) {
  const hasItems = day.items?.length > 0
  const hasFoodStay = Boolean(day.breakfast || day.lunch || day.dinner || day.hotel)

  return (
    <Flex vertical gap={12}>
      <Flex wrap gap={12} align="center">
        {day.day_theme ? <Tag color="cyan">{day.day_theme}</Tag> : null}
        <Typography.Text type="secondary" style={{ fontSize: 12 }}>
          {formatDateCN(day.itinerary_date)}
          {day.total_duration > 0 ? ` · 游览 ${formatMinutes(day.total_duration)}` : ''}
          {day.total_distance ? ` · 约 ${day.total_distance} 公里` : ''}
          {day.daily_cost > 0 ? ` · 当日费用 ${formatMoney(day.daily_cost)}` : ''}
        </Typography.Text>
      </Flex>

      {hasItems ? (
        <Timeline
          items={day.items.map((item) => ({
            children: (
              <div>
                <Typography.Text strong type="secondary" style={{ fontSize: 13 }}>
                  {item.start_time} - {item.end_time}
                </Typography.Text>
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