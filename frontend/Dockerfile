# ── 构建阶段 ──────────────────────────────────────────────
FROM node:20-alpine AS builder

WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci || npm install

COPY . .
RUN npm run build

# ── 运行阶段（Nginx 托管静态资源 + API 反向代理）────────────
FROM nginx:1.27-alpine

COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=builder /app/dist /usr/share/nginx/html

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]
