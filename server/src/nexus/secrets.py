"""Détection et masquage des secrets avant toute écriture (ADR-006, SECURITY §1).

Aucun secret n'est stocké, journalisé ni renvoyé : toute correspondance devient `[REDACTED]`.
Les motifs visent des formats reconnaissables pour limiter les faux positifs sur du texte normal.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Callable
from math import log2
from typing import Any

REDACTED = "[REDACTED]"

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
# A `?` or `#` never belongs to the userinfo at all (issue #84: without the
# restriction, `?redirect=mailto:alice@…` made the query's tail a « user » and
# erased `alice`). The password part carries the same restriction — Antigravity
# review on 6d78a6c: `host:port?q=…@…` read the port and the query head as a
# password and erased them, while an unencoded `?`/`#` always ends the userinfo.
_URL_CREDENTIALS = re.compile(r"(?i)\b([a-z][a-z0-9+.-]*://(?:[^\s:/@?#]+)?:)([^\s@/?#]+)(@)")

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

_ASSIGNMENT = re.compile(
    rf"(?i)(?<![\w.-])({_LABEL})"
    r"([\"']?\s*[:=]\s*)"
    # Bare value: one run, or several space-separated runs, up to the end of
    # the line — a multi-word passphrase (« mot de passe : correct horse battery
    # staple ») is masked whole (issue #15). The first run starts at a character
    # that is not a space, comma, semicolon, brace, quote or line break, and
    # bracket fragments glued to the run stay inside the value: a value
    # starting at `[` goes through the bracket shell FIRST (alternation order), a
    # value that starts at an existing [REDACTED] therefore never reaches the
    # naked-run chain, so the prose after the shell stays prose and the shell
    # value comes back unchanged through mask_value's short circuit. A word
    # followed by `=` or `:`, IF it is one of the recognised labels, ends the
    # sweep instead of joining it (the label-aware lookahead pulls it back
    # out): the resumed scan then masks it under its own label, the tail
    # [REDACTED] is never doubled, and a passphrase word that merely carries
    # an `=` (« battery=staple ») stays inside the value. A wrapped value
    # (`password=[hunter2]`) is captured with its whole shell, spaces
    # included, and the code glued right after the shell
    # (`password=[hunter2]abc123`) joins the same value; a shell that is
    # never closed is captured up to the end of the line — nothing is left
    # in the clear. An auth scheme (Basic xyz) is part of the value.
    r"(?:\"([^\"]*)\"|'([^']*)'"
    r"|((?:(?:basic|bearer|digest|negotiate|ntlm)\s+)?"
    rf"(?:\[[^\]\r\n]*\]?[^\t \r\n,;}}\"']*|[^\t \r\n,;}}\"']+(?:[ \t]+(?!(?:{_LABEL})\s*[=:])"
    r"[^\t \r\n,;}}\"']+)*)))"
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
# `_opaque_slashed` rules on the whole candidate and an opaque run takes it all
# (over-redaction, ADR-006). `_` and `-` stay out of the class: a slashed
# standard-base64 value never carries them, while paths and slugs do.
_SLASHED_TOKEN = re.compile(r"(?<![A-Za-z0-9+=])[A-Za-z0-9+=]{1,}(?:/[A-Za-z0-9+=]+)+")
# Shannon entropy in bits per character: long natural words and repetitions sit
# around 2-3 bits, a uniform 16-symbol hex run stays near log2(16) = 4 — the
# threshold divides prose from opaque randomness (documented in issue #15).
_HIGH_ENTROPY_BITS = 3.5


def _shannon_bits_per_char(token: str) -> float:
    n = len(token)
    return -sum((p / n) * log2(p / n) for p in Counter(token).values())


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
    # length (≥ 8) AND carries a digit: « tok_Y7qP2rTx_… » is opaque (issue
    # #84), while a snake_case identifier whose tail is plain words —
    # get_database_connection1, id-utilisateur-authentification1 — stays an
    # identifier even above the entropy threshold (Antigravity review on
    # 6d78a6c: the digit-free `database` used to pass on length alone).
    if len(parts) >= 2 and len(parts[0]) < 8 and all(
        len(part) >= 8 and any(ch.isdigit() for ch in part) for part in parts[1:]
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
    pairs = list(zip(segment, segment[1:], strict=False))
    # Letters and digits alternate: the signature of a chunked base64 value.
    boundaries = sum(
        1
        for left, right in pairs
        if (left.isalpha() and right.isdigit()) or (left.isdigit() and right.isalpha())
    )
    if len(pairs) >= 3 and boundaries / len(pairs) >= 0.6:
        return True
    # Case changes at random rather than at word starts (letter pairs only).
    # Short PascalCase names (`ApiV2`, `AppData`) stay out: a real value mixes
    # case across many more letter pairs than a name holds.
    letter_pairs = [(left, right) for left, right in pairs if left.isalpha() and right.isalpha()]
    return (
        len(letter_pairs) >= 6
        and sum(1 for left, right in letter_pairs if left.isupper() != right.isupper())
        / len(letter_pairs)
        > 0.5
    )


def _opaque_slashed(token: str) -> bool:
    """Guard of the slashed pattern (issue #84): an opaque chopped value, not a path."""
    if len(token) < 24:
        return False
    if not any(ch.isdigit() for ch in token):
        return False
    if _shannon_bits_per_char(token) < _HIGH_ENTROPY_BITS:
        return False
    # A chopped value keeps the signature of its chunks: at least TWO of them
    # are blobs (24-character floor instead of 40, Antigravity review on
    # c73aee9: 24-to-39-character keys leaked). Paths of words
    # (`deployments/20261018/releases/build42/output`), case-mixed deployment
    # names (`Apps/V2Prod2026/Release42Build`) and source paths
    # (`src/views/AccountSettingsV2/OAuth2Callback`) reach zero or one blob and
    # stay intact. An all-lowercase slashed blob still reads as words to the
    # guard: assumed limit, as with the hex segment of an asset path (#84).
    return sum(1 for part in token.split("/") if part and _blob_segment(part)) >= 2


def redact(text: str) -> tuple[str, list[str]]:
    """Renvoie le texte masqué et la liste des types de secrets trouvés."""
    found: list[str] = []
    for kind, pattern in _FULL:
        text, count = pattern.subn(REDACTED, text)
        if count:
            found.append(kind)

    def mask_value(match: re.Match[str]) -> str:
        label, separator, double, single, bare = match.groups()
        value = next(v for v in (double, single, bare) if v is not None)
        if not value or value == REDACTED:
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
        if not _opaque_run(token):
            return token
        found.append("high_entropy")
        return REDACTED

    def mask_slashed_run(match: re.Match[str]) -> str:
        token = match.group(0)
        if not _opaque_slashed(token):
            return token
        found.append("high_entropy")
        return REDACTED

    # Labelled values run FIRST: a value that is itself a URL holding credentials
    # is masked whole (one marker, no doubled [REDACTED]), then the URL and header
    # layers clean up what is left. The slashed pass runs just before the entropy
    # pass so a segmented value is masked whole (issue #84), and the entropy pass
    # runs last.
    text = _ASSIGNMENT.sub(mask_value, text)
    text = _URL_CREDENTIALS.sub(mask_url, text)
    text = _HEADER_CREDENTIALS.sub(mask_header, text)
    text = _SLASHED_TOKEN.sub(mask_slashed_run, text)
    text = _ENTROPY_TOKEN.sub(mask_random_run, text)
    return text, sorted(set(found))


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
