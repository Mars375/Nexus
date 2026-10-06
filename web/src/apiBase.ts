/*
 * Base de l'API (#25, ADR-017). Dans le navigateur, la page et l'API partagent l'origine : la base
 * reste vide et les adresses restent relatives. Dans une WebView (`http://tauri.localhost`), la
 * page n'est pas servie par l'API : la base se fixe à la compilation avec VITE_NEXUS_API_URL
 * (validée par vite.config.ts, puis de nouveau ici).
 */
import { normalizeApiBase } from './normalizeApiBase'

export const API_BASE = normalizeApiBase(import.meta.env.VITE_NEXUS_API_URL)

export const apiUrl = (path: string, base: string = API_BASE): string => `${base}${path}`
