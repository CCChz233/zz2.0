# -*- coding: utf-8 -*-
"""
配置管理模块
------------
用于加载和管理系统提示词配置
"""

import os
import json
from typing import Dict, List, Any, Optional

# 配置文件路径
CONFIG_DIR = os.path.dirname(os.path.abspath(__file__))
PROMPTS_CONFIG_FILE = os.path.join(CONFIG_DIR, "prompts.json")

# 缓存配置
_cached_config: Optional[Dict[str, Any]] = None


def _get_default_config() -> Dict[str, Any]:
    """默认配置"""
    return {
        "base_system_prompt": "你是致真精密仪器公司的智能体助手，专注于为致真精密仪器公司提供专业的业务支持。你的主要职责包括：1) 分析公司相关的业务数据、市场信息、技术趋势；2) 生成与公司产品（精密仪器、半导体测试设备、磁性测量仪器等）相关的研究报告；3) 提供针对公司业务发展的建议和洞察。请始终围绕致真精密仪器公司的业务场景进行回答，用简洁、专业的语气回复。",
        "global_prompts": [],
        "default_options": {
            "temperature": 0.8,
            "top_p": 0.8
        }
    }


def load_prompts_config() -> Dict[str, Any]:
    """加载提示词配置"""
    global _cached_config
    
    if _cached_config is not None:
        return _cached_config
    
    try:
        with open(PROMPTS_CONFIG_FILE, 'r', encoding='utf-8') as f:
            _cached_config = json.load(f)
        return _cached_config
    except FileNotFoundError:
        print(f"⚠️ 配置文件不存在: {PROMPTS_CONFIG_FILE}，使用默认配置")
        _cached_config = _get_default_config()
        return _cached_config
    except json.JSONDecodeError as e:
        print(f"⚠️ 配置文件格式错误: {e}，使用默认配置")
        _cached_config = _get_default_config()
        return _cached_config
    except Exception as e:
        print(f"⚠️ 加载配置文件失败: {e}，使用默认配置")
        _cached_config = _get_default_config()
        return _cached_config


def get_base_system_prompt() -> str:
    """获取基础系统提示词（环境变量优先）"""
    # 环境变量优先
    env_prompt = os.getenv("BASE_SYSTEM_PROMPT")
    if env_prompt:
        return env_prompt
    
    # 从配置文件读取
    config = load_prompts_config()
    return config.get("base_system_prompt", "你是致真智能体，一个友好、专业的AI助手。")


def get_global_prompts() -> List[str]:
    """获取全局提示词列表"""
    config = load_prompts_config()
    return config.get("global_prompts", [])


def get_default_options() -> Dict[str, Any]:
    """获取默认API选项"""
    config = load_prompts_config()
    return config.get("default_options", {"temperature": 0.8, "top_p": 0.8})


def build_system_prompt(temporary_prompts: Optional[List[str]] = None) -> str:
    """构建完整的系统提示词
    
    Args:
        temporary_prompts: 临时提示词列表（可选）
    
    Returns:
        组合后的完整系统提示词
    """
    base = get_base_system_prompt()
    globals = get_global_prompts()
    temporaries = temporary_prompts or []
    
    # 组合所有提示词
    all_prompts = [base] + globals + temporaries
    
    # 过滤空字符串
    all_prompts = [p.strip() for p in all_prompts if p and p.strip()]
    
    return '\n\n'.join(all_prompts)


def reload_config():
    """重新加载配置（用于热更新）"""
    global _cached_config
    _cached_config = None
    return load_prompts_config()

