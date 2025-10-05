# -*- coding: utf-8 -*-
"""
Flask 后端：新闻 API（基于视图 news_feed_view，且只返回有摘要的记录）
依赖:
    pip install flask supabase
环境变量（如未用环境变量，可直接按下方常量写死）:
    SUPABASE_URL=...
    SUPABASE_SERVICE_KEY=...
"""

import os
from datetime import datetime
from typing import Optional

from flask import Flask, request, jsonify
from supabase import create_client

# ====== 配置 ======
SUPABASE_URL = os.getenv("SUPABASE_URL", "https://zlajhzeylrzfbchycqyy.supabase.co")
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_KEY", "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InpsYWpoemV5bHJ6ZmJjaHljcXl5Iiwicm9sZSI6InNlcnZpY2Vfcm9sZSIsImlhdCI6MTc1NTYwMTIwMiwiZXhwIjoyMDcxMTc3MjAyfQ.u6vYYEL3qCh4lJU62wEmT4UJTZrstX-_yscRPXrZH7s")
VIEW_NAME = os.getenv("NEWS_FEED_VIEW", "news_feed_ready_view")  # 你创建的视图名

# ====== 初始化 ======
app = Flask(__name__)
sb = create_client(SUPABASE_URL, SUPABASE_KEY)

# ====== 工具函数 ======
def iso_utc(dt: Optional[datetime]) -> Optional[str]:
    if not dt:
        return None
    # 输出 ISO UTC（去微秒）
    return dt.replace(microsecond=0).isoformat() + "Z"

def parse_time_maybe(s: Optional[str]) -> (Optional[str], Optional[str]):
    """
    将数据库中的 publish_time（可能是 'YYYY-MM-DD' 或 ISO 字符串）拆成日期和时分。
    兼容：无 Z、微秒位数不标准等。
    """
    if not s:
        return None, None
    try:
        t = s.strip()
        # 替换 Z
        if t.endswith("Z"):
            t = t.replace("Z", "+00:00")
        # 处理微秒长度不标准
        if "." in t:
            # 仅对形如 2025-09-28T22:51:13.42462 这种无时区的做补齐
            date_part, frac_part = t.split(".", 1)
            # frac 里可能还带时区，拆一下
            tz_pos = max(frac_part.find("+"), frac_part.find("-"))
            if tz_pos > 0:
                micro = frac_part[:tz_pos]
                tz = frac_part[tz_pos:]
            else:
                micro, tz = frac_part, ""
            micro = (micro + "000000")[:6]
            t = f"{date_part}.{micro}{tz}"
        # 如果仅日期
        if len(t) == 10 and t[4] == "-" and t[7] == "-":
            dt = datetime.fromisoformat(t)
        else:
            dt = datetime.fromisoformat(t)
        return dt.strftime("%Y-%m-%d"), dt.strftime("%H:%M")
    except Exception:
        # 容错：只要能提取到日期就行
        try:
            if len(s) >= 10:
                return s[:10], None
        except Exception:
            pass
        return None, None

def estimate_read_time(text: str) -> str:
    """根据正文字数估算阅读时间（200字≈1分钟）"""
    if not text:
        return "1分钟"
    minutes = max(1, len(text) // 200)
    return f"{minutes}分钟"

def map_category(news_type: Optional[str]) -> str:
    """
    将后端枚举（如 policy/industry/competitor/tech）映射到前端 category。
    也可直接返回 news_type（英文），根据需要自行调整。
    """
    mapping = {
        "policy": "policy",
        "industry": "industry",
        "competitor": "competitor",
        "tech": "tech",
    }
    if not news_type:
        return "all"
    return mapping.get(news_type, news_type)

# ====== 列表接口 ======
@app.route("/api/dashboard/news", methods=["GET"])
def get_news_list():
    page = int(request.args.get("page", 1))
    page_size = int(request.args.get("pageSize", 20))
    category = request.args.get("category", "all")  # all/policy/industry/competitor/tech
    keyword = request.args.get("keyword", "").strip()
    date = request.args.get("date")

    start = (page - 1) * page_size
    end = start + page_size - 1

    # 基础查询 + 计数（exact）
    query = sb.table(VIEW_NAME).select("*", count="exact")

    # ✅ 只返回「有摘要」的记录（服务端过滤，total 与数据一致）
    # 兼容不同 supabase-py 版本，统一用 filter("not.is","null")
    query = query.filter("short_summary", "not.is", "null").neq("short_summary", "")

    # 分类筛选（按英文枚举）
    if category != "all":
        query = query.eq("news_type", category)

    # 关键词（对标题模糊）
    if keyword:
        query = query.ilike("title", f"%{keyword}%")

    # 日期筛选（按 publish_time 的日期部分）
    if date:
        # 视图里 publish_time 是 timestamptz/文本？这里统一用 ilike 兼容
        query = query.ilike("publish_time::text", f"{date}%")

    # 排序（先按 publish_time 降序，再按 id 降序，保证稳定）
    query = query.order("publish_time", desc=True).order("id", desc=True)

    # 分页
    res = query.range(start, end).execute()

    rows = res.data or []
    total = res.count or 0

    news_list = []
    for r in rows:
        # 视图里对应字段：
        # id, title, publish_time, source_url, source_type, news_type,
        # clean_text, short_summary, long_summary, created_at, updated_at
        date_str, time_str = parse_time_maybe(r.get("publish_time"))
        created_at_iso = iso_utc(datetime.fromisoformat(r["created_at"].replace("Z", "+00:00"))) if r.get("created_at") else None

        news_list.append({
            "id": r["id"],
            "category": map_category(r.get("news_type")),  # 返回英文枚举
            "title": r.get("title"),
            "source": r.get("source_type"),
            "time": time_str,
            "publishTime": date_str,
            "readTime": estimate_read_time(r.get("clean_text") or ""),
            "link": r.get("source_url"),
            "summary": r.get("short_summary"),
            "actionSuggestion": None,
            "relatedNews": [],
            "createdAt": created_at_iso,
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

# ====== 详情接口 ======
@app.route("/api/dashboard/news/<string:news_id>", methods=["GET"])
def get_news_detail(news_id: str):
    # 只查有摘要的记录
    res = (
        sb.table(VIEW_NAME)
        .select("*")
        .eq("id", news_id)
        .filter("long_summary", "not.is", "null")
        .neq("long_summary", "")
        .single()
        .execute()
    )
    r = res.data
    if not r:
        return jsonify({"code": 404, "message": "not found", "data": {}})

    date_str, time_str = parse_time_maybe(r.get("publish_time"))

    # created/updated 容错
    def to_iso_safe(v: Optional[str]) -> Optional[str]:
        if not v:
            return None
        try:
            return iso_utc(datetime.fromisoformat(v.replace("Z", "+00:00")))
        except Exception:
            return v

    detail = {
        "id": r["id"],
        "category": map_category(r.get("news_type")),
        "title": r.get("title"),
        "source": r.get("source_type"),
        "time": time_str,
        "publishTime": date_str,
        "readTime": estimate_read_time(r.get("clean_text") or ""),
        "link": r.get("source_url"),
        "content": r.get("clean_text"),
        "summary": r.get("long_summary"),
        "actionSuggestion": None,
        "relatedNews": [],
        "tags": [],  # 可从 summary_json.entities 推出（若视图中有暴露）
        "createdAt": to_iso_safe(r.get("created_at")),
        "updatedAt": to_iso_safe(r.get("updated_at")),
    }

    return jsonify({"code": 200, "message": "success", "data": detail})


# ====== 健康检查 ======
@app.route("/healthz", methods=["GET"])
def healthz():
    return jsonify({"ok": True})


if __name__ == "__main__":
    # 本地调试
    app.run(host="0.0.0.0", port=8000, debug=True)