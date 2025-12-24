# Dashboard 模块 API 接口文档

## 概述

本文档描述了致真信息大脑控制台（Dashboard）模块所需的所有API接口。Dashboard模块包含四个主要功能组件：每日AI简报、核心数据指标卡、今日全球要闻和客户与线索跟踪。

## 基础信息

- **基础URL**: `/api/dashboard`
- **认证方式**: Bearer Token
- **数据格式**: JSON
- **字符编码**: UTF-8

---

## 1. 每日AI简报接口

### 1.1 获取每日简报

**接口地址**: `GET /api/dashboard/daily-report`

**请求参数**:
```json
{
  "date": "2023-11-15",           // 可选，查询日期，默认为今天
  "view": "management"            // 可选，视角类型：management/market/sales/product
}
```

**响应数据**:
```json
{
  "code": 200,
  "message": "success",
  "data": {
    "date": "2023-11-15",
    "view": "management",
    "highlights": [
      {
        "id": 1,
        "category": "政策动向",
        "content": "国家发布新一代人工智能创新发展指导意见，明确支持企业建设行业大模型。建议立即组织跨部门会议评估该政策对公司业务的影响，制定响应策略。",
        "priority": "high",
        "priorityText": "高",
        "createdAt": "2023-11-15T09:00:00Z"
      },
      {
        "id": 2,
        "category": "竞品动态", 
        "content": "竞品A公司宣布完成新一轮融资，计划加大AI研发投入，重点布局智能决策支持系统。建议密切关注其产品迭代计划，调整我们的竞品策略。",
        "priority": "medium",
        "priorityText": "中",
        "createdAt": "2023-11-15T08:30:00Z"
      },
      {
        "id": 3,
        "category": "销售机会",
        "content": "某省交通厅发布智能交通系统升级项目招标公告，预算约1200万元，需求与我司产品高度匹配。建议立即组建专项投标小组，准备相关材料。",
        "priority": "high", 
        "priorityText": "高",
        "createdAt": "2023-11-15T10:15:00Z"
      }
    ]
  }
}
```

### 1.2 更新简报视角

**接口地址**: `PUT /api/dashboard/daily-report/view`

**请求参数**:
```json
{
  "view": "management"  // 视角类型：management/market/sales/product
}
```

**响应数据**:
```json
{
  "code": 200,
  "message": "success",
  "data": {
    "view": "management",
    "updatedAt": "2023-11-15T10:30:00Z"
  }
}
```

---

## 2. 核心数据指标卡接口

### 2.1 获取数据指标

**接口地址**: `GET /api/dashboard/data-cards`

**请求参数**:
```json
{
  "date": "2023-11-15",           // 可选，查询日期，默认为今天
  "period": "day"                 // 可选，时间周期：day/week/month
}
```

**响应数据**:
```json
{
  "code": 200,
  "message": "success", 
  "data": {
    "date": "2023-11-15",
    "period": "day",
    "cards": [
      {
        "id": 1,
        "label": "今日信息增量",
        "value": "+128 条",
        "trend": {
          "type": "success",
          "text": "较昨日 ↑ 15%",
          "icon": "el-icon-top"
        },
        "progress": 75,
        "icon": {
          "class": "form",
          "color": "blue"
        }
      },
      {
        "id": 2,
        "label": "客户线索",
        "value": "24 条",
        "trend": {
          "type": "info",
          "text": "待跟进"
        },
        "progress": 60,
        "icon": {
          "class": "user",
          "color": "green"
        }
      },
      {
        "id": 3,
        "label": "最新论文",
        "value": "12篇",
        "trend": {
          "type": "warning",
          "text": "较上月 ↑ 8.5%",
          "icon": "el-icon-top"
        },
        "progress": 45,
        "icon": {
          "class": "table",
          "color": "amber"
        }
      },
      {
        "id": 4,
        "label": "预警监控数",
        "value": "5 个",
        "trend": {
          "type": "danger",
          "text": "竞品重大动态"
        },
        "progress": 30,
        "icon": {
          "class": "eye",
          "color": "red"
        }
      }
    ]
  }
}
```

### 2.2 获取指标趋势数据

**接口地址**: `GET /api/dashboard/data-cards/trend`

**请求参数**:
```json
{
  "cardId": 1,                    // 指标卡ID
  "period": "week",               // 时间周期：day/week/month/quarter
  "startDate": "2023-11-08",     // 开始日期
  "endDate": "2023-11-15"        // 结束日期
}
```

**响应数据**:
```json
{
  "code": 200,
  "message": "success",
  "data": {
    "cardId": 1,
    "period": "week",
    "trendData": [
      {
        "date": "2023-11-08",
        "value": 95,
        "change": 5.2
      },
      {
        "date": "2023-11-09", 
        "value": 108,
        "change": 13.7
      },
      {
        "date": "2023-11-10",
        "value": 102,
        "change": -5.6
      },
      {
        "date": "2023-11-11",
        "value": 115,
        "change": 12.7
      },
      {
        "date": "2023-11-12",
        "value": 98,
        "change": -14.8
      },
      {
        "date": "2023-11-13",
        "value": 120,
        "change": 22.4
      },
      {
        "date": "2023-11-14",
        "value": 128,
        "change": 6.7
      }
    ]
  }
}
```

---

## 3. 今日全球要闻接口

### 3.1 获取要闻列表

**接口地址**: `GET /api/dashboard/news`

**请求参数**:
```json
{
  "page": 1,                      // 页码，默认为1
  "pageSize": 20,                 // 每页数量，默认为20
  "category": "all",              // 分类：all/政策新闻/行业新闻/竞品新闻/商机
  "keyword": "",                  // 搜索关键词
  "date": "2023-11-15"           // 查询日期，默认为今天
}
```

**响应数据**:
```json
{
  "code": 200,
  "message": "success",
  "data": {
    "total": 25,
    "page": 1,
    "pageSize": 20,
    "news": [
      {
        "id": 1,
        "category": "政策新闻",
        "title": "国家发布新一代人工智能创新发展指导意见，明确支持企业建设行业大模型",
        "source": "政策新闻",
        "time": "09:32",
        "publishTime": "2023-11-15",
        "readTime": "5分钟",
        "link": "http://www.gov.cn/zhengce/content/2023-11/15/content_5823121.htm",
        "summary": "国家发改委与科技部联合发布《新一代人工智能创新发展指导意见》，明确提出支持具备条件的企业建设行业大模型，推动AI技术与实体经济深度融合。",
        "actionSuggestion": "建议：立即组织战略部、产品部和技术部召开专题会议，评估该政策对公司业务的影响，制定行业大模型建设方案。",
        "relatedNews": [
          {
            "id": 1,
            "title": "国务院关于加快数字经济发展的若干意见解读",
            "source": "政策解读",
            "time": "3天前"
          }
        ],
        "createdAt": "2023-11-15T09:32:00Z"
      }
    ]
  }
}
```

### 3.2 获取要闻详情

**接口地址**: `GET /api/dashboard/news/{id}`

**请求参数**:
- `id`: 要闻ID（路径参数）

**响应数据**:
```json
{
  "code": 200,
  "message": "success",
  "data": {
    "id": 1,
    "category": "政策新闻",
    "title": "国家发布新一代人工智能创新发展指导意见，明确支持企业建设行业大模型",
    "source": "政策新闻",
    "time": "09:32",
    "publishTime": "2023-11-15",
    "readTime": "5分钟",
    "link": "http://www.gov.cn/zhengce/content/2023-11/15/content_5823121.htm",
    "content": "详细新闻内容...",
    "summary": "国家发改委与科技部联合发布《新一代人工智能创新发展指导意见》...",
    "actionSuggestion": "建议：立即组织战略部、产品部和技术部召开专题会议...",
    "relatedNews": [
      {
        "id": 1,
        "title": "国务院关于加快数字经济发展的若干意见解读",
        "source": "政策解读",
        "time": "3天前"
      }
    ],
    "tags": ["AI", "政策", "大模型"],
    "createdAt": "2023-11-15T09:32:00Z",
    "updatedAt": "2023-11-15T09:32:00Z"
  }
}
```

### 3.3 标记要闻为已读

**接口地址**: `POST /api/dashboard/news/{id}/read`

**请求参数**:
- `id`: 要闻ID（路径参数）

**响应数据**:
```json
{
  "code": 200,
  "message": "success",
  "data": {
    "id": 1,
    "readAt": "2023-11-15T10:30:00Z"
  }
}
```

### 3.4 采纳AI行动建议

**接口地址**: `POST /api/dashboard/news/{id}/adopt-suggestion`

**请求参数**:
```json
{
  "id": 1,                        // 要闻ID（路径参数）
  "action": "adopt",              // 操作类型：adopt/edit
  "note": "已安排相关部门跟进"    // 备注信息
}
```

**响应数据**:
```json
{
  "code": 200,
  "message": "success",
  "data": {
    "id": 1,
    "action": "adopt",
    "note": "已安排相关部门跟进",
    "adoptedAt": "2023-11-15T10:35:00Z"
  }
}
```

---

## 4. 客户与线索跟踪接口

### 4.1 获取线索列表

**接口地址**: `GET /api/dashboard/leads`

**请求参数**:
```json
{
  "status": "all",                // 线索状态：all/new/assigned/following/converted
  "period": "week",               // 时间周期：week/month/quarter
  "page": 1,                      // 页码
  "pageSize": 20,                 // 每页数量
  "channel": "",                  // 渠道筛选
  "ownerId": ""                   // 负责人ID
}
```

**响应数据**:
```json
{
  "code": 200,
  "message": "success",
  "data": {
    "total": 50,
    "page": 1,
    "pageSize": 20,
    "leads": [
      {
        "id": 1,
        "channel": "招标网",
        "title": "某省交通厅智能交通系统升级项目",
        "description": "需求：智能交通管理平台升级，需要AI数据分析和决策支持功能",
        "status": "new",
        "priority": "high",
        "owner": {
          "id": 1,
          "name": "王经理",
          "avatar": "https://example.com/avatar1.png"
        },
        "createdAt": "2023-11-15T09:00:00Z",
        "updatedAt": "2023-11-15T09:00:00Z"
      }
    ]
  }
}
```

### 4.2 获取线索看板数据

**接口地址**: `GET /api/dashboard/leads/board`

**请求参数**:
```json
{
  "period": "week"                // 时间周期：week/month/quarter
}
```

**响应数据**:
```json
{
  "code": 200,
  "message": "success",
  "data": {
    "period": "week",
    "columns": [
      {
        "status": "new",
        "title": "新获取",
        "count": 8,
        "leads": [
          {
            "id": 1,
            "channel": "招标网",
            "title": "某省交通厅智能交通系统升级项目",
            "description": "需求：智能交通管理平台升级，需要AI数据分析和决策支持功能",
            "owner": {
              "id": 1,
              "name": "王经理",
              "avatar": "https://example.com/avatar1.png"
            },
            "createdAt": "2023-11-15T09:00:00Z"
          }
        ]
      },
      {
        "status": "assigned",
        "title": "已分配",
        "count": 6,
        "leads": []
      },
      {
        "status": "following",
        "title": "跟进中",
        "count": 4,
        "leads": []
      }
    ]
  }
}
```

### 4.3 获取线索趋势数据

**接口地址**: `GET /api/dashboard/leads/trend`

**请求参数**:
```json
{
  "period": "week",               // 时间周期：week/month/quarter
  "type": "new"                   // 数据类型：new/converted
}
```

**响应数据**:
```json
{
  "code": 200,
  "message": "success",
  "data": {
    "period": "week",
    "type": "new",
    "trendData": {
      "labels": ["周一", "周二", "周三", "周四", "周五", "周六", "周日"],
      "newLeads": [12, 19, 15, 28, 22, 18, 25],
      "convertedLeads": [5, 8, 6, 12, 9, 7, 10]
    }
  }
}
```

### 4.4 更新线索状态

**接口地址**: `PUT /api/dashboard/leads/{id}/status`

**请求参数**:
```json
{
  "id": 1,                        // 线索ID（路径参数）
  "status": "assigned",           // 新状态：new/assigned/following/converted
  "ownerId": 2,                   // 负责人ID（可选）
  "note": "已分配给销售经理"      // 备注信息（可选）
}
```

**响应数据**:
```json
{
  "code": 200,
  "message": "success",
  "data": {
    "id": 1,
    "status": "assigned",
    "ownerId": 2,
    "note": "已分配给销售经理",
    "updatedAt": "2023-11-15T10:30:00Z"
  }
}
```

### 4.5 获取AI洞察

**接口地址**: `GET /api/dashboard/leads/{id}/insights`

**请求参数**:
- `id`: 线索ID（路径参数）

**响应数据**:
```json
{
  "code": 200,
  "message": "success",
  "data": {
    "id": 1,
    "insights": {
      "opportunityScore": 85,      // 机会评分（0-100）
      "riskFactors": [             // 风险因素
        "预算可能不足",
        "决策周期较长"
      ],
      "suggestions": [             // AI建议
        "重点关注技术方案展示",
        "准备详细ROI分析报告"
      ],
      "competitors": [             // 潜在竞争对手
        "公司A",
        "公司B"
      ],
      "nextSteps": [               // 下一步行动
        "安排技术演示",
        "准备项目提案"
      ]
    },
    "generatedAt": "2023-11-15T10:30:00Z"
  }
}
```

---

## 5. 通用接口

### 5.1 获取用户偏好设置

**接口地址**: `GET /api/dashboard/preferences`

**响应数据**:
```json
{
  "code": 200,
  "message": "success",
  "data": {
    "dailyReportView": "management",
    "dataCardsPeriod": "day",
    "newsCategory": "all",
    "leadsPeriod": "week",
    "notifications": {
      "email": true,
      "browser": true,
      "mobile": false
    }
  }
}
```

### 5.2 更新用户偏好设置

**接口地址**: `PUT /api/dashboard/preferences`

**请求参数**:
```json
{
  "dailyReportView": "management",
  "dataCardsPeriod": "day",
  "newsCategory": "all",
  "leadsPeriod": "week",
  "notifications": {
    "email": true,
    "browser": true,
    "mobile": false
  }
}
```

**响应数据**:
```json
{
  "code": 200,
  "message": "success",
  "data": {
    "updatedAt": "2023-11-15T10:30:00Z"
  }
}
```

---

## 错误码说明

| 错误码 | 说明 |
|--------|------|
| 200 | 成功 |
| 400 | 请求参数错误 |
| 401 | 未授权，需要登录 |
| 403 | 权限不足 |
| 404 | 资源不存在 |
| 500 | 服务器内部错误 |

## 数据字典

### 线索状态 (Lead Status)
- `new`: 新获取
- `assigned`: 已分配
- `following`: 跟进中
- `converted`: 已转化

### 线索渠道 (Lead Channel)
- `招标网`: 招标网站
- `官网`: 公司官网
- `论文库`: 学术论文库
- `展会`: 行业展会
- `合作伙伴`: 合作伙伴推荐

### 优先级 (Priority)
- `high`: 高
- `medium`: 中
- `low`: 低

### 视角类型 (View Type)
- `management`: 管理层视角
- `market`: 市场部视角
- `sales`: 销售部视角
- `product`: 产品部视角

---

## 更新日志

| 版本 | 日期 | 更新内容 |
|------|------|----------|
| 1.0.0 | 2023-11-15 | 初始版本，包含所有基础接口 |
