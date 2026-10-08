"""Agent d'exemple : joue claimed → working → progress → done + preuve, avec read-back.

    uv run python -m nexus.demo_agent --task nx-task-1 --actor helios --evidence commit:a1b2c3d

Avec un jeton d'acteur (ADR-020), il l'envoie dans `Authorization: Bearer …`. Le jeton vient de la
variable `NEXUS_TOKEN` ou d'un fichier (`--token-file <chemin>`, qui l'emporte) : jamais d'un
argument `--token`, visible dans la liste des processus. Nexus exige un jeton partout : sans lui,
le serveur répond 401 (le jeton de l'acteur `--actor`, émis par `nexus-token issue <acteur>`).

Avec `--ask`, il demande plutôt une validation à Loïc et, avec `--wait`, relit
`GET /api/approvals/<ref>` jusqu'à la décision (EVENT-PROTOCOL §6 ter) :

    uv run python -m nexus.demo_agent --task nx-task-1 --ask "Publier ?" --wait 120

Montre à un agent lancé ailleurs comment se déclarer dans Nexus (EVENT-PROTOCOL, ADR-015 b).
N'utilise que la bibliothèque standard : un agent peut copier ce code tel quel.
"""

from __future__ import annotations

import argparse
import ipaddress
import json
import math
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

from nexus.clock import now

# Exit codes of `--ask --wait`: an agent that reads 0 as « go » must not go after a refusal.
EXIT_NO_ANSWER = 1  # timeout, expired request, or Nexus unreachable
EXIT_USAGE = 2  # invalid arguments: argparse exits with it
EXIT_REJECTED = 3  # Loïc refused
# 0: approved or answered (or, without --wait, asked and not waiting)


MIN_INTERVAL = 0.1  # seconds between two reads of the approval

# `nxt_` + 43 base64url characters (nexus.auth.tokens); spelled out here so the file stays copyable.
_TOKEN_FORMAT = re.compile(r"nxt_[A-Za-z0-9_-]{43}")
_TOKEN_FILE_MAX = 4096  # bytes read: a token file is one short line, never a big file

# The bearer token of the current run, set by `main`. Module state keeps `call`'s signature stable.
_bearer: str | None = None


class TokenError(Exception):
    """The token cannot be used; the message is French and never carries the token or the file."""


def load_token(token_file: str | None, environ=os.environ) -> str | None:
    """The token from `--token-file`, else from `NEXUS_TOKEN`, else None (no authentication)."""
    if token_file is not None:
        try:
            with open(token_file, "rb") as handle:
                raw = handle.read(_TOKEN_FILE_MAX + 1)
        except OSError as err:
            raise TokenError("--token-file : fichier introuvable ou illisible") from err
        if len(raw) > _TOKEN_FILE_MAX:
            raise TokenError("--token-file : le contenu n'est pas un jeton Nexus (nxt_…)")
        try:
            token = raw.decode("ascii").strip()
        except UnicodeDecodeError as err:
            raise TokenError("--token-file : le contenu n'est pas un jeton Nexus (nxt_…)") from err
        source = "--token-file"
    else:
        token, source = environ.get("NEXUS_TOKEN", "").strip(), "NEXUS_TOKEN"
        if not token:
            return None
    if not _TOKEN_FORMAT.fullmatch(token):
        raise TokenError(f"{source} : le contenu n'est pas un jeton Nexus (nxt_…)")
    return token


_TAILNET = ipaddress.ip_network("100.64.0.0/10")


def safe_for_token(base: str) -> bool:
    """Whether a bearer token may travel to `base`: HTTPS, or HTTP to this machine or a
    Tailscale peer given by its 100.64.0.0/10 address (WireGuard encrypts the tailnet). A
    `*.ts.net` name is refused over HTTP: what it resolves to is not checked."""
    try:
        url = urllib.parse.urlsplit(base)
        host = (url.hostname or "").lower()
    except ValueError:  # e.g. an unclosed IPv6 bracket
        return False
    if url.scheme == "https":
        return True
    if url.scheme != "http" or not host:
        return False
    if host == "localhost":
        return True
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return False
    return address.is_loopback or address in _TAILNET


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """urllib copies every header, Authorization included, to any redirect target: follow none."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None  # the 3xx then surfaces as an HTTPError


def _open(request: urllib.request.Request, timeout: float):
    # An `http_proxy` would carry the request, token included, in clear: plain HTTP goes
    # direct. HTTPS may still use `https_proxy`, whose CONNECT tunnel stays encrypted.
    proxies = {k: v for k, v in urllib.request.getproxies().items() if k.lower() != "http"}
    opener = urllib.request.build_opener(_NoRedirect, urllib.request.ProxyHandler(proxies))
    return opener.open(request, timeout=timeout)


def call(base: str, method: str, path: str, body: dict | None = None) -> dict:
    data = json.dumps(body).encode() if body is not None else None
    headers = {"Content-Type": "application/json"}
    if _bearer:
        headers["Authorization"] = f"Bearer {_bearer}"
    request = urllib.request.Request(base + path, data=data, method=method, headers=headers)
    try:
        with _open(request, timeout=10) as res:
            return json.load(res)
    except urllib.error.HTTPError as err:
        if 300 <= err.code < 400:
            message = f"refusé ({err.code}) : redirection non suivie, vérifie --base"
            raise SystemExit(message) from err
        detail = json.load(err).get("detail")
        hint = ""
        if err.code == 401 and not _bearer:
            hint = " — fournis le jeton de l'acteur par NEXUS_TOKEN ou --token-file"
        raise SystemExit(f"refusé ({err.code}) : {detail}{hint}") from err


def publish(base: str, actor: str, task: str, kind: str, subject: str, **fields) -> dict:
    event = {
        "v": 1, "id": f"evt_{actor}_{uuid.uuid4().hex[:12]}", "at": now().isoformat(),
        "actor": actor, "task": task, "kind": kind, "subject": subject,
    } | fields
    created = call(base, "POST", "/api/events", event)
    # Read-back : l'événement n'est publié qu'une fois relu (EVENT-PROTOCOL §6).
    read = call(base, "GET", f"/api/events/{created['id']}")
    if read["actor_event_id"] != event["id"]:
        raise SystemExit(f"read-back incohérent pour {created['id']}")
    effects = ", ".join(
        f"{e['action']} {'appliqué' if e['applied'] else 'refusé : ' + e.get('reason', '')}"
        for e in read["effects"]
    ) or "aucun effet"
    print(f"{read['id']}  {read['kind']:<9} {subject}  ({effects})")
    return read


def ask(base: str, actor: str, task: str, kind: str, subject: str, options: list[str],
        consequence: str) -> str:
    """Ask Loïc and return the approval reference Nexus gives back (the `approval` effect)."""
    payload: dict = {"consequence": consequence}
    if kind == "needs_human":
        payload["options"] = options
    event = publish(base, actor, task, kind, subject, needs=["loic"], payload=payload)
    refs = [e["approval"] for e in event["effects"] if e["action"] == "approval"]
    if not refs:
        raise SystemExit("aucune approbation ouverte : la demande ne vise pas un humain")
    return refs[0]


def wait_for_decision(base: str, ref: str, timeout: float, interval: float,
                      sleep=time.sleep, monotonic=time.monotonic) -> dict:
    """Read the approval until it is no longer `pending`, or until `timeout` seconds."""
    deadline = monotonic() + timeout
    while True:
        approval = call(base, "GET", f"/api/approvals/{ref}")
        if approval["status"] != "pending":
            return approval
        remaining = deadline - monotonic()
        if remaining <= 0:
            return approval
        sleep(min(interval, remaining))


def report(approval: dict) -> int:
    """Say what happened to the request and return the exit code (see EXIT_*)."""
    ref, status, response = approval["id"], approval["status"], approval["response"] or {}
    if status == "pending":
        print(f"{ref}  aucune décision pour l'instant")
        return EXIT_NO_ANSWER
    if status == "expired":
        print(f"{ref}  expirée : l'échéance est passée sans décision")
        return EXIT_NO_ANSWER
    if status == "rejected":
        detail = f" ({response['text']})" if response.get("text") else ""
        print(f"{ref}  refusée par {approval['decided_by']}{detail}")
        return EXIT_REJECTED
    verb = {"approved": "validée", "rejected": "refusée", "answered": "répondue"}[status]
    detail = [f"choix {response['choice']}"] if response.get("choice") is not None else []
    detail += [response["text"]] if response.get("text") else []
    suffix = f" ({' · '.join(detail)})" if detail else ""
    print(f"{ref}  {verb} par {approval['decided_by']}{suffix}")
    return 0


def main(argv: list[str] | None = None, sleep=time.sleep, monotonic=time.monotonic) -> int:
    # No abbreviations: `--token <secret>` must not pass for `--token-file <path>`.
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0], allow_abbrev=False)
    parser.add_argument("--base", default="http://127.0.0.1:8765")
    parser.add_argument("--task", required=True, help="ex. nx-task-1")
    parser.add_argument("--actor", default="helios")
    parser.add_argument("--evidence", default=None, help="preuve de fin, ex. commit:a1b2c3d")
    parser.add_argument("--ask", metavar="SUJET", help="demander une décision à Loïc, sans jouer")
    parser.add_argument("--ask-kind", choices=["needs_human", "question"], default="needs_human")
    parser.add_argument("--option", action="append", dest="options", help="option (répétable)")
    parser.add_argument("--consequence", default="Rien ne change tant que Loïc n'a pas décidé")
    parser.add_argument("--wait", type=float, default=0, metavar="SECONDES",
                        help="relire l'approbation jusqu'à la décision, au plus ce temps")
    parser.add_argument("--interval", type=float, default=2, metavar="SECONDES")
    parser.add_argument("--token-file", metavar="CHEMIN",
                        help="fichier contenant le jeton d'acteur (sinon variable NEXUS_TOKEN)")
    args, unknown = parser.parse_known_args(argv)
    if unknown:  # argparse would echo them, and one of them may be a token
        parser.error("arguments non reconnus (le jeton se passe par NEXUS_TOKEN ou --token-file, "
                     "jamais en argument)")
    global _bearer
    try:
        _bearer = load_token(args.token_file)
    except TokenError as err:
        _bearer = None
        parser.error(str(err))
    if _bearer and not safe_for_token(args.base):
        _bearer = None
        parser.error("--base : le jeton ne part qu'en HTTPS, ou en HTTP vers cette machine "
                     "(localhost, 127.0.0.0/8, ::1) ou une adresse Tailscale (100.64.0.0/10)")
    if args.ask is not None and not args.ask.strip():
        parser.error("--ask : le sujet ne peut pas être vide")
    if not math.isfinite(args.wait) or args.wait < 0:
        parser.error("--wait : un nombre de secondes fini, 0 ou plus")
    if not math.isfinite(args.interval) or args.interval < MIN_INTERVAL:
        parser.error(f"--interval : un nombre de secondes fini, au moins {MIN_INTERVAL}")

    if args.ask is not None:
        ref = ask(args.base, args.actor, args.task, args.ask_kind, args.ask,
                  args.options or ["oui", "non"], args.consequence)
        print(f"{ref}  en attente de Loïc")
        if not args.wait:
            return 0
        try:
            approval = wait_for_decision(args.base, ref, args.wait, args.interval, sleep, monotonic)
        except OSError as err:  # URLError and timeouts: Nexus is unreachable, say it briefly
            print(f"{ref}  Nexus injoignable pendant l'attente ({type(err).__name__})")
            return EXIT_NO_ANSWER
        return report(approval)

    publish(args.base, args.actor, args.task, "claimed", "Je prends la tâche")
    # working ouvre le run : c'est lui qui fait passer la tâche en cours (EVENT-PROTOCOL §3).
    run_ref = f"demo:{uuid.uuid4().hex[:8]}"
    publish(args.base, args.actor, args.task, "working", "Je commence",
            payload={"run_ref": run_ref})
    publish(args.base, args.actor, args.task, "progress", "À mi-chemin", payload={"percent": 50})
    evidence = [args.evidence] if args.evidence else []
    # Chaque clôture nomme son run : sans lui, Nexus ne peut pas savoir quel run elle termine.
    publish(args.base, args.actor, args.task, "done", "Terminé", evidence=evidence, run=run_ref)
    return 0


if __name__ == "__main__":
    sys.exit(main())
