"""Agent d'exemple : joue claimed → working → progress → done + preuve, avec read-back.

    uv run python -m nexus.demo_agent --task nx-task-1 --actor helios --evidence commit:a1b2c3d

Montre à un agent lancé ailleurs comment se déclarer dans Nexus (EVENT-PROTOCOL, ADR-015 b).
N'utilise que la bibliothèque standard : un agent peut copier ce code tel quel.
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
import uuid

from nexus.clock import now


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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--base", default="http://127.0.0.1:8765")
    parser.add_argument("--task", required=True, help="ex. nx-task-1")
    parser.add_argument("--actor", default="helios")
    parser.add_argument("--evidence", default=None, help="preuve de fin, ex. commit:a1b2c3d")
    args = parser.parse_args(argv)

    publish(args.base, args.actor, args.task, "claimed", "Je prends la tâche")
    # working ouvre le run : c'est lui qui fait passer la tâche en cours (EVENT-PROTOCOL §3).
    run_ref = f"demo:{uuid.uuid4().hex[:8]}"
    publish(args.base, args.actor, args.task, "working", "Je commence",
            payload={"run_ref": run_ref})
    publish(args.base, args.actor, args.task, "progress", "À mi-chemin", payload={"percent": 50})
    evidence = [args.evidence] if args.evidence else []
    publish(args.base, args.actor, args.task, "done", "Terminé", evidence=evidence)
    return 0


if __name__ == "__main__":
    sys.exit(main())
