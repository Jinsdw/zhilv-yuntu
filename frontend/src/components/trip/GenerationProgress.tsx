/**
 * 8.3.4 生成进度：后端 POST /trip/generate 为单次阻塞调用（无流式进度），
 * 这里按编排管线五阶段做“预估进度”轮播，实际阶段以后端返回为准。
 * 组件只负责展示，不发起请求。
 */

import { useEffect, useMemo, useState } from 'react'

import {
  BulbOutlined,
  CheckCircleFilled,
  CompassOutlined,
  EnvironmentOutlined,
  FileSearchOutlined,
  WalletOutlined,
} from '@ant-design/icons'
import { Alert, Flex, Progress, Steps, Typography } from 'antd'

/** 与后端主编排管线顺序一致的五阶段文案（trip_service.generate_trip） */
export const GENERATION_STAGES = [
  { title: '解析目的地与参数', desc: '城市、日期与人群', icon: <FileSearchOutlined /> },
  { title: '检索攻略与候选池', desc: 'RAG 召回 + 高德 POI', icon: <CompassOutlined /> },
  { title: '规划每日行程', desc: '景点、交通与食宿编排', icon: <EnvironmentOutlined /> },
  { title: '补全天气与点位', desc: '地图坐标 + 天气建议', icon: <BulbOutlined /> },
  { title: '汇总预算与方案', desc: '拆分预算并生成方案', icon: <WalletOutlined /> },
] as const

/** 每阶段预估停留时长（毫秒）：后端整体约 1-3 分钟，快慢结合轮播 */
const STAGE_INTERVALS = [8_000, 12_000, 15_000, 12_000, 15_000]

export default function GenerationProgress() {
  const [stageIndex, setStageIndex] = useState(0)

  const percent = useMemo(() => Math.min(99, Math.round(((stageIndex + 1) / GENERATION_STAGES.length) * 100)), [stageIndex])

  useEffect(() => {
    if (stageIndex >= GENERATION_STAGES.length - 1) return
    const timer = window.setTimeout(() => setStageIndex((v) => v + 1), STAGE_INTERVALS[stageIndex])
    return () => window.clearTimeout(timer)
  }, [stageIndex])

  return (
    <Flex vertical gap={24}>
      {/* 旅途站点：每一阶段即一站 */}
      <Steps
        direction="vertical"
        size="small"
        current={stageIndex}
        items={GENERATION_STAGES.map((stage) => ({
          title: stage.title,
          description: stage.desc,
          icon: stage.icon,
        }))}
      />
      <Flex vertical gap={6}>
        <Progress
          percent={percent}
          status="active"
          strokeColor={{ from: '#C0472F', to: '#E8A33D' }}
        />
        <Typography.Text type="secondary" style={{ fontSize: 12 }}>
          已完成 {GENERATION_STAGES[stageIndex]?.title}
        </Typography.Text>
      </Flex>
      <Alert
        type="info"
        showIcon
        icon={<CheckCircleFilled />}
        message="大模型正在生成行程"
        description="整体耗时通常 1 至 3 分钟，期间请勿关闭页面；生成完成后将自动跳转结果页。"
      />
    </Flex>
  )
}
