# LLM返回NULL的原因分析

## 问题确认

✅ **查询结果显示**：所有143条政策数据的 `llm_country` 和 `llm_province` 都是 `NULL`

## 根本原因分析

### 1. **LLM Prompt 过于保守**

当前的 prompt（第138-145行）要求：
```
"你必须判断事件发生的国家（优先返回 ISO3，如 CHN/USA/DEU；若不确定，返回 null）"
"请避免臆测；当无法判断时，对应字段置为 null。"
```

**问题**：
- 政策/论文类内容通常是全国性的，不包含明确的地理标识
- LLM 从正文内容中无法判断具体省份
- 由于 prompt 要求"不确定就返回 null"，LLM 采取了保守策略

### 2. **LLM 没有充分利用 URL 信息**

虽然代码中把 URL 传给了 LLM（第502行）：
```python
payload = {
    "title": row.get("title"),
    "content": (row.get("content") or "")[:6000],
    "url": row.get("url_norm") or row.get("url"),  # URL被传入
    ...
}
```

但是 **prompt 中没有明确要求 LLM 从 URL 中提取省份信息**！

**问题**：
- URL 可能包含省份信息（如 `beijing.gov.cn`、`zj.gov.cn`）
- 但 prompt 没有特别强调要从 URL 中提取
- LLM 可能忽略了 URL 中的地理信息

### 3. **政策内容本身的特点**

政策/论文类内容的特点：
- 通常是全国性的，标题和正文很少包含具体省份
- 例如："关于促进人工智能发展的指导意见" - 没有省份信息
- 但来源URL可能是 `beijing.gov.cn`，说明是北京市的政策

### 4. **数据是历史数据**

这143条数据是在添加 URL/标题推断逻辑之前处理的，所以：
- LLM 返回 NULL
- 没有 URL 推断逻辑
- 最终所有记录的 `province_code` 都是 NULL

## 解决方案

### 方案1：改进 LLM Prompt（推荐）

针对政策/论文类数据，改进 prompt，特别强调从 URL 中提取信息：

```python
PROMPT_SUMMARY = (
    "你是一名严谨的中英文信息总结与地理定位助手。无论输入是什么语言，请始终用简体中文输出。"
    "如果原文为英文论文或英文资讯，请先理解后用中文进行专业概括，不要保留英文句子。"
    
    "**重要：地理信息提取规则**"
    "1. **国家判断**：优先返回 ISO3（如 CHN/USA/DEU），若不确定返回 null"
    "2. **省份判断**（仅适用于中国）："
    "   - **优先从 URL 中提取**："
    "     * 如果 URL 包含省份拼音或缩写（如 beijing.gov.cn → 北京市，zj.gov.cn → 浙江省）"
    "     * 如果 URL 包含省份中文名（如 ...北京... → 北京市）"
    "   - **其次从标题中提取**：如果标题包含省份名称（如'北京市'、'广东省'）"
    "   - **最后从正文中提取**：如果正文明确提到省份"
    "   - 如果确实是全国性政策，可以标注为'全国'或留空"
    "   - **不要因为政策内容本身没有省份就返回 null，要先检查 URL 和标题！**"
    
    "请仅返回严格的 JSON 对象，字段如下："
    "{\\\"summary\\\":\\\"<=300字的简体中文摘要\\\",\\\"keywords\\\":[\\\"关键词1\\\",...],\\\"country\\\":\\\"ISO3或国家名(如 CHN/中国/USA/美国)\\\",\\\"province\\\":\\\"中国省级行政区中文名(如 广东省、北京市、全国)，若完全无法判断才留空或null\\\"}。"
    "请避免臆测；当无法判断时，对应字段置为 null。禁止输出除 JSON 以外的任何内容。"
)
```

### 方案2：重新处理数据（已添加URL推断逻辑）

我已经在代码中添加了 URL 和标题推断逻辑（第564-583行），但需要重新处理数据才能生效。

**步骤**：
1. 先运行 SQL 查询，看看有多少数据可以从 URL/标题推断
2. 重新运行数据处理脚本

### 方案3：批量修复已有数据

创建一个 SQL 脚本，对已有数据进行批量修复（从 URL 推断省份）。

## 立即行动

### 步骤1：检查有多少数据可以从 URL/标题推断

运行以下 SQL（在 `check_policies_geo_detail.sql` 的查询5和6）：

```sql
-- 检查 URL 中是否包含省份信息
SELECT 
    CASE 
        WHEN url ILIKE '%beijing%' OR url ILIKE '%北京%' OR url ILIKE '%.bj.%' OR url ILIKE '%bj.gov.cn%' THEN '北京'
        WHEN url ILIKE '%shanghai%' OR url ILIKE '%上海%' OR url ILIKE '%.sh.%' OR url ILIKE '%sh.gov.cn%' THEN '上海'
        WHEN url ILIKE '%guangdong%' OR url ILIKE '%广东%' OR url ILIKE '%.gd.%' OR url ILIKE '%gd.gov.cn%' THEN '广东'
        WHEN url ILIKE '%zhejiang%' OR url ILIKE '%浙江%' OR url ILIKE '%.zj.%' OR url ILIKE '%zj.gov.cn%' THEN '浙江'
        WHEN url ILIKE '%gov.cn%' THEN '其他gov.cn'
        ELSE '无明确省份信息'
    END as url_province_hint,
    COUNT(*) as count
FROM fact_events
WHERE src_table = '00_papers'
GROUP BY url_province_hint
ORDER BY count DESC;
```

如果查询结果显示有很多 URL 包含省份信息，说明可以通过 URL 推断修复！

### 步骤2：改进 Prompt 并重新处理

1. 改进 prompt（方案1）
2. 重新运行数据处理脚本

### 步骤3：验证修复效果

运行 SQL 验证是否有省份信息了。

