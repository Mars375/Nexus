"""`nexus-token`: issue, list and revoke actor tokens (ADR-020, D3).

The token is printed once, on standard output and nothing else; guidance goes to standard
error. The CLI never migrates the database: it requires that Nexus already did.
"""

from __future__ import annotations

import argparse
import re
import sqlite3
import sys
from collections.abc import Sequence

from sqlalchemy import select, update
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import sessionmaker

from nexus import migrate
from nexus.actors import ACTORS
from nexus.auth import tokens
from nexus.clock import now
from nexus.config import Settings
from nexus.db import make_engine
from nexus.models import ActorToken

_REF = re.compile(r"nx-tok-([0-9]{1,12})")
# Seconds sqlite waits on a lock held by the running server (module level so tests can shorten it).
BUSY_TIMEOUT = 15.0


class _Parser(argparse.ArgumentParser):
    """Usage errors print a fixed French message: argparse would echo the offending value."""

    def error(self, message: str):
        self.print_usage(sys.stderr)
        print("Erreur : arguments invalides.", file=sys.stderr)
        raise SystemExit(2)


def _error(message: str) -> int:
    print(f"Erreur : {message}", file=sys.stderr)
    return 1


def _issue(factory, args: argparse.Namespace) -> int:
    if args.actor not in ACTORS:
        return _error("acteur inconnu")
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
        # A single conditional UPDATE: two simultaneous revocations make only one.
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
    parser = _Parser(prog="nexus-token", description="Jetons d'acteur de Nexus (ADR-020).")
    sub = parser.add_subparsers(dest="command", required=True)
    issue = sub.add_parser("issue", help="émet un jeton (affiché une seule fois)")
    issue.add_argument("actor", help="acteur : " + ", ".join(sorted(ACTORS)))
    issue.add_argument("--label", required=True, help="à quoi sert ce jeton (64 caractères max)")
    sub.add_parser("list", help="liste les jetons (jamais leur valeur)")
    revoke = sub.add_parser("revoke", help="révoque un jeton")
    revoke.add_argument("ref", help="référence nx-tok-<n>")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        settings = Settings.from_env()
    except ValueError:
        # Fixed text: a `float()`/`int()` error would repeat the received value.
        return _error(
            "configuration invalide : vérifie les variables NEXUS_* (NEXUS_HOST une adresse de la "
            "boucle locale et au plus une adresse du tailnet, NEXUS_ALLOWED_HOSTS une liste de "
            "noms d'hôte, NEXUS_PORT un nombre)"
        )
    # Never creates nor migrates the database (sqlite would create an empty file on connect).
    if not settings.db_path.is_file() or migrate.pending(settings.db_url):
        return _error(
            "la base de Nexus n'est pas à jour : démarre Nexus une fois "
            "(elle se migre au démarrage), puis relance cette commande."
        )
    engine = make_engine(settings.db_url, timeout=BUSY_TIMEOUT)
    try:
        factory = sessionmaker(engine, expire_on_commit=False)
        handler = {"issue": _issue, "list": _list, "revoke": _revoke}[args.command]
        return handler(factory, args)
    except OperationalError as exc:
        # The exception text carries the SQL and its parameters: print none of it.
        code = getattr(exc.orig, "sqlite_errorcode", None)
        if code in (sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED):
            return _error("la base est occupée, réessaie dans un instant")
        name = getattr(exc.orig, "sqlite_errorname", None) or "erreur SQLite"
        return _error(f"la base est inaccessible ({name})")
    finally:
        engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
