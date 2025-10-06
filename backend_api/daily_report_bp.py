# -*- coding: utf-8 -*-
"""
每日AI简报 API Blueprint
依赖: pip install flask supabase python-dateutil

环境变量（如未配置，可按默认写死）:
  SUPABASE_URL
  SUPABASE_SERVICE_KEY
表:
  - analysis_results(id, competitor_id, analysis_date, threat_level, summary_report, created_at, detected_changes, website_content, raw_data)
  - competitors(id, name, website, product, last_analyzed, created_at)
"""

import os
import json
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional

from flask import Blueprint, request, jsonify, make_response
from dateutil import parser as dateparser
from supabase import create_client

# ==== 配置 ====
SUPABASE_URL = os.getenv("SUPABASE_URL", "https://zlajhzeylrzfbchycqyy.supabase.co")
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_KEY", "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InpsYWpoemV5bHJ6ZmJjaHljcXl5Iiwicm9sZSI6InNlcnZpY2Vfcm9sZSIsImlhdCI6MTc1NTYwMTIwMiwiZXhwIjoyMDcxMTc3MjAyfQ.u6vYYEL3qCh4lJU62wEmT4UJTZrstX-_yscRPXrZH7s")
ANALYSIS_TABLE = "analysis_results"
COMP_TABLE = "competitors"

# 视角配置（简单持久在内存；若需跨进程持久化可落表/Redis）
CURRENT_VIEW = {"view": "management"}

# ==== 初始化 ====
daily_report_bp = Blueprint('daily_report', __name__)
sb = create_client(SUPABASE_URL, SUPABASE_KEY)

# ==== 工具 ====
def to_iso_utc(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt.replace(microsecond=0).isoformat().replace("+00:00", "Z")

def parse_date_only(s: Optional[str]) -> Optional[str]:
    if not s:
        return None
    try:
        dt = dateparser.isoparse(s)
        return dt.date().isoformat()
    except Exception:
        try:
            if len(s) >= 10:
                return s[:10]
        except Exception:
            pass
        return None

def cn_priority(threat_level: str) -> Dict[str, str]:
    # 将analysis_results.threat_level(low/medium/high等)映射到前端priority
    lvl = (threat_level or "").lower()
    if "high" in lvl:
        return {"priority": "high", "priorityText": "高"}
    if "medium" in lvl:
        return {"priority": "medium", "priorityText": "中"}
    return {"priority": "low", "priorityText": "低"}

def suggest_action(threat_level: str, comp_name: str) -> str:
    lvl = (threat_level or "").lower()
    if "high" in lvl:
        return f"建议：对「{comp_name}」建立专项跟踪，48小时内复核技术/报价与现有项目的冲突与机会点，准备应对话术与客户沟通材料。"
    if "medium" in lvl:
        return f"建议：两周内复盘「{comp_name}」相关产品卖点与我方差异化，必要时更新竞对资料。"
    return f"建议：纳入例行监测清单，月度回顾。"

def pick_anchor_date(date_param: Optional[str]) -> Optional[datetime]:
    """优先使用用户给的date；否则取 analysis_results 最新的 analysis_date(日期部分)"""
    if date_param:
        try:
            return dateparser.isoparse(date_param).date()
        except Exception:
            try:
                return datetime.fromisoformat(date_param[:10]).date()
            except Exception:
                pass
    # 查 analysis_results 最新一条
    res = (
        sb.table(ANALYSIS_TABLE)
        .select("analysis_date")
        .order("analysis_date", desc=True)
        .limit(1)
        .execute()
    )
    rows = res.data or []
    if not rows:
        return None
    # Supabase返回可能是字符串/ISO
    ad = rows[0]["analysis_date"]
    try:
        return dateparser.isoparse(ad).date()
    except Exception:
        return datetime.fromisoformat(ad[:10]).date()

def load_analysis_for_date(anchor_date) -> List[Dict[str, Any]]:
    """取 anchor_date 当天的分析；若当天无数据，则回退到最近一天有数据的记录"""
    # 先尝试当天
    q = (
        sb.table(ANALYSIS_TABLE)
        .select("*")
        .gte("analysis_date", f"{anchor_date}T00:00:00Z")
        .lte("analysis_date", f"{anchor_date}T23:59:59Z")
        .order("analysis_date", desc=True)
        .limit(50)
    )
    res = q.execute()
    data = res.data or []

    if not data:
        # 回退：直接取最新一批
        res = (
            sb.table(ANALYSIS_TABLE)
            .select("*")
            .order("analysis_date", desc=True)
            .limit(50)
            .execute()
        )
        data = res.data or []
    return data

def map_category_by_view(view: str) -> str:
    # 你可以按需要区分：management/market/sales/product
    # 目前主要来自竞品情报 -> “竞品动态”
    mapping = {
        "management": "竞品动态",
        "market": "竞品动态",
        "sales": "销售机会",   # 如后续有检测到招标/价格/活动可填充
        "product": "产品动向"
    }
    return mapping.get(view, "竞品动态")

# ==== API ====
@daily_report_bp.route("/daily-report", methods=["GET"])
def get_daily_report():
    """
    入参: date(可选), view(可选: management/market/sales/product)
    出参: 符合你们约定的 highlights 列表
    """
    view = (request.args.get("view") or CURRENT_VIEW["view"]).strip()
    date_param = request.args.get("date")
    anchor = pick_anchor_date(date_param)

    if not anchor:
        response_data = {
            "code": 200,
            "message": "success",
            "data": {
                "date": None,
                "view": view,
                "highlights": []
            }
        }
        response = make_response(
            json.dumps(response_data, ensure_ascii=False, indent=2)
        )
        response.status_code = 200
        response.mimetype = 'application/json; charset=utf-8'
        return response

    # 拉取当天（或最近）的分析结果
    analysis_rows = load_analysis_for_date(anchor)
    if not analysis_rows:
        response_data = {
            "code": 200,
            "message": "success",
            "data": {
                "date": anchor.isoformat(),
                "view": view,
                "highlights": []
            }
        }
        response = make_response(
            json.dumps(response_data, ensure_ascii=False, indent=2)
        )
        response.status_code = 200
        response.mimetype = 'application/json; charset=utf-8'
        return response

    # 取涉及的竞品，做一次性映射
    comp_ids = list({r.get("competitor_id") for r in analysis_rows if r.get("competitor_id")})
    comp_map = {}
    if comp_ids:
        comp_res = (
            sb.table(COMP_TABLE)
            .select("id,name,product,website")
            .in_("id", comp_ids)
            .execute()
        )
        for cr in (comp_res.data or []):
            comp_map[cr["id"]] = cr

    # 组装 highlights
    highlights = []
    category = map_category_by_view(view)

    # 为了避免过多噪音，这里只取Top 8条，按 threat_level 高>中>低 再按 analysis_date 新>旧
    def sort_key(r):
        lvl = (r.get("threat_level") or "").lower()
        lvl_rank = 2
        if "high" in lvl:
            lvl_rank = 0
        elif "medium" in lvl:
            lvl_rank = 1
        ad = r.get("analysis_date") or r.get("created_at") or ""
        try:
            ts = dateparser.isoparse(ad)
        except Exception:
            ts = datetime.min.replace(tzinfo=timezone.utc)
        return (lvl_rank, -ts.timestamp())

    sorted_rows = sorted(analysis_rows, key=sort_key)[:8]

    for idx, r in enumerate(sorted_rows, start=1):
        comp = comp_map.get(r.get("competitor_id"), {})
        comp_name = comp.get("name") or "未命名竞品"
        pr = cn_priority(r.get("threat_level"))
        summary = (r.get("summary_report") or "").strip()
        if not summary:
            # 如果无结构化摘要，回退截取网页正文的一段
            summary = (r.get("website_content") or "").strip()[:140] + ("..." if (r.get("website_content") or "") else "")

        content = f"{comp_name}：{summary}"
        # 加一个自动化“行动建议”
        content = content.rstrip("。") + "。" + suggest_action(r.get("threat_level") or "", comp_name)

        # createdAt 使用 analysis_date 或 created_at
        created_iso = None
        if r.get("analysis_date"):
            created_iso = to_iso_utc(dateparser.isoparse(r["analysis_date"]))
        elif r.get("created_at"):
            created_iso = to_iso_utc(dateparser.isoparse(r["created_at"]))
        else:
            created_iso = to_iso_utc(datetime.now(timezone.utc))

        highlights.append({
            "id": idx,  # 若需稳定ID可用分析表主键hash
            "category": category,
            "content": content,
            **pr,
            "createdAt": created_iso
        })

    response_data = {
        "code": 200,
        "message": "success",
        "data": {
            "date": anchor.isoformat(),   # 采用锚定日期（当天或最近有数据日）
            "view": view,
            "highlights": highlights
        }
    }
    response = make_response(
        json.dumps(response_data, ensure_ascii=False, indent=2)
    )
    response.status_code = 200
    response.mimetype = 'application/json; charset=utf-8'
    return response

@daily_report_bp.route("/daily-report/view", methods=["PUT"])
def update_daily_report_view():
    """
    仅更新后端当前默认视角（内存）；如需跨实例共享，可写入配置表
    """
    body = request.get_json(silent=True) or {}
    v = (body.get("view") or "").strip()
    if v not in ("management", "market", "sales", "product"):
        error_data = {"code": 400, "message": "invalid view", "data": {}}
        response = make_response(
            json.dumps(error_data, ensure_ascii=False, indent=2)
        )
        response.status_code = 400
        response.mimetype = 'application/json; charset=utf-8'
        return response
    
    CURRENT_VIEW["view"] = v
    now_iso = to_iso_utc(datetime.now(timezone.utc))
    response_data = {
        "code": 200,
        "message": "success",
        "data": {"view": v, "updatedAt": now_iso}
    }
    response = make_response(
        json.dumps(response_data, ensure_ascii=False, indent=2)
    )
    response.status_code = 200
    response.mimetype = 'application/json; charset=utf-8'
    return response

# 移除独立运行代码，现在作为Blueprint使用
