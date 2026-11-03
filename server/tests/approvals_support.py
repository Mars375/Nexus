"""Shared helpers for the approval answer and decision tests (#26, PR 2)."""

from datetime import UTC, timedelta

from nexus.clock import now
from nexus.models import Approval

AT = "2026-09-28T09:05:00+02:00"
TOKEN = "ghp_" + "A" * 36  # built at runtime: never a literal secret in the repository
REF = "nx-appr-1"


def ask(client, id="e1", kind="question", actor="mnema", **fields):
    body = {"id": id, "at": AT, "actor": actor, "kind": kind, "subject": f"Sujet {id}",
            "needs": ["loic"]} | fields
    if kind == "needs_human":
        body["payload"] = {"options": ["oui", "non"], "consequence": "Publie l'épisode"} | (
            fields.get("payload") or {}
        )
    res = client.post("/api/events", json=body)
    assert res.status_code == 201, res.text
    return res.json()


def headers(actor):
    return {"X-Nexus-Actor": actor} if actor else {}


def answer(client, ref=REF, actor=None, **body):
    return client.post(f"/api/approvals/{ref}/answer", json=body or {"text": "Version 2"},
                       headers=headers(actor))


def decide(client, ref=REF, actor=None, **body):
    return client.post(f"/api/approvals/{ref}/decision", json=body, headers=headers(actor))


def code_of(res, status=409):
    assert res.status_code == status, res.text
    return res.json()["detail"]["code"] if status == 409 else res.json()


def answer_events(client):
    return client.get("/api/events", params={"kind": "answer"}).json()


def approval_row(client, number=1):
    with client.app.state.sessionmaker() as session:
        row = session.get(Approval, number)
        return row.status, row.response_event_id, row.version


def untouched(client, number=1):
    """Nothing stored: no answer event, approval still pending, version never bumped."""
    assert answer_events(client) == []
    assert approval_row(client, number) == ("pending", None, 1)


def freeze(monkeypatch, instant):
    monkeypatch.setattr("nexus.approvals.service.now", lambda: instant)


def in_a_day():
    return (now() + timedelta(days=1)).astimezone(UTC)
