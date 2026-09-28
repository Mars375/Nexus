import react from '@vitejs/plugin-react'
import { defineConfig } from 'vitest/config'

const API = `http://127.0.0.1:${process.env.NEXUS_PORT ?? '8765'}`

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/api': { target: API, ws: true },
    },
  },
  test: {
    environment: 'jsdom',
    setupFiles: ['./src/test-setup.ts'],
  },
})
