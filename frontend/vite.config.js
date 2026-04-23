import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')
  const backendTarget = env.VITE_BACKEND_URL || 'http://localhost:8000'

  return {
    plugins: [react()],
    server: {
      proxy: {
        '/api': { target: backendTarget, changeOrigin: true },
        '/auth': { target: backendTarget, changeOrigin: true },
        '/ws': { target: backendTarget, changeOrigin: true, ws: true },
        '/health': { target: backendTarget, changeOrigin: true },
        '/docs': { target: backendTarget, changeOrigin: true },
        '/openapi.json': { target: backendTarget, changeOrigin: true },
      },
    },
  }
})
