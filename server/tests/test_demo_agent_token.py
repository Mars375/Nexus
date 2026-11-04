"""The actor token of the example agent (#16, ADR-020): NEXUS_TOKEN or --token-file."""

import json

import demo_agent_support
import pytest
from demo_agent_support import run

from nexus import demo_agent

_no_developer_token = demo_agent_support._no_developer_token
http = demo_agent_support.http
task = demo_agent_support.task


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
