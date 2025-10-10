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
from datetime import datetime, timezone, date
from typing import List, Dict, Any, Optional

from flask import Blueprint, request, make_response
from dateutil import parser as dateparser
from supabase import create_client

# ========= 常量 & 配置 =========
ALLOWED_VIEWS = {"management", "market", "sales", "product"}
DEFAULT_VIEW = os.getenv("DAILY_REPORT_DEFAULT_VIEW", "management")
INTERNAL_DEFAULT_LIMIT = int(os.getenv("DAILY_REPORT_MAX", "8"))   # 仅用于截取，不回传
HARD_FETCH_LIMIT = 200  # 预留大一点的抓取量，便于去重后再排序截取

SUPABASE_URL = os.getenv("SUPABASE_URL", "https://zlajhzeylrzfbchycqyy.supabase.co")
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_KEY", "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InpsYWpoemV5bHJ6ZmJjaHljcXl5Iiwicm9sZSI6InNlcnZpY2Vfcm9sZSIsImlhdCI6MTc1NTYwMTIwMiwiZXhwIjoyMDcxMTc3MjAyfQ.u6vYYEL3qCh4lJU62wEmT4UJTZrstX-_yscRPXrZH7s")

if not SUPABASE_URL or not SUPABASE_KEY:
    raise RuntimeError("Missing SUPABASE_URL or SUPABASE_SERVICE_KEY")

TABLE_DASHBOARD = "dashboard_daily_reports"

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

def pick_anchor_date(date_param: Optional[str]) -> Optional[date]:
    """
    锚定日期：
      1) 优先用用户传入 YYYY-MM-DD/ISO；
      2) 否则取 dashboard_daily_reports 最新的 report_date。
    """
    if date_param:
        try:
            return dateparser.isoparse(date_param).date()
        except Exception:
            try:
                return datetime.fromisoformat(date_param[:10]).date()
            except Exception:
                pass

    res = (
        sb.table(TABLE_DASHBOARD)
        .select("report_date")
        .order("report_date", desc=True)
        .limit(1)
        .execute()
    )
    rows = res.data or []
    if not rows:
        return None
    rd = rows[0].get("report_date")
    try:
        return dateparser.isoparse(rd).date()
    except Exception:
        return datetime.fromisoformat(str(rd)[:10]).date()

def cn_priority(priority_value: str) -> Dict[str, str]:
    """将 priority 映射为前端所需字段"""
    lvl = (priority_value or "").lower()
    if "high" in lvl:
        return {"priority": "high", "priorityText": "高"}
    if "medium" in lvl:
        return {"priority": "medium", "priorityText": "中"}
    return {"priority": "low", "priorityText": "低"}

def suggest_action_by_priority(priority_value: str, comp_name: str) -> str:
    """与同事版的建议口吻保持一致，只是依据 priority 来判断"""
    lvl = (priority_value or "").lower()
    if "high" in lvl:
        return f"建议：对「{comp_name}」建立专项跟踪，48小时内复核技术/报价与现有项目的冲突与机会点，准备应对话术与客户沟通材料。"
    if "medium" in lvl:
        return f"建议：两周内复盘「{comp_name}」相关产品卖点与我方差异化，必要时更新竞对资料。"
    return f"建议：纳入例行监测清单，月度回顾。"

def map_category_by_view(view: str) -> str:
    """严格按同事版：只由 view 决定，不读取行内 category"""
    mapping = {
        "management": "竞品动态",
        "market": "竞品动态",
        "sales": "销售机会",
        "product": "产品动向"
    }
    return mapping.get(view, "竞品动态")

def extract_summary(payload: Any, fallback_text: str = "") -> str:
    """
    从 payload(json) 提取摘要内容。
    支持的键：summary, summary_report, brief, abstract, content
    若均不存在，则回退到 website_content 截断或 fallback 文本。
    """
    if isinstance(payload, dict):
        for k in ("summary", "summary_report", "brief", "abstract", "content"):
            v = payload.get(k)
            if isinstance(v, str) and v.strip():
                return v.strip()
        v = payload.get("website_content")
        if isinstance(v, str) and v.strip():
            s = v.strip()
            return s[:140] + ("..." if len(s) > 140 else "")
    if isinstance(fallback_text, str) and fallback_text.strip():
        return fallback_text.strip()
    return ""

def priority_rank(v: str) -> int:
    """排序用：high(0) < medium(1) < other(2)"""
    x = (v or "").lower()
    if "high" in x: return 0
    if "medium" in x: return 1
    return 2

# 新增：轻改版综合评分，仅用于排序
def score_report(r: Dict[str, Any]) -> float:
    """
    轻改版综合评分（仅用于排序，不改变返回格式）：
      - 优先级：high&gt;medium&gt;low
      - 摘要质量：摘要越长越好（上限加分）
      - 命名质量：有明确竞品名加分
      - 时效性：当天内创建时间越新越好（小权重）
    """
    # priority
    pr = (r.get("priority") or "").lower()
    if "high" in pr:
        pr_score = 3.0
    elif "medium" in pr:
        pr_score = 2.0
    else:
        pr_score = 1.0

    # summary quality
    payload = r.get("payload") or {}
    summary = extract_summary(payload, "")
    sum_len = len(summary)
    # 每 80 字加 1 分，最多 3 分
    sum_score = min(sum_len / 80.0, 3.0)

    # name quality
    comp_from_payload = payload.get("competitor_name") if isinstance(payload, dict) else None
    comp_fallback = r.get("competitor_name")
    comp_name = (comp_from_payload or comp_fallback or "").strip()
    name_score = 0.5 if comp_name and comp_name != "未命名竞品" else 0.0

    # freshness（更“新”的分更高，权重较小）
    ts_raw = r.get("created_ts") or r.get("processed_at") or r.get("created_at") or ""
    try:
        ts = dateparser.isoparse(ts_raw)
    except Exception:
        ts = None
    fresh_score = 0.0
    if ts:
        # 以小时为粒度，越新越高，但最高 1.0 分
        now_utc = datetime.now(timezone.utc)
        age_hours = max(0.0, (now_utc - ts.astimezone(timezone.utc)).total_seconds() / 3600.0)
        if age_hours <= 6:
            fresh_score = 1.0
        elif age_hours <= 24:
            fresh_score = 0.6
        else:
            fresh_score = 0.2

    # 总分
    return pr_score * 1.0 + sum_score * 1.0 + name_score * 1.0 + fresh_score * 0.5

# ========= API =========
@daily_report_bp.route("/daily-report", methods=["GET"])
def get_daily_report():
    """
    入参: date(可选), view(可选: management/market/sales/product), limit/offset(可选，仅用于截取，不回传)
    出参: 与同事版结构完全一致
    """
    view = (request.args.get("view") or CURRENT_VIEW["view"]).strip()
    if view not in ALLOWED_VIEWS:
        view = DEFAULT_VIEW

    date_param = request.args.get("date")
    # 仅用于内部截取，响应中不回传
    try:
        limit = int(request.args.get("limit", INTERNAL_DEFAULT_LIMIT))
    except Exception:
        limit = INTERNAL_DEFAULT_LIMIT
    try:
        offset = int(request.args.get("offset", 0))
    except Exception:
        offset = 0
    limit = max(0, min(limit, HARD_FETCH_LIMIT))
    offset = max(0, offset)

    anchor = pick_anchor_date(date_param)

    if not anchor:
        response_data = {
            "code": 200,
            "message": "success",
            "data": {"date": None, "view": view, "highlights": []}
        }
        response = make_response(json.dumps(response_data, ensure_ascii=False, indent=2))
        response.status_code = 200
        response.mimetype = 'application/json; charset=utf-8'
        return response

    # === 新逻辑：从 dashboard_daily_reports 读取 ===
    # 精确匹配当天（如你的列为 timestamptz，请改为 gte/lte 当天边界）
    q = (
        sb.table(TABLE_DASHBOARD)
        .select("*")
        .eq("report_date", anchor.isoformat())
        .eq("view", view)
        .order("created_ts", desc=True)  # 先按时间粗排，后面在 Python 层综合 priority 排
        .limit(HARD_FETCH_LIMIT)
    )
    res = q.execute()
    rows = res.data or []

    if not rows:
        response_data = {
            "code": 200,
            "message": "success",
            "data": {"date": anchor.isoformat(), "view": view, "highlights": []}
        }
        response = make_response(json.dumps(response_data, ensure_ascii=False, indent=2))
        response.status_code = 200
        response.mimetype = 'application/json; charset=utf-8'
        return response

    # 去重（按 content_hash > analysis_id > id）
    seen = set()
    deduped: List[Dict[str, Any]] = []
    for r in rows:
        key = r.get("content_hash") or r.get("analysis_id") or r.get("id")
        if key and key in seen:
            continue
        if key:
            seen.add(key)
        deduped.append(r)

    # 轻改版：综合评分排序（不改变返回格式）
    ordered = sorted(deduped, key=score_report, reverse=True)
    window = ordered[offset: offset + limit] if limit > 0 else []

    # 组装 highlights（键名/行为与同事版一致）
    highlights: List[Dict[str, Any]] = []

    for idx, r in enumerate(window, start=1+offset):
        payload = r.get("payload") or {}
        comp_name = None
        if isinstance(payload, dict):
            # 兼容你当前 payload 结构：优先 competitor_name，其次 title
            comp_name = payload.get("competitor_name") or payload.get("title")
        if not comp_name:
            comp_name = r.get("competitor_name") or "未命名竞品"

        summary = extract_summary(payload, "")
        if not summary:
            summary = "（暂无摘要）"

        # 与同事版一致：content = "竞品名：摘要" + "。" + 建议
        pr_map = cn_priority(r.get("priority") or "")
        content = f"{comp_name}：{summary}".rstrip("。") + "。" + \
                  suggest_action_by_priority(r.get("priority") or "", comp_name)

        # createdAt：优先 created_ts / processed_at / created_at / 当前
        created_src = r.get("created_ts") or r.get("processed_at") or r.get("created_at")
        try:
            created_iso = to_iso_utc(dateparser.isoparse(created_src)) if created_src else to_iso_utc(datetime.now(timezone.utc))
        except Exception:
            created_iso = to_iso_utc(datetime.now(timezone.utc))

        # 分类：优先使用 payload.category；没有则按 view 映射
        cat_from_payload = None
        if isinstance(payload, dict):
            cat_from_payload = payload.get("category")
        final_category = cat_from_payload or map_category_by_view(view)

        highlights.append({
            "id": idx,                 # 与同事版一致：顺序号，而不是数据库主键
            "category": final_category,
            "content": content,
            **pr_map,                  # 展开 priority / priorityText
            "createdAt": created_iso
        })

    response_data = {
        "code": 200,
        "message": "success",
        "data": {
            "date": anchor.isoformat(),
            "view": view,
            "highlights": highlights
        }
    }
    response = make_response(json.dumps(response_data, ensure_ascii=False, indent=2))
    response.status_code = 200
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