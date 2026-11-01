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
- **Une empreinte n'est pas un secret** (ADR-020) : Nexus ne garde des jetons d'acteur que leur SHA-256 (`actor_tokens.token_hash`). Elle ne permet ni de s'authentifier ni de retrouver le jeton (256 bits d'entropie) ; elle peut donc figurer dans la base et ses sauvegardes. Le jeton en clair, lui, n'est jamais stocké, journalisé ni renvoyé : `nxt_…` collé dans un texte est masqué comme tout secret.
- **Limites connues du scanner** (`nexus.secrets.redact`, décisions de Loïc du 2026-11-01 sur #95, mesures sur `master` du 2026-11-01) : le scanner masque dans le doute (ADR-006), donc il se trompe dans les deux sens.
  - *Sur-masquage assumé :* un lien dont l'identifiant ressemble à un secret est masqué en partie, par exemple `https://drive.google.com/file/d/<id>/view` devient `https://drive.google.[REDACTED]…`. Il n'est pas considéré comme vide (la preuve est conservée), mais sa valeur est abîmée.
  - *Fuite connue, correction suivie dans #144 :* une clé à barres obliques de 40 caractères suivie de mots de chemin ou précédée d'un chemin peut rester en clair (échantillon de 400 clés synthétiques contenant un `/` : `s3://bucket/<clé>/backups/production`, clé entière en clair dans 28 % des cas ; `cat /etc/tokens/<clé>`, 10 %). Ne pas compter sur le scanner pour ces formes : ne pas coller de clé dans un chemin ou une commande.

## 2. Classification des données

| Niveau | Exemples | Règle |
|---|---|---|
| Public | docs projet, inspirations | libre |
| Interne | tâches, runs, quotas, planning | local uniquement |
| Sensible | mails, conversations (chats, sessions), identités, finances | local, accès restreint, minimisation, jamais exporté |
| Secret | tokens, clés, mots de passe | jamais stocké — coffre uniquement |

## 3. Matrice de permissions (cible ; la partie appliquée par #16 est détaillée plus bas)

| Acteur \ Action | Lire | Commenter | Créer tâche | Assigner | Exécuter | Publier/Envoyer | Supprimer |
|---|---|---|---|---|---|---|---|
| Loïc | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ (lui-même) | ✓ |
| Helios | ✓ | ✓ | ✓ | ✓ | ✓ | sur validation | ✗ |
| Mnēma / Aether | ✓ | ✓ | ✓ | ✓ | ✓ (leur nœud) | sur validation | ✗ |
| Artémis | ✓ (son périmètre) | ✓ | ✓ | ✓ | ✓ (usine) | sur validation | ✗ |
| Claude / Codex / Orca / Hermes | ✓ | ✓ | ✓ | — | ✓ (tâches confiées) | sur validation | ✗ |

- **Suppression** : jamais par un agent. Seul Loïc supprime — ou un script explicitement validé par lui.
- **Exécution** : chaque agent exécute dans son périmètre de nœud et ses permissions locales existantes (inchangées par Nexus).
- **Qui décide d'une approbation** (#26, ADR-019) : seul un destinataire **humain** de la demande (`needs`) peut y répondre ou la trancher ; un autre acteur est refusé en **409** `not_addressee`, et le demandeur qui tranche sa propre demande en **409** `self_decision` (règle de cohérence, pas un 403 : `POST /api/approvals/<ref>/answer` et `/decision`). **Contrôle de cohérence, pas de sécurité :** depuis ADR-020 l'acteur est authentifié par son jeton (ci-dessous), mais ce refus reste un 409 de cohérence (le contrat d'ADR-019 ne change pas). Reste vrai : un agent ne peut pas publier lui-même un événement `answer` (réservé à Nexus, `POST /api/events` le refuse), et une réponse masque les secrets comme tout événement. La `consequence` d'une demande est annoncée par le demandeur et non vérifiée (ADR-005).
- **Authentification des acteurs** (#16, ADR-020) : **le jeton est exigé** sur toute route REST, lectures comprises, sauf `GET /api/health` ; la documentation OpenAPI (`/openapi.json`, `/docs`, `/docs/oauth2-redirect`, `/redoc`) reste ouverte (schéma de l'API seulement, aucune donnée de Nexus ; protégés du DNS rebinding par le contrôle `Host`). Un acteur s'authentifie par un jeton porteur `Authorization: Bearer nxt_…`, émis par `nexus-token issue <acteur> --label <texte>` et révocable par `nexus-token revoke nx-tok-<n>` (effet dès la requête suivante). L'acteur est celui du jeton, jamais un en-tête déclaré : sans jeton, `X-Nexus-Actor` seul ne donne rien (401). Un `Authorization` absent ou mal formé donne 401 `auth_required` (avec `WWW-Authenticate: Bearer`), un jeton inconnu ou révoqué 401 `invalid_token` (même réponse dans les deux cas), et rien de ce qui est reçu n'est recopié dans la réponse. `X-Nexus-Actor` reste facultatif mais, s'il est présent, il doit égaler l'acteur du jeton, comme l'`actor` d'un événement : sinon 403 `actor_mismatch`. Le **WebSocket** `/api/ws` exige un ticket `nxw_…` à usage unique (30 s, 256 bits), obtenu par `POST /api/ws-ticket` avec le jeton porteur (réponse `Cache-Control: no-store`) et envoyé dans `Sec-WebSocket-Protocol` à côté de `nexus.live.v1`, jamais dans l'URL ; il est lié au jeton qui l'a demandé (par l'empreinte du jeton, non par son identifiant de ligne, que SQLite peut réattribuer après une suppression). Tout refus avant l'acceptation est une fermeture 1008 sans raison (HTTP 403 pour le client), sans distinguer les cas. Un jeton révoqué ou supprimé ferme une socket déjà ouverte en 4401 « jeton révoqué ». Au plus 16 tickets en attente par jeton ; un seul processus serveur (les tickets vivent en mémoire). Les journaux DEBUG et TRACE masquent en-têtes, trames et scope. `Origin` et `Host` restent contrôlés, et `NEXUS_HOST` admet la boucle locale et une adresse du tailnet (ADR-021, détails plus bas). **Exception à ADR-006 (ADR-021) :** quand websockets refuse lui-même une poignée de main mal formée, le corps du 400 recopie l'en-tête reçu, ticket compris. Acceptée, pour trois raisons : l'écho ne va qu'à l'expéditeur, qui détient déjà le ticket ; un navigateur ne peut pas produire cet en-tête, ni le client websockets (seul un client écrit à la main le peut) ; le ticket est à usage unique et vit 30 s au plus. Un test parcourt toutes les routes et échoue si l'une répond sans jeton hors de cette liste (`/api/health` et la documentation OpenAPI), le WebSocket étant refusé sans ticket. L'interface demande le jeton de `loic` sur l'écran « Nexus verrouillé » (VIEWS §9) ; elle le garde en clair dans le `localStorage` du navigateur, jamais affiché ni journalisé. `demo_agent` lit `NEXUS_TOKEN` ou `--token-file`.
- **Contrôle de l'en-tête `Host`** (DNS rebinding, ADR-020 D6) : HTTP comme WebSocket n'admettent que `localhost`, `127.0.0.1` et `::1` (tout port, IPv6 entre crochets compris), les adresses IP de `NEXUS_HOST` (ADR-021 D11) et les noms de `NEXUS_ALLOWED_HOSTS` (liste séparée par des virgules, noms ou adresses seuls, sans port ni joker). Tout autre `Host` reçoit `400` `invalid_host` (le WebSocket est refusé à la poignée de main par une fermeture 1008, que le serveur ASGI transmet au client en HTTP 403), avant toute authentification, sans recopier la valeur.
- **Origines (REST et WebSocket, #47).** Une seule liste, `NEXUS_ALLOWED_ORIGINS` (séparateur `,`, comparaison exacte, `schéma://hôte[:port]` sans chemin, slash final, identifiants ni requête), sert au CORS du REST et à la poignée de main du WebSocket. Le CORS n'admet que `GET`, `POST`, `PATCH`, `PUT`, `DELETE` et les en-têtes `Authorization`, `Content-Type`, `X-Nexus-Actor`, sans `allow_credentials` (le jeton voyage dans `Authorization`, jamais un cookie), pré-vol mis en cache 600 s, `Access-Control-Allow-Private-Network` pour la WebView ; jamais `*`. Une origine non listée reçoit un pré-vol `400` sans `Access-Control-Allow-Origin` ; une requête simple est traitée par l'API mais sa réponse n'est pas lisible par la page ; aucun refus ne recopie l'origine reçue. Le CORS n'est pas un contrôle d'accès (un client hors navigateur l'ignore) : le jeton reste la frontière. Le WebSocket admet en plus les origines de boucle locale et refuse la poignée de main (1008) hors liste. `Host` est contrôlé avant le CORS, pré-vol compris. Pour Tauri, déclarer l'origine exacte de la page (`http://tauri.localhost` sous Windows, `https://tauri.localhost` si `useHttpsScheme`, `tauri://localhost` sous macOS/Linux).
- **Écoute sur le tailnet (ADR-021).** `NEXUS_HOST` est une liste séparée par des virgules (D9, D10) : au plus **une** adresse de la boucle locale (`127.0.0.1`, `localhost` ou `::1`) et **une** adresse IP du tailnet (`100.64.0.0/10` ou `fd7a:115c:a1e0::/48`), sans port, crochets ni zone. `127.0.0.1` est ajouté d'office quand la liste n'a pas d'adresse de boucle locale. Nexus refuse de démarrer, sans recopier la valeur reçue, pour tout le reste : `0.0.0.0`, `::`, une entrée vide, un nom DNS, une adresse du réseau local ou d'une autre plage, une IPv4 écrite dans de l'IPv6, deux adresses du tailnet ou deux de la boucle locale. Un seul serveur sert toutes les écoutes. La boucle locale démarre sans attendre Tailscale, et un échec de bind y reste fatal (sortie 3). L'écoute du tailnet s'ouvre au premier tour d'une tâche de surveillance, qui la retente toutes les 30 s tant qu'elle manque, reprend toute écoute perdue en service (boucle locale comprise) et écrit chaque échec en WARNING **une fois par changement d'état**, sans l'adresse. `nexus-dev` ne sert que la boucle locale et refuse une adresse du tailnet.
  - **Contrôle auprès de Tailscale (obligatoire).** Une adresse de `100.64.0.0/10` peut être celle d'un opérateur (CGNAT) et non celle de Tailscale. Avant chaque bind de l'adresse du tailnet, puis à chaque tour tant qu'elle est servie, Nexus lance `tailscale status --json --peers=false` et exige l'état `Running` et l'adresse parmi celles de ce nœud. Sinon l'écoute ne s'ouvre pas, ou se ferme, et le contrôle échoue fermé : CLI absente, démon injoignable, réponse illisible ou trop lente valent « non confirmée ». Aucun message ne recopie l'adresse, la sortie de Tailscale ni `str(exc)` ; seuls des mots fixes, le type d'une exception et `errno` sont écrits.
  - **Ce que le contrôle ne prouve pas.** Il fait confiance au binaire `tailscale` local (limite d'ADR-020 D5). Il dit que l'adresse appartient à Tailscale au moment du contrôle, pas jusqu'au suivant : une adresse qui change de main reste écoutée **42 s au plus**, et les connexions acceptées avant la fermeture continuent (le jeton et le ticket restent exigés). Surtout, il ne dit rien de l'interface par laquelle arrivent les paquets (ci-dessous).
  - **ACL Tailscale (recommandé).** Limite le port de Nexus aux appareils de Loïc et aux nœuds qui écrivent dans Nexus ; un appareil partagé ou un nœud compromis n'a rien à y faire.
  - **Règle de pare-feu par interface : recommandée, non imposée par le code** (décision du 2026-10-13). Écouter sur `100.x` choisit l'adresse de destination, pas l'interface d'arrivée. Linux applique le modèle d'hôte faible : une socket liée à `100.101.102.103` accepte un paquet destiné à cette adresse arrivé par `wlan0` ou `eth0`. Un pair du réseau local qui ajoute une route vers cette adresse par la machine de Nexus atteint le port **en clair, sans WireGuard ni ACL Tailscale** (`rp_filter` n'y change rien : la source du pair est joignable par l'interface d'arrivée). Les jetons et les tickets protègent toujours les données, mais le port est exposé au réseau local, et un jeton envoyé par ce chemin circulerait en clair. Parade : n'accepter le port que sur `tailscale0` et `lo`, dans une table à part, qui ne suppose ni table `inet filter` ni chaîne `input` existantes (dans nftables, un `accept` d'une chaîne de base laisse le paquet aux autres chaînes du même point d'accroche, un `drop` est définitif). Le script se rejoue sans doublon :

    ```sh
    NEXUS_PORT=8765   # la valeur configurée pour Nexus
    nft -f - <<EOF
    add table inet nexus
    flush table inet nexus
    table inet nexus {
      chain input {
        type filter hook input priority filter; policy accept;
        tcp dport $NEXUS_PORT iifname != { "lo", "tailscale0" } drop
      }
    }
    EOF
    ```

    `iifname` (et non `iif`) admet une interface absente au chargement, comme `tailscale0` avant le démarrage de Tailscale ; `lo` reste nécessaire, car une connexion locale vers sa propre adresse `100.x` passe par `lo`. **Persistance :** enregistre le script dans un fichier (par exemple `/etc/nftables.d/nexus.nft`, avec le port écrit en clair) et ajoute `include "/etc/nftables.d/nexus.nft"` à la fin de `/etc/nftables.conf`, après son éventuel `flush ruleset` ; la table se recharge alors au démarrage.
  - **Windows (Helios).** La documentation de Microsoft (« Strong and Weak Host Models ») indique le modèle d'hôte fort en réception par défaut, sauf pour une interface où `WeakHostReceive` ou le routage (`Forwarding`) est activé (partage de connexion, Hyper-V, WSL, Tailscale en routeur de sous-réseau ou nœud de sortie). Ce n'est pas vérifié sur Helios : la règle est recommandée dans tous les cas, entrante, limitée au port de `NEXUS_PORT` et à l'interface Tailscale, sur tous les profils (l'interface Tailscale n'a pas forcément le profil du réseau de la maison) : `New-NetFirewallRule -DisplayName "Nexus (tailnet)" -Direction Inbound -Protocol TCP -LocalPort <NEXUS_PORT> -InterfaceAlias Tailscale -Profile Any -Action Allow`. La boucle locale n'est pas filtrée par le Pare-feu Windows.
  - **Piège de l'invite « python.exe ».** Au premier lancement, Windows propose d'autoriser `python.exe`, avec le profil **Privé coché par défaut** : accepter crée une règle qui autorise tout port sur toute interface classée Privé, donc le Wi-Fi de la maison s'il l'est, et annule la restriction par interface. Cliquer « Autoriser » avec Privé seul coché crée **aussi** des règles qui **bloquent** `python.exe` sur le profil Public ; si l'interface Tailscale est classée Public, elles l'emportent sur « Nexus (tailnet) » et ferment le tailnet (une règle de blocage l'emporte sur toute règle d'autorisation). Après le premier lancement, liste **toutes** les règles entrantes qui visent `python.exe`, qu'elles autorisent ou bloquent, sans filtre `-Action` : `Get-NetFirewallRule -Direction Inbound | Where-Object { ($_ | Get-NetFirewallApplicationFilter).Program -like '*python*.exe' } | Select-Object DisplayName,Action,Profile,Enabled`, puis désactive-les toutes avec la même commande terminée par `| Disable-NetFirewallRule`. Ne les remplace pas par une règle qui bloque `python.exe` : elle fermerait aussi le tailnet. Évite aussi de fermer l'invite par « Annuler », qui crée des règles de blocage du programme.
  - **Contrôles à faire sur Helios** (non vérifiés ici) : le modèle d'hôte fort (`Get-NetIPInterface | Select-Object InterfaceAlias,AddressFamily,Forwarding,WeakHostReceive`, rien n'en attend le résultat) ; les règles exactes que crée l'invite « python.exe » (actions, profils, protocoles) et le profil de l'interface Tailscale (`Get-NetConnectionProfile -InterfaceAlias Tailscale`) ; la version de la CLI (`tailscale version`) et la sortie de `tailscale status --json --peers=false` (l'option existe depuis la version 1.4 et réduit la sortie à ce nœud depuis la 1.24 ; **repli** si la CLI la refuse : `tailscale status --json`, même lecture et même borne de 5 s) ; la reprise d'une écoute perdue sous la boucle proactor pendant que des connexions acceptées par elle restent ouvertes, dont la WebSocket du proxy Vite (`socket.create_server` ne pose pas `SO_REUSEADDR` sous Windows : si le nouveau bind échoue, l'échec est écrit en WARNING avec son `errno` et l'écoute reste en attente).
- **Matrice appliquée** (`server/src/nexus/permissions.py`, fonctions pures appelées par les services de tâches et d'événements) : trois groupes d'acteurs, **humains** (`loic`), **agents de nœud** (`helios`, `mnema`, `aether`, `artemis`) et **exécutants** (`claude`, `codex`, `orca`, `hermes`). Un refus de droit est un **403** `{"detail": {"code", "message"}}` ; il ne nomme que le champ, jamais la valeur reçue.

| Action | Humain | Agent de nœud | Exécutant | Refus |
|---|---|---|---|---|
| Lire (tous les `GET /api/…` sauf health et la documentation OpenAPI), commenter, joindre une preuve (`POST …/evidence`, sur tout statut : ajout seul), lier ou délier une dépendance, changer de statut sauf `dropped` | ✓ | ✓ | ✓ | aucun refus de droit : 401 seulement, sans jeton valide (la règle d'état, 409 `task_done` pour lier, délier ou changer le statut d'une tâche `done`, relève d'ADR-022 et de DATA-MODEL §3) |
| `POST /api/tasks` : `lead_agent`, `collaborators` | libres | libres | `lead_agent` ∈ {soi, vide}, `collaborators` ⊆ {soi} | 403 `assign_forbidden` |
| `PATCH /api/tasks/<ref>` : `lead_agent`, `collaborators` | libres | libres | seulement ce qui **change** : vers soi, vers un humain ou à personne (`lead_agent`) ; ajouter soi ou un humain (`collaborators`) | 403 `assign_forbidden` |
| `POST …/status` vers `dropped` | ✓ | ✗ | ✗ | 403 `human_only` |
| `POST /api/events` | `actor` = acteur du jeton | idem | idem | 403 `actor_mismatch` |
| effet `claimed` | l'émetteur devient agent principal | idem | idem (il ne désigne que lui-même) | — |
| effet `handoff` | appliqué vers n'importe qui (sauf vers soi-même : 409 `handoff_to_self`, pour tout acteur) | idem | appliqué vers un humain, ou vers l'agent principal actuel quand c'est un autre acteur (seule la prochaine action change ; déjà agent principal, l'exécutant passe par `PATCH`) ; vers un autre agent : événement enregistré, effet non appliqué (`applied: false` + raison) | pas d'erreur de droit (409 `handoff_to_self` vers soi-même) |
| `POST /api/approvals/<ref>/answer`, `/decision` | si destinataire | 409 `not_addressee` | 409 `not_addressee` | inchangé (ADR-019) |

Un changement d'assignation n'est contrôlé que s'il **change** quelque chose : un exécutant peut renommer une tâche menée par un autre agent. Abandonner une tâche (`dropped`) est la « suppression » du produit, donc réservée aux humains : un agent propose l'abandon par un événement `needs_human`. Aucune route ne supprime une tâche, ni ne confie une exécution (ADR-012) ; la future route « confier à » sera réservée aux humains.
- **Limite assumée :** un processus qui tourne sous le compte OS de Loïc peut lire un jeton (fichier, `localStorage`) ou en émettre un avec `nexus-token`. Les jetons arrêtent les pages web, les pairs du tailnet et l'erreur d'un agent qui utilise un autre jeton que le sien ; ils n'arrêtent pas un agent local déterminé à tricher : seule une séparation des comptes OS le ferait.
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
- Phase actuelle : lecture distante uniquement (Tailscale/SSH read-only) ; aucune mutation croisée. Les nœuds **écrivent** dans Nexus par l'API, sur le tailnet, avec leur jeton (ADR-015, ADR-021) : ce n'est pas une mutation croisée.
- Une intervention croisée se demande, se justifie, se sauvegarde, se relit — jamais de modification silencieuse.

## 6. Audit & traçabilité

- L'émission, la dernière utilisation et la révocation d'un jeton sont tracées dans `actor_tokens` (`created_at`, `last_used_at`, `revoked_at`, `label`) : une ligne n'est jamais supprimée, seulement révoquée.
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
- Comptes de messagerie (WhatsApp, Telegram) : aucun mode d'accès qui mette en danger le compte personnel de Loïc sans décision explicite (voir INTEGRATIONS §3, risque de bannissement WhatsApp).
- Toute ouverture réseau entrante (ex. webhook WhatsApp) : limitée à un seul endpoint, signature vérifiée, décision explicite.
- Backups avant mutation (règle Nexus « réversible ») — ex. : sauvegarde config avant toute modification de routing.
- Les dashboards existants gardent leurs propres accès — Nexus ne les contourne pas.

## 9. Ce que Nexus ne fera jamais

- Stocker un secret, même « temporairement » ou « chiffré maison ».
- Envoyer/publier/dépenser sans go explicite.
- Lancer un agent sans action explicite de Loïc.
- Fermer une tâche sans preuve lisible.
- Exposer une surface hors de la machine locale et du tailnet de Loïc (ADR-021 D1) ; jamais `tailscale funnel`.
- Prendre une décision à la place de Loïc (il propose, Loïc tranche).
