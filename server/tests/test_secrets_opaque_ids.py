"""Opaque runs against generated identifiers (issue #101).

The entropy pass masks a candidate when its material — what is left once
timestamps, UUIDs, ULIDs and names are set aside — could hold a 128-bit secret,
however the value is chopped. Secrets are assembled at runtime from short pieces
or drawn from a seeded generator; nothing here is a real credential.
"""

import base64
import random
import string
import time

import pytest

from nexus.secrets import REDACTED, redact

B62 = string.ascii_letters + string.digits
HEX = "0123456789abcdef"
NANOID = "useandom-26T198340PX75pxJACKVERYMINDBUSHWOLF_GQZbfghjklqvwyzrict"


def _draw(rng, alphabet, size):
    return "".join(rng.choice(alphabet) for _ in range(size))


def _urlsafe(rng, nbytes):
    raw = rng.getrandbits(8 * nbytes).to_bytes(nbytes, "big")
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def _masked(value):
    cleaned, _ = redact(f"valeur {value} fin")
    return value not in cleaned


@pytest.mark.parametrize(
    "identifiant",
    [
        # issue #101: a head of eight characters or more
        "workflow_20261018143022_4f3a9b2c",
        "pipeline_1729260000123_4f3a9b2c",
        "deployment-20261018143022-4f3a9b2c",
        # issue #101: the « flat run >= 24 » rule
        "evt_3f2b8c1e9a7d4f6b8c2e1a9d7b5f3c1e",  # UUID v4, 32 hex digits
        "evt_01m57pqe1g7wnrr7mtfn7pq31e",  # ULID, lowercase
        "01M57PQE1G7WNRR7MTFN7PQ31E",  # ULID, canonical
        "evt_V1StGXR8_Z5jdHi6B-myT",  # nanoid21
        "evt_20261018143022_4f3a9b2c1d7e8f90a1b2c3d4",
        "evt_handleCustomerAccountDeletionRequest2026",
        "fetchUserProfileSettingsDashboardV2",
        # other generated shapes
        "evt_01a14f6bb8307a3c9f1e2d3c4b5a6978",  # UUID v7, 32 hex digits
        "evt-3686f22a-1ac5-4c8a-9d5b-8f29c2f21e90",
        "evt_652f1c9e8b3a4d0012ab34cd",  # ObjectId, 96 bits
        "evt_tz4a98xxat96iws9zmbrgj3a",  # cuid2, 124 bits
        "job_20261018T143022Z_4f3a9b2c1d7e8f90a1b2c3d4",
        "trace_1729260000123456_4f3a9b2c1d7e8f90a1b2c3d4",  # epoch in microseconds
    ],
)
def test_generated_identifiers_stay_untouched(identifiant):
    # The API refused these with a 409 (`secret_in_event_id`, `secret_in_run_ref`):
    # their random part stays under 128 bits once the timestamp, UUID, ULID or
    # name is set aside.
    assert redact(identifiant) == (identifiant, [])


@pytest.mark.parametrize(
    "chaine",
    [
        "NRJS-" + "4f3a9b2c1d7e8f90a1b",
        "sgp_" + "4f3a9b2c1d7e8f90" + "_" + "a1b2c3d4e5f60718293a" + "4b5c6d7e8f9012345678",
        "sgp_local_" + "a1b2c3d4e5f60718293a" + "4b5c6d7e8f9012345678",
    ],
)
def test_named_formats_under_the_entropy_floor_are_masked(chaine):
    # New Relic (76 bits) sits under the 128-bit floor: only its format catches
    # it. Sourcegraph is caught by both; the format names it.
    cleaned, found = redact(f"cle {chaine} ici")
    assert cleaned == f"cle {REDACTED} ici"
    assert len(found) == 1 and found[0] in {"newrelic_key", "sourcegraph_token"}


@pytest.mark.parametrize(
    "chaine",
    [
        # A short segment between opaque ones no longer hides the value (#84 assumed it did).
        "sk_live_" + "Y7qP2rTx_N9vH4mKu" + "_C6wJ8sZa_R5dE3fGh",
        # 4 × hex8 = 128 bits, whatever the chopping (#99 assumed it was an id).
        "key_" + "4f3a9b2c_1d7e8f90" + "_a1b2c3d4_e5f60718",
        # A hex segment that drew no letter is still hex (8 × 4 bits, not 8 × 3.3).
        "key_" + "30882887_4f3a9b2c" + "_a1b2c3d4_e5f60718",
        # A 12-digit run is no timestamp: it stays material (#99 cost).
        "acct-" + "482910375562" + "-" + "Y7qP2rTxN9vH4mKu",
        # A date that does not exist is no timestamp either.
        "evt_" + "20261318143022" + "_" + "4f3a9b2c1d7e8f90a1b2c3d4",
        # An epoch past 2100 neither.
        "evt_" + "9999999999999" + "_" + "4f3a9b2c1d7e8f90a1b2c3d4",
    ],
)
def test_chopped_values_of_128_bits_are_masked(chaine):
    cleaned, found = redact(f"cle {chaine} ici")
    assert cleaned == f"cle {REDACTED} ici"
    assert found == ["high_entropy"]


def test_the_floor_is_128_bits_of_material():
    # 32 hex digits (128 bits) are masked, 31 (124) are not; 22 base62
    # characters (131 bits) are masked, 21 (125, a nanoid) are not.
    hex32 = "4f3a9b2c1d7e" + "8f90a1b2c3d4e5f60718"
    assert _masked("key-" + hex32)
    assert redact("key-" + hex32[:31]) == ("key-" + hex32[:31], [])
    b62 = "Y7qP2rTxN9v" + "H4mKuC6wJ8s"
    assert _masked("tok_" + b62)
    assert redact("tok_" + b62[:21]) == ("tok_" + b62[:21], [])


def test_repeated_material_is_not_opaque():
    # Long enough on paper (k × n), but nowhere near the entropy of a draw.
    for text in ("evt_" + "ab12" * 12, "run_" + "0" * 40 + "a1", "id_" + "Aa1" * 16):
        assert redact(text) == (text, []), text


@pytest.mark.parametrize(
    ("chaine", "masque"),
    [
        # Same shape as a `key_<hex16>_<hex16>`: 128 bits of hex, masked.
        ("span_" + "4f3a9b2c1d7e8f90" + "_a1b2c3d4e5f60718", True),
        # A hex32 key shaped like a UUID v4 (one draw in 64) reads as an id.
        ("key-" + "4f3a9b2c1d7e" + "4f6b8c2e1a9d7b5f3c1e", False),
        # An unknown 103-bit format with no known prefix stays in the clear.
        ("LIC-" + "Q7ZK2M9XRT" + "4WB8NC3VJ5", False),
        # A camelCase name with digits inside its words is material (master masked it too).
        ("evt_handleOAuth2Callback" + "ForS3BucketUpload", True),
    ],
)
def test_assumed_trade_offs_are_pinned(chaine, masque):
    # Prices of the 128-bit rule (issue #101), pinned so a later change has to
    # argue with this test.
    assert _masked(chaine) is masque


@pytest.mark.parametrize(
    ("famille", "plancher"),
    [
        (lambda rng: _urlsafe(rng, 32), 297),
        (lambda rng: _urlsafe(rng, 24), 290),
        (lambda rng: _draw(rng, HEX, 32), 290),
        (lambda rng: _draw(rng, HEX, 40), 300),
        (lambda rng: "tok_" + "_".join(_draw(rng, B62, 8) for _ in range(4)), 285),
        (lambda rng: "key_" + "_".join(_draw(rng, B62, 12) for _ in range(2)), 270),
        (lambda rng: "acct-" + _draw(rng, string.digits, 12) + "-" + _draw(rng, B62, 16), 290),
    ],
    ids=["urlsafe32", "urlsafe24", "hex32", "hex40", "tok_b62_8x4", "key_b62_12x2", "acct"],
)
def test_random_secret_families_are_masked(famille, plancher):
    # 300 seeded draws per family; the floor sits a few draws under the rate
    # measured on 1 000 draws (issue #101), so a regression shows.
    rng = random.Random(101)
    assert sum(_masked(famille(rng)) for _ in range(300)) >= plancher


@pytest.mark.parametrize(
    "famille",
    [
        lambda rng: f"workflow_2026{rng.randint(1, 12):02d}{rng.randint(1, 28):02d}"
        f"{rng.randint(0, 23):02d}{rng.randint(0, 59):02d}00_{_draw(rng, HEX, 8)}",
        lambda rng: f"pipeline_{rng.randint(1_700_000_000_000, 1_900_000_000_000)}_"
        f"{_draw(rng, HEX, 8)}",
        lambda rng: f"evt_2026{rng.randint(1, 12):02d}{rng.randint(1, 28):02d}"
        f"143022_{_draw(rng, HEX, 24)}",
        lambda rng: "evt_" + _draw(rng, NANOID, 21),
        lambda rng: "evt_" + _draw(rng, string.ascii_lowercase + string.digits, 24),
    ],
    ids=["workflow_ts14_hex8", "pipeline_epoch_ms_hex8", "evt_ts14_hex24", "nanoid21", "b36_24"],
)
def test_random_generated_identifier_families_stay_untouched(famille):
    rng = random.Random(101)
    for _ in range(300):
        identifiant = famille(rng)
        assert redact(identifiant) == (identifiant, []), identifiant


@pytest.mark.parametrize(
    "text",
    [
        "_".join(["Y7qP2"] * 66_000),  # one 400 KB candidate, many segments
        "_".join(["20261018"] * 44_000) + "_a1",  # many timestamp checks
        "a" * 399_998 + "b1",  # one name segment
        " ".join(["Y7qP2rTxN9vH4mKuC6wJ8sZa"] * 16_000),  # many 24-character candidates
    ],
    ids=["chopped", "timestamps", "name", "candidates"],
)
def test_opaque_rule_stays_linear(text):
    # A comment body has no length bound (`CommentIn.body`): the ceiling catches
    # a quadratic or exponential return (a quarter of a second at worst now).
    started = time.perf_counter()
    redact(text)
    assert time.perf_counter() - started < 1.0
