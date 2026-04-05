"""ISO 4217 currency exponent conversion."""

from decimal import ROUND_HALF_EVEN, Decimal

from ._iso_4217 import ISO_4217_EXPONENTS

_CURRENCY_CODE_LENGTH = 3


def _exponent(currency: str) -> int:
    if not isinstance(currency, str):
        msg = "Currency must be an uppercase ISO 4217 string"
        raise TypeError(msg)
    if not currency.isascii() or len(currency) != _CURRENCY_CODE_LENGTH or not currency.isupper():
        msg = f"Currency must be an uppercase ISO 4217 string: {currency!r}"
        raise ValueError(msg)
    try:
        return ISO_4217_EXPONENTS[currency]
    except KeyError:
        msg = f"Unsupported currency: {currency!r}"
        raise ValueError(msg) from None


def to_minor_units(major_units: Decimal, currency: str) -> int:
    """Convert a finite Decimal amount to integral ISO 4217 minor units.

    Values exactly halfway between minor units use round-half-even.

    Raises:
        TypeError: If the amount is not Decimal or currency is not str.
        ValueError: If the amount is non-finite or currency is invalid,
            unsupported, or has no ISO-defined minor unit.
    """
    if not isinstance(major_units, Decimal):
        msg = "Major-unit amount must be a Decimal"
        raise TypeError(msg)
    if not major_units.is_finite():
        msg = "Major-unit amount must be finite"
        raise ValueError(msg)
    factor = 10 ** _exponent(currency)
    return int((major_units * factor).to_integral_value(rounding=ROUND_HALF_EVEN))


def to_major_units(minor_units: int, currency: str) -> Decimal:
    """Convert integral minor units to an exact major-unit Decimal.

    Raises:
        TypeError: If minor units is not int (bool is rejected) or currency is
            not str.
        ValueError: If currency is invalid, unsupported, or has no ISO-defined
            minor unit.
    """
    if isinstance(minor_units, bool) or not isinstance(minor_units, int):
        msg = "Minor-unit amount must be an integer"
        raise TypeError(msg)
    return Decimal(minor_units).scaleb(-_exponent(currency))
