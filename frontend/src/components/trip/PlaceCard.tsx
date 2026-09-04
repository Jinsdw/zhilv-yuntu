/**
 * 8.3.5 行程卡片：单个景点/活动的时间区间、图片、评分、交通、费用、提示、预约。
 * v2 山海拾光：纸张卡片 + 胶囊标签，信息密度不变。
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
    <Card
      size="small"
      className="zl-paper-card zl-paper-card--hover"
      styles={{ body: { padding: 14 } }}
      style={{ marginBottom: 10, boxShadow: 'none' }}
    >
      <Flex gap={14} align="flex-start">
        {imageUrl ? (
          <Image
            src={imageUrl}
            alt={place.name}
            width={110}
            height={82}
            style={{ objectFit: 'cover', borderRadius: 12, flexShrink: 0 }}
            preview={{ mask: false }}
          />
        ) : (
          <Flex
            align="center"
            justify="center"
            style={{
              width: 110,
              height: 82,
              borderRadius: 12,
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
            <Typography.Text strong style={{ fontSize: 15 }}>{place.name}</Typography.Text>
            {place.rating != null && place.review_count > 0 && (
              <Typography.Text style={{ fontSize: 12, color: '#B7791F' }}>
                ★ {place.rating.toFixed(1)} · {place.review_count} 条点评
              </Typography.Text>
            )}
            {place.tags?.slice(0, 3).map((tag) => (
              <Tag key={tag} bordered={false} style={{ marginInlineEnd: 0, borderRadius: 999, background: 'rgba(192,71,47,0.08)' }}>
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
              <Tag color="blue" bordered={false} style={{ marginInlineEnd: 0, borderRadius: 999 }}>
                {transportText(transport.transport_type)} {transport.duration} 分钟
                {transport.cost > 0 ? ` · ${formatMoney(transport.cost)}` : ''}
              </Tag>
            )}
            {place.suggested_duration > 0 && (
              <Tag bordered={false} style={{ marginInlineEnd: 0, borderRadius: 999 }}>建议 {formatMinutes(place.suggested_duration)}</Tag>
            )}
            {place.suitable_for_kids && (
              <Tag color="green" bordered={false} style={{ marginInlineEnd: 0, borderRadius: 999 }}>适合儿童</Tag>
            )}
            {place.suitable_for_elderly && (
              <Tag color="gold" bordered={false} style={{ marginInlineEnd: 0, borderRadius: 999 }}>适合老人</Tag>
            )}
            {place.has_wheelchair && (
              <Tag color="cyan" bordered={false} style={{ marginInlineEnd: 0, borderRadius: 999 }}>无障碍可达</Tag>
            )}
            {item.booking_required && (
              <Tag color="orange" bordered={false} style={{ marginInlineEnd: 0, borderRadius: 999 }}>
                需预约
              </Tag>
            )}
            {item.photo_spot && (
              <Tag bordered={false} style={{ marginInlineEnd: 0, borderRadius: 999 }}>拍照点：{item.photo_spot}</Tag>
            )}
          </Space>
        </Flex>
      </Flex>
    </Card>
  )
}
