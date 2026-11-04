"""Shared fixtures and helpers for the example agent tests (EVENT-PROTOCOL 6 bis, 6 ter)."""

import pytest

from nexus import demo_agent


@pytest.fixture
def http(client, monkeypatch):
    """Route the agent's HTTP calls to the test app."""

    def call(_base, method, path, body=None):
        res = client.request(method, path, json=body)
        if res.status_code >= 400:
            raise SystemExit(f"refusé ({res.status_code}) : {res.json().get('detail')}")
        return res.json()

    monkeypatch.setattr(demo_agent, "call", call)
    return client


@pytest.fixture
def task(client):
    return client.post("/api/tasks", json={"title": "Pont", "objective": "Lire"}).json()["id"]


@pytest.fixture(autouse=True)
def _no_developer_token(monkeypatch):
    """The developer's own NEXUS_TOKEN must not leak into the agent under test."""
    monkeypatch.delenv("NEXUS_TOKEN", raising=False)


def run(*argv, **kwargs):
    return demo_agent.main(["--task", *argv], **kwargs)
