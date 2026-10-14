# ── 构建阶段 ──────────────────────────────────────────────
ARG NODE_BASE_IMAGE=node:20-alpine
ARG NGINX_BASE_IMAGE=nginx:1.27-alpine
FROM ${NODE_BASE_IMAGE} AS builder

WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci || npm install

COPY . .
RUN npm run build

# ── 运行阶段（Nginx 托管静态资源 + API 反向代理）────────────
FROM ${NGINX_BASE_IMAGE}

COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=builder /app/dist /usr/share/nginx/html

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]
