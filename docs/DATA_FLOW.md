# 智旅云图 - 数据流图说明

> 本文档描述行程生成、检索、编辑、导出等核心链路的数据流转。

## 1. 端到端数据流（行程生成）

```
用户输入（目的地/日期/预算/人数/偏好）
    │
    ▼
POST /trip/generate（TripRequest, user_id 可选）
    │
    ▼
trip_service.generate_trip()
    │
    ├─ 1. 城市归一化（"北京市" → "北京"，guide_catalog.resolve_city）
    ├─ 2. 缓存命中检查（Redis，key = md5(请求摘要)）
    ├─ 3. 城市分级路由（A 级 → RAG；B 级 → POI 三池；C 级 → 400）
    ├─ 4. Agent.plan → LangGraph 主图生成行程草案
    ├─ 5. 地图补全（高德 geocode + POI 图片 + 餐饮/住宿真实信息）
    ├─ 6. 天气补全（高德天气 API + LLM 出行建议）
    ├─ 7. 预算二次校正（基于补全后的真实门票）
    ├─ 8. 元数据回填（token 用量 / warnings / 耗时）
    ├─ 9. 持久化到 SQLite（create_trip 回填 trip_id）
    └─ 10. 写回缓存
    │
    ▼
TripResponse（含每日行程、地图、天气、预算、贴士、trip_id）
    │
    ▼
前端 Result 页渲染（行程时间线 + 地图标记/路线 + 天气 + 预算）
```

## 2. Agent 主图数据流（LangGraph）

```
START
  → prefetch_rag（沉淀城市预取攻略上下文）
  → llm_plan（LLM 生成；可能发起 tool_calls）
      ├─ 有 tool_calls → rag_tools（search_travel_guides）→ llm_plan
      ├─ 无 tool_calls → parse_draft（抽取 Draft JSON）
      │     ├─ 解析成功 → validate_repair（校验/修复，缺景点自动补选）
      │     ├─ 解析失败 → repair_json（LLM 修复 JSON）→ parse_draft
      │     └─ 失败 → fallback（降级模板）
      └─ 失败 → fallback
  → build_trip（Draft → TripResponse）
  → enrich_budget（预算拆分与汇总）
  → END
```

关键点：
- `prefetch_rag` 让沉淀城市在首轮 LLM 调用前就带上下文，减少工具往返。
- 任意步骤出错且 `allow_fallback=True` 时走 `fallback`，用攻略模板生成兜底行程，保证接口不失败。

## 3. RAG 检索链路（沉淀城市）

```
用户查询
  → Query 预处理（城市/天数提取）
  → 意图识别（景点/餐饮/住宿/行程）
  → 查询扩展（supplementary terms）
  → 向量检索（ChromaDB, 256 维 embedding）
  → Cross-encoder Rerank（threshold 0.35）
  → 检索缓存（key = query + city + intent）
  → RAGChunk 列表（压缩至 token 预算，带引用编号）
  → 组装 tool message 回传 LLM
```

降级策略：向量库为空 / 检索失败时返回空结果，由 Agent 走 fallback 或放宽过滤重试。

## 4. 动态城市链路（B 级，POI 候选池）

```
TripRequest（动态城市）
  → place_candidate_service.build_pool
      ├─ build_query_plan（按偏好生成查询计划）
      ├─ 拉取景点/餐饮/住宿三池（高德 place/text + place/around，含缓存）
      ├─ 区域聚类（district_clusters）
      └─ 打分排序（filter_and_rank：类别/评分/距离加权）
  → 组装 Prompt sections（scenic / food / hotel / clusters）
  → Agent.plan（candidate_sections, use_tools=False）
  → 地图补全（geocode 真实坐标 + 图片）
```

景点池为空或拉取失败 → 回退 `Agent.plan(use_tools=True)` RAG 路径。

## 5. 单日编辑链路

```
POST /trip/edit（trip_id + day_number + instruction + context）
  → trip_service.edit_trip_day
  → storage 读取原行程 → 反推 TripRequest
  → edit_day_graph：
      build_edit_day_input（只保留目标日 + 其他日地点排除清单）
        → llm_plan ⇄ rag_tools（可选检索）
        → parse_draft → validate/repair
        → merge_edit_day（合并回原行程）
  → 单日地图补全（geocode + 餐饮/住宿，复用 photo_cache）
  → 持久化更新 + 返回编辑后完整 TripResponse
```

## 6. 导出链路

```
GET /export/markdown/{trip_id} 或 /export/pdf/{trip_id}
  → storage_service.get_trip（行程不存在 → 404）
  → export_service.export_to_markdown / export_to_pdf
      - Markdown：结构化文本（含每日明细、预算、分类贴士）
      - PDF：HTML/CSS 模板 → WeasyPrint 渲染
  → Response（Content-Disposition 携带中文文件名，RFC 5987）
  → 前端 blob 下载
```

## 7. 天气链路

```
GET /weather/{city}?days=3&mode=both
  → weather_service.get_live_weather / get_forecast / get_city_adcode
  → 高德 v3 weather/weatherInfo（限流 0.2s + 指数退避重试）
  → Redis 缓存（实时 30 分钟 / 预报 6 小时）
  → CityWeatherResponse（live + forecast 列表）
```

天气是补充信息：查无数据返回 200 + 空结构，不阻断行程主流程；服务不可用返回 503。

## 8. 数据持久化

- **SQLite**（`trips.db`）：`trip_history` 表存储请求/响应 JSON + 索引字段（目的地、日期、用户、收藏）。
- **ChromaDB**（`chroma_db/`）：攻略分块向量库，按城市组织，支持增量更新与备份恢复。
- **Redis**（可选，`CACHE_ENABLED=true`）：行程结果、天气、地图、RAG 检索缓存。
- **文件系统**：`backend/data/guides/` 攻略原文、`backend/exports/` 导出产物、`backend/logs/app.log` 日志。

---

相关文档：[README.md](../README.md) · [技术架构](ARCHITECTURE.md) · [环境变量](ENVIRONMENT.md) · [启动方式](STARTUP.md) · [API 文档](API.md)
