# -*- coding: utf-8 -*-
"""
GPT-Researcher API 适配层
------------------------
将 GPT-Researcher 的 API 格式转换为 OpenAI 兼容格式
"""

import os
import json
import time
import requests
import asyncio
import websockets
import queue
import threading
from typing import List, Dict, Any, Optional, Iterator, Callable
import logging

logger = logging.getLogger(__name__)

# ===== 配置 =====
GPT_RESEARCHER_BASE_URL = os.getenv("GPT_RESEARCHER_BASE_URL", "http://localhost:8000")
GPT_RESEARCHER_CHAT_ENDPOINT = f"{GPT_RESEARCHER_BASE_URL}/api/chat"  # 保留用于聊天场景
GPT_RESEARCHER_REPORT_ENDPOINT = f"{GPT_RESEARCHER_BASE_URL}/report/"  # 用于生成研究报告
GPT_RESEARCHER_WS_URL = GPT_RESEARCHER_BASE_URL.replace("http://", "ws://").replace("https://", "wss://") + "/ws"  # WebSocket 端点
# 增加超时时间：研究任务可能需要 5-10 分钟
GPT_RESEARCHER_TIMEOUT = int(os.getenv("GPT_RESEARCHER_TIMEOUT", "600"))  # 从 300 秒增加到 600 秒（10分钟）


class GPTResearcherAdapter:
    """GPT-Researcher API 适配器，转换为 OpenAI 兼容格式"""
    
    def __init__(self, base_url: str = None):
        self.base_url = base_url or GPT_RESEARCHER_BASE_URL
        self.chat_endpoint = f"{self.base_url}/api/chat"  # 保留用于聊天场景
        self.report_endpoint = f"{self.base_url}/report/"  # 用于生成研究报告
        self.timeout = GPT_RESEARCHER_TIMEOUT
    
    def _convert_to_gpt_researcher_chat_format(
        self, 
        messages: List[Dict[str, str]], 
        report: str = ""
    ) -> Dict[str, Any]:
        """将 OpenAI 格式的消息转换为 GPT-Researcher Chat 格式（/api/chat）"""
        return {
            "report": report,
            "messages": messages
        }
    
    def _fallback_to_chat_endpoint(
        self,
        messages: List[Dict[str, str]],
        model: str,
        report: str = ""
    ) -> Dict[str, Any]:
        """回退到 /api/chat 端点（当 /report/ 端点失败时）"""
        request_data = self._convert_to_gpt_researcher_chat_format(messages, report)
        
        logger.info(f"回退到 GPT-Researcher /api/chat 端点: {self.chat_endpoint}")
        response = requests.post(
            self.chat_endpoint,
            json=request_data,
            timeout=self.timeout,
            headers={"Content-Type": "application/json"}
        )
        response.raise_for_status()
        result = response.json()
        
        # 转换为 OpenAI 格式
        return self._convert_to_openai_format(result, model)
    
    def _normalize_tone(self, tone: str) -> str:
        """将 tone 字符串转换为 GPT-Researcher Tone 枚举名称"""
        # Tone 枚举名称映射（小写 -> 枚举名称）
        tone_map = {
            "informative": "Informative",
            "objective": "Objective",
            "formal": "Formal",
            "analytical": "Analytical",
            "persuasive": "Persuasive",
            "explanatory": "Explanatory",
            "descriptive": "Descriptive",
            "critical": "Critical",
            "comparative": "Comparative",
            "speculative": "Speculative",
            "reflective": "Reflective",
            "narrative": "Narrative",
            "humorous": "Humorous",
            "optimistic": "Optimistic",
            "pessimistic": "Pessimistic",
            "simple": "Simple",
            "casual": "Casual"
        }
        
        # 如果已经是正确的格式，直接返回
        if tone in tone_map.values():
            return tone
        
        # 转换为小写并查找映射
        tone_lower = tone.lower()
        if tone_lower in tone_map:
            return tone_map[tone_lower]
        
        # 如果找不到，默认使用 Informative
        logger.warning(f"未知的 tone 值: {tone}，使用默认值 Informative")
        return "Informative"
    
    def _convert_to_gpt_researcher_report_format(
        self,
        messages: List[Dict[str, str]],
        report_type: str = "research_report",
        tone: str = "informative"
    ) -> Dict[str, Any]:
        """将 OpenAI 格式的消息转换为 GPT-Researcher Report 格式（/report/）"""
        # 从消息中提取用户查询（通常是最后一条用户消息）
        user_message = ""
        for msg in reversed(messages):
            if msg.get("role") == "user":
                user_message = msg.get("content", "")
                break
        
        # 如果没有找到用户消息，使用第一条消息的内容
        if not user_message and messages:
            user_message = messages[-1].get("content", "")
        
        # 规范化 tone 参数（转换为枚举名称）
        normalized_tone = self._normalize_tone(tone)
        
        return {
            "task": user_message,
            "report_type": report_type,  # "research_report" 或 "detailed_report"
            "report_source": "web",  # "web", "arxiv", "local", "youtube", "reddit" 等
            "tone": normalized_tone,  # 枚举名称，如 "Informative", "Analytical" 等
            "headers": None,
            "repo_name": "",
            "branch_name": "",
            "generate_in_background": False  # 同步生成，不使用后台任务
        }
    
    def _convert_report_response_to_openai_format(
        self,
        report_response: Dict[str, Any],
        model: str = "gpt-researcher"
    ) -> Dict[str, Any]:
        """将 /report/ 端点的响应转换为 OpenAI 兼容格式"""
        if "error" in report_response:
            raise Exception(report_response["error"])
        
        # /report/ 端点返回的格式：
        # {
        #     "research_id": "...",
        #     "research_information": {
        #         "source_urls": [...],
        #         "visited_urls": [...],
        #         ...
        #     },
        #     "report": "...",  # 完整的研究报告（通常已包含参考文献）
        #     "docx_path": "...",
        #     "pdf_path": "..."
        # }
        
        report_content = report_response.get("report", "")
        research_info = report_response.get("research_information", {})
        source_urls = research_info.get("source_urls", [])
        visited_urls = research_info.get("visited_urls", [])
        
        # 如果报告中没有参考文献，但从 research_information 中有来源，添加参考文献
        if source_urls and "## 参考文献" not in report_content and "参考文献" not in report_content:
            references = []
            seen_urls = set()
            
            # 使用 source_urls（这些是实际使用的来源）
            for url in source_urls:
                if url and url not in seen_urls:
                    seen_urls.add(url)
                    references.append(f"[{len(references) + 1}] {url}")
            
            # 如果 source_urls 为空，使用 visited_urls
            if not references and visited_urls:
                for url in visited_urls:
                    if url and url not in seen_urls:
                        seen_urls.add(url)
                        references.append(f"[{len(references) + 1}] {url}")
            
            if references:
                report_content = report_content.rstrip() + "\n\n## 参考文献\n\n" + "\n".join(references)
                logger.info(f"已添加 {len(references)} 个来源的参考文献")
        
        # 构建 OpenAI 兼容的响应
        openai_response = {
            "id": f"chatcmpl-{hash(report_content) % 10**24:024d}",
            "object": "chat.completion",
            "created": int(time.time()),
            "model": model,
            "choices": [
                {
                    "index": 0,
                    "message": {
                        "role": "assistant",
                        "content": report_content
                    },
                    "finish_reason": "stop"
                }
            ],
            "usage": {
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "total_tokens": 0
            },
            "metadata": {
                "research_id": report_response.get("research_id"),
                "source_urls": source_urls,
                "visited_urls": list(visited_urls) if visited_urls else [],
                "research_information": research_info
            }
        }
        
        return openai_response
    
    def _format_references(self, metadata: Dict[str, Any]) -> str:
        """从 metadata 中提取搜索来源并格式化为参考文献"""
        if not metadata or "tool_calls" not in metadata:
            return ""
        
        references = []
        seen_urls = set()  # 避免重复的 URL
        
        # 遍历所有工具调用
        for tool_call in metadata.get("tool_calls", []):
            if tool_call.get("tool") == "quick_search":
                search_metadata = tool_call.get("search_metadata", {})
                sources = search_metadata.get("sources", [])
                
                for idx, source in enumerate(sources, 1):
                    url = source.get("url", "")
                    title = source.get("title", "")
                    
                    # 跳过空 URL 和重复的 URL
                    if not url or url in seen_urls:
                        continue
                    
                    seen_urls.add(url)
                    
                    # 格式化参考文献
                    if title:
                        references.append(f"[{len(references) + 1}] {title}. {url}")
                    else:
                        references.append(f"[{len(references) + 1}] {url}")
        
        if references:
            return "\n\n## 参考文献\n\n" + "\n".join(references)
        return ""
    
    def _convert_to_openai_format(
        self, 
        gpt_researcher_response: Dict[str, Any],
        model: str = "gpt-researcher"
    ) -> Dict[str, Any]:
        """将 GPT-Researcher 响应转换为 OpenAI 兼容格式"""
        if "error" in gpt_researcher_response:
            raise Exception(gpt_researcher_response["error"])
        
        assistant_message = gpt_researcher_response.get("response", {})
        content = assistant_message.get("content", "")
        timestamp = assistant_message.get("timestamp", int(time.time() * 1000))
        metadata = assistant_message.get("metadata", {})
        
        # 从 metadata 中提取搜索来源并格式化为参考文献
        references = self._format_references(metadata)
        
        # 如果有关键词搜索，在内容末尾添加参考文献
        if references and metadata:
            # 检查是否有工具调用（说明进行了网络搜索）
            tool_calls = metadata.get("tool_calls", [])
            if tool_calls:
                # 将参考文献添加到内容末尾
                content = content.rstrip() + references
                logger.info(f"已添加 {len([tc for tc in tool_calls if tc.get('tool') == 'quick_search'])} 个搜索来源的参考文献")
        
        # 构建 OpenAI 兼容的响应
        openai_response = {
            "id": f"chatcmpl-{hash(content) % 10**24:024d}",
            "object": "chat.completion",
            "created": timestamp // 1000,  # 转换为秒
            "model": model,
            "choices": [
                {
                    "index": 0,
                    "message": {
                        "role": "assistant",
                        "content": content
                    },
                    "finish_reason": "stop"
                }
            ],
            "usage": {
                "prompt_tokens": 0,  # GPT-Researcher 不返回 token 使用量
                "completion_tokens": 0,
                "total_tokens": 0
            }
        }
        
        # 添加 metadata（如果有）
        if metadata:
            openai_response["metadata"] = metadata
        
        return openai_response
    
    def chat_completions(
        self,
        messages: List[Dict[str, str]],
        model: str = "gpt-researcher",
        report: str = "",
        use_report_endpoint: bool = True,  # 是否使用 /report/ 端点（默认使用）
        report_type: str = "research_report",  # "research_report" 或 "detailed_report"
        tone: str = "informative",  # "informative", "analytical", "casual" 等
        **options
    ) -> Dict[str, Any]:
        """
        调用 GPT-Researcher API，返回 OpenAI 兼容格式
        
        Args:
            messages: OpenAI 格式的消息列表
            model: 模型名称（用于响应格式）
            report: 研究报告内容（可选，仅用于 /api/chat 端点）
            use_report_endpoint: 是否使用 /report/ 端点生成完整研究报告（默认 True）
            report_type: 报告类型，"research_report"（快速）或 "detailed_report"（详细）
            tone: 报告语调，"informative", "analytical", "casual" 等
            **options: 其他选项
        
        Returns:
            OpenAI 兼容格式的响应
        """
        try:
            if use_report_endpoint:
                # 使用 /report/ 端点生成完整研究报告
                request_data = self._convert_to_gpt_researcher_report_format(
                    messages, report_type=report_type, tone=tone
                )
                
                logger.info(f"调用 GPT-Researcher /report/ 端点生成研究报告: {self.report_endpoint}")
                logger.info(f"研究任务: {request_data['task'][:50]}...")
                
                try:
                    response = requests.post(
                        self.report_endpoint,
                        json=request_data,
                        timeout=self.timeout,
                        headers={"Content-Type": "application/json"}
                    )
                    response.raise_for_status()
                    result = response.json()
                    
                    # 转换为 OpenAI 格式（/report/ 端点的响应格式不同）
                    return self._convert_report_response_to_openai_format(result, model)
                except requests.exceptions.Timeout as e:
                    error_msg = f"GPT-Researcher /report/ 端点超时（超过 {self.timeout} 秒）"
                    logger.error(f"{error_msg}: {e}")
                    logger.warning("研究任务可能仍在进行中，但请求已超时")
                    logger.warning("回退到 /api/chat 端点（功能受限，但不需要 embeddings）")
                    # 回退到 /api/chat 端点
                    return self._fallback_to_chat_endpoint(messages, model, report)
                except requests.exceptions.HTTPError as e:
                    if e.response.status_code == 500:
                        error_msg = "GPT-Researcher /report/ 端点错误（可能是 embedding 配置问题）"
                        logger.error(f"{error_msg}: {e}")
                        logger.warning("回退到 /api/chat 端点（功能受限，但不需要 embeddings）")
                        # 回退到 /api/chat 端点
                        return self._fallback_to_chat_endpoint(messages, model, report)
                    else:
                        raise
            else:
                # 使用 /api/chat 端点进行聊天（保留兼容性）
                request_data = self._convert_to_gpt_researcher_chat_format(messages, report)
                
                logger.info(f"调用 GPT-Researcher /api/chat 端点: {self.chat_endpoint}")
                response = requests.post(
                    self.chat_endpoint,
                    json=request_data,
                    timeout=self.timeout,
                    headers={"Content-Type": "application/json"}
                )
                response.raise_for_status()
                result = response.json()
                
                # 转换为 OpenAI 格式
                return self._convert_to_openai_format(result, model)
            
        except requests.exceptions.RequestException as e:
            logger.error(f"GPT-Researcher API 请求失败: {e}")
            raise Exception(f"GPT-Researcher API 请求失败: {str(e)}")
        except Exception as e:
            logger.error(f"GPT-Researcher 适配器错误: {e}")
            raise
    
    def chat_completions_stream(
        self,
        messages: List[Dict[str, str]],
        model: str = "gpt-researcher",
        report: str = "",
        use_report_endpoint: bool = True,  # 是否使用 /report/ 端点（默认使用）
        report_type: str = "research_report",
        tone: str = "informative",
        progress_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
        **options
    ) -> Iterator[Dict[str, Any]]:
        """
        流式调用 GPT-Researcher API（模拟流式）
        
        注意：GPT-Researcher 当前不支持真正的流式响应，
        此方法会先获取完整响应，然后模拟流式输出
        
        Args:
            messages: OpenAI 格式的消息列表
            model: 模型名称
            report: 研究报告内容（可选）
            **options: 其他选项
        
        Yields:
            OpenAI 兼容格式的流式响应块
        """
        try:
            # 如果提供了进度回调，尝试使用 WebSocket 获取实时进度
            if progress_callback and use_report_endpoint:
                try:
                    yield from self._stream_with_websocket_progress(
                        messages, model, report, report_type, tone, progress_callback, **options
                    )
                    return
                except Exception as e:
                    logger.warning(f"WebSocket 进度获取失败，回退到传统方式: {e}")
            
            # 传统方式：先获取完整响应
            logger.info(f"开始调用 GPT-Researcher API 获取完整响应...")
            # 传递 use_report_endpoint 参数
            full_response = self.chat_completions(
                messages, 
                model, 
                report, 
                use_report_endpoint=use_report_endpoint,
                report_type=report_type,
                tone=tone,
                **options
            )
            content = full_response["choices"][0]["message"]["content"]
            response_id = full_response["id"]
            created = full_response["created"]
            logger.info(f"GPT-Researcher 响应获取成功，内容长度: {len(content)} 字符，开始模拟流式输出...")
            
            # 模拟流式输出（按字符或词分割）
            # 为了更好的用户体验，按句子分割，并添加适当延迟
            import re
            import time
            
            # 按句子分割（保留分隔符）
            sentences = re.split(r'([。！？\n])', content)
            
            buffer = ""
            chunk_size = 20  # 每次发送约20个字符
            delay_between_chunks = 0.05  # 每个chunk之间延迟50ms，模拟真实流式
            
            for i, part in enumerate(sentences):
                buffer += part
                # 当buffer达到chunk_size或遇到句子结束符时发送
                if len(buffer) >= chunk_size or (part in ['。', '！', '？', '\n'] and buffer):
                    if buffer:
                        yield {
                            "id": response_id,
                            "object": "chat.completion.chunk",
                            "created": created,
                            "model": model,
                            "choices": [
                                {
                                    "index": 0,
                                    "delta": {"content": buffer},
                                    "finish_reason": None
                                }
                            ]
                        }
                        # 添加延迟，模拟真实流式输出
                        time.sleep(delay_between_chunks)
                        buffer = ""
            
            # 发送完成标记
            yield {
                "id": response_id,
                "object": "chat.completion.chunk",
                "created": created,
                "model": model,
                "choices": [
                    {
                        "index": 0,
                        "delta": {},
                        "finish_reason": "stop"
                    }
                ]
            }
            
        except Exception as e:
            logger.error(f"GPT-Researcher 流式适配器错误: {e}")
            raise
    
    def _stream_with_websocket_progress(
        self,
        messages: List[Dict[str, str]],
        model: str,
        report: str,
        report_type: str,
        tone: str,
        progress_callback: Callable[[Dict[str, Any]], None],
        **options
    ) -> Iterator[Dict[str, Any]]:
        """
        通过 WebSocket 获取实时进度，然后流式输出最终报告
        """
        import queue
        
        # 用于存储进度和最终结果
        progress_queue = queue.Queue()
        result_queue = queue.Queue()
        error_queue = queue.Queue()
        
        # 获取用户消息
        user_message = ""
        if messages and messages[-1].get("role") == "user":
            user_message = messages[-1].get("content", "")
        
        # 在后台线程中运行 WebSocket 客户端
        def ws_client_thread():
            try:
                asyncio.run(self._ws_client_async(
                    user_message, report_type, tone, progress_queue, result_queue, error_queue
                ))
            except Exception as e:
                logger.error(f"WebSocket 客户端线程错误: {e}")
                error_queue.put(e)
        
        # 启动 WebSocket 客户端线程
        ws_thread = threading.Thread(target=ws_client_thread, daemon=True)
        ws_thread.start()
        time.sleep(0.5)  # 等待连接建立
        
        # 流式输出：先发送进度，再发送最终内容
        final_content = None
        timeout = time.time() + GPT_RESEARCHER_TIMEOUT
        last_progress_time = time.time()
        
        while time.time() < timeout:
            # 检查错误（但排除需要回退到HTTP的标记）
            try:
                error = error_queue.get_nowait()
                # 如果是需要回退到HTTP的标记，不抛出异常，而是标记需要回退
                if "需要回退到HTTP请求" in str(error):
                    logger.info("检测到需要回退到HTTP请求的标记")
                    final_content = None  # 确保触发回退逻辑
                    break
                raise error
            except queue.Empty:
                pass
            
            # 检查进度更新
            had_progress = False
            try:
                while True:
                    progress = progress_queue.get_nowait()
                    if progress_callback:
                        progress_callback(progress)
                    last_progress_time = time.time()
                    had_progress = True
            except queue.Empty:
                pass

            # 如果本轮有新的进度，让调用方的 for-loop 至少跑一轮，
            # 这样 SSE 层就可以及时把 progress flush 给前端
            if had_progress:
                yield {
                    "id": f"progress-{int(time.time() * 1000)}",
                    "object": "chat.completion.chunk",
                    "created": int(time.time()),
                    "model": model,
                    "choices": [
                        {
                            "index": 0,
                            "delta": {},  # 不携带内容，仅用于驱动外层循环
                            "finish_reason": None,
                        }
                    ],
                }
            
            # 检查最终结果
            try:
                final_content = result_queue.get_nowait()
                break
            except queue.Empty:
                pass
            
            # 如果超过 5 秒没有进度更新，发送心跳
            if time.time() - last_progress_time > 5:
                if progress_callback:
                    progress_callback({
                        "type": "progress",
                        "content": "info",
                        "output": "研究任务进行中，请稍候..."
                    })
                last_progress_time = time.time()
            
            time.sleep(0.1)
        
        # 如果超时，尝试获取最终结果或回退
        if final_content is None:
            try:
                final_content = result_queue.get(timeout=2)
            except queue.Empty:
                logger.warning("WebSocket 超时，回退到传统 HTTP 请求")
                full_response = self.chat_completions(
                    messages, model, report, 
                    use_report_endpoint=True,
                    report_type=report_type,
                    tone=tone,
                    **options
                )
                final_content = full_response["choices"][0]["message"]["content"]
        
        # 流式输出最终内容
        if final_content:
            response_id = f"chatcmpl-{hash(final_content) % 10**24:024d}"
            created = int(time.time())
            import re
            sentences = re.split(r'([。！？\n])', final_content)
            buffer = ""
            chunk_size = 20
            delay_between_chunks = 0.05
            
            for part in sentences:
                buffer += part
                if len(buffer) >= chunk_size or (part in ['。', '！', '？', '\n'] and buffer):
                    if buffer:
                        yield {
                            "id": response_id,
                            "object": "chat.completion.chunk",
                            "created": created,
                            "model": model,
                            "choices": [{
                                "index": 0,
                                "delta": {"content": buffer},
                                "finish_reason": None
                            }]
                        }
                        time.sleep(delay_between_chunks)
                        buffer = ""
            
            yield {
                "id": response_id,
                "object": "chat.completion.chunk",
                "created": created,
                "model": model,
                "choices": [{
                    "index": 0,
                    "delta": {},
                    "finish_reason": "stop"
                }]
            }
    
    async def _ws_client_async(
        self,
        task: str,
        report_type: str,
        tone: str,
        progress_queue: queue.Queue,
        result_queue: queue.Queue,
        error_queue: queue.Queue
    ):
        """异步 WebSocket 客户端"""
        try:
            ws_url = GPT_RESEARCHER_WS_URL
            logger.info(f"连接到 GPT-Researcher WebSocket: {ws_url}")
            
            async with websockets.connect(ws_url) as websocket:
                request_data = {
                    "task": task,
                    "report_type": report_type,
                    "report_source": "web",
                    "tone": self._normalize_tone(tone),
                    "headers": None,
                    "repo_name": "",
                    "branch_name": "",
                    "generate_in_background": False
                }
                
                start_command = f"start {json.dumps(request_data)}"
                await websocket.send(start_command)
                logger.info("已发送研究任务请求到 WebSocket")
                
                report_received = False
                while not report_received:
                    try:
                        message = await asyncio.wait_for(websocket.recv(), timeout=2.0)
                        
                        if isinstance(message, str):
                            if message == "pong":
                                continue
                            
                            try:
                                data = json.loads(message)
                                if data.get("type") == "logs":
                                    progress_queue.put({
                                        "type": "progress",
                                        "content": data.get("content", ""),
                                        "output": data.get("output", "")
                                    })
                                elif data.get("type") == "report" or "report" in data:
                                    report_content = data.get("report", data.get("content", ""))
                                    if report_content:
                                        result_queue.put(report_content)
                                        report_received = True
                                        break
                                elif data.get("type") == "path":
                                    # 收到文件路径，说明报告已完成
                                    # 如果还没有收到报告内容，使用备用方案：通过 HTTP 请求获取
                                    file_paths = data.get("output", {})
                                    logger.info(f"收到文件路径: {file_paths}")
                                    
                                    # 如果还没有收到报告内容，标记需要回退到 HTTP 请求
                                    if not report_received:
                                        logger.warning("通过 WebSocket 未收到报告内容，将使用备用 HTTP 请求")
                                        # 设置一个特殊标记，让外层代码知道需要回退
                                        error_queue.put(Exception("WebSocket未返回报告内容，需要回退到HTTP请求"))
                                        report_received = True
                                        break
                            except json.JSONDecodeError:
                                if len(message) > 100 and ("报告" in message or "report" in message.lower()):
                                    result_queue.put(message)
                                    report_received = True
                                    break
                    except asyncio.TimeoutError:
                        await websocket.send("ping")
                        continue
        except Exception as e:
            logger.error(f"WebSocket 客户端错误: {e}")
            error_queue.put(e)


# 全局适配器实例
_gpt_researcher_adapter: Optional[GPTResearcherAdapter] = None


def get_gpt_researcher_adapter() -> GPTResearcherAdapter:
    """获取 GPT-Researcher 适配器实例（单例模式）"""
    global _gpt_researcher_adapter
    if _gpt_researcher_adapter is None:
        _gpt_researcher_adapter = GPTResearcherAdapter()
    return _gpt_researcher_adapter


def detect_task_type(user_message: str) -> str:
    """
    检测任务类型，决定使用哪个服务
    
    Args:
        user_message: 用户消息内容
    
    Returns:
        'research': 研究任务，使用 GPT-Researcher
        'data': 数据分析任务，使用 DeepAnalyze
        'chat': 通用聊天，使用默认服务
    """
    message_lower = user_message.lower()
    
    # 研究任务关键词
    research_keywords = [
        '研究', '报告', '分析', '调研', '调查', '研究一下', '研究报告',
        'research', 'report', 'analyze', 'investigate', 'study', 'analysis'
    ]
    
    # 数据分析任务关键词（增强版）
    data_keywords = [
        '数据', '表格', '图表', '可视化', 'csv', 'excel', '数据分析', '数据处理',
        '数据统计', '数据计算', '数据挖掘', '数据科学', '数据探索',
        'data', 'table', 'chart', 'visualization', 'analyze data', 'data analysis',
        'data processing', 'data science', 'data exploration', 'statistics', 'statistical'
    ]
    
    # 检查研究任务（优先匹配，使用更精确的关键词）
    # 检查是否包含明确的研究意图关键词
    research_patterns = [
        '研究一下', '研究', '调研', '调查报告', '分析报告', '研究报告',
        'research', 'investigate', 'study', 'analysis report'
    ]
    
    for pattern in research_patterns:
        if pattern in message_lower:
            logger.info(f"检测到研究任务关键词: '{pattern}' 在消息中")
            return 'research'
    
    # 检查"分析"关键词（但需要排除一些常见聊天场景）
    if '分析' in message_lower or 'analyze' in message_lower:
        # 如果明确提到数据分析相关词汇，优先判断为数据分析任务
        if any(kw in message_lower for kw in ['数据', 'data', '表格', 'table', 'csv', 'excel']):
            logger.info(f"检测到数据分析任务关键词")
            return 'data'
        # 排除简单的聊天场景
        if not any(word in message_lower for word in ['帮我', '请', '可以', '能', 'help', 'please', 'can']):
            logger.info(f"检测到分析任务关键词")
            return 'research'
    
    # 检查数据分析任务（优先于通用聊天）
    if any(kw in message_lower for kw in data_keywords):
        logger.info(f"检测到数据分析任务关键词")
        return 'data'
    
    # 默认通用聊天
    logger.info(f"未检测到研究任务，使用默认聊天服务")
    return 'chat'

