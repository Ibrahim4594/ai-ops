from fastapi.testclient import TestClient

from app.main import app


def test_healthz() -> None:
    with TestClient(app) as client:
        response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_work() -> None:
    with TestClient(app) as client:
        response = client.get("/work")
    assert response.status_code == 200
    assert response.json() == {"status": "done"}
