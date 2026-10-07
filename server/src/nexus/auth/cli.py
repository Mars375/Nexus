"""`nexus-token` : émission, liste et révocation des jetons d'acteur (ADR-020, D3).

Le jeton n'est affiché qu'une fois, sur la sortie standard et rien d'autre ; les consignes vont
sur la sortie d'erreur. La CLI ne migre jamais la base : elle exige que Nexus l'ait fait.
"""

from __future__ import annotations

import argparse
import re
import sys
from collections.abc import Sequence

from sqlalchemy import select, update
from sqlalchemy.orm import sessionmaker

from nexus import migrate
from nexus.actors import ACTORS
from nexus.auth import tokens
from nexus.clock import now
from nexus.config import Settings
from nexus.db import make_engine
from nexus.models import ActorToken

_REF = re.compile(r"nx-tok-([0-9]{1,12})")


def _error(message: str) -> int:
    print(f"Erreur : {message}", file=sys.stderr)
    return 1


def _issue(factory, args: argparse.Namespace) -> int:
    with factory() as session:
        try:
            row, token = tokens.issue(session, args.actor, args.label)
        except ValueError as exc:
            session.rollback()
            return _error(str(exc))
        session.commit()
        ref, actor, label = row.ref, row.actor, row.label
    print(token)
    print(
        f"Jeton {ref} émis pour {actor} ({label}). Il ne sera plus jamais affiché : "
        "conserve-le maintenant (variable NEXUS_TOKEN ou fichier protégé). "
        f"Pour le révoquer : nexus-token revoke {ref}",
        file=sys.stderr,
    )
    return 0


def _list(factory, _args: argparse.Namespace) -> int:
    with factory() as session:
        rows = session.scalars(select(ActorToken).order_by(ActorToken.id)).all()
    if not rows:
        print("Aucun jeton émis.")
        return 0
    for row in rows:
        revoked = f"révoqué {row.revoked_at:%Y-%m-%d %H:%M}" if row.revoked_at else "actif"
        print(
            f"{row.ref}  {row.actor:<8}  {row.label}  créé {row.created_at:%Y-%m-%d %H:%M}"
            f"  {revoked}"
        )
    return 0


def _revoke(factory, args: argparse.Namespace) -> int:
    match = _REF.fullmatch(args.ref)
    if match is None:
        return _error("référence invalide (attendu : nx-tok-<n>)")
    token_id = int(match.group(1))
    with factory() as session:
        # Un seul UPDATE conditionnel : deux révocations simultanées n'en font qu'une.
        changed = session.execute(
            update(ActorToken)
            .where(ActorToken.id == token_id, ActorToken.revoked_at.is_(None))
            .values(revoked_at=now())
        ).rowcount
        session.commit()
        if changed:
            print(f"Jeton nx-tok-{token_id} révoqué : il est refusé dès la requête suivante.",
                  file=sys.stderr)
            return 0
        if session.get(ActorToken, token_id) is None:
            return _error("jeton inconnu")
    print(f"Jeton nx-tok-{token_id} déjà révoqué : rien à faire.")
    return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="nexus-token", description="Jetons d'acteur de Nexus (ADR-020)."
    )
    sub = parser.add_subparsers(dest="command", required=True)
    issue = sub.add_parser("issue", help="émet un jeton (affiché une seule fois)")
    issue.add_argument("actor", choices=sorted(ACTORS))
    issue.add_argument("--label", required=True, help="à quoi sert ce jeton (64 caractères max)")
    sub.add_parser("list", help="liste les jetons (jamais leur valeur)")
    revoke = sub.add_parser("revoke", help="révoque un jeton")
    revoke.add_argument("ref", help="référence nx-tok-<n>")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    settings = Settings.from_env()
    # Ne crée ni ne migre jamais la base (sqlite créerait un fichier vide à la connexion).
    if not settings.db_path.is_file() or migrate.pending(settings.db_url):
        return _error(
            "la base de Nexus n'est pas à jour : démarre Nexus une fois "
            "(elle se migre au démarrage), puis relance cette commande."
        )
    engine = make_engine(settings.db_url)
    try:
        factory = sessionmaker(engine, expire_on_commit=False)
        handler = {"issue": _issue, "list": _list, "revoke": _revoke}[args.command]
        return handler(factory, args)
    finally:
        engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
