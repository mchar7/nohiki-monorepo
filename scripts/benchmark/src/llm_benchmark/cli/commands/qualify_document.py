"""CLI command for deterministic document-model qualification."""

import asyncio
import json
from math import isfinite
from pathlib import Path
from typing import Annotated, Protocol

import click
import typer
from nohiki_llm_client import LLMInstrumentationSettings, LLMSettings
from typer._types import TyperChoice

from llm_benchmark.cli._helpers import load_api_keys, load_credential_free_chain
from llm_benchmark.display.console import console
from llm_benchmark.document_fixtures import (
    DOCUMENT_FIXTURES,
    DocumentQualificationFixture,
    get_document_fixture,
)
from llm_benchmark.schemas.document_qualification import (
    APPROVED_ROUTE_ALIASES,
    DocumentQualificationResult,
    GateName,
)

_DEFAULT_GOTENBERG_URL = "http://localhost:3000"


class _QualificationRunner(Protocol):
    """Narrow engine surface used by the CLI orchestration seam."""

    async def run(
        self,
        *,
        selected_routes: tuple[str, ...],
        selected_fixtures: tuple[str, ...],
        runs: int,
        output_path: Path,
        existing: DocumentQualificationResult | None,
        preflight: bool,
    ) -> DocumentQualificationResult:
        """Run selected qualification cells."""
        ...


def _build_runner(
    *,
    llm_settings: LLMSettings,
    chain: str,
    fixtures: tuple[DocumentQualificationFixture, ...],
    cost_cap: float,
    unknown_price_max: float | None,
    gotenberg_url: str,
) -> _QualificationRunner:
    """Import and construct the heavy document engine only for execution."""
    from llm_benchmark.engine.document_qualification import (
        DocumentQualificationRunner,
    )

    return DocumentQualificationRunner(
        llm_settings=llm_settings,
        chain_name=chain,
        fixtures=fixtures,
        cost_cap_usd=cost_cap,
        unknown_price_max_usd=unknown_price_max,
        gotenberg_url=gotenberg_url,
    )


def _instrumentation_enabled(path: Path) -> bool:
    """Read only the tracing switch needed to enforce safe evidence."""
    raw: object = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        return False
    instrumentation = raw.get("instrumentation")
    return LLMInstrumentationSettings.model_validate(instrumentation or {}).enabled


def _select_fixtures(
    fixture_ids: list[str] | None,
) -> tuple[DocumentQualificationFixture, ...]:
    """Resolve the requested fixture IDs in stable order."""
    selected_ids = fixture_ids or [fixture.fixture_id for fixture in DOCUMENT_FIXTURES]
    if len(selected_ids) != len(set(selected_ids)):
        msg = "Fixture IDs must be unique"
        raise typer.BadParameter(msg, param_hint="--fixture")
    try:
        return tuple(get_document_fixture(fixture_id) for fixture_id in selected_ids)
    except KeyError as exc:
        msg = "Unknown document fixture"
        raise typer.BadParameter(msg, param_hint="--fixture") from exc


def _select_routes(route_aliases: list[str] | None) -> tuple[str, ...]:
    """Return unique selected route aliases in stable order."""
    selected = tuple(route_aliases or APPROVED_ROUTE_ALIASES)
    if len(selected) != len(set(selected)):
        msg = "Route aliases must be unique"
        raise typer.BadParameter(msg, param_hint="--route")
    return selected


def _load_existing(output: Path, *, fresh: bool) -> DocumentQualificationResult | None:
    """Load resumable evidence unless a fresh run was requested."""
    if fresh:
        output.unlink(missing_ok=True)
        return None
    if not output.exists():
        return None
    return DocumentQualificationResult.load(output)


async def _run_qualification(
    runner: _QualificationRunner,
    *,
    selected_routes: tuple[str, ...],
    selected_fixtures: tuple[str, ...],
    runs: int,
    output_path: Path,
    existing: DocumentQualificationResult | None,
    preflight: bool,
) -> DocumentQualificationResult:
    """Invoke the engine through a narrow orchestration seam."""
    return await runner.run(
        selected_routes=selected_routes,
        selected_fixtures=selected_fixtures,
        runs=runs,
        output_path=output_path,
        existing=existing,
        preflight=preflight,
    )


def _display_safe_summary(
    result: DocumentQualificationResult,
    selected_routes: tuple[str, ...],
) -> None:
    """Print only bounded, non-sensitive qualification evidence."""
    console.print(f"status={result.status}")
    console.print(f"experiment_sha256={result.experiment_fingerprint}")
    console.print(f"fixtures={','.join(sorted(result.fixture_checksums))}")
    routes_by_alias = {route.identity.route_alias: route for route in result.routes.values()}
    for alias in selected_routes:
        route = routes_by_alias.get(alias)
        if route is None:
            console.print(f"route={alias} status=incomplete")
            continue
        duration_ms = sum(case.telemetry.cell_latency_ms for case in route.cases)
        actual_cost = sum(case.telemetry.actual_cost_usd or 0.0 for case in route.cases)
        charged_cost = sum(case.telemetry.charged_cost_usd for case in route.cases)
        console.print(
            f"route={alias} status={route.status} cells={len(route.cases)} "
            f"duration_ms={duration_ms:.3f} actual_cost_usd={actual_cost:.6f} "
            f"charged_cost_usd={charged_cost:.6f}"
        )
        for gate in GateName:
            totals = route.gate_totals[gate]
            console.print(f"route={alias} gate={gate.value} passed={totals['passed']} failed={totals['failed']}")


def _requested_cells_qualified(
    result: DocumentQualificationResult,
    selected_routes: tuple[str, ...],
    selected_fixtures: tuple[str, ...],
    runs: int,
) -> bool:
    routes_by_alias = {route.identity.route_alias: route for route in result.routes.values()}
    expected = {(fixture_id, run_number) for fixture_id in selected_fixtures for run_number in range(1, runs + 1)}
    for alias in selected_routes:
        route = routes_by_alias.get(alias)
        if route is None:
            return False
        cases = {
            (case.fixture_id, case.run_number): case
            for case in route.cases
            if case.fixture_id in selected_fixtures and case.run_number <= runs
        }
        if set(cases) != expected or any(not case.passed for case in cases.values()):
            return False
    return True


def _validate_options(
    *,
    chain: str,
    cost_cap: float,
    unknown_price_max: float | None,
    gotenberg_url: str,
    llm_settings_path: Path,
) -> None:
    """Validate qualification options that Typer cannot express."""
    if not chain.strip():
        msg = "Chain name must not be empty"
        raise typer.BadParameter(msg, param_hint="--chain")
    if not isfinite(cost_cap):
        msg = "Cost cap must be finite"
        raise typer.BadParameter(msg, param_hint="--cost-cap")
    if unknown_price_max is not None and not isfinite(unknown_price_max):
        msg = "Unknown-price maximum must be finite"
        raise typer.BadParameter(msg, param_hint="--unknown-price-max")
    if not gotenberg_url.strip():
        msg = "Gotenberg URL must not be empty"
        raise typer.BadParameter(msg, param_hint="--gotenberg-url")
    if _instrumentation_enabled(llm_settings_path):
        msg = "Instrumentation must be disabled for safe qualification evidence"
        raise typer.BadParameter(msg, param_hint="--llm-settings")


def qualify_document(
    output: Annotated[
        Path,
        typer.Option("--output", "-o", help="Crash-safe qualification evidence JSON"),
    ],
    llm_settings_path: Annotated[
        Path,
        typer.Option(
            "--llm-settings",
            exists=True,
            dir_okay=False,
            readable=True,
            help="Credential-free standard LLMSettings JSON",
        ),
    ],
    chain: Annotated[
        str,
        typer.Option("--chain", help="Named exact three-route document chain"),
    ],
    cost_cap: Annotated[
        float,
        typer.Option("--cost-cap", min=0.000000001, help="Owner-approved total USD cap"),
    ],
    routes: Annotated[
        list[str] | None,
        typer.Option(
            "--route",
            help="Route alias to dispatch; repeat for a subset",
            click_type=TyperChoice(APPROVED_ROUTE_ALIASES),
        ),
    ] = None,
    fixtures: Annotated[
        list[str] | None,
        typer.Option("--fixture", help="Document fixture ID; repeat to select"),
    ] = None,
    unknown_price_max: Annotated[
        float | None,
        typer.Option(
            "--unknown-price-max",
            min=0.000000001,
            help="Owner-approved maximum USD charge for an unknown-price call",
        ),
    ] = None,
    runs: Annotated[
        int,
        typer.Option("--runs", min=1, help="Runs per fixture and route"),
    ] = 1,
    gotenberg_url: Annotated[
        str,
        typer.Option("--gotenberg-url", help="Gotenberg base URL used for PDF gates"),
    ] = _DEFAULT_GOTENBERG_URL,
    preflight: Annotated[
        bool,
        typer.Option("--preflight", help="Validate contracts and reservation without dispatch"),
    ] = False,
    fresh: Annotated[
        bool,
        typer.Option("--fresh", help="Delete incompatible prior evidence before starting"),
    ] = False,
) -> None:
    """Qualify the exact production document-model chain deterministically."""
    selected_routes = _select_routes(routes)
    selected_fixtures = _select_fixtures(fixtures)
    selected_fixture_ids = tuple(fixture.fixture_id for fixture in selected_fixtures)

    try:
        _validate_options(
            chain=chain,
            cost_cap=cost_cap,
            unknown_price_max=unknown_price_max,
            gotenberg_url=gotenberg_url,
            llm_settings_path=llm_settings_path,
        )
        api_keys = load_api_keys()
        _, resolved_chain = load_credential_free_chain(llm_settings_path, chain, api_keys)
        settings = LLMSettings(
            provider=resolved_chain,
            chains={chain: resolved_chain},
            instrumentation=LLMInstrumentationSettings(enabled=False),
        )
        runner = _build_runner(
            llm_settings=settings,
            chain=chain,
            fixtures=DOCUMENT_FIXTURES,
            cost_cap=cost_cap,
            unknown_price_max=unknown_price_max,
            gotenberg_url=gotenberg_url,
        )
        existing = _load_existing(output, fresh=fresh)
        result = asyncio.run(
            _run_qualification(
                runner,
                selected_routes=selected_routes,
                selected_fixtures=selected_fixture_ids,
                runs=runs,
                output_path=output,
                existing=existing,
                preflight=preflight,
            )
        )
    except typer.Exit:
        raise
    except typer.BadParameter:
        raise
    except click.ClickException:
        raise
    except Exception as exc:
        console.print("status=failed")
        raise typer.Exit(code=1) from exc

    _display_safe_summary(result, selected_routes)
    if preflight:
        if result.status != "preflight":
            raise typer.Exit(code=1)
        return
    if not _requested_cells_qualified(result, selected_routes, selected_fixture_ids, runs):
        raise typer.Exit(code=1)
