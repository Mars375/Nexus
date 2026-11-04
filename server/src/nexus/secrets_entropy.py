"""Jugement des valeurs opaques par entropie (ADR-006, SECURITY §1) : identifiants générés, mots,
entropie attendue. Fonctions pures, sans état."""

from __future__ import annotations

import re
from collections import Counter
from functools import cache
from math import log2

# Shannon entropy in bits per character: long natural words and repetitions sit
# around 2-3 bits, a uniform 16-symbol hex run stays near log2(16) = 4 — the
# threshold divides prose from opaque randomness (documented in issue #15).
_HIGH_ENTROPY_BITS = 3.5


def _shannon_bits_per_char(token: str) -> float:
    n = len(token)
    return -sum((p / n) * log2(p / n) for p in Counter(token).values())


def _lower_run_share(text: str) -> float:
    """Share of lowercase letters sitting in runs of three or more.

    A word scores near 1 (`utilisateur`, `deployments`); an opaque chunk,
    whose lowercase letters sit alone between digits or capitals
    (`N9vH4mKu`), scores near 0. Both slashed and underscore guards rule
    « words » with it.
    """
    total = longs = 0
    run = 0
    for ch in text + "\x00":
        if ch.islower():
            run += 1
            continue
        if run >= 3:
            longs += run
        total += run
        run = 0
    return longs / total if total else 0.0


def _case_chaos(token: str) -> float | None:
    """Share of adjacent letter pairs that shuffle case, on eight pairs or more.

    A random value shuffles case between neighbours; a name changes case at
    word starts, and a word start is not a shuffle. The chain of three-letter
    TitleCase words — `Dev/Ops/Tool/Run12345/Log6789` — holds two-character
    lowercase runs, below the words veto, and reached 0.45 on word starts
    alone: it was erased (Antigravity review on 5b186c5, a regression against
    master). A token whose changes ONLY open words carries no shuffle: None.
    None as well when the token holds too few letter pairs for the ratio to
    mean anything.
    """
    changes = word_starts = pairs = 0
    for index, (left, right) in enumerate(zip(token, token[1:], strict=False)):
        if not (left.isalpha() and right.isalpha()):
            continue
        pairs += 1
        if left.isupper() == right.isupper():
            continue
        changes += 1
        preceding = token[index - 1] if index else ""
        if left.isupper() and right.islower() and not preceding.isalpha():
            word_starts += 1
    if pairs < 8 or changes == word_starts:
        # Every change opens a word: `Dev/Ops/Tool/Run12345/Log6789` shuffles
        # nothing, a value that changes case only at word starts is a name.
        return None
    return changes / pairs


def _alternating_chunk(segment: str) -> bool:
    """Nearly every adjacent pair of a segment alternates a letter and a digit
    (`k1l2=`, `A1b`): the signature of a short chopped piece."""
    segment = segment.rstrip("=")
    pairs = list(zip(segment, segment[1:], strict=False))
    if len(pairs) < 2:
        return False
    boundaries = sum(
        1
        for left, right in pairs
        if (left.isalpha() and right.isdigit()) or (left.isdigit() and right.isalpha())
    )
    return boundaries / len(pairs) >= 0.8


def _word_chunk(part: str) -> bool:
    """A vocabulary chunk (a path word): all-lowercase letters, six of them at
    least.

    `controllers`, `tokens`, `releases` are words; a crypto segment keeps a
    digit (`SIIn3hucz0P4s`, `A0b`), shuffles case (`IlatOVdVhdwasWF`), or
    stays under six letters — where a base64 fragment is indistinguishable
    from a short word (`xyz`, `fcn`, `vwsw=`; Antigravity review on a77d504:
    reading every digitless chunk of three lowercase letters as a word leaked
    real 44-character keys). A path built only from shorter words
    (`api/v1/users/getById/v2b1`) is ruled by the whole-candidate share of
    `_opaque_slashed` before this rescue runs. The rescue in `_opaque_chunks`
    reads this to tell a phrase from a chopped value.
    """
    letters = part.rstrip("=")
    return letters.isalpha() and letters.islower() and len(letters) >= 6


# Generated-identifier pieces (issue #101): a timestamp, a UUID of version 4 or 7
# written as 32 hex digits, a ULID. Shared by the additions of the entropy pass and
# by the generated-identifier exemption.
_EPOCH_MS_FLOOR = 946_684_800_000  # 2000-01-01T00:00:00Z
_EPOCH_MS_CEILING = 4_102_444_800_000  # 2100-01-01T00:00:00Z
_HEX_SEGMENT = re.compile(r"[0-9a-f]+|[0-9A-F]+")
_ULID_SEGMENT = re.compile(r"[0-7][0-9a-hjkmnp-tv-z]{25}|[0-7][0-9A-HJKMNP-TV-Z]{25}")
_CROCKFORD = "0123456789abcdefghjkmnpqrstvwxyz"
_STAMP_WITH_T = re.compile(r"([0-9]{8})T([0-9]{6})Z?")
_MONTH_DAYS = (31, 29, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31)


def _timestamp_segment(segment: str) -> bool:
    """A date or a Unix epoch written in digits, as generators stamp their ids.

    `20261018`, `202610181430`, `20261018143022` and `20261018T143022Z` must be a
    valid date-time between 1970 and 2099; a 10- or 13-digit run must be an epoch
    in seconds or milliseconds between 2000 and 2100. Any other digit run (a
    counter, an account number, a 16-digit card number) is not one.
    """
    stamped = _STAMP_WITH_T.fullmatch(segment)
    if stamped:
        segment = stamped.group(1) + stamped.group(2)
    if not (segment.isascii() and segment.isdigit()):
        return False
    size = len(segment)
    if size in (8, 12, 14):
        year, month, day = int(segment[:4]), int(segment[4:6]), int(segment[6:8])
        if not (1970 <= year < 2100 and 1 <= month <= 12 and 1 <= day <= _MONTH_DAYS[month - 1]):
            return False
        if month == 2 and day == 29 and not (year % 4 == 0 and (year % 100 or year % 400 == 0)):
            return False
        clock = segment[8:]
        return all(
            int(clock[index:index + 2]) < (24 if index == 0 else 60)
            for index in range(0, len(clock), 2)
        )
    if size in (10, 13):
        millis = int(segment) * 1000 if size == 10 else int(segment)
        return _EPOCH_MS_FLOOR <= millis < _EPOCH_MS_CEILING
    return False


def _generated_id_segment(segment: str) -> bool:
    """A UUID of version 4 or 7 written as 32 hex digits, or a ULID.

    Version nibble and variant bits for the UUID (a random hex32 value matches a
    v4 one draw in 64), a plausible millisecond timestamp for the UUID v7 and the
    ULID (Crockford base32, one case, at least one letter past `f`: a hex run of
    26 digits is not one).
    """
    if len(segment) == 32 and _HEX_SEGMENT.fullmatch(segment):
        lowered = segment.lower()
        if lowered[16] not in "89ab":
            return False
        if lowered[12] == "4":
            return True
        return lowered[12] == "7" and (
            _EPOCH_MS_FLOOR <= int(lowered[:12], 16) < _EPOCH_MS_CEILING
        )
    if _ULID_SEGMENT.fullmatch(segment) and not _HEX_SEGMENT.fullmatch(segment):
        millis = 0
        for ch in segment[:10].lower():
            millis = millis * 32 + _CROCKFORD.index(ch)
        return _EPOCH_MS_FLOOR <= millis < _EPOCH_MS_CEILING
    return False


def _camel_shape(letters: str, versioned: bool) -> bool:
    """Every block of capitals opens a word (one capital before lowercase
    letters), is an acronym before a word (three capitals or more, `HTTPServer`),
    a trailing acronym (`toJSON`) or a version tag before final digits (`apiV2`).
    A random draw shuffles case (`SNcveshQ`, `JVwPNruz`). One linear scan."""
    index, size = 0, len(letters)
    while index < size:
        if not letters[index].isupper():
            index += 1
            continue
        end = index
        while end < size and letters[end].isupper():
            end += 1
        block = end - index
        if end < size and block == 2:
            return False
        if end == size and block == 1 and not versioned:
            return False
        index = end
    return True


def _opaque_run(token: str) -> bool:
    """Does a high-entropy candidate read as an opaque token or an identifier?"""
    if _shannon_bits_per_char(token) < _HIGH_ENTROPY_BITS:
        return False
    # Vendor tokens are drawn from digit-bearing alphabets; a candidate made
    # only of letters (joined label vocabulary such as
    # « authentification-rechargement ») is a phrase, not a secret —
    # clean_label() validates its labels through this very gate.
    if not any(ch.isdigit() for ch in token):
        return False
    # Framing separators (markdown italics `_token_`) only produce empty
    # segments: they do not drag the floor down, real segments decide.
    parts = [part for part in re.split(r"[-_]", token) if part]
    if parts and min(map(len, parts)) >= 8:
        return True
    # A short head segment is tolerated when EVERY following segment is full
    # length (≥ 8), carries a digit, mixes upper- and lowercase letters, AND
    # does not itself read as a word: « tok_Y7qP2rTx_… » is opaque (issue #84),
    # while a snake_case identifier whose tail is plain words with a digit
    # appended — v1_userprofile2_accountsettings3, db_connectionpool1_maxconnections2 —
    # stays an identifier (Antigravity review on d2361cc: those digit-bearing
    # word tails passed on length alone and masked five identifiers, a
    # regression against master; a digit-free tail such as `database` was
    # already ruled out on 6d78a6c). A tail of single lowercase letters
    # between digits and capitals keeps scoring 0 and passes.
    # Mixed case is the base62 signature of a vendor tail (issue #93): generated
    # identifiers draw theirs from single-case alphabets — decimal timestamps,
    # hex digests, base36 — and `evt_20261018143022_a1b2c3d4` was refused with a
    # 409. A segment of 24+ characters is exempt: a long hex tail is the shape of
    # real vendor keys (`key-<hex32>`, `shpat_<hex32>`) and no generated
    # identifier of this family carries one next to a decimal timestamp (that
    # segment still fails the case test). Assumed price: a short-prefixed value
    # made only of single-case segments under 24 characters is no longer masked.
    if len(parts) >= 2 and len(parts[0]) < 8 and all(
        len(part) >= 8
        and any(ch.isdigit() for ch in part)
        and (
            len(part) >= 24
            or (any(ch.isupper() for ch in part) and any(ch.islower() for ch in part))
        )
        and _lower_run_share(part) < 0.6
        for part in parts[1:]
    ):
        return True
    # A short vendor prefix does not break a token that holds a flat 24+ run
    # behind it (« tok_Y7qP2rTx… »): the prefix belongs to the value it names
    # and the whole candidate is masked. The 4-character groups of a UUID and
    # the words of a slug never reach 24 characters on their own.
    return any(
        len(part) >= 24 and _shannon_bits_per_char(part) >= _HIGH_ENTROPY_BITS
        for part in parts
    )


# Additions of the entropy pass (issue #101). `_opaque_run` is master's rule and
# is left untouched; `mask_random_run` masks a candidate when EITHER rule says so,
# so this block only ever adds masks. It catches the random values the segment
# rule missed — `token_urlsafe(32)` chopped at `-`/`_`, hex32/hex40 under 3.5 bits,
# `tok_<b62_8>×4`, `key_<hex8>×4`, `acct-<digits>-<b62>`, `<hex32>=`, `x+<hex32>` —
# by measuring the candidate's material: the candidate is split on `-` and `_`,
# the segments a person or a generator writes on purpose are set aside (a
# timestamp, a UUID, a ULID, a name), and the rest is cut at the base64 `+` and
# `=`. The candidate is added when that material holds at least `_OPAQUE_BITS`
# (Σ length × log2(alphabet), a joiner drawn inside a base64 value counting 6
# bits) and its Shannon entropy sits within `_ENTROPY_MARGIN` of a uniform draw.
# Setting a segment aside only ever removes an addition, never a mask of master.
# Its price is measured in the #101 comment: a split hex value of 128 bits is
# masked whatever its prefix (`span_<hex16>_<hex16>`), as a full SHA-1 already is.
_OPAQUE_BITS = 128.0
_ENTROPY_MARGIN = 0.6
# The expected entropy grows with the length; past 128 characters the cap only
# lowers the bar (more masking), and it bounds the cache of `_expected_entropy`.
_ENTROPY_SAMPLE_CAP = 128
_UUID_DASHED = re.compile(
    r"(?<![A-Za-z0-9])[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}"
    r"-[0-9a-fA-F]{12}(?![A-Za-z0-9])"
)
_NAME_SEGMENT = re.compile(r"[A-Za-z]+[0-9]{0,8}")
# A SCREAMING_SNAKE word of three letters or more (`HTTP2`, `MAX`, `CONCURRENT`).
_UPPER_NAME = re.compile(r"[A-Z]{3,}[0-9]{0,8}")
_BASE64_SIGNS = re.compile(r"[+=]")
# A `+` carries drawn bits only between two characters of material: a run of `+`
# (`v2++++++`) is not a base64 draw and must not inflate the bit count.
_PLUS_JOINER = re.compile(r"(?<=[A-Za-z0-9])\+(?=[A-Za-z0-9])")
# No usual alphabet is wider than base64: the bits per character are capped at
# log2(64), which also bounds the cache of `_expected_entropy`.
_MAX_ALPHABET = 64
# A `+`, `-` or `_` drawn as part of a base64 value carries log2(64) bits.
_DRAWN_JOINER_BITS = 6.0


def _name_segment(segment: str) -> bool:
    """A word or a camelCase / PascalCase / SCREAMING name, at most eight digits
    at its end (`accountsettings3`, `handleUserLoginV2`, `HTTPServer`, `HTTP2`)."""
    if _UPPER_NAME.fullmatch(segment):
        return True
    if not _NAME_SEGMENT.fullmatch(segment) or _lower_run_share(segment) < 0.6:
        return False
    letters = segment.rstrip("0123456789")
    return _camel_shape(letters, len(letters) < len(segment))


def _alphabet_size(piece: str) -> int:
    """The smallest usual alphabet that holds a piece: 16 for hex digits of one
    case, otherwise 10 per digit class and 26 per letter case present."""
    has_lower = any("a" <= ch <= "z" for ch in piece)
    has_upper = any("A" <= ch <= "Z" for ch in piece)
    has_digit = any("0" <= ch <= "9" for ch in piece)
    if (has_lower or has_upper) and _HEX_SEGMENT.fullmatch(piece):
        return 16
    return 10 * has_digit + 26 * has_lower + 26 * has_upper


@cache
def _expected_entropy(size: int, alphabet: int) -> float:
    """Expected Shannon entropy, in bits per character, of `size` characters
    drawn uniformly from `alphabet` symbols: log2(n) − (k / n) · E[c · log2(c)],
    c the binomial count of one symbol. At most 128 × 63 pairs are ever computed.
    """
    p = 1.0 / alphabet
    ratio = p / (1.0 - p)
    pmf = (1.0 - p) ** size
    weighted = 0.0
    for count in range(1, size + 1):
        pmf *= (size - count + 1) / count * ratio
        if count >= 2:
            weighted += pmf * count * log2(count)
    return log2(size) - alphabet * weighted / size


def _mixed_case(part: str) -> bool:
    return any("a" <= ch <= "z" for ch in part) and any("A" <= ch <= "Z" for ch in part)


def _drawn_joiners(parts: list[str], aside: list[bool]) -> int:
    """Joiners drawn as base64 symbols: a `+` between two characters of material counts
    (a run of `+` does not); a `-` or `_` counts when a neighbour is mixed-case material
    and no neighbour was set aside (`tok_<urlsafe16>`, 128 bits, lost 6 bits per joiner)."""
    count = sum(
        len(_PLUS_JOINER.findall(part)) for part, kept in zip(parts, aside, strict=True) if not kept
    )
    for left, right, left_aside, right_aside in zip(
        parts, parts[1:], aside, aside[1:], strict=False
    ):
        if not (left_aside or right_aside) and (_mixed_case(left) or _mixed_case(right)):
            count += 1
    return count


def _opaque_material(token: str) -> bool:
    """Does the candidate hold a uniform draw of 128 bits or more? An addition
    to `_opaque_run`, never a replacement."""
    if not any(ch.isdigit() for ch in token) or not any(ch.isalpha() for ch in token):
        return False
    parts = re.split(r"[-_]", _UUID_DASHED.sub("_", token))
    aside = [
        bool(part)
        and (_timestamp_segment(part) or _generated_id_segment(part) or _name_segment(part))
        for part in parts
    ]
    pieces = [
        piece
        for part, kept in zip(parts, aside, strict=True)
        if part and not kept
        for piece in _BASE64_SIGNS.split(part)
        if piece
    ]
    if not pieces:
        return False
    sizes = [_alphabet_size(piece) for piece in pieces]
    # A hex piece that drew no letter (`30882887`) is still hex.
    if 16 in sizes:
        sizes = [16 if size == 10 else size for size in sizes]
    bits = sum(len(piece) * log2(size) for piece, size in zip(pieces, sizes, strict=True))
    bits += _DRAWN_JOINER_BITS * _drawn_joiners(parts, aside)
    if bits < _OPAQUE_BITS:
        return False
    joined = "".join(pieces)
    alphabet = min(_MAX_ALPHABET, max(2, round(2 ** (bits / len(joined)))))
    expected = _expected_entropy(min(len(joined), _ENTROPY_SAMPLE_CAP), alphabet)
    return _shannon_bits_per_char(joined) >= expected - _ENTROPY_MARGIN
