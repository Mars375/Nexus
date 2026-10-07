"""Authentication dependency (ADR-020).

PR 1: a bearer token is accepted when present; without an `Authorization` header the former
behaviour stays (`X-Nexus-Actor`, `loic` by default). Nothing received is ever echoed back.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Header, HTTPException, Request, status
from sqlalchemy.orm import Session

from nexus.actors import ACTORS, DEFAULT_ACTOR
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


def token_actor(
    session: Annotated[Session, Depends(get_session)],
    authorization: Annotated[str | None, Header()] = None,
    x_nexus_actor: Annotated[str | None, Header()] = None,
) -> str | None:
    """The actor of the presented token; None when no `Authorization` header is sent."""
    if authorization is None:
        return None
    token = bearer_token(authorization)
    if token is None:
        raise _unauthorized("auth_required", "authentification requise : jeton porteur attendu")
    actor = tokens.lookup(session, token)
    if actor is None:
        raise _unauthorized("invalid_token", "jeton invalide ou révoqué")
    if x_nexus_actor is not None and x_nexus_actor != actor:
        raise HTTPException(status.HTTP_403_FORBIDDEN, {
            "code": "actor_mismatch",
            "message": "l'acteur de l'en-tête X-Nexus-Actor diffère de celui du jeton",
        })
    return actor


def authenticated_actor(
    from_token: Annotated[str | None, Depends(token_actor)],
    x_nexus_actor: Annotated[str | None, Header()] = None,
) -> str:
    if from_token is not None:
        return from_token
    actor = x_nexus_actor or DEFAULT_ACTOR
    if actor not in ACTORS:
        # La valeur reçue n'est jamais renvoyée : l'en-tête pourrait contenir un secret.
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "acteur inconnu dans l'en-tête X-Nexus-Actor"
        )
    return actor
