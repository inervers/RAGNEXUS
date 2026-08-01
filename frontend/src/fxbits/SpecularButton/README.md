# SpecularButton

镜面高光描边按钮（WebGL / ogl）。按钮边缘有一圈高光描边，随鼠标位置改变光源方向，靠近按钮时高光渐显。

## 依赖

```bash
npm install ogl
```

## 使用

```tsx
import SpecularButton from './SpecularButton';

<SpecularButton
  size="lg"
  radius={4}
  tint="#3566D6"
  tintOpacity={1}
  blur={0}
  textColor="#F4F7FF"
  lineColor="#8FB4FF"
  baseColor="#3566D6"
  intensity={1}
  shineSize={10}
  shineFade={40}
  thickness={1}
  speed={0.35}
  followMouse
  proximity={250}
  autoAnimate={false}
  onClick={() => console.log('clicked')}
>
  启动平台
</SpecularButton>
```

## Props

| Prop | 默认 | 说明 |
|------|------|------|
| size | lg | sm / md / lg |
| radius | 18 | 圆角（px） |
| tint / tintOpacity / blur | - | 底色 tint 与模糊（玻璃效果，可关） |
| textColor | #f5f5f5 | 文字色 |
| lineColor | #ffffff | 高光描边色 |
| baseColor | #525252 | 描边底色 |
| intensity | 1 | 高光强度 |
| shineSize / shineFade | 10 / 40 | 高光角度窗口 |
| thickness | 1 | 描边粗细 |
| speed | 0.35 | 空闲时扫动速度 |
| followMouse | true | 跟随鼠标 |
| proximity | 250 | 高光响应距离 |
| autoAnimate | false | 常亮扫光 |
| disabled / onClick / type | - | 标准按钮行为 |

## RagNexus 适配

- 主按钮配色：tint 与 baseColor 用主蓝 `#3566D6`，文字 `#F4F7FF`，高光 `#8FB4FF`
- radius 改 4 保持直角工程感（原示例 18 太圆润）
- CSS 里默认 box-shadow 带 24px 投影，与设计纪律冲突时可去掉
- 来源：reactbits.dev (MIT)，保留版权声明
