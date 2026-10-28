"""Additions of the entropy pass and vendor formats (issue #101, PR A).

`_opaque_run` keeps master's rule; `_opaque_material` and four vendor formats only
add masks. Secrets are assembled at runtime from short pieces or drawn from a
seeded generator; nothing here is a real credential.
"""

import base64
import random
import re
import string
import time

import pytest

from nexus.secrets import REDACTED, redact

B62 = string.ascii_letters + string.digits
HEX = "0123456789abcdef"
B32 = "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567"
HEX32 = "8c291f2fc8b5f208" + "99203fad89d9b0ef"
HEX64 = "4f3a9b2c1d7e8f90a1b2c3d4e5f60718" + "293a4b5c6d7e8f9012345678abcdef01"
B62_20 = "z8lYBSDOgt" + "TvahBSA3tx"


def _draw(rng, alphabet, size):
    return "".join(rng.choice(alphabet) for _ in range(size))


def _urlsafe(rng, nbytes):
    raw = rng.getrandbits(8 * nbytes).to_bytes(nbytes, "big")
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def _masked(value):
    cleaned, _ = redact(f"valeur {value} fin")
    return value not in cleaned


@pytest.mark.parametrize(
    "text",
    [
        f"https://cdn.example.com/a.png?exp=1729260000&sig={HEX64}",
        f"X-Hub-Signature-256: sha256={HEX64}",
        f"digest={HEX64}",
        f"GET https://api.example.com/v1/items?k={HEX32}&page=2",
        f"cle {HEX32}= fin",
        f"ref x+{HEX32} fin",
        f"pk 0x{HEX64} fin",
        f"export SIGNING_KEY={HEX32[:24]}",
        f"webhook_sig={HEX32[:24]}",
    ],
    ids=["sig", "sha256", "digest", "query", "padding", "plus", "0x", "env-key", "x_sig"],
)
def test_hex_values_glued_to_labels_or_signs_are_masked(text):
    cleaned, found = redact(text)
    assert HEX32[:16] not in cleaned and HEX64[:16] not in cleaned
    assert found == ["high_entropy"]


@pytest.mark.parametrize(
    ("chaine", "kind"),
    [
        ("NRJS-" + HEX32[:19], "newrelic_key"),
        ("#fragNRJS-" + HEX32[:19], "newrelic_key"),
        ("sgp_" + HEX32[:16] + "_" + HEX64[:40], "sourcegraph_token"),
        ("sgp_local_" + HEX64[:40], "sourcegraph_token"),
        ("glpat-" + B62_20, "gitlab_token"),
        ("glrt-" + B62_20, "gitlab_token"),
        ("Xk3p9Qglpat-" + B62_20 + "tail", "gitlab_token"),
        ("glpat-" + B62_20 + "+uv31av8zq" + "E0LUYAl=", "gitlab_token"),  # base64 tail
        ("Xk3p+Q9z" + "glpat-" + B62_20, "gitlab_token"),  # head with a `+`
        ("dapi" + HEX32, "databricks_token"),
        ("dapi" + HEX32 + "-2", "databricks_token"),
    ],
)
def test_vendor_formats_mask_their_whole_run(chaine, kind):
    # The whole run of letters, digits, `-` and `_` goes, glued head included.
    cleaned, found = redact(f"cle {chaine} fin")
    assert REDACTED in cleaned
    assert not any(part in cleaned for part in re.findall(r"[A-Za-z0-9]{8,}", chaine))
    assert found == [kind]


def test_vendor_format_takes_a_glued_label_and_keeps_a_spaced_one():
    # A label glued by `=` belongs to the run, as `digest=<hex>` does on master;
    # a spaced label stays readable.
    cleaned, found = redact("TOKEN=glpat-" + B62_20)
    assert (cleaned, found) == (REDACTED, ["gitlab_token"])
    cleaned, found = redact("TOKEN: glpat-" + B62_20)
    assert cleaned.startswith("TOKEN: ") and B62_20 not in cleaned
    assert "gitlab_token" in found


def test_aws_key_glued_to_a_vendor_format_is_masked_in_one_pass():
    # The vendor formats run before the patterns anchored by a word boundary and
    # take the whole glued run: the AWS key goes with the GitLab token, in one
    # pass (with the formats after `aws_access_key`, the key waited for a second).
    text = "AKIA" + "H72VBEH3WIHBDLRB" + "glpat-" + B62_20
    once, found = redact(text)
    assert once == REDACTED
    assert redact(once)[0] == once
    assert found == ["gitlab_token"]


@pytest.mark.parametrize(
    "chaine",
    [
        "sk_live_" + "Y7qP2rTx_N9vH4mKu" + "_C6wJ8sZa_R5dE3fGh",
        "key_" + "4f3a9b2c_1d7e8f90" + "_a1b2c3d4_e5f60718",
        "key_" + "30882887_4f3a9b2c" + "_a1b2c3d4_e5f60718",
        "acct-" + "482910375562" + "-" + "Y7qP2rTxN9vH4mKu",
        "tok_" + "hlmUnKMI_R5QuKp9B" + "_Drd0hPO6_HhxZ2Ev4",
    ],
)
def test_chopped_random_values_are_added(chaine):
    cleaned, found = redact(f"cle {chaine} ici")
    assert cleaned == f"cle {REDACTED} ici"
    assert found == ["high_entropy"]


@pytest.mark.parametrize(
    ("famille", "plancher"),
    [
        (lambda rng: _urlsafe(rng, 32), 295),
        (lambda rng: _urlsafe(rng, 24), 290),
        (lambda rng: "tok_" + _urlsafe(rng, 16), 250),
        (lambda rng: _draw(rng, HEX, 32), 290),
        (lambda rng: _draw(rng, HEX, 40), 295),
        (lambda rng: "tok_" + "_".join(_draw(rng, B62, 8) for _ in range(4)), 280),
        (lambda rng: "key_" + "_".join(_draw(rng, B62, 12) for _ in range(2)), 270),
        (lambda rng: "acct-" + _draw(rng, string.digits, 12) + "-" + _draw(rng, B62, 16), 290),
        (lambda rng: "-".join(_draw(rng, B32, 8) for _ in range(4)), 295),
        (lambda rng: _draw(rng, HEX, 24), 140),
        (lambda rng: _draw(rng, string.ascii_lowercase + string.digits, 24), 292),
    ],
    ids=["urlsafe32", "urlsafe24", "tok_urlsafe16", "hex32", "hex40", "tok_b62_8x4",
         "key_b62_12x2", "acct", "b32_8x4", "hex24", "b36_24"],
)
def test_random_secret_families_are_masked(famille, plancher):
    # 300 seeded draws per family; the floor sits a few draws under the rate
    # measured with this rule, itself at or above master's on every family.
    rng = random.Random(101)
    assert sum(_masked(famille(rng)) for _ in range(300)) >= plancher


@pytest.mark.parametrize(
    "texte",
    [
        "evt_20261018143022_a1b2c3d4",
        "run_1729260000123_4f3a9b2c",
        "evt_k3x9m2p7q1zt_w8v4n6b2c5yr",
        "span_4f3a9b2c1d7e8f90_a1b2c3d4",
        "HTTP2_MAX_CONCURRENT_STREAMS_PER_CONNECTION",
        "AWS_S3_BUCKET_NAME_FOR_NIGHTLY_BACKUPS",
        "id_transaction2026_confirmation2026",
        "uuid 3686f22a-1ac5-4c8a-9d5b-8f29c2f21e90",
    ],
)
def test_additions_leave_what_master_leaves(texte):
    # Names, timestamps, UUIDs and short hex tails are set aside before the
    # material is measured: under 128 bits, nothing is added.
    assert redact(texte) == (texte, [])


def test_split_hex_of_128_bits_is_masked_as_assumed():
    # Price of the addition: 128 bits of hex are masked whatever their chopping,
    # as a full SHA-1 already is on master.
    assert _masked("span_" + "4f3a9b2c1d7e8f90" + "_a1b2c3d4e5f60718")


@pytest.mark.parametrize(
    "text",
    [
        "gl" * 50_000,
        ("glpat-" + "a" * 10 + "_") * 5_900,
        ("dapi" + "a" * 31 + "g") * 2_800,
        ("NRJS-" + "a" * 18 + "x") * 4_200,
        "_".join(["Y7qP2"] * 16_500),
        "_".join(["20261018"] * 11_000) + "_a1",
        "=".join(["aB3dE5"] * 14_300),
    ],
    ids=["gl", "glpat-short", "dapi-short", "NRJS-short", "chopped", "dates", "eqchain"],
)
def test_additions_stay_linear(text):
    # 100 KB each (a comment body has no length bound): the ceiling catches a
    # quadratic return; the bench of #101 measured the 400 KB versions.
    started = time.perf_counter()
    redact(text)
    assert time.perf_counter() - started < 1.0


@pytest.mark.parametrize(("slash", "plafond"), [(False, 0), (True, 1)])
def test_redaction_is_idempotent_on_a_fixed_seed(slash, plafond):
    # 4 000 seeded inputs built from labels, quotes, URLs, prefixes and random
    # runs. Without `/`, redact is idempotent; with `/`, the failures are those of
    # master on this seed (the slashed pass, issue #126).
    fragments = [
        "password", "token", "api_key", "mot de passe", "Authorization: ", ":", "=", " ",
        "\n", '"', "'", "\\", ",", ";", "{", "}", "[", "]", "_", "-", ".", "@", "#", "?",
        "+", "[REDACTED]", "https://", "postgres://u:", "evt_", "tok_", "key-", "sk_live_",
        "NRJS-", "glpat-", "dapi", "0x", "sha256=", "AKIA", "20261018143022",
        "1729260000123", "3686f22a-1ac5-4c8a-9d5b-8f29c2f21e90", "getUserById",
        "HTTP2_MAX", "userprofile2",
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
