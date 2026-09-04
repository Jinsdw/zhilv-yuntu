/**
 * 8.3.6 天气展示组件：每日天气卡片（图标/类型/温度/AQI）+ 出行建议 Alert。
 * 数据来自 TripResponse.days[].weather（后端行程补全阶段已写入）。
 */

import { CloudOutlined } from '@ant-design/icons'
import { Alert, Card, Descriptions, Empty, Flex, Tag, Typography } from 'antd'

import type { WeatherInfo } from '@/types'
import { formatDateCN } from '@/utils/format'

interface WeatherPanelProps {
  /** 按天顺序的天气列表（与行程天数对应） */
  list: Array<{ date: string; weather: WeatherInfo | null | undefined }>
  /** 大模型生成的行程级天气出行建议 */
  suggestions?: string[]
}

/** 天气类型 → 语义色（只表达状态，不承担品牌，见 DESIGN.md §2.1） */
function weatherTagColor(type: string): string {
  if (/雨|雪/.test(type)) return 'blue'
  if (/晴/.test(type)) return 'gold'
  if (/阴|云/.test(type)) return 'default'
  if (/霾|雾/.test(type)) return 'orange'
  return 'default'
}

/** 只返回接口中实际有值的明细项，未返回的字段（AQI/湿度/穿衣等）不展示 */
function weatherDetailItems(weather: WeatherInfo) {
  const items: Array<{ key: string; label: string; children: string }> = []

  if (weather.aqi_level != null || weather.aqi != null) {
    items.push({
      key: 'aqi',
      label: '空气质量',
      children: weather.aqi_level ?? `${weather.aqi}`,
    })
  }
  if (weather.humidity != null) {
    items.push({ key: 'humidity', label: '湿度', children: `${weather.humidity}%` })
  }
  if (weather.wind_direction) {
    items.push({
      key: 'wind',
      label: '风力',
      children: `${weather.wind_direction}${weather.wind_speed != null ? ` ${weather.wind_speed}` : ''}`.trim(),
    })
  }
  if (weather.dressing_suggestion) {
    items.push({ key: 'dress', label: '穿衣', children: weather.dressing_suggestion })
  }

  return items
}

export default function WeatherPanel({ list, suggestions = [] }: WeatherPanelProps) {
  const days = list.filter((item) => item.weather)
  if (days.length === 0) {
    return (
      <Card title="天气" className="zl-paper-card" styles={{ body: { padding: 16 } }}>
        <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无天气数据" />
      </Card>
    )
  }

  const tips = suggestions.filter((text): text is string => Boolean(text))

  return (
    <Card
      className="zl-paper-card"
      styles={{ body: { padding: 20 } }}
      title={
        <Flex align="center" gap={8}>
          <Flex
            align="center"
            justify="center"
            style={{
              width: 28,
              height: 28,
              borderRadius: 9,
              background: 'rgba(47,125,122,0.14)',
              color: '#2F7D7A',
            }}
          >
            <CloudOutlined style={{ fontSize: 14 }} />
          </Flex>
          <Typography.Text strong className="zl-serif" style={{ fontSize: 16 }}>
            天气
          </Typography.Text>
        </Flex>
      }
    >
      <Flex vertical gap={16}>
        <Flex wrap gap={12}>
          {days.map(({ date, weather }) => (
            <Card
              key={date}
              size="small"
              className="zl-paper-card zl-paper-card--hover"
              style={{ flex: '1 1 200px', boxShadow: 'none' }}
              styles={{ body: { padding: 12 } }}
            >
              <Flex vertical gap={8}>
                <Typography.Text strong style={{ fontSize: 13 }}>{formatDateCN(date)}</Typography.Text>
                <Flex align="center" gap={8}>
                  <Tag color={weatherTagColor(weather!.weather_type)} bordered={false} style={{ marginInlineEnd: 0, borderRadius: 999 }}>
                    {weather!.weather_type}
                  </Tag>
                  <Typography.Text strong className="num" style={{ fontSize: 16 }}>
                    {weather!.temp_low}°C ~ {weather!.temp_high}°C
                  </Typography.Text>
                </Flex>
                {weatherDetailItems(weather!).length > 0 && (
                  <Descriptions size="small" column={1} items={weatherDetailItems(weather!)} />
                )}
              </Flex>
            </Card>
          ))}
        </Flex>

        {tips.length > 0 && (
          <Alert
            type="info"
            showIcon
            message="出行建议"
            description={tips.join('；')}
          />
        )}
      </Flex>
    </Card>
  )
}
