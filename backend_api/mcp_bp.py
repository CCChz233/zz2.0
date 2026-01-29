# -*- coding: utf-8 -*-
"""
MCP管理API Blueprint
-------------------
提供HTTP接口管理MCP服务器
"""

import os
import asyncio
from flask import Blueprint, request, jsonify
from backend_api.mcp_manager import mcp_manager, MCP_AVAILABLE

mcp_bp = Blueprint("mcp", __name__)


@mcp_bp.route("/health", methods=["GET"])
def health_check():
    """健康检查"""
    return jsonify({
        "code": 200,
        "message": "MCP管理器运行正常",
        "data": {
            "mcp_available": MCP_AVAILABLE,
            "servers_count": len(mcp_manager.servers)
        }
    })


@mcp_bp.route("/servers", methods=["GET"])
def list_servers():
    """列出所有已配置的MCP服务器"""
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        servers = loop.run_until_complete(
            mcp_manager.list_servers()
        )

        return jsonify({
            "code": 200,
            "message": "success",
            "data": servers
        })

    except Exception as e:
        return jsonify({
            "code": 500,
            "message": f"获取服务器列表失败: {str(e)}",
            "data": []
        }), 500


@mcp_bp.route("/servers", methods=["POST"])
def add_server():
    """添加新的MCP服务器"""
    try:
        data = request.get_json()

        # 验证必需字段
        required_fields = ["id", "name", "server_type", "command", "args"]
        for field in required_fields:
            if field not in data:
                return jsonify({
                    "code": 400,
                    "message": f"缺少必需字段: {field}",
                    "data": None
                }), 400

        # 异步添加服务器
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        result = loop.run_until_complete(
            mcp_manager.add_server(
                server_id=data["id"],
                name=data["name"],
                server_type=data["server_type"],
                command=data["command"],
                args=data["args"],
                env=data.get("env", {})
            )
        )

        if result["success"]:
            return jsonify({
                "code": 200,
                "message": result["message"],
                "data": {
                    "server_id": result.get("server_id"),
                    "tools": result.get("tools", [])
                }
            })
        else:
            return jsonify({
                "code": 500,
                "message": result["message"],
                "data": None
            }), 500

    except Exception as e:
        return jsonify({
            "code": 500,
            "message": f"添加服务器失败: {str(e)}",
            "data": None
        }), 500


@mcp_bp.route("/servers/<server_id>", methods=["DELETE"])
def remove_server(server_id):
    """删除MCP服务器"""
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        result = loop.run_until_complete(
            mcp_manager.remove_server(server_id)
        )

        if result["success"]:
            return jsonify({
                "code": 200,
                "message": result["message"],
                "data": None
            })
        else:
            return jsonify({
                "code": 500,
                "message": result["message"],
                "data": None
            }), 500

    except Exception as e:
        return jsonify({
            "code": 500,
            "message": f"删除服务器失败: {str(e)}",
            "data": None
        }), 500


@mcp_bp.route("/servers/<server_id>/status", methods=["GET"])
def get_server_status(server_id):
    """获取MCP服务器状态"""
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        status = loop.run_until_complete(
            mcp_manager.get_server_status(server_id)
        )

        return jsonify({
            "code": 200,
            "message": "success",
            "data": status
        })

    except Exception as e:
        return jsonify({
            "code": 500,
            "message": f"获取服务器状态失败: {str(e)}",
            "data": None
        }), 500


@mcp_bp.route("/servers/<server_id>/tools", methods=["GET"])
def list_server_tools(server_id):
    """列出指定MCP服务器的工具"""
    try:
        tools = mcp_manager.tools_cache.get(server_id, [])

        return jsonify({
            "code": 200,
            "message": "success",
            "data": {
                "server_id": server_id,
                "tools": tools
            }
        })

    except Exception as e:
        return jsonify({
            "code": 500,
            "message": f"获取工具列表失败: {str(e)}",
            "data": None
        }), 500


@mcp_bp.route("/servers/<server_id>/tools/refresh", methods=["POST"])
def refresh_server_tools(server_id):
    """刷新MCP服务器的工具列表"""
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        result = loop.run_until_complete(
            mcp_manager.refresh_tools(server_id)
        )

        if result["success"]:
            return jsonify({
                "code": 200,
                "message": result["message"],
                "data": result.get("tools", [])
            })
        else:
            return jsonify({
                "code": 500,
                "message": result["message"],
                "data": None
            }), 500

    except Exception as e:
        return jsonify({
            "code": 500,
            "message": f"刷新工具列表失败: {str(e)}",
            "data": None
        }), 500


@mcp_bp.route("/tools", methods=["GET"])
def list_all_tools():
    """列出所有可用工具"""
    try:
        all_tools = mcp_manager.tools_cache

        return jsonify({
            "code": 200,
            "message": "success",
            "data": all_tools
        })

    except Exception as e:
        return jsonify({
            "code": 500,
            "message": f"获取工具列表失败: {str(e)}",
            "data": {}
        }), 500


@mcp_bp.route("/tools/<server_id>/<tool_name>", methods=["POST"])
def call_tool(server_id, tool_name):
    """调用MCP工具"""
    try:
        arguments = request.get_json() or {}

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        result = loop.run_until_complete(
            mcp_manager.call_tool(server_id, tool_name, arguments)
        )

        return jsonify({
            "code": 200,
            "message": "success",
            "data": {
                "server_id": server_id,
                "tool_name": tool_name,
                "result": result
            }
        })

    except Exception as e:
        return jsonify({
            "code": 500,
            "message": f"调用工具失败: {str(e)}",
            "data": None
        }), 500


@mcp_bp.route("/templates", methods=["GET"])
def list_templates():
    """列出可用的MCP服务器模板"""
    templates = {
        "github": {
            "id": "github-template",
            "name": "GitHub",
            "server_type": "github",
            "command": "npx",
            "args": ["-y", "@modelcontextprotocol/server-github"],
            "env_vars": ["GITHUB_PERSONAL_ACCESS_TOKEN"],
            "description": "访问GitHub仓库、Issues、PR",
            "icon": "el-icon-link"
        },
        "filesystem": {
            "id": "filesystem-template",
            "name": "本地文件",
            "server_type": "filesystem",
            "command": "npx",
            "args": ["-y", "@modelcontextprotocol/server-filesystem", "/path/to/files"],
            "env_vars": [],
            "description": "访问本地文件系统",
            "icon": "el-icon-folder"
        },
        "slack": {
            "id": "slack-template",
            "name": "Slack",
            "server_type": "slack",
            "command": "npx",
            "args": ["-y", "@modelcontextprotocol/server-slack"],
            "env_vars": ["SLACK_TOKEN"],
            "description": "访问Slack消息和频道",
            "icon": "el-icon-chat-dot-round"
        },
        "brave-search": {
            "id": "brave-search-template",
            "name": "Brave搜索",
            "server_type": "search",
            "command": "npx",
            "args": ["-y", "@modelcontextprotocol/server-brave-search"],
            "env_vars": ["BRAVE_API_KEY"],
            "description": "使用Brave搜索引擎",
            "icon": "el-icon-search"
        }
    }

    return jsonify({
        "code": 200,
        "message": "success",
        "data": [
            {
                "id": key,
                **template
            }
            for key, template in templates.items()
        ]
    })
