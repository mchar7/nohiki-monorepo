"""Currency inference from country codes.

Maps ISO 3166-1 alpha-3 country codes to ISO 4217 currency codes.
Used by provider mappers to infer currency when not explicitly provided.
"""

from __future__ import annotations

from nohiki.common.v1 import CountryCode, CurrencyCode

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


def infer_currency_from_country(country: CountryCode) -> CurrencyCode:
    """Infer currency from country code.

    Args:
        country: ISO 3166-1 alpha-3 country code.

    Returns:
        Corresponding currency code, or UNSPECIFIED if unknown.

    """
    return COUNTRY_TO_CURRENCY.get(country, CurrencyCode.UNSPECIFIED)


def parse_country_code(value: str) -> CountryCode:
    """Parse country string to CountryCode enum.

    Accepts ISO 3166-1 alpha-2 or alpha-3 codes (case-insensitive).

    Args:
        value: Country code string (e.g., "US", "USA", "us").

    Returns:
        Corresponding CountryCode, or UNSPECIFIED if not recognized.

    """
    if not value:
        return CountryCode.UNSPECIFIED
    return ISO2_TO_COUNTRY.get(value.lower().strip(), CountryCode.UNSPECIFIED)


def infer_currency_from_country_string(country_str: str) -> CurrencyCode:
    """Infer currency from a country code string.

    Combines parse_country_code and infer_currency_from_country.

    Args:
        country_str: Country code string (e.g., "US", "USA").

    Returns:
        Corresponding currency code, or UNSPECIFIED if unknown.

    """
    country = parse_country_code(country_str)
    return infer_currency_from_country(country)
