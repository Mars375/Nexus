// Faux `claude` des tests de bout en bout : il ne parle à aucun modèle (ADR-023, D8).
// Il lit le brief sur l'entrée standard, raconte une session en stream-json (les cinq outils, aucun
// serveur MCP), écrit un fichier dans son dossier de travail puis se termine. Il ne lance jamais git :
// c'est Nexus qui commite. Un brief qui contient « ATTENDRE » le fait rester en vie jusqu'à ce qu'on le tue.
import { writeFileSync } from 'node:fs'

const args = process.argv.slice(2)
if (args[0] === '--version') {
  console.log('2.1.322 (e2e)')
  process.exit(0)
}

let brief = ''
process.stdin.setEncoding('utf8')
for await (const chunk of process.stdin) brief += chunk

const say = (event) => console.log(JSON.stringify(event))
const model = args[args.indexOf('--model') + 1]
say({
  type: 'system',
  subtype: 'init',
  cwd: process.cwd(),
  session_id: 'e2e',
  tools: ['Edit', 'Glob', 'Grep', 'Read', 'Write'],
  mcp_servers: [],
  model: `claude-${model}-e2e`,
  permissionMode: 'dontAsk',
  slash_commands: [],
  apiKeySource: 'none',
})
say({ type: 'assistant', message: { role: 'assistant', content: [{ type: 'text', text: 'Je commence (faux Claude Code).' }] } })

if (brief.includes('ATTENDRE')) {
  setInterval(() => {}, 1000)
  await new Promise(() => {})
}

writeFileSync('TRAVAIL-CLAUDE.txt', 'travail e2e\n')
say({
  type: 'assistant',
  message: { role: 'assistant', content: [{ type: 'tool_use', name: 'Write', input: { file_path: 'TRAVAIL-CLAUDE.txt', content: 'travail e2e\n' } }] },
})
say({ type: 'result', subtype: 'success', is_error: false, num_turns: 2, duration_ms: 10, result: 'Fait.', errors: null, permission_denials: [] })
