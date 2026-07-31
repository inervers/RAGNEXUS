import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      // API_BASE="" 时前端直接请求 /health、/query 等相对路径，全部转发到后端
      '/health': { target: 'http://localhost:8000', changeOrigin: true },
      '/query': { target: 'http://localhost:8000', changeOrigin: true },
      '/doc': { target: 'http://localhost:8000', changeOrigin: true },
      '/kb': { target: 'http://localhost:8000', changeOrigin: true },
      '/agent': { target: 'http://localhost:8000', changeOrigin: true },
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, ''),
      },
    },
  },
})
