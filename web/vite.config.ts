import { fileURLToPath } from 'node:url'
import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { loadEnv } from 'vite'
import { defineConfig } from 'vitest/config'
import { normalizeApiBase } from './src/normalizeApiBase.ts'

const API = `http://127.0.0.1:${process.env.NEXUS_PORT ?? '8765'}`

export default defineConfig(({ mode }) => {
  // A bad API base fails the build or dev server here, before it can reach the bundle (#25).
  normalizeApiBase(loadEnv(mode, process.cwd(), 'VITE_').VITE_NEXUS_API_URL)
  return {
    plugins: [react(), tailwindcss()],
    resolve: {
      alias: { '@': fileURLToPath(new URL('./src', import.meta.url)) },
    },
    server: {
      proxy: {
        '/api': { target: API, ws: true },
      },
    },
    test: {
      environment: 'jsdom',
      setupFiles: ['./src/test-setup.ts'],
      exclude: ['e2e/**', 'node_modules/**'],
    },
  }
})
