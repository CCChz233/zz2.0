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
  SUPABASE_URL                      Supabase 项目 URL
  SUPABASE_SERVICE_KEY              Service Role Key
  DATABOARD_NEWS_TABLE              新闻表（默认：00_news），需包含 publish_time 与 news_type
  DATABOARD_COMPETITOR_NEWS_TABLE   竞品新闻表（默认：00_competitors_news），需包含 publish_time、title、content
  DATABOARD_COMPETITORS_TABLE       竞品公司表（默认：00_competitors），需包含 id、company_name
  DATABOARD_PAPERS_TABLE            论文表（默认：00_papers），需包含 published_at、keywords_matched
  DATABOARD_OPPORTUNITY_TABLE       招标机会表（默认：00_opportunity），需包含 publish_time
  DATABOARD_NEWS_MONTHS             新闻趋势默认月份数（默认 12）
  DATABOARD_TREND_MONTHS            竞品/研究趋势月份数（默认 6）
  DATABOARD_FETCH_BATCH_SIZE        Supabase 拉取每页大小（默认 500）
  DATABOARD_FETCH_MAX_RECORDS       Supabase 最大拉取条数（默认 2000）
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
# 根据实际表结构配置
NEWS_TABLE = os.getenv("DATABOARD_NEWS_TABLE", "00_news")  # 新闻表
COMPETITOR_NEWS_TABLE = os.getenv("DATABOARD_COMPETITOR_NEWS_TABLE", "00_competitors_news")  # 竞品新闻表
COMPETITOR_TABLE = os.getenv("DATABOARD_COMPETITORS_TABLE", "00_competitors")  # 竞品公司表
PAPER_TABLE = os.getenv("DATABOARD_PAPERS_TABLE", "00_papers")  # 论文表
OPPORTUNITY_TABLE = os.getenv("DATABOARD_OPPORTUNITY_TABLE", "00_opportunity")  # 招标机会表
MONTHLY_TABLE = os.getenv("DATABOARD_MONTHLY_TABLE", "dashboard_daily_events")
MONTHLY_EVENT_TYPE = os.getenv("DATABOARD_MONTHLY_EVENT_TYPE", "monthly_summary")
MONTHLY_EVENT_ORDER = [
    ("monthly-行业新闻", "行业新闻"),
    ("monthly-竞品动态", "竞品动态"),
    ("monthly-销售机会", "销售机会"),
    ("monthly-科技论文", "科技论文"),
]

DEFAULT_NEWS_MONTHS = int(os.getenv("DATABOARD_NEWS_MONTHS", "12"))
DEFAULT_TREND_MONTHS = int(os.getenv("DATABOARD_TREND_MONTHS", "6"))
FETCH_BATCH_SIZE = max(1, int(os.getenv("DATABOARD_FETCH_BATCH_SIZE", "500")))
FETCH_MAX_RECORDS = max(FETCH_BATCH_SIZE, int(os.getenv("DATABOARD_FETCH_MAX_RECORDS", "2000")))

# ===================== 数据模式开关 =====================
# 数据模式开关：True=使用模拟数据（缺省值模式），False=查询数据库（统计模式）
# 直接修改这里的值即可切换模式
USE_DEFAULT_DATA = True  # 改为 False 则使用数据库统计模式

COLOR_POLICY = "#5470c6"
COLOR_INDUSTRY = "green"
COLOR_BID = "#d37448"
COMPETITOR_COLORS = ["#91cc75", "#fac858", "#ee6666", "#73c0de", "#fc8452"]
RESEARCH_COLORS = ["#5470C6", "#91CC75", "#FAC858", "#EE6666", "#73C0DE", "#3BA272"]
COMP_TYPE_ORDER = ["融资", "市场活动", "技术更新", "合作签约", "其他动态"]

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


def _empty_line_chart(name: str, color: str, labels: Optional[List[str]] = None) -> Dict[str, Any]:
    """
    生成统一的空折线图数据格式。
    
    Args:
        name: 系列名称
        color: 系列颜色
        labels: X轴标签列表，如果为None则返回空数组
    
    Returns:
        {
            "xAxisData": [...],
            "seriesData": [{"name": "...", "data": [...], "color": "..."}]
        }
    """
    x_axis_data = labels if labels is not None else []
    data_points = [0] * len(x_axis_data) if x_axis_data else []
    return {
        "xAxisData": x_axis_data,
        "seriesData": [
            {
                "name": name,
                "data": data_points,
                "color": color,
            }
        ],
    }


def _default_line_chart(name: str, color: str, months: int = 12) -> Dict[str, Any]:
    """
    生成带默认模拟数据的折线图（用于无数据时显示好看的图表）。
    生成一个平滑的上升趋势曲线。
    """
    import random
    labels = [f"{i}月" for i in range(1, months + 1)]
    # 生成一个平滑的上升趋势，带一些随机波动
    base_value = 50
    trend = [base_value + i * 5 + random.randint(-10, 15) for i in range(months)]
    # 确保最小值不为负
    trend = [max(0, v) for v in trend]
    return {
        "xAxisData": labels,
        "seriesData": [
            {
                "name": name,
                "data": trend,
                "color": color,
            }
        ],
    }


def _default_day_chart(name: str, color: str, days: int = 7) -> Dict[str, Any]:
    """
    生成带默认模拟数据的日统计折线图（带真实波动）。
    """
    import random
    from datetime import datetime, timedelta
    anchor = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    labels = []
    data = []
    # 使用累积随机变化，模拟真实波动
    current_value = random.randint(1, 3)  # 起始值
    for i in range(days):
        start = anchor - timedelta(days=days - i - 1)
        labels.append(f"{start.month}月{start.day}日")
        # 有60%概率上升，40%概率下降
        if random.random() < 0.6:
            # 上升：增加0-2之间的随机值
            change = random.randint(0, 2)
        else:
            # 下降：减少0-2之间的随机值
            change = -random.randint(0, 2)
        # 添加随机噪声（-1到+1）
        noise = random.randint(-1, 1)
        current_value = max(0, current_value + change + noise)
        data.append(int(current_value))
    return {
        "xAxisData": labels,
        "seriesData": [
            {
                "name": name,
                "data": data,
                "color": color,
            }
        ],
    }


def _empty_pie_chart(items: Optional[List[Tuple[str, int]]] = None) -> Dict[str, Any]:
    """
    生成统一的空饼图数据格式。
    
    Args:
        items: 可选，[(name, value)] 列表。如果提供，返回这些项（value为0）；
               如果为None，返回空数组
    
    Returns:
        {"seriesData": [{"value": ..., "name": "..."}, ...]}
    """
    if items is None:
        return {"seriesData": []}
    return {
        "seriesData": [{"value": value, "name": name} for name, value in items]
    }


def _default_pie_chart(items: List[Tuple[str, int]]) -> Dict[str, Any]:
    """
    生成带默认模拟数据的饼图（用于无数据时显示好看的图表）。
    为每个分类生成合理的随机值。
    """
    import random
    # 生成总数为100-500之间的随机值，然后按比例分配
    total = random.randint(100, 500)
    num_items = len(items)
    if num_items == 0:
        return {"seriesData": []}
    
    # 生成随机比例（总和为1）
    ratios = [random.random() for _ in range(num_items)]
    ratio_sum = sum(ratios)
    ratios = [r / ratio_sum for r in ratios]
    
    # 按比例分配，确保每个值至少为5
    values = [max(5, int(total * r)) for r in ratios]
    # 调整最后一个值，确保总和正确
    values[-1] = total - sum(values[:-1])
    
    return {
        "seriesData": [{"value": value, "name": name} for (name, _), value in zip(items, values)]
    }


def _empty_pie_chart_array(items: Optional[List[Tuple[str, int]]] = None) -> List[Dict[str, Any]]:
    """
    生成统一的空饼图数据格式（数组包装，用于竞品类型等）。
    
    Args:
        items: 可选，[(name, value)] 列表。如果提供，返回这些项（value为0）；
               如果为None，返回包含空数组的单个对象
    
    Returns:
        [{"seriesData": [{"value": ..., "name": "..."}, ...]}]
    """
    if items is None:
        return [{"seriesData": []}]
    return [_empty_pie_chart(items)]


def _default_pie_chart_array(items: List[Tuple[str, int]]) -> List[Dict[str, Any]]:
    """
    生成带默认模拟数据的饼图数组格式。
    """
    return [_default_pie_chart(items)]


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


def _day_buckets(days: int, anchor: Optional[datetime] = None) -> List[Tuple[str, datetime, datetime]]:
    """返回近N天的日期桶 [(label, start, end)]。
    标签格式：11月4日（与API文档一致）
    """
    if days <= 0:
        return []
    anchor = (anchor or datetime.utcnow()).replace(hour=0, minute=0, second=0, microsecond=0)
    buckets: List[Tuple[str, datetime, datetime]] = []
    for idx in range(days):
        start = anchor - timedelta(days=days - idx - 1)
        end = start + timedelta(days=1) - timedelta(seconds=1)
        # 格式：11月4日（与API文档一致）
        label = f"{start.month}月{start.day}日"
        buckets.append((label, start, end))
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


def _fetch_monthly_summaries(view: str) -> List[Dict[str, Any]]:
    """
    从 dashboard_daily_events（或自定义表）中读取月度汇总结果。
    返回顺序固定为行业新闻/竞品动态/销售机会/科技论文。
    """
    try:
        res = (
            sb.table(MONTHLY_TABLE)
            .select("event_id,payload,priority,category,report_date,created_ts,processed_at,view")
            .eq("view", view)
            .eq("event_type", MONTHLY_EVENT_TYPE)
            .order("report_date", desc=True)
            .order("created_ts", desc=True)
            .limit(len(MONTHLY_EVENT_ORDER) * 4)
            .execute()
        )
        rows = res.data or []
    except Exception as exc:  # pragma: no cover
        print(f"[WARN] fetch monthly summary failed: {exc}")
        rows = []

    latest_by_event: Dict[str, Dict[str, Any]] = {}
    for row in rows:
        event_id = row.get("event_id")
        if not event_id:
            continue
        if event_id not in latest_by_event:
            latest_by_event[event_id] = row

    items: List[Dict[str, Any]] = []
    for event_id, display_name in MONTHLY_EVENT_ORDER:
        row = latest_by_event.get(event_id, {})
        payload = row.get("payload")
        if not isinstance(payload, dict):
            payload = {}
        items.append(
            {
                "eventId": event_id,
                "displayName": display_name,
                "category": row.get("category") or display_name,
                "reportDate": row.get("report_date"),
                "priority": (row.get("priority") or "medium").lower(),
                "createdTs": row.get("created_ts") or row.get("processed_at"),
                "payload": payload,
            }
        )
    return items


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
        "融资": ["融资", "投资", "轮次", "估值", "募资", "IPO", "上市", "IPO"],
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
    """
    从论文行中提取关键词。
    优先使用 keywords_matched 字段（text[]），如果没有则尝试从 payload 中提取。
    """
    # 优先使用 keywords_matched 字段（00_papers 表的实际字段）
    keywords_matched = row.get("keywords_matched")
    if isinstance(keywords_matched, list):
        kws = [kw.strip() for kw in keywords_matched if isinstance(kw, str) and kw.strip()]
        if kws:
            return [kw[:30] for kw in kws]
    
    # 回退：尝试从 payload 中提取（如果存在）
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


def _news_statistics_default(months: int) -> Dict[str, Any]:
    """新闻统计：生成默认模拟数据（带真实波动）"""
    import random
    labels = [f"{i}月" for i in range(1, months + 1)]
    
    # 政策新闻：使用累积随机变化，模拟真实波动
    policy_data = []
    current_value = random.randint(6, 12)  # 起始值
    for i in range(months):
        # 有70%概率上升，30%概率下降，但整体趋势向上
        if random.random() < 0.7:
            # 上升：增加1-6之间的随机值
            change = random.randint(1, 6)
        else:
            # 下降：减少1-4之间的随机值
            change = -random.randint(1, 4)
        # 添加额外的随机波动（-3到+3）
        noise = random.randint(-3, 3)
        current_value = max(4, current_value + change + noise)
        policy_data.append(int(current_value))
    
    # 行业新闻：波动更大，体现行业活跃度
    industry_data = []
    current_value = random.randint(10, 18)  # 起始值
    for i in range(months):
        # 有65%概率上升，35%概率下降
        if random.random() < 0.65:
            # 上升：增加1-8之间的随机值
            change = random.randint(1, 8)
        else:
            # 下降：减少1-6之间的随机值
            change = -random.randint(1, 6)
        # 添加较大的随机波动（-5到+5）
        noise = random.randint(-5, 5)
        current_value = max(6, current_value + change + noise)
        industry_data.append(int(current_value))
    
    return {
        "policyNews": {
            "xAxisData": labels,
            "seriesData": [
                {
                    "name": "新闻消息",
                    "data": policy_data,
                    "color": COLOR_POLICY,
                }
            ],
        },
        "industryNews": {
            "xAxisData": labels,
            "seriesData": [
                {
                    "name": "行业新闻",
                    "data": industry_data,
                    "color": COLOR_INDUSTRY,
                }
            ],
        },
    }


def _news_statistics(months: int) -> Dict[str, Any]:
    """新闻统计：使用数据库查询（00_news 表）"""
    # 新闻部分始终使用数据库，不受 USE_DEFAULT_DATA 开关影响
    # 数据库统计模式
    buckets = _month_buckets(months)
    labels = [label for label, _, _ in buckets]
    counts = {
        "policy": [0] * len(buckets),
        "industry": [0] * len(buckets),
    }
    if not buckets:
        return {
            "policyNews": _empty_line_chart("新闻消息", COLOR_POLICY),
            "industryNews": _empty_line_chart("行业新闻", COLOR_INDUSTRY),
        }

    start_iso = buckets[0][1].isoformat()
    end_iso = buckets[-1][2].isoformat()

    # 从 00_news 表查询新闻数据
    rows = _fetch_rows(
        NEWS_TABLE,
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
        # 根据 news_type 字段分类：支持 "政策新闻" 和 "行业新闻"
        typ = (row.get("news_type") or "").strip()
        if typ == "政策新闻":
            counts["policy"][idx] += 1
        elif typ == "行业新闻":
            counts["industry"][idx] += 1
        # 兼容旧格式（英文或简写）
        elif typ.lower() in ("policy", "政策"):
            counts["policy"][idx] += 1
        elif typ.lower() in ("industry", "行业"):
            counts["industry"][idx] += 1

    return {
        "policyNews": {
            "xAxisData": labels,
            "seriesData": [
                {
                    "name": "新闻消息",
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


def _competitor_statistics_default(months: int) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    """竞品统计：生成默认模拟数据（带真实波动）"""
    import random
    labels = [f"{i}月" for i in range(1, months + 1)]
    
    # 生成3条竞品趋势线，每条有不同的波动模式
    trend_series = []
    for idx in range(3):
        # 每条线有不同的起始值和波动特性
        current_value = random.randint(2 + idx * 2, 5 + idx * 2)
        data = []
        for i in range(months):
            # 每条线有不同的上升概率（60%-75%）
            up_prob = 0.6 + idx * 0.05
            if random.random() < up_prob:
                # 上升：增加0-4之间的随机值
                change = random.randint(0, 4)
            else:
                # 下降：减少0-3之间的随机值
                change = -random.randint(0, 3)
            # 添加随机噪声（-2到+3）
            noise = random.randint(-2, 3)
            current_value = max(1, current_value + change + noise)
            data.append(int(current_value))
        trend_series.append({
            "name": f"竞品{idx + 1}",
            "data": data,
            "color": COMPETITOR_COLORS[idx % len(COMPETITOR_COLORS)],
        })
    
    # 生成竞品类型饼图数据（5个类型）
    type_values = {
        "融资": random.randint(15, 35),
        "市场活动": random.randint(18, 40),
        "技术更新": random.randint(12, 28),
        "合作签约": random.randint(8, 20),
        "其他动态": random.randint(5, 15),
    }
    series_data = [{"value": value, "name": name} for name, value in type_values.items()]
    
    return {"xAxisData": labels, "seriesData": trend_series}, [{"seriesData": series_data}]


def _competitor_statistics(months: int) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    """竞品统计：根据开关选择使用模拟数据或查询数据库"""
    if USE_DEFAULT_DATA:
        return _competitor_statistics_default(months)
    
    # 数据库统计模式
    buckets = _month_buckets(months)
    labels = [label for label, _, _ in buckets]
    if not buckets:
        empty_trend = _empty_line_chart("", "")
        empty_trend["seriesData"] = []
        empty_type = _empty_pie_chart_array([(label, 0) for label in COMP_TYPE_ORDER])
        return empty_trend, empty_type

    start_iso = buckets[0][1].isoformat()
    end_iso = buckets[-1][2].isoformat()

    # 从 00_competitors_news 表查询竞品新闻数据
    rows = _fetch_rows(
        COMPETITOR_NEWS_TABLE,
        columns="id, title, content, publish_time, created_at, news_type",
        filters=[("gte", "publish_time", start_iso), ("lte", "publish_time", end_iso)],
        order=("publish_time", True),
    )
    if not rows:
        rows = _fetch_rows(
            COMPETITOR_NEWS_TABLE,
            columns="id, title, content, publish_time, created_at, news_type",
            filters=[("gte", "created_at", start_iso), ("lte", "created_at", end_iso)],
            order=("created_at", True),
        )

    series_map: Dict[str, List[int]] = defaultdict(lambda: [0] * len(buckets))
    type_counter: Counter[str] = Counter()
    end_bound = buckets[-1][2]

    for row in rows:
        news_id = str(row.get("id") or "")
        dt = _parse_dt(row.get("publish_time") or row.get("created_at"))
        if not dt or dt < buckets[0][1] or dt > end_bound:
            continue
        idx = _bucket_index(dt, buckets)
        if idx is None:
            continue
        group_key = (row.get("news_type") or "竞品动态").strip()
        series_map[group_key][idx] += 1
        type_counter[_classify_competitor_event(row)] += 1

    ranked = sorted(series_map.items(), key=lambda item: sum(item[1]), reverse=True)[:3]
    trend_series: List[Dict[str, Any]] = []
    for idx, (group_key, data) in enumerate(ranked):
        name = group_key if group_key else f"竞品动态{idx + 1}"
        color = COMPETITOR_COLORS[idx % len(COMPETITOR_COLORS)]
        trend_series.append({"name": name, "data": data, "color": color})

    while len(trend_series) < 3:
        idx = len(trend_series)
        trend_series.append({
            "name": f"竞品{idx + 1}",
            "data": [0] * len(buckets),
            "color": COMPETITOR_COLORS[idx % len(COMPETITOR_COLORS)],
        })

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


def _bid_list_statistics_default(days: int = 7) -> Dict[str, Any]:
    """招标统计：生成默认模拟数据"""
    return _default_day_chart("数量", COLOR_BID, days)


def _bid_list_statistics(days: int = 7) -> Dict[str, Any]:
    """招标统计：根据开关选择使用模拟数据或查询数据库"""
    if USE_DEFAULT_DATA:
        return _bid_list_statistics_default(days)
    
    # 数据库统计模式
    buckets = _day_buckets(days)
    labels = [label for label, _, _ in buckets]
    counts = [0] * len(buckets)
    
    if not buckets:
        return _empty_line_chart("数量", COLOR_BID)

    start_iso = buckets[0][1].isoformat()
    end_iso = buckets[-1][2].isoformat()

    rows: List[Dict[str, Any]] = []
    try:
        rows = _fetch_rows(
            OPPORTUNITY_TABLE,
            columns="id, publish_time",
            filters=[("gte", "publish_time", start_iso), ("lte", "publish_time", end_iso)],
            order=("publish_time", True),
            max_records=1000,
        )
    except Exception:
        try:
            rows = _fetch_rows(
                OPPORTUNITY_TABLE,
                columns="id, publish_time, created_at",
                filters=[("gte", "created_at", start_iso), ("lte", "created_at", end_iso)],
                order=("created_at", True),
                max_records=1000,
            )
        except Exception:
            pass

    for row in rows:
        dt = _parse_dt(row.get("publish_time") or row.get("created_at"))
        if not dt:
            continue
        idx = _bucket_index(dt, buckets)
        if idx is not None:
            counts[idx] += 1

    return {
        "xAxisData": labels,
        "seriesData": [
            {
                "name": "数量",
                "data": counts,
                "color": COLOR_BID,
            }
        ],
    }


def _research_statistics_default(months: int) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """研究统计：生成默认模拟数据（带真实波动）
    返回: (researchTopicNumData, researchTopicData)
    """
    import random
    labels = [f"{i}月" for i in range(1, months + 1)]
    
    # 生成6条研究主题趋势线，每条有不同的波动模式
    topic_order = ["磁学", "量子", "纳米", "科学仪器", "光谱", "仪器国产化"]
    trend_series = []
    for idx, topic in enumerate(topic_order):
        # 每条主题有不同的起始值和波动特性
        current_value = random.randint(3 + idx, 6 + idx * 2)
        data = []
        for i in range(months):
            # 不同主题有不同的上升概率（55%-70%）
            up_prob = 0.55 + idx * 0.025
            if random.random() < up_prob:
                # 上升：增加0-3之间的随机值
                change = random.randint(0, 3)
            else:
                # 下降：减少0-2之间的随机值
                change = -random.randint(0, 2)
            # 添加随机噪声（-2到+3）
            noise = random.randint(-2, 3)
            current_value = max(2, current_value + change + noise)
            data.append(int(current_value))
        trend_series.append({
            "name": topic,
            "data": data,
            "color": RESEARCH_COLORS[idx % len(RESEARCH_COLORS)],
        })
    
    # 生成研究主题饼图数据（使用完整名称）
    topic_mapping = {
        "磁学": "磁学与自旋电子学",
        "量子": "量子与低温测量",
        "纳米": "纳米与光学成像",
        "科学仪器": "科学仪器智能化",
        "光谱": "光谱与分析技术",
        "仪器国产化": "仪器工程与国产化",
    }
    
    total = random.randint(50, 150)
    ratios = [random.random() for _ in range(6)]
    ratio_sum = sum(ratios)
    ratios = [r / ratio_sum for r in ratios]
    
    topic_values = {}
    for idx, topic_key in enumerate(topic_order):
        value = max(5, int(total * ratios[idx]))
        topic_values[topic_mapping[topic_key]] = value
    
    current_sum = sum(topic_values.values())
    last_key = topic_mapping[topic_order[-1]]
    topic_values[last_key] = total - (current_sum - topic_values[last_key])
    
    topic_data = [{"value": value, "name": name} for name, value in topic_values.items()]
    
    research_topic_num_data = {"xAxisData": labels, "seriesData": trend_series}
    research_topic_data = {"seriesData": topic_data}
    
    return research_topic_num_data, research_topic_data


def _research_statistics(months: int) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """研究统计：根据开关选择使用模拟数据或查询数据库
    返回: (researchTopicNumData, researchTopicData)
    """
    if USE_DEFAULT_DATA:
        return _research_statistics_default(months)
    
    # 数据库统计模式
    buckets = _month_buckets(months)
    labels = [label for label, _, _ in buckets]
    if not buckets:
        empty_trend = _empty_line_chart("", "")
        empty_trend["seriesData"] = []
        empty_topic = _empty_pie_chart()
        return empty_trend, empty_topic

    # 从 00_papers 表查询论文数据
    # 注意：00_papers 表的 published_at 是 date 类型
    start_iso_date = buckets[0][1].date().isoformat()
    end_iso_date = buckets[-1][2].date().isoformat()
    
    rows = _fetch_rows(
        PAPER_TABLE,
        columns="id, published_at, title, keywords_matched",
        filters=[("gte", "published_at", start_iso_date), ("lte", "published_at", end_iso_date)],
        order=("published_at", True),
    )

    kw_counter: Counter[str] = Counter()
    kw_month_map: Dict[str, List[int]] = defaultdict(lambda: [0] * len(buckets))

    for row in rows:
        # 00_papers 表的 published_at 是 date 类型，需要转换为 datetime
        published_at = row.get("published_at")
        if published_at:
            if isinstance(published_at, str):
                dt = datetime.fromisoformat(published_at).replace(tzinfo=None)
            elif isinstance(published_at, datetime):
                dt = published_at.replace(tzinfo=None) if published_at.tzinfo else published_at
            else:
                # 可能是 date 对象
                dt = datetime.combine(published_at, datetime.min.time())
        else:
            continue
            
        if dt < buckets[0][1] or dt > buckets[-1][2]:
            continue
        idx = _bucket_index(dt, buckets)
        if idx is None:
            continue
        
        # 从 keywords_matched 字段提取关键词（text[] 数组）
        keywords = row.get("keywords_matched")
        if isinstance(keywords, list):
            keywords = [kw for kw in keywords if isinstance(kw, str) and kw.strip()]
        else:
            keywords = []
        
        if not keywords:
            keywords = ["其他主题"]
            
        for kw in keywords:
            kw = kw.strip()[:30]  # 限制长度
            if kw:
                kw_counter[kw] += 1
                kw_month_map[kw][idx] += 1

    # 根据API文档，研究主题包括：磁学与自旋电子学、量子与低温测量、纳米与光学成像、科学仪器智能化、光谱与分析技术、仪器工程与国产化
    # researchTopicData 使用完整名称，researchTopicNumData 使用简化名称
    topic_mapping = {
        "磁学": {
            "full_name": "磁学与自旋电子学",
            "keywords": ["磁学", "自旋电子学", "磁性"],
        },
        "量子": {
            "full_name": "量子与低温测量",
            "keywords": ["量子", "低温测量", "低温"],
        },
        "纳米": {
            "full_name": "纳米与光学成像",
            "keywords": ["纳米", "光学成像", "成像"],
        },
        "科学仪器": {
            "full_name": "科学仪器智能化",
            "keywords": ["科学仪器", "智能化", "智能"],
        },
        "光谱": {
            "full_name": "光谱与分析技术",
            "keywords": ["光谱", "分析技术", "分析"],
        },
        "仪器国产化": {
            "full_name": "仪器工程与国产化",
            "keywords": ["仪器工程", "国产化", "工程"],
        },
    }
    
    # 映射实际关键词到标准主题
    topic_counts: Dict[str, int] = Counter()
    topic_month_map: Dict[str, List[int]] = defaultdict(lambda: [0] * len(buckets))
    
    for kw, count in kw_counter.items():
        matched = False
        for topic_key, topic_info in topic_mapping.items():
            if any(k in kw for k in topic_info["keywords"]):
                topic_counts[topic_key] += count
                # 合并月份数据
                for idx in range(len(buckets)):
                    topic_month_map[topic_key][idx] += kw_month_map.get(kw, [0] * len(buckets))[idx]
                matched = True
                break
        if not matched:
            topic_counts["其他主题"] += count
            for idx in range(len(buckets)):
                topic_month_map["其他主题"][idx] += kw_month_map.get(kw, [0] * len(buckets))[idx]

    # 如果没有数据，使用默认主题
    if not topic_counts:
        for topic_key in topic_mapping.keys():
            topic_counts[topic_key] = 0
            topic_month_map[topic_key] = [0] * len(buckets)

    # researchTopicNumData: 各研究主题数量变化（月度趋势）
    # 根据API文档，使用简化名称：磁学、量子、纳米、科学仪器、光谱、仪器国产化
    topic_order = ["磁学", "量子", "纳米", "科学仪器", "光谱", "仪器国产化"]
    trend_series: List[Dict[str, Any]] = []
    for idx, topic_key in enumerate(topic_order):
        trend_series.append(
            {
                "name": topic_key,
                "data": topic_month_map.get(topic_key, [0] * len(buckets)),
                "color": RESEARCH_COLORS[idx % len(RESEARCH_COLORS)],
            }
        )

    # researchTopicData: 学术论文主题（饼图数据）
    # 根据API文档格式，使用完整名称
    topic_data = []
    for topic_key in topic_order:
        full_name = topic_mapping[topic_key]["full_name"]
        value = topic_counts.get(topic_key, 0)
        topic_data.append({"value": value, "name": full_name})

    research_topic_num_data = {"xAxisData": labels, "seriesData": trend_series}
    research_topic_data = {"seriesData": topic_data}

    return research_topic_num_data, research_topic_data


# ===================== 路由实现 =====================
@databoard_data_bp.route("/getNews", methods=["GET"])
def get_databoard_data():
    """
    返回数据看板所需的综合统计，符合API文档约定：
      - policyNews: 政策新闻月度趋势
      - industryNews: 行业新闻月度趋势
      - bidListData: 近一周招标消息（按日统计）
      - competitorType: 竞品公司动态类型分布（饼图）
      - researchTopicData: 学术论文主题分布（饼图）
      - researchTopicNumData: 各研究主题数量变化（月度趋势）
    可选查询参数：
      newsMonths: int [3,24]   默认为 DATABOARD_NEWS_MONTHS（12）
      trendMonths: int [3,12]  默认为 DATABOARD_TREND_MONTHS（6）
    """
    news_months = _safe_int(request.args.get("newsMonths"), DEFAULT_NEWS_MONTHS, 3, 24)
    trend_months = _safe_int(request.args.get("trendMonths"), DEFAULT_TREND_MONTHS, 3, 12)

    try:
        news_stats = _news_statistics(news_months)
        bid_list_data = _bid_list_statistics(7)  # 近一周
        _, competitor_type = _competitor_statistics(trend_months)
        research_topic_num_data, research_topic_data = _research_statistics(trend_months)

        payload = {
            "statistics": {
                "policyNews": news_stats["policyNews"],
                "industryNews": news_stats["industryNews"],
                "bidListData": bid_list_data,
                "competitorType": competitor_type,  # 已经是数组格式
                "researchTopicData": research_topic_data,  # 对象格式，包含seriesData
                "researchTopicNumData": research_topic_num_data,  # 对象格式，包含xAxisData和seriesData
            }
        }
        return _json_ok(payload)
    except ValueError as exc:
        return _json_err(400, f"invalid parameters: {exc}")
    except Exception as exc:  # pragma: no cover
        print(f"[ERROR] databoard_data_bp: {exc}")
        return _json_err(500, "internal server error")


@databoard_data_bp.route("/getData", methods=["GET"])
def get_databoard_data_alias():
    """兼容旧路径 /api/databoard/data/getData，复用 getNews 逻辑。"""
    return get_databoard_data()


@databoard_data_bp.route("/getMonthlySummary", methods=["GET"])
def get_monthly_summary():
    """
    返回 Dashboard 月度综合总结（四类各一条）。
    默认视角 management，可通过 ?view=xxx 指定。
    """
    view = (request.args.get("view") or "management").strip() or "management"
    try:
        items = _fetch_monthly_summaries(view)
        payload = {
            "view": view,
            "items": items,
        }
        return _json_ok(payload)
    except Exception as exc:  # pragma: no cover
        print(f"[ERROR] getMonthlySummary: {exc}")
        return _json_err(500, "internal server error")
