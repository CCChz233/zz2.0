# -*- coding: utf-8 -*-
"""
每日AI简报 API Blueprint（整合版：新数据源 + 旧返回格式 + return response 风格）
依赖: pip install flask supabase python-dateutil

环境变量（必须配置，否则抛错）:
  SUPABASE_URL
  SUPABASE_SERVICE_KEY

数据源（视图/表）:
  - dashboard_daily_reports(
      id, report_date::date, view::text,
      competitor_name::text?, analysis_id, content_hash,
      payload::jsonb, priority::text, category::text?,
      created_ts::timestamptz, processed_at::timestamptz?, created_at::timestamptz?
    )
"""

import os
import json
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional, Tuple

from flask import Blueprint, request, make_response
from dateutil import parser as dateparser
from supabase import create_client

# ========= 常量 & 配置 =========
ALLOWED_VIEWS = {"management", "market", "sales", "product"}
DEFAULT_VIEW = os.getenv("DAILY_REPORT_DEFAULT_VIEW", "management")
MONTHLY_TABLE = "dashboard_daily_events"
MONTHLY_EVENT_TYPE = "monthly_summary"
MONTHLY_EVENT_ORDER = [
    ("monthly-行业新闻", "行业新闻"),
    ("monthly-竞品动态", "竞品动态"),
    ("monthly-销售机会", "销售机会"),
    ("monthly-科技论文", "科技论文"),
]

SUPABASE_URL = os.getenv("SUPABASE_URL", "https://zlajhzeylrzfbchycqyy.supabase.co")
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_KEY", "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InpsYWpoemV5bHJ6ZmJjaHljcXl5Iiwicm9sZSI6InNlcnZpY2Vfcm9sZSIsImlhdCI6MTc1NTYwMTIwMiwiZXhwIjoyMDcxMTc3MjAyfQ.u6vYYEL3qCh4lJU62wEmT4UJTZrstX-_yscRPXrZH7s")

if not SUPABASE_URL or not SUPABASE_KEY:
    raise RuntimeError("Missing SUPABASE_URL or SUPABASE_SERVICE_KEY")

# 为了保持与同事版行为一致，保留“内存视角”（生产建议改为无状态或落库/Redis）
CURRENT_VIEW = {"view": DEFAULT_VIEW}

# ========= 初始化 =========
daily_report_bp = Blueprint('daily_report', __name__)
sb = create_client(SUPABASE_URL, SUPABASE_KEY)

# ========= 工具函数 =========
def to_iso_utc(dt: datetime) -> str:
    """输出形如 2025-10-08T03:21:00Z"""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt.replace(microsecond=0).isoformat().replace("+00:00", "Z")

def cn_priority(priority_value: str) -> Dict[str, str]:
    """将 priority 映射为前端所需字段"""
    lvl = (priority_value or "").lower()
    if "high" in lvl:
        return {"priority": "high", "priorityText": "高"}
    if "medium" in lvl:
        return {"priority": "medium", "priorityText": "中"}
    return {"priority": "low", "priorityText": "低"}

def fetch_monthly_summaries(view: str) -> List[Dict[str, Any]]:
    """
    读取四个固定 event_id 的月度汇总。
    """
    try:
        res = (
            sb.table(MONTHLY_TABLE)
            .select("event_id,payload,priority,category,report_date,created_ts,processed_at")
            .eq("view", view)
            .eq("event_type", MONTHLY_EVENT_TYPE)
            .order("report_date", desc=True)
            .order("created_ts", desc=True)
            .limit(len(MONTHLY_EVENT_ORDER) * 4)
            .execute()
        )
        rows = res.data or []
    except Exception as exc:  # pragma: no cover
        print(f"[WARN] fetch monthly summaries failed: {exc}")
        rows = []

    latest: Dict[str, Dict[str, Any]] = {}
    for row in rows:
        event_id = row.get("event_id")
        if not event_id or event_id in latest:
            continue
        latest[event_id] = row

    items: List[Dict[str, Any]] = []
    for event_id, display_name in MONTHLY_EVENT_ORDER:
        row = latest.get(event_id, {})
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


def _to_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (list, tuple)):
        return "\n".join(str(item).strip() for item in value if item)
    return str(value)


def build_highlights_from_monthly(items: List[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], Optional[str]]:
    highlights: List[Dict[str, Any]] = []
    report_date: Optional[str] = None

    for idx, item in enumerate(items, start=1):
        payload = item.get("payload") or {}
        title = _to_text(payload.get("title"))

        summary_lines: List[str] = []
        summary_raw = payload.get("summary_md") or payload.get("summary")
        if isinstance(summary_raw, list):
            summary_lines = [_to_text(line) for line in summary_raw if line]
        else:
            summary_text = _to_text(summary_raw)
            if summary_text:
                summary_lines = [summary_text]

        outlook = _to_text(payload.get("outlook"))

        rec_lines: List[str] = []
        rec_raw = payload.get("recommendations")
        if isinstance(rec_raw, list):
            rec_lines = [_to_text(line) for line in rec_raw if line]
        else:
            rec_text = _to_text(rec_raw)
            if rec_text:
                rec_lines = [rec_text]

        sources = payload.get("sources")
        if not isinstance(sources, list):
            sources = []

        content_parts: List[str] = []
        if title:
            content_parts.append(title)
        if summary_lines:
            bullets = "\n".join(f"- {line}" for line in summary_lines if line)
            if bullets:
                content_parts.append(bullets)
        if outlook:
            content_parts.append(f"展望：{outlook}")
        if rec_lines:
            actions = "\n".join(f"- {line}" for line in rec_lines if line)
            if actions:
                content_parts.append(f"行动建议：\n{actions}")

        content = "\n\n".join(part for part in content_parts if part).strip() or "(暂无内容)"

        pr_map = cn_priority(item.get("priority", "medium"))

        created_src = item.get("createdTs") or ""
        created_iso: str
        try:
            if created_src:
                created_iso = to_iso_utc(dateparser.isoparse(created_src))
            else:
                created_iso = to_iso_utc(datetime.now(timezone.utc))
        except Exception:
            created_iso = to_iso_utc(datetime.now(timezone.utc))

        highlights.append(
            {
                "id": idx,
                "category": item.get("displayName") or item.get("category") or "综合汇总",
                "content": content,
                "title": title,
                "summaryLines": summary_lines,
                "recommendationLines": rec_lines,
                "outlook": outlook,
                "tags": payload.get("tags") if isinstance(payload.get("tags"), list) else [],
                "sources": sources,
                **pr_map,
                "createdAt": created_iso,
            }
        )

        if not report_date and item.get("reportDate"):
            report_date = str(item.get("reportDate"))

    return highlights, report_date

# ========= API =========
@daily_report_bp.route("/daily-report", methods=["GET"])
def get_daily_report():
    """
    入参: view(可选: management/market/sales/product)
    出参: 固定四条月度汇总摘要
    """
    view = (request.args.get("view") or CURRENT_VIEW["view"]).strip()
    if view not in ALLOWED_VIEWS:
        view = DEFAULT_VIEW

    items = fetch_monthly_summaries(view)
    highlights, report_date = build_highlights_from_monthly(items)

    response_data = {
        "code": 200,
        "message": "success",
        "data": {
            "date": report_date,
            "view": view,
            "highlights": highlights
        }
    }
    response = make_response(json.dumps(response_data, ensure_ascii=False, indent=2))
    response.status_code = 200
    response.mimetype = 'application/json; charset=utf-8'
    return response


@daily_report_bp.route("/daily-report/monthly", methods=["GET"])
def get_monthly_report():
    """
    返回按类别合并的大模型月度汇总（四条）。
    """
    view = (request.args.get("view") or CURRENT_VIEW["view"]).strip()
    if view not in ALLOWED_VIEWS:
        view = DEFAULT_VIEW

    try:
        items = fetch_monthly_summaries(view)
        response_payload = {
            "code": 200,
            "message": "success",
            "data": {
                "view": view,
                "items": items,
            },
        }
        response = make_response(json.dumps(response_payload, ensure_ascii=False, indent=2))
        response.status_code = 200
        response.mimetype = 'application/json; charset=utf-8'
        return response
    except Exception as exc:  # pragma: no cover
        print(f"[ERROR] get_monthly_report: {exc}")
        error_payload = {"code": 500, "message": "internal server error", "data": {}}
        response = make_response(json.dumps(error_payload, ensure_ascii=False, indent=2))
        response.status_code = 500
        response.mimetype = 'application/json; charset=utf-8'
        return response

@daily_report_bp.route("/daily-report/view", methods=["PUT"])
def update_daily_report_view():
    """
    与同事版一致：仅更新后端当前默认视角（内存）。
    """
    body = request.get_json(silent=True) or {}
    v = (body.get("view") or "").strip()
    if v not in ALLOWED_VIEWS:
        error_data = {"code": 400, "message": "invalid view", "data": {}}
        response = make_response(json.dumps(error_data, ensure_ascii=False, indent=2))
        response.status_code = 400
        response.mimetype = 'application/json; charset=utf-8'
        return response

    CURRENT_VIEW["view"] = v
    now_iso = to_iso_utc(datetime.now(timezone.utc))
    response_data = {"code": 200, "message": "success", "data": {"view": v, "updatedAt": now_iso}}
    response = make_response(json.dumps(response_data, ensure_ascii=False, indent=2))
    response.status_code = 200
    response.mimetype = 'application/json; charset=utf-8'
    return response

# 移除独立运行代码，现在作为 Blueprint 使用