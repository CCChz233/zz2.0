# 提示词配置迁移总结

## 迁移完成 ✅

已将所有系统提示词从前端迁移到后端配置文件管理。

## 变更内容

### 1. 新增文件

- `backend/config/__init__.py` - 配置加载模块
- `backend/config/prompts.json` - 提示词配置文件
- `backend/config/README.md` - 配置文件使用说明
- `backend/config/PROMPTS_MIGRATION.md` - 本文档

### 2. 修改文件

#### 后端
- `backend/backend_api/agent_chat_bp.py`
  - 导入配置模块：`from config import build_system_prompt, get_default_options`
  - 修改 `/chat` 接口：从配置文件获取系统提示词
  - 修改 `/chat/stream` 接口：从配置文件获取系统提示词
  - 支持 `temporary_prompts` 参数（临时提示词）

#### 前端
- `vue-admin-zhizhen/src/views/databoard/AgentModule.vue`
  - 移除 `systemPrompt` 数据属性
  - 移除 `globalSystemPrompts` 数据属性
  - 移除 `setGlobalSystemPrompt()` 方法
  - 移除 `replaceGlobalSystemPrompts()` 方法
  - 移除 `clearGlobalSystemPrompts()` 方法
  - 修改 `buildCombinedSystemPrompt()` → `buildTemporaryPrompts()`（只返回临时提示词）
  - 更新 API 调用：传递 `temporary_prompts` 而不是 `system_prompt`

- `vue-admin-zhizhen/src/api/agent/chat.js`
  - 更新参数说明：`system_prompt` → `temporary_prompts`
  - 更新请求体：传递 `temporary_prompts` 数组

## 配置结构

### prompts.json 结构

```json
{
  "base_system_prompt": "基础系统提示词",
  "global_prompts": [
    "全局提示词1",
    "全局提示词2"
  ],
  "default_options": {
    "temperature": 0.8,
    "top_p": 0.8
  }
}
```

## 提示词组合逻辑

后端自动组合：

```
最终提示词 = base_system_prompt + global_prompts + temporary_prompts
```

## API 变更

### 请求参数变更

**之前**:
```json
{
  "message": "用户消息",
  "system_prompt": "完整的系统提示词（前端组合）",
  "conversation_history": [],
  "options": {}
}
```

**现在**:
```json
{
  "message": "用户消息",
  "temporary_prompts": ["临时提示词1", "临时提示词2"],  // 可选
  "conversation_history": [],
  "options": {}
}
```

## 优势

1. ✅ **业务逻辑安全**: 提示词不再暴露在前端
2. ✅ **易于维护**: 修改配置文件即可，无需重新部署前端
3. ✅ **版本控制**: 可以追踪提示词的变更历史
4. ✅ **环境隔离**: 可以为不同环境准备不同配置
5. ✅ **代码简洁**: 前端代码更简洁，移除200+行提示词代码

## 使用说明

### 修改提示词

1. 编辑 `backend/config/prompts.json`
2. 重启后端服务
3. 新配置立即生效

### 添加临时提示词（前端）

```javascript
// 在 AgentModule.vue 中
this.setTemporarySystemPrompt("请用表格格式回答")
// 发送消息后自动清空
```

## 测试

配置模块已测试通过：

```bash
cd backend
python -c "from config import build_system_prompt; print(build_system_prompt())"
```

## 注意事项

1. 修改配置文件后需要重启后端服务
2. 确保 JSON 格式正确
3. 文件使用 UTF-8 编码
4. 环境变量 `BASE_SYSTEM_PROMPT` 优先级高于配置文件

