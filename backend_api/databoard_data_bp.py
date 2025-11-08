# -*- coding: utf-8 -*-
"""
Databoard · 数据模块 API Blueprint
----------------------------------
本 Blueprint 依据《数据看板数据模块 API 文档》实现以下端点：
  GET /api/databoard/data/getNews

设计目标：
- 与现有 Blueprint 写法保持一致（Supabase 作为唯一数据源，响应统一包装）。
- 提供政策/行业新闻趋势、竞品动态趋势+类型分布、研究论文趋势+热点主题。
- 在 Supabase 查询异常或暂无数据时，保证返回结构完整（数值回退为 0）。

环境变量（可选项均提供默认值，需按实际库结构调整）:
  SUPABASE_URL                 Supabase 项目 URL
  SUPABASE_SERVICE_KEY         Service Role Key
  DATABOARD_NEWS_VIEW          新闻视图/表，需包含 publish_time 与 news_type
  DATABOARD_ANALYSIS_TABLE     竞品分析结果表，需包含 competitor_id、analysis_date/created_at
  DATABOARD_COMPETITORS_TABLE  竞品主数据表，需包含 id、company_name
  DATABOARD_PAPERS_TABLE       论文事实表，需包含 published_at、payload->keywords
  DATABOARD_NEWS_MONTHS        新闻趋势默认月份数（默认 12）
  DATABOARD_TREND_MONTHS       竞品/研究趋势月份数（默认 6）
  DATABOARD_FETCH_BATCH_SIZE   Supabase 拉取每页大小（默认 500）
  DATABOARD_FETCH_MAX_RECORDS  Supabase 最大拉取条数（默认 2000）
"""
from __future__ import annotations

import json
import os
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Sequence, Tuple

from dateutil import parser as dateparser
from dateutil.relativedelta import relativedelta
from flask import Blueprint, make_response, request
from supabase import Client, create_client

# ===================== 初始化 =====================
databoard_data_bp = Blueprint("databoard_data", __name__)

SUPABASE_URL = os.getenv("SUPABASE_URL", "https://zlajhzeylrzfbchycqyy.supabase.co")
SUPABASE_KEY = os.getenv(
    "SUPABASE_SERVICE_KEY",
    "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InpsYWpoemV5bHJ6ZmJjaHljcXl5Iiwicm9sZSI6InNlcnZpY2Vfcm9sZSIsImlhdCI6MTc1NTYwMTIwMiwiZXhwIjoyMDcxMTc3MjAyfQ.u6vYYEL3qCh4lJU62wEmT4UJTZrstX-_yscRPXrZH7s",
)

if not SUPABASE_URL or not SUPABASE_KEY:
    raise RuntimeError("❌ 环境变量 SUPABASE_URL / SUPABASE_SERVICE_KEY 未配置。")

sb: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# ===================== 配置常量 =====================
NEWS_VIEW = os.getenv("DATABOARD_NEWS_VIEW", os.getenv("NEWS_FEED_VIEW", "news_feed_ready_view_v2"))
ANALYSIS_TABLE = os.getenv("DATABOARD_ANALYSIS_TABLE", "analysis_results")
COMPETITOR_TABLE = os.getenv("DATABOARD_COMPETITORS_TABLE", "00_competitors")
PAPER_TABLE = os.getenv("DATABOARD_PAPERS_TABLE", "fact_papers")

DEFAULT_NEWS_MONTHS = int(os.getenv("DATABOARD_NEWS_MONTHS", "12"))
DEFAULT_TREND_MONTHS = int(os.getenv("DATABOARD_TREND_MONTHS", "6"))
FETCH_BATCH_SIZE = max(1, int(os.getenv("DATABOARD_FETCH_BATCH_SIZE", "500")))
FETCH_MAX_RECORDS = max(FETCH_BATCH_SIZE, int(os.getenv("DATABOARD_FETCH_MAX_RECORDS", "2000")))

COLOR_POLICY = "#5470c6"
COLOR_INDUSTRY = "#3ba272"
COMPETITOR_COLORS = ["#91cc75", "#fac858", "#ee6666", "#73c0de", "#fc8452"]
RESEARCH_COLORS = ["#73c0de", "#3ba272", "#fc8452", "#5470c6", "#9a60b4"]
COMP_TYPE_ORDER = ["产品发布", "市场活动", "技术更新", "合作签约", "其他动态"]

# ===================== 工具函数 =====================
def _json_ok(data: Any, code: int = 200, message: str = "success", http_status: int = 200):
    payload = {"code": code, "message": message, "data": data}
    resp = make_response(json.dumps(payload, ensure_ascii=False, indent=2))
    resp.status_code = http_status
    resp.mimetype = "application/json; charset=utf-8"
    return resp


def _json_err(code: int, message: str, http_status: int = 400, data: Optional[dict] = None):
    payload = {"code": code, "message": message, "data": data or {}}
    resp = make_response(json.dumps(payload, ensure_ascii=False, indent=2))
    resp.status_code = http_status
    resp.mimetype = "application/json; charset=utf-8"
    return resp


def _safe_int(value: Optional[str], default: int, minimum: int, maximum: int) -> int:
    try:
        num = int(value) if value is not None else default
    except (TypeError, ValueError):
        num = default
    return max(minimum, min(maximum, num))


def _parse_dt(value: Any) -> Optional[datetime]:
    if value is None:
        return None
    if isinstance(value, datetime):
        dt = value
    else:
        text = str(value).strip()
        if not text:
            return None
        text = text.replace("Z", "+00:00") if text.endswith("Z") else text
        try:
            dt = datetime.fromisoformat(text)
        except ValueError:
            try:
                dt = dateparser.isoparse(text)
            except Exception:
                return None
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def _month_buckets(months: int, anchor: Optional[datetime] = None) -> List[Tuple[str, datetime, datetime]]:
    """返回 [(label, start, end)]。"""
    if months <= 0:
        return []
    anchor = (anchor or datetime.utcnow()).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    buckets: List[Tuple[str, datetime, datetime]] = []
    for idx in range(months):
        start = anchor - relativedelta(months=months - idx - 1)
        end = start + relativedelta(months=1) - timedelta(seconds=1)
        buckets.append((f"{start.month}月", start, end))
    return buckets


def _bucket_index(dt: datetime, buckets: Sequence[Tuple[str, datetime, datetime]]) -> Optional[int]:
    for idx, (_, start, end) in enumerate(buckets):
        if start <= dt <= end:
            return idx
    return None


def _fetch_rows(
    table: str,
    columns: str = "*",
    filters: Optional[List[Tuple[str, str, Any]]] = None,
    order: Optional[Tuple[str, bool]] = None,
    batch_size: int = FETCH_BATCH_SIZE,
    max_records: int = FETCH_MAX_RECORDS,
) -> List[Dict[str, Any]]:
    """
    通用 Supabase 拉取函数（分页 + 容错）。
    - filters: 列表 (op, field, value)，支持 gte/lte/eq/in。
    - order: (field, desc)。
    """
    rows: List[Dict[str, Any]] = []
    filters = filters or []
    offset = 0

    while offset < max_records:
        try:
            query = sb.table(table).select(columns)
            for op, field, value in filters:
                if op == "gte":
                    query = query.gte(field, value)
                elif op == "lte":
                    query = query.lte(field, value)
                elif op == "eq":
                    query = query.eq(field, value)
                elif op == "in":
                    query = query.in_(field, value or [])
                elif op == "is":
                    query = query.is_(field, value)
            if order:
                field, desc = order
                query = query.order(field, desc=bool(desc))
            res = query.range(offset, offset + batch_size - 1).execute()
            data = res.data or []
            rows.extend(data)
            if len(data) < batch_size:
                break
            offset += batch_size
        except Exception as exc:  # pragma: no cover
            print(f"[WARN] fetch {table} failed at offset={offset}: {exc}")
            break
    return rows[:max_records]


def _classify_competitor_event(row: Dict[str, Any]) -> str:
    """基于摘要/正文的简单关键词分类，用于竞品类型饼图。"""
    text_parts: List[str] = []
    for key in ("summary_report", "summary_md", "website_content", "title", "content"):
        val = row.get(key)
        if isinstance(val, str) and val.strip():
            text_parts.append(val)
    payload = row.get("payload")
    if isinstance(payload, dict):
        for key in ("summary", "summary_md", "content"):
            val = payload.get(key)
            if isinstance(val, str) and val.strip():
                text_parts.append(val)
    text = " ".join(text_parts)
    if not text:
        return "其他动态"

    lowered = text.lower()
    rules = {
        "产品发布": ["新品", "发布", "升级", "版本", "上市", "roadmap"],
        "市场活动": ["市场", "活动", "营销", "推广", "展会", "峰会", "大会", "博览"],
        "技术更新": ["技术", "研发", "突破", "算法", "专利", "创新", "技术更新", "技术升级"],
        "合作签约": ["合作", "签约", "协议", "战略合作", "联合", "携手", "共建"],
    }
    for label, keywords in rules.items():
        for kw in keywords:
            if kw.lower() in lowered:
                return label
    return "其他动态"


def _extract_keywords(row: Dict[str, Any]) -> List[str]:
    payload = row.get("payload")
    kws: List[str] = []
    if isinstance(payload, dict):
        raw = payload.get("keywords") or payload.get("keyword")
        if isinstance(raw, list):
            for item in raw:
                if isinstance(item, str):
                    word = item.strip()
                    if word:
                        kws.append(word[:30])
    return kws


def _load_competitor_names(ids: Sequence[str]) -> Dict[str, str]:
    if not ids:
        return {}
    rows = _fetch_rows(
        COMPETITOR_TABLE,
        columns="id, company_name",
        filters=[("in", "id", list(ids))],
        order=None,
        batch_size=min(len(ids), FETCH_BATCH_SIZE),
        max_records=len(ids),
    )
    mapping: Dict[str, str] = {}
    for r in rows:
        cid = r.get("id")
        if cid:
            mapping[cid] = (r.get("company_name") or "").strip() or cid
    return mapping


def _news_statistics(months: int) -> Dict[str, Any]:
    buckets = _month_buckets(months)
    labels = [label for label, _, _ in buckets]
    counts = {
        "policy": [0] * len(buckets),
        "industry": [0] * len(buckets),
    }
    if not buckets:
        return {
            "policyNews": {"xAxisData": [], "seriesData": [{"name": "政策新闻", "data": [], "color": COLOR_POLICY}]},
            "industryNews": {"xAxisData": [], "seriesData": [{"name": "行业新闻", "data": [], "color": COLOR_INDUSTRY}]},
        }

    start_iso = buckets[0][1].isoformat()
    end_iso = buckets[-1][2].isoformat()

    rows = _fetch_rows(
        NEWS_VIEW,
        columns="news_type, publish_time",
        filters=[("gte", "publish_time", start_iso), ("lte", "publish_time", end_iso)],
        order=("publish_time", True),
    )

    for row in rows:
        dt = _parse_dt(row.get("publish_time"))
        if not dt:
            continue
        idx = _bucket_index(dt, buckets)
        if idx is None:
            continue
        typ = (row.get("news_type") or "").lower()
        if typ == "policy":
            counts["policy"][idx] += 1
        elif typ == "industry":
            counts["industry"][idx] += 1

    return {
        "policyNews": {
            "xAxisData": labels,
            "seriesData": [
                {
                    "name": "政策新闻",
                    "data": counts["policy"],
                    "color": COLOR_POLICY,
                }
            ],
        },
        "industryNews": {
            "xAxisData": labels,
            "seriesData": [
                {
                    "name": "行业新闻",
                    "data": counts["industry"],
                    "color": COLOR_INDUSTRY,
                }
            ],
        },
    }


def _competitor_statistics(months: int) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    buckets = _month_buckets(months)
    labels = [label for label, _, _ in buckets]
    if not buckets:
        empty = {"xAxisData": [], "seriesData": []}
        return empty, [{"seriesData": [{"value": 0, "name": label} for label in COMP_TYPE_ORDER]}]

    start_iso_date = buckets[0][1].date().isoformat()
    start_iso_ts = buckets[0][1].isoformat()

    rows = _fetch_rows(
        ANALYSIS_TABLE,
        columns="id, competitor_id, analysis_date, created_at, summary_report, website_content, payload",
        filters=[("gte", "analysis_date", start_iso_date)],
        order=("analysis_date", True),
    )
    if not rows:
        rows = _fetch_rows(
            ANALYSIS_TABLE,
            columns="id, competitor_id, analysis_date, created_at, summary_report, website_content, payload",
            filters=[("gte", "created_at", start_iso_ts)],
            order=("created_at", True),
        )

    series_map: Dict[str, List[int]] = defaultdict(lambda: [0] * len(buckets))
    type_counter: Counter[str] = Counter()

    end_bound = buckets[-1][2]

    for row in rows:
        cid = row.get("competitor_id")
        if not cid:
            continue
        dt = _parse_dt(row.get("analysis_date") or row.get("created_at"))
        if not dt or dt < buckets[0][1] or dt > end_bound:
            continue
        idx = _bucket_index(dt, buckets)
        if idx is None:
            continue
        series_map[cid][idx] += 1
        type_counter[_classify_competitor_event(row)] += 1

    ranked = sorted(series_map.items(), key=lambda item: sum(item[1]), reverse=True)[:3]
    comp_names = _load_competitor_names([cid for cid, _ in ranked])

    trend_series: List[Dict[str, Any]] = []
    for idx, (cid, data) in enumerate(ranked):
        name = comp_names.get(cid) or f"竞品{idx + 1}"
        color = COMPETITOR_COLORS[idx % len(COMPETITOR_COLORS)]
        trend_series.append({"name": name, "data": data, "color": color})

    # 如果不足三条，补零保持前端结构稳定
    while len(trend_series) < 3:
        idx = len(trend_series)
        trend_series.append(
            {
                "name": f"竞品{idx + 1}",
                "data": [0] * len(buckets),
                "color": COMPETITOR_COLORS[idx % len(COMPETITOR_COLORS)],
            }
        )

    total_known = 0
    series_data: List[Dict[str, Any]] = []
    for label in COMP_TYPE_ORDER[:-1]:
        value = type_counter.get(label, 0)
        total_known += value
        series_data.append({"value": value, "name": label})

    other_value = max(0, sum(type_counter.values()) - total_known)
    other_value = other_value or type_counter.get("其他动态", 0)
    series_data.append({"value": other_value, "name": "其他动态"})

    return {"xAxisData": labels, "seriesData": trend_series}, [{"seriesData": series_data}]


def _research_statistics(months: int) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    buckets = _month_buckets(months)
    labels = [label for label, _, _ in buckets]
    if not buckets:
        empty = {"xAxisData": [], "seriesData": []}
        return empty, [{"seriesData": []}]

    start_iso_date = buckets[0][1].date().isoformat()
    rows = _fetch_rows(
        PAPER_TABLE,
        columns="id, published_at, title, payload",
        filters=[("gte", "published_at", start_iso_date)],
        order=("published_at", True),
    )

    kw_counter: Counter[str] = Counter()
    kw_month_map: Dict[str, List[int]] = defaultdict(lambda: [0] * len(buckets))

    for row in rows:
        dt = _parse_dt(row.get("published_at"))
        if not dt:
            continue
        idx = _bucket_index(dt, buckets)
        if idx is None:
            continue
        keywords = _extract_keywords(row) or ["其他主题"]
        for kw in keywords:
            kw_counter[kw] += 1
            kw_month_map[kw][idx] += 1

    top_keywords = [kw for kw, _ in kw_counter.most_common(3)]
    if not top_keywords:
        top_keywords = ["人工智能", "大数据", "云计算"]
        for kw in top_keywords:
            kw_month_map.setdefault(kw, [0] * len(buckets))

    trend_series: List[Dict[str, Any]] = []
    for idx, kw in enumerate(top_keywords):
        trend_series.append(
            {
                "name": kw,
                "data": kw_month_map.get(kw, [0] * len(buckets)),
                "color": RESEARCH_COLORS[idx % len(RESEARCH_COLORS)],
            }
        )

    pie_items = kw_counter.most_common(4)
    counted = sum(count for _, count in pie_items)
    other_count = max(0, sum(kw_counter.values()) - counted)
    if other_count > 0 or not pie_items:
        pie_items.append(("其他主题", other_count))
    research_topic = [
        {
            "seriesData": [{"value": count, "name": kw} for kw, count in pie_items],
        }
    ]

    return {"xAxisData": labels, "seriesData": trend_series}, research_topic


# ===================== 路由实现 =====================
@databoard_data_bp.route("/getNews", methods=["GET"])
def get_databoard_data():
    """
    返回数据看板所需的综合统计：
      - 新闻（月度趋势，政策/行业）
      - 竞品（月度趋势、事件类型占比）
      - 研究（月度趋势、热点主题占比）
    可选查询参数：
      newsMonths: int [3,24]   默认为 DATABOARD_NEWS_MONTHS（12）
      trendMonths: int [3,12]  默认为 DATABOARD_TREND_MONTHS（6）
    """
    news_months = _safe_int(request.args.get("newsMonths"), DEFAULT_NEWS_MONTHS, 3, 24)
    trend_months = _safe_int(request.args.get("trendMonths"), DEFAULT_TREND_MONTHS, 3, 12)

    try:
        news_stats = _news_statistics(news_months)
        competitor_trend, competitor_type = _competitor_statistics(trend_months)
        research_trend, research_topic = _research_statistics(trend_months)

        payload = {
            "statistics": {
                "policyNews": news_stats["policyNews"],
                "industryNews": news_stats["industryNews"],
                "competitorTrend": competitor_trend,
                "competitorType": competitor_type,
                "researchTrend": research_trend,
                "researchTopic": research_topic,
            }
        }
        return _json_ok(payload)
    except ValueError as exc:
        return _json_err(400, f"invalid parameters: {exc}")
    except Exception as exc:  # pragma: no cover
        print(f"[ERROR] databoard_data_bp: {exc}")
        return _json_err(500, "internal server error")

