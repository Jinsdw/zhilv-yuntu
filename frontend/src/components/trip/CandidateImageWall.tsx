/**
 * 12.1.6 候选图片墙：预览接口（POST /trip/preview）返回的 POI 候选图。
 * 展示在生成进度面板上半区——带地点名、分类标签与评分，渐进淡入；
 * 点击封面可放大预览（Image.PreviewGroup）。无图候选渲染占位图标兜底。
 */

import { useMemo } from 'react'

import { EnvironmentOutlined, PictureOutlined, StarFilled } from '@ant-design/icons'
import { Card, Empty, Flex, Image, Skeleton, Tag, Typography } from 'antd'

import type { PreviewCandidate } from '@/types'

export interface CandidateImageWallProps {
  /** 候选地点列表（已由后端按有图优先排序） */
  candidates: PreviewCandidate[]
  /** 是否仍在加载（骨架屏） */
  loading?: boolean
}

/** 分类标签配色：与结果页 PlaceCard 分类色一致 */
const CATEGORY_COLORS: Record<string, string> = {
  景点: 'geekblue',
  餐厅: 'orange',
  酒店: 'purple',
}

export default function CandidateImageWall({ candidates, loading = false }: CandidateImageWallProps) {
  const cards = useMemo(
    () => candidates.map((candidate, index) => ({ ...candidate, index })),
    [candidates],
  )

  if (loading) {
    return (
      <Flex wrap gap={12}>
        {Array.from({ length: 6 }, (_, i) => (
          <div key={i} style={{ width: 172 }}>
            <Skeleton.Image active style={{ width: 172, height: 110 }} />
          </div>
        ))}
      </Flex>
    )
  }

  if (cards.length === 0) {
    return (
      <Empty
        image={Empty.PRESENTED_IMAGE_SIMPLE}
        description="暂未获取到候选图片，正在为你规划行程…"
      />
    )
  }

  return (
    <Flex wrap gap={12}>
      <Image.PreviewGroup>
        {cards.map((candidate) => (
          <div
            key={`${candidate.category}-${candidate.name}`}
            style={{
              animation: 'zl-fade-in 0.45s ease both',
              animationDelay: `${candidate.index * 70}ms`,
            }}
          >
            <Card
              hoverable
              size="small"
              style={{ width: 172, borderRadius: 12, overflow: 'hidden' }}
              styles={{ body: { padding: 10 } }}
              cover={
                candidate.photos.length > 0 ? (
                  <Image
                    src={candidate.photos[0]}
                    alt={candidate.name}
                    height={110}
                    style={{ objectFit: 'cover' }}
                  />
                ) : (
                  <Flex
                    align="center"
                    justify="center"
                    style={{ height: 110, background: 'rgba(192,71,47,0.06)' }}
                  >
                    <PictureOutlined style={{ fontSize: 28, color: 'rgba(192,71,47,0.35)' }} />
                  </Flex>
                )
              }
            >
              <Flex vertical gap={4}>
                <Typography.Text strong ellipsis style={{ fontSize: 13 }}>
                  {candidate.name}
                </Typography.Text>
                <Flex gap={6} align="center">
                  <Tag
                    color={CATEGORY_COLORS[candidate.category] ?? 'default'}
                    style={{ fontSize: 11, marginInlineEnd: 0 }}
                  >
                    {candidate.category}
                  </Tag>
                  {candidate.rating != null && (
                    <Typography.Text type="secondary" style={{ fontSize: 11 }} className="num">
                      <StarFilled style={{ color: '#E8A33D', fontSize: 11 }} />{' '}
                      {candidate.rating.toFixed(1)}
                    </Typography.Text>
                  )}
                </Flex>
                {candidate.district && (
                  <Typography.Text type="secondary" ellipsis style={{ fontSize: 11 }}>
                    <EnvironmentOutlined /> {candidate.district}
                  </Typography.Text>
                )}
              </Flex>
            </Card>
          </div>
        ))}
      </Image.PreviewGroup>
    </Flex>
  )
}
