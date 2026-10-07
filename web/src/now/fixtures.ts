// Test fixtures of /api/now asks (shared by the Maintenant tests; never imported by the app).
import type { NowApproval, NowAsk } from '@/api'

export const approval = (over: Partial<NowApproval> = {}): NowApproval => ({
  ref: 'nx-appr-1', status: 'pending', expires_at: null, decided_by: null, decided_at: null, ...over,
})

/** A pending question of Mnema; `approval: null` is a request from before migration 0004. */
export const ask = (over: Partial<NowAsk> = {}): NowAsk => ({
  event: 'nx-evt-1', agent: 'mnema', kind: 'question', subject: 'Python ?', task: null,
  at: new Date().toISOString(), received_at: new Date().toISOString(),
  body: null, options: [], consequence: null, approval: approval(), ...over,
})
