"""Jetons d'acteur (#16, ADR-020) : format, empreinte, recherche."""

import hashlib
import logging
import re
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.orm import sessionmaker

from nexus import migrate
from nexus.auth import tokens
from nexus.clock import TZ, now
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


@pytest.fixture
def factory(settings, session):
    engine = make_engine(settings.db_url)
    yield sessionmaker(engine, expire_on_commit=False)
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


def test_label_accepts_long_french_joined_words(session):
    # The entropy guard requires a digit in a candidate: joined label
    # vocabulary (no digit, no short segment) keeps passing clean_label
    # (reviewer regression on 327aa8e).
    label = "authentification-rechargement"
    assert tokens.issue(session, "loic", label)[0].label == label


def test_label_refuses_format_characters_with_a_clear_message(session):
    with pytest.raises(ValueError, match="caractères imprimables"):
        tokens.issue(session, "loic", "a\u200bb")


def test_lookup_row_returns_the_live_row(session):
    row, token = tokens.issue(session, "codex", "cli")
    session.commit()
    found = tokens.lookup_row(session, token)
    assert found is not None and found.id == row.id and found.actor == "codex"


def test_lookup_row_ignores_unknown_malformed_and_revoked(session):
    row, token = tokens.issue(session, "loic", "navigateur")
    session.commit()
    assert tokens.lookup_row(session, "nxt_" + "A" * 43) is None
    assert tokens.lookup_row(session, "n'importe quoi") is None
    row.revoked_at = now()
    session.commit()
    assert tokens.lookup_row(session, token) is None


def test_is_live_is_false_for_a_revoked_or_deleted_row(session):
    row, _ = tokens.issue(session, "loic", "navigateur")
    other, _ = tokens.issue(session, "codex", "cli")
    session.commit()
    assert tokens.is_live(session, row.id) is True
    row.revoked_at = now()
    session.commit()
    assert tokens.is_live(session, row.id) is False
    session.delete(other)  # an absent row counts as a revocation (D6)
    session.commit()
    assert tokens.is_live(session, other.id) is False
    assert tokens.is_live(session, 987654) is False


def test_touch_last_used_sets_it_on_the_first_use(session, factory):
    row, _ = tokens.issue(session, "helios", "poste")
    session.commit()
    assert row.last_used_at is None
    tokens.touch_last_used(factory, row.id)
    session.refresh(row)
    assert row.last_used_at is not None
    assert abs((row.last_used_at - now()).total_seconds()) < 5


def test_touch_last_used_leaves_a_recent_value_alone(session, factory):
    row, _ = tokens.issue(session, "helios", "poste")
    recent = now() - timedelta(seconds=100)
    row.last_used_at = recent
    session.commit()
    tokens.touch_last_used(factory, row.id)
    session.expire(row)
    assert row.last_used_at == recent


def test_touch_last_used_writes_again_after_the_window(session, factory):
    row, _ = tokens.issue(session, "helios", "poste")
    old = now() - timedelta(seconds=301)
    row.last_used_at = old
    session.commit()
    tokens.touch_last_used(factory, row.id)
    session.expire(row)
    assert row.last_used_at is not None and row.last_used_at > old
    assert abs((row.last_used_at - now()).total_seconds()) < 5


def test_two_touches_in_a_row_write_once(session, factory):
    row, _ = tokens.issue(session, "helios", "poste")
    session.commit()
    tokens.touch_last_used(factory, row.id)
    session.refresh(row)
    first = row.last_used_at
    tokens.touch_last_used(factory, row.id)
    session.expire(row)
    assert row.last_used_at == first


def test_touch_last_used_ignores_an_unknown_token(factory):
    tokens.touch_last_used(factory, 987654)  # no exception, nothing written


def test_a_failed_touch_never_fails_the_request(caplog):
    class Broken:
        def __call__(self):
            raise RuntimeError("base indisponible")

    caplog.set_level(logging.WARNING, logger="nexus")
    tokens.touch_last_used(Broken(), 1)
    assert "dernière utilisation" in caplog.text
    assert "base indisponible" not in caplog.text


class _NoSession:
    """A factory that must never be called: inside the window nothing is written (#94)."""

    def __init__(self):
        self.calls = 0

    def __call__(self):
        self.calls += 1
        raise AssertionError("no session expected")


def test_a_known_recent_use_opens_no_session(caplog):
    spy = _NoSession()
    caplog.set_level(logging.WARNING, logger="nexus")
    tokens.touch_last_used(spy, 1, last_used_at=now() - timedelta(seconds=10))
    assert spy.calls == 0
    assert caplog.text == ""


def test_a_known_use_beyond_the_window_still_writes(session, factory):
    row, _ = tokens.issue(session, "helios", "poste")
    old = now() - timedelta(seconds=301)
    row.last_used_at = old
    session.commit()
    tokens.touch_last_used(factory, row.id, last_used_at=old)
    session.expire(row)
    assert abs((row.last_used_at - now()).total_seconds()) < 5


def test_a_known_never_used_token_still_writes(session, factory):
    row, _ = tokens.issue(session, "helios", "poste")
    session.commit()
    tokens.touch_last_used(factory, row.id, last_used_at=None)
    session.expire(row)
    assert row.last_used_at is not None


def test_the_update_stays_the_arbiter_for_a_stale_row(session, factory):
    # Another request touched the token after this one loaded its row: Python sees a stale
    # value, the conditional UPDATE matches nothing and keeps the recent one.
    row, _ = tokens.issue(session, "helios", "poste")
    recent = now() - timedelta(seconds=10)
    row.last_used_at = recent
    session.commit()
    tokens.touch_last_used(factory, row.id, last_used_at=now() - timedelta(seconds=301))
    session.expire(row)
    assert row.last_used_at == recent


def test_a_future_last_use_counts_as_inside_the_window():
    spy = _NoSession()
    tokens.touch_last_used(spy, 1, last_used_at=now() + timedelta(hours=1))
    assert spy.calls == 0


def test_the_python_window_boundary_matches_the_sql(monkeypatch):
    fixed = datetime(2026, 9, 28, 9, 5, tzinfo=TZ)
    monkeypatch.setattr(tokens, "now", lambda: fixed)
    cutoff = fixed.astimezone(UTC) - tokens.TOUCH_WINDOW
    on_cutoff, before = _NoSession(), _NoSession()
    tokens.touch_last_used(on_cutoff, 1, last_used_at=cutoff.astimezone(TZ))
    assert on_cutoff.calls == 0  # `last_used_at < cutoff` is false: the UPDATE writes nothing
    just_before = (cutoff - timedelta(microseconds=1)).astimezone(TZ)
    tokens.touch_last_used(before, 1, last_used_at=just_before)
    assert before.calls == 1


def test_the_python_window_holds_across_the_fall_back_instants(monkeypatch):
    # Same wall-clock zone on both sides would compare 02:30+02:00 as before 02:15+01:00
    # (PEP 495 ignores fold): compare instants. 02:30+02:00 is 45 minutes older: due.
    fixed = datetime(2026, 10, 25, 2, 15, tzinfo=TZ, fold=1)
    monkeypatch.setattr(tokens, "now", lambda: fixed)
    stale = (fixed.astimezone(UTC) - timedelta(minutes=45)).astimezone(TZ)
    spy = _NoSession()
    tokens.touch_last_used(spy, 1, last_used_at=stale)
    assert spy.calls == 1
    inside = _NoSession()
    recent = (fixed.astimezone(UTC) - timedelta(seconds=299)).astimezone(TZ)
    tokens.touch_last_used(inside, 1, last_used_at=recent)
    assert inside.calls == 0


def test_a_naive_last_use_is_left_to_the_update(session, factory):
    row, _ = tokens.issue(session, "helios", "poste")
    session.commit()
    tokens.touch_last_used(factory, row.id, last_used_at=datetime(2026, 1, 1))
    session.expire(row)
    assert row.last_used_at is not None


def test_the_window_holds_across_the_autumn_fall_back(session, factory, monkeypatch):
    # 2026-10-25: 03:00 CEST becomes 02:00 CET, so this local time exists twice (fold=1).
    # 02:15+01:00 is 01:15Z: values are built on the UTC timeline, as real instants are.
    fixed = datetime(2026, 10, 25, 2, 15, tzinfo=TZ, fold=1)
    monkeypatch.setattr(tokens, "now", lambda: fixed)
    row, _ = tokens.issue(session, "helios", "poste")

    inside = (fixed.astimezone(UTC) - timedelta(seconds=299)).astimezone(TZ)
    row.last_used_at = inside
    session.commit()
    tokens.touch_last_used(factory, row.id)
    session.expire(row)
    assert row.last_used_at == inside  # still inside the window

    # 45 minutes is beyond the window; wall-clock subtraction would call it recent (00:30Z).
    stale = (fixed.astimezone(UTC) - timedelta(minutes=45)).astimezone(TZ)
    row.last_used_at = stale
    session.commit()
    tokens.touch_last_used(factory, row.id)
    session.expire(row)
    assert row.last_used_at == fixed

    outside = (fixed.astimezone(UTC) - timedelta(seconds=301)).astimezone(TZ)
    row.last_used_at = outside
    session.commit()
    tokens.touch_last_used(factory, row.id)
    session.expire(row)
    assert row.last_used_at == fixed


def test_the_window_holds_across_the_spring_forward(session, factory, monkeypatch):
    # 2026-03-29: 02:00 CET becomes 03:00 CEST. At 03:02+02:00 (01:02Z), wall-clock
    # subtraction lands on 02:57, an hour that does not exist, i.e. 01:57Z: the future.
    fixed = datetime(2026, 3, 29, 3, 2, tzinfo=TZ)
    monkeypatch.setattr(tokens, "now", lambda: fixed)
    row, _ = tokens.issue(session, "helios", "poste")

    recent = (fixed.astimezone(UTC) - timedelta(minutes=2)).astimezone(TZ)
    row.last_used_at = recent
    session.commit()
    tokens.touch_last_used(factory, row.id)
    session.expire(row)
    assert row.last_used_at == recent  # still inside the window
