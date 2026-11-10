"""`GET /api/tasks/{ref}/timeline` (ADR-023, lot E): one story per card, in order of time."""

from datetime import UTC, datetime, timedelta

from events_support import AT, publish
from runs_support import dispatch, make_task, register, tick

from nexus.models import Event, TaskHistory

T0 = datetime(2026, 11, 10, 9, 0, tzinfo=UTC)


def timeline(client, ref, **params):
    res = client.get(f"/api/tasks/{ref}/timeline", params=params)
    assert res.status_code == 200, res.text
    return res.json()


def walk(client, ref, limit):
    """Every entry, page by page, newest first."""
    out, cursor = [], None
    while True:
        page = timeline(client, ref, limit=limit, **({"before": cursor} if cursor else {}))
        out += page["entries"]
        cursor = page["next_cursor"]
        if cursor is None:
            return out


def task(client):
    res = client.post("/api/tasks", json={"title": "Pont", "objective": "Lire", "next_action": "x"})
    assert res.status_code == 201, res.text
    return res.json()["id"]


def insert(client, rows):
    with client.app.state.sessionmaker() as s:
        s.add_all(rows)
        s.commit()


def hist(at, n):
    return TaskHistory(task_id=1, actor="loic", at=at, action="updated", changes={"title": [n, n]})


def evt(at, n, kind="progress"):
    return Event(
        actor="helios", actor_event_id=f"e{n}", at=at, received_at=at, task_id=1, run_ref=None,
        kind=kind, subject=f"fait {n}", body=None, payload={}, evidence=[], needs=[], redacted=[],
        origin="api", effects=[])


def test_the_story_merges_history_events_and_runs_newest_first(client):
    register(client)
    ref = make_task(client)
    dispatch(client, ref)
    tick(client)  # claimed, working, done with a commit as proof

    page = timeline(client, ref)

    kinds = [(e["kind"], e.get("event_kind") or e.get("action")) for e in page["entries"]]
    assert page["source"] == "nexus.db" and page["measured_at"] and page["next_cursor"] is None
    assert all(e["source"] == "nexus.db" and e["measured_at"] for e in page["entries"])
    assert ("run_ended", None) in [(k, None) for k, _ in kinds]
    assert [k for k, _ in kinds].count("run_started") == 1
    events = [e for e in reversed(page["entries"]) if e["kind"] == "event"]
    assert [e["event_kind"] for e in events] == ["claimed", "working", "done"]
    assert events[-1]["evidence"][0].startswith("commit:") and events[0]["run"] == "nx-run-1"
    assert events[0]["origin"] == "fake" and events[0]["actor"] == "codex"
    ats = [e["at"] for e in page["entries"]]
    assert ats == sorted(ats, key=datetime.fromisoformat, reverse=True)


def test_equal_instants_keep_a_stable_order(client):
    task(client)
    same = T0 + timedelta(hours=1)
    insert(client, [evt(same, 1), hist(same, 2), evt(same, 3), hist(same, 4)])

    def label(e):
        return e.get("subject") or str((e["changes"] or {}).get("title", [""])[0])

    first = [label(e) for e in timeline(client, "nx-task-1")["entries"]]
    again = [label(e) for e in timeline(client, "nx-task-1")["entries"]]

    assert first == again
    # events rank above history at equal instants, and the higher id comes first within a kind
    tied = [x for x in first if x in ("fait 1", "fait 3", "2", "4")]
    assert tied == ["fait 3", "fait 1", "4", "2"]


def test_pages_have_no_duplicate_and_no_hole(client):
    task(client)
    insert(client, [evt(T0 + timedelta(minutes=n), n) for n in range(1, 8)])
    full = [e["id"] for e in walk(client, "nx-task-1", 100)]

    paged = [e["id"] for e in walk(client, "nx-task-1", 3)]

    assert paged == full and len(set(paged)) == len(paged)


def test_an_event_arriving_between_two_pages_is_neither_doubled_nor_lost(client):
    task(client)
    insert(client, [evt(T0 + timedelta(minutes=n), n) for n in range(1, 8)])
    first = timeline(client, "nx-task-1", limit=3)

    # an old fact arrives late (older than the page boundary) and a new one arrives (newer)
    insert(client, [evt(T0 - timedelta(days=1), 100), evt(T0 + timedelta(days=1), 101)])
    rest, cursor = [], first["next_cursor"]
    while cursor:
        page = timeline(client, "nx-task-1", limit=3, before=cursor)
        rest += page["entries"]
        cursor = page["next_cursor"]

    ids = [e["id"] for e in first["entries"] + rest]
    subjects = [e.get("subject") for e in first["entries"] + rest]
    assert len(set(ids)) == len(ids)  # no duplicate
    assert "fait 100" in subjects  # the late old fact is in a later page: no hole
    assert "fait 101" not in subjects  # the new one is for a refresh of the first page
    refreshed = [e.get("subject") for e in timeline(client, "nx-task-1", limit=3)["entries"]]
    assert "fait 101" in refreshed


def test_an_unknown_task_is_404_and_a_bad_cursor_is_422(client):
    assert client.get("/api/tasks/nx-task-99/timeline").status_code == 404
    task(client)
    res = client.get("/api/tasks/nx-task-1/timeline", params={"before": "n'importe quoi"})
    assert (res.status_code, res.json()["detail"]["code"]) == (422, "invalid_cursor")
    assert client.get("/api/tasks/nx-task-1/timeline", params={"limit": 0}).status_code == 422
    assert client.get("/api/tasks/nx-task-1/timeline", params={"limit": 1000}).status_code == 422


def test_a_secret_in_an_event_never_comes_out(client):
    ref = task(client)
    secret = "ghp_" + "A" * 36
    publish(client, "progress", "sujet", task=ref, body=f"j'ai trouvé {secret}")

    text = client.get(f"/api/tasks/{ref}/timeline").text

    assert secret not in text and "[REDACTED]" in text


def test_an_effect_that_was_not_applied_says_why(client):
    ref = task(client)
    res = client.post("/api/events", json={
        "id": "h1", "at": AT, "actor": "codex", "kind": "handoff", "subject": "À toi", "task": ref,
        "needs": ["helios"], "payload": {"next_action": "reprendre"}, "run": "r1",
    })
    assert res.status_code == 201

    [handoff] = [e for e in timeline(client, ref)["entries"] if e.get("event_kind") == "handoff"]

    [effect] = handoff["effects"]
    assert effect["applied"] is False and effect["reason"]


def test_an_agent_may_read_the_story(client):
    ref = task(client)
    res = client.get(f"/api/tasks/{ref}/timeline", headers={"X-Nexus-Actor": "helios"})
    assert res.status_code == 200
