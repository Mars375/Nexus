"""The example agent (EVENT-PROTOCOL 6 bis, 6 ter): it can also ask and wait for the decision."""

import demo_agent_support
import pytest
from demo_agent_support import run

from nexus import demo_agent

_no_developer_token = demo_agent_support._no_developer_token
http = demo_agent_support.http
task = demo_agent_support.task


def test_ask_publishes_a_needs_human_for_loic_with_its_consequence(http, task, capsys):
    code = run(task, "--ask", "Publier l'épisode ?", "--consequence", "Mise en ligne")

    assert code == 0
    [event] = http.get("/api/events", params={"kind": "needs_human"}).json()
    assert event["actor"] == "helios" and event["needs"] == ["loic"]
    assert event["subject"] == "Publier l'épisode ?"
    assert event["payload"]["options"] == ["oui", "non"]
    assert event["payload"]["consequence"] == "Mise en ligne"
    assert "nx-appr-1" in capsys.readouterr().out
    # An ask is only an ask: the claimed -> done story is not played.
    assert [e["kind"] for e in http.get("/api/events").json()] == ["needs_human"]


def test_ask_can_be_a_question_with_its_own_options(http, task):
    run(task, "--ask", "Quel scope ?", "--ask-kind", "question")
    run(task, "--ask", "Quelle option ?", "--option", "a", "--option", "b", "--option", "c")

    kinds = {e["kind"]: e for e in http.get("/api/events").json()}
    assert "options" not in kinds["question"]["payload"]
    assert kinds["needs_human"]["payload"]["options"] == ["a", "b", "c"]


def test_wait_polls_the_approval_until_the_decision(http, task, capsys):
    polls = []

    def sleep(seconds):
        polls.append(seconds)
        if len(polls) == 2:  # Loïc decides while the agent waits
            http.post("/api/approvals/nx-appr-1/decision",
                      json={"decision": "approved", "choice": 1, "note": "go"})

    code = run(task, "--ask", "Publier ?", "--wait", "60", "--interval", "3", sleep=sleep,
               monotonic=lambda: 0.0)

    out = capsys.readouterr().out
    assert code == 0
    assert polls == [3, 3]
    assert "validée par loic" in out and "choix 1" in out and "go" in out


def test_wait_reports_an_answer_text(http, task, capsys):
    def sleep(_seconds):
        http.post("/api/approvals/nx-appr-1/answer", json={"text": "Version 2"})

    code = run(task, "--ask", "Quelle version ?", "--ask-kind", "question", "--wait", "60",
               sleep=sleep, monotonic=lambda: 0.0)

    out = capsys.readouterr().out
    assert code == 0
    assert "répondue par loic" in out and "Version 2" in out


def test_wait_gives_up_at_the_timeout_without_a_decision(http, task, capsys):
    clock = iter([0.0, 5.0, 11.0])

    code = run(task, "--ask", "Publier ?", "--wait", "10", "--interval", "5",
               sleep=lambda _s: None, monotonic=lambda: next(clock))

    assert code == 1
    assert "aucune décision" in capsys.readouterr().out


def test_wait_stops_on_an_expired_request(http, task, monkeypatch):
    from datetime import timedelta

    from nexus.clock import now

    deadline = now() + timedelta(days=1)
    http.post("/api/events", json={
        "id": "e1", "at": now().isoformat(), "actor": "helios", "kind": "question",
        "subject": "Q", "needs": ["loic"], "payload": {"expires_at": deadline.isoformat()}})
    monkeypatch.setattr("nexus.approvals.service.now", lambda: deadline)

    approval = demo_agent.wait_for_decision(
        "", "nx-appr-1", 60, 1, sleep=lambda _s: None, monotonic=lambda: 0.0
    )

    assert approval["status"] == "expired"
    assert demo_agent.report(approval) == 1


def test_a_refused_ask_is_reported_not_swallowed(http, task):
    with pytest.raises(SystemExit, match="refusé"):
        run(task, "--ask", "Publier ?", "--consequence", "x" * 1001)


def test_without_ask_the_agent_plays_the_usual_story(http, task, capsys):
    code = run(task, "--evidence", "commit:a1b2c3d")

    assert code == 0
    assert [e["kind"] for e in http.get("/api/events").json()][::-1] == [
        "claimed", "working", "progress", "done"
    ]
    done = http.get(f"/api/tasks/{task}").json()
    assert done["status"] == "done" and done["lead_agent"] == "helios"
    assert done["evidence"] == ["commit:a1b2c3d"]


def test_a_task_without_next_action_gets_one_before_work_starts(http, task):
    """An active task needs a next action: the agent gives one instead of failing silently."""
    assert http.get(f"/api/tasks/{task}").json()["next_action"] is None
    assert run(task, "--next-action", "Relire le pont", "--evidence", "commit:a1b2c3d") == 0
    after = http.get(f"/api/tasks/{task}").json()
    assert after["status"] == "done" and after["next_action"] == "Relire le pont"


def test_an_existing_next_action_is_kept(http, task):
    http.patch(f"/api/tasks/{task}", json={"next_action": "Garder celle-ci"})
    assert run(task) == 0
    after = http.get(f"/api/tasks/{task}").json()
    assert after["next_action"] == "Garder celle-ci"
    assert after["status"] == "review"  # no evidence: the agent's done waits for Loïc


def test_a_refused_effect_is_a_non_zero_exit_that_names_it(http, task, capsys):
    """An unresolved dependency refuses `in_progress`: the event is recorded, the effect is not."""
    other = http.post("/api/tasks", json={"title": "Avant", "objective": "o"}).json()["id"]
    http.put(f"/api/tasks/{task}/dependencies/{other}")
    code = run(task)
    assert code == demo_agent.EXIT_EFFECT_REFUSED
    out = capsys.readouterr().out
    assert "effet attendu non appliqué" in out and "status:in_progress" in out
    kinds = [e["kind"] for e in http.get("/api/events").json()]
    assert "done" not in kinds  # it stops at the first unmet effect


def test_a_rerun_on_a_task_it_already_leads_does_not_trip_the_noise_rule(http, task):
    """Re-running within NOISE_WINDOW used to stop on a 409 noise for the same `claimed`."""
    http.patch(f"/api/tasks/{task}", json={"next_action": "Reprendre"})
    first = demo_agent.publish("", "helios", task, "claimed", "Je prends la tâche")
    assert first["effects"][0]["applied"] is True
    assert run(task, "--evidence", "commit:a1b2c3d") == 0
    kinds = [e["kind"] for e in http.get("/api/events").json()][::-1]
    assert kinds == ["claimed", "working", "progress", "done"]
    assert http.get(f"/api/tasks/{task}").json()["status"] == "done"


def test_two_full_runs_on_the_same_task_within_the_noise_window_both_succeed(http, task):
    """The second run's progress names its own run: it is a new fact, not noise."""
    # The first run has no evidence: its `done` is recorded as `review` and the task waits for
    # Loïc (a closed task would be final, so a second run could not start on it).
    assert run(task) == 0
    assert http.get(f"/api/tasks/{task}").json()["status"] == "review"
    assert run(task, "--evidence", "commit:d4e5f6a") == 0
    kinds = [e["kind"] for e in http.get("/api/events").json()][::-1]
    assert kinds == ["claimed", "working", "progress", "review", "working", "progress", "done"]
    assert http.get(f"/api/tasks/{task}").json()["status"] == "done"


def test_after_a_refused_working_the_run_is_closed_so_a_rerun_works(http, task, capsys):
    """A recorded `working` whose effect is refused still opens a run: the agent closes it."""
    other = http.post("/api/tasks", json={"title": "Avant", "objective": "o"}).json()["id"]
    http.put(f"/api/tasks/{task}/dependencies/{other}")
    assert run(task) == demo_agent.EXIT_EFFECT_REFUSED
    failed = http.get("/api/events").json()[0]
    assert failed["kind"] == "failed" and failed["run"] == http.get("/api/events").json()[1]["run"]
    assert http.delete(f"/api/tasks/{task}/dependencies/{other}").status_code in (200, 204)
    assert run(task, "--evidence", "commit:a1b2c3d") == 0
    assert http.get(f"/api/tasks/{task}").json()["status"] == "done"


def test_a_refused_done_is_exit_4(http, task, monkeypatch, capsys):
    """The verdict comes from the event's own effects: a refused `done` effect stops the agent."""
    real = demo_agent.publish

    def publish(base, actor, ref, kind, subject, **fields):
        event = real(base, actor, ref, kind, subject, **fields)
        if kind == "done":
            event["effects"] = [{"action": "status:done", "applied": False, "reason": "refus"}]
        return event

    monkeypatch.setattr(demo_agent, "publish", publish)
    assert run(task, "--evidence", "commit:a1b2c3d") == demo_agent.EXIT_EFFECT_REFUSED
    assert "effet attendu non appliqué (status:done : refus)" in capsys.readouterr().out


def test_with_evidence_a_done_left_in_review_is_exit_4(http, task, monkeypatch, capsys):
    """With evidence the expected effect is `done`: `review` would let an orchestrator read 0 as
    « finished » while the task still waits for Loïc."""
    real = demo_agent.publish

    def publish(base, actor, ref, kind, subject, **fields):
        event = real(base, actor, ref, kind, subject, **fields)
        if kind == "done":
            event["effects"] = [{"action": "status:review", "applied": True}]
        return event

    monkeypatch.setattr(demo_agent, "publish", publish)
    assert run(task, "--evidence", "commit:a1b2c3d") == demo_agent.EXIT_EFFECT_REFUSED
    out = capsys.readouterr().out
    assert "effet attendu non appliqué (status:review appliqué, status:done attendu)" in out


def test_without_evidence_the_expected_effect_is_review(http, task, monkeypatch):
    """Without evidence Nexus records the agent's `done` as `review`: that is the expected effect,
    and a `done` effect would not be."""
    real = demo_agent.publish

    def publish(base, actor, ref, kind, subject, **fields):
        event = real(base, actor, ref, kind, subject, **fields)
        if kind == "done":
            event["effects"] = [{"action": "status:done", "applied": True}]
        return event

    monkeypatch.setattr(demo_agent, "publish", publish)
    assert run(task) == demo_agent.EXIT_EFFECT_REFUSED


@pytest.mark.parametrize("next_action", ["", "   ", "[REDACTED]"])
def test_a_blank_next_action_is_a_usage_error_before_anything_is_sent(http, task, next_action):
    with pytest.raises(SystemExit) as exit_:
        run(task, "--next-action", next_action, "--evidence", "commit:a1b2c3d")
    assert exit_.value.code == 2
    assert http.get("/api/events").json() == []
    assert http.get(f"/api/tasks/{task}").json()["next_action"] is None


@pytest.mark.parametrize("evidence", [
    "   ", "commit:" + "a" * 600, "commit:\udcff",
    # Only a label left: Nexus would record the `done` as `review` (secrets.is_blank_reference).
    "commit:", "[REDACTED]", "commit: token=[REDACTED]", "commit: url:",
])
def test_an_unusable_evidence_is_a_usage_error_before_anything_is_sent(http, task, evidence):
    with pytest.raises(SystemExit) as exit_:
        run(task, "--evidence", evidence)
    assert exit_.value.code == 2
    assert http.get("/api/events").json() == []
    assert run(task, "--evidence", "commit:a1b2c3d") == 0


def test_a_request_refused_after_working_closes_the_run(http, task, monkeypatch):
    real = demo_agent.publish

    def publish(base, actor, ref, kind, subject, **fields):
        if kind == "done" and not getattr(publish, "refused", False):
            publish.refused = True
            raise SystemExit("refusé (422) : simulé")
        return real(base, actor, ref, kind, subject, **fields)

    monkeypatch.setattr(demo_agent, "publish", publish)
    with pytest.raises(SystemExit):
        run(task, "--evidence", "commit:a1b2c3d")
    events = http.get("/api/events").json()
    assert events[0]["kind"] == "failed" and events[0]["run"] == events[1]["run"]
    assert run(task, "--evidence", "commit:a1b2c3d") == 0  # nothing left open


def test_a_claimed_without_effect_because_already_lead_is_not_a_failure(http, task, monkeypatch):
    """Someone made this agent lead between its read of the task and its `claimed`."""
    http.patch(f"/api/tasks/{task}", json={"next_action": "x"})
    real = demo_agent.call

    def call(base, method, path, body=None):
        if method == "POST" and path == "/api/events" and body["kind"] == "claimed":
            http.patch(f"/api/tasks/{task}", json={"lead_agent": "helios"})
        return real(base, method, path, body)

    monkeypatch.setattr(demo_agent, "call", call)
    assert run(task, "--evidence", "commit:a1b2c3d") == 0


def test_a_working_refused_by_the_main_operation_rule_stops_at_once(http, task, capsys):
    """« … est déjà en cours … » is a refusal, not « already there »: failed(run), exit 4."""
    other = http.post("/api/tasks", json={"title": "Autre", "objective": "o",
                                          "next_action": "x"}).json()["id"]
    assert http.post(f"/api/tasks/{other}/status",
                     json={"status": "in_progress"}).json()["operation_role"] == "main"
    http.patch(f"/api/tasks/{task}", json={"next_action": "x", "operation_role": "main"})
    assert run(task, "--evidence", "commit:a1b2c3d") == demo_agent.EXIT_EFFECT_REFUSED
    kinds = [e["kind"] for e in http.get("/api/events").json()][::-1]
    assert kinds == ["claimed", "working", "failed"]
    assert "opération principale" in capsys.readouterr().out


def test_nexus_unreachable_after_working_still_tries_to_close_the_run(http, task, monkeypatch):
    real = demo_agent.publish

    def publish(base, actor, ref, kind, subject, **fields):
        if kind == "progress":
            raise OSError("connection reset")
        return real(base, actor, ref, kind, subject, **fields)

    monkeypatch.setattr(demo_agent, "publish", publish)
    with pytest.raises(OSError):
        run(task, "--evidence", "commit:a1b2c3d")
    failed = http.get("/api/events").json()[0]
    assert failed["kind"] == "failed"
    assert failed["payload"]["cause"] == "Nexus injoignable pendant le run"


def test_a_non_json_error_reply_is_a_short_refusal(monkeypatch):
    import io
    import urllib.error

    def urlopen(request, timeout=None):
        body = io.BytesIO(b"Internal Server Error")
        raise urllib.error.HTTPError(request.full_url, 500, "x", {}, body)

    monkeypatch.setattr(demo_agent, "_open", urlopen)
    with pytest.raises(SystemExit, match="réponse illisible"):
        demo_agent.call("http://127.0.0.1:8765", "GET", "/api/tasks/nx-task-1")


def test_a_working_recorded_but_not_read_back_still_closes_the_run(http, task, monkeypatch):
    real = demo_agent.call

    def call(base, method, path, body=None):
        if method == "GET" and path.startswith("/api/events/"):
            kind = http.get(path).json()["kind"]
            if kind == "working":
                raise OSError("connection reset")
        return real(base, method, path, body)

    monkeypatch.setattr(demo_agent, "call", call)
    with pytest.raises(OSError):
        run(task, "--evidence", "commit:a1b2c3d")
    events = http.get("/api/events").json()
    assert [e["kind"] for e in events][:2] == ["failed", "working"]
    assert events[0]["run"] == events[1]["run"]


def test_a_failed_recorded_but_not_read_back_is_not_called_open(http, task, monkeypatch, capsys):
    """The closing `failed` reached Nexus: the run is closed even if its read-back fails."""
    other = http.post("/api/tasks", json={"title": "Avant", "objective": "o"}).json()["id"]
    http.put(f"/api/tasks/{task}/dependencies/{other}")
    real = demo_agent.call

    def call(base, method, path, body=None):
        if method == "GET" and path.startswith("/api/events/"):
            if http.get(path).json()["kind"] == "failed":
                raise OSError("connection reset")
        return real(base, method, path, body)

    monkeypatch.setattr(demo_agent, "call", call)
    assert run(task) == demo_agent.EXIT_EFFECT_REFUSED
    out = capsys.readouterr().out
    assert "reste ouvert" not in out and "relecture impossible" in out
    assert http.get("/api/events").json()[0]["kind"] == "failed"


def test_a_secret_in_next_action_is_not_echoed(http, task, capsys):
    secret = "ghp_" + "A" * 36
    assert run(task, "--next-action", f"publier avec {secret}", "--evidence", "commit:a1") == 0
    assert secret not in capsys.readouterr().out


def test_a_next_action_made_only_of_a_masked_secret_counts_as_absent(http, task):
    http.patch(f"/api/tasks/{task}", json={"next_action": "token=[REDACTED]"})
    assert run(task, "--next-action", "Relire", "--evidence", "commit:a1b2c3d") == 0
    assert http.get(f"/api/tasks/{task}").json()["next_action"] == "Relire"


# --- Exit codes and arguments (0 played/approved/answered, 3 rejected, 1 timeout/expired/network
# or refused request, 2 usage, 4 expected effect not applied)


def decide_in_sleep(http, **body):
    def sleep(_seconds):
        http.post("/api/approvals/nx-appr-1/decision", json=body)

    return sleep


def test_a_rejection_is_not_a_green_light(http, task, capsys):
    code = run(task, "--ask", "Publier ?", "--wait", "60",
               sleep=decide_in_sleep(http, decision="rejected", note="non"),
               monotonic=lambda: 0.0)

    assert code == 3
    assert "refusée par loic" in capsys.readouterr().out


def test_an_approval_is_exit_0(http, task):
    code = run(task, "--ask", "Publier ?", "--wait", "60",
               sleep=decide_in_sleep(http, decision="approved", choice=0), monotonic=lambda: 0.0)

    assert code == 0


@pytest.mark.parametrize("argv", [
    ["--ask", "Q", "--wait", "nan"], ["--ask", "Q", "--wait", "inf"],
    ["--ask", "Q", "--wait", "-1"], ["--ask", "Q", "--wait", "5", "--interval", "0"],
    ["--ask", "Q", "--wait", "5", "--interval", "0.05"],
    ["--ask", "Q", "--wait", "5", "--interval", "nan"],
    ["--ask", "Q", "--wait", "5", "--interval", "inf"],
    ["--ask", "Q", "--wait", "5", "--interval", "-2"],
    ["--ask", ""], ["--ask", "   "],
])
def test_invalid_arguments_are_a_usage_error_without_traceback(http, task, capsys, argv):
    with pytest.raises(SystemExit) as exit_:
        run(task, *argv)

    assert exit_.value.code == 2
    assert "usage" in capsys.readouterr().err.lower()
    assert http.get("/api/events").json() == []  # nothing was published


def test_a_network_error_while_waiting_is_a_short_message_and_exit_1(http, task, monkeypatch,
                                                                    capsys):
    import urllib.error

    real = demo_agent.call

    def flaky(base, method, path, body=None):
        if method == "GET" and path.startswith("/api/approvals/"):
            raise urllib.error.URLError("connection refused")
        return real(base, method, path, body)

    monkeypatch.setattr(demo_agent, "call", flaky)

    code = run(task, "--ask", "Publier ?", "--wait", "60", sleep=lambda _s: None,
               monotonic=lambda: 0.0)

    assert code == 1
    out = capsys.readouterr()
    assert "injoignable" in out.out + out.err
    assert "Traceback" not in out.out + out.err


def test_a_timeout_while_waiting_is_exit_1(http, task, monkeypatch, capsys):
    real = demo_agent.call

    def slow(base, method, path, body=None):
        if method == "GET" and path.startswith("/api/approvals/"):
            raise TimeoutError("timed out")
        return real(base, method, path, body)

    monkeypatch.setattr(demo_agent, "call", slow)

    assert run(task, "--ask", "Publier ?", "--wait", "60", sleep=lambda _s: None,
               monotonic=lambda: 0.0) == 1
