import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// dev 时把 /api 转发到本地 FastAPI，避免跨域 & 保留 SSE 长连接
// 生产可通过反代把 /api 打到同源。
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
        // SSE 要禁用响应缓冲；Vite 内置 http-proxy 已按 chunked 透传，这里只关掉压缩
        ws: false,
      },
    },
  },
});
