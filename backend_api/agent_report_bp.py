# -*- coding: utf-8 -*-
"""
智能体初始报告 API Blueprint
----------------------------
接口：GET /api/agent/initial-report
说明：
    - 优先从 Supabase 视图/表拉取数据
    - 超时或数据缺失时降级为内置示例数据
    - 返回结构严格遵循 agent-report-api.md 约定
"""

import json
import os
import threading
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

import requests

from flask import Blueprint, make_response

from infra import llm
from infra.db import supabase

# ===== 配置 =====
AGENT_REPORT_SOURCE = os.getenv("AGENT_REPORT_SOURCE", "agent_initial_report_view")
AGENT_REPORT_LIMIT = int(os.getenv("AGENT_REPORT_LIMIT", "12"))
AGENT_REPORT_CACHE_TABLE = os.getenv("AGENT_REPORT_CACHE_TABLE", "agent_daily_report_cache")
AGENT_REPORT_SEARCH_DEPTH = os.getenv("AGENT_REPORT_SEARCH_DEPTH", "basic").strip() or "basic"
AGENT_REPORT_SEARCH_MAX_RESULTS = int(os.getenv("AGENT_REPORT_SEARCH_MAX_RESULTS", "6"))
AGENT_REPORT_SOURCE_LIMIT = int(os.getenv("AGENT_REPORT_SOURCE_LIMIT", "6"))
AGENT_REPORT_SUMMARY_MODEL = os.getenv("AGENT_REPORT_SUMMARY_MODEL") or None

REPORT_CACHE_LOCK = threading.Lock()
REPORT_CACHE_STATE: Dict[str, Any] = {"date": None, "payload": None}

SECTION_CONFIGS = [
    {
        "id": 1,
        "title": "政策解读",
        "heading": "最新政策动态",
        "icon": "el-icon-document-checked",
        "priority": 1,
        "query": "高端科学仪器 国产化 政策 动态 近期 规划 建议",
    },
    {
        "id": 2,
        "title": "论文报告",
        "heading": "前沿研究进展",
        "icon": "el-icon-reading",
        "priority": 2,
        "query": "原子力显微镜 磁性探针 纳米表征 最新研究 论文 进展",
    },
    {
        "id": 3,
        "title": "市场动态",
        "heading": "最新产业动态",
        "icon": "el-icon-data-line",
        "priority": 3,
        "query": "精密仪器 行业 动态 产业 合作 投资 近期",
    },
]

agent_report_bp = Blueprint("agent_report", __name__)
_supabase = supabase

# ===== 回退数据（与文档示例一致） =====
_FALLBACK_GENERATED_AT = "2023-11-15T10:30:00Z"
_FALLBACK_SECTIONS: List[Dict[str, Any]] = [
    {
        "id": 1,
        "title": "政策解读",
        "icon": "el-icon-document-checked",
        "content": (
            "## 最新政策动态\n\n"
            "**中央发布\"十五五\"规划建议，明确产业与科技发展重点**\n\n"
            "近日，党的二十届四中全会审议通过了《中共中央关于制定国民经济和社会发展第十五个五年规划的建议》，明确提出：\n\n"
            "* 推动**建设现代化产业体系**，巩固壮大实体经济根基\n"
            "* 加快实现**高水平科技自立自强**，突破关键核心技术\n"
            "* 全面推进**数字中国建设**，实施\"人工智能+\"行动\n\n"
            "### 核心要点\n\n"
            "1. **高端技术方向**：聚焦**集成电路、工业母机、高端仪器**等领域开展攻关\n"
            "2. **科技与产业融合**：支持企业牵头联合攻关，加强成果转化应用\n"
            "3. **数字基础能力**：强化**算力、算法、数据**等高效供给，全方位赋能千行百业\n\n"
            "> 📌 \"十五五\"规划建议对仪器装备、自主研发能力与智能技术提出系统部署，释放明确政策导向。"
        ),
        "priority": 1,
        "updatedAt": "2023-11-15T09:00:00Z",
    },
    {
        "id": 2,
        "title": "论文报告",
        "icon": "el-icon-reading",
        "content": (
            "## 前沿研究进展\n\n"
            "### Nanoscale 最新发表\n\n"
            "**Temperature-dependent sign reversal of tunneling magnetoresistance in van der Waals ferromagnetic heterojunctions**\n\n"
            "西安交通大学材料科学与工程学院自旋电子与量子系统研究中心团队于《Nanoscale》期刊发表研究成果，揭示磁隧道结中TMR信号随温度变化发生正负反转的物理机制：\n\n"
            "* 构建 CrVI₆ / Fe₃GeTe₂ 异质结构，观察到居里温度附近出现**TMR符号反转**\n"
            "* 实验验证**反铁磁耦合**是TMR反转的核心机制\n"
            "* 发现**温度+偏压联动调控下可实现多态TMR行为**\n\n"
            "### 实验支撑设备\n\n"
            "该研究依托**致真精密仪器 KMP-L 系统**完成关键测试：\n\n"
            "* 成功实现**低温强场微区磁畴成像**\n"
            "* 在50K下观察异质层呈现**相反磁衬度**\n"
            "* 系统提供空间分辨的MOKE测量，直接证实AFM耦合存在\n\n"
            "> 💡 KMP-L系统成为连接材料微观磁结构与器件宏观性能的重要纽带，显著支撑了该研究成果的验证过程。"
        ),
        "priority": 2,
        "updatedAt": "2023-11-15T08:30:00Z",
    },
    {
        "id": 3,
        "title": "市场动态",
        "icon": "el-icon-data-line",
        "content": (
            "## 最新产业动态\n\n"
            "**富睿思×天玑算共建原子力显微镜分析测试中心，落地成都**\n\n"
            "2025年9月25日，富睿思与天玑算在成都签署合作协议，联合设立**原子力显微镜（AFM）分析测试中心**，旨在推动高端精密检测资源更好服务科研与产业一线。\n\n"
            "### 核心要点\n\n"
            "1. **合作内容**：中心聚焦**形貌表征、物性分析、工业级检测校准**等核心方向\n"
            "2. **设备支撑**：富睿思提供**科研至计量级**全系列AFM产品，技术涵盖\"True3D扫描\"\"自动换针系统\"等\n"
            "3. **服务体系**：天玑算提供**实验检测、算力支持与定制化科研服务**，形成\"设备+服务\"一体化解决方案\n\n"
            "> 📌 此次合作为高端检测设备在科研与工程领域的深入应用搭建新平台，助力资源整合与能力提升。"
        ),
        "priority": 3,
        "updatedAt": "2023-11-15T07:00:00Z",
    },
]


def _to_iso(value: Optional[Any]) -> Optional[str]:
    """将 str/datetime 转成 ISO8601 UTC（无微秒）；其余类型返回 None。"""
    if value is None:
        return None
    if isinstance(value, datetime):
        dt = value.astimezone(timezone.utc) if value.tzinfo else value.replace(tzinfo=timezone.utc)
        return dt.replace(microsecond=0).isoformat().replace("+00:00", "Z")
    if isinstance(value, str):
        txt = value.strip()
        if not txt:
            return None
        try:
            if txt.endswith("Z"):
                txt = txt.replace("Z", "+00:00")
            dt = datetime.fromisoformat(txt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            else:
                dt = dt.astimezone(timezone.utc)
            return dt.replace(microsecond=0).isoformat().replace("+00:00", "Z")
        except Exception:
            return value
    return None


def _get_tavily_key() -> str:
    return os.getenv("TAVILY_API_KEY", "").strip()


def _today_key() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def _fetch_cached_report(date_key: str) -> Optional[Tuple[str, List[Dict[str, Any]]]]:
    if not _supabase:
        return None
    try:
        res = (
            _supabase.table(AGENT_REPORT_CACHE_TABLE)
            .select("generated_at, sections, source, updated_at")
            .eq("cache_date", date_key)
            .order("updated_at", desc=True)
            .limit(1)
            .execute()
        )
        rows = res.data or []
        if not rows:
            return None
        row = rows[0]
        sections = row.get("sections")
        if not isinstance(sections, list):
            return None
        generated_at = row.get("generated_at") or row.get("updated_at") or _FALLBACK_GENERATED_AT
        return generated_at, sections
    except Exception as exc:
        print(f"⚠️ 读取日报缓存失败: {exc}")
        return None


def _fetch_latest_cached_report() -> Optional[Tuple[str, List[Dict[str, Any]]]]:
    if not _supabase:
        return None
    try:
        res = (
            _supabase.table(AGENT_REPORT_CACHE_TABLE)
            .select("cache_date, generated_at, sections, source, updated_at")
            .order("cache_date", desc=True)
            .order("updated_at", desc=True)
            .limit(1)
            .execute()
        )
        rows = res.data or []
        if not rows:
            return None
        row = rows[0]
        sections = row.get("sections")
        if not isinstance(sections, list):
            return None
        generated_at = row.get("generated_at") or row.get("updated_at") or _FALLBACK_GENERATED_AT
        return generated_at, sections
    except Exception as exc:
        print(f"⚠️ 读取最新日报缓存失败: {exc}")
        return None


def _save_cached_report(date_key: str, generated_at: str, sections: List[Dict[str, Any]], source: str) -> None:
    if not _supabase:
        return
    payload = {
        "cache_date": date_key,
        "generated_at": generated_at,
        "sections": sections,
        "source": source,
        "updated_at": _to_iso(datetime.now(timezone.utc)) or _FALLBACK_GENERATED_AT,
    }
    try:
        _supabase.table(AGENT_REPORT_CACHE_TABLE).upsert(payload, on_conflict="cache_date").execute()
    except Exception as exc:
        print(f"⚠️ 写入日报缓存失败: {exc}")


def _normalize_date(value: Optional[Any]) -> Optional[str]:
    if not value:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        if text.endswith("Z"):
            text = text.replace("Z", "+00:00")
        dt = datetime.fromisoformat(text)
        return dt.date().isoformat()
    except Exception:
        return text[:10] if len(text) >= 10 else None


def _extract_source_name(url: str) -> str:
    if not url:
        return ""
    try:
        parsed = urlparse(url)
        return parsed.netloc or ""
    except Exception:
        return ""


def _truncate(text: str, limit: int) -> str:
    if not text:
        return ""
    cleaned = " ".join(text.split())
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[:limit].rstrip() + "..."


def _normalize_tavily_result(raw: dict) -> dict:
    title = str(raw.get("title") or "").strip()
    url = str(raw.get("url") or "").strip()
    snippet = (
        str(raw.get("content") or raw.get("snippet") or raw.get("summary") or "").strip()
    )
    published_at = _normalize_date(
        raw.get("published_date")
        or raw.get("published_time")
        or raw.get("published")
        or raw.get("date")
    )
    source = str(raw.get("source") or "").strip() or _extract_source_name(url)
    return {
        "title": title,
        "url": url,
        "snippet": _truncate(snippet, 260),
        "publishedAt": published_at,
        "source": source,
    }


def _dedupe_results(results: List[dict]) -> List[dict]:
    seen = set()
    deduped = []
    for item in results:
        key = item.get("url") or item.get("title")
        if not key or key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped


def _call_tavily_search(query: str, max_results: int) -> List[dict]:
    api_key = _get_tavily_key()
    if not api_key:
        raise RuntimeError("missing TAVILY_API_KEY")
    payload = {
        "api_key": api_key,
        "query": query,
        "search_depth": AGENT_REPORT_SEARCH_DEPTH,
        "max_results": max_results,
        "include_answer": False,
        "include_images": False,
        "include_raw_content": False,
    }
    timeout = int(os.getenv("TAVILY_TIMEOUT", "25"))
    try:
        response = requests.post("https://api.tavily.com/search", json=payload, timeout=timeout)
        response.raise_for_status()
        data = response.json() or {}
    except requests.RequestException as exc:
        detail = ""
        if getattr(exc, "response", None) is not None:
            try:
                detail = exc.response.text[:300]
            except Exception:
                detail = ""
        print(f"⚠️ Tavily 请求失败: {exc} {detail}".strip())
        raise
    raw_results = data.get("results") or []
    normalized = [_normalize_tavily_result(item) for item in raw_results if isinstance(item, dict)]
    normalized = [item for item in normalized if item.get("url") and item.get("title")]
    return _dedupe_results(normalized)


def _llm_summarize_section(heading: str, results: List[dict]) -> str:
    if not results:
        return "- 暂无可靠公开信息，可稍后刷新查看"

    context_lines = []
    for idx, item in enumerate(results[:AGENT_REPORT_SOURCE_LIMIT], start=1):
        title = item.get("title") or "未命名"
        snippet = item.get("snippet") or ""
        source = item.get("source") or "未知来源"
        published = item.get("publishedAt") or "未知日期"
        url = item.get("url") or ""
        context_lines.append(
            f"{idx}. 标题：{title}\n摘要：{snippet}\n来源：{source}\n发布时间：{published}\n链接：{url}"
        )

    prompt = (
        f"请根据下面的检索结果，生成《{heading}》简报。\n"
        "要求：\n"
        "1) 用中文输出；\n"
        "2) 3-5条要点，使用项目符号；\n"
        "3) 总字数控制在120-220字；\n"
        "4) 不要捏造事实，不要编造来源；\n"
        "5) 不要包含链接或引用格式。\n\n"
        "检索结果：\n"
        + "\n\n".join(context_lines)
    )

    messages = [
        {
            "role": "system",
            "content": "你是企业情报助手，输出精炼、结构化的中文要点。",
        },
        {"role": "user", "content": prompt},
    ]

    try:
        resp = llm.chat(
            messages,
            temperature=0.3,
            top_p=0.8,
            max_tokens=500,
            model=AGENT_REPORT_SUMMARY_MODEL,
            timeout=60,
        )
        data = resp.json() if hasattr(resp, "json") else {}
        content = (
            data.get("choices", [{}])[0]
            .get("message", {})
            .get("content", "")
            .strip()
        )
        if content:
            return content
    except Exception:
        pass

    fallback_lines = [f"- {item.get('title')}" for item in results[:3] if item.get("title")]
    return "\n".join(fallback_lines) or "- 暂无可靠公开信息，可稍后刷新查看"


def _build_dynamic_sections() -> Tuple[str, List[Dict[str, Any]]]:
    generated_at = _to_iso(datetime.now(timezone.utc)) or _FALLBACK_GENERATED_AT
    sections: List[Dict[str, Any]] = []

    for section in SECTION_CONFIGS:
        try:
            results = _call_tavily_search(
                section["query"],
                max_results=AGENT_REPORT_SEARCH_MAX_RESULTS,
            )
        except Exception as exc:
            print(f"⚠️ Tavily 搜索失败 [{section['title']}]: {exc}")
            results = []
        summary = _llm_summarize_section(section["heading"], results)
        content = f"## {section['heading']}\n\n{summary}"

        sources = []
        for item in results[:AGENT_REPORT_SOURCE_LIMIT]:
            sources.append(
                {
                    "title": item.get("title"),
                    "url": item.get("url"),
                    "source": item.get("source"),
                    "publishedAt": item.get("publishedAt"),
                }
            )

        sections.append(
            {
                "id": section["id"],
                "title": section["title"],
                "icon": section["icon"],
                "content": content,
                "priority": section["priority"],
                "updatedAt": generated_at,
                "sources": sources,
            }
        )

    sections.sort(key=lambda s: (s.get("priority", 99), s.get("id", 0)))
    return generated_at, sections


def _get_cached_or_refresh(force_refresh: bool) -> Tuple[str, List[Dict[str, Any]], str]:
    today = _today_key()
    if not force_refresh:
        with REPORT_CACHE_LOCK:
            cached_date = REPORT_CACHE_STATE.get("date")
            cached_payload = REPORT_CACHE_STATE.get("payload")
            if cached_payload and cached_date == today:
                return cached_payload["generatedAt"], cached_payload["sections"], "cache"

        cached_db = _fetch_cached_report(today)
        if cached_db:
            generated_at, sections = cached_db
            payload = {"generatedAt": generated_at, "sections": sections}
            with REPORT_CACHE_LOCK:
                REPORT_CACHE_STATE["date"] = today
                REPORT_CACHE_STATE["payload"] = payload
            return generated_at, sections, "cache-db"

    try:
        generated_at, sections = _build_dynamic_sections()
    except Exception as exc:
        print(f"⚠️ 生成动态日报失败，回退缓存: {exc}")
        with REPORT_CACHE_LOCK:
            cached_payload = REPORT_CACHE_STATE.get("payload")
        if cached_payload:
            return cached_payload["generatedAt"], cached_payload["sections"], "cache-stale"
        cached_db = _fetch_cached_report(today)
        if cached_db:
            return cached_db[0], cached_db[1], "cache-stale"
        cached_latest = _fetch_latest_cached_report()
        if cached_latest:
            return cached_latest[0], cached_latest[1], "cache-stale"
        raise

    payload = {"generatedAt": generated_at, "sections": sections}
    with REPORT_CACHE_LOCK:
        REPORT_CACHE_STATE["date"] = today
        REPORT_CACHE_STATE["payload"] = payload
    _save_cached_report(today, generated_at, sections, "tavily")
    return generated_at, sections, "tavily"


def _fetch_from_supabase(limit: int) -> Tuple[str, List[Dict[str, Any]]]:
    if not _supabase:
        raise RuntimeError("Supabase client not available")

    query = (
        _supabase.table(AGENT_REPORT_SOURCE)
        .select("*")
        .order("priority", desc=False)
        .order("updated_at", desc=True)
    )
    if limit > 0:
        query = query.limit(limit)
    res = query.execute()
    rows = res.data or []

    if not rows:
        raise ValueError("no rows in Supabase result")

    sections: List[Dict[str, Any]] = []
    generated_candidates: List[str] = []

    for row in rows:
        section_id = row.get("id")
        title = row.get("title")
        content = row.get("content")
        icon = row.get("icon")

        if section_id is None or not title or not content:
            continue

        priority_val = row.get("priority")
        try:
            priority_int = int(priority_val)
        except Exception:
            priority_int = 99

        updated_at = row.get("updated_at") or row.get("updatedAt")
        formatted_updated = _to_iso(updated_at) or _to_iso(row.get("created_at"))

        sections.append(
            {
                "id": int(section_id),
                "title": str(title),
                "icon": str(icon) if icon else "el-icon-reading",
                "content": str(content),
                "priority": priority_int,
                "updatedAt": formatted_updated or _FALLBACK_GENERATED_AT,
                "sources": row.get("sources") if isinstance(row.get("sources"), list) else [],
            }
        )

        generated_raw = row.get("generated_at") or row.get("generatedAt")
        formatted_generated = _to_iso(generated_raw)
        if formatted_generated:
            generated_candidates.append(formatted_generated)

    if not sections:
        raise ValueError("no valid sections from Supabase")

    sections.sort(key=lambda s: (s["priority"], s["id"]))

    generated_at = (
        generated_candidates[0]
        if generated_candidates
        else sections[0].get("updatedAt")
        or _FALLBACK_GENERATED_AT
    )

    return generated_at, sections


def _fallback_report() -> Tuple[str, List[Dict[str, Any]]]:
    return _FALLBACK_GENERATED_AT, _FALLBACK_SECTIONS


@agent_report_bp.route("/initial-report", methods=["GET"])
def get_agent_initial_report():
    force_refresh = False
    try:
        from flask import request

        force_refresh = request.args.get("refresh") == "1"
    except Exception:
        force_refresh = False

    tavily_key = _get_tavily_key()
    if not tavily_key:
        print("[WARN] TAVILY_API_KEY missing; Tavily fetch disabled")
    if tavily_key:
        try:
            generated_at, sections, source = _get_cached_or_refresh(force_refresh)
        except Exception:
            try:
                generated_at, sections = _fetch_from_supabase(AGENT_REPORT_LIMIT)
                source = "remote"
            except Exception:
                generated_at, sections = _fallback_report()
                source = "fallback"
    else:
        try:
            generated_at, sections = _fetch_from_supabase(AGENT_REPORT_LIMIT)
            source = "remote"
        except Exception:
            generated_at, sections = _fallback_report()
            source = "fallback"

    payload = {
        "code": 200,
        "message": "success",
        "data": {
            "generatedAt": generated_at,
            "sections": sections,
        },
        "source": source,
    }

    try:
        print(f"[INFO] agent initial report source={source} generatedAt={generated_at}")
    except Exception:
        pass

    response = make_response(json.dumps(payload, ensure_ascii=False, indent=2))
    response.status_code = 200
    response.mimetype = "application/json; charset=utf-8"
    return response


# 此 Blueprint 仅供 app.py 注册使用，无需独立运行入口
