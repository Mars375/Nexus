"""Jugement des valeurs à barres obliques (ADR-006, SECURITY §1, issue #144) : segments opaques,
queue de candidat, fenêtres opaques et leur application."""

from __future__ import annotations

import re
from collections.abc import Callable
from contextvars import ContextVar
from math import log2

from nexus.secrets_entropy import (
    _HIGH_ENTROPY_BITS,
    _alternating_chunk,
    _case_chaos,
    _lower_run_share,
    _name_segment,
    _shannon_bits_per_char,
    _word_chunk,
)
from nexus.secrets_patterns import _MARKED_SLASHED_RUN, REDACTED


def _blob_segment(segment: str) -> bool:
    """One chunk of an opaque slashed value, as opposed to a path word.

    Opaque chunks interleave letters and digits (`A1b2C3d4E5`,
    `K1N7xP9mQ2vL8jR3tY6`) or shuffle case without any word structure
    (`G9woFbdKetaZSNxZWxL2`). Human names of the corpus — `AccountSettingsV2`,
    `V1Release2026Build`, `deployments`, `build42` — keep letters and digits in
    words, and change case at word starts instead of at random, so each part
    stays far below one of the two signals (Antigravity and reviewer reviews on
    c73aee9: this guard replaces the old « two segments mixing case and digits »,
    which erased exactly those paths).
    """
    # A segment may end with base64 padding (`k1l2=`): the blob reads its data
    # part, `=` never carries a signal.
    segment = segment.rstrip("=")
    pairs = list(zip(segment, segment[1:], strict=False))
    # Letters and digits alternate: the signature of a chunked base64 value.
    # Six pairs at least (seven characters): a shorter chunk is a version tag
    # or an instance type (`v1rc1`, `v1a1`, `g4dn`, `c5ad`), whose alternation
    # is the signature of a NAME at that scale (Antigravity review on d2361cc:
    # those tags counted as blobs and erased release, k8s and Terraform paths).
    boundaries = sum(
        1
        for left, right in pairs
        if (left.isalpha() and right.isdigit()) or (left.isdigit() and right.isalpha())
    )
    if len(pairs) >= 6 and boundaries / len(pairs) >= 0.6:
        return True
    # Case changes at random rather than at word starts (letter pairs only).
    # Short PascalCase names (`ApiV2`, `AppData`) stay out: a real value mixes
    # case across many more letter pairs than a name holds. A camelCase method
    # (`getById`) can reach the ratio alone, but it never makes a path: the
    # words veto of `_opaque_slashed` rules the candidate before this arm.
    letter_pairs = [(left, right) for left, right in pairs if left.isalpha() and right.isalpha()]
    return (
        len(letter_pairs) >= 6
        and sum(1 for left, right in letter_pairs if left.isupper() != right.isupper())
        / len(letter_pairs)
        > 0.5
    )


def _blobs_of(parts: list[str]) -> list[str]:
    return [part for part in parts if _blob_segment(part)]


def _opaque_chunks(parts: list[str]) -> bool:
    """Structural signal of a chopped value: its blobs and boundary chunks.

    At least TWO blobs, or one blob when the other chunks read as the rest of
    a value rather than as a phrase: they carry a signal — a strong
    letter-digit alternation (`k1l2=`), a one-or-two character boundary
    segment (`A/…`, `…/p6`, Antigravity review on d2361cc, finding 1: such
    chunks can never be blobs on their own), or a chunk that shuffles case
    like a random draw (`IlatOVdVhdwasWF`, `q3QCEgcaHD6honHxcM`; Antigravity
    review on a77d504: real 44-character keys leaked whole when every extra
    chunk missed the first two arms) — and none of them is a word. A path
    word beside an alternating tag is a route, not a value
    (`controllers/DevSecOps/v1a1`, Antigravity review on 5efcee9), while a
    digit-bearing crypto segment is not a word (`SIIn3hucz0P4s`, `NZD`;
    Antigravity review on 49b2fe0: requiring the signal on EVERY other chunk
    leaked real keys whose extra segment misses the blob floor). A lone blob
    with nothing beside it is a bare value. The whole-candidate guard and the
    tail guard rule on the same signal.
    """
    blobs = _blobs_of(parts)
    if len(blobs) >= 2:
        return True
    if blobs:
        rest = [part for part in parts if part not in blobs]
        if not rest:
            return True
        carries_signal = any(
            _alternating_chunk(part)
            or len(part) <= 2
            or (_case_chaos(part) or 0) > 0.30
            for part in rest
        )
        if carries_signal and not any(_word_chunk(part) for part in rest):
            return True
    return False


def _opaque_tail_start(parts: list[str]) -> int | None:
    """The lowest start whose tail is an opaque value, in one backward pass.

    The words veto of `_opaque_slashed` reads `etc/tokens/A1b2…/K1l2…` as a
    path — the words ahead of the value push its lowercase share to 0.6 — and
    the whole candidate then failed the guard with the value in the clear
    (Antigravity review on 5b186c5; the leak exists on master too). The
    case-shuffle arm is left out here: it rules a whole candidate, and a name
    split on one slash, `DevSecOps/getById2`, reaches it alone (frozen keep
    case, Antigravity review on c73aee9). The tail must show the structural
    signal instead — the same blobs and boundary chunks as the whole guard
    (Antigravity review on cc0eeb3: a two-blob floor let `cat
    /etc/tokens/A/1b2…` leak whole and left the boundary chunks of
    `…/A/F6g7…/B` in the clear).

    Every gate of that per-tail predicate reads quantities of the tail this
    pass accumulates part by part — its length, a digit, the Shannon entropy
    (kept as Σ c·log2(c), one step per character), the share of lowercase
    letters in runs of three, and the flags `_opaque_chunks` reads — so the
    lowest opaque start comes out of ONE pass and no tail is ever rebuilt:
    `"/".join(parts[start:])` per start cost O(parts × length) and a comment
    body carries no length bound (`CommentIn.body`), which handed a
    synchronous worker minutes of CPU for one long slashed run (CodeRabbit
    review on 7d8fdcd). The start found is the same the loop returned — the
    first tail the gates accept — and every tail stays eligible: a length
    bound would skip the head of a value longer than the bound and mask only
    its end.
    """
    length = 0
    has_digit = False
    counts: dict[str, int] = {}
    weighted = 0.0  # Σ c·log2(c) of the tail: entropy = log2(length) - weighted / length
    lower_total = 0
    lower_long = 0
    blobs = 0
    extra = 0
    signals = 0
    words = 0
    start_found: int | None = None
    first = True
    for start in range(len(parts) - 1, 0, -1):
        part = parts[start]
        if first:
            first = False
        else:
            length += 1  # the slash joining this part to the tail below it
            before = counts.get("/", 0)
            counts["/"] = after = before + 1
            if before:
                weighted += after * log2(after) - before * log2(before)
        length += len(part)
        run = 0
        for ch in part:
            before = counts.get(ch, 0)
            counts[ch] = after = before + 1
            if before:
                weighted += after * log2(after) - before * log2(before)
            if ch.isdigit():
                has_digit = True
            if ch.islower():
                run += 1
                continue
            if run >= 3:
                lower_long += run
            lower_total += run
            run = 0
        if run >= 3:
            lower_long += run
        lower_total += run
        if _blob_segment(part):
            blobs += 1
        else:
            extra += 1
            if _alternating_chunk(part) or len(part) <= 2 or (_case_chaos(part) or 0) > 0.30:
                signals += 1
            if _word_chunk(part):
                words += 1
        if length < 24 or not has_digit:
            continue
        if log2(length) - weighted / length < _HIGH_ENTROPY_BITS:
            continue
        if lower_total and lower_long / lower_total >= 0.6:
            continue
        # Same structural rule as `_opaque_chunks`, on counted flags: two
        # blobs, or one blob whose other chunks carry a signal and none of
        # them is a word (no other chunk at all keeps the bare value).
        if blobs >= 2 or (blobs and (extra == 0 or (signals > 0 and words == 0))):
            start_found = start
    return start_found


def _opaque_slashed(token: str) -> bool:
    """Guard of the slashed pattern (issue #84): an opaque chopped value, not a path."""
    if len(token) < 24:
        return False
    if not any(ch.isdigit() for ch in token):
        return False
    if _shannon_bits_per_char(token) < _HIGH_ENTROPY_BITS:
        return False
    # A path is made of words: when most lowercase letters sit in runs of
    # three or more, the candidate names something and stays intact. The veto
    # covers `serveur/src/nexus`, `/var/backups/…`, `deployments/20261018/…`,
    # `C:/Users/Orion/AppData/…` and the camelCase routes
    # (`api/v1/users/getById/v2b1` — Antigravity review on d2361cc: judging
    # chunk by chunk alone erased them; every keep-corpus candidate that
    # reaches the guard sits at 0.64 or above).
    if _lower_run_share(token) >= 0.6:
        return False
    # A random value shuffles case between adjacent letters; a name changes
    # case at word starts. The veto above rules the word paths, and among the
    # candidates that reach this line 0.30 was the tightest floor that kept
    # the whole corpus (Antigravity review on d2361cc, finding 1: whole-value
    # signals do not depend on how the value happened to be chopped — real
    # 32-byte base64 keys leaked 16.1 % whole and 70.5 % partly).
    chaos = _case_chaos(token)
    if chaos is not None and chaos > 0.30:
        return True
    # A chopped value also keeps the signature of its chunks, worked out by
    # `_opaque_chunks` (24-character floor instead of 40, Antigravity review on
    # c73aee9: 24-to-39-character keys leaked). Two assumed limits stay, both
    # carrying no signal for that rule: an all-lowercase slashed blob and a
    # value whose every slash segment falls under the floor — as with the hex
    # segment of an asset path (#84).
    parts = [part for part in token.split("/") if part]
    return _opaque_chunks(parts)


# Segments that read as path words and cut a slashed candidate into windows
# (issue #144): a lowercase word with a short numeric suffix, digits alone, a
# version tag (`v1`, `V2`, `v1beta2`, `v2rc1`), a release candidate (`rc1`), or a
# name in camelCase / PascalCase / SCREAMING style (`_name_segment`).
_PATH_WORD = re.compile(
    r"[a-z]{3,}[0-9]{0,4}|[0-9]+|[vV][0-9]{1,3}(?:(?:alpha|beta|rc)[0-9]+)?|rc[0-9]+"
)


def _path_word(segment: str) -> bool:
    return bool(_PATH_WORD.fullmatch(segment)) or _name_segment(segment)


# Opaque windows (tuples of consecutive segments) met by the passes of ONE `redact` call
# (issue #144).
# A ContextVar, never a module global: the scanner runs in concurrent workers, and
# each call (each thread, each task) sees only its own collector. None outside
# `redact`: the rule then collects nothing.
_WINDOWS: ContextVar[set[tuple[str, ...]] | None] = ContextVar("opaque_windows", default=None)


def _mask_opaque_windows(parts: list[str]) -> None:
    """Note the opaque windows between path words of a candidate.

    A key whose own slashes chop it into segments, written between path words
    (`s3://bucket/<key>/backups/production`, `api/v1/<key>/download`), made the
    words veto of `_opaque_slashed` rule the whole candidate a path, and the
    tail rule never finds a tail free of words: the key leaked. Cutting the
    candidate at every word leaves windows of consecutive non-word segments;
    a window of two segments or more that `_opaque_slashed` judges opaque is
    noted, as the ordered tuple of its segments, in the collector of the running
    `redact` call.

    Nothing is rewritten here: masking a window during a pass changed what the
    next passes of the fixed point saw (`<16>/backups/MRS/rkEj/<24>` lost its
    entropy-masked tail and kept 16 opaque characters readable, PR 146 review).
    `redact` applies the noted windows once the passes of the existing rules
    reached their fixed point. One pass over the segments, each read once.
    """
    collector = _WINDOWS.get()
    if collector is None:
        return
    window: list[str] = []

    def close() -> None:
        if 2 <= len(window) < len(parts) and _opaque_slashed("/".join(window)):
            collector.add(tuple(window))
        window.clear()

    for part in parts:
        if _path_word(part):
            close()
        else:
            window.append(part)
    close()


# Verification budget of `_mask_noted_segments`, per segment read (windows noted + parts of
# the slashed runs): beyond it the output is masked by maximal window instead.
_APPLY_BUDGET_FACTOR = 16


class _BudgetExceeded(Exception):
    pass


def _walk(
    parts: list[str], start: int, seq: tuple[str, ...], k: int, step: int, spend: Callable[[], None]
) -> int | None:
    """Follow `seq` from element `k` (exclusive) and text part `start` (exclusive) in
    direction `step`; return the last part index reached, None when the text differs.

    A `[REDACTED]` marker may stand for one element or more (the tail rule and the
    labelled values swallow several segments in one mask): it eats elements up to the
    next one equal to the part after the marker.
    """
    ti, sk = start + step, k + step
    while 0 <= sk < len(seq):
        if not 0 <= ti < len(parts):
            return None
        spend()
        if parts[ti] == seq[sk]:
            ti += step
            sk += step
        elif parts[ti] == REDACTED:
            sk += step
            after = ti + step
            while 0 <= sk < len(seq) and not (0 <= after < len(parts) and parts[after] == seq[sk]):
                spend()
                sk += step
            ti = after
        else:
            return None
    return ti - step


def _mask_noted_segments(text: str, noted: set[tuple[str, ...]]) -> str:
    """Mask, in the slashed runs of `text`, every noted window found whole.

    A window applies only where its CONSECUTIVE segments are all found (a marker
    standing for several of them): a segment shared with a healthy path is never
    touched on its own. Windows overlapping or nested add up. Verifications are
    counted; a pathological text that exceeds the budget is masked by maximal window
    (non-word segments and markers) holding a noted segment instead, which is linear
    and only over-masks (ADR-006).
    """
    if not noted:
        return text
    index: dict[str, list[tuple[tuple[str, ...], int]]] = {}
    for seq in noted:
        for k, segment in enumerate(seq):
            index.setdefault(segment, []).append((seq, k))
    budget = _APPLY_BUDGET_FACTOR * (sum(len(seq) for seq in noted) + len(text.split("/")))

    def spend() -> None:
        nonlocal budget
        budget -= 1
        if budget < 0:
            raise _BudgetExceeded

    def mask_run(match: re.Match[str]) -> str:
        parts = match.group(0).split("/")
        hit = [False] * len(parts)
        for i, part in enumerate(parts):
            for seq, k in index.get(part, ()):
                if hit[i]:
                    break
                spend()
                left = _walk(parts, i, seq, k, -1, spend)
                right = _walk(parts, i, seq, k, 1, spend) if left is not None else None
                if left is not None and right is not None:
                    for position in range(min(left, i), max(right, i) + 1):
                        hit[position] = True
        return "/".join(REDACTED if flag else part for part, flag in zip(parts, hit, strict=True))

    known = {segment for seq in noted for segment in seq}

    def mask_windows(match: re.Match[str]) -> str:
        parts = match.group(0).split("/")
        out: list[str] = []
        window: list[str] = []

        def close() -> None:
            if any(part in known for part in window):
                out.extend(REDACTED for _ in window)
            else:
                out.extend(window)
            window.clear()

        for part in parts:
            if part != REDACTED and _path_word(part):
                close()
                out.append(part)
            else:
                window.append(part)
        close()
        return "/".join(out)

    try:
        return _MARKED_SLASHED_RUN.sub(mask_run, text)
    except _BudgetExceeded:
        return _MARKED_SLASHED_RUN.sub(mask_windows, text)
