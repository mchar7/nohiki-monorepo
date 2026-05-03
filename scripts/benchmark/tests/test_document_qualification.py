"""Exact deterministic policy tests for document qualification."""

import json
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from nohiki_llm_client import (
    ApiKeyRegistry,
    LLMModelConfig,
    LLMProviderSettings,
    LLMResult,
    LLMSettings,
)
from pydantic_ai.usage import RunUsage
from tailor.lint.models import Severity

from llm_benchmark.document_fixtures import (
    DocumentQualificationFixture,
    get_document_fixture,
)
from llm_benchmark.engine.document_qualification import (
    APPROVED_DOCUMENT_ROUTES,
    CELL_TIMEOUT_SECONDS,
    GENERATION_TIMEOUT_SECONDS,
    DocumentContractEvaluation,
    DocumentQualificationRunner,
    evaluate_document_contracts,
    evaluate_source_fidelity,
    redact_for_evidence,
    validate_approved_document_chain,
)
from llm_benchmark.schemas.document_qualification import (
    ArtifactEvidence,
    FailureCode,
    GateEvidence,
    GateName,
    GateOutcome,
)

_PROXY = "https://provider.example.test/v1"
_FIXTURE = get_document_fixture("unicode_complete_resume")


def _models() -> tuple[LLMModelConfig, ...]:
    return (
        LLMModelConfig(
            model="openai:gpt-5.6-sol",
            reasoning_effort="medium",
            base_url=_PROXY,
        ),
        LLMModelConfig(
            model="openai:claude-opus-4-8",
            reasoning_effort="medium",
            base_url=_PROXY,
        ),
        LLMModelConfig(
            model="openrouter:moonshotai/kimi-k2.6",
            reasoning_effort="high",
            provider_order=("SiliconFlow",),
            provider_allow_fallbacks=False,
            provider_zdr=True,
        ),
    )


def _provider(models: tuple[LLMModelConfig, ...] | None = None) -> LLMProviderSettings:
    return LLMProviderSettings(
        models=list(models or _models()),
        api_keys=ApiKeyRegistry.model_validate(
            {"openai": "synthetic-openai-key", "openrouter": "synthetic-router-key"}
        ),
        max_tokens=4096,
        timeout_seconds=GENERATION_TIMEOUT_SECONDS,
        max_tool_retries=1,
        concurrency_limit=1,
    )


def _settings(models: tuple[LLMModelConfig, ...] | None = None) -> LLMSettings:
    provider = _provider(models)
    return LLMSettings(provider=provider, chains={"documents": provider})


def _replace_model(index: int, **changes: object) -> tuple[LLMModelConfig, ...]:
    models = list(_models())
    models[index] = models[index].model_copy(update=changes)
    return tuple(models)


def test_exact_approved_chain_and_route_order_are_pinned() -> None:
    routes = validate_approved_document_chain(_models(), _provider(), instrumentation_enabled=False)

    assert tuple(route.approved for route in routes) == APPROVED_DOCUMENT_ROUTES
    assert tuple(route.approved.alias for route in routes) == ("sol", "opus", "kimi")
    assert all(len(route.endpoint_sha256) == 64 for route in routes)
    assert all(_PROXY not in route.treatment_fingerprint for route in routes)


@pytest.mark.parametrize(
    ("models", "error_match"),
    [
        (_models()[::-1], "does not match the approved route contract"),
        (_models()[:2], "requires exactly the three approved routes"),
        ((*_models(), _models()[0]), "requires exactly the three approved routes"),
        (
            _replace_model(0, model="openai:gpt-5.6"),
            "does not match the approved route contract",
        ),
        (
            _replace_model(1, model="openai:claude-opus-4-7"),
            "does not match the approved route contract",
        ),
        (
            _replace_model(2, model="openrouter:moonshotai/kimi-k2.5"),
            "does not match the approved route contract",
        ),
        (
            _replace_model(0, reasoning_effort="high"),
            "does not match the approved route contract",
        ),
        (
            _replace_model(1, reasoning_effort="low"),
            "does not match the approved route contract",
        ),
        (
            _replace_model(2, reasoning_effort="medium"),
            "does not match the approved route contract",
        ),
        (_replace_model(0, base_url=None), "require an explicit proxy endpoint"),
        (
            _replace_model(1, base_url="https://api.openai.com/v1"),
            "require a non-public explicit proxy endpoint",
        ),
        (_replace_model(2, base_url=_PROXY), "must use the public OpenRouter endpoint"),
        (
            _replace_model(0, provider_order=("SiliconFlow",)),
            "does not match the approved route contract",
        ),
        (
            _replace_model(0, provider_allow_fallbacks=False),
            "does not match the approved route contract",
        ),
        (
            _replace_model(0, provider_allow_fallbacks=None),
            "does not match the approved route contract",
        ),
        (
            _replace_model(0, provider_zdr=True),
            "does not match the approved route contract",
        ),
        (
            _replace_model(0, provider_zdr=None),
            "does not match the approved route contract",
        ),
        (
            _replace_model(1, provider_order=("SiliconFlow",)),
            "does not match the approved route contract",
        ),
        (
            _replace_model(1, provider_allow_fallbacks=False),
            "does not match the approved route contract",
        ),
        (
            _replace_model(1, provider_allow_fallbacks=None),
            "does not match the approved route contract",
        ),
        (
            _replace_model(1, provider_zdr=True),
            "does not match the approved route contract",
        ),
        (
            _replace_model(1, provider_zdr=None),
            "does not match the approved route contract",
        ),
        (
            _replace_model(2, provider_order=()),
            "does not match the approved route contract",
        ),
        (
            _replace_model(2, provider_order=("Together",)),
            "does not match the approved route contract",
        ),
        (
            _replace_model(2, provider_order=("SiliconFlow", "Together")),
            "does not match the approved route contract",
        ),
        (
            _replace_model(2, provider_allow_fallbacks=True),
            "does not match the approved route contract",
        ),
        (
            _replace_model(2, provider_allow_fallbacks=None),
            "does not match the approved route contract",
        ),
        (
            _replace_model(2, provider_zdr=False),
            "does not match the approved route contract",
        ),
        (
            _replace_model(2, provider_zdr=None),
            "does not match the approved route contract",
        ),
    ],
)
def test_every_route_identity_variant_is_rejected(
    models: tuple[LLMModelConfig, ...],
    error_match: str,
) -> None:
    with pytest.raises(ValueError, match=error_match):
        validate_approved_document_chain(models, _provider(models), instrumentation_enabled=False)


@pytest.mark.parametrize(
    ("url", "error_match"),
    [
        ("http://provider.example.test/v1", "must be explicit HTTPS URLs"),
        (
            "https://user:credential@provider.example.test/v1",
            "cannot contain credentials, query strings, or fragments",
        ),
        (
            "https://provider.example.test/v1?credential=value",
            "must end with the OpenAI-compatible /v1 path",
        ),
        (
            "https://provider.example.test/v1#fragment",
            "must end with the OpenAI-compatible /v1 path",
        ),
    ],
)
def test_unsafe_proxy_endpoint_variants_are_rejected(url: str, error_match: str) -> None:
    models = _replace_model(0, base_url=url)
    with pytest.raises(ValueError, match=error_match):
        validate_approved_document_chain(models, _provider(models), instrumentation_enabled=False)


def test_normalized_equivalent_proxy_endpoints_have_same_safe_identity() -> None:
    left_models = _models()
    right_models = tuple(
        model.model_copy(update={"base_url": "https://provider.example.test/v1"}) if index < 2 else model
        for index, model in enumerate(_models())
    )
    left = validate_approved_document_chain(left_models, _provider(left_models), instrumentation_enabled=False)
    right = validate_approved_document_chain(right_models, _provider(right_models), instrumentation_enabled=False)

    assert [route.endpoint_sha256 for route in left] == [route.endpoint_sha256 for route in right]


@pytest.mark.parametrize(
    ("provider_change", "instrumentation_options", "error_match"),
    [
        (
            {"max_tokens": None},
            {"instrumentation_enabled": False},
            "requires a finite max_tokens bound",
        ),
        (
            {"timeout_seconds": 119},
            {"instrumentation_enabled": False},
            "requires positive max_tokens and the 120-second generation deadline",
        ),
        (
            {},
            {"instrumentation_enabled": True},
            "rejects prompt/response instrumentation",
        ),
    ],
)
def test_pre_dispatch_policy_rejects_unbounded_timeout_or_instrumentation(
    provider_change: dict[str, object],
    instrumentation_options: dict[str, bool],
    error_match: str,
) -> None:
    provider = _provider().model_copy(update=provider_change)
    with pytest.raises(ValueError, match=error_match):
        validate_approved_document_chain(
            tuple(provider.models),
            provider,
            **instrumentation_options,
        )


def _set_path(output: dict[str, object], path: str, value: str) -> None:
    current = output
    parts = path.removeprefix("$.").split(".")
    for part in parts[:-1]:
        child = current.setdefault(part, {})
        assert isinstance(child, dict)
        current = child
    current[parts[-1]] = value


def _faithful_output(fixture: DocumentQualificationFixture) -> dict[str, object]:
    output: dict[str, object] = {}
    for locked in fixture.ledger.locked_paths:
        _set_path(output, locked.path, locked.value)
    output["grounded_facts"] = [atom.value for atom in fixture.ledger.required_atoms]
    return output


def test_source_fidelity_accepts_only_locked_and_declared_facts() -> None:
    outcome = evaluate_source_fidelity(_faithful_output(_FIXTURE), _FIXTURE)

    assert outcome.passed
    assert outcome.evidence.issue_count == 0
    assert outcome.evidence.checked_count == len(_FIXTURE.ledger.locked_paths) + len(_FIXTURE.ledger.required_atoms)


def test_source_fidelity_accepts_every_declared_allowed_atom() -> None:
    output = _faithful_output(_FIXTURE)
    output["declared_allowed_facts"] = [atom.value for atom in _FIXTURE.ledger.allowed_atoms]

    outcome = evaluate_source_fidelity(output, _FIXTURE)

    assert outcome.passed
    assert outcome.evidence.unsupported_count == 0


def test_source_fidelity_rejects_changed_or_missing_locked_paths() -> None:
    output = _faithful_output(_FIXTURE)
    _set_path(output, _FIXTURE.ledger.locked_paths[0].path, "Mallory Override")
    output.pop("contact")

    outcome = evaluate_source_fidelity(output, _FIXTURE)

    assert not outcome.passed
    assert outcome.failure_codes == (FailureCode.FIDELITY,)
    assert outcome.evidence.changed_count >= 2


def test_source_fidelity_rejects_missing_required_and_forbidden_canary() -> None:
    fixture = get_document_fixture("adversarial_cover_letter")
    output = _faithful_output(fixture)
    output["grounded_facts"] = [
        fixture.ledger.required_atoms[0].value,
        fixture.ledger.forbidden_atoms[0].value,
    ]

    outcome = evaluate_source_fidelity(output, fixture)

    assert not outcome.passed
    assert outcome.evidence.missing_count >= 2


def test_source_fidelity_rejects_unsupported_contact_number_and_url() -> None:
    output = _faithful_output(_FIXTURE)
    output["fabricated"] = "intruder@unsupported.invalid +1 202-555-0199 https://unsupported.example.invalid 2099"

    outcome = evaluate_source_fidelity(output, _FIXTURE)

    assert not outcome.passed
    assert outcome.evidence.unsupported_count >= 4


def _contract_patches(
    *,
    valid: bool = True,
    content_issues: list[object] | None = None,
    layout_issues: list[object] | None = None,
    pdf: bytes = b"%PDF-synthetic",
    page_count: int = 1,
    text: str | None = None,
) -> tuple[patch, ...]:
    report = SimpleNamespace(valid=valid, issues=[] if valid else [object()])
    lint_config = SimpleNamespace(layout=SimpleNamespace(rules=[]))
    extracted_text = text or "\n".join(_FIXTURE.ledger.rendered_literals)
    parsed_page = SimpleNamespace(extract_text=lambda: extracted_text)
    parsed_pdf = MagicMock()
    parsed_pdf.__enter__.return_value = SimpleNamespace(pages=[parsed_page])
    parsed_pdf.__exit__.return_value = False
    service = MagicMock()
    service.convert_html_to_pdf = AsyncMock(return_value=pdf)
    draft_validator = MagicMock()
    draft_validator.return_value.iter_errors.return_value = ()
    return (
        patch("jsonschema.Draft202012Validator", draft_validator),
        patch(
            "doc_template_service.core.validation.validate_data",
            return_value=report,
        ),
        patch(
            "tailor.lint.config.load_lint_config",
            return_value=lint_config,
        ),
        patch(
            "tailor.lint.engine.LintEngine.evaluate",
            return_value=SimpleNamespace(issues=content_issues or []),
        ),
        patch(
            "doc_template_service.core.templates.jinja_engine.render_template",
            new=AsyncMock(return_value="<html/>"),
        ),
        patch(
            "doc_template_service.services.gotenberg.GotenbergService",
            return_value=service,
        ),
        patch(
            "tailor.lint.layout.pdfplumber_extractor.PdfPlumberLayoutExtractor.extract",
            return_value=SimpleNamespace(page_count=page_count),
        ),
        patch(
            "tailor.lint.layout.rules.run_layout_lint",
            return_value=layout_issues or [],
        ),
        patch("pdfplumber.open", return_value=parsed_pdf),
    )


async def _evaluate_with_patches(**kwargs: object) -> DocumentContractEvaluation:
    patches = _contract_patches(**kwargs)
    for active_patch in patches:
        active_patch.start()
    try:
        return await evaluate_document_contracts(
            _faithful_output(_FIXTURE), _FIXTURE, gotenberg_url="http://gotenberg.test"
        )
    finally:
        for active_patch in reversed(patches):
            active_patch.stop()


@pytest.mark.asyncio
async def test_schema_failure_stops_before_render_and_fails_closed() -> None:
    result = await _evaluate_with_patches(valid=False)

    assert not result.gate_outcomes[GateName.SCHEMA].passed
    assert result.artifact is None
    assert GateName.ARTIFACT not in result.gate_outcomes


@pytest.mark.asyncio
async def test_raw_draft_schema_rejects_additional_properties_without_render() -> None:
    result = await evaluate_document_contracts(
        {"unexpected_property": "synthetic"},
        _FIXTURE,
        gotenberg_url="http://gotenberg.test",
    )

    assert not result.gate_outcomes[GateName.SCHEMA].passed
    assert result.gate_outcomes[GateName.SCHEMA].evidence.issue_count > 0
    assert result.artifact is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("severity", "expected_issue_count"),
    [(Severity.INFO, 0), (Severity.WARNING, 0), (Severity.ERROR, 1)],
)
async def test_only_lint_errors_fail_coverage(severity: Severity, expected_issue_count: int) -> None:
    issue = SimpleNamespace(severity=severity)
    result = await _evaluate_with_patches(content_issues=[issue])

    evidence = result.gate_outcomes[GateName.COVERAGE].evidence
    assert result.gate_outcomes[GateName.COVERAGE].passed is (expected_issue_count == 0)
    assert evidence.issue_count == expected_issue_count
    assert evidence.warning_count == (1 if severity is Severity.WARNING else 0)


@pytest.mark.asyncio
async def test_pdf_header_is_required() -> None:
    with pytest.raises(ValueError, match="PDF"):
        await _evaluate_with_patches(pdf=b"not-a-pdf")


@pytest.mark.asyncio
async def test_pdf_hash_must_be_64_lower_hex() -> None:
    def invalid_pdf_hash(value: bytes | str) -> str:
        return "invalid" if isinstance(value, bytes) else "a" * 64

    with (
        patch(
            "llm_benchmark.engine.document_qualification._sha256",
            side_effect=invalid_pdf_hash,
        ),
        pytest.raises(ValueError, match="digest"),
    ):
        await _evaluate_with_patches()


@pytest.mark.asyncio
async def test_missing_required_pdf_text_fails_artifact_gate() -> None:
    result = await _evaluate_with_patches(text="unrelated extracted text")

    assert not result.gate_outcomes[GateName.ARTIFACT].passed
    assert result.gate_outcomes[GateName.ARTIFACT].evidence.missing_count == len(_FIXTURE.ledger.rendered_literals)


@pytest.mark.asyncio
async def test_page_limit_layout_error_fails_but_warning_does_not() -> None:
    error = SimpleNamespace(severity=Severity.ERROR)
    warning = SimpleNamespace(severity=Severity.WARNING)

    failed = await _evaluate_with_patches(page_count=3, layout_issues=[error])
    warned = await _evaluate_with_patches(page_count=2, layout_issues=[warning])

    assert not failed.gate_outcomes[GateName.ARTIFACT].passed
    assert warned.gate_outcomes[GateName.ARTIFACT].passed
    assert warned.gate_outcomes[GateName.ARTIFACT].evidence.warning_count == 1


def test_safe_redaction_recurses_through_keys_and_values() -> None:
    secret = "provider exploded: raw prompt, ThinkingPart, credential-value"
    unsafe = {
        _FIXTURE.ledger.locked_paths[0].value: {
            "endpoint": _PROXY,
            "contact": "intruder@unsafe.invalid +1 202-555-0199",
            "exception": secret,
            "messages": ["https://provider.example.test/v1"],
        }
    }

    redacted = redact_for_evidence(unsafe, _FIXTURE)
    serialized = json.dumps(redacted)

    for forbidden in (
        _FIXTURE.ledger.locked_paths[0].value,
        _PROXY,
        "intruder@unsafe.invalid",
        "+1 202-555-0199",
        "https://provider.example.test/v1",
    ):
        assert forbidden not in serialized
    assert "<redacted>" in serialized


class _FakeClient:
    def __init__(
        self,
        model: str,
        *,
        downstream_provider: str | None,
        error: BaseException | None = None,
    ) -> None:
        self.model = model
        self.downstream_provider = downstream_provider
        self.error = error
        self.calls = 0

    def create_dynamic_schema_agent(self, config: object) -> object:
        return config

    async def run(self, _agent: object, _prompt: str, **_kwargs: object) -> LLMResult[dict[str, object]]:
        self.calls += 1
        if self.error is not None:
            raise self.error
        return LLMResult(
            output={},
            usage=RunUsage(input_tokens=10, output_tokens=5, requests=1),
            model_used=self.model,
            duration_seconds=0.01,
            cost_usd=None,
            downstream_provider=self.downstream_provider,
        )


def _passing_contracts() -> DocumentContractEvaluation:
    gates = {
        gate: GateOutcome(passed=True, evidence=GateEvidence(checked_count=1))
        for gate in (
            GateName.SCHEMA,
            GateName.SOURCE_FIDELITY,
            GateName.COVERAGE,
            GateName.ARTIFACT,
        )
    }
    return DocumentContractEvaluation(
        gate_outcomes=gates,
        artifact=ArtifactEvidence(
            size_bytes=100,
            sha256="a" * 64,
            page_count=1,
            text_sha256="b" * 64,
            required_literals_checked=1,
            required_literals_present=1,
        ),
        output_sha256="c" * 64,
    )


def _runner(
    factory: Callable[[LLMSettings], _FakeClient],
    *,
    cost_cap_usd: float = 100,
    fixtures: tuple[DocumentQualificationFixture, ...] = (_FIXTURE,),
) -> DocumentQualificationRunner:
    async def renderer(
        _output: dict[str, object],
        _fixture: DocumentQualificationFixture,
        _gotenberg_url: str,
    ) -> DocumentContractEvaluation:
        return _passing_contracts()

    return DocumentQualificationRunner(
        llm_settings=_settings(),
        chain_name="documents",
        fixtures=fixtures,
        cost_cap_usd=cost_cap_usd,
        unknown_price_max_usd=1,
        gotenberg_url="http://gotenberg.test",
        evidence_environment="test",
        client_factory=factory,
        renderer=renderer,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("downstream", [None, "Together"])
async def test_kimi_missing_or_wrong_downstream_provider_fails(downstream: str | None, tmp_path: Path) -> None:
    clients: list[_FakeClient] = []

    def factory(settings: LLMSettings) -> _FakeClient:
        model = settings.provider.models[0].model
        client = _FakeClient(model, downstream_provider=downstream)
        clients.append(client)
        return client

    result = await _runner(factory).run(
        selected_routes=("kimi",),
        selected_fixtures=(_FIXTURE.fixture_id,),
        runs=1,
        output_path=tmp_path / "result.json",
    )
    case = next(iter(result.routes.values())).cases[0]

    assert not case.gate_outcomes[GateName.ROUTE_IDENTITY].passed
    assert case.safe_error is not None
    assert case.safe_error.code is FailureCode.ROUTE_IDENTITY
    assert sum(client.calls for client in clients) == 1


@pytest.mark.asyncio
async def test_dispatched_provider_failure_is_safely_persisted_and_charged(
    tmp_path: Path,
) -> None:
    body = "raw endpoint https://provider.example.test/v1 and credential-value"
    factory_calls = 0

    def factory(settings: LLMSettings) -> _FakeClient:
        nonlocal factory_calls
        factory_calls += 1
        return _FakeClient(
            settings.provider.models[0].model,
            downstream_provider=None,
            error=RuntimeError(body),
        )

    output = tmp_path / "result.json"
    runner = _runner(factory)
    result = await runner.run(
        selected_routes=("sol",),
        selected_fixtures=(_FIXTURE.fixture_id,),
        runs=1,
        output_path=output,
    )
    case = next(iter(result.routes.values())).cases[0]

    assert case.telemetry.charged_cost_usd == case.telemetry.reserved_cost_usd
    assert case.cell_key in result.completed_cell_keys()
    assert body not in output.read_text(encoding="utf-8")
    assert case.safe_error is not None
    assert case.safe_error.exception_type == "RuntimeError"

    rerun = await runner.run(
        selected_routes=("sol",),
        selected_fixtures=(_FIXTURE.fixture_id,),
        runs=1,
        output_path=output,
        existing=result,
    )
    assert factory_calls == 1
    assert rerun.completed_cell_keys() == result.completed_cell_keys()
    assert rerun.charged_cost_usd == pytest.approx(result.charged_cost_usd)


@pytest.mark.asyncio
async def test_cap_rejection_is_not_dispatched_or_persisted(tmp_path: Path) -> None:
    clients: list[_FakeClient] = []

    def factory(settings: LLMSettings) -> _FakeClient:
        client = _FakeClient(settings.provider.models[0].model, downstream_provider=None)
        clients.append(client)
        return client

    output = tmp_path / "result.json"
    result = await _runner(factory, cost_cap_usd=0.000001).run(
        selected_routes=("sol",),
        selected_fixtures=(_FIXTURE.fixture_id,),
        runs=1,
        output_path=output,
    )

    assert result.completed_cell_keys() == frozenset()
    assert not output.exists()
    assert clients == []


@pytest.mark.asyncio
async def test_generation_timeout_is_persisted_as_safe_timeout(tmp_path: Path) -> None:
    class SlowClient(_FakeClient):
        async def run(self, _agent: object, _prompt: str, **_kwargs: object) -> LLMResult[dict[str, object]]:
            import asyncio

            self.calls += 1
            await asyncio.sleep(0.02)
            message = "timeout should cancel this call"
            raise AssertionError(message)

    def factory(settings: LLMSettings) -> _FakeClient:
        return SlowClient(settings.provider.models[0].model, downstream_provider=None)

    output = tmp_path / "result.json"
    runner = _runner(factory)
    with patch(
        "llm_benchmark.engine.document_qualification.GENERATION_TIMEOUT_SECONDS",
        0.001,
    ):
        result = await runner.run(
            selected_routes=("sol",),
            selected_fixtures=(_FIXTURE.fixture_id,),
            runs=1,
            output_path=output,
        )
    case = next(iter(result.routes.values())).cases[0]

    assert case.safe_error is not None
    assert case.safe_error.code is FailureCode.TIMEOUT
    assert case.telemetry.charged_cost_usd == case.telemetry.reserved_cost_usd
    assert "timeout should cancel" not in output.read_text(encoding="utf-8")


@pytest.mark.asyncio
async def test_stale_fixture_resume_reruns_only_changed_cell(tmp_path: Path) -> None:
    second = get_document_fixture("complete_cover_letter")
    fixtures = (_FIXTURE, second)
    factory_calls: list[str] = []

    def factory(settings: LLMSettings) -> _FakeClient:
        model = settings.provider.models[0].model
        factory_calls.append(model)
        return _FakeClient(model, downstream_provider=None)

    output = tmp_path / "result.json"
    original = await _runner(factory, fixtures=fixtures).run(
        selected_routes=("sol",),
        selected_fixtures=tuple(fixture.fixture_id for fixture in fixtures),
        runs=1,
        output_path=output,
    )
    changed = replace(
        _FIXTURE,
        branch_tags=_FIXTURE.branch_tags | {"checksum-drift-control"},
    )

    resumed = await _runner(factory, fixtures=(changed, second)).run(
        selected_routes=("sol",),
        selected_fixtures=(changed.fixture_id, second.fixture_id),
        runs=1,
        output_path=output,
        existing=original,
    )

    assert len(factory_calls) == 3
    assert len(resumed.completed_cell_keys()) == 2


@pytest.mark.asyncio
async def test_independent_route_runs_append_under_one_full_chain_identity(
    tmp_path: Path,
) -> None:
    factory_calls: list[str] = []

    def factory(settings: LLMSettings) -> _FakeClient:
        model = settings.provider.models[0].model
        factory_calls.append(model)
        downstream = "SiliconFlow" if model.startswith("openrouter:") else None
        return _FakeClient(model, downstream_provider=downstream)

    runner = _runner(factory)
    output = tmp_path / "result.json"
    current = None
    experiment_fingerprints: set[str] = set()
    for alias in ("sol", "opus", "kimi"):
        current = await runner.run(
            selected_routes=(alias,),
            selected_fixtures=(_FIXTURE.fixture_id,),
            runs=1,
            output_path=output,
            existing=current,
        )
        experiment_fingerprints.add(current.experiment_fingerprint)

    assert len(factory_calls) == 3
    assert len(experiment_fingerprints) == 1
    assert current is not None
    assert len(current.routes) == 3
    assert all(case.passed for route in current.routes.values() for case in route.cases)
    assert current.status == "incomplete"


def test_production_evidence_rejects_every_injected_test_seam() -> None:
    def factory(settings: LLMSettings) -> _FakeClient:
        return _FakeClient(settings.provider.models[0].model, downstream_provider=None)

    with pytest.raises(ValueError, match="test evidence"):
        DocumentQualificationRunner(
            llm_settings=_settings(),
            chain_name="documents",
            fixtures=(_FIXTURE,),
            cost_cap_usd=10,
            unknown_price_max_usd=1,
            gotenberg_url="http://gotenberg.test",
            client_factory=factory,
        )

    assert CELL_TIMEOUT_SECONDS == 180
    assert GENERATION_TIMEOUT_SECONDS == 120
