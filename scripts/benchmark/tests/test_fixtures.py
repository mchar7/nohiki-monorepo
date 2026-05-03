"""Behavioral contracts for the benchmark fixture and gold registries."""

import hashlib
import json
import re

import pytest
from job_ingest_enrichment_service.extraction_contract import DEFAULT_EXTRACTION_SPEC

from llm_benchmark.fixtures import compute_fixture_checksum, get_fixture, get_gold_case, list_fixture_ids
from llm_benchmark.schemas.gold import GOLD_CONTRACT_VERSION, GoldField, GoldJobCase, score_extraction

EXPECTED_FIXTURE_IDS = {
    "data_scientist_remote",
    "devops_engineer_hybrid",
    "director_engineering",
    "electrician_onsite",
    "financial_analyst_hybrid",
    "french_language",
    "hr_director_hybrid",
    "hvac_technician",
    "junior_frontend_hybrid",
    "marketing_manager_remote",
    "no_explicit_compensation",
    "nurse_icu_onsite",
    "pharmacist_hybrid",
    "physical_therapist",
    "prompt_injection_adversarial",
    "prompt_length_boundary",
    "remote_ambiguity",
    "senior_python_remote",
    "sparse_malformed",
    "staff_platform_hybrid",
    "vp_product_remote",
}

CRITICAL_STRATA = {
    "french_language": "non_english",
    "no_explicit_compensation": "no_explicit_compensation",
    "prompt_injection_adversarial": "prompt_injection",
    "prompt_length_boundary": "prompt_length_boundary",
    "remote_ambiguity": "remote_ambiguity",
    "sparse_malformed": "sparse_malformed",
}


def _normalized(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.casefold()).strip()


def test_registry_contains_exactly_the_21_curated_cases() -> None:
    assert set(list_fixture_ids()) == EXPECTED_FIXTURE_IDS


def test_every_case_has_versioned_source_supported_gold() -> None:
    for fixture_id in EXPECTED_FIXTURE_IDS:
        listing = get_fixture(fixture_id)
        gold = get_gold_case(fixture_id)
        normalized_source = f" {_normalized(listing.description)} "

        assert gold.fixture_id == fixture_id
        assert gold.version == GOLD_CONTRACT_VERSION
        assert gold.raw_source == listing.description
        assert gold.fields
        assert gold.required_skills
        assert all(f" {_normalized(skill)} " in normalized_source for skill in gold.required_skills)


def test_critical_strata_are_explicitly_labeled_in_gold() -> None:
    assert {
        fixture_id: branch in get_gold_case(fixture_id).critical_branches
        for fixture_id, branch in CRITICAL_STRATA.items()
    } == dict.fromkeys(CRITICAL_STRATA, True)


def test_no_gold_field_is_a_scored_null_impossibility() -> None:
    """Exhaustive audit: no scored gold field can be impossible to satisfy.

    A ``GoldField`` with ``expected=None`` and ``scored=True`` can never be scored
    ``correct``: the deterministic scorer treats a null extraction as ``missing``,
    so a truthful null answer is always penalized (the manual-adjudication blocker).
    Such a field is only legitimate when its ``alternatives`` include a non-null,
    source-grounded value that makes a correct score reachable. Otherwise the field
    must be ``scored=False`` (matching the critical-fixture "location unavailable"
    convention). This runs over every generated and critical gold case.
    """
    offenders = []
    for fixture_id in list_fixture_ids():
        gold = get_gold_case(fixture_id)
        normalized_source = f" {_normalized(gold.raw_source)} "
        for field_name, field in gold.fields.items():
            if field.expected is not None or not field.scored:
                continue
            has_source_grounded_alternative = any(
                alt is not None and f" {_normalized(str(alt))} " in normalized_source for alt in field.alternatives
            )
            if not has_source_grounded_alternative:
                offenders.append((fixture_id, field_name, field.alternatives))
    assert offenders == [], (
        "scored gold fields with expected=None and no source-grounded non-null "
        f"alternative can never score correctly: {offenders}"
    )


def _fixture_contract_digest(fixture_id: str, gold: GoldJobCase) -> str:
    """Reproduce ``compute_fixture_checksum`` with an injectable gold contract.

    Mirrors the production contract dict exactly (asserted below) so a swapped gold
    can be checksummed through public seams without touching the private registry.
    """
    contract = {
        "output_schema": DEFAULT_EXTRACTION_SPEC.output_type.model_json_schema(),
        "system_prompt": DEFAULT_EXTRACTION_SPEC.system_prompt,
        "user_prompt": DEFAULT_EXTRACTION_SPEC.build_prompt(get_fixture(fixture_id)),
        "gold_contract": gold.model_dump(mode="json"),
    }
    return hashlib.sha256(json.dumps(contract, sort_keys=True).encode()).hexdigest()


def test_null_location_policy_change_invalidates_fixture_checksum() -> None:
    """Correcting a scored-null gold field must invalidate the fixture checksum.

    The fixture checksum digests the gold contract's ``model_dump``, so the
    experiment fingerprint changes when a field flips from the broken
    ``expected=None, scored=True`` form to the corrected ``scored=False`` form.
    Reverting ``marketing_manager_remote`` city/state to the impossible gold yields
    a different digest, proving stale run artifacts are invalidated.
    """
    fixture_id = "marketing_manager_remote"
    corrected_gold = get_gold_case(fixture_id)

    # The helper faithfully reproduces the production checksum for the live gold,
    # pinning it to compute_fixture_checksum so the comparison below is meaningful.
    assert _fixture_contract_digest(fixture_id, corrected_gold) == compute_fixture_checksum(fixture_id)

    impossible_gold = corrected_gold.model_copy(
        update={
            "fields": {
                **corrected_gold.fields,
                "location.city": GoldField(expected=None),
                "location.state_province": GoldField(expected=None),
            },
        },
    )
    assert impossible_gold.model_dump(mode="json") != corrected_gold.model_dump(mode="json")
    assert _fixture_contract_digest(fixture_id, impossible_gold) != compute_fixture_checksum(fixture_id)


def _accepted_value(field: GoldField) -> object:
    """The value a perfect grounded extraction would emit for a scored gold field."""
    if field.expected is not None:
        return field.expected
    for alternative in field.alternatives:
        if alternative is not None:
            return alternative
    return None


def _ideal_candidate(gold: GoldJobCase) -> dict[str, object]:
    """Build the perfect, source-grounded extraction a gold case must accept.

    Every scored field is filled from the gold's own accepted value, so an internally
    consistent gold scores it ``correct``. The two contract-derived location fields
    (``is_remote_eligible`` from the arrangement, per the production schema) are set
    from the contract rather than the possibly-broken gold expectation -- that is what
    exposes "impossible" gold that would penalize a truthful, grounded extraction.
    """
    fields = gold.fields

    def scored_value(name: str) -> object:
        field = fields[name]
        return _accepted_value(field) if field.scored else None

    work_arrangement = fields["work_arrangement"].expected or "UNSPECIFIED"
    location: dict[str, object] = {
        "country_code": _accepted_value(fields["location.country_code"]) or "UNSPECIFIED",
        "is_remote_eligible": str(work_arrangement) in {"REMOTE", "HYBRID"},
        "confidence_percent": 80,
    }
    city = scored_value("location.city")
    if city is not None:
        location["city"] = city
    state = scored_value("location.state_province")
    if state is not None:
        location["state_province"] = state

    experience: dict[str, object] = {}
    min_years = scored_value("experience.min_years")
    if min_years is not None:
        experience["min_years"] = {"years": min_years, "source": "explicit"}
    max_years = scored_value("experience.max_years")
    if max_years is not None:
        experience["max_years"] = {"years": max_years, "source": "explicit"}

    min_amount = scored_value("compensation.min_amount")
    if min_amount is not None:
        compensation: dict[str, object] = {
            "min_amount": {"amount": min_amount, "source": "employer_provided"},
            "max_amount": {"amount": _accepted_value(fields["compensation.max_amount"]), "source": "employer_provided"},
            "currency": _accepted_value(fields["compensation.currency"]) or "USD",
            "period": _accepted_value(fields["compensation.period"]) or "ANNUALLY",
            "reasoning": "Employer stated the compensation range explicitly in the source posting.",
        }
    else:
        compensation = {
            "min_amount": {"amount": 1, "source": "llm_inferred", "confidence_percent": 50},
            "max_amount": {"amount": 1, "source": "llm_inferred", "confidence_percent": 50},
            "currency": "USD",
            "period": "ANNUALLY",
            "reasoning": "Synthetic estimate used only to satisfy the production schema.",
        }

    return {
        "cleaned_title": _accepted_value(fields["cleaned_title"]),
        "cleaned_company": _accepted_value(fields["cleaned_company"]),
        "location": location,
        "work_arrangement": str(work_arrangement),
        "employment_term": "UNSPECIFIED",
        "seniority_level": scored_value("seniority_level") or "MID",
        "language": _accepted_value(fields["language"]) or "en",
        "experience": experience,
        "skills": [{"raw_skill": skill} for skill in sorted(gold.required_skills)],
        "compensation_estimate": compensation,
    }


def test_ideal_grounded_extraction_scores_perfectly_for_every_fixture() -> None:
    """No gold case may penalize the perfect, source-grounded extraction it describes.

    For every fixture, a candidate built from the gold's accepted values -- with the
    remote-eligibility flag derived from the contract (HYBRID and REMOTE are remote
    eligible) -- must validate and score a flawless 1.0: no scored field ``incorrect``,
    nothing missing, no skill false positives. This fails on the pre-fix "impossible"
    gold (HYBRID fixtures expected ``is_remote_eligible=False``, so a truthful hybrid
    extraction was marked wrong) and passes once the contract-correct gold lands.
    """
    for fixture_id in list_fixture_ids():
        gold = get_gold_case(fixture_id)
        result = score_extraction(gold, _ideal_candidate(gold))

        assert result.schema_valid is True, (fixture_id, result.schema_errors)
        incorrect = {name: score.actual for name, score in result.fields.items() if score.status == "incorrect"}
        assert incorrect == {}, (fixture_id, incorrect)
        assert result.missing_fields == (), (fixture_id, result.missing_fields)
        assert result.skills.false_positives == (), (fixture_id, result.skills.false_positives)
        assert result.skills.f1 == pytest.approx(1.0), fixture_id
        assert result.deterministic_score == pytest.approx(1.0), fixture_id


def test_gold_contract_version_bumped_to_v2_changes_every_checksum() -> None:
    """The M2 scoring change bumps the gold contract version, invalidating checksums.

    The contract version is digested into every fixture checksum, so reverting a live
    (v2) gold case to the pre-M2 ``job-extraction-gold-v1`` yields a different digest.
    This pins that the version moved off v1 and that it genuinely participates in the
    fingerprint that guards stale run artifacts.
    """
    assert GOLD_CONTRACT_VERSION == "job-extraction-gold-v2"
    for fixture_id in list_fixture_ids():
        assert get_gold_case(fixture_id).version == "job-extraction-gold-v2", fixture_id

    fixture_id = "senior_python_remote"
    live_gold = get_gold_case(fixture_id)
    assert _fixture_contract_digest(fixture_id, live_gold) == compute_fixture_checksum(fixture_id)

    pre_m2_gold = live_gold.model_copy(update={"version": "job-extraction-gold-v1"})
    assert _fixture_contract_digest(fixture_id, pre_m2_gold) != compute_fixture_checksum(fixture_id)
