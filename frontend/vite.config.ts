import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: Object.fromEntries(['/auth', '/dispatch', '/jobs', '/approvals', '/schedules', '/memory', '/agents', '/system', '/pipeline', '/runs', '/router', '/conversations', '/health', '/ready'].map(path => [path, 'http://127.0.0.1:8080'])),
  },
  build: { chunkSizeWarningLimit: 1000 },
})
