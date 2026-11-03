"""Valeurs à barres obliques masquées par le scanner de secrets (#87, #95, ADR-006)."""

import base64
import random
import time

import pytest

from nexus.secrets import REDACTED, redact


def test_slashed_base64_is_masked_whole():
    # issue #84, first disposition: a slash broke the candidate class and every
    # flat sub-run stayed under 24 characters; the dedicated pattern masks the
    # whole value (61 characters, three slashes, assembled at runtime).
    chaine = "G9woFbdKetaZSNx" + "ZWxL2/h6SqXW3Jx2" + "i1Un7pjawt/N/" + "lHENmK19lIgDjpy40"
    cleaned, found = redact(f"cle {chaine} notée")
    assert cleaned == f"cle {REDACTED} notée"
    assert found == ["high_entropy"]


def test_slashed_run_with_a_flat_24_segment_is_masked_whole():
    # Order matters: the slashed pass runs BEFORE the entropy pass, so a value
    # whose first segment already reaches 24 characters is masked in one piece.
    chaine = "A1b2C3d4E5f6G7h8" + "I9j0K1l2/M3n4O5p6Q7" + "r8S9t0U1v2/W3x4Y5z6" + "A7b8C9d0E1f2"
    cleaned, found = redact(f"jeton {chaine} reçu")
    assert cleaned == f"jeton {REDACTED} reçu"
    assert found == ["high_entropy"]


def test_slashed_base64_with_a_short_head_is_masked_whole():
    # Antigravity review on 6d78a6c: anchoring the pattern at 16 characters left
    # the head of the value in the clear (`A1b2C3d4E5/[REDACTED]` is still a
    # leak) — the whole value is masked now, first segment included.
    chaine = (
        "A1b2C3d4E5/"
        + "F6g7H8i9J0k1L2m3N4"
        + "/O5p6Q7r8S9t0U1v2W3"
        + "/X4y5Z6a7B8c9D0e"
        + "1F2"
    )
    cleaned, found = redact(f"cle {chaine} ici")
    assert cleaned == f"cle {REDACTED} ici"
    assert found == ["high_entropy"]


def test_slashed_base64_with_a_single_slash_is_masked_whole():
    # A 44-character key split by ONE slash (many 32-byte keys carry a single
    # `/`): the two-slash floor let it out in the clear (Antigravity review on
    # 6d78a6c). Assembled at runtime from short pieces.
    chaine = "K1N7xP+9mQ2vL8jR" + "3tY6/wA0bC4dE5fG7" + "h8i9j0k1l2="
    cleaned, found = redact(f"cle {chaine} ici")
    assert cleaned == f"cle {REDACTED} ici"
    assert found == ["high_entropy"]


def test_slashed_value_with_a_one_character_head_is_masked_whole():
    # Antigravity review on c73aee9: a two-character minimum on the first
    # segment let a one-character head through (`A/F6g7…` half in the clear).
    chaine = (
        "A/"
        + "F6g7H8i9J0k1L2m3N4"
        + "/O5p6Q7r8S9t0U1v2W3"
        + "/X4y5Z6a7B8c9D0e1F2"
    )
    cleaned, found = redact(f"cle {chaine} ici")
    assert cleaned == f"cle {REDACTED} ici"
    assert found == ["high_entropy"]


def test_slashed_value_glued_behind_a_slash_is_masked_whole():
    # Antigravity review on c73aee9: the lookbehind included `/`, so a value
    # written after a bare slash (`lecture /<jeton>`) blocked every start and
    # leaked whole. Assembled at runtime from short pieces.
    chaine = (
        "A1b2C3d4E5/" + "F6g7H8i9J0k1L2m3N4"
        + "/O5p6Q7r8S9t0U1v2W3"
        + "/X4y5Z6a7B8c9D0e1F2"
    )
    cleaned, found = redact(f"lecture /{chaine} sur le disque")
    assert cleaned == f"lecture /{REDACTED} sur le disque"
    assert found == ["high_entropy"]


def test_slashed_value_behind_path_words_is_masked_whole():
    # `/etc/tokens/<jeton>`: the match starts on the path words ahead of the
    # value and the opaque run takes them with it (over-redaction, ADR-006).
    chaine = (
        "A1b2C3d4E5/" + "F6g7H8i9J0k1L2m3N4"
        + "/O5p6Q7r8S9t0U1v2W3"
        + "/X4y5Z6a7B8c9D0e1F2"
    )
    cleaned, found = redact(f"cat /etc/tokens/{chaine}")
    assert cleaned == f"cat /{REDACTED}"
    assert found == ["high_entropy"]


def test_slashed_key_behind_path_words_is_masked_to_its_tail():
    # Antigravity review on 5b186c5: a 24-to-39-character key behind path
    # words pushes the words veto over 0.6 — the candidate reads as a path
    # and the key leaked in the clear (`cat /etc/tokens/…`, the failure the
    # long chain above never reached because its segments diluted the words).
    # The opaque tail is masked; the path words ahead of it are kept.
    chaine = "A1b2C3d4E5f6" + "/K1l2M3n4O5p6"
    cleaned, found = redact(f"cat /etc/tokens/{chaine}")
    assert cleaned == f"cat /etc/{REDACTED}"
    assert found == ["high_entropy"]


def test_slashed_key_behind_url_words_is_masked_to_its_tail():
    # The same leak in a URL: `localhost/keys/<cle>` and `…/tokens/<cle>`.
    chaine = "A1b2C3d4" + "/E5f6G7h8" + "/I9j0K1l2" + "/M3n4O5p6"
    cleaned, found = redact(f"curl http://localhost/keys/{chaine}")
    assert cleaned == f"curl http://localhost/{REDACTED}"
    assert found == ["high_entropy"]
    cleaned, found = redact(f"https://example.com/api/v1/auth/tokens/{chaine}")
    assert cleaned == f"https://example.com/{REDACTED}"
    assert found == ["high_entropy"]


def test_slashed_key_with_short_boundary_chunks_behind_path_words_is_masked():
    # Antigravity review on cc0eeb3: the tail guard demanded TWO blobs while
    # the whole guard also accepts one blob sided by boundary chunks — the
    # frozen `<cle>`, `A/<cle>`, `<cle>/p6` and `A/<cle>/B` forms leaked whole
    # behind `/etc/tokens/`, their boundary chunks included (`A/…/B` showed
    # `A/` and `/B`). The tail now rules on the same chunks. Chains assembled
    # at runtime from short pieces.
    cas = (
        # `A/<cle>`.
        ("A/" + "1b2C3d4E5f6" + "K1l2M3n4O5p6", f"cat /etc/tokens/{REDACTED}"),
        # `A1b/<cle>`: a three-character chunk whose letter-digit alternation
        # makes it a signal on its own (the path word `tokens` stays visible).
        ("A1b/" + "2C3d4E5f6" + "K1l2M3n4" + "O5p6", f"cat /etc/tokens/{REDACTED}"),
        # `<cle>/p6`.
        (
            "A1b2C3d4E5f6" + "K1l2M3n4O5" + "/p6",
            f"cat /etc/tokens/{REDACTED}",
        ),
        # `A/<cle>/B`, both boundaries in the masked run.
        (
            "A/" + "F6g7H8i9J0" + "k1L2m3N4O5p6" + "Q7r8S9t0" + "/B",
            f"cat /etc/tokens/{REDACTED}",
        ),
    )
    for chaine, attendu in cas:
        cleaned, found = redact(f"cat /etc/tokens/{chaine}")
        assert cleaned == attendu, chaine
        assert found == ["high_entropy"], chaine


def test_slashed_key_with_a_crypto_segment_beside_its_blob_is_masked():
    # Antigravity review on 49b2fe0: the rescue then demanded the signal on
    # EVERY other chunk, so a real key whose remaining segment is a
    # digit-bearing crypto chunk (no word shape: `SIIn3hucz0P4s`, `NZD`)
    # leaked wholly — naked in a sentence, or behind a path when the
    # whole-token guard stays silent (the tail guard read the same `all`).
    # The rescue now pairs the signal with a word veto per chunk. Chains
    # assembled at runtime from short pieces.
    cas = (
        # Naked in a sentence: one blob, one alternating chunk and one
        # digit-bearing segment that is neither.
        (
            "cle " + "J5PHA+i9s8X" + "93R4P4TJ/tk6W0L/" + "tavrOV3TVE" + "8YJaZWP ici",
            f"cle {REDACTED} ici",
        ),
        # Behind a path: the path words hold the whole candidate under its
        # words floor, and the digit-bearing segment is no word.
        (
            "cat /etc/tokens/" + "SIIn3hucz0P4s" + "/A0b/" + "nIrNiDHFU8O48=",
            f"cat /etc/tokens/{REDACTED}",
        ),
        # A digitless all-caps segment (`NZD`) has no run of three lowercase
        # letters: not a word, so the rescue fires.
        (
            "cat /etc/tokens/" + "NZD/" + "3GdKQgov3o/rIlI9wynQZe/" + "N5Q==",
            f"cat /etc/tokens/{REDACTED}",
        ),
        (
            "cat /etc/tokens/" + "6R8Z/" + "8Dy2EbS6FWyaH/" + "LsWZ2cA==",
            f"cat /etc/tokens/{REDACTED}",
        ),
        # The constructed form of `reviewer` r7 (P3): every chunk under the
        # 24-character floor, one blob, one alternating segment and one
        # version-shaped segment — no word, so the rescue fires.
        (
            "cle " + "A1b2C3d4E5f6" + "/k1l2=/" + "v1rc1" + " ici",
            f"cle {REDACTED} ici",
        ),
    )
    for text, attendu in cas:
        cleaned, found = redact(text)
        assert cleaned == attendu, text
        assert found == ["high_entropy"], text


def test_slashed_key_with_short_lowercase_fragments_is_masked():
    # Antigravity review on a77d504: the word veto read any digitless chunk
    # holding three adjacent lowercase letters as a word, so a real key that
    # carries a short base64 fragment (`xyz`, `abcde`, `fcn`, `vwsw=`) leaked
    # naked or behind a path. A word is now all-lowercase letters, six of them
    # at least. Chains assembled at runtime from short pieces.
    cas = (
        (
            "cat /etc/tokens/" + "A1b2C3d4E5f6" + "/k1l2=/" + "abcde",
            f"cat /etc/tokens/{REDACTED}",
        ),
        (
            "cle " + "A/1b2C3d4E5f6" + "K1l2M3n4O5p6" + "/xyz" + " ici",
            f"cle {REDACTED} ici",
        ),
        (
            "cat /etc/tokens/" + "A/1b2C3d4E5f6" + "K1l2M3n4O5p6" + "/xyz",
            f"cat /etc/tokens/{REDACTED}",
        ),
        # The digitless mixed-case chunk (`reviewer` r8, P3) stays no word
        # either: it shuffles case, it is not lowercase letters.
        (
            "cle " + "A1b2C3d4E5f6G7h8" + "/abc/XY/w ici",
            f"cle {REDACTED} ici",
        ),
        (
            "cle " + "a1b2c3d4e5f6g7h8" + "/ijkl/MN ici",
            f"cle {REDACTED} ici",
        ),
    )
    for text, attendu in cas:
        cleaned, found = redact(text)
        assert cleaned == attendu, text
        assert found == ["high_entropy"], text


def test_slashed_key_whose_extra_chunks_shuffle_case_is_masked():
    # Antigravity review on a77d504: a real 44-character base64 key chopped
    # by its own slashes leaked whole when every extra chunk missed the two
    # older signal arms (no letter-digit alternation, no boundary segment).
    # A chunk whose case shuffles like a random draw is the third signal of a
    # chopped piece, at the same 0.30 bar the whole-candidate guard reads on
    # its own token. Chains assembled at runtime from short pieces.
    cas = (
        (
            "cat /etc/tokens/"
            + "0UzvrPCc"
            + "/fcn/"
            + "8SKDsHj+ePj"
            + "/"
            + "q3QCEgcaHD6honHxcM=",
            f"cat /etc/tokens/0UzvrPCc/{REDACTED}",
        ),
        (
            "cat /etc/tokens/"
            + "xJ8byUs17"
            + "mQNVb7DnqRJ"
            + "/"
            + "IlatOVdVhdwasWF"
            + "/"
            + "JbUUEY=",
            f"cat /etc/tokens/{REDACTED}",
        ),
    )
    for text, attendu in cas:
        cleaned, found = redact(text)
        assert cleaned == attendu, text
        assert found == ["high_entropy"], text


def test_a_very_long_slashed_value_behind_path_words_is_masked_from_its_head():
    # CodeRabbit review on 7d8fdcd: bounding the tails before the pass (the
    # review's 256-character suggestion) would skip this head and leave it
    # visible — a 533-character value behind path words is still masked
    # whole from its first segment. The boundary pass keeps every tail
    # eligible; the shape is assembled at runtime.
    value = "/".join(["A1B2C3D4E5F6"] * 40) + "/K1L2M3N4O5P6="
    cleaned, found = redact(f"cat /etc/tokens/{value}")
    assert cleaned == f"cat /etc/tokens/{REDACTED}"
    assert found == ["high_entropy"]


def test_a_very_long_slashed_run_is_analysed_in_one_pass():
    # CodeRabbit review on 7d8fdcd (Major): every start rebuilt its tail
    # (`"/".join(parts[start:])`) and re-read the gates, and this repetitive
    # run fails the whole-candidate guard at the entropy floor, so the old
    # loop analysed all 4 000 tails — `CommentIn.body` carries no length
    # bound and one 48 KB run cost 2.4 s of CPU on a synchronous worker. The
    # boundary pass accumulates the same gates in one sweep; the ceiling
    # below catches a quadratic return (tens of milliseconds now, seconds for
    # the old loop). The mask starts on segment 3 861 — the first tail
    # clearing the entropy floor once the trailing sample weighs in — pinned
    # so a heuristic shift has to argue with this test.
    text = "/".join(["8SKDsHj+ePj"] * 4000) + "/q3QCEgcaHD6honHxcM="
    cleaned, found = redact(text)
    assert cleaned == "/".join(["8SKDsHj+ePj"] * 3861) + "/" + REDACTED
    assert found == ["high_entropy"]

    # The ceiling is relative, not a wall-clock bound alone that a slow CI runner could trip:
    # four times the segments must cost about four times as long (the old quadratic loop cost
    # 13 to 16 times as much). Best of several runs, so one scheduling hiccup does not decide.
    # Under heavy CPU load the larger run is almost always preempted while the smaller one fits
    # a scheduler quantum, which inflates the ratio of a linear scan; a generous absolute
    # ceiling therefore also lets it through (the quadratic loop takes 2.4 s or more).
    def best_of(parts, runs=5):
        sample = "/".join(["8SKDsHj+ePj"] * parts) + "/q3QCEgcaHD6honHxcM="
        times = []
        for _ in range(runs):
            started = time.perf_counter()
            redact(sample)
            times.append(time.perf_counter() - started)
        return min(times)

    small, large = best_of(1000), best_of(4000)
    assert large < 9 * max(small, 0.002) or large < 0.5, (small, large)


@pytest.mark.parametrize(
    "chaine",
    [
        # A short segment on either side of the single slash.
        "k1l2=/" + "K1N7xP+9mQ" + "2vL8jR3tY6" + "wA0bC4dE5f" + "G7h8i9j0",
        "K1N7xP+9mQ" + "2vL8jR3tY6" + "wA0bC4dE5f" + "G7h8i9j0" + "/k1l2=",
        # Unequal sides, no segment reaching the old 40-character key length.
        "1a2b3c4d5e6f" + "7g8h9i0j1" + "/K1N7xP9mQ2vL" + "8jR3tY6wA=",
    ],
)
def test_slashed_values_sided_by_a_short_segment_are_masked_whole(chaine):
    # Antigravity review on c73aee9: a value split by ONE slash with a short
    # segment beside it (`k1l2=/…`, `…/k1l2=`, 21/22 characters) leaked partly
    # or whole — the guard reads the chunks, it does not count full-length
    # segments.
    cleaned, found = redact(f"cle {chaine} ici")
    assert cleaned == f"cle {REDACTED} ici"
    assert found == ["high_entropy"]


def test_slashed_keys_from_24_to_39_characters_are_masked_whole():
    # Antigravity review on c73aee9: the 40-character floor let 24-to-39
    # character slashed keys stay in the clear (the flat floor is 24 too).
    for chaine in (
        "A1b2C3d4E5f6" + "/K1l2M3n4O5p6",
        "A1b2C3d4E5f6" + "G7h8I9j" + "/K1l2M3n4O5p6" + "Q7r8S9t",
    ):
        cleaned, found = redact(f"jeton {chaine} reçu")
        assert cleaned == f"jeton {REDACTED} reçu"
        assert found == ["high_entropy"]


def test_slashed_key_with_a_short_boundary_segment_is_masked_whole():
    # Antigravity review on d2361cc (F1): a single-slash key whose body
    # touches a one-or-two character segment could never bring two blobs
    # together and the flat floor stayed out of reach — all three shapes
    # leaked whole. A short boundary segment is now read as what it is: a
    # chopped piece, not a chunk that has to pass a blob test.
    for chaine in (
        "A/1b2C3d4E5f6" + "K1l2M3n4O5p6",
        "A1b/2C3d4E5f6" + "K1l2M3n4O5p6",
        "A1b2C3d4E5f6" + "K1l2M3n4O5/p6",
    ):
        cleaned, found = redact(f"cle {chaine} ici")
        assert cleaned == f"cle {REDACTED} ici"
        assert found == ["high_entropy"]


def test_slashed_key_sided_by_one_character_segments_is_masked_whole():
    # Antigravity review on d2361cc (F1): `A/F6g7…` kept its head and
    # `A/F6g7…/B` both boundary letters in the clear — a one-character
    # segment can never be a blob, so the single-body shapes fell out of the
    # two-blob rule.
    for chaine in (
        "A/" + "F6g7H8i9J0k1L2m3N4" + "O5p6Q7r8S9t0U1v2W3",
        "A/" + "F6g7H8i9J0k1L2m3N4" + "O5p6Q7r8S9t0" + "/B",
    ):
        cleaned, found = redact(f"cle {chaine} ici")
        assert cleaned == f"cle {REDACTED} ici"
        assert found == ["high_entropy"]


def test_real_cryptographic_key_with_a_slash_is_masked_whole():
    # Antigravity review on d2361cc (F1): the exact key of the report — a
    # uniform 32-byte base64 draw — leaked its head (`OLTmUuRNp/` in the
    # clear) before the whole-value signals replaced the per-chunk test.
    chaine = "OLTmUuRNp/" + "I3DZ4mDicTZVCko6bQf1wMMy+LEiQIP9I="
    cleaned, found = redact(f"cle {chaine} ici")
    assert cleaned == f"cle {REDACTED} ici"
    assert found == ["high_entropy"]


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (
            "payload=" + "A1b2C3d4E5f6/K1l2M3n4O5p6 ok",
            "payload=" + REDACTED + " ok",
        ),
        (
            "https://example.com/oauth?payload=" + "A1b2C3d4E5f6/K1l2M3n4O5p6 ok",
            "https://example.com/oauth?payload=" + REDACTED + " ok",
        ),
        (
            "param=k1l2=/" + "K1N7xP+9mQ2vL8jR3tY6" + "wA0bC4dE5fG7h8i9j0 ok",
            "param=" + REDACTED + " ok",
        ),
    ],
)
def test_slashed_value_glued_behind_an_equals_sign_is_masked_whole(text, expected):
    # Antigravity review on d2361cc (F2): with `=` in the lookbehind the
    # engine could not start after the sign — the first two shapes leaked
    # whole and the third kept its short head (`k1l2=/`) in the clear.
    # Base64 padding only ever CLOSES a segment.
    cleaned, found = redact(text)
    assert cleaned == expected
    assert found == ["high_entropy"]


def test_random_32_byte_keys_with_a_slash_are_masked_whole():
    # Antigravity review on d2361cc (F1 and F5): real 32-byte base64 keys
    # holding a `/` leaked 16.1 % whole and 70.5 % partly on a 5 000-key draw
    # of the report; the whole-value signals leave 2.1 % whole and 11.3 %
    # partly on a 3 000-key draw of the same shape. The sample below comes
    # from a fixed seed, so its outcome is stable: the measured coverage
    # (92 of 100) is pinned as a floor, and the residual stays the documented
    # limit of a boundary-free value (#84).
    rng = random.Random(20261018)
    keys = []
    while len(keys) < 100:
        key = base64.b64encode(bytes(rng.getrandbits(8) for _ in range(32))).decode()
        if "/" in key:
            keys.append(key)
    masked = sum(
        1 for key in keys if redact(f"cle {key} ici")[0] == f"cle {REDACTED} ici"
    )
    assert masked >= 92


def test_slashed_run_under_the_length_floor_stays_untouched():
    # 23 characters: under the slashed and flat floors alike, no candidate.
    text = "cle A1b2C3d4E5f6/K1l2M3n4O5 fin"
    assert redact(text) == (text, [])
