"""Tests for sample_data._common module."""

from __future__ import annotations

from uuid import UUID

from nohiki.common.v1 import (
    CountryCode,
    CurrencyCode,
    LocationPrecision,
    LocationSource,
    LocationType,
    NotificationChannel,
    NotificationFrequency,
    PaymentFrequency,
)
from nohiki.ml.v1 import EmbeddingType
from nohiki.skill.v1 import SkillProficiencyLevel, SkillProvenance
from nohiki_test_utils.sample_data._common import (
    COLLECTION_VERSION,
    DEFAULT_AUTO_TAILOR_THRESHOLD,
    DEFAULT_EMBEDDING_DIMS,
    DEFAULT_EXPERIENCE_IMPORTANCE,
    DEFAULT_LOCATION_IMPORTANCE,
    DEFAULT_MIN_FIT_SCORE_DISQUALIFY,
    DEFAULT_NOTIFICATION_THRESHOLD,
    DEFAULT_RECENCY_IMPORTANCE,
    DEFAULT_SALARY_IMPORTANCE,
    DEFAULT_SKILL_MATCH_IMPORTANCE,
    DEFAULT_WORK_ARRANGEMENT_IMPORTANCE,
    EVENT_METADATA_VERSION,
    SAMPLE_DATA_MODEL_ID,
    SKILL_EXTRACTION_CONFIDENCE,
    SKILL_PROVENANCE_CONFIDENCE,
    make_compensation_bound,
    make_compensation_range,
    make_embedding,
    make_entity_timestamps,
    make_event_metadata,
    make_location,
    make_monetary_amount,
    make_notification_config,
    make_raw_content_hash,
    make_remote_location,
    make_skill_requirements,
    make_user_skills,
    stable_uuid,
)
from nohiki_test_utils.sample_data._ids import FIXED_TIMESTAMP


class TestStableUuid:
    """Tests for stable_uuid function."""

    def test_returns_valid_uuid(self) -> None:
        """Stable UUID produces valid UUID string."""
        result = stable_uuid("test-seed")
        UUID(result)

    def test_deterministic_for_same_seed(self) -> None:
        """Same seed always produces same UUID."""
        first = stable_uuid("my-seed")
        second = stable_uuid("my-seed")
        assert first == second

    def test_different_for_different_seeds(self) -> None:
        """Different seeds produce different UUIDs."""
        first = stable_uuid("seed-a")
        second = stable_uuid("seed-b")
        assert first != second


class TestMakeRawContentHash:
    """Tests for make_raw_content_hash function."""

    def test_returns_hex_digest(self) -> None:
        """Returns valid hex string."""
        result = make_raw_content_hash("test")
        assert len(result) == 64
        assert all(c in "0123456789abcdef" for c in result)

    def test_deterministic(self) -> None:
        """Same input produces same hash."""
        first = make_raw_content_hash("content")
        second = make_raw_content_hash("content")
        assert first == second

    def test_different_inputs_different_hashes(self) -> None:
        """Different inputs produce different hashes."""
        first = make_raw_content_hash("content-a")
        second = make_raw_content_hash("content-b")
        assert first != second


class TestMakeLocation:
    """Tests for make_location function."""

    def test_physical_location_with_city_state(self) -> None:
        """Physical location includes city and state."""
        loc = make_location("San Francisco", "CA")
        assert loc.city == "San Francisco"
        assert loc.state_province == "CA"
        assert loc.country == CountryCode.USA
        assert loc.location_type == LocationType.PHYSICAL
        assert loc.precision == LocationPrecision.CITY_CENTER
        assert loc.source == LocationSource.JOB_POSTING

    def test_custom_country(self) -> None:
        """Location respects custom country code."""
        loc = make_location("Toronto", "ON", country=CountryCode.CAN)
        assert loc.country == CountryCode.CAN

    def test_custom_location_type_remote(self) -> None:
        """Location respects custom location type."""
        loc = make_location("Chicago", "IL", location_type=LocationType.REMOTE)
        assert loc.location_type == LocationType.REMOTE


class TestMakeRemoteLocation:
    """Tests for make_remote_location function."""

    def test_remote_location_has_no_city_state(self) -> None:
        """Remote location has None for city and state."""
        loc = make_remote_location()
        assert loc.city is None
        assert loc.state_province is None

    def test_remote_location_type(self) -> None:
        """Remote location has REMOTE type."""
        loc = make_remote_location()
        assert loc.location_type == LocationType.REMOTE

    def test_remote_location_precision(self) -> None:
        """Remote location has UNSPECIFIED precision."""
        loc = make_remote_location()
        assert loc.precision == LocationPrecision.UNSPECIFIED

    def test_remote_location_custom_country(self) -> None:
        """Remote location respects custom country."""
        loc = make_remote_location(country=CountryCode.GBR)
        assert loc.country == CountryCode.GBR


class TestMakeMonetaryAmount:
    """Tests for make_monetary_amount function."""

    def test_minor_units_and_currency(self) -> None:
        """Monetary amount includes units and default currency."""
        amount = make_monetary_amount(10000000)
        assert amount.minor_units == 10000000
        assert amount.currency == CurrencyCode.USD

    def test_custom_currency(self) -> None:
        """Monetary amount respects custom currency."""
        amount = make_monetary_amount(5000000, currency=CurrencyCode.EUR)
        assert amount.currency == CurrencyCode.EUR


class TestMakeCompensationBound:
    """Tests for make_compensation_bound function."""

    def test_bound_with_amount(self) -> None:
        """Compensation bound has nested amount."""
        bound = make_compensation_bound(12000000)
        assert bound.amount.minor_units == 12000000
        assert bound.amount.currency == CurrencyCode.USD


class TestMakeCompensationRange:
    """Tests for make_compensation_range function."""

    def test_range_with_min_max(self) -> None:
        """Compensation range has min and max bounds."""
        comp = make_compensation_range(10000000, 15000000)
        assert comp.min_amount is not None
        assert comp.max_amount is not None
        assert comp.min_amount.amount.minor_units == 10000000
        assert comp.max_amount.amount.minor_units == 15000000
        assert comp.frequency == PaymentFrequency.ANNUALLY


class TestMakeEmbedding:
    """Tests for make_embedding function."""

    def test_embedding_has_correct_dims(self) -> None:
        """Embedding has specified dimensions."""
        emb = make_embedding("seed", dims=16)
        assert emb.dense is not None
        assert len(emb.dense.values) == 16

    def test_embedding_default_dims(self) -> None:
        """Embedding uses default dimensions."""
        emb = make_embedding("seed")
        assert emb.dense is not None
        assert len(emb.dense.values) == DEFAULT_EMBEDDING_DIMS

    def test_embedding_values_in_range(self) -> None:
        """Embedding values are normalized to [-1, 1]."""
        emb = make_embedding("seed")
        assert emb.dense is not None
        for val in emb.dense.values:
            assert -1.0 <= val <= 1.0

    def test_embedding_deterministic(self) -> None:
        """Same seed produces same embedding."""
        first = make_embedding("seed")
        second = make_embedding("seed")
        assert first.dense is not None
        assert second.dense is not None
        assert first.dense.values == second.dense.values

    def test_embedding_model_id(self) -> None:
        """Embedding has correct model ID."""
        emb = make_embedding("seed")
        assert emb.model_id == SAMPLE_DATA_MODEL_ID

    def test_embedding_collection_version(self) -> None:
        """Embedding has correct collection version."""
        emb = make_embedding("seed")
        assert emb.collection_version == COLLECTION_VERSION

    def test_embedding_type(self) -> None:
        """Embedding respects specified type."""
        emb = make_embedding("seed", embedding_type=EmbeddingType.MUVERA)
        assert emb.embedding_type == EmbeddingType.MUVERA


class TestMakeSkillRequirements:
    """Tests for make_skill_requirements function."""

    def test_creates_requirements_for_each_skill(self, sample_skill_list: list[str]) -> None:
        """Creates one requirement per skill."""
        reqs = make_skill_requirements(sample_skill_list)
        assert len(reqs) == len(sample_skill_list)

    def test_skill_names_preserved(self, sample_skill_list: list[str]) -> None:
        """Skill names are preserved."""
        reqs = make_skill_requirements(sample_skill_list)
        names = [r.skill_name for r in reqs]
        assert names == sample_skill_list

    def test_skill_ids_are_valid_uuids(self, sample_skill_list: list[str]) -> None:
        """Skill IDs are valid UUIDs."""
        reqs = make_skill_requirements(sample_skill_list)
        for req in reqs:
            UUID(req.skill_id)

    def test_skill_proficiency_level(self, sample_skill_list: list[str]) -> None:
        """Skills have INTERMEDIATE proficiency."""
        reqs = make_skill_requirements(sample_skill_list)
        for req in reqs:
            assert req.proficiency_level == SkillProficiencyLevel.INTERMEDIATE

    def test_extraction_confidence(self, sample_skill_list: list[str]) -> None:
        """Skills have correct extraction confidence."""
        reqs = make_skill_requirements(sample_skill_list)
        for req in reqs:
            assert req.extraction_confidence == SKILL_EXTRACTION_CONFIDENCE


class TestMakeUserSkills:
    """Tests for make_user_skills function."""

    def test_creates_entries_for_each_skill(self, sample_skill_list: list[str]) -> None:
        """Creates one entry per skill."""
        entries = make_user_skills(sample_skill_list)
        assert len(entries) == len(sample_skill_list)

    def test_skill_proficiency_advanced(self, sample_skill_list: list[str]) -> None:
        """User skills have ADVANCED proficiency."""
        entries = make_user_skills(sample_skill_list)
        for entry in entries:
            assert entry.proficiency == SkillProficiencyLevel.ADVANCED

    def test_skill_provenance(self, sample_skill_list: list[str]) -> None:
        """User skills are USER_DECLARED."""
        entries = make_user_skills(sample_skill_list)
        for entry in entries:
            assert entry.provenance == SkillProvenance.USER_DECLARED

    def test_provenance_confidence(self, sample_skill_list: list[str]) -> None:
        """User skills have correct provenance confidence."""
        entries = make_user_skills(sample_skill_list)
        for entry in entries:
            assert entry.provenance_confidence == SKILL_PROVENANCE_CONFIDENCE

    def test_timestamps_set(self, sample_skill_list: list[str]) -> None:
        """User skills have declared_at and last_verified_at set."""
        entries = make_user_skills(sample_skill_list)
        for entry in entries:
            assert entry.declared_at == FIXED_TIMESTAMP
            assert entry.last_verified_at == FIXED_TIMESTAMP


class TestMakeEntityTimestamps:
    """Tests for make_entity_timestamps function."""

    def test_default_timestamp(self) -> None:
        """Uses FIXED_TIMESTAMP by default."""
        ts = make_entity_timestamps()
        assert ts.created_at == FIXED_TIMESTAMP
        assert ts.updated_at == FIXED_TIMESTAMP


class TestMakeNotificationConfig:
    """Tests for make_notification_config function."""

    def test_default_threshold(self) -> None:
        """Uses default notification threshold."""
        config = make_notification_config()
        assert config.threshold == DEFAULT_NOTIFICATION_THRESHOLD

    def test_default_frequency(self) -> None:
        """Uses DAILY frequency."""
        config = make_notification_config()
        assert config.frequency == NotificationFrequency.DAILY

    def test_email_method_enabled(self) -> None:
        """Email notification method is enabled."""
        config = make_notification_config()
        assert len(config.methods) == 1
        assert config.methods[0].enabled is True
        assert config.methods[0].channel == NotificationChannel.EMAIL


class TestMakeEventMetadata:
    """Tests for make_event_metadata function."""

    def test_event_metadata_fields(self) -> None:
        """Event metadata has all required fields."""
        meta = make_event_metadata(
            event_id="evt-123",
            source_service="test-service",
            correlation_id="corr-456",
        )
        assert meta.event_id == "evt-123"
        assert meta.source_service == "test-service"
        assert meta.correlation_id == "corr-456"
        assert meta.timestamp == FIXED_TIMESTAMP
        assert meta.version == EVENT_METADATA_VERSION


class TestConstants:
    """Tests for module-level constants."""

    def test_embedding_dims(self) -> None:
        """Default embedding dims is reasonable."""
        assert DEFAULT_EMBEDDING_DIMS == 8

    def test_confidence_scores_in_range(self) -> None:
        """Confidence scores are between 0 and 1."""
        assert 0.0 < SKILL_EXTRACTION_CONFIDENCE < 1.0
        assert 0.0 < SKILL_PROVENANCE_CONFIDENCE < 1.0

    def test_importance_weights_in_range(self) -> None:
        """Importance weights are percentages (0-100)."""
        weights = [
            DEFAULT_SKILL_MATCH_IMPORTANCE,
            DEFAULT_LOCATION_IMPORTANCE,
            DEFAULT_WORK_ARRANGEMENT_IMPORTANCE,
            DEFAULT_EXPERIENCE_IMPORTANCE,
            DEFAULT_SALARY_IMPORTANCE,
            DEFAULT_RECENCY_IMPORTANCE,
        ]
        for w in weights:
            assert 0 <= w <= 100

    def test_thresholds_in_range(self) -> None:
        """Thresholds are reasonable values."""
        assert 0 <= DEFAULT_MIN_FIT_SCORE_DISQUALIFY <= 100
        assert 0 <= DEFAULT_AUTO_TAILOR_THRESHOLD <= 100
        assert 0 <= DEFAULT_NOTIFICATION_THRESHOLD <= 100
