// Faux `codex` des tests de bout en bout : il ne parle à aucun modèle (ADR-023, D8).
// Il lit le brief sur l'entrée standard, raconte un tour en JSONL, puis commite dans son worktree.
// Un brief qui contient « ATTENDRE » le fait rester en vie jusqu'à ce qu'on le tue (annulation).
import { execFileSync } from 'node:child_process'

const args = process.argv.slice(2)
if (args[0] === '--version') {
  console.log('codex-cli 0.0.0-e2e')
  process.exit(0)
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

const cwd = args[args.indexOf('--cd') + 1]
execFileSync(
  'git',
  ['-c', 'user.name=e2e', '-c', 'user.email=e2e@example.invalid', 'commit', '--allow-empty', '-m', 'travail e2e'],
  { cwd, stdio: 'ignore' },
)
say({ type: 'turn.completed', usage: {} })
