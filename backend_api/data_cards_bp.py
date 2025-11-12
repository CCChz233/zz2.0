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
    """计算当前周期的起止时间（固定为最近30天）"""
    # 固定使用30天窗口
    end = datetime.combine(anchor, datetime.max.time())
    start = datetime.combine(anchor - timedelta(days=29), datetime.min.time())
    return start, end

def _previous_window(start: datetime, end: datetime) -> Tuple[datetime, datetime]:
    delta = end - start + timedelta(seconds=1)
    prev_end = start - timedelta(seconds=1)
    prev_start = prev_end - delta + timedelta(seconds=1)
    return prev_start, prev_end

# ===================== 数据统计函数 =====================
def _count_competitors_news_between(start: datetime, end: datetime) -> int:
    """统计 00_competitors_news 表在指定时间范围内的新增数量（优先使用 created_at）"""
    try:
        # 优先使用 created_at，如果没有则使用 publish_time
        res = (
            sb.table("00_competitors_news")
            .select("id", count="exact")
            .gte("created_at", start.isoformat())
            .lte("created_at", end.isoformat())
            .execute()
        )
        return res.count or 0
    except Exception:
        # 回退到使用 publish_time
        try:
            res = (
                sb.table("00_competitors_news")
                .select("id", count="exact")
                .gte("publish_time", start.isoformat())
                .lte("publish_time", end.isoformat())
                .execute()
            )
            return res.count or 0
        except Exception:
            return 0

def _count_opportunity_between(start: datetime, end: datetime) -> int:
    """统计 00_opportunity 表在指定时间范围内的新增数量（优先使用 created_at）"""
    try:
        # 优先使用 created_at，如果没有则使用 publish_time
        res = (
            sb.table("00_opportunity")
            .select("id", count="exact")
            .gte("created_at", start.isoformat())
            .lte("created_at", end.isoformat())
            .execute()
        )
        return res.count or 0
    except Exception:
        # 回退到使用 publish_time
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
            return 0

def _count_papers_between(start: datetime, end: datetime) -> int:
    """统计 00_papers 表在指定时间范围内的新增数量（优先使用 created_at）"""
    try:
        # 优先使用 created_at
        res = (
            sb.table("00_papers")
            .select("id", count="exact")
            .gte("created_at", start.isoformat())
            .lte("created_at", end.isoformat())
            .execute()
        )
        return res.count or 0
    except Exception:
        # 回退到使用 published_at（date 类型）
        try:
            res = (
                sb.table("00_papers")
                .select("id", count="exact")
                .gte("published_at", start.date().isoformat())
                .lte("published_at", end.date().isoformat())
                .execute()
            )
            return res.count or 0
        except Exception:
            return 0

def _count_news_between(start: datetime, end: datetime) -> int:
    """统计 00_news 表在指定时间范围内的新增数量（优先使用 created_at）"""
    try:
        # 优先使用 created_at
        res = (
            sb.table("00_news")
            .select("id", count="exact")
            .gte("created_at", start.isoformat())
            .lte("created_at", end.isoformat())
            .execute()
        )
        return res.count or 0
    except Exception:
        # 回退到使用 publish_time
        try:
            res = (
                sb.table("00_news")
                .select("id", count="exact")
                .gte("publish_time", start.isoformat())
                .lte("publish_time", end.isoformat())
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
    KPI 数据卡：统计最近30天的新增数据
    - 卡片1（竞品动态）→ 00_competitors_news 表
    - 卡片2（招标机会）→ 00_opportunity 表
    - 卡片3（相关论文）→ 00_papers 表
    - 卡片4（新闻消息）→ 00_news 表
    """
    period = request.args.get("period", "day")  # 保持兼容，但实际固定为30天

    # 使用当前时间作为锚点，统计最近30天和上30天
    anchor_now = datetime.utcnow()
    anchor_date = anchor_now.date()

    # 计算最近30天的时间窗口
    cur_end = datetime.combine(anchor_date, datetime.max.time())
    cur_start = datetime.combine(anchor_date - timedelta(days=29), datetime.min.time())
    
    # 计算上30天的时间窗口（用于环比）
    prev_end = cur_start - timedelta(seconds=1)
    prev_start = datetime.combine((prev_end.date() - timedelta(days=29)), datetime.min.time())

    # === 统计四个表的新增数量 ===
    # 卡片1：竞品动态（00_competitors_news）
    competitors_news_curr = _count_competitors_news_between(cur_start, cur_end)
    competitors_news_prev = _count_competitors_news_between(prev_start, prev_end)

    # 卡片2：招标机会（00_opportunity）
    opportunity_curr = _count_opportunity_between(cur_start, cur_end)
    opportunity_prev = _count_opportunity_between(prev_start, prev_end)

    # 卡片3：相关论文（00_papers）
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
            "progress": _progress_from_value(papers_curr, 20),
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
    """趋势数据接口（自动取最近30天数据）"""
    card_id = int(request.args.get("cardId", 1))
    period = request.args.get("period", "week")

    end_d = datetime.utcnow().date()
    start_d = end_d - timedelta(days=29)  # 最近30天
    start = datetime.combine(start_d, datetime.min.time())
    end = datetime.combine(end_d, datetime.max.time())

    if card_id == 1:
        # 卡片1：竞品动态（00_competitors_news）
        pts = _daily_points(start, end, _count_competitors_news_between)
    elif card_id == 2:
        # 卡片2：招标机会（00_opportunity）
        pts = _daily_points(start, end, _count_opportunity_between)
    elif card_id == 3:
        # 卡片3：相关论文（00_papers）
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
