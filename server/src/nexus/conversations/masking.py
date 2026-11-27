"""The masking factory of the conversation index (spec §7.1, ADR-025 D5).

Every text kept from a source goes through here before it leaves the reader: the whole text is
masked by `nexus.secrets.redact` (within the 1 MiB line bound), then cut to its column's length
without ever splitting a redaction mark. `ParsedMessage` is only built by `make_message`: no code
path can hand a raw text to the index.
"""

from __future__ import annotations

import itertools
import re
from dataclasses import dataclass, field
from datetime import datetime

from nexus.conversations import models
from nexus.secrets import REDACTED, redact

BODY_MAX = models.BODY_MAX
TITLE_MAX, WORKSPACE_MAX, BRANCH_MAX, MODEL_MAX = 200, 500, 200, 64
AUTHOR_MAX = 32
JOIN_WINDOW = 512  # characters kept on each side of a join between two text blocks

# NUL breaks the body CHECK of 0010; \x02 and \x03 are the marks of `snippet()`.
_DROP = str.maketrans("", "", "\x00\x02\x03")
# `json.loads` admits a lone surrogate, which SQLite refuses to encode mid-batch.
_SURROGATE = re.compile("[\ud800-\udfff]")
_MODEL = re.compile(rf"[A-Za-z0-9._:-]{{1,{MODEL_MAX}}}")
_FACTORY = object()


@dataclass(frozen=True)
class ParsedMessage:
    external_id: str
    role: str
    author: str
    at: datetime
    body: str
    truncated: bool
    redacted: bool
    model: str | None
    _key: object = field(default=None, repr=False, compare=False)

    def __post_init__(self) -> None:
        if self._key is not _FACTORY:
            raise ValueError("ParsedMessage se construit par make_message")


def _clean(text: str) -> str:
    return _SURROGATE.sub("�", text.translate(_DROP))


def cut(masked: str, limit: int) -> tuple[str, bool]:
    """`masked` cut to `limit` characters; a mark that straddles the cut is dropped whole."""
    if len(masked) <= limit:
        return masked, False
    start = masked.find(REDACTED, max(0, limit - len(REDACTED) + 1))
    end = start if 0 <= start < limit else limit
    return masked[:end], True


def _mask(text: str) -> tuple[str, bool]:
    masked, found = redact(_clean(text))
    return masked.strip(), bool(found)


def join_blocks(parts: list[str]) -> str:
    """Text blocks joined by a blank line, unless a secret only shows once they touch: a
    secret split between two blocks would escape `redact` behind the separator."""
    spaced = "\n\n".join(parts)
    for left, right in itertools.pairwise(parts):  # only the text around each join is scanned
        left, right = left[-JOIN_WINDOW:], right[:JOIN_WINDOW]
        if len(redact(_clean(left + right))[1]) > len(redact(_clean(f"{left}\n\n{right}"))[1]):
            return "".join(parts)
    return spaced


def mask_field(text: object, limit: int) -> str | None:
    """A session field (title, workspace, git branch) masked then cut, or None."""
    if not isinstance(text, str):
        return None
    masked, _ = _mask(text)
    return cut(masked, limit)[0] or None


def make_message(*, external_id: str, role: str, author: str, at: datetime, text: object,
                 model: object = None) -> ParsedMessage | None:
    """The masked message, None when nothing is left; ValueError on an invalid field."""
    if role not in models.ROLES:
        raise ValueError("rôle inconnu")
    if not isinstance(author, str) or not 1 <= len(author) <= AUTHOR_MAX:
        raise ValueError("auteur invalide")
    if not isinstance(at, datetime) or at.tzinfo is None:
        raise ValueError("instant sans fuseau refusé")
    if not isinstance(text, str) or not isinstance(external_id, str):
        raise ValueError("texte invalide")
    masked, redacted = _mask(text)
    if not masked:
        return None
    body, truncated = cut(masked, BODY_MAX)
    # A token fits the model pattern too: a model the scanner flags is dropped, never stored.
    kept = model if (isinstance(model, str) and _MODEL.fullmatch(model)
                     and not redact(model)[1]) else None
    return ParsedMessage(external_id, role, author, at, body, truncated, redacted, kept,
                         _FACTORY)
