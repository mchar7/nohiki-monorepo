"""Deterministic production-equivalent document model qualification."""

import asyncio
import hashlib
import io
import json
import re
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Protocol, cast
from urllib.parse import urlsplit, urlunsplit

from doc_content_service.services.context import DocumentContentContext
from doc_content_service.services.prompt_builder import (
    build_system_prompt,
    build_user_prompt,
)
from nohiki_llm_client import (
    DynamicAgentConfig,
    LLMClient,
    LLMModelConfig,
    LLMProviderSettings,
    LLMResult,
    LLMSettings,
)
from nohiki_test_utils import get_repo_root

from llm_benchmark.document_fixtures import (
    DOCUMENT_FIXTURES,
    DocumentQualificationFixture,
    compute_document_fixture_checksum,
)
from llm_benchmark.engine.budget import BudgetExhaustedError, BudgetScheduler
from llm_benchmark.pricing import PricingSnapshot, resolve_pricing_snapshot
from llm_benchmark.schemas.document_qualification import (
    APPROVED_ROUTE_ALIASES,
    ArtifactEvidence,
    CaseTelemetry,
    DocumentCaseResult,
    DocumentQualificationResult,
    FailureCode,
    GateEvidence,
    GateName,
    GateOutcome,
    PricingEvidence,
    RouteQualification,
    SafeError,
    SafeRouteIdentity,
)

DOCUMENT_POLICY_VERSION = "document-qualification-policy-v1"
GENERATION_TIMEOUT_SECONDS = 120
CELL_TIMEOUT_SECONDS = 180
_APPLICATION_ATTEMPTS = 3
_PUBLIC_OPENROUTER_ENDPOINT = "https://openrouter.ai/api/v1"
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_EMAIL_RE = re.compile(r"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b")
_URL_RE = re.compile(r"(?i)\bhttps?://[^\s<>\"]+")
_PHONE_RE = re.compile(r"(?<!\w)(?:\+?\d[\d(). -]{7,}\d)(?!\w)")
_NUMBER_RE = re.compile(r"(?<![\w.])\d[\d,./-]*(?![\w.])")
_LONG_IDENTIFIER_RE = re.compile(r"\b[A-Za-z0-9_-]{24,}\b")


@dataclass(frozen=True, slots=True)
class ApprovedDocumentRoute:
    """One exact route in the approved qualification chain."""

    alias: Literal["sol", "opus", "kimi"]
    model: str
    reasoning_effort: Literal["medium", "high"]
    endpoint_class: Literal["proxy", "public_openrouter"]
    provider_order: tuple[str, ...]
    allow_fallbacks: bool
    zdr: bool


APPROVED_DOCUMENT_ROUTES: tuple[ApprovedDocumentRoute, ...] = (
    ApprovedDocumentRoute(
        alias="sol",
        model="openai:gpt-5.6-sol",
        reasoning_effort="medium",
        endpoint_class="proxy",
        provider_order=(),
        allow_fallbacks=True,
        zdr=False,
    ),
    ApprovedDocumentRoute(
        alias="opus",
        model="openai:claude-opus-4-8",
        reasoning_effort="medium",
        endpoint_class="proxy",
        provider_order=(),
        allow_fallbacks=True,
        zdr=False,
    ),
    ApprovedDocumentRoute(
        alias="kimi",
        model="openrouter:moonshotai/kimi-k2.6",
        reasoning_effort="high",
        endpoint_class="public_openrouter",
        provider_order=("SiliconFlow",),
        allow_fallbacks=False,
        zdr=True,
    ),
)


@dataclass(frozen=True, slots=True)
class ValidatedDocumentRoute:
    """Approved route plus its safe, stable treatment identity."""

    approved: ApprovedDocumentRoute
    model_config: LLMModelConfig
    endpoint_sha256: str
    treatment_id: str
    treatment_fingerprint: str


@dataclass(frozen=True, slots=True)
class DocumentContractEvaluation:
    """Safe output of schema, fidelity, lint, render, and layout evaluation."""

    gate_outcomes: dict[GateName, GateOutcome]
    artifact: ArtifactEvidence | None
    output_sha256: str


class DocumentClient(Protocol):
    """Generate one schema-constrained document through an isolated client."""

    async def generate_document(
        self,
        config: DynamicAgentConfig[DocumentContentContext],
        prompt: str,
        /,
        *,
        deps: DocumentContentContext,
    ) -> LLMResult[dict[str, object]]:
        """Generate a document with the supplied schema and prompt context."""
        ...


class ClientFactory(Protocol):
    """Construct an isolated document client for one-model settings."""

    def __call__(self, settings: LLMSettings, /) -> DocumentClient:
        """Return a client bound to exactly one model."""
        ...


class DocumentRenderer(Protocol):
    """Evaluate all deterministic output contracts, including real PDF rendering."""

    async def __call__(
        self,
        output: dict[str, object],
        fixture: DocumentQualificationFixture,
        gotenberg_url: str,
        /,
    ) -> DocumentContractEvaluation:
        """Return safe contract evidence."""
        ...


def _canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sha256(value: bytes | str) -> str:
    payload = value.encode() if isinstance(value, str) else value
    return hashlib.sha256(payload).hexdigest()


def _normalize_endpoint(value: str) -> str:
    parsed = urlsplit(value.strip())
    if parsed.scheme.lower() != "https" or not parsed.hostname:
        msg = "Document qualification endpoints must be explicit HTTPS URLs"
        raise ValueError(msg)
    if parsed.username is not None or parsed.password is not None or parsed.query or parsed.fragment:
        msg = "Document qualification endpoints cannot contain credentials, query strings, or fragments"
        raise ValueError(msg)
    host = parsed.hostname.lower()
    port = parsed.port
    netloc = host if port in (None, 443) else f"{host}:{port}"
    path = "/" + "/".join(part for part in parsed.path.split("/") if part)
    return urlunsplit(("https", netloc, path.rstrip("/"), "", ""))


def classify_and_hash_endpoint(
    model: LLMModelConfig,
) -> tuple[Literal["proxy", "public_openrouter"], str]:
    """Classify a route without retaining its endpoint and return its SHA-256."""
    if model.provider_name == "openrouter":
        normalized = _PUBLIC_OPENROUTER_ENDPOINT if model.base_url is None else _normalize_endpoint(model.base_url)
        if normalized != _PUBLIC_OPENROUTER_ENDPOINT:
            msg = "The approved Kimi route must use the public OpenRouter endpoint"
            raise ValueError(msg)
        return "public_openrouter", _sha256(normalized)
    if model.provider_name == "openai" and model.base_url is not None:
        normalized = _normalize_endpoint(model.base_url)
        if normalized in {
            _normalize_endpoint(_PUBLIC_OPENROUTER_ENDPOINT),
            "https://api.openai.com/v1",
        }:
            msg = "Approved proxy routes require a non-public explicit proxy endpoint"
            raise ValueError(msg)
        return "proxy", _sha256(normalized)
    msg = "Approved proxy routes require an explicit proxy endpoint"
    raise ValueError(msg)


def validate_approved_document_chain(
    models: tuple[LLMModelConfig, ...],
    settings: LLMProviderSettings,
    *,
    instrumentation_enabled: bool,
) -> tuple[ValidatedDocumentRoute, ...]:
    """Reject every deviation from the exact three-route production chain."""
    if instrumentation_enabled:
        msg = "Document qualification rejects prompt/response instrumentation"
        raise ValueError(msg)
    if settings.max_tokens is None:
        msg = "Document qualification requires a finite max_tokens bound"
        raise ValueError(msg)
    if settings.max_tokens <= 0 or settings.timeout_seconds != GENERATION_TIMEOUT_SECONDS:
        msg = "Document qualification requires positive max_tokens and the 120-second generation deadline"
        raise ValueError(msg)
    if len(models) != len(APPROVED_DOCUMENT_ROUTES):
        msg = "Document qualification requires exactly the three approved routes"
        raise ValueError(msg)

    validated: list[ValidatedDocumentRoute] = []
    for model, approved in zip(models, APPROVED_DOCUMENT_ROUTES, strict=True):
        endpoint_class, endpoint_sha256 = classify_and_hash_endpoint(model)
        common_actual = (model.model, model.reasoning_effort, endpoint_class)
        common_expected = (
            approved.model,
            approved.reasoning_effort,
            approved.endpoint_class,
        )
        proxy_controls_absent = (
            not model.provider_order and model.provider_allow_fallbacks is True and model.provider_zdr is False
        )
        kimi_controls_exact = (
            model.provider_order == approved.provider_order
            and model.provider_allow_fallbacks is approved.allow_fallbacks
            and model.provider_zdr is approved.zdr
        )
        controls_valid = proxy_controls_absent if approved.endpoint_class == "proxy" else kimi_controls_exact
        if common_actual != common_expected or not controls_valid:
            msg = f"Route {approved.alias!r} does not match the approved route contract"
            raise ValueError(msg)
        material = {
            "alias": approved.alias,
            "model": approved.model,
            "reasoning_effort": approved.reasoning_effort,
            "endpoint_class": endpoint_class,
            "endpoint_sha256": endpoint_sha256,
            "provider_order": approved.provider_order,
            "allow_fallbacks": approved.allow_fallbacks,
            "zdr": approved.zdr,
        }
        fingerprint = _sha256(_canonical_json(material))
        validated.append(
            ValidatedDocumentRoute(
                approved=approved,
                model_config=model,
                endpoint_sha256=endpoint_sha256,
                treatment_id=f"document-{approved.alias}-{fingerprint[:16]}",
                treatment_fingerprint=fingerprint,
            )
        )
    return tuple(validated)


def document_experiment_fingerprint(
    *,
    routes: tuple[ValidatedDocumentRoute, ...],
    fixtures: tuple[DocumentQualificationFixture, ...],
    pricing: Mapping[str, PricingSnapshot],
    settings: LLMProviderSettings,
    runs: int,
    cost_cap_usd: float,
    unknown_price_max_usd: float | None = None,
) -> str:
    """Fingerprint the full chain, contracts, pricing, deadlines, and cap policy."""
    if tuple(route.approved.alias for route in routes) != APPROVED_ROUTE_ALIASES:
        msg = "Experiment identity must always contain the complete approved chain"
        raise ValueError(msg)
    if runs < 1 or cost_cap_usd <= 0:
        msg = "Runs and owner-approved cost cap must be positive"
        raise ValueError(msg)
    fixture_material = []
    for fixture in fixtures:
        context = fixture.build_context()
        fixture_material.append(
            {
                "id": fixture.fixture_id,
                "checksum": compute_document_fixture_checksum(fixture),
                "system_prompt_sha256": _sha256(build_system_prompt(context)),
                "user_prompt_sha256": _sha256(build_user_prompt(context)),
                "raw_schema_sha256": _sha256((get_repo_root() / fixture.schema_identifier).read_bytes()),
                "processed_schema_sha256": _sha256(_canonical_json(context.schema_definition)),
                "template_sha256": _sha256((get_repo_root() / fixture.template_identifier).read_bytes()),
                "lint_sha256": _sha256((get_repo_root() / fixture.lint_identifier).read_bytes()),
            }
        )
    material = {
        "policy": DOCUMENT_POLICY_VERSION,
        "routes": [route.treatment_fingerprint for route in routes],
        "pricing": {alias: pricing[alias].fingerprint_material() for alias in APPROVED_ROUTE_ALIASES},
        "fixtures": fixture_material,
        "temperature": settings.temperature,
        "max_tokens": settings.max_tokens,
        "timeout_seconds": settings.timeout_seconds,
        "max_tool_retries": settings.max_tool_retries,
        "concurrency_limit": settings.concurrency_limit,
        "generation_timeout_seconds": GENERATION_TIMEOUT_SECONDS,
        "cell_timeout_seconds": CELL_TIMEOUT_SECONDS,
        "application_attempts": _APPLICATION_ATTEMPTS,
        "runs": runs,
        "cost_cap_usd": cost_cap_usd,
        "unknown_price_max_usd": unknown_price_max_usd,
    }
    return _sha256(_canonical_json(material))


def _resolve_path(value: object, path: str) -> object:
    current = value
    for part in path.removeprefix("$.").split("."):
        match = re.fullmatch(r"([^\[]+)(?:\[(\d+)\])?", part)
        if match is None or not isinstance(current, dict):
            raise KeyError(path)
        current = cast("dict[str, object]", current)[match.group(1)]
        if (index := match.group(2)) is not None:
            if not isinstance(current, list):
                raise KeyError(path)
            current = current[int(index)]
    return current


def _flatten_strings(value: object) -> tuple[str, ...]:
    match value:
        case str():
            return (value,)
        case dict():
            return tuple(text for child in value.values() for text in _flatten_strings(child))
        case list() | tuple():
            return tuple(text for child in value for text in _flatten_strings(child))
        case _:
            return ()


def _fact_tokens(text: str) -> set[str]:
    tokens: set[str] = set()
    for pattern in (_EMAIL_RE, _URL_RE, _PHONE_RE, _NUMBER_RE):
        tokens.update(match.group(0).casefold().rstrip(".,;:") for match in pattern.finditer(text))
    return tokens


def _factual_field_values(value: object, path: str = "$") -> tuple[str, ...]:
    """Return leaf strings from schema fields that carry discrete facts."""
    markers = (
        "skill",
        "certif",
        "institution",
        "school",
        "company",
        "employer",
        "organization",
        "email",
        "phone",
        "url",
        "date",
        "position",
        "role",
    )
    match value:
        case dict():
            values: list[str] = []
            for key, child in cast("dict[str, object]", value).items():
                child_path = f"{path}.{key}"
                if isinstance(child, str) and any(marker in key.casefold() for marker in markers):
                    values.append(child)
                else:
                    values.extend(_factual_field_values(child, child_path))
            return tuple(values)
        case list() | tuple():
            return tuple(
                text for index, child in enumerate(value) for text in _factual_field_values(child, f"{path}[{index}]")
            )
        case str() if any(marker in path.casefold() for marker in markers):
            return (value,)
        case _:
            return ()


def evaluate_source_fidelity(
    output: dict[str, object],
    fixture: DocumentQualificationFixture,
) -> GateOutcome:
    """Evaluate locked values and factual atom allow/deny rules without scoring."""
    serialized = _canonical_json(output)
    folded = serialized.casefold()
    missing = sum(atom.value.casefold() not in folded for atom in fixture.ledger.required_atoms)
    forbidden = sum(atom.value.casefold() in folded for atom in fixture.ledger.forbidden_atoms)
    changed = 0
    checked = len(fixture.ledger.locked_paths) + len(fixture.ledger.required_atoms)
    for locked in fixture.ledger.locked_paths:
        try:
            if _resolve_path(output, locked.path) != locked.value:
                changed += 1
        except KeyError, IndexError, TypeError:
            changed += 1

    allowed_text = "\n".join(
        [
            *(item.value for item in fixture.ledger.allowed_atoms),
            *(item.value for item in fixture.ledger.required_atoms),
            *(item.value for item in fixture.ledger.locked_paths),
        ]
    )
    allowed_tokens = _fact_tokens(allowed_text)
    allowed_values = {
        item.value.casefold().strip()
        for item in (
            *fixture.ledger.allowed_atoms,
            *fixture.ledger.required_atoms,
            *fixture.ledger.locked_paths,
        )
    }
    unsupported_fields = {
        value.casefold().strip()
        for value in _factual_field_values(output)
        if value.strip()
        and not any(
            value.casefold().strip() == allowed
            or value.casefold().strip() in allowed
            or allowed in value.casefold().strip()
            for allowed in allowed_values
        )
    }
    unsupported = len((_fact_tokens("\n".join(_flatten_strings(output))) - allowed_tokens) | unsupported_fields)
    issue_count = missing + forbidden + changed + unsupported
    evidence = GateEvidence(
        issue_count=issue_count,
        missing_count=missing + forbidden,
        unsupported_count=unsupported,
        changed_count=changed,
        checked_count=checked,
        evidence_sha256=_sha256(
            _canonical_json(
                {
                    "missing": missing,
                    "forbidden": forbidden,
                    "unsupported": unsupported,
                    "changed": changed,
                    "paths": [_sha256(item.path) for item in fixture.ledger.locked_paths],
                }
            )
        ),
    )
    return GateOutcome(
        passed=issue_count == 0,
        failure_codes=() if issue_count == 0 else (FailureCode.FIDELITY,),
        evidence=evidence,
    )


def _issue_evidence(issues: Sequence[object]) -> GateEvidence:
    severities = [str(getattr(issue, "severity", "")) for issue in issues]
    errors = severities.count("error")
    warnings = severities.count("warning")
    infos = severities.count("info")
    return GateEvidence(
        issue_count=errors,
        warning_count=warnings,
        info_count=infos,
        checked_count=len(issues),
        evidence_sha256=_sha256(_canonical_json({"errors": errors, "warnings": warnings, "infos": infos})),
    )


def _build_artifact_evidence(
    pdf: bytes,
    pdf_sha256: str,
    page_count: int,
    text: str,
    layout_evidence: GateEvidence,
    required_literals: tuple[str, ...],
) -> tuple[ArtifactEvidence, GateOutcome]:
    """Build deterministic evidence for a rendered PDF and its layout gate."""
    required_literals_checked = len(required_literals)
    required_literals_present = sum(literal.casefold() in text.casefold() for literal in required_literals)
    artifact = ArtifactEvidence(
        size_bytes=len(pdf),
        sha256=pdf_sha256,
        page_count=page_count,
        text_sha256=_sha256(text),
        required_literals_checked=required_literals_checked,
        required_literals_present=required_literals_present,
    )
    artifact_ok = (
        page_count > 0 and layout_evidence.issue_count == 0 and required_literals_present == required_literals_checked
    )
    artifact_gate = GateOutcome(
        passed=artifact_ok,
        failure_codes=() if artifact_ok else (FailureCode.LAYOUT,),
        evidence=GateEvidence(
            issue_count=layout_evidence.issue_count,
            warning_count=layout_evidence.warning_count,
            info_count=layout_evidence.info_count,
            missing_count=required_literals_checked - required_literals_present,
            checked_count=required_literals_checked,
            evidence_sha256=_sha256(
                _canonical_json(
                    {
                        "pdf": pdf_sha256,
                        "text": artifact.text_sha256,
                        "pages": page_count,
                    }
                )
            ),
        ),
    )
    return artifact, artifact_gate


async def evaluate_document_contracts(
    output: dict[str, object],
    fixture: DocumentQualificationFixture,
    *,
    gotenberg_url: str,
) -> DocumentContractEvaluation:
    """Apply schema, fidelity, shipped lint, real render, and layout gates in order."""
    # These production modules instantiate service settings at import time, so
    # keep them behind the paid render boundary. Preflight and pure gates remain
    # credential-free and do not require S3/database configuration.
    # Tailor intentionally establishes non-secret standalone defaults before
    # doc-template-service imports its service Settings singleton.
    import pdfplumber
    import tailor
    from doc_template_service.core.templates.jinja_engine import render_template
    from doc_template_service.core.validation import validate_data
    from doc_template_service.services.gotenberg import GotenbergService
    from jsonschema import Draft202012Validator

    del tailor
    from tailor.lint.config import load_lint_config
    from tailor.lint.engine import LintEngine
    from tailor.lint.layout.pdfplumber_extractor import PdfPlumberLayoutExtractor
    from tailor.lint.layout.rules import run_layout_lint

    output_sha256 = _sha256(_canonical_json(output))
    raw_schema_value = json.loads((get_repo_root() / fixture.schema_identifier).read_text(encoding="utf-8"))
    if not isinstance(raw_schema_value, dict):
        msg = "Shipped document schema must be an object"
        raise TypeError(msg)
    raw_schema = cast("dict[str, object]", raw_schema_value)
    Draft202012Validator.check_schema(raw_schema)
    draft_issues = tuple(Draft202012Validator(raw_schema).iter_errors(output))
    report = validate_data(output, raw_schema)
    schema_issues = max(len(report.issues), len(draft_issues))
    schema_valid = report.valid and not draft_issues and schema_issues == 0
    schema_gate = GateOutcome(
        passed=schema_valid,
        failure_codes=() if schema_valid else (FailureCode.SCHEMA,),
        evidence=GateEvidence(
            issue_count=schema_issues,
            checked_count=schema_issues,
            evidence_sha256=_sha256(str(schema_issues)),
        ),
    )
    fidelity_gate = evaluate_source_fidelity(output, fixture)

    template_path = get_repo_root() / fixture.template_identifier
    lint_config = load_lint_config(template_path)
    if lint_config is None:
        msg = "Shipped document lint configuration is required"
        raise ValueError(msg)
    content_issues = list(LintEngine().evaluate(output, lint_config).issues)
    coverage_evidence = _issue_evidence(content_issues)
    coverage_gate = GateOutcome(
        passed=coverage_evidence.issue_count == 0,
        failure_codes=() if coverage_evidence.issue_count == 0 else (FailureCode.COVERAGE,),
        evidence=coverage_evidence,
    )

    if not schema_gate.passed:
        return DocumentContractEvaluation(
            gate_outcomes={
                GateName.SCHEMA: schema_gate,
                GateName.SOURCE_FIDELITY: fidelity_gate,
                GateName.COVERAGE: coverage_gate,
            },
            artifact=None,
            output_sha256=output_sha256,
        )

    template = template_path.read_text(encoding="utf-8")
    html = await render_template(template, output)
    pdf = await GotenbergService(base_url=gotenberg_url).convert_html_to_pdf(html)
    if not pdf.startswith(b"%PDF-") or not pdf:
        msg = "Renderer did not return a non-empty PDF"
        raise ValueError(msg)
    pdf_sha256 = _sha256(pdf)
    if not _SHA256_RE.fullmatch(pdf_sha256):
        msg = "PDF digest is invalid"
        raise ValueError(msg)
    layout = PdfPlumberLayoutExtractor().extract(pdf, output)
    layout_issues = (
        run_layout_lint(lint_config.layout.rules, layout, data=output) if lint_config.layout is not None else []
    )
    layout_evidence = _issue_evidence(layout_issues)
    with pdfplumber.open(io.BytesIO(pdf)) as parsed:
        text = "\n".join(page.extract_text() or "" for page in parsed.pages)
    artifact, artifact_gate = _build_artifact_evidence(
        pdf,
        pdf_sha256,
        layout.page_count,
        text,
        layout_evidence,
        fixture.ledger.rendered_literals,
    )
    return DocumentContractEvaluation(
        gate_outcomes={
            GateName.SCHEMA: schema_gate,
            GateName.SOURCE_FIDELITY: fidelity_gate,
            GateName.COVERAGE: coverage_gate,
            GateName.ARTIFACT: artifact_gate,
        },
        artifact=artifact,
        output_sha256=output_sha256,
    )


def redact_for_evidence(value: object, fixture: DocumentQualificationFixture) -> object:
    """Recursively redact contacts, URLs, long identifiers, and fixture facts."""
    fixture_values = tuple(
        item.value
        for item in (
            *fixture.ledger.locked_paths,
            *fixture.ledger.required_atoms,
            *fixture.ledger.allowed_atoms,
            *fixture.ledger.forbidden_atoms,
        )
    )

    def redact_text(text: str) -> str:
        redacted = text
        for literal in sorted(fixture_values, key=len, reverse=True):
            if literal:
                redacted = re.sub(re.escape(literal), "<redacted>", redacted, flags=re.IGNORECASE)
        for pattern in (_EMAIL_RE, _URL_RE, _PHONE_RE, _LONG_IDENTIFIER_RE):
            redacted = pattern.sub("<redacted>", redacted)
        return redacted

    match value:
        case str():
            return redact_text(value)
        case dict():
            return {redact_text(str(key)): redact_for_evidence(child, fixture) for key, child in value.items()}
        case list():
            return [redact_for_evidence(child, fixture) for child in value]
        case tuple():
            return tuple(redact_for_evidence(child, fixture) for child in value)
        case _:
            return value


class _DefaultDocumentClient(LLMClient):
    async def generate_document(
        self,
        config: DynamicAgentConfig[DocumentContentContext],
        prompt: str,
        /,
        *,
        deps: DocumentContentContext,
    ) -> LLMResult[dict[str, object]]:
        agent = self.create_dynamic_schema_agent(config)
        return await self.run(agent, prompt, deps=deps)


def _default_client_factory(settings: LLMSettings) -> DocumentClient:
    return _DefaultDocumentClient(settings)


def _pricing_source(
    snapshot: PricingSnapshot,
) -> Literal["genai_prices", "provider", "owner_bound", "free"]:
    if snapshot.source == "local":
        return "free"
    if snapshot.source == "openrouter_endpoint":
        return "provider"
    if snapshot.source == "unknown":
        return "owner_bound"
    return "genai_prices"


def _failure_gate(code: FailureCode) -> GateOutcome:
    return GateOutcome(passed=False, failure_codes=(code,), evidence=GateEvidence(issue_count=1))


def _passing_gate(**evidence: object) -> GateOutcome:
    return GateOutcome(passed=True, evidence=GateEvidence.model_validate(evidence))


def _safe_exception(error: BaseException) -> tuple[FailureCode, str]:
    name = type(error).__name__
    if isinstance(error, (TimeoutError, asyncio.TimeoutError)) or "Timeout" in name:
        return FailureCode.TIMEOUT, name
    if "Validation" in name:
        return FailureCode.VALIDATION, name
    if "Gotenberg" in name or "Render" in name or "Template" in name:
        return FailureCode.RENDER, name
    if "Layout" in name or "PDF" in name or "Pdf" in name:
        return FailureCode.LAYOUT, name
    if "Provider" in name or "LLM" in name or "Model" in name:
        return FailureCode.PROVIDER_RESPONSE, name
    return FailureCode.INTERNAL, name


class DocumentQualificationRunner:
    """Run exact resumable qualification cells with fail-closed budget accounting."""

    def __init__(
        self,
        *,
        llm_settings: LLMSettings,
        chain_name: str,
        fixtures: tuple[DocumentQualificationFixture, ...] = DOCUMENT_FIXTURES,
        cost_cap_usd: float,
        unknown_price_max_usd: float | None,
        gotenberg_url: str,
        evidence_environment: Literal["production", "test"] = "production",
        client_factory: ClientFactory | None = None,
        renderer: DocumentRenderer | None = None,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        """Validate configuration and freeze all dependencies before dispatch."""
        if chain_name not in llm_settings.chains:
            msg = "Qualification requires an explicitly named LLM chain"
            raise ValueError(msg)
        if cost_cap_usd <= 0:
            msg = "Owner-approved cost cap must be positive"
            raise ValueError(msg)
        render_endpoint = urlsplit(gotenberg_url.strip())
        if (
            render_endpoint.scheme not in {"http", "https"}
            or not render_endpoint.hostname
            or render_endpoint.username is not None
            or render_endpoint.password is not None
            or render_endpoint.query
            or render_endpoint.fragment
        ):
            msg = "Gotenberg URL must be an HTTP(S) endpoint without credentials, query, or fragment"
            raise ValueError(msg)
        custom_seam = client_factory is not None or renderer is not None or monotonic is not time.monotonic
        if custom_seam and evidence_environment != "test":
            msg = "Injected qualification seams require test evidence"
            raise ValueError(msg)
        self._settings = llm_settings
        self._chain_name = chain_name
        self._provider = llm_settings.chains[chain_name]
        self._fixtures = fixtures
        self._cost_cap_usd = cost_cap_usd
        self._unknown_price_max_usd = unknown_price_max_usd
        self._gotenberg_url = gotenberg_url
        self._evidence_environment = evidence_environment
        self._client_factory = client_factory or _default_client_factory
        self._uses_default_renderer = renderer is None
        self._renderer = renderer or self._render
        self._monotonic = monotonic
        self._routes = validate_approved_document_chain(
            tuple(self._provider.models),
            self._provider,
            instrumentation_enabled=llm_settings.instrumentation.enabled,
        )
        self._pricing: dict[str, PricingSnapshot] = {
            route.approved.alias: resolve_pricing_snapshot(route.model_config) for route in self._routes
        }
        for snapshot in self._pricing.values():
            snapshot.maximum_call_cost(
                max_input_tokens=1,
                max_output_tokens=cast("int", self._provider.max_tokens),
                unknown_price_max_usd=self._unknown_price_max_usd,
            )

    async def _render(
        self,
        output: dict[str, object],
        fixture: DocumentQualificationFixture,
        gotenberg_url: str,
    ) -> DocumentContractEvaluation:
        return await evaluate_document_contracts(output, fixture, gotenberg_url=gotenberg_url)

    async def _run_preflight(
        self,
        *,
        selected_routes: tuple[str, ...],
        selected_fixtures: tuple[str, ...],
        runs: int,
    ) -> None:
        """Validate shipped contracts, reservation, and Gotenberg without dispatch."""
        import httpx
        import tailor
        from jsonschema import Draft202012Validator
        from tailor.lint.config import load_lint_config

        del tailor
        fixture_by_id = {fixture.fixture_id: fixture for fixture in self._fixtures}
        for fixture in self._fixtures:
            raw_schema = json.loads((get_repo_root() / fixture.schema_identifier).read_text(encoding="utf-8"))
            Draft202012Validator.check_schema(raw_schema)
            (get_repo_root() / fixture.template_identifier).read_bytes()
            if load_lint_config(get_repo_root() / fixture.template_identifier) is None:
                msg = "Shipped document lint configuration is required"
                raise ValueError(msg)
            fixture.build_context()
            compute_document_fixture_checksum(fixture)

        total_reservation = sum(
            self._maximum_cost(route, fixture_by_id[fixture_id]) * runs
            for route in self._routes
            if route.approved.alias in selected_routes
            for fixture_id in selected_fixtures
        )
        if total_reservation > self._cost_cap_usd:
            msg = "Selected qualification cells exceed the owner-approved cost cap"
            raise BudgetExhaustedError(msg)
        if self._uses_default_renderer:
            health_url = f"{self._gotenberg_url.rstrip('/')}/health"
            async with httpx.AsyncClient(timeout=2.0) as client:
                response = await client.get(health_url)
            if response.status_code != 200:
                msg = "Gotenberg health check failed"
                raise RuntimeError(msg)

    def _maximum_cost(self, route: ValidatedDocumentRoute, fixture: DocumentQualificationFixture) -> float:
        context = fixture.build_context()
        prompt_bytes = len(build_system_prompt(context).encode()) + len(build_user_prompt(context).encode())
        retry_multiplier = _APPLICATION_ATTEMPTS * (self._provider.max_tool_retries + 1)
        return self._pricing[route.approved.alias].maximum_call_cost(
            max_input_tokens=prompt_bytes * retry_multiplier,
            max_output_tokens=cast("int", self._provider.max_tokens) * retry_multiplier,
            unknown_price_max_usd=self._unknown_price_max_usd,
        )

    def _single_model_settings(self, route: ValidatedDocumentRoute) -> LLMSettings:
        provider = self._provider.model_copy(update={"models": [route.model_config]})
        return self._settings.model_copy(update={"provider": provider, "chains": {}})

    def _identity(self, route: ValidatedDocumentRoute) -> SafeRouteIdentity:
        snapshot = self._pricing[route.approved.alias]
        maximum = max(self._maximum_cost(route, fixture) for fixture in self._fixtures)
        pricing_fingerprint = _sha256(_canonical_json(snapshot.fingerprint_material()))
        return SafeRouteIdentity(
            route_alias=route.approved.alias,
            treatment_id=route.treatment_id,
            treatment_fingerprint=route.treatment_fingerprint,
            configured_model=route.approved.model,
            reasoning_effort=route.approved.reasoning_effort,
            endpoint_class=route.approved.endpoint_class,
            endpoint_sha256=route.endpoint_sha256,
            provider_order=route.approved.provider_order,
            allow_fallbacks=route.approved.allow_fallbacks,
            zdr=route.approved.zdr,
            pricing=PricingEvidence(
                pricing_fingerprint=pricing_fingerprint,
                source=_pricing_source(snapshot),
                input_per_million_usd=snapshot.input_per_million_usd,
                output_per_million_usd=snapshot.output_per_million_usd,
                maximum_call_cost_usd=maximum,
            ),
        )

    def _configuration_fingerprint(self, runs: int) -> str:
        """Hash non-corpus execution policy used to reject unsafe resume drift."""
        return _sha256(
            _canonical_json(
                {
                    "routes": [route.treatment_fingerprint for route in self._routes],
                    "pricing": {alias: self._pricing[alias].fingerprint_material() for alias in APPROVED_ROUTE_ALIASES},
                    "temperature": self._provider.temperature,
                    "max_tokens": self._provider.max_tokens,
                    "timeout_seconds": self._provider.timeout_seconds,
                    "max_tool_retries": self._provider.max_tool_retries,
                    "concurrency_limit": self._provider.concurrency_limit,
                    "cost_cap_usd": self._cost_cap_usd,
                    "unknown_price_max_usd": self._unknown_price_max_usd,
                    "runs": runs,
                    "generation_timeout_seconds": GENERATION_TIMEOUT_SECONDS,
                    "cell_timeout_seconds": CELL_TIMEOUT_SECONDS,
                    "environment": self._evidence_environment,
                }
            )
        )

    def _rebase_fixture_drift(
        self,
        existing: DocumentQualificationResult,
        expected: DocumentQualificationResult,
    ) -> DocumentQualificationResult:
        """Rebase only changed fixture cells while rejecting all policy drift."""
        stable_fields = (
            "contract_version",
            "policy_fingerprint",
            "route_fingerprint",
            "config_fingerprint",
            "expected_routes",
            "runs_per_fixture",
            "deadline_seconds",
            "evidence_environment",
        )
        mismatched = [field for field in stable_fields if getattr(existing, field) != getattr(expected, field)]
        if mismatched:
            msg = f"Cannot resume qualification with changed non-corpus identity: {mismatched}"
            raise ValueError(msg)
        cleaned, _ = existing.strip_stale_fixture_results(list(expected.fixture_checksums), expected.fixture_checksums)
        current_by_treatment = {route.treatment_id: self._identity(route) for route in self._routes}
        rebased_routes: dict[str, RouteQualification] = {}
        for treatment_id, stored in cleaned.routes.items():
            current_identity = current_by_treatment.get(treatment_id)
            if current_identity is None:
                msg = "Stored qualification route is no longer approved"
                raise ValueError(msg)
            stored_material = stored.identity.model_dump(exclude={"returned_model", "downstream_provider"})
            current_material = current_identity.model_dump(exclude={"returned_model", "downstream_provider"})
            stored_material["pricing"]["maximum_call_cost_usd"] = current_material["pricing"]["maximum_call_cost_usd"]
            if stored_material != current_material:
                msg = "Stored qualification route or pricing identity changed"
                raise ValueError(msg)
            identity = current_identity.model_copy(
                update={
                    "returned_model": stored.identity.returned_model,
                    "downstream_provider": stored.identity.downstream_provider,
                }
            )
            rebased_routes[treatment_id] = RouteQualification.model_validate(
                stored.model_copy(update={"identity": identity}).model_dump()
            )
        return DocumentQualificationResult.model_validate(
            cleaned.model_copy(
                update={
                    "experiment_fingerprint": expected.experiment_fingerprint,
                    "corpus_fingerprint": expected.corpus_fingerprint,
                    "config_fingerprint": expected.config_fingerprint,
                    "fixture_checksums": expected.fixture_checksums,
                    "routes": rebased_routes,
                }
            ).model_dump()
        )

    def _new_result(self, runs: int, *, preflight: bool) -> DocumentQualificationResult:
        checksums = {fixture.fixture_id: compute_document_fixture_checksum(fixture) for fixture in self._fixtures}
        experiment = document_experiment_fingerprint(
            routes=self._routes,
            fixtures=self._fixtures,
            pricing=self._pricing,
            settings=self._provider,
            runs=runs,
            cost_cap_usd=self._cost_cap_usd,
            unknown_price_max_usd=self._unknown_price_max_usd,
        )
        policy = _sha256(DOCUMENT_POLICY_VERSION)
        corpus = _sha256(_canonical_json(checksums))
        route_fp = _sha256(_canonical_json([route.treatment_fingerprint for route in self._routes]))
        config_fp = self._configuration_fingerprint(runs)
        return DocumentQualificationResult(
            contract_version=DOCUMENT_POLICY_VERSION,
            experiment_fingerprint=experiment,
            policy_fingerprint=policy,
            corpus_fingerprint=corpus,
            route_fingerprint=route_fp,
            config_fingerprint=config_fp,
            expected_routes=APPROVED_ROUTE_ALIASES,
            fixture_checksums=checksums,
            runs_per_fixture=runs,
            evidence_environment=self._evidence_environment,
            preflight=preflight,
        )

    async def run(
        self,
        *,
        selected_routes: tuple[str, ...] = APPROVED_ROUTE_ALIASES,
        selected_fixtures: tuple[str, ...] = (),
        runs: int = 1,
        output_path: Path,
        existing: DocumentQualificationResult | None = None,
        preflight: bool = False,
    ) -> DocumentQualificationResult:
        """Dispatch pending exact cells and atomically persist every attempt."""
        if runs < 1:
            msg = "runs must be positive"
            raise ValueError(msg)
        unknown_routes = set(selected_routes) - set(APPROVED_ROUTE_ALIASES)
        if not selected_routes or unknown_routes or len(set(selected_routes)) != len(selected_routes):
            msg = "Selected routes must be unique approved aliases"
            raise ValueError(msg)
        fixture_by_id = {fixture.fixture_id: fixture for fixture in self._fixtures}
        fixture_ids = selected_fixtures or tuple(fixture_by_id)
        if set(fixture_ids) - set(fixture_by_id) or len(set(fixture_ids)) != len(fixture_ids):
            msg = "Selected fixtures must be unique registered fixture IDs"
            raise ValueError(msg)

        expected = self._new_result(runs, preflight=preflight)
        if existing is not None:
            if preflight:
                msg = "Preflight cannot resume a dispatched artifact"
                raise ValueError(msg)
            rebased = self._rebase_fixture_drift(existing, expected)
            expected = expected.merge(rebased)
        if preflight:
            await self._run_preflight(
                selected_routes=selected_routes,
                selected_fixtures=fixture_ids,
                runs=runs,
            )
            expected.save(output_path)
            return expected

        return await self._dispatch_cells(
            expected,
            selected_routes=selected_routes,
            fixture_ids=fixture_ids,
            fixture_by_id=fixture_by_id,
            runs=runs,
            output_path=output_path,
        )

    async def _dispatch_cells(
        self,
        current: DocumentQualificationResult,
        *,
        selected_routes: tuple[str, ...],
        fixture_ids: tuple[str, ...],
        fixture_by_id: dict[str, DocumentQualificationFixture],
        runs: int,
        output_path: Path,
    ) -> DocumentQualificationResult:
        scheduler = BudgetScheduler(
            cap_usd=self._cost_cap_usd,
            max_concurrency=self._provider.concurrency_limit or 1,
            initial_charged_usd=current.charged_cost_usd,
            initial_actual_usd=current.actual_cost_usd,
        )
        completed = current.completed_cell_keys()
        for route in self._routes:
            if route.approved.alias not in selected_routes:
                continue
            current, exhausted = await self._run_route_cells(
                current,
                scheduler=scheduler,
                route=route,
                fixture_ids=fixture_ids,
                fixture_by_id=fixture_by_id,
                completed=completed,
                runs=runs,
                output_path=output_path,
            )
            if exhausted:
                break
            completed = current.completed_cell_keys()
        return current

    async def _run_route_cells(
        self,
        current: DocumentQualificationResult,
        *,
        scheduler: BudgetScheduler,
        route: ValidatedDocumentRoute,
        fixture_ids: tuple[str, ...],
        fixture_by_id: dict[str, DocumentQualificationFixture],
        completed: frozenset[tuple[str, str, int]],
        runs: int,
        output_path: Path,
    ) -> tuple[DocumentQualificationResult, bool]:
        stored_route = current.routes.get(route.treatment_id)
        identity = stored_route.identity if stored_route is not None else self._identity(route)
        cases = list(stored_route.cases) if stored_route is not None else []
        for fixture_id in fixture_ids:
            fixture = fixture_by_id[fixture_id]
            for run_number in range(1, runs + 1):
                key = (route.treatment_id, fixture_id, run_number)
                if key in completed:
                    continue
                maximum = self._maximum_cost(route, fixture)
                before = scheduler.snapshot
                try:
                    case, returned_model, downstream_provider = await self._run_cell(
                        scheduler,
                        route=route,
                        fixture=fixture,
                        run_number=run_number,
                        maximum=maximum,
                        config_fingerprint=current.config_fingerprint,
                    )
                except BudgetExhaustedError:
                    return current, True
                except Exception as error:
                    case = self._failed_case(
                        error,
                        scheduler=scheduler,
                        before_charged_usd=before.charged_usd,
                        route=route,
                        fixture=fixture,
                        run_number=run_number,
                        maximum=maximum,
                        config_fingerprint=current.config_fingerprint,
                    )
                    returned_model = None
                    downstream_provider = None
                except BaseException as error:
                    case = self._failed_case(
                        error,
                        scheduler=scheduler,
                        before_charged_usd=before.charged_usd,
                        route=route,
                        fixture=fixture,
                        run_number=run_number,
                        maximum=maximum,
                        config_fingerprint=current.config_fingerprint,
                    )
                    current = self._persist_case(
                        current,
                        route=route,
                        identity=identity,
                        cases=[*cases, case],
                        runs=runs,
                        output_path=output_path,
                    )
                    raise
                if returned_model is not None:
                    identity = identity.model_copy(
                        update={
                            "returned_model": returned_model,
                            "downstream_provider": downstream_provider,
                        }
                    )
                cases.append(case)
                current = self._persist_case(
                    current,
                    route=route,
                    identity=identity,
                    cases=cases,
                    runs=runs,
                    output_path=output_path,
                )
                completed = current.completed_cell_keys()
        return current, False

    async def _run_cell(
        self,
        scheduler: BudgetScheduler,
        *,
        route: ValidatedDocumentRoute,
        fixture: DocumentQualificationFixture,
        run_number: int,
        maximum: float,
        config_fingerprint: str,
    ) -> tuple[DocumentCaseResult, str | None, str | None]:
        return await scheduler.run(
            maximum,
            lambda: self._execute_cell(
                route,
                fixture,
                run_number,
                maximum,
                config_fingerprint,
            ),
        )

    def _failed_case(
        self,
        error: BaseException,
        *,
        scheduler: BudgetScheduler,
        before_charged_usd: float,
        route: ValidatedDocumentRoute,
        fixture: DocumentQualificationFixture,
        run_number: int,
        maximum: float,
        config_fingerprint: str,
    ) -> DocumentCaseResult:
        code, exception_type = _safe_exception(error)
        gates = {gate: _failure_gate(code) for gate in GateName}
        return DocumentCaseResult(
            treatment_id=route.treatment_id,
            fixture_id=fixture.fixture_id,
            fixture_checksum=compute_document_fixture_checksum(fixture),
            run_number=run_number,
            cell_fingerprint=self._cell_fingerprint(route, fixture, run_number, config_fingerprint),
            gate_outcomes=gates,
            telemetry=CaseTelemetry(
                latency_ms=0,
                cell_latency_ms=0,
                reserved_cost_usd=maximum,
                charged_cost_usd=scheduler.snapshot.charged_usd - before_charged_usd,
            ),
            safe_error=SafeError(code=code, exception_type=exception_type),
        )

    @staticmethod
    def _persist_case(
        current: DocumentQualificationResult,
        *,
        route: ValidatedDocumentRoute,
        identity: SafeRouteIdentity,
        cases: list[DocumentCaseResult],
        runs: int,
        output_path: Path,
    ) -> DocumentQualificationResult:
        route_result = RouteQualification(
            identity=identity,
            expected_fixture_checksums=current.fixture_checksums,
            runs_per_fixture=runs,
            cases=cases,
        )
        routes = dict(current.routes)
        routes[route.treatment_id] = route_result
        updated = DocumentQualificationResult.model_validate(current.model_copy(update={"routes": routes}).model_dump())
        updated.save(output_path)
        return updated

    def _cell_fingerprint(
        self,
        route: ValidatedDocumentRoute,
        fixture: DocumentQualificationFixture,
        run_number: int,
        config_fingerprint: str,
    ) -> str:
        return _sha256(
            _canonical_json(
                {
                    "config": config_fingerprint,
                    "treatment": route.treatment_fingerprint,
                    "fixture": compute_document_fixture_checksum(fixture),
                    "run": run_number,
                }
            )
        )

    async def _execute_cell(
        self,
        route: ValidatedDocumentRoute,
        fixture: DocumentQualificationFixture,
        run_number: int,
        maximum_cost_usd: float,
        config_fingerprint: str,
    ) -> tuple[tuple[DocumentCaseResult, str | None, str | None], float | None]:
        started = self._monotonic()
        context = fixture.build_context()
        client = self._client_factory(self._single_model_settings(route))
        config = DynamicAgentConfig(
            deps_type=DocumentContentContext,
            json_schema=context.schema_definition,
            schema_name=context.schema_name,
            schema_description=f"Generated document matching {context.schema_name} schema",
            system_prompt_fn=lambda run_context: build_system_prompt(run_context.deps),
        )
        async with asyncio.timeout(CELL_TIMEOUT_SECONDS):
            generation_started = self._monotonic()
            async with asyncio.timeout(GENERATION_TIMEOUT_SECONDS):
                llm_result = await client.generate_document(
                    config,
                    build_user_prompt(context),
                    deps=context,
                )
            generation_ms = (self._monotonic() - generation_started) * 1000
            contracts = await self._renderer(llm_result.output, fixture, self._gotenberg_url)
        cell_ms = (self._monotonic() - started) * 1000
        usage = llm_result.usage
        input_tokens = usage.input_tokens or 0
        output_tokens = usage.output_tokens or 0
        request_count = usage.requests
        actual_cost = self._pricing[route.approved.alias].recorded_cost(
            client_cost=llm_result.cost_usd,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )
        route_ok = (
            llm_result.model_used == route.approved.model
            and request_count > 0
            and (route.approved.alias != "kimi" or llm_result.downstream_provider == "SiliconFlow")
        )
        gates = dict(contracts.gate_outcomes)
        gates[GateName.ROUTE_IDENTITY] = GateOutcome(
            passed=route_ok,
            failure_codes=() if route_ok else (FailureCode.ROUTE_IDENTITY,),
            evidence=GateEvidence(
                request_count=request_count,
                checked_count=2 if route.approved.alias == "kimi" else 1,
            ),
        )
        gates[GateName.LATENCY] = GateOutcome(
            passed=generation_ms <= GENERATION_TIMEOUT_SECONDS * 1000 and cell_ms <= CELL_TIMEOUT_SECONDS * 1000,
            failure_codes=()
            if generation_ms <= GENERATION_TIMEOUT_SECONDS * 1000 and cell_ms <= CELL_TIMEOUT_SECONDS * 1000
            else (FailureCode.TIMEOUT,),
            evidence=GateEvidence(duration_ms=cell_ms, deadline_seconds=CELL_TIMEOUT_SECONDS),
        )
        cost_ok = actual_cost is None or 0 <= actual_cost <= maximum_cost_usd
        gates[GateName.COST] = GateOutcome(
            passed=cost_ok,
            failure_codes=() if cost_ok else (FailureCode.COST,),
            evidence=GateEvidence(checked_count=1),
        )
        gates[GateName.DIAGNOSTICS] = _passing_gate(checked_count=1)
        for gate in GateName:
            gates.setdefault(gate, _failure_gate(FailureCode.INTERNAL))
        all_passed = all(gate.passed for gate in gates.values())
        charged_cost = actual_cost if all_passed and actual_cost is not None else maximum_cost_usd
        safe_error = None
        if not all_passed:
            first_code = next(code for gate in GateName for code in gates[gate].failure_codes)
            safe_error = SafeError(code=first_code)
        case = DocumentCaseResult(
            treatment_id=route.treatment_id,
            fixture_id=fixture.fixture_id,
            fixture_checksum=compute_document_fixture_checksum(fixture),
            run_number=run_number,
            cell_fingerprint=self._cell_fingerprint(route, fixture, run_number, config_fingerprint),
            gate_outcomes=gates,
            telemetry=CaseTelemetry(
                latency_ms=generation_ms,
                cell_latency_ms=cell_ms,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                request_count=request_count,
                retry_count=llm_result.retry_count,
                actual_cost_usd=actual_cost,
                reserved_cost_usd=maximum_cost_usd,
                charged_cost_usd=charged_cost,
            ),
            output_sha256=contracts.output_sha256,
            artifact=contracts.artifact,
            safe_error=safe_error,
        )
        return (
            case,
            llm_result.model_used,
            llm_result.downstream_provider,
        ), actual_cost if all_passed else None
