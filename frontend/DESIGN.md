# 智旅云图前端设计蓝图

> 依据 `.cursor/skills/design-taste-frontend/SKILL.md`（Anti-Slop Frontend Skill）并结合本项目实际落地。
> 该 skill 主要面向营销/落地页，本项目是**产品型 UI**，因此按 skill 的规则选用真实设计系统
> **Ant Design 5**（见 skill 第 2 节与第 13 节），并把品味规则（单一强调色、形状一致、
> 明暗双模式、三态完备、文案纪律）应用到 antd 主题体系上。

---

## 1. 设计读法（Design Read）与旋钮

**Reading this as:** 消费者向的 AI 旅行规划产品 UI（行程生成 / 结果展示 / 历史管理），
以 Ant Design 5 为设计系统，视觉语言沉稳海洋青，功能优先，动效克制。

| 旋钮 | 值 | 说明 |
|------|----|------|
| DESIGN_VARIANCE | 5 | 产品日常密度，左对齐 + 非对称留白，不做营销页花活 |
| MOTION_INTENSITY | 3 | 仅 antd 内置过渡，不引入自定义滚动动效与动画库 |
| VISUAL_DENSITY | 5 | 标准应用密度，数据可呼吸但不过度留白 |

落地载体：`src/theme/index.ts`（设计令牌）+ `src/theme/ThemeContext.tsx`（明暗切换）。
全部颜色来自 antd token，组件内部不写死十六进制。

---

## 2. 设计语言

### 2.1 色彩

| 角色 | 值 | 说明 |
|------|----|------|
| 主色（深海青） | `#0C7C7E` | 全站唯一强调色；白字对比度约 5.0:1，满足 WCAG AA |
| 主色悬浮 | `#1D8F91` | hover 态 |
| 主色按压 | `#0A6668` | active 态 |
| 中性色 | antd 默认灰度 | 不引入第二套暖/冷灰度，保持一致性锁定 |
| 语义色 | antd 默认（成功/警告/错误） | 只表达状态，不承担品牌 |
| 装饰渐变 | `#0C7C7E -> #58BFC2` | 仅用于大面积背景装饰，文本必须落在深色上 |

### 2.2 圆角（单一系统）

- 控件（按钮、输入框、菜单项）：`6px`
- 大容器（卡片、抽屉、弹窗）：`12px`
- 规则一旦确定全站遵守，不允许局部另起炉灶。

### 2.3 字体

- 系统字体栈（PingFang SC / 微软雅黑优先），不引入 Web 字体，避免加载成本。
- 数字与金额统一加 `.num`（tabular-nums）保证纵向对齐。

### 2.4 间距与布局

- 内容区：`max-width 1180px` 居中，由 `layout.contentMaxWidth` 常量控制。
- 页面级间距 `24px`，卡片组内部 `16px`，紧凑分组 `8px`。
- 侧边栏 `216px`，折叠 `64px`，`lg` 断点以下自动折叠。

---

## 3. 页面蓝图与组件树

> 约定：**页面只做组装**，不写业务逻辑；业务组件独立成文件，显式 props 类型；
> 一个页面最多保留 1 个状态容器组件（页面级），其余全部为受控展示组件。

### 3.1 应用外壳 AppLayout（已实现 `src/layouts/AppLayout.tsx`）

```
┌──────────────┬────────────────────────────────────────┐
│ 品牌区(Logo)  │ Header：折叠按钮 ······ 深色模式开关     │
│ 侧边菜单      ├────────────────────────────────────────┤
│ 规划/结果/历史 │ Content（max 1180 居中）                │
│              │   <Outlet />                            │
│              ├────────────────────────────────────────┤
│              │ Footer                                 │
└──────────────┴────────────────────────────────────────┘
```

antd：`Layout / Sider / Header / Content / Footer`、`Menu`、`Avatar`、`Button`、`Switch`。
路由：`/home` `/result` `/history` + 通配 404，页面全部懒加载（`Suspense` + `PageLoading`）。

### 3.2 规划页 Home（8.3 按此实现）

```
Home
├── HeroHeader            Typography.Title + Paragraph（一句话价值主张）
├── TripPlannerForm       Form（表单核心，见下）
│   ├── DestinationField  AutoComplete 目的地 + 城市分级 Tag（A/B/C 提示）
│   ├── DateRangeField    DatePicker.RangePicker（start/end 互校验）
│   ├── PeopleField       InputNumber 人数 + Switch 儿童/老人/无障碍
│   ├── StyleField        Segmented 旅行风格 + Select 预算等级 + Select 天气偏好
│   ├── KeywordsField     Select mode="tags" 偏好关键词 / 排除关键词
│   ├── AdvancedCollapse  Collapse：每日预算上限 / 每日景点上限 / 餐标
│   └── SubmitBar         Button primary「生成行程」+ Button「重置」
├── GenerationProgress    Steps + Progress + Alert（生成中五阶段状态）
└── PresetCities          Tag 快捷填入六个沉淀城市（已实现占位）
```

antd：`Form`、`AutoComplete`、`DatePicker.RangePicker`、`InputNumber`、`Segmented`、
`Select(tags)`、`Switch`、`Collapse`、`Tag`、`Button`、`Steps`、`Progress`、`Alert`、`Space`。
状态：表单值受控；提交 `TripRequest` 后 `navigate('/result', { state: { trip, request } })`。

### 3.3 结果页 Result（8.3 按此实现）

```
Result
├── TripSummaryHeader   Typography 行程名 + Statistic 总览 + Dropdown 导出(Markdown/PDF)
├── TripOverview        描述区：目的地/日期/天数/人均 + Tag 行程亮点（≤5 条）
├── DayTabs             Tabs 按天切换
│   └── DayTimeline     Timeline 时间轴（09:00-11:00 等）
│       └── PlaceCard   Card：地点图片/评分/距离/交通/费用/提示/预约
├── WeatherPanel        Card：每日天气 Descriptions + Alert 出行建议（雨天带伞等）
├── BudgetPanel         Card：Statistic 总预算 + Progress 分项(住宿/餐饮/交通/门票/购物/其他)
├── MapPanel            Card：AmapTripMap 地图 + Drawer 点位列表（8.4 实现地图）
└── EditDayModal        Modal + Input.TextArea 自然语言编辑单日（TripEditRequest）
```

antd：`Tabs`、`Timeline`、`Card`、`Descriptions`、`Statistic`、`Progress`、`Tag`、`Alert`、
`Dropdown`、`Button`、`Drawer`、`Modal`、`Input.TextArea`、`Empty`、`Spin`、`Skeleton`。
兜底：刷新后 `location.state` 为空时展示 `Empty` 引导回规划页（可选加 sessionStorage 快照）。

### 3.4 历史页 History（8.3 按此实现）

```
History
├── HistoryToolbar  Input 搜索目的地 + Select 收藏筛选 + Radio 排序
├── HistoryList     List + Card 摘要行（分页拉取 TripHistoryListResponse）
│   └── HistoryItemCard  目的地 + 日期区间 + Statistic 天数/预算 + Tag 收藏 + Dropdown 操作
├── HistoryPagination  Pagination（limit/offset 与服务端对齐）
└── DeleteConfirm   Popconfirm 删除二次确认
```

antd：`List`、`Card`、`Input`、`Select`、`Radio`、`Tag`、`Button`、`Dropdown`、
`Popconfirm`、`Pagination`、`Empty`、`Skeleton`、`Avatar`、`Statistic`、`Descriptions`。

---

## 4. 目录与开发约定

```
frontend/src
├── components/   业务组件（按域分子目录：trip/weather/budget/map/common）
├── hooks/        通用 hooks（useThemeMode 已建；后续 useTripQuery 等）
├── layouts/      AppLayout.tsx（已实现）
├── pages/        Home / Result / History / NotFound（已建占位，8.3 填充）
├── router/       路由表 + ROUTES 常量（已实现）
├── services/     8.2 落地 axios 实例与接口封装（任务清单 8.2 指定 services/api.ts）
├── styles/       global.css（已实现，只放浏览器基准样式）
├── theme/        设计令牌 + 明暗模式（已实现）
└── types/        类型定义（已实现，对齐后端 schemas）
```

- 页面不写业务逻辑，只做组装与状态编排。
- 组件 props 全部显式类型；枚举选项（旅行风格/预算等级等中文 label 映射）集中为常量，
  不在组件内散落。
- 所有请求统一消费 `types/api.ts` 的 `ApiErrorBody`（`error_code` / `error_message`），
  错误码分支参考 `ApiErrorCode` 常量。
- 目录清理：`src/views/` 是 Vue 时代的遗留空目录，确认无用后可删除。

---

## 5. 状态与数据流

| 场景 | 数据流 |
|------|--------|
| 生成行程 | Home 提交 `TripRequest` → `POST /trip/generate` → `TripResponse` → 存 `location.state` 跳结果页 |
| 单日编辑 | 结果页 `EditDayModal` → `POST /trip/edit`（`TripEditRequest`）→ 返回新 `TripResponse` 就地替换当天 |
| 历史列表 | History 分页拉取 `GET /trip/history` → `TripHistoryListResponse` |
| 删除记录 | `DELETE /trip/history/{trip_id}` → 204 → 列表刷新 |
| 天气 | `GET /weather/{city}?days=3&mode=both` → `CityWeatherResponse` |
| 导出 | `GET /export/markdown/{trip_id}` / `GET /export/pdf/{trip_id}`，浏览器直接下载 |
| 健康检查 | `GET /health` → `HealthCheckResponse`（可做顶栏后端状态灯，可选） |

后端 API 前缀一览（详见 backend/app/api/main.py 注册与各路由）：

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | /trip/generate | 生成行程 |
| POST | /trip/edit | 单日编辑 |
| GET | /trip/history | 历史分页 |
| DELETE | /trip/history/{trip_id} | 删除历史 |
| GET | /export/markdown/{trip_id} | 导出 Markdown |
| GET | /export/pdf/{trip_id} | 导出 PDF |
| GET | /weather/{city} | 实时 + 预报 |
| GET | /health | 健康检查 |

---

## 6. 体验规范（采纳 taste skill 的硬规则）

- **三态完备**：载入用与最终布局同形的 `Skeleton`，空态用 `Empty` + 引导动作，错误内联显示 + toast。
- **明暗双模式**：初始跟随系统，`Switch` 手动切换并持久化 localStorage（已实现）。
- **文案纪律**：全中文；禁用 em dash（—）与 en dash（–），用逗号/冒号/括号断句；
  按钮文案不超过 3 个词；术语与后端一致（行程/预算/沉淀城市）。
- **按钮对比度**：主按钮白字落在主色上（5.0:1，AA 达标），幽灵按钮必有边框。
- **动效克制**：只使用 antd 内置过渡，不引入 Framer/GSAP；尊重 `prefers-reduced-motion`。
- **Tag 只表语义**：不用装饰性标签堆叠，Tag 出现必有含义（城市分级/收藏状态/预算状态）。

---

## 7. 当前进度与下一步

- ✅ 已完成 8.1.1-8.1.5：Vite + React 18 + TS 配置、antd 主题体系、路由、类型定义全对齐。
- ⏳ 8.2 API 服务封装：`services/api.ts` 建 axios 实例（baseURL 读 `VITE_API_BASE_URL`）、
  错误拦截器统一抛 `ApiErrorBody`，按第 5 节表格封装各域接口。
- ⏳ 8.3 视图组件：按 3.2-3.4 组件树逐个实现，先表单后结果页，最后历史页。
- ⏳ 8.4 地图组件：`AmapTripMap.tsx` 集成高德 JS API，供结果页 MapPanel 使用。