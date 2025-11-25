# 智能体实现逻辑说明文档

## 一、整体架构

智能体模块采用**前后端分离**架构，实现了完整的聊天功能，包括流式传输和聊天记录管理。

```
┌─────────────────┐         ┌──────────────────┐         ┌──────────────┐
│   前端 Vue.js    │  HTTP   │   Flask 后端      │  HTTP   │  Qwen API    │
│  AgentModule    │ ◄─────► │  agent_chat_bp   │ ◄─────► │  (阿里云)    │
└─────────────────┘         └──────────────────┘         └──────────────┘
         │                           │
         │                           │
         │                           ▼
         │                  ┌──────────────┐
         │                  │   Supabase    │
         │                  │   (数据库)    │
         │                  └──────────────┘
         │
         ▼
    ┌─────────┐
    │ 用户界面 │
    └─────────┘
```

## 二、核心组件

### 2.1 前端组件

#### AgentModule.vue
- **位置**: `vue-admin-zhizhen/src/views/databoard/AgentModule.vue`
- **功能**: 
  - 聊天界面渲染
  - 用户输入处理
  - 流式数据接收和实时显示
  - 消息历史管理
  - Markdown渲染

**关键数据**:
```javascript
{
  inputMessage: '',           // 用户输入的消息
  sending: false,             // 是否正在发送
  sessionId: null,            // 当前会话ID
  conversationHistory: [],    // 对话历史（用于上下文）
  messages: [],               // 显示的消息列表
  streamController: null,     // 流式传输控制器
  systemPrompt: '...',        // 基础系统提示词
  globalSystemPrompts: [],    // 全局系统提示词
}
```

#### chat.js (API封装)
- **位置**: `vue-admin-zhizhen/src/api/agent/chat.js`
- **功能**: 封装后端API调用
- **主要函数**:
  - `chatWithAgent()` - 普通聊天（非流式）
  - `chatWithAgentStream()` - 流式聊天（SSE）
  - `getChatHistory()` - 获取聊天记录
  - `getChatSessions()` - 获取会话列表
  - `deleteChatSession()` - 删除会话

### 2.2 后端组件

#### agent_chat_bp.py
- **位置**: `backend/backend_api/agent_chat_bp.py`
- **功能**: 提供聊天API服务
- **主要接口**:
  - `POST /api/agent/chat` - 普通聊天
  - `POST /api/agent/chat/stream` - 流式聊天
  - `GET /api/agent/chat/history` - 获取历史记录
  - `GET /api/agent/chat/sessions` - 获取会话列表
  - `DELETE /api/agent/chat/sessions/<id>` - 删除会话

**核心函数**:
```python
_call_qwen_api()              # 调用Qwen API
_save_message()               # 保存消息到数据库
_create_or_update_session()   # 创建或更新会话
_get_chat_history()            # 获取聊天历史
```

### 2.3 数据库结构

#### chat_sessions 表
存储聊天会话信息：
- `id` (UUID) - 会话唯一标识
- `title` (TEXT) - 会话标题
- `created_at` (TIMESTAMPTZ) - 创建时间
- `updated_at` (TIMESTAMPTZ) - 更新时间

#### chat_messages 表
存储聊天消息：
- `id` (UUID) - 消息唯一标识
- `session_id` (UUID) - 所属会话ID（外键）
- `role` (TEXT) - 消息角色：user/assistant/system
- `content` (TEXT) - 消息内容
- `created_at` (TIMESTAMPTZ) - 创建时间

## 三、数据流程

### 3.1 流式聊天完整流程

```
1. 用户输入消息
   ↓
2. 前端 AgentModule.vue
   - 添加用户消息到 messages 数组
   - 添加到 conversationHistory
   - 创建加载中的AI消息占位符
   ↓
3. 调用 chatWithAgentStream()
   - 构建请求参数
   - 使用 fetch API 发送 POST 请求到 /api/agent/chat/stream
   ↓
4. 后端 agent_chat_bp.py
   - 接收请求，解析参数
   - 创建/更新会话（确保会话存在）
   - 保存用户消息到数据库
   - 构建消息列表（system + history + user）
   ↓
5. 调用 Qwen API
   - 发送流式请求
   - 接收流式响应
   ↓
6. 后端流式处理
   - 解析SSE格式的响应
   - 提取每个chunk的内容
   - 通过SSE发送给前端
   ↓
7. 前端接收流式数据
   - 使用 ReadableStream 读取
   - 解析 SSE 格式（data: {...}\n\n）
   - 实时更新AI消息内容
   ↓
8. 流式传输完成
   - 后端保存完整AI回复到数据库
   - 更新会话的 updated_at
   - 发送 done 事件
   ↓
9. 前端处理完成
   - 更新 conversationHistory
   - 清理临时状态
   - 滚动到底部
```

### 3.2 消息构建逻辑

后端在调用Qwen API前，会构建完整的消息列表：

```python
messages = []

# 1. 添加系统提示词
if system_prompt:
    messages.append({
        "role": "system",
        "content": system_prompt  # 基础提示词 + 全局提示词 + 临时提示词
    })

# 2. 添加历史对话
messages.extend(conversation_history)  # 格式: [{"role": "user", "content": "..."}, ...]

# 3. 添加当前用户消息
messages.append({
    "role": "user",
    "content": user_message
})
```

**系统提示词组合逻辑**（前端）:
```javascript
buildCombinedSystemPrompt() {
  const globals = this.globalSystemPrompts || []
  const extras = this.temporarySystemPrompts || []
  return [
    this.systemPrompt,  // 基础提示词
    ...globals,         // 全局提示词（持久生效）
    ...extras           // 临时提示词（一次性）
  ].join('\n\n')
}
```

## 四、关键技术实现

### 4.1 流式传输（SSE）

#### 后端实现
```python
@agent_chat_bp.route("/chat/stream", methods=["POST"])
def chat_stream():
    def generate():
        # 发送开始事件
        yield f"data: {json.dumps({'type': 'start'})}\n\n"
        
        # 处理Qwen API的流式响应
        for line in response.iter_lines():
            # 解析每个chunk
            chunk_data = json.loads(line_str)
            content = chunk_data["choices"][0]["delta"]["content"]
            
            # 发送数据块
            yield f"data: {json.dumps({'type': 'chunk', 'content': content})}\n\n"
        
        # 发送完成事件
        yield f"data: {json.dumps({'type': 'done'})}\n\n"
    
    return stream_with_context(generate())
```

#### 前端实现
```javascript
// 使用 fetch API 的 ReadableStream
const reader = response.body.getReader()
const decoder = new TextDecoder()
let buffer = ''

function readStream() {
  reader.read().then(({ done, value }) => {
    if (done) return
    
    // 解码数据
    buffer += decoder.decode(value, { stream: true })
    
    // 按 SSE 格式解析（data: {...}\n\n）
    const lines = buffer.split('\n\n')
    buffer = lines.pop() || ''
    
    for (const line of lines) {
      if (line.startsWith('data: ')) {
        const data = JSON.parse(line.slice(6))
        if (data.type === 'chunk') {
          onChunk(data.content)  // 实时更新UI
        }
      }
    }
    
    readStream()  // 继续读取
  })
}
```

### 4.2 聊天记录持久化

#### 保存消息流程
```python
# 1. 确保会话存在
_create_or_update_session(session_id)

# 2. 保存用户消息
_save_message(session_id, "user", user_message)

# 3. 调用API获取回复后
_save_message(session_id, "assistant", ai_content)

# 4. 更新会话时间
_create_or_update_session(session_id)  # 更新 updated_at
```

#### 会话创建/更新逻辑
```python
def _create_or_update_session(session_id: str, title: Optional[str] = None):
    # 1. 先查询会话是否存在
    existing = _supabase.table(CHAT_SESSIONS_TABLE).select("id").eq("id", session_id).execute()
    
    if existing.data:
        # 2. 存在则更新
        _supabase.table(CHAT_SESSIONS_TABLE).update({...}).eq("id", session_id).execute()
    else:
        # 3. 不存在则插入
        _supabase.table(CHAT_SESSIONS_TABLE).insert({...}).execute()
```

### 4.3 历史记录管理

#### 前端历史记录限制
```javascript
// 限制历史记录长度，避免超出token限制
if (this.conversationHistory.length > 20) {
  this.conversationHistory = this.conversationHistory.slice(-20)
}
```

#### 后端历史记录查询
```python
def _get_chat_history(session_id: str, limit: int = 50):
    result = (
        _supabase.table(CHAT_MESSAGES_TABLE)
        .select("*")
        .eq("session_id", session_id)
        .order("created_at", desc=False)  # 按时间正序
        .limit(limit)
        .execute()
    )
    return result.data or []
```

## 五、关键特性

### 5.1 前后端分离
- ✅ API密钥安全：Qwen API密钥存储在后端环境变量中
- ✅ 统一接口：前端通过HTTP请求调用后端API
- ✅ 错误处理：统一的错误处理和响应格式

### 5.2 流式传输
- ✅ 实时响应：AI回复实时显示，提升用户体验
- ✅ 打字机效果：逐字显示，类似ChatGPT
- ✅ 可取消：支持取消正在进行的流式传输

### 5.3 聊天记录
- ✅ 自动保存：所有消息自动保存到数据库
- ✅ 会话管理：支持多个会话，每个会话独立管理
- ✅ 历史查询：支持查询和加载历史聊天记录

### 5.4 系统提示词管理
- ✅ 基础提示词：默认的系统角色设定
- ✅ 全局提示词：持久生效的上下文信息
- ✅ 临时提示词：一次性提示词，用后即清

## 六、错误处理

### 6.1 前端错误处理
```javascript
{
  onError: (error) => {
    // 显示错误消息
    this.messages[loadingIndex] = {
      type: 'ai',
      content: errorMsg,
      error: true
    }
    this.$message.error('发送消息失败')
  }
}
```

### 6.2 后端错误处理
```python
try:
    # API调用
    response = _call_qwen_api(...)
except requests.exceptions.RequestException as e:
    # 处理API错误
    error_msg = f"API调用失败: {str(e)}"
    return jsonify({"code": 500, "message": error_msg}), 500
except Exception as e:
    # 处理其他错误
    return jsonify({"code": 500, "message": f"服务器错误: {str(e)}"}), 500
```

## 七、配置说明

### 7.1 环境变量（后端）

```bash
# Qwen API配置
QWEN_API_KEY=sk-xxx
QWEN_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
QWEN_MODEL=qwen-turbo

# Supabase配置
SUPABASE_URL=https://xxx.supabase.co
SUPABASE_SERVICE_KEY=xxx

# 数据库表名（可选）
CHAT_SESSIONS_TABLE=chat_sessions
CHAT_MESSAGES_TABLE=chat_messages
```

### 7.2 前端配置

```javascript
// request.js 中的 baseURL
baseURL: 'http://127.0.0.1:8000/'
```

## 八、使用示例

### 8.1 发送消息（流式）

```javascript
// 在 AgentModule.vue 中
async handleSendMessage() {
  const userContent = this.inputMessage.trim()
  
  // 添加用户消息到UI
  this.messages.push({
    type: 'user',
    content: userContent,
    time: this.getCurrentTime()
  })
  
  // 调用流式API
  this.streamController = chatWithAgentStream(
    {
      message: userContent,
      session_id: this.sessionId,
      system_prompt: this.buildCombinedSystemPrompt(),
      conversation_history: this.conversationHistory,
      options: { temperature: 0.8, top_p: 0.8 }
    },
    {
      onChunk: (chunk) => {
        // 实时更新AI消息
        aiContent += chunk
        this.messages[loadingIndex].content = aiContent
      },
      onDone: (data) => {
        // 流完成，保存到历史
        this.conversationHistory.push({
          role: 'assistant',
          content: aiContent
        })
      },
      onError: (error) => {
        // 处理错误
        console.error(error)
      }
    }
  )
}
```

### 8.2 加载历史记录

```javascript
async loadChatHistory() {
  if (!this.sessionId) return
  
  const response = await getChatHistory(this.sessionId)
  if (response.code === 200) {
    // 转换格式并显示
    this.messages = response.data.messages.map(msg => ({
      type: msg.role === 'user' ? 'user' : 'ai',
      content: msg.content,
      time: msg.time
    }))
  }
}
```

## 九、注意事项

1. **数据库表**: 必须在Supabase中执行 `chat_tables.sql` 创建表结构
2. **会话创建**: 保存消息前必须先创建会话，避免外键约束错误
3. **历史记录限制**: 建议限制在20条以内，避免超出token限制
4. **流式传输**: 前端需要正确处理SSE格式，注意数据缓冲
5. **错误处理**: 网络错误、API错误都需要妥善处理
6. **CORS配置**: 后端需要正确配置CORS，允许前端跨域请求

## 十、系统提示词管理详解

### 10.1 提示词类型

系统提示词分为三种类型，按优先级和生命周期管理：

#### 1. 基础提示词（systemPrompt）
- **位置**: `AgentModule.vue` 的 `data.systemPrompt`
- **默认值**: "你是致真智能体，一个友好、专业的AI助手..."
- **特点**: 
  - 每次对话都会包含
  - 定义AI的基本角色和性格
  - 可修改但通常保持不变

#### 2. 全局提示词（globalSystemPrompts）
- **位置**: `AgentModule.vue` 的 `data.globalSystemPrompts`
- **特点**:
  - 持久生效，每次对话都包含
  - 可以动态添加、删除、替换
  - 用于提供上下文信息（如业务数据、政策信息等）
- **管理方法**:
  ```javascript
  setGlobalSystemPrompt(prompts)      // 追加全局提示词
  replaceGlobalSystemPrompts(prompts)  // 替换全局提示词
  clearGlobalSystemPrompts()           // 清空全局提示词
  ```

#### 3. 临时提示词（temporarySystemPrompts）
- **位置**: `AgentModule.vue` 的 `data.temporarySystemPrompts`
- **特点**:
  - 仅对下一次对话生效
  - 使用后自动清空
  - 用于一次性指令或特殊要求
- **管理方法**:
  ```javascript
  setTemporarySystemPrompt(prompts)    // 设置临时提示词
  clearTemporarySystemPrompts()        // 手动清空（通常自动清空）
  ```

### 10.2 提示词组合逻辑

```javascript
buildCombinedSystemPrompt() {
  const globals = (this.globalSystemPrompts || [])
    .map(p => (p || '').trim())
    .filter(p => p.length > 0)
  const extras = (this.temporarySystemPrompts || [])
    .map(p => (p || '').trim())
    .filter(p => p.length > 0)
  
  // 组合顺序：基础 + 全局 + 临时
  return [
    this.systemPrompt,  // 基础角色定义
    ...globals,         // 持久上下文
    ...extras           // 一次性指令
  ].join('\n\n')
}
```

### 10.3 使用场景示例

#### 场景1: 添加业务上下文
```javascript
// 在组件初始化时，添加业务相关的全局提示词
this.setGlobalSystemPrompt([
  '以下是最近的采购信息：...',
  '公司产品信息：...'
])
```

#### 场景2: 一次性特殊指令
```javascript
// 在发送特定消息前，设置临时提示词
this.setTemporarySystemPrompt('请用表格格式回答')
// 发送消息后，临时提示词自动清空
```

#### 场景3: 动态更新上下文
```javascript
// 根据用户操作，动态更新全局提示词
this.replaceGlobalSystemPrompts([
  '当前查看的是2025年11月的数据',
  '重点关注：政策解读、市场动态'
])
```

## 十一、扩展建议

1. **会话标题**: 根据第一条消息自动生成会话标题
2. **消息分页**: 实现聊天记录的分页加载
3. **搜索功能**: 支持在聊天记录中搜索关键词
4. **导出功能**: 支持导出聊天记录为文本或PDF
5. **多用户支持**: 添加用户ID关联，支持多用户聊天记录隔离
6. **消息编辑**: 支持编辑和删除已发送的消息
7. **文件上传**: 支持上传图片、文档等文件进行AI分析
8. **提示词模板**: 提供常用提示词模板，方便快速使用
9. **提示词历史**: 记录提示词变更历史，支持回滚
10. **提示词优化**: 根据对话效果自动优化提示词

