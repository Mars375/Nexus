"""Pure translation of `hermes kanban show --json` into facts (spec §4.2, §4.3, §4.5)."""

from datetime import UTC, datetime

from hermes_support import T0, TASK_ID, event, run_row, show_payload

from nexus.adapters.hermes_translate import GRACE_SECONDS, SEQ_WATCHDOG, translate

NOW = datetime.fromtimestamp(T0 + 60, UTC)
REF = f"hermes:nexus/{TASK_ID}"
PROOF = r"file:C:\x\rapport.md"


def run(show, after=0, proofs=(), now=NOW, max_seconds=3600.0):
    return translate(show, after, proofs=list(proofs), now=now, max_seconds=max_seconds)


def kinds(t):
    return [(e.seq, e.kind) for e in t.events]


def story(*events, **kw):
    return show_payload("running", events=list(events), **kw)


def completed(at=T0 + 5, run_id=1):
    return event("completed", at, {"summary": "fini"}, run_id)


def test_a_whole_story_with_a_proof():
    show = story(event("created"), event("claimed", T0 + 1), event("spawned", T0 + 2, run_id=1),
                 event("heartbeat", T0 + 3, run_id=1), completed(),
                 runs=[run_row(1, "completed", "Rapport écrit")])
    t = run(show, proofs=[PROOF])
    assert kinds(t) == [(2, "claimed"), (3, "working"), (5, "done")]
    assert t.cursor == "5"
    assert t.events[-1].evidence == [PROOF, REF]


def test_a_completion_without_proof_is_a_review_to_read():
    show = story(event("spawned"), completed(),
                 runs=[run_row(1, "completed", "Le résumé du run")])
    t = run(show)
    end = t.events[-1]
    assert end.kind == "review" and end.evidence == [REF]
    assert "Hermes a terminé sans livrable relu" in end.body and "Le résumé du run" in end.body
    assert t.needs_proofs is True


def test_the_cursor_only_returns_what_follows():
    show = story(event("created"), event("claimed"), event("spawned"), event("heartbeat"),
                 completed())
    assert [e.seq for e in run(show, after=3, proofs=[PROOF]).events] == [5]
    assert run(show, after=5).events == ()
    assert run(show, after=5).cursor == "5"


def test_unknown_kinds_and_heartbeats_are_consumed_without_a_fact():
    show = story(event("heartbeat"), event("brand_new_kind_2030"), event("commented"))
    t = run(show)
    assert t.events == () and t.cursor == "3"


def test_a_timeout_then_gave_up_is_progress_then_failed():
    show = story(event("timed_out", payload={"error": "trop long"}),
                 event("gave_up", payload={"trigger_outcome": "timed_out", "error": "trop long"}))
    t = run(show)
    assert kinds(t) == [(1, "progress"), (2, "failed")]
    assert "timed_out" in t.events[-1].payload["cause"] and t.archive is True


def test_blocked_gives_cause_and_plan():
    t = run(story(event("blocked", payload={"kind": "needs_input", "reason": "Quelle clé ?"})))
    end = t.events[-1]
    assert end.kind == "blocked" and end.payload["cause"] == "Quelle clé ?"
    assert end.payload["plan"] and t.archive is True


def test_a_blocked_without_a_usable_reason_has_a_fallback_cause():
    for payload in (None, {"reason": ""}, {"reason": "token=[REDACTED]"}):
        end = run(story(event("blocked", payload=payload))).events[-1]
        assert end.payload["cause"] == "Helios a bloqué la tâche sans dire pourquoi"


def test_hermes_review_is_progress_and_never_a_close():
    show = story(event("spawned"), event("review_requested"),
                 event("changes_requested", payload={"reason": "ajoute un test"}),
                 event("spawned"))
    t = run(show)
    assert [e.kind for e in t.events] == ["working", "progress", "progress", "progress"]
    assert "nouvelle tentative" in t.events[-1].subject
    assert not t.archive


def test_an_archive_nobody_asked_for_is_a_failure():
    end = run(story(event("archived"))).events[-1]
    assert end.kind == "failed" and "archivée dans Hermes" in end.payload["cause"]


def test_a_close_seals_the_story():
    show = story(event("claimed"), event("blocked", payload={"reason": "stop"}),
                 event("spawned"), completed())
    t = run(show)
    assert [e.seq for e in t.events] == [1, 2] and t.cursor == "2"


def test_malformed_events_are_consumed_without_a_fact():
    show = story({"kind": 7, "payload": None, "created_at": T0}, {"kind": "claimed"},
                 {"kind": "spawned", "created_at": T0, "payload": "x"}, "not a dict")
    t = run(show)
    assert t.cursor == "4"
    assert all(isinstance(e.seq, int) for e in t.events)


def test_secrets_are_masked_before_the_cut():
    key = "ghp_" + "A" * 36
    t = run(story(event("blocked", payload={"reason": f"{'x' * 480} {key}"})))
    cause = t.events[-1].payload["cause"]
    assert "ghp_" not in cause and len(cause) <= 500
    review = run(story(completed(), runs=[run_row(1, "completed", f"voici {key}")])).events[-1]
    assert key not in str(review.body)


def test_the_instant_is_the_one_of_hermes_in_utc():
    t = run(story(event("claimed", T0 + 7)))
    assert t.events[0].at == datetime.fromtimestamp(T0 + 7, UTC)
    assert t.events[0].at.tzinfo is not None


def test_watchdog_on_a_task_nobody_took():
    old = datetime.fromtimestamp(T0 + 600 + GRACE_SECONDS + 1, UTC)
    t = run(show_payload("ready"), now=old, max_seconds=600)
    assert kinds(t) == [(SEQ_WATCHDOG, "failed")] and t.archive is True
    assert "n'a pas pris la tâche" in t.events[0].payload["cause"]
    assert t.events[0].at == old


def test_watchdog_on_a_running_task():
    old = datetime.fromtimestamp(T0 + 600 + GRACE_SECONDS + 1, UTC)
    t = run(story(event("claimed"), event("spawned")), now=old, max_seconds=600)
    assert t.events[-1].seq == SEQ_WATCHDOG
    assert "durée maximale dépassée (10 min)" in t.events[-1].payload["cause"]


def test_within_the_delay_nothing_and_a_close_beats_the_watchdog():
    inside = datetime.fromtimestamp(T0 + 600 + GRACE_SECONDS - 1, UTC)
    assert run(story(event("spawned")), now=inside, max_seconds=600).events[-1].kind == "working"
    late = datetime.fromtimestamp(T0 + 10_000, UTC)
    t = run(story(completed()), now=late, max_seconds=600)
    assert SEQ_WATCHDOG not in [e.seq for e in t.events]


def test_native_status():
    gave_up = show_payload("blocked", events=[event("gave_up")], runs=[run_row(1, "gave_up")])
    assert run(gave_up).native_status == "blocked/gave_up"
    done = show_payload("done", events=[completed()], runs=[run_row(1, "completed")])
    assert run(done).native_status == "done/completed"
    assert run(show_payload("ready")).native_status == "ready"
