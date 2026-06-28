import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// In dev, proxy the read API's paths to the FastAPI server so the frontend can
// use relative URLs and avoid CORS. Override the target with VITE_API_TARGET.
const apiTarget = process.env.VITE_API_TARGET ?? 'http://localhost:8000'
const apiPaths = ['/health', '/report', '/articles', '/companies']

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: Object.fromEntries(
      apiPaths.map((p) => [p, { target: apiTarget, changeOrigin: true }]),
    ),
  },
})
