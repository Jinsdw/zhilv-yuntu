/**
 * 8.3.7 预算展示组件：总预算 Statistic + 分项 Progress + 状态说明。
 * 数据来自 TripResponse.budget（后端预算校正已聚合 tiktok 分项）。
 */

import { CalculatorOutlined } from '@ant-design/icons'
import { Card, Col, Flex, Progress, Row, Statistic, Tag, Typography } from 'antd'

import { BUDGET_STATUS_META } from '@/constants/options'
import type { BudgetInfo } from '@/types'
import { formatMoney } from '@/utils/format'

interface BudgetPanelProps {
  budget: BudgetInfo
  /** 出行天数（用于展示人均/日均口径） */
  totalDays?: number
}

/** 分项配置：字段名 → 中文标签（顺序即展示顺序） */
const BREAKDOWN_ITEMS: Array<{ key: keyof BudgetInfo; label: string }> = [
  { key: 'accommodation_budget', label: '住宿' },
  { key: 'food_budget', label: '餐饮' },
  { key: 'transportation_budget', label: '交通' },
  { key: 'ticket_budget', label: '门票' },
  { key: 'shopping_budget', label: '购物' },
  { key: 'other_budget', label: '其他' },
]

export default function BudgetPanel({ budget, totalDays }: BudgetPanelProps) {
  const statusMeta = BUDGET_STATUS_META[budget.budget_status] ?? BUDGET_STATUS_META.within_budget
  const total = Math.max(budget.total_budget, 1)

  return (
    <Card
      title={
        <Flex align="center" gap={8}>
          <CalculatorOutlined />
          预算
        </Flex>
      }
      extra={<Tag color={statusMeta.color}>{statusMeta.label}</Tag>}
    >
      <Flex wrap gap={32} align="flex-start">
        <Flex vertical gap={8} style={{ minWidth: 200 }}>
          <Typography.Text type="secondary">总预算</Typography.Text>
          <Statistic value={budget.total_budget} prefix="¥" className="num" precision={0} />
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
            人均 {formatMoney(budget.budget_per_person)}
            {totalDays ? ` · 日均 ${formatMoney(budget.daily_avg_budget)}` : ''}
          </Typography.Text>
          {budget.savings != null && budget.savings > 0 && (
            <Typography.Text type="success" style={{ fontSize: 12 }}>
              预计可节省 {formatMoney(budget.savings)}
            </Typography.Text>
          )}
        </Flex>

        <Row gutter={[16, 12]} style={{ flex: 1, minWidth: 280 }}>
          {BREAKDOWN_ITEMS.map(({ key, label }) => {
            const value = Number(budget[key] ?? 0)
            return (
              <Col key={key} xs={24} sm={12}>
                <Flex vertical gap={4}>
                  <Flex justify="space-between">
                    <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                      {label}
                    </Typography.Text>
                    <Typography.Text className="num" style={{ fontSize: 12 }}>
                      {formatMoney(value)}
                    </Typography.Text>
                  </Flex>
                  <Progress percent={Math.round((value / total) * 100)} size="small" showInfo={false} />
                </Flex>
              </Col>
            )
          })}
        </Row>
      </Flex>
    </Card>
  )
}