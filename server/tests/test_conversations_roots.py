"""Roots of the conversation sources (spec §5.1 rule 2, ADR-025 D1): checked as configured,
before any resolution, then resolved and checked again; refusals never repeat the path."""

import os
from pathlib import Path

import pytest
from conversations_support import (
    junction,
    needs_windows,
    recording,
    symlink_or_skip,
    under,
    write,
)

from nexus.conversations import paths
from nexus.conversations.paths import SourceRefused

KINDS = {"claude-code": "projects", "codex": "sessions", "hermes": "state.db"}


def make_root(base: Path, source: str) -> Path:
    path = base / KINDS[source]
    if source == "hermes":
        write(path, "")
    else:
        path.mkdir(parents=True)
    return path


def refusal(configured: Path, source: str, tmp_path: Path) -> str:
    with pytest.raises(SourceRefused) as exc:
        paths.check_root(configured, source)
    text = str(exc.value)
    assert str(tmp_path) not in text and configured.name not in text
    assert exc.value.__cause__ is None
    return exc.value.code


@pytest.mark.parametrize("source", list(KINDS))
def test_a_well_named_directory_is_accepted(tmp_path, source):
    configured = make_root(tmp_path / "home", source)

    root = paths.check_root(configured, source)

    assert root.path == configured.resolve(strict=True)
    assert root.source == source
    info = os.lstat(configured)
    assert root.ident == (info.st_dev, info.st_ino)


@pytest.mark.parametrize("source", list(KINDS))
def test_a_missing_root_is_refused(tmp_path, source):
    assert refusal(tmp_path / KINDS[source], source, tmp_path) == "root_missing"


@pytest.mark.parametrize("source", list(KINDS))
def test_a_relative_root_is_refused(tmp_path, source):
    assert refusal(Path(KINDS[source]), source, tmp_path) == "root_not_absolute"


def test_a_root_of_the_wrong_kind_is_refused(tmp_path):
    projects = write(tmp_path / "a" / "projects", "")
    state = tmp_path / "b" / "state.db"
    state.mkdir(parents=True)

    assert refusal(projects, "claude-code", tmp_path) == "root_wrong_kind"
    assert refusal(state, "hermes", tmp_path) == "root_wrong_kind"


@pytest.mark.parametrize(
    ("source", "name"),
    [("codex", ".codex"), ("claude-code", ".claude"), ("hermes", "hermes.db"),
     ("claude-code", "Projects")],
)
def test_a_badly_named_root_is_refused(tmp_path, source, name):
    configured = tmp_path / "home" / name
    if source == "hermes":
        write(configured, "")
    else:
        configured.mkdir(parents=True)

    assert refusal(configured, source, tmp_path) == "root_badly_named"


@needs_windows
def test_a_root_that_is_a_junction_is_refused(tmp_path):
    target = make_root(tmp_path / "ailleurs", "claude-code")
    link = tmp_path / "home" / "projects"
    link.parent.mkdir()
    junction(link, target)

    assert refusal(link, "claude-code", tmp_path) == "root_is_link"


@pytest.mark.parametrize("source", list(KINDS))
def test_a_root_that_is_a_symlink_is_refused(tmp_path, source):
    target = make_root(tmp_path / "ailleurs", source)
    link = tmp_path / "home" / KINDS[source]
    link.parent.mkdir()
    symlink_or_skip(link, target, directory=source != "hermes")

    assert refusal(link, source, tmp_path) == "root_is_link"


def test_a_hard_linked_hermes_db_is_refused(tmp_path):
    state = make_root(tmp_path / "hermes", "hermes")
    second = tmp_path / "copie.db"
    os.link(state, second)

    assert refusal(state, "hermes", tmp_path) == "root_hard_linked"

    second.unlink()
    assert paths.check_root(state, "hermes").path == state.resolve()


@needs_windows
def test_the_link_check_runs_before_resolve(tmp_path, monkeypatch):
    target = make_root(tmp_path / "ailleurs", "claude-code")
    link = tmp_path / "home" / "projects"
    link.parent.mkdir()
    junction(link, target)
    calls = []
    real_resolve, real_realpath = Path.resolve, os.path.realpath
    monkeypatch.setattr(Path, "resolve", lambda self, *a, **k: calls.append(self) or
                        real_resolve(self, *a, **k))
    monkeypatch.setattr(os.path, "realpath", lambda p, *a, **k: calls.append(p) or
                        real_realpath(p, *a, **k))

    assert refusal(link, "claude-code", tmp_path) == "root_is_link"
    assert calls == []


def test_a_relative_root_touches_nothing(tmp_path, monkeypatch):
    (tmp_path / "projects").mkdir()
    monkeypatch.chdir(tmp_path)

    with recording() as events:
        with pytest.raises(SourceRefused) as exc:
            paths.check_root(Path("projects"), "claude-code")

    assert exc.value.code == "root_not_absolute"
    assert under(events, tmp_path) == []


@needs_windows
def test_a_root_swapped_before_resolve_is_refused(tmp_path, monkeypatch):
    configured = make_root(tmp_path / "home", "claude-code")
    elsewhere = make_root(tmp_path / "ailleurs", "claude-code")
    real_resolve = Path.resolve
    swapped = []

    def swap_then_resolve(self, *args, **kwargs):
        if not swapped:
            swapped.append(self)
            configured.rename(configured.with_name("ancien"))
            junction(configured, elsewhere)
        return real_resolve(self, *args, **kwargs)

    monkeypatch.setattr(Path, "resolve", swap_then_resolve)

    assert refusal(configured, "claude-code", tmp_path) == "root_substituted"
    assert swapped


def test_the_refusal_messages_are_fixed_french_text():
    assert set(paths.MESSAGES) >= {
        "root_not_absolute", "root_missing", "root_wrong_kind", "root_is_link",
        "root_hard_linked", "root_badly_named", "root_substituted", "substituted",
    }
