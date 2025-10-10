# -*- coding: utf-8 -*-
"""
News Cleaning + Qwen Summarization + Supabase Upsert (完整修正版)

依赖:
    pip install supabase requests python-dotenv

环境变量:
    SUPABASE_URL=...
    SUPABASE_SERVICE_KEY=...
    QWEN_API_KEY=...
    QWEN_MODEL=qwen-turbo
"""

import os
import re
import json
import time
import random
import logging
from datetime import datetime, timezone
from typing import Dict, Any, List

import requests
from supabase import create_client, Client
from dotenv import load_dotenv

# ---------------- 环境变量 ----------------
load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_KEY")
QWEN_API_KEY = os.getenv("QWEN_API_KEY")
QWEN_MODEL = os.getenv("QWEN_MODEL", "qwen-turbo")

PIPELINE_MODE = os.getenv("PIPELINE_MODE", "multi").lower()  # multi | single
RAW_NEWS_TABLE = os.getenv("RAW_NEWS_TABLE", "00_news")      # 原始新闻表

BATCH_SIZE = int(os.getenv("BATCH_SIZE", "20"))  # 每批文章数量

if not all([SUPABASE_URL, SUPABASE_KEY, QWEN_API_KEY]):
    raise SystemExit("请设置 SUPABASE_URL / SUPABASE_SERVICE_KEY / QWEN_API_KEY")

# ---------------- Logging ----------------
logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(levelname)s  %(message)s")
logger = logging.getLogger("qwen-news-pipeline")

logger.info(f"Using RAW_NEWS_TABLE = {RAW_NEWS_TABLE} | PIPELINE_MODE = {PIPELINE_MODE}")

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

# ---------------- Prompt ----------------
PROMPT_TPL = """
你是新闻编辑。以下是清洗后的新闻正文，请输出严格 JSON（UTF-8，无注释）：
字段：
- title: 新闻标题
- short_summary: ≤120字摘要
- long_summary: 200~300字摘要
- bullets: 3-6条要点，每条≤40字
- entities: {{ "org":[], "person":[], "location":[], "date":[] }}
- ai_suggestion: ≤80字的行动建议（企业/政策视角，可操作且不夸张）
- ai_suggestion_full: 150~300字的完整建议（包含背景、影响、建议动作）

要求：
- 只使用给定文本里的信息，不能虚构
- 保留关键数字与时间
- 忽略噪声
- 严格输出 JSON（不要任何额外说明或 Markdown 代码块）

标题提示：{title_hint}
正文：
\"\"\"{body}\"\"\"
""".strip()

# ---------------- Supabase IO ----------------
def fetch_articles_batch(offset: int, limit: int) -> List[Dict[str, Any]]:
    res = sb.table(RAW_NEWS_TABLE) \
        .select("id,title,content,publish_time,source_url,source_type") \
        .order("id", desc=True) \
        .range(offset, offset + limit - 1) \
        .execute()
    return res.data or []

def fetch_summaries_map(ids: List[str]) -> Dict[str, Dict[str, Any]]:
    if not ids:
        return {}
    # Supabase: where in (...)
    res = sb.table("news_summaries") \
        .select("news_id,short_summary,long_summary,ai_suggestion,ai_suggestion_full") \
        .in_("news_id", ids) \
        .execute()
    m = {}
    for r in (res.data or []):
        m[str(r["news_id"])] = r
    return m

# ---------------- Qwen API ----------------
DASHSCOPE_BASES = [
    "https://dashscope.aliyuncs.com",        # 国内
    "https://dashscope-intl.aliyuncs.com",   # 国际
]

def safe_truncate(s: str, max_len: int) -> str:
    return s[:max_len] if len(s) > max_len else s

def _strip_fence_to_json(s: str) -> dict:
    s = s.strip()
    if s.startswith("```"):
        s = s.strip("`").replace("json", "", 1).strip()
    i, j = s.find("{"), s.rfind("}")
    if 0 <= i < j:
        s = s[i:j+1]
    return json.loads(s)

def qwen_chat_json(prompt: str, timeout: int = 60, max_retries: int = 6) -> Dict[str, Any]:
    headers = {"Authorization": f"Bearer {QWEN_API_KEY}", "Content-Type": "application/json"}

    def make_payload_messages():
        return {
            "model": QWEN_MODEL,
            "input": {
                "messages": [
                    {"role": "system", "content": "你是严谨的新闻编辑，严格输出 JSON。"},
                    {"role": "user", "content": prompt}
                ]
            },
            "parameters": {"result_format": "json", "temperature": 0.2, "top_p": 0.8}
        }

    def make_payload_plain():
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
        payload = make_payload_plain() if use_plain_input else make_payload_messages()

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

# ---------------- Key Normalizer ----------------
def _normalize_summary_keys(d: Dict[str, Any]) -> Dict[str, Any]:
    """
    兼容大小写/驼峰/别名，确保包含 ai_suggestion / ai_suggestion_full 两键。
    不做“凭空生成”，仅做键名映射与基本类型兜底。
    """
    if not isinstance(d, dict):
        return {"title":"", "short_summary":"", "long_summary":"", "bullets":[], "entities":{}, "ai_suggestion":"", "ai_suggestion_full":""}

    def pick(keys, default=""):
        for k in keys:
            if k in d:
                return d.get(k)
            # 大小写兼容
            for kk in list(d.keys()):
                if kk.lower() == k.lower():
                    return d.get(kk)
        return default

    title = pick(["title"], "")
    short_summary = pick(["short_summary", "shortSummary"], "")
    long_summary = pick(["long_summary", "longSummary"], "")
    bullets = pick(["bullets", "points", "key_points", "keyPoints"], [])
    entities = pick(["entities"], {})
    ai_suggestion = pick(["ai_suggestion", "aiSuggestion", "action_suggestion", "actionSuggestion", "recommendation"], "")
    ai_suggestion_full = pick(["ai_suggestion_full", "aiSuggestionFull", "action_suggestion_full", "actionSuggestionFull", "recommendations"], "")

    # 类型兜底
    if not isinstance(bullets, list):
        try:
            if isinstance(bullets, str):
                bullets = json.loads(bullets)
            else:
                bullets = []
        except Exception:
            bullets = []
    if not isinstance(entities, dict):
        try:
            if isinstance(entities, str):
                entities = json.loads(entities)
            else:
                entities = {}
        except Exception:
            entities = {}

    out = {
        "title": title or "",
        "short_summary": short_summary or "",
        "long_summary": long_summary or "",
        "bullets": bullets or [],
        "entities": entities or {},
        "ai_suggestion": (ai_suggestion or "").strip(),
        "ai_suggestion_full": (ai_suggestion_full or "").strip(),
    }
    return out

# ---------------- Multi-Agent Prompts ----------------
SUMMARY_PROMPT = """
你是新闻编辑。基于提供正文，输出严格JSON（UTF-8，无注释），所有键必须出现：
{{
  "title": "",
  "short_summary": "",       // ≤120字
  "long_summary": "",        // 200~300字
  "bullets": ["", "", ""]    // 3~6条，每条≤40字
}}
要求：
- 仅依据原文，不得虚构；保留关键数字与时间；无说明文字、无Markdown。
- 若缺信息请置为 "" 或 []。
正文：
\"\"\"{clean_text}\"\"\"
""".strip()

ENTITIES_PROMPT = """
你是信息抽取器。抽取实体并输出严格JSON（UTF-8，无注释），所有键必须出现：
{{ "org":[], "person":[], "location":[], "date":[] }}
要求：
- 去重；保持原文表述；无解释；没有就空数组；仅依据给定文本。
文本：
\"\"\"{clean_text}\"\"\
""".strip()

ADVISOR_PROMPT = """
你是行业分析顾问。基于“摘要+要点+实体”，输出建议为严格JSON（UTF-8，无注释）：
{{
  "ai_suggestion": "",        // ≤80字，具体、可执行、不夸张
  "ai_suggestion_full": ""    // 150~300字：按“背景→影响→建议动作(1-3条)”组织
}}
要求：
- 仅使用给定信息，不得增加外部事实；避免空话。
- 两个字段都必须出现；若确无可建议，返回空字符串。
输入：
【短摘要】{short_summary}
【要点】{bullets_json}
【实体】{entities_json}
【可选长摘要】{long_summary}
""".strip()

def call_summarizer(clean_text_: str, title_hint: str = "") -> Dict[str, Any]:
    prompt = SUMMARY_PROMPT.format(clean_text=clean_text_)
    res = qwen_chat_json(prompt)
    return _normalize_summary_keys(res)

def call_entities(clean_text_: str) -> Dict[str, Any]:
    prompt = ENTITIES_PROMPT.format(clean_text=clean_text_)
    try:
        res = qwen_chat_json(prompt)
    except Exception:
        return {"org": [], "person": [], "location": [], "date": []}
    if not isinstance(res, dict):
        return {"org": [], "person": [], "location": [], "date": []}
    # 规整
    out = {"org": [], "person": [], "location": [], "date": []}
    for key in out.keys():
        v = res.get(key) or res.get(key.lower()) or res.get(key.upper())
        if isinstance(v, list):
            out[key] = v
        elif isinstance(v, str):
            try:
                vv = json.loads(v)
                if isinstance(vv, list): out[key] = vv
            except Exception:
                pass
    return out

def call_advisor(short_summary: str, long_summary: str, bullets: List[str], entities: Dict[str, Any]) -> Dict[str, Any]:
    prompt = ADVISOR_PROMPT.format(
        short_summary=short_summary or "",
        long_summary=long_summary or "",
        bullets_json=json.dumps(bullets or [], ensure_ascii=False),
        entities_json=json.dumps(entities or {}, ensure_ascii=False),
    )
    res = qwen_chat_json(prompt)
    norm = _normalize_summary_keys(res)
    # 兜底：若短建议为空而长建议有内容，用前80字填充短建议
    if not norm.get("ai_suggestion") and norm.get("ai_suggestion_full"):
        norm["ai_suggestion"] = (norm["ai_suggestion_full"][:80]).strip()
    return norm

# ---------------- Summarize ----------------
def summarize_with_qwen(clean_text_: str, title_hint: str = "") -> Dict[str, Any]:
    """single 模式：一次性产生全部字段（保留回滚能力）"""
    body = safe_truncate(clean_text_, 6000)
    prompt = PROMPT_TPL.format(title_hint=title_hint or "无", body=body)
    raw = qwen_chat_json(prompt)
    return _normalize_summary_keys(raw)

def upsert_summary(row: Dict[str, Any], clean_txt: str, summary: Dict[str, Any]) -> None:
    short_summary = (summary.get("short_summary") or "").strip()
    long_summary = (summary.get("long_summary") or "").strip()
    ai_suggestion = (summary.get("ai_suggestion") or "").strip()
    ai_suggestion_full = (summary.get("ai_suggestion_full") or "").strip()
    if (not ai_suggestion) and ai_suggestion_full:
        ai_suggestion = ai_suggestion_full[:80]
    payload = {
        "news_id": row["id"],
        "clean_text": clean_txt,
        "short_summary": short_summary[:120],
        "long_summary": long_summary[:1200],
        "ai_suggestion": ai_suggestion[:200],
        "ai_suggestion_full": ai_suggestion_full[:2000],
        "summary_json": summary,
        "model": QWEN_MODEL,
        "status": "ok",
        "updated_at": datetime.now(timezone.utc).isoformat()
    }
    sb.table("news_summaries").upsert(payload, on_conflict="news_id").execute()

from concurrent.futures import ThreadPoolExecutor

def run_pipeline_multi(max_batches: int = 10, batch_size: int = BATCH_SIZE, sleep_sec: float = 0.5, only_missing: bool = True):
    processed = 0
    for b in range(max_batches):
        rows = fetch_articles_batch(offset=b * batch_size, limit=batch_size)
        if not rows:
            logger.info("没有更多数据，处理完成。")
            break
        # 仅处理缺建议的（可配置）
        if only_missing:
            ids = [r["id"] for r in rows]
            smap = fetch_summaries_map(ids)
            def need(row):
                s = smap.get(str(row["id"]))
                if not s:
                    return True
                return not (s.get("ai_suggestion") and s.get("ai_suggestion_full"))
            rows = [r for r in rows if need(r)]
            if not rows:
                logger.info("本批全部已有建议，跳过。")
                continue
        for r in rows:
            news_id = r["id"]
            title_hint = r.get("title") or ""
            raw = r.get("content") or ""
            try:
                clean = clean_text(raw)
                if not clean:
                    logger.info(f"[SKIP] id={news_id} 清洗后为空")
                    continue
                with ThreadPoolExecutor(max_workers=2) as ex:
                    fut_sum = ex.submit(call_summarizer, clean, title_hint)
                    fut_ent = ex.submit(call_entities, clean)
                    summ = fut_sum.result()
                    ents = fut_ent.result()
                adv = call_advisor(
                    short_summary=summ.get("short_summary",""),
                    long_summary=summ.get("long_summary",""),
                    bullets=summ.get("bullets",[]),
                    entities=ents or {},
                )
                # 合并：以总结器为基，补入实体与建议
                summary = {
                    "title": summ.get("title",""),
                    "short_summary": summ.get("short_summary",""),
                    "long_summary": summ.get("long_summary",""),
                    "bullets": summ.get("bullets",[]),
                    "entities": ents or {},
                    "ai_suggestion": adv.get("ai_suggestion",""),
                    "ai_suggestion_full": adv.get("ai_suggestion_full",""),
                }
                upsert_summary(r, clean, summary)
                processed += 1
                logger.info(f"✅(multi) 已处理 {news_id} | {summary.get('short_summary','')[:30]}...")
            except Exception as e:
                logger.error(f"[ERROR] id={news_id}: {e}", exc_info=True)
                continue
            time.sleep(sleep_sec)
    logger.info(f"(multi) 管线结束，总处理条数：{processed}")

# ---------------- Pipeline ----------------
def run_pipeline(max_batches: int = 10, batch_size: int = BATCH_SIZE, sleep_sec: float = 0.5, only_missing: bool = False):
    if PIPELINE_MODE == "multi":
        return run_pipeline_multi(max_batches=max_batches, batch_size=batch_size, sleep_sec=sleep_sec, only_missing=True)
    processed = 0
    for b in range(max_batches):
        rows = fetch_articles_batch(offset=b * batch_size, limit=batch_size)
        if not rows:
            logger.info("没有更多数据，处理完成。")
            break
        for r in rows:
            news_id = r["id"]
            title_hint = r.get("title") or ""
            raw = r.get("content") or ""
            try:
                clean = clean_text(raw)
                if not clean:
                    logger.info(f"[SKIP] id={news_id} 清洗后为空")
                    continue
                summary = summarize_with_qwen(clean, title_hint)
                upsert_summary(r, clean, summary)
                processed += 1
                logger.info(f"✅(single) 已处理 {news_id} | {summary.get('short_summary','')[:30]}...")
            except Exception as e:
                logger.error(f"[ERROR] id={news_id}: {e}", exc_info=True)
                continue
            time.sleep(sleep_sec)
    logger.info(f"(single) 管线结束，总处理条数：{processed}")

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["single","multi"], default=PIPELINE_MODE)
    parser.add_argument("--batches", type=int, default=10)
    parser.add_argument("--batch-size", type=int, default=BATCH_SIZE)
    parser.add_argument("--sleep", type=float, default=0.5)
    parser.add_argument("--only-missing", action="store_true", help="仅处理缺少建议的新闻（multi模式内置为True）")
    args = parser.parse_args()
    logger.info(f"Qwen 模型: {QWEN_MODEL} | 批大小: {args.batch_size} | 模式: {args.mode} | 表: {RAW_NEWS_TABLE}")
    # 覆盖一次运行模式
    PIPELINE_MODE = args.mode
    run_pipeline(max_batches=args.batches, batch_size=args.batch_size, sleep_sec=args.sleep, only_missing=args.only_missing)