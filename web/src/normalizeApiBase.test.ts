import { describe, expect, it } from 'vitest'
import { INVALID_API_BASE, normalizeApiBase } from './normalizeApiBase'

describe('normalizeApiBase', () => {
  it('keeps relative addresses when nothing is configured', () => {
    expect(normalizeApiBase(undefined)).toBe('')
    expect(normalizeApiBase('')).toBe('')
    expect(normalizeApiBase('   ')).toBe('')
  })

  it('accepts an http(s) origin and drops trailing slashes', () => {
    expect(normalizeApiBase('http://127.0.0.1:8765')).toBe('http://127.0.0.1:8765')
    expect(normalizeApiBase(' https://nexus.local/ ')).toBe('https://nexus.local')
    expect(normalizeApiBase('http://[::1]:8765')).toBe('http://[::1]:8765')
  })

  it.each([
    'nexus.local',
    '/api',
    'ftp://nexus.local',
    'localhost:8765',
    'http://127.0.0.1:8765/api',
    'https://nexus.local/proxy',
    'http://user:pass@nexus.local',
    'http://nexus.local?x=1',
    'http://nexus.local#frag',
  ])('refuses %s without echoing it', (raw) => {
    expect(() => normalizeApiBase(raw)).toThrow(INVALID_API_BASE)
  })
})
