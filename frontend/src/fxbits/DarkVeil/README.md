# DarkVeil

深色流动面纱背景（WebGL / ogl）。适合暗色科技页面的大面积氛围背景。

## 依赖

```bash
npm install ogl
```

## 使用

```tsx
import DarkVeil from './DarkVeil';

<div style={{ width: '100%', height: '600px', position: 'relative' }}>
  <DarkVeil
    hueShift={0}
    noiseIntensity={0}
    scanlineIntensity={0}
    speed={0.5}
    scanlineFrequency={0}
    warpAmount={0}
  />
</div>
```

## Props

| Prop | 默认 | 说明 |
|------|------|------|
| hueShift | 0 | 色相偏移（度） |
| noiseIntensity | 0 | 噪点强度 0-1 |
| scanlineIntensity | 0 | 扫描线强度 0-1 |
| speed | 0.5 | 动画速度 |
| scanlineFrequency | 0 | 扫描线频率 |
| warpAmount | 0 | 扭曲量 |
| resolutionScale | 1 | 分辨率缩放（性能） |

## RagNexus 适配

- 默认输出偏亮，深色页面请放在 `position: absolute` 容器内并给内容层叠加遮罩
- 保持默认参数即可（noise/scanline 默认 0，干净）
- 来源：reactbits.dev (MIT)，保留版权声明
