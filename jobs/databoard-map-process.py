# -*- coding: utf-8 -*-
"""
Unified Events → Facts (Qwen3 + Supabase)  — 方案B风格（精简 .env + 命令行参数）
----------------------------------------------------
- 仅允许在 .env 里配置 4 个键：SUPABASE_URL、SUPABASE_SERVICE_KEY、QWEN_API_KEY、QWEN_MODEL；
  其它运行参数（时间窗、批次大小、端点区域等）全部用命令行参数 --args 指定。
- 示例：
  python databoard-map-process.py --days 7 --batch-size 15 --sleep 0.2 --region cn --fact-table fact_events
"""

import os, re, json, time, random, logging
from typing import Dict, Any, List, Optional
from datetime import datetime, timezone, timedelta
from pathlib import Path

from postgrest.exceptions import APIError  # type: ignore

# 视图内的四类来源（来自 v_source_events / v_events_geocoded）
VIEW_SOURCE_TYPES = {"news", "competitor", "opportunity", "paper"}
# 可选：命令行筛选（包含/排除），在 main() 里赋值
TYPE_FILTER_INCLUDE = set()
TYPE_FILTER_EXCLUDE = set()

# 批处理中保持稳定的时间窗起点（一次计算，多批复用）
STABLE_SINCE_ISO: Optional[str] = None

# 可选：加载 .env（若安装了 python-dotenv 且找到文件，则覆盖 os.environ）
try:
    from dotenv import load_dotenv, find_dotenv  # type: ignore
    _DOTENV_AVAILABLE = True
except Exception:
    _DOTENV_AVAILABLE = False

if _DOTENV_AVAILABLE:
    _dotenv_path = find_dotenv()
    if _dotenv_path:
        load_dotenv(_dotenv_path, override=True)


# ---------------- 基本密钥仅来自 .env/环境变量（其余走命令行参数） ----------------
import requests
from dateutil import parser as dateparser
from supabase import create_client, Client
SUPABASE_URL = os.environ.get("SUPABASE_URL") or "https://YOUR-PROJECT.supabase.co"
SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_KEY") or "YOUR_SERVICE_ROLE_KEY"
QWEN_API_KEY = os.environ.get("QWEN_API_KEY") or "YOUR_QWEN_API_KEY"
QWEN_MODEL   = os.environ.get("QWEN_MODEL") or "qwen3-72b-instruct"  # 用它来选择大模型

# 运行参数的默认值（会被命令行参数覆盖）
DASHSCOPE_REGION    = "cn"
QWEN_OPENAI_COMPAT  = True
BATCH_SIZE          = 20
MAX_BATCHES         = 20
SLEEP_BETWEEN_CALLS = 0.4
DAYS_WINDOW         = ""  # 由 --days 设置
UNIFIED_VIEW        = "v_events_ready"
DIM_CN_REGION       = "dim_cn_region"
DIM_COUNTRY         = "dim_country"
STATE_FILE          = ".databoard_map_state.json"
GEO_BY_LLM          = True
LOG_LLM             = False
LOG_GEO             = False
SUMMARY_PREVIEW_CHARS = 120

# 关键敏感变量校验
_missing = [k for k,v in {"SUPABASE_SERVICE_KEY": SUPABASE_KEY, "QWEN_API_KEY": QWEN_API_KEY}.items() if not v]
if _missing:
    raise SystemExit(f"缺少关键配置：{', '.join(_missing)}。请在 .env / 环境变量中提供。")


# ---------------- 命令行参数（覆盖运行行为） ----------------
import argparse

def parse_args():
    p = argparse.ArgumentParser(description="Unified Events → Facts (Qwen3 + Supabase)")
    p.add_argument("--days", type=int, default=7, help="仅处理近N天（示例：7、3；默认不过滤）")
    p.add_argument("--batch-size", type=int, default=20, help="每批处理条数")
    p.add_argument("--max-batches", type=int, default=20, help="最多处理批次数")
    p.add_argument("--sleep", type=float, default=0.4, help="两次 LLM 调用间的暂停秒数")
    p.add_argument("--unified-view", default="v_events_ready", help="读取的统一视图名")
    p.add_argument("--dim-cn-region", default="dim_cn_region")
    p.add_argument("--dim-country", default="dim_country")
    p.add_argument("--fact-table", default="fact_events")
    p.add_argument("--region", default="cn", choices=["cn","intl","finance"], help="大模型区域端点")
    p.add_argument("--openai-compat", dest="openai_compat", action="store_true", help="使用兼容接口（默认开）")
    p.add_argument("--no-openai-compat", dest="openai_compat", action="store_false", help="关闭兼容接口")
    p.add_argument("--include-types", default="", help="仅处理这些类型，逗号分隔（可选：news,competitor,opportunity,paper）")
    p.add_argument("--exclude-types", default="", help="排除这些类型，逗号分隔（可选：news,competitor,opportunity,paper）")
    p.add_argument("--geo-by-llm", dest="geo_by_llm", action="store_true", help="优先使用大模型从文本判断国家/省份")
    p.add_argument("--no-geo-by-llm", dest="geo_by_llm", action="store_false", help="关闭基于大模型的地理判断")
    p.add_argument("--log-llm", dest="log_llm", action="store_true", help="输出每条记录的 LLM 摘要/关键词/原始地理判断（实时）")
    p.add_argument("--no-log-llm", dest="log_llm", action="store_false")
    p.add_argument("--log-geo", dest="log_geo", action="store_true", help="输出每条记录的最终地理编码与来源（实时）")
    p.add_argument("--no-log-geo", dest="log_geo", action="store_false")
    p.add_argument("--summary-chars", type=int, default=120, help="摘要预览字符数（仅用于终端可视化，不影响存储）")
    p.set_defaults(openai_compat=True)
    p.set_defaults(geo_by_llm=True)
    p.set_defaults(log_llm=False)
    p.set_defaults(log_geo=False)
    return p.parse_args()

# Helper: parse comma-separated type list to set, only allow known source types
def _csv_types_to_set(s: str) -> set:
    ss = [x.strip().lower() for x in (s or "").split(",") if x.strip()]
    return {x for x in ss if x in VIEW_SOURCE_TYPES}

# ---------------- 日志 & 会话 ----------------
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("unified-events→facts")
SESSION = requests.Session()

# ---------------- Supabase 客户端 ----------------
sb: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

try:
    if _DOTENV_AVAILABLE and _dotenv_path:
        log.info(f"已加载 .env: {_dotenv_path}")
except Exception:
    pass

# ---------------- Qwen 兼容接口封装 ----------------
DASHSCOPE_COMPAT_BASES = {
    "cn": "https://dashscope.aliyuncs.com/compatible-mode/v1",
    "intl": "https://dashscope-intl.aliyuncs.com/compatible-mode/v1",
    "finance": "https://dashscope-finance.aliyuncs.com/compatible-mode/v1",
}

def _strip_code_fence_to_json(s: str) -> dict:
    s = (s or "").strip()
    if s.startswith("```"):
        s = re.sub(r'^\s*```(?:json)?\s*', '', s, flags=re.I)
        s = re.sub(r'\s*```\s*$', '', s)
    i, j = s.find("{"), s.rfind("}")
    if 0 <= i < j:
        s = s[i:j+1]
    return json.loads(s)

PROMPT_SUMMARY = (
    "你是一名严谨的中英文信息总结与地理定位助手。无论输入是什么语言，请始终用简体中文输出。"
    "如果原文为英文论文或英文资讯，请先理解后用中文进行专业概括，不要保留英文句子。"
    "你必须判断事件发生的国家（优先返回 ISO3，如 CHN/USA/DEU；若不确定，返回 null），不要因为出现中文或中国机构名就默认中国。"
    
    "**重要：省份信息提取规则（仅适用于中国）**"
    "1. **优先从 URL 中提取省份**："
    "   - 检查 URL 是否包含省份拼音或缩写（如 beijing.gov.cn → 北京市，zj.gov.cn → 浙江省，gd.gov.cn → 广东省）"
    "   - 检查 URL 是否包含省份中文名（如 ...北京... → 北京市）"
    "2. **其次从标题中提取**：如果标题包含省份名称（如'北京市'、'广东省'、'浙江省'等）"
    "3. **最后从正文中提取**：如果正文明确提到省份"
    "4. 如果确实是全国性政策/论文，可以标注为'全国'或留空"
    "5. **不要因为政策/论文内容本身没有省份就返回 null，一定要先检查 URL 和标题！**"
    "6. 对于政策、法规、通知等文档，来源 URL 通常包含省份信息，请仔细检查。"
    
    "请仅返回严格的 JSON 对象，字段如下："
    "{\\\"summary\\\":\\\"<=300字的简体中文摘要\\\",\\\"keywords\\\":[\\\"关键词1\\\",...],\\\"country\\\":\\\"ISO3或国家名(如 CHN/中国/USA/美国)\\\",\\\"province\\\":\\\"中国省级行政区中文名(如 广东省、北京市、全国)，若完全无法判断才留空或null\\\"}。"
    "请避免臆测；当无法判断时，对应字段置为 null。禁止输出除 JSON 以外的任何内容。"
)

def qwen_summary(payload: Dict[str, Any], timeout: int = 60, max_retries: int = 6) -> Dict[str, Any]:
    """调用 /chat/completions，返回 {summary, keywords}，强制 JSON。"""
    base = DASHSCOPE_COMPAT_BASES.get(DASHSCOPE_REGION, DASHSCOPE_COMPAT_BASES["cn"])
    url = f"{base}/chat/completions"
    headers = {"Authorization": f"Bearer {QWEN_API_KEY}", "Content-Type": "application/json"}

    def body(use_resp_fmt=True):
        b = {
            "model": QWEN_MODEL,
            "messages": [
                {"role": "system", "content": PROMPT_SUMMARY},
                {"role": "user", "content": json.dumps(payload, ensure_ascii=False)}
            ],
            "stream": False,
        }
        if use_resp_fmt:
            b["response_format"] = {"type": "json_object"}
            
        return b

    attempt, use_resp = 0, QWEN_OPENAI_COMPAT
    while True:
        attempt += 1
        try:
            resp = SESSION.post(url, headers=headers, json=body(use_resp), timeout=timeout)
            if resp.status_code == 200:
                data = resp.json()
                choices = data.get("choices") or []
                text = (choices[0].get("message") or {}).get("content") if choices else ""
                if not text:
                    raise ValueError("empty choices.content")
                try:
                    return json.loads(text)
                except Exception:
                    # 容错：去掉围栏
                    i, j = text.find("{"), text.rfind("}")
                    if 0 <= i < j:
                        return json.loads(text[i:j+1])
                    raise

            if resp.status_code == 400 and "response_format" in (resp.text or "") and use_resp:
                log.warning("兼容接口不支持 response_format，降级仅用提示词约束 JSON")
                use_resp = False
                continue

            if resp.status_code in (429, 500, 502, 503, 504):
                wait = min(2 ** (attempt - 1), 20) * (1 + random.random())
                log.warning(f"{resp.status_code}, {wait:.1f}s 后重试")
                time.sleep(wait); continue

            if resp.status_code in (401, 403):
                raise RuntimeError(f"Qwen 鉴权/权限错误 {resp.status_code}: {resp.text[:200]}")
            resp.raise_for_status()

        except Exception as e:
            if attempt < max_retries:
                wait = min(2 ** (attempt - 1), 10)
                log.warning(f"网络异常第{attempt}次重试，睡{wait:.1f}s | {e}")
                time.sleep(wait); continue
            raise

# ---------------- 中文校验与兜底翻译 ----------------
_CHN_RE = re.compile(r"[\u4e00-\u9fff]")

def _has_chinese(s: Optional[str]) -> bool:
    return bool(_CHN_RE.search(s or ""))

def qwen_fix_to_zh(result: Dict[str, Any], timeout: int = 40) -> Dict[str, Any]:
    """当模型偶发输出英文时，将现有 JSON 的值翻译为简体中文并保持键不变。"""
    base = DASHSCOPE_COMPAT_BASES.get(DASHSCOPE_REGION, DASHSCOPE_COMPAT_BASES["cn"])
    url = f"{base}/chat/completions"
    headers = {"Authorization": f"Bearer {QWEN_API_KEY}", "Content-Type": "application/json"}
    content = json.dumps(result, ensure_ascii=False)
    body = {
        "model": QWEN_MODEL,
        "messages": [
            {"role": "system", "content": "请把下列 JSON 中的所有值翻译为简体中文，保持键名与结构完全一致，仅返回 JSON。"},
            {"role": "user", "content": content}
        ],
        "response_format": {"type": "json_object"},
        "stream": False,
    }
    resp = SESSION.post(url, headers=headers, json=body, timeout=timeout)
    if resp.status_code == 200:
        data = resp.json()
        choices = data.get("choices") or []
        text = (choices[0].get("message") or {}).get("content") if choices else ""
        if text:
            try:
                return json.loads(text)
            except Exception:
                i, j = text.find("{"), text.rfind("}")
                if 0 <= i < j:
                    return json.loads(text[i:j+1])
    # 失败则原样返回
    return result

# ---------------- 维表映射 ----------------
PROV_MAP: Dict[str,str] = {}
COUNTRY_MAP: Dict[str,str] = {}

def load_province_map() -> Dict[str, str]:
    res = sb.table(DIM_CN_REGION).select("name_zh,code").eq("level","province").execute()
    return {r["name_zh"]: r["code"] for r in (res.data or [])}

def load_country_map() -> Dict[str,str]:
    res = sb.table(DIM_COUNTRY).select("iso3,name_en,name_zh").execute()
    m: Dict[str,str] = {}
    for r in (res.data or []):
        iso3 = r["iso3"]
        m[iso3] = iso3
        if r.get("name_en"): m[r["name_en"].lower()] = iso3
        if r.get("name_zh"): m[r["name_zh"]] = iso3
    return m

def name_to_province_code(name: Optional[str]) -> Optional[str]:
    if not name: return None
    name = name.strip()
    if name in PROV_MAP: return PROV_MAP[name]
    simp = re.sub(r'(省|市|自治区|壮族自治区|回族自治区|维吾尔自治区|特别行政区)$', '', name)
    for k,v in PROV_MAP.items():
        if k == name or k.startswith(simp) or name.startswith(k):
            return v
    return None

def name_to_iso3(country_name_or_iso3: Optional[str]) -> Optional[str]:
    if not country_name_or_iso3: return None
    key = country_name_or_iso3.strip()
    return COUNTRY_MAP.get(key) or COUNTRY_MAP.get(key.lower())

def norm_time(ts: Optional[str], fallback: Optional[str]) -> Optional[str]:
    for cand in [ts, fallback]:
        if not cand: continue
        try:
            dt = dateparser.parse(cand)
            if not dt.tzinfo:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc).isoformat()
        except Exception:
            continue
    return None

# ========= 省份/国家启发式补全（在 LLM 之后作为兜底） =========

# 常见省份拼音/缩写命中（可按需扩充）
PROV_PINYIN_MAP = {
    "bj": "北京市", "beijing": "北京市",
    "sh": "上海市",  "shanghai": "上海市",
    "tj": "天津市",  "tianjin": "天津市",
    "cq": "重庆市",  "chongqing": "重庆市",
    "hebei": "河北省",
    "sx": "山西省", "shanxi": "山西省",
    "ln": "辽宁省", "liaoning": "辽宁省",
    "jl": "吉林省", "jilin": "吉林省",
    "hlj": "黑龙江省", "heilongjiang": "黑龙江省",
    "shandong": "山东省", "sd": "山东省",
    "js": "江苏省", "jiangsu": "江苏省",
    "zj": "浙江省", "zhejiang": "浙江省",
    "ah": "安徽省", "anhui": "安徽省",
    "fj": "福建省", "fujian": "福建省",
    "jx": "江西省", "jiangxi": "江西省",
    "hb": "湖北省", "hubei": "湖北省",
    "hn": "湖南省", "hunan": "湖南省",
    "gd": "广东省", "guangdong": "广东省",
    "gx": "广西壮族自治区", "guangxi": "广西壮族自治区",
    "hain": "海南省", "hainan": "海南省",
    "sc": "四川省", "sichuan": "四川省",
    "gz": "贵州省", "guizhou": "贵州省",
    "yn": "云南省", "yunnan": "云南省",
    "xz": "西藏自治区", "xizang": "西藏自治区",
    "sn": "陕西省", "shaanxi": "陕西省",
    "gs": "甘肃省", "gansu": "甘肃省",
    "qh": "青海省", "qinghai": "青海省",
    "nx": "宁夏回族自治区", "ningxia": "宁夏回族自治区",
    "xj": "新疆维吾尔自治区", "xinjiang": "新疆维吾尔自治区",
    "nmg": "内蒙古自治区", "neimenggu": "内蒙古自治区",
    "hk": "香港特别行政区", "hongkong": "香港特别行政区", "hong_kong": "香港特别行政区",
    "mo": "澳门特别行政区", "macau": "澳门特别行政区", "macao": "澳门特别行政区",
}

PROV_NAME_RE = None  # 将在 main() 装载 PROV_MAP 后生成

def _cn_prov_regex() -> "re.Pattern":
    """构造中国省级中文名的正则，包含全称与去尾简写（如“广东省”/“广东”）。"""
    names = list(PROV_MAP.keys())
    simp = [re.sub(r'(省|市|自治区|壮族自治区|回族自治区|维吾尔自治区|特别行政区)$', '', n) for n in names]
    all_names = list(set(names + simp))
    pat = "|".join(re.escape(x) for x in sorted(all_names, key=len, reverse=True))
    return re.compile(pat)

def infer_province_from_text(*texts: Optional[str]) -> Optional[str]:
    """从文本中正则命中中文省名，返回 province_code。"""
    global PROV_NAME_RE
    if PROV_NAME_RE is None:
        return None
    txt = " ".join([t or "" for t in texts])
    m = PROV_NAME_RE.search(txt)
    if m:
        return name_to_province_code(m.group(0))
    return None

def infer_province_from_url(url: Optional[str]) -> Optional[str]:
    """从域名的中文、省份拼音/缩写推测省份。"""
    if not url:
        return None
    try:
        host = re.sub(r'^https?://', '', url).split('/')[0]
    except Exception:
        return None
    # 1) 主机名直接中文命中
    pc = infer_province_from_text(host)
    if pc:
        return pc
    # 2) 拼音/缩写命中（如 zjhr.com、gd.gov.cn）
    host_lower = host.lower()
    for key, prov_zh in PROV_PINYIN_MAP.items():
        if key in host_lower:
            return name_to_province_code(prov_zh)
    # 3) *.gov.cn 子域（如 zj.gov.cn / gd.gov.cn）
    segs = host_lower.split('.')
    if len(segs) >= 3 and segs[-2:] == ["gov", "cn"]:
        sub = segs[-3]
        if sub in PROV_PINYIN_MAP:
            return name_to_province_code(PROV_PINYIN_MAP[sub])
    return None

def looks_chinese(*texts: Optional[str]) -> bool:
    txt = " ".join([t or "" for t in texts])
    return bool(re.search(r'[\u4e00-\u9fff]', txt))


def infer_country_fallback(url: Optional[str], *texts: Optional[str]) -> Optional[str]:
    """当省份/国家都缺失时：若域名为 .cn 或文本含中文，兜底为 CHN；否则 None。"""
    try:
        host = re.sub(r'^https?://', '', url or "").split('/')[0].lower()
    except Exception:
        host = ""
    if host.endswith(".cn") or looks_chinese(*texts):
        return "CHN"
    return None

# 依据 ccTLD 推断国家（尽量少猜；只在明确 ccTLD 时返回）
TLD_TO_ISO3 = {
    "cn": "CHN", "us": "USA", "uk": "GBR", "gb": "GBR", "de": "DEU", "fr": "FRA",
    "jp": "JPN", "kr": "KOR", "ca": "CAN", "au": "AUS", "ru": "RUS", "in": "IND",
    "br": "BRA", "it": "ITA", "es": "ESP", "nl": "NLD", "se": "SWE", "ch": "CHE",
    "at": "AUT", "il": "ISR", "sg": "SGP", "tw": "TWN", "hk": "HKG"
}

def infer_country_from_url(url: Optional[str]) -> Optional[str]:
    if not url:
        return None
    try:
        host = re.sub(r'^https?://', '', url).split('/')[0].lower()
    except Exception:
        return None
    segs = host.split('.')
    if len(segs) < 2:
        return None
    tld = segs[-1]
    # 处理二级 ccTLD（如 .co.uk, .com.au）
    if tld in ("uk", "gb", "au") and len(segs) >= 3:
        # 取最后一个片段作为 ccTLD
        pass
    # 常见二级国别 tld
    if tld in TLD_TO_ISO3:
        return TLD_TO_ISO3[tld]
    if len(segs) >= 2 and segs[-2] in TLD_TO_ISO3 and tld in ("uk","gb","au","nz"):
        return TLD_TO_ISO3[segs[-2]]
    return None

# ---------------- 时间窗（近N天）工具 ----------------

def _compute_since_iso() -> Optional[str]:
    """若设置了 DAYS_WINDOW（正整数），返回 UTC 截止时间的 ISO 字符串；否则返回 None。"""
    if not DAYS_WINDOW:
        return None
    try:
        days = int(DAYS_WINDOW)
        if days <= 0:
            return None
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        return cutoff.isoformat()
    except Exception:
        return None

# ---------------- 读取统一视图 ----------------
def fetch_unified_batch(offset: int, limit: int) -> List[Dict[str,Any]]:
    res = (
        sb.table(UNIFIED_VIEW)
        .select("*")
        .order("time_hint", desc=True, nullsfirst=False)
        .order("src_id", desc=True)
        .range(offset, offset + limit - 1)
        .execute()
    )
    return res.data or []


# ---------------- 目标表存在性检查（避免白跑 LLM） ----------------

def _table_exists(table: str) -> bool:
    try:
        # 选任意列；不存在表会抛 PGRST205
        sb.table(table).select("*").limit(1).execute()
        return True
    except Exception as e:
        try:
            if isinstance(e, APIError):
                err = getattr(e, "args", [None])[0] or {}
                if isinstance(err, dict) and err.get("code") == "PGRST205":
                    return False
        except Exception:
            pass
        # 其他错误一律认为存在（避免误杀），由后续流程处理
        return True

FACT_TABLE = "fact_events"

def ensure_fact_table_exists_or_die():
    if _table_exists(FACT_TABLE):
        return
    ddl = (
        "-- 在 Supabase SQL Editor 执行，创建统一事实表\n"
        "create table if not exists public.fact_events (\n"
        "  id bigserial primary key,\n"
        "  type text not null,\n"
        "  title text not null,\n"
        "  url text not null unique,\n"
        "  source text,\n"
        "  published_at timestamptz,\n"
        "  country_iso3 text references public.dim_country(iso3),\n"
        "  province_code text references public.dim_cn_region(code),\n"
        "  summary text,\n"
        "  keywords text[],\n"
        "  row_hash text not null,\n"
        "  src_table text not null,\n"
        "  src_id text not null,\n"
        "  payload jsonb,\n"
        "  created_at timestamptz default now()\n"
        ");\n"
        "create unique index if not exists idx_fact_events_row_hash on public.fact_events(row_hash);\n"
        "create index if not exists idx_fact_events_pub_at on public.fact_events(published_at desc);\n"
        "create index if not exists idx_fact_events_geo on public.fact_events(country_iso3, province_code);\n"
    )
    log.error("未找到表 public.fact_events（PGRST205）。你可以：1) 运行我下面的 DDL 创建它；或 2) 改代码回退到分表。\n\n" + ddl)
    raise SystemExit(1)

# ---------------- 主处理 ----------------

def process_row(row: Dict[str,Any]) -> Dict[str,Any]:
    # 送入 LLM 的负载（仅用于摘要/关键词）
    payload = {
        "title": row.get("title"),
        "content": (row.get("content") or "")[:6000],
        "url": row.get("url_norm") or row.get("url"),
        "source": row.get("source"),
        "type": row.get("type"),
        "time_hint": row.get("published_at")
    }
    s = qwen_summary(payload)

    # 强制中文：若摘要不含中文字符，则进行一次 JSON 内值的中文化兜底
    if not _has_chinese(s.get("summary")):
        s = qwen_fix_to_zh(s)
    # 同时确保关键词为中文（若关键词存在且大多为英文，做一次兜底）
    if isinstance(s.get("keywords"), list):
        joined = " ".join([str(x) for x in s["keywords"]])
        if not _has_chinese(joined):
            s = qwen_fix_to_zh(s)

    # ===== 国家与省份推断（优先 LLM，再回退启发式） =====
    country_iso3 = row.get("country_iso3")
    province_code = row.get("province_code")
    url_for_geo = row.get("url_norm") or row.get("url")

    # 0) 尝试从 LLM 结果映射
    geo_source = None
    if GEO_BY_LLM:
        llm_country = s.get("country") if isinstance(s, dict) else None
        llm_province = s.get("province") if isinstance(s, dict) else None
        # 优先信任 LLM：有则直接覆盖源视图同名字段
        if llm_province:
            _pc = name_to_province_code(str(llm_province))
            if _pc:
                province_code = _pc
        if llm_country:
            _c3 = name_to_iso3(str(llm_country))
            if _c3:
                country_iso3 = _c3
                # 业务规则：若 LLM 判定为非中国国家，则按“国家=国外处理”并清空中国省份
                if country_iso3 != "CHN":
                    province_code = None
        if province_code or country_iso3:
            geo_source = "llm"

    # 1) 若国家仍缺失，尝试根据 ccTLD 推断
    c_from_url = None
    if not country_iso3:
        c_from_url = infer_country_from_url(url_for_geo)
        if c_from_url:
            country_iso3 = c_from_url
            if not geo_source:
                geo_source = "url"
    # 2) 禁止盲目“省份=>中国”：仅当 LLM 明确判定中国或 URL 明确是 .cn 时，才将国家设为 CHN
    if not country_iso3 and province_code:
        llm_country_norm = None
        try:
            llm_country_norm = (s.get("country") if isinstance(s, dict) else None)
        except Exception:
            llm_country_norm = None
        llm_cn = str(llm_country_norm or "").strip().lower()
        if llm_cn in ("chn","cn","china","中国","中华人民共和国") or c_from_url == "CHN":
            country_iso3 = "CHN"
    # 3) 兜底规则（避免把英文论文误判为中国，不再根据"包含中文"来强制 CHN）
    #    若仍为空就保持 NULL，让前端统计为"未知/其他"。
    
    # 4) 特别处理：如果是政策/论文数据且没有省份，尝试从 URL 和标题推断
    #    这对于政策类数据很重要，因为很多政策可能是全国性的，但可以从来源推断省份
    if row.get("type") == "paper" and not province_code:
        # 优先从 URL 推断
        inferred_prov = infer_province_from_url(url_for_geo)
        if inferred_prov:
            province_code = inferred_prov
            if not geo_source:
                geo_source = "url_inference"
        else:
            # 如果 URL 推断失败，尝试从标题中提取省份名称
            title_text = row.get("title") or ""
            inferred_prov = infer_province_from_text(title_text)
            if inferred_prov:
                province_code = inferred_prov
                if not geo_source:
                    geo_source = "title_inference"
        # 如果推断出省份，确保国家是中国
        if province_code and not country_iso3:
            country_iso3 = "CHN"

    # 可视化：生成摘要预览
    _summary_preview = (s.get("summary") or "")[:SUMMARY_PREVIEW_CHARS] if isinstance(s, dict) else None

    rec = {
        "type": row.get("type"),
        "title": row.get("title"),
        "url": url_for_geo,
        "source": row.get("source"),
        "published_at": row.get("published_at"),
        "country_iso3": country_iso3,
        "province_code": province_code,
        "summary": s.get("summary"),
        "keywords": s.get("keywords"),
        "row_hash": row.get("row_hash"),
        "src_table": row.get("src_table"),
        "src_id": str(row.get("src_id")),
        "payload": {
            "lang_hint": row.get("lang_hint"),
            "geo_source": geo_source,
            "llm_country": (s.get("country") if isinstance(s, dict) else None),
            "llm_province": (s.get("province") if isinstance(s, dict) else None),
            "summary_preview": _summary_preview,
            "keywords": s.get("keywords"),
        }
    }
    return rec

def route_and_insert(rec: Dict[str,Any]) -> str:
    try:
        sb.table(FACT_TABLE).upsert(rec, on_conflict="url").execute()
        return FACT_TABLE
    except APIError as e:
        err = getattr(e, "args", [None])[0] or {}
        if isinstance(err, dict) and err.get("code") == "PGRST205":
            log.error("表 public.fact_events 不存在。建议先创建统一事实表，或将代码回退为按类型分别写入既有表（如 fact_news 等）。")
        raise

def run_once(offset=0, limit=BATCH_SIZE, sleep_sec=SLEEP_BETWEEN_CALLS) -> int:
    # 使用 main() 里计算好的稳定时间窗，避免每批次滑动导致分页错乱
    since_iso = STABLE_SINCE_ISO

    q = sb.table(UNIFIED_VIEW).select("*")
    if since_iso:
        q = q.gte("published_at", since_iso)

    # 尽可能下推类型过滤到服务端，减少无效网络与分页偏移
    if TYPE_FILTER_INCLUDE:
        q = q.in_("type", sorted(TYPE_FILTER_INCLUDE))
    elif TYPE_FILTER_EXCLUDE:
        q = q.not_.in_("type", sorted(TYPE_FILTER_EXCLUDE))

    rows = (
        q.order("published_at", desc=True, nullsfirst=False)
         .order("src_id", desc=True)
         .range(offset, offset + limit - 1)
         .execute()
    ).data or []

    if not rows:
        log.info("无更多记录。" + (f"（时间窗：近{DAYS_WINDOW}天）" if since_iso else ""))
        return 0

    def _short(s: Optional[str], n: int = 40) -> str:
        t = (s or "").replace("\n", " ").replace("\r", " ")
        return (t[:n] + "…") if len(t) > n else t

    upserts = 0
    for r in rows:
        try:
            rec = process_row(r)
            if LOG_LLM:
                p = rec.get("payload") or {}
                log.info(
                    f"[LLM] {rec.get('type')} | {_short(rec.get('title'), 40)} | country={p.get('llm_country')} | province={p.get('llm_province')} | kw={','.join((rec.get('keywords') or [])[:5]) if isinstance(rec.get('keywords'), list) else ''} | sum={_short(p.get('summary_preview'), SUMMARY_PREVIEW_CHARS)}"
                )
            where = route_and_insert(rec)
            if where == "fact_events":
                upserts += 1
            if LOG_GEO:
                p = rec.get("payload") or {}
                if rec.get('country_iso3') and rec.get('country_iso3') != 'CHN':
                    log.info(
                        f"[GEO] iso3={rec.get('country_iso3')} | prov={rec.get('province_code')} | source={p.get('geo_source')} | url={_short(rec.get('url'), 80)}"
                    )
                else:
                    log.info(
                        f"[GEO] iso3={rec.get('country_iso3')} | prov={rec.get('province_code')} | source={p.get('geo_source')}"
                    )
            log.info(f"[upsert] fact_events | {rec.get('type')} | {_short(rec.get('title'), 40)}")
        except Exception as e:
            log.exception(f"处理失败: {r.get('src_table')}:{r.get('src_id')} | {e}")
        time.sleep(sleep_sec)
    return upserts

def main():
    global PROV_MAP, COUNTRY_MAP
    args = parse_args()
    global UNIFIED_VIEW, DIM_CN_REGION, DIM_COUNTRY, BATCH_SIZE, MAX_BATCHES, SLEEP_BETWEEN_CALLS, DAYS_WINDOW, DASHSCOPE_REGION, QWEN_OPENAI_COMPAT, FACT_TABLE, GEO_BY_LLM, LOG_LLM, LOG_GEO, SUMMARY_PREVIEW_CHARS
    UNIFIED_VIEW = args.unified_view
    DIM_CN_REGION = args.dim_cn_region
    DIM_COUNTRY = args.dim_country
    BATCH_SIZE = args.batch_size
    MAX_BATCHES = args.max_batches
    SLEEP_BETWEEN_CALLS = args.sleep
    DAYS_WINDOW = str(args.days or "").strip()
    DASHSCOPE_REGION = args.region
    QWEN_OPENAI_COMPAT = args.openai_compat
    FACT_TABLE = args.fact_table
    GEO_BY_LLM = bool(args.geo_by_llm)
    LOG_LLM = bool(args.log_llm)
    LOG_GEO = bool(args.log_geo)
    try:
        SUMMARY_PREVIEW_CHARS = max(20, int(args.summary_chars))
    except Exception:
        SUMMARY_PREVIEW_CHARS = 120

    global TYPE_FILTER_INCLUDE, TYPE_FILTER_EXCLUDE
    TYPE_FILTER_INCLUDE = _csv_types_to_set(args.include_types)
    TYPE_FILTER_EXCLUDE = _csv_types_to_set(args.exclude_types)
    if TYPE_FILTER_INCLUDE:
        log.info(f"仅处理类型: {sorted(TYPE_FILTER_INCLUDE)}")
    if TYPE_FILTER_EXCLUDE:
        log.info(f"排除类型: {sorted(TYPE_FILTER_EXCLUDE)}")

    # 现在再打印所用模型与端点（region/compat 已更新）
    model_src = "env/.env" if os.environ.get("QWEN_MODEL") else "DEFAULT"
    log.info(f"LLM 使用模型: {QWEN_MODEL}（来源: {model_src}）, 兼容模式={QWEN_OPENAI_COMPAT}, 区域={DASHSCOPE_REGION}, 地理由LLM={GEO_BY_LLM}")
    log.info(f"可视化: log_llm={LOG_LLM}, log_geo={LOG_GEO}, summary_chars={SUMMARY_PREVIEW_CHARS}")
    _BASE_EP = DASHSCOPE_COMPAT_BASES.get(DASHSCOPE_REGION, DASHSCOPE_COMPAT_BASES["cn"])
    log.info(f"LLM 端点: {_BASE_EP}/chat/completions")

    # 批处理中保持稳定的时间窗起点（一次计算，多批复用）
    global STABLE_SINCE_ISO
    STABLE_SINCE_ISO = _compute_since_iso()
    if STABLE_SINCE_ISO:
        log.info(f"时间窗起点(UTC)：{STABLE_SINCE_ISO}")

    # 装载维表映射
    PROV_MAP = load_province_map()
    COUNTRY_MAP = load_country_map()
    log.info(f"省份映射 {len(PROV_MAP)} 条，国家映射 {len(COUNTRY_MAP)} 条")
    if DAYS_WINDOW: log.info(f"仅处理近 {DAYS_WINDOW} 天内的记录")
    ensure_fact_table_exists_or_die()
    # 基于已加载的 PROV_MAP 生成中文省名正则
    global PROV_NAME_RE
    PROV_NAME_RE = _cn_prov_regex()
    if not COUNTRY_MAP:
        log.warning("dim_country 为空：将忽略任何 country_iso3 写入以避免外键错误。建议先填充 dim_country（至少 CHN/USA/DEU 等）。")
    # 批量循环
    offset = 0
    total = 0
    for _ in range(MAX_BATCHES):
        n = run_once(offset=offset, limit=BATCH_SIZE, sleep_sec=SLEEP_BETWEEN_CALLS)
        if n == 0 and offset > 0:
            break
        offset += BATCH_SIZE
        total += n
    log.info(f"结束：累计写入 {total} 条")

if __name__ == "__main__":
    main()
