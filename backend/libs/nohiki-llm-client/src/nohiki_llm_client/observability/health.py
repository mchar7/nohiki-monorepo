"""LLM health probe for provider connectivity checking.

Uses a registry pattern for provider health endpoints, supporting
OpenRouter, OpenAI, and Ollama with a single generic check method.
"""

import asyncio
import time
from typing import Final

import httpx
from anthropic import AsyncAnthropicVertex
from nohiki_common_exceptions import (
    HealthProbeResult,
    HealthProbeTimer,
    create_healthy_result,
    create_unhealthy_result,
)
from nohiki_observability import get_logger
from pydantic_ai.messages import ModelRequest, UserPromptPart
from pydantic_ai.models import ModelRequestParameters
from pydantic_ai.profiles.openai import openai_model_profile
from pydantic_ai.providers.google_cloud import GoogleCloudProvider
from pydantic_ai.settings import ModelSettings

from nohiki_llm_client.config.constants import (
    DEFAULT_HEALTH_TIMEOUT_SECONDS,
    DEFAULT_RETRY_INTERVAL_SECONDS,
    DEFAULT_STARTUP_TIMEOUT_SECONDS,
    HEALTH_PROBE_NAME,
    HTTP_OK,
    HTTP_UNAUTHORIZED,
    PROVIDER_ANTHROPIC,
    PROVIDER_GOOGLE_VERTEX,
    PROVIDER_LLAMACPP,
    PROVIDER_OLLAMA,
    PROVIDER_OPENAI,
    PROVIDER_OPENROUTER,
)
from nohiki_llm_client.config.settings import (
    LLMModelConfig,
    LLMProviderSettings,
    LLMSettings,
)
from nohiki_llm_client.providers.factory import (
    create_model,
    uses_fixed_openai_reasoning,
)
from nohiki_llm_client.transport import (
    LLAMACPP_API_KEY_PLACEHOLDER,
    OLLAMA_API_KEY_PLACEHOLDER,
    OPENAI_COMPATIBLE_API_KEY_PLACEHOLDER,
    create_model_ssl_context,
    resolve_google_vertex_base_url,
    resolve_local_api_key,
    resolve_vertex_anthropic_base_url,
)

logger = get_logger(__name__)

_HEALTH_ENDPOINTS: Final[dict[str, str]] = {
    PROVIDER_OPENROUTER: "https://openrouter.ai/api/v1/models",
    PROVIDER_OPENAI: "https://api.openai.com/v1/models",
    PROVIDER_ANTHROPIC: "https://api.anthropic.com/v1/models",
}

type _HealthTarget = tuple[LLMModelConfig, LLMProviderSettings]
type _HealthTargetKey = tuple[LLMModelConfig, str | None]
type _HealthChain = tuple[_HealthTarget, ...]
type _HealthTask = asyncio.Task[tuple[bool, str | None]]


def _resolve_health_url(provider: str, base_url: str | None) -> str | None:
    """Resolve provider health check URL, preferring custom base_url when set.

    URL construction is provider-aware because base_url conventions differ:

    - **Anthropic**: ``base_url`` excludes ``/v1`` (the SDK appends it),
      so ``/v1/models`` is appended here for the health check.
    - **OpenAI-compatible**: ``base_url`` already includes ``/v1``,
      so only ``/models`` is appended.

    Args:
        provider: Provider identifier constant.
        base_url: Custom API base URL from model config, or ``None``.

    Returns:
        Health check URL, or ``None`` if no endpoint is registered.
    """
    if base_url is not None:
        stripped = base_url.rstrip("/")
        if provider == PROVIDER_ANTHROPIC:
            return f"{stripped}/v1/models"
        return f"{stripped}/models"
    return _HEALTH_ENDPOINTS.get(provider)


def _build_auth_headers(provider: str, api_key: str | None) -> dict[str, str]:
    """Build provider-appropriate authentication headers for health probes.

    Anthropic's API uses the ``x-api-key`` header format; all other
    providers use the standard ``Authorization: Bearer`` format.

    Args:
        provider: Provider identifier constant.
        api_key: API key string, or ``None`` for unauthenticated checks.

    Returns:
        Headers dict ready for the health check HTTP request.
    """
    if not api_key:
        return {}
    if provider == PROVIDER_ANTHROPIC:
        return {
            "anthropic-version": "2023-06-01",
            "x-api-key": api_key,
        }
    return {"Authorization": f"Bearer {api_key}"}


def _create_health_http_client(
    timeout_seconds: float,
    tls_ca_file: str | None,
) -> httpx.AsyncClient:
    """Create a health client whose scoped trust matches the model transport."""
    return httpx.AsyncClient(
        timeout=timeout_seconds,
        verify=create_model_ssl_context(tls_ca_file),
    )


class LLMHealthProbe:
    """Health probe for the effective fallback chains a service consumes."""

    __slots__ = ("_chains", "_settings", "_targets", "_timeout_seconds")

    def __init__(
        self,
        settings: LLMSettings,
        *,
        chains: tuple[str, ...] | None = None,
        timeout_seconds: float = DEFAULT_HEALTH_TIMEOUT_SECONDS,
    ) -> None:
        """Initialize readiness for the same named chains a service consumes.

        Missing names resolve to the default provider, matching ``LLMClient``.
        ``None`` probes that default directly. Duplicate configs are probed once.

        Args:
            settings: LLM settings containing the default and named chains.
            chains: Named service chains for which at least one fallback must be ready.
                ``None`` selects the default provider.
            timeout_seconds: Overall timeout for the parallel probe set.

        Raises:
            ValueError: If an explicit empty chain tuple is supplied.
        """
        if chains == ():
            msg = "LLM health readiness requires at least one named chain"
            raise ValueError(msg)
        providers = (
            (settings.provider,)
            if chains is None
            else tuple(settings.chains.get(chain, settings.provider) for chain in chains)
        )
        selected_chains: list[_HealthChain] = []
        targets: list[_HealthTarget] = []
        seen_targets: set[_HealthTargetKey] = set()
        seen_chains: set[tuple[_HealthTargetKey, ...]] = set()
        for provider in providers:
            chain_targets: list[_HealthTarget] = []
            chain_keys: list[_HealthTargetKey] = []
            seen_in_chain: set[_HealthTargetKey] = set()
            for config in provider.models:
                key = (config, self._effective_health_api_key(config, provider))
                if key in seen_in_chain:
                    continue
                seen_in_chain.add(key)
                chain_keys.append(key)
                target = (config, provider)
                chain_targets.append(target)
                if key not in seen_targets:
                    seen_targets.add(key)
                    targets.append(target)
            signature = tuple(chain_keys)
            if signature not in seen_chains:
                seen_chains.add(signature)
                selected_chains.append(tuple(chain_targets))
        self._settings = settings
        self._chains = tuple(selected_chains)
        self._targets = tuple(targets)
        self._timeout_seconds = timeout_seconds

    @property
    def name(self) -> str:
        """Probe identifier."""
        return HEALTH_PROBE_NAME

    async def check(self) -> HealthProbeResult:
        """Verify every selected chain has at least one reachable model."""
        with HealthProbeTimer() as timer:
            tasks: dict[_HealthTargetKey, _HealthTask] = {}
            try:
                for config, provider_settings in self._targets:
                    key = (config, self._effective_health_api_key(config, provider_settings))
                    tasks[key] = asyncio.create_task(self._check_model(config, provider_settings))
                async with asyncio.timeout(self._timeout_seconds):
                    results = await asyncio.gather(*(self._check_chain(chain, tasks) for chain in self._chains))
                for ok, config, err in results:
                    if not ok:
                        details = {}
                        if config is not None:
                            details = {
                                "model": config.model,
                                "provider": config.provider_name,
                            }
                        return create_unhealthy_result(
                            name=self.name,
                            message=err or "LLM fallback chain check failed",
                            latency_ms=timer.elapsed_ms,
                            details=details,
                        )
                models = ", ".join(config.model for _, config, _ in results if config is not None)
                return create_healthy_result(
                    name=self.name,
                    message=f"LLM model chains are healthy: {models}",
                    latency_ms=timer.elapsed_ms,
                    details={"models": models},
                )
            except TimeoutError:
                return create_unhealthy_result(
                    name=self.name,
                    message=f"LLM health check timeout after {self._timeout_seconds}s",
                    latency_ms=timer.elapsed_ms,
                )
            except (OSError, RuntimeError) as exc:
                return create_unhealthy_result(
                    name=self.name,
                    message=f"LLM connection failed: {exc}",
                    latency_ms=timer.elapsed_ms,
                    details={"error": str(exc), "error_type": type(exc).__name__},
                )
            except Exception as exc:
                logger.exception("Unexpected error during LLM health check")
                return create_unhealthy_result(
                    name=self.name,
                    message=f"Unexpected LLM health check failure: {exc}",
                    latency_ms=timer.elapsed_ms,
                    details={"error": str(exc), "error_type": type(exc).__name__},
                )
            finally:
                pending = [task for task in tasks.values() if not task.done()]
                for task in pending:
                    task.cancel()
                if pending:
                    await asyncio.gather(*pending, return_exceptions=True)

    async def _check_chain(
        self,
        chain: _HealthChain,
        tasks: dict[_HealthTargetKey, _HealthTask],
    ) -> tuple[bool, LLMModelConfig | None, str | None]:
        """Return as soon as one model in a fallback chain is usable."""
        pending = {
            tasks[(config, self._effective_health_api_key(config, provider_settings))]: config
            for config, provider_settings in chain
        }
        errors: list[str] = []
        last_config: LLMModelConfig | None = None
        while pending:
            done, _ = await asyncio.wait(pending, return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                config = pending.pop(task)
                last_config = config
                ok, err = task.result()
                if ok:
                    return True, config, None
                errors.append(err or f"LLM model '{config.model}' check failed")
        return False, last_config, "LLM fallback chain unavailable: " + "; ".join(errors)

    async def _check_model(
        self,
        config: LLMModelConfig,
        provider_settings: LLMProviderSettings,
    ) -> tuple[bool, str | None]:
        """Require both endpoint liveness and one exact-model request."""
        provider = config.provider_name
        if config.health_url is not None:
            ok, err = await self._check_cloud_endpoint(
                config.health_url,
                headers={},
                tls_ca_file=config.tls_ca_file,
            )
        elif provider == PROVIDER_OLLAMA:
            ok, err = await self._check_ollama(config)
        elif provider == PROVIDER_LLAMACPP:
            base_url = config.base_url
            if base_url is None:
                return False, "llama.cpp base_url not configured"
            api_key = resolve_local_api_key(
                config.api_key.get_secret_value() if config.api_key else None,
                placeholder=LLAMACPP_API_KEY_PLACEHOLDER,
            )
            ok, err = await self._check_cloud_endpoint(
                f"{base_url.rstrip('/')}/models",
                headers=_build_auth_headers(provider, api_key),
                tls_ca_file=config.tls_ca_file,
            )
        elif provider == PROVIDER_GOOGLE_VERTEX:
            return await self._check_google_vertex(config, provider_settings)
        else:
            endpoint = _resolve_health_url(provider, config.base_url)
            if endpoint is None:
                return False, f"No health check for provider '{provider}'"
            api_key = self._effective_health_api_key(config, provider_settings)
            ok, err = await self._check_cloud_endpoint(
                endpoint,
                headers=_build_auth_headers(provider, api_key),
                tls_ca_file=config.tls_ca_file,
            )
        if not ok:
            return ok, err
        if provider == PROVIDER_GOOGLE_VERTEX:
            return await self._check_google_vertex(config, provider_settings)
        return await self._check_exact_model(config, provider_settings)

    async def _check_exact_model(
        self,
        config: LLMModelConfig,
        provider_settings: LLMProviderSettings,
    ) -> tuple[bool, str | None]:
        """Make one bounded request through the inference model and owned transport."""
        transport_clients: list[httpx.AsyncClient] = []
        try:
            try:
                probe_config = config.model_copy(update={"reasoning_effort": "disabled"})
                openai_uses_reasoning = False
                if config.provider_name == PROVIDER_OPENAI:
                    profile = openai_model_profile(config.model_name)
                    reasoning_enabled_by_default = profile.get("openai_reasoning_enabled_by_default", False)
                    supports_none = profile.get("openai_supports_reasoning_effort_none", False)
                    fixed_reasoning = uses_fixed_openai_reasoning(config.model_name)
                    openai_uses_reasoning = reasoning_enabled_by_default or fixed_reasoning
                    if (reasoning_enabled_by_default and not supports_none) or fixed_reasoning:
                        probe_config = config
                model = create_model(
                    probe_config,
                    provider_settings,
                    transport_clients=transport_clients,
                )
                probe_max_tokens = 16 if config.provider_name == PROVIDER_OPENAI else 1
                request_settings = ModelSettings(
                    max_tokens=probe_max_tokens,
                    timeout=self._timeout_seconds,
                )
                if not openai_uses_reasoning:
                    request_settings["temperature"] = 0.0
                await model.request(
                    [ModelRequest(parts=[UserPromptPart(content="health")])],
                    request_settings,
                    ModelRequestParameters(),
                )
            finally:
                await asyncio.gather(*(client.aclose() for client in transport_clients))
        except Exception as exc:
            logger.exception("Exact LLM model readiness request failed")
            return False, f"LLM model '{config.model}' request failed: {exc}"
        return True, None

    async def _check_cloud_endpoint(
        self,
        url: str,
        *,
        headers: dict[str, str],
        tls_ca_file: str | None = None,
    ) -> tuple[bool, str | None]:
        """Generic health check against a cloud provider's models endpoint.

        Args:
            url: Provider models endpoint URL.
            headers: Authentication headers for the request.
            tls_ca_file: Optional CA file scoped to this health request.

        Returns:
            Tuple of (success, error_message).
        """
        try:
            async with _create_health_http_client(self._timeout_seconds, tls_ca_file) as client:
                response = await client.get(url, headers=headers)

            if response.status_code == HTTP_OK:
                return True, None
            if response.status_code == HTTP_UNAUTHORIZED:
                return False, "API key is invalid"
        except (OSError, RuntimeError) as exc:
            return False, f"Connection failed: {exc}"
        except Exception as exc:
            logger.exception("Unexpected error during cloud provider health check")
            return False, f"Unexpected health check failure: {exc}"
        else:
            return False, f"Provider returned status {response.status_code}"

    def _resolve_health_api_key(
        self,
        config: LLMModelConfig,
        provider_settings: LLMProviderSettings | None = None,
    ) -> str | None:
        """Resolve a credential from the model and its owning chain registry."""
        if config.api_key is not None:
            return config.api_key.get_secret_value()
        owner = self._settings.provider if provider_settings is None else provider_settings
        registry_key = owner.api_keys.get(config.provider_name)
        if registry_key is not None:
            return registry_key.get_secret_value()
        return None

    def _effective_health_api_key(
        self,
        config: LLMModelConfig,
        provider_settings: LLMProviderSettings,
    ) -> str | None:
        """Resolve authentication consumed by the exact-model readiness request."""
        if config.provider_name == PROVIDER_OLLAMA:
            return resolve_local_api_key(
                config.api_key.get_secret_value() if config.api_key else None,
                placeholder=OLLAMA_API_KEY_PLACEHOLDER,
            )
        if config.provider_name == PROVIDER_LLAMACPP:
            return resolve_local_api_key(
                config.api_key.get_secret_value() if config.api_key else None,
                placeholder=LLAMACPP_API_KEY_PLACEHOLDER,
            )
        if config.provider_name == PROVIDER_GOOGLE_VERTEX and config.model_name.startswith("claude"):
            return None
        explicit_key = self._resolve_health_api_key(config, provider_settings)
        if explicit_key is None and config.provider_name == PROVIDER_OPENAI and config.base_url is not None:
            return OPENAI_COMPATIBLE_API_KEY_PLACEHOLDER
        return explicit_key

    async def _check_ollama(
        self,
        config: LLMModelConfig,
    ) -> tuple[bool, str | None]:
        """Probe Ollama's native tags route with inference-equivalent auth."""
        if not config.base_url:
            return False, "Ollama base_url not configured"

        base = config.base_url.rstrip("/").removesuffix("/v1")
        url = f"{base}/api/tags"
        api_key = resolve_local_api_key(
            config.api_key.get_secret_value() if config.api_key is not None else None,
            placeholder=OLLAMA_API_KEY_PLACEHOLDER,
        )

        try:
            async with _create_health_http_client(self._timeout_seconds, config.tls_ca_file) as client:
                response = await client.get(
                    url,
                    headers=_build_auth_headers(PROVIDER_OLLAMA, api_key),
                )
        except (OSError, RuntimeError) as exc:
            return False, f"Ollama connection failed: {exc}"
        except Exception as exc:
            logger.exception("Unexpected error during Ollama health check")
            return False, f"Unexpected Ollama health check failure: {exc}"
        if response.status_code == HTTP_OK:
            return True, None
        return False, f"Ollama returned status {response.status_code}"

    async def _check_google_vertex(
        self,
        config: LLMModelConfig,
        provider_settings: LLMProviderSettings,
    ) -> tuple[bool, str | None]:
        """Check the exact Vertex transport, authentication, and region used by inference."""
        try:
            async with _create_health_http_client(
                self._timeout_seconds,
                config.tls_ca_file,
            ) as http_client:
                if config.model_name.startswith("claude"):
                    project = config.google_project
                    region = config.google_location
                    if project is None or region is None:
                        return (
                            False,
                            "Google Vertex Claude project and location are not configured",
                        )
                    base_url = resolve_vertex_anthropic_base_url(config.base_url, region=region)
                    anthropic_client = AsyncAnthropicVertex(
                        project_id=project,
                        region=region,
                        http_client=http_client,
                        base_url=base_url,
                    )
                    await anthropic_client.messages.count_tokens(
                        model=config.model_name,
                        messages=[{"role": "user", "content": "health"}],
                    )
                else:
                    api_key = self._resolve_health_api_key(config, provider_settings)
                    uses_adc = (
                        config.google_project is not None or config.google_location is not None or api_key is None
                    )
                    if uses_adc:
                        project = config.google_project
                        location = config.google_location
                        if project is None or location is None:
                            return (
                                False,
                                "Google Vertex project and location are not configured",
                            )
                        base_url = resolve_google_vertex_base_url(
                            config.base_url,
                            location=location,
                            has_api_key=False,
                        )
                        provider = GoogleCloudProvider(
                            project=project,
                            location=location,
                            http_client=http_client,
                            base_url=base_url,
                        )
                    else:
                        base_url = resolve_google_vertex_base_url(
                            config.base_url,
                            location=None,
                            has_api_key=True,
                        )
                        provider = GoogleCloudProvider(
                            api_key=api_key,
                            http_client=http_client,
                            base_url=base_url,
                        )
                    await provider.client.aio.models.get(model=config.model_name)
        except (OSError, RuntimeError) as exc:
            return False, f"Google Vertex connection failed: {exc}"
        except Exception as exc:
            logger.exception("Unexpected error during Google Vertex health check")
            return False, f"Unexpected Google Vertex health check failure: {exc}"
        return True, None


async def ensure_llm_ready(
    settings: LLMSettings,
    *,
    chains: tuple[str, ...] | None = None,
    timeout_seconds: float = DEFAULT_STARTUP_TIMEOUT_SECONDS,
    retry_interval_seconds: float = DEFAULT_RETRY_INTERVAL_SECONDS,
) -> None:
    """Block startup until every selected LLM chain has a usable candidate.

    Args:
        settings: LLM settings containing the default and named chains.
        chains: Named chains that each require at least one reachable candidate.
            ``None`` selects the default provider.
        timeout_seconds: Hard deadline for startup readiness.
        retry_interval_seconds: Interval between retry attempts.

    Raises:
        RuntimeError: If LLM is unavailable after timeout.
    """
    start_time = time.perf_counter()
    attempt = 0

    logger.info(
        "Waiting for LLM model chains to become available",
        timeout_seconds=timeout_seconds,
        chains=chains,
    )

    while (remaining := timeout_seconds - (time.perf_counter() - start_time)) > 0:
        attempt += 1
        probe = LLMHealthProbe(
            settings,
            chains=chains,
            timeout_seconds=min(DEFAULT_HEALTH_TIMEOUT_SECONDS, remaining),
        )
        result = await probe.check()

        if result.is_healthy():
            elapsed = time.perf_counter() - start_time
            logger.info(
                "LLM model chains are available",
                elapsed_seconds=round(elapsed, 2),
                attempts=attempt,
                chains=chains,
            )
            return

        remaining = timeout_seconds - (time.perf_counter() - start_time)
        if remaining > 0:
            wait_time = min(retry_interval_seconds, remaining)
            logger.debug(
                "LLM not available, retrying",
                attempt=attempt,
                error=result.message,
                retry_in_seconds=wait_time,
            )
            await asyncio.sleep(wait_time)

    elapsed = time.perf_counter() - start_time
    msg = f"LLM unavailable after {elapsed:.1f}s ({attempt} attempts)"
    logger.error(
        "LLM startup timeout",
        elapsed_seconds=round(elapsed, 2),
        attempts=attempt,
    )
    raise RuntimeError(msg)
