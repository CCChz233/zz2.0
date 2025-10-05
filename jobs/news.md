
# 📰 News Dashboard Backend

本项目是一个基于 **Flask + Supabase** 的新闻管理与展示系统，包含 **新闻抓取、清洗、摘要生成、数据存储、前端接口** 全流程。

---

## 🔧 架构说明

[爬虫抓取器]  →  news（原始新闻表）
│
▼
[离线清洗 + LLM 摘要生成脚本]
│ upsert
▼
news_summaries（AI 摘要表）
│ LEFT JOIN
▼
view_news（供前端统一调用）
│
▼
Flask API (/api/dashboard/news)

---

## 📂 数据库结构

### 1. 原始表 `news`
存储原始新闻内容。主要字段：
- `id (UUID)`：主键
- `title (TEXT)`：标题
- `content (TEXT)`：正文
- `source_url (TEXT)`：新闻链接
- `news_type (TEXT)`：新闻类型（policy/industry/competitor/tech）
- `source (TEXT)`：来源（如 tavily、自研爬虫）
- `publish_time (TIMESTAMPTZ)`：发布时间
- `created_at (TIMESTAMPTZ)`：入库时间

---

### 2. 摘要表 `news_summaries`
存储清洗结果和 AI 摘要。主要字段：
- `news_id (UUID)`：外键，关联 `news.id`
- `clean_text (TEXT)`：清洗后的正文
- `short_summary (TEXT)`：简短摘要（列表用）
- `long_summary (TEXT)`：长摘要（详情用）
- `summary_json (JSONB)`：结构化摘要
- `model (TEXT)`：生成摘要的模型
- `created_at / updated_at (TIMESTAMPTZ)`

---

### 3. 视图 `view_news`
拼接两张表，供前端直接调用：
```sql
create or replace view public.view_news as
select
  n.id,
  n.title,
  n.source_url,
  n.news_type,
  n.source,
  n.publish_time,
  n.created_at,
  s.short_summary,
  s.long_summary,
  s.clean_text,
  s.summary_json
from public.news n
left join public.news_summaries s
  on s.news_id = n.id
order by coalesce(n.publish_time, n.created_at) desc, n.id desc;


⸻

🚀 接口说明

1. 获取要闻列表

URL: GET /api/dashboard/news

请求参数

{
  "page": 1,
  "pageSize": 20,
  "category": "all",        // 可选: all/policy/industry/competitor/tech
  "keyword": "",            // 搜索关键词
  "date": "2023-11-15"      // 可选，默认为今天
}

返回示例

{
  "code": 200,
  "message": "success",
  "data": {
    "total": 25,
    "page": 1,
    "pageSize": 20,
    "news": [
      {
        "id": "d779960f-bfc7-4ab4-9c64-5d8b5795f897",
        "category": "industry",
        "title": "航天科技一院102所助力中国高端科学仪器产业生态构建侧记",
        "source": "tavily",
        "time": "14:07",
        "publishTime": "2025-09-29",
        "readTime": "12分钟",
        "link": "https://www.spacechina.com/...",
        "summary": "航天科技一院102所推动高端仪器技术突破与生态构建，助力国产仪器发展。",
        "actionSuggestion": null,
        "relatedNews": [],
        "createdAt": "2025-09-29T06:07:37Z"
      }
    ]
  }
}


⸻

2. 获取要闻详情

URL: GET /api/dashboard/news/{id}

返回示例

{
  "code": 200,
  "message": "success",
  "data": {
    "id": "d779960f-bfc7-4ab4-9c64-5d8b5795f897",
    "category": "industry",
    "title": "航天科技一院102所助力中国高端科学仪器产业生态构建侧记",
    "source": "tavily",
    "time": "14:07",
    "publishTime": "2025-09-29",
    "readTime": "12分钟",
    "link": "https://www.spacechina.com/...",
    "content": "清洗后的正文...",
    "summary": "长摘要内容...",
    "actionSuggestion": null,
    "relatedNews": [],
    "tags": ["AI", "政策", "大模型"],
    "createdAt": "2025-09-29T06:07:37Z",
    "updatedAt": "2025-09-29T06:07:37Z"
  }
}


⸻

⚙️ 部署方式
	1.	克隆仓库

git clone https://github.com/yourname/news-dashboard.git
cd news-dashboard

	2.	安装依赖

pip install -r requirements.txt

	3.	配置环境变量 .env

SUPABASE_URL=your_supabase_url
SUPABASE_KEY=your_service_role_key

	4.	启动服务

python app.py

运行后默认监听：
	•	http://127.0.0.1:8000
	•	http://0.0.0.0:8000

⸻

🛠️ TODO
	•	支持多语言摘要
	•	摘要模型替换（更强模型重跑）
	•	相关新闻推荐（基于实体/关键词）
	•	热点聚类 & 趋势分析
