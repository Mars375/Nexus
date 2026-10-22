"""CLI nexus-token (#16, ADR-020)."""

import re
import sqlite3
from datetime import datetime

import pytest
from alembic import command

from nexus import migrate
from nexus.auth import cli, tokens
from nexus.clock import TZ

TOKEN_RE = re.compile(r"nxt_[A-Za-z0-9_-]{43}")


@pytest.fixture
def env(settings, monkeypatch):
    monkeypatch.setenv("NEXUS_DATA_DIR", str(settings.data_dir))
    settings.data_dir.mkdir(parents=True)
    migrate.upgrade(settings.db_url)
    return settings


def run(capsys, *argv):
    code = cli.main(list(argv))
    out = capsys.readouterr()
    return code, out.out, out.err


def test_issue_prints_only_the_token_on_stdout(env, capsys):
    code, out, err = run(capsys, "issue", "helios", "--label", "poste de Loïc")
    assert code == 0
    assert TOKEN_RE.fullmatch(out.strip())
    assert out.count("\n") == 1
    assert "nx-tok-1" in err and "helios" in err
    assert out.strip() not in err  # guidance never repeats the token


def test_the_issued_token_is_valid_and_only_its_digest_is_stored(env, capsys):
    _, out, _ = run(capsys, "issue", "codex", "--label", "cli")
    token = out.strip()
    conn = sqlite3.connect(env.db_path)
    rows = conn.execute("SELECT actor, label, token_hash FROM actor_tokens").fetchall()
    conn.close()
    assert rows == [("codex", "cli", tokens.digest(token))]
    raw = env.db_path.read_bytes()
    assert token.encode() not in raw


def test_list_shows_refs_but_never_token_or_hash(env, capsys):
    _, t1, _ = run(capsys, "issue", "loic", "--label", "navigateur")
    _, t2, _ = run(capsys, "issue", "claude", "--label", "session")
    run(capsys, "revoke", "nx-tok-2")
    code, out, err = run(capsys, "list")
    assert code == 0
    assert "nx-tok-1" in out and "nx-tok-2" in out
    assert "loic" in out and "navigateur" in out and "claude" in out
    for token in (t1.strip(), t2.strip()):
        digest = tokens.digest(token)
        for secret in (token, token[:8], token[4:12], digest, digest[:8]):
            assert secret not in out and secret not in err
    revoked_line = next(line for line in out.splitlines() if "nx-tok-2" in line)
    active_line = next(line for line in out.splitlines() if "nx-tok-1" in line)
    assert "révoqué" not in active_line
    assert re.search(r"\d{4}-\d{2}-\d{2}", revoked_line.split("session")[1].split("  ", 1)[-1])


def test_list_when_empty(env, capsys):
    code, out, _ = run(capsys, "list")
    assert code == 0 and "aucun" in out.lower()


def test_list_shows_jamais_for_a_fresh_token(env, capsys):
    run(capsys, "issue", "loic", "--label", "navigateur")
    code, out, _ = run(capsys, "list")
    assert code == 0
    line = next(line for line in out.splitlines() if "nx-tok-1" in line)
    assert "dernière utilisation jamais" in line


def test_list_shows_the_last_use_timestamp(env, capsys):
    run(capsys, "issue", "loic", "--label", "navigateur")
    stored = "2026-10-18T21:04:00+00:00"
    conn = sqlite3.connect(env.db_path)
    conn.execute("UPDATE actor_tokens SET last_used_at = ? WHERE id = 1", (stored,))
    conn.commit()
    conn.close()
    code, out, _ = run(capsys, "list")
    assert code == 0
    line = next(line for line in out.splitlines() if "nx-tok-1" in line)
    expected = datetime.fromisoformat(stored).astimezone(TZ).strftime("%Y-%m-%d %H:%M %z")
    assert f"dernière utilisation {expected}" in line
    assert "jamais" not in line


def test_list_tells_the_two_hours_of_the_autumn_fall_back_apart(env, capsys):
    run(capsys, "issue", "loic", "--label", "premier")
    run(capsys, "issue", "loic", "--label", "second")
    conn = sqlite3.connect(env.db_path)
    # 2026-10-25: 02:15 exists twice in Europe/Paris, one hour apart on the UTC timeline.
    conn.execute("UPDATE actor_tokens SET last_used_at = '2026-10-25T00:15:00+00:00' WHERE id = 1")
    conn.execute("UPDATE actor_tokens SET last_used_at = '2026-10-25T01:15:00+00:00' WHERE id = 2")
    conn.commit()
    conn.close()
    code, out, _ = run(capsys, "list")
    assert code == 0
    first = next(line for line in out.splitlines() if "nx-tok-1" in line)
    second = next(line for line in out.splitlines() if "nx-tok-2" in line)
    assert "02:15 +0200" in first  # CEST side (00:15Z)
    assert "02:15 +0100" in second  # CET side (01:15Z), an hour later


def test_list_shows_the_offset_of_created_and_revoked_timestamps(env, capsys):
    run(capsys, "issue", "loic", "--label", "navigateur")
    conn = sqlite3.connect(env.db_path)
    # 2026-10-25: 02:15 exists twice in Europe/Paris, one hour apart on the UTC timeline.
    conn.execute(
        "UPDATE actor_tokens SET created_at = '2026-10-25T00:15:00+00:00', "
        "revoked_at = '2026-10-25T01:15:00+00:00' WHERE id = 1"
    )
    conn.commit()
    conn.close()
    code, out, _ = run(capsys, "list")
    assert code == 0
    line = next(line for line in out.splitlines() if "nx-tok-1" in line)
    assert "créé 2026-10-25 02:15 +0200" in line
    assert "révoqué 2026-10-25 02:15 +0100" in line


def test_list_never_shows_the_token_or_its_digest_after_a_use(env, capsys):
    _, issued, _ = run(capsys, "issue", "loic", "--label", "navigateur")
    token = issued.strip()
    conn = sqlite3.connect(env.db_path)
    conn.execute("UPDATE actor_tokens SET last_used_at = '2026-10-18T21:04:00+00:00' WHERE id = 1")
    conn.commit()
    conn.close()
    code, out, err = run(capsys, "list")
    assert code == 0
    for secret in (token, token[:8], token[4:12], tokens.digest(token), tokens.digest(token)[:8]):
        assert secret not in out and secret not in err


def test_revoke_then_again_is_idempotent(env, capsys):
    run(capsys, "issue", "loic", "--label", "x")
    code, _, err = run(capsys, "revoke", "nx-tok-1")
    assert code == 0 and "révoqué" in err.lower() + _
    code, out, err = run(capsys, "revoke", "nx-tok-1")
    assert code == 0
    assert "déjà" in (out + err)


def test_revoke_unknown_or_malformed_ref_is_an_error_that_does_not_echo(env, capsys):
    for ref in ("nx-tok-99", "3", "ghp_" + "A" * 36, "nx-tok-" + "9" * 5000):
        code, out, err = run(capsys, "revoke", ref)
        assert code == 1
        assert ref not in out + err
        assert err.strip()


def test_issue_refuses_unknown_actor_and_bad_label(env, capsys):
    code, out, err = run(capsys, "issue", "mallory", "--label", "x")
    assert code == 1 and out == "" and "acteur inconnu" in err and "mallory" not in err
    code, out, err = run(capsys, "issue", "loic", "--label", "   ")
    assert code == 1 and out == "" and err.strip()
    code, out, err = run(capsys, "issue", "loic", "--label", "ghp_" + "A" * 36)
    assert code == 1 and out == "" and "ghp_" not in err


def test_refuses_a_database_not_at_head_and_does_not_migrate(settings, monkeypatch, capsys):
    monkeypatch.setenv("NEXUS_DATA_DIR", str(settings.data_dir))
    settings.data_dir.mkdir(parents=True)
    command.upgrade(migrate.alembic_config(settings.db_url), "0004")
    for argv in (["list"], ["issue", "loic", "--label", "x"], ["revoke", "nx-tok-1"]):
        code, out, err = run(capsys, *argv)
        assert code == 1 and out == ""
        assert "Nexus" in err and "démarr" in err
    conn = sqlite3.connect(settings.db_path)
    assert conn.execute("SELECT version_num FROM alembic_version").fetchone() == ("0004",)
    assert "actor_tokens" not in {
        r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }
    conn.close()


def test_refuses_when_there_is_no_database_and_creates_none(settings, monkeypatch, capsys):
    monkeypatch.setenv("NEXUS_DATA_DIR", str(settings.data_dir))
    code, out, err = run(capsys, "list")
    assert code == 1 and out == "" and "démarr" in err
    assert not settings.db_path.exists()


def test_an_invalid_actor_or_usage_error_never_echoes_the_value(env, capsys):
    fake = "ghp_" + "A" * 36
    code, out, err = run(capsys, "issue", fake, "--label", "x")
    assert code == 1 and out == "" and fake not in err and "acteur inconnu" in err
    bad_usages = (
        ["bogus-" + fake], ["issue", "loic", "--label", "x", fake], ["issue", "--" + fake]
    )
    for argv in bad_usages:
        with pytest.raises(SystemExit) as exc:
            cli.main(argv)
        assert exc.value.code == 2
        err = capsys.readouterr().err
        assert fake not in err and "Erreur" in err


def test_a_busy_database_is_a_french_error_without_traceback(env, monkeypatch, capsys):
    monkeypatch.setattr(cli, "BUSY_TIMEOUT", 0.1)
    blocker = sqlite3.connect(env.db_path, isolation_level=None)
    blocker.execute("BEGIN IMMEDIATE")
    try:
        code, out, err = run(capsys, "issue", "loic", "--label", "x")
    finally:
        blocker.close()
    assert code == 1 and out == ""
    assert "la base est occupée, réessaie dans un instant" in err
    assert "Traceback" not in err and "INSERT" not in err


def test_a_read_only_database_is_not_reported_as_busy(env, monkeypatch, capsys):
    real_make_engine = cli.make_engine
    read_only = f"sqlite:///file:{env.db_path}?mode=ro&uri=true"
    monkeypatch.setattr(cli, "make_engine", lambda url, **kw: real_make_engine(read_only, **kw))
    code, out, err = run(capsys, "issue", "loic", "--label", "x")
    assert code == 1 and out == ""
    assert "occupée" not in err
    assert "la base est inaccessible (SQLITE_READONLY)" in err
    assert "Traceback" not in err and "INSERT" not in err


@pytest.mark.parametrize("name,value", [
    ("NEXUS_HOST", "0.0.0.0"),
    ("NEXUS_HOST", "192.168.1.10"),
    ("NEXUS_ALLOWED_HOSTS", "http://evil.example/x"),
])
def test_an_invalid_configuration_is_a_french_error_without_traceback(
    env, monkeypatch, capsys, name, value
):
    monkeypatch.setenv(name, value)
    code, out, err = run(capsys, "list")
    assert code == 1 and out == ""
    assert err.startswith("Erreur : ") and "Traceback" not in err
    assert value not in err
