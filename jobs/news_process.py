# -*- coding: utf-8 -*-
"""
Flask 后端：今日全球要闻 API（基于 policy_feed_view_latest 视图）
依赖:
    pip install flask supabase python-dotenv

环境变量(推荐):
    SUPABASE_URL=...
    SUPABASE_SERVICE_KEY=...

也可直接在下方常量里硬编码（不推荐）。
"""

import os
from urllib.parse import urlparse
from datetime import datetime, timezone
from typing import Any, Dict, List, Tuple, Optional

from flask import Flask, request, jsonify
from supabase import create_client, Client
from dotenv import load_dotenv

# ====================== 配置 ======================
load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL") or "https://YOUR-PROJECT.supabase.co"
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_KEY") or "YOUR-SERVICE-KEY"

# 供前端调用的视图（建议为“只含已摘要数据”的视图）
# 如果你使用的是“全量视图”，保留代码里对 short_summary 的过滤即可。
VIEW_NAME = "policy_feed_view_latest"

# 类别映射：后端统一用英文枚举，前端可自行映射中文展示
# 你的原始 news_type 建议也是这几个英文之一
VALID_CATEGORIES = {"all", "policy", "industry", "competitor", "tech"}

app = Flask(__name__)

# Supabase 客户端
sb: Client = create_client(SUPABASE_URL, SUPABASE_KEY)


# ====================== 工具函数 ======================
def parse_iso_datetime(s: Optional[str]) -> Optional[datetime]:
    """兼容多种 ISO 输入，返回 aware datetime（UTC 假设）"""
    if not s:
        return None
    try:
        # 处理 'Z' 结尾
        if s.endswith("Z"):
            s = s.replace("Z", "+00:00")
        # 处理微秒位数不为6的情况
        if "." in s:
            date_part, frac = s.split(".", 1)
            # frac 里可能还有时区，例如 .123+00:00
            tz_part = ""
            if "+" in frac:
                frac, tz_part = frac.split("+", 1)
                tz_part = "+" + tz_part
            elif "-" in frac[1:]:
                # 负号作为时区，例如 .123-08:00
                idx = frac[1:].find("-") + 1
                frac, tz_part = frac[:idx], frac[idx:]
            # 标准化为6位微秒
            frac = (frac + "000000")[:6]
            s = f"{date_part}.{frac}{tz_part}"
        dt = datetime.fromisoformat(s)
        # 若为 naive，则视为 UTC
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None


def to_date_time_strings(publish_time: Optional[str]) -> Tuple[Optional[str], Optional[str]]:
    """返回 (YYYY-MM-DD, HH:MM)"""
    dt = parse_iso_datetime(publish_time)
    if not dt:
        return None, None
    return dt.strftime("%Y-%m-%d"), dt.strftime("%H:%M")


def to_created_at_z(s: Optional[str]) -> Optional[str]:
    """将任意 ISO 输入转成标准 Z 结尾字符串"""
    dt = parse_iso_datetime(s)
    if not dt:
        return None
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def estimate_read_time(text: Optional[str]) -> str:
    """按汉字数估算阅读时长；200字≈1分钟，至少1分钟"""
    n = len(text or "")
    minutes = max(1, n // 200)
    return f"{minutes}分钟"


def source_human_readable(source_type: Optional[str], link: Optional[str]) -> Optional[str]:
    """优先返回 source_type；否则用 link 的域名"""
    if source_type:
        return source_type
    if link:
        try:
            netloc = urlparse(link).netloc
            return netloc or None
        except Exception:
            return None
    return None


def non_null_action_suggestion(val: Optional[str]) -> str:
    """actionSuggestion 保底为非 null"""
    return val or ""


def build_tags_from_summary_json(summary_json: Optional[Dict[str, Any]]) -> List[str]:
    """从 summary_json.entities 聚合 tags（去重、最少返回 []）"""
    if not isinstance(summary_json, dict):
        return []
    entities = summary_json.get("entities") or {}
    if not isinstance(entities, dict):
        return []
    tags: List[str] = []
    for k in ("org", "person", "location", "date"):
        v = entities.get(k)
        if isinstance(v, list):
            tags.extend([str(x) for x in v if x])
    # 去重且保序
    seen = set()
    uniq = []
    for t in tags:
        if t not in seen:
            seen.add(t)
            uniq.append(t)
    return uniq[:12]  # 控制数量


# ====================== 查询构造 ======================
def base_query():
    """基础查询：按 publish_time desc, id desc"""
    return (
        sb.table(VIEW_NAME)
        .select("*")
        .order("publish_time", desc=True)
        .order("id", desc=True)
    )


def apply_filters(q, category: str, keyword: str, date_str: Optional[str]):
    """
    结合视图字段：
      - id
      - title
      - publish_time
      - source_url
      - source_type
      - short_summary
      - long_summary
      - clean_text
      - summary_json
      - news_type
      - created_at / updated_at (若视图里带出)
    """
    # 过滤：只返回有摘要（如果你的视图已经只含有摘要，可注释下一行）
    q = q.not_.is_("short_summary", "null")

    if category and category != "all":
        q = q.eq("news_type", category)

    if keyword:
        # 标题 & 摘要模糊
        q = q.or_(
            f"title.ilike.%{keyword}%,short_summary.ilike.%{keyword}%"
        )

    if date_str:
        # 同一天（按日期字符串匹配）
        q = q.gte("publish_time", f"{date_str}T00:00:00") \
             .lte("publish_time", f"{date_str}T23:59:59.999999")

    return q


def count_total(category: str, keyword: str, date_str: Optional[str]) -> int:
    """获取过滤后的总条数（只统计有摘要的）"""
    q = sb.table(VIEW_NAME).select("id", count="exact")
    q = q.not_.is_("short_summary", "null")
    if category and category != "all":
        q = q.eq("news_type", category)
    if keyword:
        q = q.or_(f"title.ilike.%{keyword}%,short_summary.ilike.%{keyword}%")
    if date_str:
        q = q.gte("publish_time", f"{date_str}T00:00:00") \
             .lte("publish_time", f"{date_str}T23:59:59.999999")
    res = q.execute()
    # supabase-py 返回 count 属性
    return int(getattr(res, "count", 0) or 0)


# ====================== 路由 ======================
@app.route("/api/dashboard/news", methods=["GET"])
def get_news_list():
    # ---- 查询参数 ----
    page = max(1, int(request.args.get("page", 1)))
    page_size = min(100, max(1, int(request.args.get("pageSize", 20))))
    category = request.args.get("category", "all").lower().strip()
    keyword = (request.args.get("keyword") or "").strip()
    date_str = (request.args.get("date") or "").strip() or None

    if category not in VALID_CATEGORIES:
        category = "all"

    # ---- 统计总数（只含有摘要的记录）----
    total = count_total(category, keyword, date_str)

    # ---- 分页范围 ----
    start = (page - 1) * page_size
    end = start + page_size - 1

    # ---- 查询列表数据 ----
    q = base_query()
    q = apply_filters(q, category, keyword, date_str)
    res = q.range(start, end).execute()
    rows = res.data or []

    # ---- 组装返回 ----
    news_list: List[Dict[str, Any]] = []
    for r in rows:
        date_only, hhmm = to_date_time_strings(r.get("publish_time"))
        created_at_z = to_created_at_z(r.get("created_at") or r.get("updated_at"))

        news_list.append({
            "id": r.get("id"),
            "category": (r.get("news_type") or "all").lower(),
            "title": r.get("title"),
            "source": source_human_readable(r.get("source_type"), r.get("source_url")),
            "time": hhmm,
            "publishTime": date_only,
            "readTime": estimate_read_time(r.get("clean_text") or r.get("long_summary") or r.get("short_summary")),
            "link": r.get("source_url"),
            "summary": r.get("short_summary") or "",
            "actionSuggestion": non_null_action_suggestion(None),  # 先给空；可后续接 LLM 生成
            "relatedNews": [],                                     # 预留：相似文章召回
            "createdAt": created_at_z,
        })

    return jsonify({
        "code": 200,
        "message": "success",
        "data": {
            "total": total,
            "page": page,
            "pageSize": page_size,
            "news": news_list
        }
    })


@app.route("/api/dashboard/news/<string:news_id>", methods=["GET"])
def get_news_detail(news_id: str):
    # 详情只查一条
    res = (
        sb.table(VIEW_NAME)
        .select("*")
        .eq("id", news_id)
        .not_.is_("short_summary", "null")  # 仅允许已摘要
        .single()
        .execute()
    )
    r = res.data
    if not r:
        return jsonify({"code": 404, "message": "not found", "data": {}})

    date_only, hhmm = to_date_time_strings(r.get("publish_time"))
    created_at_z = to_created_at_z(r.get("created_at"))
    updated_at_z = to_created_at_z(r.get("updated_at"))
    tags = build_tags_from_summary_json(r.get("summary_json"))

    detail = {
        "id": r.get("id"),
        "category": (r.get("news_type") or "all").lower(),
        "title": r.get("title"),
        "source": source_human_readable(r.get("source_type"), r.get("source_url")),
        "time": hhmm,
        "publishTime": date_only,
        "readTime": estimate_read_time(r.get("clean_text") or r.get("long_summary") or r.get("short_summary")),
        "link": r.get("source_url"),
        "content": r.get("clean_text") or "",           # 详情展示清洗后的正文
        "summary": r.get("long_summary") or r.get("short_summary") or "",
        "actionSuggestion": non_null_action_suggestion(None),
        "relatedNews": [],
        "tags": tags,
        "createdAt": created_at_z,
        "updatedAt": updated_at_z,
    }

    return jsonify({"code": 200, "message": "success", "data": detail})


# ====================== 入口 ======================
if __name__ == "__main__":
    # 本地调试：http://127.0.0.1:8000/api/dashboard/news
    app.run(host="0.0.0.0", port=8000, debug=True)