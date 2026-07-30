"""Behavioral tests for route-aware OpenRouter endpoint pricing.

These tests pin the contract that cost estimation, pre-dispatch reservation,
recorded actual cost, estimate display, and result identity for explicitly
routed OpenRouter treatments use the *selected endpoint's* rate -- taking the
conservative maximum across allowed ordered providers -- instead of the
model-level ``genai_prices`` catalog rate. Local llama.cpp/Ollama stays zero
cost, and unknown routes still require an explicit positive per-call maximum.

They fail against the old model-level accounting (missing symbols / config
field / route branching) and pass once route-aware pricing is fully wired
through pricing, config, runner, and the estimate display.

Regression pins (owner-supplied): the current Kimi slug is
``moonshotai/kimi-k2.6`` and its SiliconFlow endpoint bills 0.77/3.40 USD per
million -- distinct from the model-level catalog -- and MiMo is pinned to
provider ``Xiaomi``. No paid model is ever called: ``fetch_openrouter_endpoints``
and the LLM client are always mocked.
"""

from io import StringIO
from typing import TypedDict
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from nohiki_llm_client import ApiKeyRegistry, LLMModelConfig
from pydantic import SecretStr
from rich.console import Console

from llm_benchmark.config.constants import (
    ESTIMATED_INPUT_TOKENS_PER_CALL,
    ESTIMATED_OUTPUT_TOKENS_PER_CALL,
)
from llm_benchmark.config.models import BenchmarkConfig
from llm_benchmark.engine import runner as runner_module
from llm_benchmark.engine.runner import BenchmarkRunner, experiment_fingerprint, treatment_ids
from llm_benchmark.pricing import (
    EndpointRate,
    PricingRouteError,
    PricingSnapshot,
    fetch_openrouter_endpoints,
    get_per_million_prices,
    resolve_pricing_snapshot,
)

_FETCH_TARGET = "llm_benchmark.pricing.fetch_openrouter_endpoints"
_HTTPX_GET_TARGET = "llm_benchmark.pricing.httpx.get"

# Owner-pinned regression fixture: Kimi routed to SiliconFlow.
KIMI_SLUG = "moonshotai/kimi-k2.6"
KIMI_MODEL = f"openrouter:{KIMI_SLUG}"
SILICONFLOW_IN = 0.77
SILICONFLOW_OUT = 3.40


def _routed(
    model: str,
    providers: tuple[str, ...],
    *,
    allow_fallbacks: bool = False,
    api_key: str | None = None,
    base_url: str | None = None,
) -> LLMModelConfig:
    """Build an OpenRouter treatment pinned to explicit provider(s)."""
    return LLMModelConfig(
        model=model,
        provider_order=providers,
        provider_allow_fallbacks=allow_fallbacks,
        api_key=SecretStr(api_key) if api_key is not None else None,
        base_url=base_url,
    )


def _kimi_endpoints() -> tuple[EndpointRate, ...]:
    """SiliconFlow route plus decoy endpoints that must never win the lookup."""
    return (
        EndpointRate("Together", 9.99, 9.99),
        EndpointRate("SiliconFlow", SILICONFLOW_IN, SILICONFLOW_OUT),
        EndpointRate("DeepInfra", 0.01, 0.02),
    )


def _endpoint_snapshot(
    input_per_million: float,
    output_per_million: float,
    *,
    provider: str = "SiliconFlow",
) -> PricingSnapshot:
    """Build a routed ``openrouter_endpoint`` snapshot for one provider rate."""
    return PricingSnapshot(
        input_per_million,
        output_per_million,
        "openrouter_endpoint",
        (EndpointRate(provider, input_per_million, output_per_million),),
    )


def _mock_client() -> MagicMock:
    """LLM client whose run() returns a fixed, cheap extraction result."""
    usage = MagicMock()
    usage.input_tokens = 100
    usage.output_tokens = 50
    usage.cache_read_tokens = 0
    usage.cache_write_tokens = 0
    usage.requests = 1
    usage.tool_calls = 0
    usage.details = {"reasoning_tokens": 0}
    output = MagicMock()
    output.model_dump.return_value = {"cleaned_title": "Software Engineer"}
    run_result = MagicMock()
    run_result.output = output
    run_result.usage = usage
    run_result.retry_count = 0
    run_result.cost_usd = None
    client = MagicMock()
    client.run = AsyncMock(return_value=run_result)
    client.create_agent.return_value = MagicMock()
    return client


def _config(
    *,
    models: tuple[LLMModelConfig, ...],
    fixture_ids: list[str] | None = None,
    runs_per_fixture: int = 1,
    pricing_snapshots: tuple[PricingSnapshot, ...] = (),
) -> BenchmarkConfig:
    """Benchmark config with a finite reservation bound and generous cap."""
    return BenchmarkConfig(
        models=models,
        fixture_ids=["senior_python_remote"] if fixture_ids is None else fixture_ids,
        runs_per_fixture=runs_per_fixture,
        api_keys=ApiKeyRegistry.model_validate({"openrouter": "test-key"}),
        max_tokens=256,
        cost_cap_usd=1000.0,
        unknown_price_max_usd=0.1,
        pricing_snapshots=pricing_snapshots,
    )


class _EndpointPricing(TypedDict):
    """OpenRouter endpoint pricing payload used by response fixtures."""

    prompt: str | None
    completion: str | None


class _EndpointPayload(TypedDict):
    """OpenRouter endpoint payload used by response fixtures."""

    provider_name: str
    pricing: _EndpointPricing


class TestFetchOpenrouterEndpoints:
    """The endpoint metadata fetch keeps the author/model slash and scales pricing."""

    def _response(self, endpoints: list[_EndpointPayload]) -> MagicMock:
        response = MagicMock()
        response.raise_for_status.return_value = None
        response.json.return_value = {"data": {"endpoints": endpoints}}
        return response

    def test_url_preserves_unescaped_model_slug_slash(self) -> None:
        response = self._response(
            [{"provider_name": "SiliconFlow", "pricing": {"prompt": "0.00000077", "completion": "0.0000034"}}]
        )
        with patch(_HTTPX_GET_TARGET, return_value=response) as get_mock:
            rates = fetch_openrouter_endpoints(KIMI_SLUG, api_key=None)

        assert get_mock.call_args.args[0] == f"https://openrouter.ai/api/v1/models/{KIMI_SLUG}/endpoints"
        assert get_mock.call_args.kwargs["headers"] == {}
        assert len(rates) == 1
        assert rates[0].provider_name == "SiliconFlow"
        assert rates[0].input_per_million_usd == pytest.approx(SILICONFLOW_IN)
        assert rates[0].output_per_million_usd == pytest.approx(SILICONFLOW_OUT)

    def test_api_key_sets_bearer_header(self) -> None:
        with patch(_HTTPX_GET_TARGET, return_value=self._response([])) as get_mock:
            fetch_openrouter_endpoints(KIMI_SLUG, api_key="secret-token")

        assert get_mock.call_args.kwargs["headers"] == {"Authorization": "Bearer secret-token"}

    def test_endpoints_without_pricing_are_skipped(self) -> None:
        endpoints: list[_EndpointPayload] = [
            {"provider_name": "NoPrice", "pricing": {"prompt": None, "completion": "0.0000034"}},
            {"provider_name": "SiliconFlow", "pricing": {"prompt": "0.00000077", "completion": "0.0000034"}},
        ]
        with patch(_HTTPX_GET_TARGET, return_value=self._response(endpoints)):
            rates = fetch_openrouter_endpoints(KIMI_SLUG)

        assert [rate.provider_name for rate in rates] == ["SiliconFlow"]


class TestResolveExactRoute:
    """A pinned single-provider route prices from that exact endpoint."""

    def test_kimi_siliconflow_uses_endpoint_rate_not_model_level(self) -> None:
        model = _routed(KIMI_MODEL, ("SiliconFlow",))
        with patch(_FETCH_TARGET, return_value=_kimi_endpoints()) as fetch_mock:
            snap = resolve_pricing_snapshot(model)

        assert snap.source == "openrouter_endpoint"
        assert snap.per_million() == (SILICONFLOW_IN, SILICONFLOW_OUT)
        assert EndpointRate("SiliconFlow", SILICONFLOW_IN, SILICONFLOW_OUT) in snap.endpoints
        # The decoy endpoints (higher AND lower) never leak into the price.
        assert snap.per_million() != (9.99, 9.99)
        # Exactly one preflight fetch, addressed by the slash-preserving slug.
        assert fetch_mock.call_count == 1
        assert fetch_mock.call_args.args[0] == KIMI_SLUG
        # The whole point: the endpoint rate differs from the catalog rate.
        assert snap.per_million() != get_per_million_prices(model.model)

    def test_route_snapshot_passes_model_api_key_and_base_url_to_fetch(self) -> None:
        model = _routed(KIMI_MODEL, ("SiliconFlow",), api_key="k", base_url="https://provider.example.test/v1")
        with patch(_FETCH_TARGET, return_value=_kimi_endpoints()) as fetch_mock:
            resolve_pricing_snapshot(model)

        assert fetch_mock.call_args.kwargs["api_key"] == "k"
        assert fetch_mock.call_args.kwargs["base_url"] == "https://provider.example.test/v1"

    def test_mimo_pinned_to_xiaomi_uses_xiaomi_endpoint(self) -> None:
        model = _routed("openrouter:mimo/mimo-7b", ("Xiaomi",))
        endpoints = (EndpointRate("Xiaomi", 0.50, 1.00), EndpointRate("Other", 8.0, 9.0))
        with patch(_FETCH_TARGET, return_value=endpoints) as fetch_mock:
            snap = resolve_pricing_snapshot(model)

        assert snap.source == "openrouter_endpoint"
        assert snap.per_million() == (0.50, 1.00)
        assert fetch_mock.call_args.args[0] == "mimo/mimo-7b"

    def test_generic_slug_preserves_multi_slash_path(self) -> None:
        model = _routed("openrouter:vendor-x/family/model-y", ("RouteA",))
        endpoints = (EndpointRate("RouteA", 1.0, 2.0),)
        with patch(_FETCH_TARGET, return_value=endpoints) as fetch_mock:
            resolve_pricing_snapshot(model)

        assert fetch_mock.call_args.args[0] == "vendor-x/family/model-y"


class TestResolveMaxAcrossProviders:
    """Multiple allowed ordered providers reserve at the per-dimension maximum."""

    def test_conservative_max_taken_per_dimension(self) -> None:
        model = _routed("openrouter:generic/multi-route", ("RouteA", "RouteB"))
        endpoints = (
            EndpointRate("RouteA", 1.00, 2.00),
            EndpointRate("RouteB", 3.00, 0.50),
            EndpointRate("NotAllowed", 99.0, 99.0),
        )
        with patch(_FETCH_TARGET, return_value=endpoints):
            snap = resolve_pricing_snapshot(model)

        # max input across {1.0, 3.0} = 3.0; max output across {2.0, 0.5} = 2.0.
        assert snap.per_million() == (3.00, 2.00)
        # The unlisted provider's rate is ignored entirely.
        assert snap.per_million() != (99.0, 99.0)
        reserved = snap.maximum_call_cost(
            max_input_tokens=1_000_000,
            max_output_tokens=1_000_000,
            unknown_price_max_usd=None,
        )
        assert reserved == pytest.approx(3.00 + 2.00)
        # Audit trail retains exactly the matched providers.
        assert {rate.provider_name for rate in snap.endpoints} == {"RouteA", "RouteB"}


class TestMissingRoutePreflight:
    """An unmatched pinned provider fails before any call is dispatched."""

    def test_missing_route_raises_pricing_route_error(self) -> None:
        model = _routed(KIMI_MODEL, ("GhostProvider",))
        with patch(_FETCH_TARGET, return_value=_kimi_endpoints()), pytest.raises(PricingRouteError):
            resolve_pricing_snapshot(model)

    def test_pricing_route_error_is_a_value_error(self) -> None:
        assert issubclass(PricingRouteError, ValueError)

    def test_runner_construction_fails_fast_on_missing_route(self) -> None:
        config = _config(models=(_routed(KIMI_MODEL, ("GhostProvider",)),))
        with patch(_FETCH_TARGET, return_value=_kimi_endpoints()), pytest.raises(PricingRouteError):
            BenchmarkRunner(config)


class TestSingleFetchPerRun:
    """Endpoint metadata is fetched once per routed treatment, never per call."""

    @pytest.mark.asyncio
    async def test_metadata_not_refetched_across_fixtures_and_runs(self) -> None:
        endpoints_by_slug = {
            KIMI_SLUG: (EndpointRate("SiliconFlow", SILICONFLOW_IN, SILICONFLOW_OUT),),
            "mimo/mimo-7b": (EndpointRate("Xiaomi", 0.50, 1.00),),
        }

        def _fetch(
            model_slug: str,
            *,
            api_key: str | None = None,
            base_url: str | None = None,
        ) -> tuple[EndpointRate, ...]:
            _ = api_key, base_url
            return endpoints_by_slug[model_slug]

        config = _config(
            models=(
                _routed(KIMI_MODEL, ("SiliconFlow",)),
                _routed("openrouter:mimo/mimo-7b", ("Xiaomi",)),
                LLMModelConfig(model="llamacpp:local-candidate", base_url="https://model.example.test/v1"),
            ),
            fixture_ids=["senior_python_remote", "nurse_icu_onsite"],
            runs_per_fixture=2,
        )

        with patch(_FETCH_TARGET, side_effect=_fetch) as fetch_mock:
            runner = BenchmarkRunner(config)
            # Resolved once per routed treatment during construction; local does not fetch.
            assert fetch_mock.call_count == 2
            with patch.object(runner_module, "_create_client", return_value=_mock_client()):
                await runner.run()
            # 2 routed treatments x 2 fixtures x 2 runs never re-fetches.
            assert fetch_mock.call_count == 2
        assert {call.args[0] for call in fetch_mock.call_args_list} == {KIMI_SLUG, "mimo/mimo-7b"}


class TestKimiSiliconFlowParity:
    """Estimate, reservation, and recorded actual all bill at one endpoint rate."""

    def test_estimate_reservation_actual_share_the_route_rate(self) -> None:
        model = _routed(KIMI_MODEL, ("SiliconFlow",))
        with patch(_FETCH_TARGET, return_value=_kimi_endpoints()):
            snap = resolve_pricing_snapshot(model)

        assert snap.per_million() == (SILICONFLOW_IN, SILICONFLOW_OUT)

        def expected(input_tokens: int, output_tokens: int) -> float:
            return (input_tokens * SILICONFLOW_IN + output_tokens * SILICONFLOW_OUT) / 1_000_000

        total_calls = 3
        est_in = ESTIMATED_INPUT_TOKENS_PER_CALL * total_calls
        est_out = ESTIMATED_OUTPUT_TOKENS_PER_CALL * total_calls
        assert snap.calc_cost(est_in, est_out) == pytest.approx(expected(est_in, est_out))

        max_in, max_out = 40_000, 24_000
        reserved = snap.maximum_call_cost(
            max_input_tokens=max_in,
            max_output_tokens=max_out,
            unknown_price_max_usd=None,
        )
        assert reserved == pytest.approx(expected(max_in, max_out))

        # Recorded actual bills at the route rate on observed tokens, ignoring
        # whatever the client happened to report.
        act_in, act_out = 3_200, 480
        recorded = snap.recorded_cost(client_cost=999.0, input_tokens=act_in, output_tokens=act_out)
        assert recorded is not None
        assert recorded == pytest.approx(expected(act_in, act_out))
        assert recorded != pytest.approx(999.0)

        # Reservation is a conservative upper bound on the settled actual.
        assert reserved >= recorded
        # And none of the three collapses onto the model-level catalog rate.
        assert snap.per_million() != get_per_million_prices(model.model)


class TestPricingSnapshotFingerprintResume:
    """Pricing evidence is part of run identity, so a price change blocks resume."""

    def test_fingerprint_material_reflects_rate_and_source(self) -> None:
        base = _endpoint_snapshot(SILICONFLOW_IN, SILICONFLOW_OUT)
        same = _endpoint_snapshot(SILICONFLOW_IN, SILICONFLOW_OUT)
        bumped = _endpoint_snapshot(0.90, SILICONFLOW_OUT)
        assert base.fingerprint_material() == same.fingerprint_material()
        assert base.fingerprint_material() != bumped.fingerprint_material()

    def test_changed_route_price_invalidates_experiment_identity(self) -> None:
        model = _routed(KIMI_MODEL, ("SiliconFlow",))
        base = _config(models=(model,), pricing_snapshots=(_endpoint_snapshot(SILICONFLOW_IN, SILICONFLOW_OUT),))
        bumped = _config(models=(model,), pricing_snapshots=(_endpoint_snapshot(0.90, SILICONFLOW_OUT),))

        # Pre-resolved snapshots make identity computation fetch-free.
        with patch(_FETCH_TARGET, side_effect=AssertionError("must not fetch when snapshots are pre-resolved")):
            base_experiment, base_treatments = experiment_fingerprint(base)
            bumped_experiment, bumped_treatments = experiment_fingerprint(bumped)
            base_ids = treatment_ids(base)
            bumped_ids = treatment_ids(bumped)

        assert base_experiment != bumped_experiment
        assert base_treatments != bumped_treatments
        assert base_ids != bumped_ids

    def test_identical_route_price_keeps_stable_identity(self) -> None:
        model = _routed(KIMI_MODEL, ("SiliconFlow",))
        snap = _endpoint_snapshot(SILICONFLOW_IN, SILICONFLOW_OUT)
        first = _config(models=(model,), pricing_snapshots=(snap,))
        second = _config(models=(model,), pricing_snapshots=(snap,))
        with patch(_FETCH_TARGET, side_effect=AssertionError("must not fetch when snapshots are pre-resolved")):
            assert experiment_fingerprint(first)[0] == experiment_fingerprint(second)[0]


class TestGenericKnownPricing:
    """Non-routed cloud treatments keep model-level catalog behavior."""

    def test_genai_snapshot_arithmetic(self) -> None:
        snap = PricingSnapshot(0.30, 2.50, "genai_prices")
        assert snap.per_million() == (0.30, 2.50)
        assert snap.is_known is True
        assert snap.calc_cost(1_000_000, 1_000_000) == pytest.approx(2.80)
        assert snap.maximum_call_cost(
            max_input_tokens=1_000_000,
            max_output_tokens=1_000_000,
            unknown_price_max_usd=None,
        ) == pytest.approx(2.80)
        # Non-routed cloud keeps the client-reported actual cost.
        assert snap.recorded_cost(client_cost=1.23, input_tokens=10, output_tokens=5) == pytest.approx(1.23)

    def test_calc_cost_rejects_negative_tokens(self) -> None:
        snap = PricingSnapshot(1.0, 1.0, "genai_prices")
        with pytest.raises(ValueError, match="non-negative"):
            snap.calc_cost(-1, 0)
        with pytest.raises(ValueError, match="non-negative"):
            snap.calc_cost(0, -1)

    def test_allowed_fallbacks_route_uses_catalog_without_fetching(self) -> None:
        # provider_order set but fallbacks allowed => not an explicit route.
        model = LLMModelConfig(
            model="openrouter:moonshotai/kimi-k2",
            provider_order=("SiliconFlow",),
            provider_allow_fallbacks=True,
        )
        with patch(
            _FETCH_TARGET, side_effect=AssertionError("fallbacks-allowed must not fetch endpoints")
        ) as fetch_mock:
            snap = resolve_pricing_snapshot(model)

        assert fetch_mock.call_count == 0
        assert snap.source == "genai_prices"
        assert snap.per_million() == get_per_million_prices(model.model)

    def test_unrouted_openrouter_model_uses_catalog(self) -> None:
        model = LLMModelConfig(model="openrouter:moonshotai/kimi-k2")
        with patch(_FETCH_TARGET, side_effect=AssertionError("unrouted must not fetch endpoints")):
            snap = resolve_pricing_snapshot(model)

        assert snap.source == "genai_prices"
        assert snap.per_million() == get_per_million_prices(model.model)


class TestUnknownPriceBound:
    """Unknown pricing needs an explicit positive per-call maximum."""

    def test_unknown_snapshot_has_no_cost_and_requires_positive_max(self) -> None:
        snap = PricingSnapshot(None, None, "unknown")
        assert snap.per_million() == (None, None)
        assert snap.is_known is False
        assert snap.calc_cost(1_000, 500) is None
        with pytest.raises(ValueError, match="Pricing is unavailable"):
            snap.maximum_call_cost(max_input_tokens=1_000, max_output_tokens=500, unknown_price_max_usd=None)

    @pytest.mark.parametrize("bad_max", [0.0, -0.01])
    def test_unknown_snapshot_rejects_non_positive_max(self, bad_max: float) -> None:
        snap = PricingSnapshot(None, None, "unknown")
        with pytest.raises(ValueError, match="greater than zero"):
            snap.maximum_call_cost(max_input_tokens=1_000, max_output_tokens=500, unknown_price_max_usd=bad_max)

    def test_unknown_snapshot_reserves_the_owner_maximum(self) -> None:
        snap = PricingSnapshot(None, None, "unknown")
        reserved = snap.maximum_call_cost(
            max_input_tokens=1_000,
            max_output_tokens=500,
            unknown_price_max_usd=0.125,
        )
        assert reserved == pytest.approx(0.125)

    def test_unknown_snapshot_passes_through_client_cost(self) -> None:
        snap = PricingSnapshot(None, None, "unknown")
        assert snap.recorded_cost(client_cost=0.02, input_tokens=1, output_tokens=1) == pytest.approx(0.02)

    def test_unknown_model_resolves_to_unknown_source(self) -> None:
        model = LLMModelConfig(model="openrouter:nonexistent/model-xyz-99999")
        with patch(_FETCH_TARGET, side_effect=AssertionError("unknown model must not fetch endpoints")):
            snap = resolve_pricing_snapshot(model)

        assert snap.source == "unknown"
        assert snap.calc_cost(1_000, 500) is None


class TestLocalZeroCost:
    """llama.cpp and Ollama treatments are always zero cost, with no fetch."""

    @pytest.mark.parametrize(
        "model_str",
        ["llamacpp:local-candidate", "ollama:qwen3:30b"],
    )
    def test_local_provider_is_zero_cost(self, model_str: str) -> None:
        model = LLMModelConfig(model=model_str, base_url="https://model.example.test/v1")
        with patch(_FETCH_TARGET, side_effect=AssertionError("local must not fetch endpoints")) as fetch_mock:
            snap = resolve_pricing_snapshot(model)

        assert fetch_mock.call_count == 0
        assert snap.source == "local"
        assert snap.per_million() == (0.0, 0.0)
        assert snap.calc_cost(123_456, 78_910) == pytest.approx(0.0)
        assert snap.maximum_call_cost(
            max_input_tokens=10**9,
            max_output_tokens=10**9,
            unknown_price_max_usd=None,
        ) == pytest.approx(0.0)
        assert snap.recorded_cost(client_cost=5.0, input_tokens=100, output_tokens=50) == pytest.approx(0.0)


class TestEstimateDisplayRouteAware:
    """The CLI estimate display bills routed rows at the endpoint rate."""

    def _render(
        self,
        models: list[str | LLMModelConfig],
        fixtures: int,
        runs: int,
        snapshots: list[PricingSnapshot] | None,
    ) -> tuple[float, str]:
        import llm_benchmark.display.panels as panels_module

        buf = StringIO()
        original = panels_module.console
        panels_module.console = Console(file=buf, force_terminal=False, width=120)
        try:
            total = panels_module.display_cost_estimate(models, fixtures, runs, snapshots=snapshots)
        finally:
            panels_module.console = original
        return total, buf.getvalue()

    def test_estimate_uses_route_snapshot_rate(self) -> None:
        model = _routed(KIMI_MODEL, ("SiliconFlow",))
        snap = _endpoint_snapshot(SILICONFLOW_IN, SILICONFLOW_OUT)
        fixtures, runs = 2, 1
        total_calls = fixtures * runs
        expected = snap.calc_cost(
            ESTIMATED_INPUT_TOKENS_PER_CALL * total_calls,
            ESTIMATED_OUTPUT_TOKENS_PER_CALL * total_calls,
        )

        total, output = self._render([model], fixtures, runs, snapshots=[snap])

        assert total == pytest.approx(expected)
        assert KIMI_SLUG in output
        assert "0.770" in output
        assert "3.400" in output

    def test_route_estimate_differs_from_model_level_estimate(self) -> None:
        model = _routed(KIMI_MODEL, ("SiliconFlow",))
        snap = _endpoint_snapshot(SILICONFLOW_IN, SILICONFLOW_OUT)
        route_total, _ = self._render([model], 2, 1, snapshots=[snap])
        catalog_total, _ = self._render([KIMI_MODEL], 2, 1, snapshots=None)

        assert route_total != pytest.approx(catalog_total)
