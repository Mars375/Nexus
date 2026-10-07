"""Contrat ADR-005 : toute entité renvoyée par une route GET /api/… porte sa provenance.

Le test parcourt les routes déclarées : une nouvelle route est vérifiée sans qu'il faille
l'ajouter ici, et un paramètre de chemin inconnu fait échouer le test au lieu d'être ignoré.
"""

from datetime import datetime

import pytest

AT = "2026-09-29T09:05:00+02:00"


def fill_path(path: str, values: dict[str, str]) -> str:
    names = [part[1:-1] for part in path.split("/") if part.startswith("{")]
    missing = [name for name in names if name not in values]
    if missing:
        raise AssertionError(
            f"paramètre de chemin sans valeur de test : {missing} dans {path} — "
            "ajoute sa valeur au dict renvoyé par seed() dans test_provenance_contract.py"
        )
    return path.format(**values)


def entities(body) -> list:
    """Entités affichables d'une réponse, selon la règle de la spec."""
    if isinstance(body, list):
        return body
    if isinstance(body, dict) and "source" in body:
        return [body]
    if isinstance(body, dict):
        children = []
        for value in body.values():
            if isinstance(value, dict):
                children.append(value)
            elif isinstance(value, list):
                children.extend(value)
        return children or [body]
    return [body]


def check_entity(entity) -> None:
    assert isinstance(entity, dict), f"entité non objet : {entity!r}"
    assert isinstance(entity.get("source"), str) and entity["source"].strip(), entity
    measured = entity.get("measured_at")
    assert isinstance(measured, str), f"measured_at manquant : {entity}"
    assert datetime.fromisoformat(measured).tzinfo is not None, f"sans fuseau : {measured}"
    if "source_url" in entity and entity["source_url"] is not None:
        assert str(entity["source_url"]).startswith("https://"), entity["source_url"]


def seed(client) -> dict[str, str]:
    res = client.post("/api/tasks", json={"title": "Pont", "objective": "Lire"})
    assert res.status_code == 201, (
        f"POST /api/tasks → {res.status_code} {res.text}"
    )
    task = res.json()["id"]
    res = client.post(f"/api/tasks/{task}/comments", json={"body": "noté"})
    assert res.status_code == 201, (
        f"POST /api/tasks/{{task}}/comments → {res.status_code} {res.text}"
    )
    res = client.post("/api/events", json={
        "id": "evt_contract", "at": AT, "actor": "helios", "kind": "claimed",
        "subject": "je prends", "task": task,
    })
    assert res.status_code == 201, (
        f"POST /api/events → {res.status_code} {res.text}"
    )
    event = res.json()["id"]
    res = client.post("/api/events", json={
        "id": "evt_contract_ask", "at": AT, "actor": "mnema", "kind": "question",
        "subject": "Quelle version ?", "needs": ["loic"], "task": task,
    })
    assert res.status_code == 201, (
        f"POST /api/events (question) → {res.status_code} {res.text}"
    )
    approval = res.json()["effects"][0]["approval"]
    # An answered approval carries its response: its entities must keep their provenance too.
    res = client.post(f"/api/approvals/{approval}/answer", json={"text": "Version 2"})
    assert res.status_code == 200, (
        f"POST /api/approvals/{{approval}}/answer → {res.status_code} {res.text}"
    )
    return {"task_ref": task, "event_ref": event, "approval_ref": approval}


def api_get_routes(app) -> list[str]:
    # Sur FastAPI 0.141, les routeurs inclus avec app.include_router() ne sont pas aplatis
    # dans app.routes (restent des objets _IncludedRouter) : on énumère app.openapi()["paths"].
    paths = app.openapi().get("paths", {})
    return sorted(
        path for path in paths
        if path.startswith("/api/") and "get" in paths[path]
    )


def test_every_api_get_route_returns_entities_with_provenance(client):
    values = seed(client)
    routes = api_get_routes(client.app)
    assert routes, "aucune route GET /api/ trouvée"
    for path in routes:
        res = client.get(fill_path(path, values))
        assert res.status_code == 200, f"{path} → {res.status_code} {res.text}"
        found = entities(res.json())
        if isinstance(res.json(), list):
            assert found, f"{path} : aucune entité à vérifier"
        for entity in found:
            check_entity(entity)


def test_the_walker_sees_every_router(client):
    # Régression contre FastAPI 0.141 : app.routes ne contient pas les routeurs inclus aplatis.
    routes = api_get_routes(client.app)
    assert "/api/tasks" in routes, "routeur tasks oublié"
    assert "/api/tasks/{task_ref}/history" in routes, "routeur tasks.history oublié"
    assert "/api/events/{event_ref}" in routes, "routeur events oublié"
    assert "/api/approvals/{approval_ref}" in routes, "routeur approvals oublié"


def test_the_checker_catches_a_missing_measured_at():
    with pytest.raises(AssertionError):
        for entity in entities({"version": "1", "backup": {"source": "x"}}):
            check_entity(entity)


def test_the_checker_checks_lists_inside_a_composite():
    with pytest.raises(AssertionError):
        for entity in entities({"version": "1", "items": [{"source": "x"}]}):
            check_entity(entity)
    # avec un sous-objet valide à côté : l'ancienne règle ignorait la liste en silence
    body = {"db": {"source": "x", "measured_at": AT}, "items": [{"source": "x"}]}
    with pytest.raises(AssertionError):
        for entity in entities(body):
            check_entity(entity)


def test_the_checker_ignores_nested_data_of_an_entity():
    event = {"source": "nexus.db", "measured_at": AT, "payload": {"x": 1}, "effects": [{"a": 1}]}
    for entity in entities(event):
        check_entity(entity)


def test_an_unknown_path_parameter_fails_loudly():
    with pytest.raises(AssertionError, match="seed"):
        fill_path("/api/things/{thing_ref}", {"task_ref": "nx-task-1"})


def test_source_url_must_be_https():
    with pytest.raises(AssertionError):
        check_entity({"source": "telegram", "measured_at": AT, "source_url": "javascript:x"})
