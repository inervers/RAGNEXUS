# RAG Agent API — 设计系统

> AI 知识库工具的设计方向：干净、技术感、信息层级清晰。
> 面向开发者与高级用户，强调可读性与操作效率。

---

## 1. 视觉主题与氛围

- **氛围**：干净、专业、克制。类似 Vercel / Linear 的开发者工具美学
- **色彩策略**：深色导航 + 白底内容区，蓝色系作为功能高亮
- **字体**：系统无衬线字体，保证跨平台一致性和性能
- **情绪板关键词**：clean · technical · efficient · calm

## 2. 色彩系统

| 角色 | 色值 | 用途 |
|------|------|------|
| Primary | `#2563EB` (Blue-600) | 主按钮、链接、关键操作 |
| Primary Hover | `#1D4ED8` (Blue-700) | 按钮悬停态 |
| Primary Light | `#EFF6FF` (Blue-50) | 选中项背景、信息提示 |
| Success | `#059669` (Emerald-600) | 健康状态、成功消息 |
| Error | `#DC2626` (Red-600) | 错误提示、失败状态 |
| Warning | `#D97706` (Amber-600) | 警告信息 |
| Background | `#FAFAFA` | 页面主背景 |
| Surface | `#FFFFFF` | 卡片、面板背景 |
| Surface Secondary | `#F4F4F5` (Zinc-100) | 次要背景、代码块 |
| Border | `#E4E4E7` (Zinc-200) | 分割线、卡片边框 |
| Text Primary | `#18181B` (Zinc-900) | 正文 |
| Text Secondary | `#52525B` (Zinc-600) | 辅助文字、说明 |
| Text Muted | `#A1A1AA` (Zinc-400) | 次要标识、占位符 |

## 3. 排版

| 层级 | 大小 | 字重 | 行高 | 用途 |
|------|------|------|------|------|
| H1 | 24px | 700 | 1.3 | 页面标题 |
| H2 | 20px | 600 | 1.4 | 分节标题 |
| H3 | 16px | 600 | 1.5 | 卡片标题 |
| Body | 14px | 400 | 1.6 | 正文 |
| Small | 12px | 400 | 1.5 | 辅助文字、指标值 |
| Mono | 13px | 400 | 1.5 | 代码、JSON、日志 |

## 4. 间距与布局

- **基准网格**：4px 增量（4 / 8 / 12 / 16 / 20 / 24 / 32 / 48）
- **页面宽度**：最大 1200px，居中
- **卡片间距**：`gap` 16px（内部 padding 20px）
- **分割线**：上下 margin 24px，1px solid `#E4E4E7`
- **按钮间距**：同一行按钮之间 8px

## 5. 阴影与层次

| 层级 | 阴影值 | 用途 |
|------|--------|------|
| Card | `0 1px 3px rgba(0,0,0,0.06), 0 1px 2px rgba(0,0,0,0.04)` | 默认卡片 |
| Elevated | `0 4px 6px rgba(0,0,0,0.05), 0 2px 4px rgba(0,0,0,0.04)` | 悬停/选中 |
| Modal | `0 10px 15px rgba(0,0,0,0.08), 0 4px 6px rgba(0,0,0,0.04)` | 弹窗/下拉 |

## 6. 组件规范

### 按钮
- Primary: Blue-600 填充，白色文字，8px 圆角，hover 变深
- Secondary: 透明底 + 1px 边框，hover 加浅色背景
- 高度：36px（默认），48px（大号）
- 禁用态：opacity 0.5，no pointer

### 卡片
- 白色背景，1px 边框 `#E4E4E7`，8px 圆角，20px 内边距
- 标题区域：底部 12px 分割线分隔
- 嵌套内容：向下缩进 8px

### 输入框
- 高度 36px，8px 圆角，1px 边框
- Focus: Blue-500 边框 + 2px 浅蓝光晕
- 文本域：min-height 120px

### 标签页（Tabs）
- 选中态：底部 2px Blue-500 实线 + 加粗文字
- 未选中：灰色文字，hover 变深灰
- 标签页之间 24px 间距

### 指标卡（Metric）
- 数值：24px bold，Primary 色
- 标签：12px 灰色文字
- 布局：横向等宽排列

## 7. 动效

- 过渡：150ms ease-out（hover / focus 态）
- 展开：200ms ease-in-out（expand / collapse）
- 加载：使用 Streamlit 原生 spinner，不额外自定义
- 尊重 `prefers-reduced-motion`

## 8. 响应式

- 桌面优先（1280px 以上为设计目标）
- 平板（768px）：两栏布局压缩为一栏
- 手机（375px）：侧边栏自动收起
- 表格和信息卡片在窄屏自适应换行

## 9. Do's and Don'ts

| ✅ Do | ❌ Don't |
|------|---------|
| 使用语义色值（Primary / Success / Error） | 在组件中写死 hex 色值 |
| 保持卡片间距和内边距一致 | 用随机 margin 调位置 |
| 用表格/结构展示原始 JSON | 直接贴未格式化的 JSON |
| 标签页之间保持等宽 | 让标签页内容宽度跳跃 |
| 用灰色辅助文字降低干扰 | 用低对比度文字（< 4.5:1） |
| 保持错误/成功状态视觉一致 | 不同模块用不同颜色表示相同状态 |
