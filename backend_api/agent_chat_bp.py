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
  - 前后端分离：Qwen API调用在后端完成
  - 聊天记录持久化：存储到Supabase
  - 流式传输：支持SSE流式响应
"""

import os
import json
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import requests
from flask import Blueprint, request, make_response, stream_with_context, jsonify
from supabase import Client, create_client

# ===== 配置 =====
QWEN_API_KEY = os.getenv("QWEN_API_KEY", "sk-7cd135dca0834256a58e960048238db3")
QWEN_BASE_URL = os.getenv("QWEN_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1")
QWEN_MODEL = os.getenv("QWEN_MODEL", "qwen-turbo")

SUPABASE_URL = os.getenv("SUPABASE_URL", "https://zlajhzeylrzfbchycqyy.supabase.co")
SUPABASE_KEY = os.getenv(
    "SUPABASE_SERVICE_KEY",
    "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InpsYWpoemV5bHJ6ZmJjaHljcXl5Iiwicm9sZSI6InNlcnZpY2Vfcm9sZSIsImlhdCI6MTc1NTYwMTIwMiwiZXhwIjoyMDcxMTc3MjAyfQ.u6vYYEL3qCh4lJU62wEmT4UJTZrstX-_yscRPXrZH7s",
)

# 聊天记录表名（需要在Supabase中创建）
CHAT_SESSIONS_TABLE = os.getenv("CHAT_SESSIONS_TABLE", "chat_sessions")
CHAT_MESSAGES_TABLE = os.getenv("CHAT_MESSAGES_TABLE", "chat_messages")

agent_chat_bp = Blueprint("agent_chat", __name__)

# 初始化Supabase客户端
_supabase: Optional[Client] = None
if SUPABASE_URL and SUPABASE_KEY:
    try:
        _supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
    except Exception as e:
        print(f"⚠️ Supabase初始化失败: {e}")
        _supabase = None


def _to_iso(dt: Optional[datetime]) -> str:
    """将datetime转换为ISO8601格式"""
    if dt is None:
        dt = datetime.now(timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _call_qwen_api(messages: List[Dict[str, str]], stream: bool = False, **options):
    """调用Qwen API"""
    url = f"{QWEN_BASE_URL}/chat/completions"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {QWEN_API_KEY}",
    }
    
    data = {
        "model": QWEN_MODEL,
        "messages": messages,
        "temperature": options.get("temperature", 0.8),
        "top_p": options.get("top_p", 0.8),
        **({"stream": True} if stream else {}),
    }
    
    if options.get("max_tokens"):
        data["max_tokens"] = options["max_tokens"]
    
    response = requests.post(url, headers=headers, json=data, stream=stream, timeout=60)
    response.raise_for_status()
    return response


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
        system_prompt = data.get("system_prompt", "你是致真智能体，一个友好、专业的AI助手。你可以回答各种问题，提供工作学习上的帮助，还能随时陪伴聊天。请用简洁、友好的语气回复。")
        conversation_history = data.get("conversation_history", [])
        options = data.get("options", {})
        
        if not user_message:
            return jsonify({"code": 400, "message": "消息内容不能为空", "data": None}), 400
        
        # 构建消息列表
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.extend(conversation_history)
        messages.append({"role": "user", "content": user_message})
        
        # 先创建或更新会话（确保会话存在）
        _create_or_update_session(session_id)
        
        # 保存用户消息
        _save_message(session_id, "user", user_message)
        
        # 调用Qwen API
        response = _call_qwen_api(messages, stream=False, **options)
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
        system_prompt = data.get("system_prompt", "你是致真智能体，一个友好、专业的AI助手。你可以回答各种问题，提供工作学习上的帮助，还能随时陪伴聊天。请用简洁、友好的语气回复。")
        conversation_history = data.get("conversation_history", [])
        options = data.get("options", {})
        
        if not user_message:
            return jsonify({"code": 400, "message": "消息内容不能为空", "data": None}), 400
        
        # 构建消息列表
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.extend(conversation_history)
        messages.append({"role": "user", "content": user_message})
        
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
                # 调用Qwen API（流式）
                response = _call_qwen_api(messages, stream=True, **options)
                
                # 发送初始事件
                yield f"data: {json.dumps({'type': 'start', 'session_id': session_id}, ensure_ascii=False)}\n\n"
                
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
                                print(f"📤 发送chunk: {content[:20]}...")
                            
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

