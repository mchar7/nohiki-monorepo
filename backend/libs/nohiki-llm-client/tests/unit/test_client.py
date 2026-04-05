"""Unit tests for LLMClient."""

from dataclasses import dataclass
from typing import cast
from unittest.mock import MagicMock, patch

import pytest
from nohiki_llm_client.client import (
    DynamicAgentConfig,
    LLMClient,
    LLMResult,
    StructuredAgentConfig,
)
from nohiki_llm_client.client.core import (
    _model_supports_cache_point,
    _strip_cache_points,
)
from nohiki_llm_client.config.settings import (
    ApiKeyRegistry,
    LLMModelConfig,
    LLMProviderSettings,
    LLMSettings,
)
from pydantic import BaseModel, SecretStr
from pydantic_ai import Agent
from pydantic_ai.models.fallback import FallbackModel
from pydantic_ai.models.test import TestModel
from pydantic_ai.usage import RunUsage


@dataclass
class SampleContext:
    """Sample context for agents."""

    data: str


class SampleOutput(BaseModel):
    """Sample output model."""

    result: str


class TestLLMClientBuildModelChain:
    """Tests for _build_model_chain with fallback configuration."""

    def test_fallback_chain_creates_fallback_model(self) -> None:
        """When multiple models are configured, _build_model_chain returns a FallbackModel."""
        settings_with_chain = LLMSettings(
            provider=LLMProviderSettings(
                models=[
                    LLMModelConfig(model="openrouter:primary/model"),
                    LLMModelConfig(model="openai:gpt-4o"),
                ],
                api_keys=ApiKeyRegistry.model_validate(
                    {"openrouter": SecretStr("or-key"), "openai": SecretStr("oa-key")}
                ),
            )
        )
        client = LLMClient(settings_with_chain)
        client._settings.caching.enabled = False

        with patch("nohiki_llm_client.client.core.create_full_model_chain") as mock_factory:
            mock_factory.return_value = FallbackModel(TestModel(), TestModel())
            model = client._get_model()

        assert isinstance(model, FallbackModel)
        mock_factory.assert_called_once()


class TestLLMClientGetModel:
    """Tests for _get_model method."""

    def test_get_model_lazily_initializes(self, llm_settings: LLMSettings) -> None:
        """Creates model chain on first access."""
        client = LLMClient(llm_settings)
        client._settings.caching.enabled = False
        with patch("nohiki_llm_client.client.core.create_full_model_chain") as mock_factory:
            mock_factory.return_value = TestModel()
            model = client._get_model()
            assert model is not None
            mock_factory.assert_called_once()

    def test_get_model_caches(self, llm_settings: LLMSettings) -> None:
        """Model is cached after first call."""
        client = LLMClient(llm_settings)
        client._settings.caching.enabled = False
        with patch("nohiki_llm_client.client.core.create_full_model_chain") as mock_factory:
            mock_factory.return_value = TestModel()
            model1 = client._get_model()
            model2 = client._get_model()
            assert model1 is model2
            mock_factory.assert_called_once()


class TestLLMClientLifecycle:
    """Tests for deterministic ownership of model HTTP transports."""

    @pytest.mark.asyncio
    async def test_close_is_idempotent_for_single_model(self, llm_settings: LLMSettings) -> None:
        """A single model transport closes once and the cached model is released."""
        from unittest.mock import AsyncMock

        import httpx

        transport = MagicMock(spec=httpx.AsyncClient)

        def build(
            _provider: object,
            _caching: object,
            *,
            transport_clients: list[httpx.AsyncClient],
        ) -> TestModel:
            transport_clients.append(transport)
            return TestModel()

        client = LLMClient(llm_settings)
        transport.aclose = AsyncMock()
        with patch("nohiki_llm_client.client.core.create_full_model_chain", side_effect=build):
            client._get_model()

        await client.close()
        await client.close()

        transport.aclose.assert_awaited_once_with()
        assert client._model is None

    @pytest.mark.asyncio
    async def test_close_releases_every_fallback_transport(self, llm_settings: LLMSettings) -> None:
        """Fallback wrapper shape cannot hide any owned provider transport."""
        from unittest.mock import AsyncMock

        import httpx

        transports = [
            MagicMock(spec=httpx.AsyncClient),
            MagicMock(spec=httpx.AsyncClient),
        ]
        for transport in transports:
            transport.aclose = AsyncMock()

        def build(
            _provider: object,
            _caching: object,
            *,
            transport_clients: list[httpx.AsyncClient],
        ) -> FallbackModel:
            transport_clients.extend(transports)
            return FallbackModel(TestModel(), TestModel())

        client = LLMClient(llm_settings)
        with patch("nohiki_llm_client.client.core.create_full_model_chain", side_effect=build):
            assert isinstance(client._get_model(), FallbackModel)

        await client.close()

        for transport in transports:
            transport.aclose.assert_awaited_once_with()

    @pytest.mark.asyncio
    async def test_close_attempts_all_clients_and_retries_only_failures(
        self,
        llm_settings: LLMSettings,
    ) -> None:
        """A failed close is grouped and retained without re-closing successful peers."""
        from unittest.mock import AsyncMock

        import httpx

        failed = MagicMock(spec=httpx.AsyncClient)
        failed.aclose = AsyncMock(side_effect=[RuntimeError("close failed"), None])
        successful = MagicMock(spec=httpx.AsyncClient)
        successful.aclose = AsyncMock()
        client = LLMClient(llm_settings)
        client._transport_clients.extend([failed, successful])

        with pytest.raises(
            BaseExceptionGroup,
            match="Failed to close LLM model transports",
        ) as error:
            await client.close()

        assert len(error.value.exceptions) == 1
        assert isinstance(error.value.exceptions[0], RuntimeError)
        assert client._transport_clients == [failed]
        failed.aclose.assert_awaited_once_with()
        successful.aclose.assert_awaited_once_with()

        await client.close()
        await client.close()

        assert failed.aclose.await_count == 2
        successful.aclose.assert_awaited_once_with()
        assert client._transport_clients == []

    @pytest.mark.asyncio
    async def test_async_context_closes_transport_behind_instrumented_model(
        self,
        llm_settings: LLMSettings,
    ) -> None:
        """Instrumentation wrappers do not change public async ownership."""
        from unittest.mock import AsyncMock

        import httpx

        transport = MagicMock(spec=httpx.AsyncClient)
        transport.aclose = AsyncMock()
        instrumented_model = MagicMock()

        def build(
            _provider: object,
            _caching: object,
            *,
            transport_clients: list[httpx.AsyncClient],
        ) -> TestModel:
            transport_clients.append(transport)
            return TestModel()

        client = LLMClient(llm_settings)
        with (
            patch(
                "nohiki_llm_client.client.core.create_full_model_chain",
                side_effect=build,
            ),
            patch(
                "nohiki_llm_client.client.core.create_instrumented_model",
                return_value=instrumented_model,
            ),
        ):
            async with client as entered:
                assert entered is client
                assert entered._get_model() is instrumented_model

        transport.aclose.assert_awaited_once_with()
        assert client._model is None

    @pytest.mark.asyncio
    async def test_failed_construction_cleanup_retries_before_reallocation(
        self,
        llm_settings: LLMSettings,
    ) -> None:
        """A retained close failure is retried before another chain allocates."""
        from unittest.mock import AsyncMock

        import httpx

        failed_transport = MagicMock(spec=httpx.AsyncClient)
        failed_transport.aclose = AsyncMock(side_effect=[RuntimeError("close failed"), None])
        retry_transport = MagicMock(spec=httpx.AsyncClient)
        retry_transport.aclose = AsyncMock()
        build_count = 0

        def build(
            _provider: object,
            _caching: object,
            *,
            transport_clients: list[httpx.AsyncClient],
        ) -> TestModel:
            nonlocal build_count
            build_count += 1
            if build_count == 1:
                transport_clients.append(failed_transport)
                message = "fallback constructor failed"
                raise RuntimeError(message)
            assert failed_transport.aclose.await_count == 2
            transport_clients.append(retry_transport)
            return TestModel()

        client = LLMClient(llm_settings)
        with patch(
            "nohiki_llm_client.client.core.create_full_model_chain",
            side_effect=build,
        ):
            with pytest.raises(BaseExceptionGroup) as error:
                client._get_model()

            assert [str(exception) for exception in error.value.exceptions] == [
                "fallback constructor failed",
                "close failed",
            ]
            assert client._transport_clients == [failed_transport]

            assert isinstance(client._get_model(), TestModel)

        assert build_count == 2
        assert failed_transport.aclose.await_count == 2
        assert client._transport_clients == [retry_transport]

        await client.close()
        retry_transport.aclose.assert_awaited_once_with()


class TestLLMClientCreateAgent:
    """Tests for agent creation methods."""

    def test_create_agent(self, llm_settings: LLMSettings) -> None:
        """Creates structured output agent."""
        client = LLMClient(llm_settings)
        config = StructuredAgentConfig(
            deps_type=SampleContext,
            output_type=SampleOutput,
            system_prompt="Test prompt",
        )
        agent = client.create_agent(config)
        assert isinstance(agent, Agent)
        # PydanticAI Agent stores output_type in _output_type
        assert agent._output_type is SampleOutput

    def test_create_dynamic_schema_agent(self, llm_settings: LLMSettings) -> None:
        """Creates dynamic schema agent."""
        client = LLMClient(llm_settings)
        config = DynamicAgentConfig(
            deps_type=SampleContext,
            json_schema={"type": "object", "properties": {"foo": {"type": "string"}}},
            schema_name="DynamicFoo",
        )
        agent = client.create_dynamic_schema_agent(config)
        assert isinstance(agent, Agent)
        # Verify agent has output_type set (StructuredDict creates internal type)
        assert agent._output_type is not None

    def test_create_dynamic_schema_agent_with_system_prompt_fn(self, llm_settings: LLMSettings) -> None:
        """system_prompt_fn on DynamicAgentConfig is registered programmatically without decorator mutation."""
        client = LLMClient(llm_settings)
        config = DynamicAgentConfig(
            deps_type=SampleContext,
            json_schema={"type": "object", "properties": {"foo": {"type": "string"}}},
            schema_name="DynamicWithFn",
            system_prompt_fn=lambda ctx: f"prompt for {ctx.deps.data}",
        )
        agent = client.create_dynamic_schema_agent(config)
        assert isinstance(agent, Agent)
        assert len(agent._system_prompts) > 0


class TestLLMClientRun:
    """Tests for run method."""

    @pytest.mark.asyncio
    async def test_run_success(self, llm_settings: LLMSettings) -> None:
        """Successful run returns LLMResult."""
        client = LLMClient(llm_settings)
        model = TestModel()
        # Using cast to avoid constructor inference issues in tests.
        agent = cast(
            Agent[SampleContext, SampleOutput],
            Agent(model, deps_type=SampleContext, output_type=SampleOutput),
        )

        with patch.object(client, "_metrics") as mock_metrics:
            result = await client.run(
                agent,
                "test prompt",
                deps=SampleContext(data="test"),
            )

            assert isinstance(result, LLMResult)
            assert isinstance(result.output, SampleOutput)
            assert isinstance(result.usage, RunUsage)
            # model_id returns full "provider:model" format
            assert result.model_used == "openrouter:test/model"
            assert result.duration_seconds > 0

            # Verify metrics were recorded
            mock_metrics.record_request.assert_called_once()
            call_args = mock_metrics.record_request.call_args[0][0]
            assert call_args.success is True
            assert call_args.model == result.model_used

    @pytest.mark.asyncio
    async def test_run_failure_records_metrics(self, llm_settings: LLMSettings) -> None:
        """Failed run records failure metrics."""
        client = LLMClient(llm_settings)
        model = TestModel()
        agent = cast(
            Agent[SampleContext, SampleOutput],
            Agent(model, deps_type=SampleContext, output_type=SampleOutput),
        )

        with (
            patch.object(agent, "run", side_effect=RuntimeError("API Error")),
            patch.object(client, "_metrics") as mock_metrics,
        ):
            with pytest.raises(RuntimeError, match="API Error"):
                await client.run(
                    agent,
                    "test prompt",
                    deps=SampleContext(data="test"),
                )

            mock_metrics.record_request.assert_called_once()
            call_args = mock_metrics.record_request.call_args[0][0]
            assert call_args.success is False
            assert call_args.error_type == "RuntimeError"

    @pytest.mark.asyncio
    async def test_unexpected_model_behavior_is_retried(self, llm_settings: LLMSettings) -> None:
        """UnexpectedModelBehavior is wrapped as LLMTransientError and retried."""
        from pydantic_ai.exceptions import UnexpectedModelBehavior

        client = LLMClient(llm_settings)
        model = TestModel()
        agent = cast(
            Agent[SampleContext, SampleOutput],
            Agent(model, deps_type=SampleContext, output_type=SampleOutput),
        )

        with patch.object(agent, "run") as mock_run:
            mock_result = MagicMock()
            mock_result.output = SampleOutput(result="recovered")
            mock_result.usage = RunUsage()
            mock_result.all_messages.return_value = []

            mock_run.side_effect = [
                UnexpectedModelBehavior("Null-field response from provider"),
                mock_result,
            ]

            result = await client.run(agent, "test", deps=SampleContext(data="test"))

            assert result.output.result == "recovered"
            assert mock_run.call_count == 2

    @pytest.mark.asyncio
    async def test_unexpected_model_behavior_exhausted_raises_transient(self, llm_settings: LLMSettings) -> None:
        """After all retries are exhausted, LLMTransientError is raised."""
        from nohiki_llm_client.exceptions import LLMTransientError
        from pydantic_ai.exceptions import UnexpectedModelBehavior

        client = LLMClient(llm_settings)
        model = TestModel()
        agent = cast(
            Agent[SampleContext, SampleOutput],
            Agent(model, deps_type=SampleContext, output_type=SampleOutput),
        )

        with (
            patch.object(
                agent,
                "run",
                side_effect=UnexpectedModelBehavior("persistent null response"),
            ),
            pytest.raises(LLMTransientError, match="persistent null response"),
        ):
            await client.run(agent, "test", deps=SampleContext(data="test"))

    @pytest.mark.asyncio
    async def test_run_with_retry(self, llm_settings: LLMSettings) -> None:
        """Retries on LLMTransientError."""
        client = LLMClient(llm_settings)
        model = TestModel()
        agent = cast(
            Agent[SampleContext, SampleOutput],
            Agent(model, deps_type=SampleContext, output_type=SampleOutput),
        )

        from nohiki_llm_client.exceptions import LLMTransientError

        with patch.object(agent, "run") as mock_run:
            # Create a mock result that behaves like AgentRunResult
            mock_result = MagicMock()
            mock_result.output = SampleOutput(result="success")
            mock_result.usage = RunUsage()
            mock_result.all_messages.return_value = []

            # Fail once, then succeed
            mock_run.side_effect = [LLMTransientError("Transient Error"), mock_result]

            result = await client.run(agent, "test", deps=SampleContext(data="test"))

            assert result.output.result == "success"
            assert mock_run.call_count == 2

    @pytest.mark.asyncio
    async def test_run_success_has_zero_retry_count(self, llm_settings: LLMSettings) -> None:
        """Successful run with no retries reports retry_count=0."""
        client = LLMClient(llm_settings)
        model = TestModel()
        agent = cast(
            Agent[SampleContext, SampleOutput],
            Agent(model, deps_type=SampleContext, output_type=SampleOutput),
        )

        result = await client.run(agent, "test", deps=SampleContext(data="test"))

        assert result.retry_count == 0

    @pytest.mark.asyncio
    async def test_run_with_one_retry_has_retry_count_one(self, llm_settings: LLMSettings) -> None:
        """Run that retries once reports retry_count=1."""
        from nohiki_llm_client.exceptions import LLMTransientError

        client = LLMClient(llm_settings)
        model = TestModel()
        agent = cast(
            Agent[SampleContext, SampleOutput],
            Agent(model, deps_type=SampleContext, output_type=SampleOutput),
        )

        with patch.object(agent, "run") as mock_run:
            mock_result = MagicMock()
            mock_result.output = SampleOutput(result="ok")
            mock_result.usage = RunUsage()
            mock_result.all_messages.return_value = []

            mock_run.side_effect = [LLMTransientError("transient"), mock_result]

            result = await client.run(agent, "test", deps=SampleContext(data="test"))

            assert result.retry_count == 1

    @pytest.mark.asyncio
    async def test_run_uses_provider_cost_from_messages(self, llm_settings: LLMSettings) -> None:
        """cost_usd uses provider_details['cost'] when available, bypassing genai_prices."""
        from pydantic_ai.messages import ModelResponse, TextPart

        client = LLMClient(llm_settings)
        model = TestModel()
        agent = cast(
            Agent[SampleContext, SampleOutput],
            Agent(model, deps_type=SampleContext, output_type=SampleOutput),
        )

        model_response = ModelResponse(
            parts=[TextPart(content="hello")],
            provider_details={"cost": 0.0012345, "downstream_provider": "TestProvider"},
        )

        with patch.object(agent, "run") as mock_run:
            mock_result = MagicMock()
            mock_result.output = SampleOutput(result="ok")
            mock_result.usage = RunUsage()
            mock_result.all_messages.return_value = [model_response]

            mock_run.return_value = mock_result

            result = await client.run(agent, "test", deps=SampleContext(data="test"))

            assert result.cost_usd == pytest.approx(0.0012345)
            assert result.downstream_provider == "TestProvider"

    @pytest.mark.asyncio
    async def test_openrouter_invalid_response_raises_provider_response_error(self, llm_settings: LLMSettings) -> None:
        """UnexpectedModelBehavior with OpenRouter invalid response prefix raises LLMProviderResponseError."""
        from nohiki_llm_client.config.constants import (
            OPENROUTER_INVALID_RESPONSE_PREFIX,
        )
        from nohiki_llm_client.exceptions import LLMProviderResponseError
        from pydantic_ai.exceptions import UnexpectedModelBehavior

        client = LLMClient(llm_settings)
        model = TestModel()
        agent = cast(
            Agent[SampleContext, SampleOutput],
            Agent(model, deps_type=SampleContext, output_type=SampleOutput),
        )

        error_msg = f"{OPENROUTER_INVALID_RESPONSE_PREFIX}: 5 validation errors for _OpenRouterChatCompletion"
        with (
            patch.object(agent, "run", side_effect=UnexpectedModelBehavior(error_msg)),
            pytest.raises(LLMProviderResponseError, match="Invalid response from openrouter"),
        ):
            await client.run(agent, "test", deps=SampleContext(data="test"))

    @pytest.mark.asyncio
    async def test_openrouter_invalid_response_is_not_retried_by_tenacity(self, llm_settings: LLMSettings) -> None:
        """OpenRouter invalid response is NOT retried by Tenacity: agent.run called exactly once."""
        from nohiki_llm_client.config.constants import (
            OPENROUTER_INVALID_RESPONSE_PREFIX,
        )
        from nohiki_llm_client.exceptions import LLMProviderResponseError
        from pydantic_ai.exceptions import UnexpectedModelBehavior

        client = LLMClient(llm_settings)
        model = TestModel()
        agent = cast(
            Agent[SampleContext, SampleOutput],
            Agent(model, deps_type=SampleContext, output_type=SampleOutput),
        )

        error_msg = f"{OPENROUTER_INVALID_RESPONSE_PREFIX}: 5 validation errors for _OpenRouterChatCompletion"
        with patch.object(agent, "run", side_effect=UnexpectedModelBehavior(error_msg)) as mock_run:
            with pytest.raises(LLMProviderResponseError):
                await client.run(agent, "test", deps=SampleContext(data="test"))
            assert mock_run.call_count == 1

    @pytest.mark.asyncio
    async def test_model_http_error_4xx_raises_provider_response_error(self, llm_settings: LLMSettings) -> None:
        """ModelHTTPError with 4xx (non-429) status raises LLMProviderResponseError without retry."""
        from nohiki_llm_client.exceptions import LLMProviderResponseError
        from pydantic_ai.exceptions import ModelHTTPError

        client = LLMClient(llm_settings)
        model = TestModel()
        agent = cast(
            Agent[SampleContext, SampleOutput],
            Agent(model, deps_type=SampleContext, output_type=SampleOutput),
        )

        http_err = ModelHTTPError(status_code=404, model_name="test/model", body="No endpoints found")
        with patch.object(agent, "run", side_effect=http_err) as mock_run:
            with pytest.raises(LLMProviderResponseError):
                await client.run(agent, "test", deps=SampleContext(data="test"))
            assert mock_run.call_count == 1

    @pytest.mark.asyncio
    async def test_model_http_error_5xx_raises_transient_error(self, llm_settings: LLMSettings) -> None:
        """ModelHTTPError with 5xx status raises LLMTransientError (Tenacity retries it)."""
        from nohiki_llm_client.exceptions import LLMTransientError
        from pydantic_ai.exceptions import ModelHTTPError

        client = LLMClient(llm_settings)
        model = TestModel()
        agent = cast(
            Agent[SampleContext, SampleOutput],
            Agent(model, deps_type=SampleContext, output_type=SampleOutput),
        )

        http_err = ModelHTTPError(status_code=503, model_name="test/model", body="Service Unavailable")
        with (
            patch.object(agent, "run", side_effect=http_err),
            pytest.raises(LLMTransientError),
        ):
            await client.run(agent, "test", deps=SampleContext(data="test"))

    @pytest.mark.asyncio
    async def test_model_http_error_429_raises_rate_limit_error(self, llm_settings: LLMSettings) -> None:
        """A classified 429 surfaces after one application attempt; transport owns retries."""
        from nohiki_llm_client.exceptions import LLMRateLimitError
        from pydantic_ai.exceptions import ModelHTTPError

        client = LLMClient(llm_settings)
        model = TestModel()
        agent = cast(
            Agent[SampleContext, SampleOutput],
            Agent(model, deps_type=SampleContext, output_type=SampleOutput),
        )

        http_err = ModelHTTPError(status_code=429, model_name="test/model", body="Rate limit exceeded")
        with (
            patch.object(agent, "run", side_effect=http_err) as mock_run,
            pytest.raises(LLMRateLimitError),
        ):
            await client.run(agent, "test", deps=SampleContext(data="test"))

        assert mock_run.call_count == 1

    @pytest.mark.asyncio
    async def test_validation_exhaustion_raises_llm_validation_error(self, llm_settings: LLMSettings) -> None:
        """UnexpectedModelBehavior with 'Exceeded maximum retries' prefix raises LLMValidationError."""
        from nohiki_llm_client.exceptions import LLMValidationError
        from pydantic_ai.exceptions import UnexpectedModelBehavior

        client = LLMClient(llm_settings)
        model = TestModel()
        agent = cast(
            Agent[SampleContext, SampleOutput],
            Agent(model, deps_type=SampleContext, output_type=SampleOutput),
        )

        with (
            patch.object(
                agent,
                "run",
                side_effect=UnexpectedModelBehavior("Exceeded maximum retries (3) for output validation"),
            ),
            pytest.raises(LLMValidationError, match="Exceeded maximum retries"),
        ):
            await client.run(agent, "test", deps=SampleContext(data="test"))

    @pytest.mark.asyncio
    async def test_validation_exhaustion_is_not_retried_by_tenacity(self, llm_settings: LLMSettings) -> None:
        """Validation exhaustion is NOT retried by Tenacity: agent.run called exactly once."""
        from nohiki_llm_client.exceptions import LLMValidationError
        from pydantic_ai.exceptions import UnexpectedModelBehavior

        client = LLMClient(llm_settings)
        model = TestModel()
        agent = cast(
            Agent[SampleContext, SampleOutput],
            Agent(model, deps_type=SampleContext, output_type=SampleOutput),
        )

        with patch.object(
            agent,
            "run",
            side_effect=UnexpectedModelBehavior("Exceeded maximum retries (3) for output validation"),
        ) as mock_run:
            with pytest.raises(LLMValidationError):
                await client.run(agent, "test", deps=SampleContext(data="test"))
            assert mock_run.call_count == 1

    @pytest.mark.asyncio
    async def test_run_falls_back_to_genai_prices_when_no_provider_cost(self, llm_settings: LLMSettings) -> None:
        """cost_usd uses genai_prices when provider_details has no cost."""
        from pydantic_ai.messages import ModelResponse, TextPart

        client = LLMClient(llm_settings)
        model = TestModel()
        agent = cast(
            Agent[SampleContext, SampleOutput],
            Agent(model, deps_type=SampleContext, output_type=SampleOutput),
        )

        model_response = ModelResponse(
            parts=[TextPart(content="hello")],
            provider_details={"downstream_provider": "TestProvider"},
        )

        with patch.object(agent, "run") as mock_run:
            mock_result = MagicMock()
            mock_result.output = SampleOutput(result="ok")
            mock_result.usage = RunUsage()
            mock_result.all_messages.return_value = [model_response]

            mock_run.return_value = mock_result

            with patch("nohiki_llm_client.client.core.calc_llm_cost", return_value=0.0099) as mock_calc:
                result = await client.run(agent, "test", deps=SampleContext(data="test"))

            mock_calc.assert_called_once()
            assert result.cost_usd == pytest.approx(0.0099)


class TestModelSupportsCachePoint:
    """Tests for _model_supports_cache_point utility."""

    def test_anthropic_direct_supported(self) -> None:
        assert _model_supports_cache_point("anthropic:claude-sonnet-4-20250514") is True

    def test_anthropic_via_openrouter_supported(self) -> None:
        assert _model_supports_cache_point("openrouter:anthropic/claude-sonnet-4-20250514") is True

    def test_anthropic_case_insensitive(self) -> None:
        assert _model_supports_cache_point("Anthropic:claude-sonnet-4") is True
        assert _model_supports_cache_point("openrouter:Anthropic/claude-3.5-sonnet") is True

    def test_openai_not_supported(self) -> None:
        assert _model_supports_cache_point("openrouter:openai/gpt-5.2") is False

    def test_google_not_supported(self) -> None:
        assert _model_supports_cache_point("openrouter:google/gemini-3-flash-preview") is False

    def test_ollama_not_supported(self) -> None:
        assert _model_supports_cache_point("ollama:llama3:8b") is False


class TestStripCachePoints:
    """Tests for _strip_cache_points utility."""

    def test_plain_string_returned_unchanged(self) -> None:
        assert _strip_cache_points("hello world") == "hello world"

    def test_list_with_cache_point_stripped(self) -> None:
        from pydantic_ai import CachePoint

        result = _strip_cache_points(["part one", CachePoint(), "part two"])
        assert result == "part one\n\npart two"

    def test_list_without_cache_point(self) -> None:
        result = _strip_cache_points(["part one", "part two"])
        assert result == "part one\n\npart two"

    def test_single_element_list(self) -> None:
        result = _strip_cache_points(["only part"])
        assert result == "only part"

    def test_empty_list(self) -> None:
        result = _strip_cache_points([])
        assert result == ""
