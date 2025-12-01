# GPT-Researcher 集成说明

## 概述

已成功将 GPT-Researcher 集成到后端系统中，支持智能任务路由和自动选择服务。

## 功能特性

1. **智能任务路由**：根据用户消息内容自动选择最合适的服务
   - 研究任务 → GPT-Researcher
   - 数据分析任务 → DeepAnalyze（未来支持）
   - 通用聊天 → Qwen（默认）

2. **统一接口**：前端无需修改，后端自动处理路由

3. **流式支持**：GPT-Researcher 支持模拟流式响应

## 配置

### 环境变量

在 `.env` 文件中添加以下配置：

```bash
# GPT-Researcher 配置
USE_GPT_RESEARCHER=true              # 是否启用 GPT-Researcher
AUTO_ROUTE_TASKS=true                # 是否自动路由任务
GPT_RESEARCHER_BASE_URL=http://localhost:8000  # GPT-Researcher 服务地址
GPT_RESEARCHER_TIMEOUT=300           # 请求超时时间（秒）

# Qwen 配置（保持不变）
QWEN_API_KEY=sk-xxxxxxxxxxxxx
QWEN_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
QWEN_MODEL=qwen-turbo
```

### 任务类型检测

系统会根据以下关键词自动识别任务类型：

**研究任务关键词**（使用 GPT-Researcher）：
- 中文：研究、报告、分析、调研、调查、研究一下
- 英文：research, report, analyze, investigate, study

**数据分析任务关键词**（未来支持 DeepAnalyze）：
- 中文：数据、表格、图表、可视化、csv、excel、数据分析
- 英文：data, table, chart, visualization, analyze data

## 使用方式

### 自动路由（推荐）

默认情况下，系统会自动检测任务类型并选择服务：

```bash
# 研究任务 - 自动使用 GPT-Researcher
curl -X POST http://localhost:5000/api/agent/chat \
  -H "Content-Type: application/json" \
  -d '{
    "message": "研究一下人工智能的最新发展",
    "session_id": "test-123"
  }'

# 通用聊天 - 自动使用 Qwen
curl -X POST http://localhost:5000/api/agent/chat \
  -H "Content-Type: application/json" \
  -d '{
    "message": "你好",
    "session_id": "test-123"
  }'
```

### 强制使用指定服务

如果需要强制使用某个服务，可以在代码中修改 `force_provider` 参数。

## 架构说明

### 文件结构

```
backend/
├── backend_api/
│   ├── agent_chat_bp.py          # 主聊天接口（已修改）
│   ├── gpt_researcher_adapter.py # GPT-Researcher 适配层（新建）
│   └── GPT_RESEARCHER_INTEGRATION.md  # 本文档
```

### 适配层说明

`gpt_researcher_adapter.py` 提供以下功能：

1. **GPTResearcherAdapter 类**：
   - `chat_completions()`: 非流式聊天
   - `chat_completions_stream()`: 流式聊天（模拟）

2. **任务类型检测**：
   - `detect_task_type()`: 根据消息内容检测任务类型

3. **格式转换**：
   - GPT-Researcher 格式 ↔ OpenAI 兼容格式

### 调用流程

```
前端请求
  ↓
agent_chat_bp.py (chat/chat_stream)
  ↓
_call_llm_api() [统一调用函数]
  ↓
检测任务类型 (detect_task_type)
  ↓
├─ 研究任务 → GPT-Researcher Adapter → GPT-Researcher API
└─ 其他任务 → Qwen API
  ↓
返回统一格式响应
```

## 测试

### 1. 测试 GPT-Researcher 服务

确保 GPT-Researcher 服务正在运行：

```bash
cd /Users/chz/code/zz3.0/gpt-researcher
python -m uvicorn main:app --reload --port 8000
```

### 2. 测试后端集成

```bash
# 测试研究任务（应该使用 GPT-Researcher）
curl -X POST http://localhost:5000/api/agent/chat \
  -H "Content-Type: application/json" \
  -d '{
    "message": "研究一下量子计算的最新进展",
    "session_id": "test-research"
  }'

# 测试通用聊天（应该使用 Qwen）
curl -X POST http://localhost:5000/api/agent/chat \
  -H "Content-Type: application/json" \
  -d '{
    "message": "你好，今天天气怎么样？",
    "session_id": "test-chat"
  }'
```

### 3. 测试流式接口

```bash
curl -X POST http://localhost:5000/api/agent/chat/stream \
  -H "Content-Type: application/json" \
  -d '{
    "message": "研究一下区块链技术",
    "session_id": "test-stream"
  }'
```

## 注意事项

1. **GPT-Researcher 流式响应**：
   - GPT-Researcher 当前不支持真正的流式响应
   - 适配层会先获取完整响应，然后模拟流式输出
   - 响应速度可能比真正的流式稍慢

2. **任务类型检测**：
   - 检测基于关键词匹配，可能不够精确
   - 可以通过修改 `detect_task_type()` 函数优化检测逻辑

3. **错误处理**：
   - 如果 GPT-Researcher 服务不可用，会自动回退到 Qwen
   - 建议在生产环境中添加更完善的错误处理和监控

4. **性能考虑**：
   - GPT-Researcher 的研究任务可能需要较长时间（几分钟）
   - 建议在前端添加进度提示和超时处理

## 未来扩展

1. **DeepAnalyze 集成**：添加数据分析任务的路由支持
2. **更智能的路由**：使用 LLM 进行任务类型判断
3. **缓存机制**：缓存研究结果，避免重复请求
4. **异步处理**：对于长时间研究任务，支持异步处理和结果通知

## 故障排查

### GPT-Researcher 服务连接失败

1. 检查服务是否运行：`curl http://localhost:8000/health`
2. 检查环境变量：`GPT_RESEARCHER_BASE_URL` 是否正确
3. 查看后端日志：检查错误信息

### 任务路由不正确

1. 检查 `AUTO_ROUTE_TASKS` 环境变量是否为 `true`
2. 检查 `detect_task_type()` 函数的关键词列表
3. 查看后端日志：会输出使用的服务类型

### 响应格式错误

1. 检查 GPT-Researcher 适配器的格式转换逻辑
2. 查看 GPT-Researcher API 的响应格式是否变化
3. 检查后端日志：查看原始响应和转换后的响应

