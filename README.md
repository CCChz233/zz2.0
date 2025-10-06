# zz2.0

zz2.0 是一套围绕 "致真信息大脑" 控制台构建的后端服务与脚本集合，覆盖竞品监测、指标看板、新闻要闻等多个业务场景。仓库内的代码以 Flask + Supabase 为核心，使用 Blueprint 模式提供统一部署的 API 服务、数据处理脚本以及详细的接口文档，帮助团队快速搭建内部情报与监控系统。

## 核心功能
- **每日 AI 简报**：根据 `analysis_results` 与 `competitors` 数据生成高优先级的每日亮点，并支持视角切换。
- **KPI 数据卡**：聚合 Supabase 多张表的最新数据，展示信息增量、竞品更新、论文数量、预警监控等指标，并提供趋势接口。
- **今日全球要闻**：基于准备好的 Supabase 视图返回带摘要的新闻列表与详情。
- **数据处理脚本**：包含面向新闻摘要流程的脚本与说明文档，阐述采集、清洗、摘要、入库的完整链路。

## 目录结构
- `app.py`：主应用文件，使用 Flask Blueprint 整合所有 API 服务，统一端口 `5000`。
- `backend_api/`：四个 Blueprint 模块。
  - `daily_report_bp.py`：每日 AI 简报 Blueprint。
  - `data_cards_bp.py`：指标卡与趋势 Blueprint。
  - `news_bp.py`：新闻列表 / 详情 Blueprint。
  - `user_bp.py`：用户认证 Blueprint。
- `jobs/`
  - `news_process.py`：面向 `policy_feed_view_latest` 视图的新闻服务脚本（可自定义视图、字段映射）。
  - `news.md`：新闻数据流水线与接口的设计说明。
- `dashboard-api.md`：Dashboard 全量接口契约（含客户线索等扩展模块，便于前端协作）。
- `requirements.txt`：运行依赖（包含 Flask、Flask-CORS、Supabase、python-dateutil 等）。

## 技术栈与外部依赖
- **语言**：Python 3.10+
- **Web 框架**：Flask + Blueprint（统一应用架构）
- **数据库**：Supabase (PostgreSQL) + Supabase Python SDK
- **其他库**：`python-dateutil`, `python-dotenv`, `feedparser` (根据需求启用)
- **部署方式**：容器、本地进程或任意 WSGI 容器均可；统一使用 Flask 内置开发服务器。

## 环境变量
以下变量至少需要以环境变量形式提供，或在脚本内硬编码（不建议）：

| 变量名 | 说明 |
| ------ | ---- |
| `SUPABASE_URL` | Supabase 项目实例地址，例如 `https://xxx.supabase.co` |
| `SUPABASE_SERVICE_KEY` | Supabase Service Role Key，用于读写受保护表/视图 |
| `NEWS_FEED_VIEW` | （可选）新闻接口使用的视图名，默认 `news_feed_ready_view` |
| `PORT` | （可选）统一服务使用的端口，默认 `5000` |

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
   ```
3. **配置环境变量**（可写入 `.env` 并通过 `python-dotenv` 自动加载，或直接导出）
   ```bash
   export SUPABASE_URL="https://YOUR-PROJECT.supabase.co"
   export SUPABASE_SERVICE_KEY="YOUR-SERVICE-ROLE-KEY"
   ```
4. **启动统一服务**
   ```bash
   python app.py
   ```

> 服务默认监听 `0.0.0.0:5000`，可通过环境变量 `PORT` 修改端口。所有 API 服务现在统一在一个应用中运行。

## API 概览
| 模块 | 主要接口 | 描述 |
| ---- | -------- | ---- |
| 每日 AI 简报 (`daily_report_bp.py`) | `GET /api/dashboard/daily-report` | 返回指定日期、指定视角下的 8 条高优先级亮点 |
|  | `PUT /api/dashboard/daily-report/view` | 更新后端当前默认视角（内存态） |
| KPI 数据卡 (`data_cards_bp.py`) | `GET /api/dashboard/data-cards` | 自动定位最新日期，返回 4 张指标卡与环比信息 |
|  | `GET /api/dashboard/data-cards/trend` | 返回指标的最近一周趋势点，用于折线图 |
| 新闻接口 (`news_bp.py`) | `GET /api/dashboard/news` | 分页、分类、关键词检索，返回有摘要的新闻列表 |
|  | `GET /api/dashboard/news/<id>` | 返回指定新闻的详情、长摘要、标签等 |
| 用户认证 (`user_bp.py`) | `POST /api/user/login` | 用户登录接口 |
|  | `GET /api/user/info` | 获取用户信息接口 |
|  | `POST /api/user/logout` | 用户登出接口 |
| 系统接口 (`app.py`) | `GET /healthz` | 健康检查接口 |
|  | `GET /` | 服务信息与可用接口列表 |
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
- 使用 Blueprint 架构，所有服务统一在一个 Flask 应用中，避免端口冲突。
- 可结合 `uvicorn` 或 `gunicorn` 部署到生产环境（主应用对象为 `app.py` 中的 `app`）。
- 重要改动前建议在本地构造少量测试数据，验证时间解析、分页和排序逻辑。
- 新增服务时，创建新的 Blueprint 并在 `app.py` 中注册即可。

## 后续规划（来自仓库现有 TODO）
- 多语言摘要能力与更强模型的重跑
- 相关新闻推荐与热点聚类分析
- 更丰富的动作建议生成与客户线索模块接入

如需更多接口细节或字段说明，请参考 `dashboard-api.md` 或代码中的内联注释。

## Blueprint 架构优势

### 统一部署
- **单端口运行**：所有 API 服务现在统一在端口 5000 运行，避免端口冲突
- **统一管理**：一个应用进程管理所有服务，简化部署和监控
- **共享配置**：数据库连接、环境变量等配置统一管理

### 模块化设计
- **代码组织**：每个功能模块独立为 Blueprint，保持代码清晰
- **易于扩展**：新增服务只需创建新的 Blueprint 并注册
- **独立开发**：各模块可以独立开发和测试

### 开发效率
- **简化启动**：只需运行 `python app.py` 即可启动所有服务
- **统一日志**：所有服务的日志统一输出，便于调试
- **热重载**：开发模式下支持代码热重载

### 生产部署
- **容器友好**：单一应用更容易容器化部署
- **负载均衡**：可以轻松进行水平扩展
- **监控简化**：只需监控一个应用进程
