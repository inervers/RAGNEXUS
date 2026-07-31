# 构建阶段
FROM node:20-alpine AS build
WORKDIR /app
COPY package*.json ./
# 固定国内 registry 直连（不依赖代理，避免 npm 挂起崩溃）
# npm ci 崩溃时退出码为 0（npm 已知 bug），用 tsc 存在性做真实校验，
# 校验失败则用 npm install 兜底补装
RUN npm config set registry https://registry.npmmirror.com && \
    ( (npm ci --no-audit --no-fund && test -x node_modules/.bin/tsc) || npm install --no-audit --no-fund )
COPY . .
RUN npm run build

# 运行阶段
FROM nginx:alpine
COPY nginx.conf /etc/nginx/nginx.conf
COPY --from=build /app/dist /usr/share/nginx/html

# 前端开发时用 `npm run dev`，生产用这个
# 启动 nginx（前台运行，否则容器秒退）
CMD ["nginx", "-g", "daemon off;"]
