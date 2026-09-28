# INSPIRATIONS — Nexus

**Version :** 0.1
**Date :** 2026-09-28
**Méthode :** recherche multi-sources (GitHub, docs, DEV/HN, X, YouTube, Instagram) menée les 25–28/09/2026. Ce document liste ce qu'on **prend** et ce qu'on **évite** de chaque référence. Aucun outil existant n'est adopté tel quel : on combine les meilleurs patterns.

---

## Projets et produits

### Buzz (Block) — espaces communs humains + agents
- **Prendre :** espaces partagés (canaux, fils, dépôts, workflows, événements), identité et permissions par agent, model-agnostic (accueille Claude Code, Codex…).
- **Éviter :** en faire notre couche — c'est un espace de collaboration/communication, pas un moteur de tâches + preuves.

### AgentSpace — organisation d'agents
- **Prendre :** rôles, propriétaires, permissions, validations, audit, budgets — le vocabulaire d'organisation.
- **Éviter :** en dépendre (produit indépendant en développement) ; on reprend le modèle conceptuel.

### AgentHub — messages structurés
- **Prendre :** communication par types explicites (status, blocker, review, completion…) au lieu du chat libre → base de notre [EVENT-PROTOCOL](EVENT-PROTOCOL.md).
- **Éviter :** espaces et synchronisation temps réel complets comme prérequis.

### Vibe Kanban — agents de code
- **Prendre :** worktrees par tentative, suivi d'exécution, revue des diffs, multi-agents de code.
- **Éviter :** le limiter aux agents de code ; notre Kanban sert tout type de tâche.

### Agent Fleet (afleet.md)
- **Prendre :** flotte Claude Code + Codex réunie, tâches planifiées, heartbeat, historique des runs, coûts/tokens, permissions, observabilité, canaux Telegram/Slack/Discord.
- **Éviter :** sa couche mémoire propre et sa dépendance Obsidian — notre mémoire reste Hindsight/Mnēma.

### OpenClaw — Dashboard / Mission Control
- **Prendre :** vue mission control (tâches, calendrier, mémoires, équipes), occupation de l'espace par les agents.
- **Éviter :** les promesses d'autonomie non vérifiables des démos.

### AI Maestro
- **Prendre :** dashboard local + mémoire persistante + messagerie inter-agents — l'idée qu'un poste unique suffit.
- **Éviter :** duplication de nos dashboards existants (Mnēma/Synapse restent leurs surfaces).

### Autres dépôts survolés (Kandev, Claw-Kanban, T0ggles, Nimbalyst, Conductor, Claude Command Center, Jarvis-Copilot, openclaw-dashboard, kanbots)
- **Prendre :** idées ponctuelles (files par agent, board d'équipe, orchestration de worktrees, revue).
- **Éviter :** l'adoption complète d'un produit ; Nexus reste notre application.

## Protocoles

### A2A (Agent2Agent)
- **Prendre :** tâches, streaming, artefacts comme concepts de premier ordre.
- **Éviter :** dépendre du protocole au MVP ; on s'en inspire, on ne l'implémente pas d'abord.

### MCP Tasks (spécification)
- **Prendre :** l'état durable d'une tâche comme objet de première classe (tâche longue, reprise, statut).
- **Éviter :** coupler Nexus à une spec mouvante.

### OpenCode / Orca
- **Prendre :** sessions agents, worktrees, délégation CLI scriptable (`codex exec -p …` comme pattern).
- **Éviter :** confondre leurs identités — dans Nexus, un exécutant reste distinct d'un agent.

## Réseaux sociaux (inspirations visuelles — jamais des preuves)

- **Reels/Posts « Jarvis » et second brain (Instagram, X, YouTube) :** cerveau 3D, bureau virtuel, bureaux d'agents, calendrier, notifications.
  - **Prendre :** l'ergonomie « page d'accueil opérationnelle », la lisibilité des états, l'envie d'ouvrir Nexus à la place de 300 onglets.
  - **Éviter :** animations sans état réel, autonomie non vérifiable, dashboards-décor, mémoire propriétaire non inspectable.
- **Carrousel @lifeofarjav — « JEV Project » (Instagram, Ddm2r7KkiXU, 8 slides) :** typographie dense, thème « smarter AI systems ».
  - **Prendre :** soin éditorial des interfaces ; le fond JEV (gating, choix d'action) est déjà étudié côté Helios.
- **Carrousel @entrenology — « 4 AI Projects » (Instagram, Ddbh5ueCmUF, 6 slides) :** slide 3 « Personal Assistant » (Telegram/Gmail, mémoire, tâches planifiées, sa propre machine).
  - **Prendre :** validation du concept « agent possédé et auto-hébergé » — le socle existe déjà.
- **Reel Ddv4_13pVmH (partagé par Loïc le 27/09) :** contenu **non décodé** — Instagram le renvoie indisponible/invalide publiquement (restriction d'âge détectée) au 28/09.
  - **À faire :** obtenir capture/vidéo d'écran pour l'analyser et l'ajouter ici.
- **Reels supplémentaires repérés :** DYOHUtqubJg, DXM7hJ0j03q (catégorie second brain/Jarvis — compléments de veille).
- **Vidéos YouTube :** critique des faux dashboards Jarvis ; contrôle room Orca ; walkthroughs cockpit.
  - **Prendre :** les checklists de ce qui différencie un vrai contrôle d'agent d'un décor.

## Ce que la recherche conclut

1. **Ne pas adopter ni copier un produit existant** — construire notre propre application, autonome, avec les outils existants (Hermes compris) branchés derrière des adaptateurs.
2. **Les patterns gagnants :** espaces partagés, rôles/permissions, messages structurés, worktrees/tentatives, heartbeat, preuves, budgets visibles.
3. **Les pièges :** dashboards-décor, autonomie promise, duplication des sources, mémoire opaque.
4. **Notre différenciateur :** l'honnêteté des états (provenance, fraîcheur, `unknown`), l'usage sans LLM, l'exécution uniquement sur action explicite, et l'intégration réelle de nos 4 nœuds + exécutants dans une seule application.
