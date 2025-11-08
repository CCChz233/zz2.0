# 修复 "Server disconnected" 错误

## 问题描述

在 `_group_count` 函数执行时，出现以下错误：
```
[WARN] group_count page error (fact_events): Server disconnected
```

## 问题原因

1. **Supabase 连接超时**：分页查询时，如果数据量大或查询时间过长，Supabase 可能断开连接
2. **请求频率过高**：快速连续的分页请求可能导致连接被重置
3. **网络不稳定**：临时的网络波动可能导致连接中断

## 已实施的修复

### 1. 添加重试机制

在 `_group_count` 和 `_group_count_city_fallback` 函数中：
- **最大重试次数**：3次
- **重试延迟**：递增延迟（1s, 2s, 3s）
- **智能识别**：只对连接相关错误进行重试（server disconnected, connection, timeout, network, reset）

### 2. 添加请求限流

- **分页延迟**：每处理 5 页数据后，休息 0.1 秒
- 避免请求过快导致连接被重置

### 3. 改进错误处理

- 区分连接错误和其他错误
- 连接错误：自动重试
- 其他错误：记录日志并跳过当前页
- 达到最大重试次数后，跳过当前页继续处理

## 修复后的代码逻辑

```python
# 重试机制
max_retries = 3
retry_delay = 1.0

while retry_count < max_retries:
    try:
        # 执行查询
        r = q.execute()
        break  # 成功，跳出重试循环
    except Exception as e:
        if is_connection_error and retry_count < max_retries:
            # 等待后重试
            time.sleep(retry_delay * retry_count)
            retry_count += 1
        else:
            # 记录错误，跳过当前页
            break
```

## 效果

- ✅ 自动重试连接错误，提高成功率
- ✅ 避免请求过快，减少连接断开
- ✅ 即使部分页面失败，也能继续处理其他数据
- ✅ 详细的错误日志，便于排查问题

## 进一步优化建议

如果问题仍然存在，可以考虑：

### 1. 减少分页大小

```bash
# 设置环境变量
export MAP_FETCH_PAGE_SIZE=1000  # 默认是 5000
```

### 2. 增加重试次数

修改代码中的 `max_retries = 3` 为更大的值（如 5）

### 3. 增加延迟时间

修改代码中的 `retry_delay = 1.0` 为更大的值（如 2.0）

### 4. 检查 Supabase 连接池配置

如果使用连接池，可能需要调整连接池大小和超时设置

## 验证修复

修复后，观察日志：
- ✅ 如果仍有连接错误，应该看到重试日志
- ✅ 重试成功后，应该能正常返回数据
- ✅ 如果达到最大重试次数，会跳过当前页但继续处理

## 相关文件

- `backend_api/databoard_map_bp.py` - 已修复 `_group_count` 和 `_group_count_city_fallback` 函数

