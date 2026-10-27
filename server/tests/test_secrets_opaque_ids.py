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
    # Behind an identifier's name, 32 hex digits (128 bits) are masked and 31
    # (124) are not; 22 base62 characters (131 bits) are masked, 21 (125, a
    # nanoid) are not. A prefix that names a credential (`key`, `tok`) never
    # protects a short body (amendment 1).
    hex32 = "4f3a9b2c1d7e" + "8f90a1b2c3d4e5f60718"
    assert _masked("evt-" + hex32)
    assert redact("evt-" + hex32[:31]) == ("evt-" + hex32[:31], [])
    b62 = "Y7qP2rTxN9v" + "H4mKuC6wJ8s"
    assert _masked("evt_" + b62)
    assert redact("evt_" + b62[:21]) == ("evt_" + b62[:21], [])


def test_repeated_material_is_not_opaque():
    # Long enough on paper (k × n), but nowhere near the entropy of a draw.
    for text in ("evt_" + "ab12" * 12, "run_" + "0" * 40 + "a1", "id_" + "Aa1" * 16):
        assert redact(text) == (text, []), text


@pytest.mark.parametrize(
    ("chaine", "masque"),
    [
        # Same shape as a `key_<hex16>_<hex16>`: 128 bits of hex, masked.
        ("span_" + "4f3a9b2c1d7e8f90" + "_a1b2c3d4e5f60718", True),
        # A hex32 value shaped like a UUID v4 (one draw in 64) reads as an id.
        ("4f3a9b2c1d7e" + "4f6b8c2e1a9d7b5f3c1e", False),
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


# --- Amendment 1 (review of PR #127) --------------------------------------------
# The material rule alone left values master masked in the clear. Every candidate
# that is not a recognised generated identifier now also goes through master's
# rule; the cases below were each a regression of the first version.

HEX32 = "8c291f2fc8b5f208" + "99203fad89d9b0ef"
HEX64 = "4f3a9b2c1d7e8f90a1b2c3d4e5f60718" + "293a4b5c6d7e8f9012345678abcdef01"
B62_20 = "z8lYBSDOgt" + "TvahBSA3tx"


@pytest.mark.parametrize(
    "text",
    [
        f"https://cdn.example.com/a.png?exp=1729260000&sig={HEX64}",
        f"X-Hub-Signature-256: sha256={HEX64}",
        f"digest={HEX64}",
        f"DD_APP={HEX32}5e7a1c3d",
        f"GET https://api.example.com/v1/items?k={HEX32}&page=2",
        f"cle {HEX32}= fin",
        f"ref x+{HEX32} fin",
        f"pk 0x{HEX64} fin",
        f"sid SK{HEX32} fin",
    ],
    ids=["sig", "sha256", "digest", "DD_APP", "query", "padding", "plus", "0x", "SK"],
)
def test_hex_glued_to_a_sign_or_a_short_head_is_masked(text):
    # `=` and `+` belong to the candidate class: `sig=<hex64>` was one segment
    # whose alphabet was no longer hex, and the uniform-draw gate refused it.
    cleaned, found = redact(text)
    assert HEX32[:16] not in cleaned and HEX64[:16] not in cleaned
    assert found == ["high_entropy"]


@pytest.mark.parametrize(
    ("chaine", "kind"),
    [
        ("glpat-" + B62_20, "gitlab_token"),
        ("glrt-" + B62_20, "gitlab_token"),
        ("motpasseglpat-" + B62_20, "gitlab_token"),  # glued to a word
        ("dapi" + HEX32, "databricks_token"),
        ("#fragNRJS-" + HEX32[:19], "newrelic_key"),  # glued to a word
    ],
)
def test_vendor_formats_are_masked_even_glued(chaine, kind):
    # GitLab's 20 characters (119 bits) sit under the floor behind a name the
    # rule sets aside; the formats are unanchored like `nxt_`.
    cleaned, found = redact(f"cle {chaine} fin")
    assert B62_20 not in cleaned and HEX32[:19] not in cleaned
    assert kind in found


@pytest.mark.parametrize(
    "chaine",
    [
        "key-" + HEX32[:24],
        "key-" + HEX32[:31],
        "tok_" + B62_20,
        "secret_" + HEX32[:24],
    ],
)
def test_credential_named_prefixes_keep_masking_short_bodies(chaine):
    # A prefix that names a credential never opens the generated-identifier
    # exemption: master masked these and they stay masked.
    cleaned, found = redact(f"cle {chaine} fin")
    assert cleaned == f"cle {REDACTED} fin"
    assert found == ["high_entropy"]


@pytest.mark.parametrize(
    "constante",
    [
        "HTTP2_MAX_CONCURRENT_STREAMS_PER_CONNECTION",
        "AWS_S3_BUCKET_NAME_FOR_NIGHTLY_BACKUPS",
        "NEXUS_DATA_DIR_OVERRIDE_FOR_INTEGRATION_TESTS2",
    ],
)
def test_screaming_snake_constants_stay_untouched(constante):
    # All-capital words hold no lowercase letter: they were all material and
    # 1 147 constants out of 2 000 were masked (refused with a 409 as an id).
    assert redact(constante) == (constante, [])


def test_random_screaming_snake_constants_stay_untouched():
    words = (
        "HTTP2 MAX CONCURRENT STREAMS PER CONNECTION AWS S3 BUCKET NAME FOR NIGHTLY "
        "BACKUPS NEXUS DATA DIR OVERRIDE TESTS DEFAULT TIMEOUT RETRY LIMIT OAUTH2 "
        "CLIENT REDIS POOL SIZE V2 API BASE URL LOG LEVEL FEATURE FLAG WORKER COUNT"
    ).split()
    rng = random.Random(101)
    for _ in range(300):
        name = "_".join(rng.choice(words) for _ in range(rng.randint(3, 7))) + "_V2"
        assert redact(name) == (name, []), name


@pytest.mark.parametrize(
    ("famille", "plancher"),
    [
        (lambda rng: _draw(rng, HEX, 24), 140),
        (lambda rng: _draw(rng, HEX.upper(), 24), 140),
        (lambda rng: _draw(rng, string.ascii_lowercase + string.digits, 24), 292),
        (lambda rng: "tok_" + _urlsafe(rng, 16), 250),
    ],
    ids=["hex24", "HEX24", "b36_24", "tok_urlsafe16"],
)
def test_bare_and_short_values_keep_master_masking(famille, plancher):
    # Values with no recognised structure keep master's rule: a bare 24-character
    # hex or base36 value under 128 bits is still masked as before.
    rng = random.Random(101)
    assert sum(_masked(famille(rng)) for _ in range(300)) >= plancher


@pytest.mark.parametrize(
    ("chaine", "masque"),
    [
        # An unknown word in front of under 128 bits reads like `evt_<hex24>`.
        ("vendor_" + HEX32[:24], False),
        ("deployment-" + HEX32[:31], False),
    ],
)
def test_amendment_trade_offs_are_pinned(chaine, masque):
    assert _masked(chaine) is masque


@pytest.mark.parametrize(("slash", "plafond"), [(False, 0), (True, 1)])
def test_redaction_is_idempotent_on_a_fixed_seed(slash, plafond):
    # 4 000 seeded inputs built from labels, quotes, URLs, prefixes and random
    # runs. Without `/`, redact is idempotent; with `/`, one input fails on this
    # seed, on master as on this branch (the slashed pass, issue #126).
    fragments = [
        "password", "token", "api_key", "mot de passe", "Authorization: ", ":", "=", " ",
        "\n", '"', "'", "\\", ",", ";", "{", "}", "[", "]", "_", "-", ".", "@", "#", "?",
        "+", "[REDACTED]", "https://", "postgres://u:", "evt_", "tok_", "key-", "sk_live_",
        "NRJS-", "glpat-", "dapi", "0x", "sha256=", "20261018143022", "1729260000123",
        "3686f22a-1ac5-4c8a-9d5b-8f29c2f21e90", "getUserById", "HTTP2_MAX", "userprofile2",
    ]
    if slash:
        fragments += ["/", "/api/v1/", "C:/Users/x/", "/var/lib/", "?q=", "/tokens/"]
    alphabets = [B62, HEX, HEX.upper(), B62 + "-_", B62 + "+="] + ([B62 + "+/="] if slash else [])
    rng = random.Random(f"idempotence:101:{slash}")
    failures = 0
    for _ in range(4000):
        parts = []
        for _ in range(rng.randint(1, 8)):
            if rng.random() < 0.5:
                parts.append(rng.choice(fragments))
            else:
                alphabet = rng.choice(alphabets)
                parts.append("".join(rng.choice(alphabet) for _ in range(rng.randint(4, 48))))
        once, _ = redact("".join(parts))
        failures += redact(once)[0] != once
    assert failures <= plafond
