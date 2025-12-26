# 智能体初始报告 API 接口文档

## 概述

本文档描述了智能体模块（Agent Module）初始报告所需的API接口。该接口用于获取智能体首次加载时展示的报告内容，包括政策解读、论文报告、市场动态等多个维度的信息。

## 基础信息

- **基础URL**: `/api/agent`
- **认证方式**: Bearer Token
- **数据格式**: JSON
- **字符编码**: UTF-8
- **超时时间**: 5秒

---

## 1. 获取智能体初始报告

### 1.1 接口说明

获取智能体首次加载时展示的初始报告内容，支持多个维度的信息展示。

**接口地址**: `GET /api/agent/initial-report`

**请求参数**:

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| refresh | number | 否 | 传 `1` 强制刷新当日报告 |

**缓存策略**：
- 默认优先返回最近一次生成的报告（生成时间在 `AGENT_REPORT_REFRESH_MINUTES` 分钟内）
- 当 `refresh=1` 时强制触发重新生成（如后端允许生成）
- 缓存表允许同一天多条记录，读取时按 `generated_at` 取最新一条

**响应数据**:
```json
{
  "code": 200,
  "message": "success",
  "data": {
    "generatedAt": "2023-11-15T10:30:00Z",
    "sections": [
      {
        "id": 1,
        "title": "政策解读",
        "icon": "el-icon-document-checked",
        "content": "## 最新政策动态\n\n**国家发改委发布《高端科学仪器国产化实施方案》**\n\n本月初，国家发改委联合科技部发布了重要文件，明确提出：\n\n- 重点支持**原子力显微镜**等关键设备的研发\n- 设立专项资金，总额达**50亿元**\n- 鼓励产学研合作，加快技术转化\n\n### 核心要点\n\n1. **技术突破方向**：聚焦高分辨率成像、纳米级测量等核心技术\n2. **资金支持**：对符合条件的企业提供最高**5000万元**的研发补贴\n3. **市场准入**：简化国产仪器政府采购流程，优先采购国产设备\n\n> 💡 这对国内仪器企业来说是重大利好，预计将带动整个行业的快速发展。",
        "priority": 1,
        "updatedAt": "2023-11-15T09:00:00Z",
        "sources": [
          {
            "title": "国家发改委发布高端科学仪器国产化实施方案",
            "url": "https://example.com/policy",
            "source": "example.com",
            "publishedAt": "2023-11-14"
          }
        ]
      },
      {
        "id": 2,
        "title": "论文报告",
        "icon": "el-icon-reading",
        "content": "## 前沿研究进展\n\n### Nature最新发表\n\n**《新型原子力显微镜技术突破亚纳米分辨率》**\n\n清华大学材料学院团队在Nature上发表重要成果：\n\n- 实现了**0.3纳米**的超高分辨率成像\n- 新型扫描探针技术，速度提升**10倍**\n- 可应用于生物大分子结构分析\n\n### Science相关研究\n\n中科院物理所在原子级材料表征领域取得突破：\n\n```\n关键技术指标：\n- 扫描速度：100 lines/sec\n- 力灵敏度：< 1 pN\n- 工作温度：4K - 400K\n```\n\n**研究意义**：为二维材料、量子材料的研究提供了全新工具。\n\n---\n\n📊 **统计数据**：过去一年，相关领域发表SCI论文**127篇**，同比增长**45%**",
        "priority": 2,
        "updatedAt": "2023-11-15T08:30:00Z"
      },
      {
        "id": 3,
        "title": "市场动态",
        "icon": "el-icon-data-line",
        "content": "## 行业市场概况\n\n### 市场规模\n\n2023年全球科学仪器市场规模达到**650亿美元**，同比增长**8.5%**。其中：\n\n- 中国市场占比**25%**，增速领先全球\n- 高端仪器国产化率从**15%**提升至**23%**\n- 预计2025年市场规模将突破**800亿美元**\n\n### 重点企业动态\n\n| 企业 | 最新动态 | 影响 |\n|------|---------|------|\n| 布鲁克 | 发布新一代AFM | 技术领先 |\n| 蔡司 | 在华建厂 | 本地化加速 |\n| 国仪量子 | 完成D轮融资 | 资本看好 |\n\n> 📈 **趋势分析**：国产替代加速，技术创新成为关键竞争力",
        "priority": 3,
        "updatedAt": "2023-11-15T07:00:00Z"
      }
    ]
  }
}
```

### 1.2 字段说明

**Response 字段说明**:

| 字段路径 | 类型 | 说明 |
|---------|------|------|
| code | number | 响应状态码，200表示成功 |
| message | string | 响应消息 |
| data.generatedAt | string | 报告生成时间（ISO 8601格式） |
| data.sections | array | 报告板块数组 |
| data.sections[].id | number | 板块唯一标识 |
| data.sections[].title | string | 板块标题 |
| data.sections[].icon | string | 图标类名（Element UI图标） |
| data.sections[].content | string | Markdown格式的内容 |
| data.sections[].priority | number | 优先级（1-高，2-中，3-低） |
| data.sections[].updatedAt | string | 更新时间（ISO 8601格式） |
| data.sections[].sources | array | 来源列表 |
| data.sections[].sources[].title | string | 来源标题 |
| data.sections[].sources[].url | string | 来源链接 |
| data.sections[].sources[].source | string | 来源站点/域名 |
| data.sections[].sources[].publishedAt | string | 来源发布时间（YYYY-MM-DD） |

**Icon 可选值**:
- `el-icon-document-checked`: 政策、文档类
- `el-icon-reading`: 论文、研究类
- `el-icon-data-line`: 数据、市场类
- `el-icon-news`: 新闻、动态类
- `el-icon-medal`: 成就、荣誉类
- `el-icon-trophy`: 竞品、竞争类

### 1.3 错误响应

**业务错误**:
```json
{
  "code": 400,
  "message": "参数错误"
}
```

**未授权**:
```json
{
  "code": 401,
  "message": "未授权访问"
}
```

**服务器错误**:
```json
{
  "code": 500,
  "message": "服务器内部错误"
}
```

**超时处理**:
- 请求超时时间设置为5秒
- 超时后自动使用本地测试数据
- 不影响用户体验，确保页面正常显示

---

## 2. 使用说明

### 2.1 请求示例

**cURL**:
```bash
curl -X GET "https://api.example.com/api/agent/initial-report" \
  -H "Authorization: Bearer YOUR_ACCESS_TOKEN" \
  -H "Content-Type: application/json"
```

**JavaScript (Axios)**:
```javascript
import request from '@/utils/request'

export function getAgentInitialReport() {
  return request({
    url: '/agent/initial-report',
    method: 'get',
    timeout: 5000
  })
}
```

### 2.2 Markdown 内容规范

**支持的Markdown语法**:
- 标题：`#` `##` `###`
- 粗体：`**文本**`
- 列表：`-` 或 `1.`
- 引用：`>`
- 代码块：` ``` `
- 分隔线：`---`
- 链接：`[文本](url)`
- 表格：`| 列1 | 列2 |`

**内容建议**:
- 每个板块内容长度建议 500-2000 字
- 使用标题层级清晰组织内容
- 重要信息使用粗体或引用突出
- 数据使用表格或列表展示
- 添加emoji增强可读性

### 2.3 缓存策略

- 报告数据建议缓存 1 小时
- 用户刷新时重新获取
- 缓存失效后自动请求新数据

### 2.4 性能优化

- 内容按需加载，初始只显示前2个板块
- Markdown渲染异步处理
- 长内容支持滚动查看
- 图片延迟加载

---

## 3. 变更历史

| 版本 | 日期 | 变更内容 |
|------|------|---------|
| 1.0.0 | 2023-11-15 | 初始版本 |

---

## 4. 联系方式

如有问题，请联系：
- 负责人：后端开发团队
- 邮箱：backend@example.com
