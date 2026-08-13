import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// 后端（FastAPI）独立运行于 8800，前端 dev server 跨域访问（后端已开 CORS）。
// VITE_API_BASE 可覆盖后端地址；生产可同源部署。
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
  },
})
