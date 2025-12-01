# DeepAnalyze 集成完成 ✅

## 已完成的工作

1. ✅ 创建了 DeepAnalyze 适配层 (`backend_api/deepanalyze_adapter.py`)
2. ✅ 修改了后端聊天接口 (`backend_api/agent_chat_bp.py`)
3. ✅ 增强了任务检测逻辑，支持数据分析任务识别
4. ✅ 支持流式和非流式响应（DeepAnalyze 原生支持流式）

## 快速开始

### 1. 安装依赖

确保已安装 `openai` 包：

```bash
pip install openai
```

### 2. 配置环境变量

在后端 `.env` 文件中添加：

```bash
# DeepAnalyze 配置
USE_DEEPANALYZE=true
DEEPANALYZE_BASE_URL=http://localhost:8200
DEEPANALYZE_TIMEOUT=300  # 可选，默认 300 秒

# GPT-Researcher 配置（保持不变）
USE_GPT_RESEARCHER=true
AUTO_ROUTE_TASKS=true
GPT_RESEARCHER_BASE_URL=http://localhost:8000

# Qwen 配置（保持不变）
QWEN_API_KEY=sk-xxxxxxxxxxxxx
QWEN_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
QWEN_MODEL=qwen-turbo
```

### 3. 启动服务

```bash
# 终端1: 启动 DeepAnalyze API 服务
cd /Users/chz/code/zz3.0/DeepAnalyze/API
python start_server.py
# 或使用 uvicorn
# uvicorn main:app --host 0.0.0.0 --port 8200

# 终端2: 启动后端
cd /Users/chz/code/zz3.0/backend
python app.py
```

### 4. 测试

```bash
# 测试数据分析任务（自动使用 DeepAnalyze）
curl -X POST http://localhost:5000/api/agent/chat/stream \
  -H "Content-Type: application/json" \
  -d '{
    "message": "帮我分析一下这个数据表格",
    "session_id": "test-data-123",
    "task_type": "data"
  }'
```

## 功能说明

- **自动路由**：根据消息内容自动选择服务
  - 包含"研究"、"报告"等关键词 → GPT-Researcher
  - 包含"数据"、"表格"、"分析"等关键词 → DeepAnalyze
  - 其他消息 → Qwen（默认）

- **手动指定**：前端可以通过 `task_type` 参数手动指定服务
  - `task_type: 'research'` → GPT-Researcher
  - `task_type: 'data'` → DeepAnalyze
  - `task_type: 'chat'` → Qwen
  - `task_type: 'auto'` → 自动路由

- **统一接口**：前端无需修改，后端自动处理

- **流式支持**：DeepAnalyze 原生支持 OpenAI 兼容的流式响应

## 架构说明

```
前端请求 → 后端(Flask) → 任务路由
                          ├─ research → GPT-Researcher (port 8000)
                          ├─ data → DeepAnalyze (port 8200)
                          └─ chat → Qwen API
```

DeepAnalyze 适配器使用 OpenAI SDK 调用 DeepAnalyze API（因为 DeepAnalyze 是 OpenAI 兼容的），实现真正的流式传输。

