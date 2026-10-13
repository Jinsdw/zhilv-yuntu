/**
 * 12.2.9 生成过程实时面板（方案 B SSE 流式）。
 * 上半区：候选图片墙（poi 事件渐进填充，复用 CandidateImageWall）；
 * 下半区：真实阶段状态（status 事件）+ 草案骨架（draft 事件）+ 进度条。
 * 由 Home 根据 generateStream 事件驱动状态，本组件只做展示。
 */

import { CheckCircleFilled } from '@ant-design/icons'
import { Alert, Flex, Progress, Tag, Typography } from 'antd'

import type { DraftSkeleton, PreviewCandidate } from '@/types'

import CandidateImageWall from './CandidateImageWall'

/** 实时生成面板状态（Home 维护，逐帧事件增量更新） */
export interface LiveStreamState {
  /** 候选地点（preview 种子 + poi 事件合并，已去重） */
  candidates: PreviewCandidate[]
  /** 当前阶段标识（poi_pool / planning / draft / enrich / weather / finalize / cache_hit） */
  stage: string
  /** 当前阶段文案 */
  message: string
  /** 预估进度（0-100） */
  progress: number
  /** 草案骨架（draft 事件到达前为 null） */
  draft: DraftSkeleton | null
}

export interface LiveGenerationPanelProps {
  stream: LiveStreamState
}

export default function LiveGenerationPanel({ stream }: LiveGenerationPanelProps) {
  const { candidates, stage, message, progress, draft } = stream
  const connected = stage !== 'init'

  return (
    <Flex vertical gap={16}>
      {candidates.length > 0 && (
        <>
          <Typography.Text
            strong
            className="zl-serif"
            style={{ fontSize: 15, color: 'var(--zl-text, #2b2118)' }}
          >
            目的地候选 · 先睹为快
          </Typography.Text>
          <CandidateImageWall candidates={candidates} />
        </>
      )}

      <Flex vertical gap={6}>
        <Progress
          percent={Math.min(progress, 99)}
          status="active"
          strokeColor={{ from: '#C0472F', to: '#E8A33D' }}
        />
        <Typography.Text type="secondary" style={{ fontSize: 12 }}>
          {message}
        </Typography.Text>
      </Flex>

      {draft && draft.days.length > 0 && (
        <Flex vertical gap={8}>
          <Typography.Text
            strong
            className="zl-serif"
            style={{ fontSize: 14, color: 'var(--zl-text, #2b2118)' }}
          >
            行程草案已成形
          </Typography.Text>
          {draft.days.map((day) => (
            <Flex key={day.day_number} gap={10} align="flex-start">
              <Tag color="gold" style={{ marginInlineEnd: 0, flexShrink: 0 }}>
                第 {day.day_number} 天
              </Tag>
              <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                {day.theme ? `${day.theme}：` : ''}
                {day.places.length > 0 ? day.places.join(' → ') : '自由安排'}
              </Typography.Text>
            </Flex>
          ))}
          {draft.highlights && draft.highlights.length > 0 && (
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>
              亮点：{draft.highlights.join(' / ')}
            </Typography.Text>
          )}
        </Flex>
      )}

      <Alert
        type="info"
        showIcon
        icon={<CheckCircleFilled />}
        message={connected ? '大模型正在生成行程' : '正在连接生成服务…'}
        description="生成完成后将自动跳转结果页，期间请勿关闭页面。"
      />
    </Flex>
  )
}
