"""Generated identifiers the entropy pass leaves alone (issue #101, PR B).

The exemption is a closed grammar over the whole candidate (`_generated_identifier`);
everything outside it keeps master's verdict. Secrets are assembled at runtime from
short pieces or drawn from a seeded generator; nothing here is a real credential.
"""

import datetime as dt
import random
import string

import pytest

from nexus.secrets import REDACTED, redact

B62 = string.ascii_letters + string.digits
HEX = "0123456789abcdef"
CROCKFORD = "0123456789abcdefghjkmnpqrstvwxyz"
HEX24 = "4f3a9b2c1d7e" + "8f90a1b2c3d4"
UUID4 = "3f2b8c1e9a7d" + "4f6b8c2e1a9d7b5f3c1e"


def _draw(rng, alphabet, size):
    return "".join(rng.choice(alphabet) for _ in range(size))


def _when(rng):
    start = dt.datetime(2024, 1, 1, tzinfo=dt.UTC)
    return start + dt.timedelta(seconds=rng.randrange(4 * 365 * 86400))


def _uuid4hex(rng):
    raw = bytearray(rng.getrandbits(128).to_bytes(16, "big"))
    raw[6] = (raw[6] & 0x0F) | 0x40
    raw[8] = (raw[8] & 0x3F) | 0x80
    return raw.hex()


def _ulid(rng):
    value = (int(_when(rng).timestamp() * 1000) << 80) | rng.getrandbits(80)
    return "".join(CROCKFORD[(value >> (5 * shift)) & 31] for shift in range(25, -1, -1))


@pytest.mark.parametrize(
    "identifiant",
    [
        "workflow_20261018143022_4f3a9b2c",
        "pipeline_1729260000123_4f3a9b2c",
        "deployment-20261018143022-4f3a9b2c",
        "evt_" + UUID4,
        "evt_01m57pqe1g7wnrr7mtfn7pq31e",
        "orderId_" + UUID4,
        "evt_20261018143022_" + HEX24,
        "job_20261018T143022Z_" + HEX24,
        "evt_20261018143022_" + UUID4,
        "evt_handleCustomerAccountDeletionRequest2026",
        "fetchUserProfileSettingsDashboardV2",
        "processInvoicePaymentSubscriptionHandler_1729260000123",
    ],
)
def test_generated_identifiers_stay_untouched(identifiant):
    assert redact(identifiant) == (identifiant, [])


@pytest.mark.parametrize(
    "famille",
    [
        lambda rng: f"workflow_{_when(rng):%Y%m%d%H%M%S}_{_draw(rng, HEX, 8)}",
        lambda rng: f"pipeline_{int(_when(rng).timestamp() * 1000)}_{_draw(rng, HEX, 8)}",
        lambda rng: f"deployment-{_when(rng):%Y%m%d%H%M%S}-{_draw(rng, HEX, 8)}",
        lambda rng: "evt_" + _uuid4hex(rng),
        lambda rng: "evt_" + _ulid(rng),
        lambda rng: f"evt_{_when(rng):%Y%m%d%H%M%S}_{_draw(rng, HEX, 24)}",
    ],
    ids=["workflow", "pipeline", "deployment", "evt_uuid4hex", "evt_ulid", "evt_ts14_hex24"],
)
def test_random_generated_identifier_families_stay_untouched(famille):
    rng = random.Random(101)
    for _ in range(300):
        identifiant = famille(rng)
        assert redact(identifiant) == (identifiant, []), identifiant


@pytest.mark.parametrize(
    "chaine",
    [
        # A label glued to its value, a base64 sign: never exempt.
        "SIGNING_KEY=" + HEX24,
        "evt_20261018143022+" + HEX24,
        # A word that names a credential, alone or inside a name.
        "api-" + HEX24,
        "access_20261018143022_" + HEX24,
        "signing_20261018143022_" + HEX24,
        "refreshToken_20261018143022_" + HEX24,
        # A UUID-shaped hex32 behind a word that is not the noun of an id.
        "shpat_" + UUID4,
        # A hex tail with no timestamp before it, or longer than 24 digits.
        "vendor_" + HEX24 + "a1b2c3d4",
        "evt_20261018143022_" + HEX24 + "a1b2c3d4",
        # A shuffled draw is not a word.
        "SNcveshQ_20261018143022_" + HEX24,
        # Random capitals, a hex run of 26 read as a ULID, a 16-digit epoch.
        "ZRUiUagkoa_20261018143022_" + HEX24,
        "workflow_03bc889eaa1616ba50" + "25630567",
        "deployment-2379484371540249-" + HEX24,
        # An empty segment breaks the grammar.
        "evt__20261018143022_" + HEX24,
    ],
)
def test_shapes_outside_the_grammar_keep_masters_verdict(chaine):
    cleaned, found = redact(f"cle {chaine} fin")
    assert cleaned == f"cle {REDACTED} fin"
    assert found == ["high_entropy"]


@pytest.mark.parametrize(
    "chaine",
    [
        "evt_V1StGXR8xZ5jdHi6BmyTq",  # nanoid21: a random draw, not provable
        "evt_652f1c9e8b3a4d0012ab34cd",  # ObjectId: hex24 with no timestamp before
        "01M57PQE1G7WNRR7MTFN7PQ31E",  # bare ULID: no noun of an id
    ],
)
def test_unprovable_identifiers_keep_masters_verdict_as_assumed(chaine):
    # Residuals of #101: these shapes cannot be told from a random secret by
    # their structure, so master's rule decides (« dans le doute on masque »).
    assert redact(chaine) != (chaine, [])


@pytest.mark.parametrize(
    ("famille", "plancher"),
    [
        (lambda rng: "-".join(_draw(rng, B62, 8) for _ in range(3)), 296),
        (lambda rng: "_".join(_draw(rng, B62, 12) for _ in range(2)), 296),
        (lambda rng: "shpat_" + _draw(rng, HEX, 32), 298),
        (lambda rng: "evt_" + _draw(rng, B62, 24), 296),
    ],
    ids=["b62_8x3", "b62_12x2", "shpat_hex32", "evt_b62_24"],
)
def test_random_secrets_are_not_exempted(famille, plancher):
    # The grammar never exempts a random draw: these families keep master's rate.
    rng = random.Random(101)
    hits = 0
    for _ in range(300):
        value = famille(rng)
        hits += value not in redact(f"valeur {value} fin")[0]
    assert hits >= plancher
