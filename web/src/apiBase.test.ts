import { describe, expect, it } from 'vitest'
import { apiUrl, normalizeApiBase } from './apiBase'

describe('normalizeApiBase', () => {
  it('keeps relative addresses when nothing is configured', () => {
    expect(normalizeApiBase(undefined)).toBe('')
    expect(normalizeApiBase('')).toBe('')
    expect(normalizeApiBase('   ')).toBe('')
  })

  it('accepts an http(s) origin and drops trailing slashes', () => {
    expect(normalizeApiBase('http://127.0.0.1:8765')).toBe('http://127.0.0.1:8765')
    expect(normalizeApiBase(' https://nexus.local/ ')).toBe('https://nexus.local')
    expect(normalizeApiBase('https://nexus.local/proxy//')).toBe('https://nexus.local/proxy')
  })

  it.each([
    'nexus.local',
    '/api',
    'ftp://nexus.local',
    'http://user:pass@nexus.local',
    'http://nexus.local?x=1',
    'http://nexus.local#frag',
  ])('refuses %s without echoing it', (raw) => {
    expect(() => normalizeApiBase(raw)).toThrow(/VITE_NEXUS_API_URL/)
    try {
      normalizeApiBase(raw)
    } catch (error) {
      expect(String((error as Error).message)).not.toContain(raw)
    }
  })
})

describe('apiUrl', () => {
  it('leaves the path relative without a base', () => {
    expect(apiUrl('/api/tasks', '')).toBe('/api/tasks')
  })

  it('prefixes the path with the base', () => {
    expect(apiUrl('/api/tasks', 'http://tauri-api.local:8765')).toBe('http://tauri-api.local:8765/api/tasks')
    expect(apiUrl('/api/tasks', 'https://nexus.local/proxy')).toBe('https://nexus.local/proxy/api/tasks')
  })
})
