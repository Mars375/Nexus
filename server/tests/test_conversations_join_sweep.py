"""A secret split between text blocks never reaches the index, at any split position.

Each kind of seeded secret is cut at every position into two blocks, and at sampled positions
into three, with or without a neighbour block before and after it (glued or spaced): no piece
of 8 characters of its confidential value may remain in the stored body."""

import random
from datetime import UTC, datetime

import pytest
from redact_corpus import seeded_secret

from nexus.conversations import masking

AT = datetime(2026, 11, 1, tzinfo=UTC)


def body(parts: list[str]) -> str:
    message = masking.make_message(external_id="x", role="user", author="loic", at=AT,
                                   text=masking.join_blocks(parts))
    return "" if message is None else message.body.replace("\n", "")


def one_of_each_kind() -> list:
    rng, kinds = random.Random(204), {}
    while len(kinds) < 7:
        secret = seeded_secret(rng)
        kinds.setdefault(secret.whole[:6], secret)
    return sorted(kinds.values())


@pytest.mark.parametrize("secret", one_of_each_kind(), ids=lambda s: s.whole[:6])
def test_no_piece_of_a_split_secret_is_left(secret):
    whole, value = secret.whole, secret.value
    splits = [[whole[:i], whole[i:]] for i in range(1, len(whole))]
    splits += [[whole[:i], whole[i:j], whole[j:]]
               for i in range(1, len(whole), 3) for j in range(i + 1, len(whole), 5)]
    pieces = [value[i:i + 8] for i in range(max(1, len(value) - 7))]
    for split in splits:
        for before, after in ((None, None), ("voir", "suite"), ("voir ", " suite")):
            parts = ([before] if before else []) + split + ([after] if after else [])
            out = body(parts)
            assert not [p for p in pieces if p in out], parts
