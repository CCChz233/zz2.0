# -*- coding: utf-8 -*-
"""
智能体聊天 API Blueprint
------------------------
接口：
  POST /api/agent/chat - 普通聊天接口
  POST /api/agent/chat/stream - 流式聊天接口
  GET /api/agent/chat/history - 获取聊天记录
  DELETE /api/agent/chat/history/<session_id> - 删除聊天会话

功能：
  - 前后端分离：LLM API调用在后端完成，支持多种模型后端
  - 聊天记录持久化：存储到Supabase
  - 流式传输：支持SSE流式响应
  - 智能路由：自动或手动选择合适的服务（GPT-Researcher/DeepAnalyze/Default LLM）
"""

import os
import json
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import requests
from flask import Blueprint, request, make_response, stream_with_context, jsonify

from infra.db import supabase
from infra.llm import call_volcano_chat as llm_chat

# 导入配置模块
from config import build_system_prompt, get_default_options

# 导入 GPT-Researcher 适配器
from backend_api.gpt_researcher_adapter import (
    get_gpt_researcher_adapter, 
    detect_task_type
)

# 导入 DeepAnalyze 适配器
from backend_api.deepanalyze_adapter import get_deepanalyze_adapter
from backend_api.rag.rag_search import run_semantic_retrieval
from backend_api.rag.rag_context import build_messages_with_evidence, build_evidence_block
from backend_api.web_search import (
    search_web,
    build_web_evidence_block,
)

# ===== 配置 =====
# GPT-Researcher 配置
USE_GPT_RESEARCHER = os.getenv("USE_GPT_RESEARCHER", "true").lower() == "true"
AUTO_ROUTE_TASKS = os.getenv("AUTO_ROUTE_TASKS", "true").lower() == "true"  # 是否自动路由任务

# DeepAnalyze 配置
USE_DEEPANALYZE = os.getenv("USE_DEEPANALYZE", "true").lower() == "true"

# 聊天记录表名（需要在Supabase中创建）
CHAT_SESSIONS_TABLE = os.getenv("CHAT_SESSIONS_TABLE", "chat_sessions")
CHAT_MESSAGES_TABLE = os.getenv("CHAT_MESSAGES_TABLE", "chat_messages")

RAG_KEYWORDS = ["新闻", "事件", "发布", "公告", "动态", "发生", "最近", "最新", "有哪些", "变化", "更新"]
WEB_SEARCH_KEYWORDS = [
    "最新",
    "最近",
    "新闻",
    "政策",
    "发布",
    "进展",
    "研究",
    "报道",
    "公告",
    "行业",
]

agent_chat_bp = Blueprint("agent_chat", __name__)
_supabase = supabase


def _get_env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, default))
    except Exception:
        return default


def _get_env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, default))
    except Exception:
        return default


USE_WEB_SEARCH = os.getenv("USE_WEB_SEARCH", "true").lower() == "true"
WEB_SEARCH_TOPK = _get_env_int("WEB_SEARCH_TOPK", 6)
WEB_SEARCH_CACHE_MINUTES = _get_env_int("WEB_SEARCH_CACHE_MINUTES", 30)
WEB_SEARCH_MIN_SCORE = _get_env_float("WEB_SEARCH_MIN_SCORE", 0.0)


def _to_iso(dt: Optional[datetime]) -> str:
    """将datetime转换为ISO8601格式"""
    if dt is None:
        dt = datetime.now(timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _contains_keyword(text: str, keywords: List[str]) -> bool:
    if not text:
        return False
    return any(keyword in text for keyword in keywords)


def _build_sources_payload(evidence: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    grouped = {"database": [], "internet": []}
    seen = {"database": set(), "internet": set()}

    for item in evidence or []:
        if not isinstance(item, dict):
            continue
        origin = (item.get("origin") or "").strip().lower()
        if origin == "rag":
            group_key = "database"
        elif origin == "web":
            group_key = "internet"
        else:
            continue

        title = str(item.get("title") or "").strip()
        url = str(item.get("url") or "").strip()
        source_name = str(item.get("source") or "").strip()
        published_at = (
            item.get("published_at")
            or item.get("publishedAt")
            or item.get("published")
            or item.get("date")
            or ""
        )

        if not title and not url:
            continue
        key = url or title
        if key in seen[group_key]:
            continue
        seen[group_key].add(key)

        grouped[group_key].append(
            {
                "title": title or url or source_name or "未知来源",
                "url": url,
                "source": source_name,
                "publishedAt": published_at,
                "origin": origin,
            }
        )

    return grouped


def _build_retrieval_messages(
    user_message: str,
    system_prompt: str,
    conversation_history: List[Dict[str, str]],
    use_rag: bool,
    use_web_search: bool,
) -> Dict[str, object]:
    rag_triggered = bool(use_rag) or _contains_keyword(user_message, RAG_KEYWORDS)
    web_triggered = bool(use_web_search) or _contains_keyword(user_message, WEB_SEARCH_KEYWORDS)
    combined_triggered = rag_triggered or web_triggered

    rag_results: List[Dict[str, Any]] = []
    web_results: List[Dict[str, object]] = []
    used_evidence: List[Dict[str, Any]] = []

    if combined_triggered:
        try:
            rag_results = run_semantic_retrieval(
                user_message,
                k=_get_env_int("RAG_TOPK", 8),
                min_sim=_get_env_float("RAG_MIN_SIM", 0.4),
            )
        except Exception as exc:
            print(f"⚠️ RAG 处理异常，回退到默认聊天: {exc}")

        if USE_WEB_SEARCH:
            try:
                web_results = search_web(
                    user_message,
                    max_results=WEB_SEARCH_TOPK,
                    min_score=WEB_SEARCH_MIN_SCORE,
                    cache_ttl_seconds=WEB_SEARCH_CACHE_MINUTES * 60,
                )
            except Exception as exc:
                print(f"⚠️ Web 搜索失败: {exc}")
        elif web_triggered:
            print("⚠️ Web 搜索已触发但未启用 USE_WEB_SEARCH")

    if rag_results:
        used_evidence.extend(
            [
                {
                    "id": item.get("id"),
                    "title": item.get("title"),
                    "summary": item.get("summary"),
                    "url": item.get("url"),
                    "published_at": item.get("published_at"),
                    "source": item.get("source") or item.get("source_name"),
                    "similarity": item.get("similarity"),
                    "origin": "rag",
                }
                for item in rag_results
            ]
        )
    if web_results:
        used_evidence.extend(
            [
                {
                    "id": None,
                    "title": item.get("title"),
                    "summary": item.get("snippet"),
                    "url": item.get("url"),
                    "published_at": item.get("publishedAt"),
                    "source": item.get("source"),
                    "similarity": item.get("score"),
                    "origin": "web",
                }
                for item in web_results
            ]
        )

    evidence_blocks: List[str] = []
    if rag_results:
        evidence_blocks.append(f"【本地知识库】\n{build_evidence_block(rag_results)}")
    if web_results:
        evidence_blocks.append(build_web_evidence_block(web_results))

    messages: List[Dict[str, str]] = []
    if evidence_blocks:
        system_content = system_prompt or "你是一个有帮助的助手。"
        system_content = (
            f"{system_content}\n\n"
            "请优先使用【本地知识库】证据回答，必要时再引用【网络搜索】；"
            "不要在正文中输出来源列表，来源由系统统一追加。"
            "若证据不足，请直接说明信息不足，不要编造。\n"
            + "\n\n".join(evidence_blocks)
        )
        messages = [{"role": "system", "content": system_content}]
        messages.extend(conversation_history)
        messages.append({"role": "user", "content": user_message})

        if rag_results:
            print(f"🔍 RAG 检索已触发，返回 {len(rag_results)} 条证据")
        if web_results:
            print(f"🌐 Web 搜索已触发，返回 {len(web_results)} 条证据")
    else:
        if combined_triggered:
            print("🔍 检索已触发但无证据，回退到默认提示")

        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.extend(conversation_history)
        messages.append({"role": "user", "content": user_message})

    return {
        "messages": messages,
        "used_evidence": used_evidence,
        "sources": _build_sources_payload(used_evidence),
    }


def _call_default_llm(messages: List[Dict[str, str]], stream: bool = False, **options):
    """
    调用默认的大语言模型服务
    
    该函数提供统一的 LLM 调用接口，实际使用的模型由 DEFAULT_LLM_PROVIDER 
    环境变量控制（如 volcano, qwen, gpt-4, claude 等）。
    这样设计能够在不修改代码的情况下灵活切换底层 LLM 服务。
    """
    return llm_chat(messages, stream=stream, **options)


def _call_llm_api(
    messages: List[Dict[str, str]], 
    user_message: str = "",
    stream: bool = False,
    force_provider: str = None,
    **options
):
    """
    统一的 LLM API 调用函数，根据任务类型自动选择服务
    
    Args:
        messages: 消息列表
        user_message: 用户消息（用于任务类型检测）
        stream: 是否流式响应
        force_provider: 强制使用指定服务 ('qwen', 'gpt-researcher', 'deepanalyze', 'auto')
        **options: 其他选项
    
    Returns:
        响应对象或生成器
    """
    # 如果强制指定了服务
    if force_provider == 'gpt-researcher':
        adapter = get_gpt_researcher_adapter()
        if stream:
            return adapter.chat_completions_stream(messages, **options)
        else:
            result = adapter.chat_completions(messages, **options)
            # 转换为 requests.Response 兼容格式
            class MockResponse:
                def __init__(self, data):
                    self._data = data
                def json(self):
                    return self._data
                def raise_for_status(self):
                    pass
            return MockResponse(result)
    
    if force_provider == 'deepanalyze':
        adapter = get_deepanalyze_adapter()
        if stream:
            return adapter.chat_completions_stream(messages, **options)
        else:
            result = adapter.chat_completions(messages, **options)
            class MockResponse:
                def __init__(self, data):
                    self._data = data
                def json(self):
                    return self._data
                def raise_for_status(self):
                    pass
            return MockResponse(result)
    
    # 自动路由或使用 Qwen
    if AUTO_ROUTE_TASKS and (USE_GPT_RESEARCHER or USE_DEEPANALYZE) and user_message:
        task_type = detect_task_type(user_message)
        if task_type == 'research' and USE_GPT_RESEARCHER:
            # 研究任务使用 GPT-Researcher
            adapter = get_gpt_researcher_adapter()
            if stream:
                return adapter.chat_completions_stream(messages, **options)
            else:
                result = adapter.chat_completions(messages, **options)
                class MockResponse:
                    def __init__(self, data):
                        self._data = data
                    def json(self):
                        return self._data
                    def raise_for_status(self):
                        pass
                return MockResponse(result)
        elif task_type == 'data' and USE_DEEPANALYZE:
            # 数据分析任务使用 DeepAnalyze
            adapter = get_deepanalyze_adapter()
            if stream:
                return adapter.chat_completions_stream(messages, **options)
            else:
                result = adapter.chat_completions(messages, **options)
                class MockResponse:
                    def __init__(self, data):
                        self._data = data
                    def json(self):
                        return self._data
                    def raise_for_status(self):
                        pass
                return MockResponse(result)
    
    # 默认使用本地 LLM 服务
    return _call_default_llm(messages, stream=stream, **options)


def _save_message(session_id: str, role: str, content: str, message_id: Optional[str] = None):
    """保存消息到数据库"""
    if not _supabase:
        return None
    
    try:
        message_data = {
            "session_id": session_id,
            "role": role,
            "content": content,
            "created_at": _to_iso(datetime.now(timezone.utc)),
        }
        
        if message_id:
            message_data["id"] = message_id
        
        result = _supabase.table(CHAT_MESSAGES_TABLE).insert(message_data).execute()
        return result.data[0] if result.data else None
    except Exception as e:
        print(f"⚠️ 保存消息失败: {e}")
        return None


def _create_or_update_session(session_id: str, title: Optional[str] = None):
    """创建或更新聊天会话"""
    if not _supabase:
        return None
    
    try:
        now = _to_iso(datetime.now(timezone.utc))
        session_data = {
            "id": session_id,
            "title": title or "新对话",
            "updated_at": now,
        }
        
        # 先查询会话是否存在
        existing = _supabase.table(CHAT_SESSIONS_TABLE).select("id").eq("id", session_id).execute()
        
        if existing.data and len(existing.data) > 0:
            # 会话存在，更新
            result = _supabase.table(CHAT_SESSIONS_TABLE).update(session_data).eq("id", session_id).execute()
            return result.data[0] if result.data else None
        else:
            # 会话不存在，插入新会话
            session_data["created_at"] = now
            result = _supabase.table(CHAT_SESSIONS_TABLE).insert(session_data).execute()
            return result.data[0] if result.data else None
    except Exception as e:
        print(f"⚠️ 创建/更新会话失败: {e}")
        return None


def _get_chat_history(session_id: str, limit: int = 50) -> List[Dict[str, Any]]:
    """获取聊天历史记录"""
    if not _supabase:
        return []
    
    try:
        result = (
            _supabase.table(CHAT_MESSAGES_TABLE)
            .select("*")
            .eq("session_id", session_id)
            .order("created_at", desc=False)
            .limit(limit)
            .execute()
        )
        return result.data or []
    except Exception as e:
        print(f"⚠️ 获取聊天历史失败: {e}")
        return []


@agent_chat_bp.route("/chat", methods=["POST"])
def chat():
    """普通聊天接口（非流式）"""
    try:
        data = request.get_json()
        user_message = data.get("message", "").strip()
        session_id = data.get("session_id") or str(uuid.uuid4())
        
        # 从配置文件获取系统提示词（不再从前端传递）
        temporary_prompts = data.get("temporary_prompts", [])  # 前端可以传递临时提示词
        system_prompt = build_system_prompt(temporary_prompts=temporary_prompts)
        
        conversation_history = data.get("conversation_history", [])
        options = data.get("options", {})
        
        # 合并默认选项
        default_options = get_default_options()
        options = {**default_options, **options}
        
        if not user_message:
            return jsonify({"code": 400, "message": "消息内容不能为空", "data": None}), 400
        
        # 构建消息列表（本地 RAG + 联网搜索）
        use_rag = data.get("use_rag", False)
        use_web_search = data.get("use_web_search", False)
        retrieval = _build_retrieval_messages(
            user_message=user_message,
            system_prompt=system_prompt,
            conversation_history=conversation_history,
            use_rag=use_rag,
            use_web_search=use_web_search,
        )
        messages = retrieval["messages"]
        used_evidence = retrieval["used_evidence"]
        sources_payload = retrieval["sources"]
        
        # 先创建或更新会话（确保会话存在）
        _create_or_update_session(session_id)
        
        # 保存用户消息
        _save_message(session_id, "user", user_message)
        
        # 获取任务类型（从前端传递或自动检测）
        task_type = data.get("task_type", "auto")
        
        # 根据 task_type 决定使用哪个服务
        force_provider = None
        if task_type == 'research':
            force_provider = 'gpt-researcher'
            print(f"🎯 [任务控制] 前端指定使用 GPT-Researcher（研究任务）")
        elif task_type == 'data':
            force_provider = 'deepanalyze'
            print(f"🎯 [任务控制] 前端指定使用 DeepAnalyze（数据分析任务）")
        elif task_type == 'chat':
            force_provider = 'qwen'
            print(f"🎯 [任务控制] 前端指定使用 Qwen（聊天任务）")
        else:
            print(f"🎯 [任务控制] 使用自动路由（task_type: {task_type}）")
        
        # 调用 LLM API（根据 task_type 选择服务）
        response = _call_llm_api(messages, user_message=user_message, stream=False, force_provider=force_provider, **options)
        result = response.json()
        
        # 提取AI回复
        ai_content = ""
        if result.get("choices") and len(result["choices"]) > 0:
            ai_content = result["choices"][0].get("message", {}).get("content", "")
        elif result.get("output"):
            output = result["output"]
            if output.get("text"):
                ai_content = output["text"]
            elif output.get("choices") and len(output["choices"]) > 0:
                ai_content = output["choices"][0].get("message", {}).get("content", "") or output["choices"][0].get("text", "")
        
        if not ai_content:
            ai_content = "抱歉，我暂时无法理解您的问题，请换个方式提问。"

        # 保存AI回复
        _save_message(session_id, "assistant", ai_content)
        
        # 更新会话
        _create_or_update_session(session_id)
        
        return jsonify({
            "code": 200,
            "message": "success",
            "data": {
                "session_id": session_id,
                "content": ai_content,
                "evidence": used_evidence,  # NEW: 返回证据
                "sources": sources_payload,
                "conversation_history": conversation_history + [
                    {"role": "user", "content": user_message},
                    {"role": "assistant", "content": ai_content}
                ]
            }
        })
        
    except requests.exceptions.RequestException as e:
        error_msg = f"API调用失败: {str(e)}"
        if hasattr(e, "response") and e.response is not None:
            try:
                error_data = e.response.json()
                error_msg = error_data.get("message", error_msg)
            except:
                pass
        return jsonify({"code": 500, "message": error_msg, "data": None}), 500
    except Exception as e:
        return jsonify({"code": 500, "message": f"服务器错误: {str(e)}", "data": None}), 500


@agent_chat_bp.route("/chat/stream", methods=["POST"])
def chat_stream():
    """流式聊天接口（SSE）"""
    try:
        data = request.get_json()
        user_message = data.get("message", "").strip()
        session_id = data.get("session_id") or str(uuid.uuid4())
        
        # 从配置文件获取系统提示词（不再从前端传递）
        temporary_prompts = data.get("temporary_prompts", [])  # 前端可以传递临时提示词
        system_prompt = build_system_prompt(temporary_prompts=temporary_prompts)
        
        conversation_history = data.get("conversation_history", [])
        options = data.get("options", {})
        task_type = data.get("task_type", "auto")  # 任务类型：'research' 强制使用 GPT-Researcher, 'chat' 使用 Qwen, 'auto' 自动路由
        
        # 合并默认选项
        default_options = get_default_options()
        options = {**default_options, **options}
        
        if not user_message:
            return jsonify({"code": 400, "message": "消息内容不能为空", "data": None}), 400
        
        # 构建消息列表（本地 RAG + 联网搜索）
        use_rag = data.get("use_rag", False)
        use_web_search = data.get("use_web_search", False)
        retrieval = _build_retrieval_messages(
            user_message=user_message,
            system_prompt=system_prompt,
            conversation_history=conversation_history,
            use_rag=use_rag,
            use_web_search=use_web_search,
        )
        messages = retrieval["messages"]
        used_evidence = retrieval["used_evidence"]
        
        # 先创建或更新会话（确保会话存在）
        _create_or_update_session(session_id)
        
        # 保存用户消息
        user_message_id = str(uuid.uuid4())
        _save_message(session_id, "user", user_message, user_message_id)
        
        def generate():
            """生成流式响应"""
            ai_content = ""
            ai_message_id = str(uuid.uuid4())
            
            try:
                # 根据 task_type 决定使用哪个服务
                use_gpt_researcher = False
                use_deepanalyze = False
                force_provider = None
                
                if task_type == 'research':
                    # 前端明确指定使用 GPT-Researcher
                    use_gpt_researcher = True
                    force_provider = 'gpt-researcher'
                    print(f"🎯 [任务控制] 前端指定使用 GPT-Researcher（研究任务）")
                elif task_type == 'data':
                    # 前端明确指定使用 DeepAnalyze
                    use_deepanalyze = True
                    force_provider = 'deepanalyze'
                    print(f"🎯 [任务控制] 前端指定使用 DeepAnalyze（数据分析任务）")
                elif task_type == 'chat':
                    # 前端明确指定使用 Qwen
                    force_provider = 'qwen'
                    print(f"🎯 [任务控制] 前端指定使用 Qwen（聊天任务）")
                elif AUTO_ROUTE_TASKS and (USE_GPT_RESEARCHER or USE_DEEPANALYZE) and user_message:
                    # 自动路由
                    detected_task_type = detect_task_type(user_message)
                    if detected_task_type == 'research' and USE_GPT_RESEARCHER:
                        use_gpt_researcher = True
                        print(f"🔍 [任务路由] 自动检测到研究任务，路由到 GPT-Researcher")
                        print(f"   用户消息: {user_message[:50]}...")
                    elif detected_task_type == 'data' and USE_DEEPANALYZE:
                        use_deepanalyze = True
                        print(f"🔍 [任务路由] 自动检测到数据分析任务，路由到 DeepAnalyze")
                        print(f"   用户消息: {user_message[:50]}...")
                    else:
                        print(f"🔍 [任务路由] 自动检测到{detected_task_type}任务，使用默认服务 (Qwen)")
                else:
                    if not AUTO_ROUTE_TASKS:
                        print(f"🔍 [任务路由] 自动路由已禁用，使用默认服务")
                    elif not USE_GPT_RESEARCHER and not USE_DEEPANALYZE:
                        print(f"🔍 [任务路由] GPT-Researcher 和 DeepAnalyze 已禁用，使用默认服务")
                
                # 发送初始事件
                yield f"data: {json.dumps({'type': 'start', 'session_id': session_id}, ensure_ascii=False)}\n\n"
                # NEW: 推送证据事件（空列表也发送，方便前端处理）
                if used_evidence:
                    yield f"data: {json.dumps({'type': 'evidence', 'items': used_evidence}, ensure_ascii=False)}\n\n"
                elif used_evidence == []:
                    yield f"data: {json.dumps({'type': 'evidence', 'items': []}, ensure_ascii=False)}\n\n"
                
                if use_gpt_researcher:
                    # 使用 GPT-Researcher（支持进度显示）
                    print(f"🚀 [GPT-Researcher] 开始调用研究服务...")
                    adapter = get_gpt_researcher_adapter()
                    
                    # 定义进度回调函数（用于发送进度到前端）
                    progress_queue = []
                    def progress_callback(progress_data):
                        """将进度信息添加到队列，稍后通过 SSE 发送"""
                        progress_queue.append(progress_data)
                    
                    chunk_count = 0
                    for chunk in adapter.chat_completions_stream(
                        messages, 
                        progress_callback=progress_callback,
                        **options
                    ):
                        # 先发送所有累积的进度信息
                        while progress_queue:
                            progress_data = progress_queue.pop(0)
                            progress_json = json.dumps(progress_data, ensure_ascii=False)
                            yield f"data: {progress_json}\n\n"
                        
                        # 处理内容块
                        content = chunk.get("choices", [{}])[0].get("delta", {}).get("content", "")
                        if content:
                            ai_content += content
                            chunk_data = json.dumps({'type': 'chunk', 'content': content}, ensure_ascii=False)
                            yield f"data: {chunk_data}\n\n"
                            chunk_count += 1
                            # 只在前几个chunk打印日志，避免日志过多
                            if chunk_count <= 3:
                                print(f"📤 [GPT-Researcher] 发送chunk #{chunk_count}: {content[:30]}...")
                    
                    # 发送剩余的进度信息
                    while progress_queue:
                        progress_data = progress_queue.pop(0)
                        progress_json = json.dumps(progress_data, ensure_ascii=False)
                        yield f"data: {progress_json}\n\n"
                    
                    print(f"✅ [GPT-Researcher] 完成，共发送 {chunk_count} 个chunks，总长度: {len(ai_content)} 字符")
                elif use_deepanalyze:
                    # 使用 DeepAnalyze API（原生流式支持）
                    print(f"🚀 [DeepAnalyze] 开始调用数据分析服务...")
                    adapter = get_deepanalyze_adapter()
                    
                    chunk_count = 0
                    for chunk in adapter.chat_completions_stream(messages, **options):
                        # 处理内容块
                        content = chunk.get("choices", [{}])[0].get("delta", {}).get("content", "")
                        if content:
                            ai_content += content
                            chunk_data = json.dumps({'type': 'chunk', 'content': content}, ensure_ascii=False)
                            yield f"data: {chunk_data}\n\n"
                            chunk_count += 1
                            # 只在前几个chunk打印日志，避免日志过多
                            if chunk_count <= 3:
                                print(f"📤 [DeepAnalyze] 发送chunk #{chunk_count}: {content[:30]}...")
                    
                    print(f"✅ [DeepAnalyze] 完成，共发送 {chunk_count} 个chunks，总长度: {len(ai_content)} 字符")
                else:
                    # 使用 Qwen API（真正的流式）
                    response = _call_llm_api(messages, user_message=user_message, stream=True, force_provider=force_provider, **options)
                    
                    # 处理流式响应
                    for line in response.iter_lines():
                        if not line:
                            continue
                        
                        line_str = line.decode("utf-8")
                        
                        # 跳过空行和注释行
                        if not line_str.strip() or line_str.startswith(':'):
                            continue
                        
                        # 移除 "data: " 前缀（如果存在）
                        if line_str.startswith("data: "):
                            line_str = line_str[6:]
                        
                        # 检查结束标记
                        if line_str.strip() == "[DONE]" or line_str.strip() == 'data:[DONE]':
                            break
                        
                        try:
                            chunk_data = json.loads(line_str)
                            
                            # 尝试多种格式解析
                            content = ""
                            
                            # OpenAI兼容格式
                            if "choices" in chunk_data and len(chunk_data["choices"]) > 0:
                                delta = chunk_data["choices"][0].get("delta", {})
                                content = delta.get("content", "")
                            
                            # DashScope格式（Qwen可能使用）
                            elif "output" in chunk_data:
                                output = chunk_data["output"]
                                if "choices" in output and len(output["choices"]) > 0:
                                    choice = output["choices"][0]
                                    if "delta" in choice:
                                        content = choice["delta"].get("content", "")
                                    elif "message" in choice:
                                        content = choice["message"].get("content", "")
                                    elif "text" in choice:
                                        content = choice.get("text", "")
                                elif "text" in output:
                                    content = output.get("text", "")
                            
                            # 直接文本格式
                            elif "text" in chunk_data:
                                content = chunk_data.get("text", "")
                            
                            # 如果找到内容，立即发送
                            if content:
                                ai_content += content
                                # 立即flush，确保实时传输
                                chunk_data = json.dumps({'type': 'chunk', 'content': content}, ensure_ascii=False)
                                yield f"data: {chunk_data}\n\n"
                                # 调试：打印发送的chunk（仅前几个字符）
                                if len(ai_content) <= 50:
                                    print(f"📤 [Qwen] 发送chunk: {content[:20]}...")
                                
                        except json.JSONDecodeError as e:
                            # 如果不是JSON格式，可能是纯文本，跳过
                            print(f"⚠️ 解析流式数据失败: {e}, 行内容: {line_str[:100]}")
                            continue
                        except Exception as e:
                            print(f"⚠️ 处理流式数据出错: {e}")
                            continue
                
                # 发送完成事件
                yield f"data: {json.dumps({'type': 'done', 'session_id': session_id}, ensure_ascii=False)}\n\n"
                
                # 保存完整的AI回复
                if ai_content:
                    _save_message(session_id, "assistant", ai_content, ai_message_id)
                    _create_or_update_session(session_id)
                else:
                    # 如果没有收到内容，保存默认消息
                    default_msg = "抱歉，我暂时无法理解您的问题，请换个方式提问。"
                    _save_message(session_id, "assistant", default_msg, ai_message_id)
                    yield f"data: {json.dumps({'type': 'error', 'message': default_msg}, ensure_ascii=False)}\n\n"
                    
            except Exception as e:
                error_msg = f"流式传输错误: {str(e)}"
                yield f"data: {json.dumps({'type': 'error', 'message': error_msg}, ensure_ascii=False)}\n\n"
        
        response = make_response(stream_with_context(generate()))
        response.headers["Content-Type"] = "text/event-stream; charset=utf-8"
        response.headers["Cache-Control"] = "no-cache, no-transform"
        response.headers["Connection"] = "keep-alive"
        response.headers["X-Accel-Buffering"] = "no"  # 禁用Nginx缓冲
        return response
        
    except Exception as e:
        return jsonify({"code": 500, "message": f"服务器错误: {str(e)}", "data": None}), 500


@agent_chat_bp.route("/chat/history", methods=["GET"])
def get_chat_history():
    """获取聊天记录"""
    try:
        session_id = request.args.get("session_id")
        limit = int(request.args.get("limit", 50))
        
        if not session_id:
            return jsonify({"code": 400, "message": "session_id参数必填", "data": None}), 400
        
        history = _get_chat_history(session_id, limit)
        
        # 转换为前端需要的格式
        messages = []
        for msg in history:
            messages.append({
                "role": msg.get("role"),
                "content": msg.get("content"),
                "time": msg.get("created_at", ""),
            })
        
        return jsonify({
            "code": 200,
            "message": "success",
            "data": {
                "session_id": session_id,
                "messages": messages
            }
        })
        
    except Exception as e:
        return jsonify({"code": 500, "message": f"服务器错误: {str(e)}", "data": None}), 500


@agent_chat_bp.route("/chat/sessions", methods=["GET"])
def get_chat_sessions():
    """获取所有聊天会话列表"""
    if not _supabase:
        return jsonify({"code": 200, "message": "success", "data": {"sessions": []}})
    
    try:
        limit = int(request.args.get("limit", 20))
        result = (
            _supabase.table(CHAT_SESSIONS_TABLE)
            .select("*")
            .order("updated_at", desc=True)
            .limit(limit)
            .execute()
        )
        
        sessions = result.data or []
        return jsonify({
            "code": 200,
            "message": "success",
            "data": {"sessions": sessions}
        })
    except Exception as e:
        return jsonify({"code": 500, "message": f"服务器错误: {str(e)}", "data": None}), 500


@agent_chat_bp.route("/chat/sessions/<session_id>", methods=["DELETE"])
def delete_chat_session(session_id):
    """删除聊天会话及其所有消息"""
    if not _supabase:
        return jsonify({"code": 200, "message": "success", "data": None})
    
    try:
        # 删除消息
        _supabase.table(CHAT_MESSAGES_TABLE).delete().eq("session_id", session_id).execute()
        # 删除会话
        _supabase.table(CHAT_SESSIONS_TABLE).delete().eq("id", session_id).execute()
        
        return jsonify({
            "code": 200,
            "message": "success",
            "data": None
        })
    except Exception as e:
        return jsonify({"code": 500, "message": f"服务器错误: {str(e)}", "data": None}), 500
