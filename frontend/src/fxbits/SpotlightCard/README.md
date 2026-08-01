# SpotlightCard

聚光灯卡片（纯 CSS + React，零依赖）。鼠标移动时卡片内出现跟随光斑。

## 依赖

无。

## 使用

```tsx
import SpotlightCard from './SpotlightCard';

<SpotlightCard
  className="custom-spotlight-card"
  spotlightColor="rgba(143, 180, 255, 0.12)"
>
  {/* 内容 */}
</SpotlightCard>
```

## Props

| Prop | 默认 | 说明 |
|------|------|------|
| children | - | 卡片内容 |
| className | '' | 附加类名 |
| spotlightColor | rgba(255,255,255,0.25) | 光斑颜色 |

## RagNexus 适配

- 光斑用亮蓝 `rgba(143, 180, 255, 0.12)`，深色卡片上很克制
- CSS 里默认圆角 1.5rem、背景 #111、边框 #222，需按设计系统覆盖：圆角 4px、背景 `#12151B`、边框 `#222834`
- 适合 hero 状态卡、架构节点这类可交互卡片
- 来源：reactbits.dev (MIT)，保留版权声明
