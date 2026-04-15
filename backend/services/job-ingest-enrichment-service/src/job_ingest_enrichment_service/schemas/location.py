"""Location extraction schema for job posting enrichment.

Parses raw location text into structured city/state/country with confidence tracking.
"""

from __future__ import annotations

from typing import Annotated

from nohiki.common.v1 import CountryCode
from nohiki_domain_utils import BetterprotoEnumAdapter
from pydantic import BaseModel, ConfigDict, Field, model_validator

type ConfidencePercent = Annotated[int, Field(ge=0, le=100)]

_country_adapter = BetterprotoEnumAdapter(exclude_unspecified=False)


class LocationExtraction(BaseModel):
    """Extracted location with precision tracking.

    Parse location from raw text carefully:
    - "San Francisco, CA" → city="San Francisco", state_province="California", country_code=USA
    - "Remote (US only)" → is_remote_eligible=True, country_code=USA
    - "London, UK" → city="London", country_code=GBR

    Always use ISO 3166-1 alpha-3 country codes (USA, CAN, GBR, DEU, etc.).
    """

    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
    )

    city: str | None = Field(
        default=None,
        max_length=100,
        description=(
            "City name as stated in the posting. None when not specified or fully remote. "
            "Use the canonical English name: 'San Francisco', 'London', 'Toronto'."
        ),
    )

    state_province: str | None = Field(
        default=None,
        max_length=100,
        description=(
            "State or province full name. Expand abbreviations: 'CA' → 'California', 'ON' → 'Ontario'. "
            "None when not specified or when the country has no state-level division (e.g., Singapore, UAE)."
        ),
    )

    country_code: Annotated[CountryCode, _country_adapter] = Field(
        default=CountryCode.UNSPECIFIED,
        description=(
            "ISO 3166-1 alpha-3 country code. "
            "REQUIRED when city or state_province is present. "
            "Infer from context when not stated: 'Tyler, TX' → USA | 'London' → GBR | 'Toronto' → CAN | "
            "'Sydney' → AUS | 'Berlin' → DEU | 'Singapore' → SGP. "
            "UNSPECIFIED only when there is genuinely no geographic information."
        ),
    )

    is_remote_eligible: bool = Field(
        default=False,
        description=(
            "True when the posting explicitly mentions remote work as an option -- "
            "e.g., 'remote', 'hybrid', 'work from home', 'remote-friendly'. "
            "False when not mentioned or explicitly on-site only."
        ),
    )

    confidence_percent: ConfidencePercent = Field(
        default=50,
        description=(
            "Confidence in the extracted location (0-100). "
            "100 when a full address is explicitly stated. "
            "70-90 when city and country are clear from context. "
            "40-60 when inferred from role/company rather than explicit mention."
        ),
    )

    @model_validator(mode="after")
    def validate_location_consistency(self) -> LocationExtraction:
        """Validate and fix location field consistency.

        If LLM returns city/state but UNSPECIFIED country, clear the city/state
        rather than failing. This handles cases where LLM hallucinates partial location.
        """
        if self.country_code == CountryCode.UNSPECIFIED:
            if self.city is not None:
                self.city = None
            if self.state_province is not None:
                self.state_province = None
        return self
