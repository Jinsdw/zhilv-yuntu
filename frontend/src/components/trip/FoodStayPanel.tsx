/**
 * 每日食宿面板：早餐 / 午餐 / 晚餐 + 住宿酒店。
 * 数据来自 ItineraryDay.breakfast / lunch / dinner / hotel。
 * 与 schemas.RestaurantInfo / HotelInfo 对齐，纯展示组件。
 */

import {
  BankOutlined,
  CoffeeOutlined,
  FireOutlined,
  RestOutlined,
} from '@ant-design/icons'
import { Card, Flex, Image, Tag, Typography, theme } from 'antd'
import type { ReactNode } from 'react'

import type { HotelInfo, ItineraryDay, RestaurantInfo } from '@/types'
import { formatMoney } from '@/utils/format'

interface FoodStayPanelProps {
  day: ItineraryDay
}

/** 餐次标签 → 图标与配色 */
const MEAL_META: Record<string, { icon: ReactNode; color: string }> = {
  早餐: { icon: <CoffeeOutlined />, color: 'orange' },
  午餐: { icon: <RestOutlined />, color: 'geekblue' },
  晚餐: { icon: <FireOutlined />, color: 'volcano' },
}

/** 单个餐厅卡片 */
function MealCard({ label, meal }: { label: string; meal: RestaurantInfo }) {
  const { token } = theme.useToken()
  const meta = MEAL_META[label] ?? { icon: null, color: 'default' }
  const imageUrl = meal.images?.[0]
  const tags = meal.tags?.length ? meal.tags : meal.signature_dishes?.length ? meal.signature_dishes : []

  return (
    <Card
      size="small"
      styles={{ body: { padding: 10 } }}
      style={{ marginBottom: 0, background: token.colorFillTertiary }}
    >
      <Flex gap={10} align="flex-start">
        {imageUrl ? (
          <Image
            src={imageUrl}
            alt={meal.name}
            width={64}
            height={48}
            style={{ objectFit: 'cover', borderRadius: 8, flexShrink: 0 }}
            preview={{ mask: false }}
          />
        ) : null}

        <Flex vertical gap={4} style={{ flex: 1, minWidth: 0 }}>
          <Flex wrap gap={6} align="center">
            <Tag color={meta.color} style={{ marginInlineEnd: 0 }}>
              {meta.icon} {label}
            </Tag>
            <Typography.Text strong>{meal.name}</Typography.Text>
            {meal.rating != null && (
              <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                {meal.rating.toFixed(1)} 分
              </Typography.Text>
            )}
          </Flex>

          <Flex wrap gap={10} style={{ fontSize: 12, color: token.colorTextSecondary }}>
            {meal.cuisine_type && <span>菜系：{meal.cuisine_type}</span>}
            {meal.avg_price > 0 && <span>人均 {formatMoney(meal.avg_price)}</span>}
            {meal.business_status && <span>{meal.business_status}</span>}
          </Flex>

          {tags.length > 0 && (
            <Flex wrap gap={4}>
              {tags.slice(0, 4).map((tag) => (
                <Tag key={tag} style={{ marginInlineEnd: 0, fontSize: 12 }}>
                  {tag}
                </Tag>
              ))}
              {meal.suitable_for_kids && (
                <Tag color="green" style={{ marginInlineEnd: 0, fontSize: 12 }}>适合儿童</Tag>
              )}
              {meal.suitable_for_elderly && (
                <Tag color="gold" style={{ marginInlineEnd: 0, fontSize: 12 }}>适合老人</Tag>
              )}
              {meal.has_wheelchair && (
                <Tag color="cyan" style={{ marginInlineEnd: 0, fontSize: 12 }}>无障碍</Tag>
              )}
            </Flex>
          )}
          {tags.length === 0 && (meal.suitable_for_kids || meal.suitable_for_elderly || meal.has_wheelchair) && (
            <Flex wrap gap={4}>
              {meal.suitable_for_kids && (
                <Tag color="green" style={{ marginInlineEnd: 0, fontSize: 12 }}>适合儿童</Tag>
              )}
              {meal.suitable_for_elderly && (
                <Tag color="gold" style={{ marginInlineEnd: 0, fontSize: 12 }}>适合老人</Tag>
              )}
              {meal.has_wheelchair && (
                <Tag color="cyan" style={{ marginInlineEnd: 0, fontSize: 12 }}>无障碍</Tag>
              )}
            </Flex>
          )}

          {meal.address && (
            <Typography.Text type="secondary" style={{ fontSize: 12 }} ellipsis>
              {meal.address}
            </Typography.Text>
          )}
        </Flex>
      </Flex>
    </Card>
  )
}

/** 住宿酒店卡片 */
function HotelCard({ hotel }: { hotel: HotelInfo }) {
  const { token } = theme.useToken()
  const imageUrl = hotel.cover_image ?? hotel.images?.[0]

  return (
    <Card
      size="small"
      styles={{ body: { padding: 10 } }}
      style={{ marginBottom: 0, background: token.colorFillTertiary }}
    >
      <Flex gap={10} align="flex-start">
        {imageUrl ? (
          <Image
            src={imageUrl}
            alt={hotel.name}
            width={64}
            height={48}
            style={{ objectFit: 'cover', borderRadius: 8, flexShrink: 0 }}
            preview={{ mask: false }}
          />
        ) : null}

        <Flex vertical gap={4} style={{ flex: 1, minWidth: 0 }}>
          <Flex wrap gap={6} align="center">
            <Tag color="purple" style={{ marginInlineEnd: 0 }}>
              <BankOutlined /> 住宿
            </Tag>
            <Typography.Text strong>{hotel.name}</Typography.Text>
            {hotel.hotel_type && <Tag style={{ marginInlineEnd: 0 }}>{hotel.hotel_type}</Tag>}
            {hotel.star_rating != null && hotel.star_rating > 0 && (
              <Typography.Text type="warning" style={{ fontSize: 12 }}>
                {'★'.repeat(hotel.star_rating)}
              </Typography.Text>
            )}
          </Flex>

          <Flex wrap gap={10} style={{ fontSize: 12, color: token.colorTextSecondary }}>
            {hotel.price > 0 && <span>{formatMoney(hotel.price)} / 晚</span>}
            {hotel.rating != null && <span>评分 {hotel.rating.toFixed(1)}</span>}
          </Flex>

          {(hotel.has_breakfast || hotel.has_wifi || hotel.has_parking || hotel.suitable_for_kids || hotel.suitable_for_elderly || hotel.has_wheelchair) && (
            <Flex wrap gap={4}>
              {hotel.has_breakfast && (
                <Tag color="green" style={{ marginInlineEnd: 0, fontSize: 12 }}>
                  含早餐
                </Tag>
              )}
              {hotel.has_wifi && <Tag style={{ marginInlineEnd: 0, fontSize: 12 }}>WiFi</Tag>}
              {hotel.has_parking && <Tag style={{ marginInlineEnd: 0, fontSize: 12 }}>停车场</Tag>}
              {hotel.suitable_for_kids && (
                <Tag color="green" style={{ marginInlineEnd: 0, fontSize: 12 }}>适合儿童</Tag>
              )}
              {hotel.suitable_for_elderly && (
                <Tag color="gold" style={{ marginInlineEnd: 0, fontSize: 12 }}>适合老人</Tag>
              )}
              {hotel.has_wheelchair && (
                <Tag color="cyan" style={{ marginInlineEnd: 0, fontSize: 12 }}>无障碍</Tag>
              )}
            </Flex>
          )}

          {hotel.address && (
            <Typography.Text type="secondary" style={{ fontSize: 12 }} ellipsis>
              {hotel.address}
            </Typography.Text>
          )}
        </Flex>
      </Flex>
    </Card>
  )
}

/** 每日食宿面板：按 早/午/晚 + 住宿 顺序展示，缺失项自动隐藏 */
export default function FoodStayPanel({ day }: FoodStayPanelProps) {
  const meals: Array<{ label: string; meal: RestaurantInfo | null | undefined }> = [
    { label: '早餐', meal: day.breakfast },
    { label: '午餐', meal: day.lunch },
    { label: '晚餐', meal: day.dinner },
  ]

  const hasMeals = meals.some((m) => m.meal != null)
  const hasHotel = day.hotel != null

  if (!hasMeals && !hasHotel) return null

  return (
    <Flex vertical gap={8}>
      {hasMeals && (
        <Flex vertical gap={6}>
          {meals.map(
            ({ label, meal }) =>
              meal && <MealCard key={label} label={label} meal={meal} />,
          )}
        </Flex>
      )}

      {hasHotel && day.hotel && <HotelCard hotel={day.hotel} />}
    </Flex>
  )
}
