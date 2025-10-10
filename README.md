# zz2.0

致真信息大脑（zz2.0）是一套围绕情报中台构建的后端 API 与离线处理脚本集合，覆盖竞品监测、指标看板、要闻速递等业务。服务端采用 Flask Blueprint 统一承载多类接口，数据落地于 Supabase，并配套 Qwen 驱动的摘要/分析流水线，帮助团队快速搭建内部情报看板。

## Highlights
- 统一的 Flask 应用整合日报、指标、新闻、认证等蓝图，确保单进程部署与共享配置。
- 与 Supabase 表/视图深度集成，提供高优先级竞品简报与多种 KPI 指标。
- 提供可直接运行的 Qwen 摘要脚本，实现新闻与竞品分析的自动生成与入库。
- 伴随 `dashboard-api.md` 说明文档，便于前端协作及接口联调。

## Architecture Overview
- **入口应用**：`app.py` 创建 Flask 实例，启用全局 CORS（适配前端端口 9528/3000），并注册 4 个业务 Blueprint。
- **数据源**：所有实时接口都依赖 Supabase（PostgreSQL），通过 `supabase-py` SDK 访问视图与表。
- **模块划分**：
  - `daily_report_bp.py`：每日 AI 简报，包含视角切换、优先级排序、摘要抽取等逻辑。
  - `data_cards_bp.py`：指标卡片与趋势统计，自动寻找最新数据锚点。
  - `news_bp.py`：新闻列表 + 详情接口，提供 AI 建议、阅读时长估算、筛选过滤能力。
  - `user_bp.py`：模拟登录/权限接口，便于前端联调。
- **离线流水线**：`jobs/` 内脚本负责从原始表读取数据、调用 Qwen 模型生成内容，再写回 Supabase。

## Repository Layout
```
app.py                 # Flask 主程序 & 健康检查
backend_api/
  daily_report_bp.py   # 每日简报 API
  data_cards_bp.py     # KPI 数据卡与趋势 API
  news_bp.py           # 新闻列表与详情 API
  user_bp.py           # 用户登录/信息/登出 API
jobs/
  daily-report-process.py  # 竞品分析 -> Qwen 摘要 -> Supabase Upsert
  news_process.py          # 新闻清洗 -> Qwen 摘要 -> Supabase Upsert
  news.md                  # 新闻流水线设计文档
dashboard-api.md       # 面向前端的接口契约与示例
requirements.txt       # API 服务基础依赖
```

## Prerequisites
- Python 3.10+（建议 3.11）
- 可访问的 Supabase 项目（具备 Service Role Key）
- Qwen API Key（运行离线摘要脚本时必需）
- 可选：`python-dotenv` 方便加载 `.env`，`requests` 用于脚本访问 Qwen API（脚本会提示缺失依赖）

## Installation & Local Run
1. 创建虚拟环境并安装依赖：
   ```bash
   python -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   ```
   离线脚本另外需要：
   ```bash
   pip install requests python-dotenv
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
| `NEWS_FEED_VIEW` | `news_feed_ready_view` | 新闻接口使用的 Supabase 视图名称 |

离线脚本还会读取（详见源码说明）：

- `QWEN_API_KEY`, `QWEN_MODEL`
- `VIEW`, `DAYS`, `BATCH_SIZE`, `MAX_BATCHES`, `FORCE_REFRESH`（每日简报脚本）
- `RAW_NEWS_TABLE`, `PIPELINE_MODE`（新闻脚本）

> 代码中保留了演示用的 Supabase 默认地址/密钥，请在实际部署前覆盖为自己的项目配置。

示例 `.env`：
```dotenv
SUPABASE_URL=https://YOUR-PROJECT.supabase.co
SUPABASE_SERVICE_KEY=YOUR-SERVICE-ROLE-KEY
PORT=8000
DAILY_REPORT_DEFAULT_VIEW=management
NEWS_FEED_VIEW=news_feed_ready_view
QWEN_API_KEY=sk-******
QWEN_MODEL=qwen-turbo
RAW_NEWS_TABLE=00_news
PIPELINE_MODE=multi
```

## API Surface
| Blueprint | Endpoint | 说明 |
| --------- | -------- | ---- |
| daily_report | `GET /api/dashboard/daily-report?date=&view=&limit=&offset=` | 返回指定日期/视角下的高优先级亮点，自动去重并排序 |
|  | `PUT /api/dashboard/daily-report/view` | 更新后端当前默认视角（内存保存） |
| data_cards | `GET /api/dashboard/data-cards?period=day\|week\|month` | 汇总新闻、竞品、论文、预警四张 KPI 卡片并计算环比趋势 |
|  | `GET /api/dashboard/data-cards/trend?cardId=1..4` | 返回最近 7 天的单指标趋势点，带日环比 |
| news | `GET /api/dashboard/news?page=&pageSize=&category=&keyword=&date=&view=&onlyAI=&startDate=&endDate=&suggest=` | 新闻列表接口，支持筛选、分页、AI 建议偏好 |
|  | `GET /api/dashboard/news/<news_id>?suggest=` | 新闻详情，返回长摘要、标签、AI 建议等字段 |
| user | `POST /api/user/login` | 模拟登录，返回 token |
|  | `GET /api/user/info?token=` | 根据 token 返回角色、头像等信息 |
|  | `POST /api/user/logout` | 退出登录 |
| system | `GET /healthz` | 健康检查 |
|  | `GET /` | 列出服务概览与可用 API |

详细的请求/响应示例可参考 `dashboard-api.md`。

### API Examples
```bash
# 获取默认视角下的每日简报
curl "http://127.0.0.1:8000/api/dashboard/daily-report?view=management"

# 获取 KPI 数据卡（周维度）
curl "http://127.0.0.1:8000/api/dashboard/data-cards?period=week"

# 查询新闻列表（仅含 AI 建议，时间范围筛选）
curl "http://127.0.0.1:8000/api/dashboard/news?onlyAI=true&startDate=2024-01-01&endDate=2024-01-31&pageSize=10"
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

## Background Jobs
### `jobs/daily-report-process.py`
- 读取 `analysis_results` 与 `competitors`，按视角批量生成竞品亮点。
- 调用 Qwen 输出结构化 JSON（标题、要点、行动建议、标签、优先级等）。
- 写入 `dashboard_daily_reports` 表，并支持 `FORCE_REFRESH` 重算。
- 适合通过 `cron`/定时任务运行：
  ```bash
  export VIEW=management
  python jobs/daily-report-process.py
  ```

### `jobs/news_process.py`
- 从原始新闻表（默认 `00_news`）分页读取，清洗正文噪声。
- 调用 Qwen 生成短摘要、长摘要、行动建议、实体标签等。
- Upsert 到 `news_summaries` 表，供 `news_feed_ready_view` 聚合使用。
- 支持 `PIPELINE_MODE=single`（逐条）与 `multi`（批量）两种模式，内置限流与重试。

### Scheduling
- **本地一次性执行**：直接运行脚本并传递需要的环境变量。
- **Crontab 示例**（每日 07:30 生成日报，08:00 更新新闻摘要）：
  ```cron
  30 7 * * * cd /path/to/zz2.0 && /usr/bin/env -S bash -lc 'source .venv/bin/activate && python jobs/daily-report-process.py >> logs/daily-report.log 2>&1'
  0 8 * * * cd /path/to/zz2.0 && /usr/bin/env -S bash -lc 'source .venv/bin/activate && python jobs/news_process.py >> logs/news-pipeline.log 2>&1'
  ```
- **Supabase Edge Functions / Workers**：如需在云端运行，可将脚本逻辑抽象为函数并部署到 serverless 平台，确保安全地引用 Service Key 与 Qwen Key。

### `jobs/news.md`
- 记录新闻流水线的设计考量、表结构、扩展点与常见问题，建议在运维/二开前先阅读。

## Data Model Notes
- `dashboard_daily_reports`：每日亮点存储，包含 `report_date`, `view`, `priority`, `payload` 等字段。
- `news_feed_ready_view`：面向 API 的汇总视图，整合 `news` 与 `news_summaries`。
- `competitors`, `analysis_results`, `00_papers`：分别承载竞品画像、分析结果与论文统计。
- 若调整表/视图名称，请同步修改 Blueprint 与脚本中的常量定义。

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
  - Qwen API 限流：脚本内部会指数退避重试，仍失败时建议降低 `BATCH_SIZE` 或升级配额。
- **本地 mock**：若暂未接入 Supabase，可将查询逻辑替换为内存字典/JSON 文件，便于快速跑通前端。

## Next Steps
常见的后续扩展包括：
1. 接入更强的模型或多语言输出，提升摘要质量。
2. 为新闻接口补充相关推荐、聚类等智能能力。
3. 衔接客户线索/CRM 模块，实现从情报到行动的闭环。

更多细节可直接查阅源码或 `dashboard-api.md`，亦可根据业务需求自行裁剪模块。祝开发顺利！
