# DotField

点阵场背景（Canvas 2D）。鼠标移动时点阵产生隆起/流动，带鼠标光晕。轻量、无 WebGL 依赖。

## 依赖

无第三方依赖。

## 使用

```tsx
import DotField from './DotField';

<div style={{ width: '100%', height: '600px', position: 'relative' }}>
  <DotField
    dotRadius={1.5}
    dotSpacing={14}
    bulgeStrength={67}
    glowRadius={160}
    sparkle={false}
    waveAmplitude={0}
    cursorRadius={500}
    cursorForce={0.1}
    bulgeOnly
    gradientFrom="rgba(53, 102, 214, 0.35)"
    gradientTo="rgba(143, 180, 255, 0.18)"
    glowColor="#0A0C10"
  />
</div>
```

## Props

| Prop | 默认 | 说明 |
|------|------|------|
| dotRadius | 1.5 | 点半径 |
| dotSpacing | 14 | 点间距 |
| cursorRadius | 500 | 鼠标影响半径 |
| cursorForce | 0.1 | 鼠标作用力（bulgeOnly=false 时） |
| bulgeOnly | true | 隆起模式（默认），false 为流动模式 |
| bulgeStrength | 67 | 隆起强度 |
| glowRadius | 160 | 鼠标光晕半径 |
| sparkle | false | 闪烁点缀 |
| waveAmplitude | 0 | 波形振幅 |
| gradientFrom / gradientTo | 紫 | 点阵渐变色 |
| glowColor | #120F17 | 光晕颜色 |

## RagNexus 适配

- 渐变改成了深蓝系：`rgba(53,102,214,0.35)` → `rgba(143,180,255,0.18)`
- glowColor 用主背景 `#0A0C10`，鼠标光晕与页面融为一体
- 放在 hero 或背景容器内，z-index 低于内容
- 来源：reactbits.dev (MIT)，保留版权声明
