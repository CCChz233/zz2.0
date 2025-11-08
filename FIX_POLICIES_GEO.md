# 政策数据地理编码问题修复方案

## 问题诊断

✅ **数据存在**：`fact_events` 表中有 143 条政策数据  
❌ **地理编码缺失**：所有记录的 `province_code` 都为 NULL

## 根本原因

1. **LLM 无法从文本中提取省份信息**
   - 政策/论文类内容通常是全国性的，不包含具体省份信息
   - LLM 的 prompt 要求"若不适用留空或null"，导致很多政策数据没有省份

2. **缺少启发式规则**
   - 对于政策数据，没有从 URL、标题等字段推断省份的逻辑

## 解决方案

### 方案1：改进LLM Prompt（推荐）

针对政策/论文类数据，改进 prompt，要求 LLM 尽可能从标题、来源等推断省份：

```python
# 在 databoard-map-process.py 中修改 PROMPT_SUMMARY
PROMPT_SUMMARY = (
    "你是一名严谨的中英文信息总结与地理定位助手。无论输入是什么语言，请始终用简体中文输出。"
    "如果原文为英文论文或英文资讯，请先理解后用中文进行专业概括，不要保留英文句子。"
    "你必须判断事件发生的国家（优先返回 ISO3，如 CHN/USA/DEU；若不确定，返回 null），不要因为出现中文或中国机构名就默认中国。"
    "**重要：对于政策、法规、通知等文档，请从以下信息推断省份：**"
    "1. URL 中的省份拼音或缩写（如 zj.gov.cn 表示浙江省）"
    "2. 标题中的省份名称（如'北京市'、'广东省'等）"
    "3. 来源机构名称（如'北京市政府'、'浙江省教育厅'等）"
    "4. 如果确实是全国性政策，可以标注为'全国'"
    "请仅返回严格的 JSON 对象，字段如下："
    "{\\\"summary\\\":\\\"<=300字的简体中文摘要\\\",\\\"keywords\\\":[\\\"关键词1\\\",...],\\\"country\\\":\\\"ISO3或国家名(如 CHN/中国/USA/美国)\\\",\\\"province\\\":\\\"中国省级行政区中文名(如 广东省、北京市、全国)，若完全无法判断才留空或null\\\"}。"
    "请避免臆测；当无法判断时，对应字段置为 null。禁止输出除 JSON 以外的任何内容。"
)
```

### 方案2：增强URL推断逻辑（快速修复）

在 `process_row()` 函数中，对于政策数据，加强从 URL 推断省份的逻辑：

```python
# 在 process_row() 函数中，地理编码部分添加：

# 特别处理：如果是政策数据且没有省份，尝试从 URL 推断
if row.get("type") == "paper" and not province_code:
    # 尝试从 URL 推断省份
    inferred_prov = infer_province_from_url(url_for_geo)
    if inferred_prov:
        province_code = inferred_prov
        if not geo_source:
            geo_source = "url_inference"
```

### 方案3：允许全国性政策显示（临时方案）

修改后端API，允许显示没有省份信息的政策数据（作为"全国"或其他分类）：

```python
# 在 databoard_map_bp.py 的 _group_count 函数中
# 对于没有省份的数据，可以设置一个默认值
if not code_str:  # 如果省份代码为空
    code_str = "000000"  # 使用"000000"表示全国，或者跳过
    continue  # 或者跳过，不在地图上显示
```

### 方案4：批量修复已有数据（推荐先执行）

创建一个SQL脚本，对已有的政策数据进行地理编码修复：

```sql
-- 1. 从 URL 推断省份（如果 URL 包含省份信息）
-- 注意：这需要根据实际 URL 格式调整

-- 2. 从标题中提取省份名称
-- 可以写一个函数来匹配省份名称

-- 3. 如果确实无法推断，设置为"全国"（000000）
UPDATE fact_events
SET province_code = '110000'  -- 北京代码，作为示例
WHERE src_table = '00_papers'
  AND province_code IS NULL
  AND (url LIKE '%beijing%' OR url LIKE '%北京%' OR title LIKE '%北京%');
-- 类似地，可以为其他省份添加规则
```

## 立即执行的排查步骤

### 步骤1：检查是否有国家信息

运行以下SQL，查看政策数据的国家分布：

```sql
SELECT 
    country_iso3,
    COUNT(*) as count
FROM fact_events
WHERE src_table = '00_papers'
GROUP BY country_iso3;
```

### 步骤2：检查LLM返回的地理信息

```sql
SELECT 
    payload->>'llm_country' as llm_country,
    payload->>'llm_province' as llm_province,
    payload->>'geo_source' as geo_source,
    COUNT(*) as count
FROM fact_events
WHERE src_table = '00_papers'
GROUP BY payload->>'llm_country', payload->>'llm_province', payload->>'geo_source'
ORDER BY count DESC;
```

### 步骤3：检查URL是否可以推断省份

```sql
-- 查看一些示例数据
SELECT 
    url,
    title,
    payload->>'llm_province' as llm_province
FROM fact_events
WHERE src_table = '00_papers'
  AND province_code IS NULL
LIMIT 20;
```

## 推荐的修复流程

1. **立即执行**：运行 `check_policies_geo.sql` 中的查询，确认具体情况
2. **快速修复**：实施方案2（增强URL推断），重新处理政策数据
3. **长期优化**：实施方案1（改进LLM Prompt），提高地理编码准确性
4. **数据修复**：对已有数据运行批量修复脚本

## 重新处理政策数据

修复代码后，重新运行数据处理脚本：

```bash
# 重新处理最近30天的政策数据
python jobs/databoard-map-process.py \
  --days 30 \
  --include-types paper \
  --geo-by-llm \
  --log-geo  # 查看地理编码日志
```

## 验证修复

修复后，运行以下SQL验证：

```sql
SELECT 
    COUNT(*) as total,
    COUNT(CASE WHEN province_code IS NOT NULL THEN 1 END) as with_province
FROM fact_events
WHERE src_table = '00_papers';
```

如果 `with_province` 大于0，说明修复成功！

