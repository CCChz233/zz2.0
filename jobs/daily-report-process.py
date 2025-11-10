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
import hashlib
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
QWEN_TEMPERATURE = float(os.getenv("QWEN_TEMPERATURE", "0.0"))
ENABLE_NOISE_FILTER = os.getenv("ENABLE_NOISE_FILTER", "0").lower() in ("1", "true", "yes")

VIEW          = os.getenv("VIEW", "management")
DAYS          = int(os.getenv("DAYS", "30"))
_ENV_BATCH    = os.getenv("BATCH_SIZE")
BATCH_SIZE    = int(_ENV_BATCH or "40")
MAX_BATCHES   = int(os.getenv("MAX_BATCHES", "10"))
SLEEP_SEC     = float(os.getenv("SLEEP_SEC", "0.8"))
FORCE_REFRESH = os.getenv("FORCE_REFRESH", "0") == "1"
DEBUG         = os.getenv("DEBUG", "0") == "1"

ANALYSIS_TABLE = os.getenv("ANALYSIS_TABLE", "fact_events")
SOURCE_TABLE = (ANALYSIS_TABLE or "").lower()
IS_FACT_EVENTS = SOURCE_TABLE == "fact_events"
COMP_TABLE     = "00_competitors"
DDR_TABLE      = "dashboard_daily_reports"
FACT_DDR_TABLE = os.getenv("FACT_DDR_TABLE", "dashboard_daily_events")
MONTHLY_TABLE  = os.getenv("MONTHLY_TABLE", FACT_DDR_TABLE)
MONTHLY_DAYS   = int(os.getenv("MONTHLY_DAYS", "30"))
MONTHLY_SOURCE_TABLE = os.getenv("MONTHLY_SOURCE_TABLE", SOURCE_TABLE)
MONTHLY_LIMIT  = int(os.getenv("MONTHLY_LIMIT", "10"))

if not all([SUPABASE_URL, SUPABASE_KEY, API_KEY]):
    raise SystemExit("请设置 SUPABASE_URL / SUPABASE_SERVICE_KEY / QWEN_API_KEY 或 DASHSCOPE_API_KEY")

# ---------------- 常量 ----------------
# 统一使用业务指定的四类（不要额外判别）
ALLOWED_CATS = {"行业新闻", "科技论文", "销售机会", "竞品动态", "政策动向", "产品动向"}
# 固定映射：fact_events.type -> DDR.category
TYPE_TO_CAT = {
    "news": "行业新闻",
    "paper": "科技论文",
    "opportunity": "销售机会",
    "competitor": "竞品动态",
}
#
# 视角不再限制事件类型：空集合 = 不做类型过滤，所有视角都处理全部类型
VIEW_TO_FACT_TYPES = {
    "management": set(),
    "market": set(),
    "sales": set(),
    "product": set(),
}
NOISE_URL_KEYWORDS = [
    "translate.google", "facebook.com", "linkedin.com", "twitter.com", "instagram.com",
    "youtube.com", "tiktok.com", "weibo.com", "xiaohongshu", "play.google", "apps.apple",
    "steam", "itunes.apple", "6park", "banff", "arkansas", "arkansas.gov", "reservation",
    "ticketing", "eventbrite", "jobs.", "/career", "/jobs", "recruit", "workday", "indeed",
    "glassdoor", "monster.com", "bosszhipin", "zhipin.com", "lagou.com", "51job", "linkedin",
    "facebook", "appstore", "apk", "nanosurf", "parks", "park.", "museum", "theme park",
    "tourism", "travel.", "hotel", "booking", "xn--", "translate.", "urlextern",
]
NOISE_SOURCE_KEYWORDS = {
    "facebook", "linkedin", "boss直聘", "instagram", "推特", "twitter", "app store",
    "google play", "nanosurf", "park", "旅游", "招聘", "career"
}

# ---------------- Logging ----------------
logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(levelname)s  %(message)s")
logger = logging.getLogger("qwen-daily-report")
if _ENV_BATCH:
    logger.warning(f"环境变量 BATCH_SIZE={_ENV_BATCH} 已覆盖默认值 40，可调整或取消该变量以应用新的节流策略。")
if ENABLE_NOISE_FILTER:
    logger.info("噪声过滤已启用，可通过设置 ENABLE_NOISE_FILTER=0 关闭。")
else:
    logger.info("噪声过滤当前关闭，如需过滤可设置 ENABLE_NOISE_FILTER=1。")

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

# ---------------- 类型到分类映射 ----------------
def map_type_to_category(ev_type: Optional[str]) -> str:
    t = (ev_type or "").strip().lower()
    return TYPE_TO_CAT.get(t, "竞品动态")

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

FACT_PROMPT_TPL = """
你是一名企业情报分析师。基于给定的“事实事件”信息，生成一份结构化的重点摘要，并**严格输出 JSON（UTF-8，无注释、无额外文本）**：
字段定义：
- title: 一句话标题（≤60字）
- summary_md: 3-6条要点（Markdown 无序列表，每条≤60字）
- actions: 针对关注团队的行动建议（1-4条），格式 [{{"action":"具体行动","impact":"high|medium|low","due":"YYYY-MM-DD或空"}}]
- tags: 3-6个标签（可直接复用或扩展关键词）
- priority: "high" | "medium" | "low"
- confidence: 0.0~1.0
- sources: 1-3 个来源 [{{"title":"来源名","url":"https://..."}}]
- category: 固定为 {category}，不得输出其它枚举值

约束要求：
- 仅依据提供的事实信息，严禁臆测或引入外部事实
- 优先保留关键时间、数字、地点等细节
- 若缺少行动建议或标签，可结合摘要信息给出通用但不过度臆测的内容
- 若来源 URL 为空，可省略 sources
- 严格输出合法 JSON 对象，不要使用 Markdown 代码块

【事件元数据】
- 类型：{event_type}
- 标题：{title}
- 来源：{source}
- 发布时间：{published_at}
- 关键词：{keywords}
- 原文链接：{url}

【现有摘要或正文片段】
{summary_block}
注意：最终回答必须仅包含上述字段的 JSON 对象，键名齐全，禁止返回纯字符串或 Markdown 代码块。
输出要求（必须严格遵守）：
仅输出如下格式（不要多余任何文字）：
###BEGIN_JSON###
{{上述字段的 JSON 对象}}
###END_JSON###
""".strip()

MONTHLY_PROMPT_TPL = """
你是一名企业情报分析师。请针对以下近{days}天内的事件列表生成**单条综合总结**，必须严格输出 JSON：
- title: 一句话总结标题（≤60字）
- summary_md: 3-6条要点（Markdown无序列表，每条≤60字），侧重趋势、机会、风险
- recommendations: 针对业务团队的3-5条行动建议（Markdown无序列表，每条≤50字）
- tags: 3-6个关键词标签
- outlook: 对未来趋势的简短判断（≤80字）
- priority: "high" | "medium" | "low"
- confidence: 0.0~1.0
- category: 固定为 "{category}"
- sources: 2-5个最具代表性的来源 [{{"title":"来源名","url":"https://..."}}]

输出要求：
仅输出如下格式（不要多余任何文字）：
###BEGIN_JSON###
{{JSON 对象}}
###END_JSON###

【事件列表（按时间降序，最多 {limit} 条）】
{event_lines}
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
            "temperature": QWEN_TEMPERATURE,
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
    从模型输出中稳健抽取 JSON 对象：
    1) 优先使用 ###BEGIN_JSON### ... ###END_JSON### 包裹的对象
    2) 否则用非贪婪匹配捕获第一个 {...}
    若均失败则抛错
    """
    s = (s or "").strip()
    # 去掉 ```json ... ``` 包裹
    if s.startswith("```"):
        s = s.strip("`")
        if s[:4].lower() == "json":
            s = s[4:].strip()
    # 1) 优先标记块
    m = re.search(r"###BEGIN_JSON###\s*({[\s\S]*?})\s*###END_JSON###", s)
    if m:
        return m.group(1)
    # 2) 非贪婪捕获首个对象
    m = re.search(r"({[\s\S]*?})", s)
    if m:
        return m.group(1)
    raise ValueError("No JSON object found in model output.")

# ---- 插入 _normalize_llm_obj helper ----
def _normalize_llm_obj(obj: Dict[str, Any]) -> Dict[str, Any]:
    # 补全必备键
    obj = dict(obj)  # 复制一份，避免原地副作用
    obj.setdefault("title", "")
    obj.setdefault("summary_md", "")
    obj.setdefault("actions", [])
    obj.setdefault("tags", [])
    obj.setdefault("priority", "low")
    obj.setdefault("confidence", 0.5)
    obj.setdefault("sources", [])
    obj.setdefault("category", "")
    # 形态修复
    if not isinstance(obj["actions"], list):
        obj["actions"] = [obj["actions"]] if isinstance(obj["actions"], dict) else []
    if not isinstance(obj["tags"], list):
        obj["tags"] = [obj["tags"]] if obj["tags"] else []
    if not isinstance(obj["sources"], list):
        obj["sources"] = []
    # 值域与类型修复
    p = str(obj.get("priority", "low")).lower()
    obj["priority"] = p if p in ("high", "medium", "low") else "low"
    try:
        obj["confidence"] = float(obj.get("confidence", 0.5))
    except Exception:
        obj["confidence"] = 0.5
    return obj

def _parse_qwen_json(text: str) -> Dict[str, Any]:
    try:
        obj = json.loads(_extract_json_object_text(text))
    except Exception:
        obj = (text or "").strip()
    # 若成功解析为 dict → 规范化并返回
    if isinstance(obj, dict):
        return _normalize_llm_obj(obj)
    # 其它（str/list等）→ 构造最小可用对象
    return {
        "title": safe_truncate(str(obj), 50) or "自动摘要",
        "summary_md": _fallback_summary_md(str(obj)),
        "actions": [],
        "tags": [],
        "priority": "low",
        "confidence": 0.4,
        "sources": [],
        "category": "",
    }

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
            "parameters": {"result_format": "json", "temperature": QWEN_TEMPERATURE, "top_p": 0.8}
        }

    def payload_plain():
        return {
            "model": QWEN_MODEL,
            "input": prompt,
            "parameters": {"temperature": QWEN_TEMPERATURE, "top_p": 0.8}
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

    table = ANALYSIS_TABLE
    rows: List[Dict[str, Any]] = []

    # If using fact_events, prefer published_at/created_at
    if table == "fact_events":
        try:
            res = sb.table(table) \
                .select("*") \
                .or_(f"published_at.gte.{since_ts},and(published_at.is.null,created_at.gte.{since_ts})") \
                .order("published_at", desc=True) \
                .order("created_at", desc=True) \
                .range(offset, offset + limit - 1) \
                .execute()
            rows = res.data or []
        except Exception:
            rows = []
        if not rows:
            try:
                res = sb.table(table) \
                    .select("*") \
                    .order("published_at", desc=True) \
                    .order("created_at", desc=True) \
                    .range(offset, offset + limit - 1) \
                    .execute()
                rows = res.data or []
            except Exception:
                rows = []
        return rows

    # Default path for analysis_results (analysis_date)
    # A: timestamp/timestamptz
    try:
        res = sb.table(table) \
            .select("*") \
            .gte("analysis_date", since_ts) \
            .order("analysis_date", desc=True) \
            .range(offset, offset + limit - 1) \
            .execute()
        rows = res.data or []
    except Exception:
        rows = []

    # B: date
    if not rows:
        try:
            res = sb.table(table) \
                .select("*") \
                .gte("analysis_date", since_d) \
                .order("analysis_date", desc=True) \
                .range(offset, offset + limit - 1) \
                .execute()
            rows = res.data or []
        except Exception:
            rows = []

    # 回退：最新 N 条
    if not rows:
        res = sb.table(table) \
            .select("*") \
            .order("analysis_date", desc=True) \
            .range(offset, offset + limit - 1) \
            .execute()
        rows = res.data or []

    return rows

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
    返回当日+视角下已存在的记录映射。
    - 对 analysis_results：{competitor_id: analysis_id}
    - 对 fact_events：{event_id: event_id}
    """
    if IS_FACT_EVENTS:
        res = (
            sb.table(FACT_DDR_TABLE)
            .select("event_id")
            .eq("report_date", report_date)
            .eq("view", view)
            .execute()
        )
        rows = res.data or []
        return {str(r["event_id"]): str(r["event_id"]) for r in rows if r.get("event_id")}

    res = (
        sb.table(DDR_TABLE)
        .select("competitor_id,analysis_id")
        .eq("report_date", report_date)
        .eq("view", view)
        .execute()
    )
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

def upsert_fact_ddr_row(
    payload: Dict[str, Any],
    report_date: str,
    view: str,
    event_id: str,
    event_type: str,
    priority: str,
    created_ts_iso: str,
    model: str,
) -> None:
    row = {
        "report_date": report_date,
        "view": view,
        "event_id": event_id,
        "event_type": event_type,
        "payload": payload,
        "priority": priority,
        "category": payload.get("category", "竞品动态"),
        "created_ts": created_ts_iso,
        "model_name": model,
        "prompt_version": "fact_v1",
        "processed_at": datetime.now(timezone.utc).isoformat(),
        "content_hash": payload.get("contentHash"),
    }
    sb.table(FACT_DDR_TABLE).upsert(row, on_conflict="report_date,view,event_id").execute()

# ---------------- 业务组装 ----------------
def build_llm_prompt(ar: Dict[str, Any], comp: Dict[str, Any]) -> str:
    target_cat = map_type_to_category(ar.get("type"))
    return PROMPT_TPL.format(
        comp_name=comp.get("name") or "未知",
        product=comp.get("product") or "未知",
        website=comp.get("website") or "",
        analysis_time=ar.get("analysis_date") or ar.get("created_at") or "",
        orig_threat=ar.get("threat_level") or "unknown",
        summary_report=safe_truncate((ar.get("summary_report") or "").strip(), 2000) or "(空)",
        website_content=safe_truncate(clean_text((ar.get("website_content") or "").strip()), 2000) or "(空)",
    ) + f"\n\n请注意：本条事件类型映射的目标分类为“{target_cat}”，请在输出 JSON 中将 category 固定为该值。"

def make_payload_from_llm(
    llm: Dict[str, Any], ar: Dict[str, Any], comp: Dict[str, Any], view: str
) -> Tuple[Dict[str, Any], str, str]:
    created_dt = parse_iso_to_aware(ar.get("analysis_date") or ar.get("created_at"))
    created_iso = to_iso_utc(created_dt)
    p = (llm.get("priority") or ar.get("threat_level") or "low").lower()
    if p not in ("high", "medium", "low"):
        p = "low"

    # ✅ 类别：严格按来源类型映射（不做额外判别）
    llm_cat = map_type_to_category(ar.get("type"))

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
        "category": map_type_to_category(ar.get("type")),
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

def extract_event_datetime(ev: Dict[str, Any]) -> datetime:
    for field in ("published_at", "analysis_date", "created_at"):
        val = ev.get(field)
        if val:
            try:
                return parse_iso_to_aware(str(val))
            except Exception:
                continue
    return datetime.now(timezone.utc)

def extract_event_summary(ev: Dict[str, Any]) -> str:
    payload = ev.get("payload") if isinstance(ev.get("payload"), dict) else {}
    candidates = [
        ev.get("summary"),
        payload.get("summary_preview") if isinstance(payload, dict) else None,
        ev.get("content"),
    ]
    for cand in candidates:
        if isinstance(cand, str) and cand.strip():
            return safe_truncate(cand.strip(), 2000)
    return ""

def _format_keywords(ev: Dict[str, Any]) -> str:
    kws = ev.get("keywords")
    if isinstance(kws, list):
        return ", ".join(str(x) for x in kws if x)
    if isinstance(kws, str):
        return kws
    payload = ev.get("payload")
    if isinstance(payload, dict):
        p_kws = payload.get("keywords")
        if isinstance(p_kws, list):
            return ", ".join(str(x) for x in p_kws if x)
        if isinstance(p_kws, str):
            return p_kws
    return ""

def build_fact_event_prompt(ev: Dict[str, Any]) -> Tuple[str, str]:
    category = map_type_to_category(ev.get("type"))
    summary_text = extract_event_summary(ev) or "(暂无摘要)"
    prompt = FACT_PROMPT_TPL.format(
        category=category,
        event_type=ev.get("type") or "unknown",
        title=ev.get("title") or "未命名事件",
        source=ev.get("source") or "未知来源",
        published_at=ev.get("published_at") or ev.get("created_at") or "",
        keywords=_format_keywords(ev) or "(无)",
        url=ev.get("url") or "(无)",
        summary_block=summary_text,
    )
    return prompt, category

def is_noise_event(ev: Dict[str, Any]) -> bool:
    url = (ev.get("url") or "").lower()
    if any(kw in url for kw in NOISE_URL_KEYWORDS if kw):
        return True
    source = (ev.get("source") or "").lower()
    if any(kw in source for kw in NOISE_SOURCE_KEYWORDS if kw):
        return True
    title = (ev.get("title") or "").lower()
    if any(kw in title for kw in NOISE_SOURCE_KEYWORDS if kw):
        return True
    return False

def _fallback_summary_md(text: str) -> str:
    lines = [line.strip() for line in text.splitlines() if line.strip()] if text else []
    if not lines:
        return "- 暂无可用摘要"
    bullets = []
    for line in lines:
        if not line.startswith("-"):
            bullets.append(f"- {line}")
        else:
            bullets.append(line)
    return "\n".join(bullets) or "- 暂无可用摘要"

def make_event_payload_from_llm(llm: Dict[str, Any], ev: Dict[str, Any]) -> Tuple[Dict[str, Any], str, str]:
    if not isinstance(llm, dict):
        llm = {}
    created_dt = extract_event_datetime(ev)
    created_iso = to_iso_utc(created_dt)

    p = (llm.get("priority") or "low").lower()
    if p not in ("high", "medium", "low"):
        p = "low"

    category = map_type_to_category(ev.get("type"))
    tags = llm.get("tags") or []
    if not tags:
        kws = ev.get("keywords")
        if isinstance(kws, list):
            tags = [str(x) for x in kws if x]

    sources = llm.get("sources")
    if not sources:
        url = ev.get("url")
        if url:
            sources = [{"title": ev.get("source") or ev.get("title") or "来源", "url": url}]
        else:
            sources = []

    summary_md = llm.get("summary_md")
    if not summary_md:
        summary_md = _fallback_summary_md(extract_event_summary(ev))

    payload = {
        "id": ev.get("id"),
        "category": category,
        "title": llm.get("title") or (ev.get("title") or "未命名事件"),
        "content": summary_md,
        "actions": llm.get("actions") or [],
        "tags": tags,
        "priority": p,
        "priorityText": priority_text(p),
        "confidence": float(llm.get("confidence", 0.5)),
        "sources": sources,
        "createdAt": created_iso,
        "source": ev.get("source"),
        "url": ev.get("url"),
        "event_type": ev.get("type"),
        "published_at": ev.get("published_at"),
    }
    return payload, p, created_iso

def make_event_payload_minimal(ev: Dict[str, Any]) -> Tuple[Dict[str, Any], str, str]:
    created_dt = extract_event_datetime(ev)
    created_iso = to_iso_utc(created_dt)
    category = map_type_to_category(ev.get("type"))
    summary_text = extract_event_summary(ev)
    summary_md = _fallback_summary_md(summary_text)

    tags: List[str] = []
    kws = ev.get("keywords")
    if isinstance(kws, list):
        tags = [str(x) for x in kws if x]

    sources = []
    if ev.get("url"):
        sources = [{"title": ev.get("source") or ev.get("title") or "来源", "url": ev.get("url")}]

    payload = {
        "id": ev.get("id"),
        "category": category,
        "title": ev.get("title") or "未命名事件",
        "content": summary_md,
        "actions": [],
        "tags": tags,
        "priority": "low",
        "priorityText": priority_text("low"),
        "confidence": 0.4,
        "sources": sources,
        "createdAt": created_iso,
        "source": ev.get("source"),
        "url": ev.get("url"),
        "event_type": ev.get("type"),
        "published_at": ev.get("published_at"),
    }
    return payload, "low", created_iso

# ---------------- Pipeline ----------------
def run_pipeline(max_batches: int = int(os.getenv("MAX_BATCHES", "10")),
                 batch_size: int = int(os.getenv("BATCH_SIZE", "100")),
                 sleep_sec: float = float(os.getenv("SLEEP_SEC", "0.3"))):
    target_table = FACT_DDR_TABLE if IS_FACT_EVENTS else DDR_TABLE
    logger.info(
        f"Qwen 模型: {QWEN_MODEL} | 视角: {VIEW} | 源表: {ANALYSIS_TABLE} | 目标表: {target_table} | "
        f"批大小: {batch_size} | 批次数: {max_batches} | DAYS={DAYS} | FORCE_REFRESH={int(FORCE_REFRESH)}"
    )

    processed, skipped, skipped_noise, failed = 0, 0, 0, 0
    # 缓存：(report_date, view) -> {competitor_id: analysis_id}
    cache_exist_map: Dict[Tuple[str, str], Dict[str, Optional[str]]] = {}

    for b in range(max_batches):
        rows = fetch_analysis_batch(offset=b * batch_size, limit=batch_size, days=DAYS)
        if not rows:
            logger.info("没有更多数据，提前结束。")
            break

        comp_map: Dict[str, Dict[str, Any]] = {}
        if not IS_FACT_EVENTS:
            comp_ids: Set[str] = {r.get("competitor_id") for r in rows if r.get("competitor_id")}
            comp_map = fetch_competitors_map(comp_ids)

        target_types = VIEW_TO_FACT_TYPES.get(VIEW, set())

        for ar in rows:
            try:
                if IS_FACT_EVENTS:
                    ev_type_raw = (ar.get("type") or "").strip().lower()
                    # target_types 为空表示不过滤类型
                    if target_types and ev_type_raw not in target_types:
                        skipped += 1
                        continue
                    ev_type = ev_type_raw or "unknown"

                    if ENABLE_NOISE_FILTER and is_noise_event(ar):
                        skipped += 1
                        skipped_noise += 1
                        if DEBUG:
                            logger.debug(f"[SKIP][noise] event_id={ar.get('id')} url={ar.get('url')} source={ar.get('source')}")
                        continue

                    created_dt = extract_event_datetime(ar)
                    report_date = created_dt.date().isoformat()

                    key = (report_date, VIEW)
                    if key not in cache_exist_map:
                        cache_exist_map[key] = fetch_existing_map(report_date, VIEW)

                    raw_identifier = ar.get("id") or ar.get("row_hash") or ar.get("url")
                    event_id = str(raw_identifier or f"{ev_type}-{created_dt.isoformat()}")

                    prev = cache_exist_map[key].get(event_id)
                    if not FORCE_REFRESH and prev and str(prev) == event_id:
                        skipped += 1
                        continue

                    try:
                        prompt, _ = build_fact_event_prompt(ar)
                        llm_out = qwen_chat_json(prompt)
                        payload, pr, created_iso = make_event_payload_from_llm(llm_out, ar)
                    except Exception as e:
                        logger.warning(f"[WARN] Qwen 失败，最小payload回退 fact_event_id={event_id} | {e}")
                        payload, pr, created_iso = make_event_payload_minimal(ar)

                    upsert_fact_ddr_row(
                        payload=payload,
                        report_date=report_date,
                        view=VIEW,
                        event_id=event_id,
                        event_type=ev_type,
                        priority=pr,
                        created_ts_iso=created_iso,
                        model=QWEN_MODEL,
                    )

                    cache_exist_map[key][event_id] = event_id
                    processed += 1
                    logger.info(f"✅ upsert fact_event={event_id} | {payload.get('title','')[:36]}")
                    continue

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

                prev = cache_exist_map[key].get(cid)
                if not FORCE_REFRESH and prev and str(prev) == str(ar["id"]):
                    skipped += 1
                    continue

                try:
                    prompt = build_llm_prompt(ar, comp)
                    llm_out = qwen_chat_json(prompt)
                    payload, pr, created_iso = make_payload_from_llm(llm_out, ar, comp, VIEW)
                except Exception as e:
                    logger.warning(f"[WARN] Qwen 失败，最小payload回退 analysis_id={ar.get('id')} | {e}")
                    payload, pr, created_iso = make_payload_minimal(ar, comp, VIEW)

                upsert_ddr_row(
                    payload=payload,
                    report_date=report_date,
                    view=VIEW,
                    competitor_id=cid,
                    analysis_id=str(ar["id"]),
                    priority=pr,
                    created_ts_iso=created_iso,
                    model=QWEN_MODEL,
                )

                cache_exist_map[key][cid] = str(ar["id"])
                processed += 1
                logger.info(f"✅ upsert analysis_id={ar['id']} | {payload.get('title','')[:36]}")

            except Exception as e:
                failed += 1
                logger.error(f"[ERROR] id={ar.get('id')}: {e}", exc_info=True)
            sleep_jitter = sleep_sec * (0.8 + random.random() * 0.5)
            time.sleep(max(0.05, sleep_jitter))

    logger.info(f"管线结束：成功={processed} 跳过={skipped} (噪声={skipped_noise}) 失败={failed}")

# ---------------- Weekly Summary Pipeline ----------------
def fetch_last_15_days_by_type(table: str, types: List[str]) -> Dict[str, List[Dict[str, Any]]]:
    """
    读取最近15天内指定类型的记录，按 type 过滤。
    对 fact_events 优先使用 published_at，其次 created_at。
    对 analysis_results 使用 analysis_date。
    """
    since_dt = datetime.now(timezone.utc) - timedelta(days=15)
    since_iso = to_iso_utc(since_dt)

    out: Dict[str, List[Dict[str, Any]]] = {t: [] for t in types}
    rows: List[Dict[str, Any]] = []

    try:
        if table == "fact_events":
            res = sb.table(table) \
                .select("*") \
                .in_("type", types) \
                .or_(f"published_at.gte.{since_iso},and(published_at.is.null,created_at.gte.{since_iso})") \
                .order("published_at", desc=True) \
                .order("created_at", desc=True) \
                .limit(3000) \
                .execute()
        else:
            res = sb.table(table) \
                .select("*") \
                .in_("type", types) \
                .gte("analysis_date", since_iso) \
                .order("analysis_date", desc=True) \
                .order("created_at", desc=True) \
                .limit(3000) \
                .execute()
        rows = res.data or []
    except Exception:
        rows = []

    for r in rows:
        t = (r.get("type") or "").lower()
        if t in types:
            out[t].append(r)
    return out

def build_weekly_prompt(category_name: str, events: List[Dict[str, Any]]) -> str:
    """
    给大模型一个结构化的15日汇总提示词；输出沿用单条的 JSON schema。
    """
    # 将近15天事件做成条目文本
    bullets = []
    for ev in events[:200]:  # 上限保护
        title = (ev.get("title") or ev.get("summary_report") or "")[:120]
        ts = ev.get("published_at") or ev.get("analysis_date") or ev.get("created_at") or ""
        src = ev.get("source") or ""
        url = ev.get("url") or ""
        bullets.append(f"- [{ts}] {title} ({src}) {url}".strip())
    context = "\n".join(bullets) if bullets else "(无事件)"
    prompt = f"""
你是竞争情报分析师。请基于以下“近15天事件条目”生成一份**汇总**，并严格输出 JSON：
- title: 一句话汇总标题（≤60字）
- summary_md: 3-6条关键要点（Markdown 列表，每条≤50字）
- actions: 针对下阶段的行动建议列表（3-5条）
- tags: 3-6个标签
- priority: "high" | "medium" | "low"（整体关注度）
- confidence: 0.0~1.0
- sources: 可选，列出最具代表性的 3~5 个来源（title/url）
- category: 固定为“{category_name}”

【近15天事件条目】
{context}
""".strip()
    return prompt

WEEKLY_TABLE = os.getenv("WEEKLY_TABLE", "dashboard_weekly_reports")

def upsert_weekly_row(category_name: str, payload: Dict[str, Any]) -> None:
    # 定义周起止（以 UTC），窗口为15天
    end_dt = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    start_dt = end_dt - timedelta(days=15)
    row = {
        "week_start": start_dt.date().isoformat(),
        "week_end": end_dt.date().isoformat(),
        "category": category_name,
        "payload": payload,
        "created_ts": datetime.now(timezone.utc).isoformat(),
        "model_name": QWEN_MODEL,
        "prompt_version": "weekly_v1",
        "processed_at": datetime.now(timezone.utc).isoformat()
    }
    sb.table(WEEKLY_TABLE).upsert(row, on_conflict="week_start,week_end,category").execute()

def run_weekly_summary(source_table: str = os.getenv("ANALYSIS_TABLE", ANALYSIS_TABLE)):
    """
    读取最近15天内四种类型（news/paper/opportunity/competitor），
    各生成一份汇总（行业新闻/科技论文/销售机会/竞品动态）。
    """
    logger.info("开始汇总：最近15天 × 4 类别")
    types = ["news", "paper", "opportunity", "competitor"]
    buckets = fetch_last_15_days_by_type(source_table, types)
    for t in types:
        events = buckets.get(t, [])
        cat = map_type_to_category(t)
        try:
            prompt = build_weekly_prompt(cat, events)
            llm_out = qwen_chat_json(prompt)
            # 强制覆盖分类为映射类目
            if isinstance(llm_out, dict):
                llm_out["category"] = cat
            upsert_weekly_row(cat, llm_out)
            logger.info(f"✅ 汇总写入：{cat} | 事件数={len(events)}")
        except Exception as e:
            logger.error(f"[WEEKLY][ERROR] {cat}: {e}", exc_info=True)
    logger.info("汇总结束。")

# ---------------- Monthly Category Summary ----------------
def fetch_recent_events_by_type(table: str, ev_type: str, days: int, limit: int) -> List[Dict[str, Any]]:
    since_dt = datetime.now(timezone.utc) - timedelta(days=days)
    since_iso = to_iso_utc(since_dt)
    try:
        res = (
            sb.table(table)
            .select("*")
            .eq("type", ev_type)
            .or_(f"published_at.gte.{since_iso},and(published_at.is.null,created_at.gte.{since_iso})")
            .order("published_at", desc=True)
            .order("created_at", desc=True)
            .limit(limit)
            .execute()
        )
        return res.data or []
    except Exception:
        return []

def build_monthly_prompt(category_name: str, events: List[Dict[str, Any]], days: int, limit: int) -> str:
    lines = []
    for ev in events:
        ts = ev.get("published_at") or ev.get("created_at") or ""
        title = (ev.get("title") or ev.get("summary_report") or "")[:120]
        source = ev.get("source") or ""
        url = ev.get("url") or ""
        lines.append(f"- [{ts}] {title} ({source}) {url}".strip())
    event_lines = "\n".join(lines) if lines else "(无事件)"
    return MONTHLY_PROMPT_TPL.format(
        category=category_name,
        days=days,
        limit=limit,
        event_lines=event_lines,
    )

def _normalize_priority(value: Optional[str]) -> str:
    if not value:
        return "medium"
    v = str(value).strip().lower()
    if v not in ("high", "medium", "low"):
        return "medium"
    return v


def _deep_parse_json_field(value: Any) -> Any:
    """
    深度解析可能被错误序列化的 JSON 字段。
    如果字段是字符串且看起来像 JSON，尝试解析它。
    """
    if isinstance(value, str):
        value = value.strip()
        # 如果字符串以 { 或 [ 开头，尝试解析为 JSON
        if value.startswith("{") or value.startswith("["):
            try:
                parsed = json.loads(value)
                # 如果解析成功，递归处理（可能有多层嵌套）
                if isinstance(parsed, dict):
                    return {k: _deep_parse_json_field(v) for k, v in parsed.items()}
                elif isinstance(parsed, list):
                    return [_deep_parse_json_field(item) for item in parsed]
                return parsed
            except Exception:
                pass
    elif isinstance(value, dict):
        return {k: _deep_parse_json_field(v) for k, v in value.items()}
    elif isinstance(value, list):
        return [_deep_parse_json_field(item) for item in value]
    return value

def _clean_text_line(text: str) -> str:
    """
    清理文本行，移除 JSON 转义字符、键名等，只保留纯文本内容。
    """
    if not text:
        return ""
    
    # 先尝试从 JSON 字符串中提取实际内容
    # 匹配 "title": "实际内容" 或 "summary_md": ["实际内容"]
    title_match = re.search(r'"title"\s*:\s*"([^"]+)"', text)
    if title_match:
        return title_match.group(1).strip()
    
    # 移除 JSON 转义字符（包括转义的引号）
    text = text.replace("\\n", " ").replace("\\t", " ").replace("\\r", " ")
    text = text.replace('\\"', '').replace("\\'", "").replace("\\\\", "")
    
    # 移除 Markdown 列表符号
    text = text.strip().lstrip("-").strip().lstrip("*").strip().lstrip("+").strip()
    
    # 移除所有引号（包括转义的）
    text = re.sub(r'["\']+', '', text)
    
    # 移除 JSON 键名模式（如 "title":, "summary_md": 等）
    text = re.sub(r'["\']?\w+["\']?\s*:\s*', '', text)
    
    # 移除 JSON 结构符号
    text = text.replace("{", "").replace("}", "").replace("[", "").replace("]", "")
    
    # 移除奇怪的标点符号组合（如 \",。 或 \",。-）
    text = re.sub(r'[\\"]+[,。，]+', '，', text)
    text = re.sub(r'[,。，]+[-]+', '，', text)
    
    # 移除多余的空白
    text = re.sub(r'\s+', ' ', text).strip()
    
    return text

def _extract_clean_text_from_field(value: Any) -> List[str]:
    """
    从字段中提取清理后的纯文本列表（去重）。
    """
    clean_lines = []
    seen = set()  # 用于去重
    
    if isinstance(value, list):
        for item in value:
            if isinstance(item, str):
                # 先移除转义引号
                item = item.replace('\\"', '').replace("\\'", "")
                cleaned = _clean_text_line(item)
                # 过滤掉 JSON 键名、转义字符等
                if cleaned and len(cleaned) > 5 and not cleaned.startswith("title") and not cleaned.startswith("summary"):
                    # 检查是否包含中文字符（确保是实际内容）
                    if any('\u4e00' <= char <= '\u9fff' for char in cleaned):
                        # 使用前50字作为去重键
                        key = cleaned[:50]
                        if key not in seen:
                            clean_lines.append(cleaned)
                            seen.add(key)
    elif isinstance(value, str):
        # 先移除转义引号
        value = value.replace('\\"', '').replace("\\'", "")
        
        # 如果是字符串，先尝试解析为 JSON
        if value.strip().startswith("[") or value.strip().startswith("{"):
            try:
                parsed = json.loads(value)
                return _extract_clean_text_from_field(parsed)
            except Exception:
                pass
        
        # 尝试从 JSON 字符串中提取数组内容
        # 匹配 "summary_md": ["内容1", "内容2"]
        array_match = re.search(r'\[(.*?)\]', value, re.DOTALL)
        if array_match:
            array_content = array_match.group(1)
            # 提取所有引号内的内容
            items = re.findall(r'"([^"]+)"', array_content)
            for item in items:
                cleaned = _clean_text_line(item)
                if cleaned and len(cleaned) > 5 and any('\u4e00' <= char <= '\u9fff' for char in cleaned):
                    key = cleaned[:50]
                    if key not in seen:
                        clean_lines.append(cleaned)
                        seen.add(key)
            # 如果从数组中提取到了内容，就不再按行处理，避免重复
            if clean_lines:
                return clean_lines
        
        # 按行分割处理（只有在没有从数组中提取到内容时才执行）
        if not clean_lines:
            lines = value.split("\n")
            for line in lines:
                cleaned = _clean_text_line(line)
                if cleaned and len(cleaned) > 5 and not cleaned.startswith("title") and not cleaned.startswith("summary"):
                    # 检查是否包含中文字符
                    if any('\u4e00' <= char <= '\u9fff' for char in cleaned):
                        key = cleaned[:50]
                        if key not in seen:
                            clean_lines.append(cleaned)
                            seen.add(key)
    
    return clean_lines

def _build_text_summary(llm_data: Dict[str, Any], target_length: int = 250) -> str:
    """
    从 LLM 返回的 JSON 中提取关键信息，组合成约 250 字的纯文本总结。
    """
    # 深度解析，处理可能被错误序列化的字段
    llm_data = _deep_parse_json_field(llm_data)
    
    # 提取标题
    title_raw = llm_data.get("title", "")
    title = ""
    if isinstance(title_raw, str):
        # 先尝试从 JSON 字符串中提取标题（处理不完整的 JSON）
        title_match = re.search(r'"title"\s*:\s*"([^"]+)"', title_raw)
        if title_match:
            title = title_match.group(1).strip()
        else:
            # 如果找不到，尝试解析完整 JSON
            if title_raw.strip().startswith("{"):
                try:
                    # 尝试补全不完整的 JSON
                    if not title_raw.strip().endswith("}"):
                        title_raw = title_raw + "}"
                    title_obj = json.loads(title_raw)
                    if isinstance(title_obj, dict):
                        title = str(title_obj.get("title", "")).strip()
                    else:
                        title = str(title_obj).strip()
                except Exception:
                    # 解析失败，使用清理函数
                    title = _clean_text_line(title_raw)
            else:
                # 不是 JSON 格式，直接清理
                title = _clean_text_line(title_raw)
        
        # 最终清理：移除所有引号和转义字符
        title = title.replace('\\"', '').replace("\\'", "")
        title = re.sub(r'["\']+', '', title)
        title = title.strip()
    
    # 提取 summary_md 的所有要点
    summary_lines = _extract_clean_text_from_field(llm_data.get("summary_md"))
    
    # 提取 recommendations（如果有）
    recommendations = _extract_clean_text_from_field(llm_data.get("recommendations", []))[:2]
    
    # 提取 outlook
    outlook_raw = llm_data.get("outlook", "")
    outlook = ""
    if isinstance(outlook_raw, str):
        outlook = _clean_text_line(outlook_raw)
        if outlook.startswith("{") or "outlook" in outlook.lower():
            try:
                outlook_obj = json.loads(outlook_raw)
                if isinstance(outlook_obj, dict):
                    outlook = str(outlook_obj.get("outlook", "")).strip()
                else:
                    outlook = str(outlook_obj).strip()
            except Exception:
                match = re.search(r'"outlook"\s*:\s*"([^"]+)"', outlook_raw)
                if match:
                    outlook = match.group(1)
                else:
                    outlook = _clean_text_line(outlook_raw)
    
    # 组合文本：标题 + 所有要点 + 展望 + 建议
    parts = []
    seen = set()  # 用于去重
    
    if title and len(title) < 100 and not title.startswith("{"):  # 标题不要太长，且不是 JSON
        title_key = title[:50]  # 使用前50字作为去重键
        if title_key not in seen:
            parts.append(title)
            seen.add(title_key)
    
    # 添加所有要点（去重）
    if summary_lines:
        for line in summary_lines:
            line_key = line[:50]  # 使用前50字作为去重键
            if line_key not in seen:
                parts.append(line)
                seen.add(line_key)
    
    # 添加展望（去重）
    if outlook and len(outlook) < 150 and not outlook.startswith("{"):
        outlook_key = outlook[:50]
        if outlook_key not in seen:
            parts.append(outlook)
            seen.add(outlook_key)
    
    # 添加建议（如果有，去重）
    if recommendations:
        for rec in recommendations:
            rec_key = rec[:50]
            if rec_key not in seen:
                parts.append(rec)
                seen.add(rec_key)
    
    # 用句号连接
    combined = "。".join(parts)
    
    # 彻底清理多余的符号和 JSON 残留（但要小心不要截断文本）
    # 先记录原始长度，确保清理后不会意外缩短太多
    original_len = len(combined)
    
    # 移除所有转义引号
    combined = combined.replace('\\"', '').replace("\\'", "")
    # 移除所有普通引号（但要保留中文引号「」）
    combined = re.sub(r'["\']+', '', combined)
    # 移除 JSON 键名模式（但要小心，不要匹配到正常文本）
    # 只匹配类似 "title": 或 'title': 这样的模式，且前后有空格或标点
    combined = re.sub(r'\s*["\']?\w+["\']?\s*:\s*', '', combined)
    # 移除奇怪的标点符号组合（如 \",。 或 \",。-）
    combined = re.sub(r'[\\"]+[,。，]+', '，', combined)
    combined = re.sub(r'[,。，]+[-]+', '，', combined)
    # 移除 JSON 转义字符
    combined = combined.replace("\\n", " ").replace("\\t", " ").replace("\\r", " ")
    # 清理重复的标点符号
    combined = combined.replace("。。", "。").replace("，。", "。").replace("，,", "，")
    # 移除多余的空白
    combined = re.sub(r'\s+', ' ', combined).strip()
    
    # 如果清理后长度异常缩短（超过20%），可能是清理过度了，记录警告
    if original_len > 0 and len(combined) < original_len * 0.8:
        logger.warning(f"[WARN] 清理后文本长度异常缩短: {original_len} -> {len(combined)}")
    
    # 控制长度到约 250 字（只在最后截断）
    if len(combined) > target_length:
        # 尝试在句号处截断
        truncated = combined[:target_length]
        last_period = truncated.rfind("。")
        if last_period > target_length * 0.7:  # 如果句号位置合理（在70%之后）
            combined = truncated[:last_period + 1]
        else:
            # 如果找不到合适的句号，尝试在逗号处截断
            last_comma = truncated.rfind("，")
            if last_comma > target_length * 0.7:
                combined = truncated[:last_comma] + "。"
            else:
                combined = truncated + "..."
    
    return combined

def upsert_monthly_row(category_name: str, payload: Dict[str, Any], days: int, source_size: int) -> None:
    end_dt = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    start_dt = end_dt - timedelta(days=days)
    now_iso = datetime.now(timezone.utc).isoformat()

    # 确保 payload 是 dict，如果不是则尝试解析
    llm_data: Dict[str, Any]
    if isinstance(payload, dict):
        llm_data = dict(payload)
    elif isinstance(payload, str):
        # 如果是字符串，尝试解析 JSON
        try:
            llm_data = json.loads(payload)
        except Exception:
            llm_data = {"raw_output": payload}
    else:
        llm_data = {"raw_output": str(payload)}
    
    # 深度解析，处理可能被错误序列化的字段
    llm_data = _deep_parse_json_field(llm_data)
    
    # 提取关键字段（处理可能被序列化的情况）
    title_raw = llm_data.get("title", "")
    title = ""
    if isinstance(title_raw, str):
        # 先尝试从 JSON 字符串中提取标题（处理不完整的 JSON）
        title_match = re.search(r'"title"\s*:\s*"([^"]+)"', title_raw)
        if title_match:
            title = title_match.group(1).strip()
        else:
            # 如果找不到，尝试解析完整 JSON
            if title_raw.strip().startswith("{"):
                try:
                    # 尝试补全不完整的 JSON
                    if not title_raw.strip().endswith("}"):
                        title_raw = title_raw + "}"
                    title_obj = json.loads(title_raw)
                    if isinstance(title_obj, dict):
                        title = str(title_obj.get("title", "")).strip()
                    else:
                        title = str(title_obj).strip()
                except Exception:
                    # 解析失败，使用清理函数
                    title = _clean_text_line(title_raw)
            else:
                # 不是 JSON 格式，直接清理
                title = _clean_text_line(title_raw)
        
        # 最终清理：移除所有引号和转义字符
        title = title.replace('\\"', '').replace("\\'", "")
        title = re.sub(r'["\']+', '', title)
        title = title.strip()
    
    # 提取 tags
    tags = llm_data.get("tags", [])
    if isinstance(tags, str):
        try:
            tags = json.loads(tags)
        except Exception:
            tags = []
    if not isinstance(tags, list):
        tags = []
    
    # 提取 sources
    sources = llm_data.get("sources", [])
    if isinstance(sources, str):
        try:
            sources = json.loads(sources)
        except Exception:
            sources = []
    if not isinstance(sources, list):
        sources = []
    
    priority = _normalize_priority(llm_data.get("priority"))
    try:
        confidence = float(llm_data.get("confidence", 0.5))
    except Exception:
        confidence = 0.5
    
    # 生成纯文本总结（约 250 字）
    text_summary = _build_text_summary(llm_data, target_length=250)
    
    # 构建简洁的 payload
    clean_payload: Dict[str, Any] = {
        "title": title,
        "summary": text_summary,  # 纯文本总结
        "category": category_name,
        "priority": priority,
        "confidence": confidence,
        "tags": tags,
        "sources": sources,
        "periodStart": start_dt.date().isoformat(),
        "periodEnd": end_dt.date().isoformat(),
        "windowDays": days,
        "sourceCount": source_size,
    }

    if MONTHLY_TABLE == FACT_DDR_TABLE:
        # 复用 dashboard_daily_events 表结构：占位 event_id，汇总写入 payload
        event_id = f"monthly-{category_name}"
        content_hash = hashlib.sha256(json.dumps(clean_payload, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()
        row = {
            "report_date": end_dt.date().isoformat(),
            "view": VIEW,
            "event_id": event_id,
            "event_type": "monthly_summary",
            "payload": clean_payload,
            "priority": priority,
            "category": category_name,
            "created_ts": now_iso,
            "model_name": QWEN_MODEL,
            "prompt_version": "monthly_v1",
            "processed_at": now_iso,
            "content_hash": content_hash,
        }
        sb.table(FACT_DDR_TABLE).upsert(row, on_conflict="report_date,view,event_id").execute()
    else:
        row = {
            "period_start": start_dt.date().isoformat(),
            "period_end": end_dt.date().isoformat(),
            "category": category_name,
            "payload": clean_payload,
            "model_name": QWEN_MODEL,
            "prompt_version": "monthly_v1",
            "processed_at": now_iso,
        }
        sb.table(MONTHLY_TABLE).upsert(row, on_conflict="period_start,period_end,category").execute()

def run_monthly_summary():
    logger.info(f"开始月度分类汇总：近{MONTHLY_DAYS}天，每类最新{MONTHLY_LIMIT}条")
    types = ["news", "competitor", "opportunity", "paper"]
    for ev_type in types:
        try:
            events = fetch_recent_events_by_type(
                MONTHLY_SOURCE_TABLE,
                ev_type,
                MONTHLY_DAYS,
                MONTHLY_LIMIT,
            )
            category_name = map_type_to_category(ev_type)
            prompt = build_monthly_prompt(category_name, events, MONTHLY_DAYS, MONTHLY_LIMIT)
            llm_out = qwen_chat_json(prompt)
            if isinstance(llm_out, dict):
                llm_out["category"] = category_name
            upsert_monthly_row(category_name, llm_out, MONTHLY_DAYS, len(events))
            logger.info(f"✅ 月度汇总写入：{category_name} | 事件数={len(events)} | 表={MONTHLY_TABLE}")
        except Exception as e:
            logger.error(f"[MONTHLY][ERROR] {category_name}: {e}", exc_info=True)
    logger.info("月度分类汇总结束。")

# ---------------- Main ----------------
if __name__ == "__main__":
    MODE = os.getenv("MODE", "monthly").lower()  # monthly | daily | weekly
    if MODE == "weekly":
        # 按近15天四类生成 4 份汇总
        run_weekly_summary(os.getenv("ANALYSIS_TABLE", ANALYSIS_TABLE))
    elif MODE == "monthly":
        run_monthly_summary()
    else:
        # 逐事件写入每日展示表（fact_events → dashboard_daily_events | analysis_results → dashboard_daily_reports）
        run_pipeline()