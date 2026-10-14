"""Erreurs de validation en français (AGENTS.md : textes en français), sans jamais la valeur reçue.

La validation a lieu avant le masquage des secrets (ADR-006) : la valeur envoyée n'est donc
jamais recopiée dans la réponse, seulement le champ et la raison.
"""

from __future__ import annotations

import math
import re
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, StringConstraints, TypeAdapter, model_validator

from nexus import secrets

# The API strips evidence items with Pydantic before measuring them: every path that stores
# evidence reuses that exact stripping (it differs from `str.strip()`, which also removes U+001C
# to U+001F).
API_STRIP = TypeAdapter(Annotated[str, StringConstraints(strip_whitespace=True)])

# Moitié de paire UTF-16 isolée (« \ud800 » en JSON) : le décodeur l'accepte, mais elle ne
# s'encode pas en UTF-8 — stockée, elle ferait échouer chaque réponse qui la relit.
_LONE_SURROGATE = re.compile("[\ud800-\udfff]")


def _has_lone_surrogate(value: Any) -> bool:
    if isinstance(value, str):
        return bool(_LONE_SURROGATE.search(value))
    if isinstance(value, dict):
        return any(_has_lone_surrogate(k) or _has_lone_surrogate(v) for k, v in value.items())
    if isinstance(value, list):
        return any(_has_lone_surrogate(v) for v in value)
    return False


def has_unencodable(value: Any) -> bool:
    """Tout ce qui ne se stocke ni ne se renvoie en JSON strict, n'importe où (clés comprises) :
    demi-paire UTF-16, nombre non fini, ou type hors JSON (ensemble, octets, date…). L'API le
    garantit par ses modèles ; sert aussi aux adaptateurs qui appellent le service directement."""
    if value is None or isinstance(value, (bool, int)):
        return False
    if isinstance(value, float):
        return not math.isfinite(value)
    if isinstance(value, str):
        return _has_lone_surrogate(value)
    if isinstance(value, dict):
        return any(
            not isinstance(k, str) or has_unencodable(k) or has_unencodable(v)
            for k, v in value.items()
        )
    if isinstance(value, (list, tuple)):
        return any(has_unencodable(v) for v in value)
    return True


class InputModel(BaseModel):
    """Base de tout corps de requête : champ inconnu refusé, texte non encodable refusé."""

    model_config = ConfigDict(extra="forbid")  # un champ inconnu n'est jamais ignoré en silence

    @model_validator(mode="before")
    @classmethod
    def _no_lone_surrogates(cls, data: Any) -> Any:
        if _has_lone_surrogate(data):
            raise ValueError("texte invalide : caractère Unicode isolé (demi-paire UTF-16)")
        return data

_MESSAGES = {
    "missing": "champ obligatoire",
    "string_too_short": "ne peut pas être vide",
    "string_too_long": "trop long (au plus {max_length} caractères)",
    "string_type": "texte attendu",
    "literal_error": "valeur non autorisée (attendu : {expected})",
    "enum": "valeur non autorisée (attendu : {expected})",
    "list_type": "liste attendue",
    "dict_type": "objet attendu",
    "int_type": "nombre entier attendu",
    "int_parsing": "nombre entier attendu",
    "bool_type": "vrai ou faux attendu",
    "bool_parsing": "vrai ou faux attendu",
    "datetime_type": "date et heure ISO-8601 attendues",
    "datetime_parsing": "date et heure ISO-8601 attendues",
    "datetime_from_date_parsing": "date et heure ISO-8601 attendues",
    "timezone_aware": "l'instant doit préciser son fuseau horaire",
    "greater_than_equal": "doit être au moins {ge}",
    "less_than_equal": "doit être au plus {le}",
    "json_invalid": "JSON invalide",
    "extra_forbidden": "champ inconnu ou non modifiable ici",
    "model_attributes_type": "objet attendu",
}


def _field(loc: tuple) -> str:
    parts = [str(p) for p in loc if p not in ("body", "query", "path", "header")]
    return ".".join(parts) or "requête"


def _message(error: dict[str, Any]) -> str:
    kind = error.get("type", "")
    if kind == "value_error":
        # Message écrit par nos propres validateurs, déjà en français.
        return str(error.get("msg", "")).removeprefix("Value error, ")
    template = _MESSAGES.get(kind, "valeur invalide")
    try:
        return template.format(**(error.get("ctx") or {}))
    except (KeyError, IndexError):
        return template.split(" (")[0]


def _safe_loc(loc: tuple) -> tuple:
    # Un nom de champ inconnu est lui aussi une donnée reçue : s'il contient un secret, il est
    # masqué avant d'être recopié dans `loc` et dans `msg` (ADR-006).
    return tuple(
        secrets.REDACTED if isinstance(part, str) and secrets.redact(part)[1] else part
        for part in loc
    )


def french_errors(errors: list[dict[str, Any]]) -> list[dict[str, Any]]:
    cleaned = []
    for e in errors:
        loc = _safe_loc(tuple(e.get("loc", ())))
        cleaned.append({"loc": list(loc), "msg": f"{_field(loc)} : {_message(e)}",
                        "type": e.get("type")})
    return cleaned
