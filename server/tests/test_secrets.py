import pytest

from nexus.secrets import REDACTED, redact, redact_value

# Valeurs factices, construites pour ressembler aux vrais formats.
SAMPLES = {
    "api_key": "sk-proj-" + "a1B2c3D4e5F6g7H8i9J0k1L2",
    "github_token": "ghp_" + "A" * 36,
    "aws_access_key": "AKIA" + "ABCDEFGHIJKLMNOP",
    "slack_token": "xoxb-" + "1234567890-abcdefghij",
    "google_api_key": "AIza" + "B" * 35,
    "jwt": "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0In0.c2lnbmF0dXJlLXZhbGV1cg",
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
        ("AWS_SECRET_ACCESS_KEY=wJalrXUtnFEMIK7MDENG", "AWS_SECRET_ACCESS_KEY=[REDACTED]"),
        ("CLIENT_SECRET=abc123", "CLIENT_SECRET=[REDACTED]"),
        ('{"db.password": "x1"}', '{"db.password": "[REDACTED]"}'),
        ("otp: 123456", "otp: [REDACTED]"),
        ("2fa_code=123456", "2fa_code=[REDACTED]"),
        ("verification_code=123456", "verification_code=[REDACTED]"),
        ("code de vérification : 123456", "code de vérification : [REDACTED]"),
    ],
)
def test_quoted_credentials_are_masked(text, expected):
    cleaned, found = redact(text)
    assert cleaned == expected
    assert found == ["credential"]


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
