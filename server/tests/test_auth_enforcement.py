"""Jeton exigé partout (#16, ADR-020, D5/D7/D8/D9) et invariant de couverture des routes."""

import pytest
from conftest import tailscale_json
from fastapi import APIRouter, FastAPI
from fastapi.routing import APIRoute, APIWebSocketRoute
from starlette.websockets import WebSocket, WebSocketDisconnect

from nexus import actors
from nexus.app import create_app

AT = "2026-09-28T09:05:00+02:00"
# Les seules routes sans jeton : l'état du serveur et la documentation OpenAPI servie par
# FastAPI (aucune donnée de Nexus). Le WebSocket exige un ticket à usage unique (#57) : sans
# ticket, la connexion est refusée avant l'acceptation.
OPEN_REST = {("GET", "/api/health")}
OPEN_WEBSOCKETS: set[str] = set()
OPEN_STATIC = {"/openapi.json", "/docs", "/docs/oauth2-redirect", "/redoc"}


def flat_routes(routes, prefix=""):
    """(chemin complet, route) pour toutes les routes, préfixes des `include_router` cumulés.

    FastAPI 0.141 n'aplatit pas les routeurs inclus : `route.path` seul perdrait le préfixe.
    """
    for route in routes:
        inner = getattr(route, "original_router", None)
        if inner is not None:
            yield from flat_routes(inner.routes, prefix + route.include_context.prefix)
        else:
            yield prefix + getattr(route, "path", ""), route


def all_routes(app: FastAPI):
    """Routes normales puis routes à basse priorité (`app.frontend()`), routeurs inclus compris."""
    yield from flat_routes(app.routes)
    low = getattr(app.router, "_iter_low_priority_routes", None)
    if low is not None:
        for route in low():
            route = getattr(route, "original_route", route)
            for leaf in getattr(route, "routes", [route]):  # un groupe `frontend` en contient
                yield getattr(leaf, "path", "") or "", leaf


def fill(path):
    for part in [p[1:-1] for p in path.split("/") if p.startswith("{")]:
        path = path.replace("{" + part + "}", "x")
    return path


def websocket_refused(client, path) -> bool:
    """True when a connection without any ticket is closed with 1008 before being accepted."""
    try:
        with client.websocket_connect(fill(path)):
            return False  # accepted: the route is open
    except WebSocketDisconnect as closed:
        return closed.code == 1008
    except Exception:
        return False


def unauthenticated_routes(app: FastAPI, client) -> list[str]:
    """Routes qui répondent sans jeton, hors liste blanche (vide si tout est verrouillé)."""
    offenders = []
    for path, route in all_routes(app):
        if isinstance(route, APIRoute):
            for method in sorted(route.methods - {"HEAD", "OPTIONS"}):
                if (method, path) in OPEN_REST:
                    continue
                res = client.request(method, fill(path), json={})
                ok = res.status_code == 401 and res.json()["detail"]["code"] == "auth_required"
                if not ok:
                    offenders.append(f"{method} {path} → {res.status_code}")
        elif isinstance(route, APIWebSocketRoute):
            if path not in OPEN_WEBSOCKETS and not websocket_refused(client, path):
                offenders.append(f"WS {path}")
        elif path not in OPEN_STATIC:
            offenders.append(f"{type(route).__name__} {path}")
    return offenders


def test_every_route_requires_a_token_except_the_allow_list(anonymous):
    assert unauthenticated_routes(anonymous.app, anonymous) == []


def test_the_walker_sees_every_router(anonymous):
    seen = {(m, p) for p, r in flat_routes(anonymous.app.routes) if isinstance(r, APIRoute)
            for m in r.methods}
    for expected in [
        ("GET", "/api/health"), ("GET", "/api/nodes"), ("GET", "/api/now"),
        ("POST", "/api/tasks"), ("POST", "/api/events"),
        ("POST", "/api/approvals/{approval_ref}/answer"), ("POST", "/api/ws-ticket"),
    ]:
        assert expected in seen, expected
    assert any(isinstance(r, APIWebSocketRoute) for _, r in flat_routes(anonymous.app.routes))


def test_a_route_added_without_a_token_fails_the_invariant(settings, tmp_path):
    from conftest import ActorClient

    app = create_app(settings, nodes_runner=tailscale_json)

    @app.get("/api/oops")
    def oops() -> dict:
        return {}

    @app.websocket("/api/oops-ws")
    async def oops_ws(websocket: WebSocket) -> None:
        await websocket.accept()  # an open route: accepted without any ticket

    app.mount("/static-oops", FastAPI())
    v2 = APIRouter()
    sub = APIRouter(prefix="/sub")

    @v2.get("/open")
    def v2_open() -> dict:
        return {}

    @sub.get("/deep")
    def sub_deep() -> dict:
        return {}

    v2.include_router(sub, prefix="/inner")
    app.include_router(v2, prefix="/v2")
    app.frontend("/ui", directory=str(tmp_path), check_dir=False)
    with ActorClient(app, authenticate=False) as client:
        offenders = unauthenticated_routes(app, client)
    assert any(o.startswith("GET /api/oops ") for o in offenders)
    assert "WS /api/oops-ws" in offenders
    assert any("/static-oops" in o for o in offenders)
    assert any(o.startswith("GET /v2/open ") for o in offenders)
    assert any(o.startswith("GET /v2/inner/sub/deep ") for o in offenders)
    assert any("/ui" in o for o in offenders)


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


def test_the_websocket_requires_a_ticket(anonymous):
    with pytest.raises(WebSocketDisconnect) as closed:
        with anonymous.websocket_connect("/api/ws"):
            pass
    assert closed.value.code == 1008 and closed.value.reason == ""
