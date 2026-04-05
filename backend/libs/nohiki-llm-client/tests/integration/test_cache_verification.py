"""Real API test to verify LLM provider caching via OpenRouter.

Uses OpenRouter's /generation API to verify actual cache usage by checking
the `native_tokens_cached` field in generation details.

Results (as of 2026-01-16):
- anthropic/claude-haiku-4.5: ✅ Caching works via Amazon Bedrock
- openai/gpt-5-mini: ✅ Caching works via OpenAI
- google/gemini-2.5-flash: ❌ No caching reported via OpenRouter

Note: Gemini models via OpenRouter do not appear to support/report caching,
even with large contexts (7000+ tokens) and cache_control breakpoints.

Usage:
    cd <repo-root>
    uv run python backend/libs/nohiki-llm-client/tests/integration/test_cache_verification.py
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final

import httpx
from nohiki_test_utils import get_test_secrets_dir
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

OPENROUTER_KEY_PATH: Final[Path] = get_test_secrets_dir() / "llm" / "provider" / "api_keys" / "openrouter"

OPENROUTER_BASE_URL: Final[str] = "https://openrouter.ai/api/v1"

console = Console(stderr=True)


def _generate_large_context(min_tokens: int = 2000) -> str:
    """Generate a large context block to exceed caching thresholds."""
    base_content = """
## Technical Documentation Reference

### Chapter 1: Software Architecture Patterns

#### 1.1 Microservices Architecture
Microservices architecture is a design approach where a single application is developed as a suite
of small, independently deployable services. Each service runs in its own process and communicates
through lightweight mechanisms, typically HTTP-based APIs. Key characteristics include:

- **Service Independence**: Each microservice can be developed, deployed, and scaled independently
- **Technology Diversity**: Different services can use different programming languages and databases
- **Resilience**: Failure in one service doesn't necessarily cascade to others
- **Scalability**: Individual services can be scaled based on demand

#### 1.2 Event-Driven Architecture
Event-driven architecture (EDA) is a software design pattern promoting the production, detection,
consumption of, and reaction to events. Components include:

- **Event Producers**: Components that detect and publish events
- **Event Consumers**: Components that subscribe to and process events
- **Event Channels**: Infrastructure for event transmission (message brokers like Kafka, RabbitMQ)
- **Event Processing**: Logic for handling events (simple processing, complex event processing)

#### 1.3 Domain-Driven Design (DDD)
Domain-Driven Design is an approach to software development that centers the development on
programming a domain model that has a rich understanding of the processes and rules of a domain:

- **Bounded Contexts**: Explicit boundaries within which a domain model exists
- **Aggregates**: Clusters of domain objects treated as a single unit
- **Entities**: Objects defined by their identity rather than attributes
- **Value Objects**: Objects defined by their attributes rather than identity
- **Domain Events**: Events that domain experts care about
- **Repositories**: Mechanisms for encapsulating storage and retrieval logic

### Chapter 2: Database Design Principles

#### 2.1 Relational Database Design
Proper relational database design follows normalization principles:

- **First Normal Form (1NF)**: Eliminate repeating groups, create separate tables
- **Second Normal Form (2NF)**: Remove partial dependencies on composite keys
- **Third Normal Form (3NF)**: Remove transitive dependencies
- **Boyce-Codd Normal Form (BCNF)**: Every determinant is a candidate key

#### 2.2 NoSQL Database Patterns
NoSQL databases offer different data models for different use cases:

- **Document Stores**: MongoDB, CouchDB - flexible schema, JSON-like documents
- **Key-Value Stores**: Redis, DynamoDB - simple, fast lookups
- **Column Family**: Cassandra, HBase - wide columns, time-series data
- **Graph Databases**: Neo4j, Neptune - relationship-heavy data

### Chapter 3: API Design Best Practices

#### 3.1 RESTful API Design
REST APIs should follow these principles:

- **Resource-Based URLs**: /users, /orders, /products
- **HTTP Methods**: GET (read), POST (create), PUT (update), DELETE (remove)
- **Status Codes**: 200 (OK), 201 (Created), 400 (Bad Request), 404 (Not Found)

#### 3.2 gRPC and Protocol Buffers
gRPC provides high-performance RPC framework:

- **Protocol Buffers**: Binary serialization format
- **Service Definitions**: .proto files define services
- **Streaming**: Unary, server streaming, client streaming, bidirectional
"""
    repeated = base_content
    while len(repeated.split()) < min_tokens:
        repeated += base_content
    return repeated


LARGE_CACHED_CONTEXT: Final[str] = _generate_large_context(4500)


@dataclass
class GenerationResult:
    """Result from a single generation request."""

    generation_id: str
    native_tokens_prompt: int
    native_tokens_cached: int
    native_tokens_completion: int
    provider_name: str
    success: bool
    error: str | None = None


@dataclass
class ModelCacheReport:
    """Aggregate cache report for a model."""

    model: str
    results: list[GenerationResult] = field(default_factory=list)
    cache_working: bool = False

    @property
    def total_cached_tokens(self) -> int:
        return sum(r.native_tokens_cached for r in self.results if r.success)


def _build_messages_with_cache_control(context: str, question: str) -> list[dict[str, Any]]:
    """Build messages with cache_control breakpoints for Anthropic/Gemini."""
    return [
        {
            "role": "system",
            "content": [
                {"type": "text", "text": "You are a helpful technical assistant."},
                {"type": "text", "text": context, "cache_control": {"type": "ephemeral"}},
            ],
        },
        {"role": "user", "content": question},
    ]


def _build_messages_simple(context: str, question: str) -> list[dict[str, Any]]:
    """Build simple messages for OpenAI (automatic caching)."""
    return [
        {"role": "system", "content": f"You are a helpful technical assistant.\n\n{context}"},
        {"role": "user", "content": question},
    ]


async def _make_completion_request(
    client: httpx.AsyncClient,
    api_key: str,
    model: str,
    messages: list[dict[str, Any]],
) -> dict[str, Any]:
    """Make a chat completion request to OpenRouter."""
    response = await client.post(
        f"{OPENROUTER_BASE_URL}/chat/completions",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://nohiki.dev",
            "X-Title": "Nohiki Cache Test",
        },
        json={
            "model": model,
            "messages": messages,
            "max_tokens": 100,
            "temperature": 0,
        },
        timeout=60.0,
    )
    response.raise_for_status()
    return response.json()


async def _get_generation_details(
    client: httpx.AsyncClient,
    api_key: str,
    generation_id: str,
) -> dict[str, Any]:
    """Get generation details from OpenRouter's generation API."""
    response = await client.get(
        f"{OPENROUTER_BASE_URL}/generation?id={generation_id}",
        headers={"Authorization": f"Bearer {api_key}"},
        timeout=30.0,
    )
    response.raise_for_status()
    return response.json()


async def _test_model_caching(
    client: httpx.AsyncClient,
    api_key: str,
    model: str,
    *,
    use_cache_control: bool,
) -> ModelCacheReport:
    """Test caching for a specific model by checking generation API."""
    report = ModelCacheReport(model=model)

    questions = [
        "What is microservices architecture? One sentence.",
        "What is event-driven architecture? One sentence.",
        "What are the key database indexing strategies? List briefly.",
    ]

    for question in questions:
        if use_cache_control:
            messages = _build_messages_with_cache_control(LARGE_CACHED_CONTEXT, question)
        else:
            messages = _build_messages_simple(LARGE_CACHED_CONTEXT, question)

        try:
            completion = await _make_completion_request(client, api_key, model, messages)
            generation_id = completion.get("id", "")

            await asyncio.sleep(1.0)

            gen_details = await _get_generation_details(client, api_key, generation_id)
            data = gen_details.get("data", gen_details)

            result = GenerationResult(
                generation_id=generation_id,
                native_tokens_prompt=data.get("native_tokens_prompt", 0),
                native_tokens_cached=data.get("native_tokens_cached", 0) or 0,
                native_tokens_completion=data.get("native_tokens_completion", 0),
                provider_name=data.get("provider_name", "unknown"),
                success=True,
            )
            report.results.append(result)

            if result.native_tokens_cached > 0:
                report.cache_working = True

        except Exception as e:
            report.results.append(
                GenerationResult(
                    generation_id="",
                    native_tokens_prompt=0,
                    native_tokens_cached=0,
                    native_tokens_completion=0,
                    provider_name="error",
                    success=False,
                    error=str(e)[:100],
                )
            )

        await asyncio.sleep(0.5)

    return report


def _print_model_report(report: ModelCacheReport) -> None:
    """Print a formatted report for a model's cache test."""
    status = "[green]✓ CACHED[/green]" if report.cache_working else "[red]✗ NO CACHE[/red]"

    table = Table(title=f"{report.model} - {status}")
    table.add_column("Req#", style="cyan", justify="center")
    table.add_column("Generation ID", justify="left")
    table.add_column("Provider", justify="left")
    table.add_column("Prompt", justify="right")
    table.add_column("Cached", justify="right", style="green")
    table.add_column("Completion", justify="right")
    table.add_column("Status", justify="center")

    for i, r in enumerate(report.results, 1):
        if r.success:
            cached_style = "[green]" if r.native_tokens_cached > 0 else "[red]"
            table.add_row(
                str(i),
                r.generation_id[:20] + "..." if len(r.generation_id) > 20 else r.generation_id,
                r.provider_name[:15],
                str(r.native_tokens_prompt),
                f"{cached_style}{r.native_tokens_cached}[/]",
                str(r.native_tokens_completion),
                "[green]OK[/green]",
            )
        else:
            error_msg = r.error[:20] if r.error else "Unknown error"
            table.add_row(str(i), "-", "-", "0", "0", "0", f"[red]{error_msg}...[/red]")

    console.print(table)
    console.print()


async def run_cache_verification() -> None:
    """Run cache verification for all target models via OpenRouter generation API."""
    api_key = OPENROUTER_KEY_PATH.read_text().strip()

    models_config = [
        ("google/gemini-3-flash-preview", False),
        ("anthropic/claude-haiku-4.5", True),
        ("openai/gpt-5-mini", False),
    ]

    console.print(
        Panel.fit(
            "[bold cyan]OpenRouter Cache Verification Test[/bold cyan]\n\n"
            f"Context size: ~{len(LARGE_CACHED_CONTEXT.split())} words\n"
            "Verifying via OpenRouter /generation API (native_tokens_cached)\n"
            "Using cache_control breakpoints for Anthropic/Gemini",
            title="Cache Verification",
        )
    )
    console.print()

    reports: list[ModelCacheReport] = []

    async with httpx.AsyncClient() as client:
        for model, use_cache_control in models_config:
            console.print(f"[bold]Testing {model}...[/bold]")
            report = await _test_model_caching(client, api_key, model, use_cache_control=use_cache_control)
            reports.append(report)
            _print_model_report(report)

    console.print("=" * 70)
    console.print("[bold]FINAL SUMMARY - OpenRouter native_tokens_cached[/bold]")
    console.print("=" * 70)

    all_working = all(r.cache_working for r in reports)

    for report in reports:
        status = "[green]✓[/green]" if report.cache_working else "[red]✗[/red]"
        console.print(f"  {status} {report.model}: native_tokens_cached={report.total_cached_tokens}")

    console.print()
    if all_working:
        console.print("[bold green]✓ ALL MODELS SHOW CACHING![/bold green]")
    else:
        failed = [r.model for r in reports if not r.cache_working]
        console.print(f"[bold red]✗ No caching detected for: {', '.join(failed)}[/bold red]")


if __name__ == "__main__":
    asyncio.run(run_cache_verification())
