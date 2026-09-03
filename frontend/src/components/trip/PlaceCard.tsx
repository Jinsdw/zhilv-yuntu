/**
 * 8.3.5 行程卡片：单个景点/活动的时间区间、图片、评分、交通、费用、提示、预约。
 * 纯展示组件，数据来自 ItineraryItem。
 */

import { CalendarOutlined } from '@ant-design/icons'
import { Card, Flex, Image, Space, Tag, Typography, theme } from 'antd'

import type { ItineraryItem } from '@/types'
import { formatMinutes, formatMoney } from '@/utils/format'

interface PlaceCardProps {
  item: ItineraryItem
}

/** 交通类型 → 简短文案（后端给出中文类型，此处仅兜底） */
function transportText(type: string): string {
  const known: Record<string, string> = {
    地铁: '地铁',
    公交: '公交',
    打车: '打车',
    步行: '步行',
    驾车: '驾车',
  }
  return known[type] ?? type
}

export default function PlaceCard({ item }: PlaceCardProps) {
  const { token } = theme.useToken()
  const { place, arrival_transport: transport } = item
  const ticket = item.ticket_price ?? place.ticket_price
  const imageUrl = place.cover_image ?? place.images?.[0]

  return (
    <Card size="small" styles={{ body: { padding: 12 } }} style={{ marginBottom: 8, background: token.colorFillTertiary }}>
      <Flex gap={12} align="flex-start">
        {imageUrl ? (
          <Image
            src={imageUrl}
            alt={place.name}
            width={96}
            height={72}
            style={{ objectFit: 'cover', borderRadius: 8, flexShrink: 0 }}
            preview={{ mask: false }}
          />
        ) : (
          <Flex
            align="center"
            justify="center"
            style={{
              width: 96,
              height: 72,
              borderRadius: 8,
              flexShrink: 0,
              background: token.colorFillSecondary,
              color: token.colorTextTertiary,
              fontSize: 12,
            }}
          >
            暂无图片
          </Flex>
        )}

        <Flex vertical gap={6} style={{ flex: 1, minWidth: 0 }}>
          <Flex wrap gap={6} align="center">
            <Typography.Text strong>{place.name}</Typography.Text>
            {place.rating != null && place.review_count > 0 && (
              <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                {place.rating.toFixed(1)} 分 · {place.review_count} 条点评
              </Typography.Text>
            )}
            {place.tags?.slice(0, 3).map((tag) => (
              <Tag key={tag} style={{ marginInlineEnd: 0 }}>
                {tag}
              </Tag>
            ))}
          </Flex>

          <Flex wrap gap={12} style={{ fontSize: 12, color: token.colorTextSecondary }}>
            <span>
              <CalendarOutlined /> {item.activity}
            </span>
            {ticket != null && <span>门票 {formatMoney(ticket)}</span>}
            {item.tips?.[0] && <span>提示：{item.tips[0]}</span>}
          </Flex>

          <Typography.Text type="secondary" style={{ fontSize: 12 }} ellipsis>
            {item.activity_detail || place.description || place.address}
          </Typography.Text>

          <Space size={8} wrap>
            {transport && (
              <Tag color="blue" style={{ marginInlineEnd: 0 }}>
                {transportText(transport.transport_type)} {transport.duration} 分钟
                {transport.cost > 0 ? ` · ${formatMoney(transport.cost)}` : ''}
              </Tag>
            )}
            {place.suggested_duration > 0 && (
              <Tag style={{ marginInlineEnd: 0 }}>建议 {formatMinutes(place.suggested_duration)}</Tag>
            )}
            {place.suitable_for_kids && (
              <Tag color="green" style={{ marginInlineEnd: 0 }}>适合儿童</Tag>
            )}
            {place.suitable_for_elderly && (
              <Tag color="gold" style={{ marginInlineEnd: 0 }}>适合老人</Tag>
            )}
            {place.has_wheelchair && (
              <Tag color="cyan" style={{ marginInlineEnd: 0 }}>无障碍可达</Tag>
            )}
            {item.booking_required && (
              <Tag color="orange" style={{ marginInlineEnd: 0 }}>
                需预约
              </Tag>
            )}
            {item.photo_spot && <Tag style={{ marginInlineEnd: 0 }}>拍照点：{item.photo_spot}</Tag>}
          </Space>
        </Flex>
      </Flex>
    </Card>
  )
}