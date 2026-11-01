"""Détection et masquage des secrets avant toute écriture (ADR-006, SECURITY §1).

Aucun secret n'est stocké, journalisé ni renvoyé : toute correspondance devient `[REDACTED]`.
Les motifs visent des formats reconnaissables pour limiter les faux positifs sur du texte normal.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Callable
from contextvars import ContextVar
from functools import cache
from math import log2
from typing import Any

REDACTED = "[REDACTED]"

# A vendor format masks the whole run it sits in (issue #101): from the start of
# the run of entropy-candidate characters before it — one attempt per run, as
# `_URL_CREDENTIALS` does, so the scan stays linear — to the end of the run of
# entropy-candidate characters after it. A random head or base64 tail glued to the
# format would otherwise stay in the clear, too short for the entropy pass. The
# formats run after every label, URL, header and slashed-value pass (see `_VENDOR`):
# a known label (`TOKEN=<token>`, `password: <token> and more`) is read by those
# passes exactly as on master; an unknown one glued by `=` goes with the run, as the
# entropy pass already takes `digest=<hex>` whole.
_GLUED_RUN = r"(?<![A-Za-z0-9+=_-])[A-Za-z0-9+=_-]*?"
_RUN_TAIL = r"[A-Za-z0-9+=_-]*"

_FULL: list[tuple[str, re.Pattern[str]]] = [
    ("private_key", re.compile(
        r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?(?:-----END [A-Z ]*PRIVATE KEY-----|\Z)"
    )),
    ("api_key", re.compile(r"\bsk-(?:proj-|ant-)?[A-Za-z0-9_-]{20,}")),
    ("github_token", re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{22,})")),
    ("aws_access_key", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")),
    ("slack_token", re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}")),
    ("google_api_key", re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b")),
    # Nexus actor token (ADR-020): `nxt_` + 43 base64url characters; a longer run is redacted whole.
    # Deliberately unanchored (no `\b`): ADR-006 prefers over-redaction, so a token glued to
    # other text is still masked.
    ("actor_token", re.compile(r"nxt_[A-Za-z0-9_-]{43,}")),
    # Nexus WebSocket ticket (#57): `nxw_` + 43 base64url characters, unanchored as above.
    ("ws_ticket", re.compile(r"nxw_[A-Za-z0-9_-]{43,}")),
    ("jwt", re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}")),
    ("bearer_token", re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]{20,}")),
]

# Mot de passe dans une URL de connexion : postgresql://alice:hunter2@hôte/base.
# The username is optional (redis drops it: REDIS_URL=redis://:hunter2@localhost/0);
# the masked URL keeps its exact shape, including the colon of the empty username.
# A URL with a username and no password (git clone https://git@host/org/tool) is not
# a secret, and a host:port never matches (the password must end at an @).
# The username runs up to the first `:` and may hold `@`, `?` and `#` (issue #104:
# `smtp://alice@example.com:<pw>@smtp.example.com:587`); it may not hold a `=` after
# a `?` or a `#`, which keeps the query case of #84 out (`?redirect=mailto:alice@…`
# must not turn the query's tail into a « user » and erase `alice`).
# The password may hold `?`, `#` and, since #104, a raw `@`: it runs greedily up to
# the last `@` before a `/` or whitespace. When that last `@` delimits the password,
# the mask stops there and the host stays visible
# (`postgres://alice:[REDACTED]@db.local/app`); when another `@` follows in the same
# run, the mask swallows it and the host is lost — accepted, pinned by T8
# (`postgres://u:<pw>@h?email=a@b.example` → `postgres://u:[REDACTED]@b.example`).
# Two limits stay documented: a `/` inside a password (#95) and a `=` in a username
# after a `?` or a `#` (both pinned by xfail tests in test_secrets_url_credentials).
# When in doubt, mask (Loïc, 2026-10-20; ADR-006: too much rather than too little):
# there is no « port + query » exemption, because `postgresql://alice:12#a=b@db`
# (a password) and `http://localhost:8080#a=b@example.com` (no credentials) are the
# same string shape and no rule tells them apart without leaving a password in the
# clear (Antigravity, PR #97). Accepted false positives, pinned by the tests: such a
# URL without credentials loses its port and query head
# (`http://localhost:[REDACTED]@example.com`), and a `#mailto:` or `?mailto:` tail,
# or an `email=` query followed by another `@`, is masked too.
# The lookbehind allows one attempt per scheme run — `\b` retried at every `.`, `+`
# and `-`, which made the scan quadratic (20 s on 100 KB). It also stops `_` from
# hiding a scheme it precedes: `_` is not a scheme character, but `\b` refused to
# start a match right after it, so `_postgres://u:<pw>@h/x` stayed in the clear.
# A `.` right before the scheme already worked on `master`, and
# `Connexion...postgres://alice:<pw>@db/app` keeps being masked; T6 pins both.
_URL_CREDENTIALS = re.compile(
    r"(?i)(?<![a-z0-9+.-])"                # one attempt per scheme run: linear scan
    r"([a-z0-9+.-]+://"                    # scheme: the whole run, whatever its first character
    r"[^\s:/?#]*(?:[?#][^\s:/?#=]*)*:)"    # username: may hold @, ? and #; no = after a ? or #
    r"([^\s/]+)"                           # password: greedy, up to the LAST @ before / or space
    r"(@)"
)

# En-tête HTTP d'identifiant écrit tel quel (« Authorization: Digest username="…", … »,
# « Cookie: a=1; b=2 ») : sa valeur court jusqu'à la fin de la ligne, virgules et ; compris,
# et continue sur les lignes repliées (qui commencent par une espace ou une tabulation).
# Forme citée comprise (« "Authorization": "Digest username=\"…\"" ») : des guillemets
# échappés dans la valeur l'arrêteraient sinon au premier.
_HEADER_CREDENTIALS = re.compile(
    r"(?im)(?<![\w.-])((?:proxy[_-]?)?authorization|(?:set[_-]?)?cookie)([\"']?\s*:\s*)"
    r"(?=\S)([^\r\n]+(?:\r?\n[ \t][^\r\n]*)*)"
)

# « mot de passe : xyz », « token=abc »… : on masque la valeur, on garde l'étiquette.
# Couvre aussi la forme JSON/YAML collée ({"password": "hunter2"}, 'token': 'abc') et les
# variables d'environnement préfixées (AWS_SECRET_ACCESS_KEY=…, CLIENT_SECRET=…). Préfixe
# et suffixe doivent être séparés par _ . ou - : « tokens: 3000 » n'est pas un secret.
_LABEL = (
    r"(?:[\w.-]*[_.-])?"
    r"(?:password|passwd|pwd|secret|api[ _-]?key|access[ _-]?token|private[ _-]?key|token"
    # Codes à usage unique (SECURITY §1 : les codes 2FA sont des secrets).
    r"|otp|totp|2fa|mfa|verification[ _-]?code|one[ _-]?time[ _-]?code"
    # En-têtes HTTP qui portent un identifiant, quel que soit le schéma (Basic, Digest…).
    r"|authorization|cookie)"
    r"(?:[_.-][\w.-]*)?"
    # camelCase / PascalCase (clientSecret, refreshToken, dbPassword) : la majuscule sert de
    # séparateur, sensible à la casse pour que « maxTokens » ou « tokenizer » restent intacts.
    r"|(?-i:[A-Za-z][A-Za-z0-9]*?"
    r"(?:Password|Passwd|Pwd|Secret|ApiKey|AccessToken|PrivateKey|Token|Otp|Totp|Mfa"
    r"|Authorization|Cookie)"
    r"(?:[A-Z][A-Za-z0-9]*)?)"
    r"|mot de passe|mdp|code de vérification"
)
# Clé JSON qui nomme un identifiant : {"password": "…"} — sa valeur est un secret.
_CREDENTIAL_KEY = re.compile(rf"(?i){_LABEL}")

# Characters that end a bare value: whitespace, comma, semicolon, closing brace.
_STOP = r"\t \r\n,;}"
# What may sit between a label and its separator: a quote, escaped or not (`"<label>":`,
# `\"<label>\":`). Never a lone backslash: `<label>\:` is not an assignment, and
# reading it as one hid the next label from the scan (`<l1>\:<l2>" =x` left x clear).
_SEP_QUOTE = r"(?:\\?[\"'])?"
# A label is only worth stopping for when a value follows its separator; a label
# with nothing after it stays inside the value that reached it.
_HAS_VALUE = rf"(?=\s*[^{_STOP}])"
# A label that opens another value behind a quote, bare or escaped (`"<label>":`,
# `'<label>'=`, `\"<label>\":`). Master ended every bare value at a quote, so its scan
# resumed there and masked that label's own value; a value that now runs across
# quotes stops in front of such a label instead (issue #106).
_QUOTED_LABEL = rf"\\?[\"'](?:{_LABEL}){_SEP_QUOTE}\s*[=:]{_HAS_VALUE}"
# The same, quote optional: a further word that opens another labelled value.
_NEXT_LABEL = rf"\\?[\"']?(?:{_LABEL}){_SEP_QUOTE}\s*[=:]{_HAS_VALUE}"
# The blanks after a separator cross a line break only towards a line that does
# not open another assignment: `<label>:` left empty above `<label2>: x` (YAML
# nesting, an empty `.env` entry) has no value, and `<label2>` keeps its own.
_SEP_TAIL = rf"[ \t]*(?:\r?\n(?![ \t]*(?:export[ \t]+)?{_NEXT_LABEL})[ \t]*)*"
# A backslash that escapes a quote ending the run: it stays with that quote, so
# masking the value never turns `\"` into a bare `"` that a second pass would read
# as a closing quote (idempotence).
_LONE_BACKSLASH = rf"\\(?=[\"'](?![^{_STOP}]))"
# A label inside a value, at the end of its line, whose own value sits on the next
# line (`<label>: x#<label>:` then `y`): the value runs on across the line break and
# the next line is masked too. Not when the next line opens another assignment
# (YAML `<label>:` with nested keys, `.env` `<LABEL>=` left empty): that line keeps
# its label and the scan masks its own value.
_LABEL_AT_LINE_END = (
    rf"(?<![\w.-])(?:{_LABEL}){_SEP_QUOTE}[ \t]*[=:][ \t]*\r?\n\s*(?=[^{_STOP}])"
    rf"(?!(?:export[ \t]+)?{_NEXT_LABEL})"
)
# One character of a bare value after its first: a quote belongs to the value only
# when the value goes on after it (j'aime, pa"ss) and does not open another label;
# a quote that ends the run stays outside, so `"<label>: voir Bitwarden" dans le
# canal` keeps its closing quote and its prose.
_RUN_CHAR = (
    rf"(?:{_LABEL_AT_LINE_END}"
    rf"|(?!{_QUOTED_LABEL}|{_LONE_BACKSLASH})(?:[^{_STOP}\"']|[\"'](?=[^{_STOP}])))"
)
# A further space-separated word of a passphrase, unless it opens another labelled value.
_NEXT_WORD = rf"[ \t]+(?!{_NEXT_LABEL}|{_LONE_BACKSLASH})[^{_STOP}]{_RUN_CHAR}*"
# Text glued after a closing quote that did not end the value: up to the next stop.
_GLUE_CHAR = rf"(?:{_LABEL_AT_LINE_END}|(?!{_QUOTED_LABEL})[^{_STOP}])"
_GLUED_WORD = rf"[ \t]+(?!{_NEXT_LABEL}){_GLUE_CHAR}+"
# A value never starts on a label between quotes that has its own value
# (`<label>: "<label>": x`): the scan resumes on that label and masks its value.
_NOT_A_LABEL = (
    rf"(?!\\?\"(?:{_LABEL})\\?\"\s*[=:]{_HAS_VALUE}"
    rf"|\\?'(?:{_LABEL})\\?'\s*[=:]{_HAS_VALUE})"
)
# A line that opens another labelled value: a quoted value never runs across it.
_NEW_ASSIGNMENT_LINE = (
    rf"[ \t]*(?:export[ \t]+)?\\?[\"']?(?:{_LABEL}){_SEP_QUOTE}[ \t]*[:=]"
)
# A value made only of [REDACTED] markers, quotes, separators and backslashes is
# already masked: when the scan stops in front of a label, the entropy pass may
# mask that label too and leave `[REDACTED]'[REDACTED]:` behind; masking it again
# on a second pass would break idempotence.
_ONLY_MARKERS = re.compile(r"[\"':=\\]*(?:\[REDACTED\][\"':=\\]*)+")


def _quoted(q: str) -> str:
    """A value between quotes `q`, backslash escapes honoured. It spans lines up to
    its closing quote unless a line in between opens another labelled value; with
    no closing quote it runs to the end of its line, or of the next one when its
    line ends on a label (issue #106)."""
    return (
        rf"{q}((?:[^{q}\\\r\n]|\\[\s\S]|[\r\n](?!{_NEW_ASSIGNMENT_LINE}))*(?={q})"
        rf"|(?:{_LABEL_AT_LINE_END}|[^{q}\\\r\n]|\\[^\r\n])*\\?(?=[\r\n]|\Z)){q}?"
    )


_DQ = _quoted('"')
_SQ = _quoted("'")

_ASSIGNMENT = re.compile(
    rf"(?i)(?<![\w.-])({_LABEL})"
    rf"({_SEP_QUOTE}\s*[:=]{_SEP_TAIL})"
    rf"{_NOT_A_LABEL}(?:(?:{_DQ}|{_SQ})"
    rf"((?=[\w\\\"'])(?!{_NEXT_LABEL}){_GLUE_CHAR}+(?:{_GLUED_WORD})*)?"
    r"|((?:(?:basic|bearer|digest|negotiate|ntlm)\s+)?"
    # Bare value: one run, or several space-separated runs, up to the end of the
    # line — a multi-word passphrase is masked whole (issue #15). A value that
    # starts on a label whose own value sits on the next line takes that line too.
    # Text glued after a bracket shell joins the value unless it opens another
    # label (`[REDACTED]"<label>": x`). Bracket fragments glued to the run stay
    # inside the value: a value starting at `[` goes through the bracket shell
    # FIRST (alternation order), so a value that starts at an existing [REDACTED]
    # never reaches the naked-run chain, the prose after the shell stays prose,
    # and the shell value comes back unchanged through mask_value's short circuit
    # (idempotence). A further word that opens a recognised label ends the sweep
    # instead of joining it: the resumed scan masks it under its own label, so
    # [REDACTED] is never doubled, while a passphrase word that merely carries an
    # `=` (« battery=staple ») stays inside the value. An auth scheme (Basic xyz)
    # is part of the value.
    rf"(?:{_LABEL_AT_LINE_END}{_RUN_CHAR}*(?:{_NEXT_WORD})*"
    rf"|\[(?:{_LABEL_AT_LINE_END}|[^\]\r\n])*\]?(?:(?!{_NEXT_LABEL}){_RUN_CHAR}+)?"
    rf"|(?!{_LONE_BACKSLASH})[^{_STOP}\"']{_RUN_CHAR}*(?:{_NEXT_WORD})*)))"
)

# Long opaque runs: random-looking tokens that matched no format above (third-party
# API keys, full-width hashes). The pass runs last, once labelled values are already
# masked. Dots, slashes and colons are not in the candidate class, so UUIDs, paths,
# URLs and dotted hosts never become candidates; `_` and `-` joiners ARE allowed —
# a token like « Y7qP2rTx_N9vH4mKu_C6wJ8sZa_R5dE3fGh » splits into runs below 24
# characters — with the segment guard in mask_random_run keeping identifiers
# (a short word between separators) and 4-character UUID groups out (issue #15).
_ENTROPY_TOKEN = re.compile(r"[A-Za-z0-9+=_-]{24,}")
# Unlabelled base64 split by slashes (issue #84): the class above has no `/`, so a
# segmented value leaked — every flat sub-run stayed under the floor. This pattern
# spans the whole value from its FIRST segment, however short (Antigravity review
# on 6d78a6c: anchoring at 16 characters left the head in the clear; review on
# c73aee9: `{2,}` still let a one-character head through — `A/F6g7…`), and the
# lookbehind leaves `/` OUT so a value glued behind one is reached (`/etc/tokens/…`,
# review on c73aee9). The match may then start on a path word ahead of the value:
# `_opaque_slashed` rules on the whole candidate, and when the candidate reads as a
# path `mask_slashed_run` masks from the head of an opaque tail instead (review on
# 5b186c5: a real 24-to-39-character key behind `etc/tokens` leaked whole); when the
# whole candidate is opaque, all of it goes (over-redaction, ADR-006).
# `_` and `-` stay out of the class: a slashed standard-base64 value never
# carries them, while paths and slugs do.
# `=` is base64 padding: it only ever CLOSES a segment and stays out of the
# lookbehind, so a value glued behind an unlabelled `=` is reached
# (`payload=A1b2…/K1l2…`, `param=k1l2=/K1N7…` — Antigravity review on d2361cc:
# with `=` in the lookbehind no match could start after the sign and the value
# leaked whole).
_SLASHED_TOKEN = re.compile(r"(?<![A-Za-z0-9+])[A-Za-z0-9+]{1,}={0,2}(?:/[A-Za-z0-9+]+={0,2})+")
# Shannon entropy in bits per character: long natural words and repetitions sit
# around 2-3 bits, a uniform 16-symbol hex run stays near log2(16) = 4 — the
# threshold divides prose from opaque randomness (documented in issue #15).
_HIGH_ENTROPY_BITS = 3.5


def _shannon_bits_per_char(token: str) -> float:
    n = len(token)
    return -sum((p / n) * log2(p / n) for p in Counter(token).values())


def _lower_run_share(text: str) -> float:
    """Share of lowercase letters sitting in runs of three or more.

    A word scores near 1 (`utilisateur`, `deployments`); an opaque chunk,
    whose lowercase letters sit alone between digits or capitals
    (`N9vH4mKu`), scores near 0. Both slashed and underscore guards rule
    « words » with it.
    """
    total = longs = 0
    run = 0
    for ch in text + "\x00":
        if ch.islower():
            run += 1
            continue
        if run >= 3:
            longs += run
        total += run
        run = 0
    return longs / total if total else 0.0


def _case_chaos(token: str) -> float | None:
    """Share of adjacent letter pairs that shuffle case, on eight pairs or more.

    A random value shuffles case between neighbours; a name changes case at
    word starts, and a word start is not a shuffle. The chain of three-letter
    TitleCase words — `Dev/Ops/Tool/Run12345/Log6789` — holds two-character
    lowercase runs, below the words veto, and reached 0.45 on word starts
    alone: it was erased (Antigravity review on 5b186c5, a regression against
    master). A token whose changes ONLY open words carries no shuffle: None.
    None as well when the token holds too few letter pairs for the ratio to
    mean anything.
    """
    changes = word_starts = pairs = 0
    for index, (left, right) in enumerate(zip(token, token[1:], strict=False)):
        if not (left.isalpha() and right.isalpha()):
            continue
        pairs += 1
        if left.isupper() == right.isupper():
            continue
        changes += 1
        preceding = token[index - 1] if index else ""
        if left.isupper() and right.islower() and not preceding.isalpha():
            word_starts += 1
    if pairs < 8 or changes == word_starts:
        # Every change opens a word: `Dev/Ops/Tool/Run12345/Log6789` shuffles
        # nothing, a value that changes case only at word starts is a name.
        return None
    return changes / pairs


def _alternating_chunk(segment: str) -> bool:
    """Nearly every adjacent pair of a segment alternates a letter and a digit
    (`k1l2=`, `A1b`): the signature of a short chopped piece."""
    segment = segment.rstrip("=")
    pairs = list(zip(segment, segment[1:], strict=False))
    if len(pairs) < 2:
        return False
    boundaries = sum(
        1
        for left, right in pairs
        if (left.isalpha() and right.isdigit()) or (left.isdigit() and right.isalpha())
    )
    return boundaries / len(pairs) >= 0.8


def _word_chunk(part: str) -> bool:
    """A vocabulary chunk (a path word): all-lowercase letters, six of them at
    least.

    `controllers`, `tokens`, `releases` are words; a crypto segment keeps a
    digit (`SIIn3hucz0P4s`, `A0b`), shuffles case (`IlatOVdVhdwasWF`), or
    stays under six letters — where a base64 fragment is indistinguishable
    from a short word (`xyz`, `fcn`, `vwsw=`; Antigravity review on a77d504:
    reading every digitless chunk of three lowercase letters as a word leaked
    real 44-character keys). A path built only from shorter words
    (`api/v1/users/getById/v2b1`) is ruled by the whole-candidate share of
    `_opaque_slashed` before this rescue runs. The rescue in `_opaque_chunks`
    reads this to tell a phrase from a chopped value.
    """
    letters = part.rstrip("=")
    return letters.isalpha() and letters.islower() and len(letters) >= 6


# Generated-identifier pieces (issue #101): a timestamp, a UUID of version 4 or 7
# written as 32 hex digits, a ULID. Shared by the additions of the entropy pass and
# by the generated-identifier exemption.
_EPOCH_MS_FLOOR = 946_684_800_000  # 2000-01-01T00:00:00Z
_EPOCH_MS_CEILING = 4_102_444_800_000  # 2100-01-01T00:00:00Z
_HEX_SEGMENT = re.compile(r"[0-9a-f]+|[0-9A-F]+")
_ULID_SEGMENT = re.compile(r"[0-7][0-9a-hjkmnp-tv-z]{25}|[0-7][0-9A-HJKMNP-TV-Z]{25}")
_CROCKFORD = "0123456789abcdefghjkmnpqrstvwxyz"
_STAMP_WITH_T = re.compile(r"([0-9]{8})T([0-9]{6})Z?")
_MONTH_DAYS = (31, 29, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31)


def _timestamp_segment(segment: str) -> bool:
    """A date or a Unix epoch written in digits, as generators stamp their ids.

    `20261018`, `202610181430`, `20261018143022` and `20261018T143022Z` must be a
    valid date-time between 1970 and 2099; a 10- or 13-digit run must be an epoch
    in seconds or milliseconds between 2000 and 2100. Any other digit run (a
    counter, an account number, a 16-digit card number) is not one.
    """
    stamped = _STAMP_WITH_T.fullmatch(segment)
    if stamped:
        segment = stamped.group(1) + stamped.group(2)
    if not (segment.isascii() and segment.isdigit()):
        return False
    size = len(segment)
    if size in (8, 12, 14):
        year, month, day = int(segment[:4]), int(segment[4:6]), int(segment[6:8])
        if not (1970 <= year < 2100 and 1 <= month <= 12 and 1 <= day <= _MONTH_DAYS[month - 1]):
            return False
        if month == 2 and day == 29 and not (year % 4 == 0 and (year % 100 or year % 400 == 0)):
            return False
        clock = segment[8:]
        return all(
            int(clock[index:index + 2]) < (24 if index == 0 else 60)
            for index in range(0, len(clock), 2)
        )
    if size in (10, 13):
        millis = int(segment) * 1000 if size == 10 else int(segment)
        return _EPOCH_MS_FLOOR <= millis < _EPOCH_MS_CEILING
    return False


def _generated_id_segment(segment: str) -> bool:
    """A UUID of version 4 or 7 written as 32 hex digits, or a ULID.

    Version nibble and variant bits for the UUID (a random hex32 value matches a
    v4 one draw in 64), a plausible millisecond timestamp for the UUID v7 and the
    ULID (Crockford base32, one case, at least one letter past `f`: a hex run of
    26 digits is not one).
    """
    if len(segment) == 32 and _HEX_SEGMENT.fullmatch(segment):
        lowered = segment.lower()
        if lowered[16] not in "89ab":
            return False
        if lowered[12] == "4":
            return True
        return lowered[12] == "7" and (
            _EPOCH_MS_FLOOR <= int(lowered[:12], 16) < _EPOCH_MS_CEILING
        )
    if _ULID_SEGMENT.fullmatch(segment) and not _HEX_SEGMENT.fullmatch(segment):
        millis = 0
        for ch in segment[:10].lower():
            millis = millis * 32 + _CROCKFORD.index(ch)
        return _EPOCH_MS_FLOOR <= millis < _EPOCH_MS_CEILING
    return False


def _camel_shape(letters: str, versioned: bool) -> bool:
    """Every block of capitals opens a word (one capital before lowercase
    letters), is an acronym before a word (three capitals or more, `HTTPServer`),
    a trailing acronym (`toJSON`) or a version tag before final digits (`apiV2`).
    A random draw shuffles case (`SNcveshQ`, `JVwPNruz`). One linear scan."""
    index, size = 0, len(letters)
    while index < size:
        if not letters[index].isupper():
            index += 1
            continue
        end = index
        while end < size and letters[end].isupper():
            end += 1
        block = end - index
        if end < size and block == 2:
            return False
        if end == size and block == 1 and not versioned:
            return False
        index = end
    return True


def _opaque_run(token: str) -> bool:
    """Does a high-entropy candidate read as an opaque token or an identifier?"""
    if _shannon_bits_per_char(token) < _HIGH_ENTROPY_BITS:
        return False
    # Vendor tokens are drawn from digit-bearing alphabets; a candidate made
    # only of letters (joined label vocabulary such as
    # « authentification-rechargement ») is a phrase, not a secret —
    # clean_label() validates its labels through this very gate.
    if not any(ch.isdigit() for ch in token):
        return False
    # Framing separators (markdown italics `_token_`) only produce empty
    # segments: they do not drag the floor down, real segments decide.
    parts = [part for part in re.split(r"[-_]", token) if part]
    if parts and min(map(len, parts)) >= 8:
        return True
    # A short head segment is tolerated when EVERY following segment is full
    # length (≥ 8), carries a digit, mixes upper- and lowercase letters, AND
    # does not itself read as a word: « tok_Y7qP2rTx_… » is opaque (issue #84),
    # while a snake_case identifier whose tail is plain words with a digit
    # appended — v1_userprofile2_accountsettings3, db_connectionpool1_maxconnections2 —
    # stays an identifier (Antigravity review on d2361cc: those digit-bearing
    # word tails passed on length alone and masked five identifiers, a
    # regression against master; a digit-free tail such as `database` was
    # already ruled out on 6d78a6c). A tail of single lowercase letters
    # between digits and capitals keeps scoring 0 and passes.
    # Mixed case is the base62 signature of a vendor tail (issue #93): generated
    # identifiers draw theirs from single-case alphabets — decimal timestamps,
    # hex digests, base36 — and `evt_20261018143022_a1b2c3d4` was refused with a
    # 409. A segment of 24+ characters is exempt: a long hex tail is the shape of
    # real vendor keys (`key-<hex32>`, `shpat_<hex32>`) and no generated
    # identifier of this family carries one next to a decimal timestamp (that
    # segment still fails the case test). Assumed price: a short-prefixed value
    # made only of single-case segments under 24 characters is no longer masked.
    if len(parts) >= 2 and len(parts[0]) < 8 and all(
        len(part) >= 8
        and any(ch.isdigit() for ch in part)
        and (
            len(part) >= 24
            or (any(ch.isupper() for ch in part) and any(ch.islower() for ch in part))
        )
        and _lower_run_share(part) < 0.6
        for part in parts[1:]
    ):
        return True
    # A short vendor prefix does not break a token that holds a flat 24+ run
    # behind it (« tok_Y7qP2rTx… »): the prefix belongs to the value it names
    # and the whole candidate is masked. The 4-character groups of a UUID and
    # the words of a slug never reach 24 characters on their own.
    return any(
        len(part) >= 24 and _shannon_bits_per_char(part) >= _HIGH_ENTROPY_BITS
        for part in parts
    )


# Additions of the entropy pass (issue #101). `_opaque_run` is master's rule and
# is left untouched; `mask_random_run` masks a candidate when EITHER rule says so,
# so this block only ever adds masks. It catches the random values the segment
# rule missed — `token_urlsafe(32)` chopped at `-`/`_`, hex32/hex40 under 3.5 bits,
# `tok_<b62_8>×4`, `key_<hex8>×4`, `acct-<digits>-<b62>`, `<hex32>=`, `x+<hex32>` —
# by measuring the candidate's material: the candidate is split on `-` and `_`,
# the segments a person or a generator writes on purpose are set aside (a
# timestamp, a UUID, a ULID, a name), and the rest is cut at the base64 `+` and
# `=`. The candidate is added when that material holds at least `_OPAQUE_BITS`
# (Σ length × log2(alphabet), a joiner drawn inside a base64 value counting 6
# bits) and its Shannon entropy sits within `_ENTROPY_MARGIN` of a uniform draw.
# Setting a segment aside only ever removes an addition, never a mask of master.
# Its price is measured in the #101 comment: a split hex value of 128 bits is
# masked whatever its prefix (`span_<hex16>_<hex16>`), as a full SHA-1 already is.
_OPAQUE_BITS = 128.0
_ENTROPY_MARGIN = 0.6
# The expected entropy grows with the length; past 128 characters the cap only
# lowers the bar (more masking), and it bounds the cache of `_expected_entropy`.
_ENTROPY_SAMPLE_CAP = 128
_UUID_DASHED = re.compile(
    r"(?<![A-Za-z0-9])[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}"
    r"-[0-9a-fA-F]{12}(?![A-Za-z0-9])"
)
_NAME_SEGMENT = re.compile(r"[A-Za-z]+[0-9]{0,8}")
# A SCREAMING_SNAKE word of three letters or more (`HTTP2`, `MAX`, `CONCURRENT`).
_UPPER_NAME = re.compile(r"[A-Z]{3,}[0-9]{0,8}")
_BASE64_SIGNS = re.compile(r"[+=]")
# A `+` carries drawn bits only between two characters of material: a run of `+`
# (`v2++++++`) is not a base64 draw and must not inflate the bit count.
_PLUS_JOINER = re.compile(r"(?<=[A-Za-z0-9])\+(?=[A-Za-z0-9])")
# No usual alphabet is wider than base64: the bits per character are capped at
# log2(64), which also bounds the cache of `_expected_entropy`.
_MAX_ALPHABET = 64
# A `+`, `-` or `_` drawn as part of a base64 value carries log2(64) bits.
_DRAWN_JOINER_BITS = 6.0


def _name_segment(segment: str) -> bool:
    """A word or a camelCase / PascalCase / SCREAMING name, at most eight digits
    at its end (`accountsettings3`, `handleUserLoginV2`, `HTTPServer`, `HTTP2`)."""
    if _UPPER_NAME.fullmatch(segment):
        return True
    if not _NAME_SEGMENT.fullmatch(segment) or _lower_run_share(segment) < 0.6:
        return False
    letters = segment.rstrip("0123456789")
    return _camel_shape(letters, len(letters) < len(segment))


def _alphabet_size(piece: str) -> int:
    """The smallest usual alphabet that holds a piece: 16 for hex digits of one
    case, otherwise 10 per digit class and 26 per letter case present."""
    has_lower = any("a" <= ch <= "z" for ch in piece)
    has_upper = any("A" <= ch <= "Z" for ch in piece)
    has_digit = any("0" <= ch <= "9" for ch in piece)
    if (has_lower or has_upper) and _HEX_SEGMENT.fullmatch(piece):
        return 16
    return 10 * has_digit + 26 * has_lower + 26 * has_upper


@cache
def _expected_entropy(size: int, alphabet: int) -> float:
    """Expected Shannon entropy, in bits per character, of `size` characters
    drawn uniformly from `alphabet` symbols: log2(n) − (k / n) · E[c · log2(c)],
    c the binomial count of one symbol. At most 128 × 63 pairs are ever computed.
    """
    p = 1.0 / alphabet
    ratio = p / (1.0 - p)
    pmf = (1.0 - p) ** size
    weighted = 0.0
    for count in range(1, size + 1):
        pmf *= (size - count + 1) / count * ratio
        if count >= 2:
            weighted += pmf * count * log2(count)
    return log2(size) - alphabet * weighted / size


def _mixed_case(part: str) -> bool:
    return any("a" <= ch <= "z" for ch in part) and any("A" <= ch <= "Z" for ch in part)


def _drawn_joiners(parts: list[str], aside: list[bool]) -> int:
    """Joiners drawn as base64 symbols: a `+` between two characters of material counts
    (a run of `+` does not); a `-` or `_` counts when a neighbour is mixed-case material
    and no neighbour was set aside (`tok_<urlsafe16>`, 128 bits, lost 6 bits per joiner)."""
    count = sum(
        len(_PLUS_JOINER.findall(part)) for part, kept in zip(parts, aside, strict=True) if not kept
    )
    for left, right, left_aside, right_aside in zip(
        parts, parts[1:], aside, aside[1:], strict=False
    ):
        if not (left_aside or right_aside) and (_mixed_case(left) or _mixed_case(right)):
            count += 1
    return count


def _opaque_material(token: str) -> bool:
    """Does the candidate hold a uniform draw of 128 bits or more? An addition
    to `_opaque_run`, never a replacement."""
    if not any(ch.isdigit() for ch in token) or not any(ch.isalpha() for ch in token):
        return False
    parts = re.split(r"[-_]", _UUID_DASHED.sub("_", token))
    aside = [
        bool(part)
        and (_timestamp_segment(part) or _generated_id_segment(part) or _name_segment(part))
        for part in parts
    ]
    pieces = [
        piece
        for part, kept in zip(parts, aside, strict=True)
        if part and not kept
        for piece in _BASE64_SIGNS.split(part)
        if piece
    ]
    if not pieces:
        return False
    sizes = [_alphabet_size(piece) for piece in pieces]
    # A hex piece that drew no letter (`30882887`) is still hex.
    if 16 in sizes:
        sizes = [16 if size == 10 else size for size in sizes]
    bits = sum(len(piece) * log2(size) for piece, size in zip(pieces, sizes, strict=True))
    bits += _DRAWN_JOINER_BITS * _drawn_joiners(parts, aside)
    if bits < _OPAQUE_BITS:
        return False
    joined = "".join(pieces)
    alphabet = min(_MAX_ALPHABET, max(2, round(2 ** (bits / len(joined)))))
    expected = _expected_entropy(min(len(joined), _ENTROPY_SAMPLE_CAP), alphabet)
    return _shannon_bits_per_char(joined) >= expected - _ENTROPY_MARGIN


def _blob_segment(segment: str) -> bool:
    """One chunk of an opaque slashed value, as opposed to a path word.

    Opaque chunks interleave letters and digits (`A1b2C3d4E5`,
    `K1N7xP9mQ2vL8jR3tY6`) or shuffle case without any word structure
    (`G9woFbdKetaZSNxZWxL2`). Human names of the corpus — `AccountSettingsV2`,
    `V1Release2026Build`, `deployments`, `build42` — keep letters and digits in
    words, and change case at word starts instead of at random, so each part
    stays far below one of the two signals (Antigravity and reviewer reviews on
    c73aee9: this guard replaces the old « two segments mixing case and digits »,
    which erased exactly those paths).
    """
    # A segment may end with base64 padding (`k1l2=`): the blob reads its data
    # part, `=` never carries a signal.
    segment = segment.rstrip("=")
    pairs = list(zip(segment, segment[1:], strict=False))
    # Letters and digits alternate: the signature of a chunked base64 value.
    # Six pairs at least (seven characters): a shorter chunk is a version tag
    # or an instance type (`v1rc1`, `v1a1`, `g4dn`, `c5ad`), whose alternation
    # is the signature of a NAME at that scale (Antigravity review on d2361cc:
    # those tags counted as blobs and erased release, k8s and Terraform paths).
    boundaries = sum(
        1
        for left, right in pairs
        if (left.isalpha() and right.isdigit()) or (left.isdigit() and right.isalpha())
    )
    if len(pairs) >= 6 and boundaries / len(pairs) >= 0.6:
        return True
    # Case changes at random rather than at word starts (letter pairs only).
    # Short PascalCase names (`ApiV2`, `AppData`) stay out: a real value mixes
    # case across many more letter pairs than a name holds. A camelCase method
    # (`getById`) can reach the ratio alone, but it never makes a path: the
    # words veto of `_opaque_slashed` rules the candidate before this arm.
    letter_pairs = [(left, right) for left, right in pairs if left.isalpha() and right.isalpha()]
    return (
        len(letter_pairs) >= 6
        and sum(1 for left, right in letter_pairs if left.isupper() != right.isupper())
        / len(letter_pairs)
        > 0.5
    )


def _blobs_of(parts: list[str]) -> list[str]:
    return [part for part in parts if _blob_segment(part)]


def _opaque_chunks(parts: list[str]) -> bool:
    """Structural signal of a chopped value: its blobs and boundary chunks.

    At least TWO blobs, or one blob when the other chunks read as the rest of
    a value rather than as a phrase: they carry a signal — a strong
    letter-digit alternation (`k1l2=`), a one-or-two character boundary
    segment (`A/…`, `…/p6`, Antigravity review on d2361cc, finding 1: such
    chunks can never be blobs on their own), or a chunk that shuffles case
    like a random draw (`IlatOVdVhdwasWF`, `q3QCEgcaHD6honHxcM`; Antigravity
    review on a77d504: real 44-character keys leaked whole when every extra
    chunk missed the first two arms) — and none of them is a word. A path
    word beside an alternating tag is a route, not a value
    (`controllers/DevSecOps/v1a1`, Antigravity review on 5efcee9), while a
    digit-bearing crypto segment is not a word (`SIIn3hucz0P4s`, `NZD`;
    Antigravity review on 49b2fe0: requiring the signal on EVERY other chunk
    leaked real keys whose extra segment misses the blob floor). A lone blob
    with nothing beside it is a bare value. The whole-candidate guard and the
    tail guard rule on the same signal.
    """
    blobs = _blobs_of(parts)
    if len(blobs) >= 2:
        return True
    if blobs:
        rest = [part for part in parts if part not in blobs]
        if not rest:
            return True
        carries_signal = any(
            _alternating_chunk(part)
            or len(part) <= 2
            or (_case_chaos(part) or 0) > 0.30
            for part in rest
        )
        if carries_signal and not any(_word_chunk(part) for part in rest):
            return True
    return False


def _opaque_tail_start(parts: list[str]) -> int | None:
    """The lowest start whose tail is an opaque value, in one backward pass.

    The words veto of `_opaque_slashed` reads `etc/tokens/A1b2…/K1l2…` as a
    path — the words ahead of the value push its lowercase share to 0.6 — and
    the whole candidate then failed the guard with the value in the clear
    (Antigravity review on 5b186c5; the leak exists on master too). The
    case-shuffle arm is left out here: it rules a whole candidate, and a name
    split on one slash, `DevSecOps/getById2`, reaches it alone (frozen keep
    case, Antigravity review on c73aee9). The tail must show the structural
    signal instead — the same blobs and boundary chunks as the whole guard
    (Antigravity review on cc0eeb3: a two-blob floor let `cat
    /etc/tokens/A/1b2…` leak whole and left the boundary chunks of
    `…/A/F6g7…/B` in the clear).

    Every gate of that per-tail predicate reads quantities of the tail this
    pass accumulates part by part — its length, a digit, the Shannon entropy
    (kept as Σ c·log2(c), one step per character), the share of lowercase
    letters in runs of three, and the flags `_opaque_chunks` reads — so the
    lowest opaque start comes out of ONE pass and no tail is ever rebuilt:
    `"/".join(parts[start:])` per start cost O(parts × length) and a comment
    body carries no length bound (`CommentIn.body`), which handed a
    synchronous worker minutes of CPU for one long slashed run (CodeRabbit
    review on 7d8fdcd). The start found is the same the loop returned — the
    first tail the gates accept — and every tail stays eligible: a length
    bound would skip the head of a value longer than the bound and mask only
    its end.
    """
    length = 0
    has_digit = False
    counts: dict[str, int] = {}
    weighted = 0.0  # Σ c·log2(c) of the tail: entropy = log2(length) - weighted / length
    lower_total = 0
    lower_long = 0
    blobs = 0
    extra = 0
    signals = 0
    words = 0
    start_found: int | None = None
    first = True
    for start in range(len(parts) - 1, 0, -1):
        part = parts[start]
        if first:
            first = False
        else:
            length += 1  # the slash joining this part to the tail below it
            before = counts.get("/", 0)
            counts["/"] = after = before + 1
            if before:
                weighted += after * log2(after) - before * log2(before)
        length += len(part)
        run = 0
        for ch in part:
            before = counts.get(ch, 0)
            counts[ch] = after = before + 1
            if before:
                weighted += after * log2(after) - before * log2(before)
            if ch.isdigit():
                has_digit = True
            if ch.islower():
                run += 1
                continue
            if run >= 3:
                lower_long += run
            lower_total += run
            run = 0
        if run >= 3:
            lower_long += run
        lower_total += run
        if _blob_segment(part):
            blobs += 1
        else:
            extra += 1
            if _alternating_chunk(part) or len(part) <= 2 or (_case_chaos(part) or 0) > 0.30:
                signals += 1
            if _word_chunk(part):
                words += 1
        if length < 24 or not has_digit:
            continue
        if log2(length) - weighted / length < _HIGH_ENTROPY_BITS:
            continue
        if lower_total and lower_long / lower_total >= 0.6:
            continue
        # Same structural rule as `_opaque_chunks`, on counted flags: two
        # blobs, or one blob whose other chunks carry a signal and none of
        # them is a word (no other chunk at all keeps the bare value).
        if blobs >= 2 or (blobs and (extra == 0 or (signals > 0 and words == 0))):
            start_found = start
    return start_found


def _opaque_slashed(token: str) -> bool:
    """Guard of the slashed pattern (issue #84): an opaque chopped value, not a path."""
    if len(token) < 24:
        return False
    if not any(ch.isdigit() for ch in token):
        return False
    if _shannon_bits_per_char(token) < _HIGH_ENTROPY_BITS:
        return False
    # A path is made of words: when most lowercase letters sit in runs of
    # three or more, the candidate names something and stays intact. The veto
    # covers `serveur/src/nexus`, `/var/backups/…`, `deployments/20261018/…`,
    # `C:/Users/Orion/AppData/…` and the camelCase routes
    # (`api/v1/users/getById/v2b1` — Antigravity review on d2361cc: judging
    # chunk by chunk alone erased them; every keep-corpus candidate that
    # reaches the guard sits at 0.64 or above).
    if _lower_run_share(token) >= 0.6:
        return False
    # A random value shuffles case between adjacent letters; a name changes
    # case at word starts. The veto above rules the word paths, and among the
    # candidates that reach this line 0.30 was the tightest floor that kept
    # the whole corpus (Antigravity review on d2361cc, finding 1: whole-value
    # signals do not depend on how the value happened to be chopped — real
    # 32-byte base64 keys leaked 16.1 % whole and 70.5 % partly).
    chaos = _case_chaos(token)
    if chaos is not None and chaos > 0.30:
        return True
    # A chopped value also keeps the signature of its chunks, worked out by
    # `_opaque_chunks` (24-character floor instead of 40, Antigravity review on
    # c73aee9: 24-to-39-character keys leaked). Two assumed limits stay, both
    # carrying no signal for that rule: an all-lowercase slashed blob and a
    # value whose every slash segment falls under the floor — as with the hex
    # segment of an asset path (#84).
    parts = [part for part in token.split("/") if part]
    return _opaque_chunks(parts)


# Segments that read as path words and cut a slashed candidate into windows
# (issue #144): a lowercase word with a short numeric suffix, digits alone, a
# version tag, or a name in camelCase / PascalCase / SCREAMING style.
_PATH_WORD = re.compile(r"[a-z]{3,}[0-9]{0,4}|[0-9]+|v[0-9]{1,3}")


def _path_word(segment: str) -> bool:
    return bool(_PATH_WORD.fullmatch(segment)) or _name_segment(segment)


# Segments of the opaque windows met by the passes of ONE `redact` call (issue #144).
# A ContextVar, never a module global: the scanner runs in concurrent workers, and
# each call (each thread, each task) sees only its own collector. None outside
# `redact`: the rule then collects nothing.
_WINDOW_SEGMENTS: ContextVar[set[str] | None] = ContextVar("window_segments", default=None)
# Shortest segment replaced afterwards: a shorter one is too common to be told apart.
_MIN_WINDOW_SEGMENT = 3


def _mask_opaque_windows(parts: list[str]) -> None:
    """Note the segments of the opaque windows between path words of a candidate.

    A key whose own slashes chop it into segments, written between path words
    (`s3://bucket/<key>/backups/production`, `api/v1/<key>/download`), made the
    words veto of `_opaque_slashed` rule the whole candidate a path, and the
    tail rule never finds a tail free of words: the key leaked. Cutting the
    candidate at every word leaves windows of consecutive non-word segments;
    a window of two segments or more that `_opaque_slashed` judges opaque has
    its segments noted in the collector of the running `redact` call.

    Nothing is rewritten here: masking a window during a pass changed what the
    next passes of the fixed point saw (`<16>/backups/MRS/rkEj/<24>` lost its
    entropy-masked tail and kept 16 opaque characters readable, PR 146 review).
    `redact` applies the noted segments once the passes of the existing rules
    reached their fixed point. One pass over the segments, each read once.
    """
    collector = _WINDOW_SEGMENTS.get()
    if collector is None:
        return
    window: list[str] = []

    def close() -> None:
        if 2 <= len(window) < len(parts) and _opaque_slashed("/".join(window)):
            collector.update(part for part in window if len(part) >= _MIN_WINDOW_SEGMENT)
        window.clear()

    for part in parts:
        if _path_word(part):
            close()
        else:
            window.append(part)
    close()


# A slashed run of the output of the passes: its segments may be `[REDACTED]` markers.
_MARKED_SLASHED_RUN = re.compile(
    r"(?<![A-Za-z0-9+])(?:\[REDACTED\]|[A-Za-z0-9+]+={0,2})"
    r"(?:/(?:\[REDACTED\]|[A-Za-z0-9+]+={0,2}))+"
)


def _mask_noted_segments(text: str, noted: set[str]) -> str:
    """Replace every noted segment found in a slashed run of `text` by a mask."""

    def mask_run(match: re.Match[str]) -> str:
        return "/".join(
            REDACTED if part in noted else part for part in match.group(0).split("/")
        )

    return _MARKED_SLASHED_RUN.sub(mask_run, text)


_VENDOR: list[tuple[str, re.Pattern[str]]] = [
    # Unanchored vendor formats (issue #101), applied by `redact` just before the entropy
    # pass and after every pass that reads a label, a URL, a header or a slashed value:
    # a format that ran first would stop at a space, a dot or a slash and leave the rest
    # of a value that master masks in the clear (PR #135 review). The run they mask is
    # exactly the maximal run the entropy pass reads, so they only add masks. A token
    # glued to an AWS key (`AKIA…<token>`) is masked whole in one pass because the closing
    # word boundary of `aws_access_key` fails after the key and the format takes the entire run.
    # New Relic browser key: `NRJS-` + 19 hex digits (76 bits, under any entropy floor).
    ("newrelic_key", re.compile(rf"{_GLUED_RUN}NRJS-[a-f0-9]{{19}}{_RUN_TAIL}")),
    # Sourcegraph access token: `sgp_` + 16 hex digits (or `local`) + `_` + 40 hex.
    ("sourcegraph_token", re.compile(
        rf"{_GLUED_RUN}sgp_(?:[a-fA-F0-9]{{16}}|local)_[a-fA-F0-9]{{40}}{_RUN_TAIL}"
    )),
    # GitLab tokens: `glpat-` and its siblings + 20 characters (119 bits).
    ("gitlab_token", re.compile(
        rf"{_GLUED_RUN}gl(?:pat|rt|dt|ft|soat|cbt|ptt)-[0-9A-Za-z_-]{{20}}{_RUN_TAIL}"
    )),
    # Databricks personal access token: `dapi` + 32 hex digits, optional `-<n>`.
    ("databricks_token", re.compile(rf"{_GLUED_RUN}dapi[a-f0-9]{{32}}{_RUN_TAIL}")),
]


# Fixed-point bound of `redact` (issue #126): the slashed-value pass and the entropy
# pass can feed each other, so a masked tail makes the next pass read the remaining
# head as opaque and mask more. Retuning the detection rules to avoid that would risk
# leaving a real secret in the clear (over-redaction is the accepted price, ADR-006);
# running the unchanged passes again until nothing moves is safe by construction, since
# a pass only ever adds masks. Three passes are enough for the observed cases, and a
# text without a secret stops after the first one.
_MAX_PASSES = 3


def _redact_once(text: str) -> tuple[str, list[str]]:
    """Apply every masking pass once; return the masked text and the kinds found."""
    found: list[str] = []
    for kind, pattern in _FULL:
        text, count = pattern.subn(REDACTED, text)
        if count:
            found.append(kind)

    def mask_value(match: re.Match[str]) -> str:
        label, separator, double, single, glued, bare = match.groups()
        value = next(v for v in (double, single, bare) if v is not None)
        # Text glued after the closing quote means the quote did not end the value;
        # a value (glued text included) made only of markers is already masked.
        masked = value + (glued or "")
        if not masked or _ONLY_MARKERS.fullmatch(masked):
            return match.group(0)
        found.append("credential")
        quote = '"' if double is not None else "'" if single is not None else ""
        return f"{label}{separator}{quote}{REDACTED}{quote}"

    def mask_url(match: re.Match[str]) -> str:
        if match.group(2) == REDACTED:
            return match.group(0)
        found.append("url_credentials")
        return f"{match.group(1)}{REDACTED}{match.group(3)}"

    def mask_header(match: re.Match[str]) -> str:
        if match.group(3).strip() == REDACTED:
            return match.group(0)
        found.append("credential")
        return f"{match.group(1)}{match.group(2)}{REDACTED}"

    def mask_random_run(match: re.Match[str]) -> str:
        token = match.group(0)
        if not (_opaque_run(token) or _opaque_material(token)):
            return token
        found.append("high_entropy")
        return REDACTED

    def mask_slashed_run(match: re.Match[str]) -> str:
        token = match.group(0)
        if _opaque_slashed(token):
            found.append("high_entropy")
            return REDACTED
        # The match starts on the FIRST segment, and a value written behind
        # path words comes with them: the candidate then reads as a path and
        # the value leaked whole (`cat /etc/tokens/A1b2…/K1l2…` — Antigravity
        # review on 5b186c5). Mask from the head of the longest opaque tail
        # and keep the path words ahead of it.
        parts = token.split("/")
        start = _opaque_tail_start(parts)
        if start is not None:
            found.append("high_entropy")
            return "/".join(parts[:start]) + "/" + REDACTED
        # Neither the whole candidate nor its tail is opaque: path words may
        # sit on BOTH sides of the value (`s3://bucket/<key>/backups/production`).
        # The rule only notes the segments; `redact` masks them afterwards.
        _mask_opaque_windows(parts)
        return token

    # Labelled values run FIRST: a value that is itself a URL holding credentials
    # is masked whole (one marker, no doubled [REDACTED]), then the URL and header
    # layers clean up what is left. The slashed pass runs just before the entropy
    # pass so a segmented value is masked whole (issue #84), and the entropy pass
    # runs last.
    text = _ASSIGNMENT.sub(mask_value, text)
    text = _URL_CREDENTIALS.sub(mask_url, text)
    text = _HEADER_CREDENTIALS.sub(mask_header, text)
    text = _SLASHED_TOKEN.sub(mask_slashed_run, text)
    for kind, pattern in _VENDOR:
        text, count = pattern.subn(REDACTED, text)
        if count:
            found.append(kind)
    text = _ENTROPY_TOKEN.sub(mask_random_run, text)
    return text, sorted(set(found))


def _converge(text: str) -> tuple[str, list[str]]:
    """Run `_redact_once` until a fixed point, at most `_MAX_PASSES` passes."""
    found: list[str] = []
    for _ in range(_MAX_PASSES):
        masked, kinds = _redact_once(text)
        found.extend(kinds)
        if masked == text:
            break
        text = masked
    return text, found


def redact(text: str) -> tuple[str, list[str]]:
    """Mask text until a fixed point, at most `_MAX_PASSES` passes.

    Return the masked text and every kind of secret found along the way, duplicates
    included: a later pass only reports what it actually masked.

    The passes first reach the fixed point of the older rules, while the window rule
    (issue #144) only notes the opaque segments it meets in a collector local to this
    call. Those segments are then masked in the slashed runs of the output and the
    passes run again with the collection still active, at most `_MAX_PASSES` rounds:
    the window rule only ever adds masks on top of the older rules' result. A text
    without a noted segment costs nothing more.
    """
    collector: set[str] = set()
    token = _WINDOW_SEGMENTS.set(collector)
    try:
        text, found = _converge(text)
        for _ in range(_MAX_PASSES):
            if not collector:
                break
            masked = _mask_noted_segments(text, collector)
            if masked == text:
                break
            found.append("high_entropy")
            text, kinds = _converge(masked)
            found.extend(kinds)
    finally:
        _WINDOW_SEGMENTS.reset(token)
    return text, found


# Un secret masqué et ce qui l'entoure : étiquette suivie de : ou = (password=),
# guillemets, parenthèses. Un simple mot devant (« utiliser [REDACTED] ») reste du sens.
_REDACTED_SPAN = re.compile(r"(?:[\w.-]+\s*[:=]\s*)?[\"'(\[]*\[REDACTED\][\"')\]]*")


def is_blank(text: str | None) -> bool:
    """Vide, ou ne contenant que des secrets masqués : ne dit rien d'utilisable."""
    if not text:
        return True
    return not re.search(r"\w", _REDACTED_SPAN.sub("", text))


def is_blank_reference(text: str | None) -> bool:
    """Une preuve doit garder un identifiant : « commit: token=[REDACTED] » n'a plus que
    son étiquette, elle ne prouve rien."""
    if is_blank(text):
        return True
    rest = _REDACTED_SPAN.sub("", text)
    rest = re.sub(r"^\s*[\w.-]+\s*:", "", rest, count=1)  # étiquette : commit:, url:, https:
    # Étiquettes restées vides ailleurs (« … url: ») : elles ne portent aucun identifiant.
    rest = re.sub(r"[\w.-]+\s*[:=](?=\s|$)", "", rest)
    return not re.search(r"\w", rest)


def redact_value(value: Any) -> tuple[Any, list[str]]:
    """Comme `redact`, sur une chaîne, une liste ou un dict — clés comprises : un secret
    collé comme nom de propriété JSON serait sinon stocké tel quel."""
    found: set[str] = set()

    def walk(v: Any) -> Any:
        if isinstance(v, str):
            cleaned, kinds = redact(v)
            found.update(kinds)
            return cleaned
        if isinstance(v, (list, tuple)):  # un tuple part en JSON comme une liste
            return [walk(x) for x in v]
        if isinstance(v, dict):
            return {
                (walk(k) if isinstance(k, str) else k): mask_if_credential(k, x)
                for k, x in v.items()
            }
        return v

    def mask_if_credential(key: Any, value: Any) -> Any:
        # Sous une clé d'identifiant, toute valeur non vide est un secret — liste ou objet
        # compris ({"password": ["…"]}, {"api_key": {"value": "…"}}).
        if isinstance(value, str):
            empty = not value.strip() or value == REDACTED
        else:
            empty = value is None or value == [] or value == {}
        if isinstance(key, str) and _CREDENTIAL_KEY.fullmatch(key.strip()) and not empty:
            found.add("credential")
            return REDACTED
        return walk(value)

    return walk(value), sorted(found)


def redact_fields(
    values: dict[str, Any], on_found: Callable[[str, list[str]], None] | None = None
) -> dict[str, Any]:
    """Masque chaque champ ; `on_found(champ, types)` est appelé pour chaque champ touché."""
    cleaned = {}
    for field, value in values.items():
        cleaned[field], kinds = redact_value(value)
        if kinds and on_found:
            on_found(field, kinds)
    return cleaned
