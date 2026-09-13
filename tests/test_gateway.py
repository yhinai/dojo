from concurrent.futures import ThreadPoolExecutor

import httpx
import pytest

from herd.gateway import BudgetExceeded, BudgetLedger, GatewayConfig, GatewayError, ProviderGateway


def test_atomic_budget_and_crash_reservations(tmp_path):
    ledger = BudgetLedger(tmp_path / "money.db", 1)

    def reserve(i):
        try:
            ledger.reserve(str(i), 0.6)
            return True
        except BudgetExceeded:
            return False

    with ThreadPoolExecutor(2) as executor:
        assert sum(executor.map(reserve, range(2))) == 1
    assert BudgetLedger(tmp_path / "money.db", 1).summary()["committed_usd"] == 0.6
    ledger.settle("0" if reserve_id(ledger) == "0" else "1", 0.2)
    assert ledger.summary()["committed_usd"] == 0.2


def reserve_id(ledger):
    with ledger._connect() as db:
        return db.execute("SELECT request_id FROM inference_budget").fetchone()[0]


@pytest.mark.asyncio
async def test_usage_settlement_and_no_secret_error(tmp_path):
    ledger = BudgetLedger(tmp_path / "money.db", 1)

    def response(request):
        assert request.headers["Authorization"] == "Bearer secret-value"
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": "hello"}}],
                "usage": {"prompt_tokens": 4, "completion_tokens": 2},
            },
        )

    gateway = ProviderGateway(GatewayConfig(api_key="secret-value"), ledger, httpx.MockTransport(response))
    completion = await gateway.complete([{"role": "user", "content": "hi"}], 10, "one")
    assert completion.cost_usd == pytest.approx((4 * 0.13 + 2 * 0.28) / 1e6)
    assert ledger.summary()["pending_requests"] == 0
    assert await gateway.complete([{"role": "user", "content": "hi"}], 10, "one") == completion
    with pytest.raises(GatewayError, match="different inputs"):
        await gateway.complete([], 10, "one")
    assert "secret-value" not in repr(gateway.config)


@pytest.mark.asyncio
async def test_unknown_http_outcome_retains_reservation(tmp_path):
    ledger = BudgetLedger(tmp_path / "money.db", 1)
    gateway = ProviderGateway(
        GatewayConfig(api_key="secret"),
        ledger,
        httpx.MockTransport(lambda req: httpx.Response(500, text="secret")),
    )
    with pytest.raises(GatewayError, match="HTTP 500"):
        await gateway.complete([], 10, "one")
    assert ledger.summary()["pending_requests"] == 1
    assert ledger.summary()["committed_usd"] > 0


def test_other_model_requires_own_prices(monkeypatch):
    monkeypatch.setenv("HERD_MODEL", "different")
    for key in ("HERD_INPUT_PRICE_PER_MILLION", "HERD_OUTPUT_PRICE_PER_MILLION", "HERD_PRICING_SOURCE"):
        monkeypatch.delenv(key, raising=False)
    with pytest.raises(ValueError, match="explicit verified pricing"):
        GatewayConfig.from_env()


def test_gateway_uses_canonical_wandb_project(monkeypatch):
    monkeypatch.delenv("HERD_WEAVE_PROJECT", raising=False)
    monkeypatch.setenv("WANDB_ENTITY", "team")
    monkeypatch.setenv("WANDB_PROJECT", "project")
    assert GatewayConfig.from_env().project == "team/project"


@pytest.mark.asyncio
async def test_reconciled_retry_preserves_original_charge_and_caches(tmp_path):
    ledger = BudgetLedger(tmp_path / "budget.db", 1)
    responses = iter(
        [
            httpx.Response(500),
            httpx.Response(
                200,
                json={
                    "choices": [{"message": {"content": "recovered"}}],
                    "usage": {"prompt_tokens": 4, "completion_tokens": 2},
                },
            ),
        ]
    )
    gateway = ProviderGateway(
        GatewayConfig(api_key="secret"), ledger, httpx.MockTransport(lambda req: next(responses))
    )
    with pytest.raises(GatewayError):
        await gateway.complete([], 10, "run:turn:0")
    ledger.reconcile(
        "run:turn:0", 0.001, "Provider support invoice 123 request abc", "operator", authorize_retry=True
    )
    result = await gateway.complete([], 10, "run:turn:0")
    assert result.content == "recovered"
    assert ledger.summary()["committed_usd"] == pytest.approx(0.001 + result.cost_usd)
    assert len(ledger.entries()) == 2
    assert await gateway.complete([], 10, "run:turn:0") == result


def test_retry_can_be_authorized_after_reconciliation(tmp_path):
    ledger = BudgetLedger(tmp_path / "budget.db", 1)
    ledger.reserve("run:turn:0", 0.1)
    ledger.reconcile("run:turn:0", 0.02, "Invoice INV-12 from provider", "billing")
    with pytest.raises(GatewayError, match="explicitly authorize"):
        ledger.physical_request_id("run:turn:0")
    ledger.reconcile(
        "run:turn:0", 0.02, "Reviewed incident INC-22; permit retry", "operator", authorize_retry=True
    )
    assert ledger.physical_request_id("run:turn:0") == "run:turn:0:retry:1"
    assert ledger.summary()["committed_usd"] == 0.02
    with ledger._connect() as db:
        assert db.execute("SELECT count(*) FROM inference_reconciliations").fetchone()[0] == 1
        assert db.execute("SELECT count(*) FROM inference_retry_authorizations").fetchone()[0] == 1
