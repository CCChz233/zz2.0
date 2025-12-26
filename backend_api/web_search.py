# -*- coding: utf-8 -*-
import hashlib
import os
import time
import threading
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional
from urllib.parse import urlparse

import requests

from infra.db import supabase as _supabase

_CACHE_LOCK = threading.Lock()
_CACHE: Dict[str, Dict[str, object]] = {}
WEB_SEARCH_CACHE_TABLE = os.getenv("WEB_SEARCH_CACHE_TABLE", "agent_web_search_cache")


def _now_ts() -> float:
    return time.time()


def _cache_get(key: str) -> Optional[List[Dict[str, object]]]:
    with _CACHE_LOCK:
        entry = _CACHE.get(key)
        if not entry:
            return None
        if entry.get("expires_at", 0) <= _now_ts():
            _CACHE.pop(key, None)
            return None
        return entry.get("data")


def _cache_set(key: str, data: List[Dict[str, object]], ttl_seconds: int) -> None:
    with _CACHE_LOCK:
        _CACHE[key] = {"data": data, "expires_at": _now_ts() + ttl_seconds}


def _extract_source(url: str) -> str:
    if not url:
        return ""
    try:
        parsed = urlparse(url)
        return parsed.netloc or ""
    except Exception:
        return ""


def _normalize_date(value: Optional[object]) -> Optional[str]:
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


def _truncate(text: str, limit: int) -> str:
    if not text:
        return ""
    cleaned = " ".join(text.split())
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[:limit].rstrip() + "..."


def _to_iso(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt.replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _parse_iso(text: str) -> Optional[datetime]:
    if not text:
        return None
    try:
        if text.endswith("Z"):
            text = text.replace("Z", "+00:00")
        return datetime.fromisoformat(text)
    except Exception:
        return None


def _cache_hash(value: str) -> str:
    return hashlib.sha1(value.encode("utf-8")).hexdigest()


def _db_get_cache(cache_hash: str) -> Optional[Dict[str, object]]:
    if not _supabase:
        return None
    now_iso = _to_iso(datetime.now(timezone.utc))
    try:
        res = (
            _supabase.table(WEB_SEARCH_CACHE_TABLE)
            .select("results, expires_at")
            .eq("query_hash", cache_hash)
            .gt("expires_at", now_iso)
            .order("created_at", desc=True)
            .limit(1)
            .execute()
        )
        rows = res.data or []
        if not rows:
            return None
        row = rows[0]
        results = row.get("results")
        if not isinstance(results, list):
            return None
        return row
    except Exception:
        return None


def _db_set_cache(query: str, cache_hash: str, results: List[Dict[str, object]], ttl_seconds: int) -> None:
    if not _supabase:
        return
    now = datetime.now(timezone.utc)
    payload = {
        "query_hash": cache_hash,
        "query": query,
        "results": results,
        "created_at": _to_iso(now),
        "expires_at": _to_iso(now + timedelta(seconds=ttl_seconds)),
    }
    try:
        _supabase.table(WEB_SEARCH_CACHE_TABLE).insert(payload).execute()
    except Exception:
        pass

def _normalize_result(raw: Dict[str, object]) -> Dict[str, object]:
    title = str(raw.get("title") or "").strip()
    url = str(raw.get("url") or "").strip()
    snippet = str(raw.get("content") or raw.get("snippet") or "").strip()
    published_at = _normalize_date(
        raw.get("published_date")
        or raw.get("published_time")
        or raw.get("published")
        or raw.get("date")
    )
    source = str(raw.get("source") or "").strip() or _extract_source(url)
    score = raw.get("score")
    return {
        "title": title,
        "url": url,
        "snippet": _truncate(snippet, 260),
        "publishedAt": published_at,
        "source": source,
        "score": score,
    }


def _dedupe_results(results: List[Dict[str, object]]) -> List[Dict[str, object]]:
    seen = set()
    deduped: List[Dict[str, object]] = []
    for item in results:
        key = item.get("url") or item.get("title")
        if not key or key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped


def search_web(
    query: str,
    max_results: int = 6,
    min_score: float = 0.0,
    cache_ttl_seconds: int = 1800,
) -> List[Dict[str, object]]:
    query = (query or "").strip()
    if not query:
        return []

    cache_key = f"{max_results}:{min_score}:{query}"
    cache_hash = _cache_hash(cache_key)
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    db_cached = _db_get_cache(cache_hash)
    if db_cached:
        results = db_cached.get("results") or []
        expires_at = db_cached.get("expires_at")
        ttl_seconds = cache_ttl_seconds
        if isinstance(expires_at, str):
            dt = _parse_iso(expires_at)
            if dt:
                ttl_seconds = max(1, int((dt - datetime.now(timezone.utc)).total_seconds()))
        _cache_set(cache_key, results, ttl_seconds)
        return results

    api_key = os.getenv("TAVILY_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("missing TAVILY_API_KEY")

    search_depth = os.getenv("WEB_SEARCH_DEPTH", "basic").strip() or "basic"
    payload = {
        "api_key": api_key,
        "query": query,
        "search_depth": search_depth,
        "max_results": max_results,
        "include_answer": False,
        "include_images": False,
        "include_raw_content": False,
    }

    response = requests.post("https://api.tavily.com/search", json=payload, timeout=25)
    response.raise_for_status()
    data = response.json() or {}
    raw_results = data.get("results") or []

    normalized = [_normalize_result(item) for item in raw_results if isinstance(item, dict)]
    normalized = [
        item
        for item in normalized
        if item.get("url") and item.get("title")
    ]

    if min_score > 0:
        filtered = []
        for item in normalized:
            score = item.get("score")
            try:
                if score is not None and float(score) >= min_score:
                    filtered.append(item)
            except Exception:
                filtered.append(item)
        normalized = filtered

    normalized = _dedupe_results(normalized)
    _cache_set(cache_key, normalized, cache_ttl_seconds)
    _db_set_cache(query, cache_hash, normalized, cache_ttl_seconds)
    return normalized


def build_web_evidence_block(results: List[Dict[str, object]]) -> str:
    if not results:
        return ""
    lines = ["【网络搜索】"]
    for idx, item in enumerate(results, start=1):
        title = item.get("title") or "未提供标题"
        url = item.get("url") or ""
        snippet = item.get("snippet") or ""
        published_at = item.get("publishedAt") or "时间未知"
        source = item.get("source") or "来源未知"
        header = f"{idx}. {title}（时间：{published_at}，来源：{source}）"
        if url:
            header += f" | 链接：{url}"
        lines.append(header)
        if snippet:
            lines.append(f"   摘要：{snippet}")
    return "\n".join(lines)


def build_web_sources_block(results: List[Dict[str, object]]) -> str:
    if not results:
        return ""
    lines = ["来源："]
    for idx, item in enumerate(results, start=1):
        title = item.get("title") or item.get("url") or "未命名来源"
        url = item.get("url") or ""
        meta_parts = []
        if item.get("publishedAt"):
            meta_parts.append(item.get("publishedAt"))
        if item.get("source"):
            meta_parts.append(item.get("source"))
        meta_text = f"（{' · '.join(meta_parts)}）" if meta_parts else ""
        if url:
            lines.append(f"{idx}. [{title}]({url}){meta_text}")
        else:
            lines.append(f"{idx}. {title}{meta_text}")
    return "\n".join(lines)
