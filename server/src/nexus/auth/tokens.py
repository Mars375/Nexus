"""Actor bearer tokens (ADR-020): generation, digest and lookup.

Nexus keeps only the SHA-256 digest of a token. 256 bits of entropy make a salt or a slow hash
pointless. Lookup is by digest, confirmed with a constant-time comparison, and never cached:
a revocation is effective on the next request.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import re
import secrets

from sqlalchemy import select
from sqlalchemy.orm import Session

from nexus import secrets as redaction
from nexus.actors import ACTORS
from nexus.clock import now
from nexus.models import ActorToken

PREFIX = "nxt_"
BODY_LENGTH = 43  # base64url of 32 bytes, without padding
LABEL_MAX = 64

# ASCII alphabet spelled out: `\d` and `\w` accept other scripts' digits and letters.
_FORMAT = re.compile(rf"nxt_[A-Za-z0-9_-]{{{BODY_LENGTH}}}")


def generate() -> str:
    body = base64.urlsafe_b64encode(secrets.token_bytes(32)).rstrip(b"=").decode("ascii")
    return PREFIX + body


def digest(token: str) -> str:
    return hashlib.sha256(token.encode("ascii")).hexdigest()


def is_well_formed(token: object) -> bool:
    """Checked before any hashing: a presented value of any other shape is never looked up."""
    return isinstance(token, str) and token.isascii() and _FORMAT.fullmatch(token) is not None


def lookup(session: Session, token: str) -> str | None:
    """The actor a live (non-revoked) token belongs to, or None."""
    if not is_well_formed(token):
        return None
    wanted = digest(token)
    row = session.scalars(
        select(ActorToken).where(ActorToken.token_hash == wanted, ActorToken.revoked_at.is_(None))
    ).first()
    if row is None or not hmac.compare_digest(row.token_hash, wanted):
        return None
    return row.actor


def clean_label(label: str) -> str:
    """Stripped, 1 to 64 printable characters, no secret. Never echoes the value."""
    if not isinstance(label, str):
        raise ValueError("le label doit être un texte")
    label = label.strip()
    if not label:
        raise ValueError("le label ne peut pas être vide")
    if len(label) > LABEL_MAX:
        raise ValueError(f"le label fait au plus {LABEL_MAX} caractères")
    if not label.isprintable():
        raise ValueError("le label ne peut pas contenir de caractère de contrôle")
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
