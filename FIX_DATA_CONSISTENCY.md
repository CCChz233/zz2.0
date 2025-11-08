# 数据一致性问题修复说明

## 问题描述

每次刷新页面时，地图数据统计数值都会变化，导致用户体验不佳。

## 根本原因

1. **日期参数未固定**：如果前端没有传入 `date` 参数，后端会使用 `datetime.utcnow().date()`（UTC 的今天），每次请求时间不同
2. **数据实时更新**：后台脚本 `databoard-map-process.py` 可能在实时写入新数据，导致查询时数据量在变化
3. **分页查询时序问题**：`_group_count` 函数使用分页拉取数据，如果数据在查询过程中被更新，可能出现不一致

## 解决方案

### 方案1：前端固定传入日期参数（推荐）

**前端修改**：在调用 API 时，明确传入 `date` 参数

```javascript
// 前端代码示例
const today = new Date().toISOString().split('T')[0]; // YYYY-MM-DD
fetch(`/api/databoard/map/data?date=${today}&timeRange=day&type=all&level=province`)
```

**优点**：
- 简单直接
- 用户可以控制查看哪个日期的数据
- 不会因为数据实时更新而影响查询结果

### 方案2：后端使用数据库最新日期（已实现）

已在 `_parse_date_arg()` 函数中实现：
- 如果前端未传 `date` 参数，从数据库获取最新数据的日期
- 这样可以保证在同一次会话中多次刷新时数据一致

**优点**：
- 向后兼容，不影响现有前端代码
- 自动使用最新的数据日期

**缺点**：
- 每次请求都要查询数据库（轻微性能影响）
- 如果数据在两次请求间更新，仍可能看到不同结果

### 方案3：使用数据快照（最佳但复杂）

如果需要完全一致的数据视图，可以考虑：
1. 创建数据快照表
2. 定期（如每小时）生成快照
3. 前端查询时使用快照数据

## 已修复的代码

已修改 `backend_api/databoard_map_bp.py` 中的 `_parse_date_arg()` 函数：

```python
def _parse_date_arg(d: Optional[str]) -> date_cls:
    """
    解析日期参数。
    如果未提供日期，返回数据库中最新的日期（保证数据一致性），
    而不是使用 UTC 的今天（避免因数据实时更新导致每次查询结果不同）。
    """
    if not d:
        # 从数据库获取最新日期，而不是使用 UTC 的今天
        try:
            res = sb.table("fact_events").select("published_at")
                .order("published_at", desc=True).limit(1).execute()
            # ... 解析并返回最新日期
        except Exception:
            # 兜底：如果查询失败，使用 UTC 今天
            return datetime.utcnow().date()
    # ... 正常解析传入的日期
```

## 建议的完整解决方案

### 1. 前端修改（强烈推荐）

在调用地图 API 时，始终传入固定的日期参数：

```typescript
// 在组件的生命周期中，固定一个日期
const [queryDate] = useState(() => {
  // 默认使用今天的日期，或者从 URL 参数/状态管理中获取
  return new Date().toISOString().split('T')[0];
});

// 所有 API 调用都使用这个日期
useEffect(() => {
  fetch(`/api/databoard/map/data?date=${queryDate}&timeRange=day&type=all&level=province`)
    .then(res => res.json())
    .then(data => {
      // 处理数据
    });
}, [queryDate]);
```

### 2. 后端优化（可选）

如果希望减少数据库查询，可以考虑：
- 添加 Redis 缓存，缓存最新日期（TTL 5分钟）
- 或者提供一个 `/api/databoard/map/latest-date` 接口，前端先获取日期再查询

### 3. 数据写入优化

如果 `databoard-map-process.py` 脚本在实时运行：
- 考虑在固定的时间窗口内批量写入（如每小时写入一次）
- 或者使用数据库事务，确保查询时数据一致性

## 验证修复

1. 重启后端服务
2. 刷新页面多次，观察数值是否保持一致
3. 检查后端日志，确认日期参数是否正确

## 相关文件

- `backend_api/databoard_map_bp.py` - 已修复日期参数解析
- `jobs/databoard-map-process.py` - 数据写入脚本
- 前端代码 - 建议添加固定的日期参数

