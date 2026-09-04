# 智旅云图前端设计蓝图（v2 · 山海拾光）

> 依据 `.cursor/skills/design-taste-frontend/SKILL.md`（Anti-Slop Frontend Skill）并结合本项目实际落地。
> v2 为全面重设计：主题、交互、界面全部焕新，**核心流程不变**（规划 → 生成 → 结果 → 历史 → 导出）。
> 设计系统仍为 **Ant Design 5**（见 skill 第 2 节与第 13 节），把品味规则（单一强调色、形状一致、
> 明暗双模式、三态完备、文案纪律）应用到 antd 主题体系上。

---

## 1. 设计读法（Design Read）与旋钮

**Reading this as:** 消费者向 AI 旅行规划产品 UI 的全面重设计（行程生成 / 结果展示 / 历史管理），
以 Ant Design 5 为设计系统，视觉语言「温暖旅行编辑感 / 明信片杂志」（奶油纸 + 陶土日出橙 + 暖墨 + 宋体衬线标题），
反模板化：不用 AI 紫渐变、不做深色网格、不堆三张等宽卡片。

| 旋钮 | 值 | 说明 |
|------|----|------|
| DESIGN_VARIANCE | 7 | 编辑感的不对称与装饰（Hero 暖阳底纹、明信片封面、胶囊 Tag），但不失控 |
| MOTION_INTENSITY | 4 | antd 内置过渡 + 少量 hover 抬升与页面淡入，尊重 `prefers-reduced-motion` |
| VISUAL_DENSITY | 4 | 比 v1（5）更轻盈，数据可呼吸但不过度留白 |

落地载体：`src/theme/index.ts`（设计令牌）+ `src/theme/ThemeContext.tsx`（明暗切换，同步 `data-theme`）+ `src/styles/global.css`（纸张/暖墨变量、衬线标题、卡片质感）。
全部颜色来自 antd token 或 global.css 的 `--zl-*` 变量，组件内部不散落硬编码十六进制（语义色与封面渐变除外）。

---

## 2. 设计语言

### 2.1 色彩（暖调，与 v1 深海青切割）

| 角色 | 值 | 说明 |
|------|----|------|
| 主色（陶土日出橙） | `#C0472F` | 全站唯一强调色；白字对比度约 5.0:1，满足 WCAG AA |
| 主色悬浮 | `#D15B43` | hover 态 |
| 主色按压 | `#9C3723` | active 态 |
| 点缀金 | `#E8A33D` | 评分 / 高亮 / 装饰渐变（不承担主按钮） |
| 辅助青绿 | `#2F7D7A` | 保留 v1 海洋青基因，用于天气等次级信息 |
| 浅色纸张 | `#FBF6EE`（页底）/ `#FFFDF8`（卡片） | 奶油纸质感 |
| 暖墨文本 | `#2B2118` | 大面积段落标题 |
| 暗色模式 | 暖炭 `#201A14` + 米色文字 `#F0E6D6` | 明暗自适应，不走纯黑 |
| 装饰渐变 | `#C0472F -> #E8A33D` | 仅用于 Hero / 封面 / 明信片 / 图标块，文本必须落在深色或白字上 |

### 2.2 形状（单一圆角系统）

- 控件（按钮、输入框、菜单项）：`8px`，主 CTA 与胶囊 Tag：`999px`
- 大容器（卡片、抽屉、弹窗）：`16px`，封面 / Hero：`20px`
- 规则一旦确定全站遵守，不允许局部另起炉灶。

### 2.3 字体

- 正文：系统无衬线栈（PingFang SC / 微软雅黑优先），不引入 Web 字体。
- 标题：宋体衬线栈 `.zl-serif`（`Noto Serif SC / Songti SC / SimSun`），旅行杂志编辑感，无加载成本。
- 数字与金额统一加 `.num`（tabular-nums）保证纵向对齐。

### 2.4 间距与布局

- 内容区：`max-width 1180px` 居中，由 `layout.contentMaxWidth` 常量控制。
- 页面级间距 `20-28px`，卡片组内部 `16-24px`，紧凑分组 `8px`。
- 导航从 v1 侧边栏改为**顶部导航**（品牌 + 横向菜单 + 明暗开关，sticky + 毛玻璃），高度 64px。

---

## 3. 页面蓝图与组件树

> 约定不变：**页面只做组装**，不写业务逻辑；业务组件独立成文件，显式 props 类型。

### 3.1 应用外壳 AppLayout（已重写 `src/layouts/AppLayout.tsx`）

```
┌────────────────────────────────────────────────────────┐
│ Header(sticky)：品牌(Rocket 渐变块 + 智旅云图) · 菜单(规划/结果/历史) · 明暗开关 │
├────────────────────────────────────────────────────────┤
│ Content（max 1180 居中，.zl-page 淡入）                 │
│   <Outlet />                                           │
├────────────────────────────────────────────────────────┤
│ Footer                                                 │
└────────────────────────────────────────────────────────┘
```

antd：`Layout / Header / Content / Footer`、`Menu(mode=horizontal)`、`Button`。
路由：`/home` `/result` `/history` + 通配 404，页面全部懒加载（`Suspense` + `PageLoading`）。

### 3.2 规划页 Home（已重写）

```
Home
├── Hero（.zl-hero 暖阳底纹）：Tag 徽章 + 宋体大标题「把想去的远方，排成一天天的好日子。」
│   + 副文案 + 沉淀城市快捷胶囊（点击填入表单 destination）
├── TripPlannerForm（分区表单卡片）
│   ├── 01 去哪儿：DestinationField（AutoComplete + 城市分级 Tag） + DateRangeField
│   ├── 02 和谁去：PeopleField（人数 + 儿童/老人/无障碍开关） + StyleField（节奏/预算/天气）
│   ├── 03 怎么玩：KeywordsField（偏好 / 排除关键词）
│   ├── AdvancedCollapse（每日预算上限 / 景点上限 / 餐标 / 室内外 / 备注）
│   └── SubmitBar（胶囊主按钮「开始生成行程」+ 重置 + 耗时提示）
└── GenerationProgress（生成中：旅途站点 Steps + 渐变 Progress + 提示）
```

数据流不变：`TripPlannerForm.onSubmit(TripRequest)` → Home → `POST /trip/generate` → 快照 + 跳转结果页。

### 3.3 结果页 Result（已重写）

```
Result
├── 行程封面（.zl-hero）：目的地 Tag + 宋体行程名 + 日期区间
│   ├── 概览统计条：天数 / 人均预算 / 综合评分（图标块 + 数字）
│   ├── 行程亮点胶囊
│   └── 操作：返回规划 / 编辑当天 / 导出(Markdown·PDF)
├── Day 导航条：胶囊按钮「第 N 天 · MM-DD」（横向可滚动）
├── 两栏内容
│   ├── 左：当日时间线（DayTimeline 日期徽章 + 时间节点 + PlaceCard 纸张卡片 + 编辑当天）
│   └── 右：WeatherPanel + BudgetPanel（纸张卡片）
├── MapPanel（行程地图，天筛选 + 图例 + 点位抽屉）
├── 特殊需求保障 / 推荐美食（纸张卡片并排）
└── 行程贴士（分组纸张卡片）
```

数据流不变：`location.state` → `?trip_id=` → 快照；单日编辑 `POST /trip/edit` 就地替换。

### 3.4 历史页 History（已重写）

```
History
├── 标题「我的旅行手账」+ 副文案
├── 工具条（纸张卡片）：全选本页 / 目的地搜索（防抖）/ 收藏筛选 / 排序 Radio / 共 N 条
│   └── 批量操作栏（已选 N 条：批量收藏 / 取消收藏 / 批量删除 Popconfirm / 清除选择）
├── 明信片墙（Row/Col 网格，xs24/sm12/lg8）
│   └── HistoryCard：渐变封面（目的地首字大号宋体 + 收藏/模型 Tag）+ 目的地 + 复选框
│       + 日期区间 + 天数/预算 + 生成时间 + 查看/导出/删除（Popconfirm）
├── 骨架（loading 时 6 张占位卡）/ 空态
└── Pagination（limit/offset 与服务端对齐）
```

数据流不变：分页拉取 `GET /trip/history`、`DELETE /trip/history/{trip_id}`、批量删除/收藏、点击卡片 `?trip_id=` 回看。

---

## 4. 目录与开发约定

- 目录结构不变（见 AGENTS.md），v2 新增能力集中在 `styles/global.css`（CSS 变量 + 工具类）与 `theme/index.ts`。
- 页面不写业务逻辑，只做组装与状态编排；组件 props 全部显式类型。
- 所有请求统一消费 `services/api.ts`；错误码分支参考 `ApiErrorCode`。
- **色彩纪律**：品牌色一律经 `theme/index.ts` 的 `brand` 与 antd token；纸张/暖墨经 `--zl-*` CSS 变量；
  组件内只允许语义色（成功/警告/错误）与封面渐变的局部硬编码。

---

## 5. 状态与数据流

与 v1 完全一致（生成 / 编辑 / 历史 / 天气 / 导出 / 健康检查），接口清单见 `docs/API.md` 与 `frontend/src/services/api.ts`。

---

## 6. 体验规范（采纳 taste skill 的硬规则）

- **三态完备**：载入用与最终布局同形的 Skeleton / 占位卡，空态用引导文案，错误内联 + toast。
- **明暗双模式**：初始跟随系统，顶部按钮手动切换并持久化 localStorage；`data-theme` 驱动 CSS 变量。
- **文案纪律**：全中文；按钮文案不超过 3 个词；术语与后端一致（行程/预算/沉淀城市）。
- **按钮对比度**：主按钮白字落在陶土橙上（约 5.0:1，AA 达标），幽灵按钮必有边框。
- **动效克制**：antd 内置过渡 + hover 抬升 + 页面淡入；尊重 `prefers-reduced-motion`。
- **Tag 只表语义**：胶囊 Tag 用于城市分级 / 收藏状态 / 亮点 / 美食，不堆装饰性标签。
- **可访问性**：明信片卡片 `role="button"` + 键盘回车支持；图标按钮带 aria-label。

---

## 7. 版本记录

- v1（2026-09-04 前）：沉稳海洋青，侧边栏布局，VARIANCE 5 / MOTION 3 / DENSITY 5。
- v2（2026-09-04）：山海拾光主题重设计。颜色切陶土日出橙 + 奶油纸；标题切宋体衬线；
  布局切顶部导航；首页 Hero + 分区表单；结果页封面 + 概览条 + 胶囊 Day 导航 + 两栏内容；
  历史页改明信片墙；404 旅行迷路主题；地图天配色同步新调色板。核心流程与接口零改动。
