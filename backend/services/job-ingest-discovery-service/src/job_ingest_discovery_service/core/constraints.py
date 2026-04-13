"""Validation constraints mirroring proto buf.validate rules.

These constants must stay in sync with the proto definitions in
``proto/nohiki/job/ingest/v1/entities.proto``. Drift will cause
DiscoveredListing events to be rejected at the Kafka boundary by
buf.validate, blowing up entire discovery batches.
"""

from __future__ import annotations

from typing import Final

# Matches `(buf.validate.field).string.min_len = 200` on
# DiscoveredListing.description in proto/nohiki/job/ingest/v1/entities.proto.
# Listings without a meaningful description produce garbage enrichment
# (0 skills, hallucinated comp) and waste LLM tokens: reject at source.
MIN_DESCRIPTION_LENGTH: Final[int] = 200

# Matches `(buf.validate.field).string.min_len = 1` on
# DiscoveredListing.company_name and DiscoveredListing.location_raw.
MIN_COMPANY_NAME_LENGTH: Final[int] = 1
MIN_LOCATION_RAW_LENGTH: Final[int] = 1

# Matches `(buf.validate.field).string.max_len = 50000` on
# DiscoveredListing.description in proto/nohiki/job/ingest/v1/entities.proto.
MAX_DESCRIPTION_LENGTH: Final[int] = 50000

# Matches `(buf.validate.field).string.max_len = 500` on
# DiscoveredListing.company_name in proto/nohiki/job/ingest/v1/entities.proto.
MAX_COMPANY_NAME_LENGTH: Final[int] = 500

# Matches `(buf.validate.field).string.max_len = 500` on
# DiscoveredListing.location_raw in proto/nohiki/job/ingest/v1/entities.proto.
MAX_LOCATION_RAW_LENGTH: Final[int] = 500

# Matches `(buf.validate.field).string.max_len = 500` on
# DiscoveredListing.title in proto/nohiki/job/ingest/v1/entities.proto.
MAX_TITLE_LENGTH: Final[int] = 500

# Matches `(buf.validate.field).string.max_len = 2048` on
# DiscoveredListing.listing_url in proto/nohiki/job/ingest/v1/entities.proto.
MAX_LISTING_URL_LENGTH: Final[int] = 2048
