"""Shared numeric constants for enrichment processing.

Centralised here so processor_service, proto_builders, and extraction_agent
agree on a single conversion factor between MonetaryAmount.minor_units (proto)
and the major-unit currency amounts the LLM emits.
"""

from __future__ import annotations

from typing import Final

# Currencies with a 1:100 minor-to-major ratio (USD, EUR, GBP, ...) cover the
# vast majority of postings we ingest today. JPY, KRW (0 decimals) and BHD,
# KWD, OMR, JOD (3 decimals) need ISO 4217 exponent lookup: tracked under
# the upcoming ISO 4217 conversion work and not handled here.
MINOR_UNITS_PER_MAJOR: Final[int] = 100
