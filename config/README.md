# 提示词配置文件说明

## 概述

所有系统提示词现在统一由后端配置文件管理，不再硬编码在前端代码中。

## 配置文件位置

`backend/config/prompts.json`

## 配置文件结构

```json
{
  "base_system_prompt": "基础系统提示词（定义AI的基本角色）",
  "global_prompts": [
    "全局提示词1（业务上下文信息）",
    "全局提示词2（更多业务信息）"
  ],
  "default_options": {
    "temperature": 0.8,
    "top_p": 0.8
  }
}
```

## 提示词类型

### 1. base_system_prompt（基础系统提示词）
- **位置**: `prompts.json` 的 `base_system_prompt` 字段
- **作用**: 定义AI的基本角色和性格
- **特点**: 每次对话都会包含
- **优先级**: 环境变量 `BASE_SYSTEM_PROMPT` > 配置文件

### 2. global_prompts（全局提示词）
- **位置**: `prompts.json` 的 `global_prompts` 数组
- **作用**: 提供业务上下文信息（如采购信息、政策信息、公司信息等）
- **特点**: 持久生效，每次对话都包含
- **修改**: 直接编辑 `prompts.json` 文件

### 3. temporary_prompts（临时提示词）
- **位置**: 前端 `AgentModule.vue` 的 `temporarySystemPrompts` 数组
- **作用**: 一次性指令或特殊要求
- **特点**: 仅对下一次对话生效，用后即清空
- **传递**: 通过API请求的 `temporary_prompts` 参数传递

## 提示词组合逻辑

后端会自动组合三种提示词：

```
最终系统提示词 = base_system_prompt + global_prompts + temporary_prompts
```

组合顺序：
1. 基础系统提示词
2. 全局提示词（按数组顺序）
3. 临时提示词（按数组顺序）

## 如何修改提示词

### 修改基础提示词

编辑 `backend/config/prompts.json`：

```json
{
  "base_system_prompt": "你的新提示词内容"
}
```

或者使用环境变量：

```bash
export BASE_SYSTEM_PROMPT="你的新提示词内容"
```

### 修改全局提示词

编辑 `backend/config/prompts.json`：

```json
{
  "global_prompts": [
    "新的全局提示词1",
    "新的全局提示词2"
  ]
}
```

### 添加临时提示词（前端）

```javascript
// 在 AgentModule.vue 中
this.setTemporarySystemPrompt("请用表格格式回答")
```

## 配置热更新

修改配置文件后，需要重启后端服务才能生效。

如果需要热更新（不重启服务），可以调用：

```python
from config import reload_config
reload_config()
```

## 配置文件示例

```json
{
  "base_system_prompt": "你是致真智能体，一个友好、专业的AI助手。",
  "global_prompts": [
    "以下是最近的采购信息：...",
    "公司产品信息：..."
  ],
  "default_options": {
    "temperature": 0.8,
    "top_p": 0.8
  }
}
```

## 注意事项

1. **JSON格式**: 确保JSON格式正确，可以使用JSON验证工具检查
2. **编码**: 文件使用UTF-8编码，支持中文
3. **备份**: 修改前建议备份配置文件
4. **重启**: 修改后需要重启后端服务（除非实现了热更新）
5. **环境变量**: 环境变量优先级高于配置文件

## 文件位置

- 配置文件: `backend/config/prompts.json`
- 配置模块: `backend/config/__init__.py`
- 使用位置: `backend/backend_api/agent_chat_bp.py`

