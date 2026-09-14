import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import path from 'path'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
  server: {
    port: 3000,
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
        // 开发环境剥离 /api 前缀，使后端路由（无 /api 前缀）直接匹配。
        // 配合后端移除 openapi_prefix（C3），开发与生产（nginx 已剥离 /api）行为一致。
        rewrite: (path) => path.replace(/^\/api/, ''),
      },
    },
  },
})