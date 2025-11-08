# Agent 提示词：更新前端类型显示名称

## 任务背景

后端API已经更新，现在返回的数据中包含 `typeLabels` 字段，提供了更准确的类型显示名称。前端需要更新代码，使用这些新的显示名称，而不是硬编码的旧名称。

## 需要修改的内容

### 1. 旧名称 → 新名称映射

| 旧名称 | 新名称 | 对应字段 |
|--------|--------|----------|
| 线索 | **竞品动态** | `leads` |
| 招标 | **招标机会** | `tenders` |
| 政策 | **政策文件** | `policies` |
| 新闻 | **新闻** | `news` |

### 2. API 返回数据结构

后端API `/api/databoard/map/data` 现在返回：

```json
{
  "code": 20000,
  "message": "success",
  "data": {
    "statistics": [
      {
        "name": "北京",
        "code": "110000",
        "value": 131,
        "leads": 120,
        "tenders": 4,
        "policies": 0,
        "news": 7,
        "typeLabels": {
          "leads": "竞品动态",
          "tenders": "招标机会",
          "policies": "政策文件",
          "news": "新闻"
        }
      }
    ],
    "summary": {...},
    "typeLabels": {
      "leads": "竞品动态",
      "tenders": "招标机会",
      "policies": "政策文件",
      "news": "新闻"
    }
  }
}
```

## 需要修改的前端代码位置

### 1. 图例（Legend）显示
**查找位置**：搜索包含 "线索"、"招标"、"政策"、"新闻" 的字符串
**修改要求**：从 API 响应中读取 `typeLabels`，使用 `typeLabels.leads`、`typeLabels.tenders` 等替代硬编码的字符串

### 2. 工具提示（Tooltip）显示
**查找位置**：地图鼠标悬停时的 tooltip，柱状图的 tooltip
**修改要求**：使用 `typeLabels` 中的名称显示数据标签

### 3. 图表系列名称
**查找位置**：ECharts 或其他图表库的 series 配置中的 `name` 字段
**修改要求**：使用 `typeLabels` 中的名称

### 4. 下拉选择框/筛选器
**查找位置**：类型筛选下拉框的选项文本
**修改要求**：使用 `typeLabels` 中的名称

## 修改步骤

### 步骤1：查找所有硬编码的旧名称

在代码库中搜索以下字符串：
- "线索"
- "招标"
- "政策"
- "新闻"

特别注意以下位置：
- 组件文件（.vue, .tsx, .jsx, .ts, .js）
- 配置文件
- 常量定义文件
- 图表配置（ECharts options）

### 步骤2：添加 typeLabels 状态管理

在调用 `/api/databoard/map/data` 的组件中：

```javascript
// React 示例
const [typeLabels, setTypeLabels] = useState({
  leads: "线索",
  tenders: "招标",
  policies: "政策",
  news: "新闻"
});

// 在 API 调用后更新
useEffect(() => {
  fetch('/api/databoard/map/data?...')
    .then(res => res.json())
    .then(result => {
      if (result.data?.typeLabels) {
        setTypeLabels(result.data.typeLabels);
      }
      // ... 其他处理
    });
}, []);
```

```javascript
// Vue 示例
data() {
  return {
    typeLabels: {
      leads: "线索",
      tenders: "招标",
      policies: "政策",
      news: "新闻"
    }
  }
},
async mounted() {
  const response = await fetch('/api/databoard/map/data?...');
  const result = await response.json();
  if (result.data?.typeLabels) {
    this.typeLabels = result.data.typeLabels;
  }
}
```

### 步骤3：替换硬编码的字符串

**替换规则：**
- `"线索"` → `typeLabels.leads` 或 `${typeLabels.leads}`
- `"招标"` → `typeLabels.tenders` 或 `${typeLabels.tenders}`
- `"政策"` → `typeLabels.policies` 或 `${typeLabels.policies}`
- `"新闻"` → `typeLabels.news` 或 `${typeLabels.news}`

**示例：**

```javascript
// 修改前
const legendItems = [
  { label: "线索", color: "green" },
  { label: "招标", color: "blue" },
  { label: "政策", color: "orange" },
  { label: "新闻", color: "red" },
];

// 修改后
const legendItems = [
  { label: typeLabels.leads, color: "green" },
  { label: typeLabels.tenders, color: "blue" },
  { label: typeLabels.policies, color: "orange" },
  { label: typeLabels.news, color: "red" },
];
```

```javascript
// 修改前（ECharts tooltip）
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

// 修改后
tooltip: {
  formatter: function(params) {
    const labels = params.data.typeLabels || typeLabels;
    return `
      全部数据: ${params.value}
      ${labels.leads}: ${params.data.leads}
      ${labels.tenders}: ${params.data.tenders}
      ${labels.policies}: ${params.data.policies}
      ${labels.news}: ${params.data.news}
    `;
  }
}
```

## 具体修改要求

### 要求1：向后兼容
- 如果 API 没有返回 `typeLabels`，使用默认值（旧名称）
- 确保代码在两种情况下都能正常工作

### 要求2：保持数据字段名不变
- **不要**修改 `leads`、`tenders`、`policies`、`news` 这些字段名
- **只修改**显示给用户看的文本标签

### 要求3：全局统一
- 所有显示类型名称的地方都要使用 `typeLabels`
- 包括：地图、图表、列表、筛选器等

### 要求4：性能优化
- 如果多个组件都需要 `typeLabels`，考虑使用全局状态管理（如 Vuex、Redux）或 Context
- 避免在每次 API 调用时都重新获取

## 验证检查清单

修改完成后，请检查以下内容：

- [ ] 图例显示为：竞品动态、招标机会、政策文件、新闻
- [ ] 地图 tooltip 显示新名称
- [ ] 柱状图 tooltip 显示新名称
- [ ] 图表系列名称使用新名称
- [ ] 筛选器下拉框使用新名称
- [ ] 如果 API 没有返回 typeLabels，使用默认值（向后兼容）
- [ ] 所有硬编码的旧名称都已替换

## 测试建议

1. **正常情况**：API 返回 `typeLabels`，验证显示为新名称
2. **兼容性测试**：模拟 API 不返回 `typeLabels`，验证使用默认值
3. **视觉检查**：检查所有显示类型名称的地方是否都已更新

## 注意事项

1. **不要修改** API 请求参数（如 `type=leads` 等），这些是后端需要的字段名
2. **只修改显示文本**，不修改数据字段名
3. 如果使用 TypeScript，记得更新类型定义

## 可能涉及的 API 端点

以下 API 端点都返回了 `typeLabels`：
- `GET /api/databoard/map/data` - 地图数据（主要使用）
- `GET /api/databoard/map/summary` - 汇总数据
- `GET /api/databoard/map/region` - 区域详情

## 完成标准

修改完成后，前端应该：
- ✅ 所有显示"线索"的地方改为"竞品动态"
- ✅ 所有显示"招标"的地方改为"招标机会"  
- ✅ 所有显示"政策"的地方改为"政策文件"
- ✅ "新闻"保持不变
- ✅ 代码向后兼容，即使 API 没有返回 typeLabels 也能正常工作

