# Nohiki LLM Client

Wraps [PydanticAI](https://ai.pydantic.dev/) to provide structured LLM output generation
with automatic schema-validation retries, HTTP-level retry with exponential backoff,
provider-level cost tracking, and OpenRouter prompt caching. Three services depend on it:
`doc-content-service` (resume/cover letter generation from dynamic JSON schemas),
`job-ingest-enrichment-service` (structured extraction of job posting data and skill clarification),
and `job-correlation-evaluation-service` (LLM-assisted feature scoring).

## Quick Start

```python
from pydantic import BaseModel
from nohiki_llm_client import LLMClient, LLMResult, StructuredAgentConfig, LLMMixin
from nohiki_core_settings import NohikiBaseSettings

# 1. Add LLMMixin to your service settings
class Settings(LLMMixin, NohikiBaseSettings):
    model_config = SettingsConfigDict(env_prefix="MY_SERVICE_")

# 2. Create the client. Use one per service, typically as a module-level singleton
settings = get_settings()
client = LLMClient(settings.llm)

# 3. Define your output schema
class JobSummary(BaseModel):
    title: str
    seniority: str
    skills: list[str]

# 4. Create an agent (create once, reuse across requests)
agent = client.create_agent(StructuredAgentConfig(
    deps_type=str,           # type of per-request context passed to system_prompt_fn
    output_type=JobSummary,
    system_prompt="Extract structured data from job postings.",
))

# 5. Run it. Retries, metrics, and cost tracking are automatic
result: LLMResult[JobSummary] = await client.run(agent, prompt, deps="context")
print(result.output.skills)
print(f"${result.cost_usd:.6f}  |  {result.usage.input_tokens} in / {result.usage.output_tokens} out")
```

To use a named chain (e.g., a separate model for a specific use case):

```python
client = LLMClient(settings.llm, chain="enrichment")
```

If the named chain is not found in `settings.llm.chains`, the client falls back to
`settings.llm.provider` automatically.

## Core Concepts

### Structured vs. Dynamic Schema Output

`LLMClient` supports two agent types depending on whether the output schema is known at
compile time.

**`StructuredAgentConfig`** uses a `BaseModel` subclass as the output type. PydanticAI
serialises the model's JSON schema into the tool-call definition and validates the response
against it. If validation fails, PydanticAI sends the validation error back to the model
and retries up to `max_tool_retries` times (default: 3). This is how
`job-ingest-enrichment-service` extracts `JobExtractionSchema` and `SkillClarificationResponse`.

**`DynamicAgentConfig`** uses a raw `dict[str, Any]` JSON schema passed as `json_schema`.
PydanticAI wraps it in a `StructuredDict` output type. This is how `doc-content-service`
handles resume and cover letter generation. The schema comes from the document template,
which changes per request, so it cannot be a fixed Pydantic model. When the schema varies
per template but the agent is long-lived, services key an agent cache on the template's
`version_id` to avoid rebuilding the agent for every request.

Both agent types share the same `client.run()` entry point and receive identical retry,
metrics, and cost tracking behaviour.

### Retry Architecture (Two Independent Layers)

There are two distinct retry mechanisms, each targeting a different failure mode:

**PydanticAI agent-level retries** (configurable via `LLM__PROVIDER__MAX_TOOL_RETRIES`,
default: 3): When the model produces output that fails schema validation, PydanticAI feeds
the `ValidationError` back to the model as an additional message and retries the LLM call.
This is purely within PydanticAI. When all retries are exhausted, PydanticAI raises
`UnexpectedModelBehavior` with the message `"Exceeded maximum retries"`.

**Tenacity application-level retries** (3 attempts, exponential backoff 2s-30s): `LLMClient.run()`
wraps the PydanticAI call in a Tenacity `AsyncRetrying` loop. It retries only on
`LLMTransientError` (HTTP 5xx, momentary null-field responses from the provider). It does NOT
retry on `LLMValidationError` (schema exhaustion), `LLMProviderResponseError` (permanent routing
failure), or `LLMRateLimitError` (rate limiting). Rate-limit errors propagate up to the Kafka
consumer, which has its own backoff strategy.

**HTTP transport-level retries** (5 attempts, Tenacity `AsyncTenacityTransport`): The
`httpx.AsyncClient` used by every provider also retries on 429, 502, 503, 504, and network
errors, with `Retry-After` header support. This operates below the PydanticAI layer.

The exception hierarchy used by `LLMClient` to classify outcomes:

| Exception | Retried by Tenacity | Kafka consumer action |
| --- | --- | --- |
| `LLMTransientError` | Yes (up to 3 attempts) | Exponential backoff retry |
| `LLMRateLimitError` | No at the application layer (HTTP transport honors `Retry-After`) | Backoff retry |
| `LLMValidationError` | No | DLQ |
| `LLMProviderResponseError` | No | DLQ |
| `LLMAuthenticationError` | No | DLQ |
| `LLMContextTooLongError` | No | DLQ |

### Provider Configuration and Model Chains

Models are identified by `provider:model_name` strings (for example `openai:primary-model`,
`openrouter:vendor/fallback-model`, `anthropic:generation-model`, or `ollama:local-model`). `LLMProviderSettings`
holds a priority-ordered list of
`LLMModelConfig` entries. If there are multiple models, the factory wraps them in a PydanticAI
`FallbackModel` -- the first model is used; subsequent entries are tried automatically on failure.

API keys live in `ApiKeyRegistry`, a Pydantic model with `extra="allow"` that coerces all
values to `SecretStr`. Keys are resolved per-model: first the model's own `api_key`, then the
registry keyed by provider name. Chains automatically inherit the `provider.api_keys` registry
at settings parse time, so a single secrets mount at `/run/secrets/llm/provider/api_keys/` serves
all chains.

OpenRouter models accept per-model routing controls: `provider_order` (with
`provider_allow_fallbacks`) pins upstream provider preference, and `provider_zdr`
requires Zero Data Retention. When `provider_zdr` is `true`, every request carries
`provider.zdr = true` so OpenRouter routes only to endpoints that neither log nor
retain prompt or response data; it merges alongside `provider_order` when both are
set. Both controls are ignored by non-OpenRouter transports.

Named chains (`LLMSettings.chains`) let services configure distinct models per use case without
creating multiple `LLMClient` instances:

```python
# env config
JOB_INGEST_ENRICHMENT__LLM__PROVIDER__MODELS__0__MODEL=openai:primary-model
JOB_INGEST_ENRICHMENT__LLM__PROVIDER__MODELS__0__REASONING_EFFORT=high
JOB_INGEST_ENRICHMENT__LLM__CHAINS__SKILL_CLARIFICATION__MODELS__0__MODEL=openrouter:vendor/fast-model
JOB_INGEST_ENRICHMENT__LLM__CHAINS__SKILL_CLARIFICATION__MODELS__0__REASONING_EFFORT=low

# usage
extraction_client = LLMClient(settings.llm, chain="extraction")
clarification_client = LLMClient(settings.llm, chain="skill_clarification")
```

### Prompt Caching (OpenRouter)

When the primary model is an OpenRouter provider and `LLM__CACHING__ENABLED=true` (the default),
the factory wraps the model in `CachingOpenRouterModel`. This subclass injects
`cache_control: {"type": "ephemeral", "ttl": "5m"}` into system prompt message blocks before
dispatching the request. OpenRouter forwards this to supporting providers (Anthropic, Google
Gemini) which serve subsequent identical system prompts from cache, reducing input token costs
on repeated calls with the same long system prompt.

Cache hits emit `cache_read_tokens` in `RunUsage`, which `LLMClient._record_metrics()` counts
separately from regular `prompt_tokens`. The `nohiki_llm_cache_hits_total` and
`nohiki_llm_cache_read_tokens_total` Prometheus counters track this.

### Cost Tracking

`LLMResult.cost_usd` is the estimated USD cost of each call. Cost resolution uses two sources
in priority order:

1. **Provider metadata** (`provider_details["cost"]` in `ModelResponse`): OpenRouter includes
   actual billed costs in the response. When present, this value is used directly.
2. **`genai-prices` snapshot**: If the provider did not include cost metadata, `calc_llm_cost()`
   looks up the model in the bundled `genai-prices` pricing table. Returns `None` for unknown
   models rather than raising.

Cost is recorded to `nohiki_llm_cost_microdollars_total` as integer microdollars for Prometheus
counter compatibility.

### Concurrency Limiting

`LLMProviderSettings.concurrency_limit` sets a maximum number of concurrent requests via
PydanticAI's `ConcurrencyLimitedModel`. For Ollama (a single-threaded local process), the default
is `concurrency_limit=1` when using `create_settings_from_model()`. Critically, all `LLMClient`
instances targeting the same Ollama base URL share a single `ConcurrencyLimiter` from a
module-level registry. Without sharing, two clients could each hold their own semaphore(1) and
issue concurrent requests, defeating the limit.

```python
# Reset the registry in tests that create fresh event loops
from nohiki_llm_client import reset_provider_limiters
reset_provider_limiters()
```

### OpenRouter Quirks Registry

Several OpenRouter-routed providers have behavioural differences that cause PydanticAI to fail
without per-model handling:

- **`xiaomi/*` and `openai/gpt-oss-120b:exacto`**: Serialise `$ref`-referenced nested objects
  as escaped JSON strings in tool-call arguments. `InlinedRefsJsonSchemaTransformer` eliminates
  all `$defs`/`$ref` pointers before the request is sent.
- **`qwen/qwen3-next`**: Responds using Hermes XML tool-call format. Setting
  `default_structured_output_mode="native"` bypasses tool-calling entirely; structured output
  is requested via `response_format: json_schema` instead.
- **`meta-llama/*`**: Rejects `tool_choice="required"`. Profile sets
  `openai_supports_tool_choice_required=False` so PydanticAI sends `tool_choice="auto"`.
- **`qwen/qwen3-vl`, `meta-llama`, `qwen/qwen3-next`**: Reject the `reasoning` request parameter
  with HTTP 400. `supports_openrouter_reasoning=False` in their quirk entries suppresses it.

The quirks registry uses longest-prefix matching so series-level overrides (e.g., `qwen/qwen3-vl`)
take precedence over vendor-level entries.

### llamacpp Provider

`llamacpp` is a local inference alternative to Ollama. It targets a llama.cpp HTTP server
running an OpenAI-compatible Chat Completions API, and does not require an API key. Unlike Ollama,
llama.cpp surfaces reasoning output in a `reasoning_content` message field (not in `usage`).
`LlamaCppProvider` configures the PydanticAI profile to parse this into `ThinkingPart` objects.

```python
# Via settings
MY_SERVICE__LLM__PROVIDER__MODELS__0__MODEL=llamacpp:Qwen3.5-35B-A3B-UD-Q4_K_M.gguf
MY_SERVICE__LLM__PROVIDER__MODELS__0__BASE_URL=http://llama.example.test:8888/v1

# Or via env var
export LLAMACPP_BASE_URL=http://llama.example.test:8888/v1
```

## API Reference

### LLMClient

- **`LLMClient(settings, *, chain=None)`** -- Primary client class. `settings` is `LLMSettings`
  from `LLMMixin`. `chain` selects a named use-case chain; falls back to `settings.provider`
  when `None` or not found. Lazily builds the model chain on first use.
- **`create_agent(config: StructuredAgentConfig) -> Agent`** -- Create a PydanticAI agent with
  a fixed Pydantic model output type. Create once per process and reuse.
- **`create_dynamic_schema_agent(config: DynamicAgentConfig) -> Agent`** -- Create an agent with
  a raw JSON schema output type. When `config.system_prompt_fn` is set, it is registered as a
  dynamic prompt callback so it can access per-request `RunContext.deps`.
- **`run(agent, prompt, *, deps, message_history=None, usage_limits=None) -> LLMResult`** --
  Execute any agent. Applies Tenacity retries, records OTel metrics, and computes `cost_usd`.

### LLMResult

```python
@dataclass(frozen=True, slots=True)
class LLMResult[T]:
    output: T               # parsed structured output
    usage: RunUsage         # input_tokens, output_tokens, cache_read_tokens, cache_write_tokens
    model_used: str         # "openrouter:google/gemini-3-flash"
    duration_seconds: float
    cost_usd: float | None  # None if model not in genai-prices and provider omitted cost
    messages: tuple[ModelMessage, ...]  # full history including ThinkingPart objects
    retry_count: int        # number of Tenacity retries (0 = first attempt succeeded)
```

### Agent Configuration

- **`StructuredAgentConfig[TDeps, TOutput: BaseModel]`** -- `deps_type`, `output_type`,
  optional `system_prompt` string.
- **`DynamicAgentConfig[TDeps]`** -- `deps_type`, `json_schema` dict, `schema_name`,
  optional `schema_description`, `system_prompt`, or `system_prompt_fn: (RunContext) -> str`.

### Factory Helpers

- **`create_settings_from_model(model, api_keys=None, *, reasoning_effort, timeout_seconds)`** --
  Convenience factory for single-model configuration. Detects Ollama automatically and applies
  `concurrency_limit=1` and `DEFAULT_OLLAMA_NUM_CTX`.
- **`resolve_chain(chain_name, settings)`** -- Returns the named chain's `LLMProviderSettings`
  or falls back to `settings.provider`. Called internally by `LLMClient.__init__`.

### Observability

- **`LLMHealthProbe(settings, *, chains=None)`**: `async check() -> HealthProbeResult`.
  Runs bounded endpoint and exact-model checks concurrently for each selected effective chain.
  Readiness requires at least one usable candidate per chain, so an unavailable primary does not
  mask a working fallback. Supports OpenRouter, OpenAI, Anthropic, Google Vertex, Ollama, and
  llama.cpp. Register with `nohiki-fastapi-utils` health during service lifespan startup.
- **`ensure_llm_ready(settings, *, chains=None, timeout_seconds=30, retry_interval_seconds=5)`**:
  Blocks startup until every selected chain has a usable candidate. Raises `RuntimeError` after
  the timeout.
- **`get_llm_metrics() -> LLMMetrics`** -- Returns the singleton `LLMMetrics` instance (OTel
  counters/histograms). `LLMClient` calls this automatically; use it only for custom metric reads.
- **`llm_span_context(*, use_case, user_id=None, session_id=None, metadata=None)`** -- Context
  manager that adds OpenInference attributes to the current Phoenix trace span.
- **`prompt_template_context(*, template, variables, version="v1")`** -- Context manager for
  prompt version tracking in Phoenix.
- **`set_llm_span_feedback(*, score=None, label=None, explanation=None)`** -- Annotates the
  current span with user feedback. Call after the `run()` completes.

### Evaluation Framework

`LLMEvaluator` wraps `pydantic-evals` to run structured output agents against labelled datasets:

```python
from nohiki_llm_client import LLMEvaluator, FieldMatchEvaluator, create_extraction_dataset
from pydantic_evals import Case

dataset = create_extraction_dataset(
    "job_extraction_v1",
    cases=[Case(name="senior_swe", inputs=listing, expected_output=expected)],
    field_evaluators=[("seniority_level", 0.0), ("location.country_code", 0.0)],
)

evaluator = LLMEvaluator(client)
result = await evaluator.evaluate_structured(dataset, agent_config=agent_config)
print(f"Pass rate: {result.pass_rate:.1%}")
```

- **`FieldMatchEvaluator(field_path, tolerance=0.0, case_sensitive=True)`** -- Scores exact
  match or numeric near-match using dot-notation path to reach nested fields.
- **`ListLengthEvaluator(field_path, min_items=None, max_items=None, tolerance_ratio=0.2)`** --
  Scores whether a list field extracted the right number of items (useful for skill extraction).

## Configuration

### LLMMixin

Add `LLMMixin` to your service settings class to expose the `llm: LLMSettings` field:

```python
from nohiki_llm_client import LLMMixin
from nohiki_core_settings import NohikiBaseSettings

class Settings(LLMMixin, KafkaMixin, NohikiBaseSettings):
    model_config = SettingsConfigDict(env_prefix="MY_SERVICE_")
```

### Environment Variables

All variables are prefixed by the service's `env_prefix`. The examples below use `MY_SERVICE_`.

**Provider / model chain:**

| Variable | Default | Description |
| --- | --- | --- |
| `MY_SERVICE__LLM__PROVIDER__MODELS__0__MODEL` | *(required)* | Primary model in `provider:name` format |
| `MY_SERVICE__LLM__PROVIDER__MODELS__1__MODEL` | -- | Fallback model (tried when primary fails) |
| `MY_SERVICE__LLM__PROVIDER__API_KEYS__OPENROUTER` | -- | OpenRouter API key |
| `MY_SERVICE__LLM__PROVIDER__API_KEYS__OPENAI` | -- | OpenAI API key |
| `MY_SERVICE__LLM__PROVIDER__TEMPERATURE` | `0.0` | Sampling temperature (0.0-2.0) |
| `MY_SERVICE__LLM__PROVIDER__MAX_TOKENS` | `null` | Max output tokens (null = provider default) |
| `MY_SERVICE__LLM__PROVIDER__TIMEOUT_SECONDS` | `120.0` | Per-request timeout |
| `MY_SERVICE__LLM__PROVIDER__MAX_TOOL_RETRIES` | `3` | PydanticAI schema-validation retries |
| `MY_SERVICE__LLM__PROVIDER__REASONING_EFFORT` | `high` | `disabled`, `low`, `medium`, or `high` |
| `MY_SERVICE__LLM__PROVIDER__CONCURRENCY_LIMIT` | `null` | Max concurrent requests (null = unlimited) |
| `MY_SERVICE__LLM__PROVIDER__MODELS__0__PROVIDER_ZDR` | `false` | OpenRouter Zero Data Retention: sends `provider.zdr=true` so requests route only to non-retaining endpoints (OpenRouter only) |

**Caching (OpenRouter only):**

| Variable | Default | Description |
| --- | --- | --- |
| `MY_SERVICE__LLM__CACHING__ENABLED` | `true` | Enable `cache_control` on system prompts |
| `MY_SERVICE__LLM__CACHING__TTL` | `5m` | Cache TTL: `5m` or `1h` |

**Instrumentation (Phoenix/OpenInference):**

| Variable | Default | Description |
| --- | --- | --- |
| `MY_SERVICE__LLM__INSTRUMENTATION__ENABLED` | `false` | Enable Phoenix tracing |
| `MY_SERVICE__LLM__INSTRUMENTATION__COLLECTOR_ENDPOINT` | `""` | Phoenix gRPC collector URL |
| `MY_SERVICE__LLM__INSTRUMENTATION__PROJECT_NAME` | `nohiki` | Phoenix project name |
| `MY_SERVICE__LLM__INSTRUMENTATION__SERVICE_NAME` | `nohiki-llm` | Service name in traces |

**Named chains:**

Named chains allow different models per use case. They inherit `api_keys` from the default
provider, so no additional secrets are needed:

```bash
MY_SERVICE__LLM__CHAINS__EXTRACTION__MODELS__0__MODEL=openrouter:vendor/extraction-model
MY_SERVICE__LLM__CHAINS__EXTRACTION__MODELS__0__REASONING_EFFORT=low
MY_SERVICE__LLM__CHAINS__DOCUMENT_GENERATION__MODELS__0__MODEL=openai:generation-model
MY_SERVICE__LLM__CHAINS__DOCUMENT_GENERATION__MODELS__0__REASONING_EFFORT=high
# api_keys are automatically inherited from LLM__PROVIDER__API_KEYS__*
```

**Ollama-specific options:**

| Variable | Default | Description |
| --- | --- | --- |
| `MY_SERVICE__LLM__PROVIDER__OLLAMA__NUM_CTX` | `16384` | Context window tokens |
| `MY_SERVICE__LLM__PROVIDER__OLLAMA__TOP_K` | `40` | Top-K token candidates |
| `MY_SERVICE__LLM__PROVIDER__OLLAMA__REPEAT_PENALTY` | `1.1` | Repetition penalty |
| `MY_SERVICE__LLM__PROVIDER__OLLAMA__THINK` | `true` | Enable extended reasoning mode |

Ollama requires `base_url` per model config:

```bash
MY_SERVICE__LLM__PROVIDER__MODELS__0__MODEL=ollama:qwq-32b
MY_SERVICE__LLM__PROVIDER__MODELS__0__BASE_URL=http://localhost:11434/v1
```

## Testing

Use `pydantic_ai.models.test.TestModel` as the underlying model to avoid real API calls. The
`LLMClient` initialises a model chain lazily, so patch `create_full_model_chain` to inject a
`TestModel` without touching provider auth:

```python
from unittest.mock import patch
from pydantic_ai.models.test import TestModel
from nohiki_llm_client import LLMClient, StructuredAgentConfig, LLMResult
from nohiki_llm_client.config.settings import (
    ApiKeyRegistry, LLMModelConfig, LLMProviderSettings, LLMSettings,
)

@pytest.fixture
def llm_settings() -> LLMSettings:
    return LLMSettings(
        provider=LLMProviderSettings(
            models=[LLMModelConfig(model="openrouter:test/model")],
            api_keys=ApiKeyRegistry.model_validate({"openrouter": "test-key"}),
        ),
    )

async def test_my_agent(llm_settings):
    client = LLMClient(llm_settings)
    # TestModel is injected; no HTTP calls made
    agent = client.create_agent(StructuredAgentConfig(
        deps_type=MyContext,
        output_type=MyOutput,
        system_prompt="...",
    ))
    result = await client.run(agent, "prompt", deps=MyContext(...))
    assert isinstance(result.output, MyOutput)
```

`TestModel` generates minimal valid output based on the Pydantic schema, so it validates the
agent configuration and `LLMResult` handling without requiring real model responses.

To test retry behaviour, patch `agent.run` to raise `LLMTransientError` on the first call:

```python
from nohiki_llm_client.exceptions import LLMTransientError

with patch.object(agent, "run") as mock_run:
    mock_run.side_effect = [LLMTransientError("transient"), mock_result]
    result = await client.run(agent, "prompt", deps=deps)
    assert result.retry_count == 1
```

Call `reset_provider_limiters()` in test teardown when tests create new event loops, to clear
the shared Ollama concurrency limiter registry:

```python
from nohiki_llm_client import reset_provider_limiters

@pytest.fixture(autouse=True)
def clear_limiters():
    yield
    reset_provider_limiters()
```

Integration tests (marked `@pytest.mark.integration`) require a live provider. Run them
selectively with `uv run pytest -m integration`.

## Design Decisions

### Why not use PydanticAI directly in services?

Provider auth resolution, the OpenRouter quirks registry, `CachingOpenRouterModel`, the
`RobustOpenRouterModel` embedded-error extraction, and the HTTP retry transport all require
non-trivial knowledge of provider behaviour. Centralising this prevents each service from
independently discovering that Xiaomi backends serialise `$ref` pointers incorrectly, or that
OpenRouter returns HTTP 200 with null `choices` when a model is not found.

### Why two retry layers?

PydanticAI's agent-level retries handle LLM quality failures: the model produced an output that
failed schema validation. Tenacity's application-level retries handle provider failures: the
HTTP connection was unreliable or the provider was temporarily overloaded. These are orthogonal
failure modes with different recovery strategies.

When PydanticAI exhausts its validation retries, it raises `UnexpectedModelBehavior("Exceeded
maximum retries")`. `LLMClient._single_attempt()` discriminates this from other
`UnexpectedModelBehavior` exceptions by prefix-matching the message, converting it to
`LLMValidationError` (non-retryable) rather than `LLMTransientError` (retryable). This prevents
Tenacity from masking a prompt-engineering problem as a transient failure.

### Cost tracking fallback order

OpenRouter's `provider_details["cost"]` field carries actual billed costs and is authoritative
when present. The `genai-prices` snapshot provides estimates for cases where the provider does
not include billing metadata (Ollama, llamacpp, OpenAI when using the Responses API). Returning
`None` rather than raising on unknown models lets callers display "cost unknown" without
crashing the request pipeline.
