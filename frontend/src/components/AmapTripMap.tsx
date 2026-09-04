/**
 * 8.4 高德行程地图组件（AmapTripMap.tsx）
 *
 * 职责：纯地图引擎 ——
 *   - 8.4.1 组件骨架
 *   - 8.4.2 集成高德 JavaScript API（AMapLoader v2.0 + 安全密钥）
 *   - 8.4.3 景点标记展示（起点/终点图钉 + 途经点数字序号）
 *   - 8.4.4 路线规划展示（驾车，失败降级直线）
 *   - 8.4.5 信息窗体展示（点击标记 / 点位联动）
 *   - 8.4.6 地图交互（缩放 / 平移控件 + 视野自适应 + 点位定位）
 *
 * 外层 MapPanel 负责卡片外壳、天筛选、点位抽屉与图例（本组件不感知 antd）。
 * 数据约定：place.coordinate 为 GCJ-02 经纬度（后端高德 Web 服务返回，与 JSAPI 一致）。
 */

import { useCallback, useEffect, useRef, useState } from 'react'

import AMapLoader from '@amap/amap-jsapi-loader'

import type { ItineraryDay, ItineraryItem } from '@/types'

/** 与后端 map_service.DAY_COLORS 对齐的天配色（第 N 天取第 N 个） */
export const DAY_COLORS = [
  '#C0472F', // 陶土橙
  '#E8A33D', // 日出金
  '#2F7D7A', // 雾霭青
  '#7C6A2E', // 橄榄
  '#A85C6E', // 莓红
  '#5B6E9C', // 暮蓝
  '#7A5C9E', // 岩紫
  '#B7791F', // 深金
] as const

/** 地图默认中心（北京；渲染点位后立即自适应视野，仅作首屏兜底） */
const DEFAULT_CENTER: [number, number] = [116.397428, 39.90923]

export interface AmapTripMapProps {
  /** 每日行程数据 */
  days: ItineraryDay[]
  /** 选中天数（1-based）；0 或未传时默认取第一天（不提供「全部」视图） */
  activeDay?: number
  /** 需要定位/弹窗的点位 id（抽屉点选联动） */
  focusPlaceId?: string | null
  /** 标记点击回调（供点位列表高亮联动） */
  onPlaceClick?: (placeId: string) => void
  /** 信息窗体「导航」按钮主色（由外层传 antd token 主色，避免组件写死十六进制） */
  brandColor?: string
}

/** 扁平化后的标记点 */
interface MapPoint {
  placeId: string
  dayNumber: number
  order: number
  item: ItineraryItem
  /** [经度, 纬度]（高德 GCJ-02） */
  position: [number, number]
}

function toPosition(item: ItineraryItem): [number, number] | null {
  const { longitude, latitude } = item.place.coordinate ?? {}
  if (typeof longitude !== 'number' || typeof latitude !== 'number') return null
  if (!Number.isFinite(longitude) || !Number.isFinite(latitude)) return null
  return [longitude, latitude]
}

function dayColor(dayNumber: number): string {
  return DAY_COLORS[(dayNumber - 1) % DAY_COLORS.length]
}

/** 转义 HTML，防止地名/简介等内容注入信息窗体 */
function escapeHtml(value: unknown): string {
  return String(value ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;')
}

/** 数字序号标记 DOM（按天配色，白色描边水滴感圆形） */
function markerContent(order: number, color: string): string {
  return `<div style="
    width:26px;height:26px;border-radius:50%;background:${color};color:#fff;
    display:flex;align-items:center;justify-content:center;
    font-size:12px;font-weight:600;line-height:1;
    border:2px solid #fff;box-shadow:0 1px 6px rgba(0,0,0,.35);
  ">${order}</div>`
}

/** 起点/终点图钉标记 DOM（导航式起终点：SVG 图钉 + 起/终字） */
function endpointMarkerContent(label: '起' | '终', color: string): string {
  return `<div style="position:relative;width:32px;height:40px;">
    <svg width="32" height="40" viewBox="0 0 32 40" style="display:block;filter:drop-shadow(0 2px 4px rgba(0,0,0,.35));">
      <path d="M16 1 C8.3 1 2 7.3 2 15 c0 10.8 14 24 14 24 s14-13.2 14-24 C30 7.3 23.7 1 16 1z" fill="${color}" stroke="#fff" stroke-width="2.5"/>
    </svg>
    <div style="position:absolute;top:0;left:0;width:32px;height:26px;display:flex;align-items:center;justify-content:center;color:#fff;font-size:13px;font-weight:700;line-height:1;">${label}</div>
  </div>`
}

export default function AmapTripMap({
  days,
  activeDay = 0,
  focusPlaceId,
  onPlaceClick,
  brandColor = '#C0472F',
}: AmapTripMapProps) {
  const containerRef = useRef<HTMLDivElement>(null)
  const mapRef = useRef<any>(null)
  const amapRef = useRef<any>(null)
  const infoWindowRef = useRef<any>(null)
  const resizeHandlerRef = useRef<(() => void) | null>(null)
  /** 当前展示的扁平点位数据（供定位联动查询） */
  const markersRef = useRef<MapPoint[]>([])
  /** 已挂载的 Marker 实例（清理用） */
  const markerInstancesRef = useRef<any[]>([])
  /** 已挂载的 Polyline 实例（清理用） */
  const polylineInstancesRef = useRef<any[]>([])
  /** 路线规划请求序号：丢弃过期异步回调 */
  const routeSeqRef = useRef(0)

  const [mapReady, setMapReady] = useState(false)
  const [loadError, setLoadError] = useState<string | null>(null)

  /** 打开信息窗体（点击标记 / 点位联动共用） */
  const openInfoWindow = useCallback((point: MapPoint) => {
    const map = mapRef.current
    const infoWindow = infoWindowRef.current
    if (!map || !infoWindow) return

    const { place, start_time, end_time } = point.item
    const cover = place.cover_image ?? place.images?.[0]
    const ticket = point.item.ticket_price ?? place.ticket_price
    const rating = place.rating != null ? `★ ${place.rating.toFixed(1)}` : ''
    const duration = place.suggested_duration > 0 ? `时长 ${place.suggested_duration} 分钟` : ''
    const price = ticket != null ? (ticket === 0 ? '门票 免费' : `门票 ¥${ticket}`) : place.is_free ? '门票 免费' : ''
    const [lng, lat] = point.position
    const navUrl = `https://uri.amap.com/navigation?to=${lng},${lat},${encodeURIComponent(place.name)}&mode=driving&coordinate=gaode&callnative=0`

    const rows: string[] = []
    if (place.address) rows.push(`<div style="color:#595959;font-size:12px">地址：${escapeHtml(place.address)}</div>`)
    if (place.opening_hours) rows.push(`<div style="color:#595959;font-size:12px">营业：${escapeHtml(place.opening_hours)}</div>`)
    const meta = [rating, duration, price].filter(Boolean).join(' · ')
    if (meta) rows.push(`<div style="color:#595959;font-size:12px">${escapeHtml(meta)}</div>`)
    const desc = place.highlight ?? place.description
    if (desc) rows.push(`<div style="color:#595959;font-size:12px;margin-top:2px">${escapeHtml(desc)}</div>`)

    const content = `
      <div style="font-size:13px;line-height:1.6;min-width:220px;max-width:280px">
        ${cover ? `<img src="${escapeHtml(cover)}" alt="" style="width:100%;height:110px;object-fit:cover;border-radius:8px;margin-bottom:8px" />` : ''}
        <div style="font-weight:600;font-size:15px;margin-bottom:2px">${escapeHtml(place.name)}</div>
        <div style="color:#8c8c8c;font-size:12px;margin-bottom:6px">第 ${point.dayNumber} 天 · ${escapeHtml(start_time)} - ${escapeHtml(end_time)}</div>
        ${rows.join('')}
        <div style="margin-top:10px">
          <a href="${escapeHtml(navUrl)}" target="_blank" rel="noreferrer" style="
            display:inline-block;padding:5px 14px;border-radius:6px;background:${escapeHtml(brandColor)};
            color:#fff;font-size:12px;text-decoration:none;
          ">去这里（导航）</a>
        </div>
      </div>
    `

    infoWindow.setContent(content)
    infoWindow.open(map, point.position)
  }, [brandColor])

  /** 路线规划：按天逐段绘制（驾车），失败降级为直线虚线 */
  const planRoutes = useCallback((targetDays: ItineraryDay[]) => {
    const map = mapRef.current
    const AMap = amapRef.current
    if (!map || !AMap) return

    const seq = ++routeSeqRef.current

    const drawPolyline = (path: unknown[], color: string, opts?: { weight?: number; dashed?: boolean }) => {
      if (!Array.isArray(path) || path.length < 2) return
      const polyline = new AMap.Polyline({
        path,
        strokeColor: color,
        strokeWeight: opts?.weight ?? 6,
        strokeOpacity: 0.85,
        strokeStyle: opts?.dashed ? 'dashed' : 'solid',
        strokeDasharray: opts?.dashed ? [8, 8] : undefined,
        lineJoin: 'round',
        lineCap: 'round',
        zIndex: 110,
      })
      map.add(polyline)
      polylineInstancesRef.current.push(polyline)
    }

    const drawFallback = (a: [number, number], b: [number, number], color: string) => {
      drawPolyline([a, b], color, { weight: 4, dashed: true })
    }

    targetDays.forEach((day) => {
      const positions = day.items.map(toPosition).filter((p): p is [number, number] => p !== null)
      const color = dayColor(day.day_number)

      for (let i = 0; i + 1 < positions.length; i++) {
        const start = positions[i]
        const end = positions[i + 1]
        if (start[0] === end[0] && start[1] === end[1]) continue

        // 驾车路线规划
        const driving = new AMap.Driving({ policy: AMap.DrivingPolicy.LEAST_TIME })
        driving.search(start, end, (status: string, result: any) => {
          if (seq !== routeSeqRef.current) return // 丢弃过期结果
          if (status === 'complete' && result?.routes?.length) {
            const path: unknown[] = []
            result.routes[0].steps.forEach((step: any) => path.push(...(step.path ?? [])))
            drawPolyline(path, color)
          } else {
            drawFallback(start, end, color)
          }
        })
      }
    })
  }, [])

  // 1) 初始化地图（仅一次）
  useEffect(() => {
    let disposed = false
    const container = containerRef.current
    if (!container) return

    if (!__AMAP_JS_API_KEY__) {
      setLoadError('未配置高德地图 Key：请在项目根 .env 中设置 AMAP_JS_API_KEY')
      return
    }

    // 安全密钥必须在 AMapLoader.load 之前配置（JSAPI v2.0 强制鉴权）
    window._AMapSecurityConfig = { securityJsCode: __AMAP_SECURITY_JS_CODE__ }

    AMapLoader.load({
      key: __AMAP_JS_API_KEY__,
      version: '2.0',
      plugins: ['AMap.Scale', 'AMap.ToolBar', 'AMap.ControlBar', 'AMap.Driving'],
    })
      .then((AMap: any) => {
        if (disposed || !containerRef.current) return
        amapRef.current = AMap

        const map = new AMap.Map(containerRef.current, {
          viewMode: '3D',
          zoom: 12,
          center: DEFAULT_CENTER,
        })
        mapRef.current = map

        // 8.4.6 交互控件：比例尺 / 缩放工具栏（右下，关闭定位按钮）/ 3D 旋转俯仰控制条
        map.addControl(new AMap.Scale())
        map.addControl(new AMap.ToolBar({ position: 'RB', locate: false }))
        map.addControl(new AMap.ControlBar({ position: 'RB' }))

        infoWindowRef.current = new AMap.InfoWindow({
          isCustom: false,
          offset: new AMap.Pixel(0, -42),
          autoMove: true,
          closeWhenClickMap: true,
        })

        // 容器尺寸变化（窗口缩放/侧栏折叠）时同步地图
        const onResize = () => map.resize()
        resizeHandlerRef.current = onResize
        window.addEventListener('resize', onResize)

        setMapReady(true)
      })
      .catch((error: unknown) => {
        if (disposed) return
        const detail = error instanceof Error ? error.message : String(error)
        setLoadError(`高德地图加载失败（请检查 AMAP_JS_API_KEY / AMAP_SECURITY_JS_CODE 是否有效）${detail ? `：${detail}` : ''}`)
      })

    return () => {
      disposed = true
      if (resizeHandlerRef.current) window.removeEventListener('resize', resizeHandlerRef.current)
      resizeHandlerRef.current = null
      mapRef.current?.destroy?.()
      mapRef.current = null
      amapRef.current = null
      infoWindowRef.current = null
      markerInstancesRef.current = []
      polylineInstancesRef.current = []
      markersRef.current = []
      setMapReady(false)
    }
  }, [])

  // 2) 数据变化：重建标记与路线
  useEffect(() => {
    const map = mapRef.current
    const AMap = amapRef.current
    if (!map || !AMap || !mapReady) return

    // 清理旧覆盖物
    markerInstancesRef.current.forEach((m) => m.remove?.())
    markerInstancesRef.current = []
    polylineInstancesRef.current.forEach((p) => p.remove?.())
    polylineInstancesRef.current = []
    routeSeqRef.current++ // 使在途路线回调作废

    // 展平点位：只展示选中的那一天（默认第一天），不做「全部」聚合
    const resolvedDay = activeDay > 0 ? activeDay : (days[0]?.day_number ?? 0)
    const filteredDays = resolvedDay > 0 ? days.filter((d) => d.day_number === resolvedDay) : []
    const points: MapPoint[] = []
    filteredDays.forEach((day) => {
      day.items.forEach((item, index) => {
        const position = toPosition(item)
        if (!position) return
        points.push({ placeId: item.place.place_id, dayNumber: day.day_number, order: index + 1, item, position })
      })
    })
    markersRef.current = points

    if (points.length === 0) return

    // 8.4.3 景点标记：起点（绿色图钉「起」）、终点（红色图钉「终」）、途经点（数字序号）
    const instances = points.map((point, index) => {
      const isStart = index === 0
      const isEnd = index === points.length - 1 && points.length > 1

      const content = isStart
        ? endpointMarkerContent('起', '#52c41a')
        : isEnd
          ? endpointMarkerContent('终', '#f5222d')
          : markerContent(point.order, dayColor(point.dayNumber))

      const marker = new AMap.Marker({
        position: point.position,
        title: point.item.place.name,
        content,
        anchor: isStart || isEnd ? 'bottom-center' : 'top-left',
        offset: isStart || isEnd ? new AMap.Pixel(0, 0) : new AMap.Pixel(-13, -13),
        zIndex: isStart || isEnd ? 130 : 120,
      })
      marker.on('click', () => {
        openInfoWindow(point)
        onPlaceClick?.(point.placeId)
      })
      map.add(marker)
      return marker
    })
    markerInstancesRef.current = instances

    // 8.4.4 路线规划（按天着色）
    planRoutes(filteredDays)

    // 8.4.6 视野自适应：所有标记可见
    map.setFitView(instances, false, [60, 60, 60, 60])
  }, [days, activeDay, mapReady, planRoutes, openInfoWindow, onPlaceClick])

  // 3) 点位定位联动（抽屉点选 / 标记点击反馈）
  useEffect(() => {
    const map = mapRef.current
    if (!map || !focusPlaceId) return
    const target = markersRef.current.find((p) => p.placeId === focusPlaceId)
    if (!target) return
    map.setZoomAndCenter(15, target.position)
    openInfoWindow(target)
  }, [focusPlaceId, mapReady, openInfoWindow])

  return (
    <div style={{ position: 'relative', width: '100%', height: 480, borderRadius: 12, overflow: 'hidden' }}>
      <div ref={containerRef} style={{ width: '100%', height: '100%' }} />
      {loadError && (
        <div
          style={{
            position: 'absolute',
            inset: 0,
            zIndex: 999,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            background: 'rgba(255,255,255,.92)',
          }}
        >
          <div style={{ textAlign: 'center', padding: 24, maxWidth: 440 }}>
            <div style={{ fontSize: 14, fontWeight: 600, color: '#cf1322', marginBottom: 8 }}>地图加载失败</div>
            <div style={{ fontSize: 12, color: '#595959' }}>{loadError}</div>
          </div>
        </div>
      )}
    </div>
  )
}
