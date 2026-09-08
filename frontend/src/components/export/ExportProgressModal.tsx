/**
 * 8.3.4 导出进度弹窗：导出接口为单次阻塞 blob 下载（无流式进度），
 * 与生成进度（GenerationProgress）一致，按导出管线五阶段做“预估进度”轮播；
 * 真实完成时刻以父组件传入的 status 为准（success 即跳到 100% 并自动关闭）。
 */

import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react'

import {
  CheckCircleFilled,
  CloseCircleFilled,
  CompassOutlined,
  DownloadOutlined,
  FilePdfOutlined,
  FileTextOutlined,
  InboxOutlined,
  PictureOutlined,
} from '@ant-design/icons'
import { Button, Flex, Modal, Progress, Steps, Typography, theme } from 'antd'

import { brand } from '@/theme'

export type ExportStatus = 'running' | 'success' | 'error'

interface ExportStage {
  title: string
  desc: string
  icon: ReactNode
}

/** 导出管线阶段（与 backend/app/services/export_service.py 流程对齐：归档 → 景点 → 图片 → 渲染 → 打包） */
function buildStages(format: 'markdown' | 'pdf'): ExportStage[] {
  return [
    { title: '正在归档行程数据', desc: '整理行程、预算与贴士', icon: <InboxOutlined /> },
    { title: '正在加载景点信息', desc: '读取每日景点与点位', icon: <CompassOutlined /> },
    { title: '正在加载图片素材', desc: '封面与景点图片', icon: <PictureOutlined /> },
    {
      title: format === 'pdf' ? '正在渲染 PDF 文档' : '正在渲染 Markdown 文档',
      desc: '排版并生成文件',
      icon: format === 'pdf' ? <FilePdfOutlined /> : <FileTextOutlined />,
    },
    { title: '正在打包下载', desc: '完成导出，准备下载', icon: <DownloadOutlined /> },
  ]
}

/** 每阶段预估停留时长（毫秒）：导出整体通常数秒，快慢结合轮播 */
const STAGE_INTERVALS = [1_400, 1_600, 2_000, 1_800, 1_200]

/** 成功态最短展示时长（毫秒）：避免导出太快导致进度一闪而过 */
const SUCCESS_HOLD_MS = 1_200

/** 弹窗整体最短展示时长（毫秒） */
const MIN_DISPLAY_MS = 2_500

/** 预估进度上限：真实请求完成后才跳到 100% */
const SIMULATED_MAX = 90

interface ExportProgressModalProps {
  open: boolean
  format: 'markdown' | 'pdf'
  status: ExportStatus
  errorMessage?: string
  onClose: () => void
}

export default function ExportProgressModal({
  open,
  format,
  status,
  errorMessage,
  onClose,
}: ExportProgressModalProps) {
  const { token } = theme.useToken()
  const [stageIndex, setStageIndex] = useState(0)
  const openAtRef = useRef(0)
  const onCloseRef = useRef(onClose)

  useEffect(() => {
    onCloseRef.current = onClose
  }, [onClose])

  const stages = useMemo(() => buildStages(format), [format])

  // 预估进度：五阶段均分 90%；成功后才跳到 100%
  const percent = useMemo(() => {
    if (status === 'success') return 100
    return Math.min(SIMULATED_MAX, Math.round(((stageIndex + 1) / stages.length) * SIMULATED_MAX))
  }, [stageIndex, stages.length, status])

  // 每次打开/切换格式时重置阶段与计时起点
  useEffect(() => {
    if (!open) return
    setStageIndex(0)
    openAtRef.current = Date.now()
  }, [open, format])

  // 运行中：阶段轮播（预估进度）
  useEffect(() => {
    if (!open || status !== 'running') return
    if (stageIndex >= stages.length - 1) return
    const timer = window.setTimeout(() => setStageIndex((v) => v + 1), STAGE_INTERVALS[stageIndex])
    return () => window.clearTimeout(timer)
  }, [open, status, stageIndex, stages.length])

  // 成功：停留片刻后自动关闭
  useEffect(() => {
    if (!open || status !== 'success') return
    const hold = Math.max(SUCCESS_HOLD_MS, MIN_DISPLAY_MS - (Date.now() - openAtRef.current))
    const timer = window.setTimeout(() => onCloseRef.current(), hold)
    return () => window.clearTimeout(timer)
  }, [open, status])

  const formatLabel = format === 'pdf' ? 'PDF 行程报告' : 'Markdown 行程文档'

  return (
    <Modal
      open={open}
      title={null}
      footer={null}
      width={480}
      centered
      closable={status !== 'running'}
      maskClosable={false}
      keyboard={false}
      onCancel={onClose}
    >
      <Flex vertical gap={20}>
        {/* 标题区 */}
        <Flex gap={12} align="center">
          <Flex
            align="center"
            justify="center"
            style={{
              width: 40,
              height: 40,
              borderRadius: 12,
              background: `${token.colorPrimary}1A`,
              color: token.colorPrimary,
              fontSize: 20,
              flexShrink: 0,
            }}
          >
            {format === 'pdf' ? <FilePdfOutlined /> : <FileTextOutlined />}
          </Flex>
          <Flex vertical gap={2}>
            <Typography.Text strong style={{ fontSize: 16 }}>
              {status === 'success' ? '导出完成' : status === 'error' ? '导出失败' : `正在导出${formatLabel}`}
            </Typography.Text>
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>
              {status === 'success' ? '文件已开始下载' : '导出完成后将自动开始下载，请稍候'}
            </Typography.Text>
          </Flex>
        </Flex>

        {/* 阶段步骤 + 进度条 */}
        <Steps
          direction="vertical"
          size="small"
          current={status === 'error' ? stageIndex : status === 'success' ? stages.length : stageIndex}
          status={status === 'error' ? 'error' : 'process'}
          items={stages.map((stage) => ({
            title: stage.title,
            description: stage.desc,
            icon: stage.icon,
          }))}
        />

        <Flex vertical gap={6}>
          <Progress
            percent={percent}
            status={status === 'error' ? 'exception' : status === 'success' ? 'success' : 'active'}
            strokeColor={{ from: brand.gradientFrom, to: brand.gradientTo }}
          />
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
            {status === 'success'
              ? '已完成导出，正在下载文件'
              : status === 'error'
                ? (errorMessage ?? '导出失败，请稍后重试')
                : stages[stageIndex]?.title}
          </Typography.Text>
        </Flex>

        {/* 成功 / 失败提示 */}
        {status === 'success' && (
          <Flex align="center" gap={8} style={{ background: '#16a34a14', borderRadius: 10, padding: '10px 14px' }}>
            <CheckCircleFilled style={{ color: '#16a34a' }} />
            <Typography.Text style={{ fontSize: 13 }}>导出成功，请检查浏览器下载记录。</Typography.Text>
          </Flex>
        )}
        {status === 'error' && (
          <Flex
            align="center"
            justify="space-between"
            gap={8}
            style={{ background: '#c0472f14', borderRadius: 10, padding: '10px 14px' }}
          >
            <Flex align="center" gap={8} style={{ minWidth: 0 }}>
              <CloseCircleFilled style={{ color: token.colorError }} />
              <Typography.Text style={{ fontSize: 13 }}>导出未完成，可关闭后重新尝试。</Typography.Text>
            </Flex>
            <Button size="small" type="primary" onClick={onClose}>
              知道了
            </Button>
          </Flex>
        )}
      </Flex>
    </Modal>
  )
}
