#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Opportunity Summarization → Qwen Judgement → Supabase Upsert (opportunity_insights)

依赖:
    pip install supabase requests python-dotenv

环境变量:
    SUPABASE_URL=...
    SUPABASE_SERVICE_KEY=...
    QWEN_API_KEY=...
    QWEN_MODEL=qwen3-max
    DASHSCOPE_API_KEY=...        # 可与 QWEN_API_KEY 二选一
    DASHSCOPE_REGION=cn          # cn | intl | finance
    QWEN_OPENAI_COMPAT=1         # 设为1启用 OpenAI 兼容接口（qwen3-* 推荐）
    BATCH_SIZE=50
    MAX_BATCHES=10
    SLEEP_SEC=0.3
    ONLY_MISSING=1               # 1=仅处理尚无洞察的商机；0=全部重算
    DAYS=30                      # 只扫描最近N天的商机（0=不限）
"""

import os
import re
import json
import time
import random
import logging
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, List, Optional

import requests
SESSION = requests.Session()
from supabase import create_client, Client
from dotenv import load_dotenv

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

BATCH_SIZE = int(os.getenv("BATCH_SIZE", "50"))
MAX_BATCHES = int(os.getenv("MAX_BATCHES", "10"))
SLEEP_SEC = float(os.getenv("SLEEP_SEC", "0.3"))
ONLY_MISSING = os.getenv("ONLY_MISSING", "1").lower() in ("1","true","yes")
DAYS = int(os.getenv("DAYS", "30"))

RAW_TABLE = os.getenv("OPPORTUNITY_TABLE", '00_opportunity')
TARGET_TABLE = os.getenv("OPPORTUNITY_INSIGHTS_TABLE", "opportunity_insights")

if not all([SUPABASE_URL, SUPABASE_KEY, QWEN_API_KEY]):
    raise SystemExit("请设置 SUPABASE_URL / SUPABASE_SERVICE_KEY / QWEN_API_KEY")

# ---------------- Logging ----------------
logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(levelname)s  %(message)s")
logger = logging.getLogger("qwen-opportunity-pipeline")

logger.info(f"Using RAW_TABLE = {RAW_TABLE} → TARGET_TABLE = {TARGET_TABLE}")

# ---------------- Supabase ----------------
sb: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# ---------------- 清洗函数 ----------------
IMG_MD_PATTERN = re.compile(r'!\[[^\]]*\]\([^)]+\)')
NOISE_RE = re.compile(
    r'header|footer|logo|search|nav|二维码|微信公众号|移动客户端|/images?/|'
    r'\.(png|jpg|jpeg|svg)\b|^相关人物$|^下一步$|欢迎访问|统一身份认证|尊敬的用户',
    re.IGNORECASE
)

def clean_text(raw: str) -> str:
    """去掉图片/页眉页脚/二维码/登录公告等噪声"""
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

# ---------------- Qwen API ----------------
DASHSCOPE_BASES = [
    "https://dashscope.aliyuncs.com",        # 国内
    "https://dashscope-intl.aliyuncs.com",   # 国际
]

DASHSCOPE_COMPAT_BASES = {
    "cn": "https://dashscope.aliyuncs.com/compatible-mode/v1",
    "intl": "https://dashscope-intl.aliyuncs.com/compatible-mode/v1",
    "finance": "https://dashscope-finance.aliyuncs.com/compatible-mode/v1",
}

FENCE_RE = re.compile(r'^\s*```(?:json)?\s*([\s\S]*?)\s*```\s*$', re.I)

def _strip_fence_to_json(s: str) -> dict:
    s = (s or "").strip()
    m = FENCE_RE.match(s)
    if m:
        s = m.group(1)
    i, j = s.find("{"), s.rfind("}")
    if 0 <= i < j:
        s = s[i:j+1]
    return json.loads(s)

def qwen_chat_json_compat(prompt: str, timeout: int = 60, max_retries: int = 6) -> Dict[str, Any]:
    base = DASHSCOPE_COMPAT_BASES.get(DASHSCOPE_REGION, DASHSCOPE_COMPAT_BASES["cn"])
    url = f"{base}/chat/completions"
    headers = {"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"}
    def make_payload(use_resp_fmt: bool = True):
        body: Dict[str, Any] = {
            "model": QWEN_MODEL,
            "messages": [
                {"role": "system", "content": "你是严谨的行业分析师，严格输出 JSON。"},
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
            resp = SESSION.post(url, headers=headers, json=payload, timeout=timeout)
            if resp.status_code == 200:
                data = resp.json()
                choices = data.get("choices") or []
                if not choices:
                    raise ValueError("OpenAI兼容接口返回空choices")
                text = (choices[0].get("message") or {}).get("content") or ""
                if not text:
                    raise ValueError("OpenAI兼容接口content为空")
                return _strip_fence_to_json(text)
            if resp.status_code == 400 and "response_format" in (resp.text or "") and use_resp_fmt:
                logger.warning("兼容接口不支持 response_format，降级仅用提示词约束 JSON")
                use_resp_fmt = False
                continue
            if resp.status_code in (429, 500, 502, 503, 504):
                wait = min(2 ** (attempt - 1), 20) * (1 + random.random())
                logger.warning(f"兼容接口 {resp.status_code}，睡 {wait:.1f}s 后重试")
                time.sleep(wait)
                continue
            if resp.status_code in (401, 403):
                raise RuntimeError(f"DashScope兼容接口鉴权/权限错误 {resp.status_code}: {resp.text[:180]}")
            resp.raise_for_status()
        except Exception as e:
            if attempt < max_retries:
                wait = min(2 ** (attempt - 1), 10)
                logger.warning(f"兼容接口网络异常，第{attempt}次重试，睡 {wait:.1f}s | {e}")
                time.sleep(wait)
                continue
            raise

def qwen_chat_json(prompt: str, timeout: int = 60, max_retries: int = 6) -> Dict[str, Any]:
    if QWEN_OPENAI_COMPAT or QWEN_MODEL.lower().startswith("qwen3-"):
        logger.info("使用 OpenAI 兼容接口调用：/chat/completions")
        return qwen_chat_json_compat(prompt, timeout=timeout, max_retries=max_retries)
    headers = {"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"}
    def make_payload_messages():
        return {
            "model": QWEN_MODEL,
            "input": {
                "messages": [
                    {"role": "system", "content": "你是严谨的行业分析师，严格输出 JSON。"},
                    {"role": "user", "content": prompt}
                ]
            },
            "parameters": {"result_format": "json", "temperature": 0.0, "top_p": 0.8}
        }
    def make_payload_plain():
        sys = "你是严谨的行业分析师，严格输出 JSON。"
        return {
            "model": QWEN_MODEL,
            "input": f"{sys}\n\n{prompt}",
            "parameters": {"result_format": "json", "temperature": 0.0, "top_p": 0.8}
        }
    attempt, use_plain_input = 0, False
    bases_to_try = DASHSCOPE_BASES[:]
    while True:
        attempt += 1
        base = bases_to_try[0]
        url = f"{base}/api/v1/services/aigc/text-generation/generation"
        payload = make_payload_plain() if use_plain_input else make_payload_messages()
        try:
            resp = SESSION.post(url, headers=headers, json=payload, timeout=timeout)
            if resp.status_code == 200:
                data = resp.json()
                out = data.get("output") or {}
                text = out.get("text") or data.get("output_text")
                if not text and "choices" in out:
                    text = out["choices"][0]["message"]["content"]
                if not text:
                    raise ValueError("Qwen 返回空")
                return _strip_fence_to_json(text)
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
                logger.warning(f"网络异常，第{attempt}次重试，睡 {wait:.1f}s | {e}")
                time.sleep(wait)
                continue
            raise

# ---------------- Prompt ----------------
OPPORTUNITY_PROMPT = """
你是B2B商机分析师。基于输入的商机原文，判断其是否“值得关注”，并输出严格JSON（UTF-8，无注释），所有键必须出现：
{
  "title": "",                  // 核心标题，尽量简洁
  "short_summary": "",          // ≤120字摘要
  "noteworthy": false,          // 是否值得关注（对公司有潜在价值/影响）
  "reasons": ["", ""],          // 2-5条理由，每条≤40字
  "priority": "low",            // high/medium/low
  "actions": ["", ""],          // 1-3条建议动作（可执行）
  "tags": ["", ""],             // 2-5个标签
  "confidence": 0.6             // 0~1，模型置信度
}
判定维度（择要）：
- 行业相关性（半导体/科研仪器/设备/测试/高校科研）
- 金额/体量/项目阶段/采购信号
- 政策/资本/头部客户/关键合作
- 可落地性（是否能转化为拜访/投标/合作）
要求：仅依据输入，不得虚构；不输出 Markdown 或说明文字；禁止注释与尾随逗号。
正文：
\"\"\"{clean_text}\"\"\"
""".strip()

def _normalize_opportunity_keys(d: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(d, dict):
        return {
            "title": "", "short_summary": "", "noteworthy": False,
            "reasons": [], "priority": "low", "actions": [], "tags": [], "confidence": 0.5
        }
    def pick(keys, default=None):
        for k in keys:
            if k in d:
                return d.get(k)
            for kk in list(d.keys()):
                if kk.lower() == k.lower():
                    return d.get(kk)
        return default
    title = pick(["title"], "")
    short_summary = pick(["short_summary", "summary"], "")
    noteworthy = bool(pick(["noteworthy", "is_noteworthy"], False))
    reasons = pick(["reasons"], [])
    priority = (pick(["priority", "level"], "low") or "low").lower()
    actions = pick(["actions", "suggestions"], [])
    tags = pick(["tags", "labels"], [])
    confidence = pick(["confidence", "conf"], 0.5)
    # 类型兜底
    if not isinstance(reasons, list):
        try:
            if isinstance(reasons, str):
                reasons = json.loads(reasons)
            else:
                reasons = []
        except Exception:
            reasons = []
    if not isinstance(actions, list):
        actions = []
    if not isinstance(tags, list):
        tags = []
    try:
        confidence = float(confidence)
    except Exception:
        confidence = 0.5
    if priority not in ("high", "medium", "low"):
        priority = "low"
    return {
        "title": (title or "").strip(),
        "short_summary": (short_summary or "").strip()[:120],
        "noteworthy": bool(noteworthy),
        "reasons": [str(x).strip()[:40] for x in (reasons or []) if isinstance(x, (str,int))][:5],
        "priority": priority,
        "actions": [str(x).strip()[:60] for x in (actions or []) if isinstance(x, (str,int))][:3],
        "tags": [str(x).strip()[:24] for x in (tags or []) if isinstance(x, (str,int))][:6],
        "confidence": max(0.0, min(1.0, confidence)),
    }

def analyze_opportunity(clean_text_: str) -> Dict[str, Any]:
    body = clean_text_[:6000]
    prompt = OPPORTUNITY_PROMPT.format(clean_text=body)
    raw = qwen_chat_json(prompt)
    return _normalize_opportunity_keys(raw)

# ---------------- Supabase IO ----------------
def fetch_opportunities_batch(offset: int, limit: int) -> List[Dict[str, Any]]:
    q = sb.table(RAW_TABLE) \
        .select("id,title,content,source_url,publish_time,source_type,news_type")
    if DAYS and DAYS > 0:
        since = (datetime.now(timezone.utc) - timedelta(days=DAYS)).isoformat()
        q = q.gte("publish_time", since)
    res = q.order("publish_time", desc=True, nullsfirst=False) \
           .order("id", desc=True) \
           .range(offset, offset + limit - 1) \
           .execute()
    return res.data or []

def fetch_insights_map(ids: List[str]) -> Dict[str, Dict[str, Any]]:
    if not ids:
        return {}
    try:
        res = sb.table(TARGET_TABLE) \
            .select("opportunity_id,noteworthy,priority,updated_at") \
            .in_("opportunity_id", ids) \
            .execute()
    except Exception:
        return {}
    m: Dict[str, Dict[str, Any]] = {}
    for r in (res.data or []):
        m[str(r["opportunity_id"])] = r
    return m

def upsert_insight(row: Dict[str, Any], clean_txt: str, insight: Dict[str, Any]) -> None:
    payload = {
        "opportunity_id": row["id"],
        "clean_text": clean_txt,
        "short_summary": (insight.get("short_summary") or "")[:120],
        "noteworthy": bool(insight.get("noteworthy")),
        "reasons": insight.get("reasons") or [],
        "priority": insight.get("priority") or "low",
        "actions": insight.get("actions") or [],
        "tags": insight.get("tags") or [],
        "confidence": float(insight.get("confidence") or 0.5),
        "raw_json": insight,
        "model": QWEN_MODEL,
        "updated_at": datetime.now(timezone.utc).isoformat(),
        # 可选透传
        "title": row.get("title") or insight.get("title") or "",
        "source_url": row.get("source_url") or "",
        "publish_time": row.get("publish_time"),
        "source_type": row.get("source_type") or "",
        "news_type": row.get("news_type") or "",
    }
    sb.table(TARGET_TABLE).upsert(payload, on_conflict="opportunity_id").execute()

# ---------------- Pipeline ----------------
def run_pipeline(max_batches: int = MAX_BATCHES, batch_size: int = BATCH_SIZE, sleep_sec: float = SLEEP_SEC, only_missing: bool = ONLY_MISSING):
    processed = 0
    for b in range(max_batches):
        rows = fetch_opportunities_batch(offset=b * batch_size, limit=batch_size)
        if not rows:
            logger.info("没有更多数据，处理完成。")
            break
        if only_missing:
            ids = [r["id"] for r in rows]
            imap = fetch_insights_map(ids)
            rows = [r for r in rows if str(r["id"]) not in imap]
            if not rows:
                logger.info("本批全部已有洞察，跳过。")
                continue
        for r in rows:
            oid = r["id"]
            raw = r.get("content") or ""
            try:
                clean = clean_text(raw)
                if not clean:
                    logger.info(f"[SKIP] id={oid} 清洗后为空")
                    continue
                insight = analyze_opportunity(clean)
                upsert_insight(r, clean, insight)
                processed += 1
                logger.info(f"✅ 已处理 {oid} | noteworthy={insight.get('noteworthy')} | priority={insight.get('priority')}")
            except Exception as e:
                logger.error(f"[ERROR] id={oid}: {e}", exc_info=True)
                continue
            time.sleep(sleep_sec)
    logger.info(f"管线结束，总处理条数：{processed}")

if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--batches", type=int, default=MAX_BATCHES)
    p.add_argument("--batch-size", type=int, default=BATCH_SIZE)
    p.add_argument("--sleep", type=float, default=SLEEP_SEC)
    p.add_argument("--all", dest="only_missing", action="store_false", help="不论是否已有洞察，全部重算")
    p.set_defaults(only_missing=ONLY_MISSING)
    p.add_argument("--days", type=int, default=DAYS, help="仅处理最近N天（0=不限）")
    args = p.parse_args()
    # 覆盖运行参数
    MAX_BATCHES = args.batches
    BATCH_SIZE = args.batch_size
    SLEEP_SEC = args.sleep
    ONLY_MISSING = args.only_missing
    DAYS = args.days
    logger.info(f"Qwen 模型: {QWEN_MODEL} | 批大小: {BATCH_SIZE} | days={DAYS} | only_missing={ONLY_MISSING}")
    run_pipeline(max_batches=MAX_BATCHES, batch_size=BATCH_SIZE, sleep_sec=SLEEP_SEC, only_missing=ONLY_MISSING)


