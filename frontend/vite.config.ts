import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    host: true,
    proxy: {
      '/api': 'http://127.0.0.1:12121',
      '/characters': 'http://127.0.0.1:12121',
      '/music': 'http://127.0.0.1:12121',
      '/ws': { target: 'ws://127.0.0.1:12121', ws: true },
    },
  },
})
