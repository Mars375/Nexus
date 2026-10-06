/*
 * Validation de VITE_NEXUS_API_URL (#25). Module pur, sans import.meta.env : vite.config.ts s'en
 * sert pour faire échouer la compilation avant qu'une valeur invalide n'entre dans le bundle.
 */
export const INVALID_API_BASE =
  'VITE_NEXUS_API_URL doit être une origine http(s) seule (http://hôte:port), sans chemin, identifiants, requête ni fragment.'

// Raw shape first: new URL() would normalise `/a/..` to `/` and drop an empty `?` or `#`.
const RAW_ORIGIN = /^https?:\/\/[^/\\?#@\s]+\/?$/i

export function normalizeApiBase(raw: string | undefined): string {
  const value = raw?.trim() ?? ''
  if (value === '') return ''
  if (!RAW_ORIGIN.test(value)) throw new Error(INVALID_API_BASE)
  let url: URL
  try {
    url = new URL(value)
  } catch {
    throw new Error(INVALID_API_BASE)
  }
  return url.origin
}
