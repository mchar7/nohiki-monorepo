"""PydanticAI-based LLM client with unified execution, metrics, and retry.

Delegates model construction to ``factory.py`` and instrumentation to
``instrumentation.py``. Provides a single ``run()`` method for both
structured (``BaseModel``) and dynamic (``dict[str, Any]``) output agents.
"""

import asyncio
import time
from collections.abc import Callable
from dataclasses import dataclass
from types import TracebackType
from typing import Any, Final, Self, cast

from httpx import AsyncClient
from nohiki_observability import get_logger
from pydantic import BaseModel, ValidationError
from pydantic_ai import (
    Agent,
    AgentRunResult,
    CachePoint,
    PromptedOutput,
    StructuredDict,
    UsageLimits,
)
from pydantic_ai.exceptions import (
    AgentRunError,
    ContentFilterError,
    FallbackExceptionGroup,
    ModelAPIError,
    ModelHTTPError,
    ModelRetry,
    ToolRetryError,
    UnexpectedModelBehavior,
    UsageLimitExceeded,
    UserError,
)
from pydantic_ai.messages import ModelMessage, ModelResponse
from pydantic_ai.models import Model
from pydantic_ai.settings import ModelSettings
from pydantic_ai.tools import RunContext
from pydantic_ai.usage import RunUsage
from tenacity import AsyncRetrying, RetryCallState, retry_if_exception, stop_after_attempt, wait_exponential
from tenacity.wait import WaitBaseT

from nohiki_llm_client.config.constants import (
    HTTP_RETRYABLE_STATUS_CODES,
    HTTP_STATUS_RATE_LIMIT,
    LLM_MODEL_SEPARATOR,
    MAX_RETRY_ATTEMPTS,
    OPENROUTER_INVALID_RESPONSE_PREFIX,
    RETRY_MAX_WAIT_SECONDS,
    RETRY_MIN_WAIT_SECONDS,
    RETRY_MULTIPLIER,
)
from nohiki_llm_client.config.settings import LLMSettings
from nohiki_llm_client.exceptions import (
    LLMApplicationRateLimitError,
    LLMConfigurationError,
    LLMContentFilterError,
    LLMError,
    LLMProviderResponseError,
    LLMRateLimitError,
    LLMTransientError,
    LLMUsageLimitError,
    LLMValidationError,
)
from nohiki_llm_client.observability.instrumentation import create_instrumented_model
from nohiki_llm_client.observability.metrics import (
    LLMMetrics,
    RequestMetricsParams,
    get_llm_metrics,
)
from nohiki_llm_client.pricing import calc_llm_cost
from nohiki_llm_client.providers.factory import (
    create_full_model_chain,
    resolve_chain,
    rollback_transport_clients,
)
from nohiki_llm_client.providers.openrouter import _EmbeddedRateLimitError

type SystemPromptFn[TDeps] = Callable[[RunContext[TDeps]], str | None]

_RUN_CONTEXT_CLASS = RunContext

logger = get_logger(__name__)
_OUTPUT_RETRY_EXHAUSTED_PREFIX: Final[str] = "Exceeded maximum output retries ("


def _is_application_retryable(exc: BaseException) -> bool:
    """Return whether the application-level Tenacity policy retries ``exc``."""
    return isinstance(exc, LLMApplicationRateLimitError) or (
        isinstance(exc, LLMTransientError) and not isinstance(exc, LLMRateLimitError)
    )


def _model_supports_cache_point(model_string: str) -> bool:
    """Check if a model supports PydanticAI ``CachePoint`` markers in user messages.

    Only Anthropic-based models support cache_control; other providers reject it with HTTP errors.
    """
    lower = model_string.lower()
    return lower.startswith("anthropic:") or "anthropic/" in lower


def _strip_cache_points(prompt: str | list[str | CachePoint]) -> str:
    """Remove ``CachePoint`` markers and join text parts into a plain string.

    Non-supporting providers receive a clean concatenated string prompt.
    """
    if isinstance(prompt, str):
        return prompt
    return "\n\n".join(part for part in prompt if isinstance(part, str))


@dataclass
class _RetryState:
    """Mutable counter tracking Tenacity retry attempts within a single run."""

    count: int = 0


def _create_default_retry_wait() -> WaitBaseT:
    """Build the production wait strategy, including embedded rate-limit hints."""
    exponential_wait = wait_exponential(
        multiplier=RETRY_MULTIPLIER,
        min=RETRY_MIN_WAIT_SECONDS,
        max=RETRY_MAX_WAIT_SECONDS,
    )

    def _wait_for_retry(state: RetryCallState) -> float:
        exception = state.outcome.exception() if state.outcome else None
        if isinstance(exception, LLMRateLimitError) and exception.retry_after is not None:
            return min(float(exception.retry_after), RETRY_MAX_WAIT_SECONDS)
        return exponential_wait(state)

    return _wait_for_retry


def _extract_provider_cost(messages: tuple[ModelMessage, ...]) -> float | None:
    """Extract actual billed cost from OpenRouter's ``provider_details["cost"]`` field.

    Args:
        messages: Full message history from an agent run.

    Returns:
        Actual billed cost in USD if present, else ``None``.
    """
    for msg in messages:
        if (
            isinstance(msg, ModelResponse)
            and msg.provider_details
            and (cost := msg.provider_details.get("cost")) is not None
        ):
            return float(cost)
    return None


def _extract_downstream_provider(messages: tuple[ModelMessage, ...]) -> str | None:
    """Return the provider selected by a routed model response, when reported."""
    for message in messages:
        if isinstance(message, ModelResponse) and message.provider_details:
            provider = message.provider_details.get("downstream_provider")
            if isinstance(provider, str) and provider:
                return provider
    return None


# Library failure types that map one-to-one onto a Nohiki class with no extra condition.
# Ordered most specific first: `ContentFilterError` subclasses `UnexpectedModelBehavior`,
# so it must be matched here before the conditional `UnexpectedModelBehavior` branch below.
_DIRECT_FAILURE_CLASSES: Final[tuple[tuple[type[BaseException], type[LLMError]], ...]] = (
    (ContentFilterError, LLMContentFilterError),
    (UsageLimitExceeded, LLMUsageLimitError),
    (UserError, LLMConfigurationError),
)


def _classify_agent_failure(exc: BaseException) -> LLMError | None:
    """Map a PydanticAI failure onto the Nohiki taxonomy, or ``None`` when unmapped.

    Pure and recursive so ``FallbackExceptionGroup`` can be classified member-wise
    rather than as an opaque container. Order is load-bearing: ``_EmbeddedRateLimitError``
    before ``ModelHTTPError``, and ``ContentFilterError`` before
    ``UnexpectedModelBehavior``, because each pair is a subclass relation.

    Returning ``None`` means "not ours": the caller re-raises the original untouched
    rather than mislabelling it.
    """
    if isinstance(exc, FallbackExceptionGroup):
        return _classify_fallback_group(exc)
    if isinstance(exc, _EmbeddedRateLimitError):
        return LLMApplicationRateLimitError(str(exc), retry_after=exc.retry_after)
    if isinstance(exc, ModelHTTPError):
        return _classify_http_failure(exc)
    if isinstance(exc, ModelAPIError):
        return LLMTransientError(str(exc))
    classified: LLMError | None = None
    for library_type, nohiki_type in _DIRECT_FAILURE_CLASSES:
        if isinstance(exc, library_type):
            classified = nohiki_type(str(exc))
            break
    if classified is None and isinstance(exc, UnexpectedModelBehavior):
        classified = _classify_unexpected_behavior(exc)
    return classified


def _classify_http_failure(exc: ModelHTTPError) -> LLMError:
    """Split an HTTP failure into rate limit, retryable, and permanent."""
    if exc.status_code in HTTP_RETRYABLE_STATUS_CODES:
        if exc.status_code == HTTP_STATUS_RATE_LIMIT:
            return LLMRateLimitError(str(exc), retry_after=exc.retry_after)
        return LLMTransientError(str(exc))
    return LLMProviderResponseError(str(exc))


def _classify_unexpected_behavior(exc: UnexpectedModelBehavior) -> LLMError:
    """Classify a non-content-filter ``UnexpectedModelBehavior``.

    OpenRouter's null-field body is identified by its library-owned message because it has no
    distinguishing type. Output retry exhaustion normally chains ``ToolRetryError`` or
    ``ModelRetry``. The output-tool path instead exposes its original ``ValidationError``,
    which is also the cause used for malformed provider payloads, so that ambiguous cause is
    accepted only with PydanticAI's output-budget context.
    """
    exc_str = str(exc)
    if OPENROUTER_INVALID_RESPONSE_PREFIX in exc_str:
        return LLMProviderResponseError(exc_str)
    cause = exc.__cause__
    if isinstance(cause, ToolRetryError | ModelRetry) or (
        isinstance(cause, ValidationError) and str(exc).startswith(_OUTPUT_RETRY_EXHAUSTED_PREFIX)
    ):
        return LLMValidationError(exc_str)
    return LLMTransientError(exc_str)


def _classify_fallback_group(group: FallbackExceptionGroup) -> LLMError | None:
    """Classify a fallback group by its members rather than as a container.

    Application-retryable failures take precedence because a hop may succeed on
    the next immediate attempt. Transport-owned rate limits come next because
    Kafka can retry the whole operation after backoff. Terminal failures are
    returned only when no retryable hop exists. Members that classify to
    ``None`` (``ResponseRejected``, anything not ours) carry no provider verdict
    and are skipped; a group of only those returns ``None`` so the group itself
    propagates.

    The chosen member's message is surfaced, and the caller chains the whole group
    onto ``__cause__``, so no hop detail is lost.
    """
    first_rate_limit: LLMRateLimitError | None = None
    first_terminal: LLMError | None = None
    for member in group.exceptions:
        classified = _classify_agent_failure(member)
        if classified is None:
            continue
        if _is_application_retryable(classified):
            return classified
        if isinstance(classified, LLMRateLimitError):
            if first_rate_limit is None:
                first_rate_limit = classified
        elif first_terminal is None:
            first_terminal = classified
    return first_rate_limit or first_terminal


@dataclass(frozen=True, slots=True)
class LLMResult[T]:
    """Result of an LLM run.

    Attributes:
        output: The parsed output from the agent (typed by ``T``).
        usage: PydanticAI ``RunUsage`` with ``input_tokens``, ``output_tokens``,
            ``cache_read_tokens``, ``cache_write_tokens``, ``cost()``, etc.
        model_used: The model name string that served the request.
        duration_seconds: Wall-clock time for the run.
        cost_usd: Total cost in USD calculated via genai-prices after the run.
            ``None`` if the model or provider is not in the pricing snapshot.
        downstream_provider: Provider selected by a routed model response, when reported.
        messages: Full message history including thinking parts. Use for
            inspecting ``ThinkingPart`` objects in responses.
    """

    output: T
    usage: RunUsage
    model_used: str
    duration_seconds: float
    cost_usd: float | None = None
    downstream_provider: str | None = None
    messages: tuple[ModelMessage, ...] = ()
    retry_count: int = 0


@dataclass(frozen=True, slots=True)
class StructuredAgentConfig[TDeps, TOutput: BaseModel]:
    """Configuration for creating a structured output agent.

    Attributes:
        deps_type: Type of the dependency object passed to the agent.
        output_type: Pydantic model type for structured output validation.
        system_prompt: Optional system prompt baked into the agent.
        inject_schema_prompt: Whether to inject the default schema prompt. Defaults to
            ``True``. Set to ``False`` to disable PydanticAI's automatic schema
            injection (requires PydanticAI >=1.67.0).
        model_settings: Provider-specific model settings (e.g.,
            ``AnthropicModelSettings`` for prompt caching). Passed to the
            PydanticAI ``Agent`` at creation time.
    """

    deps_type: type[TDeps]
    output_type: type[TOutput]
    system_prompt: str | None = None
    inject_schema_prompt: bool = True
    model_settings: ModelSettings | None = None

    def __post_init__(self) -> None:
        """Validate structured output model type."""
        if not issubclass(self.output_type, BaseModel):
            msg = "output_type must inherit from pydantic.BaseModel"
            raise TypeError(msg)


@dataclass(frozen=True, slots=True)
class DynamicAgentConfig[TDeps]:
    """Configuration for creating a dynamic JSON schema agent.

    Attributes:
        deps_type: Type of the dependency object.
        json_schema: Raw JSON schema dict for ``StructuredDict`` output.
        schema_name: Name for the dynamic output type.
        schema_description: Description for the dynamic output type.
        system_prompt: Optional static system prompt string.
        system_prompt_fn: Optional async callable ``(RunContext[TDeps]) -> str`` for
            dynamic prompts that depend on per-request dependencies.
        inject_schema_prompt: Whether to inject the default schema prompt. Defaults to
            ``True``. Set to ``False`` to disable PydanticAI's automatic schema
            injection (requires PydanticAI >=1.67.0).
        model_settings: Provider-specific model settings. Passed to the
            PydanticAI ``Agent`` at creation time.
    """

    deps_type: type[TDeps]
    json_schema: dict[str, Any]
    schema_name: str = "response"
    schema_description: str | None = None
    system_prompt: str | None = None
    system_prompt_fn: SystemPromptFn[TDeps] | None = None
    inject_schema_prompt: bool = True
    model_settings: ModelSettings | None = None


class LLMClient:
    """PydanticAI LLM client with model chain, metrics, and instrumentation.

    Lazily builds the model chain on first use. Provides unified agent creation
    and execution with retry logic and metrics recording.

    Example::

        client = LLMClient(settings.llm)
        agent = client.create_agent(StructuredAgentConfig(
            deps_type=MyContext,
            output_type=MyOutput,
            system_prompt="You are a helpful assistant.",
        ))
        result = await client.run(agent, "Generate", deps=MyContext(...))
        print(result.output)
        print(result.usage.input_tokens)
    """

    __slots__ = ("_metrics", "_model", "_provider", "_retry_wait", "_settings", "_transport_clients")

    def __init__(
        self,
        settings: LLMSettings,
        *,
        chain: str | None = None,
        retry_wait: WaitBaseT | None = None,
    ) -> None:
        """Initialize the LLM client.

        Args:
            settings: Complete LLM configuration from ``LLMMixin``.
            chain: Named use-case chain from ``settings.chains``. Falls back to
                ``settings.provider`` when ``None`` or the name is not found.
            retry_wait: Wait strategy for application-level retries. Defaults to
                the production exponential backoff.
        """
        self._settings = settings
        self._provider = resolve_chain(chain, settings)
        self._retry_wait = _create_default_retry_wait() if retry_wait is None else retry_wait
        self._model: Model | None = None
        self._metrics: LLMMetrics = get_llm_metrics()
        self._transport_clients: list[AsyncClient] = []

    async def __aenter__(self) -> Self:
        """Return this client for deterministic async-context ownership."""
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """Close all model transports when leaving the owning context."""
        del exc_type, exc_value, traceback
        await self.close()

    async def close(self) -> None:
        """Close all transports, retaining only failures for a safe retry."""
        clients = tuple(self._transport_clients)
        self._transport_clients.clear()
        self._model = None
        close_future = asyncio.gather(
            *(client.aclose() for client in clients),
            return_exceptions=True,
        )
        outer_cancellation: asyncio.CancelledError | None = None
        try:
            outcomes = await asyncio.shield(close_future)
        except asyncio.CancelledError as exc:
            outer_cancellation = exc
            outcomes = await close_future

        cancellations: list[asyncio.CancelledError] = []
        failures: list[Exception] = []
        for client, outcome in zip(clients, outcomes, strict=True):
            if isinstance(outcome, asyncio.CancelledError):
                self._transport_clients.append(client)
                cancellations.append(outcome)
            elif isinstance(outcome, Exception):
                self._transport_clients.append(client)
                failures.append(outcome)
        if outer_cancellation is not None:
            cancellations.append(outer_cancellation)

        message = "Failed to close LLM model transports"
        if cancellations:
            if len(cancellations) == 1 and not failures:
                raise cancellations[0]
            raise BaseExceptionGroup(message, [*cancellations, *failures])
        if failures:
            raise ExceptionGroup(message, failures)

    def _get_model(self) -> Model:
        """Get or lazily build the model chain.

        Returns:
            Configured ``Model`` (possibly ``FallbackModel``, possibly instrumented).
        """
        if self._model is not None:
            return self._model

        if self._transport_clients:
            failures = rollback_transport_clients(self._transport_clients, 0)
            if failures:
                message = "Failed to close transports from a previous LLM construction attempt"
                raise BaseExceptionGroup(message, failures)

        attempt_start = len(self._transport_clients)
        try:
            model = self._build_model_chain()
            model = create_instrumented_model(model, self._settings.instrumentation)
        except BaseException as exc:
            failures = rollback_transport_clients(self._transport_clients, attempt_start)
            if failures:
                message = "Failed to initialize and close LLM model transports"
                raise BaseExceptionGroup(message, [exc, *failures]) from exc
            raise

        self._model = model
        return model

    def _build_model_chain(self) -> Model:
        """Build the complete model chain via the factory."""
        return create_full_model_chain(
            self._provider,
            self._settings.caching,
            transport_clients=self._transport_clients,
        )

    def create_agent[TDeps, TOutput: BaseModel](
        self,
        config: StructuredAgentConfig[TDeps, TOutput],
    ) -> Agent[TDeps, TOutput]:
        """Create a PydanticAI agent with structured output.

        Passes the output type directly to PydanticAI, which selects the
        appropriate output mode automatically:

        - For Anthropic models with thinking active, PydanticAI's ``prepare_request``
          hook auto-selects ``output_mode='native'`` (JSON schema via
          ``output_config``) for models that support structured outputs, avoiding
          the ``tool_choice=required`` incompatibility with thinking.
        - For other models and configurations, PydanticAI uses its default
          structured output mode (typically tool-use).

        When ``config.inject_schema_prompt`` is ``False``, the output type is
        wrapped in ``PromptedOutput`` to disable PydanticAI's automatic schema
        prompt injection (client-side validation only).

        Args:
            config: Agent configuration including output type and system prompt.

        Returns:
            Configured ``Agent`` instance.
        """
        model = self._get_model()

        output_type: type[TOutput] | PromptedOutput[Any]
        if config.inject_schema_prompt:
            output_type = config.output_type
        else:
            output_type = cast(
                "PromptedOutput[TOutput]",
                PromptedOutput(config.output_type, template=False),
            )

        return cast(
            "Agent[TDeps, TOutput]",
            Agent(
                model=model,
                output_type=output_type,
                system_prompt=config.system_prompt or "",
                retries=self._settings.provider.max_tool_retries,
                model_settings=config.model_settings,
            ),
        )

    def create_dynamic_schema_agent[TDeps](
        self,
        config: DynamicAgentConfig[TDeps],
    ) -> Agent[TDeps, dict[str, Any]]:
        """Create a PydanticAI agent with dynamic JSON schema output.

        If ``config.system_prompt_fn`` is set, registers it as a dynamic prompt
        callback so it can access per-request ``RunContext.deps``. This avoids
        the decorator mutation anti-pattern at call sites.

        Args:
            config: Agent configuration including JSON schema.

        Returns:
            Configured ``Agent`` with ``StructuredDict`` output.
        """
        model = self._get_model()

        structured_dict = StructuredDict(
            config.json_schema,
            name=config.schema_name,
            description=config.schema_description,
        )

        # Wrap output type to disable schema prompt injection if requested
        output = structured_dict if config.inject_schema_prompt else PromptedOutput(structured_dict, template=False)

        agent = cast(
            "Agent[TDeps, dict[str, Any]]",
            Agent(
                model=model,
                output_type=output,
                system_prompt=config.system_prompt or "",
                retries=self._settings.provider.max_tool_retries,
                model_settings=config.model_settings,
            ),
        )

        if config.system_prompt_fn is not None:
            agent.system_prompt(config.system_prompt_fn)

        return agent

    async def run[TDeps, TOut](
        self,
        agent: Agent[TDeps, TOut],
        prompt: str | list[str | CachePoint],
        *,
        deps: TDeps,
        message_history: list[ModelMessage] | None = None,
        usage_limits: UsageLimits | None = None,
    ) -> LLMResult[TOut]:
        """Execute an agent with retry logic and metrics recording.

        This is the **single entry point** for all agent execution: both
        structured output (``BaseModel``) and dynamic schema (``dict[str, Any]``)
        agents.

        ``CachePoint`` markers in the prompt are automatically stripped for
        models that do not support them (non-Anthropic).  Callers can always
        include ``CachePoint`` markers for optimal caching without worrying
        about provider compatibility.

        Args:
            agent: The PydanticAI agent to execute.
            prompt: User prompt string, or a list of strings and ``CachePoint``
                markers for fine-grained prompt caching control.
            deps: Dependencies to pass to the agent.
            message_history: Optional conversation history.
            usage_limits: Optional token usage limits for the run.

        Returns:
            ``LLMResult`` containing the output and usage metrics.

        Raises:
            LLMTransientError: On retryable failures after all retries exhausted.
        """
        start = time.perf_counter()
        model = self._get_model()
        model_id = getattr(model, "model_id", model.model_name)
        provider_url = self._provider.models[0].base_url
        retry_state = _RetryState()

        # Auto-strip CachePoint markers for models that don't support them
        primary_model = self._provider.models[0].model
        if isinstance(prompt, list) and not _model_supports_cache_point(primary_model):
            prompt = _strip_cache_points(prompt)

        def _before_sleep(rs: RetryCallState) -> None:
            retry_state.count += 1
            logger.warning(
                "LLM transient error; retrying",
                model=model_id,
                attempt=rs.attempt_number,
                error=str(rs.outcome.exception()) if rs.outcome else None,
            )

        _result: AgentRunResult[TOut] | None = None
        try:
            async for attempt in AsyncRetrying(
                retry=retry_if_exception(_is_application_retryable),
                stop=stop_after_attempt(MAX_RETRY_ATTEMPTS),
                wait=self._retry_wait,
                reraise=True,
                before_sleep=_before_sleep,
            ):
                with attempt:
                    _result = await self._single_attempt(
                        agent,
                        prompt,
                        deps=deps,
                        message_history=message_history,
                        usage_limits=usage_limits,
                    )

            result = cast("AgentRunResult[TOut]", _result)

            duration = time.perf_counter() - start
            usage: RunUsage = result.usage
            messages = tuple(result.all_messages())

            self._record_metrics(
                model=model_id,
                duration=duration,
                usage=usage,
                success=True,
            )

            provider_cost = _extract_provider_cost(messages)
            downstream_provider = _extract_downstream_provider(messages)
            # Strip provider prefix for genai-prices (expects bare model name)
            bare_model = (
                model_id.split(LLM_MODEL_SEPARATOR, maxsplit=1)[-1] if LLM_MODEL_SEPARATOR in model_id else model_id
            )
            cost_usd = (
                provider_cost
                if provider_cost is not None
                else calc_llm_cost(usage, bare_model, provider_api_url=provider_url)
            )

            return LLMResult(
                output=result.output,
                usage=usage,
                model_used=model_id,
                duration_seconds=duration,
                cost_usd=cost_usd,
                downstream_provider=downstream_provider,
                messages=messages,
                retry_count=retry_state.count,
            )

        except Exception as exc:
            duration = time.perf_counter() - start
            self._record_metrics(
                model=model_id,
                duration=duration,
                usage=RunUsage(),
                success=False,
                error_type=type(exc).__name__,
            )
            raise

    async def _single_attempt[TDeps, TOut](
        self,
        agent: Agent[TDeps, TOut],
        prompt: str | list[str | CachePoint],
        *,
        deps: TDeps,
        message_history: list[ModelMessage] | None = None,
        usage_limits: UsageLimits | None = None,
    ) -> AgentRunResult[TOut]:
        """Execute a single agent attempt, converting library failures to the Nohiki taxonomy.

        All classification lives in :func:`_classify_agent_failure`, which dispatches on
        exception TYPE and on ``__cause__`` and never on message text (the one exception,
        and the reason why, is documented there). Anything it declines to classify is
        re-raised untouched rather than mislabelled.

        A bare ``ModelAPIError`` needs its own branch: it is the PARENT of
        ``ModelHTTPError`` and a sibling of ``UnexpectedModelBehavior``, so neither of
        those clauses catches it. PydanticAI raises it for a provider body that carries
        no completion and no error envelope, which it documents as a transient hiccup
        (``models/openrouter.py`` ``_raise_for_no_completion``); a genuine
        model-not-found still arrives through the error envelope as a 404
        ``ModelHTTPError``.

        Args:
            agent: The PydanticAI agent to execute.
            prompt: User prompt string.
            deps: Dependencies to pass to the agent.
            message_history: Optional conversation history.
            usage_limits: Optional token usage limits.

        Returns:
            Raw ``AgentRunResult`` from PydanticAI.

        Raises:
            LLMApplicationRateLimitError: On a rate limit embedded in an HTTP-200 body.
            LLMRateLimitError: On ``ModelHTTPError`` with status 429.
            LLMTransientError: On ``ModelHTTPError`` with 5xx status, on a bare
                ``ModelAPIError``, or on other transient ``UnexpectedModelBehavior``.
            LLMProviderResponseError: On ``ModelHTTPError`` with 4xx (non-429) status,
                or ``UnexpectedModelBehavior`` matching the OpenRouter null-field pattern.
            LLMValidationError: When PydanticAI's output-validation retries are exhausted.
            LLMContentFilterError: When the provider blocked the request on content policy.
            LLMUsageLimitError: When a configured ``UsageLimits`` refused the run.
            LLMConfigurationError: On ``UserError``, a configuration mistake of ours.
        """
        try:
            return await agent.run(
                prompt,
                deps=deps,
                message_history=message_history,
                usage_limits=usage_limits,
            )
        except (AgentRunError, UserError, FallbackExceptionGroup) as exc:
            classified = _classify_agent_failure(exc)
            if classified is None:
                raise
            raise classified from exc

    def _record_metrics(
        self,
        *,
        model: str,
        duration: float,
        usage: RunUsage,
        success: bool,
        error_type: str | None = None,
    ) -> None:
        """Record LLM request metrics from ``RunUsage``."""
        provider = model.split(LLM_MODEL_SEPARATOR, maxsplit=1)[0] if LLM_MODEL_SEPARATOR in model else "unknown"

        self._metrics.record_request(
            RequestMetricsParams(
                model=model,
                provider=provider,
                duration_seconds=duration,
                success=success,
                prompt_tokens=usage.input_tokens,
                completion_tokens=usage.output_tokens,
                cache_read_tokens=usage.cache_read_tokens,
                cache_write_tokens=usage.cache_write_tokens,
                error_type=error_type,
            ),
        )
