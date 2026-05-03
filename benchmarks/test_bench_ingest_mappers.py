"""Benchmarks for job ingest data mapping operations.

Measures currency inference, country code parsing, deduplication hashing,
compensation building, and enum mapping -- pure functions inlined from
job-ingest-discovery-service, job-ingest-enrichment-service, and
job-storage-service to avoid importing service packages.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime

import pytest
from nohiki.common.v1 import (
    Compensation,
    CompensationBound,
    CompensationSource,
    CountryCode,
    CurrencyCode,
    MonetaryAmount,
    PaymentFrequency,
)

# Inlined from job_ingest_discovery_service.core.currency

COUNTRY_TO_CURRENCY: dict[CountryCode, CurrencyCode] = {
    CountryCode.USA: CurrencyCode.USD,
    CountryCode.CAN: CurrencyCode.CAD,
    CountryCode.GBR: CurrencyCode.GBP,
    CountryCode.AUS: CurrencyCode.AUD,
    CountryCode.DEU: CurrencyCode.EUR,
    CountryCode.FRA: CurrencyCode.EUR,
    CountryCode.NLD: CurrencyCode.EUR,
    CountryCode.IRL: CurrencyCode.EUR,
    CountryCode.CHE: CurrencyCode.CHF,
    CountryCode.NZL: CurrencyCode.NZD,
    CountryCode.SGP: CurrencyCode.SGD,
    CountryCode.IND: CurrencyCode.INR,
    CountryCode.ARE: CurrencyCode.AED,
    CountryCode.ISR: CurrencyCode.ILS,
}

ISO2_TO_COUNTRY: dict[str, CountryCode] = {
    "us": CountryCode.USA,
    "usa": CountryCode.USA,
    "ca": CountryCode.CAN,
    "can": CountryCode.CAN,
    "gb": CountryCode.GBR,
    "gbr": CountryCode.GBR,
    "uk": CountryCode.GBR,
    "de": CountryCode.DEU,
    "deu": CountryCode.DEU,
    "fr": CountryCode.FRA,
    "fra": CountryCode.FRA,
    "nl": CountryCode.NLD,
    "nld": CountryCode.NLD,
    "ie": CountryCode.IRL,
    "irl": CountryCode.IRL,
    "ch": CountryCode.CHE,
    "che": CountryCode.CHE,
    "au": CountryCode.AUS,
    "aus": CountryCode.AUS,
    "nz": CountryCode.NZL,
    "nzl": CountryCode.NZL,
    "sg": CountryCode.SGP,
    "sgp": CountryCode.SGP,
    "in": CountryCode.IND,
    "ind": CountryCode.IND,
    "ae": CountryCode.ARE,
    "are": CountryCode.ARE,
    "il": CountryCode.ISR,
    "isr": CountryCode.ISR,
}


def parse_country_code(value: str) -> CountryCode:
    """Parse country string to CountryCode enum."""
    if not value:
        return CountryCode.UNSPECIFIED
    return ISO2_TO_COUNTRY.get(value.lower().strip(), CountryCode.UNSPECIFIED)


def infer_currency_from_country(country: CountryCode) -> CurrencyCode:
    """Infer currency from country code."""
    return COUNTRY_TO_CURRENCY.get(country, CurrencyCode.UNSPECIFIED)


def infer_currency_from_country_string(country_str: str) -> CurrencyCode:
    """Infer currency from a country code string."""
    return infer_currency_from_country(parse_country_code(country_str))


# Inlined from job_storage_service.services.data_mapper


def compute_dedup_hash(title: str, company_name: str, posted_at: datetime | None) -> str:
    """Compute cross-source deduplication hash."""
    normalized_title = title.lower().strip()
    normalized_company = company_name.lower().strip()
    posted_date = posted_at.date().isoformat() if posted_at else "unknown"
    content = f"{normalized_title}|{normalized_company}|{posted_date}"
    return hashlib.sha256(content.encode()).hexdigest()


# Inlined from job_ingest_enrichment_service.services.compensation_builder

_SOURCE_MAP: dict[str, CompensationSource] = {
    "employer_provided": CompensationSource.EMPLOYER_PROVIDED,
    "job_board_estimate": CompensationSource.ESTIMATED_BY_JOB_BOARD,
}

_JOB_BOARD_CONFIDENCE = 70


def build_compensation_bound(
    amount_cents: int,
    currency: CurrencyCode,
    source: str,
    confidence: int | None,
) -> CompensationBound:
    """Build CompensationBound from extraction estimate."""
    proto_source = _SOURCE_MAP.get(source, CompensationSource.ESTIMATED_BY_NOHIKI)
    bound = CompensationBound(
        amount=MonetaryAmount(minor_units=amount_cents, currency=currency),
        source=proto_source,
    )
    if proto_source != CompensationSource.EMPLOYER_PROVIDED and confidence is not None:
        bound.confidence_percent = confidence
    return bound


def build_full_compensation(
    min_cents: int,
    max_cents: int,
    currency: CurrencyCode,
    frequency: PaymentFrequency,
) -> Compensation:
    """Build full Compensation with both bounds."""
    return Compensation(
        min_amount=CompensationBound(
            amount=MonetaryAmount(minor_units=min_cents, currency=currency),
            source=CompensationSource.ESTIMATED_BY_NOHIKI,
        ),
        max_amount=CompensationBound(
            amount=MonetaryAmount(minor_units=max_cents, currency=currency),
            source=CompensationSource.ESTIMATED_BY_NOHIKI,
        ),
        frequency=frequency,
    )


# Inlined enum mapping (used in both ingest services)

SALARY_PERIOD_TO_FREQUENCY: dict[str, PaymentFrequency] = {
    "yearly": PaymentFrequency.ANNUALLY,
    "monthly": PaymentFrequency.MONTHLY,
    "weekly": PaymentFrequency.WEEKLY,
    "daily": PaymentFrequency.DAILY,
    "hourly": PaymentFrequency.HOURLY,
}

PUBLISHER_TO_SOURCE_MAP: dict[str, str] = {
    "indeed": "INDEED",
    "linkedin": "LINKEDIN",
    "glassdoor": "GLASSDOOR",
    "ziprecruiter": "ZIPRECRUITER",
    "google": "GOOGLE",
}

# BENCHMARKS

# Country code parsing (every inbound listing)


def test_bench_parse_country_alpha2(benchmark: pytest.BenchmarkFixture) -> None:
    """Benchmark parsing ISO 3166-1 alpha-2 code."""
    benchmark(parse_country_code, "US")


def test_bench_parse_country_alpha3(benchmark: pytest.BenchmarkFixture) -> None:
    """Benchmark parsing ISO 3166-1 alpha-3 code."""
    benchmark(parse_country_code, "USA")


def test_bench_parse_country_lowercase(benchmark: pytest.BenchmarkFixture) -> None:
    """Benchmark parsing lowercase country code."""
    benchmark(parse_country_code, "gbr")


def test_bench_parse_country_unknown(benchmark: pytest.BenchmarkFixture) -> None:
    """Benchmark parsing unknown country (returns UNSPECIFIED)."""
    benchmark(parse_country_code, "ZZZ")


def test_bench_parse_country_empty(benchmark: pytest.BenchmarkFixture) -> None:
    """Benchmark parsing empty string (fast path)."""
    benchmark(parse_country_code, "")


# Currency inference (every listing with salary data)


def test_bench_infer_currency_direct(benchmark: pytest.BenchmarkFixture) -> None:
    """Benchmark direct country→currency lookup."""
    benchmark(infer_currency_from_country, CountryCode.USA)


def test_bench_infer_currency_from_string(benchmark: pytest.BenchmarkFixture) -> None:
    """Benchmark full string→country→currency pipeline."""
    benchmark(infer_currency_from_country_string, "US")


def test_bench_infer_currency_miss(benchmark: pytest.BenchmarkFixture) -> None:
    """Benchmark currency inference for unknown country."""
    benchmark(infer_currency_from_country_string, "XX")


# Deduplication hash (every listing stored)

_SAMPLE_POSTED = datetime(2024, 6, 15, 12, 0, 0, tzinfo=UTC)


def test_bench_dedup_hash(benchmark: pytest.BenchmarkFixture) -> None:
    """Benchmark dedup hash computation."""
    benchmark(compute_dedup_hash, "Senior Python Engineer", "Acme Corp", _SAMPLE_POSTED)


def test_bench_dedup_hash_no_date(benchmark: pytest.BenchmarkFixture) -> None:
    """Benchmark dedup hash with no posted_at."""
    benchmark(compute_dedup_hash, "Senior Python Engineer", "Acme Corp", None)


def test_bench_dedup_hash_long_title(benchmark: pytest.BenchmarkFixture) -> None:
    """Benchmark dedup hash with long title."""
    benchmark(
        compute_dedup_hash,
        "Senior Staff Software Engineer, Backend Infrastructure & Platform Team",
        "Alphabet Inc. (Google Cloud Platform Division)",
        _SAMPLE_POSTED,
    )


# Compensation building (every enriched listing)


def test_bench_build_compensation_bound(benchmark: pytest.BenchmarkFixture) -> None:
    """Benchmark building a single CompensationBound."""
    benchmark(
        build_compensation_bound,
        12000000,
        CurrencyCode.USD,
        "employer_provided",
        None,
    )


def test_bench_build_compensation_bound_nohiki(
    benchmark: pytest.BenchmarkFixture,
) -> None:
    """Benchmark building a Nohiki-estimated bound (with confidence)."""
    benchmark(
        build_compensation_bound,
        15000000,
        CurrencyCode.USD,
        "nohiki_estimate",
        _JOB_BOARD_CONFIDENCE,
    )


def test_bench_build_full_compensation(benchmark: pytest.BenchmarkFixture) -> None:
    """Benchmark building full Compensation with both bounds."""
    benchmark(
        build_full_compensation,
        10000000,
        20000000,
        CurrencyCode.USD,
        PaymentFrequency.ANNUALLY,
    )


# Enum mapping (every listing mapping)


def test_bench_salary_period_map(benchmark: pytest.BenchmarkFixture) -> None:
    """Benchmark salary period to PaymentFrequency mapping."""
    benchmark(lambda: SALARY_PERIOD_TO_FREQUENCY.get("yearly", PaymentFrequency.UNSPECIFIED))


def test_bench_publisher_source_map(benchmark: pytest.BenchmarkFixture) -> None:
    """Benchmark publisher string to source enum mapping."""
    benchmark(lambda: PUBLISHER_TO_SOURCE_MAP.get("linkedin", "UNSPECIFIED"))


def test_bench_publisher_source_miss(benchmark: pytest.BenchmarkFixture) -> None:
    """Benchmark publisher mapping miss."""
    benchmark(lambda: PUBLISHER_TO_SOURCE_MAP.get("unknown_board", "UNSPECIFIED"))
