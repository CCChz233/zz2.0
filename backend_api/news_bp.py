# -*- coding: utf-8 -*-
"""
Flask 后端：新闻 API Blueprint（基于事实表 fact_events）
依赖:
    pip install flask supabase
环境变量（如未用环境变量，可直接按下方常量写死）:
    SUPABASE_URL=...
    SUPABASE_SERVICE_KEY=...
"""

import os
import json
from datetime import datetime
from typing import Optional

from flask import Blueprint, request, jsonify, make_response
from postgrest.exceptions import APIError

from infra.db import supabase

# ====== 配置 ======
# 优先使用 NEWS_FEED_TABLE，兼容旧的 NEWS_FEED_VIEW
NEWS_FEED_TABLE = (
    os.getenv("NEWS_FEED_TABLE")
    or os.getenv("NEWS_FEED_VIEW")
    or "fact_events"
)

# ====== 初始化 ======
news_bp = Blueprint('news', __name__)
sb = supabase

# ====== 工具函数 ======
def iso_utc(dt: Optional[datetime]) -> Optional[str]:
    if not dt:
        return None
    # 输出 ISO UTC（去微秒）
    return dt.replace(microsecond=0).isoformat() + "Z"

def parse_time_maybe(s: Optional[str]) -> (Optional[str], Optional[str]):
    """
    将数据库中的 published_at（可能是 'YYYY-MM-DD' 或 ISO 字符串）拆成日期和时分。
    兼容：无 Z、微秒位数不标准等。
    """
    if not s:
        return None, None
    try:
        t = str(s).strip()
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

NEWS_TYPE_ALIASES = {
    "policy": "政策新闻",
    "industry": "行业新闻",
    "competitor": "竞品新闻",
    "opportunity": "商机",
    "新闻消息": "政策新闻",
    "行业动态": "行业新闻",
    "竞品消息": "竞品新闻",
    "竞品动态": "竞品新闻",
    "技术前沿": "行业新闻",
    "政策": "政策新闻",
    "行业": "行业新闻",
    "竞品": "竞品新闻",
    "机会": "商机",
}

TYPE_TO_NEWS_TYPE = {
    "policy": "政策新闻",
    "industry": "行业新闻",
    "competitor": "竞品新闻",
    "opportunity": "商机",
}

CATEGORY_FILTERS = {
    "政策新闻": {
        "news_type": ["政策新闻", "政策", "policy", "新闻消息", "政策动态"],
        "type": ["policy"],
    },
    "行业新闻": {
        "news_type": ["行业新闻", "行业", "industry", "行业动态", "技术前沿"],
        "type": ["industry"],
    },
    "竞品新闻": {
        "news_type": ["竞品新闻", "竞品动态", "竞品消息", "competitor"],
        "type": ["competitor"],
    },
    "商机": {
        "news_type": ["商机", "机会", "opportunity", "招标机会"],
        "type": ["opportunity", "tender", "tenders"],
    },
}

def normalize_news_type(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    return NEWS_TYPE_ALIASES.get(value, value)

def normalize_category_param(value: Optional[str]) -> Optional[str]:
    if not value or value == "all":
        return None
    return normalize_news_type(value)

def map_category(news_type: Optional[str], fallback_type: Optional[str] = None) -> str:
    if news_type:
        return normalize_news_type(news_type) or news_type
    mapped = TYPE_TO_NEWS_TYPE.get(fallback_type or "")
    return mapped or "all"

def normalize_payload(payload: Optional[object]) -> dict:
    if not payload:
        return {}
    if isinstance(payload, dict):
        return payload
    try:
        return json.loads(payload)
    except Exception:
        return {}

def _build_or_clause(field: str, values: list) -> list:
    return [f"{field}.eq.{value}" for value in values if value]

def apply_category_filter(query, category_value: str):
    filters = CATEGORY_FILTERS.get(category_value)
    if not filters:
        return query.eq("news_type", category_value)
    clauses = []
    clauses.extend(_build_or_clause("news_type", filters.get("news_type", [])))
    clauses.extend(_build_or_clause("type", filters.get("type", [])))
    if not clauses:
        return query.eq("news_type", category_value)
    return query.or_(",".join(clauses))

# ====== 列表接口 ======
@news_bp.route("/news", methods=["GET"])
def get_news_list():
    if not sb:
        return jsonify({"code": 500, "message": "Supabase 未配置", "data": None}), 500
    page = int(request.args.get("page", 1))
    page_size = int(request.args.get("pageSize", 20))
    category = request.args.get("category", "all")  # all/政策新闻/行业新闻/竞品新闻/商机
    category = "".join(category.split())
    keyword = request.args.get("keyword", "").strip()
    date = request.args.get("date")

    # 视角/筛选增强（可选）
    view = request.args.get("view", "global")
    only_ai = request.args.get("onlyAI", "false").lower() == "true"
    start_date = request.args.get("startDate")
    end_date = request.args.get("endDate")

    # 建议长度偏好（full/short）
    suggest_pref = (request.args.get("suggest", "full") or "full").lower()

    start = (page - 1) * page_size
    end = start + page_size - 1

    # 基础查询 + 计数（exact）
    query = sb.table(NEWS_FEED_TABLE).select("*", count="exact")

    # ✅ 只返回「有摘要」的记录（服务端过滤，total 与数据一致）
    # 统一用 summary 字段兜底
    query = query.filter("summary", "not.is", "null").neq("summary", "")

    # 分类筛选（按 news_type）
    normalized_category = normalize_category_param(category)
    if normalized_category:
        query = apply_category_filter(query, normalized_category)

    # 关键词（对标题模糊）
    if keyword:
        query = query.ilike("title", f"%{keyword}%")

    # 日期筛选（按 published_at 的日期部分）
    if date:
        query = query.gte("published_at", f"{date}T00:00:00")
        query = query.lte("published_at", f"{date}T23:59:59.999999")

    # 日期范围（闭区间）
    if start_date:
        query = query.gte("published_at", f"{start_date}T00:00:00")
    if end_date:
        query = query.lte("published_at", f"{end_date}T23:59:59.999999")

    # 视角快捷逻辑
    if view == "management":
        # 高管视角：优先有 AI 建议
        query = query.filter("payload->>ai_suggestion", "not.is", "null").neq("payload->>ai_suggestion", "")
    elif view == "analysis":
        # 分析视角：有长摘要
        query = query.filter("payload->>long_summary", "not.is", "null").neq("payload->>long_summary", "")

    # 显式只看有AI
    if only_ai:
        query = query.filter("payload->>ai_suggestion", "not.is", "null").neq("payload->>ai_suggestion", "")

    # 排序（先按 published_at 降序，再按 id 降序，保证稳定）
    query = query.order("published_at", desc=True).order("id", desc=True)

    # 分页
    res = query.range(start, end).execute()

    rows = res.data or []
    total = res.count or 0

    news_list = []
    for r in rows:
        payload = normalize_payload(r.get("payload"))
        date_str, time_str = parse_time_maybe(r.get("published_at"))

        summary_short = (
            payload.get("short_summary")
            or payload.get("summary_preview")
            or payload.get("summary")
            or r.get("summary")
        )
        summary_long = (
            payload.get("long_summary")
            or payload.get("summary")
            or r.get("summary")
        )

        ai_full = payload.get("ai_suggestion_full")
        ai_short = payload.get("ai_suggestion")
        if suggest_pref == "full":
            ai_selected = ai_full or ai_short
        else:
            ai_selected = ai_short or ai_full

        created_col = r.get("created_at")
        created_at_iso = None
        if created_col:
            try:
                created_at_iso = iso_utc(datetime.fromisoformat(str(created_col).replace("Z", "+00:00")))
            except Exception:
                created_at_iso = str(created_col)

        news_list.append({
            "id": r["id"],
            "category": map_category(r.get("news_type"), r.get("type")),
            "title": r.get("title"),
            "source": r.get("source") or r.get("url"),
            "time": time_str,
            "publishTime": date_str,
            "readTime": estimate_read_time(
                payload.get("clean_text")
                or summary_long
                or summary_short
                or ""
            ),
            "link": r.get("url"),
            "summary": summary_short or summary_long,

            # === AI 建议：按照参数选择返回，同时把两种都透出，前端可自行选择 ===
            "actionSuggestion": ai_selected,
            "actionSuggestionFull": ai_full,
            "actionSuggestionShort": ai_short,
            "hasAI": bool((ai_full and ai_full.strip()) or (ai_short and ai_short.strip())),

            "relatedNews": [],
            "tags": r.get("keywords") or payload.get("keywords") or [],
            "createdAt": created_at_iso,
        })

    response_data = {
        "code": 200,
        "message": "success",
        "data": {
            "total": total,
            "page": page,
            "pageSize": page_size,
            "news": news_list
        }
    }
    
    # 使用自定义JSON编码器确保中文字符正确显示
    response = make_response(
        json.dumps(response_data, ensure_ascii=False, indent=2)
    )
    response.status_code = 200
    response.mimetype = 'application/json; charset=utf-8'
    return response

# ====== 详情接口 ======
@news_bp.route("/news/<string:news_id>", methods=["GET"])
def get_news_detail(news_id: str):
    if not sb:
        return jsonify({"code": 500, "message": "Supabase 未配置", "data": None}), 500
    # 只查有摘要的记录
    try:
        res = (
            sb.table(NEWS_FEED_TABLE)
            .select("*")
            .eq("id", news_id)
            .maybe_single()
            .execute()
        )
    except APIError as e:
        # 统一兜底：将 Supabase 返回的 0 行错误转换成 404
        details = (getattr(e, "details", "") or "").lower()
        message = (getattr(e, "message", "") or "").lower()
        if "0 rows" in details or "0 rows" in message:
            res = None
        else:
            raise

    if not res or not getattr(res, "data", None):
        error_data = {"code": 404, "message": "not found", "data": {}}
        response = make_response(
            json.dumps(error_data, ensure_ascii=False, indent=2)
        )
        response.status_code = 404
        response.mimetype = 'application/json; charset=utf-8'
        return response

    r = res.data
    payload = normalize_payload(r.get("payload"))

    date_str, time_str = parse_time_maybe(r.get("published_at"))

    # 建议长度偏好（full/short）
    suggest_pref = (request.args.get("suggest", "full") or "full").lower()

    ai_full = payload.get("ai_suggestion_full")
    ai_short = payload.get("ai_suggestion")
    if suggest_pref == "full":
        ai_selected = ai_full or ai_short
    else:
        ai_selected = ai_short or ai_full

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
        "category": map_category(r.get("news_type"), r.get("type")),
        "title": r.get("title"),
        "source": r.get("source") or r.get("url"),
        "time": time_str,
        "publishTime": date_str,
        "readTime": estimate_read_time(
            payload.get("clean_text")
            or payload.get("long_summary")
            or payload.get("summary")
            or r.get("summary")
            or ""
        ),
        "link": r.get("url"),
        "content": (
            payload.get("clean_text")
            or payload.get("long_summary")
            or payload.get("summary")
            or r.get("summary")
        ),
        "summary": (
            payload.get("long_summary")
            or payload.get("summary")
            or r.get("summary")
        ),

        # === AI 建议：按照参数选择返回，同时把两种都透出，前端可自行选择 ===
        "actionSuggestion": ai_selected,
        "actionSuggestionFull": ai_full,
        "actionSuggestionShort": ai_short,

        "relatedNews": [],

        "tags": r.get("keywords") or payload.get("keywords") or [],
        "createdAt": to_iso_safe(r.get("created_at")),
        "updatedAt": None,
    }

    response_data = {"code": 200, "message": "success", "data": detail}
    
    # 使用自定义JSON编码器确保中文字符正确显示
    response = make_response(
        json.dumps(response_data, ensure_ascii=False, indent=2)
    )
    response.status_code = 200
    response.mimetype = 'application/json; charset=utf-8'
    return response


# 移除独立运行代码，现在作为Blueprint使用
