"""Tail reading of a JSONL file on a descriptor the caller already opened (spec §6.2).

Pure: no path, no database. Only lines that end with `\\n` are returned; a line longer than
`LINE_MAX` is skipped as a stream up to its `\\n`, never loaded, and a skip cut by the budget or
by the end of the range is resumed by the next call (`skipping`). Nothing is read past `end`,
the size `lstat` saw before the open (plan A5), so a cursor never claims bytes it did not see.
"""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass

LINE_MAX = 1 << 20
HEAD_BYTES = 4096
CHUNK = 1 << 16


@dataclass(frozen=True)
class Line:
    start: int
    end: int  # just past the "\n"
    data: bytes  # without the "\n"


@dataclass(frozen=True)
class Tail:
    lines: list[Line]
    offset: int  # where the next read starts: after the last consumed byte
    skipping: bool  # a too long line is still being skipped at `offset`
    oversized: int  # too long lines met by this call (a resumed skip is not counted again)
    read: int  # bytes read by this call, counted against the pass budget
    at_end: bool  # the end of the range (or of the file) was reached
    peak: int = 0  # largest buffer held, for the tests


def read_tail(fd: int, *, start: int, end: int, budget: int, skipping: bool) -> Tail:
    line_max = LINE_MAX  # read at call time: tests lower it
    os.lseek(fd, start, os.SEEK_SET)
    pos = offset = buf_start = start
    buf = bytearray()
    lines: list[Line] = []
    oversized = read = peak = 0
    at_end = False
    while True:
        if pos >= end:
            at_end = True
            break
        if read >= budget:
            break
        chunk = os.read(fd, min(CHUNK, end - pos, budget - read))
        if not chunk:  # the file shrank after its lstat
            at_end = True
            break
        read += len(chunk)
        pos += len(chunk)
        if skipping:
            cut = chunk.find(b"\n")
            if cut < 0:
                offset = buf_start = pos
                continue
            skipping = False
            chunk = chunk[cut + 1:]
            offset = buf_start = pos - len(chunk)
        buf += chunk
        peak = max(peak, len(buf))
        scan = 0
        while (cut := buf.find(b"\n", scan)) >= 0:
            if cut - scan > line_max:
                oversized += 1
            else:
                lines.append(Line(buf_start + scan, buf_start + cut + 1, bytes(buf[scan:cut])))
            scan = cut + 1
        if scan:
            del buf[:scan]
            buf_start += scan
            offset = buf_start
        if len(buf) > line_max:
            oversized += 1
            skipping = True
            buf.clear()
            offset = buf_start = pos
    return Tail(lines, offset, skipping, oversized, read, at_end, peak)


def head_bytes(fd: int, length: int) -> bytes:
    """The first `length` bytes, fewer if the file is shorter (`os.pread` does not exist on
    Windows); `length` is at most `HEAD_BYTES` for the callers."""
    os.lseek(fd, 0, os.SEEK_SET)
    data = bytearray()
    while len(data) < length:
        chunk = os.read(fd, min(CHUNK, length - len(data)))
        if not chunk:
            break
        data += chunk
    return bytes(data)


def head_digest(fd: int, length: int) -> str:
    """SHA-256 of the first `length` bytes."""
    return hashlib.sha256(head_bytes(fd, length)).hexdigest()
