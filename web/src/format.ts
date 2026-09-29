const dateTime = new Intl.DateTimeFormat('fr-FR', { dateStyle: 'medium', timeStyle: 'short' })
const shortDate = new Intl.DateTimeFormat('fr-FR', { day: 'numeric', month: 'short' })

export function formatDateTime(iso: string): string {
  return dateTime.format(new Date(iso))
}

export function formatShortDate(iso: string): string {
  return shortDate.format(new Date(iso))
}

export function age(iso: string, now: number): string {
  const seconds = Math.max(0, Math.round((now - new Date(iso).getTime()) / 1000))
  if (seconds < 60) return `il y a ${seconds} s`
  const minutes = Math.round(seconds / 60)
  if (minutes < 60) return `il y a ${minutes} min`
  const hours = Math.round(minutes / 60)
  if (hours < 48) return `il y a ${hours} h`
  return `il y a ${Math.round(hours / 24)} j`
}

export function isOverdue(iso: string | null, now: number): boolean {
  return iso !== null && new Date(iso).getTime() < now
}

/** Valeur d'un <input type="datetime-local"> (heure locale) → instant ISO avec fuseau. */
export function localInputToIso(value: string): string | null {
  return value ? new Date(value).toISOString() : null
}

/** Instant ISO → valeur d'un <input type="datetime-local"> en heure locale. */
export function isoToLocalInput(iso: string | null): string {
  if (!iso) return ''
  const d = new Date(iso)
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`
}
