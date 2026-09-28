import pytest
from fastapi.testclient import TestClient

from nexus.app import create_app
from nexus.config import Settings


@pytest.fixture
def settings(tmp_path) -> Settings:
    return Settings(data_dir=tmp_path / "data")


@pytest.fixture
def client(settings):
    with TestClient(create_app(settings)) as client:
        yield client
