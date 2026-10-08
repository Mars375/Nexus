"""Jeton exigé partout (#16, ADR-020, D5/D7/D8/D9) et invariant de couverture des routes."""

from conftest import tailscale_json
from fastapi import FastAPI
from fastapi.routing import APIRoute, APIWebSocketRoute

from nexus import actors
from nexus.app import create_app

AT = "2026-09-28T09:05:00+02:00"
# Les seules routes sans jeton : l'état du serveur, le WebSocket (Origin et Host seulement, D5)
# et la documentation OpenAPI servie par FastAPI (aucune donnée de Nexus).
OPEN_REST = {("GET", "/api/health")}
OPEN_WEBSOCKETS = {"/api/ws"}
OPEN_STATIC = {"/openapi.json", "/docs", "/docs/oauth2-redirect", "/redoc"}


def flat_routes(routes):
    """Toutes les routes, y compris celles des routeurs inclus (non aplatis par FastAPI 0.141)."""
    for route in routes:
        inner = getattr(route, "original_router", None)
        if inner is not None:
            yield from flat_routes(inner.routes)
        else:
            yield route


def fill(path):
    for part in [p[1:-1] for p in path.split("/") if p.startswith("{")]:
        path = path.replace("{" + part + "}", "x")
    return path


def unauthenticated_routes(app: FastAPI, client) -> list[str]:
    """Routes qui répondent sans jeton, hors liste blanche (vide si tout est verrouillé)."""
    offenders = []
    for route in flat_routes(app.routes):
        path = getattr(route, "path", "")
        if isinstance(route, APIRoute):
            for method in sorted(route.methods - {"HEAD", "OPTIONS"}):
                if (method, path) in OPEN_REST:
                    continue
                res = client.request(method, fill(path), json={})
                ok = res.status_code == 401 and res.json()["detail"]["code"] == "auth_required"
                if not ok:
                    offenders.append(f"{method} {path} → {res.status_code}")
        elif isinstance(route, APIWebSocketRoute):
            if path not in OPEN_WEBSOCKETS:
                offenders.append(f"WS {path}")
        elif path not in OPEN_STATIC:
            offenders.append(f"{type(route).__name__} {path}")
    return offenders


def test_every_route_requires_a_token_except_the_allow_list(anonymous):
    assert unauthenticated_routes(anonymous.app, anonymous) == []


def test_the_walker_sees_every_router(anonymous):
    seen = {(m, r.path) for r in flat_routes(anonymous.app.routes) if isinstance(r, APIRoute)
            for m in r.methods}
    for expected in [
        ("GET", "/api/health"), ("GET", "/api/nodes"), ("GET", "/api/now"),
        ("POST", "/api/tasks"), ("POST", "/api/events"),
        ("POST", "/api/approvals/{approval_ref}/answer"),
    ]:
        assert expected in seen, expected
    assert any(isinstance(r, APIWebSocketRoute) for r in flat_routes(anonymous.app.routes))


def test_a_route_added_without_a_token_fails_the_invariant(settings):
    from conftest import ActorClient

    app = create_app(settings, nodes_runner=tailscale_json)

    @app.get("/api/oops")
    def oops() -> dict:
        return {}

    @app.websocket("/api/oops-ws")
    async def oops_ws(websocket) -> None: ...

    app.mount("/static-oops", FastAPI())
    with ActorClient(app, authenticate=False) as client:
        offenders = unauthenticated_routes(app, client)
    assert any(o.startswith("GET /api/oops ") for o in offenders)
    assert "WS /api/oops-ws" in offenders
    assert any("/static-oops" in o for o in offenders)


def test_health_stays_open_even_with_a_bad_authorization(anonymous):
    assert anonymous.get("/api/health").status_code == 200
    assert anonymous.get("/api/health", headers={"Authorization": "Basic x"}).status_code == 200


def test_reads_require_a_token(anonymous):
    for path in ["/api/tasks", "/api/tasks/nx-task-1", "/api/events", "/api/now", "/api/nodes",
                 "/api/approvals"]:
        res = anonymous.get(path)
        assert res.status_code == 401, path
        assert res.json()["detail"]["code"] == "auth_required"
        assert res.headers["www-authenticate"] == "Bearer"


def test_reads_refuse_an_invalid_token(client):
    res = client.get("/api/tasks", headers={"Authorization": "Bearer nxt_" + "A" * 43})
    assert res.status_code == 401 and res.json()["detail"]["code"] == "invalid_token"


def test_the_actor_header_alone_is_not_an_identity(anonymous):
    for actor in ("loic", "helios", "mallory"):
        res = anonymous.post("/api/tasks", json={"title": "t", "objective": "o"},
                             headers={"X-Nexus-Actor": actor})
        assert res.status_code == 401
        assert "mallory" not in res.text


def test_the_default_actor_no_longer_exists():
    assert not hasattr(actors, "DEFAULT_ACTOR")


def test_a_tokenless_event_is_401_not_422(anonymous):
    body = {"id": "e1", "at": AT, "actor": "helios", "kind": "question", "subject": "?",
            "needs": ["loic"]}
    assert anonymous.post("/api/events", json=body).status_code == 401
    res = anonymous.post("/api/events", json=body, headers={"X-Nexus-Actor": "codex"})
    assert res.status_code == 401


def test_nothing_is_written_by_a_refused_tokenless_request(anonymous, client):
    anonymous.post("/api/tasks", json={"title": "t", "objective": "o"})
    assert client.get("/api/tasks").json() == []


def test_the_websocket_keeps_origin_and_host_checks_only(anonymous):
    with anonymous.websocket_connect("/api/ws") as ws:
        assert ws.receive_json()["type"] == "hello"
