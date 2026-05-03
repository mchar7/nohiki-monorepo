"""Resume, persistence, and cost invariants for document qualification."""

from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

import pytest

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
_FIXTURES = {"fixture-a": _HASH_C, "fixture-b": _HASH_D}


def _outcomes(failed: GateName | None = None) -> dict[GateName, GateOutcome]:
    return {
        gate: GateOutcome(
            passed=gate is not failed,
            failure_codes=() if gate is not failed else (FailureCode.PROVIDER_RESPONSE,),
        )
        for gate in GateName
    }


def _case(
    alias: str,
    fixture_id: str,
    *,
    failed: GateName | None = None,
    actual_cost_usd: float | None = 0.04,
) -> DocumentCaseResult:
    reserved = 0.25
    charged = actual_cost_usd if actual_cost_usd is not None else reserved
    passed = failed is None
    return DocumentCaseResult(
        treatment_id=f"treatment-{alias}",
        fixture_id=fixture_id,
        fixture_checksum=_FIXTURES[fixture_id],
        run_number=1,
        cell_fingerprint=_HASH_B,
        gate_outcomes=_outcomes(failed),
        telemetry=CaseTelemetry(
            latency_ms=80,
            cell_latency_ms=120,
            request_count=1,
            actual_cost_usd=actual_cost_usd,
            reserved_cost_usd=reserved,
            charged_cost_usd=charged,
        ),
        output_sha256=_HASH_A if passed else None,
        artifact=(
            ArtifactEvidence(
                size_bytes=512,
                sha256=_HASH_B,
                page_count=1,
                text_sha256=_HASH_C,
                required_literals_checked=2,
                required_literals_present=2,
            )
            if passed
            else None
        ),
        safe_error=(
            None
            if passed
            else SafeError(
                code=FailureCode.PROVIDER_RESPONSE,
                exception_type="SyntheticProviderError",
            )
        ),
    )


def _route(alias: str, cases: list[DocumentCaseResult]) -> RouteQualification:
    kimi = alias == "kimi"
    return RouteQualification(
        identity=SafeRouteIdentity(
            route_alias=alias,
            treatment_id=f"treatment-{alias}",
            treatment_fingerprint=_HASH_A,
            configured_model={
                "sol": "openai:gpt-5.6-sol",
                "opus": "openai:claude-opus-4-8",
                "kimi": "openrouter:moonshotai/kimi-k2.6",
            }[alias],
            returned_model={
                "sol": "openai:gpt-5.6-sol",
                "opus": "openai:claude-opus-4-8",
                "kimi": "openrouter:moonshotai/kimi-k2.6",
            }[alias],
            reasoning_effort="high" if kimi else "medium",
            endpoint_class="public_openrouter" if kimi else "proxy",
            endpoint_sha256=_HASH_B,
            provider_order=("SiliconFlow",) if kimi else (),
            allow_fallbacks=False,
            zdr=kimi,
            downstream_provider="SiliconFlow" if kimi else None,
            pricing=PricingEvidence(
                pricing_fingerprint=_HASH_D,
                source="provider",
                maximum_call_cost_usd=0.25,
            ),
        ),
        expected_fixture_checksums=_FIXTURES,
        runs_per_fixture=1,
        cases=cases,
    )


def _result(
    routes: dict[str, RouteQualification] | None = None,
    *,
    evidence_environment: str = "test",
) -> DocumentQualificationResult:
    return DocumentQualificationResult(
        contract_version="document-contract-v1",
        experiment_fingerprint=_HASH_A,
        policy_fingerprint=_HASH_B,
        corpus_fingerprint=_HASH_C,
        route_fingerprint=_HASH_D,
        config_fingerprint="e" * 64,
        expected_routes=("sol", "opus", "kimi"),
        fixture_checksums=_FIXTURES,
        runs_per_fixture=1,
        evidence_environment=evidence_environment,
        routes=routes or {},
    )


def test_dispatched_failure_is_persisted_skipped_and_charged() -> None:
    failed = _case(
        "sol",
        "fixture-a",
        failed=GateName.DIAGNOSTICS,
        actual_cost_usd=None,
    )
    result = _result({"treatment-sol": _route("sol", [failed])})

    assert failed.cell_key in result.completed_cell_keys()
    assert result.charged_cost_usd == pytest.approx(0.25)
    assert result.actual_cost_usd == pytest.approx(0.0)
    assert result.status == "failed"


def test_non_dispatched_budget_rejection_has_no_persisted_cell_or_charge() -> None:
    result = _result()

    assert result.completed_cell_keys() == frozenset()
    assert result.charged_cost_usd == pytest.approx(0.0)
    assert result.actual_cost_usd == pytest.approx(0.0)
    assert result.status == "incomplete"


def test_resume_totals_seed_from_known_and_unknown_cost_attempts() -> None:
    known = _case("sol", "fixture-a", actual_cost_usd=0.07)
    unknown = _case("sol", "fixture-b", actual_cost_usd=None)
    restored = DocumentQualificationResult.model_validate_json(
        _result({"treatment-sol": _route("sol", [known, unknown])}).model_dump_json()
    )

    assert restored.actual_cost_usd == pytest.approx(0.07)
    assert restored.charged_cost_usd == pytest.approx(0.32)
    assert restored.completed_cell_keys() == frozenset({known.cell_key, unknown.cell_key})


def test_stale_fixture_reruns_only_changed_exact_cells() -> None:
    cases = [_case("sol", fixture_id) for fixture_id in _FIXTURES]
    result = _result({"treatment-sol": _route("sol", cases)})
    changed = dict(_FIXTURES) | {"fixture-a": "f" * 64}

    cleaned, stale = result.strip_stale_fixture_results(list(_FIXTURES), changed)

    assert stale == frozenset({"fixture-a"})
    assert cleaned.completed_cell_keys() == frozenset({("treatment-sol", "fixture-b", 1)})
    pending = {("treatment-sol", fixture_id, 1) for fixture_id in _FIXTURES} - cleaned.completed_cell_keys()
    assert pending == {("treatment-sol", "fixture-a", 1)}


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("experiment_fingerprint", "f" * 64),
        ("policy_fingerprint", "f" * 64),
        ("corpus_fingerprint", "f" * 64),
        ("route_fingerprint", "f" * 64),
        ("config_fingerprint", "f" * 64),
        ("deadline_seconds", 179),
        ("evidence_environment", "production"),
    ],
)
def test_root_drift_rejects_resume(field: str, value: object) -> None:
    original = _result()
    drifted = original.model_copy(update={field: value})

    with pytest.raises(ValueError, match="different root identity"):
        original.merge(drifted)


def test_exact_rerun_has_zero_pending_calls() -> None:
    cases = [_case(alias, fixture_id) for alias in ("sol", "opus", "kimi") for fixture_id in _FIXTURES]
    result = _result(
        {
            f"treatment-{alias}": _route(
                alias,
                [case for case in cases if case.treatment_id == f"treatment-{alias}"],
            )
            for alias in ("sol", "opus", "kimi")
        }
    )
    expected = {(f"treatment-{alias}", fixture_id, 1) for alias in ("sol", "opus", "kimi") for fixture_id in _FIXTURES}

    assert expected - result.completed_cell_keys() == set()
    assert result.status == "incomplete"


def test_atomic_save_failure_retains_prior_artifact(tmp_path: Path) -> None:
    output = tmp_path / "qualification.json"
    output.write_text('{"prior":"artifact"}', encoding="utf-8")

    with (
        patch.object(Path, "replace", side_effect=OSError("private failure body")),
        pytest.raises(OSError, match="private failure body"),
    ):
        _result().save(output)

    assert output.read_text(encoding="utf-8") == '{"prior":"artifact"}'
    assert not output.with_suffix(".tmp").exists()


def test_separate_routes_append_and_only_full_production_chain_qualifies() -> None:
    started_at = datetime.now(UTC)
    partials = [
        _result(
            {
                f"treatment-{alias}": _route(
                    alias,
                    [_case(alias, fixture_id) for fixture_id in _FIXTURES],
                )
            },
            evidence_environment="production",
        ).model_copy(update={"started_at": started_at})
        for alias in ("sol", "opus", "kimi")
    ]

    merged = partials[0]
    assert merged.status == "incomplete"
    merged = merged.merge(partials[1])
    assert merged.status == "incomplete"
    merged = merged.merge(partials[2])

    assert merged.status == "qualified"
    assert set(merged.routes) == {
        "treatment-sol",
        "treatment-opus",
        "treatment-kimi",
    }


def test_test_double_evidence_can_never_become_production_qualified() -> None:
    routes = {
        f"treatment-{alias}": _route(alias, [_case(alias, fixture_id) for fixture_id in _FIXTURES])
        for alias in ("sol", "opus", "kimi")
    }

    result = _result(routes, evidence_environment="test")

    assert result.status == "incomplete"
    assert result.evidence_environment == "test"
    assert '"evidence_environment":"test"' in result.model_dump_json()
