/**
 * 智旅云图 - 浏览器设备指纹（无登录场景的数据隔离标识）
 *
 * 用途：项目无登录体系，部署上线后需要用设备指纹做历史记录隔离。
 * 前端把 device_id 作为 X-Device-Id header 统一附加到所有请求，
 * 后端将其落库为 user_id，并在读取/删除/收藏/导出时强制归属校验。
 *
 * 设计要点：
 *     - 轻量自实现（不引入 fingerprintjs 等第三方依赖）：
 *       canvas 指纹 + UA/语言/时区/屏幕/硬件并发 + localStorage 随机种子
 *     - 用 Web Crypto SHA-256 哈希为 32 位 hex，前缀 dev_ 便于日志区分
 *     - localStorage 种子保证同一浏览器身份稳定；指纹信号防止
 *       简单复制 localStorage 到另一台设备即可冒用身份
 *     - 结果按模块级 Promise 缓存，幂等；多次调用不重复计算
 *     - 非安全上下文（http）无 crypto.subtle 时回退到同步哈希
 */

const STORAGE_KEY = 'zl_yuntu_device_seed'

let cachedDeviceId: Promise<string> | null = null

/** 同步字符串哈希（crypto.subtle 不可用时的回退方案） */
function syncHash(input: string): string {
  let h1 = 0x811c9dc5
  let h2 = 0x01000193
  for (let i = 0; i < input.length; i += 1) {
    const code = input.charCodeAt(i)
    h1 = (h1 ^ code) >>> 0
    h1 = Math.imul(h1, 16777619) >>> 0
    h2 = (h2 * 33 + code) >>> 0
  }
  return (h1 >>> 0).toString(16).padStart(8, '0') + (h2 >>> 0).toString(16).padStart(8, '0')
}

/** SHA-256 摘要（Web Crypto），非安全上下文时回退同步哈希 */
async function digestHex(input: string): Promise<string> {
  try {
    if (globalThis.crypto?.subtle) {
      const data = new TextEncoder().encode(input)
      const digest = await crypto.subtle.digest('SHA-256', data)
      return Array.from(new Uint8Array(digest))
        .map((byte) => byte.toString(16).padStart(2, '0'))
        .join('')
    }
  } catch {
    // 回退到同步哈希
  }
  return syncHash(input).repeat(4).slice(0, 64)
}

/** 读取（或首次生成）localStorage 随机种子 */
function getSeed(): string {
  try {
    let seed = localStorage.getItem(STORAGE_KEY)
    if (!seed) {
      seed =
        typeof crypto.randomUUID === 'function'
          ? crypto.randomUUID()
          : `${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}`
      localStorage.setItem(STORAGE_KEY, seed)
    }
    return seed
  } catch {
    // localStorage 不可用（隐私模式 / 被禁用）：退化为纯指纹
    return `anon-${Math.random().toString(36).slice(2)}-${Date.now().toString(36)}`
  }
}

/** canvas 指纹：绘制文本+色块取像素数据哈希，跨浏览器差异明显 */
function canvasFingerprint(): string {
  try {
    const canvas = document.createElement('canvas')
    canvas.width = 240
    canvas.height = 64
    const ctx = canvas.getContext('2d')
    if (!ctx) return ''
    ctx.textBaseline = 'top'
    ctx.font = '14px Arial'
    ctx.fillStyle = '#0C7C7E'
    ctx.fillRect(0, 0, 240, 64)
    ctx.fillStyle = '#E8A33D'
    ctx.fillText('智旅云图 zhilv-yuntu device fingerprint', 4, 4)
    ctx.font = '16px "Times New Roman"'
    ctx.fillStyle = '#5B6E9C'
    ctx.fillText('canvas-signal-2026', 4, 32)
    const data = ctx.getImageData(0, 0, 240, 64).data
    let hash = 0
    for (let i = 0; i < data.length; i += 4) {
      hash = (hash * 31 + data[i] * 3 + data[i + 1] * 5 + data[i + 2] * 7) >>> 0
    }
    return hash.toString(16).padStart(8, '0')
  } catch {
    return ''
  }
}

/** 收集稳定的指纹信号 */
function collectSignals(): string[] {
  const nav = navigator
  return [
    nav.userAgent ?? '',
    nav.language ?? '',
    Array.isArray(nav.languages) ? nav.languages.join(',') : '',
    nav.platform ?? '',
    String(nav.hardwareConcurrency ?? ''),
    String((nav as Navigator & { deviceMemory?: number }).deviceMemory ?? ''),
    Intl.DateTimeFormat().resolvedOptions().timeZone ?? '',
    `${screen.width}x${screen.height}x${screen.colorDepth}`,
    canvasFingerprint(),
  ]
}

async function buildDeviceId(): Promise<string> {
  const payload = [...collectSignals(), getSeed()].join('|')
  const hash = await digestHex(payload)
  return `dev_${hash.slice(0, 32)}`
}

/** 获取设备指纹 ID（幂等，Promise 缓存） */
export function getDeviceId(): Promise<string> {
  if (!cachedDeviceId) {
    cachedDeviceId = buildDeviceId()
  }
  return cachedDeviceId
}
