# 端口配置说明

## 服务端口分配

- **GPT-Researcher**: `http://localhost:8000`
  - 用于研究任务
  - 前端不需要直接访问

- **后端 Flask 应用**: `http://localhost:5001` (默认)
  - 主 API 服务
  - 前端应该访问这个端口

## 启动服务

```bash
# 终端1: 启动 GPT-Researcher
cd /Users/chz/code/zz3.0/gpt-researcher
python -m uvicorn main:app --reload --port 8000

# 终端2: 启动后端 Flask 应用
cd /Users/chz/code/zz3.0/backend
python app.py  # 默认端口 5001

# 或者指定端口
python app.py --port 5001
```

## 环境变量配置

可以在 `.env` 文件中设置：

```bash
PORT=5001  # 后端 Flask 应用端口
GPT_RESEARCHER_BASE_URL=http://localhost:8000  # GPT-Researcher 地址
```

## 测试

```bash
# 测试后端 API（注意端口是 5001）
curl -X POST http://localhost:5001/api/agent/chat \
  -H "Content-Type: application/json" \
  -d '{
    "message": "研究一下人工智能",
    "session_id": "test-123"
  }'
```
