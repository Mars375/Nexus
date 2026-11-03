"""Détection et masquage des secrets avant toute écriture (ADR-006, SECURITY §1).

Aucun secret n'est stocké, journalisé ni renvoyé : toute correspondance devient `[REDACTED]`.
Les motifs visent des formats reconnaissables pour limiter les faux positifs sur du texte normal.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any

from nexus.secrets_entropy import (
    _expected_entropy as _expected_entropy,
)
from nexus.secrets_entropy import (
    _opaque_material,
    _opaque_run,
)
from nexus.secrets_patterns import (
    _ASSIGNMENT,
    _CREDENTIAL_KEY,
    _ENTROPY_TOKEN,
    _FULL,
    _HEADER_CREDENTIALS,
    _ONLY_MARKERS,
    _SLASHED_TOKEN,
    _URL_CREDENTIALS,
    _VENDOR,
    REDACTED,
)
from nexus.secrets_slashed import (
    _WINDOWS,
    _mask_noted_segments,
    _mask_opaque_windows,
    _opaque_slashed,
    _opaque_tail_start,
)
from nexus.secrets_slashed import (
    _path_word as _path_word,
)

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
    collector: set[tuple[str, ...]] = set()
    token = _WINDOWS.set(collector)
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
        _WINDOWS.reset(token)
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
