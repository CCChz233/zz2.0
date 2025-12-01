# -*- coding: utf-8 -*-
"""
DeepAnalyze API 适配层
-----------------------
将 DeepAnalyze 的 API 格式转换为 OpenAI 兼容格式
DeepAnalyze 本身已经是 OpenAI 兼容的，所以适配层相对简单
"""

import os
import time
from typing import List, Dict, Any, Optional, Iterator, Callable
import logging

try:
    import openai
except ImportError:
    openai = None
    logging.warning("openai 包未安装，DeepAnalyze 适配器将无法工作")

logger = logging.getLogger(__name__)

# ===== 配置 =====
DEEPANALYZE_BASE_URL = os.getenv("DEEPANALYZE_BASE_URL", "http://localhost:8200")
DEEPANALYZE_TIMEOUT = int(os.getenv("DEEPANALYZE_TIMEOUT", "300"))  # 5分钟超时
# DeepAnalyze 内部使用的模型名（需要与 DeepAnalyze/.env 中的 QWEN_MODEL_NAME 一致）
DEEPANALYZE_MODEL = os.getenv("DEEPANALYZE_MODEL", "qwen-plus")


class DeepAnalyzeAdapter:
    """DeepAnalyze API 适配器，转换为 OpenAI 兼容格式"""
    
    def __init__(self, base_url: str = None):
        if openai is None:
            raise ImportError("openai 包未安装，请运行: pip install openai")
        
        self.base_url = base_url or DEEPANALYZE_BASE_URL
        # DeepAnalyze 使用 OpenAI 兼容的 API，所以可以直接使用 OpenAI SDK
        self.client = openai.OpenAI(
            base_url=f"{self.base_url}/v1",
            api_key="dummy",  # DeepAnalyze 不需要真实的 API key
            timeout=DEEPANALYZE_TIMEOUT
        )
        logger.info(f"DeepAnalyze 适配器初始化完成，base_url: {self.base_url}")
    
    def chat_completions(
        self,
        messages: List[Dict[str, str]],
        model: str = None,
        **options
    ) -> Dict[str, Any]:
        """
        调用 DeepAnalyze API，返回 OpenAI 兼容格式
        
        Args:
            messages: OpenAI 格式的消息列表
            model: 模型名称（DeepAnalyze 使用默认模型）
            **options: 其他选项（temperature, max_tokens 等）
        
        Returns:
            OpenAI 兼容格式的响应
        """
        try:
            # 使用配置的模型名，而不是传入的 model 参数
            actual_model = model or DEEPANALYZE_MODEL
            logger.info(f"调用 DeepAnalyze API: {self.base_url}/v1/chat/completions")
            logger.info(f"消息数量: {len(messages)}, 模型: {actual_model}")
            
            # DeepAnalyze 的 API 是 OpenAI 兼容的，直接调用
            response = self.client.chat.completions.create(
                model=actual_model,
                messages=messages,
                stream=False,
                **options
            )
            
            # 转换为标准字典格式
            result = {
                "id": response.id,
                "object": "chat.completion",
                "created": response.created,
                "model": response.model,
                "choices": [
                    {
                        "index": choice.index,
                        "message": {
                            "role": choice.message.role,
                            "content": choice.message.content
                        },
                        "finish_reason": choice.finish_reason
                    } for choice in response.choices
                ],
                "usage": {
                    "prompt_tokens": response.usage.prompt_tokens if response.usage else 0,
                    "completion_tokens": response.usage.completion_tokens if response.usage else 0,
                    "total_tokens": response.usage.total_tokens if response.usage else 0
                }
            }
            
            # 如果有生成的文件，添加到响应中
            if hasattr(response, 'generated_files') and response.generated_files:
                result["generated_files"] = response.generated_files
            
            logger.info(f"DeepAnalyze API 调用成功，响应长度: {len(result['choices'][0]['message']['content']) if result['choices'] else 0} 字符")
            return result
            
        except Exception as e:
            logger.error(f"DeepAnalyze API 调用失败: {e}")
            raise Exception(f"DeepAnalyze API 调用失败: {str(e)}")
    
    def chat_completions_stream(
        self,
        messages: List[Dict[str, str]],
        model: str = None,
        progress_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
        **options
    ) -> Iterator[Dict[str, Any]]:
        """
        流式调用 DeepAnalyze API
        
        DeepAnalyze 原生支持 OpenAI 兼容的流式响应，所以直接使用即可
        
        Args:
            messages: OpenAI 格式的消息列表
            model: 模型名称
            progress_callback: 进度回调函数（可选，DeepAnalyze 暂不支持进度回调）
            **options: 其他选项
        
        Yields:
            OpenAI 兼容格式的流式响应块
        """
        try:
            # 使用配置的模型名，而不是传入的 model 参数
            actual_model = model or DEEPANALYZE_MODEL
            logger.info(f"开始流式调用 DeepAnalyze API: {self.base_url}/v1/chat/completions, 模型: {actual_model}")
            
            # DeepAnalyze 支持原生流式响应
            stream = self.client.chat.completions.create(
                model=actual_model,
                messages=messages,
                stream=True,
                **options
            )
            
            for chunk in stream:
                # 转换为 OpenAI 兼容的流式格式
                chunk_data = {
                    "id": chunk.id,
                    "object": "chat.completion.chunk",
                    "created": chunk.created,
                    "model": chunk.model,
                    "choices": [
                        {
                            "index": choice.index,
                            "delta": {
                                "content": choice.delta.content or ""
                            },
                            "finish_reason": choice.finish_reason
                        } for choice in chunk.choices
                    ]
                }
                
                # 如果有生成的文件信息，添加到最后一个 chunk
                if hasattr(chunk, 'generated_files') and chunk.generated_files:
                    chunk_data["generated_files"] = chunk.generated_files
                
                yield chunk_data
                
        except Exception as e:
            logger.error(f"DeepAnalyze 流式调用失败: {e}")
            raise Exception(f"DeepAnalyze 流式调用失败: {str(e)}")


# 全局适配器实例
_deepanalyze_adapter: Optional[DeepAnalyzeAdapter] = None


def get_deepanalyze_adapter() -> DeepAnalyzeAdapter:
    """获取 DeepAnalyze 适配器实例（单例模式）"""
    global _deepanalyze_adapter
    if _deepanalyze_adapter is None:
        _deepanalyze_adapter = DeepAnalyzeAdapter()
    return _deepanalyze_adapter

