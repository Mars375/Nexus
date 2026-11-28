"""Tail reading of a JSONL file on an open descriptor (spec §6.2): complete lines only, a 1 MiB
cap per line skipped as a stream (`skipping`), never past the size seen by `lstat`."""

import hashlib
import os

import pytest

from nexus.conversations import jsonl_tail
from nexus.conversations.jsonl_tail import CHUNK, LINE_MAX, head_digest, read_tail

MIB = 1 << 20


@pytest.fixture
def make(tmp_path):
    fds = []

    def _make(data: bytes):
        path = tmp_path / f"s{len(fds)}.jsonl"
        path.write_bytes(data)
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_BINARY", 0))
        fds.append(fd)
        return fd, path

    yield _make
    for fd in fds:
        os.close(fd)


def tail(fd, *, start=0, end=None, budget=8 * MIB, skipping=False):
    if end is None:
        end = os.fstat(fd).st_size
    return read_tail(fd, start=start, end=end, budget=budget, skipping=skipping)


def test_complete_lines_are_returned_with_their_end_offsets(make):
    fd, _ = make(b"a\nbb\nccc\n")

    got = tail(fd)

    assert [(ln.start, ln.end, ln.data) for ln in got.lines] == [
        (0, 2, b"a"), (2, 5, b"bb"), (5, 9, b"ccc")]
    assert got.offset == 9 and got.at_end and not got.skipping and got.read == 9


def test_a_last_line_without_newline_is_left_for_the_next_read(make):
    fd, path = make(b"a\nbb")

    first = tail(fd)
    assert [ln.data for ln in first.lines] == [b"a"]
    assert first.offset == 2 and first.at_end

    with open(path, "ab") as handle:
        handle.write(b"b\n")
    second = tail(fd, start=first.offset)
    assert [ln.data for ln in second.lines] == [b"bbb"] and second.offset == 6


def test_a_line_of_exactly_the_cap_is_kept_one_more_byte_is_skipped(make):
    exact = b"x" * LINE_MAX
    fd, _ = make(exact + b"\n" + b"y" * (LINE_MAX + 1) + b"\nz\n")

    got = tail(fd, budget=16 * MIB)

    assert [ln.data for ln in got.lines] == [exact, b"z"]
    assert got.oversized == 1 and not got.skipping


def test_a_2_mib_line_is_skipped_without_growing_the_buffer(make):
    fd, _ = make(b"a\n" + b"x" * (2 * MIB) + b"\nb\n")

    got = tail(fd)

    assert [ln.data for ln in got.lines] == [b"a", b"b"]
    assert got.oversized == 1
    assert got.peak <= LINE_MAX + CHUNK


def test_a_skip_straddling_the_budget_resumes_without_counting_twice(make):
    fd, _ = make(b"a\n" + b"x" * (2 * MIB) + b"\nb\n")

    first = tail(fd, budget=MIB + MIB // 2)
    assert first.skipping and first.oversized == 1
    assert 2 < first.offset < 2 * MIB
    assert [ln.data for ln in first.lines] == [b"a"]

    second = tail(fd, start=first.offset, skipping=True)
    assert not second.skipping and second.oversized == 0
    assert [ln.data for ln in second.lines] == [b"b"]


@pytest.mark.parametrize("first_len", [CHUNK - 1, CHUNK])
def test_a_newline_on_a_chunk_boundary(make, first_len):
    first = b"x" * first_len
    fd, _ = make(first + b"\nsecond\n")

    got = tail(fd)

    assert [ln.data for ln in got.lines] == [first, b"second"]
    assert got.lines[0].end == first_len + 1


def test_nothing_is_read_past_the_size_seen_before_opening(make):
    fd, _ = make(b"a\nb\nappended\n")

    got = tail(fd, end=4)

    assert [ln.data for ln in got.lines] == [b"a", b"b"]
    assert got.read == 4 and got.offset == 4 and got.at_end


def test_a_file_that_shrank_after_its_lstat_ends_the_read(make):
    fd, _ = make(b"a\nb\n")

    got = tail(fd, end=100)

    assert [ln.data for ln in got.lines] == [b"a", b"b"] and got.at_end


def test_a_9_mib_line_for_an_8_mib_budget_never_blocks(make):
    """§13 literal: a skip that spans two passes, then the next lines; never the start again."""
    fd, _ = make(b"a\n" + b"x" * (9 * MIB) + b"\nb\nc\n")

    first = tail(fd, budget=8 * MIB)
    assert first.skipping and first.oversized == 1
    assert first.offset == 8 * MIB and first.read == 8 * MIB

    second = tail(fd, start=first.offset, skipping=True, budget=8 * MIB)
    assert not second.skipping and second.oversized == 0
    assert [ln.data for ln in second.lines] == [b"b", b"c"] and second.at_end
    assert second.read < 2 * MIB


def test_head_digest(make):
    data = os.urandom(5000)
    fd, _ = make(data)
    assert head_digest(fd, 4096) == hashlib.sha256(data[:4096]).hexdigest()

    small, _ = make(data[:100])
    assert head_digest(small, 100) == hashlib.sha256(data[:100]).hexdigest()


def test_empty_lines_and_crlf_are_returned(make):
    fd, _ = make(b'{"a": 1}\r\n\n{"b": 2}\r\n')

    got = tail(fd)

    assert [ln.data for ln in got.lines] == [b'{"a": 1}\r', b"", b'{"b": 2}\r']


def test_a_short_budget_stops_at_the_last_complete_line(make):
    fd, _ = make(b"aaaa\nbbbb\ncccc\n")

    got = tail(fd, budget=7)

    assert [ln.data for ln in got.lines] == [b"aaaa"]
    assert got.offset == 5 and not got.at_end and got.read == 7


def test_the_cap_is_read_at_call_time(make, monkeypatch):
    monkeypatch.setattr(jsonl_tail, "LINE_MAX", 8)
    fd, _ = make(b"short\n" + b"y" * 20 + b"\nok\n")

    got = tail(fd)

    assert [ln.data for ln in got.lines] == [b"short", b"ok"] and got.oversized == 1
