# SECURITY — Nexus

**Version :** 0.1 (draft à valider)
**Date :** 2026-09-28

---

## 1. Règle d'or des secrets

> **Aucun secret n'est jamais conservé, affiché, transmis ou journalisé.**

- Toute valeur sensible (token, mot de passe, clé, code 2FA) est remplacée par `[REDACTED]` — dans les docs, logs, bases, exports, captures et messages.
- Contrôles d'existence **uniquement** : on vérifie qu'une clé est présente, jamais sa valeur (`grep -l`, comptage de longueur, présence de fichier).
- Les credentials restent dans leurs coffres (vault local, ACL fichiers, registre de credentials) — jamais dans Nexus.
- Un secret qui apparaît quelque part est un **incident** (§7), pas une fatalité.

## 2. Classification des données

| Niveau | Exemples | Règle |
|---|---|---|
| Public | docs projet, inspirations | libre |
| Interne | tâches, runs, quotas, planning | local uniquement |
| Sensible | mails, conversations (chats, sessions), identités, finances | local, accès restreint, minimisation, jamais exporté |
| Secret | tokens, clés, mots de passe | jamais stocké — coffre uniquement |

## 3. Matrice de permissions (cible)

| Acteur \ Action | Lire | Commenter | Créer tâche | Assigner | Exécuter | Publier/Envoyer | Supprimer |
|---|---|---|---|---|---|---|---|
| Loïc | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ (lui-même) | ✓ |
| Helios | ✓ | ✓ | ✓ | ✓ | ✓ | sur validation | ✗ |
| Mnēma / Aether | ✓ | ✓ | ✓ | ✓ | ✓ (leur nœud) | sur validation | ✗ |
| Artémis | ✓ (son périmètre) | ✓ | ✓ | ✓ | ✓ (usine) | sur validation | ✗ |
| Claude / Codex / Orca | ✓ | ✓ | ✓ | — | ✓ (tâches confiées) | sur validation | ✗ |

- **Suppression** : jamais par un agent. Seul Loïc supprime — ou un script explicitement validé par lui.
- **Exécution** : chaque agent exécute dans son périmètre de nœud et ses permissions locales existantes (inchangées par Nexus).
- **« Confier à »** : depuis Nexus, seul Loïc déclenche l'exécution d'une tâche par un agent (ADR-012) ; un agent peut le proposer (`needs_human`), jamais le déclencher lui-même via Nexus.

## 4. Actions gated (go humain explicite, à chaque fois)

- Envoi de mail, envoi de message à un tiers humain, publication (réseaux, web), achat/dépense, suppression de données,
- Création ou modification d'un événement d'agenda partagé,
- Déploiement/service permanent, modification de config critique (routing, gateways, backups),
- Toute mutation touchant un autre nœud que le sien,
- Toute bascule de modèle/provider payant.

Format d'une demande de validation : **quoi · pourquoi · conséquence · plan de retour**. Une validation vaut pour l'action décrite — pas pour la suivante.

## 5. Frontière par nœud

- Chaque nœud applique ses changements **par son gardien local** (Helios, Mnēma/Cortex, Aether/Synapse, Artémis).
- Phase actuelle : lecture distante uniquement (Tailscale/SSH read-only) ; aucune mutation croisée.
- Une intervention croisée se demande, se justifie, se sauvegarde, se relit — jamais de modification silencieuse.

## 6. Audit & traçabilité

- Les événements sont **immuables** (on corrige par un nouvel événement, jamais par réécriture).
- Chaque mutation : qui, quoi, quand, avant/après (si applicable), preuve de read-back.
- Les logs Nexus ne contiennent jamais de secret ; un contrôle automatique peut scanner les écritures (pattern tokens/clés) et bloquer.

## 7. Incidents

1. **Détecter** (scan, audit périodique, signalement d'agent).
2. **Contenir** (stopper l'écriture concernée, ne pas propager).
3. **Nettoyer** : rédaction (`[REDACTED]`), rotation si un secret a été exposé (décidée par Loïc).
4. **Rapporter** : quoi, où, impact, correction, leçon — dans le journal des décisions si durable.
5. **Vérifier** : read-back du nettoyage.

## 8. Bonnes pratiques vérifiées à conserver

- Agents finance : lecture seule, secrets sous ACL fichiers (jamais en base).
- Scopes OAuth minimaux ; toute extension de scope = validation explicite.
- Backups avant mutation (règle Nexus « réversible ») — ex. : sauvegarde config avant toute modification de routing.
- Les dashboards existants gardent leurs propres accès — Nexus ne les contourne pas.

## 9. Ce que Nexus ne fera jamais

- Stocker un secret, même « temporairement » ou « chiffré maison ».
- Envoyer/publier/dépenser sans go explicite.
- Lancer un agent sans action explicite de Loïc.
- Fermer une tâche sans preuve lisible.
- Exposer une surface d'administration hors de la machine locale.
- Prendre une décision à la place de Loïc (il propose, Loïc tranche).
