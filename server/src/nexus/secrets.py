"""Détection et masquage des secrets avant toute écriture (ADR-006, SECURITY §1).

Aucun secret n'est stocké, journalisé ni renvoyé : toute correspondance devient `[REDACTED]`.
Les motifs visent des formats reconnaissables pour limiter les faux positifs sur du texte normal.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any

REDACTED = "[REDACTED]"

_FULL: list[tuple[str, re.Pattern[str]]] = [
    ("private_key", re.compile(
        r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?(?:-----END [A-Z ]*PRIVATE KEY-----|\Z)"
    )),
    ("api_key", re.compile(r"\bsk-(?:proj-|ant-)?[A-Za-z0-9_-]{20,}")),
    ("github_token", re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{22,})")),
    ("aws_access_key", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")),
    ("slack_token", re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}")),
    ("google_api_key", re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b")),
    # Nexus actor token (ADR-020): `nxt_` + 43 base64url characters; a longer run is redacted whole.
    # Deliberately unanchored (no `\b`): ADR-006 prefers over-redaction, so a token glued to
    # other text is still masked.
    ("actor_token", re.compile(r"nxt_[A-Za-z0-9_-]{43,}")),
    # Nexus WebSocket ticket (#57): `nxw_` + 43 base64url characters, unanchored as above.
    ("ws_ticket", re.compile(r"nxw_[A-Za-z0-9_-]{43,}")),
    ("jwt", re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}")),
    ("bearer_token", re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]{20,}")),
]

# Mot de passe dans une URL de connexion : postgresql://alice:hunter2@hôte/base.
_URL_CREDENTIALS = re.compile(r"(?i)\b([a-z][a-z0-9+.-]*://[^\s:/@]+:)([^\s@/]+)(@)")

# En-tête HTTP d'identifiant écrit tel quel (« Authorization: Digest username="…", … »,
# « Cookie: a=1; b=2 ») : sa valeur court jusqu'à la fin de la ligne, virgules et ; compris,
# et continue sur les lignes repliées (qui commencent par une espace ou une tabulation).
# Forme citée comprise (« "Authorization": "Digest username=\"…\"" ») : des guillemets
# échappés dans la valeur l'arrêteraient sinon au premier.
_HEADER_CREDENTIALS = re.compile(
    r"(?im)(?<![\w.-])((?:proxy[_-]?)?authorization|(?:set[_-]?)?cookie)([\"']?\s*:\s*)"
    r"(?=\S)([^\r\n]+(?:\r?\n[ \t][^\r\n]*)*)"
)

# « mot de passe : xyz », « token=abc »… : on masque la valeur, on garde l'étiquette.
# Couvre aussi la forme JSON/YAML collée ({"password": "hunter2"}, 'token': 'abc') et les
# variables d'environnement préfixées (AWS_SECRET_ACCESS_KEY=…, CLIENT_SECRET=…). Préfixe
# et suffixe doivent être séparés par _ . ou - : « tokens: 3000 » n'est pas un secret.
_LABEL = (
    r"(?:[\w.-]*[_.-])?"
    r"(?:password|passwd|pwd|secret|api[ _-]?key|access[ _-]?token|private[ _-]?key|token"
    # Codes à usage unique (SECURITY §1 : les codes 2FA sont des secrets).
    r"|otp|totp|2fa|mfa|verification[ _-]?code|one[ _-]?time[ _-]?code"
    # En-têtes HTTP qui portent un identifiant, quel que soit le schéma (Basic, Digest…).
    r"|authorization|cookie)"
    r"(?:[_.-][\w.-]*)?"
    # camelCase / PascalCase (clientSecret, refreshToken, dbPassword) : la majuscule sert de
    # séparateur, sensible à la casse pour que « maxTokens » ou « tokenizer » restent intacts.
    r"|(?-i:[A-Za-z][A-Za-z0-9]*?"
    r"(?:Password|Passwd|Pwd|Secret|ApiKey|AccessToken|PrivateKey|Token|Otp|Totp|Mfa"
    r"|Authorization|Cookie)"
    r"(?:[A-Z][A-Za-z0-9]*)?)"
    r"|mot de passe|mdp|code de vérification"
)
# Clé JSON qui nomme un identifiant : {"password": "…"} — sa valeur est un secret.
_CREDENTIAL_KEY = re.compile(rf"(?i){_LABEL}")

_ASSIGNMENT = re.compile(
    rf"(?i)(?<![\w.-])({_LABEL})"
    r"([\"']?\s*[:=]\s*)"
    # Valeur nue : un schéma d'authentification éventuel (Basic xyz) en fait partie.
    r"(?:\"([^\"]*)\"|'([^']*)'"
    r"|((?:(?:basic|bearer|digest|negotiate|ntlm)\s+)?[^\s,;}\"']+))"
)


def redact(text: str) -> tuple[str, list[str]]:
    """Renvoie le texte masqué et la liste des types de secrets trouvés."""
    found: list[str] = []
    for kind, pattern in _FULL:
        text, count = pattern.subn(REDACTED, text)
        if count:
            found.append(kind)

    def mask_value(match: re.Match[str]) -> str:
        label, separator, double, single, bare = match.groups()
        value = next(v for v in (double, single, bare) if v is not None)
        if not value or value == REDACTED:
            return match.group(0)
        found.append("credential")
        quote = '"' if double is not None else "'" if single is not None else ""
        return f"{label}{separator}{quote}{REDACTED}{quote}"

    def mask_url(match: re.Match[str]) -> str:
        if match.group(2) == REDACTED:
            return match.group(0)
        found.append("url_credentials")
        return f"{match.group(1)}{REDACTED}{match.group(3)}"

    def mask_header(match: re.Match[str]) -> str:
        if match.group(3).strip() == REDACTED:
            return match.group(0)
        found.append("credential")
        return f"{match.group(1)}{match.group(2)}{REDACTED}"

    text = _URL_CREDENTIALS.sub(mask_url, text)
    text = _HEADER_CREDENTIALS.sub(mask_header, text)
    text = _ASSIGNMENT.sub(mask_value, text)
    return text, sorted(set(found))


# Un secret masqué et ce qui l'entoure : étiquette suivie de : ou = (password=),
# guillemets, parenthèses. Un simple mot devant (« utiliser [REDACTED] ») reste du sens.
_REDACTED_SPAN = re.compile(r"(?:[\w.-]+\s*[:=]\s*)?[\"'(\[]*\[REDACTED\][\"')\]]*")


def is_blank(text: str | None) -> bool:
    """Vide, ou ne contenant que des secrets masqués : ne dit rien d'utilisable."""
    if not text:
        return True
    return not re.search(r"\w", _REDACTED_SPAN.sub("", text))


def is_blank_reference(text: str | None) -> bool:
    """Une preuve doit garder un identifiant : « commit: token=[REDACTED] » n'a plus que
    son étiquette, elle ne prouve rien."""
    if is_blank(text):
        return True
    rest = _REDACTED_SPAN.sub("", text)
    rest = re.sub(r"^\s*[\w.-]+\s*:", "", rest, count=1)  # étiquette : commit:, url:, https:
    # Étiquettes restées vides ailleurs (« … url: ») : elles ne portent aucun identifiant.
    rest = re.sub(r"[\w.-]+\s*[:=](?=\s|$)", "", rest)
    return not re.search(r"\w", rest)


def redact_value(value: Any) -> tuple[Any, list[str]]:
    """Comme `redact`, sur une chaîne, une liste ou un dict — clés comprises : un secret
    collé comme nom de propriété JSON serait sinon stocké tel quel."""
    found: set[str] = set()

    def walk(v: Any) -> Any:
        if isinstance(v, str):
            cleaned, kinds = redact(v)
            found.update(kinds)
            return cleaned
        if isinstance(v, (list, tuple)):  # un tuple part en JSON comme une liste
            return [walk(x) for x in v]
        if isinstance(v, dict):
            return {
                (walk(k) if isinstance(k, str) else k): mask_if_credential(k, x)
                for k, x in v.items()
            }
        return v

    def mask_if_credential(key: Any, value: Any) -> Any:
        # Sous une clé d'identifiant, toute valeur non vide est un secret — liste ou objet
        # compris ({"password": ["…"]}, {"api_key": {"value": "…"}}).
        if isinstance(value, str):
            empty = not value.strip() or value == REDACTED
        else:
            empty = value is None or value == [] or value == {}
        if isinstance(key, str) and _CREDENTIAL_KEY.fullmatch(key.strip()) and not empty:
            found.add("credential")
            return REDACTED
        return walk(value)

    return walk(value), sorted(found)


def redact_fields(
    values: dict[str, Any], on_found: Callable[[str, list[str]], None] | None = None
) -> dict[str, Any]:
    """Masque chaque champ ; `on_found(champ, types)` est appelé pour chaque champ touché."""
    cleaned = {}
    for field, value in values.items():
        cleaned[field], kinds = redact_value(value)
        if kinds and on_found:
            on_found(field, kinds)
    return cleaned
