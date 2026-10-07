"""The example agent (EVENT-PROTOCOL §6 bis, §6 ter): it can also ask and wait for the decision."""

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


# --- Exit codes and arguments (0 approved/answered, 3 rejected, 1 timeout/expired/network, 2 usage)


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
