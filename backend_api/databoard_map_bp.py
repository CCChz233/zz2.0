# -*- coding: utf-8 -*-
"""
Databoard · 地图模块 API Blueprint
---------------------------------
本 Blueprint 依据《数据看板地图模块 API 文档》实现以下端点：
  GET /api/databoard/map/data
  GET /api/databoard/map/region
  GET /api/databoard/map/summary
  GET /api/databoard/map/trend

实现风格与现有 data_cards Blueprint 保持一致：
- 使用 Supabase（PostgREST）作为数据源
- 统一响应：{"code": 20000, "message": "success", "data": {...}}
- 使用 make_response 保证 UTF-8 与易读缩进
- 提供尽可能健壮的入参解析与时间窗口计算

⚠️ 注意
由于不同环境的表结构差异较大，本实现通过环境变量暴露字段与表名的映射，
以最大化复用现有数据表。默认值做了合理猜测，若实际表结构不同，请调整
对应的环境变量或常量。
"""
from __future__ import annotations

from datetime import datetime, timedelta, date as date_cls, timezone
from typing import Dict, Tuple, List, Optional, Any, Iterable
import time
import os
import json
import math
import re

from flask import Blueprint, jsonify, request, make_response

from infra.db import supabase

# ===================== 初始化 =====================
databoard_map_bp = Blueprint("databoard_map", __name__)

sb = supabase

# ============ 可配置：数据源与字段映射（按需要修改） ============
# 数据类型到表与时间字段的映射
# 统一改为使用一张事实表（fact_events），按 type 字段区分
# 允许通过环境变量覆盖：MAP_FACT_TABLE / MAP_FACT_TIME_FIELD
DATA_TYPE_SOURCES: Dict[str, Dict[str, str]] = {
    "news": {
        "table": os.getenv("MAP_FACT_TABLE", "fact_events"),
        "time_field": os.getenv("MAP_FACT_TIME_FIELD", "published_at"),
    },
    "leads": {
        "table": os.getenv("MAP_FACT_TABLE", "fact_events"),
        "time_field": os.getenv("MAP_FACT_TIME_FIELD", "published_at"),
    },
    "tenders": {
        "table": os.getenv("MAP_FACT_TABLE", "fact_events"),
        "time_field": os.getenv("MAP_FACT_TIME_FIELD", "published_at"),
    },
    "policies": {
        "table": os.getenv("MAP_FACT_TABLE", "fact_events"),
        "time_field": os.getenv("MAP_FACT_TIME_FIELD", "published_at"),
    },
}

# 中国层级字段（按 level 分组时使用的字段）
CN_REGION_FIELDS = {
    "province": os.getenv("MAP_CN_PROVINCE_FIELD", "province_code"),
    "city": os.getenv("MAP_CN_CITY_FIELD", "city_code"),
    "district": os.getenv("MAP_CN_DISTRICT_FIELD", "district_code"),
}
# 中国层级 name 字段（可选，用于返回展示名；若不存在会回退为 code）
CN_REGION_NAME_FIELDS = {
    "province": os.getenv("MAP_CN_PROVINCE_NAME_FIELD", "province_name"),
    "city": os.getenv("MAP_CN_CITY_NAME_FIELD", "city_name"),
    "district": os.getenv("MAP_CN_DISTRICT_NAME_FIELD", "district_name"),
}

# 统一事实表的类型字段（按此过滤：news/leads/tenders/policies）

TYPE_FIELD = os.getenv("MAP_TYPE_FIELD", "type")
# === 前端类型 → 数据库源表映射
# 注意：这里的英文名称（leads/tenders/policies）是 API 接口字段名，为了保持 API 兼容性而保留
# 实际数据内容与字段名的字面含义不完全一致，请参考 TYPE_DISPLAY_NAMES 了解实际含义
# 查询时会用 src_table 精确过滤，不再用 type 字段
SRC_TABLE_FIELD = os.getenv("MAP_SRC_TABLE_FIELD", "src_table")
TYPE_TO_SRC_TABLE = {
    "news": "00_news",                 # API字段: news → 数据库表: 00_news (新闻表)
    "leads": "00_competitors_news",    # API字段: leads (历史命名，实际是竞品动态) → 数据库表: 00_competitors_news
    "tenders": "00_opportunity",        # API字段: tenders → 数据库表: 00_opportunity (招标机会表)
    "policies": "00_papers",            # API字段: policies (历史命名，实际是科技论文) → 数据库表: 00_papers
}

# === 类型显示名称映射（用于前端显示，反映实际数据内容）
# 这是前端展示给用户的名称，更准确地反映了数据的实际内容
TYPE_DISPLAY_NAMES = {
    "news": "相关新闻",      # 00_news: 相关新闻
    "leads": "竞品动态",     # 00_competitors_news: 竞品动态（注：API字段名是 leads，但实际内容是竞品新闻）
    "tenders": "招标机会",   # 00_opportunity: 招标机会
    "policies": "科技论文",  # 00_papers: 科技论文（注：API字段名是 policies，但实际内容是科技论文，不是政策）
}

# 世界地图用的国家字段（推荐使用英文名或 ISO 码）
WORLD_REGION_CODE_FIELD = os.getenv("MAP_WORLD_FIELD", "country_iso3")  # 作为 code 与 name 的主字段（建议使用 ISO3）
WORLD_REGION_NAME_FIELD = os.getenv("MAP_WORLD_NAME_FIELD", WORLD_REGION_CODE_FIELD)

# 维表（用于把 code → 中文名），不存在时返回 code 作为兜底
# 中国行政区：你的库使用单表 dim_cn_region(code, name_zh, level)
CN_PROVINCE_DIM_TABLE = os.getenv("MAP_CN_PROVINCE_DIM_TABLE", "dim_cn_region")
CN_PROVINCE_DIM_CODE_FIELD = os.getenv("MAP_CN_PROVINCE_DIM_CODE_FIELD", "code")
CN_PROVINCE_DIM_NAME_FIELD = os.getenv("MAP_CN_PROVINCE_DIM_NAME_FIELD", "name_zh")
CN_CITY_DIM_TABLE = os.getenv("MAP_CN_CITY_DIM_TABLE", "dim_cn_region")
CN_CITY_DIM_CODE_FIELD = os.getenv("MAP_CN_CITY_DIM_CODE_FIELD", "code")
CN_CITY_DIM_NAME_FIELD = os.getenv("MAP_CN_CITY_DIM_NAME_FIELD", "name_zh")
CN_DISTRICT_DIM_TABLE = os.getenv("MAP_CN_DISTRICT_DIM_TABLE", "dim_cn_region")
CN_DISTRICT_DIM_CODE_FIELD = os.getenv("MAP_CN_DISTRICT_DIM_CODE_FIELD", "code")
CN_DISTRICT_DIM_NAME_FIELD = os.getenv("MAP_CN_DISTRICT_DIM_NAME_FIELD", "name_zh")

# 世界国家维表（你的表 dim_country(iso3, iso2, name_en, name_zh)）
WORLD_DIM_TABLE = os.getenv("MAP_WORLD_DIM_TABLE", "dim_country")
WORLD_DIM_CODE_FIELD = os.getenv("MAP_WORLD_DIM_CODE_FIELD", "iso3")       # 用 iso3 做映射
WORLD_DIM_NAME_FIELD = os.getenv("MAP_WORLD_DIM_NAME_FIELD", "name_zh")    # 返回中文国名
WORLD_DIM_EN_NAME_FIELD = os.getenv("MAP_WORLD_DIM_EN_FIELD", "name_en")  # ECharts 世界地图通常用英文国名

# 当使用单表 dim_cn_region 存放省/市/区时，用该列区分层级
CN_DIM_LEVEL_FIELD = os.getenv("MAP_CN_DIM_LEVEL_FIELD", "level")

# 合法 level 与类型
VALID_LEVELS = {"province", "city", "district", "world"}
VALID_TYPES = {"all", "leads", "tenders", "policies", "news"}
VALID_TIMERANGE = {"day", "week", "month", "quarter", "year"}
VALID_PERIOD = {"day", "week", "month", "quarter", "year"}

# ===================== 缓存最新日期（避免频繁查询数据库） =====================
_LATEST_DATE_CACHE: Optional[Tuple[date_cls, float]] = None  # (date, timestamp)
_LATEST_DATE_CACHE_TTL = 300  # 缓存5分钟

def _get_latest_date_from_db() -> date_cls:
    """从数据库获取最新数据的日期（带缓存）"""
    global _LATEST_DATE_CACHE
    
    now = time.time()
    # 如果缓存有效，直接返回
    if _LATEST_DATE_CACHE and (now - _LATEST_DATE_CACHE[1]) < _LATEST_DATE_CACHE_TTL:
        return _LATEST_DATE_CACHE[0]
    
    # 缓存过期或不存在，查询数据库
    try:
        res = sb.table("fact_events").select("published_at").order("published_at", desc=True).limit(1).execute()
        if res.data and res.data[0].get("published_at"):
            latest = res.data[0]["published_at"]
            if isinstance(latest, str):
                latest = datetime.fromisoformat(latest.replace("Z", "+00:00"))
            elif not isinstance(latest, datetime):
                latest = datetime.fromisoformat(str(latest))
            # 转为 UTC date
            if latest.tzinfo:
                latest = latest.astimezone(timezone.utc)
            latest_date = latest.date()
            # 更新缓存
            _LATEST_DATE_CACHE = (latest_date, now)
            return latest_date
    except Exception as e:
        print(f"[WARN] 无法获取最新日期: {e}")
    
    # 查询失败，使用 UTC 今天并缓存
    today = datetime.utcnow().date()
    _LATEST_DATE_CACHE = (today, now)
    return today

# ===================== 工具函数 =====================
def _json_ok(data: Any, code: int = 20000, message: str = "success", http_status: int = 200):
    payload = {"code": code, "message": message, "data": data}
    resp = make_response(json.dumps(payload, ensure_ascii=False, indent=2))
    resp.status_code = http_status
    resp.mimetype = "application/json; charset=utf-8"
    return resp

def _json_err(code: int, message: str, http_status: int = 400, data: Optional[dict] = None):
    payload = {"code": code, "message": message, "data": data or {}}
    resp = make_response(json.dumps(payload, ensure_ascii=False, indent=2))
    resp.status_code = http_status
    resp.mimetype = "application/json; charset=utf-8"
    return resp

def _parse_date_arg(d: Optional[str]) -> date_cls:
    """
    解析日期参数。
    如果未提供日期，返回数据库中最新的日期（带缓存，保证数据一致性），
    而不是使用 UTC 的今天（避免因数据实时更新导致每次查询结果不同）。
    
    使用缓存机制（5分钟TTL）减少数据库查询，同时保证短时间内的请求使用相同日期。
    """
    if not d:
        # 使用缓存的最新日期，而不是每次都查询数据库
        return _get_latest_date_from_db()
    try:
        return datetime.fromisoformat(d).date()
    except Exception:
        # 40003: 日期格式错误
        raise ValueError("40003")

def _window_from_timerange(anchor: date_cls, time_range: str) -> Tuple[datetime, datetime]:
    """根据 timeRange 计算窗口 [start, end]（含端点）。"""
    tr = time_range if time_range in VALID_TIMERANGE else "day"

    if tr == "day":
        start = datetime.combine(anchor, datetime.min.time())
        end = datetime.combine(anchor, datetime.max.time())
    elif tr == "week":
        start = datetime.combine(anchor - timedelta(days=6), datetime.min.time())
        end = datetime.combine(anchor, datetime.max.time())
    elif tr == "month":
        first = anchor.replace(day=1)
        if first.month == 12:
            next_first = first.replace(year=first.year + 1, month=1, day=1)
        else:
            next_first = first.replace(month=first.month + 1, day=1)
        start = datetime.combine(first, datetime.min.time())
        end = datetime.combine(next_first - timedelta(seconds=1), datetime.max.time())
    elif tr == "quarter":
        q = (anchor.month - 1) // 3  # 0..3
        first_month = q * 3 + 1
        first = anchor.replace(month=first_month, day=1)
        if first_month == 10:
            next_first = first.replace(year=first.year + 1, month=1, day=1)
        else:
            next_first = first.replace(month=first_month + 3, day=1)
        start = datetime.combine(first, datetime.min.time())
        end = datetime.combine(next_first - timedelta(seconds=1), datetime.max.time())
    else:  # year
        first = anchor.replace(month=1, day=1)
        next_first = first.replace(year=first.year + 1, month=1, day=1)
        start = datetime.combine(first, datetime.min.time())
        end = datetime.combine(next_first - timedelta(seconds=1), datetime.max.time())
    return start, end

def _previous_window(start: datetime, end: datetime) -> Tuple[datetime, datetime]:
    delta = end - start + timedelta(seconds=1)
    prev_end = start - timedelta(seconds=1)
    prev_start = prev_end - delta + timedelta(seconds=1)
    return prev_start, prev_end

def _calc_trend(curr: int, prev: int) -> float:
    """返回百分比变化（带限幅）"""
    if prev <= 0 and curr > 0:
        pct = 100.0
    elif prev <= 0 and curr <= 0:
        pct = 0.0
    else:
        pct = round((curr - prev) * 100.0 / prev, 1)
    return max(min(pct, 500.0), -90.0)


def _safe_select(table: str, select: str, **kwargs) -> List[dict]:
    """包装 Supabase select，失败时返回空列表而不是抛错。"""
    try:
        q = sb.table(table).select(select)
        # where 条件
        for k, v in kwargs.items():
            # v 允许传入三元组 ("op", value) 或 ("op","value","cast")
            if isinstance(v, tuple):
                if len(v) == 2:
                    op, val = v
                    q = q.filter(k, op, val)
                elif len(v) == 3:
                    op, val, cast = v
                    q = q.filter(k, op, val, cast=cast)
            else:
                q = q.eq(k, v)
        r = q.execute()
        return r.data or []
    except Exception as e:
        print(f"[WARN] select error {table}: {e}")
        return []

# 区域 code → 中文名映射
def _map_region_names(level: str, codes: Iterable[str]) -> Dict[str, str]:
    """
    将一组区域 code 映射为中文名；兼容维表中 code 为 TEXT 或 INTEGER 的情况。
    查询失败时返回空映射，由上层用 code 兜底。
    level: province | city | district | world
    """
    raw_list = [c for c in set(codes or []) if c not in (None, "", "null")]
    if not raw_list:
        return {}

    # 选择维表与字段
    if level == "province":
        table, code_f, name_f = CN_PROVINCE_DIM_TABLE, CN_PROVINCE_DIM_CODE_FIELD, CN_PROVINCE_DIM_NAME_FIELD
    elif level == "city":
        table, code_f, name_f = CN_CITY_DIM_TABLE, CN_CITY_DIM_CODE_FIELD, CN_CITY_DIM_NAME_FIELD
    elif level == "district":
        table, code_f, name_f = CN_DISTRICT_DIM_TABLE, CN_DISTRICT_DIM_CODE_FIELD, CN_DISTRICT_DIM_NAME_FIELD
    else:  # world
        table, code_f, name_f = WORLD_DIM_TABLE, WORLD_DIM_CODE_FIELD, WORLD_DIM_NAME_FIELD

    # 是否需要附加 level 过滤（用于单表 dim_cn_region）
    need_level_filter = level in ("province", "city", "district") and table in (
        CN_PROVINCE_DIM_TABLE, CN_CITY_DIM_TABLE, CN_DISTRICT_DIM_TABLE
    )

    # 构造多轮尝试：保持原样 → 全转字符串 → 全转整数（仅当都是数字）
    attempts: List[List[Any]] = []
    attempts.append(list(raw_list))
    attempts.append([str(c) for c in raw_list])
    digits = []
    all_digit = True
    for c in raw_list:
        s = str(c)
        if re.fullmatch(r"\d+$", s):
            try:
                digits.append(int(s))
            except Exception:
                all_digit = False
                break
        else:
            all_digit = False
            break
    if all_digit and digits:
        attempts.append(digits)

    for payload in attempts:
        q_base = sb.table(table).select(f"{code_f},{name_f}")
        try:
            if need_level_filter:
                # 支持中英文层级别名，避免维表 level 为中文时查询不到
                level_alias = {
                    "province": ["province", "省", "省级", "直辖市", "自治区"],
                    "city": ["city", "市", "地级市", "盟", "地区"],
                    "district": ["district", "区", "县", "区县", "自治县", "旗"]
                }
                candidates = level_alias.get(level, [level])
                q = q_base.in_(CN_DIM_LEVEL_FIELD, candidates).in_(code_f, payload)
            else:
                q = q_base.in_(code_f, payload)
            r = q.execute()
        except Exception as _qe:
            # 回退：不带 level 过滤再试（兼容没有 level 列的多表设计）
            try:
                r = q_base.in_(code_f, payload).execute()
            except Exception as _qe2:
                print(f"[WARN] map names error on {table} with payload type={type(payload[0]).__name__ if payload else 'empty'}: {_qe2}")
                continue
        rows = r.data or []
        if rows:
            # 正常命中
            return {str(x.get(code_f)).strip(): x.get(name_f) for x in rows if x.get(code_f) is not None}

    # ===== Fallback: 全量拉取该层级维表再本地匹配（避免 in_ 类型不一致/空格等问题） =====
    try:
        q_full = sb.table(table).select(f"{code_f},{name_f}")
        if need_level_filter:
            level_alias = {
                "province": ["province", "省", "省级", "直辖市", "自治区"],
                "city": ["city", "市", "地级市", "盟", "地区"],
                "district": ["district", "区", "县", "区县", "自治县", "旗"]
            }
            candidates = level_alias.get(level, [level])
            q_full = q_full.in_(CN_DIM_LEVEL_FIELD, candidates)
        # 最多取 2000 条足够覆盖省/市/区
        q_full = q_full.limit(2000)
        r_full = q_full.execute()
        rows_full = r_full.data or []
        if rows_full:
            # 归一化：转字符串、去空白 → 再按 GB/T2260 规则右侧补零到6位：
            #  - 省级：2位 → + '0000'
            #  - 地市：4位 → + '00'
            #  - 区县：6位 → 原样
            #  - 其他长度：右侧补零到6位
            def canon6(v: Any) -> str:
                s = str(v).strip()
                # 仅保留数字
                if not s:
                    return s
                if s.isdigit():
                    n = len(s)
                    if n == 2:
                        return s + "0000"
                    elif n == 4:
                        return s + "00"
                    elif n == 6:
                        return s
                    else:
                        # 非标准长度，按右侧补零到6位
                        return (s + "000000")[:6]
                # 非纯数字，原样返回用于世界映射等场景
                return s

            lut = {canon6(x.get(code_f)): x.get(name_f) for x in rows_full if x.get(code_f) is not None}
            # 仅返回需要的 keys（同样做 canon6）
            out = {}
            for c in raw_list:
                key = canon6(c)
                if key in lut:
                    out[key] = lut[key]
            if out:
                return out
    except Exception as _fallback_e:
        print(f"[WARN] map names full-scan fallback error: {_fallback_e}")

    # 所有尝试均无结果
    print(f"[WARN] map names: no hits for level={level}, table={table}, size={len(raw_list)}")
    return {}

def _group_count(
    table: str,
    time_field: str,
    group_field: str,
    start: datetime,
    end: datetime,
    extra_filters: Optional[Dict[str, Any]] = None,
) -> Dict[str, Dict[str, Any]]:
    """
    以“只选择分组列 + 内存聚合”的方式做统计，彻底绕过 PostgREST 聚合语法兼容性问题
   （例如 42803 需要 GROUP BY、以及不同版本的 count() 解析差异）。

    优点：
      - 没有 select 聚合语法差异，PostgREST 任意版本均可运行；
      - 仅选择分组字段，网络负载可控；
      - 支持分页拉取，避免单次响应过大。

    可通过环境变量 MAP_FETCH_PAGE_SIZE 调整分页大小（默认 5000）。
    返回结构：{ code: {"count": n, "name": None} }
    """
    extra_filters = extra_filters or {}
    page_size = int(os.getenv("MAP_FETCH_PAGE_SIZE", "5000"))

    counts: Dict[str, int] = {}
    frm = 0

    def _apply_filters(q):
        q = q.gte(time_field, start.isoformat()).lte(time_field, end.isoformat())
        for k, v in (extra_filters or {}).items():
            if isinstance(v, tuple):
                op, val = v
                q = q.filter(k, op, val)
            else:
                q = q.eq(k, v)
        return q

    max_retries = 3
    retry_delay = 1.0  # 秒
    
    while True:
        rows: List[dict] = []
        retry_count = 0
        
        # 重试机制：最多重试3次
        while retry_count < max_retries:
            try:
                q = sb.table(table).select(group_field)
                q = _apply_filters(q).order(group_field, desc=False).range(frm, frm + page_size - 1)
                r = q.execute()
                rows = r.data or []
                break  # 成功，跳出重试循环
            except Exception as e:
                retry_count += 1
                error_msg = str(e)
                is_connection_error = any(keyword in error_msg.lower() for keyword in [
                    "server disconnected", "connection", "timeout", "network", "reset"
                ])
                
                if retry_count < max_retries and is_connection_error:
                    # 连接相关错误，等待后重试
                    wait_time = retry_delay * retry_count
                    print(f"[WARN] group_count page error ({table}, offset={frm}): {error_msg}，{wait_time:.1f}s后重试 ({retry_count}/{max_retries})")
                    time.sleep(wait_time)
                else:
                    # 非连接错误或已达最大重试次数
                    print(f"[WARN] group_count page error ({table}, offset={frm}): {error_msg}")
                    if retry_count >= max_retries:
                        print(f"[ERROR] group_count 达到最大重试次数，跳过当前页")
                    rows = []
                    break  # 跳出重试循环

        if not rows:
            # 如果没有数据，可能是最后一页或出错，退出循环
            break

        for row in rows:
            code = row.get(group_field)
            if code in (None, "", "null"):
                continue
            code_str = str(code).strip()
            if not code_str:
                continue
            counts[code_str] = counts.get(code_str, 0) + 1

        if len(rows) < page_size:
            break
        frm += page_size
        
        # 分页之间添加小延迟，避免请求过快
        if frm % (page_size * 5) == 0:  # 每5页休息一下
            time.sleep(0.1)

    # 统一输出形式，与原函数保持兼容
    out: Dict[str, Dict[str, Any]] = {code: {"count": cnt, "name": None} for code, cnt in counts.items()}
    return out

# ===== 城市级兜底辅助函数 =====
def _canon_city_code(code: Optional[Any]) -> Optional[str]:
    """将任意行政码规范为地市级 6 位码（前 4 位 + '00'）。"""
    if code in (None, "", "null"):
        return None
    s = str(code).strip()
    if not s:
        return None
    if not s.isdigit():
        return None
    n = len(s)
    if n >= 6:
        return s[:4] + "00"
    if n == 4:
        return s + "00"
    if n == 2:
        return s + "0000"
    # 其他长度：尽量取前 4 位补 '00'
    if n > 4:
        return s[:4] + "00"
    return None

def _group_count_city_fallback(
    table: str,
    time_field: str,
    start: datetime,
    end: datetime,
    extra_filters: Optional[Dict[str, Any]] = None,
) -> Dict[str, Dict[str, Any]]:
    """
    city 层级兜底：
      1) 优先尝试直接用 city_code 分组；
      2) 若失败或为空，尝试拉取 district_code，在服务端规范到 city 码（前4位+'00'）后再聚合；
    """
    extra_filters = extra_filters or {}
    page_size = int(os.getenv("MAP_FETCH_PAGE_SIZE", "5000"))

    def _apply_filters(q):
        q = q.gte(time_field, start.isoformat()).lte(time_field, end.isoformat())
        for k, v in (extra_filters or {}).items():
            if isinstance(v, tuple):
                op, val = v
                q = q.filter(k, op, val)
            else:
                q = q.eq(k, v)
        return q

    # 1) 直接 city_code 分组
    try:
        res_direct = _group_count(table, time_field, CN_REGION_FIELDS["city"], start, end, extra_filters)
        if res_direct:
            return res_direct
    except Exception as e:
        print(f"[WARN] city fallback direct city_code failed: {e}")

    # 2) 用 district_code 拉取并在内存规范到 city
    counts: Dict[str, int] = {}
    frm = 0
    max_retries = 3
    retry_delay = 1.0
    
    while True:
        rows: List[dict] = []
        retry_count = 0
        
        # 重试机制：最多重试3次
        while retry_count < max_retries:
            try:
                q = sb.table(table).select(CN_REGION_FIELDS["district"])
                q = _apply_filters(q).order(CN_REGION_FIELDS["district"], desc=False).range(frm, frm + page_size - 1)
                r = q.execute()
                rows = r.data or []
                break  # 成功，跳出重试循环
            except Exception as e:
                retry_count += 1
                error_msg = str(e)
                is_connection_error = any(keyword in error_msg.lower() for keyword in [
                    "server disconnected", "connection", "timeout", "network", "reset"
                ])
                
                if retry_count < max_retries and is_connection_error:
                    wait_time = retry_delay * retry_count
                    print(f"[WARN] city fallback page error ({table}, offset={frm}): {error_msg}，{wait_time:.1f}s后重试 ({retry_count}/{max_retries})")
                    time.sleep(wait_time)
                else:
                    print(f"[WARN] city fallback page error ({table}, offset={frm}): {error_msg}")
                    if retry_count >= max_retries:
                        print(f"[ERROR] city fallback 达到最大重试次数，跳过当前页")
                    rows = []
                    break

        if not rows:
            break

        for row in rows:
            dcode = row.get(CN_REGION_FIELDS["district"])
            ccode = _canon_city_code(dcode)
            if not ccode:
                continue
            counts[ccode] = counts.get(ccode, 0) + 1

        if len(rows) < page_size:
            break
        frm += page_size
        
        # 分页之间添加小延迟
        if frm % (page_size * 5) == 0:
            time.sleep(0.1)

    return {code: {"count": cnt, "name": None} for code, cnt in counts.items()}

def _detect_region_kind(region: str) -> str:
    """粗略判定 region 是中国行政码还是世界国家名。"""
    if re.fullmatch(r"\d{6}", region):
        return "cn"
    return "world"


def _infer_level_from_code(code: str) -> str:
    """
    简化推断：
      - 以 '0000' 结尾：省级
      - 以 '00' 结尾：市级
      - 其他：区县级
    """
    if code.endswith("0000"):
        return "province"
    elif code.endswith("00"):
        return "city"
    return "district"


# --- ECharts 地图中国省级名称规范化 ---
def _to_echarts_cn_province(name: Optional[str]) -> Optional[str]:
    """
    将中国省级行政区标准中文名规范为 ECharts 地图内置的区域名：
      - 去掉“省”“市”后缀；
      - “自治区/特别行政区”取常用简称；
      - 直辖市：北京市/上海市/天津市/重庆市 → 北京/上海/天津/重庆
    """
    if not name:
        return name
    s = str(name).strip()

    # 直辖市
    direct = {
        "北京市": "北京",
        "上海市": "上海",
        "天津市": "天津",
        "重庆市": "重庆",
    }
    if s in direct:
        return direct[s]

    # 自治区/特别行政区
    special_map = {
        "内蒙古自治区": "内蒙古",
        "广西壮族自治区": "广西",
        "西藏自治区": "西藏",
        "宁夏回族自治区": "宁夏",
        "新疆维吾尔自治区": "新疆",
        "香港特别行政区": "香港",
        "澳门特别行政区": "澳门",
        "台湾省": "台湾",
    }
    if s in special_map:
        return special_map[s]

    # 省份：去掉“省”后缀；黑龙江省/海南省/广东省/江苏省 等
    if s.endswith("省"):
        return s[:-1]

    # 已经是期望短名或无法处理的，原样返回
    return s

# --- 省级中文名模糊兼容：去后缀/长称呼，映射为常用短名 ---
def _normalize_to_echarts_name(name: Optional[str]) -> Optional[str]:
    """
    将各种形式的中国省级名称（含“省/市/自治区/特别行政区”等后缀，
    或者诸如“北京市市辖区/北京省”等不规范写法）模糊归一为 ECharts 省级地图
    使用的短名（如“北京/广东/广西/内蒙古/新疆/西藏/香港/澳门/台湾”等）。
    该函数仅做兼容性放宽处理，不改变原始统计逻辑。
    """
    if not name:
        return name
    s = str(name).strip()

    # 直辖市与特殊地区的常见写法映射
    mapping = {
        "北京市": "北京", "北京省": "北京", "北京市市辖区": "北京",
        "上海市": "上海", "天津市": "天津", "重庆市": "重庆",
        # 自治区/特别行政区/常见全称
        "内蒙古自治区": "内蒙古",
        "广西壮族自治区": "广西",
        "宁夏回族自治区": "宁夏",
        "新疆维吾尔自治区": "新疆",
        "西藏自治区": "西藏",
        "香港特别行政区": "香港",
        "澳门特别行政区": "澳门",
        "台湾省": "台湾",
    }
    if s in mapping:
        return mapping[s]

    # 通用后缀裁剪（尽量宽松）
    for suf in ("省", "市", "壮族自治区", "回族自治区", "维吾尔自治区", "自治区", "特别行政区"):
        if s.endswith(suf):
            s = s[: -len(suf)]
            break

    # 个别名称本身已是短名（黑龙江/内蒙古等），或非上述后缀场景
    return s

def _sum_summary(stat_list: List[Dict[str, Any]]) -> Dict[str, Any]:
    values = [int(x.get("value") or 0) for x in stat_list]
    if not values:
        return {"total": 0, "max": 0, "min": 0, "avg": 0.0, "count": 0}
    return {
        "total": int(sum(values)),
        "max": int(max(values)),
        "min": int(min(values)),
        "avg": round(sum(values) / float(len(values)), 2),
        "count": len(values),
    }

def _merge_type_buckets(
    buckets_by_type: Dict[str, Dict[str, Dict[str, Any]]]
) -> Dict[str, Dict[str, Any]]:
    """
    将不同类型（news/leads/...）的分组统计合并为：
      { code: { name, value, leads, tenders, policies, news } }
    """
    merged: Dict[str, Dict[str, Any]] = {}
    for typ, bucket in buckets_by_type.items():
        for code, info in bucket.items():
            # 先不把 code 塞进 name，保留 None 以便后续映射能生效
            node = merged.setdefault(code, {"name": info.get("name")})
            # 各类型值
            node[typ] = node.get(typ, 0) + int(info.get("count", 0))
            # 汇总 value
            node["value"] = node.get("value", 0) + int(info.get("count", 0))
    # 补齐缺省类型字段
    for code, node in merged.items():
        for t in ("leads", "tenders", "policies", "news"):
            node.setdefault(t, 0)
    return merged

def _ensure_stat_item(code: str, name: Optional[str], data: Dict[str, Any]) -> Dict[str, Any]:
    """
    确保统计项包含所有必需字段，并添加显示名称映射
    """
    return {
        "name": name or code,
        "code": code,
        "value": int(data.get("value", 0)),
        "leads": int(data.get("leads", 0)),
        "tenders": int(data.get("tenders", 0)),
        "policies": int(data.get("policies", 0)),
        "news": int(data.get("news", 0)),
        "trend": float(data.get("trend", 0.0)),
        # 添加显示名称映射，方便前端使用
        "typeLabels": {
            "leads": TYPE_DISPLAY_NAMES.get("leads", "竞品动态"),
            "tenders": TYPE_DISPLAY_NAMES.get("tenders", "招标机会"),
            "policies": TYPE_DISPLAY_NAMES.get("policies", "科技论文"),
            "news": TYPE_DISPLAY_NAMES.get("news", "相关新闻"),
        },
    }

# ===================== 主逻辑：/data =====================
@databoard_map_bp.route("/data", methods=["GET"])
def get_map_data():
    """
    地图聚合数据（含 summary）
    参数：
      - level: province|city|district|world（默认 province）
      - date: YYYY-MM-DD（可选，默认今天）
      - type: all|leads|tenders|policies|news（默认 all）
      - provinceCode: 当 level=city|district 时必需
      - cityCode: 当 level=district 时必需
      - timeRange: day|week|month|quarter|year（可选，默认 day）
    """
    if not sb:
        return _json_err(50000, "Supabase 未配置", 500)

    try:
        level = request.args.get("level", "province")
        if level not in VALID_LEVELS:
            return _json_err(40001, "参数错误：不支持的 level", 400)

        date_s = request.args.get("date")
        anchor = _parse_date_arg(date_s)  # 可能抛 ValueError("40003")
        tr = request.args.get("timeRange", "day")
        start, end = _window_from_timerange(anchor, tr)

        typ = request.args.get("type", "all")
        if typ not in VALID_TYPES:
            return _json_err(40001, "参数错误：不支持的 type", 400)

        province_code = request.args.get("provinceCode")
        city_code = request.args.get("cityCode")

    except ValueError as e:
        if str(e) == "40003":
            return _json_err(40003, "日期格式错误，需 YYYY-MM-DD", 400)
        return _json_err(40001, "参数错误", 400)

    # 组装 where 过滤（层级限定）
    extra_filters: Dict[str, Any] = {}
    if level in {"city", "district"} and not province_code:
        return _json_err(40001, "参数错误：level 为 city/district 时必须提供 provinceCode", 400)
    if level == "district" and not city_code:
        return _json_err(40001, "参数错误：level 为 district 时必须提供 cityCode", 400)

    # 决定分组字段
    if level == "world":
        group_field = WORLD_REGION_CODE_FIELD
        name_field = WORLD_REGION_NAME_FIELD
    else:
        group_field = CN_REGION_FIELDS[level]
        name_field = CN_REGION_NAME_FIELDS[level]
        # 上级过滤
        if level == "city" and province_code:
            extra_filters[CN_REGION_FIELDS["province"]] = province_code
        elif level == "district":
            if province_code:
                extra_filters[CN_REGION_FIELDS["province"]] = province_code
            if city_code:
                extra_filters[CN_REGION_FIELDS["city"]] = city_code

    # 需要计算的类型集合
    types_to_calc: Iterable[str]
    if typ == "all":
        types_to_calc = ("leads", "tenders", "policies", "news")
    else:
        types_to_calc = (typ,)

    # 当前窗口分组计数
    buckets_now: Dict[str, Dict[str, Dict[str, Any]]] = {}
    for t in types_to_calc:
        src = DATA_TYPE_SOURCES.get(t)
        if not src or not src.get("table") or not src.get("time_field"):
            continue
        src_tbl = TYPE_TO_SRC_TABLE.get(t)
        if not src_tbl:
            continue
        ef = dict(extra_filters)
        ef[SRC_TABLE_FIELD] = src_tbl
        b = _group_count(src["table"], src["time_field"], group_field, start, end, ef)
        buckets_now[t] = b

    merged_now = _merge_type_buckets(buckets_now)

    # 若为 city 层级且没有任何数据，尝试使用 district_code → city 的兜底聚合
    if level == "city" and not merged_now:
        buckets_now_fb: Dict[str, Dict[str, Dict[str, Any]]] = {}
        for t in types_to_calc:
            src = DATA_TYPE_SOURCES.get(t)
            if not src or not src.get("table") or not src.get("time_field"):
                continue
            src_tbl = TYPE_TO_SRC_TABLE.get(t)
            if not src_tbl:
                continue
            ef = dict(extra_filters)
            ef[SRC_TABLE_FIELD] = src_tbl
            b_fb = _group_count_city_fallback(src["table"], src["time_field"], start, end, ef)
            buckets_now_fb[t] = b_fb
        merged_now = _merge_type_buckets(buckets_now_fb)

    # 用维表把 code → name，避免前端只看到数字码
    try:
        level_for_map = level
        name_map = _map_region_names(level_for_map, merged_now.keys())
        for code, node in merged_now.items():
            curr = node.get("name")
            # 如果 name 为空，或者等于 code（说明还没映射成功），则用维表名覆盖
            if (not curr) or (str(curr).strip() == str(code).strip()):
                nm = name_map.get(str(code))
                if nm:
                    node["name"] = nm
                else:
                    # 兜底：保持 code，避免前端空白
                    node.setdefault("name", code)
    except Exception as _e:
        print(f"[WARN] enrich names failed: {_e}")

    # 上一窗口（用于趋势）
    prev_start, prev_end = _previous_window(start, end)
    buckets_prev: Dict[str, Dict[str, Dict[str, Any]]] = {}
    for t in types_to_calc:
        src = DATA_TYPE_SOURCES.get(t)
        if not src or not src.get("table") or not src.get("time_field"):
            continue
        src_tbl = TYPE_TO_SRC_TABLE.get(t)
        if not src_tbl:
            continue
        ef = dict(extra_filters)
        ef[SRC_TABLE_FIELD] = src_tbl
        b = _group_count(src["table"], src["time_field"], group_field, prev_start, prev_end, ef)
        buckets_prev[t] = b
    merged_prev = _merge_type_buckets(buckets_prev)
    if level == "city" and not merged_prev:
        buckets_prev_fb: Dict[str, Dict[str, Dict[str, Any]]] = {}
        for t in types_to_calc:
            src = DATA_TYPE_SOURCES.get(t)
            if not src or not src.get("table") or not src.get("time_field"):
                continue
            src_tbl = TYPE_TO_SRC_TABLE.get(t)
            if not src_tbl:
                continue
            ef = dict(extra_filters)
            ef[SRC_TABLE_FIELD] = src_tbl
            b_fb = _group_count_city_fallback(src["table"], src["time_field"], prev_start, prev_end, ef)
            buckets_prev_fb[t] = b_fb
        merged_prev = _merge_type_buckets(buckets_prev_fb)

    # 计算 trend
    statistics: List[Dict[str, Any]] = []
    for code, node in merged_now.items():
        prev_total = merged_prev.get(code, {}).get("value", 0)
        trend = _calc_trend(int(node.get("value", 0)), int(prev_total or 0))
        nm = node.get("name")
        statistics.append(_ensure_stat_item(code, nm, {**node, "trend": trend}))

    # 排序（默认 value desc）
    statistics.sort(key=lambda x: x.get("value", 0), reverse=True)

    # 为 ECharts 地图提供专用名称
    if level == "province":
        # 省级：去后缀、用短名与 ECharts 对齐
        for item in statistics:
            base = _normalize_to_echarts_name(item.get("name"))
            item["mapName"] = _to_echarts_cn_province(base) or base or item.get("name")
            # 兼容前端仍使用 name 作为 ECharts map 的匹配键（避免出现全部为 0 的情况）
            item["name"] = item["mapName"]
    elif level == "world":
        # 世界：ECharts 世界地图通常按英文国名匹配（如 China, United States）
        # 用维表把 iso3 → 英文名；若没有英文名则退回中文/原名
        try:
            codes = [str(x.get("code")) for x in statistics if x.get("code") is not None]
            if codes:
                r = sb.table(WORLD_DIM_TABLE).select(
                    f"{WORLD_DIM_CODE_FIELD},{WORLD_DIM_EN_NAME_FIELD},{WORLD_DIM_NAME_FIELD}"
                ).in_(WORLD_DIM_CODE_FIELD, codes).execute()
                world_rows = r.data or []
                en_map = {str(x.get(WORLD_DIM_CODE_FIELD)): (x.get(WORLD_DIM_EN_NAME_FIELD) or x.get(WORLD_DIM_NAME_FIELD)) for x in world_rows}
            else:
                en_map = {}
        except Exception as _we:
            print(f"[WARN] world name map failed: {_we}")
            en_map = {}
        for item in statistics:
            code = str(item.get('code'))
            en = en_map.get(code)
            # mapName 用英文，name 也同步为英文，确保与 ECharts 的 geo 名称匹配
            if en:
                item['mapName'] = en
                item['name'] = en
            else:
                # 兜底：已有 name/中文名；但为了最大兼容，保持 name 与 mapName 一致
                fallback = item.get('name')
                item['mapName'] = fallback
                item['name'] = fallback
    else:
        # 其他层级：做一次轻量归一，便于前端兜底显示
        for item in statistics:
            norm = _normalize_to_echarts_name(item.get("name"))
            if norm:
                item.setdefault("mapName", norm)

    data = {
        "statistics": statistics,
        "summary": _sum_summary(statistics),
        # 添加类型显示名称映射到顶层，方便前端直接使用
        "typeLabels": {
            "leads": TYPE_DISPLAY_NAMES.get("leads", "竞品动态"),
            "tenders": TYPE_DISPLAY_NAMES.get("tenders", "招标机会"),
            "policies": TYPE_DISPLAY_NAMES.get("policies", "科技论文"),
            "news": TYPE_DISPLAY_NAMES.get("news", "相关新闻"),
        },
    }
    return _json_ok(data)

# ===================== 区域详情：/region =====================
@databoard_map_bp.route("/region", methods=["GET"])
def get_region_detail():
    """
    单区域详情（含下钻）
    参数：
      - region: 必填；中国=6位码；世界=英文国家名（或配置的 WORLD_REGION_CODE_FIELD）
      - date: YYYY-MM-DD（可选，默认今天）
      - type: all|leads|tenders|policies|news（默认 all）
      - timeRange: day|week|month|quarter|year（默认 day）
    """
    if not sb:
        return _json_err(50000, "Supabase 未配置", 500)

    region = request.args.get("region")
    if not region:
        return _json_err(40001, "参数错误：region 必填", 400)

    try:
        anchor = _parse_date_arg(request.args.get("date"))
    except ValueError:
        return _json_err(40003, "日期格式错误，需 YYYY-MM-DD", 400)

    tr = request.args.get("timeRange", "day")
    start, end = _window_from_timerange(anchor, tr)
    typ = request.args.get("type", "all")
    if typ not in VALID_TYPES:
        return _json_err(40001, "参数错误：不支持的 type", 400)

    # 区域种类与层级
    rk = _detect_region_kind(region)
    if rk == "cn":
        # 推断层级
        level = _infer_level_from_code(region)
        group_field = CN_REGION_FIELDS[level]
        name_field = CN_REGION_NAME_FIELDS[level]
        # 自身统计的过滤条件
        self_filters = {group_field: region}
        # 子级：确定子级层级
        if level == "province":
            child_level = "city"
        elif level == "city":
            child_level = "district"
        else:
            child_level = None
    else:
        level = "world"
        group_field = WORLD_REGION_CODE_FIELD
        name_field = WORLD_REGION_NAME_FIELD
        self_filters = {group_field: region}
        child_level = None  # 世界层级暂不下钻（可扩展为省份/州）

    # 计算 types
    types_to_calc = ("leads", "tenders", "policies", "news") if typ == "all" else (typ,)

    # 当前/上期窗口（用于趋势百分比）
    prev_start, prev_end = _previous_window(start, end)

    # 自身统计（合并多类型）
    buckets_now: Dict[str, Dict[str, Dict[str, Any]]] = {}
    buckets_prev: Dict[str, Dict[str, Dict[str, Any]]] = {}
    for t in types_to_calc:
        src = DATA_TYPE_SOURCES.get(t)
        if not src:
            continue
        src_tbl = TYPE_TO_SRC_TABLE.get(t)
        if not src_tbl:
            continue
        ef_self = dict(self_filters)
        ef_self[SRC_TABLE_FIELD] = src_tbl
        b_now = _group_count(src["table"], src["time_field"], group_field, start, end, ef_self)
        b_prev = _group_count(src["table"], src["time_field"], group_field, prev_start, prev_end, ef_self)
        buckets_now[t] = b_now
        buckets_prev[t] = b_prev

    merged_now = _merge_type_buckets(buckets_now)
    merged_prev = _merge_type_buckets(buckets_prev)
    self_node = merged_now.get(region, {})
    prev_total = merged_prev.get(region, {}).get("value", 0)
    self_trend = _calc_trend(int(self_node.get("value", 0)), int(prev_total or 0))

    region_info = {
        "name": self_node.get("name") or region,
        "code": region,
        "level": level,
    }
    # 补充自身名称（若缺失）
    try:
        nm_map_self = _map_region_names(level, [region])
        if not region_info.get("name") or region_info["name"] == region:
            region_info["name"] = nm_map_self.get(region) or region_info["name"]
    except Exception as _e:
        print(f"[WARN] enrich self name failed: {_e}")
    statistics = [_ensure_stat_item(region, self_node.get("name"), {**self_node, "trend": self_trend})]

    # 下钻子级（若有）
    sub_regions: List[Dict[str, Any]] = []
    if child_level:
        # 组合过滤（限定上级）
        child_filters = dict(self_filters)
        child_group_field = CN_REGION_FIELDS[child_level]
        # 当前期
        child_buckets_now: Dict[str, Dict[str, Dict[str, Any]]] = {}
        for t in types_to_calc:
            src = DATA_TYPE_SOURCES.get(t)
            if not src:
                continue
            src_tbl = TYPE_TO_SRC_TABLE.get(t)
            if not src_tbl:
                continue
            ef_child = dict(child_filters)
            ef_child[SRC_TABLE_FIELD] = src_tbl
            b = _group_count(src["table"], src["time_field"], child_group_field, start, end, ef_child)
            child_buckets_now[t] = b
        child_merged = _merge_type_buckets(child_buckets_now)
        # 子级名称映射
        try:
            nm_map_child = _map_region_names(child_level, child_merged.keys())
        except Exception:
            nm_map_child = {}
        for code, node in child_merged.items():
            nm = node.get("name") or nm_map_child.get(str(code))
            sub_regions.append(_ensure_stat_item(code, nm, {**node, "trend": 0.0}))
        sub_regions.sort(key=lambda x: x.get("value", 0), reverse=True)

    # Top Items（示例实现：返回空数组；如需可扩展查询每类型最近条目）
    top_items: List[Dict[str, Any]] = []

    data = {
        "region": region_info,
        "statistics": statistics,
        "subRegions": sub_regions,
        "topItems": top_items,
    }
    return _json_ok(data)

# ===================== 汇总：/summary =====================
@databoard_map_bp.route("/summary", methods=["GET"])
def get_map_summary():
    """
    汇总（全国或指定区域；当未传 region 时为总体汇总）
    参数：
      - region: 可选；中国=6位码；世界=英文国家名
      - date: YYYY-MM-DD（可选）
      - type: all|leads|tenders|policies|news（默认 all）
      - timeRange: day|week|month|quarter|year（默认 day）
    """
    if not sb:
        return _json_err(50000, "Supabase 未配置", 500)

    region = request.args.get("region")
    try:
        anchor = _parse_date_arg(request.args.get("date"))
    except ValueError:
        return _json_err(40003, "日期格式错误，需 YYYY-MM-DD", 400)

    tr = request.args.get("timeRange", "day")
    start, end = _window_from_timerange(anchor, tr)

    typ = request.args.get("type", "all")
    if typ not in VALID_TYPES:
        return _json_err(40001, "参数错误：不支持的 type", 400)

    types_to_calc = ("leads", "tenders", "policies", "news") if typ == "all" else (typ,)

    # 可选区域过滤
    extra_filters = {}
    if region:
        rk = _detect_region_kind(region)
        if rk == "cn":
            level = _infer_level_from_code(region)
            extra_filters[CN_REGION_FIELDS[level]] = region
        else:
            extra_filters[WORLD_REGION_CODE_FIELD] = region

    # 汇总直接计数（不分组）
    total = 0
    part_values = {"leads": 0, "tenders": 0, "policies": 0, "news": 0}
    for t in types_to_calc:
        src = DATA_TYPE_SOURCES.get(t)
        if not src:
            continue
        src_tbl = TYPE_TO_SRC_TABLE.get(t)
        if not src_tbl:
            continue
        try:
            q = sb.table(src["table"]).select("id", count="exact")
            q = q.gte(src["time_field"], start.isoformat()).lte(src["time_field"], end.isoformat())
            for k, v in extra_filters.items():
                q = q.eq(k, v)
            q = q.eq(SRC_TABLE_FIELD, src_tbl)
            r = q.execute()
            c = int(r.count or 0)
        except Exception as e:
            print(f"[WARN] summary count error on {t}: {e}")
            c = 0
        part_values[t] = c
        total += c

    data = {
        "total": total,
        "max": total,  # 对总体汇总无组间比较，max=min=total
        "min": total,
        "avg": float(total),
        "count": 1,
        "byType": part_values,
        # 添加类型显示名称映射
        "typeLabels": {
            "leads": TYPE_DISPLAY_NAMES.get("leads", "竞品动态"),
            "tenders": TYPE_DISPLAY_NAMES.get("tenders", "招标机会"),
            "policies": TYPE_DISPLAY_NAMES.get("policies", "科技论文"),
            "news": TYPE_DISPLAY_NAMES.get("news", "相关新闻"),
        },
    }
    return _json_ok(data)

# ===================== 趋势：/trend =====================
def _build_time_bins(anchor: date_cls, period: str) -> List[Tuple[datetime, datetime, str]]:
    """
    生成时间桶：
      - day   -> 最近 7 天（按日）
      - week  -> 最近 8 周（按周）
      - month -> 最近 12 个月（按月）
      - quarter -> 最近 8 个季度
      - year  -> 最近 5 年
    返回 [(start,end,label), ...]，label 为显示用日期字符串。
    """
    p = period if period in VALID_PERIOD else "month"
    bins: List[Tuple[datetime, datetime, str]] = []

    if p == "day":
        for i in range(6, -1, -1):
            d = anchor - timedelta(days=i)
            s = datetime.combine(d, datetime.min.time())
            e = datetime.combine(d, datetime.max.time())
            bins.append((s, e, d.isoformat()))
    elif p == "week":
        # 近 8 周（每周 7 天，末端为锚点所在日）
        end_d = anchor
        for i in range(7, -1, -1):
            e = datetime.combine(end_d - timedelta(weeks=(7 - i)), datetime.max.time())
            s = e - timedelta(days=6)
            bins.append((s, e, f"{s.date().isoformat()}~{e.date().isoformat()}"))
    elif p == "month":
        # 近 12 个月
        y, m = anchor.year, anchor.month
        parts = []
        for _ in range(12):
            first = datetime(y, m, 1)
            # next month
            if m == 12:
                next_first = datetime(y + 1, 1, 1)
            else:
                next_first = datetime(y, m + 1, 1)
            s = first
            e = next_first - timedelta(seconds=1)
            parts.append((s, e, f"{y}-{m:02d}"))
            # prev month
            if m == 1:
                y -= 1
                m = 12
            else:
                m -= 1
        bins = list(reversed(parts))
    elif p == "quarter":
        # 近 8 个季度
        y, m = anchor.year, anchor.month
        q = (m - 1) // 3 + 1
        parts = []
        for _ in range(8):
            first_month = (q - 1) * 3 + 1
            first = datetime(y, first_month, 1)
            if q == 4:
                next_first = datetime(y + 1, 1, 1)
            else:
                next_first = datetime(y, first_month + 3, 1)
            s = first
            e = next_first - timedelta(seconds=1)
            parts.append((s, e, f"{y}Q{q}"))
            # 前一季度
            if q == 1:
                y -= 1
                q = 4
            else:
                q -= 1
        bins = list(reversed(parts))
    else:  # year
        y = anchor.year
        parts = []
        for _ in range(5):
            first = datetime(y, 1, 1)
            next_first = datetime(y + 1, 1, 1)
            s = first
            e = next_first - timedelta(seconds=1)
            parts.append((s, e, str(y)))
            y -= 1
        bins = list(reversed(parts))

    return bins

@databoard_map_bp.route("/trend", methods=["GET"])
def get_region_trend():
    """
    区域趋势
    参数：
      - region: 必填（中国行政码或世界国家名）
      - type: all|leads|tenders|policies|news（默认 all）
      - period: day|week|month|quarter|year（默认 month；用于时间桶粒度与跨度）
      - date: YYYY-MM-DD（可选，锚点，默认今天）
    """
    if not sb:
        return _json_err(50000, "Supabase 未配置", 500)

    region = request.args.get("region")
    if not region:
        return _json_err(40001, "参数错误：region 必填", 400)

    try:
        anchor = _parse_date_arg(request.args.get("date"))
    except ValueError:
        return _json_err(40003, "日期格式错误，需 YYYY-MM-DD", 400)

    period = request.args.get("period", "month")
    if period not in VALID_PERIOD:
        return _json_err(40001, "参数错误：不支持的 period", 400)

    typ = request.args.get("type", "all")
    if typ not in VALID_TYPES:
        return _json_err(40001, "参数错误：不支持的 type", 400)
    types_to_calc = ("leads", "tenders", "policies", "news") if typ == "all" else (typ,)

    # 区域过滤
    rk = _detect_region_kind(region)
    if rk == "cn":
        level = _infer_level_from_code(region)
        region_filter_key = CN_REGION_FIELDS[level]
    else:
        region_filter_key = WORLD_REGION_CODE_FIELD

    bins = _build_time_bins(anchor, period)
    points: List[Dict[str, Any]] = []

    prev_val = None
    for (s, e, label) in bins:
        total = 0
        for t in types_to_calc:
            src = DATA_TYPE_SOURCES.get(t)
            if not src:
                continue
            src_tbl = TYPE_TO_SRC_TABLE.get(t)
            if not src_tbl:
                continue
            try:
                q = sb.table(src["table"]).select("id", count="exact")
                q = q.gte(src["time_field"], s.isoformat()).lte(src["time_field"], e.isoformat())
                q = q.eq(region_filter_key, region)
                q = q.eq(SRC_TABLE_FIELD, src_tbl)
                r = q.execute()
                total += int(r.count or 0)
            except Exception as ex:
                print(f"[WARN] trend count error {t}: {ex}")
        if prev_val is None:
            change = 0.0
        else:
            change = _calc_trend(total, prev_val)
        points.append({"date": label, "value": total, "change": change})
        prev_val = total

    data = {
        "region": region,
        "type": typ,
        "period": period,
        "trendData": points,
    }
    return _json_ok(data)

# 该 Blueprint 不包含独立运行入口，由应用主程序注册：
# app.register_blueprint(databoard_map_bp, url_prefix="/api/databoard/map")
