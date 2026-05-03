"""Versioned deterministic gold cases and scoring for job extraction benchmarks."""

import re
import unicodedata
from collections.abc import Mapping
from typing import Literal

from job_ingest_enrichment_service.schemas import JobExtractionSchema
from pydantic import BaseModel, ConfigDict, Field, ValidationError

GOLD_CONTRACT_VERSION = "job-extraction-gold-v2"
type FieldStatus = Literal["correct", "incorrect", "ambiguous", "unscored"]


class GoldField(BaseModel):
    """A source-defensible expected value with explicit alternatives."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    expected: str | int | bool | None = None
    alternatives: tuple[str | int | bool | None, ...] = ()
    scored: bool = True
    note: str | None = None


class GoldJobCase(BaseModel):
    """Immutable gold contract for one raw job posting."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    version: Literal["job-extraction-gold-v2"] = GOLD_CONTRACT_VERSION
    fixture_id: str
    domain: str
    critical_branches: frozenset[str]
    raw_source: str
    fields: dict[str, GoldField]
    required_skills: frozenset[str]


class FieldScore(BaseModel):
    """Serializable result for one deterministic comparison."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    status: FieldStatus
    score: float | None = Field(default=None, ge=0.0, le=1.0)
    expected: object | None = None
    actual: object | None = None
    note: str | None = None


class SkillsScore(BaseModel):
    """Deterministic skill-set metrics and source-grounding diagnostics."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    precision: float
    recall: float
    f1: float
    true_positives: tuple[str, ...]
    false_positives: tuple[str, ...]
    source_supported_unscored: tuple[str, ...]
    inferred_unscored: tuple[str, ...]
    missing_required: tuple[str, ...]


class GoldScore(BaseModel):
    """Serializable primary ranking evidence for one extraction."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    contract_version: str
    fixture_id: str
    schema_valid: bool
    schema_errors: tuple[str, ...] = ()
    fields: dict[str, FieldScore]
    skills: SkillsScore
    hallucination_signals: tuple[str, ...]
    coverage: float
    missing_fields: tuple[str, ...]
    ambiguous_fields: tuple[str, ...]
    unscored_fields: tuple[str, ...]
    deterministic_score: float


def _normalized(value: object) -> str:
    """Casefold, strip diacritics (NFKD + drop combining marks), collapse to a-z0-9 tokens.

    Diacritically or canonically equivalent forms and their accent-stripped
    output compare equal ("Montréal" == "Montreal", "Québec" == "Quebec") while
    word boundaries are preserved: only combining marks are removed, so no two
    distinct space-separated tokens are ever merged into a new substring match.
    """
    text = str(getattr(value, "name", value))
    decomposed = unicodedata.normalize("NFKD", text.casefold())
    stripped = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return re.sub(r"[^a-z0-9]+", " ", stripped).strip()


def _contains_phrase(text: str, phrase: str) -> bool:
    """Match a normalized phrase on token boundaries, not inside another token."""
    return bool(phrase) and f" {phrase} " in f" {text} "


def _field_score(gold: GoldField, actual: object) -> FieldScore:
    if not gold.scored:
        return FieldScore(status="unscored", expected=gold.expected, actual=actual, note=gold.note)
    accepted = (gold.expected, *gold.alternatives)
    if actual is None:
        return FieldScore(status="incorrect", score=0.0, expected=accepted, actual=None, note="missing")
    normalized_actual = _normalized(actual)
    if any(normalized_actual == _normalized(value) for value in accepted):
        return FieldScore(status="correct", score=1.0, expected=accepted, actual=actual)
    return FieldScore(status="incorrect", score=0.0, expected=accepted, actual=actual)


def _get(value: object, *path: str) -> object | None:
    current: object | None = value
    for part in path:
        current = current.get(part) if isinstance(current, Mapping) else getattr(current, part, None)
        if current is None:
            break
    return current


def _score_skills(case: GoldJobCase, output: JobExtractionSchema | None) -> SkillsScore:
    predicted = output.skills if output is not None else []
    expected_by_norm = {_normalized(skill): skill for skill in case.required_skills}
    matched: set[str] = set()
    false_positive: set[str] = set()
    supported: set[str] = set()
    inferred: set[str] = set()
    raw_normalized = _normalized(case.raw_source)
    for skill in predicted:
        normalized = _normalized(skill.raw_skill)
        if normalized in expected_by_norm:
            matched.add(expected_by_norm[normalized])
        elif skill.source == "inferred":
            inferred.add(skill.raw_skill)
        elif _contains_phrase(raw_normalized, normalized):
            supported.add(skill.raw_skill)
        else:
            false_positive.add(skill.raw_skill)
    denominator = len(matched) + len(false_positive)
    precision = len(matched) / denominator if denominator else 0.0
    recall = len(matched) / len(expected_by_norm) if expected_by_norm else 1.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return SkillsScore(
        precision=precision,
        recall=recall,
        f1=f1,
        true_positives=tuple(sorted(matched)),
        false_positives=tuple(sorted(false_positive)),
        source_supported_unscored=tuple(sorted(supported)),
        inferred_unscored=tuple(sorted(inferred)),
        missing_required=tuple(sorted(case.required_skills - matched)),
    )


def score_extraction(case: GoldJobCase, candidate: JobExtractionSchema | Mapping[str, object]) -> GoldScore:
    """Score an extraction without model calls or subjective inference."""
    errors: tuple[str, ...] = ()
    try:
        output = (
            candidate if isinstance(candidate, JobExtractionSchema) else JobExtractionSchema.model_validate(candidate)
        )
    except ValidationError as exc:
        output = None
        errors = tuple(f"{'.'.join(str(part) for part in error['loc'])}: {error['msg']}" for error in exc.errors())

    paths: dict[str, tuple[str, ...]] = {
        "cleaned_title": ("cleaned_title",),
        "cleaned_company": ("cleaned_company",),
        "location.city": ("location", "city"),
        "location.state_province": ("location", "state_province"),
        "location.country_code": ("location", "country_code"),
        "location.is_remote_eligible": ("location", "is_remote_eligible"),
        "location.confidence_percent": ("location", "confidence_percent"),
        "work_arrangement": ("work_arrangement",),
        "employment_term": ("employment_term",),
        "seniority_level": ("seniority_level",),
        "language": ("language",),
        "compensation.min_amount": ("compensation_estimate", "min_amount", "amount"),
        "compensation.max_amount": ("compensation_estimate", "max_amount", "amount"),
        "compensation.min_source": ("compensation_estimate", "min_amount", "source"),
        "compensation.max_source": ("compensation_estimate", "max_amount", "source"),
        "compensation.currency": ("compensation_estimate", "currency"),
        "compensation.period": ("compensation_estimate", "period"),
        "compensation.reasoning": ("compensation_estimate", "reasoning"),
        "experience.min_years": ("experience", "min_years", "years"),
        "experience.max_years": ("experience", "max_years", "years"),
        "experience.min_source": ("experience", "min_years", "source"),
        "experience.max_source": ("experience", "max_years", "source"),
    }
    field_scores = {
        name: _field_score(gold, _get(output, *paths[name]) if output is not None else None)
        for name, gold in case.fields.items()
    }
    skills = _score_skills(case, output)
    hallucinations = [f"unsupported_skill:{skill}" for skill in skills.false_positives]
    scored = [item for item in field_scores.values() if item.score is not None]
    coverage = sum(item.actual is not None for item in scored) / len(scored) if scored else 0.0
    missing = tuple(sorted(name for name, item in field_scores.items() if item.note == "missing"))
    ambiguous = tuple(sorted(name for name, item in field_scores.items() if item.status == "ambiguous"))
    unscored = tuple(sorted(name for name, item in field_scores.items() if item.status == "unscored"))
    components = [item.score for item in scored if item.score is not None]
    components.append(skills.f1)
    deterministic = sum(components) / len(components) if components else 0.0
    return GoldScore(
        contract_version=case.version,
        fixture_id=case.fixture_id,
        schema_valid=output is not None,
        schema_errors=errors,
        fields=field_scores,
        skills=skills,
        hallucination_signals=tuple(sorted(hallucinations)),
        coverage=coverage,
        missing_fields=missing,
        ambiguous_fields=ambiguous,
        unscored_fields=unscored,
        deterministic_score=deterministic,
    )
