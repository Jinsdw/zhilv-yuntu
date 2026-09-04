/**
 * 8.3.4 行程规划表单：字段区 + 高级选项折叠 + 提交栏。
 * v2 山海拾光：分区标题（目的地/日期、人员与偏好、关键词）提升长表单可扫读性。
 * 页面只做组装，本组件承载表单状态与 TripRequest 构造。
 */

import { RocketOutlined } from '@ant-design/icons'
import { App as AntdApp, Button, Collapse, Flex, Form, Typography } from 'antd'
import type { Dayjs } from 'dayjs'
import type { FormInstance } from 'antd'

import type { TripRequest } from '@/types'

import AdvancedCollapse from './AdvancedCollapse'
import DateRangeField from './DateRangeField'
import DestinationField from './DestinationField'
import GenerationProgress from './GenerationProgress'
import KeywordsField from './KeywordsField'
import PeopleField from './PeopleField'
import StyleField from './StyleField'

/** 表单内部形态：日期用 dayjs 区间，提交时转 ISO 字符串 */
export interface TripFormValues {
  destination: string
  dateRange: [Dayjs, Dayjs] | null
  travelers: number
  with_kids: boolean
  with_elderly: boolean
  has_disability: boolean
  travel_style: TripRequest['travel_style']
  budget_level: TripRequest['budget_level']
  weather_preference: TripRequest['weather_preference']
  preferred_keywords: string[]
  excluded_keywords: string[]
  include_indoor: boolean
  include_outdoor: boolean
  daily_budget?: number | null
  max_places_per_day: number
  restaurant_budget_per_meal: number
  /** 备注：后端 TripRequest 暂无对应字段，提交时忽略（见 handleFinish） */
  note?: string
}

export interface TripPlannerFormProps {
  /** 生成中（由 Home 控制，切换为进度视图） */
  busy: boolean
  /** 触发生成：提交组装好的 TripRequest */
  onSubmit: (request: TripRequest) => Promise<void>
  /** 重置回调（Home 用于清理错误与进度） */
  onReset?: () => void
  /** 外部表单实例（Home 用于沉淀城市快捷填入 destination） */
  form?: FormInstance<TripFormValues>
}

/** 表单分区标题：序号 + 宋体标题 + 说明 */
function SectionHeader({
  index,
  title,
  subtitle,
}: {
  index: string
  title: string
  subtitle: string
}) {
  return (
    <Flex align="baseline" gap={10} style={{ marginBottom: 14, marginTop: 4 }}>
      <Typography.Text
        strong
        className="zl-serif"
        style={{
          fontSize: 15,
          color: 'var(--zl-text, #2b2118)',
        }}
      >
        {index} · {title}
      </Typography.Text>
      <Typography.Text type="secondary" style={{ fontSize: 12 }}>
        {subtitle}
      </Typography.Text>
    </Flex>
  )
}

/** 初始值：与后端 TripRequest 默认值对齐（schemas.py） */
const INITIAL_VALUES: Partial<TripFormValues> = {
  destination: '',
  travelers: 2,
  with_kids: false,
  with_elderly: false,
  has_disability: false,
  travel_style: 'relaxed',
  budget_level: 'standard',
  weather_preference: 'no_preference',
  preferred_keywords: [],
  excluded_keywords: [],
  include_indoor: true,
  include_outdoor: true,
  daily_budget: null,
  max_places_per_day: 5,
  restaurant_budget_per_meal: 100,
  note: '',
}

export default function TripPlannerForm({ busy, onSubmit, onReset, form: externalForm }: TripPlannerFormProps) {
  const { message } = AntdApp.useApp()
  const [internalForm] = Form.useForm<TripFormValues>()
  const form = externalForm ?? internalForm

  const handleFinish = async (values: TripFormValues) => {
    if (!values.dateRange) {
      message.warning('请选择行程日期')
      return
    }

    // 备注字段后端暂无承载，正式请求忽略（说明见 AdvancedCollapse）
    const { dateRange, note: _note, ...rest } = values

    const request: TripRequest = {
      ...rest,
      start_date: dateRange[0].format('YYYY-MM-DD'),
      end_date: dateRange[1].format('YYYY-MM-DD'),
    }

    await onSubmit(request)
  }

  const handleReset = () => {
    form.resetFields()
    onReset?.()
  }

  return (
    <Flex vertical gap={16}>
      {/* 生成中隐藏表单但保持挂载，失败回退时不丢失用户输入 */}
      <div style={{ display: busy ? 'none' : undefined }}>
        <Form<TripFormValues> form={form} layout="vertical" initialValues={INITIAL_VALUES} onFinish={handleFinish}>
          <SectionHeader index="01" title="去哪儿" subtitle="目的地与日期" />
          <Flex wrap gap={32} align="flex-start">
            <div style={{ flex: '1 1 360px', minWidth: 0 }}>
              <DestinationField />
            </div>
            <div style={{ flex: '1 1 360px', minWidth: 0 }}>
              <DateRangeField />
            </div>
          </Flex>

          <SectionHeader index="02" title="和谁去" subtitle="人数、节奏与预算" />
          <PeopleField />
          <StyleField />

          <SectionHeader index="03" title="怎么玩" subtitle="偏好与关键词" />
          <KeywordsField />

          <Collapse
            ghost
            style={{ marginBottom: 8 }}
            items={[
              {
                key: 'advanced',
                label: '高级选项',
                children: <AdvancedCollapse />,
              },
            ]}
          />

          <Flex
            gap={12}
            align="center"
            wrap
            style={{
              marginTop: 12,
              paddingTop: 20,
              borderTop: '1px dashed rgba(192,71,47,0.18)',
            }}
          >
            <Button
              type="primary"
              htmlType="submit"
              size="large"
              icon={<RocketOutlined />}
              style={{ minWidth: 180, borderRadius: 999 }}
            >
              开始生成行程
            </Button>
            <Button size="large" onClick={handleReset} style={{ borderRadius: 999 }}>
              重置
            </Button>
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>
              通常需要 1 至 3 分钟，期间请保持页面打开
            </Typography.Text>
          </Flex>
        </Form>
      </div>

      {busy && <GenerationProgress />}
    </Flex>
  )
}
