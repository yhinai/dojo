import json

import pytest

from herd.integrations.aria import export_bundle, import_analysis
from herd.integrations.weave import WeaveIntegration, behavioral_scores


def test_outbox_preserves_pending_and_deduplicates(tmp_path):
    adapter = WeaveIntegration(None, tmp_path)
    adapter.enqueue("event", "event-1", {"a": 1})
    adapter.enqueue("event", "event-1", {"a": 1})
    assert len(adapter.status()) == 1
    assert adapter.flush()["uploaded"] == 0
    assert adapter.status()[0]["status"] == "pending"
    with pytest.raises(ValueError):
        adapter.enqueue("event", "event-1", {"a": 2})
    assert WeaveIntegration(None, tmp_path).status()[0]["attempts"] == 1


def test_outbox_real_ack_only(tmp_path, monkeypatch):
    class Ref:
        def uri(self):
            return "weave:///entity/project/object/evidence:digest"

    class SDK:
        def publish(self, payload, name):
            assert payload["local_evidence_id"] == "e"
            return Ref()

    adapter = WeaveIntegration("entity/project", tmp_path)
    monkeypatch.setattr(adapter, "connect", lambda: SDK())
    adapter.enqueue("event", "e", {"measured": True})
    assert adapter.flush()["uploaded"] == 1
    assert adapter.flush()["uploaded"] == 0
    assert adapter.status()[0]["remote_ref"].startswith("weave:///")


def test_scorer_missing_not_passing():
    assert behavioral_scores({"run_id": "x"})["passed"] is None
    output = {"run_id": "x", "result": {"checks": [{"name": "semantic", "passed": True}]}}
    assert behavioral_scores(output)["passed"] is True
    assert behavioral_scores(output, "interaction_probe")["passed"] is None
    output["result"]["infrastructure_error"] = "crash"
    assert behavioral_scores(output)["passed"] is False


def test_aria_honest_handoff_and_integrity(tmp_path):
    with pytest.raises(ValueError):
        export_bundle("e", {"partition": "final"}, tmp_path)
    path = export_bundle("e", {"partition": "development", "events": []}, tmp_path)
    record = import_analysis(
        path,
        "Actual report content",
        "https://wandb.ai/team/project/aria/report",
        "operator",
        "Add form tasks next development round",
    )
    assert record["verification"] == "operator_attested_manual_import"
    with pytest.raises(ValueError):
        import_analysis(path, "text", "https://wandb.ai.evil.test/report", "operator", "action")
    data = json.loads(path.read_text())
    data["summary"]["events"] = ["changed"]
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError):
        import_analysis(path, "text", "https://wandb.ai/report", "operator", "action")


def test_trace_redacts_credentials_and_runtime_objects(monkeypatch):
    from herd.integrations.weave import sanitize_trace

    monkeypatch.setenv("TEST_API_KEY", "private-key-value")
    output = sanitize_trace(
        {
            "self": object(),
            "api_key": "private-key-value",
            "nested": {"source": 'print("private-key-value")', "messages": [{"secret": "value"}]},
            "record": object(),
        }
    )
    assert "self" not in output
    assert "api_key" not in output
    assert "messages" not in output["nested"]
    assert "private-key-value" not in str(output)


@pytest.mark.asyncio
async def test_automatic_sweep_recovers_without_credentials(tmp_path, monkeypatch):
    from herd.store import Store

    store = Store(tmp_path / "herd.sqlite3")
    store.put("e", "pool", "p", {"pool_hash": "p", "lessons": []})
    adapter = WeaveIntegration(None, tmp_path)
    first = await adapter.sync_store(store, "e")
    assert first["status"] == "pending_configuration"
    assert len(adapter.status()) == 1
    await WeaveIntegration(None, tmp_path).sync_store(store, "e")
    assert len(adapter.status()) == 1
    store.put("e", "attempt", "test", {"run_id": "test", "mode": "test"})
    assert (await adapter.sync_store(store, "e"))["status"] == "fixture_experiment_excluded"


@pytest.mark.asyncio
async def test_recovered_upload_creates_authentic_local_link(tmp_path, monkeypatch):
    from herd.store import Store

    store = Store(tmp_path / "herd.sqlite3")
    store.put("e", "pool", "p", {"pool_hash": "p", "lessons": []})
    monkeypatch.setenv("WANDB_API_KEY", "test-key-not-real")
    adapter = WeaveIntegration("team/project", tmp_path)

    class Ref:
        def uri(self):
            return "weave:///team/project/object/p:real-sdk-ack"

    class SDK:
        def publish(self, payload, name):
            return Ref()

    monkeypatch.setattr(adapter, "connect", lambda: SDK())
    await adapter.sync_store(store, "e")
    assert store.list("e", "weave_link")[0]["remote_ref"].endswith("real-sdk-ack")
    event_count = len(store.events("e"))
    await adapter.sync_store(store, "e")
    assert len(store.events("e")) == event_count


@pytest.mark.asyncio
async def test_live_evaluation_rows_and_privacy(monkeypatch):
    import weave
    from herd.integrations.weave import log_execution_pair, sanitize_trace
    from herd.schemas import AttemptRecord
    from weave.trace.context import weave_client_context

    monkeypatch.setattr(weave_client_context, "get_weave_client", lambda: object())
    calls = []

    class Row:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def log_score(self, name, score):
            calls.append(("score", name, score))

    class Logger:
        def __init__(self, **kwargs):
            calls.append(("init", kwargs))

        def log_prediction(self, **kwargs):
            calls.append(("row", kwargs))
            return Row()

        def log_summary(self):
            calls.append(("summary",))

    monkeypatch.setattr(weave, "EvaluationLogger", Logger)
    record = AttemptRecord(run_id="r", task_id="t", learner_id="learner-1", round_id=1, pool_hash="p")
    assert (await log_execution_pair("pair", [record]))["status"] == "logged"
    assert calls[1][1]["example_id"] == "r"
    monkeypatch.setenv("HERD_TRACE_CONVERSATIONS", "1")
    monkeypatch.setenv("TEST_API_KEY", "long-private-secret")
    value = sanitize_trace({"messages": [{"role": "user", "content": "learn marimo long-private-secret"}]})
    assert value["messages"][0]["content"] == "learn marimo [REDACTED]"


@pytest.mark.asyncio
async def test_live_evaluation_real_sdk_without_client():
    from herd.integrations.weave import log_execution_pair
    from herd.schemas import AttemptRecord

    record = AttemptRecord(run_id="r", task_id="t", learner_id="l", round_id=1, pool_hash="p")
    assert (await log_execution_pair("offline", [record]))["status"] == "unconfigured"
