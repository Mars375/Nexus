"""Jetons d'acteur (#16, ADR-020) : format, empreinte, recherche."""

import hashlib
import re

import pytest
from sqlalchemy.orm import sessionmaker

from nexus import migrate
from nexus.auth import tokens
from nexus.clock import now
from nexus.db import make_engine
from nexus.models import ActorToken


@pytest.fixture
def session(settings):
    settings.data_dir.mkdir(parents=True)
    migrate.upgrade(settings.db_url)
    engine = make_engine(settings.db_url)
    with sessionmaker(engine, expire_on_commit=False)() as s:
        yield s
    engine.dispose()


def test_generate_gives_prefix_and_43_url_safe_characters():
    token = tokens.generate()
    assert re.fullmatch(r"nxt_[A-Za-z0-9_-]{43}", token)
    assert "=" not in token


def test_generate_never_repeats():
    assert len({tokens.generate() for _ in range(200)}) == 200


def test_digest_is_sha256_hex():
    token = "nxt_" + "A" * 43
    assert tokens.digest(token) == hashlib.sha256(token.encode()).hexdigest()
    assert len(tokens.digest(token)) == 64


@pytest.mark.parametrize("bad", [
    "", "nxt_", "nxt_" + "A" * 42, "nxt_" + "A" * 44, "NXT_" + "A" * 43, "ghp_" + "A" * 43,
    "nxt_" + "A" * 42 + "=", "nxt_" + "A" * 42 + "é", " nxt_" + "A" * 43, "nxt_" + "A" * 43 + "\n",
    "nxt_" + "A" * 42 + "٠",  # chiffre arabo-indien : \d l'accepterait
])
def test_malformed_tokens_are_not_well_formed(bad):
    assert tokens.is_well_formed(bad) is False


def test_generated_token_is_well_formed():
    assert tokens.is_well_formed(tokens.generate()) is True


def test_issue_stores_only_the_digest(session):
    row, token = tokens.issue(session, "helios", "poste")
    session.commit()
    assert row.token_hash == tokens.digest(token)
    assert token not in repr(row.__dict__)
    assert row.revoked_at is None


def test_lookup_returns_the_actor(session):
    _, token = tokens.issue(session, "codex", "cli")
    session.commit()
    assert tokens.lookup(session, token) == "codex"


def test_lookup_ignores_unknown_and_malformed_tokens(session):
    tokens.issue(session, "codex", "cli")
    session.commit()
    assert tokens.lookup(session, "nxt_" + "A" * 43) is None
    assert tokens.lookup(session, "n'importe quoi") is None
    assert tokens.lookup(session, "") is None


def test_lookup_ignores_revoked_tokens_at_once(session):
    row, token = tokens.issue(session, "loic", "navigateur")
    session.commit()
    assert tokens.lookup(session, token) == "loic"
    row.revoked_at = now()
    session.commit()
    assert tokens.lookup(session, token) is None


@pytest.mark.parametrize("label", ["", "   ", "x" * 65, "a\x1b[31mb", "a\nb"])
def test_issue_refuses_a_bad_label(session, label):
    with pytest.raises(ValueError):
        tokens.issue(session, "loic", label)


def test_issue_refuses_a_label_that_holds_a_secret(session):
    with pytest.raises(ValueError) as exc:
        tokens.issue(session, "loic", "ghp_" + "A" * 36)
    assert "ghp_" not in str(exc.value)


def test_issue_refuses_an_unknown_actor(session):
    with pytest.raises(ValueError):
        tokens.issue(session, "mallory", "x")


def test_the_database_refuses_an_unknown_actor_or_empty_label(session):
    for fields in (
        {"actor": "mallory", "label": "x"},
        {"actor": "loic", "label": ""},
        {"actor": "loic", "label": "x" * 65},
        {"actor": "loic", "label": "x", "token_hash": "abc"},
    ):
        from sqlalchemy.exc import IntegrityError

        session.add(ActorToken(
            **({"token_hash": tokens.digest(tokens.generate())} | fields), created_at=now()
        ))
        with pytest.raises(IntegrityError):
            session.flush()
        session.rollback()


@pytest.mark.parametrize("space", ["\u00a0", "\u202f"])
def test_label_accepts_unicode_space_separators_as_plain_spaces(session, space):
    row, _ = tokens.issue(session, "loic", f"poste{space}:{space}Loïc")
    assert row.label == "poste : Loïc"


def test_label_refuses_format_characters_with_a_clear_message(session):
    with pytest.raises(ValueError, match="caractères imprimables"):
        tokens.issue(session, "loic", "a\u200bb")
