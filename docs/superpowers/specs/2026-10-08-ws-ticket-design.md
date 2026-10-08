# Ticket WebSocket et écoute sur le tailnet — conception (#57)

**Date :** 2026-10-08 · **Statut :** validé par Loïc le 2026-10-08 : D1 à D12 selon les recommandations (a), D10 complétée par une reprise automatique de l'écoute sur le tailnet (§2)
**Sources lues :** AGENTS.md ; DECISIONS (ADR-005, 006, 010, 017, 020 D1 à D9 et ses règles d'application) ; SECURITY §1, §3, §5, §9 ; ARCHITECTURE §3.3, §3.4, §5, §7 ; EVENT-PROTOCOL (authentification, diffusion) ; `docs/agents/review-checklist.md` ; spec temps réel (2026-09-30) et spec ADR-020 (2026-10-07) ; `server/src/nexus/{app,config,hosts,live,logs,__init__}.py`, `auth/{tokens,deps}.py` ; `server/tests/{test_host_check,test_live,test_access_log,test_auth_enforcement}.py` ; `web/src/{api,auth,live,liveUpdates,App}.ts(x)`, `web/vite.config.ts`, `web/playwright.config.ts` ; uvicorn 0.54.0 (`websockets_sansio_impl`), websockets 17.1, Vite 8.3.1 installés.
Il n'existe ni `CONTEXT.md` ni `docs/adr/` : les ADR sont dans `DECISIONS.md` (dernier : ADR-020). Cette conception deviendra **ADR-021**.

## 0. Constat

- `/api/ws` (`live.py:live_updates`) ne contrôle que `Origin` (`origin_allowed`, un `Origin` absent passe) ; `HostCheckMiddleware` contrôle `Host` avant lui. Aucun jeton : le flux (références `nx-task-…`, `nx-evt-…`, `kind`, curseurs, `instance`) est lisible par quiconque atteint le port avec un `Host` admis.
- `Settings.__post_init__` refuse tout `NEXUS_HOST` hors de `localhost`, `127.0.0.1`, `::1` (renvoi à #57). `nexus` et `nexus-dev` lancent uvicorn sur **une** adresse, `access_log=False`, `uvicorn_log_config()`.
- `uvicorn[standard]` choisit `websockets_sansio_impl`. Au niveau INFO, uvicorn écrit `"WebSocket %s"` avec **le chemin et la requête** (`get_path_with_query_string`) ; `WebSocketPathFilter` en retire la requête. **Au niveau DEBUG**, websockets 17 écrit en plus sur `uvicorn.error` la ligne de requête complète (`< GET /api/ws?… HTTP/1.1`) et **chaque en-tête reçu** (`< %s: %s`, `websockets/server.py:631`), puis chaque en-tête envoyé. Aucun filtre ne couvre ces lignes aujourd'hui.
- Côté interface, `liveUpdates.ts` ouvre `new WebSocket(url)` sans protocole ; `live.ts:connectLive` reconnecte avec backoff (0,5 s à 10 s, ±20 %), déclare `unknown` après 30 s, coupe après 45 s de silence. L'application reste montée sous l'écran verrouillé et la connexion temps réel continue (`App.tsx`).
- Le proxy Vite vise `http://127.0.0.1:${NEXUS_PORT}` en dur (`vite.config.ts`), sans `changeOrigin` : `Host: localhost:5173` et `Origin: http://localhost:5173` arrivent au serveur. Ses erreurs WebSocket ne journalisent que la pile (`ws proxy error:`), pas l'URL ; ses erreurs HTTP journalisent l'URL.
- Le `live_instance` est déjà tiré **par processus** (`app.py`) : Nexus suppose déjà un seul processus serveur.
- SECURITY §9 dit « Nexus ne fera jamais : exposer une surface d'administration hors de la machine locale » ; §5 « lecture distante uniquement » ; ARCHITECTURE §3.4 « pas d'exposition publique ». Écouter sur le tailnet touche ces trois phrases (D1).

## 1. Modèle de menace

**Ce qui change en écoutant sur le tailnet.** Le port devient joignable par tout appareil du tailnet que les ACL Tailscale laissent passer : les nœuds (Helios, Cortex, Synapse, Artémis), les autres appareils de Loïc, et tout appareil partagé ou nœud compromis. Le trafic est chiffré de bout en bout par WireGuard : HTTP en clair sur le tailnet ne s'expose pas au réseau local traversé (Wi-Fi). Le REST est déjà fermé par jeton (ADR-020) ; le WebSocket est la seule surface de données encore ouverte. Ce qu'il livre (références, types, curseurs, rythme d'activité) est peu, mais c'est de la donnée interne (SECURITY §2) : elle ne doit pas sortir de la machine sans authentification.

| Menace | Situation | Parade retenue |
|---|---|---|
| Pair du tailnet qui écoute `/api/ws` | ouvert aujourd'hui (seul le bind loopback protège) | ticket obligatoire, obtenu par `POST /api/ws-ticket` avec un jeton porteur |
| Page web malveillante (CSWSH) | pas de cookie : la page ne peut obtenir de ticket sans jeton ; CORS l'empêche de lire une réponse REST | `Origin` gardé en défense en profondeur ; le ticket ne s'obtient que par `Authorization` |
| DNS rebinding | inchangé : `Host` = domaine de l'attaquant | `HostCheckMiddleware` inchangé ; une adresse IP littérale de bind est admise (D11), car une page ne peut pas être servie depuis l'adresse de Nexus |
| Vol du ticket par l'URL | une requête d'URL est journalisée par uvicorn (INFO, filtré), par websockets (DEBUG, non filtré), par tout proxy, et Chrome écrit l'URL complète dans la console quand une connexion échoue | ticket hors de l'URL : en-tête `Sec-WebSocket-Protocol` (D2) |
| Vol par les journaux d'en-têtes | websockets écrit tous les en-têtes au niveau DEBUG | nouveau filtre de journal qui masque les lignes de poignée de main (§3.6), prouvé sur un vrai serveur en DEBUG |
| `Referer`, historique | une connexion WebSocket n'est pas une navigation : pas d'entrée d'historique, et l'URL de la page ne porte rien | rien à faire ; noté pour mémoire |
| Rejeu | un ticket intercepté ou relu dans un journal | usage unique + TTL 30 s (D3) : un ticket consommé ou périmé ne vaut plus rien |
| Course sur l'usage unique (TOCTOU) | deux poignées de main avec le même ticket en parallèle | consommation atomique sous verrou : `pop` du ticket, une seule gagne (§3.3) |
| Plusieurs processus | un ticket émis par le processus A n'existe pas dans B | un seul processus serveur, déjà supposé par `live_instance` ; écrit dans ARCHITECTURE (§3.3) |
| Horloge | saut NTP, mise en veille | TTL mesuré sur `time.monotonic()` **et** sur l'horloge murale : le ticket expire dès que l'une des deux dit 30 s (§3.2) |
| Force brute | deviner un ticket | 256 bits d'entropie ; aucune limite de débit utile |
| Jeton révoqué, socket ouvert | la socket survivrait à la révocation | revérification du jeton à chaque tour de lecture, fermeture 4401 (D6) |
| Épuisement mémoire | un acteur authentifié émet des tickets en boucle | 16 tickets en attente au plus par jeton, le plus ancien est évincé (D4) |
| Exposition à Internet | `tailscale funnel` sur ce port | interdit par SECURITY §9 révisé (D1) ; `tailscale serve` déconseillé (proxy qui peut journaliser) |
| Agent local décidé à tricher | lit le jeton ou en émet un | **limite assumée inchangée** (ADR-020 D5) |

## 2. Décisions (validées par Loïc le 2026-10-08)

**D1 — Portée de l'exposition.** Nexus peut écouter sur le tailnet de Loïc, jamais sur un réseau local ni sur Internet.
- (a) **Recommandé :** tailnet seulement. SECURITY §9 devient « exposer une surface hors de la machine locale et du tailnet de Loïc » ; §5 précise que les nœuds **écrivent** dans Nexus par l'API (ADR-015), ce qui n'est pas une mutation croisée ; ARCHITECTURE §3.4 cite le tailnet. Recommandation de doc : une règle d'ACL Tailscale qui limite le port 8765 aux appareils de Loïc et aux nœuds.
- (b) Tailnet et réseau local (192.168.x) : rien ne le demande, et le Wi-Fi traversé verrait les jetons en clair (pas de TLS).
- (c) Garder la boucle locale pour toujours : #57 se réduit au ticket, les agents des autres nœuds ne publient jamais d'événement.

**D2 — Transport du ticket à la poignée de main.**
- (a) **Recommandé :** `Sec-WebSocket-Protocol`. Le client offre deux sous-protocoles, `new WebSocket(url, ['nexus.live.v1', ticket])` ; le serveur exige exactement ces deux entrées et accepte avec `subprotocol="nexus.live.v1"`, **jamais** le ticket en écho (Chrome rejette une poignée de main qui n'en renvoie aucun quand le client en a offert). Les caractères base64url et `_` sont des `token` HTTP valides. Aucun journal d'uvicorn ni de Vite n'écrit d'en-tête au niveau INFO ; la console de Chrome n'écrit que l'URL. C'est le schéma de Kubernetes (`base64url.bearer.authorization.k8s.io.…`).
- (b) Paramètre de requête `?ticket=` : le plus simple, mais l'URL est ce que tout le monde journalise (uvicorn, proxies, console du navigateur, traces Playwright) ; on dépendrait de `WebSocketPathFilter` pour chaque nouvelle ligne, contre la règle « jamais de requête reçue dans un journal » (checklist §1).
- (c) Premier message après `accept` : écarté par le critère d'acceptation (refus **avant** `accept`).
- (d) Cookie : écarté par ADR-020 D4 (Tauri, CSRF).

**D3 — Format et durée de vie.**
- (a) **Recommandé :** `nxw_` + 43 caractères base64url (32 octets de `secrets.token_bytes`), même forme que `nxt_` pour réutiliser la validation stricte ASCII. TTL **30 s** : couvre une requête REST lente (10 s de délai) puis l'ouverture, sans laisser de fenêtre utile à un vol. Motif `nxw_` ajouté à `nexus/secrets.py` (un ticket collé dans un commentaire est masqué). Pas de règle `.gitleaks.toml` : un ticket vit 30 s et n'est jamais écrit dans un fichier, et toucher `.gitleaks.toml` retire la PR de la fusion par l'agent.
- (b) TTL 10 s : plus court, mais une requête de ticket lente (proxy Vite, machine chargée) échoue sans raison visible.
- (c) TTL 60 s ou 128 bits : sans gain.

**D4 — Stockage.**
- (a) **Recommandé :** en mémoire, dans le processus (`app.state.ws_tickets`, classe `TicketStore`), indexé par l'empreinte SHA-256 du ticket (comme `actor_tokens.token_hash` : un vidage mémoire ou un `repr` ne livre aucun ticket utilisable). Un redémarrage efface les tickets : le client en redemande un, comme il le fait déjà après chaque coupure. **Pas de migration.** Au plus 16 tickets en attente par jeton : le 17ᵉ évince le plus ancien (pas d'erreur, l'interface n'en garde jamais plus d'un). Les tickets périmés sont purgés à chaque émission et consommation.
- (b) Table SQLite `ws_tickets` (migration `0006`, `UPDATE … WHERE used_at IS NULL` atomique) : survit au redémarrage et à plusieurs processus, mais impose une migration, une écriture par connexion et un nettoyage, pour un objet de 30 s. La PR ne serait plus fusionnable par l'agent.

**D5 — Liaison du ticket et contenu du flux.**
- (a) **Recommandé :** le ticket est lié au **jeton** qui l'a demandé (`token_id`, `actor`). À la consommation, le serveur relit la ligne `actor_tokens` : un jeton révoqué entre l'émission et l'usage fait refuser le ticket. Le flux **n'est pas filtré par acteur** : la matrice appliquée (SECURITY §3) donne la lecture de tout à tout acteur authentifié, et le WebSocket ne livre que ce que les `GET` livrent déjà. L'acteur est gardé pour la révocation (D6) et pour un futur périmètre (Artémis, v2, ADR-008).
- (b) Filtrer le flux par acteur : aucune règle de lecture par acteur n'existe à appliquer.

**D6 — Révocation pendant une connexion ouverte.**
- (a) **Recommandé :** la boucle `push` relit `actor_tokens.revoked_at` par clé primaire dans la même session que `changes_since` (une lecture indexée de plus toutes les 250 ms) ; un jeton révoqué ferme la socket avec le code **4401** et la raison fixe « jeton révoqué ». Effet en moins de 0,25 s, cohérent avec « une révocation vaut à la requête suivante » (ADR-020 D2).
- (b) Relire toutes les 15 s, au rythme du `ping` : moins de lectures, révocation tardive.
- (c) Ne rien relire : une socket ouverte avant la révocation reste ouverte jusqu'à sa fin, sans limite.

**D7 — Codes de refus.**
- (a) **Recommandé :** avant `accept`, tout refus (sous-protocoles absents ou mal formés, ticket inconnu, périmé, déjà utilisé, jeton révoqué, `Origin` étrangère, curseur invalide) est une fermeture **1008 sans raison distinctive** ; uvicorn la transmet en HTTP 403, que le navigateur ne voit que comme une fermeture 1006. Les cas sont indiscernables : aucun oracle sur l'existence d'un ticket. Après `accept` : **4401** pour la révocation (D6), les codes existants pour le reste. L'interface n'a pas besoin de distinguer : elle redemande un ticket, et c'est la requête REST qui dit 401.
- (b) Réponses HTTP distinctes à la poignée de main (extension ASGI `websocket.http.response`, 401 vs 403) : utile à une CLI, invisible au navigateur, et crée l'oracle évité en (a).

**D8 — Clients hors navigateur (CLI, agents).**
- (a) **Recommandé :** le ticket seulement. Un agent fait `POST /api/ws-ticket` avec son jeton, puis ouvre le WebSocket avec les mêmes sous-protocoles (`websockets.connect(uri, subprotocols=["nexus.live.v1", ticket])`). Un seul chemin d'authentification à tester. `demo_agent` n'utilise pas le WebSocket : rien à changer.
- (b) Accepter aussi `Authorization: Bearer` à la poignée de main : plus simple pour une CLI, mais deux chemins, et websockets écrit `Authorization` au niveau DEBUG.

**D9 — Valeurs admises pour `NEXUS_HOST`.**
- (a) **Recommandé :** la boucle locale (`127.0.0.1`, `localhost`, `::1`, comme aujourd'hui) et les **adresses IP littérales** des plages Tailscale : `100.64.0.0/10` (IPv4) et `fd7a:115c:a1e0::/48` (IPv6). Refusés : `0.0.0.0`, `::` et toute adresse joker, tout nom DNS (hors `localhost`), toute autre plage (LAN, publique), une adresse avec port, crochets, zone (`%eth0`), forme IPv4 dans IPv6 (`::ffff:100.64.0.1`), chiffres non ASCII ; message générique, sans recopier la valeur (ADR-006). Limite : `100.64.0.0/10` est aussi l'espace CGNAT des opérateurs ; un partage de connexion mobile peut donner une telle adresse hors Tailscale. Le risque est faible (il faut configurer exprès cette adresse) et documenté.
- (b) Toute adresse littérale sauf joker : plus souple, mais un `192.168.x` expose Nexus au Wi-Fi, en clair.
- (c) (a) plus vérification au démarrage que l'adresse appartient à Tailscale (`tailscale ip`, déjà appelé par `nodes`) : lève l'ambiguïté CGNAT, mais lie le démarrage au binaire Tailscale.

**D10 — Boucle locale et tailnet ensemble.** Une écoute sur la seule adresse du tailnet casse l'interface locale (le proxy Vite vise `127.0.0.1` en dur) et empêche Nexus de démarrer si Tailscale n'est pas encore lancé (démarrage automatique, Tauri).
- (a) **Recommandé :** `NEXUS_HOST` devient une liste (`127.0.0.1,100.101.102.103`) : au plus une adresse de boucle locale et une adresse du tailnet ; la boucle locale est toujours écoutée. `nexus` ouvre une socket par adresse et appelle `uvicorn.Server(config).run(sockets=[…])`. Si l'adresse du tailnet n'est pas disponible au démarrage, Nexus journalise un avertissement (sans l'adresse) et sert la boucle locale seule. **Reprise (demandée par Loïc) :** tant que la socket du tailnet manque, Nexus retente de l'ouvrir toutes les 30 s et l'ajoute au serveur dès que Tailscale répond, sans redémarrage ; une coupure de Tailscale pendant le service ne touche jamais la boucle locale. Le succès de la reprise est journalisé une fois, sans l'adresse. `nexus-dev` (rechargement automatique, une seule socket) reste limité à la boucle locale.
- (b) Une seule adresse : l'utilisateur local passe aussi par l'adresse du tailnet (nouvelle variable pour la cible du proxy Vite) ; Nexus est injoignable, même en local, quand Tailscale est arrêté.
- (c) Comme (a), mais refus de démarrer si l'adresse du tailnet manque : plus visible, mais Nexus disparaît pour une panne qui n'est pas la sienne (ARCHITECTURE §6).

**D11 — Couplage avec `NEXUS_ALLOWED_HOSTS`.**
- (a) **Recommandé :** les adresses IP de `NEXUS_HOST` sont admises d'office dans le contrôle de `Host` (forme normalisée de `hosts.normalize_host`) : un `Host` littéral égal à l'adresse d'écoute ne peut pas venir d'un DNS rebinding. Un nom MagicDNS (`helios.<tailnet>.ts.net`) reste à déclarer dans `NEXUS_ALLOWED_HOSTS`.
- (b) Exiger que chaque adresse non loopback de `NEXUS_HOST` figure aussi dans `NEXUS_ALLOWED_HOSTS`, sinon refus de démarrer : explicite, mais c'est une configuration en double qui ne protège de rien.

**D12 — Découpage.**
- (a) **Recommandé :** deux PR après celle de cette conception (§6). Le ticket exigé et son envoi par l'interface vont ensemble : les deux appelants (interface, tests) sont dans ce dépôt, et un ticket « accepté s'il est présent » serait un contournement temporaire sans appelant externe à ménager.
- (b) Trois PR à la manière d'ADR-020 D7 (ticket accepté, puis envoyé, puis exigé) : une fenêtre où le WebSocket reste ouvert sans ticket, pour aucun appelant externe.

## 3. Conception détaillée (sous les recommandations)

### 3.1 Émission : `POST /api/ws-ticket`

- Route du routeur de `live.py`, dépendance `authenticated_token` (nouvelle, dans `auth/deps.py`, qui rend `(token_id, actor)` ; `authenticated_actor` reste et s'appuie dessus ; `tokens.lookup` gagne une variante qui rend la ligne). Mêmes refus qu'ailleurs : 401 `auth_required`, 401 `invalid_token`, 403 `actor_mismatch` (D8, D9 d'ADR-020).
- Pas de corps attendu. Réponse `200` : `{"ticket": "nxw_…", "protocol": "nexus.live.v1", "expires_in": 30}`, en-tête `Cache-Control: no-store`. Ce n'est pas une entité de `nexus.db` : ni `source` ni `measured_at` (le contrat de provenance ne parcourt que les `GET`).
- Le journal d'accès écrit `POST /api/ws-ticket 200 1 ms`, jamais le corps.

### 3.2 `TicketStore` (`server/src/nexus/auth/tickets.py`)

- `issue(token_id, actor) -> str`, `consume(ticket) -> Grant | None` (`Grant` : `token_id`, `actor`). Horloges injectables pour les tests : `monotonic` (défaut `time.monotonic`) et `wall` (défaut `nexus.clock.now`).
- Une entrée garde l'empreinte, `token_id`, `actor`, l'instant monotone et l'instant mural d'émission. Périmée si `monotonic() - m0 >= 30` **ou** si l'horloge murale a avancé de 30 s ou plus ou reculé (veille : `CLOCK_MONOTONIC` de Linux s'arrête pendant la mise en veille, l'horloge murale non). La borne exacte (30,000 s) est refusée.
- `consume` vérifie la forme (`is_well_formed`, `nxw_`) avant tout hachage, puis fait le `pop` de l'empreinte sous un `threading.Lock` (l'émission tourne dans le pool de threads de FastAPI, la consommation dans la boucle asyncio : un `asyncio.Lock` ne suffirait pas). Le ticket est retiré **même s'il est périmé**. La recherche est un accès de dictionnaire par empreinte : le temps qu'elle prend ne renseigne que sur une empreinte, pas sur le ticket.

### 3.3 Poignée de main (`live.py:live_updates`)

Ordre, chaque refus étant une fermeture 1008 avant `accept`, sans raison qui recopie quoi que ce soit :
1. `Host` (middleware, inchangé).
2. `Origin` (inchangé ; le commentaire « client non navigateur, local » devient « client non navigateur : il lui faut quand même un ticket »). Refusé ici, le ticket **n'est pas consommé**.
3. Sous-protocoles : exactement deux entrées, `nexus.live.v1` et un ticket bien formé, sans doublon ; sinon refus.
4. `consume(ticket)` sous verrou ; puis relecture de `actor_tokens` par `token_id` (`asyncio.to_thread`) : révoqué, refus.
5. Curseur (`start_cursor`, inchangé). Refusé ici, le ticket est déjà brûlé : l'usage unique ne dépend d'aucune autre condition.
6. `accept(subprotocol="nexus.live.v1")`, puis `hello` (inchangé).

**Un seul processus.** Les tickets, comme `live_instance`, vivent dans le processus. Nexus se lance par `nexus` (un processus), `nexus-dev` (un processus de travail, relancé au rechargement : les tickets en cours sont perdus, le client en redemande) ou le sidecar Tauri. Lancer uvicorn avec `--workers` n'est pas pris en charge : ARCHITECTURE §3.3 l'écrit.

### 3.4 Connexion ouverte

`read_changes` relit aussi `ActorToken.revoked_at` du `token_id` dans la même session ; révoqué, `push` ferme avec 4401 « jeton révoqué » et s'arrête. Les messages ne changent pas (références, types, curseurs).

### 3.5 Interface

- `web/src/api.ts` : `liveApi.ticket(signal)` = `request<{ticket, protocol, expires_in}>('/api/ws-ticket', { method: 'POST', signal })` ; la réponse est validée (forme `nxw_`, `protocol` attendu) avant usage. Un 401 passe par le chemin existant de `request()` : oubli du jeton refusé, écran « Nexus verrouillé ».
- `web/src/live.ts` : `connectLive` reçoit `ticket: (signal: AbortSignal) => Promise<string>` et `open: (url, protocols) => LiveSocket`. **Avant chaque connexion et chaque reconnexion**, il demande un ticket neuf, ne le garde pas et ne le réutilise jamais. L'URL ne change pas (curseur et `instance` seulement). Le délai de silence (45 s) est armé avant la demande de ticket : une demande qui n'aboutit pas compte comme une poignée de main qui n'aboutit pas.
- Échec de la demande : 401 → aucune socket, aucune nouvelle tentative tant que l'application est verrouillée (plus de boucle de 401 toutes les 10 s) ; au déverrouillage (`markUnlocked`, `onUnlockedElsewhere`), connexion immédiate avec `attempt` remis à zéro. Erreur réseau, délai dépassé, 5xx → backoff existant (`attempt` + 1).
- `stop()` pendant la demande : la requête est annulée (`AbortController`) et aucune socket n'est ouverte ; une réponse tardive est ignorée.
- Fermeture 4401 ou toute autre perte : chemin de reconnexion habituel ; la demande de ticket qui suit reçoit le 401 et verrouille. Le ticket n'est jamais affiché ni écrit dans la console par le code de l'interface.
- Tauri : `new WebSocket(url, protocols)` fonctionne dans WebView2 ; `NEXUS_ALLOWED_ORIGINS` et le CORS de #47 restent nécessaires pour une interface distante (hors de #57).

### 3.6 Journaux

- Nouveau filtre dans `nexus/logs.py`, ajouté par `uvicorn_log_config()` à chaque gestionnaire comme `WebSocketPathFilter` : il masque les enregistrements de poignée de main de websockets (`"< %s %s %s"`, `"< %s: %s"`, `"> %s: %s"`) en remplaçant leurs arguments par `<masqué>` (masquage par position et forme du message, jamais d'après la forme de la valeur, checklist §1). Il couvre le ticket, `Authorization` d'un client non navigateur et le curseur.
- Rien d'autre ne lit le ticket : il n'entre ni dans un 4xx, ni dans `hello`, ni dans la base.

### 3.7 `NEXUS_HOST` et `Host` (PR B)

- `config.py` : `host` devient `hosts: tuple[str, ...]`, lu d'une liste séparée par des virgules ; validation D9 par `ipaddress` (forme normalisée), au plus une boucle locale et une adresse du tailnet, la boucle locale ajoutée d'office si absente. Le message d'erreur ne recopie rien.
- `nexus/__init__.py:main` : une socket par adresse (`socket.create_server`), `uvicorn.Server(Config(..., access_log=False, log_config=uvicorn_log_config())).run(sockets=…)` ; échec de la socket du tailnet → avertissement sur le journal `nexus` sans l'adresse, boucle locale seule, puis une tâche de fond retente l'ouverture toutes les 30 s (D10). uvicorn n'ajoute pas de socket à un serveur lancé : la reprise démarre un second `uvicorn.Server` sur la **même application** et la même boucle d'événements, avec `lifespan="off"` (le lifespan, la base et `live_instance` restent ceux du premier), arrêté avec lui. Les tickets (`app.state`) restent communs aux deux écoutes. `dev()` refuse une adresse non loopback avec un message clair.
- `app.py` : `HostCheckMiddleware(allowed_hosts=settings.allowed_hosts | adresses littérales de NEXUS_HOST)` (D11).

## 4. Cas limites à tester d'abord

- **Ticket, émission.** Sans jeton : 401 `auth_required` ; jeton révoqué : 401 `invalid_token` ; `X-Nexus-Actor` différent : 403. La réponse porte un `nxw_` bien formé, `Cache-Control: no-store`, `protocol` = `nexus.live.v1`. Deux émissions donnent deux tickets différents. Le 17ᵉ ticket d'un même jeton évince le premier (refusé ensuite), pas celui d'un autre jeton.
- **Poignée de main, refus avant `accept` (1008, `WebSocketDisconnect` côté `TestClient`).** Aucun sous-protocole ; `nexus.live.v1` seul ; le ticket seul ; deux tickets ; `nexus.live.v1` en double ; un autre nom de protocole en plus ; ticket de 42 ou 44 caractères, chiffres non ASCII, `nxw_` + 43 caractères avec `=` ; **un jeton `nxt_` présenté comme ticket** ; ticket inconnu ; ticket émis par une autre instance de l'application (redémarrage) ; ticket périmé (horloge injectée : 29,999 s accepté, 30,000 s refusé ; horloge murale reculée ; horloge murale +31 s avec horloge monotone figée, cas de la veille) ; ticket déjà utilisé, y compris après la fermeture de la première socket ; jeton révoqué entre émission et usage. Aucun de ces refus ne recopie une valeur dans la raison.
- **Ordre.** `Origin` étrangère avec un ticket valide : refusée, et le ticket reste utilisable ensuite par une origine admise. Curseur invalide avec un ticket valide : refusé, et le ticket est brûlé.
- **Concurrence.** Sur un vrai serveur uvicorn (`_serve` de `test_host_check.py`), 20 threads ouvrent la poignée de main brute avec le même ticket : exactement une réponse `101`, toutes les autres `403`. Test unitaire du `TicketStore` : 50 `consume` simultanés (barrière de threads), un seul `Grant`.
- **Réponse.** Sur vrai serveur, la réponse 101 porte `Sec-WebSocket-Protocol: nexus.live.v1` et jamais le ticket.
- **Révocation, socket ouverte.** Révoquer le jeton par la base pendant qu'une socket reçoit : fermeture 4401 au tour suivant. Deux jetons du même acteur : seule la socket du jeton révoqué se ferme.
- **Journaux.** Sur vrai serveur, `uvicorn_log_config()` au niveau DEBUG, sortie capturée dans un flux : après une émission, une connexion acceptée, une refusée et une rejouée, ni le ticket, ni son corps sans préfixe, ni son empreinte n'apparaissent. Le test échoue sans le nouveau filtre (prouvé sur l'ancien code, checklist §9).
- **Couverture.** `test_auth_enforcement.py` : `OPEN_WEBSOCKETS` devient vide ; le test vérifie qu'un WebSocket de l'application est refusé sans ticket (au lieu de l'exempter). `test_the_websocket_keeps_origin_and_host_checks_only` s'inverse. Les tests existants de `test_live.py` et `test_host_check.py` passent par une aide `ws_connect(client, …)` qui demande un ticket.
- **`NEXUS_HOST` (PR B).** Admis : `127.0.0.1`, `localhost`, `::1`, `100.64.0.1`, `100.127.255.254`, `fd7a:115c:a1e0::1`, `127.0.0.1,100.101.102.103`, l'adresse du tailnet seule (boucle locale ajoutée). Refusés sans recopie : `0.0.0.0`, `::`, vide, `100.63.255.255`, `100.128.0.0`, `192.168.1.10`, `10.0.0.1`, `fd7a:115c:a1e1::1`, `helios.ts.net`, `100.64.0.1:8765`, `[fd7a:115c:a1e0::1]`, `::ffff:100.64.0.1`, `fe80::1%eth0`, `１００.64.0.1`, `100.64.0.1\n`, deux adresses du tailnet, deux boucles locales. `nexus-dev` avec une adresse du tailnet : refus clair. Une adresse indisponible (injectée) : avertissement et boucle locale servie (vrai serveur) ; puis l'adresse redevient disponible (injectée, horloge de reprise accélérée) : la socket du tailnet est ouverte sans redémarrage et sert la même application, la boucle locale n'ayant jamais cessé de répondre. Deux sockets réelles (`127.0.0.1` et `::1` si IPv6 est disponible, sinon test ignoré) servent la même application.
- **`Host` (PR B).** L'adresse d'écoute en `Host` (`100.101.102.103:8765`, `[fd7a:115c:a1e0::1]:8765`) est admise ; une autre adresse du tailnet ne l'est pas.
- **Interface (Vitest).** Une demande de ticket précède chaque `open`, reconnexions comprises, et chaque `open` reçoit `['nexus.live.v1', ticket]` avec un ticket différent ; l'URL ne contient jamais `nxw_`. 401 sur la demande : aucune socket, aucune nouvelle demande jusqu'au déverrouillage, puis une connexion immédiate. Erreur réseau : backoff croissant. `stop()` pendant la demande : requête annulée, aucune socket. Réponse de ticket mal formée : traitée comme un échec, jamais ouverte. Fermeture 4401 : nouvelle demande de ticket.
- **Bout en bout (Playwright).** Les specs existantes (temps réel compris) passent avec le ticket ; `auth.spec.ts` : un jeton révoqué pendant que l'interface est ouverte la verrouille et la connexion temps réel se ferme. Les traces Playwright contiennent des tickets consommés d'une base jetable : sans valeur, et le hook de pré-commit bloque déjà ces artefacts.

## 5. Documents

- **ADR-021** « Ticket WebSocket et écoute sur le tailnet » (D1 à D12), et une précision à ADR-020 D5 : « le WebSocket exige un ticket depuis ADR-021 ; le bind hors boucle locale est permis dans les limites d'ADR-021 ».
- **SECURITY** : §3 (paragraphe WebSocket réécrit : ticket, sous-protocole, TTL, usage unique, 4401 ; `NEXUS_HOST` et D9 à D11 ; recommandation d'ACL Tailscale), §5 (écriture des nœuds par l'API), §9 (D1).
- **EVENT-PROTOCOL** (authentification et diffusion), **ARCHITECTURE** §3.3 (un seul processus), §3.4, §5, §7 (Tauri : sous-protocoles).
- **Spec temps réel** (2026-09-30) : note sur la connexion par ticket et le code 4401.
- **README / AGENTS.md** : rien pour PR A ; PR B ajoute l'exemple `NEXUS_HOST=127.0.0.1,<adresse tailnet>` au README seulement (AGENTS.md n'est pas touché, pour garder la PR A fusionnable).

## 6. Découpage en PR

0. **`docs/57-ws-ticket-spec`** : ce document seul. Fusion par l'agent possible (aucun fichier protégé), après validation des décisions par Loïc.
1. **`feat/57-ws-ticket`** (PR A) : `auth/tickets.py`, `authenticated_token` dans `auth/deps.py`, `POST /api/ws-ticket` et poignée de main dans `live.py`, revérification du jeton (D6), filtre de journal dans `logs.py`, motif `nxw_` dans `secrets.py` ; interface (`api.ts`, `live.ts`, `liveUpdates.ts`) ; tests serveur, Vitest et Playwright ; docs SECURITY §3 (WebSocket), EVENT-PROTOCOL, ARCHITECTURE §3.3/§3.4/§7, spec temps réel. Le refus du bind hors boucle locale **reste** (son message cite ADR-021 au lieu de #57). Ni migration, ni `DECISIONS.md`, ni `.gitleaks.toml` : fusionnable par l'agent aux conditions d'AGENTS.md. Passe par `architect` (authentification, secrets, concurrence) avant `implementer`.
2. **`feat/57-tailnet-bind`** (PR B, empilée ou après la fusion de A) : `config.py`, `nexus/__init__.py`, `app.py` (D9 à D11), `test_config.py`, tests de vrai serveur, README, SECURITY §3/§5/§9, ARCHITECTURE §3.4/§5, **ADR-021** et précision d'ADR-020 dans `DECISIONS.md`. **Touche `DECISIONS.md` : fusion seulement sur l'accord de Loïc.** Porte `Closes #57` ; PR A porte `Refs #57`.

**Fichiers concernés :** `server/src/nexus/{live,logs,secrets,app,config,__init__}.py`, `server/src/nexus/auth/{tickets,deps,tokens}.py`, `server/tests/{test_ws_ticket,test_live,test_host_check,test_auth_enforcement,test_access_log,test_config}.py`, `web/src/{api,live,liveUpdates}.ts` et leurs tests, `web/e2e/auth.spec.ts`, `docs/{SECURITY,EVENT-PROTOCOL,ARCHITECTURE}.md`, `docs/superpowers/specs/2026-09-30-temps-reel-design.md`, `DECISIONS.md`, `README.md`.

## 7. Risques résiduels

- **Niveau DEBUG** : toute bibliothèque qui écrit ses en-têtes au niveau DEBUG (websockets aujourd'hui, une autre demain) peut contourner le filtre ; le test en DEBUG sur vrai serveur est le garde-fou, à relancer à chaque montée de version d'uvicorn ou de websockets.
- **CGNAT** : une adresse `100.64.0.0/10` qui n'est pas celle de Tailscale passerait D9 (a) ; seule l'option (c) le ferme.
- **HTTP en clair** : sur le tailnet, WireGuard chiffre ; un `tailscale serve` ou un proxy ajouté plus tard journaliserait peut-être les en-têtes ; SECURITY le déconseille.
- **Un seul processus** : un futur déploiement à plusieurs processus devra passer à D4 (b).
- **Interface distante** : un navigateur d'un autre appareil n'appelle pas encore le REST (CORS #47) ; #57 ouvre surtout le tailnet aux agents des autres nœuds.
