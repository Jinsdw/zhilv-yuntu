/**
 * 结果页单日编辑弹窗（DESIGN.md 3.3 组件树 EditDayModal）：
 * 收集自然语言指令，由页面调用 POST /trip/edit 并就地替换当天数据。
 */

import { useState, useEffect } from 'react'

import { App as AntdApp, Input, Modal, Typography } from 'antd'

interface EditDayModalProps {
  open: boolean
  /** 第几天（1-based） */
  dayNumber: number
  /** 弹窗标题附加信息（如日期主题） */
  dayTitle?: string
  loading: boolean
  onCancel: () => void
  onSubmit: (instruction: string) => void
}

export default function EditDayModal({ open, dayNumber, dayTitle, loading, onCancel, onSubmit }: EditDayModalProps) {
  const { message } = AntdApp.useApp()
  const [instruction, setInstruction] = useState('')

  // 每次打开时清空输入
  useEffect(() => {
    if (open) setInstruction('')
  }, [open])

  const handleOk = () => {
    const text = instruction.trim()
    if (!text) {
      message.warning('请输入编辑指令')
      return
    }
    onSubmit(text)
  }

  return (
    <Modal
      title={`编辑第 ${dayNumber} 天${dayTitle ? `（${dayTitle}）` : ''}`}
      open={open}
      onOk={handleOk}
      onCancel={onCancel}
      confirmLoading={loading}
      okText="提交编辑"
      cancelText="取消"
      destroyOnHidden
    >
      <Typography.Paragraph type="secondary" style={{ marginBottom: 12 }}>
        用自然语言调整当天行程，例如：“上午换成故宫，下午留 2 小时自由活动”“删掉第 3 个景点”。
      </Typography.Paragraph>
      <Input.TextArea
        rows={4}
        maxLength={500}
        showCount
        value={instruction}
        onChange={(e) => setInstruction(e.target.value)}
        placeholder="输入编辑指令..."
      />
    </Modal>
  )
}