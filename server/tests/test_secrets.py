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
