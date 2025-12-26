# zz2.0

致真信息大脑（zz2.0）是一套围绕情报中台构建的后端 API 服务，覆盖竞品监测、指标看板、要闻速递、地图可视化、数据统计分析、智能体报告等业务。服务端采用 Flask Blueprint 统一承载多类接口，数据落地于 Supabase，帮助团队快速搭建内部情报看板。

## Highlights
- 统一的 Flask 应用整合 7 个业务蓝图（日报、指标、新闻、地图、数据、智能体、认证），确保单进程部署与共享配置。
- 与 Supabase 表/视图深度集成，提供高优先级竞品简报、多种 KPI 指标、地理分布数据、趋势分析等能力。
- 完整的 API 文档体系，包含 `dashboard-api.md`、`agent-report-api.md`、`databoard-map-api.md`、`databoard-data-api.md`，便于前端协作及接口联调。
- 支持多视角切换（管理/市场/销售/产品）、智能筛选、分页查询、趋势分析等丰富功能。

## Architecture Overview
- **入口应用**：`app.py` 创建 Flask 实例，启用全局 CORS（适配前端端口 9528/3000），并注册 7 个业务 Blueprint。
- **数据源**：所有实时接口都依赖 Supabase（PostgreSQL），通过 `supabase-py` SDK 访问视图与表。
- **模块划分**：
  - `daily_report_bp.py`：每日 AI 简报，包含视角切换（management/market/sales/product）、优先级排序、摘要抽取、月度汇总等逻辑。
  - `data_cards_bp.py`：指标卡片与趋势统计，自动寻找最新数据锚点，支持日/周/月维度统计。
  - `news_bp.py`：新闻列表 + 详情接口，提供 AI 建议、阅读时长估算、多维度筛选过滤能力。
  - `databoard_map_bp.py`：地图模块 API，提供地理分布数据、区域统计、趋势分析等功能。
  - `databoard_data_bp.py`：数据模块 API，提供新闻趋势、竞品动态、研究论文等统计分析。
  - `agent_report_bp.py`：智能体初始报告接口，支持多维度信息展示（政策解读、论文报告、市场动态等）。
  - `user_bp.py`：用户认证接口，提供模拟登录、用户信息查询、登出等功能。

## Repository Layout
```
app.py                      # Flask 主程序 & 健康检查
backend_api/
  daily_report_bp.py        # 每日简报 API
  data_cards_bp.py          # KPI 数据卡与趋势 API
  news_bp.py                # 新闻列表与详情 API
  databoard_map_bp.py       # 地图模块 API
  databoard_data_bp.py      # 数据模块 API
  agent_report_bp.py        # 智能体初始报告 API
  user_bp.py                # 用户登录/信息/登出 API
  dashboard-api.md          # Dashboard 模块接口文档
  agent-report-api.md       # 智能体报告接口文档
  databoard-map-api.md      # 地图模块接口文档
  databoard-data-api.md     # 数据模块接口文档
requirements.txt            # API 服务基础依赖
README.md                   # 项目说明文档
```

## Prerequisites
- Python 3.10+（建议 3.11）
- 可访问的 Supabase 项目（具备 Service Role Key）
- 可选：`python-dotenv` 方便加载 `.env` 文件

## Installation & Local Run
1. 创建虚拟环境并安装依赖：
   ```bash
   python -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   ```
   如需使用 `.env` 文件管理环境变量，可额外安装：
   ```bash
   pip install python-dotenv
   ```
2. 配置环境变量（可写入 `.env`）：
   ```bash
   export SUPABASE_URL="https://YOUR-PROJECT.supabase.co"
   export SUPABASE_SERVICE_KEY="YOUR-SERVICE-ROLE-KEY"
   ```
3. 启动统一 API 服务：
   ```bash
   python app.py --port 8000
   ```
   服务器默认监听 `0.0.0.0:8000`；也可通过 `PORT` 环境变量覆盖。
4. 健康检查：
   ```bash
   curl http://127.0.0.1:8000/healthz
   ```

## Configuration
核心 API 使用到的环境变量：

| 变量 | 默认值 | 说明 |
| ---- | ------ | ---- |
| `SUPABASE_URL` | _无默认，需显式设置_ | Supabase 项目 URL |
| `SUPABASE_SERVICE_KEY` | _无默认，需显式设置_ | Supabase Service Role Key，用于读写受限表 |
| `PORT` | `8000` | Flask 服务监听端口 |
| `DAILY_REPORT_DEFAULT_VIEW` | `management` | 每日简报的默认视角（management/market/sales/product） |
| `DAILY_REPORT_MAX` | `8` | 每日简报内部抓取上限（仅用于分页窗口） |
| `NEWS_FEED_TABLE` | `fact_events` | 新闻接口使用的 Supabase 表名（兼容旧的 `NEWS_FEED_VIEW` 配置） |
| `AGENT_REPORT_SOURCE` | `agent_initial_report_view` | 智能体报告数据源视图 |
| `AGENT_REPORT_LIMIT` | `12` | 智能体报告返回条目数上限 |
| `AGENT_REPORT_CACHE_TABLE` | `agent_daily_report_cache` | 智能体初始报告缓存表 |
| `AGENT_REPORT_GENERATION_ENABLED` | `true` | 是否允许生成新报告（false 时仅使用缓存，refresh=1 可强制生成） |
| `AGENT_REPORT_REFRESH_MINUTES` | `1440` | 智能体报告刷新间隔（分钟） |
| `DATABOARD_NEWS_TABLE` | `00_news` | 数据模块新闻表名 |
| `DATABOARD_COMPETITOR_NEWS_TABLE` | `00_competitors_news` | 数据模块竞品新闻表名 |
| `DATABOARD_COMPETITORS_TABLE` | `00_competitors` | 数据模块竞品公司表名 |
| `DATABOARD_PAPERS_TABLE` | `00_papers` | 数据模块论文表名 |
| `DATABOARD_OPPORTUNITY_TABLE` | `00_opportunity` | 数据模块招标机会表名 |
| `DATABOARD_NEWS_MONTHS` | `12` | 新闻趋势默认月份数 |
| `DATABOARD_TREND_MONTHS` | `6` | 竞品/研究趋势月份数 |
| `MAP_FACT_TABLE` | `fact_events` | 地图模块事实表名（可通过环境变量覆盖） |
| `USE_WEB_SEARCH` | `true` | 聊天是否启用联网搜索 |
| `WEB_SEARCH_TOPK` | `6` | 联网搜索返回条数 |
| `WEB_SEARCH_CACHE_MINUTES` | `30` | 联网搜索缓存分钟数 |
| `WEB_SEARCH_MIN_SCORE` | `0` | 联网搜索最低分过滤 |
| `WEB_SEARCH_CACHE_TABLE` | `agent_web_search_cache` | 联网搜索缓存表 |

> 代码中保留了演示用的 Supabase 默认地址/密钥，请在实际部署前覆盖为自己的项目配置。

示例 `.env`：
```dotenv
SUPABASE_URL=https://YOUR-PROJECT.supabase.co
SUPABASE_SERVICE_KEY=YOUR-SERVICE-ROLE-KEY
PORT=8000
DAILY_REPORT_DEFAULT_VIEW=management
NEWS_FEED_TABLE=fact_events
AGENT_REPORT_SOURCE=agent_initial_report_view
AGENT_REPORT_LIMIT=12
AGENT_REPORT_CACHE_TABLE=agent_daily_report_cache
AGENT_REPORT_GENERATION_ENABLED=true
AGENT_REPORT_REFRESH_MINUTES=1440
DATABOARD_NEWS_TABLE=00_news
DATABOARD_COMPETITOR_NEWS_TABLE=00_competitors_news
DATABOARD_COMPETITORS_TABLE=00_competitors
DATABOARD_PAPERS_TABLE=00_papers
DATABOARD_OPPORTUNITY_TABLE=00_opportunity
DATABOARD_NEWS_MONTHS=12
DATABOARD_TREND_MONTHS=6
USE_WEB_SEARCH=true
WEB_SEARCH_TOPK=6
WEB_SEARCH_CACHE_MINUTES=30
WEB_SEARCH_MIN_SCORE=0
WEB_SEARCH_CACHE_TABLE=agent_web_search_cache
```

## API Surface
| Blueprint | Endpoint | 说明 |
| --------- | -------- | ---- |
| daily_report | `GET /api/dashboard/daily-report?date=&view=&limit=&offset=` | 返回指定日期/视角下的高优先级亮点，自动去重并排序 |
|  | `GET /api/dashboard/daily-report/monthly?year=&month=&view=` | 获取月度汇总报告 |
|  | `PUT /api/dashboard/daily-report/view` | 更新后端当前默认视角（内存保存） |
| data_cards | `GET /api/dashboard/data-cards?period=day\|week\|month` | 汇总新闻、竞品、论文、预警四张 KPI 卡片并计算环比趋势 |
|  | `GET /api/dashboard/data-cards/trend?cardId=1..4` | 返回最近 7 天的单指标趋势点，带日环比 |
| news | `GET /api/dashboard/news?page=&pageSize=&category=&keyword=&date=&view=&onlyAI=&startDate=&endDate=&suggest=` | 新闻列表接口，支持筛选、分页、AI 建议偏好 |
|  | `GET /api/dashboard/news/<news_id>?suggest=` | 新闻详情，返回长摘要、标签、AI 建议等字段 |
| databoard_map | `GET /api/databoard/map/data?type=&startDate=&endDate=&region=` | 获取地图数据，支持按类型、时间、区域筛选 |
|  | `GET /api/databoard/map/region?type=&date=` | 获取区域统计数据 |
|  | `GET /api/databoard/map/summary?type=&startDate=&endDate=` | 获取地图汇总信息 |
|  | `GET /api/databoard/map/trend?type=&region=&days=` | 获取地图趋势数据 |
| databoard_data | `GET /api/databoard/data/getNews` | 获取新闻趋势统计数据 |
|  | `GET /api/databoard/data/getData` | 获取竞品动态、研究论文等综合数据 |
|  | `GET /api/databoard/data/getMonthlySummary` | 获取月度汇总数据 |
| agent_report | `GET /api/agent/initial-report` | 获取智能体初始报告（政策解读、论文报告、市场动态等） |
|  | `GET /agent/initial-report` | 兼容旧路径的智能体报告接口 |
| user | `POST /api/user/login` | 模拟登录，返回 token |
|  | `GET /api/user/info?token=` | 根据 token 返回角色、头像等信息 |
|  | `POST /api/user/logout` | 退出登录 |
| system | `GET /healthz` | 健康检查 |
|  | `GET /` | 列出服务概览与可用 API |

详细的请求/响应示例可参考各模块对应的 API 文档：
- `backend_api/dashboard-api.md` - Dashboard 模块接口文档
- `backend_api/agent-report-api.md` - 智能体报告接口文档
- `backend_api/databoard-map-api.md` - 地图模块接口文档
- `backend_api/databoard-data-api.md` - 数据模块接口文档

## Cache Tables (Optional)

如需启用智能体初始报告与联网搜索缓存（跨进程持久化），请在 Supabase 执行：

```
backend/backend_api/agent_cache_tables.sql
```

说明：智能体日报缓存表已支持“同一天多条记录”，如需从旧表结构迁移，请按 `agent_cache_tables.sql` 里的迁移提示执行。

### API Examples
```bash
# 获取默认视角下的每日简报
curl "http://127.0.0.1:8000/api/dashboard/daily-report?view=management"

# 获取 KPI 数据卡（周维度）
curl "http://127.0.0.1:8000/api/dashboard/data-cards?period=week"

# 查询新闻列表（仅含 AI 建议，时间范围筛选）
curl "http://127.0.0.1:8000/api/dashboard/news?onlyAI=true&startDate=2024-01-01&endDate=2024-01-31&pageSize=10"

# 获取地图数据（新闻类型，最近30天）
curl "http://127.0.0.1:8000/api/databoard/map/data?type=news&startDate=2024-01-01&endDate=2024-01-31"

# 获取数据模块综合统计
curl "http://127.0.0.1:8000/api/databoard/data/getData"

# 获取智能体初始报告
curl "http://127.0.0.1:8000/api/agent/initial-report"
```

典型响应（节选）：
```json
{
  "code": 200,
  "message": "success",
  "data": {
    "date": "2024-03-18",
    "view": "management",
    "highlights": [
      {
        "id": 1,
        "category": "竞品动态",
        "content": "竞品A：核心摘要... 建议：对竞品A建立专项跟踪...",
        "priority": "high",
        "priorityText": "高",
        "createdAt": "2024-03-18T09:12:00Z"
      }
    ]
  }
}
```

## 数据模型说明
项目依赖以下 Supabase 表/视图结构：

### 核心表
- `dashboard_daily_reports`：每日亮点存储，包含 `report_date`, `view`, `priority`, `payload` 等字段
- `fact_events`：事实表（新闻接口与地图模块统一使用），包含 `news_type`、摘要、来源等字段
- `agent_initial_report_view`：智能体初始报告数据源视图

### 业务表
- `00_news`：原始新闻表，包含 `publish_time`, `news_type` 等字段
- `00_competitors_news`：竞品新闻表，包含 `publish_time`, `title`, `content` 等字段
- `00_competitors`：竞品公司表，包含 `id`, `company_name` 等字段
- `00_papers`：论文表，包含 `published_at`, `keywords_matched` 等字段
- `00_opportunity`：招标机会表，包含 `publish_time` 等字段
- `competitors`：竞品画像表
- `analysis_results`：分析结果表

> 若调整表/视图名称，请同步修改对应 Blueprint 中的常量定义或环境变量配置。


## Development Tips
- 默认 CORS 白名单包含 `http://localhost:9528` 与 `http://localhost:3000`，若前端域名不同请在 `app.py` 中调整。
- Blueprint 结构便于扩展：创建新模块后，只需在 `app.py` 注册即可加入统一服务。
- 建议在 Supabase 中预先准备少量测试数据，验证日期解析、分页、排序等逻辑。
- 部署到生产时可改用 `gunicorn` 等 WSGI Server：`gunicorn -w 4 "app:app" --bind 0.0.0.0:8000`。
- 配置密钥时避免使用仓库中示例值，确保 Service Key 权限仅限必要表。

## Testing & Troubleshooting
- **接口联调**：推荐使用 `httpie` 或 `curl` 搭配 `jq`，快速验证过滤条件、分页与响应格式。
- **调试 Supabase 请求**：Blueprint 中的查询均打印在异常路径，可在本地增加 `print`/`logging` 定位问题；留意日期字段是否带时区。
- **常见错误**：
  - `Missing SUPABASE_URL or SUPABASE_SERVICE_KEY`：确认环境变量是否在当前 shell 导出，或 `.env` 是否被 `python-dotenv` 读取。
  - `Invalid cardId` / `invalid view`：前端参数校验未覆盖，可在请求前限制取值集合。
  - `Table/View not found`：检查 Supabase 中对应的表/视图是否存在，字段名是否匹配。
  - `CORS error`：确认前端域名是否在 `app.py` 的 CORS 白名单中。
- **本地 mock**：若暂未接入 Supabase，可将查询逻辑替换为内存字典/JSON 文件，便于快速跑通前端。
- **性能优化**：对于大数据量查询，建议在 Supabase 中创建适当的索引，并合理使用分页参数。

## Next Steps
常见的后续扩展包括：
1. 接入 AI 模型增强摘要质量，为新闻和报告提供更智能的分析。
2. 为新闻接口补充相关推荐、聚类等智能能力。
3. 衔接客户线索/CRM 模块，实现从情报到行动的闭环。
4. 扩展地图模块，支持更多地理维度的数据可视化。
5. 优化数据模块，提供更丰富的统计维度和自定义报表功能。

更多细节可直接查阅源码或各模块对应的 API 文档，亦可根据业务需求自行裁剪模块。祝开发顺利！
