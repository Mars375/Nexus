"""Erreurs de validation en français (AGENTS.md : textes en français), sans jamais la valeur reçue.

La validation a lieu avant le masquage des secrets (ADR-006) : la valeur envoyée n'est donc
jamais recopiée dans la réponse, seulement le champ et la raison.
"""

from __future__ import annotations

from typing import Any

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


def french_errors(errors: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "loc": list(e.get("loc", ())),
            "msg": f"{_field(tuple(e.get('loc', ())))} : {_message(e)}",
            "type": e.get("type"),
        }
        for e in errors
    ]
