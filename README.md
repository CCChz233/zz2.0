# zz2.0

zz2.0 是一套围绕 "致真信息大脑" 控制台构建的后端服务与脚本集合，覆盖竞品监测、指标看板、新闻要闻等多个业务场景。仓库内的代码以 Flask + Supabase 为核心，提供可以独立部署的 API 服务、数据处理脚本以及详细的接口文档，帮助团队快速搭建内部情报与监控系统。

## 核心功能
- **每日 AI 简报**：根据 `analysis_results` 与 `competitors` 数据生成高优先级的每日亮点，并支持视角切换。
- **KPI 数据卡**：聚合 Supabase 多张表的最新数据，展示信息增量、竞品更新、论文数量、预警监控等指标，并提供趋势接口。
- **今日全球要闻**：基于准备好的 Supabase 视图返回带摘要的新闻列表与详情。
- **数据处理脚本**：包含面向新闻摘要流程的脚本与说明文档，阐述采集、清洗、摘要、入库的完整链路。

## 目录结构
- `backend_api/`：三套可独立运行的 Flask 服务。
  - `daily-report.py`：每日 AI 简报接口，端口默认 `5003`。
  - `data-cards.py`：指标卡与趋势接口，端口默认 `5002`。
  - `news.py`：新闻列表 / 详情接口，端口默认 `8000`。
- `jobs/`
  - `news_process.py`：面向 `policy_feed_view_latest` 视图的新闻服务脚本（可自定义视图、字段映射）。
  - `news.md`：新闻数据流水线与接口的设计说明。
- `dashboard-api.md`：Dashboard 全量接口契约（含客户线索等扩展模块，便于前端协作）。
- `requirements.txt`：运行依赖（Flask 相关依赖需在此基础上补充 `flask`, `python-dateutil` 等包）。

## 技术栈与外部依赖
- **语言**：Python 3.10+
- **Web 框架**：Flask（各服务以独立脚本启动）
- **数据库**：Supabase (PostgreSQL) + Supabase Python SDK
- **其他库**：`python-dateutil`, `python-dotenv`, `feedparser` (根据需求启用)
- **部署方式**：容器、本地进程或任意 WSGI 容器均可；脚本级服务默认使用 Flask 内置开发服务器。

## 环境变量
以下变量至少需要以环境变量形式提供，或在脚本内硬编码（不建议）：

| 变量名 | 说明 |
| ------ | ---- |
| `SUPABASE_URL` | Supabase 项目实例地址，例如 `https://xxx.supabase.co` |
| `SUPABASE_SERVICE_KEY` | Supabase Service Role Key，用于读写受保护表/视图 |
| `NEWS_FEED_VIEW` | （可选）新闻接口使用的视图名，默认 `news_feed_ready_view` |
| `PORT` | （可选）`daily-report.py` 使用的端口，默认 `5003` |

> 专用表结构：`analysis_results`, `competitors`, `00_papers`, `news`, `news_summaries` 以及多个拼接视图 (`news_feed_ready_view`, `policy_feed_view_latest`)。

## 快速开始
1. **克隆仓库并创建虚拟环境**
   ```bash
   git clone <repo-url>
   cd zz2.0
   python -m venv .venv
   source .venv/bin/activate
   ```
2. **安装依赖**
   ```bash
   pip install -r requirements.txt
   pip install flask python-dateutil
   ```
3. **配置环境变量**（可写入 `.env` 并通过 `python-dotenv` 自动加载，或直接导出）
   ```bash
   export SUPABASE_URL="https://YOUR-PROJECT.supabase.co"
   export SUPABASE_SERVICE_KEY="YOUR-SERVICE-ROLE-KEY"
   ```
4. **启动需要的服务**
   - 每日简报：`python backend_api/daily-report.py`
   - KPI 数据卡：`python backend_api/data-cards.py`
   - 新闻接口：`python backend_api/news.py`

> 各服务默认监听 `0.0.0.0`，可通过环境变量或代码修改端口。

## API 概览
| 模块 | 主要接口 | 描述 |
| ---- | -------- | ---- |
| 每日 AI 简报 (`daily-report.py`) | `GET /api/dashboard/daily-report` | 返回指定日期、指定视角下的 8 条高优先级亮点 |
|  | `PUT /api/dashboard/daily-report/view` | 更新后端当前默认视角（内存态） |
| KPI 数据卡 (`data-cards.py`) | `GET /api/dashboard/data-cards` | 自动定位最新日期，返回 4 张指标卡与环比信息 |
|  | `GET /api/dashboard/data-cards/trend` | 返回指标的最近一周趋势点，用于折线图 |
| 新闻接口 (`news.py`) | `GET /api/dashboard/news` | 分页、分类、关键词检索，返回有摘要的新闻列表 |
|  | `GET /api/dashboard/news/<id>` | 返回指定新闻的详情、长摘要、标签等 |
| 新闻接口 (`jobs/news_process.py`) | 同上 | 面向 `policy_feed_view_latest` 的可替换实现，包含更多容错与标签抽取 |

更完整的请求 / 响应示例，参见 `dashboard-api.md`。

## 数据模型与视图
- `analysis_results`：每日竞品分析结果，含 `competitor_id`, `threat_level`, `summary_report`, `website_content` 等字段。
- `competitors`：竞品画像，含 `name`, `product`, `website`, `last_analyzed`。
- `00_papers`：科研论文元数据，用于计算最新论文数量。
- `news`, `news_summaries`：原始新闻及摘要结果；视图 `news_feed_ready_view` 用于向前端提供结构化字段。
- `policy_feed_view_latest`：策略要闻视图，结合摘要 JSON 字段，可用于标签与推荐等扩展能力。

## 背景任务与脚本
- `jobs/news_process.py` 提供了更通用的新闻接口实现：
  - 自带 `VALID_CATEGORIES`、标签构建、阅读时长估算等逻辑。
  - 支持 `.env` 读取与更健壮的日期解析。
- `jobs/news.md` 记录了新闻数据从抓取、清洗、摘要到接口的完整流程，可作为运维或二次开发的说明文档。

## 开发与调试建议
- Supabase 视图与表名称请与脚本保持一致，修改后需同步调整 Python 代码中的常量。
- 建议为每个 Flask 服务单独创建 `Procfile` 或 systemd 服务，避免端口冲突。
- 可结合 `uvicorn` 或 `gunicorn` 部署到生产环境（需要将 Flask 应用对象暴露为 `app`）。
- 重要改动前建议在本地构造少量测试数据，验证时间解析、分页和排序逻辑。

## 后续规划（来自仓库现有 TODO）
- 多语言摘要能力与更强模型的重跑
- 相关新闻推荐与热点聚类分析
- 更丰富的动作建议生成与客户线索模块接入

如需更多接口细节或字段说明，请参考 `dashboard-api.md` 或代码中的内联注释。
