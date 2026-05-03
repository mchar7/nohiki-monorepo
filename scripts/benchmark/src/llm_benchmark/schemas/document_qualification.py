"""Safe, resumable evidence models for document-model qualification."""

from datetime import UTC, datetime
from enum import StrEnum
from math import isclose
from pathlib import Path
from typing import Annotated, Literal, Self

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

from llm_benchmark.persistence import atomic_write_json

SCHEMA_VERSION = "document-qualification-v1"
APPROVED_ROUTE_ALIASES = ("sol", "opus", "kimi")


type Sha256 = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
type SafeIdentifier = Annotated[str, Field(min_length=1, max_length=160, pattern=r"^[A-Za-z0-9_.:/-]+$")]
type NonNegativeFloat = Annotated[float, Field(ge=0, allow_inf_nan=False)]
type PositiveFloat = Annotated[float, Field(gt=0, allow_inf_nan=False)]
type NonNegativeInt = Annotated[int, Field(ge=0)]
type PositiveInt = Annotated[int, Field(gt=0)]


class QualificationModel(BaseModel):
    """Base configuration shared by all persisted qualification records."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    schema_version: Literal["document-qualification-v1"] = SCHEMA_VERSION


class GateName(StrEnum):
    """Deterministic gates required for every dispatched document cell."""

    ROUTE_IDENTITY = "route_identity"
    SCHEMA = "schema"
    SOURCE_FIDELITY = "source_fidelity"
    COVERAGE = "coverage"
    ARTIFACT = "artifact"
    LATENCY = "latency"
    COST = "cost"
    DIAGNOSTICS = "diagnostics"


class FailureCode(StrEnum):
    """Closed, non-sensitive failure vocabulary persisted in evidence."""

    TIMEOUT = "timeout"
    PROVIDER_RESPONSE = "provider_response"
    VALIDATION = "validation"
    SCHEMA = "schema"
    FIDELITY = "fidelity"
    COVERAGE = "coverage"
    RENDER = "render"
    LAYOUT = "layout"
    ARTIFACT = "artifact"
    ROUTE_IDENTITY = "route_identity"
    COST = "cost"
    BUDGET = "budget"
    UNSAFE_EVIDENCE = "unsafe_evidence"
    INTERNAL = "internal"


class GateEvidence(QualificationModel):
    """Bounded scalar/count/hash evidence with no free-form content."""

    issue_count: NonNegativeInt = 0
    warning_count: NonNegativeInt = 0
    info_count: NonNegativeInt = 0
    missing_count: NonNegativeInt = 0
    unsupported_count: NonNegativeInt = 0
    changed_count: NonNegativeInt = 0
    request_count: NonNegativeInt = 0
    checked_count: NonNegativeInt = 0
    duration_ms: NonNegativeFloat | None = None
    deadline_seconds: PositiveFloat | None = None
    evidence_sha256: Sha256 | None = None


class GateOutcome(QualificationModel):
    """Outcome of one deterministic gate without raw diagnostic text."""

    passed: bool
    failure_codes: tuple[FailureCode, ...] = ()
    evidence: GateEvidence = Field(default_factory=GateEvidence)

    @model_validator(mode="after")
    def validate_outcome(self) -> Self:
        """Require failures to carry codes and passing gates to carry none."""
        if self.passed and self.failure_codes:
            msg = "A passing gate cannot contain failure codes"
            raise ValueError(msg)
        if not self.passed and not self.failure_codes:
            msg = "A failed gate must contain at least one failure code"
            raise ValueError(msg)
        if len(set(self.failure_codes)) != len(self.failure_codes):
            msg = "Gate failure codes must be unique"
            raise ValueError(msg)
        return self


class PricingEvidence(QualificationModel):
    """Immutable, non-secret pricing material used for admission and charging."""

    pricing_fingerprint: Sha256
    source: Literal["genai_prices", "provider", "owner_bound", "free"]
    input_per_million_usd: NonNegativeFloat | None = None
    output_per_million_usd: NonNegativeFloat | None = None
    maximum_call_cost_usd: NonNegativeFloat


class SafeRouteIdentity(QualificationModel):
    """Route identity containing hashes and approved routing scalars only."""

    route_alias: SafeIdentifier
    treatment_id: SafeIdentifier
    treatment_fingerprint: Sha256
    configured_model: SafeIdentifier
    returned_model: SafeIdentifier | None = None
    reasoning_effort: Literal["medium", "high"]
    endpoint_class: Literal["proxy", "public_openrouter"]
    endpoint_sha256: Sha256
    provider_order: tuple[SafeIdentifier, ...] = ()
    allow_fallbacks: bool
    zdr: bool
    downstream_provider: SafeIdentifier | None = None
    pricing: PricingEvidence


class ArtifactEvidence(QualificationModel):
    """Metadata proving a PDF artifact without retaining the PDF or its text."""

    content_type: Literal["application/pdf"] = "application/pdf"
    size_bytes: PositiveInt
    sha256: Sha256
    page_count: PositiveInt
    text_sha256: Sha256
    required_literals_checked: PositiveInt
    required_literals_present: NonNegativeInt

    @model_validator(mode="after")
    def validate_literal_counts(self) -> Self:
        """Reject impossible required-literal evidence."""
        if self.required_literals_present > self.required_literals_checked:
            msg = "Required literals present cannot exceed literals checked"
            raise ValueError(msg)
        return self


class CaseTelemetry(QualificationModel):
    """Typed request, latency, token, retry, and budget telemetry."""

    latency_ms: NonNegativeFloat
    cell_latency_ms: NonNegativeFloat
    input_tokens: NonNegativeInt = 0
    output_tokens: NonNegativeInt = 0
    request_count: NonNegativeInt = 0
    retry_count: NonNegativeInt | None = None
    actual_cost_usd: NonNegativeFloat | None = None
    reserved_cost_usd: NonNegativeFloat
    charged_cost_usd: NonNegativeFloat

    @model_validator(mode="after")
    def validate_charge(self) -> Self:
        """Allow only a known actual charge or the fail-closed reservation."""
        permitted = [self.reserved_cost_usd]
        if self.actual_cost_usd is not None:
            permitted.append(self.actual_cost_usd)
        if not any(isclose(self.charged_cost_usd, value, rel_tol=1e-12, abs_tol=1e-12) for value in permitted):
            msg = "Charged cost must equal known actual cost or reserved cost"
            raise ValueError(msg)
        return self


class SafeError(QualificationModel):
    """Closed error code plus an exception class name, never an exception body."""

    code: FailureCode
    exception_type: (
        Annotated[
            str,
            Field(min_length=1, max_length=120, pattern=r"^[A-Za-z_][A-Za-z0-9_.]*$"),
        ]
        | None
    ) = None


class DocumentCaseResult(QualificationModel):
    """One dispatched treatment/fixture/run result and its safe evidence."""

    treatment_id: SafeIdentifier
    fixture_id: SafeIdentifier
    fixture_checksum: Sha256
    run_number: PositiveInt
    cell_fingerprint: Sha256
    attempted: Literal[True] = True
    gate_outcomes: dict[GateName, GateOutcome]
    telemetry: CaseTelemetry
    output_sha256: Sha256 | None = None
    artifact: ArtifactEvidence | None = None
    safe_error: SafeError | None = None
    updated_at: AwareDatetime = Field(default_factory=lambda: datetime.now(UTC))

    @model_validator(mode="after")
    def validate_gates(self) -> Self:
        """Require the exact deterministic gate set and coherent safe failure data."""
        expected = set(GateName)
        actual = set(self.gate_outcomes)
        if actual != expected:
            missing = sorted(gate.value for gate in expected - actual)
            extra = sorted(gate.value for gate in actual - expected)
            msg = f"Gate outcomes must be exact; missing={missing}, extra={extra}"
            raise ValueError(msg)
        all_passed = all(outcome.passed for outcome in self.gate_outcomes.values())
        if all_passed and self.safe_error is not None:
            msg = "A passing cell cannot contain a safe error"
            raise ValueError(msg)
        if not all_passed and self.safe_error is None:
            msg = "A failed cell must contain a safe error"
            raise ValueError(msg)
        failed_codes = {
            code for outcome in self.gate_outcomes.values() if not outcome.passed for code in outcome.failure_codes
        }
        if self.safe_error is not None and self.safe_error.code not in failed_codes:
            msg = "Safe error code must occur in a failed gate"
            raise ValueError(msg)
        if all_passed and (self.output_sha256 is None or self.artifact is None):
            msg = "A passing cell requires output and artifact evidence"
            raise ValueError(msg)
        expected_charge = (
            self.telemetry.actual_cost_usd
            if all_passed and self.telemetry.actual_cost_usd is not None
            else self.telemetry.reserved_cost_usd
        )
        if not isclose(
            self.telemetry.charged_cost_usd,
            expected_charge,
            rel_tol=1e-12,
            abs_tol=1e-12,
        ):
            msg = "Passing known-cost cells charge actual cost; failures and unknown costs charge reservation"
            raise ValueError(msg)
        return self

    @property
    def cell_key(self) -> tuple[str, str, int]:
        """Exact resumable unit key: treatment, fixture, and 1-indexed run."""
        return (self.treatment_id, self.fixture_id, self.run_number)

    @property
    def passed(self) -> bool:
        """Whether every deterministic gate passed."""
        return all(outcome.passed for outcome in self.gate_outcomes.values())


class RouteQualification(QualificationModel):
    """All expected document cases for one independently dispatched route."""

    identity: SafeRouteIdentity
    expected_fixture_checksums: dict[SafeIdentifier, Sha256]
    runs_per_fixture: PositiveInt
    cases: list[DocumentCaseResult] = Field(default_factory=list)
    status: Literal["incomplete", "route_qualified", "failed"] = "incomplete"

    @model_validator(mode="after")
    def compute_status(self) -> Self:
        """Compute route status from exact expected coverage and all gates."""
        if not self.expected_fixture_checksums:
            msg = "Route fixture expectations must be non-empty"
            raise ValueError(msg)
        seen: set[tuple[str, str, int]] = set()
        for case in self.cases:
            if case.treatment_id != self.identity.treatment_id:
                msg = "Case treatment does not match route identity"
                raise ValueError(msg)
            if case.fixture_id not in self.expected_fixture_checksums:
                msg = "Route contains a case for an unexpected fixture"
                raise ValueError(msg)
            if case.fixture_checksum != self.expected_fixture_checksums[case.fixture_id]:
                msg = "Case fixture checksum does not match route expectation"
                raise ValueError(msg)
            if case.run_number > self.runs_per_fixture:
                msg = "Case run number exceeds the route run count"
                raise ValueError(msg)
            if case.cell_key in seen:
                msg = "Route contains duplicate exact cells"
                raise ValueError(msg)
            seen.add(case.cell_key)

        expected = {
            (self.identity.treatment_id, fixture_id, run_number)
            for fixture_id in self.expected_fixture_checksums
            for run_number in range(1, self.runs_per_fixture + 1)
        }
        if any(not case.passed for case in self.cases):
            status = "failed"
        elif seen == expected:
            status = "route_qualified"
        else:
            status = "incomplete"
        object.__setattr__(self, "status", status)
        return self

    @property
    def gate_totals(self) -> dict[GateName, dict[str, int]]:
        """Return pass/fail counts for every deterministic gate."""
        return {
            gate: {
                "passed": sum(case.gate_outcomes[gate].passed for case in self.cases),
                "failed": sum(not case.gate_outcomes[gate].passed for case in self.cases),
            }
            for gate in GateName
        }


class JudgmentDimension(QualificationModel):
    """Non-numeric, blinded judgment with only hashed citations and issue codes."""

    conclusion: Literal["clear", "concern", "uncertain"]
    citation_sha256s: tuple[Sha256, ...] = ()
    issue_codes: tuple[SafeIdentifier, ...] = ()


class BlindDocumentJudgment(QualificationModel):
    """Optional non-gating qualitative judgment for one exact document cell."""

    judge_fingerprint: Sha256
    judge_family_sha256: Sha256
    treatment_id: SafeIdentifier
    fixture_id: SafeIdentifier
    run_number: PositiveInt
    candidate_cell_fingerprint: Sha256
    attempted: Literal[True] = True
    clarity: JudgmentDimension
    job_relevance: JudgmentDimension
    terminal_readability: JudgmentDimension
    actual_cost_usd: NonNegativeFloat | None = None
    reserved_cost_usd: NonNegativeFloat
    charged_cost_usd: NonNegativeFloat
    updated_at: AwareDatetime = Field(default_factory=lambda: datetime.now(UTC))

    @model_validator(mode="after")
    def validate_charge(self) -> Self:
        """Apply the same known-versus-reserved charging rule as route cells."""
        expected = self.reserved_cost_usd if self.actual_cost_usd is None else self.actual_cost_usd
        if not isclose(self.charged_cost_usd, expected, rel_tol=1e-12, abs_tol=1e-12):
            msg = "Judgment charged cost must equal actual cost when known, otherwise reserved cost"
            raise ValueError(msg)
        return self

    @property
    def judgment_key(self) -> tuple[str, str, str, int]:
        """Exact judge fingerprint/treatment/fixture/run resume key."""
        return (
            self.judge_fingerprint,
            self.treatment_id,
            self.fixture_id,
            self.run_number,
        )


class DocumentQualificationResult(QualificationModel):
    """Crash-safe, exact-cell resumable document qualification artifact."""

    contract_version: SafeIdentifier
    experiment_fingerprint: Sha256
    policy_fingerprint: Sha256
    corpus_fingerprint: Sha256
    route_fingerprint: Sha256
    config_fingerprint: Sha256
    expected_routes: tuple[SafeIdentifier, ...]
    fixture_checksums: dict[SafeIdentifier, Sha256]
    runs_per_fixture: PositiveInt
    deadline_seconds: Literal[180] = 180
    evidence_environment: Literal["production", "test"] = "production"
    preflight: bool = False
    started_at: AwareDatetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: AwareDatetime = Field(default_factory=lambda: datetime.now(UTC))
    actual_cost_usd: NonNegativeFloat = 0.0
    charged_cost_usd: NonNegativeFloat = 0.0
    routes: dict[SafeIdentifier, RouteQualification] = Field(default_factory=dict)
    optional_judges: list[BlindDocumentJudgment] = Field(default_factory=list)
    status: Literal["preflight", "incomplete", "route_qualified", "qualified", "failed"] = "incomplete"

    def _validate_root_expectations(self) -> None:
        """Validate non-empty, unique root coverage expectations."""
        if not self.expected_routes or len(set(self.expected_routes)) != len(self.expected_routes):
            msg = "Expected routes must be non-empty and unique"
            raise ValueError(msg)
        if not self.fixture_checksums:
            msg = "Fixture checksums must be non-empty"
            raise ValueError(msg)

    def _validate_routes(self) -> tuple[set[str], list[DocumentCaseResult]]:
        """Validate route identities and exact cell coverage."""
        aliases: set[str] = set()
        cells: set[tuple[str, str, int]] = set()
        case_results: list[DocumentCaseResult] = []
        for treatment_id, route in self.routes.items():
            if treatment_id != route.identity.treatment_id:
                msg = "Route mapping key does not match treatment identity"
                raise ValueError(msg)
            if route.identity.route_alias in aliases:
                msg = "Each expected route alias may appear only once"
                raise ValueError(msg)
            aliases.add(route.identity.route_alias)
            if route.identity.route_alias not in self.expected_routes:
                msg = "Route identity alias is not expected"
                raise ValueError(msg)
            if route.expected_fixture_checksums != self.fixture_checksums:
                msg = "Route fixture expectations do not match the root corpus"
                raise ValueError(msg)
            if route.runs_per_fixture != self.runs_per_fixture:
                msg = "Route run count does not match the root run count"
                raise ValueError(msg)
            for case in route.cases:
                if case.cell_key in cells:
                    msg = "Result contains duplicate exact cells"
                    raise ValueError(msg)
                cells.add(case.cell_key)
                case_results.append(case)
        return aliases, case_results

    def _validate_judgments(self, case_results: list[DocumentCaseResult]) -> None:
        """Validate unique judgments against their exact stored cells."""
        cases_by_key = {case.cell_key: case for case in case_results}
        judgment_keys: set[tuple[str, str, str, int]] = set()
        for judgment in self.optional_judges:
            if judgment.judgment_key in judgment_keys:
                msg = "Result contains duplicate exact judgments"
                raise ValueError(msg)
            judgment_keys.add(judgment.judgment_key)
            candidate = cases_by_key.get((judgment.treatment_id, judgment.fixture_id, judgment.run_number))
            if candidate is None or candidate.cell_fingerprint != judgment.candidate_cell_fingerprint:
                msg = "Judgment does not identify an exact stored candidate cell"
                raise ValueError(msg)

    def _qualification_status(
        self,
        aliases: set[str],
        case_results: list[DocumentCaseResult],
    ) -> Literal["preflight", "incomplete", "route_qualified", "qualified", "failed"]:
        """Derive the root status after all coverage validation succeeds."""
        if self.preflight:
            if case_results or self.optional_judges:
                msg = "A preflight artifact cannot contain attempted cells or judgments"
                raise ValueError(msg)
            return "preflight"
        if any(route.status == "failed" for route in self.routes.values()):
            return "failed"
        if (
            self.evidence_environment == "production"
            and aliases == set(self.expected_routes)
            and all(route.status == "route_qualified" for route in self.routes.values())
        ):
            return "qualified" if self.expected_routes == APPROVED_ROUTE_ALIASES else "route_qualified"
        return "incomplete"

    @model_validator(mode="after")
    def compute_aggregates_and_status(self) -> Self:
        """Validate exact coverage and derive costs and qualification status."""
        self._validate_root_expectations()
        aliases, case_results = self._validate_routes()
        self._validate_judgments(case_results)

        actual = sum(case.telemetry.actual_cost_usd or 0.0 for case in case_results)
        charged = sum(case.telemetry.charged_cost_usd for case in case_results)
        object.__setattr__(self, "actual_cost_usd", actual)
        object.__setattr__(self, "charged_cost_usd", charged)
        object.__setattr__(self, "status", self._qualification_status(aliases, case_results))
        return self

    def completed_cell_keys(self) -> frozenset[tuple[str, str, int]]:
        """Return every dispatched cell, including persisted failures."""
        return frozenset(case.cell_key for route in self.routes.values() for case in route.cases)

    def strip_stale_fixture_results(
        self,
        selected_fixtures: list[str],
        current_checksums: dict[str, str],
    ) -> tuple[Self, frozenset[str]]:
        """Remove only cells and judgments whose selected fixture changed."""
        missing = set(selected_fixtures) - set(current_checksums)
        if missing:
            msg = f"Current checksums missing selected fixtures: {sorted(missing)}"
            raise ValueError(msg)
        stale = frozenset(
            fixture_id
            for fixture_id in selected_fixtures
            if fixture_id in self.fixture_checksums
            and self.fixture_checksums[fixture_id] != current_checksums[fixture_id]
        )
        if not stale:
            return self, frozenset()

        checksums = dict(self.fixture_checksums)
        checksums.update({fixture_id: current_checksums[fixture_id] for fixture_id in stale})
        routes = {
            treatment_id: RouteQualification.model_validate(
                route.model_dump()
                | {
                    "expected_fixture_checksums": checksums,
                    "cases": [case for case in route.cases if case.fixture_id not in stale],
                }
            )
            for treatment_id, route in self.routes.items()
        }
        cleaned = self.model_copy(
            update={
                "fixture_checksums": checksums,
                "routes": routes,
                "optional_judges": [judgment for judgment in self.optional_judges if judgment.fixture_id not in stale],
                "updated_at": datetime.now(UTC),
            }
        )
        return type(self).model_validate(cleaned.model_dump()), stale

    def merge(self, other: Self) -> Self:
        """Merge compatible artifacts, choosing the newest record for each exact key."""
        root_identity = (
            "experiment_fingerprint",
            "policy_fingerprint",
            "corpus_fingerprint",
            "route_fingerprint",
            "config_fingerprint",
            "evidence_environment",
            "contract_version",
            "expected_routes",
            "fixture_checksums",
            "runs_per_fixture",
            "deadline_seconds",
        )
        mismatched = [name for name in root_identity if getattr(self, name) != getattr(other, name)]
        if mismatched:
            msg = f"Cannot merge qualification results with different root identity: {mismatched}"
            raise ValueError(msg)

        merged_routes: dict[str, RouteQualification] = {}
        for treatment_id in sorted(set(self.routes) | set(other.routes)):
            left = self.routes.get(treatment_id)
            right = other.routes.get(treatment_id)
            if left is None:
                if right is not None:
                    merged_routes[treatment_id] = right
                continue
            if right is None:
                merged_routes[treatment_id] = left
                continue
            if left.identity != right.identity:
                msg = f"Cannot merge conflicting route identity for {treatment_id}"
                raise ValueError(msg)
            by_key = {case.cell_key: case for case in left.cases}
            for case in right.cases:
                existing = by_key.get(case.cell_key)
                if existing is None or case.updated_at >= existing.updated_at:
                    by_key[case.cell_key] = case
            merged_routes[treatment_id] = RouteQualification.model_validate(
                left.model_dump() | {"cases": sorted(by_key.values(), key=lambda case: case.cell_key)}
            )

        judgments = {judgment.judgment_key: judgment for judgment in self.optional_judges}
        for judgment in other.optional_judges:
            existing = judgments.get(judgment.judgment_key)
            if existing is None or judgment.updated_at >= existing.updated_at:
                judgments[judgment.judgment_key] = judgment

        merged = self.model_copy(
            update={
                "preflight": self.preflight and other.preflight,
                "started_at": min(self.started_at, other.started_at),
                "updated_at": max(self.updated_at, other.updated_at, datetime.now(UTC)),
                "routes": merged_routes,
                "optional_judges": sorted(judgments.values(), key=lambda item: item.judgment_key),
            }
        )
        return type(self).model_validate(merged.model_dump())

    def save(self, path: Path) -> None:
        """Atomically persist the safe JSON artifact."""
        atomic_write_json(path, self.model_dump_json(indent=2))

    @classmethod
    def load(cls, path: Path) -> Self:
        """Load and fully validate a persisted qualification artifact."""
        return cls.model_validate_json(path.read_text())
