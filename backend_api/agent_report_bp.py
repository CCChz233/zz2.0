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
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from flask import Blueprint, make_response

from infra.db import supabase

# ===== 配置 =====
AGENT_REPORT_SOURCE = os.getenv("AGENT_REPORT_SOURCE", "agent_initial_report_view")
AGENT_REPORT_LIMIT = int(os.getenv("AGENT_REPORT_LIMIT", "12"))

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

    response = make_response(json.dumps(payload, ensure_ascii=False, indent=2))
    response.status_code = 200
    response.mimetype = "application/json; charset=utf-8"
    return response


# 此 Blueprint 仅供 app.py 注册使用，无需独立运行入口
