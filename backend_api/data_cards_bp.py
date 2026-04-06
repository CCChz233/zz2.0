# -*- coding: utf-8 -*-
"""
KPI 概览接口 Blueprint（自动取数据库中最新数据日期）
-----------------------------------------------------
用法：
  export SUPABASE_URL="https://xxxxx.supabase.co"
  export SUPABASE_SERVICE_KEY="your_service_key"

访问：
  /api/dashboard/data-cards
  /api/dashboard/data-cards/trend
"""

import os
import json
import re
import unicodedata
from datetime import datetime, timedelta, date as date_cls
from typing import Dict, Tuple, List, Optional

from flask import Blueprint, request, make_response

from infra.db import supabase

# ===================== 初始化 =====================
data_cards_bp = Blueprint('data_cards', __name__)

sb = supabase

FACT_EVENTS_TABLE = (
    os.getenv("NEWS_FEED_TABLE")
    or os.getenv("NEWS_FEED_VIEW")
    or "fact_events"
)

OPPORTUNITY_FACT_FILTERS = {
    "news_type": ["商机", "机会", "opportunity", "招标机会"],
    "type": ["opportunity", "tender", "tenders"],
}

FETCH_BATCH_SIZE = 1000

# ===================== 工具函数 =====================
def _period_window(anchor: date_cls, period: str) -> Tuple[datetime, datetime]:
    """计算当前周期的起止时间（固定为最近7天）"""
    # 固定使用7天窗口
    end = datetime.combine(anchor, datetime.max.time())
    start = datetime.combine(anchor - timedelta(days=6), datetime.min.time())
    return start, end

def _previous_window(start: datetime, end: datetime) -> Tuple[datetime, datetime]:
    delta = end - start + timedelta(seconds=1)
    prev_end = start - timedelta(seconds=1)
    prev_start = prev_end - delta + timedelta(seconds=1)
    return prev_start, prev_end


def _json_err(code: int, message: str, http_status: int = 400):
    payload = {"code": code, "message": message, "data": {}}
    response = make_response(json.dumps(payload, ensure_ascii=False, indent=2))
    response.status_code = http_status
    response.mimetype = 'application/json; charset=utf-8'
    return response


def _build_or_clause(field: str, values: List[str]) -> List[str]:
    return [f"{field}.eq.{value}" for value in values if value]


def _apply_opportunity_fact_filter(query):
    clauses: List[str] = []
    clauses.extend(_build_or_clause("news_type", OPPORTUNITY_FACT_FILTERS["news_type"]))
    clauses.extend(_build_or_clause("type", OPPORTUNITY_FACT_FILTERS["type"]))
    if clauses:
        query = query.or_(",".join(clauses))
    return query


def _fetch_rows_between(
    table: str,
    columns: str,
    field: str,
    start_value: str,
    end_value: str,
    order_field: Optional[str] = None,
    batch_size: int = FETCH_BATCH_SIZE,
) -> List[Dict]:
    rows: List[Dict] = []
    offset = 0

    while True:
        query = (
            sb.table(table)
            .select(columns)
            .gte(field, start_value)
            .lte(field, end_value)
        )
        if order_field:
            query = query.order(order_field, desc=False)

        res = query.range(offset, offset + batch_size - 1).execute()
        batch = res.data or []
        if not batch:
            break

        rows.extend(batch)
        if len(batch) < batch_size:
            break
        offset += batch_size

    return rows


def _has_keywords_matched(row: Dict) -> bool:
    keywords_matched = row.get("keywords_matched")
    if not isinstance(keywords_matched, list):
        return False
    return any(isinstance(kw, str) and kw.strip() for kw in keywords_matched)


def _normalize_title(title: Optional[str]) -> str:
    if not title:
        return ""
    normalized = unicodedata.normalize("NFKC", str(title)).strip().lower()
    return re.sub(r"\s+", " ", normalized)

# ===================== 数据统计函数 =====================
def _count_competitors_news_between(start: datetime, end: datetime) -> int:
    """统计 00_competitors_news 表在指定时间范围内的新增数量（优先使用 publish_time）"""
    try:
        # 优先使用 publish_time，如果没有则使用 created_at
        res = (
            sb.table("00_competitors_news")
            .select("id", count="exact")
            .gte("publish_time", start.isoformat())
            .lte("publish_time", end.isoformat())
            .execute()
        )
        return res.count or 0
    except Exception:
        # 回退到使用 created_at
        try:
            res = (
                sb.table("00_competitors_news")
                .select("id", count="exact")
                .gte("created_at", start.isoformat())
                .lte("created_at", end.isoformat())
                .execute()
            )
            return res.count or 0
        except Exception:
            return 0

def _count_opportunity_between_raw(start: datetime, end: datetime) -> int:
    """按原始表统计 00_opportunity 表在指定时间范围内的新增数量"""
    try:
        res = (
            sb.table("00_opportunity")
            .select("id", count="exact")
            .gte("publish_time", start.isoformat())
            .lte("publish_time", end.isoformat())
            .execute()
        )
        return res.count or 0
    except Exception:
        # 回退到使用 created_at
        try:
            res = (
                sb.table("00_opportunity")
                .select("id", count="exact")
                .gte("created_at", start.isoformat())
                .lte("created_at", end.isoformat())
                .execute()
            )
            return res.count or 0
        except Exception:
            return 0


def _count_opportunity_between(start: datetime, end: datetime) -> int:
    """按事实表统计商机数量，与新闻列表“商机”页签保持一致"""
    try:
        query = (
            sb.table(FACT_EVENTS_TABLE)
            .select("id", count="exact")
            .filter("summary", "not.is", "null")
            .neq("summary", "")
            .gte("published_at", start.isoformat())
            .lte("published_at", end.isoformat())
        )
        query = _apply_opportunity_fact_filter(query)
        res = query.execute()
        return res.count or 0
    except Exception:
        return _count_opportunity_between_raw(start, end)


def _count_papers_between(start: datetime, end: datetime) -> int:
    """统计相关论文数量：仅保留带关键词的记录，并按标题去重"""
    unique_titles = set()

    def collect(rows: List[Dict]) -> int:
        for row in rows:
            if not _has_keywords_matched(row):
                continue
            title_key = _normalize_title(row.get("title")) or f"id:{row.get('id')}"
            unique_titles.add(title_key)
        return len(unique_titles)

    try:
        rows = _fetch_rows_between(
            table="00_papers",
            columns="id,title,keywords_matched,published_at",
            field="published_at",
            start_value=start.date().isoformat(),
            end_value=end.date().isoformat(),
            order_field="published_at",
        )
        return collect(rows)
    except Exception:
        try:
            rows = _fetch_rows_between(
                table="00_papers",
                columns="id,title,keywords_matched,created_at",
                field="created_at",
                start_value=start.isoformat(),
                end_value=end.isoformat(),
                order_field="created_at",
            )
            return collect(rows)
        except Exception:
            return 0

def _count_news_between(start: datetime, end: datetime) -> int:
    """统计 00_news 表在指定时间范围内的新增数量（优先使用 publish_time）"""
    try:
        # 优先使用 publish_time
        res = (
            sb.table("00_news")
            .select("id", count="exact")
            .gte("publish_time", start.isoformat())
            .lte("publish_time", end.isoformat())
            .execute()
        )
        return res.count or 0
    except Exception:
        # 回退到使用 created_at
        try:
            res = (
                sb.table("00_news")
                .select("id", count="exact")
                .gte("created_at", start.isoformat())
                .lte("created_at", end.isoformat())
                .execute()
            )
            return res.count or 0
        except Exception:
            return 0

# ===================== 辅助逻辑 =====================
def _calc_trend(curr: int, prev: int) -> Tuple[str, str, Optional[str], float]:
    """带平滑上限的环比计算"""
    if prev <= 0 and curr > 0:
        pct = 100.0
    elif prev <= 0 and curr <= 0:
        pct = 0.0
    else:
        pct = round((curr - prev) * 100.0 / prev, 1)

    # 限制显示范围，防止 12700% 这种情况
    pct = max(min(pct, 500.0), -90.0)

    if pct > 0:
        return "success", f"较上期 ↑ {pct}%", "el-icon-top", pct
    elif pct < 0:
        return "danger", f"较上期 ↓ {abs(pct)}%", "el-icon-bottom", pct
    else:
        return "info", "较上期 持平", None, pct


def _progress_from_value(v: int, soft_target: int) -> int:
    if soft_target <= 0:
        return 0
    return max(0, min(100, int(round(v * 100.0 / soft_target))))


# ===================== KPI 主接口 =====================
@data_cards_bp.route("/data-cards", methods=["GET"])
def get_data_cards_latest():
    """
    KPI 数据卡：统计最近7天的新增数据
    - 卡片1（竞品动态）→ 00_competitors_news 表
    - 卡片2（招标机会）→ fact_events 中的“商机”事实，与列表页统一
    - 卡片3（相关论文）→ 00_papers 中带关键词且按标题去重的论文
    - 卡片4（新闻消息）→ 00_news 表
    """
    if not sb:
        return _json_err(500, "Supabase 未配置", http_status=500)

    period = request.args.get("period", "day")  # 保持兼容，但实际固定为7天

    # 使用当前时间作为锚点，统计最近7天和前7天
    anchor_now = datetime.utcnow()
    anchor_date = anchor_now.date()

    # 计算最近7天的时间窗口
    cur_end = datetime.combine(anchor_date, datetime.max.time())
    cur_start = datetime.combine(anchor_date - timedelta(days=6), datetime.min.time())

    # 计算前7天的时间窗口（用于环比）
    prev_end = cur_start - timedelta(seconds=1)
    prev_start = datetime.combine((prev_end.date() - timedelta(days=6)), datetime.min.time())

    # === 统计四个表的新增数量 ===
    # 卡片1：竞品动态（00_competitors_news）
    competitors_news_curr = _count_competitors_news_between(cur_start, cur_end)
    competitors_news_prev = _count_competitors_news_between(prev_start, prev_end)

    # 卡片2：招标机会（fact_events 中的商机记录）
    opportunity_curr = _count_opportunity_between(cur_start, cur_end)
    opportunity_prev = _count_opportunity_between(prev_start, prev_end)

    # 卡片3：相关论文（带关键词且按标题去重）
    papers_curr = _count_papers_between(cur_start, cur_end)
    papers_prev = _count_papers_between(prev_start, prev_end)

    # 卡片4：新闻消息（00_news）
    news_curr = _count_news_between(cur_start, cur_end)
    news_prev = _count_news_between(prev_start, prev_end)

    # === 环比趋势（带限幅） ===
    t1, txt1, icon1, _ = _calc_trend(competitors_news_curr, competitors_news_prev)
    t2, txt2, icon2, _ = _calc_trend(opportunity_curr, opportunity_prev)
    t3, txt3, icon3, _ = _calc_trend(papers_curr, papers_prev)
    t4, txt4, icon4, _ = _calc_trend(news_curr, news_prev)

    # === 组装结果 ===
    cards = [
        {
            "id": 1,
            "label": "竞品动态",
            "value": f"{'+' if competitors_news_curr > 0 else ''}{competitors_news_curr} 条",
            "trend": {"type": t1, "text": txt1, "icon": icon1},
            "progress": _progress_from_value(competitors_news_curr, 100),
            "icon": {"class": "form", "color": "blue"},
        },
        {
            "id": 2,
            "label": "招标机会",
            "value": f"{opportunity_curr} 条",
            "trend": {"type": t2, "text": txt2, "icon": icon2},
            "progress": _progress_from_value(opportunity_curr, 30),
            "icon": {"class": "user", "color": "green"},
        },
        {
            "id": 3,
            "label": "相关论文",
            "value": f"{papers_curr} 篇",
            "trend": {"type": t3, "text": txt3, "icon": icon3},
            "progress": _progress_from_value(papers_curr, 500),
            "icon": {"class": "table", "color": "amber"},
        },
        {
            "id": 4,
            "label": "新闻消息",
            "value": f"{news_curr} 个",
            "trend": {"type": t4, "text": txt4, "icon": icon4},
            "progress": _progress_from_value(news_curr, 10),
            "icon": {"class": "eye", "color": "red"},
        },
    ]

    response_data = {
        "code": 200,
        "message": "success",
        "data": {"date": anchor_date.isoformat(), "period": period, "cards": cards}
    }
    response = make_response(json.dumps(response_data, ensure_ascii=False, indent=2))
    response.status_code = 200
    response.mimetype = 'application/json; charset=utf-8'
    return response

# ===================== 趋势接口 =====================
def _daily_points(start: datetime, end: datetime, counter_fn) -> List[Dict]:
    pts = []
    d = start.date()
    while d <= end.date():
        ds = datetime.combine(d, datetime.min.time())
        de = datetime.combine(d, datetime.max.time())
        val = counter_fn(ds, de)
        pts.append({"date": d.isoformat(), "value": val})
        d += timedelta(days=1)
    for i in range(1, len(pts)):
        prev = pts[i-1]["value"] or 0
        curr = pts[i]["value"] or 0
        _, _, _, pct = _calc_trend(curr, prev)
        pts[i]["change"] = pct
    if pts:
        pts[0]["change"] = 0.0
    return pts

@data_cards_bp.route("/data-cards/trend", methods=["GET"])
def get_data_cards_trend():
    """趋势数据接口（自动取最近7天数据）"""
    if not sb:
        return _json_err(500, "Supabase 未配置", http_status=500)

    card_id = int(request.args.get("cardId", 1))
    period = request.args.get("period", "week")

    end_d = datetime.utcnow().date()
    start_d = end_d - timedelta(days=6)  # 最近7天
    start = datetime.combine(start_d, datetime.min.time())
    end = datetime.combine(end_d, datetime.max.time())

    if card_id == 1:
        # 卡片1：竞品动态（00_competitors_news）
        pts = _daily_points(start, end, _count_competitors_news_between)
    elif card_id == 2:
        # 卡片2：招标机会（fact_events 中的商机记录）
        pts = _daily_points(start, end, _count_opportunity_between)
    elif card_id == 3:
        # 卡片3：相关论文（带关键词且按标题去重）
        pts = _daily_points(start, end, _count_papers_between)
    elif card_id == 4:
        # 卡片4：新闻消息（00_news）
        pts = _daily_points(start, end, _count_news_between)
    else:
        error_data = {"code": 400, "message": "invalid cardId", "data": {}}
        response = make_response(
            json.dumps(error_data, ensure_ascii=False, indent=2)
        )
        response.status_code = 400
        response.mimetype = 'application/json; charset=utf-8'
        return response

    response_data = {
        "code": 200,
        "message": "success",
        "data": {"cardId": card_id, "period": period, "trendData": pts}
    }
    response = make_response(
        json.dumps(response_data, ensure_ascii=False, indent=2)
    )
    response.status_code = 200
    response.mimetype = 'application/json; charset=utf-8'
    return response

# 移除独立运行代码，现在作为Blueprint使用
