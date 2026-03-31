"""Cross-boundary contracts between wire compensation enums and finance policy."""

from nohiki.common.v1 import CurrencyCode, PaymentFrequency
from nohiki_finance import ISO_4217_EXPONENTS, PayPeriod

WIRE_CURRENCY_TO_ISO = {
    CurrencyCode.USD: "USD",
    CurrencyCode.EUR: "EUR",
    CurrencyCode.GBP: "GBP",
    CurrencyCode.CAD: "CAD",
    CurrencyCode.AUD: "AUD",
    CurrencyCode.CHF: "CHF",
    CurrencyCode.NZD: "NZD",
    CurrencyCode.SGD: "SGD",
    CurrencyCode.INR: "INR",
    CurrencyCode.AED: "AED",
    CurrencyCode.ILS: "ILS",
}
WIRE_FREQUENCY_TO_PAY_PERIOD = {
    PaymentFrequency.HOURLY: PayPeriod.HOURLY,
    PaymentFrequency.DAILY: PayPeriod.DAILY,
    PaymentFrequency.WEEKLY: PayPeriod.WEEKLY,
    PaymentFrequency.BIWEEKLY: PayPeriod.BIWEEKLY,
    PaymentFrequency.MONTHLY: PayPeriod.MONTHLY,
    PaymentFrequency.ANNUALLY: PayPeriod.ANNUALLY,
}
UNSUPPORTED_WIRE_FREQUENCIES: frozenset[PaymentFrequency] = frozenset()


def test_every_wire_currency_has_a_deliberate_supported_iso_mapping() -> None:
    concrete_wire_currencies = set(CurrencyCode) - {CurrencyCode.UNSPECIFIED}

    assert set(WIRE_CURRENCY_TO_ISO) == concrete_wire_currencies
    assert all(code in ISO_4217_EXPONENTS for code in WIRE_CURRENCY_TO_ISO.values())


def test_every_wire_payment_frequency_is_mapped_or_explicitly_unsupported() -> None:
    concrete_wire_frequencies = set(PaymentFrequency) - {PaymentFrequency.UNSPECIFIED}

    assert set(WIRE_FREQUENCY_TO_PAY_PERIOD).isdisjoint(UNSUPPORTED_WIRE_FREQUENCIES)
    assert set(WIRE_FREQUENCY_TO_PAY_PERIOD) | UNSUPPORTED_WIRE_FREQUENCIES == concrete_wire_frequencies
    assert all(isinstance(period, PayPeriod) for period in WIRE_FREQUENCY_TO_PAY_PERIOD.values())
