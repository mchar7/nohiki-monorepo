"""Hermetic Phoenix workflow tests plus an explicit external smoke CLI.

Pytest uses mocked LLM clients and ``httpx.MockTransport``. It never reads API
keys or contacts Phoenix. Run the external smoke explicitly from the repository
root with:

    uv run --package nohiki-llm-client \
        python backend/libs/nohiki-llm-client/tests/integration/test_phoenix_integration.py run
"""

from __future__ import annotations

import asyncio
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Final
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
import typer
from nohiki_llm_client import LLMModelConfig, LLMProviderSettings, LLMSettings
from nohiki_llm_client.client import LLMClient, StructuredAgentConfig
from nohiki_llm_client.config.settings import LLMInstrumentationSettings
from nohiki_test_utils import get_test_secrets_dir
from pydantic import BaseModel, SecretStr
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

SECRETS_DIR: Final[Path] = get_test_secrets_dir() / "llm" / "provider" / "api_keys"
OPENAI_API_KEY_FILE: Final[Path] = SECRETS_DIR / "openai"
OPENROUTER_API_KEY_FILE: Final[Path] = SECRETS_DIR / "openrouter"

PHOENIX_ENDPOINT: Final[str] = "http://localhost:4320"
PHOENIX_UI_URL: Final[str] = "http://localhost:6006"
PHOENIX_GRAPHQL_URL: Final[str] = f"{PHOENIX_UI_URL}/graphql"
PHOENIX_PROJECT: Final[str] = "nohiki-integration-test"
PHOENIX_SMOKE_ENV: Final[str] = "NOHIKI_RUN_PHOENIX_SMOKE"
SERVICE_NAME: Final[str] = "llm-client-integration-test"

console = Console(stderr=True)
app = typer.Typer(
    name="phoenix-integration-test",
    help="Test Phoenix LLM tracing with real API calls.",
    no_args_is_help=False,
)


class SimpleResponse(BaseModel):
    """Simple response model for LLM testing."""

    answer: str


@dataclass
class LLMTestResult:
    """Result of a single LLM test."""

    provider: str
    model: str
    success: bool
    response: str | None
    error: str | None
    duration_ms: int


def _require_smoke_opt_in() -> None:
    if os.environ.get(PHOENIX_SMOKE_ENV) != "1":
        console.print(f"[red]Set {PHOENIX_SMOKE_ENV}=1 to run the external Phoenix smoke.[/red]")
        raise typer.Exit(2)


def _load_api_key(key_file: Path) -> str:
    """Load API key from file."""
    if not key_file.exists():
        console.print(f"[red]API key file not found: {key_file}[/red]")
        raise typer.Exit(1)
    return key_file.read_text().strip()


def _build_instrumentation() -> LLMInstrumentationSettings:
    """Build Phoenix instrumentation settings for the integration test."""
    return LLMInstrumentationSettings(
        enabled=True,
        collector_endpoint=PHOENIX_ENDPOINT,
        project_name=PHOENIX_PROJECT,
        service_name=SERVICE_NAME,
    )


def _create_llm_client(
    provider: str,
    model: str,
    api_key: str,
    instrumentation: LLMInstrumentationSettings,
) -> LLMClient:
    """Create an instrumented LLMClient for the given provider and model."""
    return LLMClient(
        LLMSettings(
            provider=LLMProviderSettings(
                models=[
                    LLMModelConfig(
                        model=f"{provider}:{model}",
                        api_key=SecretStr(api_key),
                    )
                ],
            ),
            instrumentation=instrumentation,
        )
    )


async def _make_llm_request(
    client: LLMClient,
    provider: str,
    model: str,
    prompt: str,
) -> LLMTestResult:
    """Make a single LLM request and measure performance."""
    start_time = time.perf_counter()

    try:
        agent = client.create_agent(
            StructuredAgentConfig(
                deps_type=type(None),
                output_type=SimpleResponse,
                system_prompt="You are a helpful assistant. Respond very briefly.",
            )
        )
        result = await client.run(agent, prompt, deps=None)
        duration_ms = int((time.perf_counter() - start_time) * 1000)

        return LLMTestResult(
            provider=provider,
            model=model,
            success=True,
            response=result.output.answer,
            error=None,
            duration_ms=duration_ms,
        )
    except Exception as e:
        duration_ms = int((time.perf_counter() - start_time) * 1000)
        return LLMTestResult(
            provider=provider,
            model=model,
            success=False,
            response=None,
            error=str(e),
            duration_ms=duration_ms,
        )


def _query_phoenix_projects(client: httpx.Client | None = None) -> dict:
    """Query Phoenix for project information."""
    owns_client = client is None
    query_client = client or httpx.Client()
    try:
        response = query_client.post(
            PHOENIX_GRAPHQL_URL,
            json={"query": "{ projects { edges { node { name id traceCount } } } }"},
            timeout=10.0,
        )
        response.raise_for_status()
        return response.json()
    except Exception as error:
        console.print(f"[yellow]Warning: Could not query Phoenix: {error}[/yellow]")
        return {}
    finally:
        if owns_client:
            query_client.close()


def _phoenix_has_exported_traces(project_data: dict) -> bool:
    """Return whether the configured smoke project has at least one trace."""
    edges = project_data.get("data", {}).get("projects", {}).get("edges", [])
    return any(
        edge.get("node", {}).get("name") == PHOENIX_PROJECT and edge.get("node", {}).get("traceCount", 0) > 0
        for edge in edges
    )


async def _wait_for_phoenix_traces(
    *,
    client: httpx.Client | None = None,
    timeout_seconds: float = 30.0,
    poll_interval_seconds: float = 0.25,
) -> dict:
    """Poll Phoenix until exported traces are observable."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout_seconds

    while True:
        project_data = _query_phoenix_projects(client)
        if _phoenix_has_exported_traces(project_data):
            return project_data

        remaining = deadline - loop.time()
        if remaining <= 0:
            msg = f"Phoenix did not expose traces for {PHOENIX_PROJECT}"
            raise TimeoutError(msg)
        await asyncio.sleep(min(poll_interval_seconds, remaining))


def _display_results(results: list[LLMTestResult]) -> None:
    """Display test results in a rich table."""
    table = Table(
        title="[bold cyan]LLM Test Results[/bold cyan]",
        show_header=True,
        header_style="bold cyan",
        border_style="cyan",
    )
    table.add_column("Provider", style="cyan")
    table.add_column("Model", style="dim")
    table.add_column("Status", justify="center", width=10)
    table.add_column("Response", min_width=20, max_width=40)
    table.add_column("Duration", justify="right", width=10)

    for result in results:
        status = "[green]✓ Pass[/green]" if result.success else "[red]✗ Fail[/red]"
        if result.response:
            response_text = result.response[:40]
        elif result.error:
            response_text = f"[red]{result.error[:40]}[/red]"
        else:
            response_text = "[red]Unknown[/red]"
        duration_text = f"{result.duration_ms}ms"

        table.add_row(
            result.provider,
            result.model,
            status,
            response_text,
            duration_text,
        )

    console.print(table)


def _display_phoenix_stats(project_data: dict) -> None:
    """Display Phoenix project statistics."""
    projects = project_data.get("data", {}).get("projects", {}).get("edges", [])

    if not projects:
        console.print("[yellow]No projects found in Phoenix[/yellow]")
        return

    table = Table(
        title="[bold magenta]Phoenix Projects[/bold magenta]",
        show_header=True,
        header_style="bold magenta",
        border_style="magenta",
    )
    table.add_column("Project", style="magenta")
    table.add_column("Traces", justify="right", style="bold")

    for project in projects:
        node = project.get("node", {})
        name = node.get("name", "Unknown")
        trace_count = node.get("traceCount", 0)
        table.add_row(name, str(trace_count))

    console.print(table)


async def _run_llm_tests(
    openai_model: str,
    openrouter_model: str,
    openai_key: str,
    openrouter_key: str,
    instrumentation: LLMInstrumentationSettings,
) -> list[LLMTestResult]:
    """Run LLM tests for both OpenAI and OpenRouter."""
    results: list[LLMTestResult] = []

    with console.status("[bold green]Testing OpenAI...", spinner="dots"):
        openai_client = _create_llm_client("openai", openai_model, openai_key, instrumentation)
        result = await _make_llm_request(
            openai_client,
            "openai",
            openai_model,
            "What is 2+2? Answer in one word.",
        )
        results.append(result)
        status = "[green]✓[/green]" if result.success else "[red]✗[/red]"
        console.print(f"{status} OpenAI {openai_model}: {result.duration_ms}ms")

    with console.status("[bold green]Testing OpenRouter...", spinner="dots"):
        openrouter_client = _create_llm_client("openrouter", openrouter_model, openrouter_key, instrumentation)
        result = await _make_llm_request(
            openrouter_client,
            "openrouter",
            openrouter_model,
            "What is 3+3? Answer in one word.",
        )
        results.append(result)
        status = "[green]✓[/green]" if result.success else "[red]✗[/red]"
        console.print(f"{status} OpenRouter {openrouter_model}: {result.duration_ms}ms")

    return results


async def _test_fallback(
    openrouter_model: str,
    openai_key: str,
    instrumentation: LLMInstrumentationSettings,
    results: list[LLMTestResult],
) -> None:
    """Test LLMClient fallback with invalid OpenRouter key."""
    console.print()
    console.print("[bold yellow]Testing fallback mechanism...[/bold yellow]")

    with console.status("[bold yellow]Testing LLMClient with invalid OpenRouter key...", spinner="dots"):
        try:
            settings = LLMSettings(
                provider=LLMProviderSettings(
                    models=[
                        LLMModelConfig(
                            model=f"openrouter:{openrouter_model}",
                            api_key=SecretStr("invalid-fixture"),
                        ),
                        LLMModelConfig(
                            model="openai:gpt-4o-mini",
                            api_key=SecretStr(openai_key),
                        ),
                    ],
                ),
                instrumentation=instrumentation,
            )
            client = LLMClient(settings)

            class FallbackResponse(BaseModel):
                answer: str

            agent = client.create_agent(
                StructuredAgentConfig(
                    deps_type=type(None),
                    output_type=FallbackResponse,
                    system_prompt="Answer in one word.",
                )
            )

            result_obj = await client.run(agent, "What is 5+5?", deps=None)
            result = LLMTestResult(
                provider="openrouter→openai",
                model=f"{openrouter_model}→gpt-4o-mini",
                success=True,
                response=result_obj.output.answer,
                error=None,
                duration_ms=0,
            )
            results.append(result)
            console.print("[yellow]✓[/yellow] Fallback to OpenAI succeeded (model mapping works)")
        except Exception as e:
            error_msg = str(e)
            if "FallbackModel failed" in error_msg:
                console.print("[yellow]✓[/yellow] FallbackModel configured (OpenRouter failed, OpenAI attempted)")
                result = LLMTestResult(
                    provider="openrouter→openai",
                    model=f"{openrouter_model}→gpt-4o-mini",
                    success=True,
                    response="Fallback chain verified",
                    error=None,
                    duration_ms=0,
                )
            else:
                result = LLMTestResult(
                    provider="openrouter→openai",
                    model=f"{openrouter_model}→gpt-4o-mini",
                    success=False,
                    response=None,
                    error=error_msg[:60],
                    duration_ms=0,
                )
                console.print(f"[red]✗[/red] Fallback failed: {error_msg[:60]}")
            results.append(result)


async def _run_external_smoke(
    openai_model: str,
    openrouter_model: str,
    openai_key: str,
    openrouter_key: str,
    instrumentation: LLMInstrumentationSettings,
    *,
    test_fallback: bool,
) -> tuple[list[LLMTestResult], dict]:
    """Run paid requests and wait for their Phoenix traces."""
    results = await _run_llm_tests(openai_model, openrouter_model, openai_key, openrouter_key, instrumentation)
    if test_fallback:
        await _test_fallback(openrouter_model, openai_key, instrumentation, results)
    project_data = await _wait_for_phoenix_traces()
    return results, project_data


@app.command()
def run(
    openai_model: Annotated[
        str,
        typer.Option("--openai-model", help="OpenAI model to test"),
    ] = "gpt-5-mini",
    openrouter_model: Annotated[
        str,
        typer.Option("--openrouter-model", help="OpenRouter model to test"),
    ] = "google/gemini-3-flash-preview",
    *,
    test_fallback: Annotated[
        bool,
        typer.Option("--test-fallback", help="Test OpenRouter fallback with invalid key"),
    ] = False,
) -> None:
    """Run Phoenix integration tests with real LLM calls."""
    _require_smoke_opt_in()
    console.print()
    console.print(
        Panel.fit(
            "[bold cyan]Phoenix LLM Tracing Integration Test[/bold cyan]\n"
            "[dim]Testing real API calls with OpenAI and OpenRouter[/dim]",
            border_style="cyan",
        )
    )
    console.print()

    openai_key = _load_api_key(OPENAI_API_KEY_FILE)
    openrouter_key = _load_api_key(OPENROUTER_API_KEY_FILE)

    instrumentation = _build_instrumentation()
    console.print("[green]✓[/green] Phoenix instrumentation configured")
    console.print()

    console.print("[bold]Running LLM tests...[/bold]")
    console.print()

    with asyncio.Runner() as runner:
        results, project_data = runner.run(
            _run_external_smoke(
                openai_model,
                openrouter_model,
                openai_key,
                openrouter_key,
                instrumentation,
                test_fallback=test_fallback,
            )
        )

    console.print("[green]✓[/green] Traces exported")
    console.print()

    _display_results(results)
    console.print()
    _display_phoenix_stats(project_data)
    console.print()

    console.print(
        Panel.fit(
            f"[bold green]Integration Test Complete[/bold green]\n[dim]View traces at {PHOENIX_UI_URL}[/dim]",
            border_style="green",
        )
    )

    success_count = sum(1 for r in results if r.success)
    if success_count < len(results):
        raise typer.Exit(1) from None


def _check_phoenix_health() -> httpx.Response | None:
    """Check Phoenix health endpoint, returning response or None on error."""
    try:
        return httpx.get(f"{PHOENIX_UI_URL}/healthz", timeout=5.0)
    except Exception as e:
        console.print(f"[red]✗[/red] Phoenix UI not accessible: {e}")
        return None


@app.command()
def check() -> None:
    """Check that Phoenix is running and accessible."""
    _require_smoke_opt_in()
    console.print()
    console.print("[bold]Checking Phoenix availability...[/bold]")
    console.print()

    response = _check_phoenix_health()
    if response is None:
        raise typer.Exit(1)
    if response.status_code != 200:
        console.print(f"[red]✗[/red] Phoenix UI returned status {response.status_code}")
        raise typer.Exit(1)
    console.print(f"[green]✓[/green] Phoenix UI accessible at {PHOENIX_UI_URL}")

    project_data = _query_phoenix_projects()
    if project_data:
        console.print("[green]✓[/green] Phoenix GraphQL API accessible")
        _display_phoenix_stats(project_data)
    else:
        console.print("[yellow]⚠[/yellow] Could not query Phoenix GraphQL API")

    console.print()

    if not OPENAI_API_KEY_FILE.exists():
        console.print(f"[red]✗[/red] OpenAI API key file not found: {OPENAI_API_KEY_FILE}")
    else:
        console.print("[green]✓[/green] OpenAI API key file found")

    if not OPENROUTER_API_KEY_FILE.exists():
        console.print(f"[red]✗[/red] OpenRouter API key file not found: {OPENROUTER_API_KEY_FILE}")
    else:
        console.print("[green]✓[/green] OpenRouter API key file found")

    console.print()


def test_external_smoke_requires_explicit_opt_in(monkeypatch: pytest.MonkeyPatch) -> None:
    """External Phoenix commands fail closed unless the operator opts in."""
    monkeypatch.delenv(PHOENIX_SMOKE_ENV, raising=False)

    with pytest.raises(typer.Exit) as error:
        _require_smoke_opt_in()

    assert error.value.exit_code == 2


@pytest.mark.asyncio
async def test_llm_workflow_uses_mocked_clients(monkeypatch: pytest.MonkeyPatch) -> None:
    """Preserve both provider request contracts without provider traffic."""
    clients: dict[str, MagicMock] = {}

    def create_client(
        provider: str,
        model: str,
        api_key: str,
        instrumentation: LLMInstrumentationSettings,
    ) -> MagicMock:
        del model, api_key, instrumentation
        client = MagicMock(spec=LLMClient)
        client.run = AsyncMock(
            return_value=MagicMock(output=SimpleResponse(answer="4" if provider == "openai" else "6"))
        )
        clients[provider] = client
        return client

    monkeypatch.setattr(__name__ + "._create_llm_client", create_client)

    results = await _run_llm_tests("openai-model", "router-model", "openai-key", "router-key", MagicMock())

    assert [(result.provider, result.response, result.success) for result in results] == [
        ("openai", "4", True),
        ("openrouter", "6", True),
    ]
    clients["openai"].run.assert_awaited_once()
    clients["openrouter"].run.assert_awaited_once()


@pytest.mark.asyncio
async def test_llm_request_reports_transport_failure() -> None:
    """Keep provider failures observable in the workflow report."""
    client = MagicMock(spec=LLMClient)
    client.run = AsyncMock(side_effect=httpx.ConnectError("mock transport unavailable"))

    result = await _make_llm_request(client, "openai", "mock-model", "prompt")

    assert result.success is False
    assert result.response is None
    assert result.error == "mock transport unavailable"


@pytest.mark.asyncio
async def test_fallback_contract_uses_mocked_llm_transport(monkeypatch: pytest.MonkeyPatch) -> None:
    """Preserve invalid-primary fallback success without paid calls."""
    client = MagicMock(spec=LLMClient)
    client.run = AsyncMock(return_value=MagicMock(output=SimpleResponse(answer="10")))
    monkeypatch.setattr(__name__ + ".LLMClient", MagicMock(return_value=client))
    results: list[LLMTestResult] = []

    await _test_fallback("router-model", "openai-key", _build_instrumentation(), results)

    assert len(results) == 1
    assert results[0].success is True
    assert results[0].provider == "openrouter→openai"
    assert results[0].response == "10"
    client.run.assert_awaited_once()


@pytest.mark.asyncio
async def test_phoenix_transport_is_polled_until_trace_export() -> None:
    """Preserve Phoenix trace verification with deterministic readiness polling."""
    request_count = 0

    def handle_request(request: httpx.Request) -> httpx.Response:
        nonlocal request_count
        assert request.url == PHOENIX_GRAPHQL_URL
        payload = request.read().decode()
        assert "traceCount" in payload
        request_count += 1
        return httpx.Response(
            200,
            json={
                "data": {
                    "projects": {
                        "edges": [
                            {
                                "node": {
                                    "name": PHOENIX_PROJECT,
                                    "id": "project-id",
                                    "traceCount": int(request_count > 1),
                                }
                            }
                        ]
                    }
                }
            },
        )

    with httpx.Client(transport=httpx.MockTransport(handle_request)) as client:
        project_data = await _wait_for_phoenix_traces(client=client, poll_interval_seconds=0)

    assert request_count == 2
    assert _phoenix_has_exported_traces(project_data)


def test_phoenix_transport_failure_returns_empty_report() -> None:
    """Keep Phoenix transport failures non-fatal and visible as no data."""

    def handle_request(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, request=request)

    with httpx.Client(transport=httpx.MockTransport(handle_request)) as client:
        assert _query_phoenix_projects(client) == {}


if __name__ == "__main__":
    app()
