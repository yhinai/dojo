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


def test_startup_recovers_abandoned_but_preserves_external_scheduler(tmp_path):
    store = Store(tmp_path / "state.db")
    store.put("e", "experiment", "e", {"id": "e", "status": "running"})
    with store.execution_lock(), TestClient(create_app(store, demo=True)):
        assert store.get("e", "experiment", "e")["status"] == "running"
    with TestClient(create_app(store, demo=True)):
        assert store.get("e", "experiment", "e")["status"] == "paused"
    assert store.events("e")[-1]["event_type"] == "recovery.abandoned_scheduler"


def test_pagination_artifacts_and_readiness(tmp_path, monkeypatch):
    monkeypatch.setenv("HERD_AUTH_READS", "1")
    monkeypatch.setenv("HERD_CONTROL_TOKEN", "token")
    monkeypatch.setattr(
        "herd.config.runtime_readiness",
        lambda engine: {
            "engine_configured": False,
            "docker_runtime_available": True,
            "browser_binary_available": False,
        },
    )
    store = Store(tmp_path / "state.db")
    store.put("e", "experiment", "e", {"id": "e", "status": "paused"})
    for i in range(4):
        store.put(
            "e",
            "attempt",
            str(i),
            {"run_id": str(i), "source": "sensitive code", "messages": ["conversation"]},
        )
    client = TestClient(create_app(store, demo=True))
    headers = {"X-Herd-Token": "token"}
    assert client.get("/api/experiments/e/attempts/0").status_code == 401
    page = client.get("/api/experiments/e/attempts?limit=2&offset=1", headers=headers).json()
    assert [v["run_id"] for v in page["items"]] == ["1", "2"]
    assert page["total"] == 4 and page["next_offset"] == 3
    assert "source" not in str(page)
    assert "sensitive code" not in client.get("/api/experiments/e", headers=headers).text
    assert client.get("/api/experiments/e/attempts/0", headers=headers).json()["source"] == "sensitive code"
    events = client.get("/api/experiments/e/events?limit=2&after=1", headers=headers).json()
    assert [e["sequence"] for e in events["items"]] == [2, 3]
    assert not client.get("/api/readiness", headers=headers).json()["ready"]
    assert client.get("/api/health").json()["status"] == "ok"
    assert client.get("/api/experiments/e/attempts?limit=100000", headers=headers).status_code == 422


def test_pause_external_worker_waits_for_checkpoint(tmp_path, monkeypatch):
    monkeypatch.setenv("HERD_CONTROL_TOKEN", "token")
    store = Store(tmp_path / "state.db")
    store.put("e", "experiment", "e", {"id": "e", "status": "running"})
    client = TestClient(create_app(store))
    with store.execution_lock():
        response = client.post("/api/experiments/e/pause", headers={"X-Herd-Token": "token"})
        assert response.status_code == 200
        assert store.get("e", "experiment", "e")["status"] == "running"
        assert store.control("e")["action"] == "pause"


def test_collection_pages_and_readiness_http_status(tmp_path, monkeypatch):
    store = Store(tmp_path / "s.db")
    store.put("e", "experiment", "e", {"id": "e", "status": "paused"})
    for i in range(3):
        store.put("e", "weave_link", str(i), {"local_id": str(i)})
    monkeypatch.setattr("herd.config.runtime_readiness", lambda engine: {"engine_configured": False})
    client = TestClient(create_app(store, demo=True))
    assert client.get("/api/readiness").status_code == 503
    assert client.get("/api/experiments/e/collections/weave_link?offset=1&limit=1").json()["items"] == [
        {"local_id": "1"}
    ]
    assert client.get("/api/experiments/e/collections/attempt").status_code == 404
    assert client.get("/api/experiments/e").json()["collection_pages"]["weave_link"]["total"] == 3


def test_readiness_requires_browser_launch_and_healthy_database(tmp_path, monkeypatch):
    from types import SimpleNamespace

    store = Store(tmp_path / "s.db")
    monkeypatch.setattr(
        "herd.config.runtime_readiness",
        lambda engine: {
            "engine_configured": True,
            "provider_credentials_configured": True,
            "docker_runtime_available": True,
            "browser_binary_available": True,
        },
    )

    class Evaluator:
        ready = False
        calls = []

        async def preflight(self, browser=False):
            self.calls.append(browser)
            return {"ready": self.ready, "secure_for_generated_code": True, "browser": {"ready": self.ready}}

    evaluator = Evaluator()
    client = TestClient(
        create_app(store, engine=SimpleNamespace(learner=SimpleNamespace(evaluator=evaluator)))
    )
    response = client.get("/api/readiness")
    assert response.status_code == 503
    assert not response.json()["checks"]["browser_launch_ready"]
    evaluator.ready = True
    assert client.get("/api/readiness").status_code == 200
    monkeypatch.setattr(store, "health", lambda: {"database": "corrupt"})
    response = client.get("/api/readiness")
    assert response.status_code == 503
    assert not response.json()["checks"]["database_healthy"]
    assert evaluator.calls == [True, True, True]
