# 前端更新指南：使用新的类型显示名称

## 后端已完成的修改

后端API现在会在返回数据中包含 `typeLabels` 字段，提供更准确的显示名称：

```json
{
  "code": 20000,
  "message": "success",
  "data": {
    "statistics": [...],
    "summary": {...},
    "typeLabels": {
      "leads": "竞品动态",      // 原"线索"
      "tenders": "招标机会",    // 原"招标"
      "policies": "政策文件",   // 原"政策"
      "news": "新闻"
    }
  }
}
```

## 前端需要修改的地方

### 1. 图例（Legend）显示

**原来的代码可能类似：**
```javascript
const legendItems = [
  { label: "线索", color: "green" },
  { label: "招标", color: "blue" },
  { label: "政策", color: "orange" },
  { label: "新闻", color: "red" },
];
```

**修改为：**
```javascript
// 从API响应中获取
const typeLabels = response.data.typeLabels || {
  leads: "线索",
  tenders: "招标",
  policies: "政策",
  news: "新闻"
};

const legendItems = [
  { label: typeLabels.leads, color: "green" },
  { label: typeLabels.tenders, color: "blue" },
  { label: typeLabels.policies, color: "orange" },
  { label: typeLabels.news, color: "red" },
];
```

### 2. 工具提示（Tooltip）显示

**原来的代码可能类似：**
```javascript
tooltip: {
  formatter: function(params) {
    return `
      全部数据: ${params.value}
      线索: ${params.data.leads}
      招标: ${params.data.tenders}
      政策: ${params.data.policies}
      新闻: ${params.data.news}
    `;
  }
}
```

**修改为：**
```javascript
// 在组件中保存 typeLabels
const [typeLabels, setTypeLabels] = useState({
  leads: "线索",
  tenders: "招标",
  policies: "政策",
  news: "新闻"
});

// 在API调用后更新
useEffect(() => {
  fetch('/api/databoard/map/data')
    .then(res => res.json())
    .then(data => {
      if (data.data.typeLabels) {
        setTypeLabels(data.data.typeLabels);
      }
      // ... 其他处理
    });
}, []);

// 在 tooltip 中使用
tooltip: {
  formatter: function(params) {
    return `
      全部数据: ${params.value}
      ${typeLabels.leads}: ${params.data.leads}
      ${typeLabels.tenders}: ${params.data.tenders}
      ${typeLabels.policies}: ${params.data.policies}
      ${typeLabels.news}: ${params.data.news}
    `;
  }
}
```

### 3. 柱状图数据系列

**如果使用 ECharts，修改 series 配置：**

```javascript
// 原来的代码
const series = [
  { name: "线索", data: [...], type: "bar" },
  { name: "招标", data: [...], type: "bar" },
  { name: "政策", data: [...], type: "bar" },
  { name: "新闻", data: [...], type: "bar" },
];

// 修改为
const series = [
  { name: typeLabels.leads, data: leadsData, type: "bar" },
  { name: typeLabels.tenders, data: tendersData, type: "bar" },
  { name: typeLabels.policies, data: policiesData, type: "bar" },
  { name: typeLabels.news, data: newsData, type: "bar" },
];
```

## 完整示例代码

### React/Vue 示例

```javascript
// 组件状态
const [typeLabels, setTypeLabels] = useState({
  leads: "线索",
  tenders: "招标",
  policies: "政策",
  news: "新闻"
});

// API 调用
useEffect(() => {
  const fetchData = async () => {
    try {
      const response = await fetch('/api/databoard/map/data?level=province&type=all');
      const result = await response.json();
      
      if (result.code === 20000 && result.data) {
        // 更新类型标签
        if (result.data.typeLabels) {
          setTypeLabels(result.data.typeLabels);
        }
        
        // 处理统计数据
        const statistics = result.data.statistics || [];
        // ... 其他处理
      }
    } catch (error) {
      console.error('获取数据失败:', error);
    }
  };
  
  fetchData();
}, []);

// 在渲染中使用
<Legend>
  <LegendItem color="green">{typeLabels.leads}</LegendItem>
  <LegendItem color="blue">{typeLabels.tenders}</LegendItem>
  <LegendItem color="orange">{typeLabels.policies}</LegendItem>
  <LegendItem color="red">{typeLabels.news}</LegendItem>
</Legend>
```

## 显示名称对照表

| 原名称 | 新名称 | 说明 |
|--------|--------|------|
| 线索 | **竞品动态** | 更准确反映 `00_competitors_news` 表的内容 |
| 招标 | **招标机会** | 更准确反映 `00_opportunity` 表的内容 |
| 政策 | **政策文件** | 更准确反映 `00_papers` 表的内容 |
| 新闻 | **新闻** | 保持不变 |

## 向后兼容

后端同时返回了旧字段名（`leads`, `tenders`, `policies`, `news`）和新的 `typeLabels` 字段，所以：
- 前端可以逐步迁移
- 如果前端不读取 `typeLabels`，仍然可以使用硬编码的名称（但建议更新）

## 验证

修改后，前端应该显示：
- ✅ "竞品动态" 而不是 "线索"
- ✅ "招标机会" 而不是 "招标"
- ✅ "政策文件" 而不是 "政策"
- ✅ "新闻" 保持不变

## 需要修改的API端点

以下API端点都包含了 `typeLabels` 字段：
- `GET /api/databoard/map/data` - 地图数据
- `GET /api/databoard/map/summary` - 汇总数据
- `GET /api/databoard/map/region` - 区域详情（每个统计项也有 `typeLabels`）

