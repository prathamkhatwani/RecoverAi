import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

// The backend is the single source of truth for every number on screen, so the dev
// server proxies /api straight through rather than duplicating any of it here.
// Buffering is disabled on the SSE route so the live triage view arrives frame by
// frame instead of in one lump at the end.
export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
        configure: (proxy) => {
          proxy.on('proxyRes', (proxyRes) => {
            if (proxyRes.headers['content-type']?.includes('text/event-stream')) {
              proxyRes.headers['x-no-compression'] = '1'
            }
          })
        },
      },
    },
  },
})
