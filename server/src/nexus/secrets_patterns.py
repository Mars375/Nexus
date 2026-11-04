"""Motifs de détection des secrets (ADR-006, SECURITY §1) : formats reconnaissables, URL, en-têtes,
étiquettes et valeurs. Aucune logique de masquage ici : `nexus.secrets` les applique."""

from __future__ import annotations

import re

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


# A slashed run of the output of the passes: its segments may be `[REDACTED]` markers.
_MARKED_SLASHED_RUN = re.compile(
    r"(?<![A-Za-z0-9+])(?:\[REDACTED\]|[A-Za-z0-9+]+={0,2})"
    r"(?:/(?:\[REDACTED\]|[A-Za-z0-9+]+={0,2}))+"
)


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
