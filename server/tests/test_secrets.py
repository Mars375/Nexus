import base64
import random

import pytest

from nexus.secrets import REDACTED, is_blank_reference, redact, redact_value

# Valeurs factices, construites pour ressembler aux vrais formats — assemblées à l'exécution
# pour que gitleaks ne voie jamais de secret écrit en clair dans le dépôt.
SAMPLES = {
    "api_key": "sk-proj-" + "a1B2c3D4e5F6g7H8i9J0k1L2",
    "github_token": "ghp_" + "A" * 36,
    "aws_access_key": "AKIA" + "ABCDEFGHIJKLMNOP",
    "slack_token": "xoxb-" + "1234567890-abcdefghij",
    "google_api_key": "AIza" + "B" * 35,
    "jwt": ".".join(["eyJhbGciOiJIUzI1NiJ9", "eyJzdWIiOiIxMjM0In0", "c2lnbmF0dXJlLXZhbGV1cg"]),
    "bearer_token": "Bearer " + "x" * 32,
    "private_key": "-----BEGIN RSA PRIVATE KEY-----\nMIIEow\n-----END RSA PRIVATE KEY-----",
}


@pytest.mark.parametrize(("kind", "secret"), SAMPLES.items())
def test_known_formats_are_redacted(kind, secret):
    text, found = redact(f"voici la valeur {secret} à utiliser")

    assert secret not in text
    assert REDACTED in text
    assert kind in found


@pytest.mark.parametrize(
    "text", ["mot de passe : hunter2", "password=hunter2", "token: abc123", "api_key = abc123"]
)
def test_labelled_values_are_masked_but_label_kept(text):
    cleaned, found = redact(text)

    assert "hunter2" not in cleaned and "abc123" not in cleaned
    assert cleaned.endswith(REDACTED)
    assert found == ["credential"]


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ('{"password": "hunter2"}', '{"password": "[REDACTED]"}'),
        ("{'token': 'abc123'}", "{'token': '[REDACTED]'}"),
        ('{"api_key":"abc 123"}', '{"api_key":"[REDACTED]"}'),
        ("secret: hunter2}", "secret: [REDACTED]}"),
        ("AWS_SECRET_ACCESS_KEY=" + "wJalrXUtnFEMIK7MDENG", "AWS_SECRET_ACCESS_KEY=[REDACTED]"),
        ("CLIENT_SECRET=abc123", "CLIENT_SECRET=[REDACTED]"),
        ('{"db.password": "x1"}', '{"db.password": "[REDACTED]"}'),
        ("otp: 123456", "otp: [REDACTED]"),
        (
            "DATABASE_URL=postgresql://alice:hunter2@db.example/nexus",
            "DATABASE_URL=postgresql://alice:[REDACTED]@db.example/nexus",
        ),
        ("2fa_code=123456", "2fa_code=[REDACTED]"),
        ("verification_code=123456", "verification_code=[REDACTED]"),
        ("code de vérification : 123456", "code de vérification : [REDACTED]"),
    ],
)
def test_quoted_credentials_are_masked(text, expected):
    cleaned, found = redact(text)
    assert cleaned == expected
    assert found in (["credential"], ["url_credentials"])


@pytest.mark.parametrize(
    "text",
    [
        '{"password": ""}',
        'token: "[REDACTED]"',
        "tokens: 187012 utilisés",
        "passwords: 3 à changer",
        "Relire la PR #12 et lancer les tests",
        "Le token Google couvre calendar et drive.file",
        "commit:a1b2c3d",
        "https://github.com/Mars375/Nexus/pull/9",
        "mot de passe : [REDACTED]",
    ],
)
def test_normal_text_is_untouched(text):
    assert redact(text) == (text, [])


def test_nested_values_are_redacted():
    value = {"refs": ["ok", "password=hunter2"], "note": "rien"}
    cleaned, found = redact_value(value)

    assert cleaned == {"refs": ["ok", f"password={REDACTED}"], "note": "rien"}
    assert found == ["credential"]


@pytest.mark.parametrize(
    ("text", "blank"),
    [
        (None, True),
        ("", True),
        ("[REDACTED]", True),
        ("password=[REDACTED]", True),
        ("([REDACTED])", True),
        (' token: "[REDACTED]" ', True),
        ("Relancer la PR", False),
        ("voir [REDACTED] puis relancer", False),
        ("utiliser [REDACTED]", False),
    ],
)
def test_is_blank_ignores_redactions_and_their_labels(text, blank):
    from nexus.secrets import is_blank

    assert is_blank(text) is blank


def test_values_under_credential_named_keys_are_masked():
    cleaned, found = redact_value({"password": "hunter2", "tokens": 3000, "note": "rien"})

    assert cleaned == {"password": REDACTED, "tokens": 3000, "note": "rien"}
    assert found == ["credential"]


@pytest.mark.parametrize("value", [["hunter2"], {"value": "abc"}, True, 1234])
def test_any_value_under_a_credential_key_is_masked(value):
    cleaned, found = redact_value({"password": value, "note": "rien"})

    assert cleaned == {"password": REDACTED, "note": "rien"}
    assert found == ["credential"]


@pytest.mark.parametrize("value", [None, "", [], {}])
def test_empty_value_under_a_credential_key_is_left_alone(value):
    assert redact_value({"password": value}) == ({"password": value}, [])


@pytest.mark.parametrize(
    "key",
    ["clientSecret", "refreshToken", "dbPassword", "ClientSecret", "userApiKey", "sessionOtp"],
)
def test_camel_case_credential_keys_are_masked(key):
    cleaned, found = redact_value({key: "hunter2", "note": "rien"})
    assert cleaned == {key: REDACTED, "note": "rien"}
    assert found == ["credential"]


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("clientSecret=hunter2", "clientSecret=[REDACTED]"),
        ('{"refreshToken": "abc123"}', '{"refreshToken": "[REDACTED]"}'),
    ],
)
def test_camel_case_labels_in_text_are_masked(text, expected):
    assert redact(text) == (expected, ["credential"])


@pytest.mark.parametrize("text", ["maxTokens: 3000", '{"maxTokens": 3000}', "tokenizer: bpe"])
def test_camel_case_words_that_are_not_credentials_are_untouched(text):
    assert redact(text) == (text, [])


def test_camel_case_counters_are_not_credential_keys():
    assert redact_value({"maxTokens": 3000}) == ({"maxTokens": 3000}, [])


@pytest.mark.parametrize(
    "key", ["Authorization", "authorization", "Proxy-Authorization", "proxyAuthorization", "Cookie"]
)
def test_http_credential_headers_are_masked_whatever_the_format(key):
    cleaned, found = redact_value({key: "Basic dXNlcjpwYXNz"})
    assert cleaned == {key: REDACTED}
    assert found == ["credential"]


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Authorization: Basic dXNlcjpwYXNz", "Authorization: [REDACTED]"),
        ("Proxy-Authorization: Digest abc123", "Proxy-Authorization: [REDACTED]"),
        ("Cookie: session=abc123", "Cookie: [REDACTED]"),
    ],
)
def test_http_credential_headers_in_text_are_masked(text, expected):
    assert redact(text) == (expected, ["credential"])


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (
            'Authorization: Digest username="Mufasa", realm="test", response="deadbeef"',
            "Authorization: [REDACTED]",
        ),
        ("Cookie: session=abc123; theme=dark; csrf=xyz", "Cookie: [REDACTED]"),
        ("avant\nSet-Cookie: id=a3fWa; Secure\naprès", "avant\nSet-Cookie: [REDACTED]\naprès"),
    ],
)
def test_multi_part_http_credentials_are_masked_whole(text, expected):
    cleaned, found = redact(text)
    assert cleaned == expected
    assert "credential" in found


@pytest.mark.parametrize(
    ("ref", "blank"),
    [
        ("commit: token=[REDACTED]", True),
        ("commit:[REDACTED]", True),
        ("url: [REDACTED]", True),
        ("commit: token=[REDACTED] url:", True),
        ("commit: [REDACTED] note: [REDACTED] url:", True),
        ("commit:a1b2c3d token=[REDACTED]", False),
        ("commit:a1b2c3d", False),
        ("https://github.com/Mars375/Nexus/pull/9", False),
    ],
)
def test_reference_needs_an_identifier_after_redaction(ref, blank):
    assert is_blank_reference(ref) is blank


def test_folded_http_credential_header_is_masked_across_continuation_lines():
    text = 'Authorization: Digest username="u",\n realm="r",\n\tresponse="deadbeef"\nsuite'
    cleaned, found = redact(text)
    assert cleaned == "Authorization: [REDACTED]\nsuite"
    assert "deadbeef" not in cleaned and "credential" in found


@pytest.mark.parametrize(
    "text",
    [
        'Authorization: "Digest username=\\"Mufasa\\", realm=\\"r\\", response=\\"deadbeef\\""',
        '{"Authorization": "Digest username=\\"Mufasa\\", response=\\"deadbeef\\""}',
    ],
)
def test_quoted_http_credential_header_values_are_masked_whole(text):
    cleaned, found = redact(text)
    assert "Mufasa" not in cleaned and "deadbeef" not in cleaned
    assert "credential" in found


def test_tuples_are_scanned_like_lists():
    cleaned, found = redact_value({"metadata": ("token=hunter2", "ok")})
    assert "hunter2" not in str(cleaned)
    assert found == ["credential"]


def test_actor_token_is_redacted_whatever_its_surroundings():
    token = "nxt_" + "A" * 43  # construit à l'exécution
    for text in (f"voici {token} ok", f"x={token}", f"({token})", token + "B" * 5, f"a_{token}"):
        cleaned, found = redact(text)
        assert "nxt_" not in cleaned, text
        assert "actor_token" in found or "credential" in found
    assert redact("nxt_court")[0] == "nxt_court"


def test_ws_ticket_is_redacted_whatever_its_surroundings():
    ticket = "nxw_" + "A" * 43  # built at runtime
    header = "Sec-WebSocket-Protocol: nexus.live.v1, " + ticket
    for text in (ticket, f" {ticket} ", "x" + ticket, header, ticket + "B" * 5):
        cleaned, found = redact(text)
        assert "nxw_" not in cleaned, text
        assert "ws_ticket" in found or "credential" in found
    cleaned, _ = redact(ticket + "B" * 5)
    assert "B" not in cleaned  # a longer run is masked whole
    assert redact("nxw_court")[0] == "nxw_court"


def test_url_with_password_and_no_username_is_masked():
    # issue #15: redis strips usernames, the password alone sits between // and @.
    # The masked URL keeps its exact shape: the colon of the empty username stays.
    cleaned, found = redact("REDIS_URL=redis://:hunter2@localhost/0")
    assert cleaned == f"REDIS_URL=redis://:{REDACTED}@localhost/0"
    assert found == ["url_credentials"]


def test_url_with_username_and_no_password_is_kept():
    # A bare username is not a credential (git clone URLs stay readable).
    text = "git clone https://git@github.com/Mars375/Nexus"
    assert redact(text) == (text, [])


def test_url_without_credentials_in_a_query_is_kept():
    # issue #84, third disposition: without the user-class restriction, the query
    # fed the « user » role and `alice` was erased.
    text = "https://example.org?redirect=mailto:alice@example.net"
    assert redact(text) == (text, [])


def test_url_credentials_before_a_query_are_still_masked():
    cleaned, found = redact("postgresql://alice:hunter2@db.example/nexus?sslmode=require")
    assert cleaned == f"postgresql://alice:{REDACTED}@db.example/nexus?sslmode=require"
    assert found == ["url_credentials"]


def test_url_with_a_port_and_a_query_is_kept():
    # Antigravity review on 6d78a6c (same disposition as above): `host:port` in
    # front of a query read as a password and the port and query head were
    # erased. An unencoded ? or # always ends the userinfo, never a password.
    for text in (
        "http://localhost:3000?email=alice@example.com",
        "https://example.org:443?redirect=mailto:alice@example.net",
    ):
        assert redact(text) == (text, [])


def test_url_credentials_before_a_port_and_a_query_stay_masked():
    # The password restriction leaves real credentials masked, port included.
    cleaned, found = redact("https://alice:hunter2@host:8443/x?y=1")
    assert cleaned == f"https://alice:{REDACTED}@host:8443/x?y=1"
    assert found == ["url_credentials"]


def test_multi_word_passphrase_is_masked_to_end_of_line():
    # issue #15: only the first word used to survive (« correct »).
    cleaned, found = redact("mot de passe : correct horse battery staple")
    assert cleaned == f"mot de passe : {REDACTED}"
    assert found == ["credential"]


def test_bare_value_stops_at_inline_boundaries():
    # The end-of-line value keeps inline structure readable: a comma, brace or
    # quote after the value stays untouched, so JSON and trailing prose survive.
    cleaned, _ = redact("password: hunter2, puis relancer les tests")
    assert cleaned == f"password: {REDACTED}, puis relancer les tests"
    cleaned, _ = redact('{"secret": "abc 123", "note": "ok"}')
    assert cleaned == f'{{"secret": "{REDACTED}", "note": "ok"}}'


def test_long_random_string_is_masked_as_high_entropy():
    # Assembled at runtime from short pieces: 30 unique characters (~4.9 bits/char).
    chaine = "is6Xk9ZmdwaO1Pq" + "Trhv4lHB7sYpG3u"
    cleaned, found = redact(f"probe output: {chaine} rest")
    assert cleaned == f"probe output: {REDACTED} rest"
    assert found == ["high_entropy"]


def test_high_entropy_masking_needs_length_and_randomness():
    # 23 characters: below the length threshold, never an entropy candidate.
    court = "a1b2c3d4e5f6a7b8c9d0e1f"
    assert redact(f"commit {court} ok") == (f"commit {court} ok", [])
    # A repeated character carries no randomness: long but flat is kept.
    plat = "a" * 40
    assert redact(f"commit {plat} ok") == (f"commit {plat} ok", [])
    # A full-width hex run reads like a random token: masked (over-redaction, ADR-006).
    sha = "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0"
    cleaned, found = redact(f"commit {sha} sur main")
    assert sha not in cleaned
    assert found == ["high_entropy"]


@pytest.mark.parametrize(
    "text",
    [
        "uuid 3686f22a-1ac5-4c8a-9d5b-8f29c2f21e90",
        "chemin F:\\Projet\\Nexus\\serveur\\taches\\evenements.db",
        "Réponse lente du serveur 127.0.0.1:5173, réessai dans 200s",
    ],
)
def test_entropy_pass_leaves_structured_but_unlabelled_text_untouched(text):
    # The false-positive criterion (#15): the entropy pass adds nothing to the
    # normal-text corpus — dashes and dots break candidate runs, prose stays flat.
    assert redact(text) == (text, [])


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
    assert masked >= 85


def test_slashed_run_under_the_length_floor_stays_untouched():
    # 23 characters: under the slashed and flat floors alike, no candidate.
    text = "cle A1b2C3d4E5f6/K1l2M3n4O5 fin"
    assert redact(text) == (text, [])


@pytest.mark.parametrize(
    "text",
    [
        "serveur/src/nexus/secrets.py",
        "/var/backups/2026-10-18/nexus.db",
        "https://example.org/documentation_officielle_2026/notes/finales",
        "https://example.org/une_variable_tres_longue_2026/archives/notes_finales",
        "deployments/v1_release_20261018/build_artifacts_run42/output.log",
        "https://cdn.example.org/v1_release_20261018/build_artifacts_run42/output",
        "deployments/20261018/releases/build42/output",
    ],
)
def test_paths_with_slashes_stay_untouched(text):
    # The slashed-pattern guard (#84): a path of words is not an opaque value,
    # even when it is long and carries digits (Antigravity review on 6d78a6c:
    # deployment/build paths used to pass the guard and were erased).
    assert redact(text) == (text, [])


@pytest.mark.parametrize(
    "text",
    [
        "Deployments/V1Release2026Build/Build42Output2026",
        "Apps/V2Prod2026/Release42Build/Deploy20261018",
        "src/views/AccountSettingsV2/OAuth2Callback",
        "components/AuthDialogV2/Step1EmailAddress",
        "api/Version2/PaymentGateway3/ProcessOrder",
        "app/Http/Controllers/ApiV2/Auth3StepFlow",
    ],
)
def test_case_mixed_paths_and_names_stay_untouched(text):
    # Antigravity and reviewer reviews on c73aee9: the previous guard masked a
    # path part merely for mixing case and digits (`Deployments/V1Release…`,
    # `…AccountSettingsV2/OAuth2Callback`). A path names its parts: neither
    # signal of `_blob_segment` fires on a word or a version number.
    assert redact(text) == (text, [])


@pytest.mark.parametrize(
    "text",
    [
        "Dev/Ops/Tool/Run12345/Log6789",
        "Src/App/Doc/Test1/Build2",
        "App/Api/Doc/Web/Job1/Log2",
        "Pkg/Src/Doc/Lib1/Bin2026",
    ],
)
def test_short_titlecase_word_paths_stay_untouched(text):
    # Antigravity review on 5b186c5: a three-letter TitleCase word holds a
    # two-character lowercase run, below the words veto, and chains of them
    # were erased on their word-start capitals alone (a regression against
    # master, where they stayed intact). A change that only opens a word is
    # not a shuffle.
    assert redact(text) == (text, [])


@pytest.mark.parametrize(
    "text",
    [
        "https://github.com/org/repo/releases/v1rc1/v2rc2",
        "kubernetes/crds/v1a1/v1b1",
        "download/ubuntu/v1rc1/v2rc2",
        "terraform/modules/compute/g4dn/c5ad",
        "git checkout refs/heads/release/v1rc1/g4dn",
        "api/v1/users/getById/v2b1",
        "src/controllers/users/getById/v2rc1",
        "endpoints/tasks/toDoList/v1b1",
        "controllers/DevSecOps/getById2",
    ],
)
def test_release_tags_and_camel_case_routes_stay_untouched(text):
    # Antigravity review on d2361cc (F3): a four-to-five character version tag
    # (`v1rc1`, `g4dn`) alternates letters and digits at the scale of a name,
    # and a camelCase method shuffles case between its short words. The blob
    # floor (six pairs) and the words veto of the guard keep both families
    # intact.
    assert redact(text) == (text, [])


@pytest.mark.parametrize(
    "text",
    [
        "GET /api/v1/controllers/DevSecOps/v1a1",
        "https://example.com/api/v1/controllers/DevSecOps/v1a1",
        "src/controllers/DevSecOps/v1a1",
        "controllers/DevSecOps/v1a1",
    ],
)
def test_route_with_a_mixed_case_name_and_a_version_tag_stays_untouched(text):
    # Antigravity review on 5efcee9: the rescue arm accepted a single
    # signal-shaped chunk (`any`) while the same shape reads as a phrase — a
    # word beside an alternating segment (`controllers` beside `v1a1`) no
    # longer lets its blob (the mixed-case name) mask the run. The bare route
    # was already masked on cc0eeb3 (the `any` arm of the whole guard); the
    # three prefixed forms were regressions against it.
    assert redact(text) == (text, [])


def test_hexadecimal_segment_in_an_asset_path_is_masked_as_assumed():
    # issue #84, fourth disposition: over-masking assumed (never a leak); the
    # honest fix needs a path-context heuristic — the current behaviour is
    # pinned here so the assumption stays visible.
    text = "https://example.org/assets/0123456789abcdef0123456789abcdef/logo.svg"
    cleaned, found = redact(text)
    assert cleaned == f"https://example.org/assets/{REDACTED}/logo.svg"
    assert found == ["high_entropy"]


def test_labelled_value_that_is_a_url_with_credentials_is_masked_whole():
    # The labelled value itself is a connection URL: one marker, kept whole (the
    # assignment layer runs before the URL layer so the value is not split).
    cleaned, found = redact("password=postgresql://alice:hunter2@db.example/nexus")
    assert cleaned == f"password={REDACTED}"
    assert found == ["credential"]


def test_masked_token_then_another_secret_on_the_same_line():
    # The first label's value starts at an existing [REDACTED] and does not
    # match; the resumed scan masks the second secret under its own label.
    cleaned, found = redact("token=[REDACTED] password=hunter2 to try")
    assert cleaned == f"token={REDACTED} password={REDACTED}"
    assert found == ["credential"]


def test_another_secret_then_masked_token_on_the_same_line():
    # The value sweep stops before the `token=` fragment (continuation runs
    # exclude `=` and `:`), so the tail mask is not doubled.
    cleaned, found = redact("password=hunter2 token=[REDACTED]")
    assert cleaned == f"password={REDACTED} token={REDACTED}"
    assert found == ["credential"]


def test_bracketed_value_is_masked_whole():
    # A value wrapped in brackets is a real secret (CodeRabbit finding on
    # 58f3920): today the bare value skips a leading `[`, none of the other
    # layers catch a short run, and the password would go out unmasked.
    cleaned, found = redact("password=[hunter2]")
    assert cleaned == f"password={REDACTED}"
    assert found == ["credential"]


def test_bracketed_value_with_spaces_is_masked_whole():
    # The bracket form is captured with its whole shell, spaces included.
    cleaned, found = redact("mot de passe=[correct horse battery staple]")
    assert cleaned == f"mot de passe={REDACTED}"
    assert found == ["credential"]


def test_bracketed_marker_value_is_idempotent():
    # An existing [REDACTED] value is returned unchanged and does not report
    # a credential a second time (mask_value's short circuit).
    cleaned, found = redact("token=[REDACTED]")
    assert cleaned == "token=[REDACTED]"
    assert found == []


def test_passphrase_containing_an_unlabelled_equals_word_is_masked_whole():
    # `battery=staple` is part of the passphrase (CodeRabbit comment on
    # 58f3920): the continued sweep only stops before a word that IS one of
    # the recognised labels followed by `=` or `:`, not before any `=`.
    cleaned, found = redact("mot de passe : correct horse battery=staple")
    assert cleaned == "mot de passe : [REDACTED]"
    assert found == ["credential"]


def test_next_recognised_label_still_ends_the_sweep():
    # A later, recognised label with its own value ends the sweep: the two
    # labelled secrets are masked separately, each keeping its own label
    # (the sweep's generous tail belongs to the second label, not the first).
    cleaned, found = redact("password: correct horse api_key=xyz soon")
    assert cleaned == "password: [REDACTED] api_key=[REDACTED]"
    assert found == ["credential"]


def test_underscored_high_entropy_token_in_prose_is_masked():
    # A random token framed with `_` separators splits into runs below the
    # 24-character candidate length (CodeRabbit finding on 7f314de); the
    # entropy candidate now spans the separators.
    cleaned, found = redact("jeton reçu : Y7qP2rTx_N9vH4mKu_C6wJ8sZa_R5dE3fGh à lire")
    assert cleaned == f"jeton reçu : {REDACTED} à lire"
    assert found == ["high_entropy"]


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


def test_interleaved_short_vendor_segments_stay_untouched_as_assumed():
    # Same review, the other half of the finding: a value that interleaves a
    # SHORT segment (`live`, `v1`) between opaque ones stays out of reach on
    # purpose — tolerating it would reopen the identifier false positives just
    # closed (see test_identifier_with_one_short_head_…). The assumption is
    # pinned here so a later widening has to argue with this test.
    text = "sk_live_" + "Y7qP2rTx_N9vH4mKu" + "_C6wJ8sZa_R5dE3fGh"
    assert redact(text) == (text, [])


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


def test_title_case_slug_with_short_word_stays_untouched():
    # A candidate with one short segment is only opaque when a flat 24+ run
    # hides behind it; title-case words (3.545 bits joined) have none.
    text = "cap sur « Dictionnaire-des_Expressions_Francaises » à lire"
    assert redact(text) == (text, [])


def test_passphrase_containing_an_unlabelled_label_word_is_masked_whole():
    # A word that IS one of the recognised labels but carries no `=` or `:`
    # must not abort the sweep (Antigravity review on 34e5902): the grouped
    # lookahead shares its `\s*[=:]` requirement with every label branch,
    # not just the last one, so a plain label word inside the passphrase
    # keeps the sweep running and the value is masked whole.
    for text in (
        "mot de passe : this is my secret passphrase",
        "password: use the token right now",
        "mot de passe : mon mot de passe est simple",
        "token: un mot de passe fragile comme mot de passe",
    ):
        label, _, _ = text.partition(":")
        cleaned, found = redact(text)
        assert cleaned == f"{label}: {REDACTED}"
        assert found == ["credential"]


def test_framed_underscore_high_entropy_token_in_prose_is_masked():
    # Markdown italics frame the token with extra `_` separators (Antigravity
    # review on 34e5902): the empty framing segments must not drag the
    # segment floor to 0 and free the candidate.
    cleaned, found = redact(
        "jeton reçu : _Y7qP2rTx_N9vH4mKu_C6wJ8sZa_R5dE3fGh_ à lire"
    )
    assert cleaned == f"jeton reçu : {REDACTED} à lire"
    assert found == ["high_entropy"]


def test_hyphen_joined_high_entropy_token_in_prose_is_masked():
    # The same segmented token with `-` joiners (Antigravity review on
    # 34e5902): locked before the framing fix so the guard cannot regress.
    cleaned, found = redact(
        "jeton reçu : Y7qP2rTx-N9vH4mKu-C6wJ8sZa-R5dE3fGh à lire"
    )
    assert cleaned == f"jeton reçu : {REDACTED} à lire"
    assert found == ["high_entropy"]


def test_bracketed_value_with_colon_is_masked_whole():
    # A colon-separated bracketed value (Antigravity review on 34e5902):
    # the bracket shell is masked whole whatever the separator.
    cleaned, found = redact("password: [hunter2]")
    assert cleaned == f"password: {REDACTED}"
    assert found == ["credential"]


def test_label_vocabulary_with_long_joined_words_stays_untouched():
    # Joined label words are prose, not secrets: an entropy candidate that
    # carries no digit is vocabulary, whatever the joiners (reviewer
    # regression on 327aa8e — labels routed through clean_label were
    # rejected once the candidate class allowed `_` and `-`).
    text = "authentification-rechargement"
    assert redact(text) == (text, [])

    text = "pending+cancelled+overdue"
    assert redact(text) == (text, [])


def test_unclosed_bracket_value_is_masked_to_end_of_line():
    # A shell with no closing bracket must still hide the value (reviewer
    # regression on 327aa8e: the bracket branch required the `]`, and the
    # bare run refuses to start at `[` for idempotence).
    cleaned, found = redact("password: [hunter2")
    assert cleaned == f"password: {REDACTED}"
    assert found == ["credential"]


def test_bracket_closed_after_a_new_line_stays_line_scoped():
    # The shell never crosses a newline; the leftover of a value closed on
    # the next line keeps the base behaviour (`[REDACTED]\n123]`).
    cleaned, found = redact("password: [hunter2\n123]")
    assert cleaned == f"password: {REDACTED}\n123]"
    assert found == ["credential"]


def test_double_dash_framed_token_is_masked_whole():
    # CLI flags frame tokens with `--`: the framing separators belong to
    # the candidate and are masked with it (reviewer probe on 327aa8e).
    cleaned, found = redact(
        "portail --Y7qP2rTx-N9vH4mKu-C6wJ8sZa-R5dE3fGh-- actif"
    )
    assert cleaned == f"portail {REDACTED} actif"
    assert found == ["high_entropy"]


def test_digits_only_run_is_not_opaque():
    # A pure-digit run carries at most log2(10) ≈ 3.32 bits per character:
    # below the Shannon threshold, whatever its length (locked choice).
    text = "numerique : 842157306914827563201984 annote"
    assert redact(text) == (text, [])


def test_entropy_candidate_floor_is_24_characters():
    # Exactly 24 opaque characters are masked, 23 are not even a candidate
    # (locked boundary; reviewer probe on 327aa8e).
    cleaned, found = redact("cle A7x9QzW2Ry5Nt8Kv4Jm6Pa1C nette")
    assert cleaned == f"cle {REDACTED} nette"
    assert found == ["high_entropy"]

    text = "cle B7x9QzW2Ry5Nt8Kv4Jm6Pa1 brisee"
    assert redact(text) == (text, [])


def test_glued_bracket_fragments_join_the_labelled_value():
    # Bracket fragments glued to a labelled value are part of the same
    # secret (reviewer P2-3 on 0808860): the naked run of the base class
    # admitted `[` and `]`, so nothing survives; the shell alternative and
    # mask_value's marker short-circuit keep the idempotence safe.
    for text, expected in (
        ("password=abc[hunter2]", f"password={REDACTED}"),
        ("password=abc[hunter2", f"password={REDACTED}"),
        ("password: hunter2[beta]", f"password: {REDACTED}"),
        ("password=([hunter2])", f"password={REDACTED}"),
        ("password=([correct horse battery staple])", f"password={REDACTED}"),
    ):
        cleaned, found = redact(text)
        assert cleaned == expected, text
        assert found == ["credential"], text


def test_suffix_glued_after_a_shell_joins_the_value():
    # CodeRabbit Major (18:36Z on d6d4033, verified at source): the shell
    # branch stopped right after the closing bracket, so code glued to a
    # masked shell survived in the clear (`password=[hunter2]abc123` kept
    # `abc123`); the never-glued base class masked it whole. The shell
    # branch now takes the glued run too; prose after a SPACE stays prose,
    # and the exact marker still comes back unchanged through the short
    # circuit.
    cleaned, found = redact("password=[hunter2]abc123")
    assert cleaned == f"password={REDACTED}"
    assert found == ["credential"]

    cleaned, found = redact("password: [hunter2]x suite")
    assert cleaned == f"password: {REDACTED} suite"
    assert found == ["credential"]

    cleaned, found = redact("password=[hunter2]abc def")
    assert cleaned == f"password={REDACTED} def"
    assert found == ["credential"]

    # A glued suffix on an already-masked value collapses back to the
    # marker; the marker alone comes back unchanged.
    cleaned, found = redact("token=[REDACTED]abc123")
    assert cleaned == f"token={REDACTED}"
    assert found == ["credential"]
    assert redact("token=[REDACTED]") == ("token=[REDACTED]", [])
