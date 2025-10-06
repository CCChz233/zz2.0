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

from flask import Blueprint, jsonify, request, make_response
from supabase import create_client, Client
from datetime import datetime, timedelta, date as date_cls
from typing import Dict, Tuple, List, Optional
import os
import json

# ===================== 初始化 =====================
data_cards_bp = Blueprint('data_cards', __name__)

SUPABASE_URL = os.getenv("SUPABASE_URL", "https://zlajhzeylrzfbchycqyy.supabase.co")
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_KEY", "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InpsYWpoemV5bHJ6ZmJjaHljcXl5Iiwicm9sZSI6InNlcnZpY2Vfcm9sZSIsImlhdCI6MTc1NTYwMTIwMiwiZXhwIjoyMDcxMTc3MjAyfQ.u6vYYEL3qCh4lJU62wEmT4UJTZrstX-_yscRPXrZH7s")

if not SUPABASE_URL or not SUPABASE_KEY:
    raise RuntimeError("❌ 环境变量 SUPABASE_URL / SUPABASE_SERVICE_KEY 未配置。")

sb: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
VIEW_NAME = "news_feed_ready_view"

# ===================== 工具函数 =====================
def _parse_date_arg(d: Optional[str]) -> date_cls:
    if not d:
        return datetime.utcnow().date()
    return datetime.fromisoformat(d).date()

def _period_window(anchor: date_cls, period: str) -> Tuple[datetime, datetime]:
    """计算当前周期的起止时间"""
    if period not in {"day", "week", "month"}:
        period = "day"
    if period == "day":
        start = datetime.combine(anchor, datetime.min.time())
        end = datetime.combine(anchor, datetime.max.time())
    elif period == "week":
        start = datetime.combine(anchor - timedelta(days=6), datetime.min.time())
        end = datetime.combine(anchor, datetime.max.time())
    else:  # month
        first = anchor.replace(day=1)
        if first.month == 12:
            next_first = first.replace(year=first.year + 1, month=1, day=1)
        else:
            next_first = first.replace(month=first.month + 1, day=1)
        start = datetime.combine(first, datetime.min.time())
        end = datetime.combine(next_first - timedelta(seconds=1), datetime.max.time())
    return start, end

def _previous_window(start: datetime, end: datetime) -> Tuple[datetime, datetime]:
    delta = end - start + timedelta(seconds=1)
    prev_end = start - timedelta(seconds=1)
    prev_start = prev_end - delta + timedelta(seconds=1)
    return prev_start, prev_end

# ===================== 数据统计函数 =====================
def _count_news_between(start: datetime, end: datetime) -> int:
    res = (
        sb.table(VIEW_NAME)
        .select("id", count="exact")
        .filter("short_summary", "not.is", "null")
        .neq("short_summary", "")
        .gte("publish_time", start.isoformat())
        .lte("publish_time", end.isoformat())
        .execute()
    )
    return res.count or 0

def _count_papers_between(start: datetime, end: datetime) -> int:
    res = (
        sb.table("00_papers")
        .select("id", count="exact")
        .gte("published_at", start.date().isoformat())
        .lte("published_at", end.date().isoformat())
        .execute()
    )
    return res.count or 0

def _count_competitors_updated_between(start: datetime, end: datetime) -> int:
    res = (
        sb.table("competitors")
        .select("id", count="exact")
        .gte("last_analyzed", start.isoformat())
        .lte("last_analyzed", end.isoformat())
        .execute()
    )
    return res.count or 0

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

def _get_latest_date(table: str, time_field: str) -> Optional[datetime]:
    """从 Supabase 获取表中最新时间字段，并去掉时区信息"""
    res = (
        sb.table(table)
        .select(time_field)
        .order(time_field, desc=True)
        .limit(1)
        .execute()
    )
    if res.data and res.data[0].get(time_field):
        t = res.data[0][time_field]
        try:
            # 兼容三种情况：带Z、带+00:00、不带时区
            if isinstance(t, str):
                t = t.replace("Z", "+00:00") if t.endswith("Z") else t
                dt = datetime.fromisoformat(t)
            else:
                dt = t

            # 如果带 tzinfo（offset-aware），统一转成 UTC，再去 tzinfo
            if dt.tzinfo is not None:
                dt = dt.astimezone(tz=None).replace(tzinfo=None)
            return dt
        except Exception as e:
            print(f"[WARN] parse time error in {table}.{time_field}: {e}")
            return None
    return None


# ===================== KPI 主接口 =====================
@data_cards_bp.route("/data-cards", methods=["GET"])
def get_data_cards_latest():
    """
    自动定位数据库最新日期的 KPI 数据卡
    """
    latest_news = _get_latest_date(VIEW_NAME, "publish_time")
    latest_comp = _get_latest_date("competitors", "last_analyzed")
    latest_paper = _get_latest_date("00_papers", "published_at")
    candidates = [d for d in [latest_news, latest_comp, latest_paper] if d]
    if not candidates:
        response_data = {
            "code": 200,
            "message": "no data found",
            "data": {"cards": [], "date": None, "period": "day"}
        }
        response = make_response(
            json.dumps(response_data, ensure_ascii=False, indent=2)
        )
        response.status_code = 200
        response.mimetype = 'application/json; charset=utf-8'
        return response
    anchor_dt = max(candidates)
    anchor = anchor_dt.date()

    period = request.args.get("period", "day")
    cur_start, cur_end = _period_window(anchor, period)
    prev_start, prev_end = _previous_window(cur_start, cur_end)

    # 数据统计
    news_curr = _count_news_between(cur_start, cur_end)
    news_prev = _count_news_between(prev_start, prev_end)
    papers_curr = _count_papers_between(cur_start, cur_end)
    papers_prev = _count_papers_between(prev_start, prev_end)
    comp_curr = _count_competitors_updated_between(cur_start, cur_end)
    comp_prev = _count_competitors_updated_between(prev_start, prev_end)

    # 预警监控数
    alert_kw = ["原子力", "强磁场", "探针台", "克尔"]
    res = (
        sb.table("competitors")
        .select("id,product")
        .gte("last_analyzed", cur_start.isoformat())
        .lte("last_analyzed", cur_end.isoformat())
        .execute()
    )
    alerts_curr = sum(
        1 for r in (res.data or [])
        if any(k in (r.get("product") or "") for k in alert_kw)
    )
    res_prev = (
        sb.table("competitors")
        .select("id,product")
        .gte("last_analyzed", prev_start.isoformat())
        .lte("last_analyzed", prev_end.isoformat())
        .execute()
    )
    alerts_prev = sum(
        1 for r in (res_prev.data or [])
        if any(k in (r.get("product") or "") for k in alert_kw)
    )

    # 组装结果
    t1, txt1, icon1, _ = _calc_trend(news_curr, news_prev)
    t2, txt2, icon2, _ = _calc_trend(comp_curr, comp_prev)
    t3, txt3, icon3, _ = _calc_trend(papers_curr, papers_prev)
    t4, txt4, icon4, _ = _calc_trend(alerts_curr, alerts_prev)

    cards = [
        {
            "id": 1,
            "label": "今日信息增量",
            "value": f"{'+' if news_curr > 0 else ''}{news_curr} 条",
            "trend": {"type": t1, "text": txt1, "icon": icon1},
            "progress": _progress_from_value(news_curr, 100),
            "icon": {"class": "form", "color": "blue"},
        },
        {
            "id": 2,
            "label": "竞品更新",
            "value": f"{comp_curr} 条",
            "trend": {"type": t2, "text": txt2, "icon": icon2},
            "progress": _progress_from_value(comp_curr, 30),
            "icon": {"class": "user", "color": "green"},
        },
        {
            "id": 3,
            "label": "最新论文",
            "value": f"{papers_curr} 篇",
            "trend": {"type": t3, "text": txt3, "icon": icon3},
            "progress": _progress_from_value(papers_curr, 20),
            "icon": {"class": "table", "color": "amber"},
        },
        {
            "id": 4,
            "label": "预警监控数",
            "value": f"{alerts_curr} 个",
            "trend": {"type": t4, "text": txt4, "icon": icon4},
            "progress": _progress_from_value(alerts_curr, 10),
            "icon": {"class": "eye", "color": "red"},
        },
    ]

    response_data = {
        "code": 200,
        "message": "success",
        "data": {"date": anchor.isoformat(), "period": period, "cards": cards}
    }
    response = make_response(
        json.dumps(response_data, ensure_ascii=False, indent=2)
    )
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
    """趋势数据接口（自动取最近一周数据）"""
    card_id = int(request.args.get("cardId", 1))
    period = request.args.get("period", "week")

    end_d = datetime.utcnow().date()
    start_d = end_d - timedelta(days=6)
    start = datetime.combine(start_d, datetime.min.time())
    end = datetime.combine(end_d, datetime.max.time())

    if card_id == 1:
        pts = _daily_points(start, end, _count_news_between)
    elif card_id == 2:
        pts = _daily_points(start, end, _count_competitors_updated_between)
    elif card_id == 3:
        pts = _daily_points(start, end, _count_papers_between)
    elif card_id == 4:
        def _count_alert(ds, de):
            r = (
                sb.table("competitors")
                .select("id,product")
                .gte("last_analyzed", ds.isoformat())
                .lte("last_analyzed", de.isoformat())
                .execute()
            )
            return sum(
                1 for row in (r.data or [])
                if any(k in (row.get("product") or "") for k in ["原子力", "强磁场", "探针台", "克尔"])
            )
        pts = _daily_points(start, end, _count_alert)
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
