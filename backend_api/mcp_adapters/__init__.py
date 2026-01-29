# -*- coding: utf-8 -*-
"""
MCP适配器模块
----------
包装现有功能为MCP服务器，实现增量更新
"""

from .search_mcp import app as search_mcp_app

__all__ = ["search_mcp_app"]
