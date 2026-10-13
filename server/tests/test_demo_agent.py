"""The example agent (EVENT-PROTOCOL §6 bis, §6 ter): it can also ask and wait for the decision."""

import json

import pytest

from nexus import demo_agent


@pytest.fixture
def http(client, monkeypatch):
    """Route the agent's HTTP calls to the test app."""

    def call(_base, method, path, body=None):
        res = client.request(method, path, json=body)
        if res.status_code >= 400:
            raise SystemExit(f"refusé ({res.status_code}) : {res.json().get('detail')}")
        return res.json()

    monkeypatch.setattr(demo_agent, "call", call)
    return client


@pytest.fixture
def task(client):
    return client.post("/api/tasks", json={"title": "Pont", "objective": "Lire"}).json()["id"]


@pytest.fixture(autouse=True)
def _no_developer_token(monkeypatch):
    """The developer's own NEXUS_TOKEN must not leak into the agent under test."""
    monkeypatch.delenv("NEXUS_TOKEN", raising=False)


def run(*argv, **kwargs):
    return demo_agent.main(["--task", *argv], **kwargs)


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
    assert run(task, "--evidence", "commit:a1b2c3d") == 0
    assert run(task, "--evidence", "commit:d4e5f6a") == 0
    kinds = [e["kind"] for e in http.get("/api/events").json()][::-1]
    assert kinds == ["claimed", "working", "progress", "done", "working", "progress", "done"]


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


@pytest.mark.parametrize("evidence", ["   ", "commit:" + "a" * 600])
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


# --- Jeton d'acteur (#16, ADR-020) : NEXUS_TOKEN ou --token-file, jamais --token ---------------

TOKEN = "nxt_" + "A" * 43  # built at runtime: never a literal token in the repository


@pytest.fixture
def wire(monkeypatch):
    """Capture what the agent really sends: the headers of each request it opens."""
    import io

    sent = []

    def urlopen(request, timeout=None):
        sent.append(request)
        # One body for every request: it reads as an event and as a task (lead, next action).
        body = {"id": "evt_1", "actor_event_id": "x", "kind": "claimed", "effects": [],
                "lead_agent": None, "next_action": "x", "status": "backlog"}
        return io.BytesIO(json.dumps(body).encode())

    monkeypatch.setattr(demo_agent, "_open", urlopen)
    monkeypatch.delenv("NEXUS_TOKEN", raising=False)
    return sent


def test_without_a_token_no_authorization_header_is_sent(wire):
    with pytest.raises(SystemExit):  # the stub read-back does not match: only the headers matter
        run("nx-task-1")

    assert wire and all(r.get_header("Authorization") is None for r in wire)


def test_the_token_of_the_environment_is_sent_as_a_bearer(wire, monkeypatch):
    monkeypatch.setenv("NEXUS_TOKEN", TOKEN)
    with pytest.raises(SystemExit):
        run("nx-task-1")

    assert wire and all(r.get_header("Authorization") == f"Bearer {TOKEN}" for r in wire)


def test_the_token_file_wins_over_the_environment(wire, monkeypatch, tmp_path):
    monkeypatch.setenv("NEXUS_TOKEN", "nxt_" + "B" * 43)
    path = tmp_path / "token"
    path.write_text(TOKEN + "\r\n")  # editors and `echo` add a line end

    with pytest.raises(SystemExit):
        run("nx-task-1", "--token-file", str(path))

    assert wire and all(r.get_header("Authorization") == f"Bearer {TOKEN}" for r in wire)


def test_a_token_reaches_the_server_and_names_the_actor(http, task, tmp_path, monkeypatch):
    """End to end: the header the agent builds is the one the server authenticates."""
    from nexus.auth import tokens

    with http.app.state.sessionmaker() as session:
        _row, issued = tokens.issue(session, "codex", "demo")
        session.commit()
    seen = []

    def call(_base, method, path, body=None):
        seen.append(demo_agent._bearer)
        headers = {"Authorization": f"Bearer {demo_agent._bearer}"}
        res = http.request(method, path, json=body, headers=headers)
        assert res.status_code < 400, res.text
        return res.json()

    monkeypatch.setattr(demo_agent, "call", call)
    path = tmp_path / "token"
    path.write_text(issued)

    assert run(task, "--actor", "codex", "--token-file", str(path)) == 0

    assert set(seen) == {issued}
    assert {e["actor"] for e in http.get("/api/events").json()} == {"codex"}


@pytest.mark.parametrize("content", [
    b"", b"\n", b"contenu-confidentiel-xyz", b"nxt_" + b"A" * 42, b"\xff\xfe\x00",
    b"nxt_" + b"A" * 43 + b"\nautre ligne",
    pytest.param(b"x" * 100_000, id="huge"),  # a long id breaks PYTEST_CURRENT_TEST on Windows
])
def test_a_bad_token_file_is_a_usage_error_that_never_echoes_its_content(
    wire, tmp_path, capsys, content
):
    path = tmp_path / "token"
    path.write_bytes(content)

    with pytest.raises(SystemExit) as exit_:
        run("nx-task-1", "--token-file", str(path))

    err = capsys.readouterr().err
    assert exit_.value.code == 2
    assert "--token-file" in err and "usage" in err.lower()
    assert "confidentiel" not in err and "autre ligne" not in err and "A" * 20 not in err
    assert wire == []  # nothing was sent


def test_a_missing_or_unreadable_token_file_is_a_usage_error(wire, tmp_path, capsys):
    for target in (tmp_path / "absent", tmp_path):  # a missing file, then a directory
        with pytest.raises(SystemExit) as exit_:
            run("nx-task-1", "--token-file", str(target))
        assert exit_.value.code == 2
    err = capsys.readouterr().err
    assert "--token-file" in err and "introuvable ou illisible" in err
    assert wire == []


def test_a_malformed_environment_token_is_a_usage_error_without_echo(wire, monkeypatch, capsys):
    monkeypatch.setenv("NEXUS_TOKEN", "secret-confidentiel-xyz")

    with pytest.raises(SystemExit) as exit_:
        run("nx-task-1")

    err = capsys.readouterr().err
    assert exit_.value.code == 2
    assert "NEXUS_TOKEN" in err and "secret-confidentiel-xyz" not in err
    assert wire == []


def test_an_empty_environment_token_counts_as_absent(wire, monkeypatch):
    monkeypatch.setenv("NEXUS_TOKEN", "")
    with pytest.raises(SystemExit):
        run("nx-task-1")
    assert wire and all(r.get_header("Authorization") is None for r in wire)


@pytest.mark.parametrize("flag", [["--token", TOKEN], [f"--token={TOKEN}"], ["--tok", TOKEN]])
def test_the_token_is_never_accepted_on_the_command_line_nor_echoed(wire, capsys, flag):
    with pytest.raises(SystemExit) as exit_:
        run("nx-task-1", *flag)

    err = capsys.readouterr().err
    assert exit_.value.code == 2
    assert TOKEN not in err and "A" * 20 not in err
    assert "NEXUS_TOKEN" in err and "--token-file" in err
    assert wire == []


@pytest.mark.parametrize("base", [
    "http://nexus.example:8765",
    "http://192.168.1.10:8765",
    "http://10.0.0.5",
    "ftp://127.0.0.1",
    "http://helios.tail1234.ts.net:8765",  # a name: what it resolves to is not checked
])
def test_a_token_is_never_sent_in_clear_to_a_remote_host(wire, monkeypatch, capsys, base):
    monkeypatch.setenv("NEXUS_TOKEN", TOKEN)
    with pytest.raises(SystemExit) as exc:
        run("nx-task-1", "--base", base)

    assert exc.value.code == 2
    assert wire == []  # nothing left the process
    err = capsys.readouterr().err
    assert "--base" in err and TOKEN not in err


@pytest.mark.parametrize("base", [
    "http://127.0.0.1:8765",
    "http://localhost:8765",
    "http://[::1]:8765",
    "http://100.101.102.103:8765",  # Tailscale (WireGuard-encrypted)
    "https://nexus.example",
])
def test_a_token_goes_over_https_loopback_or_tailscale(wire, monkeypatch, base):
    monkeypatch.setenv("NEXUS_TOKEN", TOKEN)
    with pytest.raises(SystemExit):
        run("nx-task-1", "--base", base)

    assert wire and all(r.get_header("Authorization") == f"Bearer {TOKEN}" for r in wire)


def test_without_a_token_a_remote_http_base_stays_allowed(wire):
    with pytest.raises(SystemExit):
        run("nx-task-1", "--base", "http://nexus.example:8765")

    assert wire


def test_a_redirect_is_never_followed_so_the_token_never_leaves(monkeypatch, capsys):
    """urllib would copy Authorization to any redirect target: the agent follows none."""
    import http.server
    import threading

    reached = []

    class Elsewhere(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            reached.append(self.headers.get("Authorization"))
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"{}")

        do_POST = do_GET

        def log_message(self, *args):
            pass

    other = http.server.HTTPServer(("127.0.0.1", 0), Elsewhere)

    class Redirect(Elsewhere):
        def do_GET(self):
            self.send_response(302)
            self.send_header("Location", f"http://127.0.0.1:{other.server_port}/x")
            self.end_headers()

        do_POST = do_GET

    first = http.server.HTTPServer(("127.0.0.1", 0), Redirect)
    for server in (first, other):
        threading.Thread(target=server.serve_forever, daemon=True).start()
    monkeypatch.setenv("NEXUS_TOKEN", TOKEN)
    try:
        with pytest.raises(SystemExit) as exc:
            run("nx-task-1", "--base", f"http://127.0.0.1:{first.server_port}")
    finally:
        first.shutdown()
        other.shutdown()

    assert reached == []
    assert "redirection" in str(exc.value) and TOKEN not in str(exc.value)
    assert TOKEN not in capsys.readouterr().err


@pytest.mark.parametrize("base", ["http://[::1", "http://[evil]"])
def test_an_unparsable_base_with_a_token_is_a_usage_error(wire, monkeypatch, capsys, base):
    monkeypatch.setenv("NEXUS_TOKEN", TOKEN)
    with pytest.raises(SystemExit) as exc:
        run("nx-task-1", "--base", base)

    assert exc.value.code == 2 and wire == []
    assert TOKEN not in capsys.readouterr().err


def test_an_http_proxy_never_sees_the_token():
    """`http_proxy` would carry the request, token included, in clear: plain HTTP goes direct.

    Run in a subprocess so the proxy variables exist before `nexus.demo_agent` is imported."""
    import http.server
    import os
    import subprocess
    import sys
    import threading

    proxied, direct = [], []

    def recorder(seen):
        class Handler(http.server.BaseHTTPRequestHandler):
            def do_POST(self):
                seen.append(self.headers.get("Authorization"))
                self.send_response(500)
                self.end_headers()
                self.wfile.write(b'{"detail": "stop"}')

            do_GET = do_POST  # the agent reads the task first

            def log_message(self, *args):
                pass

        return Handler

    proxy = http.server.HTTPServer(("127.0.0.1", 0), recorder(proxied))
    nexus = http.server.HTTPServer(("127.0.0.1", 0), recorder(direct))
    for server in (proxy, nexus):
        threading.Thread(target=server.serve_forever, daemon=True).start()
    env = {k: v for k, v in os.environ.items() if "proxy" not in k.lower()}
    env |= {"http_proxy": f"http://127.0.0.1:{proxy.server_port}", "no_proxy": "",
            "NEXUS_TOKEN": TOKEN}
    try:
        done = subprocess.run(
            [sys.executable, "-m", "nexus.demo_agent", "--task", "nx-task-1",
             "--base", f"http://127.0.0.1:{nexus.server_port}"],
            env=env, capture_output=True, text=True, timeout=30,
        )
    finally:
        proxy.shutdown()
        nexus.shutdown()

    assert done.returncode != 0  # the stub answers 500
    assert proxied == []
    assert direct == [f"Bearer {TOKEN}"]
    assert TOKEN not in done.stdout + done.stderr


def test_a_401_without_a_token_says_where_to_put_it(monkeypatch):
    import io
    import urllib.error

    def refuse(request, timeout=None):
        body = {"detail": {"code": "auth_required", "message": "jeton porteur attendu"}}
        raise urllib.error.HTTPError(
            request.full_url, 401, "Unauthorized", {}, io.BytesIO(json.dumps(body).encode())
        )

    monkeypatch.setattr(demo_agent, "_open", refuse)
    with pytest.raises(SystemExit, match=r"refusé \(401\).*NEXUS_TOKEN ou --token-file"):
        run("nx-task-1")


def test_a_403_actor_mismatch_says_which_actor_to_pass_without_echoing_the_token(
    monkeypatch, tmp_path
):
    import io
    import urllib.error

    def refuse(request, timeout=None):
        body = {"detail": {"code": "actor_mismatch", "message": "acteur différent du jeton"}}
        raise urllib.error.HTTPError(
            request.full_url, 403, "Forbidden", {}, io.BytesIO(json.dumps(body).encode())
        )

    monkeypatch.setattr(demo_agent, "_open", refuse)
    path = tmp_path / "token"
    path.write_text(TOKEN)
    with pytest.raises(SystemExit) as exc:
        run("nx-task-1", "--actor", "helios", "--token-file", str(path))
    message = str(exc.value)
    assert "refusé (403)" in message and "--actor <acteur du jeton>" in message
    assert TOKEN not in message
