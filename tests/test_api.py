from fastapi.testclient import TestClient

from herd.api import create_app
from herd.store import Store


def test_readonly_api_empty_and_auth(tmp_path):
    store = Store(tmp_path / "state.db")
    client = TestClient(create_app(store, demo=True))
    assert client.get("/api/experiments").json() == []
    assert client.get("/api/experiments/missing").status_code == 404
    assert client.post("/api/experiments").status_code == 403
    assert client.get("/api/health").json()["demo"] is True
    client = TestClient(create_app(store))
    assert client.post("/api/experiments").status_code == 401


def test_private_reads_and_controls(tmp_path, monkeypatch):
    monkeypatch.setenv("HERD_AUTH_READS", "1")
    monkeypatch.setenv("HERD_CONTROL_TOKEN", "operator-secret")
    store = Store(tmp_path / "state.db")
    store.put("e", "experiment", "e", {"id": "e", "status": "running"})
    client = TestClient(create_app(store))
    headers = {"X-Herd-Token": "operator-secret"}
    assert client.get("/api/health").status_code == 200
    assert client.get("/api/experiments").status_code == 401
    assert client.get("/api/experiments", headers=headers).status_code == 200
    assert client.post("/api/experiments/e/pause").status_code == 401
    assert client.post("/api/experiments/e/pause", headers=headers).status_code == 200
    assert store.control("e")["action"] == "pause"
    assert store.get("e", "experiment", "e")["status"] == "paused"
    assert client.post("/api/experiments/e/cancel", headers=headers).status_code == 200
    assert store.get("e", "experiment", "e")["status"] == "cancelled"
    assert client.post("/api/experiments/e/cancel", headers=headers).status_code == 409
    assert (
        client.post(
            "/api/experiments/e/lifecycle", headers=headers, json={"action": "delete_everything"}
        ).status_code
        == 422
    )
