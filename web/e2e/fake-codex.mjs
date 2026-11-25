// Faux `codex` des tests de bout en bout : il ne parle à aucun modèle (ADR-023, D8).
// Il répond aux appels de contrôle du lancement (`--version`, `mcp list --json`, `debug prompt-input`).
// It reads the brief on stdin, tells a turn in JSONL, then writes a file in its worktree.
// It never runs git: Nexus commits at the end of a successful turn (#186).
// Un brief qui contient « ATTENDRE » le fait rester en vie jusqu'à ce qu'on le tue (annulation).
// Un brief qui contient « ÉCHOUER » termine son tour par un `turn.failed` et un code non nul (cause affichée).
import { writeFileSync } from 'node:fs'
import { join } from 'node:path'

const args = process.argv.slice(2)
// The control calls Nexus makes before a run (spec #186, §5.3; spec 2026-11-25, B), answered before
// stdin is read: a measured version, no MCP server, and a model input without any skills block.
// The exit waits for the write to be flushed: a bare process.exit() could cut a piped output short.
const answer = (text) => new Promise(() => process.stdout.write(text + '\n', () => process.exit(0)))
// Nexus refuses a version it has not measured: this one must stay in MEASURED_VERSIONS (codex_cli.py).
if (args[0] === '--version') await answer('codex-cli 0.167.1')
if (args[0] === 'mcp' && args[1] === 'list' && args[2] === '--json') await answer('[]')
if (args[0] === 'debug' && args[1] === 'prompt-input') {
  const input = [{ type: 'message', role: 'developer', content: [{ type: 'input_text', text: 'Instructions de base.' }] }]
  await answer(JSON.stringify(input))
}

let brief = ''
process.stdin.setEncoding('utf8')
for await (const chunk of process.stdin) brief += chunk

const say = (event) => console.log(JSON.stringify(event))
say({ type: 'thread.started', thread_id: 'e2e' })
say({ type: 'turn.started' })
say({ type: 'item.completed', item: { type: 'agent_message', text: 'Je commence (faux Codex).' } })

if (brief.includes('ATTENDRE')) {
  setInterval(() => {}, 1000)
  await new Promise(() => {})
}

if (brief.includes('ÉCHOUER')) {
  say({ type: 'turn.failed', error: { message: 'quota épuisé (faux Codex), reprise à 14 h' } })
  // No process.exit(): it could cut the piped output short; the exit code is set instead.
  process.exitCode = 1
} else {
  const worktree = args[args.indexOf('--cd') + 1]
  writeFileSync(join(worktree, 'TRAVAIL-CODEX.txt'), 'travail e2e\n')
  say({ type: 'turn.completed', usage: {} })
}
