/**
 * 8.3.3 历史页：历史行程记录（分页拉取 TripHistoryListResponse）。
 * v2 山海拾光：旅行明信片墙（网格卡片），工具条与批量操作逻辑不变。
 * 工具条：目的地搜索（防抖）+ 收藏筛选 + 排序；卡片操作：查看 / 导出 / 删除（Popconfirm）。
 * 点击卡片 → 携带 trip_id 跳转结果页，结果页通过 GET /trip/{trip_id} 拉取完整详情。
 */

import { useEffect, useMemo, useState } from 'react'

import {
  DeleteOutlined,
  DownloadOutlined,
  EyeOutlined,
  HeartFilled,
  HeartOutlined,
  SearchOutlined,
} from '@ant-design/icons'
import {
  App as AntdApp,
  Button,
  Checkbox,
  Col,
  Dropdown,
  Flex,
  Input,
  Pagination,
  Popconfirm,
  Radio,
  Row,
  Select,
  Tag,
  Typography,
} from 'antd'
import type { MenuProps } from 'antd'
import { useNavigate } from 'react-router-dom'

import { useDebouncedValue } from '@/hooks/useDebouncedValue'
import { ROUTES } from '@/router/routes'
import { exportApi, tripApi, type HistoryQueryParams } from '@/services/api'
import type { TripHistorySummary } from '@/types'
import { toErrorMessage } from '@/utils/error'
import { formatDateCN, formatMoney } from '@/utils/format'

const PAGE_SIZE = 10

type SortMode = 'created_desc' | 'created_asc' | 'updated_desc' | 'access_desc'

/** 排序选项 → 后端 Query 参数 */
const SORT_OPTIONS: Array<{ value: SortMode; label: string }> = [
  { value: 'created_desc', label: '最新创建' },
  { value: 'created_asc', label: '最早创建' },
  { value: 'updated_desc', label: '最近更新' },
  { value: 'access_desc', label: '访问最多' },
]

function sortParams(mode: SortMode): Pick<HistoryQueryParams, 'order_by' | 'order_desc'> {
  switch (mode) {
    case 'created_desc':
      return { order_by: 'created_at', order_desc: true }
    case 'created_asc':
      return { order_by: 'created_at', order_desc: false }
    case 'updated_desc':
      return { order_by: 'updated_at', order_desc: true }
    case 'access_desc':
      return { order_by: 'access_count', order_desc: true }
  }
}

/** 目的地首字渐变色（明信片封面用，按目的地取稳定色） */
function coverGradient(destination: string): string {
  const palettes = [
    'linear-gradient(135deg, #C0472F, #E8A33D)',
    'linear-gradient(135deg, #2F7D7A, #5B6E9C)',
    'linear-gradient(135deg, #A85C6E, #E8A33D)',
    'linear-gradient(135deg, #7A5C9E, #2F7D7A)',
    'linear-gradient(135deg, #B7791F, #C0472F)',
  ]
  let hash = 0
  for (let i = 0; i < destination.length; i += 1) {
    hash = (hash * 31 + destination.charCodeAt(i)) >>> 0
  }
  return palettes[hash % palettes.length]
}

export default function History() {
  const { message } = AntdApp.useApp()
  const navigate = useNavigate()

  const [keyword, setKeyword] = useState('')
  const debouncedKeyword = useDebouncedValue(keyword.trim(), 400)
  const [favoriteOnly, setFavoriteOnly] = useState<boolean | undefined>(undefined)
  const [sortMode, setSortMode] = useState<SortMode>('created_desc')
  const [page, setPage] = useState(1)

  const [items, setItems] = useState<TripHistorySummary[]>([])
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(false)
  const [deletingId, setDeletingId] = useState<string | null>(null)
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set())
  const [batchBusy, setBatchBusy] = useState(false)

  // 分页查询参数：依赖项变化时重置到第 1 页
  useEffect(() => {
    setPage(1)
  }, [debouncedKeyword, favoriteOnly, sortMode])

  const load = useMemo(
    () => async () => {
      setLoading(true)
      try {
        const params: HistoryQueryParams = {
          ...sortParams(sortMode),
          limit: PAGE_SIZE,
          offset: (Math.max(page, 1) - 1) * PAGE_SIZE,
          destination: debouncedKeyword || undefined,
          is_favorite: favoriteOnly,
        }
        const res = await tripApi.listHistory(params)
        setItems(res.items)
        setTotal(res.total)
      } catch (error) {
        message.error(toErrorMessage(error, '加载历史记录失败'))
      } finally {
        setLoading(false)
      }
    },
    [page, debouncedKeyword, favoriteOnly, sortMode, message],
  )

  useEffect(() => {
    void load()
  }, [load])

  // 分页 / 筛选变化时清空已选
  useEffect(() => {
    setSelectedIds(new Set())
  }, [page, debouncedKeyword, favoriteOnly, sortMode])

  const toggleOne = (id: string) => {
    setSelectedIds((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  const toggleAll = () => {
    setSelectedIds((prev) => {
      const pageIds = items.map((item) => item.id)
      const allSelected = pageIds.length > 0 && pageIds.every((id) => prev.has(id))
      const next = new Set(prev)
      if (allSelected) {
        pageIds.forEach((id) => next.delete(id))
      } else {
        pageIds.forEach((id) => next.add(id))
      }
      return next
    })
  }

  const handleBatchDelete = async () => {
    if (selectedIds.size === 0) return
    setBatchBusy(true)
    try {
      const res = await tripApi.batchDeleteHistory(Array.from(selectedIds))
      message.success(`已删除 ${res.affected} 条`)
      setSelectedIds(new Set())
      if (items.length === res.affected && page > 1) {
        setPage((p) => p - 1)
      } else {
        void load()
      }
    } catch (error) {
      message.error(toErrorMessage(error, '批量删除失败'))
    } finally {
      setBatchBusy(false)
    }
  }

  const handleBatchFavorite = async (isFavorite: boolean) => {
    if (selectedIds.size === 0) return
    setBatchBusy(true)
    try {
      const res = await tripApi.batchSetFavorite(Array.from(selectedIds), isFavorite)
      message.success(isFavorite ? `已收藏 ${res.affected} 条` : `已取消收藏 ${res.affected} 条`)
      setSelectedIds(new Set())
      void load()
    } catch (error) {
      message.error(toErrorMessage(error, isFavorite ? '批量收藏失败' : '批量取消收藏失败'))
    } finally {
      setBatchBusy(false)
    }
  }

  const handleDelete = async (id: string) => {
    setDeletingId(id)
    try {
      await tripApi.deleteHistory(id)
      message.success('已删除')
      // 若当前页删空且非第一页，回退一页
      if (items.length === 1 && page > 1) {
        setPage((p) => p - 1)
      } else {
        void load()
      }
    } catch (error) {
      message.error(toErrorMessage(error, '删除失败'))
    } finally {
      setDeletingId(null)
    }
  }

  const handleExport = async (item: TripHistorySummary, format: 'markdown' | 'pdf') => {
    try {
      await exportApi[format](item.id, `${item.destination}-行程.${format === 'pdf' ? 'pdf' : 'md'}`)
      message.success('导出成功，已开始下载')
    } catch (error) {
      message.error(toErrorMessage(error, '导出失败'))
    }
  }

  const openTripDetail = (item: TripHistorySummary) => {
    navigate(`${ROUTES.result}?trip_id=${encodeURIComponent(item.id)}`)
  }

  const rowActions: MenuProps['items'] = [
    { key: 'md', label: '导出 Markdown', icon: <DownloadOutlined /> },
    { key: 'pdf', label: '导出 PDF', icon: <DownloadOutlined /> },
  ]

  const allSelected = items.length > 0 && items.every((item) => selectedIds.has(item.id))
  const someSelected = selectedIds.size > 0

  return (
    <Flex vertical gap={20}>
      <Flex vertical gap={4}>
        <Typography.Title level={1} className="zl-serif zl-ink" style={{ marginBottom: 0, fontSize: 32 }}>
          我的旅行手账
        </Typography.Title>
        <Typography.Paragraph type="secondary" style={{ marginBottom: 0 }}>
          已生成的行程像明信片一样收在这里，可随时回看、导出或删除。
        </Typography.Paragraph>
      </Flex>

      <div className="zl-paper-card" style={{ padding: 16 }}>
        <Flex wrap gap={12} align="center">
          <Checkbox
            checked={allSelected}
            indeterminate={someSelected && !allSelected}
            onChange={toggleAll}
            style={{ marginRight: 4 }}
          >
            全选本页
          </Checkbox>
          <Input
            prefix={<SearchOutlined />}
            placeholder="按目的地搜索"
            value={keyword}
            onChange={(e) => setKeyword(e.target.value)}
            allowClear
            style={{ width: 240 }}
          />
          <Select
            value={favoriteOnly ? 'favorite' : 'all'}
            onChange={(v) => setFavoriteOnly(v === 'favorite')}
            options={[
              { value: 'all', label: '全部行程' },
              { value: 'favorite', label: '仅看收藏' },
            ]}
            style={{ width: 140 }}
          />
          <Radio.Group
            optionType="button"
            buttonStyle="solid"
            value={sortMode}
            onChange={(e) => setSortMode(e.target.value as SortMode)}
            options={SORT_OPTIONS}
          />
          <Typography.Text type="secondary" style={{ marginLeft: 'auto', fontSize: 12 }}>
            共 {total} 条
          </Typography.Text>
        </Flex>

        {someSelected && (
          <Flex wrap gap={12} align="center" style={{ marginTop: 16, paddingTop: 12, borderTop: '1px dashed rgba(192,71,47,0.2)' }}>
            <Typography.Text strong style={{ fontSize: 13 }}>
              已选 {selectedIds.size} 条
            </Typography.Text>
            <Button
              type="primary"
              ghost
              icon={<HeartFilled />}
              loading={batchBusy}
              disabled={batchBusy}
              onClick={() => void handleBatchFavorite(true)}
            >
              批量收藏
            </Button>
            <Button
              icon={<HeartOutlined />}
              loading={batchBusy}
              disabled={batchBusy}
              onClick={() => void handleBatchFavorite(false)}
            >
              取消收藏
            </Button>
            <Popconfirm
              title={`删除选中的 ${selectedIds.size} 条历史记录？`}
              description="删除后不可恢复"
              okText="删除"
              cancelText="取消"
              okButtonProps={{ danger: true }}
              onConfirm={() => void handleBatchDelete()}
            >
              <Button danger icon={<DeleteOutlined />} loading={batchBusy} disabled={batchBusy}>
                批量删除
              </Button>
            </Popconfirm>
            <Button type="link" size="small" disabled={batchBusy} onClick={() => setSelectedIds(new Set())}>
              清除选择
            </Button>
          </Flex>
        )}
      </div>

      {/* 明信片墙 */}
      <Row gutter={[20, 20]}>
        {items.map((item) => {
          const selected = selectedIds.has(item.id)
          return (
            <Col key={item.id} xs={24} sm={12} lg={8}>
              <div
                className="zl-paper-card zl-paper-card--hover"
                role="button"
                tabIndex={0}
                onClick={() => openTripDetail(item)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' || e.key === ' ') {
                    e.preventDefault()
                    openTripDetail(item)
                  }
                }}
                style={{
                  display: 'flex',
                  flexDirection: 'column',
                  overflow: 'hidden',
                  cursor: 'pointer',
                  outline: selected ? '2px solid rgba(192,71,47,0.6)' : 'none',
                  height: '100%',
                }}
              >
                {/* 明信片封面 */}
                <div
                  style={{
                    height: 96,
                    background: coverGradient(item.destination),
                    position: 'relative',
                    padding: 16,
                    display: 'flex',
                    alignItems: 'flex-end',
                    justifyContent: 'space-between',
                  }}
                >
                  <Typography.Text className="zl-serif" style={{ fontSize: 44, color: 'rgba(255,255,255,0.92)', lineHeight: 1 }}>
                    {item.destination.slice(0, 1)}
                  </Typography.Text>
                  <Flex gap={6}>
                    {item.is_favorite && (
                      <Tag color="gold" icon={<HeartFilled />} style={{ marginInlineEnd: 0, borderRadius: 999, border: 'none' }}>
                        收藏
                      </Tag>
                    )}
                    {item.model_used && (
                      <Tag style={{ marginInlineEnd: 0, borderRadius: 999, background: 'rgba(255,255,255,0.85)', border: 'none' }}>
                        {item.model_used}
                      </Tag>
                    )}
                  </Flex>
                </div>

                {/* 卡片正文 */}
                <Flex vertical gap={8} style={{ padding: 16, flex: 1 }}>
                  <Flex justify="space-between" align="flex-start" gap={8}>
                    <Typography.Text strong style={{ fontSize: 17 }}>
                      {item.destination}
                    </Typography.Text>
                    <Checkbox
                      checked={selected}
                      onChange={() => toggleOne(item.id)}
                      onClick={(e) => e.stopPropagation()}
                      aria-label={`选择 ${item.destination}`}
                    />
                  </Flex>
                  <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                    {formatDateCN(item.start_date)} 至 {formatDateCN(item.end_date)}
                  </Typography.Text>
                  <Flex gap={16} style={{ marginTop: 4 }}>
                    <Flex vertical>
                      <Typography.Text type="secondary" style={{ fontSize: 11 }}>
                        天数
                      </Typography.Text>
                      <Typography.Text strong className="num">
                        {item.total_days} 天
                      </Typography.Text>
                    </Flex>
                    {item.total_budget != null && (
                      <Flex vertical>
                        <Typography.Text type="secondary" style={{ fontSize: 11 }}>
                          预算
                        </Typography.Text>
                        <Typography.Text strong className="num">
                          {formatMoney(item.total_budget)}
                        </Typography.Text>
                      </Flex>
                    )}
                  </Flex>
                  <Typography.Text type="secondary" style={{ fontSize: 11 }} ellipsis>
                    生成于 {item.created_at ? new Date(item.created_at).toLocaleString('zh-CN') : '—'}
                    {item.access_count > 0 ? ` · 访问 ${item.access_count} 次` : ''}
                  </Typography.Text>

                  <Flex gap={4} justify="flex-end" style={{ marginTop: 'auto', paddingTop: 8 }}>
                    <Button
                      type="text"
                      size="small"
                      icon={<EyeOutlined />}
                      onClick={(e) => {
                        e.stopPropagation()
                        openTripDetail(item)
                      }}
                    >
                      查看
                    </Button>
                    <Dropdown
                      menu={{
                        items: rowActions,
                        onClick: ({ key, domEvent }) => {
                          domEvent.stopPropagation()
                          void handleExport(item, key as 'markdown' | 'pdf')
                        },
                      }}
                    >
                      <Button
                        type="text"
                        size="small"
                        icon={<DownloadOutlined />}
                        onClick={(e) => e.stopPropagation()}
                      >
                        导出
                      </Button>
                    </Dropdown>
                    <Popconfirm
                      title="删除这条历史记录？"
                      description="删除后不可恢复"
                      okText="删除"
                      cancelText="取消"
                      okButtonProps={{ danger: true }}
                      onConfirm={() => void handleDelete(item.id)}
                    >
                      <Button
                        type="text"
                        size="small"
                        danger
                        icon={<DeleteOutlined />}
                        loading={deletingId === item.id}
                        onClick={(e) => e.stopPropagation()}
                      >
                        删除
                      </Button>
                    </Popconfirm>
                  </Flex>
                </Flex>
              </div>
            </Col>
          )
        })}
      </Row>

      {/* 加载骨架 */}
      {loading && items.length === 0 && (
        <Row gutter={[20, 20]}>
          {Array.from({ length: 6 }).map((_, index) => (
            <Col key={index} xs={24} sm={12} lg={8}>
              <div className="zl-paper-card" style={{ height: 260, background: 'var(--zl-card-bg)' }} />
            </Col>
          ))}
        </Row>
      )}

      {/* 空态 */}
      {items.length === 0 && !loading && (
        <div className="zl-paper-card" style={{ padding: 48, textAlign: 'center' }}>
          <Typography.Text type="secondary">
            {total === 0 ? '还没有历史行程，去规划页生成一份吧。' : '没有符合条件的结果。'}
          </Typography.Text>
        </div>
      )}

      <Flex justify="flex-end">
        <Pagination
          current={page}
          pageSize={PAGE_SIZE}
          total={total}
          showSizeChanger={false}
          showTotal={(t) => `共 ${t} 条`}
          onChange={setPage}
        />
      </Flex>
    </Flex>
  )
}
