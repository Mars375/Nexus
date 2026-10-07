"""Read API of approvals (#26, PR 1): list, detail, effective status (`expired` is computed)."""

from datetime import UTC, datetime, timedelta, timezone

import pytest
from sqlalchemy import update

from nexus.clock import now
from nexus.models import Approval

AT = "2026-09-28T09:05:00+02:00"


def ask(client, id, kind="question", actor="mnema", **fields):
    body = {"id": id, "at": AT, "actor": actor, "kind": kind, "subject": f"Sujet {id}",
            "needs": ["loic"]} | fields
    res = client.post("/api/events", json=body)
    assert res.status_code == 201, res.text
    return res.json()


def freeze(monkeypatch, instant: datetime) -> None:
    monkeypatch.setattr("nexus.approvals.service.now", lambda: instant)


def set_status(client, ref: str, status: str) -> None:
    with client.app.state.sessionmaker() as session:
        session.execute(
            update(Approval).where(Approval.id == int(ref.removeprefix("nx-appr-")))
            .values(status=status)
        )
        session.commit()


def test_detail_returns_the_request_read_from_the_event(client):
    task = client.post("/api/tasks", json={"title": "Pont", "objective": "Lire"}).json()["id"]
    event = ask(client, "e1", "needs_human", subject="Publier l'épisode ?", body="Version finale",
                task=task,
                payload={"options": ["oui", " non ", "", 3], "consequence": "Mise en ligne"})

    res = client.get("/api/approvals/nx-appr-1")

    assert res.status_code == 200, res.text
    body = res.json()
    assert body == {
        "id": "nx-appr-1", "event": event["id"], "ask_kind": "needs_human",
        "requested_by": "mnema", "subject": "Publier l'épisode ?", "body": "Version finale",
        "options": ["oui", "non"], "consequence": "Mise en ligne", "task": task,
        "status": "pending", "expires_at": None, "decided_by": None, "decided_at": None,
        "response": None, "source": "nexus.db", "measured_at": body["measured_at"],
    }
    assert datetime.fromisoformat(body["measured_at"]).tzinfo is not None


def test_a_question_without_options_or_consequence_reads_empty(client):
    ask(client, "e1")

    body = client.get("/api/approvals/nx-appr-1").json()

    assert body["options"] == []
    assert body["consequence"] is None
    assert body["ask_kind"] == "question"
    assert body["task"] is None


def test_the_secret_masked_in_the_event_stays_masked(client):
    token = "ghp_" + "A" * 36
    ask(client, "e1", subject=f"Clé {token} ?", payload={"consequence": f"avec {token}"})

    res = client.get("/api/approvals/nx-appr-1")

    assert token not in res.text


def test_expires_at_is_returned_as_an_instant(client):
    expires = (now() + timedelta(days=3)).astimezone(UTC).replace(microsecond=0)
    ask(client, "e1", payload={"expires_at": expires.isoformat()})

    body = client.get("/api/approvals/nx-appr-1").json()

    assert datetime.fromisoformat(body["expires_at"]) == expires


def test_pending_becomes_expired_exactly_at_the_deadline(client, monkeypatch):
    received = now()
    expires = (received + timedelta(days=1)).astimezone(UTC)
    ask(client, "e1", payload={"expires_at": expires.isoformat()})

    freeze(monkeypatch, expires - timedelta(microseconds=1))
    assert client.get("/api/approvals/nx-appr-1").json()["status"] == "pending"

    freeze(monkeypatch, expires)
    assert client.get("/api/approvals/nx-appr-1").json()["status"] == "expired"

    freeze(monkeypatch, expires + timedelta(days=400))
    assert client.get("/api/approvals/nx-appr-1").json()["status"] == "expired"


def test_the_deadline_is_compared_as_an_instant_across_offsets(client, monkeypatch):
    ask(client, "e1", payload={"expires_at": (now() + timedelta(days=1))
                               .astimezone(UTC).isoformat()})
    deadline = datetime.fromisoformat(
        client.get("/api/approvals/nx-appr-1").json()["expires_at"]
    )
    # The same instant, written with another offset.
    freeze(monkeypatch, deadline.astimezone(timezone(timedelta(hours=-5))))

    assert client.get("/api/approvals/nx-appr-1").json()["status"] == "expired"


def test_expiry_is_never_written(client, monkeypatch):
    expires = (now() + timedelta(days=1)).astimezone(UTC)
    ask(client, "e1", payload={"expires_at": expires.isoformat()})
    freeze(monkeypatch, expires + timedelta(hours=1))

    client.get("/api/approvals/nx-appr-1")
    client.get("/api/approvals", params={"status": "expired"})

    with client.app.state.sessionmaker() as session:
        assert session.get(Approval, 1).status == "pending"
        assert session.get(Approval, 1).version == 1


def test_a_decided_approval_does_not_expire(client, monkeypatch):
    expires = (now() + timedelta(days=1)).astimezone(UTC)
    ask(client, "e1", payload={"expires_at": expires.isoformat()})
    set_status(client, "nx-appr-1", "approved")
    freeze(monkeypatch, expires + timedelta(days=1))

    assert client.get("/api/approvals/nx-appr-1").json()["status"] == "approved"


def test_the_list_is_newest_first_and_filters_on_the_effective_status(client, monkeypatch):
    soon = (now() + timedelta(hours=1)).astimezone(UTC)
    ask(client, "e1", payload={"expires_at": soon.isoformat()})  # nx-appr-1
    ask(client, "e2")  # nx-appr-2
    ask(client, "e3")  # nx-appr-3
    set_status(client, "nx-appr-3", "answered")
    freeze(monkeypatch, soon)

    def ids(**params):
        return [a["id"] for a in client.get("/api/approvals", params=params).json()]

    assert ids() == ["nx-appr-3", "nx-appr-2", "nx-appr-1"]
    assert ids(status="pending") == ["nx-appr-2"]
    assert ids(status="expired") == ["nx-appr-1"]
    assert ids(status="answered") == ["nx-appr-3"]
    assert ids(status="approved") == []
    assert ids(limit=1) == ["nx-appr-3"]
    assert ids(status="pending", limit=1) == ["nx-appr-2"]


def test_the_limit_applies_after_the_computed_status_filter(client, monkeypatch):
    soon = (now() + timedelta(hours=1)).astimezone(UTC)
    ask(client, "e1")  # nx-appr-1 pending, the only one
    ask(client, "e2", payload={"expires_at": soon.isoformat()})  # nx-appr-2 expired later
    ask(client, "e3", payload={"expires_at": soon.isoformat()})  # nx-appr-3 expired later
    freeze(monkeypatch, soon + timedelta(minutes=1))

    res = client.get("/api/approvals", params={"status": "pending", "limit": 1})

    assert [a["id"] for a in res.json()] == ["nx-appr-1"]


def test_the_list_filters_by_task(client):
    t1 = client.post("/api/tasks", json={"title": "A", "objective": "a"}).json()["id"]
    t2 = client.post("/api/tasks", json={"title": "B", "objective": "b"}).json()["id"]
    ask(client, "e1", task=t1)
    ask(client, "e2", task=t2)
    ask(client, "e3")

    res = client.get("/api/approvals", params={"task": t2})

    assert [a["id"] for a in res.json()] == ["nx-appr-2"]


def test_a_malformed_task_filter_is_refused_without_echo(client):
    res = client.get("/api/approvals", params={"task": "nx-task-²"})

    assert res.status_code == 409
    assert "²" not in res.text


@pytest.mark.parametrize(
    "params",
    [{"status": "withdrawn"}, {"status": "nx-appr-1"}, {"limit": 0}, {"limit": 1001},
     {"limit": "x"}],
)
def test_invalid_query_parameters_are_a_422(client, params):
    res = client.get("/api/approvals", params=params)

    assert res.status_code == 422
    assert "withdrawn" not in res.text


def test_an_empty_list_is_an_empty_array(client):
    res = client.get("/api/approvals")

    assert (res.status_code, res.json()) == (200, [])


@pytest.mark.parametrize(
    "ref",
    ["nx-appr-²", "nx-appr-" + "9" * 5000, "nx-appr-", "nx-appr--1", "nx-appr-1x", "1",
     "nx-task-1", "nx-appr-١", "NX-APPR-1", "nx-appr-" + "1" * 13],
)
def test_a_malformed_reference_is_a_generic_404(client, ref):
    ask(client, "e1")

    res = client.get(f"/api/approvals/{ref}")

    assert res.status_code == 404
    assert res.json()["detail"]["code"] == "not_found"
    assert "²" not in res.text and "9999" not in res.text


def test_an_unknown_reference_is_a_404(client):
    res = client.get("/api/approvals/nx-appr-42")

    assert res.status_code == 404
    assert res.json()["detail"]["message"] == "approbation introuvable : nx-appr-42"


def test_a_leading_zero_reference_reads_the_same_approval(client):
    ask(client, "e1")

    assert client.get("/api/approvals/nx-appr-0001").json()["id"] == "nx-appr-1"


def test_every_list_item_carries_its_provenance(client):
    ask(client, "e1")
    ask(client, "e2")

    for item in client.get("/api/approvals").json():
        assert item["source"] == "nexus.db"
        assert datetime.fromisoformat(item["measured_at"]).tzinfo is not None
