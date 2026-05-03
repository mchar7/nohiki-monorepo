"""Centralized constants for the LLM benchmark suite.

Single source of truth for default values, thresholds, and magic numbers
used across multiple modules. Avoids scattered constants and duplication.
"""

from __future__ import annotations

from typing import Final

BENCHMARK_SOURCE_VERSION: Final[str] = "job-extraction-v2"
BENCHMARK_POLICY_VERSION: Final[str] = "gold-independent-treatment-v2"

# Default model and fixture selections

DEFAULT_FIXTURES: Final[list[str]] = [
    "senior_python_remote",
    "junior_frontend_hybrid",
    "staff_platform_hybrid",
    "data_scientist_remote",
    "devops_engineer_hybrid",
    "nurse_icu_onsite",
    "physical_therapist",
    "pharmacist_hybrid",
    "director_engineering",
    "vp_product_remote",
    "financial_analyst_hybrid",
    "marketing_manager_remote",
    "hr_director_hybrid",
    "electrician_onsite",
    "hvac_technician",
    "prompt_injection_adversarial",
    "french_language",
    "sparse_malformed",
    "no_explicit_compensation",
    "remote_ambiguity",
    "prompt_length_boundary",
]

DEFAULT_RUNS_PER_FIXTURE: Final[int] = 1

# Local inference defaults

DEFAULT_OLLAMA_BASE_URL: Final[str] = "http://localhost:11434/v1"
DEFAULT_OLLAMA_TIMEOUT_SECONDS: Final[float] = 600.0
OLLAMA_PROVIDER_PREFIX: Final[str] = "ollama:"

# Benchmark runner defaults

DEFAULT_BENCHMARK_CONCURRENCY: Final[int] = 8

# Judge / evaluation defaults

DEFAULT_EVAL_CONCURRENCY: Final[int] = 4
DEFAULT_MAX_RUNS_PER_FIXTURE: Final[int] = 3
DEFAULT_COST_CAP_USD: Final[float] = 10.0

JUDGE_TEMPERATURE: Final[float] = 0.0
JUDGE_TIMEOUT_SECONDS: Final[float] = 120.0
JUDGE_MAX_RETRIES: Final[int] = 5
JUDGE_MAX_TOKENS: Final[int] = 16384
JUDGE_APP_TITLE: Final[str] = "Nohiki LLM Benchmark Judge"
YAML_DUMP_WIDTH: Final[int] = 120
DEFAULT_JUDGE_MAX_CONCURRENCY: Final[int] = 8

# Cost estimation

ESTIMATED_INPUT_TOKENS_PER_CALL: Final[int] = 4_000
ESTIMATED_OUTPUT_TOKENS_PER_CALL: Final[int] = 500

# Classification thresholds (aggregation)

FAIL_THRESHOLD: Final[float] = 40.0
WARNING_THRESHOLD: Final[float] = 60.0
CAUTION_THRESHOLD: Final[float] = 80.0

# Snapshot management

MAX_SNAPSHOTS: Final[int] = 10
