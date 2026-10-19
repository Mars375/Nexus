"""Actor bearer tokens (ADR-020): generation, digest and lookup.

Nexus keeps only the SHA-256 digest of a token. 256 bits of entropy make a salt or a slow hash
pointless. Lookup is by digest, confirmed with a constant-time comparison, and never cached:
a revocation is effective on the next request.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import re
import secrets
import unicodedata
from datetime import timedelta

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from nexus import secrets as redaction
from nexus.actors import ACTORS
from nexus.clock import now
from nexus.models import ActorToken

PREFIX = "nxt_"
BODY_LENGTH = 43  # base64url of 32 bytes, without padding
LABEL_MAX = 64
TOUCH_WINDOW = timedelta(seconds=300)  # at most one last_used_at write per token per window

# ASCII alphabet spelled out: `\d` and `\w` accept other scripts' digits and letters.
_FORMAT = re.compile(rf"nxt_[A-Za-z0-9_-]{{{BODY_LENGTH}}}")

log = logging.getLogger("nexus")


def generate() -> str:
    body = base64.urlsafe_b64encode(secrets.token_bytes(32)).rstrip(b"=").decode("ascii")
    return PREFIX + body


def digest(token: str) -> str:
    return hashlib.sha256(token.encode("ascii")).hexdigest()


def is_well_formed(token: object) -> bool:
    """Checked before any hashing: a presented value of any other shape is never looked up."""
    return isinstance(token, str) and token.isascii() and _FORMAT.fullmatch(token) is not None


def lookup_row(session: Session, token: str) -> ActorToken | None:
    """The row of a live (non-revoked) token, or None."""
    if not is_well_formed(token):
        return None
    wanted = digest(token)
    row = session.scalars(
        select(ActorToken).where(ActorToken.token_hash == wanted, ActorToken.revoked_at.is_(None))
    ).first()
    if row is None or not hmac.compare_digest(row.token_hash, wanted):
        return None
    return row


def lookup(session: Session, token: str) -> str | None:
    """The actor a live (non-revoked) token belongs to, or None."""
    row = lookup_row(session, token)
    return row.actor if row is not None else None


def is_live(session: Session, token_id: int) -> bool:
    """Whether the token row still exists and is not revoked; an absent row counts as revoked."""
    row = session.get(ActorToken, token_id)
    return row is not None and row.revoked_at is None


def touch_last_used(factory, token_id: int) -> None:
    """Record that a token was used, at most once per window; never fails the caller.

    A separate short session keeps a failure (locked database, disk full) away from the
    request's own transaction. The conditional UPDATE is atomic: simultaneous requests write
    once, and the others see a rowcount of zero.
    """
    try:
        with factory() as session:
            session.execute(
                update(ActorToken)
                .where(
                    ActorToken.id == token_id,
                    (ActorToken.last_used_at.is_(None))
                    | (ActorToken.last_used_at < now() - TOUCH_WINDOW),
                )
                .values(last_used_at=now())
            )
            session.commit()
    except Exception:
        # The request keeps working: a missed timestamp only delays the next write.
        log.warning("dernière utilisation du jeton %s non enregistrée", token_id)


def clean_label(label: str) -> str:
    """Stripped, 1 to 64 printable characters, no secret. Never echoes the value."""
    if not isinstance(label, str):
        raise ValueError("le label doit être un texte")
    # Space separators (category Zs: no-break space, narrow no-break space...) become a plain
    # space; control and format characters stay refused below.
    label = "".join(" " if unicodedata.category(c) == "Zs" else c for c in label).strip()
    if not label:
        raise ValueError("le label ne peut pas être vide")
    if len(label) > LABEL_MAX:
        raise ValueError(f"le label fait au plus {LABEL_MAX} caractères")
    if not label.isprintable():
        raise ValueError("le label ne peut contenir que des caractères imprimables")
    if redaction.redact(label)[0] != label:
        raise ValueError("le label ne peut pas contenir de secret")
    return label


def issue(session: Session, actor: str, label: str) -> tuple[ActorToken, str]:
    """Create a token row (flushed, not committed) and return it with the clear token."""
    if actor not in ACTORS:
        raise ValueError("acteur inconnu")
    token = generate()
    row = ActorToken(
        actor=actor, label=clean_label(label), token_hash=digest(token), created_at=now()
    )
    session.add(row)
    session.flush()
    return row, token
