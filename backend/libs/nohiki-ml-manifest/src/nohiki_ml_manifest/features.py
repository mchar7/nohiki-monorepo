"""L2R feature schema for the job-matching scoring pipeline.

Defines the canonical 32-feature vector layout used by the LightGBM L2R model.
This is the single source of truth for feature names, indices, descriptions,
and monotone constraints: shared across services and libraries.
"""

from __future__ import annotations

from enum import IntEnum
from typing import Final


class FeatureIndex(IntEnum):
    """L2R Feature Vector Layout.

    Design Principles:
    1. RAW VALUES: Provide actual measurements, let model learn optimal splits
    2. GRANULAR FEATURES: Multiple signals instead of composite scores
    3. NaN HANDLING: math.nan when data missing, validity flags for explicit signal
    4. NO NORMALIZATION: Tree models don't need [0,1] ranges

    LightGBM handles NaN natively with use_missing=true (default).
    """

    # Pipeline scores (0-1) come from upstream retrieval/rerank and are always present.
    MAXSIM_SCORE = 0
    RERANK_SCORE = 1

    # Location (2-5): RAW values let the model learn distance-decay curves and
    # relocation penalties rather than baking them into hand-tuned scores.
    DISTANCE_KM = 2
    IS_SAME_CITY = 3
    IS_REMOTE_JOB = 4
    USER_OPEN_TO_RELOCATION = 5

    # Experience (6-10): RAW years/levels surface over- and under-qualification.
    USER_EXPERIENCE_YEARS = 6
    JOB_EXPERIENCE_MIN = 7
    JOB_EXPERIENCE_MAX = 8
    USER_SENIORITY_LEVEL = 9
    JOB_SENIORITY_LEVEL = 10

    # Salary (11-13): annualized minor units, same-currency only.
    # All three are NaN when the user/job currencies differ, cross-currency
    # comparison would silently mislead the model.
    USER_MIN_SALARY = 11
    USER_TARGET_SALARY = 12
    JOB_SALARY = 13

    # Skills (14-19): granular signals instead of a single composite score.
    SKILL_MATCH_COUNT = 14
    SKILL_MISSING_COUNT = 15
    SKILL_TOTAL_REQUIRED = 16
    SKILL_AVG_PROFICIENCY = 17
    SKILL_AVG_PROVENANCE = 18
    SKILL_RELATIONSHIP_COUNT = 19

    # Semantic embedding similarity (20). title_embedding is still computed
    # and stored for future occupation-based features but is not used as an
    # L2R feature; occupation matching is represented through separate ISCO features.
    SKILLS_COSINE_SIM = 20

    # Job metadata (21-23).
    JOB_AGE_HOURS = 21
    LISTING_FEEDBACK_COUNT = 22
    LISTING_QUALITY_SCORE = 23

    # Work arrangement match (24): binary user-pref vs job arrangement.
    WORK_ARRANGEMENT_MATCH = 24

    # Validity flags (25-29): explicit "missingness as a feature" signal so
    # the model can learn that a NaN feature group is itself informative.
    HAS_LOCATION_DATA = 25
    HAS_EXPERIENCE_DATA = 26
    HAS_SALARY_DATA = 27
    HAS_SKILL_DATA = 28
    HAS_LISTING_QUALITY = 29

    # Taxonomy / skill-graph distance (30-31): shortest path in the ESCO
    # skill graph between user and job skills. NaN if either side is empty;
    # 0 means same skill, higher = more distant.
    SKILL_GRAPH_MIN_DISTANCE = 30
    SKILL_GRAPH_MEAN_DISTANCE = 31


FEATURE_COUNT: Final[int] = 32

FEATURE_NAMES: Final[dict[FeatureIndex, str]] = {
    FeatureIndex.MAXSIM_SCORE: "maxsim_score",
    FeatureIndex.RERANK_SCORE: "rerank_score",
    FeatureIndex.DISTANCE_KM: "distance_km",
    FeatureIndex.IS_SAME_CITY: "is_same_city",
    FeatureIndex.IS_REMOTE_JOB: "is_remote_job",
    FeatureIndex.USER_OPEN_TO_RELOCATION: "user_open_to_relocation",
    FeatureIndex.USER_EXPERIENCE_YEARS: "user_experience_years",
    FeatureIndex.JOB_EXPERIENCE_MIN: "job_experience_min",
    FeatureIndex.JOB_EXPERIENCE_MAX: "job_experience_max",
    FeatureIndex.USER_SENIORITY_LEVEL: "user_seniority_level",
    FeatureIndex.JOB_SENIORITY_LEVEL: "job_seniority_level",
    FeatureIndex.USER_MIN_SALARY: "user_min_salary",
    FeatureIndex.USER_TARGET_SALARY: "user_target_salary",
    FeatureIndex.JOB_SALARY: "job_salary",
    FeatureIndex.SKILL_MATCH_COUNT: "skill_match_count",
    FeatureIndex.SKILL_MISSING_COUNT: "skill_missing_count",
    FeatureIndex.SKILL_TOTAL_REQUIRED: "skill_total_required",
    FeatureIndex.SKILL_AVG_PROFICIENCY: "skill_avg_proficiency",
    FeatureIndex.SKILL_AVG_PROVENANCE: "skill_avg_provenance",
    FeatureIndex.SKILL_RELATIONSHIP_COUNT: "skill_relationship_count",
    FeatureIndex.SKILLS_COSINE_SIM: "skills_cosine_sim",
    FeatureIndex.JOB_AGE_HOURS: "job_age_hours",
    FeatureIndex.LISTING_FEEDBACK_COUNT: "listing_feedback_count",
    FeatureIndex.LISTING_QUALITY_SCORE: "listing_quality_score",
    FeatureIndex.WORK_ARRANGEMENT_MATCH: "work_arrangement_match",
    FeatureIndex.HAS_LOCATION_DATA: "has_location_data",
    FeatureIndex.HAS_EXPERIENCE_DATA: "has_experience_data",
    FeatureIndex.HAS_SALARY_DATA: "has_salary_data",
    FeatureIndex.HAS_SKILL_DATA: "has_skill_data",
    FeatureIndex.HAS_LISTING_QUALITY: "has_listing_quality",
    FeatureIndex.SKILL_GRAPH_MIN_DISTANCE: "skill_graph_min_distance",
    FeatureIndex.SKILL_GRAPH_MEAN_DISTANCE: "skill_graph_mean_distance",
}

FEATURE_DESCRIPTIONS: Final[dict[FeatureIndex, str]] = {
    FeatureIndex.MAXSIM_SCORE: "ColBERT MaxSim late-interaction score from Stage 2",
    FeatureIndex.RERANK_SCORE: "LLM reranker score from Stage 3 (0.0 if skipped)",
    FeatureIndex.DISTANCE_KM: "Raw distance in kilometers between user and job location",
    FeatureIndex.IS_SAME_CITY: "Binary: 1 if user and job in same city",
    FeatureIndex.IS_REMOTE_JOB: "Binary: 1 if job is remote",
    FeatureIndex.USER_OPEN_TO_RELOCATION: "Binary: 1 if user open to relocation",
    FeatureIndex.USER_EXPERIENCE_YEARS: "Raw user years of experience",
    FeatureIndex.JOB_EXPERIENCE_MIN: "Raw job minimum experience requirement (years)",
    FeatureIndex.JOB_EXPERIENCE_MAX: "Raw job maximum experience requirement (years)",
    FeatureIndex.USER_SENIORITY_LEVEL: "User seniority level (ordinal 0-9)",
    FeatureIndex.JOB_SENIORITY_LEVEL: "Job seniority level (ordinal 0-9)",
    FeatureIndex.USER_MIN_SALARY: "User minimum salary (annualized minor units, same currency only)",
    FeatureIndex.USER_TARGET_SALARY: "User target salary (annualized minor units, same currency only)",
    FeatureIndex.JOB_SALARY: "Job salary (annualized minor units, midpoint if range, same currency only)",
    FeatureIndex.SKILL_MATCH_COUNT: "Raw count of matched skills",
    FeatureIndex.SKILL_MISSING_COUNT: "Raw count of required but missing skills",
    FeatureIndex.SKILL_TOTAL_REQUIRED: "Raw count of job skill requirements",
    FeatureIndex.SKILL_AVG_PROFICIENCY: "Average user proficiency on matched skills (0-4)",
    FeatureIndex.SKILL_AVG_PROVENANCE: "Average provenance confidence on matched skills (0-1)",
    FeatureIndex.SKILL_RELATIONSHIP_COUNT: "Count of skills matched via skill graph relationships",
    FeatureIndex.SKILLS_COSINE_SIM: "Cosine similarity: user skills vs job skills embeddings",
    FeatureIndex.JOB_AGE_HOURS: "Raw hours since job was posted",
    FeatureIndex.LISTING_FEEDBACK_COUNT: "Reserved slot; listing feedback signal is unavailable (always 0)",
    FeatureIndex.LISTING_QUALITY_SCORE: "Reserved slot; listing quality signal is unavailable (always NaN)",
    FeatureIndex.WORK_ARRANGEMENT_MATCH: "Binary: 1 if work arrangement matches preference",
    FeatureIndex.HAS_LOCATION_DATA: "Binary: 1 if location data available",
    FeatureIndex.HAS_EXPERIENCE_DATA: "Binary: 1 if experience requirements present",
    FeatureIndex.HAS_SALARY_DATA: "Binary: 1 if compensation data available",
    FeatureIndex.HAS_SKILL_DATA: "Binary: 1 if skill requirements present",
    FeatureIndex.HAS_LISTING_QUALITY: "Reserved validity slot (always 0 while listing quality is unavailable)",
    FeatureIndex.SKILL_GRAPH_MIN_DISTANCE: "Min shortest-path distance in ESCO skill graph between user and job skills",
    FeatureIndex.SKILL_GRAPH_MEAN_DISTANCE: "Mean shortest-path distance across top matched skill pairs in ESCO graph",
}

# Monotonic constraints for LightGBM training.
# 1 = positive monotonic (higher value → always higher prediction)
# -1 = negative monotonic (higher value → always lower prediction)
# 0 = no constraint (model learns freely from data)
# Index in this list corresponds to FeatureIndex integer value.
MONOTONE_CONSTRAINTS: Final[list[int]] = [
    0,  # MAXSIM_SCORE - model learns
    0,  # RERANK_SCORE - model learns
    -1,  # DISTANCE_KM - closer is better (negative monotonic)
    0,  # IS_SAME_CITY - model learns
    0,  # IS_REMOTE_JOB - not monotonic (depends on user preference)
    0,  # USER_OPEN_TO_RELOCATION - not monotonic
    0,  # USER_EXPERIENCE_YEARS - not monotonic (overqualification exists)
    0,  # JOB_EXPERIENCE_MIN - not monotonic
    0,  # JOB_EXPERIENCE_MAX - not monotonic
    0,  # USER_SENIORITY_LEVEL - not monotonic
    0,  # JOB_SENIORITY_LEVEL - not monotonic
    0,  # USER_MIN_SALARY - not monotonic
    0,  # USER_TARGET_SALARY - not monotonic
    0,  # JOB_SALARY - not monotonic (higher ≠ always better match)
    1,  # SKILL_MATCH_COUNT - more matches always better
    -1,  # SKILL_MISSING_COUNT - fewer missing always better
    0,  # SKILL_TOTAL_REQUIRED - not monotonic
    1,  # SKILL_AVG_PROFICIENCY - higher always better
    1,  # SKILL_AVG_PROVENANCE - higher confidence always better
    0,  # SKILL_RELATIONSHIP_COUNT - not monotonic (indirect matches)
    0,  # SKILLS_COSINE_SIM - model learns
    -1,  # JOB_AGE_HOURS - fresher always better
    0,  # LISTING_FEEDBACK_COUNT - reserved, always 0
    0,  # LISTING_QUALITY_SCORE - reserved, always NaN
    1,  # WORK_ARRANGEMENT_MATCH - match always better
    0,  # HAS_LOCATION_DATA - not monotonic
    0,  # HAS_EXPERIENCE_DATA - not monotonic
    0,  # HAS_SALARY_DATA - not monotonic
    0,  # HAS_SKILL_DATA - not monotonic
    0,  # HAS_LISTING_QUALITY - reserved, always 0
    -1,  # SKILL_GRAPH_MIN_DISTANCE - closer skills always better
    -1,  # SKILL_GRAPH_MEAN_DISTANCE - closer skills always better
]

# Feature names used as critical signals in drift detection.
# Drift in these features triggers CRITICAL or HIGH severity alerts.
# These are the primary ML pipeline outputs: drift here indicates model degradation.
CRITICAL_FEATURES: Final[frozenset[str]] = frozenset(
    {
        FEATURE_NAMES[FeatureIndex.MAXSIM_SCORE],  # "maxsim_score"
        FEATURE_NAMES[FeatureIndex.RERANK_SCORE],  # "rerank_score"
    }
)

# Ordered list of feature names (index 0 = FeatureIndex value 0, etc.)
# Used to construct DataFrames for drift detection and logging.
FEATURE_NAME_LIST: Final[list[str]] = [FEATURE_NAMES[FeatureIndex(i)] for i in range(FEATURE_COUNT)]
