/**
 * 12.2 SSE 流式工具：fetch + ReadableStream 解析 POST SSE。
 * EventSource 不支持 POST body（行程生成需要 JSON 请求体），故用 fetch 手动解析；
 * 支持 `event:` / `data:` 多行与 `: ping` 心跳注释行。
 */

export interface SSEFrame {
  /** 事件名（对应后端事件 type） */
  event: string
  /** data 字段原始字符串（多行 data 已拼接） */
  data: string
}

/** 解析单个 SSE 帧文本（空帧 / 纯注释帧返回 null） */
export function parseSSEFrame(frame: string): SSEFrame | null {
  let event = 'message'
  const dataLines: string[] = []
  for (const line of frame.split('\n')) {
    if (line.startsWith(':')) continue // 心跳/注释行
    if (line.startsWith('event:')) {
      event = line.slice(6).trim()
    } else if (line.startsWith('data:')) {
      dataLines.push(line.slice(5).trimStart())
    }
  }
  if (dataLines.length === 0) return null
  return { event, data: dataLines.join('\n') }
}

/**
 * 发起 SSE 请求并逐帧回调（onFrame）。
 * - 非 2xx / 无响应体视为传输错误（调用方降级为普通请求）
 * - 由调用方负责 signal 中断与 final/error 帧的业务处理
 */
export async function fetchSSE(
  url: string,
  init: RequestInit,
  onFrame: (frame: SSEFrame) => void,
): Promise<void> {
  const response = await fetch(url, init)
  if (!response.ok) {
    throw new Error(`SSE 响应异常: HTTP ${response.status}`)
  }
  if (!response.body) {
    throw new Error('SSE 无响应体')
  }

  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  for (;;) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    const parts = buffer.split('\n\n')
    buffer = parts.pop() ?? ''
    for (const part of parts) {
      const frame = parseSSEFrame(part)
      if (frame) onFrame(frame)
    }
  }
}
