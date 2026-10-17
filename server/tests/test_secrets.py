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
