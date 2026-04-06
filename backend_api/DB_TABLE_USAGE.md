# 后端数据库调用清单（Supabase）

本文档基于当前代码目录 `backend/backend_api/` 与 `infra/db.py` 做静态梳理，列出后端**直接调用**的 Supabase 表 / 视图 / RPC（含默认表名与可配置环境变量）。如环境变量覆盖表名，请以实际运行时配置为准。

## 1. 表 / 视图 / RPC 汇总

### 1.1 聊天与会话
- `chat_sessions`  
  - 可配置：`CHAT_SESSIONS_TABLE`（默认 `chat_sessions`）  
  - 读写：`SELECT / INSERT / UPDATE / DELETE`  
  - 相关接口：`/api/agent/chat`、`/api/agent/chat/stream`、`/api/agent/chat/history`、`/api/agent/chat/sessions`  
  - 代码位置：`backend/backend_api/agent_chat_bp.py`

- `chat_messages`  
  - 可配置：`CHAT_MESSAGES_TABLE`（默认 `chat_messages`）  
  - 读写：`SELECT / INSERT / DELETE`  
  - 相关接口：同上  
  - 代码位置：`backend/backend_api/agent_chat_bp.py`

> 表结构参考：`backend/backend_api/chat_tables.sql`

### 1.2 报告与缓存
- `agent_initial_report_view`（视图）  
  - 可配置：`AGENT_REPORT_SOURCE`（默认 `agent_initial_report_view`）  
  - 读写：`SELECT`  
  - 相关接口：`/api/agent/initial-report`  
  - 代码位置：`backend/backend_api/agent_report_bp.py`

- `agent_daily_report_cache`  
  - 可配置：`AGENT_REPORT_CACHE_TABLE`（默认 `agent_daily_report_cache`）  
  - 读写：`SELECT / INSERT`  
  - 相关接口：`/api/agent/initial-report`（缓存落库）  
  - 代码位置：`backend/backend_api/agent_report_bp.py`

- `agent_web_search_cache`  
  - 可配置：`WEB_SEARCH_CACHE_TABLE`（默认 `agent_web_search_cache`）  
  - 读写：`SELECT / INSERT`  
  - 相关功能：联网搜索缓存（被智能体聊天流程调用）  
  - 代码位置：`backend/backend_api/web_search.py`

### 1.3 新闻 / 事件事实表
- `fact_events`（同一张表，被新闻与地图模块复用）  
  - 新闻接口：`NEWS_FEED_TABLE` / `NEWS_FEED_VIEW`（默认 `fact_events`）  
  - 地图接口：`MAP_FACT_TABLE`（默认 `fact_events`）、`MAP_FACT_TIME_FIELD`（默认 `published_at`）  
  - 读写：`SELECT`  
  - 相关接口：`/api/news`、`/api/news/<news_id>`、`/api/databoard/map/data`、`/api/databoard/map/summary`、`/api/databoard/map/trend`  
  - 代码位置：`backend/backend_api/news_bp.py`、`backend/backend_api/databoard_map_bp.py`

> `databoard_map_bp` 会用 `src_table`（可配置：`MAP_SRC_TABLE_FIELD`，默认 `src_table`）过滤数据，过滤值映射为 `00_news / 00_competitors_news / 00_opportunity / 00_papers`，但这些表在地图接口中**不直接查询**。

### 1.4 数据看板统计表（11_ 系列）
这些表用于统计图（只读）：  
- `11_policy_news`  
- `11_industry_news`  
- `11_bid`  
- `11_competitor`  
- `11_paper_trend`  
- `11_paper_pie`  
相关接口：`/api/databoard/data/getNews`（以及 `/getData` 的别名）  
代码位置：`backend/backend_api/databoard_data_bp.py`

### 1.5 KPI / 原始数据表（00_ 系列）
这些表用于 KPI 统计与趋势（只读）：  
- `00_news`  
- `00_competitors_news`  
- `00_opportunity`  
- `00_papers`  
相关接口：`/api/dashboard/data-cards`、`/api/dashboard/data-cards/trend`  
代码位置：`backend/backend_api/data_cards_bp.py`

> `databoard_data_bp.py` 中也定义了 `DATABOARD_NEWS_TABLE / DATABOARD_COMPETITOR_NEWS_TABLE / DATABOARD_OPPORTUNITY_TABLE / DATABOARD_PAPERS_TABLE`（默认 00_*），但当前主路径使用 11_ 统计表；相关 “从原始表统计” 的函数未被路由调用。如需切换到 00_ 原始表统计，需要调整路由/选择逻辑（如 `_news_statistics` / `_competitor_statistics` 等）。

### 1.6 月度汇总表
- `dashboard_daily_events`  
  - 可配置：`DATABOARD_MONTHLY_TABLE`（默认 `dashboard_daily_events`）  
  - 读写：`SELECT`  
  - 相关接口：`/api/databoard/data/getMonthlySummary`、`/api/daily-report`、`/api/daily-report/monthly`  
  - 代码位置：`backend/backend_api/databoard_data_bp.py`、`backend/backend_api/daily_report_bp.py`

> `daily_report_bp.py` 文档注释里提到 `dashboard_daily_reports`，但当前代码实际查询的是 `dashboard_daily_events`。TODO：修正文档注释以保持一致。

### 1.7 维度表（地图）
- `dim_cn_region`  
  - 可配置：`MAP_CN_PROVINCE_DIM_TABLE / MAP_CN_CITY_DIM_TABLE / MAP_CN_DISTRICT_DIM_TABLE`  
  - 读写：`SELECT`  
  - 相关接口：`/api/databoard/map/region` 等  
  - 代码位置：`backend/backend_api/databoard_map_bp.py`

- `dim_country`  
  - 可配置：`MAP_WORLD_DIM_TABLE`（默认 `dim_country`）  
  - 读写：`SELECT`  
  - 相关接口：`/api/databoard/map/region`（world 级别）  
  - 代码位置：`backend/backend_api/databoard_map_bp.py`

### 1.8 Supabase RPC（函数）
- `semantic_search_fact_events`  
  - 可配置：`run_semantic_retrieval(..., rpc=...)`  
  - 读写：`RPC`  
  - 相关功能：RAG 语义检索（智能体聊天流程）  
  - 代码位置：`backend/backend_api/rag/rag_search.py`

## 2. 按模块 / 接口对应关系

- `agent_chat_bp.py`  
  - `/api/agent/chat`、`/api/agent/chat/stream`：写入 `chat_sessions`、`chat_messages`  
  - `/api/agent/chat/history`：读取 `chat_messages`  
  - `/api/agent/chat/sessions`：读取 `chat_sessions`  
  - `/api/agent/chat/sessions/<session_id>`：删除 `chat_messages` + `chat_sessions`

- `agent_report_bp.py`  
  - `/api/agent/initial-report`：读取 `agent_initial_report_view`，写入 / 读取 `agent_daily_report_cache`

- `web_search.py`（被智能体聊天调用）  
  - `agent_web_search_cache`：查询缓存、写入缓存

- `news_bp.py`  
  - `/api/news`、`/api/news/<news_id>`：读取 `fact_events`（或配置的 `NEWS_FEED_TABLE/VIEW`）

- `databoard_data_bp.py`  
  - `/api/databoard/data/getNews`、`/api/databoard/data/getData`：读取 11_ 系列表  
  - `/api/databoard/data/getMonthlySummary`：读取 `dashboard_daily_events`

- `data_cards_bp.py`  
  - `/api/dashboard/data-cards`、`/api/dashboard/data-cards/trend`：读取 00_ 系列表

- `databoard_map_bp.py`  
  - `/api/databoard/map/data`、`/api/databoard/map/summary`、`/api/databoard/map/trend`：读取 `fact_events`  
  - `/api/databoard/map/region`：读取 `dim_cn_region` / `dim_country`

- `daily_report_bp.py`  
  - `/api/daily-report`、`/api/daily-report/monthly`：读取 `dashboard_daily_events`

## 3. 备注
- 若设置了环境变量（如 `NEWS_FEED_TABLE`、`MAP_FACT_TABLE`、`CHAT_*_TABLE` 等），实际访问的表名会被覆盖。
- `databoard_data_bp.py` 中存在“从原始表统计”的备用函数，但当前路由未调用（需调整路由/选择逻辑才会生效）。
- 权限 / RLS：`infra/db.py` 使用 `SUPABASE_SERVICE_KEY` 创建 client，默认走 service role，RLS 会被绕过；如需按用户权限生效，需改为 anon key + 请求侧 JWT，并配置对应 RLS 策略。
- 建议在 Supabase 中保持 `fact_events` 与 `dashboard_daily_events` 的字段与索引一致，以保证看板与新闻接口稳定。

## 4. 写入来源映射（已知 / 待补充）
- `chat_sessions` / `chat_messages`：由后端 `agent_chat_bp.py` 写入。  
- `agent_daily_report_cache`：由 `agent_report_bp.py` 写入（初始报告缓存）。  
- `agent_web_search_cache`：由 `web_search.py` 写入（联网搜索缓存）。  
- `fact_events`：仓库内未定位写入脚本（通常由外部采集/ETL 写入，待补充）。  
- `dashboard_daily_events`：仓库内未定位写入脚本（通常由外部任务聚合写入，待补充）。  
- `00_*` 原始表：仓库内未定位写入脚本（待补充）。  
- `11_*` 统计表：仓库内未定位写入脚本（待补充，通常由离线统计任务生成）。  
- `dim_cn_region` / `dim_country`：维度表写入来源未定位（待补充）。  
