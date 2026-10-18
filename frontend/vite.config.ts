import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    // 개발 시 /api 요청을 FastAPI로 프록시(CORS·환경별 URL 분기 불필요)
    proxy: { '/api': 'http://localhost:8000' },
  },
});
