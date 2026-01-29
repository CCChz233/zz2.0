#!/bin/bash
# 智能体系统测试脚本
# 使用方法: ./test_mcp.sh [mode]
# mode: all | chat | mcp | manager

MODE=${1:-all}
BASE_URL="http://localhost:5001"

echo "================================"
echo "🧪 智能体系统测试"
echo "模式: $MODE"
echo "================================"
echo ""

# 颜色定义
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# 测试计数器
TOTAL_TESTS=0
PASSED_TESTS=0
FAILED_TESTS=0

# 测试函数
test_case() {
  local name="$1"
  local command="$2"

  TOTAL_TESTS=$((TOTAL_TESTS + 1))
  echo "测试 $TOTAL_TESTS: $name"

  if eval "$command"; then
    echo -e "${GREEN}✅ 通过${NC}"
    PASSED_TESTS=$((PASSED_TESTS + 1))
  else
    echo -e "${RED}❌ 失败${NC}"
    FAILED_TESTS=$((FAILED_TESTS + 1))
  fi
  echo ""
}

# 检查服务是否运行
check_server() {
  curl -s "$BASE_URL/api/mcp/health" > /dev/null 2>&1
  return $?
}

# 如果服务未运行，提示用户
if ! check_server; then
  echo -e "${YELLOW}⚠️  后端服务未运行${NC}"
  echo "请先启动服务: ./start.sh"
  echo ""
  echo "测试模式："
  echo "  ./test_mcp.sh all     - 运行所有测试"
  echo "  ./test_mcp.sh chat    - 测试聊天功能"
  echo "  ./test_mcp.sh mcp     - 测试MCP功能"
  echo "  ./test_mcp.sh manager - 测试MCP管理器"
  exit 1
fi

# ========== 测试用例 ==========

# 1. 聊天功能测试
test_chat() {
  echo "========== 聊天功能测试 =========="
  echo ""

  test_case "标准聊天（不使用MCP）" \
    "curl -s -X POST $BASE_URL/api/agent/chat \
      -H 'Content-Type: application/json' \
      -d '{\"message\": \"你好\"}' \
      | grep -q '\"code\": 200'"

  test_case "启用MCP搜索的聊天" \
    "curl -s -X POST $BASE_URL/api/agent/chat \
      -H 'Content-Type: application/json' \
      -d '{\"message\": \"测试\", \"use_mcp_search\": true}' \
      | grep -q '\"code\": 200'"
}

# 2. MCP功能测试
test_mcp() {
  echo "========== MCP功能测试 =========="
  echo ""

  test_case "MCP健康检查" \
    "curl -s $BASE_URL/api/mcp/health | grep -q 'mcp_available'"

  test_case "获取MCP服务器列表" \
    "curl -s $BASE_URL/api/mcp/servers | grep -q '\"code\": 200'"

  test_case "获取MCP工具列表" \
    "curl -s $BASE_URL/api/mcp/tools | grep -q '\"code\": 200'"

  test_case "获取MCP模板列表" \
    "curl -s $BASE_URL/api/mcp/templates | grep -q '\"code\": 200'"
}

# 3. MCP管理器测试
test_manager() {
  echo "========== MCP管理器测试 =========="
  echo ""

  test_case "添加测试MCP服务器" \
    "curl -s -X POST $BASE_URL/api/mcp/servers \
      -H 'Content-Type: application/json' \
      -d '{
        \"id\": \"test-server\",
        \"name\": \"测试服务器\",
        \"server_type\": \"test\",
        \"command\": \"echo\",
        \"args\": [\"hello\"]
      }' | grep -q '\"code\": 200'"

  test_case "获取测试服务器状态" \
    "curl -s $BASE_URL/api/mcp/servers/test-server/status | grep -q '\"code\": 200'"

  test_case "删除测试MCP服务器" \
    "curl -s -X DELETE $BASE_URL/api/mcp/servers/test-server | grep -q '\"code\": 200'"
}

# ========== 主流程 ==========

case $MODE in
  "chat")
    test_chat
    ;;
  "mcp")
    test_mcp
    ;;
  "manager")
    test_manager
    ;;
  "all")
    test_chat
    test_mcp
    test_manager
    ;;
  *)
    echo -e "${RED}未知测试模式: $MODE${NC}"
    echo "可用模式: all, chat, mcp, manager"
    exit 1
    ;;
esac

# ========== 测试结果汇总 ==========

echo "================================"
echo "📊 测试结果汇总"
echo "================================"
echo "总测试数: $TOTAL_TESTS"
echo -e "${GREEN}通过: $PASSED_TESTS${NC}"
echo -e "${RED}失败: $FAILED_TESTS${NC}"
echo ""

if [ $FAILED_TESTS -eq 0 ]; then
  echo -e "${GREEN}🎉 所有测试通过！${NC}"
  exit 0
else
  echo -e "${RED}⚠️  有 $FAILED_TESTS 个测试失败${NC}"
  exit 1
fi
