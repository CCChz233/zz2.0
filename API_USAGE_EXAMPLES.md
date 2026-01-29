# API 使用示例

## 1️⃣ 标准聊天（默认模式，不使用MCP）

```bash
curl -X POST http://localhost:5001/api/agent/chat/stream \
  -H "Content-Type: application/json" \
  -d '{
    "message": "今天天气怎么样？",
    "session_id": "test-session-001",
    "conversation_history": [],
    "use_rag": false,
    "use_web_search": false
  }'
```

---

## 2️⃣ 启用MCP搜索

### 方法1：通过前端参数（推荐）

```bash
curl -X POST http://localhost:5001/api/agent/chat/stream \
  -H "Content-Type: application/json" \
  -d '{
    "message": "最新的AI新闻有哪些？",
    "session_id": "test-session-002",
    "use_mcp_search": true,
    "use_rag": true,
    "use_web_search": true
  }'
```

### 方法2：通过环境变量（全局启用）

```bash
# 启动后端时设置
export USE_MCP_SEARCH=true
python app.py

# 然后所有请求都会使用MCP搜索
curl -X POST http://localhost:5001/api/agent/chat/stream \
  -H "Content-Type: application/json" \
  -d '{
    "message": "最新AI新闻"
  }'
```

---

## 3️⃣ 指定使用研究工具（GPT-Researcher）

```bash
curl -X POST http://localhost:5001/api/agent/chat/stream \
  -H "Content-Type: application/json" \
  -d '{
    "message": "研究一下量子计算的最新进展",
    "task_type": "research",
    "session_id": "research-session-001"
  }'
```

---

## 4️⃣ 指定使用数据分析（DeepAnalyze）

```bash
curl -X POST http://localhost:5001/api/agent/chat/stream \
  -H "Content-Type: application/json" \
  -d '{
    "message": "分析这个销售数据表格",
    "task_type": "data",
    "session_id": "data-session-001"
  }'
```

---

## 5️⃣ MCP管理API

### 5.1 列出所有MCP服务器

```bash
curl http://localhost:5001/api/mcp/servers
```

**响应示例**：
```json
{
  "code": 200,
  "message": "success",
  "data": [
    {
      "id": "github",
      "name": "GitHub",
      "server_type": "github",
      "enabled": true,
      "is_running": true,
      "tools_count": 5
    }
  ]
}
```

---

### 5.2 添加GitHub MCP服务器

```bash
curl -X POST http://localhost:5001/api/mcp/servers \
  -H "Content-Type: application/json" \
  -d '{
    "id": "github",
    "name": "GitHub",
    "server_type": "github",
    "command": "npx",
    "args": ["-y", "@modelcontextprotocol/server-github"],
    "env": {
      "GITHUB_PERSONAL_ACCESS_TOKEN": "ghp_your_token_here"
    }
  }'
```

**响应示例**：
```json
{
  "code": 200,
  "message": "服务器 'GitHub' 添加成功",
  "data": {
    "server_id": "github",
    "tools": [
      {
        "name": "search_repositories",
        "description": "搜索GitHub仓库",
        "inputSchema": {...}
      },
      {
        "name": "get_repository",
        "description": "获取仓库详情",
        "inputSchema": {...}
      }
    ]
  }
}
```

---

### 5.3 查看MCP服务器状态

```bash
curl http://localhost:5001/api/mcp/servers/github/status
```

**响应示例**：
```json
{
  "code": 200,
  "message": "success",
  "data": {
    "exists": true,
    "name": "GitHub",
    "server_type": "github",
    "enabled": true,
    "is_running": true,
    "tools_count": 5,
    "created_at": "2025-01-17T10:30:00",
    "updated_at": "2025-01-17T10:30:00"
  }
}
```

---

### 5.4 调用MCP工具

```bash
curl -X POST http://localhost:5001/api/mcp/tools/github/search_repositories \
  -H "Content-Type: application/json" \
  -d '{
    "query": "deepseek",
    "max_results": 10
  }'
```

---

### 5.5 删除MCP服务器

```bash
curl -X DELETE http://localhost:5001/api/mcp/servers/github
```

---

### 5.6 获取MCP预设模板

```bash
curl http://localhost:5001/api/mcp/templates
```

**响应示例**：
```json
{
  "code": 200,
  "message": "success",
  "data": [
    {
      "id": "github",
      "name": "GitHub",
      "server_type": "github",
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-github"],
      "env_vars": ["GITHUB_PERSONAL_ACCESS_TOKEN"],
      "description": "访问GitHub仓库、Issues、PR",
      "icon": "el-icon-link"
    },
    {
      "id": "filesystem",
      "name": "本地文件",
      "server_type": "filesystem",
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-filesystem", "/path/to/files"],
      "env_vars": [],
      "description": "访问本地文件系统",
      "icon": "el-icon-folder"
    }
  ]
}
```

---

## 6️⃣ 前端Vue组件示例

### 基础聊天组件（带MCP选项）

```vue
<template>
  <div class="chat-container">
    <!-- MCP选项开关 -->
    <el-switch
      v-model="useMcpSearch"
      active-text="启用MCP搜索"
      inactive-text="使用传统搜索">
    </el-switch>

    <!-- 消息列表 -->
    <div class="messages">
      <div
        v-for="(msg, index) in messages"
        :key="index"
        :class="['message', msg.role]">
        {{ msg.content }}
      </div>
    </div>

    <!-- 输入框 -->
    <el-input
      v-model="userMessage"
      placeholder="输入消息..."
      @keyup.enter.native="sendMessage">
      <el-button
        slot="append"
        icon="el-icon-s-promotion"
        @click="sendMessage">
        发送
      </el-button>
    </el-input>
  </div>
</template>

<script>
export default {
  data() {
    return {
      userMessage: '',
      useMcpSearch: false,  // MCP搜索开关
      messages: [],
      sessionId: ''
    }
  },
  mounted() {
    this.sessionId = this.generateSessionId()
  },
  methods: {
    async sendMessage() {
      if (!this.userMessage.trim()) return

      const userMsg = {
        role: 'user',
        content: this.userMessage
      }
      this.messages.push(userMsg)

      try {
        const response = await this.$http.post('/api/agent/chat/stream', {
          message: this.userMessage,
          session_id: this.sessionId,
          use_mcp_search: this.useMcpSearch,  // 🔥 关键：传递MCP选项
          use_rag: true,
          use_web_search: true,
          conversation_history: this.messages.slice(0, -1)
        })

        // 处理流式响应
        const reader = response.data.getReader()
        // ... 流式处理逻辑

      } catch (error) {
        console.error('发送消息失败:', error)
      }

      this.userMessage = ''
    },
    generateSessionId() {
      return 'session-' + Date.now() + '-' + Math.random().toString(36)
    }
  }
}
</script>
```

---

### MCP管理界面组件

```vue
<template>
  <div class="mcp-manager">
    <el-card>
      <div slot="header">
        <span>MCP服务器管理</span>
        <el-button
          style="float: right"
          type="primary"
          size="small"
          @click="showAddDialog = true">
          添加MCP
        </el-button>
      </div>

      <!-- 服务器列表 -->
      <el-table :data="servers" style="width: 100%">
        <el-table-column prop="name" label="名称" width="180"/>
        <el-table-column prop="server_type" label="类型" width="120"/>
        <el-table-column label="状态" width="100">
          <template slot-scope="scope">
            <el-tag :type="scope.row.is_running ? 'success' : 'info'">
              {{ scope.row.is_running ? '运行中' : '已停止' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="tools_count" label="工具数" width="100"/>
        <el-table-column label="操作">
          <template slot-scope="scope">
            <el-button
              size="mini"
              @click="refreshTools(scope.row.id)">
              刷新工具
            </el-button>
            <el-button
              size="mini"
              type="danger"
              @click="removeServer(scope.row.id)">
              删除
            </el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <!-- 添加MCP对话框 -->
    <el-dialog
      title="添加MCP服务器"
      :visible.sync="showAddDialog"
      width="600px">

      <!-- 从模板选择 -->
      <el-form>
        <el-form-item label="选择模板">
          <el-select
            v-model="selectedTemplate"
            @change="applyTemplate"
            placeholder="选择预设模板">
            <el-option
              v-for="tpl in templates"
              :key="tpl.id"
              :label="tpl.name"
              :value="tpl.id">
              <span style="float: left">{{ tpl.name }}</span>
              <span style="float: right; color: #8492a6">
                {{ tpl.description }}
              </span>
            </el-option>
          </el-select>
        </el-form-item>

        <el-form-item label="服务器ID">
          <el-input v-model="newServer.id" placeholder="github"/>
        </el-form-item>

        <el-form-item label="显示名称">
          <el-input v-model="newServer.name" placeholder="GitHub"/>
        </el-form-item>

        <el-form-item label="命令">
          <el-input v-model="newServer.command" placeholder="npx"/>
        </el-form-item>

        <el-form-item label="参数">
          <el-input
            v-model="newServer.argsStr"
            placeholder="-y @modelcontextprotocol/server-github"/>
        </el-form-item>

        <!-- 环境变量 -->
        <el-form-item
          v-for="env in requiredEnvs"
          :key="env"
          :label="env">
          <el-input
            v-model="newServer.env[env]"
            type="password"
            placeholder="输入值"/>
        </el-form-item>
      </el-form>

      <div slot="footer">
        <el-button @click="showAddDialog = false">取消</el-button>
        <el-button type="primary" @click="addServer">添加</el-button>
      </div>
    </el-dialog>
  </div>
</template>

<script>
export default {
  data() {
    return {
      servers: [],
      templates: [],
      showAddDialog: false,
      selectedTemplate: '',
      newServer: {
        id: '',
        name: '',
        command: '',
        args: [],
        env: {}
      },
      requiredEnvs: []
    }
  },
  mounted() {
    this.loadServers()
    this.loadTemplates()
  },
  methods: {
    async loadServers() {
      const res = await this.$http.get('/api/mcp/servers')
      this.servers = res.data.data
    },
    async loadTemplates() {
      const res = await this.$http.get('/api/mcp/templates')
      this.templates = res.data.data
    },
    applyTemplate(templateId) {
      const template = this.templates.find(t => t.id === templateId)
      if (template) {
        this.newServer.command = template.command
        this.newServer.args = template.args
        this.newServer.argsStr = template.args.join(' ')
        this.requiredEnvs = template.env_vars || []
      }
    },
    async addServer() {
      try {
        const args = this.newServer.argsStr.split(' ').filter(Boolean)
        await this.$http.post('/api/mcp/servers', {
          ...this.newServer,
          args
        })
        this.$message.success('MCP服务器添加成功')
        this.showAddDialog = false
        this.loadServers()
      } catch (error) {
        this.$message.error('添加失败: ' + error.message)
      }
    },
    async removeServer(id) {
      await this.$http.delete(`/api/mcp/servers/${id}`)
      this.loadServers()
    }
  }
}
</script>
```

---

## 📝 完整使用流程

### 场景：用户想启用MCP搜索并测试

```bash
# 1. 启动后端（启用MCP）
cd /Users/chz/code/zz4.0/backend
./start.sh mcp-search

# 2. 测试普通聊天（不使用MCP）
curl -X POST http://localhost:5001/api/agent/chat/stream \
  -H "Content-Type: application/json" \
  -d '{"message": "你好"}'

# 3. 测试MCP搜索
curl -X POST http://localhost:5001/api/agent/chat/stream \
  -H "Content-Type: application/json" \
  -d '{
    "message": "最新的AI新闻",
    "use_mcp_search": true
  }'

# 4. 添加GitHub MCP
curl -X POST http://localhost:5001/api/mcp/servers \
  -H "Content-Type: application/json" \
  -d '{
    "id": "github",
    "name": "GitHub",
    "server_type": "github",
    "command": "npx",
    "args": ["-y", "@modelcontextprotocol/server-github"],
    "env": {"GITHUB_PERSONAL_ACCESS_TOKEN": "your_token"}
  }'

# 5. 查看MCP服务器列表
curl http://localhost:5001/api/mcp/servers
```

---

## ✅ 快速检查清单

- [ ] 后端已启动：`./start.sh mcp-search`
- [ ] 检查健康状态：`curl http://localhost:5001/api/mcp/health`
- [ ] 前端已配置 `use_mcp_search` 参数
- [ ] 环境变量已设置（如需要）
