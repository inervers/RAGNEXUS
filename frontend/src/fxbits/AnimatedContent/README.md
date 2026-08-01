# AnimatedContent

滚动进入视口时的内容渐入动画（gsap + ScrollTrigger）。替代手写 IntersectionObserver reveal。

## 依赖

```bash
npm install gsap
```

## 使用

```tsx
import AnimatedContent from './AnimatedContent';

<AnimatedContent
  distance={24}
  direction="vertical"
  reverse={false}
  duration={0.6}
  ease="power3.out"
  initialOpacity={0}
  animateOpacity
  scale={1}
  threshold={0.1}
  delay={0}
>
  <div>Content to Animate</div>
</AnimatedContent>
```

## Props

| Prop | 默认 | 说明 |
|------|------|------|
| distance | 100 | 位移距离（px） |
| direction | vertical | vertical / horizontal |
| reverse | false | 反向位移 |
| duration | 0.8 | 动画时长（秒） |
| ease | power3.out | 缓动 |
| initialOpacity | 0 | 初始透明度 |
| animateOpacity | true | 是否动画透明度 |
| scale | 1 | 缩放 |
| threshold | 0.1 | 触发阈值 |
| delay | 0 | 延迟（秒） |
| disappearAfter / disappearDuration | 0 | 消失重播配置 |

## RagNexus 适配

- 原型里的 reveal 是手写 IntersectionObserver，接入 React 后用这个组件替代
- 注意组件自带 `visibility: hidden` 初始态，`scrollerTarget` 默认找 `#snap-main-container`，普通滚动页面传 `container` 或直接用默认 window
- 来源：reactbits.dev (MIT)，保留版权声明
