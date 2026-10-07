"""Agent d'exemple : joue claimed → working → progress → done + preuve, avec read-back.

    uv run python -m nexus.demo_agent --task nx-task-1 --actor helios --evidence commit:a1b2c3d

Avec `--ask`, il demande plutôt une validation à Loïc et, avec `--wait`, relit
`GET /api/approvals/<ref>` jusqu'à la décision (EVENT-PROTOCOL §6 ter) :

    uv run python -m nexus.demo_agent --task nx-task-1 --ask "Publier ?" --wait 120

Montre à un agent lancé ailleurs comment se déclarer dans Nexus (EVENT-PROTOCOL, ADR-015 b).
N'utilise que la bibliothèque standard : un agent peut copier ce code tel quel.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import time
import urllib.error
import urllib.request
import uuid

from nexus.clock import now

# Exit codes of `--ask --wait`: an agent that reads 0 as « go » must not go after a refusal.
EXIT_NO_ANSWER = 1  # timeout, expired request, or Nexus unreachable
EXIT_USAGE = 2  # invalid arguments: argparse exits with it
EXIT_REJECTED = 3  # Loïc refused
# 0: approved or answered (or, without --wait, asked and not waiting)


MIN_INTERVAL = 0.1  # seconds between two reads of the approval


def call(base: str, method: str, path: str, body: dict | None = None) -> dict:
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(
        base + path, data=data, method=method, headers={"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as res:
            return json.load(res)
    except urllib.error.HTTPError as err:
        detail = json.load(err).get("detail")
        raise SystemExit(f"refusé ({err.code}) : {detail}") from err


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
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
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
    args = parser.parse_args(argv)
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
