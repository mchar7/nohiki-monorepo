"""Behavioral contract tests for :mod:`nohiki_finance`."""

from __future__ import annotations

import hashlib
import importlib
import operator
import sys
from decimal import Decimal
from importlib.resources import files
from pathlib import Path
from types import MappingProxyType, ModuleType
from typing import cast

import nohiki_finance
import pytest
from nohiki_finance import (
    ANNUALIZATION_POLICY_VERSION,
    DAYS_PER_WEEK,
    HOURS_PER_WEEK,
    ISO_4217_EXPONENTS,
    PAY_PERIOD_ANNUAL_MULTIPLIER,
    WEEKS_PER_YEAR,
    PayPeriod,
    annualize_to_minor_units,
    to_major_units,
    to_minor_units,
)

EXPECTED_ISO_CODE_COUNT = 165
EXPECTED_ISO_MAP_SHA256 = "c08353e42531ed78a430624b93a65b8ec8c2ee107e22f1af4fee03393d5b7ed9"
NA_MINOR_UNIT_CODES = frozenset(
    {"XAG", "XAU", "XBA", "XBB", "XBC", "XBD", "XDR", "XPD", "XPT", "XSU", "XTS", "XUA", "XXX"}
)
EXPECTED_PAY_PERIODS = {
    PayPeriod.HOURLY: 2_080,
    PayPeriod.DAILY: 260,
    PayPeriod.WEEKLY: 52,
    PayPeriod.BIWEEKLY: 26,
    PayPeriod.SEMI_MONTHLY: 24,
    PayPeriod.MONTHLY: 12,
    PayPeriod.QUARTERLY: 4,
    PayPeriod.ANNUALLY: 1,
}


def _iso_map_checksum() -> str:
    canonical = "".join(f"{code}:{ISO_4217_EXPONENTS[code]}\n" for code in sorted(ISO_4217_EXPONENTS))
    return hashlib.sha256(canonical.encode()).hexdigest()


def test_iso_map_matches_checked_in_current_list_one_contract() -> None:
    """The complete numeric-minor-unit table changes only through an explicit contract update."""
    assert isinstance(ISO_4217_EXPONENTS, MappingProxyType)
    assert len(ISO_4217_EXPONENTS) == EXPECTED_ISO_CODE_COUNT
    assert _iso_map_checksum() == EXPECTED_ISO_MAP_SHA256
    assert all(len(code) == 3 and code.isascii() and code.isupper() for code in ISO_4217_EXPONENTS)
    assert set(ISO_4217_EXPONENTS.values()) == {0, 2, 3, 4}
    assert NA_MINOR_UNIT_CODES.isdisjoint(ISO_4217_EXPONENTS)


@pytest.mark.parametrize(
    ("currency", "exponent", "major_units", "minor_units"),
    [
        pytest.param("JPY", 0, Decimal(123), 123, id="zero-decimal-jpy"),
        pytest.param("USD", 2, Decimal("123.45"), 12_345, id="two-decimal-usd"),
        pytest.param("BHD", 3, Decimal("123.456"), 123_456, id="three-decimal-bhd"),
    ],
)
def test_representative_exponents_convert_exactly_and_round_trip(
    currency: str,
    exponent: int,
    major_units: Decimal,
    minor_units: int,
) -> None:
    converted_major = to_major_units(minor_units, currency)

    assert ISO_4217_EXPONENTS[currency] == exponent
    assert converted_major == major_units
    assert converted_major.as_tuple().exponent == -exponent
    assert to_minor_units(converted_major, currency) == minor_units


@pytest.mark.parametrize("currency", sorted(NA_MINOR_UNIT_CODES))
def test_na_minor_unit_entries_are_explicitly_unsupported(currency: str) -> None:
    with pytest.raises(ValueError, match=rf"^Unsupported currency: '{currency}'$"):
        to_minor_units(Decimal(1), currency)


@pytest.mark.parametrize(
    "currency",
    [
        pytest.param("usd", id="lowercase"),
        pytest.param("US", id="short"),
        pytest.param("USDD", id="long"),
        pytest.param("ÜSD", id="non-ascii"),
    ],
)
def test_currency_must_be_an_uppercase_ascii_code(currency: str) -> None:
    with pytest.raises(ValueError, match=r"^Currency must be an uppercase ISO 4217 string:"):
        to_minor_units(Decimal(1), currency)


def test_unknown_well_formed_currency_is_rejected() -> None:
    with pytest.raises(ValueError, match=r"^Unsupported currency: 'ZZZ'$"):
        to_minor_units(Decimal(1), "ZZZ")


@pytest.mark.parametrize("currency", [None, 840, True])
def test_non_string_currency_is_rejected(currency: object) -> None:
    with pytest.raises(TypeError, match=r"^Currency must be an uppercase ISO 4217 string$"):
        to_minor_units(Decimal(1), cast("str", currency))


@pytest.mark.parametrize("amount", [0, 1.0, True, "1.00"])
def test_major_units_require_decimal(amount: object) -> None:
    with pytest.raises(TypeError, match=r"^Major-unit amount must be a Decimal$"):
        to_minor_units(cast("Decimal", amount), "USD")


@pytest.mark.parametrize("amount", ["Infinity", "-Infinity", "NaN", "sNaN"])
def test_non_finite_decimal_is_rejected(amount: str) -> None:
    with pytest.raises(ValueError, match=r"^Major-unit amount must be finite$"):
        to_minor_units(Decimal(amount), "USD")


@pytest.mark.parametrize("minor_units", [True, False, Decimal(1), 1.0, "1"])
def test_minor_units_require_non_boolean_int(minor_units: object) -> None:
    with pytest.raises(TypeError, match=r"^Minor-unit amount must be an integer$"):
        to_major_units(cast("int", minor_units), "USD")


@pytest.mark.parametrize(
    ("major_units", "expected_minor_units"),
    [
        pytest.param("1.005", 100, id="positive-even-lower"),
        pytest.param("1.015", 102, id="positive-even-upper"),
        pytest.param("-1.005", -100, id="negative-even-upper"),
        pytest.param("-1.015", -102, id="negative-even-lower"),
    ],
)
def test_midpoints_use_round_half_even(major_units: str, expected_minor_units: int) -> None:
    assert to_minor_units(Decimal(major_units), "USD") == expected_minor_units


def test_pay_period_enum_and_multiplier_map_are_complete() -> None:
    assert len(PayPeriod) == 8
    assert set(PayPeriod) == set(EXPECTED_PAY_PERIODS)
    assert dict(PAY_PERIOD_ANNUAL_MULTIPLIER) == EXPECTED_PAY_PERIODS


@pytest.mark.parametrize(("period", "multiplier"), EXPECTED_PAY_PERIODS.items())
def test_every_pay_period_annualizes(period: PayPeriod, multiplier: int) -> None:
    assert annualize_to_minor_units(Decimal("1.00"), "USD", period) == 100 * multiplier
    assert annualize_to_minor_units(Decimal("1.00"), "USD", period.value) == 100 * multiplier


def test_annualization_rounds_before_multiplication() -> None:
    assert annualize_to_minor_units(Decimal("0.015"), "USD", "MONTHLY") == 24


@pytest.mark.parametrize("period", ["FORTNIGHTLY", "monthly"])
def test_invalid_pay_period_is_rejected(period: str) -> None:
    with pytest.raises(ValueError, match=rf"^Unsupported pay period: '{period}'$"):
        annualize_to_minor_units(Decimal(1), "USD", period)


@pytest.mark.parametrize(
    ("mapping", "key", "value"),
    [
        pytest.param(ISO_4217_EXPONENTS, "USD", 0, id="currency-exponents"),
        pytest.param(PAY_PERIOD_ANNUAL_MULTIPLIER, PayPeriod.MONTHLY, 13, id="period-multipliers"),
    ],
)
def test_canonical_maps_are_immutable(mapping: object, key: object, value: object) -> None:
    mutable = cast("dict[object, object]", mapping)
    with pytest.raises(TypeError, match="does not support item assignment"):
        operator.setitem(mutable, key, value)


def test_projection_policy_names_and_freezes_its_assumptions() -> None:
    assert ANNUALIZATION_POLICY_VERSION == "2026-07-11"
    assert HOURS_PER_WEEK == 40
    assert DAYS_PER_WEEK == 5
    assert WEEKS_PER_YEAR == 52
    assert isinstance(PAY_PERIOD_ANNUAL_MULTIPLIER, MappingProxyType)


def test_projection_multipliers_are_derived_from_named_assumptions() -> None:
    assert PAY_PERIOD_ANNUAL_MULTIPLIER[PayPeriod.HOURLY] == HOURS_PER_WEEK * WEEKS_PER_YEAR
    assert PAY_PERIOD_ANNUAL_MULTIPLIER[PayPeriod.DAILY] == DAYS_PER_WEEK * WEEKS_PER_YEAR
    assert PAY_PERIOD_ANNUAL_MULTIPLIER[PayPeriod.WEEKLY] == WEEKS_PER_YEAR
    assert PAY_PERIOD_ANNUAL_MULTIPLIER[PayPeriod.BIWEEKLY] == WEEKS_PER_YEAR // 2


def test_public_api_exports_exactly_the_clean_cutover_surface() -> None:
    expected: dict[str, object] = {
        "ANNUALIZATION_POLICY_VERSION": ANNUALIZATION_POLICY_VERSION,
        "DAYS_PER_WEEK": DAYS_PER_WEEK,
        "HOURS_PER_WEEK": HOURS_PER_WEEK,
        "ISO_4217_EXPONENTS": ISO_4217_EXPONENTS,
        "PAY_PERIOD_ANNUAL_MULTIPLIER": PAY_PERIOD_ANNUAL_MULTIPLIER,
        "WEEKS_PER_YEAR": WEEKS_PER_YEAR,
        "PayPeriod": PayPeriod,
        "annualize_to_minor_units": annualize_to_minor_units,
        "to_major_units": to_major_units,
        "to_minor_units": to_minor_units,
    }

    assert nohiki_finance.__all__ == tuple(expected)
    assert {name: getattr(nohiki_finance, name) for name in nohiki_finance.__all__} == expected
    assert not hasattr(nohiki_finance, "Currency")


def test_distribution_contains_inline_typing_marker() -> None:
    assert files(nohiki_finance).joinpath("py.typed").is_file()


def test_old_finance_project_is_absent_but_legacy_namespace_coexists() -> None:
    finance_project = Path(__file__).resolve().parents[1]
    old_project = finance_project.with_name("nohiki-domain-utils")
    finance = importlib.import_module("nohiki_finance")
    legacy = importlib.import_module("nohiki_domain_utils")

    assert not old_project.exists()
    assert isinstance(finance, ModuleType)
    assert isinstance(legacy, ModuleType)
    assert finance is sys.modules["nohiki_finance"]
    assert legacy is sys.modules["nohiki_domain_utils"]
    assert finance is not legacy
    assert finance.__name__ == "nohiki_finance"
    assert legacy.__name__ == "nohiki_domain_utils"
