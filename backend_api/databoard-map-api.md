# 数据看板地图模块 API 文档

## 概述

地图模块API提供中国地图和世界地图数据可视化所需的数据接口，支持省/市/区三级地图展示（中国地图）以及世界地图展示，以及各类数据统计（线索、招标、政策、新闻等）。

> **重要说明**: 后端只需返回统计数据（`statistics` 和 `summary`），**不需要返回地图边界数据（`mapData`）**。前端会使用本地 `/china-map.json` 文件作为中国地图边界数据，使用本地 `world.js` 文件作为世界地图边界数据，以减少API响应大小并提升性能。

## 基础信息

- **Base URL**: `http://127.0.0.1:8000/api/databoard/map`
- **认证方式**: 在请求头中携带 `X-Token`
- **数据格式**: JSON

## 通用参数说明

### 数据类型（type）
- `all`: 全部数据（默认）
- `leads`: 线索数据
- `tenders`: 招标数据
- `policies`: 政策数据
- `news`: 新闻数据

### 地图级别（level）
- `province`: 省级地图（默认，中国地图）
- `city`: 市级地图（中国地图）
- `district`: 区县级地图（中国地图）
- `world`: 世界地图（国家级别）

### 时间范围（timeRange）
- `day`: 当天（默认）
- `week`: 近一周
- `month`: 近一月
- `quarter`: 近一季度
- `year`: 近一年

### 区域代码格式
- **中国地图**：
  - 省级：6位数字，如 `110000`（北京市）
  - 市级：6位数字，如 `110100`（北京市市辖区）
  - 区县级：6位数字，如 `110101`（北京市东城区）
- **世界地图**：
  - 使用国家英文名称作为标识，如 `China`（中国）、`United States`（美国）等
  - 国家名称需与 ECharts 世界地图数据中的 `properties.name` 字段保持一致

## API 接口

### 1. 获取地图数据

获取指定级别的地图数据和统计数据。

**接口地址**: `/api/databoard/map/data`

**请求方式**: `GET`

**请求参数**:

| 参数名 | 类型 | 必填 | 说明 | 示例 |
|--------|------|------|------|------|
| level | string | 否 | 地图级别，默认province。可选值：province/city/district/world | province |
| date | string | 否 | 查询日期，格式YYYY-MM-DD，默认当前日期 | 2024-01-15 |
| type | string | 否 | 数据类型，默认all | all |
| provinceCode | string | 条件必填 | 省份代码（level为city或district时必填） | 110000 |
| cityCode | string | 条件必填 | 城市代码（level为district时必填） | 110100 |
| timeRange | string | 否 | 时间范围，默认day | day |

**请求示例**:
```bash
# 中国地图 - 省级
GET /api/databoard/map/data?level=province&date=2024-01-15&type=all&timeRange=month

# 世界地图
GET /api/databoard/map/data?level=world&date=2024-01-15&type=all&timeRange=month
```

**响应数据结构**:

**中国地图响应示例**:
```json
{
  "code": 20000,
  "message": "success",
  "data": {
    "statistics": [
      {
        "name": "北京市",
        "code": "110000",
        "value": 177,
        "leads": 45,
        "tenders": 32,
        "policies": 28,
        "news": 72,
        "trend": 12.5
      },
      {
        "name": "河南省",
        "code": "410000",
        "value": 137,
        "leads": 35,
        "tenders": 28,
        "policies": 22,
        "news": 52,
        "trend": 8.3
      }
    ],
    "summary": {
      "total": 3500,
      "max": 200,
      "min": 0,
      "avg": 105.5,
      "count": 34
    }
  }
}
```

**世界地图响应示例**:
```json
{
  "code": 20000,
  "message": "success",
  "data": {
    "statistics": [
      {
        "name": "China",
        "code": "CN",
        "value": 250,
        "leads": 60,
        "tenders": 45,
        "policies": 40,
        "news": 105,
        "trend": 12.5
      },
      {
        "name": "United States",
        "code": "US",
        "value": 220,
        "leads": 55,
        "tenders": 40,
        "policies": 35,
        "news": 90,
        "trend": 8.3
      }
    ],
    "summary": {
      "total": 5000,
      "max": 300,
      "min": 0,
      "avg": 125.5,
      "count": 150
    }
  }
}
```

**响应字段说明**:

> **注意**: `mapData` 字段不需要返回。前端会使用本地 `/china-map.json` 文件作为中国地图边界数据，使用本地 `world.js` 文件作为世界地图边界数据。GeoJSON格式的地图数据体积较大（通常500KB+），且相对固定，不需要每次请求都传输。

- `statistics`: 统计数据数组（必填）
  - `name`: 区域名称
    - **中国地图**：省份/城市名称（中文），如 `北京市`、`河南省`
    - **世界地图**：国家名称（英文），如 `China`、`United States`，需与 ECharts 世界地图数据中的 `properties.name` 字段保持一致
  - `code`: 区域代码
    - **中国地图**：6位数字代码，如 `110000`（北京市）
    - **世界地图**：国家代码（ISO 3166-1 alpha-2），如 `CN`（中国）、`US`（美国），可选
  - `value`: 总数值（根据type参数返回对应类型的数据）
  - `leads`: 线索数量
  - `tenders`: 招标数量
  - `policies`: 政策数量
  - `news`: 新闻数量
  - `trend`: 趋势变化百分比（相比上一周期）
- `summary`: 数据汇总
  - `total`: 总数
  - `max`: 最大值
  - `min`: 最小值
  - `avg`: 平均值
  - `count`: 区域数量

---

### 2. 获取区域详情数据

获取指定区域的详细统计数据。

**接口地址**: `/api/databoard/map/region`

**请求方式**: `GET`

**请求参数**:

| 参数名 | 类型 | 必填 | 说明 | 示例 |
|--------|------|------|------|------|
| region | string | 是 | 区域代码 | 110000 |
| date | string | 否 | 查询日期，格式YYYY-MM-DD，默认当前日期 | 2024-01-15 |
| type | string | 否 | 数据类型，默认all | all |
| timeRange | string | 否 | 时间范围，默认day | day |

**请求示例**:
```bash
GET /api/databoard/map/region?region=110000&date=2024-01-15&type=all&timeRange=month
```

**响应数据结构**:
```json
{
  "code": 20000,
  "message": "success",
  "data": {
    "region": {
      "name": "北京市",
      "code": "110000",
      "level": "province",
      "parentCode": "100000"
    },
    "statistics": {
      "total": 177,
      "leads": 45,
      "tenders": 32,
      "policies": 28,
      "news": 72,
      "trend": 12.5
    },
    "subRegions": [
      {
        "name": "东城区",
        "code": "110101",
        "value": 25,
        "leads": 8,
        "tenders": 5,
        "policies": 4,
        "news": 8
      }
    ],
    "topItems": {
      "leads": [
        {
          "title": "某科学仪器采购需求",
          "source": "政府采购网",
          "date": "2024-01-10"
        }
      ],
      "tenders": [
        {
          "title": "某高校实验室设备招标",
          "source": "招标网",
          "date": "2024-01-12"
        }
      ]
    }
  }
}
```

**响应字段说明**:

- `region`: 区域基本信息
- `statistics`: 统计数据
- `subRegions`: 子区域数据（如果是省级，返回市级数据；如果是市级，返回区县数据）
- `topItems`: 热门项目列表
  - `leads`: 热门线索
  - `tenders`: 热门招标

---

### 3. 获取地图统计数据汇总

获取全国或指定区域的统计数据汇总。

**接口地址**: `/api/databoard/map/summary`

**请求方式**: `GET`

**请求参数**:

| 参数名 | 类型 | 必填 | 说明 | 示例 |
|--------|------|------|------|------|
| date | string | 否 | 查询日期，格式YYYY-MM-DD，默认当前日期 | 2024-01-15 |
| type | string | 否 | 数据类型，默认all | all |
| timeRange | string | 否 | 时间范围，默认day | day |

**请求示例**:
```bash
GET /api/databoard/map/summary?date=2024-01-15&type=all&timeRange=month
```

**响应数据结构**:
```json
{
  "code": 20000,
  "message": "success",
  "data": {
    "total": 3500,
    "max": 200,
    "min": 0,
    "avg": 105.5,
    "count": 34,
    "distribution": {
      "leads": {
        "total": 1200,
        "percentage": 34.3
      },
      "tenders": {
        "total": 980,
        "percentage": 28.0
      },
      "policies": {
        "total": 750,
        "percentage": 21.4
      },
      "news": {
        "total": 570,
        "percentage": 16.3
      }
    },
    "topRegions": [
      {
        "name": "北京市",
        "code": "110000",
        "value": 177,
        "rank": 1
      },
      {
        "name": "河南省",
        "code": "410000",
        "value": 137,
        "rank": 2
      }
    ]
  }
}
```

**响应字段说明**:

- `total`: 总数值
- `max`: 最大值
- `min`: 最小值
- `avg`: 平均值
- `count`: 区域数量
- `distribution`: 数据分布（按类型）
- `topRegions`: 排名前N的区域

---

### 4. 获取区域趋势数据

获取指定区域的趋势数据（时间序列）。

**接口地址**: `/api/databoard/map/trend`

**请求方式**: `GET`

**请求参数**:

| 参数名 | 类型 | 必填 | 说明 | 示例 |
|--------|------|------|------|------|
| region | string | 是 | 区域代码 | 110000 |
| type | string | 否 | 数据类型，默认all | all |
| period | string | 否 | 时间周期，默认month | month |

**请求示例**:
```bash
GET /api/databoard/map/trend?region=110000&type=all&period=month
```

**响应数据结构**:
```json
{
  "code": 20000,
  "message": "success",
  "data": {
    "region": {
      "name": "北京市",
      "code": "110000"
    },
    "period": "month",
    "trend": [
      {
        "date": "2024-01-01",
        "value": 165,
        "leads": 42,
        "tenders": 30,
        "policies": 26,
        "news": 67
      },
      {
        "date": "2024-01-08",
        "value": 172,
        "leads": 44,
        "tenders": 31,
        "policies": 27,
        "news": 70
      },
      {
        "date": "2024-01-15",
        "value": 177,
        "leads": 45,
        "tenders": 32,
        "policies": 28,
        "news": 72
      }
    ],
    "summary": {
      "change": 12.5,
      "changeType": "increase",
      "avgValue": 171.3
    }
  }
}
```

**响应字段说明**:

- `region`: 区域信息
- `period`: 时间周期
- `trend`: 趋势数据数组（按日期排序）
- `summary`: 趋势汇总
  - `change`: 变化百分比
  - `changeType`: 变化类型（increase/decrease）
  - `avgValue`: 平均值

---

## 错误码说明

| 错误码 | 说明 |
|--------|------|
| 20000 | 成功 |
| 40001 | 参数错误 |
| 40002 | 区域代码不存在 |
| 40003 | 日期格式错误 |
| 50001 | 服务器内部错误 |
| 50008 | Token无效 |
| 50012 | 其他客户端已登录 |
| 50014 | Token已过期 |

## 错误响应示例

```json
{
  "code": 40001,
  "message": "参数错误：level参数无效",
  "data": null
}
```

## 使用示例

### JavaScript 示例

```javascript
import { getMapData, getRegionDetail } from '@/api/databoard/map'

// 获取省级地图数据（中国地图）
const fetchProvinceMap = async () => {
  try {
    const response = await getMapData({
      level: 'province',
      date: '2024-01-15',
      type: 'all',
      timeRange: 'month'
    })
    
    const { statistics, summary } = response.data
    
    // 统计数据（前端会使用本地 /china-map.json 作为地图边界）
    console.log('统计数据:', statistics)
    console.log('汇总数据:', summary)
    
    // 注意：mapData 不需要从API获取，前端会使用本地文件
  } catch (error) {
    console.error('获取地图数据失败:', error)
  }
}

// 获取世界地图数据
const fetchWorldMap = async () => {
  try {
    const response = await getMapData({
      level: 'world',
      date: '2024-01-15',
      type: 'all',
      timeRange: 'month'
    })
    
    const { statistics, summary } = response.data
    
    // 统计数据（前端会使用本地 world.js 作为地图边界）
    // 注意：世界地图中的国家名称需使用英文，如 "China", "United States" 等
    console.log('世界地图统计数据:', statistics)
    console.log('汇总数据:', summary)
    
    // 注意：mapData 不需要从API获取，前端会使用本地文件
  } catch (error) {
    console.error('获取世界地图数据失败:', error)
  }
}

// 获取区域详情
const fetchRegionDetail = async (regionCode) => {
  try {
    const response = await getRegionDetail({
      region: regionCode,
      date: '2024-01-15',
      type: 'all',
      timeRange: 'month'
    })
    
    const { region, statistics, subRegions } = response.data
    
    console.log('区域信息:', region)
    console.log('统计数据:', statistics)
    console.log('子区域数据:', subRegions)
  } catch (error) {
    console.error('获取区域详情失败:', error)
  }
}
```

## 注意事项

1. **地图数据（mapData）**: 
   - **后端不需要返回 `mapData` 字段**
   - 前端会使用本地 `/china-map.json` 文件作为中国地图边界数据，使用本地 `world.js` 文件作为世界地图边界数据
   - GeoJSON格式的地图数据体积较大（通常500KB+），且相对固定，不需要每次请求都传输
   - 前端已实现容错机制：如果API返回了 `mapData`，会优先使用；否则使用本地文件

2. **日期格式**: 日期参数必须使用 `YYYY-MM-DD` 格式

3. **区域代码**: 
   - **中国地图**：区域代码必须是6位数字字符串
   - **世界地图**：国家名称使用英文，需与 ECharts 世界地图数据中的 `properties.name` 字段保持一致（如 `China`、`United States`）

4. **国家名称格式**: 
   - 世界地图中的国家名称必须使用英文，且与 ECharts 世界地图 GeoJSON 数据中的 `properties.name` 字段完全一致
   - 常见国家名称示例：`China`、`United States`、`India`、`Japan`、`Germany`、`United Kingdom`、`France`、`Brazil`、`Russia`、`Canada` 等

5. **分页**: 统计数据列表如需分页，可在后续版本中添加分页参数

6. **性能优化**: 建议使用 `timeRange` 参数限制查询范围，避免数据量过大

## 更新日志

- **v1.1.0** (2024-01-XX): 新增世界地图支持，支持 `level=world` 参数
- **v1.0.0** (2024-01-15): 初始版本，支持省级地图数据查询

