# -*- coding: utf-8 -*-
"""
Competitor Analysis → Qwen Summarization → Supabase Upsert (dashboard_daily_reports)

依赖:
    pip install supabase requests python-dotenv python-dateutil

环境变量:
    SUPABASE_URL=...
    SUPABASE_SERVICE_KEY=...
    QWEN_API_KEY=...
    QWEN_MODEL=qwen3-max
    DASHSCOPE_API_KEY=...        # 可与 QWEN_API_KEY 二选一
    DASHSCOPE_REGION=cn          # cn | intl | finance
    QWEN_OPENAI_COMPAT=1         # 设为1启用 OpenAI 兼容接口（qwen3-* 推荐）
    VIEW=management                 # management/market/sales/product
    DAYS=365                        # 扫描最近 N 天
    BATCH_SIZE=100                  # 每批条数
    MAX_BATCHES=10                  # 最大批次数
    SLEEP_SEC=0.3                   # 每条间隔秒
    FORCE_REFRESH=0                 # 1=强制重算覆盖；0=仅同analysis_id才跳过
    DEBUG=0                         # 1=打印部分模型原始输出片段

覆盖：
export FORCE_REFRESH=1
python daily-report-process.py
"""

import os
import re
import json
import time
import random
import logging
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, List, Tuple, Set, Optional

import requests
from supabase import create_client, Client
from dotenv import load_dotenv
from dateutil import parser as dateparser

# ---------------- 环境变量 ----------------
load_dotenv()

SUPABASE_URL  = os.getenv("SUPABASE_URL")
SUPABASE_KEY  = os.getenv("SUPABASE_SERVICE_KEY")
QWEN_API_KEY  = os.getenv("QWEN_API_KEY")
QWEN_MODEL    = os.getenv("QWEN_MODEL", "qwen3-max")
DASHSCOPE_API_KEY = os.getenv("DASHSCOPE_API_KEY")
API_KEY = DASHSCOPE_API_KEY or QWEN_API_KEY  # 兼容两种命名
DASHSCOPE_REGION = os.getenv("DASHSCOPE_REGION", "cn").lower()  # cn | intl | finance
QWEN_OPENAI_COMPAT = os.getenv("QWEN_OPENAI_COMPAT", "1").lower() in ("1","true","yes")

VIEW          = os.getenv("VIEW", "management")
DAYS          = int(os.getenv("DAYS", "365"))
BATCH_SIZE    = int(os.getenv("BATCH_SIZE", "100"))
MAX_BATCHES   = int(os.getenv("MAX_BATCHES", "10"))
SLEEP_SEC     = float(os.getenv("SLEEP_SEC", "0.3"))
FORCE_REFRESH = os.getenv("FORCE_REFRESH", "0") == "1"
DEBUG         = os.getenv("DEBUG", "0") == "1"

ANALYSIS_TABLE = "analysis_results"
COMP_TABLE     = "00_competitors"
DDR_TABLE      = "dashboard_daily_reports"

if not all([SUPABASE_URL, SUPABASE_KEY, API_KEY]):
    raise SystemExit("请设置 SUPABASE_URL / SUPABASE_SERVICE_KEY / QWEN_API_KEY 或 DASHSCOPE_API_KEY")

# ---------------- 常量 ----------------
ALLOWED_CATS = {"竞品动态", "销售机会", "产品动向", "政策动向"}

# ---------------- Logging ----------------
logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(levelname)s  %(message)s")
logger = logging.getLogger("qwen-daily-report")

# ---------------- Supabase ----------------
sb: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# ---------------- 清洗工具 ----------------
IMG_MD_PATTERN = re.compile(r'!\[[^\]]*\]\([^)]+\)')
NOISE_RE = re.compile(
    r'header|footer|logo|search|nav|二维码|微信公众号|移动客户端|/images?/|'
    r'\.(png|jpg|jpeg|svg)\b|^相关人物$|^下一步$|欢迎访问|统一身份认证|尊敬的用户',
    re.IGNORECASE
)

def clean_text(raw: str) -> str:
    if not raw:
        return ""
    lines = [l.strip() for l in raw.splitlines()]
    kept = []
    for l in lines:
        l2 = IMG_MD_PATTERN.sub("", l).strip()
        if not l2 or NOISE_RE.search(l2):
            continue
        if len(re.sub(r'[\W_]+', "", l2)) <= 1:
            continue
        kept.append(l2)
    txt = "\n".join(kept)
    txt = re.sub(r'\n{3,}', '\n\n', txt).strip()
    txt = re.sub(r'(?m)^(0?\d{1,2})[．\.\s　]+', r'\1. ', txt)
    return txt

def map_category(view: str) -> str:
    return {
        "management": "竞品动态",
        "market": "竞品动态",
        "sales": "销售机会",
        "product": "产品动向",
    }.get(view, "竞品动态")

def priority_text(p: str) -> str:
    return {"high": "高", "medium": "中"}.get((p or "").lower(), "低")

def to_iso_utc(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt.replace(microsecond=0).isoformat().replace("+00:00", "Z")

def parse_iso_to_aware(s: Optional[str]) -> datetime:
    if not s:
        return datetime.now(timezone.utc)
    try:
        dt = dateparser.isoparse(s)
    except Exception:
        dt = datetime.fromisoformat(s[:19])
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)

def safe_truncate(s: str, max_len: int) -> str:
    return s[:max_len] if s and len(s) > max_len else (s or "")

# ---------------- Prompt ----------------
PROMPT_TPL = """
你是竞争情报分析师。根据以下“竞品原始字段+网页片段”，只基于已给信息，输出**严格 JSON**（UTF-8，无注释，无多余文本）：
字段：
- title: 一句话标题（≤60字）
- summary_md: 3-5条要点（Markdown无序列表，每条≤50字）
- actions: [{"action":"具体行动","impact":"high|medium|low","due":"YYYY-MM-DD可空"}]
- tags: ["标签1","标签2"]
- priority: "high" | "medium" | "low"
- confidence: 0.0~1.0
- sources: [{"title":"来源名","url":"https://..."}]
- category: "竞品动态" | "销售机会" | "产品动向" | "政策动向"

要求：
- 不能臆测，不得引入未知事实
- 保留关键时间/数字
- category 必须从给定枚举中选择，若无法判断用“竞品动态”
- 若信息不足，尽量给出通用但不虚构的摘要/行动建议
- 严格输出 JSON

【竞品信息】
- 名称：{comp_name}
- 产品：{product}
- 官网：{website}
- 原威胁等级：{orig_threat}
- 分析时间：{analysis_time}

【结构化摘要（若有）】
{summary_report}

【网页正文片段（可选）】
{website_content}
""".strip()

# ---------------- Qwen API ----------------
DASHSCOPE_BASES = [
    "https://dashscope.aliyuncs.com",
    "https://dashscope-intl.aliyuncs.com",
]

DASHSCOPE_COMPAT_BASES = {
    "cn": "https://dashscope.aliyuncs.com/compatible-mode/v1",
    "intl": "https://dashscope-intl.aliyuncs.com/compatible-mode/v1",
    "finance": "https://dashscope-finance.aliyuncs.com/compatible-mode/v1",
}
def qwen_chat_json_compat(prompt: str, timeout: int = 60, max_retries: int = 6) -> Dict[str, Any]:
    """通过 OpenAI 兼容接口 (/chat/completions) 调用 Qwen（适配 qwen3-* 等）。
    默认强制 JSON（response_format），若不支持则自动降级。
    """
    base = DASHSCOPE_COMPAT_BASES.get(DASHSCOPE_REGION, DASHSCOPE_COMPAT_BASES["cn"])  # 依据地域
    url = f"{base}/chat/completions"
    headers = {"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"}

    def make_payload(use_resp_fmt: bool = True) -> Dict[str, Any]:
        body: Dict[str, Any] = {
            "model": QWEN_MODEL,
            "messages": [
                {"role": "system", "content": "你是严谨的情报分析师，严格输出 JSON 对象。"},
                {"role": "user", "content": prompt},
            ],
            "stream": False,
        }
        if use_resp_fmt:
            body["response_format"] = {"type": "json_object"}
        return body

    attempt, use_resp_fmt = 0, True
    while True:
        attempt += 1
        try:
            payload = make_payload(use_resp_fmt)
            resp = requests.post(url, headers=headers, json=payload, timeout=timeout)
            if resp.status_code == 200:
                data = resp.json()
                choices = data.get("choices") or []
                if not choices:
                    raise ValueError("OpenAI兼容接口返回空choices")
                text = (choices[0].get("message") or {}).get("content") or ""
                if not text:
                    raise ValueError("OpenAI兼容接口content为空")
                if DEBUG:
                    logger.info(f"[DEBUG] compat_raw_out: {str(text)[:200]}")
                return _parse_qwen_json(text)

            # 400 且包含 response_format 说明不支持该参数 → 降级重试
            if resp.status_code == 400 and "response_format" in (resp.text or "") and use_resp_fmt:
                logger.warning("兼容接口不支持 response_format，降级仅用提示词约束 JSON")
                use_resp_fmt = False
                continue

            # 限流/服务端错误 → 重试指数退避
            if resp.status_code in (429, 500, 502, 503, 504):
                wait = min(2 ** (attempt - 1), 20) * (1 + random.random())
                logger.warning(f"兼容接口 {resp.status_code}，睡 {wait:.1f}s 后重试")
                time.sleep(wait)
                continue

            # 鉴权/权限
            if resp.status_code in (401, 403):
                raise RuntimeError(f"DashScope兼容接口鉴权/权限错误 {resp.status_code}: {resp.text[:180]}")

            resp.raise_for_status()
        except Exception as e:
            if attempt < max_retries:
                wait = min(2 ** (attempt - 1), 10)
                logger.warning(f"兼容接口网络/解析异常，第{attempt}次重试，睡 {wait:.1f}s | {e}")
                time.sleep(wait)
                continue
            raise

def _extract_json_object_text(s: str) -> str:
    """
    从模型输出中尽量抽取 {...} 段。若找不到对象，抛错
    避免把 "action" 这种普通字符串当成 JSON.
    """
    s = (s or "").strip()
    # 去掉 ```json ... ``` 包裹
    if s.startswith("```"):
        s = s.strip("`")
        if s[:4].lower() == "json":
            s = s[4:].strip()
    # 直接就是对象？
    if s.startswith("{") and s.endswith("}"):
        return s
    # 宽松匹配第一个 {...}
    m = re.search(r"\{[\s\S]*\}", s)
    if m:
        return m.group(0)
    raise ValueError("No JSON object found in model output.")

def _parse_qwen_json(text: str) -> Dict[str, Any]:
    obj = json.loads(_extract_json_object_text(text))
    if not isinstance(obj, dict):
        raise ValueError(f"Model returned non-object JSON: {type(obj)}")
    # 兜底键，避免后续 .get 报错
    obj.setdefault("title", "")
    obj.setdefault("summary_md", "")
    obj.setdefault("actions", [])
    obj.setdefault("tags", [])
    obj.setdefault("priority", "low")
    obj.setdefault("confidence", 0.5)
    obj.setdefault("sources", [])
    obj.setdefault("category", "")
    return obj

def qwen_chat_json(prompt: str, timeout: int = 60, max_retries: int = 6) -> Dict[str, Any]:
    if QWEN_OPENAI_COMPAT or QWEN_MODEL.lower().startswith("qwen3-"):
        logger.info("使用 OpenAI 兼容接口：/chat/completions")
        return qwen_chat_json_compat(prompt, timeout=timeout, max_retries=max_retries)
    headers = {"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"}

    def payload_messages():
        return {
            "model": QWEN_MODEL,
            "input": {"messages": [
                {"role": "system", "content": "你是严谨的情报分析师，严格输出 JSON 对象。"},
                {"role": "user", "content": prompt}
            ]},
            "parameters": {"result_format": "json", "temperature": 0.2, "top_p": 0.8}
        }

    def payload_plain():
        return {
            "model": QWEN_MODEL,
            "input": prompt,
            "parameters": {"temperature": 0.2, "top_p": 0.8}
        }

    attempt, use_plain_input = 0, False
    bases_to_try = DASHSCOPE_BASES[:]

    while True:
        attempt += 1
        base = bases_to_try[0]
        url = f"{base}/api/v1/services/aigc/text-generation/generation"
        payload = payload_plain() if use_plain_input else payload_messages()

        try:
            resp = requests.post(url, headers=headers, json=payload, timeout=timeout)
            if resp.status_code == 200:
                data = resp.json()
                out = data.get("output") or {}
                text = out.get("text") or data.get("output_text")
                if not text and "choices" in out:
                    text = out["choices"][0]["message"]["content"]
                if not text:
                    raise ValueError("Qwen 返回空")
                if DEBUG:
                    logger.info(f"[DEBUG] raw_out: {str(text)[:200]}")
                return _parse_qwen_json(text)

            if resp.status_code == 400 and ("url error" in resp.text or "InvalidParameter" in resp.text):
                if len(bases_to_try) > 1:
                    bases_to_try.pop(0)
                    logger.warning("切换域名重试...")
                    continue
                if not use_plain_input:
                    use_plain_input = True
                    logger.warning("降级为 input=纯文本")
                    continue

            if resp.status_code in (429, 500, 502, 503, 504):
                wait = min(2 ** (attempt - 1), 20) * (1 + random.random())
                logger.warning(f"限流/服务端错误 {resp.status_code}，睡 {wait:.1f}s")
                time.sleep(wait)
                continue

            resp.raise_for_status()

        except Exception as e:
            if attempt < max_retries:
                wait = min(2 ** (attempt - 1), 10)
                logger.warning(f"网络/解析异常，第{attempt}次重试，睡 {wait:.1f}s | {e}")
                time.sleep(wait)
                continue
            raise

# ---------------- Supabase IO ----------------
def fetch_analysis_batch(offset: int, limit: int, days: int = DAYS) -> List[Dict[str, Any]]:
    since_dt = datetime.now(timezone.utc) - timedelta(days=days)
    since_ts = to_iso_utc(since_dt)
    since_d  = since_dt.date().isoformat()

    # A: timestamp/timestamptz
    try:
        res = sb.table(ANALYSIS_TABLE) \
            .select("*") \
            .gte("analysis_date", since_ts) \
            .order("analysis_date", desc=True) \
            .range(offset, offset + limit - 1) \
            .execute()
        data = res.data or []
    except Exception:
        data = []

    # B: date
    if not data:
        try:
            res = sb.table(ANALYSIS_TABLE) \
                .select("*") \
                .gte("analysis_date", since_d) \
                .order("analysis_date", desc=True) \
                .range(offset, offset + limit - 1) \
                .execute()
            data = res.data or []
        except Exception:
            data = []

    # 回退：最新 N 条
    if not data:
        res = sb.table(ANALYSIS_TABLE) \
            .select("*") \
            .order("analysis_date", desc=True) \
            .range(offset, offset + limit - 1) \
            .execute()
        data = res.data or []

    return data

def fetch_competitors_map(comp_ids: Set[str]) -> Dict[str, Dict[str, Any]]:
    if not comp_ids:
        return {}
    res = sb.table(COMP_TABLE) \
        .select("id, company_name, product, website") \
        .in_("id", list(comp_ids)) \
        .execute()
    rows = res.data or []
    out: Dict[str, Dict[str, Any]] = {}
    for r in rows:
        cid = r.get("id")
        if not cid:
            continue
        out[cid] = {
            "id": cid,
            # 兼容下游 comp["name"] 的用法
            "name": r.get("company_name") or "",
            "product": r.get("product") or "",
            "website": r.get("website") or "",
        }
    return out

def fetch_existing_map(report_date: str, view: str) -> Dict[str, Optional[str]]:
    """
    返回当日+视角下的 {competitor_id: analysis_id} 映射。
    - 若同一竞品当天已存在一条，且 analysis_id 一样 → 可跳过
    - 若 analysis_id 不同 → 允许覆盖（upsert）
    """
    res = sb.table(DDR_TABLE) \
        .select("competitor_id,analysis_id") \
        .eq("report_date", report_date) \
        .eq("view", view) \
        .execute()
    rows = res.data or []
    return {r["competitor_id"]: r.get("analysis_id") for r in rows if r.get("competitor_id")}

def upsert_ddr_row(
    payload: Dict[str, Any],
    report_date: str,
    view: str,
    competitor_id: str,
    analysis_id: str,
    priority: str,
    created_ts_iso: str,
    model: str,
) -> None:
    row = {
        "report_date": report_date,
        "view": view,
        "competitor_id": competitor_id,
        "analysis_id": analysis_id,
        "payload": payload,
        "priority": priority,
        "created_ts": created_ts_iso,
        "category": payload.get("category", "竞品动态"),
        "model_name": model,
        "prompt_version": "v1",
        "processed_at": datetime.now(timezone.utc).isoformat()
    }
    sb.table(DDR_TABLE).upsert(row, on_conflict="report_date,view,competitor_id").execute()

# ---------------- 业务组装 ----------------
def build_llm_prompt(ar: Dict[str, Any], comp: Dict[str, Any]) -> str:
    return PROMPT_TPL.format(
        comp_name=comp.get("name") or "未知",
        product=comp.get("product") or "未知",
        website=comp.get("website") or "",
        analysis_time=ar.get("analysis_date") or ar.get("created_at") or "",
        orig_threat=ar.get("threat_level") or "unknown",
        summary_report=safe_truncate((ar.get("summary_report") or "").strip(), 2000) or "(空)",
        website_content=safe_truncate(clean_text((ar.get("website_content") or "").strip()), 2000) or "(空)",
    )

def make_payload_from_llm(
    llm: Dict[str, Any], ar: Dict[str, Any], comp: Dict[str, Any], view: str
) -> Tuple[Dict[str, Any], str, str]:
    created_dt = parse_iso_to_aware(ar.get("analysis_date") or ar.get("created_at"))
    created_iso = to_iso_utc(created_dt)
    p = (llm.get("priority") or ar.get("threat_level") or "low").lower()
    if p not in ("high", "medium", "low"):
        p = "low"

    # ✅ 类别：优先用 LLM 的 category，非法则回退到视角映射
    llm_cat = (llm.get("category") or "").strip()
    if llm_cat not in ALLOWED_CATS:
        llm_cat = map_category(view)

    payload = {
        "id": ar["id"],
        "category": llm_cat,
        "title": llm.get("title") or f"{comp.get('name') or '未命名竞品'} 动态",
        "content": llm.get("summary_md") or (ar.get("summary_report") or (ar.get("website_content") or "")[:140] + "..."),
        "actions": llm.get("actions") or [],
        "tags": llm.get("tags") or [],
        "priority": p,
        "priorityText": priority_text(p),
        "confidence": float(llm.get("confidence", 0.5)),
        "sources": llm.get("sources") or [],
        "createdAt": created_iso,
    }
    return payload, p, created_iso

def guess_category(ar: Dict[str, Any], view: str) -> str:
    """
    兜底时的启发式分类：不再一律“竞品动态”
    """
    text = f"{ar.get('summary_report','')} {ar.get('website_content','')}"
    if any(k in text for k in ("招标", "采购", "投标", "中标", "RFQ", "RFP")):
        return "销售机会"
    if any(k in text for k in ("指导意见", "征求意见", "政策", "办法", "通知", "标准", "文件发布")):
        return "政策动向"
    if any(k in text for k in ("新品", "版本", "升级", "固件", "软件更新", "roadmap", "发布会")):
        return "产品动向"
    return map_category(view)

def make_payload_minimal(ar: Dict[str, Any], comp: Dict[str, Any], view: str) -> Tuple[Dict[str, Any], str, str]:
    created_dt = parse_iso_to_aware(ar.get("analysis_date") or ar.get("created_at"))
    created_iso = to_iso_utc(created_dt)
    p = (ar.get("threat_level") or "low").lower()
    if p not in ("high", "medium", "low"):
        p = "low"
    payload = {
        "id": ar["id"],
        "category": guess_category(ar, view),  # ✅ 不再固定视角映射
        "title": f"{comp.get('name') or '未命名竞品'} 动态",
        "content": (ar.get("summary_report") or (ar.get("website_content") or "")[:140] + "..."),
        "actions": [],
        "tags": [],
        "priority": p,
        "priorityText": priority_text(p),
        "confidence": 0.4,
        "sources": [],
        "createdAt": created_iso,
    }
    return payload, p, created_iso

# ---------------- Pipeline ----------------
def run_pipeline(max_batches: int = int(os.getenv("MAX_BATCHES", "10")),
                 batch_size: int = int(os.getenv("BATCH_SIZE", "100")),
                 sleep_sec: float = float(os.getenv("SLEEP_SEC", "0.3"))):
    logger.info(f"Qwen 模型: {QWEN_MODEL} | 视角: {VIEW} | 批大小: {batch_size} | 批次数: {max_batches} | DAYS={DAYS} | FORCE_REFRESH={int(FORCE_REFRESH)}")

    processed, skipped, failed = 0, 0, 0
    # 缓存：(report_date, view) -> {competitor_id: analysis_id}
    cache_exist_map: Dict[Tuple[str, str], Dict[str, Optional[str]]] = {}

    for b in range(max_batches):
        rows = fetch_analysis_batch(offset=b * batch_size, limit=batch_size, days=DAYS)
        if not rows:
            logger.info("没有更多数据，提前结束。")
            break

        comp_ids: Set[str] = {r.get("competitor_id") for r in rows if r.get("competitor_id")}
        comp_map = fetch_competitors_map(comp_ids)

        for ar in rows:
            try:
                cid = ar.get("competitor_id")
                if not cid or cid not in comp_map:
                    skipped += 1
                    continue
                comp = comp_map[cid]

                created_dt = parse_iso_to_aware(ar.get("analysis_date") or ar.get("created_at"))
                report_date = created_dt.date().isoformat()

                key = (report_date, VIEW)
                if key not in cache_exist_map:
                    cache_exist_map[key] = fetch_existing_map(report_date, VIEW)

                # 跳过策略：仅当“同竞品且 analysis_id 未变化”才跳过；FORCE_REFRESH=1 则不跳过
                prev = cache_exist_map[key].get(cid)
                if not FORCE_REFRESH and prev and prev == ar["id"]:
                    skipped += 1
                    continue

                # 调 Qwen，失败则兜底
                try:
                    prompt = build_llm_prompt(ar, comp)
                    llm_out = qwen_chat_json(prompt)
                    payload, pr, created_iso = make_payload_from_llm(llm_out, ar, comp, VIEW)
                except Exception as e:
                    logger.warning(f"[WARN] Qwen 失败，最小payload回退 analysis_id={ar.get('id')} | {e}")
                    payload, pr, created_iso = make_payload_minimal(ar, comp, VIEW)

                # 写入展示层（on_conflict=(report_date,view,competitor_id)）
                upsert_ddr_row(
                    payload=payload,
                    report_date=report_date,
                    view=VIEW,
                    competitor_id=cid,
                    analysis_id=ar["id"],
                    priority=pr,
                    created_ts_iso=created_iso,
                    model=QWEN_MODEL,
                )

                # 更新缓存：该竞品当天绑定到最新 analysis_id
                cache_exist_map[key][cid] = ar["id"]
                processed += 1
                logger.info(f"✅ upsert id={ar['id']} | {payload.get('title','')[:36]}")

            except Exception as e:
                failed += 1
                logger.error(f"[ERROR] id={ar.get('id')}: {e}", exc_info=True)
            time.sleep(sleep_sec)

    logger.info(f"管线结束：成功={processed} 跳过={skipped} 失败={failed}")

# ---------------- Main ----------------
if __name__ == "__main__":
    run_pipeline()