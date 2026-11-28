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

# NUL breaks the body CHECK of 0010; \x02 and \x03 are the marks of `snippet()`.
_DROP = str.maketrans("", "", "\x00\x02\x03")
# `json.loads` admits a lone surrogate, which SQLite refuses to encode mid-batch.
_SURROGATE = re.compile("[\ud800-\udfff]")
_MODEL = re.compile(rf"[A-Za-z0-9._:-]{{1,{MODEL_MAX}}}")
_FACTORY = object()
# Joins of text blocks (`join_blocks`): the separator that stands for a join while it is
# judged, the context kept on each side, and the joins judged one by one.
_JOIN_MARK = "\n\x1f\n"
_LEFT_MAX, _RIGHT_MAX, _JOINS_MAX = 4096, 256, 256


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


def _crosses(left: str, right: str) -> bool:
    """Whether `redact` masks `left + right` otherwise than with a separator between them:
    a secret (or its label) then spans the join. Both start on a line break, so the start of
    `left` keeps its word boundary."""
    tight = redact(_clean(f"\n{left}{right}"))[0]
    split = redact(_clean(f"\n{left}{_JOIN_MARK}{right}"))[0].replace(_JOIN_MARK, "")
    return tight != split


class Joined(str):
    """Text blocks joined by `join_blocks`; `masked` says a split secret was masked there, so
    `make_message` reports the message as redacted even when `redact` finds nothing more."""

    masked: bool = False


def _masked_whole() -> Joined:
    joined = Joined(REDACTED)
    joined.masked = True
    return joined


def join_blocks(parts: list[str]) -> Joined:
    """Text blocks joined by a blank line, which keeps each block's word boundaries for
    `redact`. When a secret (or its label) may span a join (see `_crosses`), the whole message
    is masked: masking only the blocks around the join loses the context a neighbour needs
    (`password` | `=value`), and a secret of several words would leave words behind. Each
    join is judged on the whole block before it (up to `_LEFT_MAX`) and on the glued tail
    before it, against what follows it glued (`_RIGHT_MAX`), so a label far from the join, a
    prefix left in an earlier block and a secret over three blocks or more are all seen. Past
    `_JOINS_MAX` joins, the whole message is masked too (a bounded cost, over-masking)."""
    if len(parts) < 2:
        return Joined("".join(parts))
    if len(parts) - 1 > _JOINS_MAX:
        return _masked_whole()
    tight = "".join(parts)
    starts = list(itertools.accumulate((len(p) for p in parts), initial=0))
    for k in range(len(parts) - 1):
        right = tight[starts[k + 1]:starts[k + 1] + _RIGHT_MAX]
        glued = tight[max(0, starts[k + 1] - _LEFT_MAX):starts[k + 1]]
        if _crosses(parts[k][-_LEFT_MAX:], right) or _crosses(glued, right):
            return _masked_whole()
    return Joined("\n\n".join(parts))


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
    redacted = redacted or getattr(text, "masked", False)
    if not masked:
        return None
    body, truncated = cut(masked, BODY_MAX)
    # A token fits the model pattern too: a model the scanner flags is dropped, never stored.
    kept = model if (isinstance(model, str) and _MODEL.fullmatch(model)
                     and not redact(model)[1]) else None
    return ParsedMessage(external_id, role, author, at, body, truncated, redacted, kept,
                         _FACTORY)
