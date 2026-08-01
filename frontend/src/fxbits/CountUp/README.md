# CountUp

数字滚动动画（framer-motion / motion）。进入视口时从起始值滚动到目标值，带弹簧缓动。

## 依赖

```bash
npm install motion
```

## 使用

```tsx
import CountUp from './CountUp';

<CountUp
  from={0}
  to={99.2}
  separator=""
  direction="up"
  duration={1}
  className="count-up-text"
  delay={0}
/>
```

## Props

| Prop | 默认 | 说明 |
|------|------|------|
| to | 必填 | 目标值 |
| from | 0 | 起始值 |
| direction | up | up/down |
| delay | 0 | 延迟（秒） |
| duration | 2 | 动画时长（秒） |
| startWhen | true | 是否进入视口时触发 |
| separator | '' | 千分位分隔符 |
| onStart / onEnd | - | 开始/结束回调 |

## RagNexus 适配

- 指标区三个数字（99.2 / 182 / 1.2）可直接替换原型里的手写 count-up JS
- 小数自动处理（99.2 保留 1 位小数）
- 单位（%、ms、M）放在 CountUp 外的 `<small>` 里
- 来源：reactbits.dev (MIT)，保留版权声明
