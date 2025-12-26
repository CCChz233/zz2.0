# 智能体聊天 API 文档

## 概述

智能体聊天 API 提供了前后端分离的聊天功能，支持：
- 普通聊天（非流式）
- 流式聊天（SSE）
- 聊天记录管理
- 会话管理

## 基础URL

```
/api/agent
```

## 接口列表

### 1. 普通聊天接口

**接口地址**: `POST /api/agent/chat`

**功能**: 发送消息并获取AI回复（非流式）

**请求参数**:

```json
{
  "message": "用户消息内容",
  "session_id": "会话ID（可选，不传则创建新会话）",
  "system_prompt": "系统提示词（可选）",
  "conversation_history": [
    {"role": "user", "content": "历史消息1"},
    {"role": "assistant", "content": "历史回复1"}
  ],
  "use_rag": true,
  "use_web_search": true,
  "options": {
    "temperature": 0.8,
    "top_p": 0.8,
    "max_tokens": 2000
  }
}
```

**响应示例**:

```json
{
  "code": 200,
  "message": "success",
  "data": {
    "session_id": "uuid-string",
    "content": "AI回复内容",
    "evidence": [
      {
        "title": "证据标题",
        "url": "https://example.com",
        "published_at": "2025-01-01",
        "origin": "web",
        "source": "example.com"
      }
    ],
    "sources": {
      "database": [
        {
          "title": "本地知识库来源",
          "url": "",
          "publishedAt": "2025-01-01",
          "origin": "rag"
        }
      ],
      "internet": [
        {
          "title": "网络来源",
          "url": "https://example.com",
          "publishedAt": "2025-01-01",
          "origin": "web"
        }
      ]
    },
    "conversation_history": [
      {"role": "user", "content": "用户消息"},
      {"role": "assistant", "content": "AI回复"}
    ]
  }
}
```

### 2. 流式聊天接口

**接口地址**: `POST /api/agent/chat/stream`

**功能**: 发送消息并获取AI流式回复（SSE）

**请求参数**: 同普通聊天接口

**响应格式**: Server-Sent Events (SSE)

**事件类型**:

1. `start` - 流开始
```json
{"type": "start", "session_id": "uuid-string"}
```

2. `evidence` - 检索证据
```json
{"type": "evidence", "items": [{"title": "证据标题", "url": "https://example.com", "origin": "web"}]}
```

3. `chunk` - 数据块
```json
{"type": "chunk", "content": "部分内容"}
```

4. `done` - 流完成
```json
{"type": "done", "session_id": "uuid-string"}
```

5. `error` - 错误
```json
{"type": "error", "message": "错误信息"}
```

**前端使用示例**:

```javascript
import { chatWithAgentStream } from '@/api/agent/chat'

chatWithAgentStream(
  {
    message: "你好",
    session_id: "existing-session-id",
    system_prompt: "你是AI助手",
    conversation_history: [],
    options: { temperature: 0.8 }
  },
  {
    onChunk: (chunk) => {
      console.log('收到数据块:', chunk)
      // 实时更新UI
    },
    onDone: (data) => {
      console.log('流完成:', data)
    },
    onError: (error) => {
      console.error('错误:', error)
    }
  }
)
```

### 3. 获取聊天记录

**接口地址**: `GET /api/agent/chat/history`

**功能**: 获取指定会话的聊天历史记录

**请求参数**:

- `session_id` (必填): 会话ID
- `limit` (可选): 限制数量，默认50

**响应示例**:

```json
{
  "code": 200,
  "message": "success",
  "data": {
    "session_id": "uuid-string",
    "messages": [
      {
        "role": "user",
        "content": "用户消息",
        "time": "2024-01-01T10:00:00Z"
      },
      {
        "role": "assistant",
        "content": "AI回复",
        "time": "2024-01-01T10:00:01Z"
      }
    ]
  }
}
```

### 4. 获取所有会话列表

**接口地址**: `GET /api/agent/chat/sessions`

**功能**: 获取所有聊天会话列表

**请求参数**:

- `limit` (可选): 限制数量，默认20

**响应示例**:

```json
{
  "code": 200,
  "message": "success",
  "data": {
    "sessions": [
      {
        "id": "uuid-string",
        "title": "会话标题",
        "created_at": "2024-01-01T10:00:00Z",
        "updated_at": "2024-01-01T10:30:00Z"
      }
    ]
  }
}
```

### 5. 删除聊天会话

**接口地址**: `DELETE /api/agent/chat/sessions/<session_id>`

**功能**: 删除指定会话及其所有消息

**响应示例**:

```json
{
  "code": 200,
  "message": "success",
  "data": null
}
```

## 环境变量配置

需要在后端配置以下环境变量：

```bash
# Qwen API配置
QWEN_API_KEY=your-api-key
QWEN_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
QWEN_MODEL=qwen-turbo

# Supabase配置
SUPABASE_URL=your-supabase-url
SUPABASE_SERVICE_KEY=your-service-key

# Web搜索（Tavily）
TAVILY_API_KEY=your-tavily-key
USE_WEB_SEARCH=true
WEB_SEARCH_TOPK=6
WEB_SEARCH_CACHE_MINUTES=30
WEB_SEARCH_MIN_SCORE=0

# 数据库表名（可选，有默认值）
CHAT_SESSIONS_TABLE=chat_sessions
CHAT_MESSAGES_TABLE=chat_messages
```

## 数据库设置

需要在Supabase中执行 `chat_tables.sql` 脚本来创建必要的表结构。

## 错误码说明

- `200`: 成功
- `400`: 请求参数错误
- `500`: 服务器内部错误

## 注意事项

1. 流式传输使用SSE（Server-Sent Events），前端需要使用EventSource或fetch API处理
2. 聊天记录会自动保存到数据库
3. 会话ID如果不提供，会自动生成新的UUID
4. 对话历史建议限制在20条以内，避免超出token限制
