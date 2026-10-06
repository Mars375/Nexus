import { expect, test } from 'vitest'
import { apiUrl } from './apiBase'

test('apiUrl laisse le chemin relatif sans base', () => {
  expect(apiUrl('/api/tasks', '')).toBe('/api/tasks')
})

test('apiUrl préfixe le chemin avec la base', () => {
  expect(apiUrl('/api/tasks', 'http://tauri-api.local:8765')).toBe('http://tauri-api.local:8765/api/tasks')
})
