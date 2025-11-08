# Paper 类型数据处理流程详解

## 完整流程图

```
原始数据源 (00_papers 表)
    ↓
统一视图 (v_events_geocoded 或 v_events_ready)
    ↓
数据处理脚本 (databoard-map-process.py)
    ↓
[1] 数据读取与过滤
    ↓
[2] LLM 处理（摘要、关键词、地理信息）
    ↓
[3] 地理编码（多级推断）
    ↓
[4] 数据组装
    ↓
[5] 写入 fact_events 表
```

## 详细步骤说明

### 步骤1：数据读取与过滤

**位置**：`run_once()` 函数（第633-652行）

**过程**：
1. 从统一视图 `UNIFIED_VIEW`（默认：`v_events_geocoded`）读取数据
2. 过滤条件：
   ```python
   # 时间过滤（如果指定了 --days 参数）
   if since_iso:
       q = q.gte("published_at", since_iso)
   
   # 类型过滤（如果指定了 --include-types paper）
   if TYPE_FILTER_INCLUDE:
       q = q.in_("type", sorted(TYPE_FILTER_INCLUDE))  # 例如：{"paper"}
   ```
3. 排序：按 `published_at` 降序，再按 `src_id` 降序
4. 分页：每次读取 `BATCH_SIZE` 条（默认20条）

**关键字段**：
- `type`: 从视图读取，应该是 `"paper"`
- `src_table`: 从视图读取，应该是 `"00_papers"`
- `title`, `content`, `url`, `source`, `published_at` 等

---

### 步骤2：LLM 处理（摘要、关键词、地理信息）

**位置**：`process_row()` 函数（第508-518行）

**过程**：

#### 2.1 准备输入数据
```python
payload = {
    "title": row.get("title"),                    # 标题
    "content": (row.get("content") or "")[:6000], # 正文（最多6000字符）
    "url": row.get("url_norm") or row.get("url"), # URL
    "source": row.get("source"),                  # 来源
    "type": row.get("type"),                      # 类型（"paper"）
    "time_hint": row.get("published_at")          # 发布时间
}
```

#### 2.2 调用 LLM（Qwen API）
**位置**：`qwen_summary()` 函数（第158-207行）

**Prompt**（已改进，第138-156行）：
```
你是一名严谨的中英文信息总结与地理定位助手。

**重要：省份信息提取规则（仅适用于中国）**
1. **优先从 URL 中提取省份**：
   - 检查 URL 是否包含省份拼音或缩写（如 beijing.gov.cn → 北京市）
   - 检查 URL 是否包含省份中文名
2. **其次从标题中提取**：如果标题包含省份名称
3. **最后从正文中提取**：如果正文明确提到省份
4. **不要因为政策/论文内容本身没有省份就返回 null，一定要先检查 URL 和标题！**

返回 JSON：
{
  "summary": "<=300字的简体中文摘要",
  "keywords": ["关键词1", ...],
  "country": "ISO3或国家名（如 CHN/中国）",
  "province": "中国省级行政区中文名（如 广东省、北京市）"
}
```

**LLM 返回**：
```python
{
    "summary": "摘要文本",
    "keywords": ["关键词1", "关键词2", ...],
    "country": "CHN" 或 "中国" 或 null,
    "province": "北京市" 或 "广东省" 或 null
}
```

#### 2.3 中文验证与翻译兜底
**位置**：第520-527行

```python
# 如果摘要不含中文，调用 LLM 翻译
if not _has_chinese(s.get("summary")):
    s = qwen_fix_to_zh(s)

# 如果关键词不含中文，调用 LLM 翻译
if isinstance(s.get("keywords"), list):
    joined = " ".join([str(x) for x in s["keywords"]])
    if not _has_chinese(joined):
        s = qwen_fix_to_zh(s)
```

---

### 步骤3：地理编码（多级推断策略）

**位置**：`process_row()` 函数（第529-594行）

这是最复杂的部分，采用**多级推断策略**：

#### 3.1 初始化
```python
country_iso3 = row.get("country_iso3")      # 从视图读取（可能为 NULL）
province_code = row.get("province_code")    # 从视图读取（可能为 NULL）
url_for_geo = row.get("url_norm") or row.get("url")
geo_source = None  # 记录地理信息来源
```

#### 3.2 第一优先级：LLM 返回的地理信息
**位置**：第534-552行

```python
if GEO_BY_LLM:  # 默认开启
    llm_country = s.get("country")      # LLM 返回的国家
    llm_province = s.get("province")    # LLM 返回的省份
    
    # 处理省份
    if llm_province:
        _pc = name_to_province_code(str(llm_province))  # 转换为省份代码
        if _pc:
            province_code = _pc
            geo_source = "llm"
    
    # 处理国家
    if llm_country:
        _c3 = name_to_iso3(str(llm_country))  # 转换为 ISO3
        if _c3:
            country_iso3 = _c3
            # 如果判定为非中国，清空省份
            if country_iso3 != "CHN":
                province_code = None
```

#### 3.3 第二优先级：从 URL 推断国家（ccTLD）
**位置**：第554-561行

```python
if not country_iso3:
    c_from_url = infer_country_from_url(url_for_geo)
    # 例如：.cn → CHN, .us → USA, .jp → JPN
    if c_from_url:
        country_iso3 = c_from_url
        geo_source = "url"
```

#### 3.4 第三优先级：省份推断（如果省份存在但国家为空）
**位置**：第562-571行

```python
if not country_iso3 and province_code:
    # 如果 LLM 判定为中国，或 URL 是 .cn，设置国家为 CHN
    llm_cn = str(llm_country_norm or "").strip().lower()
    if llm_cn in ("chn","cn","china","中国","中华人民共和国") or c_from_url == "CHN":
        country_iso3 = "CHN"
```

#### 3.5 第四优先级：Paper 类型的特殊处理 ⭐
**位置**：第575-594行（这是针对 paper 类型的特殊逻辑）

```python
if row.get("type") == "paper" and not province_code:
    # 1. 优先从 URL 推断省份
    inferred_prov = infer_province_from_url(url_for_geo)
    # 例如：beijing.gov.cn → 北京市, zj.gov.cn → 浙江省
    if inferred_prov:
        province_code = inferred_prov
        geo_source = "url_inference"
    
    # 2. 如果 URL 推断失败，从标题推断
    if not province_code:
        title_text = row.get("title") or ""
        inferred_prov = infer_province_from_text(title_text)
        # 例如：标题包含"北京市" → 北京市
        if inferred_prov:
            province_code = inferred_prov
            geo_source = "title_inference"
    
    # 3. 如果推断出省份，确保国家是中国
    if province_code and not country_iso3:
        country_iso3 = "CHN"
```

**URL 推断逻辑**（`infer_province_from_url()` 函数，第348-371行）：
1. 从 URL 中提取主机名
2. 检查是否包含省份拼音或缩写（如 `beijing`, `zj`, `gd`）
3. 检查是否为 `.gov.cn` 域名（如 `zj.gov.cn` → 浙江省）
4. 通过 `PROV_PINYIN_MAP` 映射到省份中文名
5. 通过 `name_to_province_code()` 转换为省份代码

**标题推断逻辑**（`infer_province_from_text()` 函数，第337-346行）：
1. 使用正则表达式匹配省份中文名
2. 通过 `name_to_province_code()` 转换为省份代码

---

### 步骤4：数据组装

**位置**：`process_row()` 函数（第596-621行）

将处理后的数据组装成最终记录：

```python
rec = {
    # 基础字段
    "type": row.get("type"),                    # "paper"
    "title": row.get("title"),
    "url": url_for_geo,
    "source": row.get("source"),
    "published_at": row.get("published_at"),
    
    # 地理信息
    "country_iso3": country_iso3,              # 国家 ISO3 代码（如 "CHN"）
    "province_code": province_code,            # 省份代码（如 "110000" 北京）
    
    # LLM 生成的内容
    "summary": s.get("summary"),               # 摘要
    "keywords": s.get("keywords"),             # 关键词数组
    
    # 元数据
    "row_hash": row.get("row_hash"),           # 行哈希（用于去重）
    "src_table": row.get("src_table"),         # "00_papers"
    "src_id": str(row.get("src_id")),          # 源表 ID
    
    # 扩展信息（存储在 payload JSONB 字段）
    "payload": {
        "lang_hint": row.get("lang_hint"),
        "geo_source": geo_source,              # 地理信息来源："llm"/"url"/"url_inference"/"title_inference"
        "llm_country": s.get("country"),       # LLM 原始返回的国家
        "llm_province": s.get("province"),     # LLM 原始返回的省份
        "summary_preview": _summary_preview,   # 摘要预览
        "keywords": s.get("keywords"),
    }
}
```

---

### 步骤5：写入 fact_events 表

**位置**：`route_and_insert()` 函数（第623-631行）

```python
# 使用 upsert，基于 url 唯一键
sb.table(FACT_TABLE).upsert(rec, on_conflict="url").execute()
# FACT_TABLE = "fact_events"
```

**特点**：
- 使用 `upsert` 操作，如果 URL 已存在则更新，不存在则插入
- 基于 `url` 字段的唯一约束
- 这样可以重新处理数据时更新地理编码信息

---

## Paper 类型的特殊处理要点

### 1. 地理编码的优先级

对于 paper 类型，地理编码的优先级是：

1. **LLM 返回的地理信息**（如果 LLM 能从 URL/标题/正文中提取）
2. **URL 推断**（针对 paper 类型的特殊逻辑）
3. **标题推断**（针对 paper 类型的特殊逻辑）
4. **URL ccTLD 推断**（国家级别）

### 2. 为什么需要特殊处理？

- **政策/论文内容通常是全国性的**，正文中很少包含具体省份
- **但来源 URL 通常包含省份信息**（如 `beijing.gov.cn`, `zj.gov.cn`）
- **标题也可能包含省份**（如"北京市关于...的通知"）

因此，需要主动从 URL 和标题中提取省份信息。

### 3. 处理流程总结

```
Paper 数据
    ↓
读取视图数据（type="paper", src_table="00_papers"）
    ↓
调用 LLM（传入 title, content, url）
    ↓
LLM 返回：summary, keywords, country, province
    ↓
地理编码判断：
    ├─ LLM 有省份 → 使用 LLM 的省份
    ├─ LLM 无省份 → 从 URL 推断
    ├─ URL 无省份 → 从标题推断
    └─ 都无 → province_code = NULL
    ↓
组装数据（包含地理信息、摘要、关键词）
    ↓
写入 fact_events 表（upsert，基于 url）
```

---

## 关键函数说明

### `name_to_province_code(name)`
- **作用**：将省份中文名转换为省份代码
- **示例**：`"北京市"` → `"110000"`
- **位置**：第262-270行

### `infer_province_from_url(url)`
- **作用**：从 URL 推断省份
- **示例**：`"https://beijing.gov.cn/..."` → `"110000"`
- **位置**：第348-371行

### `infer_province_from_text(text)`
- **作用**：从文本中提取省份名称
- **示例**：`"北京市关于..."` → `"110000"`
- **位置**：第337-346行

### `name_to_iso3(country_name)`
- **作用**：将国家名转换为 ISO3 代码
- **示例**：`"中国"` → `"CHN"`
- **位置**：第272-275行

---

## 数据流向图

```
00_papers 表（原始数据）
    ↓
v_events_geocoded 视图（统一视图）
    ↓
databoard-map-process.py
    ├─ 读取：type="paper"
    ├─ LLM 处理：提取摘要、关键词、地理信息
    ├─ 地理编码：多级推断（LLM → URL → 标题）
    └─ 写入：fact_events 表
         ├─ type = "paper"
         ├─ src_table = "00_papers"
         ├─ country_iso3 = "CHN" 或 NULL
         ├─ province_code = "110000" 或 NULL
         ├─ summary = LLM 生成的摘要
         └─ keywords = LLM 生成的关键词
```

---

## 后端API查询时的映射

**位置**：`backend_api/databoard_map_bp.py`

```python
# 前端请求：type=policies
# 后端映射：
TYPE_TO_SRC_TABLE = {
    "policies": "00_papers",  # policies → 00_papers
}

# 查询时使用 src_table 过滤，而不是 type 字段
ef[SRC_TABLE_FIELD] = "00_papers"  # src_table = '00_papers'
```

所以后端查询时，使用的是 `src_table = '00_papers'` 来过滤政策数据。

