#!/bin/bash
# 智能体后端启动脚本
# 使用方法: ./start.sh [mode]
# mode: normal（默认）| mcp-search | mcp-manager

MODE=${1:-normal}
PORT=${PORT:-5001}

echo "================================"
echo "🚀 启动智能体后端服务"
echo "模式: $MODE"
echo "端口: $PORT"
echo "================================"

# 根据模式设置环境变量
case $MODE in
  "mcp-search")
    echo "📌 启用MCP搜索功能"
    export USE_MCP_SEARCH=true
    export USE_MCP_MANAGER=false
    ;;
  "mcp-manager")
    echo "📌 启用MCP管理器"
    export USE_MCP_SEARCH=true
    export USE_MCP_MANAGER=true
    ;;
  "normal")
    echo "📌 标准模式（不启用MCP）"
    export USE_MCP_SEARCH=false
    export USE_MCP_MANAGER=false
    ;;
  *)
    echo "⚠️ 未知模式: $MODE，使用标准模式"
    MODE="normal"
    export USE_MCP_SEARCH=false
    export USE_MCP_MANAGER=false
    ;;
esac

echo ""
echo "环境变量："
echo "  USE_MCP_SEARCH=$USE_MCP_SEARCH"
echo "  USE_MCP_MANAGER=$USE_MCP_MANAGER"
echo ""
echo "================================"
echo ""

# 检查Python虚拟环境
if [ -d "venv" ]; then
  echo "🔧 激活虚拟环境"
  source venv/bin/activate
fi

# 启动Flask应用
echo "🚀 启动Flask服务..."
python app.py --port $PORT
