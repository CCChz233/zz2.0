# 数据看板数据模块 API 文档

- **Base URL**: `http://127.0.0.1:5000/api/databoard/data`
- **认证方式**: 在请求头中携带 `X-Token`
- **数据格式**: JSON

## API 接口

### 1. 获取新闻消息数据

**接口地址**: `/api/databoard/data/getNews`

**请求方式**: `GET`

**请求参数**:

**响应数据结构**:
```json
{
  "code": 200,
  "message": "success",
  "data": {
    "statistics":{
      "policyNews": {
        {
          "xAxisData": ["1月", "2月", "3月", "4月", "5月", "6月", "7月", "8月", "9月", "10月", "11月", "12月"],
          "seriesData": [
            {
              "name": "政策新闻",
              "data": [120, 132, 101, 134, 90, 230, 210, 182, 191, 234, 290, 330],
              "color": "#5470c6"
            }
          ]
        }
      },
      "industryNews": {
        {
          "xAxisData": ["1月", "2月", "3月", "4月", "5月", "6月", "7月", "8月", "9月", "10月", "11月", "12月"],
          "seriesData": [
            {
              "name": "行业新闻",
              "data": [120, 132, 101, 134, 90, 230, 210, 182, 191, 234, 290, 330],
              "color": "green"
            }
          ]
        }
      },
      "competitorTrend": {
        {
          "xAxisData": ["1月", "2月", "3月", "4月", "5月", "6月"],
          "seriesData": [
            {
              "name": "公司A",
              "data": [120, 132, 101, 134, 90, 230],
              "color": "#91cc75"
            },
            {
              "name": "公司B",
              "data": [220, 182, 191, 234, 290, 330],
              "color": "#fac858"
            },
            {
              "name": "公司C",
              "data": [150, 232, 201, 154, 190, 330],
              "color": "#ee6666"
            }
          ]
        }
      },
      "competitorType": [
        {
          "seriesData": [
            {
              "value": 335,
              "name": "产品发布"
            },
            {
              "value": 310,
              "name": "市场活动"
            },
            {
              "value": 234,
              "name": "技术更新"
            },
            {
              "value": 335,
              "name": "合作签约"
            },
            {
              "value": 1548,
              "name": "其他动态"
            }
          ]
        }
      ],
      "researchTrend": {
        {
          "xAxisData": ["1月", "2月", "3月", "4月", "5月", "6月"],
          "seriesData": [
            {
              "name": "人工智能",
              "data": [120, 132, 101, 134, 90, 230],
              "color": "#73c0de"
            },
            {
              "name": "大数据",
              "data": [220, 182, 191, 234, 290, 330],
              "color": "#3ba272"
            },
            {
              "name": "云计算",
              "data": [150, 232, 201, 154, 190, 330],
              "color": "#fc8452"
            }
          ]
        }
      },
      "researchTopic": [
        {
          "seriesData": [
            {
              "value": 335,
              "name": "机器学习"
            },
            {
              "value": 310,
              "name": "深度学习"
            },
            {
              "value": 234,
              "name": "自然语言处理"
            },
            {
              "value": 135,
              "name": "计算机视觉"
            },
            {
              "value": 1548,
              "name": "其他主题"
            }
          ]
        }
      ]
    }
    
  },
}
```