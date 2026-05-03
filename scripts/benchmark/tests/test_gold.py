"""Behavior tests for deterministic benchmark gold scoring."""

import pytest

from llm_benchmark.fixtures import get_gold_case
from llm_benchmark.schemas.gold import GoldField, score_extraction


def _sparse_candidate() -> dict[str, object]:
    return {
        "cleaned_title": "Analyst",
        "cleaned_company": "Unknown Company",
        "location": {},
        "work_arrangement": "UNSPECIFIED",
        "employment_term": "UNSPECIFIED",
        "seniority_level": "MID",
        "language": "en",
        "experience": {},
        "skills": [
            {"raw_skill": "Excel"},
            {"raw_skill": "Analyst"},
            {"raw_skill": "Python"},
        ],
        "compensation_estimate": {
            "min_amount": {"amount": 1, "source": "llm_inferred", "confidence_percent": 50},
            "max_amount": {"amount": 1, "source": "llm_inferred", "confidence_percent": 50},
            "currency": "USD",
            "period": "ANNUALLY",
            "reasoning": "Synthetic estimate used only to satisfy the production schema.",
        },
    }


def test_scoring_is_exact_deterministic_and_distinguishes_supported_from_hallucinated_skills() -> None:
    gold = get_gold_case("sparse_malformed")

    first = score_extraction(gold, _sparse_candidate())
    second = score_extraction(gold, _sparse_candidate())

    assert first == second
    assert first.schema_valid is True
    assert first.coverage == pytest.approx(1.0)
    assert first.skills.true_positives == ("Excel",)
    assert first.skills.source_supported_unscored == ("Analyst",)
    assert first.skills.false_positives == ("Python",)
    assert first.hallucination_signals == ("unsupported_skill:Python",)
    assert first.deterministic_score == pytest.approx(17 / 18)


def test_invalid_output_is_deterministically_scored_as_schema_invalid() -> None:
    gold = get_gold_case("senior_python_remote")
    invalid = {"cleaned_title": ["not", "a", "string"]}

    first = score_extraction(gold, invalid)
    second = score_extraction(gold, invalid)

    assert first == second
    assert first.schema_valid is False
    assert first.schema_errors
    assert first.deterministic_score < 1.0
    assert first.coverage == 0.0


def _marketing_manager_remote_candidate() -> dict[str, object]:
    """A truthful, source-faithful extraction of the fully-remote posting.

    The posting is remote with no physical location, so city and state_province
    are honestly null while country and remote-eligibility remain source-grounded.
    """
    return {
        "cleaned_title": "Marketing Manager",
        "cleaned_company": "Aurora Brand Collective",
        "location": {
            "city": None,
            "state_province": None,
            "country_code": "USA",
            "is_remote_eligible": True,
            "confidence_percent": 90,
        },
        "work_arrangement": "REMOTE",
        "employment_term": "UNSPECIFIED",
        "seniority_level": "SENIOR",
        "language": "en",
        "experience": {
            "min_years": {"years": 5, "source": "explicit"},
            "max_years": {"years": 10, "source": "explicit"},
        },
        "skills": [{"raw_skill": "Campaign Strategy"}],
        "compensation_estimate": {
            "min_amount": {"amount": 100000, "source": "employer_provided", "confidence_percent": 90},
            "max_amount": {"amount": 130000, "source": "employer_provided", "confidence_percent": 90},
            "currency": "USD",
            "period": "ANNUALLY",
            "reasoning": "Employer stated the annual salary range explicitly in the posting.",
        },
    }


def test_truthful_null_location_is_unscored_not_penalized() -> None:
    """A remote posting's honest null city/state must not be scored as missing.

    Regression for the manual-adjudication blocker: gold generated
    ``GoldField(expected=None, scored=True)`` for remote city/state, so the
    deterministic scorer marked a truthful null extraction ``incorrect``/``missing``
    and it could never score correctly. The corrected gold marks these fields
    ``scored=False`` (note "location unavailable"), so they are excluded from
    scoring rather than penalized.
    """
    gold = get_gold_case("marketing_manager_remote")
    result = score_extraction(gold, _marketing_manager_remote_candidate())

    assert result.schema_valid is True
    for name in ("location.city", "location.state_province"):
        gold_field = gold.fields[name]
        assert gold_field.expected is None
        assert gold_field.scored is False
        assert gold_field.note == "location unavailable"

        score = result.fields[name]
        assert score.status == "unscored"
        assert score.score is None
        assert name not in result.missing_fields
        assert name in result.unscored_fields

    # A truthful remote extraction is not dragged down by its honest null location.
    assert result.missing_fields == ()
    assert result.fields["location.country_code"].status == "correct"
    assert result.fields["location.is_remote_eligible"].status == "correct"

    # The same truthful extraction scored under the pre-fix "impossible" gold (remote
    # city/state as scored non-null) is strictly penalized; the corrected gold is not.
    impossible_gold = gold.model_copy(
        update={
            "fields": {
                **gold.fields,
                "location.city": GoldField(expected=None),
                "location.state_province": GoldField(expected=None),
            },
        },
    )
    penalized = score_extraction(impossible_gold, _marketing_manager_remote_candidate())
    assert penalized.fields["location.city"].status == "incorrect"
    assert penalized.fields["location.state_province"].status == "incorrect"
    assert result.deterministic_score > penalized.deterministic_score


def test_missing_required_non_null_field_is_still_penalized() -> None:
    """The null-location fix must not weaken penalties for genuinely-missing fields.

    A field whose gold expects a source-verifiable non-null value must still score
    ``incorrect``/``missing`` when the extraction omits it, so the fix cannot be a
    blanket "null is always fine" rule.
    """
    gold = get_gold_case("marketing_manager_remote")
    required_field = gold.fields["experience.min_years"]
    assert required_field.scored is True
    assert required_field.expected is not None

    candidate = _marketing_manager_remote_candidate()
    candidate["experience"] = {}
    result = score_extraction(gold, candidate)

    score = result.fields["experience.min_years"]
    assert result.schema_valid is True
    assert score.status == "incorrect"
    assert score.score == 0.0
    assert score.note == "missing"
    assert "experience.min_years" in result.missing_fields


def _grounded_candidate(**overrides: object) -> dict[str, object]:
    """A schema-valid extraction; override any top-level field for a focused assertion."""
    base: dict[str, object] = {
        "cleaned_title": "Analyst",
        "cleaned_company": "Example Corp",
        "location": {"country_code": "USA", "is_remote_eligible": False, "confidence_percent": 60},
        "work_arrangement": "UNSPECIFIED",
        "employment_term": "UNSPECIFIED",
        "seniority_level": "MID",
        "language": "en",
        "experience": {},
        "skills": [{"raw_skill": "Python"}],
        "compensation_estimate": {
            "min_amount": {"amount": 1, "source": "llm_inferred", "confidence_percent": 50},
            "max_amount": {"amount": 1, "source": "llm_inferred", "confidence_percent": 50},
            "currency": "USD",
            "period": "ANNUALLY",
            "reasoning": "Synthetic estimate used only to satisfy the production schema.",
        },
    }
    base.update(overrides)
    return base


def _french_candidate(
    *,
    city: object = "Montréal",
    state: object = "Quebec",
    skills: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    """A schema-valid extraction of the French HYBRID critical fixture."""
    return {
        "cleaned_title": "Ingénieur logiciel",
        "cleaned_company": "Atelier Numérique",
        "location": {
            "city": city,
            "state_province": state,
            "country_code": "CAN",
            "is_remote_eligible": True,
            "confidence_percent": 80,
        },
        "work_arrangement": "HYBRID",
        "employment_term": "FULL_TIME",
        "seniority_level": "MID",
        "language": "fr",
        "experience": {},
        "skills": skills if skills is not None else [{"raw_skill": "Python"}],
        "compensation_estimate": {
            "min_amount": {"amount": 1, "source": "llm_inferred", "confidence_percent": 50},
            "max_amount": {"amount": 1, "source": "llm_inferred", "confidence_percent": 50},
            "currency": "USD",
            "period": "ANNUALLY",
            "reasoning": "Synthetic estimate used only to satisfy the production schema.",
        },
    }


def test_accent_stripped_city_and_state_match_diacritic_equivalents() -> None:
    """Canonical/diacritic/accent-stripped location spellings must score ``correct``.

    Gold city is the accented "Montréal"; a truthful extraction that emits the
    canonical English "Montreal" (or an NFD-decomposed / cased variant) is the same
    place and must not be penalized. Gold state is the ASCII "Quebec"; the accented
    "Québec" must match it too. Pre-fix ``_normalized`` dropped accented characters
    to spaces ("montr al"), so these equivalents scored ``incorrect``.
    """
    gold = get_gold_case("french_language")
    assert gold.fields["location.city"].expected == "Montréal"
    assert gold.fields["location.state_province"].expected == "Quebec"

    for city in ("Montreal", "montréal", "MONTRÉAL", "Montre\u0301al"):
        result = score_extraction(gold, _french_candidate(city=city))
        assert result.fields["location.city"].status == "correct", city

    accented_state = score_extraction(gold, _french_candidate(state="Québec"))
    assert accented_state.fields["location.state_province"].status == "correct"


def test_normalization_matches_equivalents_without_substring_collision() -> None:
    """Accent normalization equates whole tokens, never creates substring matches.

    Field scoring stays exact-equality: an accent-equivalent city matches, but a
    truncation/superstring does not. Skill grounding stays token-boundary: the
    accent-stripped "Numerique" matches the raw accented token "Numérique", while
    "Numeri" (a strict substring of that token) is never source-supported.
    """
    gold = get_gold_case("french_language")

    assert score_extraction(gold, _french_candidate(city="Montreal")).fields["location.city"].status == "correct"
    for wrong in ("Montre", "Montreal Heights", "real"):
        status = score_extraction(gold, _french_candidate(city=wrong)).fields["location.city"].status
        assert status == "incorrect", wrong

    skills = [
        {"raw_skill": "Python"},
        {"raw_skill": "Numerique"},
        {"raw_skill": "Numeri"},
    ]
    result = score_extraction(gold, _french_candidate(skills=skills))
    assert result.skills.true_positives == ("Python",)
    assert result.skills.source_supported_unscored == ("Numerique",)
    assert result.skills.false_positives == ("Numeri",)


def test_seniority_scored_only_when_source_explicit() -> None:
    """Persona seniority is scored only when the level is stated in the source.

    "Senior Python Engineer" carries the explicit "senior" token, so its seniority
    is scored. "Data Scientist" (MID) has no mid/mid-level/intermediate token, so
    seniority is unscored and an extraction cannot be penalized for it. Pre-fix,
    every persona seniority was scored unconditionally.
    """
    explicit = get_gold_case("senior_python_remote").fields["seniority_level"]
    assert explicit.scored is True
    assert explicit.expected == "SENIOR"

    unsupported = get_gold_case("data_scientist_remote").fields["seniority_level"]
    assert unsupported.scored is False

    unsupported_gold = get_gold_case("data_scientist_remote")
    lenient = score_extraction(unsupported_gold, _grounded_candidate(seniority_level="EXECUTIVE"))
    assert lenient.fields["seniority_level"].status == "unscored"
    assert lenient.fields["seniority_level"].score is None
    assert "seniority_level" in lenient.unscored_fields

    explicit_gold = get_gold_case("senior_python_remote")
    strict = score_extraction(explicit_gold, _grounded_candidate(seniority_level="INTERN"))
    assert strict.fields["seniority_level"].status == "incorrect"
    correct = score_extraction(explicit_gold, _grounded_candidate(seniority_level="SENIOR"))
    assert correct.fields["seniority_level"].status == "correct"


def test_hybrid_arrangement_is_remote_eligible() -> None:
    """HYBRID (and REMOTE) arrangements are remote-eligible; ON_SITE is not.

    Per the production LocationExtraction schema, a hybrid role is remote-eligible.
    Pre-fix gold derived ``is_remote_eligible`` from ``== REMOTE`` only, so every
    HYBRID fixture (persona and the French critical case) expected ``False``.
    """
    hybrid_ids = (
        "junior_frontend_hybrid",
        "staff_platform_hybrid",
        "devops_engineer_hybrid",
        "pharmacist_hybrid",
        "financial_analyst_hybrid",
        "hr_director_hybrid",
    )
    for fixture_id in hybrid_ids:
        assert get_gold_case(fixture_id).fields["location.is_remote_eligible"].expected is True, fixture_id

    french = get_gold_case("french_language").fields["location.is_remote_eligible"]
    assert french.expected is True
    assert french.scored is True

    for onsite_id in ("nurse_icu_onsite", "electrician_onsite"):
        assert get_gold_case(onsite_id).fields["location.is_remote_eligible"].expected is False, onsite_id

    french_result = score_extraction(get_gold_case("french_language"), _french_candidate())
    assert french_result.fields["location.is_remote_eligible"].status == "correct"
    hybrid_persona = score_extraction(
        get_gold_case("junior_frontend_hybrid"),
        _grounded_candidate(
            work_arrangement="HYBRID",
            location={
                "city": "San Francisco",
                "state_province": "California",
                "country_code": "USA",
                "is_remote_eligible": True,
                "confidence_percent": 80,
            },
        ),
    )
    assert hybrid_persona.fields["location.is_remote_eligible"].status == "correct"


def test_critical_country_scored_only_with_geographic_grounding() -> None:
    """Critical country is scored only when the source carries geography.

    Grounded critical fixtures keep their scored, source-defensible country. The
    prompt-injection fixture has no geography (location "Remote", body is an
    injection attempt), so its country is unscored -- a hallucinated/injected
    country is neither rewarded nor penalized. Pre-fix it was scored ``USA``.
    """
    grounded = {
        "french_language": "CAN",
        "no_explicit_compensation": "USA",
        "remote_ambiguity": "USA",
        "prompt_length_boundary": "USA",
    }
    for fixture_id, country in grounded.items():
        field = get_gold_case(fixture_id).fields["location.country_code"]
        assert field.scored is True, fixture_id
        assert field.expected == country, fixture_id

    injection = get_gold_case("prompt_injection_adversarial").fields["location.country_code"]
    assert injection.scored is False

    grounded_result = score_extraction(
        get_gold_case("no_explicit_compensation"),
        _grounded_candidate(
            location={
                "city": "Dallas",
                "state_province": "Texas",
                "country_code": "USA",
                "is_remote_eligible": False,
                "confidence_percent": 80,
            },
        ),
    )
    assert grounded_result.fields["location.country_code"].status == "correct"

    injected = score_extraction(
        get_gold_case("prompt_injection_adversarial"),
        _grounded_candidate(location={"country_code": "USA", "is_remote_eligible": True, "confidence_percent": 80}),
    )
    assert injected.fields["location.country_code"].status == "unscored"
    assert "location.country_code" in injected.unscored_fields


def test_inferred_skills_are_bucketed_and_excluded_from_penalty() -> None:
    """Unmatched ``source='inferred'`` skills land in ``inferred_unscored`` (M2).

    An inferred skill the model added from role context (not in the gold set and not
    in the source text) must not count as a hallucination, a false positive, or drag
    down precision. Explicit ungrounded skills are still penalized as hallucinations.
    """
    gold = get_gold_case("sparse_malformed")
    candidate = _grounded_candidate(
        skills=[
            {"raw_skill": "Excel"},
            {"raw_skill": "Analyst"},
            {"raw_skill": "Python"},
            {"raw_skill": "Git", "source": "inferred"},
        ],
    )
    result = score_extraction(gold, candidate)

    assert result.skills.true_positives == ("Excel",)
    assert result.skills.source_supported_unscored == ("Analyst",)
    assert result.skills.inferred_unscored == ("Git",)
    assert result.skills.false_positives == ("Python",)
    assert "Git" not in result.skills.false_positives
    assert result.hallucination_signals == ("unsupported_skill:Python",)
    assert result.skills.precision == pytest.approx(0.5)
    assert result.skills.recall == pytest.approx(1.0)


def test_matched_and_grounded_inferred_skill_precedence() -> None:
    """M2 precedence: matched beats source; inferred beats source-supported.

    A skill that matches an expected requirement is a true positive even when its
    source is ``inferred``. An unmatched inferred skill whose phrase does appear in
    the source is still bucketed as ``inferred_unscored`` -- never conflated with the
    explicit source-supported bucket.
    """
    gold = get_gold_case("sparse_malformed")
    candidate = _grounded_candidate(
        skills=[
            {"raw_skill": "Excel", "source": "inferred"},
            {"raw_skill": "Analyst", "source": "inferred"},
        ],
    )
    result = score_extraction(gold, candidate)

    assert result.skills.true_positives == ("Excel",)
    assert result.skills.inferred_unscored == ("Analyst",)
    assert result.skills.source_supported_unscored == ()
    assert result.skills.false_positives == ()
    assert result.hallucination_signals == ()
    assert result.skills.recall == pytest.approx(1.0)
