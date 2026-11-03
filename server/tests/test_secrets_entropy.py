"""Identifiants générés, préfixes de fournisseurs et seuils d'entropie du scanner (ADR-006)."""

import pytest

from nexus.secrets import REDACTED, redact


def test_uuid_like_dash_groups_stay_untouched():
    # A candidate that spans dashes stays an identifier at the 4-character
    # UUID groups; guarded despite the class change (documented criterion).
    text = "référence 3686f22a-1ac5-4c8a-9d5b-8f29c2f21e90 créée"
    assert redact(text) == (text, [])


def test_snake_case_identifier_stays_untouched():
    # A plausible identifier (short segment « access ») is not opaque even
    # above the entropy threshold; guarded despite the class change.
    text = "recharger un authorize_access_request_center lent"
    assert redact(text) == (text, [])


def test_short_prefixed_opaque_token_is_masked_whole():
    # A short vendor prefix does not break the token (CodeRabbit finding on
    # 341a639): the flat 24+ run behind it makes the whole candidate opaque,
    # prefix included — the token without its prefix would already be masked.
    cleaned, found = redact("portail tok_Y7qP2rTxN9vH4mKuC6wJ8sZaR5dE3fGh actif")
    assert cleaned == f"portail {REDACTED} actif"
    assert found == ["high_entropy"]


def test_short_vendor_prefix_with_full_segments_is_masked_whole():
    # issue #84, second disposition: a short prefix is accepted at the head when
    # EVERY following segment is full length (≥ 8) — the vendor token that holds
    # no flat 24+ run is protected.
    cleaned, found = redact("portail tok_Y7qP2rTx_N9vH4mKu_C6wJ8sZa_R5dE3fGh actif")
    assert cleaned == f"portail {REDACTED} actif"
    assert found == ["high_entropy"]


def test_real_vendor_key_shape_is_masked_by_the_flat_rule():
    # Closing assumption of the second disposition (Antigravity review on
    # 6d78a6c, set-aside finding): a real vendor key is `sk_live_` followed by
    # ONE continuous run — the flat 24+ rule masks the whole value, prefix
    # included. Assembled at runtime from short pieces.
    chaine = "sk_live_" + "51H8xYzAbCdEfGhIj" + "KlMnOpQrStUvWxYz" + "0123456789AbCdEfGh" + "IjKlMn"
    cleaned, found = redact(f"cle {chaine} ici")
    assert cleaned == f"cle {REDACTED} ici"
    assert found == ["high_entropy"]


def test_interleaved_short_vendor_segments_are_masked():
    # Same review, the other half of the finding: a value that interleaves a
    # SHORT segment (`live`, `v1`) between opaque ones was left out of reach on
    # purpose, to keep identifiers safe. Issue #101 adds a rule on the
    # material: the 32 base62 characters around `live` hold 190 bits and the
    # value is masked, while the identifiers of
    # test_identifier_with_one_short_head_… stay names.
    text = "sk_live_" + "Y7qP2rTx_N9vH4mKu" + "_C6wJ8sZa_R5dE3fGh"
    cleaned, found = redact(f"cle {text} ici")
    assert cleaned == f"cle {REDACTED} ici"
    assert found == ["high_entropy"]


def test_identifier_with_two_short_segments_stays_untouched():
    # Counter-example of the same disposition (#84): `String` (6) is a SECOND
    # short segment — the ordinary identifier keeps its old verdict.
    text = "get_Database_Connection_String"
    assert redact(text) == (text, [])


@pytest.mark.parametrize(
    "text",
    [
        "get_database_connection1",
        "set_Database_Connection1",
        "id-utilisateur-authentification1",
        "dans l-amendement2-constitutionnel on voit",
    ],
)
def test_identifier_with_one_short_head_and_plain_tail_stays_untouched(text):
    # Antigravity review on 6d78a6c (second disposition): full length alone did
    # not protect a snake_case tail of plain words — every segment behind the
    # short head must carry a digit too, so only generated-looking tails pass.
    assert redact(text) == (text, [])


@pytest.mark.parametrize(
    "identifiant",
    [
        "v1_userprofile2_accountsettings3",
        "id_transaction2026_confirmation2026",
        "db_connectionpool1_maxconnections2",
        "app_configuration2026_environment2026",
        "job_dataprocessing2026_batchworker2",
    ],
)
def test_identifier_with_digit_bearing_word_tails_stays_untouched(identifiant):
    # Antigravity review on d2361cc (F4): a digit-bearing tail of eight
    # characters or more passed on length alone, so a word with an index
    # (`userprofile2`) made the whole identifier opaque — five cases masked, a
    # regression against master. The tail must not read as a word either
    # (`tok_Y7qP2rTx_…`, whose tails hold no lowercase run, still passes).
    text = f"clé {identifiant} notée"
    assert redact(text) == (text, [])


@pytest.mark.parametrize(
    "identifiant",
    [
        "evt_20261018143022_a1b2c3d4",
        "run_1729260000123_4f3a9b2c",
        "evt_1729260000_a1b2c3d4e5f6",
        "job_20261018_4f3a9b2c1d7e",
        "build_20261018123456_ab12cd34",
        "helios_20261018143022_9f8e7d6c",
        "pr87_c532761947a5_f745827e",
        "evt_20260928_helios_0007",
        "evt_20261018143022_A1B2C3D4",
        "run-1729260000123-4f3a9b2c",
        "evt_1729260000123_4f3a9b2c1d7e8f90",
        "span_4f3a9b2c1d7e8f90_a1b2c3d4",
        "ci_20261018_c5327619_f745827e",
        "run_20261018143022_k3x9m2p7q1",
        "evt_k3x9m2p7q1zt_w8v4n6b2c5yr",
        "run_20261018143022_A1B2C3D4E5F6",
        "job_20261018T143022_4f3a9b2c",
    ],
)
def test_generated_identifiers_stay_untouched(identifiant):
    # Issue #93: `prefix_timestamp_hex` identifiers (event ids, run references)
    # drawn from decimal, hexadecimal or base36 alphabets carry no mixed case —
    # the base62 signature of a vendor token tail. They were masked, and the
    # API refused the event with a 409.
    text = f"réf {identifiant} notée"
    assert redact(text) == (text, [])


@pytest.mark.parametrize(
    "chaine",
    [
        "tok-" + "Y7qP2rTx-N9vH4mKu-C6wJ8sZa-R5dE3fGh",
        "key_" + "A7x9QzW2Ry5N" + "_t8Kv4Jm6Pa1C",
        # A real run behind a timestamp prefix stays masked by the flat 24+ rule.
        "evt_20261018143022_" + "A7x9QzW2Ry5Nt8Kv4Jm6Pa1C",
        "key_" + "4f3a9b2c1d7e8f90" + "a1b2c3d4e5f60718",
    ],
)
def test_prefixed_secrets_stay_masked_beside_generated_identifiers(chaine):
    cleaned, found = redact(f"cle {chaine} ici")
    assert cleaned == f"cle {REDACTED} ici"
    assert found == ["high_entropy"]


@pytest.mark.parametrize(
    "chaine",
    [
        # Mailgun-, Shopify- and Postman-shaped keys: a long single-case hex tail whose
        # entropy sits under the flat-run floor (3.3-3.5 bits) was masked by the
        # short-prefix branch on master; reviewer finding on 5df9637 (P1).
        "key-" + "8c291f2fc8b5f208" + "99203fad89d9b0ef",
        "shpat_" + "9a50f8a8e9bb8bdb" + "5eba456bf92d5d98",
        "PMAK-" + "fc2e2894e7af7c49" + "c3e30acb-" + "01ef4faa5f9dc25f" + "d5da5323091acff3ce",
    ],
)
def test_long_hexadecimal_tail_behind_a_short_prefix_stays_masked(chaine):
    cleaned, found = redact(f"cle {chaine} ici")
    assert cleaned == f"cle {REDACTED} ici"
    assert found == ["high_entropy"]


def test_single_case_short_prefixed_segments_stay_untouched_as_assumed():
    # Price of the #93 fix, narrowed by issue #101: a value chopped into
    # single-case segments is also judged on its material, 128 bits at least.
    # Four hex8 segments hold 128 bits and are now masked (test_secrets_additions);
    # two base36 segments of 12 hold 124 bits, the shape of a generated
    # identifier (`evt_<b36_12>_<b36_12>`), and stay. Pinned so a later
    # widening has to argue with this test.
    text = "cle key_k3x9m2p7q1zt_w8v4n6b2c5yr ici"
    assert redact(text) == (text, [])


def test_title_case_slug_with_short_word_stays_untouched():
    # A candidate with one short segment is only opaque when a flat 24+ run
    # hides behind it; title-case words (3.545 bits joined) have none.
    text = "cap sur « Dictionnaire-des_Expressions_Francaises » à lire"
    assert redact(text) == (text, [])
