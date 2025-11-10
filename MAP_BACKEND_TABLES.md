# Map 后端使用的数据库表

## 表结构概览

### 1. 事实表（Fact Table）

#### `fact_events` - 统一事实表
- **用途**：存储所有地图数据（新闻、线索、招标、政策）
- **关键字段**：
  - `published_at` - 发布时间（用于时间过滤）
  - `src_table` - 源表标识（用于区分数据类型）
    - `00_news` - 新闻
    - `00_competitors_news` - 竞品动态（线索）
    - `00_opportunity` - 招标机会
    - `00_papers` - 科技论文（政策）
  - `type` - 类型字段（备用）
  - `province_code` - 省级代码
  - `city_code` - 市级代码
  - `district_code` - 区县级代码
  - `country_iso3` - 国家代码（ISO3）
  - `province_name` - 省级名称（可选）
  - `city_name` - 市级名称（可选）
  - `district_name` - 区县级名称（可选）

### 2. 维表（Dimension Tables）

#### `dim_cn_region` - 中国行政区维表
- **用途**：将行政区代码映射为中文名称
- **关键字段**：
  - `code` - 行政区代码（6位GB/T2260标准）
  - `name_zh` - 中文名称
  - `level` - 层级（province/city/district 或 省/市/区）
- **使用场景**：
  - 省级数据：`level='province'` 或 `level='省'`
  - 市级数据：`level='city'` 或 `level='市'`
  - 区县级数据：`level='district'` 或 `level='区'`

#### `dim_country` - 世界国家维表
- **用途**：将国家代码映射为中文/英文名称
- **关键字段**：
  - `iso3` - 国家代码（ISO3标准，如 CHN, USA）
  - `iso2` - 国家代码（ISO2标准，如 CN, US）
  - `name_en` - 英文名称（用于 ECharts 世界地图）
  - `name_zh` - 中文名称
- **使用场景**：世界地图数据展示

## 数据流程

```
fact_events (事实表)
    ↓ (通过 src_table 过滤)
    ├─ 00_news → 新闻数据
    ├─ 00_competitors_news → 竞品动态
    ├─ 00_opportunity → 招标机会
    └─ 00_papers → 科技论文
    
    ↓ (通过区域代码关联)
    ├─ dim_cn_region → 中国行政区名称
    └─ dim_country → 世界国家名称
```

## API 端点使用的表

### GET /api/databoard/map/data
- **主要表**：`fact_events`
- **关联表**：`dim_cn_region` 或 `dim_country`（用于名称映射）

### GET /api/databoard/map/region
- **主要表**：`fact_events`
- **关联表**：`dim_cn_region` 或 `dim_country`（用于名称映射）

### GET /api/databoard/map/summary
- **主要表**：`fact_events`

### GET /api/databoard/map/trend
- **主要表**：`fact_events`

## 环境变量配置

所有表名和字段名都可通过环境变量覆盖：

- `MAP_FACT_TABLE` - 事实表名（默认：`fact_events`）
- `MAP_FACT_TIME_FIELD` - 时间字段（默认：`published_at`）
- `MAP_SRC_TABLE_FIELD` - 源表字段（默认：`src_table`）
- `MAP_CN_PROVINCE_DIM_TABLE` - 省级维表（默认：`dim_cn_region`）
- `MAP_CN_CITY_DIM_TABLE` - 市级维表（默认：`dim_cn_region`）
- `MAP_CN_DISTRICT_DIM_TABLE` - 区县级维表（默认：`dim_cn_region`）
- `MAP_WORLD_DIM_TABLE` - 世界国家维表（默认：`dim_country`）

## 数据源映射

| 前端类型 | src_table 值 | 显示名称 |
|---------|-------------|---------|
| news | 00_news | 相关新闻 |
| leads | 00_competitors_news | 竞品动态 |
| tenders | 00_opportunity | 招标机会 |
| policies | 00_papers | 科技论文 |

