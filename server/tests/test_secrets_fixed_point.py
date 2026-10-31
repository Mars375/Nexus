"""Fixed-point redaction (issue #126).

The slashed-value pass and the entropy pass can feed each other: a first pass masks
the opaque tail of a `/`-separated value and the second one then reads the remaining
head as opaque too. `redact` now runs the unchanged passes until nothing moves (three
passes at most), so the masking is idempotent without touching a detection rule.

Every opaque value below is assembled at runtime from short pieces: nothing here is a
real credential.
"""

import random
import re
import string

import pytest

from nexus import secrets
from nexus.secrets import redact

B62 = string.ascii_letters + string.digits
HEX = "0123456789abcdef"

# Three 1-minimal non-idempotent entries found on master by a seeded fuzz (removing any
# single character makes them idempotent again): the first pass masks the tail, the
# second masks the head. Each is paired with the 8+-character alphanumeric fragments
# master's first pass masked (`redact(x)[0]` no longer held them).
_PINNED = [
    (
        "".join(["cZFj", "36t/", "kXlV", "DGRl", "/var/", "lib/", "vS58", "jynn",
                 "n9in", "bFsj", "wu2P", "GBau"]),
        ["".join(["vS58", "jynn", "n9in", "bFsj", "wu2P", "GBau"])],
    ),
    (
        "".join(["8514", "2AD3", "F4B3", "27AB", "CE5A", "C1P0", "/TuN3", "GLO/",
                 "hlgl", "JduM", "P9Ib", "y5QF"]),
        ["".join(["8514", "2AD3", "F4B3", "27AB", "CE5A", "C1P0"])],
    ),
    (
        "".join(["efa6", "74bf", "dfaf", "7c5a", "dbYk", "hgGE", "/L0b3", "+So=",
                 "/S1Dm", "VuMu", "7RU4", "loB"]),
        ["".join(["efa6", "74bf", "dfaf", "7c5a", "dbYk", "hgGE"])],
    ),
]


@pytest.mark.parametrize(("text", "fragments"), _PINNED, ids=["path", "hex", "base64"])
def test_pinned_entries_reach_a_fixed_point(text, fragments):
    once, _ = redact(text)
    assert redact(once)[0] == once
    for fragment in fragments:
        assert fragment not in once


def test_a_text_without_a_secret_runs_a_single_pass(monkeypatch):
    calls = []
    original = secrets._redact_once

    def spy(value):
        calls.append(value)
        return original(value)

    monkeypatch.setattr(secrets, "_redact_once", spy)
    text = "Un compte rendu normal, sans aucun identifiant : 42 taches."
    assert redact(text) == (text, [])
    assert len(calls) == 1


def _entry(rng):
    fragments = [
        "password", "token", "api_key", "mot de passe", "Authorization: ", ":", "=", " ",
        "\n", '"', "'", "\\", ",", ";", "{", "}", "[", "]", "_", "-", ".", "@", "#", "?",
        "+", "[REDACTED]", "https://", "postgres://u:", "evt_", "tok_", "key-", "sk_live_",
        "NRJS-", "glpat-", "dapi", "0x", "sha256=", "AKIA", "20261018143022",
        "1729260000123", "3686f22a-1ac5-4c8a-9d5b-8f29c2f21e90", "getUserById",
        "HTTP2_MAX", "userprofile2", "/", "/api/v1/", "C:/Users/x/", "/var/lib/",
        "?q=", "/tokens/",
    ]
    alphabets = [B62, HEX, HEX.upper(), B62 + "-_", B62 + "+=", B62 + "+/="]
    parts = []
    for _ in range(rng.randint(1, 8)):
        if rng.random() < 0.5:
            parts.append(rng.choice(fragments))
        else:
            alphabet = rng.choice(alphabets)
            parts.append("".join(rng.choice(alphabet) for _ in range(rng.randint(4, 48))))
    return "".join(parts)


def test_fixed_point_never_unmasks_what_the_first_pass_masked():
    # 2 000 seeded inputs, `/` included: every 8+-character alphanumeric fragment the
    # first pass masks stays masked after the loop.
    rng = random.Random("fixed-point:126:non-regression")
    for _ in range(2000):
        text = _entry(rng)
        first, _ = secrets._redact_once(text)
        cleaned, _ = redact(text)
        for mask in set(re.findall(r"[A-Za-z0-9]{8,}", text)):
            if mask not in first:
                assert mask not in cleaned, text
