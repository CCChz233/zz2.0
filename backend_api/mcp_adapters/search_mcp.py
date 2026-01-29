# -*- coding: utf-8 -*-
"""
MCP搜索适配器 - 包装现有搜索功能
-------------------------------------
目的：在不改动现有代码的情况下，提供MCP接口
策略：Adapter模式，包装现有的 Tavily 和 RAG
"""

from mcp.server import Server
from mcp.types import Tool, TextContent
from typing import Any
import asyncio

# 导入现有模块（不修改）
from backend_api.web_search import search_web
from backend_api.rag.rag_search import run_semantic_retrieval

app = Server("unified-search")

@app.list_tools()
async def list_tools() -> list[Tool]:
    """列出搜索工具（MCP标准接口）"""
    return [
        Tool(
            name="search_web",
            description="网络搜索（通过Tavily）",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "搜索关键词"
                    },
                    "max_results": {
                        "type": "integer",
                        "description": "返回结果数量",
                        "default": 6
                    }
                },
                "required": ["query"]
            }
        ),
        Tool(
            name="search_database",
            description="本地知识库搜索（RAG）",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "搜索关键词"
                    },
                    "top_k": {
                        "type": "integer",
                        "description": "返回结果数量",
                        "default": 8
                    },
                    "min_sim": {
                        "type": "number",
                        "description": "最小相似度",
                        "default": 0.4
                    }
                },
                "required": ["query"]
            }
        ),
        Tool(
            name="search_all",
            description="综合搜索（同时搜索网络和本地知识库）",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "搜索关键词"
                    },
                    "web_enabled": {
                        "type": "boolean",
                        "description": "是否启用网络搜索",
                        "default": True
                    },
                    "db_enabled": {
                        "type": "boolean",
                        "description": "是否启用本地知识库搜索",
                        "default": True
                    }
                },
                "required": ["query"]
            }
        )
    ]

@app.call_tool()
async def call_tool(name: str, arguments: Any) -> list[TextContent]:
    """
    处理工具调用
    注意：这里只是包装现有函数，不修改任何逻辑
    """

    try:
        if name == "search_web":
            # 🔥 关键：直接调用现有函数，不修改
            results = await asyncio.to_thread(
                search_web,
                query=arguments["query"],
                max_results=arguments.get("max_results", 6)
            )
            return [TextContent(
                type="text",
                text=_format_web_results(results)
            )]

        elif name == "search_database":
            # 🔥 关键：直接调用现有函数，不修改
            results = await asyncio.to_thread(
                run_semantic_retrieval,
                question=arguments["query"],
                k=arguments.get("top_k", 8),
                min_sim=arguments.get("min_sim", 0.4)
            )
            return [TextContent(
                type="text",
                text=_format_db_results(results)
            )]

        elif name == "search_all":
            # 并行调用两个现有函数
            results = {}
            tasks = []

            if arguments.get("web_enabled", True):
                tasks.append(("web", asyncio.to_thread(
                    search_web,
                    query=arguments["query"],
                    max_results=6
                )))

            if arguments.get("db_enabled", True):
                tasks.append(("database", asyncio.to_thread(
                    run_semantic_retrieval,
                    question=arguments["query"],
                    k=8
                )))

            # 等待所有任务完成
            for source, task in tasks:
                try:
                    results[source] = await asyncio.wait_for(task, timeout=30)
                except asyncio.TimeoutError:
                    print(f"⚠️ {source} 搜索超时")
                    results[source] = []
                except Exception as e:
                    print(f"⚠️ {source} 搜索失败: {e}")
                    results[source] = []

            return [TextContent(
                type="text",
                text=_format_combined_results(results)
            )]

        else:
            return [TextContent(
                type="text",
                text=f"未知工具: {name}"
            )]

    except Exception as e:
        return [TextContent(
            type="text",
            text=f"搜索失败: {str(e)}"
        )]


# ========== 格式化函数（新代码，不影响现有逻辑） ==========

def _format_web_results(results: list) -> str:
    """格式化网络搜索结果"""
    if not results:
        return "【网络搜索】未找到相关内容"

    lines = ["【网络搜索结果】"]
    for i, item in enumerate(results[:10], 1):  # 限制10条
        title = item.get("title", "未命名")
        snippet = item.get("snippet", "")
        url = item.get("url", "")
        published = item.get("publishedAt", "未知时间")
        source = item.get("source", "")

        lines.append(f"\n{i}. {title}")
        lines.append(f"   时间：{published} | 来源：{source}")
        if snippet:
            lines.append(f"   摘要：{snippet[:200]}...")  # 限制摘要长度
        if url:
            lines.append(f"   链接：{url}")

    return "\n".join(lines)


def _format_db_results(results: list) -> str:
    """格式化数据库搜索结果"""
    if not results:
        return "【本地知识库】未找到相关内容"

    lines = ["【本地知识库】"]
    for i, item in enumerate(results[:10], 1):  # 限制10条
        title = item.get("title", "未命名")
        summary = item.get("summary", "")
        sim = item.get("similarity", 0)
        url = item.get("url", "")

        lines.append(f"\n{i}. {title} (相似度: {sim:.3f})")
        if summary:
            lines.append(f"   摘要：{summary[:300]}...")  # 限制摘要长度
        if url:
            lines.append(f"   链接：{url}")

    return "\n".join(lines)


def _format_combined_results(results: dict) -> str:
    """格式化综合搜索结果"""
    lines = []

    # 本地知识库优先
    if results.get("database"):
        lines.append(_format_db_results(results["database"]))
        lines.append("\n" + "=" * 60 + "\n")

    # 网络搜索
    if results.get("web"):
        lines.append(_format_web_results(results["web"]))

    return "\n".join(lines)


# ========== 启动MCP服务器 ==========

if __name__ == "__main__":
    # 启动MCP服务器（用于测试）
    import mcp.server.stdio
    mcp.server.stdio.run(app)
