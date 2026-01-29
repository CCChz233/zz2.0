# -*- coding: utf-8 -*-
"""
MCP服务器管理器
--------------
功能：动态管理MCP服务器（添加、删除、列表、工具发现）
设计：单例模式，全局共享MCP服务器连接
"""

import os
import asyncio
import json
import subprocess
import threading
from typing import Dict, List, Any, Optional
from dataclasses import dataclass, asdict
from datetime import datetime

try:
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client
    MCP_AVAILABLE = True
except ImportError:
    MCP_AVAILABLE = False
    print("⚠️ mcp包未安装，MCP管理器将不可用")


@dataclass
class MCPServerConfig:
    """MCP服务器配置"""
    id: str
    name: str
    server_type: str  # 'github', 'filesystem', 'custom'
    command: str
    args: List[str]
    env: Dict[str, str]
    enabled: bool = True
    created_at: str = None
    updated_at: str = None

    def __post_init__(self):
        if self.created_at is None:
            self.created_at = datetime.utcnow().isoformat()
        self.updated_at = datetime.utcnow().isoformat()


class MCPServerManager:
    """MCP服务器管理器（单例模式）"""

    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if hasattr(self, '_initialized'):
            return

        self._initialized = True
        self.servers: Dict[str, ClientSession] = {}
        self.server_configs: Dict[str, MCPServerConfig] = {}
        self.tools_cache: Dict[str, List[Dict]] = {}
        self._processes: Dict[str, subprocess.Popen] = {}

        # 从环境变量或数据库加载配置
        self._load_configs()

        print(f"📋 [MCP管理器] 初始化完成，已加载 {len(self.server_configs)} 个服务器配置")

    def _load_configs(self):
        """加载MCP服务器配置（从数据库或环境变量）"""
        # TODO: 从Supabase加载
        # 目前先从环境变量加载预设配置

        preset_configs = os.getenv("MCP_PRESET_CONFIGS", "")
        if preset_configs:
            try:
                configs = json.loads(preset_configs)
                for config_dict in configs:
                    config = MCPServerConfig(**config_dict)
                    self.server_configs[config.id] = config
            except Exception as e:
                print(f"⚠️ 加载MCP预设配置失败: {e}")

    async def add_server(
        self,
        server_id: str,
        name: str,
        server_type: str,
        command: str,
        args: List[str],
        env: Dict[str, str] = None
    ) -> Dict[str, Any]:
        """
        添加并启动MCP服务器

        Returns:
            {
                "success": bool,
                "message": str,
                "tools": list
            }
        """

        if not MCP_AVAILABLE:
            return {
                "success": False,
                "message": "MCP包未安装，请先安装: pip install mcp"
            }

        try:
            # 保存配置
            config = MCPServerConfig(
                id=server_id,
                name=name,
                server_type=server_type,
                command=command,
                args=args,
                env=env or {}
            )
            self.server_configs[server_id] = config

            # 启动服务器
            result = await self._start_server(config)

            # TODO: 保存到Supabase
            # await self._save_config_to_db(config)

            return result

        except Exception as e:
            return {
                "success": False,
                "message": f"添加MCP服务器失败: {str(e)}"
            }

    async def _start_server(self, config: MCPServerConfig) -> Dict[str, Any]:
        """启动MCP服务器并获取工具列表"""

        try:
            # 创建服务器参数
            server_params = StdioServerParameters(
                command=config.command,
                args=config.args,
                env=config.env or {}
            )

            # 连接到服务器
            session = await stdio_client(server_params)

            # 保存session
            self.servers[config.id] = session

            # 列出可用工具
            tools = await session.list_tools()

            # 缓存工具
            self.tools_cache[config.id] = [
                {
                    "name": tool.name,
                    "description": tool.description,
                    "inputSchema": tool.inputSchema
                }
                for tool in tools
            ]

            print(f"✅ [MCP管理器] 服务器 '{config.name}' 启动成功，发现 {len(tools)} 个工具")

            return {
                "success": True,
                "message": f"服务器 '{config.name}' 添加成功",
                "server_id": config.id,
                "tools": self.tools_cache[config.id]
            }

        except Exception as e:
            print(f"❌ [MCP管理器] 启动服务器 '{config.name}' 失败: {e}")
            return {
                "success": False,
                "message": f"启动服务器失败: {str(e)}"
            }

    async def remove_server(self, server_id: str) -> Dict[str, Any]:
        """移除MCP服务器"""

        try:
            if server_id in self.servers:
                # 关闭session
                await self.servers[server_id].close()
                del self.servers[server_id]

            if server_id in self.tools_cache:
                del self.tools_cache[server_id]

            if server_id in self.server_configs:
                del self.server_configs[server_id]

            # TODO: 从数据库删除
            # await self._delete_config_from_db(server_id)

            print(f"✅ [MCP管理器] 服务器 '{server_id}' 已移除")

            return {
                "success": True,
                "message": "服务器移除成功"
            }

        except Exception as e:
            return {
                "success": False,
                "message": f"移除服务器失败: {str(e)}"
            }

    async def list_servers(self) -> List[Dict[str, Any]]:
        """列出所有已配置的MCP服务器"""

        servers = []
        for server_id, config in self.server_configs.items():
            server_info = {
                "id": config.id,
                "name": config.name,
                "server_type": config.server_type,
                "enabled": config.enabled,
                "is_running": server_id in self.servers,
                "tools_count": len(self.tools_cache.get(server_id, []))
            }
            servers.append(server_info)

        return servers

    async def list_all_tools(self) -> Dict[str, List[Dict]]:
        """列出所有MCP服务器的工具"""

        return self.tools_cache

    async def call_tool(
        self,
        server_id: str,
        tool_name: str,
        arguments: Dict[str, Any]
    ) -> Any:
        """调用指定MCP服务器的工具"""

        if server_id not in self.servers:
            raise ValueError(f"服务器 '{server_id}' 不存在或未运行")

        try:
            session = self.servers[server_id]
            result = await session.call_tool(tool_name, arguments)
            return result

        except Exception as e:
            print(f"❌ [MCP管理器] 调用工具 '{tool_name}' 失败: {e}")
            raise

    async def refresh_tools(self, server_id: str) -> Dict[str, Any]:
        """刷新MCP服务器的工具列表"""

        if server_id not in self.servers:
            return {
                "success": False,
                "message": "服务器不存在或未运行"
            }

        try:
            session = self.servers[server_id]
            tools = await session.list_tools()

            # 更新缓存
            self.tools_cache[server_id] = [
                {
                    "name": tool.name,
                    "description": tool.description,
                    "inputSchema": tool.inputSchema
                }
                for tool in tools
            ]

            return {
                "success": True,
                "message": "工具列表已刷新",
                "tools": self.tools_cache[server_id]
            }

        except Exception as e:
            return {
                "success": False,
                "message": f"刷新工具列表失败: {str(e)}"
            }

    async def get_server_status(self, server_id: str) -> Dict[str, Any]:
        """获取MCP服务器状态"""

        if server_id not in self.server_configs:
            return {
                "exists": False
            }

        config = self.server_configs[server_id]

        return {
            "exists": True,
            "name": config.name,
            "server_type": config.server_type,
            "enabled": config.enabled,
            "is_running": server_id in self.servers,
            "tools_count": len(self.tools_cache.get(server_id, [])),
            "created_at": config.created_at,
            "updated_at": config.updated_at
        }


# 全局单例
mcp_manager = MCPServerManager()
