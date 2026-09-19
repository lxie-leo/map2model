# 前端镜像:Node 构建 + nginx 托管,并把 /api 反代到后端容器。

FROM node:22-alpine AS build
WORKDIR /app

# corepack 是 node 自带的 pnpm 启动器
ENV COREPACK_NPM_REGISTRY=https://registry.npmmirror.com
RUN corepack enable

COPY package.json pnpm-lock.yaml ./
RUN corepack pnpm install --frozen-lockfile

COPY . .
RUN corepack pnpm build

FROM nginx:alpine
COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
