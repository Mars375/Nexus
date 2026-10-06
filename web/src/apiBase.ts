/*
 * Base de l'API (#25, ADR-017). Dans le navigateur, la page et l'API partagent l'origine : la base
 * reste vide et les adresses restent relatives. Dans une WebView (`http://tauri.localhost`), la
 * page n'est pas servie par l'API : la base se fixe à la compilation avec VITE_NEXUS_API_URL.
 */
const INVALID = 'VITE_NEXUS_API_URL doit être une origine http(s) sans identifiants, requête ni fragment.'

export function normalizeApiBase(raw: string | undefined): string {
  const value = raw?.trim() ?? ''
  if (value === '') return ''
  let url: URL
  try {
    url = new URL(value)
  } catch {
    throw new Error(INVALID)
  }
  const invalid =
    (url.protocol !== 'http:' && url.protocol !== 'https:') ||
    url.username !== '' ||
    url.password !== '' ||
    url.search !== '' ||
    url.hash !== ''
  if (invalid) throw new Error(INVALID)
  return `${url.origin}${url.pathname.replace(/\/+$/, '')}`
}

export const API_BASE = normalizeApiBase(import.meta.env.VITE_NEXUS_API_URL)

export const apiUrl = (path: string, base: string = API_BASE): string => `${base}${path}`
