"""Authentication dependency (ADR-020): every route but `GET /api/health` requires a token.

The actor is the one the bearer token was issued to, never a declared header. `X-Nexus-Actor`
stays optional and must equal that actor (D9). Nothing received is ever echoed back.
"""

from __future__ import annotations

from typing import Annotated, NamedTuple

from fastapi import Depends, Header, HTTPException, Request, status
from sqlalchemy.orm import Session

from nexus.auth import tokens

_CHALLENGE = {"WWW-Authenticate": "Bearer"}


def get_session(request: Request):
    with request.app.state.sessionmaker() as session:
        yield session


def _unauthorized(code: str, message: str) -> HTTPException:
    return HTTPException(
        status.HTTP_401_UNAUTHORIZED, {"code": code, "message": message}, headers=_CHALLENGE
    )


def bearer_token(authorization: str) -> str | None:
    """The token of a well-formed `Bearer <token>` value, else None."""
    scheme, separator, token = authorization.partition(" ")
    if separator != " " or scheme.lower() != "bearer" or not tokens.is_well_formed(token):
        return None
    return token


class TokenIdentity(NamedTuple):
    """Who a presented token is: its row (to check it is still live later) and its actor."""

    token_id: int
    actor: str
    # Binds a WebSocket ticket to this token; never logged.
    token_hash: str


def authenticated_token(
    request: Request,
    session: Annotated[Session, Depends(get_session)],
    authorization: Annotated[str | None, Header()] = None,
    x_nexus_actor: Annotated[str | None, Header()] = None,
) -> TokenIdentity:
    """The token row id and actor of the presented token; 401 without a valid one, 403 on a header
    mismatch. A successful authentication records the token's last use."""
    token = None if authorization is None else bearer_token(authorization)
    if token is None:
        raise _unauthorized(
            "auth_required", "en-tête Authorization : jeton porteur attendu (Bearer nxt_…)"
        )
    row = tokens.lookup_row(session, token)
    if row is None:
        raise _unauthorized("invalid_token", "en-tête Authorization : jeton invalide ou révoqué")
    if x_nexus_actor is not None and x_nexus_actor != row.actor:
        raise HTTPException(status.HTTP_403_FORBIDDEN, {
            "code": "actor_mismatch",
            "message": "l'acteur de l'en-tête X-Nexus-Actor diffère de celui du jeton",
        })
    tokens.touch_last_used(
        request.app.state.touch_sessionmaker, row.id, last_used_at=row.last_used_at
    )
    return TokenIdentity(row.id, row.actor, row.token_hash)


def authenticated_actor(identity: Annotated[TokenIdentity, Depends(authenticated_token)]) -> str:
    """The actor of the presented token; 401 without a valid one, 403 on a header mismatch."""
    return identity.actor


Authenticated = [Depends(authenticated_actor)]
"""Router-level dependency list: `APIRouter(dependencies=Authenticated)`."""
