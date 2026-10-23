"""URL credentials in the secret scanner (#104, ADR-006).

The password of a connection URL may hold an unencoded `@` (#104) and the user
name may hold `@`, `?` and `#`; a `/` in a password stays a known limit (#95).
The fake password is assembled at runtime, never written in the clear.
"""

from __future__ import annotations

import time

import pytest

from nexus.secrets import REDACTED, redact

PW = "Zq7" + "Wx"

# T1: a raw `@` inside the password (42 cases, all red on `master`).
T1_PASSWORDS = (
    "p@ss" + PW,
    PW + "@db",
    "@" + PW,
    PW + "@@@",
    "x@y:z#w?v=" + PW,
    PW + "?email=a@b",
    PW + ",x@y",
)
T1_TEMPLATES = (
    "postgres://alice:{}@db.local/app",
    "DATABASE_URL=postgresql://nexus:{}@db:5432/nexus",
    "redis://:{}@cache.example/0",
    "mongodb+srv://svc:{}@cluster0.example.net/?retryWrites=true",
    "redis://:{}@[::1]:6379/0",
    'export X="postgres://alice:{}@db.local/app"',
)
T1_CASES = [
    (template.format(password), template.format(REDACTED))
    for password in T1_PASSWORDS
    for template in T1_TEMPLATES
]

# T2: `#`, `?` or `@` inside the user name (15 cases, all red on `master`).
T2_TEMPLATES = (
    "ftp://us#er:{}@files.example",
    "ftp://us?er:{}@files.example",
    "postgresql://a#b?c:{}@db",
    "smtp://alice@example.com:{}@smtp.example.com:587",
    "postgresql://myadmin@srv:{}@srv.postgres.example.com:5432/db",
)
T2_PASSWORDS = (PW, PW + "#2024", "p@ss" + PW)
T2_CASES = [
    (template.format(password), template.format(REDACTED))
    for password in T2_PASSWORDS
    for template in T2_TEMPLATES
]

# T5: several URLs on one line, each masked on its own (3 cases, red).
PW_WITH_AT = "p@ss" + PW
T5_CASES = [
    (
        f"postgres://u1:{PW_WITH_AT}@h1/x redis://:{PW_WITH_AT}@h2/0",
        f"postgres://u1:{REDACTED}@h1/x redis://:{REDACTED}@h2/0",
    ),
    (
        f"postgres://u:{PW_WITH_AT}@h1,redis://:{PW_WITH_AT}@h2/0",
        f"postgres://u:{REDACTED}@h1,redis://:{REDACTED}@h2/0",
    ),
    (
        f"a=postgres://u1:{PW_WITH_AT}@h1/x;b=amqp://g:{PW_WITH_AT}@h2",
        f"a=postgres://u1:{REDACTED}@h1/x;b=amqp://g:{REDACTED}@h2",
    ),
]

# T6: scheme starts the lookbehind has to keep (guard, green on `master`
# except `_postgres`).
T6_TEMPLATES = (
    "Connexion...postgres://alice:{}@db/app",
    "-postgres://u:{}@h/x",
    "9+abc://u:{}@h",
    "_postgres://u:{}@h/x",
    "POSTGRES://U:{}@H/X",
)
T6_CASES = [
    (template.format(PW + "#1"), template.format(REDACTED)) for template in T6_TEMPLATES
]

# T7: URLs without credentials, left intact (29 strings).
T7_TEXTS = (
    "git@github.com:org/repo.git",
    "ssh://git@host:22/o/r.git",
    "https://example.org?redirect=mailto:alice@example.net",
    "https://git@host/org/tool",
    "http://localhost:4873/@types/node",
    "https://host:8080/users/@alice",
    "https://example.org/path?next=a:b@c",
    "https://example.org/?redirect=mailto:alice@example.net",
    "https://example.org/a?x=1#mailto:bob@example.net",
    "git+ssh://git@github.com:org/repo.git",
    "ssh://git@host:22",
    "smtp://alice@example.com:587",
    "https://user@host:8443/x?y=1",
    "voir https://example.org:8443/docs et écrire à bob@example.net",
    "https://a.example/x https://b.example:81/y alice@example.net",
    "https://example.org?a=1&b=2#c:d@e",
    "https://example.org/@scope/pkg@1.2.3",
    "npm i https://registry.example:4873/@types/node@20",
    "mailto:alice@example.net",
    "jdbc:postgresql://db:5432/app?user=alice",
    "https://example.org:8443/a@b",
    "ws://localhost:3000/socket@1",
    "webpack://@scope/pkg/x.js",
    "docker://alpine@sha256:" + "ab12" * 16,
    "ssh://alice@example.com:2222",
    "https://alice@example.com:8443/x?y=a@b",
    "git+https://github.com/x/y.git@v1.2",
    "1://a:b",
    "http://[::1]:8080/x@y",
)

# T8: masked by choice (ADR-006, Loïc 2026-10-20: too much rather than too little).
T8_CASES = [
    (
        "https://example.org#mailto:alice@example.net",
        f"https://example.org#mailto:{REDACTED}@example.net",
    ),
    (
        "https://example.org?mailto:alice@example.net",
        f"https://example.org?mailto:{REDACTED}@example.net",
    ),
    (
        "https://user@host:8443?email=bob@example.net",
        f"https://user@host:{REDACTED}@example.net",
    ),
    (
        f"postgres://u:{PW}@h?email=a@b.example",
        f"postgres://u:{REDACTED}@b.example",
    ),
    (
        f'{{"db":"postgres://u:{PW}@h","mail":"bob@x.org"}}',
        f'{{"db":"postgres://u:{REDACTED}@x.org"}}',
    ),
    (
        "http://localhost:8080?email=alice@example.com",
        f"http://localhost:{REDACTED}@example.com",
    ),
]

ALL_URL_CASES = (*T1_CASES, *T2_CASES, *T5_CASES, *T6_CASES, *T8_CASES)


@pytest.mark.parametrize("text, expected", T1_CASES)
def test_a_raw_at_sign_in_the_password_is_masked(text, expected):
    # #104: the greedy password backs off to the LAST `@` before a `/` or a space.
    cleaned, found = redact(text)
    assert cleaned == expected, text[:120]
    assert found == ["url_credentials"], text


@pytest.mark.parametrize("text, expected", T2_CASES)
def test_a_hash_question_mark_or_at_sign_in_the_user_name_is_masked(text, expected):
    # The user name runs up to the first `:` and may hold `@`, `?` and `#`;
    # it may not hold `=` after a `?` or a `#` (the #84 query case).
    cleaned, found = redact(text)
    assert cleaned == expected, text[:120]
    assert found == ["url_credentials"], text


@pytest.mark.parametrize("text, expected", T5_CASES)
def test_several_urls_on_one_line_are_masked_separately(text, expected):
    # The `/` of the next URL bounds each match: the greedy password cannot
    # swallow a second URL.
    cleaned, found = redact(text)
    assert cleaned == expected, text[:120]
    assert found == ["url_credentials"], text


@pytest.mark.parametrize("text, expected", T6_CASES)
def test_a_scheme_run_prefix_does_not_hide_the_credentials(text, expected):
    # Lookbehind guard: one attempt per scheme run, whatever precedes it.
    cleaned, found = redact(text)
    assert cleaned == expected, text[:120]
    assert found == ["url_credentials"], text


@pytest.mark.parametrize("text", T7_TEXTS)
def test_urls_without_credentials_are_left_intact(text):
    assert redact(text) == (text, [])


@pytest.mark.parametrize("text, expected", T8_CASES)
def test_lookalike_urls_are_masked_by_choice(text, expected):
    cleaned, found = redact(text)
    assert cleaned == expected, text[:120]
    assert found == ["url_credentials"], text


@pytest.mark.parametrize("text, _expected", ALL_URL_CASES)
def test_redaction_is_idempotent(text, _expected):
    once, _found = redact(text)
    assert redact(once) == (once, [])


@pytest.mark.parametrize(
    "text",
    (
        "a." * 50_000,
        "a-" * 50_000 + "://u:x",
        "x://" + "?a#b" * 25_000,
        "x://u:" + "p@" * 50_000 + "/",
        "x://" + "u@" * 50_000,
    ),
    ids=(
        "dotted-scheme-run",
        "dashed-scheme-run",
        "query-and-fragment",
        "at-signs-in-password",
        "at-signs",
    ),
)
def test_url_credentials_scan_is_linear(text):
    # `master` was quadratic: the `\b` retried at every `.`, `+` and `-` of a
    # scheme run (20 s on 100 KB). A comment body has no length bound; the
    # ceiling catches a quadratic return (tens of milliseconds now).
    started = time.perf_counter()
    redact(text)
    elapsed = time.perf_counter() - started
    assert elapsed < 1.0, elapsed


@pytest.mark.xfail(
    strict=True,
    reason="documented limit: `=` in the user name after a `?` or a `#` (the price of #84)",
)
def test_an_equals_sign_in_the_user_name_after_a_question_mark_is_masked():
    template = "ftp://us?x=1:{}@host"
    cleaned, found = redact(template.format(PW))
    assert cleaned == template.format(REDACTED)
    assert found == ["url_credentials"]


@pytest.mark.xfail(
    strict=True,
    reason="documented limit: a raw `/` inside the password (Refs #95)",
)
def test_a_raw_slash_in_the_password_is_masked():
    template = "postgres://alice:p@ss/{}@db/app"
    cleaned, found = redact(template.format(PW))
    assert cleaned == template.format(REDACTED)
    assert found == ["url_credentials"]
