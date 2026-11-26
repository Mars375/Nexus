"""Enumeration and opening of the conversation files (spec §5.1 rules 3 to 6, §5.2; ADR-025 D2).

Every tree is fake and lives under `tmp_path`; the audit recorder proves that nothing outside the
whitelist is listed or opened, and that the parent folders (`.claude`, `.codex`) are never
touched.
"""

import logging
import os
import sys

import pytest
from conversations_support import (
    fake_claude_home,
    fake_codex_home,
    junction,
    needs_windows,
    new_uuid,
    norm,
    recording,
    rollout_name,
    symlink_or_skip,
    under,
    write,
)

from nexus.conversations import paths
from nexus.conversations.paths import SourceRefused


def claude(tmp_path):
    tree = fake_claude_home(tmp_path)
    return tree, paths.check_root(tree.root, "claude-code")


def codex(tmp_path):
    tree = fake_codex_home(tmp_path)
    return tree, paths.check_root(tree.root, "codex")


def keys(listing) -> list[str]:
    return sorted(c.path_key for c in listing.candidates)


def read_all(listing) -> None:
    for candidate in listing.candidates:
        with paths.opened(candidate) as fd:
            os.read(fd, 16)


def test_only_whitelisted_claude_files_are_listed(tmp_path):
    tree, root = claude(tmp_path)

    listing = paths.iter_claude(root)

    assert keys(listing) == sorted(tree.sessions)
    assert all("\\" not in key for key in keys(listing))
    candidate = listing.candidates[0]
    info = os.lstat(candidate.path)
    assert candidate.file_id == f"{info.st_dev}:{info.st_ino}"
    assert (candidate.size, candidate.mtime_ns) == (info.st_size, info.st_mtime_ns)


def test_only_compressed_codex_rollouts_are_listed(tmp_path):
    tree, root = codex(tmp_path)

    with recording() as events:
        listing = paths.iter_codex(root)
        read_all(listing)

    assert keys(listing) == tree.rollouts
    opened = {path for event, path in under(events, tmp_path) if event == "open"}
    assert opened == {norm(c.path) for c in listing.candidates}


@pytest.mark.parametrize("source", ["claude-code", "codex"])
def test_nothing_outside_the_whitelist_is_opened_or_scanned(tmp_path, source):
    tree, root = claude(tmp_path) if source == "claude-code" else codex(tmp_path)
    walk = paths.iter_claude if source == "claude-code" else paths.iter_codex

    with recording() as events:
        listing = walk(root)
        read_all(listing)

    seen = under(events, tmp_path)
    scanned = {path for event, path in seen if event in ("os.scandir", "os.listdir")}
    opened = {path for event, path in seen if event == "open"}
    if source == "claude-code":
        assert scanned == {norm(tree.root), norm(tree.slug_dir())}
    else:
        base = tree.root / "2026" / "11"
        assert scanned == {norm(tree.root), norm(tree.root / "2026"), norm(base),
                           norm(base / "03")}
    assert opened == {norm(c.path) for c in listing.candidates}
    assert all(path.is_relative_to(norm(tree.root)) for _event, path in seen)
    assert not any(path == norm(tree.home) for _event, path in seen)


def level_dir(tree, source, level):
    """(parent, a fresh admitted name at `level`, the admitted folders below it to a file)."""
    if source == "claude-code":
        return tree.root, "-F-Ailleurs", []
    parts = {"year": (tree.root, "2027", ["01", "02"]),
             "month": (tree.root / "2026", "12", ["01"]),
             "day": (tree.root / "2026" / "11", "04", [])}
    return parts[level]


def outside_target(tmp_path, source, below: list[str]):
    """A folder outside the root holding a file whose name the reader would admit."""
    target = tmp_path / "ailleurs" / "cible"
    name = f"{new_uuid()}.jsonl" if source == "claude-code" else rollout_name()
    return target, write(target.joinpath(*below) / name)


LEVELS = [("claude-code", "slug"), ("codex", "year"), ("codex", "month"), ("codex", "day")]


@needs_windows
@pytest.mark.parametrize(("source", "level"), LEVELS)
def test_a_junctioned_intermediate_directory_is_never_scanned(tmp_path, source, level):
    tree, root = claude(tmp_path) if source == "claude-code" else codex(tmp_path)
    walk = paths.iter_claude if source == "claude-code" else paths.iter_codex
    parent, name, below = level_dir(tree, source, level)
    target, outer = outside_target(tmp_path, source, below)
    link = parent / name
    junction(link, target)

    with recording() as events:
        listing = walk(root)
        read_all(listing)

    outside = norm(tmp_path / "ailleurs")
    assert not [p for _e, p in under(events, tmp_path) if p == outside or p.is_relative_to(outside)]
    assert not [p for _e, p in under(events, tmp_path) if p == norm(link) or
                p.is_relative_to(norm(link))]
    assert norm(outer) not in {norm(c.path) for c in listing.candidates}
    assert listing.skipped_dirs == 1
    assert keys(listing) == sorted(tree.sessions if source == "claude-code" else tree.rollouts)


@needs_windows
def test_a_junction_back_into_the_root_is_not_followed(tmp_path):
    tree, root = claude(tmp_path)
    junction(tree.root / "-F-Doublon", tree.slug_dir())
    codex_tree, codex_root = codex(tmp_path)
    day = codex_tree.root / "2026" / "11"
    junction(day / "04", day / "03")

    claude_listing = paths.iter_claude(root)
    codex_listing = paths.iter_codex(codex_root)

    assert keys(claude_listing) == sorted(tree.sessions)
    assert keys(codex_listing) == codex_tree.rollouts
    assert claude_listing.skipped_dirs == codex_listing.skipped_dirs == 1


@pytest.mark.parametrize(("source", "level"), [*LEVELS, ("claude-code", "file")])
def test_a_symlinked_level_directory_or_file_is_refused(tmp_path, source, level):
    tree, root = claude(tmp_path) if source == "claude-code" else codex(tmp_path)
    walk = paths.iter_claude if source == "claude-code" else paths.iter_codex
    if level == "file":
        outer = write(tmp_path / "ailleurs" / "x.jsonl")
        symlink_or_skip(tree.slug_dir() / f"{new_uuid()}.jsonl", outer, directory=False)
        expected_dirs = 0
    else:
        parent, name, below = level_dir(tree, source, level)
        target, outer = outside_target(tmp_path, source, below)
        symlink_or_skip(parent / name, target, directory=True)
        expected_dirs = 1

    with recording() as events:
        listing = walk(root)
        read_all(listing)

    outside = norm(tmp_path / "ailleurs")
    assert not [p for _e, p in under(events, tmp_path) if p.is_relative_to(outside)]
    assert norm(outer) not in {norm(c.path) for c in listing.candidates}
    assert listing.skipped_dirs == expected_dirs
    assert keys(listing) == sorted(tree.sessions if source == "claude-code" else tree.rollouts)


def test_a_hard_linked_file_is_refused(tmp_path):
    tree, root = claude(tmp_path)
    first = tree.root / tree.sessions[0]
    os.link(first, tree.slug_dir() / f"{new_uuid()}.jsonl")

    listing = paths.iter_claude(root)

    assert keys(listing) == [tree.sessions[1]]


def test_a_file_swapped_between_lstat_and_open_is_refused(tmp_path, monkeypatch):
    tree, root = claude(tmp_path)
    candidate = paths.iter_claude(root).candidates[0]
    other = write(tmp_path / "autre.jsonl", '{"autre": 1}\n')
    os.replace(other, candidate.path)
    descriptors = []
    real_open = os.open

    def spy(*args, **kwargs):
        fd = real_open(*args, **kwargs)
        descriptors.append(fd)
        return fd

    monkeypatch.setattr(os, "open", spy)

    with pytest.raises(SourceRefused) as exc:
        paths.open_candidate(candidate)

    assert exc.value.code == "substituted"
    assert str(tmp_path) not in str(exc.value)
    with pytest.raises(OSError):
        os.fstat(descriptors[0])


def test_the_open_flags_match_the_platform(tmp_path, monkeypatch):
    _tree, root = claude(tmp_path)
    candidate = paths.iter_claude(root).candidates[0]
    flags = []
    real_open = os.open
    monkeypatch.setattr(os, "open", lambda p, f, *a, **k: flags.append(f) or real_open(p, f, *a,
                                                                                         **k))

    with paths.opened(candidate):
        pass

    if sys.platform == "win32":
        expected = os.O_RDONLY | os.O_BINARY | os.O_NOINHERIT
    else:
        expected = os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC
    assert flags == [expected]


def test_a_candidate_is_closed_after_use(tmp_path):
    _tree, root = claude(tmp_path)
    candidate = paths.iter_claude(root).candidates[0]

    with paths.opened(candidate) as fd:
        os.fstat(fd)
    with pytest.raises(OSError):
        os.fstat(fd)

    with pytest.raises(RuntimeError):
        with paths.opened(candidate) as fd:
            raise RuntimeError("échec du lecteur")
    with pytest.raises(OSError):
        os.fstat(fd)


def test_the_resolved_candidate_stays_under_the_root(tmp_path, monkeypatch):
    tree, root = claude(tmp_path)
    slug = tree.slug_dir()
    target = tmp_path / "ailleurs" / "cible"
    outer = write(target / f"{new_uuid()}.jsonl")
    real_scandir = os.scandir
    swapped = []

    def swap_then_scan(path=None):
        if not swapped and norm(path) == norm(slug):
            swapped.append(path)
            slug.rename(slug.with_name("ancien"))
            if sys.platform == "win32":
                junction(slug, target)
            else:
                os.symlink(target, slug, target_is_directory=True)
        return real_scandir(path)

    monkeypatch.setattr(os, "scandir", swap_then_scan)

    listing = paths.iter_claude(root)

    assert swapped
    assert norm(outer) not in {norm(c.path) for c in listing.candidates}
    assert listing.candidates == []


def test_logs_carry_counts_and_codes_only(tmp_path, caplog):
    tree, root = claude(tmp_path)
    codex_tree, codex_root = codex(tmp_path)
    if sys.platform == "win32":
        target, _outer = outside_target(tmp_path, "claude-code", [])
        junction(tree.root / "-F-Ailleurs", target)
    caplog.set_level(logging.DEBUG, logger="nexus.conversations")

    paths.iter_claude(root)
    paths.iter_codex(codex_root)

    text = caplog.text
    assert caplog.records
    forbidden = [str(tmp_path), tree.slug, "-F-Ailleurs", "sessions", "projects", "2026",
                 *(key.split("/")[-1].split(".")[0] for key in tree.sessions),
                 *(key.split("/")[-1] for key in codex_tree.rollouts)]
    assert not [piece for piece in forbidden if piece in text]
    for record in caplog.records:
        assert record.args and record.args[0] in ("claude-code", "codex")


def test_a_name_at_the_wrong_level_is_not_listed(tmp_path):
    tree, root = claude(tmp_path)
    codex_tree, codex_root = codex(tmp_path)
    level_one = next(p for p in tree.root.iterdir() if p.is_file())
    month_rollout = next(p for p in (codex_tree.root / "2026" / "11").iterdir() if p.is_file())

    with recording() as events:
        claude_listing = paths.iter_claude(root)
        codex_listing = paths.iter_codex(codex_root)

    opened = {p for e, p in under(events, tmp_path) if e == "open"}
    assert norm(level_one) not in opened and norm(month_rollout) not in opened
    assert norm(level_one) not in {norm(c.path) for c in claude_listing.candidates}
    assert keys(codex_listing) == codex_tree.rollouts
