import threading
from typing import Any, Dict, List, Optional

from supabase import Client

from infra.db import supabase
from infra.embeddings import embed

DEFAULT_TOPK = 8
DEFAULT_MIN_SIM = 0.4
RPC_TIMEOUT = 20


def _log_retrieval(k: int, min_sim: float, results: List[Dict[str, Any]]):
    sims = []
    for item in results:
        try:
            val = float(item.get("similarity", 0))
            sims.append(val)
        except Exception:
            continue
    avg_sim = sum(sims) / len(sims) if sims else 0
    avg_sim_display = f"{avg_sim:.3f}" if sims else "n/a"
    print(
        f"ℹ️ RAG检索: topK={k}, min_sim={min_sim}, 返回条数={len(results)}, "
        f"平均相似度={avg_sim_display}"
    )


def _call_rpc_with_timeout(client: Client, rpc: str, payload: Dict[str, Any], timeout: int):
    result_holder: Dict[str, Any] = {}

    def _worker():
        try:
            result_holder["response"] = client.rpc(rpc, payload).execute()
        except Exception as exc:
            result_holder["error"] = exc

    thread = threading.Thread(target=_worker, daemon=True)
    thread.start()
    thread.join(timeout)

    if thread.is_alive():
        print(f"⚠️ Supabase RPC 超时（>{timeout}s），已回退为空结果")
        return None

    if "error" in result_holder:
        raise result_holder["error"]

    return result_holder.get("response")


def run_semantic_retrieval(
    question: str,
    k: int = DEFAULT_TOPK,
    min_sim: float = DEFAULT_MIN_SIM,
    rpc: str = "semantic_search_fact_events",
):
    """调用 Supabase RPC 进行语义检索，返回事件列表。"""
    query = (question or "").strip()
    if not query:
        return []

    client = supabase
    if not client:
        return []

    vector = embed(query)
    if not vector:
        print("⚠️ 未获取到有效的 query 向量，跳过检索")
        return []

    k = k or DEFAULT_TOPK
    min_sim = min_sim if min_sim is not None else DEFAULT_MIN_SIM

    payload = {
        "query_embedding": vector,
        "p_limit": k,
        "p_min_sim": min_sim,
        "p_type": None,
        "p_country_iso3": None,
        "p_province_code": None,
        "p_start": None,
        "p_end": None,
    }

    results: List[Dict[str, Any]] = []
    try:
        response = _call_rpc_with_timeout(client, rpc, payload, RPC_TIMEOUT)
        if response is None:
            return []
        results = response.data or []
    except Exception as exc:
        print(f"⚠️ 调用 Supabase RPC 失败: {exc}")
        return []

    if not isinstance(results, list):
        print("⚠️ RPC 返回结果格式异常")
        return []

    _log_retrieval(k, min_sim, results)
    return results
