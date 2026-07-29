# 构建阶段
FROM node:20-alpine AS build
WORKDIR /app
COPY package*.json ./
RUN npm ci
COPY . .
RUN npm run build

# 运行阶段
FROM nginx:alpine
COPY nginx.conf /etc/nginx/nginx.conf
COPY --from=build /app/dist /usr/share/nginx/html

# 前端开发时用 `npm run dev`，生产用这个
# 启动 nginx（前台运行，否则容器秒退）
CMD ["nginx", "-g", "daemon off;"]
