# 政策数据排查指南

## 问题：政策数据为0

## 映射关系

### 1. 前端/API 层面
- **前端显示**：`政策` (Policies)
- **API参数**：`type=policies`
- **后端映射**：`TYPE_TO_SRC_TABLE["policies"] = "00_papers"`

### 2. 数据处理脚本层面
- **视图类型**：`VIEW_SOURCE_TYPES = {"news", "competitor", "opportunity", "paper"}`
- **注意**：这里用的是 `paper`，不是 `policies`！

### 3. 数据表
- **源表**：`00_papers` (论文/政策表)
- **事实表**：`fact_events`
- **字段映射**：
  - `type` 字段：可能存储的是 `paper`（来自视图）
  - `src_table` 字段：存储的是 `00_papers`

## 问题根源

后端API查询时使用的是 **`src_table` 字段过滤**，而不是 `type` 字段：

```python
# 在 get_map_data() 函数中
src_tbl = TYPE_TO_SRC_TABLE.get(t)  # "policies" -> "00_papers"
ef[SRC_TABLE_FIELD] = src_tbl  # SRC_TABLE_FIELD = "src_table"
b = _group_count(src["table"], src["time_field"], group_field, start, end, ef)
```

所以查询逻辑是：
- 查询 `fact_events` 表
- 过滤条件：`src_table = '00_papers'`
- **不依赖 `type` 字段的值**

## 排查步骤

### 步骤1：检查数据库中是否有 `00_papers` 源表的数据

```sql
-- 查询 fact_events 表中 src_table = '00_papers' 的数据量
SELECT 
    COUNT(*) as total,
    COUNT(DISTINCT province_code) as provinces_with_data,
    MIN(published_at) as earliest,
    MAX(published_at) as latest
FROM fact_events
WHERE src_table = '00_papers';
```

### 步骤2：检查这些数据是否有地理信息（省份/国家）

```sql
-- 查询有地理信息的政策数据
SELECT 
    country_iso3,
    province_code,
    COUNT(*) as count
FROM fact_events
WHERE src_table = '00_papers'
GROUP BY country_iso3, province_code
ORDER BY count DESC;
```

### 步骤3：检查时间范围

```sql
-- 检查最近7天的政策数据
SELECT 
    DATE(published_at) as date,
    COUNT(*) as count
FROM fact_events
WHERE src_table = '00_papers'
  AND published_at >= NOW() - INTERVAL '7 days'
GROUP BY DATE(published_at)
ORDER BY date DESC;
```

### 步骤4：检查原始源表 `00_papers` 是否有数据

```sql
-- 查询原始源表
SELECT 
    COUNT(*) as total,
    MIN(published_at) as earliest,
    MAX(published_at) as latest
FROM "00_papers";
```

### 步骤5：检查视图数据

```sql
-- 检查视图（根据你的实际视图名调整）
-- 如果视图名是 v_events_geocoded 或 v_events_ready
SELECT 
    type,
    src_table,
    COUNT(*) as count
FROM v_events_geocoded  -- 替换为你的实际视图名
WHERE type = 'paper' OR src_table = '00_papers'
GROUP BY type, src_table;
```

### 步骤6：检查 type 字段的值

```sql
-- 查看 fact_events 表中所有 type 值的分布
SELECT 
    type,
    src_table,
    COUNT(*) as count
FROM fact_events
GROUP BY type, src_table
ORDER BY count DESC;
```

## 可能的问题和解决方案

### 问题1：数据未处理
**症状**：`00_papers` 表有数据，但 `fact_events` 表没有对应的记录

**原因**：`databoard-map-process.py` 脚本未运行或未处理 `paper` 类型的数据

**解决**：
1. 运行数据处理脚本：
   ```bash
   python jobs/databoard-map-process.py --days 30 --include-types paper
   ```

2. 检查脚本日志，确认是否有数据被处理

### 问题2：数据缺少地理信息
**症状**：`fact_events` 表有 `src_table='00_papers'` 的记录，但 `province_code` 或 `country_iso3` 为 NULL

**原因**：LLM 无法从文本中提取地理信息，或者原始数据中没有地理信息

**解决**：
1. 检查原始数据是否有地理信息
2. 查看脚本日志中的地理编码信息（使用 `--log-geo` 参数）
3. 可能需要改进 LLM prompt 或添加启发式规则

### 问题3：时间范围不匹配
**症状**：数据库有数据，但查询的时间范围内没有数据

**原因**：API 默认查询的是"今天"的数据，但数据库中的政策数据可能是历史数据

**解决**：
1. 前端传入更大的时间范围，如 `timeRange=month` 或 `timeRange=year`
2. 或者前端传入特定的 `date` 参数，查询历史数据

### 问题4：视图或源表配置错误
**症状**：数据存在但 `src_table` 字段值不匹配

**原因**：视图中的 `src_table` 字段值不是 `00_papers`

**解决**：
1. 检查视图定义，确认 `src_table` 字段的值
2. 如果视图中的值是其他名称，需要修改 `TYPE_TO_SRC_TABLE` 映射

## 快速诊断SQL

运行以下SQL，一次性查看所有关键信息：

```sql
-- 综合诊断查询
WITH stats AS (
    SELECT 
        'fact_events (policies)' as source,
        COUNT(*) as total,
        COUNT(CASE WHEN province_code IS NOT NULL THEN 1 END) as with_province,
        COUNT(CASE WHEN country_iso3 IS NOT NULL THEN 1 END) as with_country,
        MIN(published_at) as earliest,
        MAX(published_at) as latest
    FROM fact_events
    WHERE src_table = '00_papers'
),
source_stats AS (
    SELECT 
        '00_papers (source)' as source,
        COUNT(*) as total,
        NULL::bigint as with_province,
        NULL::bigint as with_country,
        MIN(published_at) as earliest,
        MAX(published_at) as latest
    FROM "00_papers"
)
SELECT * FROM stats
UNION ALL
SELECT * FROM source_stats;
```

## 下一步行动

1. **先运行步骤1-6的SQL查询**，确认数据在哪里断链
2. **根据查询结果**，针对性地解决问题
3. **如果数据都在但显示为0**，检查前端API调用是否正确传入了参数

