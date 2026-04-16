"""Unit tests for processor_service module."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, patch

import pytest
from job_ingest_enrichment_service.services.enrichment_context import EnrichmentContext
from job_ingest_enrichment_service.services.processor_service import process_job_enrichment
from job_ingest_enrichment_service.services.proto_builders import (
    EmbeddingBundle,
    build_stored_listing_from_context,
)
from nohiki.common.v1 import JobBoardSource, ListingReference
from nohiki.job.ingest.v1 import DiscoveredListing
from nohiki.ml.v1 import DenseData, EmbeddingType, EmbeddingVector


def _create_discovered_listing() -> DiscoveredListing:
    """Create a DiscoveredListing for testing."""
    return DiscoveredListing(
        listing_url="https://example.com/job/123",
        source=JobBoardSource.LINKEDIN,
        external_id="ext-123",
        title="Software Engineer",
        company_name="Test Corp",
        description="Build amazing software",
        raw_skills=["Python", "Go"],
    )


def _create_enrichment_context(discovered: DiscoveredListing) -> EnrichmentContext:
    """Create an EnrichmentContext for testing."""
    return EnrichmentContext(
        listing_id="test-listing-id",
        listing_url="https://example.com/job/123",
        correlation_id="test-correlation-id",
        discovered_json=discovered.to_json(),
        cleaned_title="Software Engineer",
        cleaned_company="Test Corp",
        work_arrangement="HYBRID",
        employment_term="FULL_TIME",
        seniority_level="MID",
        language="en",
        min_experience_years=3,
        min_experience_source="inferred",
        min_experience_confidence=70,
        max_experience_years=5,
        max_experience_source="inferred",
        max_experience_confidence=70,
        compensation_min_amount=80_000,
        compensation_min_source="llm_inferred",
        compensation_min_confidence=70,
        compensation_max_amount=120_000,
        compensation_max_source="llm_inferred",
        compensation_max_confidence=70,
        compensation_currency="USD",
        compensation_period="ANNUALLY",
        compensation_reasoning="Based on market data",
        location_city="San Francisco",
        location_state="CA",
        location_country_code="USA",
        geocoded_lat=None,
        geocoded_lon=None,
    )


class TestBuildStoredListingFromContext:
    """Tests for build_stored_listing_from_context function."""

    def test_builds_stored_listing_with_all_fields(self) -> None:
        """Test building StoredListing from context."""
        discovered = _create_discovered_listing()
        ctx = _create_enrichment_context(discovered)

        skills_embedding = EmbeddingVector(
            embedding_type=EmbeddingType.DENSE,
            dense=DenseData(values=[0.1] * 1024),
            model_id="test-model",
            collection_version="v1",
            content_hash="skills-hash",
        )
        title_embedding = EmbeddingVector(
            embedding_type=EmbeddingType.DENSE,
            dense=DenseData(values=[0.2] * 1024),
            model_id="test-model",
            collection_version="v1",
            content_hash="title-hash",
        )
        retrieval_vectors = [
            EmbeddingVector(
                embedding_type=EmbeddingType.MUVERA,
                dense=DenseData(values=[0.3] * 8192),
                model_id="test-model",
                collection_version="v1",
                content_hash="muvera-hash",
            ),
        ]

        result = build_stored_listing_from_context(
            ctx=ctx,
            discovered_data=discovered,
            skill_requirements=[],
            embeddings=EmbeddingBundle(
                skills=skills_embedding,
                title=title_embedding,
                retrieval=retrieval_vectors,
            ),
        )

        assert result.title == "Software Engineer"
        assert result.company_name == "Test Corp"
        assert result.listing_url == "https://example.com/job/123"
        assert result.skills_embedding is not None
        assert result.title_embedding is not None
        assert len(result.retrieval_embeddings) == 1


class TestProcessJobEnrichment:
    """Tests for process_job_enrichment function."""

    @pytest.fixture
    def listing_ref(self) -> ListingReference:
        """Create a valid listing reference."""
        return ListingReference(
            listing_id=str(uuid.uuid4()),
            listing_url="https://example.com/job/123",
            source=JobBoardSource.LINKEDIN,
        )

    @pytest.fixture
    def discovered(self) -> DiscoveredListing:
        """Create a valid discovered listing."""
        return _create_discovered_listing()

    @pytest.mark.asyncio
    async def test_calls_extraction_agent(
        self,
        listing_ref: ListingReference,
        discovered: DiscoveredListing,
    ) -> None:
        """Test that process_job_enrichment calls the extraction agent."""
        from job_ingest_enrichment_service.schemas.extraction import (
            CompensationBoundEstimate,
            CompensationEstimate,
            ExperienceExtraction,
            ExperienceYearsBound,
            ExtractedSkill,
            JobExtractionSchema,
            LocationExtraction,
        )
        from nohiki.common.v1 import (
            CountryCode,
            CurrencyCode,
            EmploymentTerm,
            PaymentFrequency,
            SeniorityLevel,
            WorkArrangement,
        )
        from nohiki_llm_client import LLMResult
        from pydantic_ai.usage import RunUsage

        mock_extraction = JobExtractionSchema(
            cleaned_title="Software Engineer",
            cleaned_company="Test Corp",
            work_arrangement=WorkArrangement.HYBRID,
            employment_term=EmploymentTerm.FULL_TIME,
            seniority_level=SeniorityLevel.MID,
            language="en",
            experience=ExperienceExtraction(
                min_years=ExperienceYearsBound(years=3, source="inferred", confidence_percent=70),
                max_years=ExperienceYearsBound(years=5, source="inferred", confidence_percent=70),
            ),
            compensation_estimate=CompensationEstimate(
                min_amount=CompensationBoundEstimate(amount=80_000, source="llm_inferred", confidence_percent=70),
                max_amount=CompensationBoundEstimate(amount=120_000, source="llm_inferred", confidence_percent=70),
                currency=CurrencyCode.USD,
                period=PaymentFrequency.ANNUALLY,
                reasoning="Based on market data",
            ),
            location=LocationExtraction(
                city="San Francisco",
                state_province="CA",
                country_code=CountryCode.USA,
            ),
            skills=[
                ExtractedSkill(raw_skill="Python", relation_type="essential"),
                ExtractedSkill(raw_skill="AWS", relation_type="essential"),
                ExtractedSkill(raw_skill="PostgreSQL", relation_type="optional"),
            ],
        )

        mock_result = LLMResult(
            output=mock_extraction,
            usage=RunUsage(),
            model_used="gpt-4o-mini",
            duration_seconds=1.5,
        )

        with (
            patch(
                "job_ingest_enrichment_service.services.processor_service.run_extraction_agent",
                new_callable=AsyncMock,
                return_value=mock_result,
            ) as mock_agent,
            patch(
                "job_ingest_enrichment_service.services.processor_service.geocode_location",
                new_callable=AsyncMock,
                side_effect=lambda loc: loc,
            ),
            patch(
                "job_ingest_enrichment_service.services.processor_service.kafka_client",
            ) as mock_kafka_client,
        ):
            mock_kafka_client.publish = AsyncMock()
            result = await process_job_enrichment(
                discovered_data=discovered,
                listing_reference=listing_ref,
                correlation_id="test-corr",
            )

            assert result is not None
            assert result["title"] == "Software Engineer"
            assert result["company"] == "Test Corp"
            mock_agent.assert_called_once_with(discovered)
            mock_kafka_client.publish.assert_called_once()

    @pytest.mark.asyncio
    async def test_language_flows_through_context(
        self,
        listing_ref: ListingReference,
        discovered: DiscoveredListing,
    ) -> None:
        """Language from LLM extraction is preserved through EnrichmentContext."""
        from job_ingest_enrichment_service.schemas.extraction import (
            CompensationBoundEstimate,
            CompensationEstimate,
            ExtractedSkill,
            JobExtractionSchema,
            LocationExtraction,
        )
        from nohiki.common.v1 import (
            CountryCode,
            CurrencyCode,
            EmploymentTerm,
            PaymentFrequency,
            SeniorityLevel,
            WorkArrangement,
        )
        from nohiki_llm_client import LLMResult
        from pydantic_ai.usage import RunUsage

        mock_extraction = JobExtractionSchema(
            cleaned_title="Ingénieur Logiciel",
            cleaned_company="Société Générale",
            work_arrangement=WorkArrangement.HYBRID,
            employment_term=EmploymentTerm.FULL_TIME,
            seniority_level=SeniorityLevel.MID,
            language="fr-CA",
            skills=[
                ExtractedSkill(raw_skill="Python"),
                ExtractedSkill(raw_skill="Java"),
                ExtractedSkill(raw_skill="Docker"),
            ],
            compensation_estimate=CompensationEstimate(
                min_amount=CompensationBoundEstimate(amount=80_000, source="llm_inferred", confidence_percent=60),
                max_amount=CompensationBoundEstimate(amount=100_000, source="llm_inferred", confidence_percent=60),
                currency=CurrencyCode.USD,
                period=PaymentFrequency.ANNUALLY,
                reasoning="Mid-level SWE estimate.",
            ),
            location=LocationExtraction(country_code=CountryCode.CAN),
        )

        mock_result = LLMResult(
            output=mock_extraction,
            usage=RunUsage(),
            model_used="gpt-4o-mini",
            duration_seconds=1.0,
        )

        published_messages: list[object] = []

        async def capture_publish(_topic: object, message: object) -> None:
            published_messages.append(message)

        with (
            patch(
                "job_ingest_enrichment_service.services.processor_service.run_extraction_agent",
                new_callable=AsyncMock,
                return_value=mock_result,
            ),
            patch(
                "job_ingest_enrichment_service.services.processor_service.geocode_location",
                new_callable=AsyncMock,
                side_effect=lambda loc: loc,
            ),
            patch(
                "job_ingest_enrichment_service.services.processor_service.kafka_client",
            ) as mock_kafka_client,
        ):
            mock_kafka_client.publish = AsyncMock(side_effect=capture_publish)
            await process_job_enrichment(
                discovered_data=discovered,
                listing_reference=listing_ref,
                correlation_id="test-corr-lang",
            )

        assert len(published_messages) == 1
        from nohiki.skill.v1 import SkillNormalizationRequested

        skill_request = published_messages[0]
        assert isinstance(skill_request, SkillNormalizationRequested)

        # Deserialize context bytes to verify language was preserved end-to-end
        ctx = EnrichmentContext.from_bytes(skill_request.command.caller_context)
        assert ctx.language == "fr-CA"

    @pytest.mark.asyncio
    async def test_relation_type_maps_to_is_required(
        self,
        listing_ref: ListingReference,
        discovered: DiscoveredListing,
    ) -> None:
        """Only relation_type=='essential' propagates as is_required=True; optional and mentioned become False."""
        from job_ingest_enrichment_service.schemas.extraction import (
            CompensationBoundEstimate,
            CompensationEstimate,
            ExtractedSkill,
            JobExtractionSchema,
            LocationExtraction,
        )
        from nohiki.common.v1 import (
            CountryCode,
            CurrencyCode,
            EmploymentTerm,
            PaymentFrequency,
            SeniorityLevel,
            WorkArrangement,
        )
        from nohiki.skill.v1 import SkillNormalizationRequested
        from nohiki_llm_client import LLMResult
        from pydantic_ai.usage import RunUsage

        mock_extraction = JobExtractionSchema(
            cleaned_title="Software Engineer",
            cleaned_company="Test Corp",
            work_arrangement=WorkArrangement.HYBRID,
            employment_term=EmploymentTerm.FULL_TIME,
            seniority_level=SeniorityLevel.MID,
            language="en",
            skills=[
                ExtractedSkill(raw_skill="Python", relation_type="essential"),
                ExtractedSkill(raw_skill="Go", relation_type="optional"),
                ExtractedSkill(raw_skill="Rust", relation_type="mentioned"),
            ],
            compensation_estimate=CompensationEstimate(
                min_amount=CompensationBoundEstimate(amount=80_000, source="llm_inferred", confidence_percent=70),
                max_amount=CompensationBoundEstimate(amount=120_000, source="llm_inferred", confidence_percent=70),
                currency=CurrencyCode.USD,
                period=PaymentFrequency.ANNUALLY,
                reasoning="Mid-level SWE in US, estimated $80k-$120k range.",
            ),
            location=LocationExtraction(country_code=CountryCode.USA),
        )
        mock_result = LLMResult(
            output=mock_extraction, usage=RunUsage(), model_used="gpt-4o-mini", duration_seconds=1.0
        )

        published: list[object] = []

        async def capture(_t: object, m: object) -> None:
            published.append(m)

        with (
            patch(
                "job_ingest_enrichment_service.services.processor_service.run_extraction_agent",
                new_callable=AsyncMock,
                return_value=mock_result,
            ),
            patch(
                "job_ingest_enrichment_service.services.processor_service.geocode_location",
                new_callable=AsyncMock,
                side_effect=lambda loc: loc,
            ),
            patch(
                "job_ingest_enrichment_service.services.processor_service.kafka_client",
            ) as mock_kafka,
        ):
            mock_kafka.publish = AsyncMock(side_effect=capture)
            await process_job_enrichment(
                discovered_data=discovered,
                listing_reference=listing_ref,
                correlation_id="test-corr-rel",
            )

        skill_request = published[0]
        assert isinstance(skill_request, SkillNormalizationRequested)
        levels = list(skill_request.raw_skills_with_levels)
        assert len(levels) == 3
        # Order matches the extraction schema input.
        assert levels[0].raw_skill == "Python"
        assert levels[0].is_required is True
        assert levels[1].raw_skill == "Go"
        assert levels[1].is_required is False
        assert levels[2].raw_skill == "Rust"
        assert levels[2].is_required is False

    @pytest.mark.asyncio
    async def test_fails_fast_when_extraction_yields_no_location(
        self,
        listing_ref: ListingReference,
        discovered: DiscoveredListing,
    ) -> None:
        """No city + UNSPECIFIED country must raise before any embedding/skill traffic."""
        from job_ingest_enrichment_service.schemas.extraction import (
            CompensationBoundEstimate,
            CompensationEstimate,
            ExtractedSkill,
            JobExtractionSchema,
            LocationExtraction,
        )
        from nohiki.common.v1 import (
            CountryCode,
            CurrencyCode,
            EmploymentTerm,
            PaymentFrequency,
            SeniorityLevel,
            WorkArrangement,
        )
        from nohiki_common_exceptions import ValidationError
        from nohiki_llm_client import LLMResult
        from pydantic_ai.usage import RunUsage

        mock_extraction = JobExtractionSchema(
            cleaned_title="Software Engineer",
            cleaned_company="Test Corp",
            work_arrangement=WorkArrangement.UNSPECIFIED,
            employment_term=EmploymentTerm.FULL_TIME,
            seniority_level=SeniorityLevel.MID,
            language="en",
            skills=[ExtractedSkill(raw_skill="Python")],
            compensation_estimate=CompensationEstimate(
                min_amount=CompensationBoundEstimate(amount=80_000, source="llm_inferred", confidence_percent=70),
                max_amount=CompensationBoundEstimate(amount=120_000, source="llm_inferred", confidence_percent=70),
                currency=CurrencyCode.USD,
                period=PaymentFrequency.ANNUALLY,
                reasoning="Mid-level SWE in US, estimated $80k-$120k range.",
            ),
            location=LocationExtraction(country_code=CountryCode.UNSPECIFIED),
        )
        mock_result = LLMResult(
            output=mock_extraction, usage=RunUsage(), model_used="gpt-4o-mini", duration_seconds=1.0
        )

        with (
            patch(
                "job_ingest_enrichment_service.services.processor_service.run_extraction_agent",
                new_callable=AsyncMock,
                return_value=mock_result,
            ),
            patch(
                "job_ingest_enrichment_service.services.processor_service.kafka_client",
            ) as mock_kafka,
        ):
            mock_kafka.publish = AsyncMock()
            with pytest.raises(ValidationError):
                await process_job_enrichment(
                    discovered_data=discovered,
                    listing_reference=listing_ref,
                    correlation_id="test-corr-noloc",
                )
            mock_kafka.publish.assert_not_called()
