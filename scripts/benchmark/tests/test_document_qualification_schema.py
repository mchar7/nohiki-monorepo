"""Contracts for safe, exact-cell document qualification evidence."""

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal
from unittest.mock import patch

import pytest
from pydantic import ValidationError

from llm_benchmark.schemas.document_qualification import (
    ArtifactEvidence,
    CaseTelemetry,
    DocumentCaseResult,
    DocumentQualificationResult,
    FailureCode,
    GateName,
    GateOutcome,
    PricingEvidence,
    RouteQualification,
    SafeError,
    SafeRouteIdentity,
)

_HASH_A = "a" * 64
_HASH_B = "b" * 64
_HASH_C = "c" * 64
_HASH_D = "d" * 64


def _gates(*, failed: GateName | None = None) -> dict[GateName, GateOutcome]:
    return {
        gate: GateOutcome(
            passed=gate is not failed,
            failure_codes=() if gate is not failed else (FailureCode.FIDELITY,),
        )
        for gate in GateName
    }


def _identity(alias: str = "sol") -> SafeRouteIdentity:
    reasoning = "high" if alias == "kimi" else "medium"
    return SafeRouteIdentity(
        route_alias=alias,
        treatment_id=f"treatment-{alias}",
        treatment_fingerprint=_HASH_A,
        configured_model=f"provider:model-{alias}",
        returned_model=f"provider:model-{alias}",
        reasoning_effort=reasoning,
        endpoint_class="public_openrouter" if alias == "kimi" else "proxy",
        endpoint_sha256=_HASH_B,
        provider_order=("SiliconFlow",) if alias == "kimi" else (),
        allow_fallbacks=False,
        zdr=alias == "kimi",
        downstream_provider="SiliconFlow" if alias == "kimi" else None,
        pricing=PricingEvidence(
            pricing_fingerprint=_HASH_C,
            source="provider",
            maximum_call_cost_usd=0.25,
        ),
    )


def _case(
    alias: str = "sol",
    fixture_id: str = "fixture-a",
    *,
    run_number: int = 1,
    checksum: str = _HASH_D,
    failed: GateName | None = None,
    updated_at: datetime | None = None,
    actual_cost: float | None = 0.03,
    reserved_cost: float = 0.10,
) -> DocumentCaseResult:
    effective_actual = None if failed is not None else actual_cost
    charged = reserved_cost if effective_actual is None else effective_actual
    return DocumentCaseResult(
        treatment_id=f"treatment-{alias}",
        fixture_id=fixture_id,
        fixture_checksum=checksum,
        run_number=run_number,
        cell_fingerprint=_HASH_C,
        gate_outcomes=_gates(failed=failed),
        telemetry=CaseTelemetry(
            latency_ms=100.0,
            cell_latency_ms=150.0,
            request_count=1,
            actual_cost_usd=effective_actual,
            reserved_cost_usd=reserved_cost,
            charged_cost_usd=charged,
        ),
        output_sha256=_HASH_A if failed is None else None,
        artifact=(
            ArtifactEvidence(
                size_bytes=100,
                sha256=_HASH_B,
                page_count=1,
                text_sha256=_HASH_C,
                required_literals_checked=2,
                required_literals_present=2,
            )
            if failed is None
            else None
        ),
        safe_error=(None if failed is None else SafeError(code=FailureCode.FIDELITY, exception_type="FidelityError")),
        updated_at=updated_at or datetime.now(UTC),
    )


def _route(
    alias: str = "sol",
    *,
    checksums: dict[str, str] | None = None,
    runs: int = 1,
    cases: list[DocumentCaseResult] | None = None,
) -> RouteQualification:
    expected = checksums or {"fixture-a": _HASH_D}
    return RouteQualification(
        identity=_identity(alias),
        expected_fixture_checksums=expected,
        runs_per_fixture=runs,
        cases=cases or [],
    )


def _result(
    *,
    expected_routes: tuple[str, ...] = ("sol",),
    checksums: dict[str, str] | None = None,
    runs: int = 1,
    routes: dict[str, RouteQualification] | None = None,
    preflight: bool = False,
    evidence_environment: Literal["production", "test"] = "production",
) -> DocumentQualificationResult:
    return DocumentQualificationResult(
        contract_version="document-contract-v1",
        experiment_fingerprint=_HASH_A,
        policy_fingerprint=_HASH_B,
        corpus_fingerprint=_HASH_C,
        route_fingerprint=_HASH_D,
        config_fingerprint="e" * 64,
        expected_routes=expected_routes,
        fixture_checksums=checksums or {"fixture-a": _HASH_D},
        runs_per_fixture=runs,
        evidence_environment=evidence_environment,
        routes=routes or {},
        preflight=preflight,
    )


def test_case_requires_every_deterministic_gate_exactly_once() -> None:
    data = _case().model_dump()
    data["gate_outcomes"].pop(GateName.COST)
    with pytest.raises(ValidationError, match="Gate outcomes must be exact"):
        DocumentCaseResult.model_validate(data)


def test_route_qualification_requires_all_gates_for_every_exact_cell() -> None:
    complete = _route(cases=[_case()])
    assert complete.status == "route_qualified"

    incomplete = _route(runs=2, cases=[_case()])
    assert incomplete.status == "incomplete"

    failed = _route(cases=[_case(failed=GateName.SOURCE_FIDELITY)])
    assert failed.status == "failed"
    assert failed.gate_totals[GateName.SOURCE_FIDELITY] == {"passed": 0, "failed": 1}


def test_status_is_computed_and_cannot_be_forged() -> None:
    route = _route(cases=[_case()])
    result = _result(routes={"treatment-sol": route})
    assert result.status == "route_qualified"

    forged = result.model_dump()
    forged["status"] = "qualified"
    assert DocumentQualificationResult.model_validate(forged).status == "route_qualified"

    assert _result(preflight=True).status == "preflight"


def test_only_complete_approved_three_route_corpus_is_qualified() -> None:
    routes: dict[str, RouteQualification] = {
        f"treatment-{alias}": _route(alias, cases=[_case(alias)]) for alias in ("sol", "opus", "kimi")
    }
    result = _result(expected_routes=("sol", "opus", "kimi"), routes=routes)
    assert result.status == "qualified"

    missing = _result(
        expected_routes=("sol", "opus", "kimi"),
        routes={key: value for key, value in routes.items() if key != "treatment-kimi"},
    )
    assert missing.status == "incomplete"


def test_mock_evidence_can_never_compute_a_qualified_status() -> None:
    routes: dict[str, RouteQualification] = {
        f"treatment-{alias}": _route(alias, cases=[_case(alias)]) for alias in ("sol", "opus", "kimi")
    }
    result = _result(
        expected_routes=("sol", "opus", "kimi"),
        routes=routes,
        evidence_environment="test",
    )
    assert all(route.status == "route_qualified" for route in result.routes.values())
    assert result.status == "incomplete"


def test_completed_cells_include_failed_attempts_but_not_absent_dispatches() -> None:
    failed = _case(failed=GateName.DIAGNOSTICS)
    result = _result(routes={"treatment-sol": _route(cases=[failed])})
    assert result.completed_cell_keys() == frozenset({failed.cell_key})


def test_charged_and_actual_totals_are_recomputed_from_cases() -> None:
    known = _case(fixture_id="fixture-a", actual_cost=0.03)
    unknown = _case(fixture_id="fixture-b", checksum=_HASH_C, actual_cost=None, reserved_cost=0.40)
    checksums = {"fixture-a": _HASH_D, "fixture-b": _HASH_C}
    result = _result(
        checksums=checksums,
        routes={"treatment-sol": _route(checksums=checksums, cases=[known, unknown])},
    )
    assert result.actual_cost_usd == pytest.approx(0.03)
    assert result.charged_cost_usd == pytest.approx(0.43)


@pytest.mark.parametrize(
    ("field", "replacement"),
    [
        ("experiment_fingerprint", "e" * 64),
        ("policy_fingerprint", "e" * 64),
        ("corpus_fingerprint", "e" * 64),
        ("route_fingerprint", "f" * 64),
        ("config_fingerprint", "f" * 64),
        ("evidence_environment", "test"),
        ("contract_version", "document-contract-v2"),
        ("runs_per_fixture", 2),
    ],
)
def test_merge_rejects_every_root_identity_drift(field: str, replacement: object) -> None:
    left = _result()
    right = left.model_copy(update={field: replacement})
    with pytest.raises(ValueError, match="different root identity"):
        left.merge(right)


def test_merge_keeps_newest_record_for_same_exact_cell() -> None:
    now = datetime.now(UTC)
    old_case = _case(updated_at=now, actual_cost=0.02)
    new_case = _case(updated_at=now + timedelta(seconds=1), actual_cost=0.07)
    old = _result(routes={"treatment-sol": _route(cases=[old_case])})
    new = _result(routes={"treatment-sol": _route(cases=[new_case])})

    merged = old.merge(new)
    assert len(merged.routes["treatment-sol"].cases) == 1
    assert merged.routes["treatment-sol"].cases[0].telemetry.actual_cost_usd == pytest.approx(0.07)


def test_stale_fixture_removes_only_its_cells_and_updates_resume_identity() -> None:
    checksums = {"fixture-a": _HASH_D, "fixture-b": _HASH_C}
    cases = [_case(), _case(fixture_id="fixture-b", checksum=_HASH_C)]
    result = _result(
        checksums=checksums,
        routes={"treatment-sol": _route(checksums=checksums, cases=cases)},
    )

    cleaned, stale = result.strip_stale_fixture_results(
        ["fixture-a", "fixture-b"], {"fixture-a": _HASH_B, "fixture-b": _HASH_C}
    )
    assert stale == frozenset({"fixture-a"})
    assert cleaned.fixture_checksums["fixture-a"] == _HASH_B
    assert cleaned.completed_cell_keys() == frozenset({("treatment-sol", "fixture-b", 1)})
    assert cleaned.status == "incomplete"


def test_serialization_is_strict_and_contains_only_safe_evidence(
    tmp_path: Path,
) -> None:
    result = _result(routes={"treatment-sol": _route(cases=[_case()])})
    dumped = result.model_dump_json()
    payload = json.loads(dumped)
    assert payload["schema_version"] == "document-qualification-v1"
    for forbidden in (
        "api_key",
        "raw_endpoint",
        "prompt",
        "messages",
        "thinking",
        "exception_message",
    ):
        assert forbidden not in dumped.casefold()

    unsafe = result.model_dump()
    unsafe["raw_endpoint"] = "https://provider.example.test/v1"
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        DocumentQualificationResult.model_validate(unsafe)

    path = tmp_path / "qualification.json"
    result.save(path)
    assert DocumentQualificationResult.load(path) == result


def test_atomic_save_failure_preserves_previous_artifact(tmp_path: Path) -> None:
    path = tmp_path / "qualification.json"
    path.write_text('{"previous": true}', encoding="utf-8")
    result = _result(routes={"treatment-sol": _route(cases=[_case()])})

    with (
        patch.object(Path, "replace", side_effect=OSError("simulated replace failure")),
        pytest.raises(OSError, match="simulated replace failure"),
    ):
        result.save(path)

    assert path.read_text(encoding="utf-8") == '{"previous": true}'
    assert not path.with_suffix(".tmp").exists()
