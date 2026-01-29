# -*- coding: utf-8 -*-
"""
工具调用决策引擎
---------------
功能：智能决定何时调用哪个工具/MCP
设计：多级决策（用户指定 > 规则引擎 > LLM决策）
"""

import re
import os
import asyncio
from typing import Dict, List, Optional, Any
from datetime import datetime

from backend_api.mcp_manager import mcp_manager
from infra.llm import call_volcano_chat as llm_chat


class ToolDecisionEngine:
    """工具调用决策引擎"""

    def __init__(self):
        self.rules = self._load_rules()
        self.llm_decider = LLMToolDecider()

    async def decide(
        self,
        user_message: str,
        conversation_context: List[Dict],
        available_tools: List[str],
        user_preference: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        决策工具调用

        Args:
            user_message: 用户消息
            conversation_context: 对话上下文
            available_tools: 可用工具列表
            user_preference: 用户明确指定的工具（优先级最高）

        Returns:
            {
                "tool_name": str,
                "tool_type": str,  # 'mcp', 'builtin', 'llm'
                "arguments": dict,
                "confidence": float,
                "reason": str
            }
        """

        # 级别1: 用户明确指定（最高优先级）
        if user_preference and user_preference != "auto":
            decision = self._handle_user_preference(
                user_preference, user_message
            )
            if decision:
                return decision

        # 级别2: 确定性规则（零失误场景）
        decision = self._apply_rules(user_message, conversation_context)
        if decision and decision.get("confidence", 0) > 0.9:
            return decision

        # 级别3: LLM决策（不确定场景）
        decision = await self.llm_decider.decide(
            user_message, conversation_context, available_tools
        )

        return decision

    def _handle_user_preference(
        self,
        preference: str,
        message: str
    ) -> Optional[Dict]:
        """处理用户明确指定"""

        # GPT-Researcher
        if preference == "research":
            return {
                "tool_name": "gpt_researcher",
                "tool_type": "builtin",
                "arguments": {"query": message},
                "confidence": 1.0,
                "reason": "用户明确指定研究任务"
            }

        # DeepAnalyze
        elif preference == "data":
            return {
                "tool_name": "deepanalyze",
                "tool_type": "builtin",
                "arguments": {"query": message},
                "confidence": 1.0,
                "reason": "用户明确指定数据分析任务"
            }

        # 普通聊天
        elif preference == "chat":
            return {
                "tool_name": "default_llm",
                "tool_type": "llm",
                "arguments": {"messages": [{"role": "user", "content": message}]},
                "confidence": 1.0,
                "reason": "用户明确指定聊天任务"
            }

        # MCP工具（格式: mcp:server_id:tool_name）
        elif preference.startswith("mcp:"):
            parts = preference.split(":")
            if len(parts) >= 3:
                server_id = parts[1]
                tool_name = parts[2]
                return {
                    "tool_name": tool_name,
                    "tool_type": "mcp",
                    "server_id": server_id,
                    "arguments": {"query": message},
                    "confidence": 1.0,
                    "reason": f"用户明确指定MCP工具: {server_id}/{tool_name}"
                }

        return None

    def _apply_rules(
        self,
        message: str,
        context: List[Dict]
    ) -> Optional[Dict]:
        """应用确定性规则"""

        message_lower = message.lower()

        # 规则1: 明确的研究意图
        if self._matches_patterns(message, self.rules["research_patterns"]):
            return {
                "tool_name": "gpt_researcher",
                "tool_type": "builtin",
                "arguments": {"query": message},
                "confidence": 0.95,
                "reason": "检测到研究关键词"
            }

        # 规则2: GitHub相关查询
        if self._matches_patterns(message, self.rules["github_patterns"]):
            # 检查GitHub MCP是否可用
            if "github" in mcp_manager.servers:
                return {
                    "tool_name": "search_repositories",
                    "tool_type": "mcp",
                    "server_id": "github",
                    "arguments": {"query": message},
                    "confidence": 0.92,
                    "reason": "检测到GitHub查询意图"
                }

        # 规则3: 文件操作
        if self._matches_patterns(message, self.rules["file_patterns"]):
            if "filesystem" in mcp_manager.servers:
                # 提取文件路径
                path = self._extract_path(message)
                return {
                    "tool_name": "read_file",
                    "tool_type": "mcp",
                    "server_id": "filesystem",
                    "arguments": {"path": path},
                    "confidence": 0.90,
                    "reason": "检测到文件读取意图"
                }

        # 规则4: 数据分析任务
        if self._matches_patterns(message, self.rules["data_analysis_patterns"]):
            # 检查是否有文件引用
            if self._has_file_attachment(context):
                return {
                    "tool_name": "deepanalyze",
                    "tool_type": "builtin",
                    "arguments": {
                        "task": message,
                        "files": self._get_files(context)
                    },
                    "confidence": 0.93,
                    "reason": "检测到数据分析+文件"
                }

        # 规则5: 时效性查询（需要搜索）
        if self._matches_patterns(message, self.rules["time_sensitive_patterns"]):
            # 优先使用MCP统一搜索（如果可用）
            if "unified-search" in mcp_manager.servers:
                return {
                    "tool_name": "search_all",
                    "tool_type": "mcp",
                    "server_id": "unified-search",
                    "arguments": {
                        "query": message,
                        "web_enabled": True,
                        "db_enabled": True
                    },
                    "confidence": 0.85,
                    "reason": "检测到时效性查询"
                }

        return None  # 规则不匹配，交给LLM

    def _matches_patterns(self, text: str, patterns: List[str]) -> bool:
        """匹配关键词模式"""
        text_lower = text.lower()
        return any(pattern.lower() in text_lower for pattern in patterns)

    def _extract_path(self, text: str) -> str:
        """从文本中提取文件路径"""
        # 简单的正则匹配
        match = re.search(r'["\']?([\w/\-\.]+)["\']?', text)
        return match.group(1) if match else "/"

    def _has_file_attachment(self, context: List[Dict]) -> bool:
        """检查是否有文件附件"""
        for msg in context:
            if msg.get("role") == "user":
                content = msg.get("content", "")
                if any(ext in content.lower() for ext in [".csv", ".xlsx", ".json", ".txt"]):
                    return True
        return False

    def _get_files(self, context: List[Dict]) -> List[str]:
        """从上下文中提取文件路径"""
        files = []
        for msg in context:
            if msg.get("role") == "user":
                content = msg.get("content", "")
                # 提取文件路径（简化版）
                if ".csv" in content.lower():
                    files.append(content.split()[-1])
        return files

    def _load_rules(self) -> Dict:
        """加载规则配置"""
        return {
            "research_patterns": [
                "研究", "研究报告", "调研", "调查", "分析报告",
                "research", "investigate", "study", "深度分析"
            ],
            "github_patterns": [
                "github", "仓库", "repo", "commit", "pr", "issue",
                "代码", "开源项目", "源码"
            ],
            "file_patterns": [
                "读取文件", "查看文件", "打开文件", "文件内容",
                "read file", "open file", "查看文档"
            ],
            "data_analysis_patterns": [
                "分析数据", "数据处理", "csv", "excel", "数据统计",
                "analyze data", "data processing", "数据可视化"
            ],
            "time_sensitive_patterns": [
                "最新", "最近", "今天", "新闻", "发布", "公告",
                "latest", "recent", "news", "announcement"
            ]
        }


class LLMToolDecider:
    """LLM工具决策器"""

    async def decide(
        self,
        user_message: str,
        context: List[Dict],
        available_tools: List[str]
    ) -> Dict:
        """使用LLM决策工具调用"""

        # 构建决策提示词
        tools_desc = self._build_tools_description(available_tools)

        prompt = f"""你是一个工具调用决策助手。根据用户输入，决定是否需要调用工具。

可用工具：
{tools_desc}

用户输入：{user_message}

对话上下文（最近3条）：
{self._format_context(context[-3:])}

请分析用户意图，返回JSON格式：
{{
    "should_call_tool": true/false,
    "tool_name": "工具名称或default_llm",
    "tool_type": "mcp/builtin/llm",
    "reason": "决策理由",
    "confidence": 0.0-1.0,
    "arguments": {{"参数名": "参数值"}}
}}

规则：
1. 如果需要研究、报告 → 使用 gpt_researcher
2. 如果需要数据分析 → 使用 deepanalyze
3. 如果需要搜索最新信息 → 使用 unified-search MCP
4. 如果需要查询GitHub → 使用 github MCP
5. 如果只是普通聊天 → 使用 default_llm
"""

        try:
            # 调用LLM（使用小型模型）
            response = llm_chat(
                [{"role": "user", "content": prompt}],
                temperature=0.1,
                max_tokens=500
            )

            # 解析响应
            response_text = ""
            if hasattr(response, 'json'):
                data = response.json()
                response_text = data.get("choices", [{}])[0].get("message", {}).get("content", "")
            else:
                response_text = str(response)

            # 提取JSON（处理可能的markdown格式）
            json_match = re.search(r'\{[^{}]+\}', response_text, re.DOTALL)
            if json_match:
                import json
                decision = json.loads(json_match.group())

                return {
                    "tool_name": decision.get("tool_name", "default_llm"),
                    "tool_type": decision.get("tool_type", "llm"),
                    "arguments": decision.get("arguments", {}),
                    "confidence": decision.get("confidence", 0.75),
                    "reason": decision.get("reason", "LLM决策")
                }

        except Exception as e:
            print(f"⚠️ LLM决策失败: {e}")

        # 回退到默认
        return {
            "tool_name": "default_llm",
            "tool_type": "llm",
            "arguments": {},
            "confidence": 0.5,
            "reason": "LLM决策失败，使用默认LLM"
        }

    def _build_tools_description(self, tools: List[str]) -> str:
        """构建工具描述"""
        descriptions = {
            "gpt_researcher": "深度研究报告（适合需要全面调研的任务）",
            "deepanalyze": "数据分析（适合处理CSV、Excel数据）",
            "default_llm": "通用对话（无需工具的聊天）",
            "unified-search": "综合搜索（适合查询最新信息、新闻）",
            "github": "GitHub代码搜索（适合查询代码仓库、Issues）"
        }

        lines = []
        for tool in tools:
            desc = descriptions.get(tool, "未知工具")
            lines.append(f"- {tool}: {desc}")

        return "\n".join(lines)

    def _format_context(self, context: List[Dict]) -> str:
        """格式化上下文"""
        if not context:
            return "无"

        lines = []
        for msg in context:
            role = msg.get("role", "unknown")
            content = msg.get("content", "")[:100]
            lines.append(f"{role}: {content}...")

        return "\n".join(lines)


# 全局单例
tool_decision_engine = ToolDecisionEngine()
