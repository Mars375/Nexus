"""CI guard of the `redact` measure (spec §7.1, plan PR 2 §2; decision D0, option A).

On 1 MiB of invented text without full hex digests, at most 1 message in 20 is masked with no
secret in it. A full SHA-1 or SHA-256 is always masked: the accepted false positive of D0,
pinned here so that a change of `redact` says so. No throughput is asserted in CI.
"""

import random

import redact_corpus as corpus

from nexus.secrets import REDACTED, redact

MIB = 1 << 20


def test_over_masking_without_full_hashes_stays_under_one_in_twenty():
    messages = corpus.build(MIB, seed=204, hash_weight=0)
    assert not any(kind in corpus.HASH_KINDS for kind, _ in messages)

    masked = sum(redact(text)[0] != text for _, text in messages)

    assert len(messages) > 200
    assert masked / len(messages) <= 1 / 20


def test_every_full_hash_is_masked_the_accepted_false_positive():
    messages = [m for m in corpus.build(MIB // 2, seed=205, hash_weight=50)
                if m[0] in corpus.HASH_KINDS]
    assert len(messages) > 20

    for _, text in messages:
        out, found = redact(text)
        assert REDACTED in out and found


def test_short_shas_stay_searchable():
    rng = random.Random(7)
    for _ in range(200):
        sha = corpus.short_sha(rng)
        text = f"PR fusionnée en {sha}."
        assert redact(text)[0] == text


def test_seeded_secrets_are_never_left_visible():
    for secret, text in corpus.seeded(200, seed=206):
        out, found = redact(text)
        assert not corpus.visible(secret, out)
        assert found


def test_a_claude_provenance_reference_is_left_intact():
    rng = random.Random(204)
    for _ in range(500):
        ref = corpus.provenance_ref(rng)
        assert redact(ref) == (ref, [])
