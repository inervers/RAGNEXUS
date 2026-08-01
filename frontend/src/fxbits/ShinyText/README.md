# ShinyText

光泽扫过文字效果（framer-motion / motion）。高光在文字表面周期性滑过，适合标题、品牌名、关键短语强调。

## 依赖

```bash
npm install motion
```

## 使用

```tsx
import ShinyText from './ShinyText';

<ShinyText
  text="RagNexus"
  speed={2}
  delay={0}
  color="#9AA1AC"
  shineColor="#8FB4FF"
  spread={120}
  direction="left"
  yoyo={false}
  pauseOnHover={false}
  disabled={false}
/>
```

## Props

| Prop | 默认 | 说明 |
|------|------|------|
| text | 必填 | 文本内容 |
| speed | 2 | 扫过速度（秒/周期） |
| delay | 0 | 周期间停顿（秒） |
| color | #b5b5b5 | 基础文字色 |
| shineColor | #ffffff | 高光色 |
| spread | 120 | 高光渐变宽度（度） |
| direction | left | 扫过方向 left/right |
| yoyo | false | 是否往返扫描 |
| pauseOnHover | false | 悬停暂停 |
| disabled | false | 禁用动画 |

## RagNexus 适配

- 基础色用次要文字 `#9AA1AC`，高光用亮蓝 `#8FB4FF`，与设计系统一致
- 原示例文本带 emoji ✨，使用时不带
- 适合 hero 标题的关键词或品牌名
- 来源：reactbits.dev (MIT)，保留版权声明
