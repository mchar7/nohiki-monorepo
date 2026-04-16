"""Tests for skill clarification service."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from job_ingest_enrichment_service.services.skill_clarification import (
    ClarificationContext,
    ExpandedSkillMatchSchema,
    SkillClarificationService,
    SkillDecisionSchema,
    SkillProposalSchema,
    close_skill_clarification_service,
    get_skill_clarification_service,
)
from nohiki.skill.v1 import CandidateSkill, SkillClarificationNeeded

# Test UUIDs following the hex pattern [0-9a-f-]{36}
VALID_UUID_1 = "12345678-1234-1234-1234-123456789abc"
VALID_UUID_2 = "12345678-1234-1234-1234-123456789def"
VALID_UUID_3 = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
VALID_UUID_DUPLICATE = "99999999-8888-7777-6666-555555555555"
# Valid format but will be used as "hallucinated" ID not in candidates list
HALLUCINATED_UUID = "00000000-0000-0000-0000-000000000000"


class TestSkillDecisionSchema:
    """Tests for SkillDecisionSchema validation."""

    def test_match_decision_valid(self) -> None:
        """Test valid MATCH decision schema."""
        decision = SkillDecisionSchema(
            raw_skill="python",
            decision="MATCH",
            matched_canonical_id=VALID_UUID_1,
            matched_canonical_name="Python",
            matched_requirement_level=3,
            matched_is_required=True,
            reasoning="Direct match for Python programming language",
        )
        assert decision.decision == "MATCH"
        assert decision.matched_requirement_level == 3
        assert decision.matched_is_required is True

    def test_match_decision_default_requirement_level(self) -> None:
        """Test that MATCH defaults to requirement_level=2."""
        decision = SkillDecisionSchema(
            raw_skill="python",
            decision="MATCH",
            matched_canonical_id=VALID_UUID_1,
            matched_canonical_name="Python",
            reasoning="Match",
        )
        assert decision.matched_requirement_level == 2  # Default

    def test_expand_decision_valid(self) -> None:
        """Test valid EXPAND decision schema."""
        decision = SkillDecisionSchema(
            raw_skill="git",
            decision="EXPAND",
            expanded_skills=[
                ExpandedSkillMatchSchema(
                    canonical_skill_id=VALID_UUID_1,
                    canonical_skill_name="Git",
                    requirement_level=2,
                    is_required=True,
                    is_additional=False,  # Primary
                    confidence=0.95,
                ),
                ExpandedSkillMatchSchema(
                    canonical_skill_id=VALID_UUID_2,
                    canonical_skill_name="GitHub",
                    requirement_level=2,
                    is_required=False,
                    is_additional=True,  # Additional
                    confidence=0.85,
                ),
            ],
            reasoning="Git in DevOps context implies both version control and GitHub usage",
        )
        assert decision.decision == "EXPAND"
        assert len(decision.expanded_skills) == 2
        assert not decision.expanded_skills[0].is_additional  # Primary
        assert decision.expanded_skills[1].is_additional  # Additional

    def test_new_skill_decision_valid(self) -> None:
        """Test valid NEW_SKILL decision schema."""
        decision = SkillDecisionSchema(
            raw_skill="prompt-engineering",
            decision="NEW_SKILL",
            proposed_skill=SkillProposalSchema(
                canonical_name="prompt-engineering",
                display_name="Prompt Engineering",
                suggested_aliases=["prompt design", "llm prompting"],
                category="artificial-intelligence",
                description="Designing effective prompts for LLMs",
            ),
            proposed_requirement_level=2,
            proposed_is_required=True,
            reasoning="Novel skill not in existing taxonomy",
        )
        assert decision.decision == "NEW_SKILL"
        assert decision.proposed_skill is not None
        assert decision.proposed_skill.canonical_name == "prompt-engineering"

    def test_invalid_decision_type_rejected(self) -> None:
        """Test that invalid decision types are rejected."""
        with pytest.raises(ValueError, match="String should match pattern"):
            SkillDecisionSchema(
                raw_skill="python",
                decision="INVALID",
                reasoning="Invalid",
            )

    def test_invalid_uuid_rejected(self) -> None:
        """Test that invalid UUIDs are rejected."""
        with pytest.raises(ValueError, match="String should match pattern"):
            SkillDecisionSchema(
                raw_skill="python",
                decision="MATCH",
                matched_canonical_id="not-a-uuid",
                reasoning="Invalid UUID",
            )


class TestExpandedSkillMatchSchema:
    """Tests for ExpandedSkillMatchSchema."""

    def test_requirement_level_valid_range(self) -> None:
        """Test requirement_level accepts values 0-4."""
        for level in range(5):
            schema = ExpandedSkillMatchSchema(
                canonical_skill_id=VALID_UUID_1,
                canonical_skill_name="Skill",
                requirement_level=level,
                is_required=True,
                is_additional=False,
                confidence=0.9,
            )
            assert schema.requirement_level == level

    def test_requirement_level_above_max_rejected(self) -> None:
        """Test requirement_level=5 is rejected."""
        with pytest.raises(ValueError, match="less than or equal to 4"):
            ExpandedSkillMatchSchema(
                canonical_skill_id=VALID_UUID_1,
                canonical_skill_name="Skill",
                requirement_level=5,
                is_required=True,
                is_additional=False,
                confidence=0.9,
            )

    def test_requirement_level_below_min_rejected(self) -> None:
        """Test requirement_level=-1 is rejected."""
        with pytest.raises(ValueError, match="greater than or equal to 0"):
            ExpandedSkillMatchSchema(
                canonical_skill_id=VALID_UUID_1,
                canonical_skill_name="Skill",
                requirement_level=-1,
                is_required=True,
                is_additional=False,
                confidence=0.9,
            )

    def test_confidence_valid_boundaries(self) -> None:
        """Test confidence accepts boundary values 0.0 and 1.0."""
        schema_min = ExpandedSkillMatchSchema(
            canonical_skill_id=VALID_UUID_1,
            canonical_skill_name="Skill",
            requirement_level=2,
            is_required=True,
            is_additional=False,
            confidence=0.0,
        )
        assert schema_min.confidence == pytest.approx(0.0)

        schema_max = ExpandedSkillMatchSchema(
            canonical_skill_id=VALID_UUID_1,
            canonical_skill_name="Skill",
            requirement_level=2,
            is_required=True,
            is_additional=False,
            confidence=1.0,
        )
        assert schema_max.confidence == pytest.approx(1.0)

    def test_confidence_above_max_rejected(self) -> None:
        """Test confidence > 1.0 is rejected."""
        with pytest.raises(ValueError, match="less than or equal to 1"):
            ExpandedSkillMatchSchema(
                canonical_skill_id=VALID_UUID_1,
                canonical_skill_name="Skill",
                requirement_level=2,
                is_required=True,
                is_additional=False,
                confidence=1.1,
            )

    def test_confidence_below_min_rejected(self) -> None:
        """Test confidence < 0.0 is rejected."""
        with pytest.raises(ValueError, match="greater than or equal to 0"):
            ExpandedSkillMatchSchema(
                canonical_skill_id=VALID_UUID_1,
                canonical_skill_name="Skill",
                requirement_level=2,
                is_required=True,
                is_additional=False,
                confidence=-0.1,
            )


class TestSkillProposalSchema:
    """Tests for SkillProposalSchema."""

    def test_canonical_name_valid_patterns(self) -> None:
        """Test canonical_name accepts valid lowercase-hyphen patterns."""
        schema1 = SkillProposalSchema(canonical_name="python", display_name="Python")
        assert schema1.canonical_name == "python"

        schema2 = SkillProposalSchema(canonical_name="machine-learning", display_name="Machine Learning")
        assert schema2.canonical_name == "machine-learning"

        schema3 = SkillProposalSchema(canonical_name="react-native", display_name="React Native")
        assert schema3.canonical_name == "react-native"

        schema4 = SkillProposalSchema(canonical_name="python3", display_name="Python 3")
        assert schema4.canonical_name == "python3"

    def test_canonical_name_uppercase_rejected(self) -> None:
        """Test canonical_name rejects uppercase letters."""
        with pytest.raises(ValueError, match="String should match pattern"):
            SkillProposalSchema(canonical_name="Python", display_name="Python")

    def test_canonical_name_spaces_rejected(self) -> None:
        """Test canonical_name rejects spaces."""
        with pytest.raises(ValueError, match="String should match pattern"):
            SkillProposalSchema(canonical_name="machine learning", display_name="Machine Learning")

    def test_canonical_name_underscores_rejected(self) -> None:
        """Test canonical_name rejects underscores."""
        with pytest.raises(ValueError, match="String should match pattern"):
            SkillProposalSchema(canonical_name="machine_learning", display_name="Machine Learning")


class TestClarificationContext:
    """Tests for ClarificationContext dataclass."""

    def test_context_creation(self) -> None:
        """Test context dataclass creation."""
        context = ClarificationContext(
            job_title="Senior Software Engineer",
            job_id="job-123",
            confirmed_skills=["Python", "Docker"],
            already_accepted_skill_ids={"uuid-1", "uuid-2"},
            description_excerpt="Looking for an experienced developer...",
        )
        assert len(context.already_accepted_skill_ids) == 2
        assert "uuid-1" in context.already_accepted_skill_ids
        assert context.job_title == "Senior Software Engineer"

    def test_context_with_empty_fields(self) -> None:
        """Test context with empty fields."""
        context = ClarificationContext(
            job_title="",
            job_id="",
            confirmed_skills=[],
            already_accepted_skill_ids=set(),
            description_excerpt="",
        )
        assert context.confirmed_skills == []
        assert context.already_accepted_skill_ids == set()


class TestValidateDecisions:
    """Tests for decision validation logic."""

    @pytest.fixture
    def service(self) -> SkillClarificationService:
        """Create a mocked service for testing validation methods."""
        with patch("job_ingest_enrichment_service.services.skill_clarification.get_settings") as mock_settings:
            mock_settings.return_value = MagicMock(
                llm=MagicMock(),
                service_name="test-service",
            )
            with patch("job_ingest_enrichment_service.services.skill_clarification.LLMClient"):
                return SkillClarificationService()

    def test_filters_invalid_candidate_ids(self, service: SkillClarificationService) -> None:
        """Test that hallucinated candidate IDs are filtered out."""
        decisions = [
            SkillDecisionSchema(
                raw_skill="python",
                decision="MATCH",
                matched_canonical_id=HALLUCINATED_UUID,
                matched_canonical_name="Python",
                reasoning="Match",
            ),
        ]

        clarifications = [
            SkillClarificationNeeded(
                extracted_skill="python",
                candidate_skills=[
                    CandidateSkill(
                        skill_id=VALID_UUID_3,
                        skill_name="Python",
                        similarity_score=0.7,
                    ),
                ],
            ),
        ]

        context = ClarificationContext(
            job_title="Engineer",
            job_id="job-1",
            confirmed_skills=[],
            already_accepted_skill_ids=set(),
            description_excerpt="",
        )

        validated = service._validate_decisions(decisions, clarifications, context)
        assert len(validated) == 0  # Invalid ID filtered

    def test_filters_duplicate_skill_ids(self, service: SkillClarificationService) -> None:
        """Test that duplicate skill IDs are filtered out."""
        decisions = [
            SkillDecisionSchema(
                raw_skill="python",
                decision="MATCH",
                matched_canonical_id=VALID_UUID_DUPLICATE,
                matched_canonical_name="Python",
                reasoning="Match",
            ),
        ]

        clarifications = [
            SkillClarificationNeeded(
                extracted_skill="python",
                candidate_skills=[
                    CandidateSkill(
                        skill_id=VALID_UUID_DUPLICATE,
                        skill_name="Python",
                        similarity_score=0.7,
                    ),
                ],
            ),
        ]

        context = ClarificationContext(
            job_title="Engineer",
            job_id="job-1",
            confirmed_skills=["Python"],
            already_accepted_skill_ids={VALID_UUID_DUPLICATE},
            description_excerpt="",
        )

        validated = service._validate_decisions(decisions, clarifications, context)
        assert len(validated) == 0  # Duplicate filtered

    def test_expand_filters_invalid_expanded_skills(self, service: SkillClarificationService) -> None:
        """Test that EXPAND filters invalid/duplicate expanded skills."""
        decisions = [
            SkillDecisionSchema(
                raw_skill="git",
                decision="EXPAND",
                expanded_skills=[
                    ExpandedSkillMatchSchema(
                        canonical_skill_id=VALID_UUID_3,
                        canonical_skill_name="Git",
                        requirement_level=2,
                        is_required=True,
                        is_additional=False,
                        confidence=0.95,
                    ),
                    ExpandedSkillMatchSchema(
                        canonical_skill_id=HALLUCINATED_UUID,  # Not in candidates
                        canonical_skill_name="GitHub",
                        requirement_level=2,
                        is_required=False,
                        is_additional=True,
                        confidence=0.85,
                    ),
                ],
                reasoning="Expand git",
            ),
        ]

        clarifications = [
            SkillClarificationNeeded(
                extracted_skill="git",
                candidate_skills=[
                    CandidateSkill(
                        skill_id=VALID_UUID_3,  # Only Git is valid
                        skill_name="Git",
                        similarity_score=0.7,
                    ),
                ],
            ),
        ]

        context = ClarificationContext(
            job_title="Engineer",
            job_id="job-1",
            confirmed_skills=[],
            already_accepted_skill_ids=set(),
            description_excerpt="",
        )

        validated = service._validate_decisions(decisions, clarifications, context)
        assert len(validated) == 1
        # Only the valid skill should remain
        assert len(validated[0].expanded_skills) == 1
        assert validated[0].expanded_skills[0].canonical_skill_name == "Git"

    def test_expand_rejected_if_all_skills_invalid(self, service: SkillClarificationService) -> None:
        """Test that EXPAND is rejected if ALL expanded skills are invalid."""
        different_uuid = "fedcba98-7654-3210-abcd-ef0123456789"
        decisions = [
            SkillDecisionSchema(
                raw_skill="git",
                decision="EXPAND",
                expanded_skills=[
                    ExpandedSkillMatchSchema(
                        canonical_skill_id=HALLUCINATED_UUID,
                        canonical_skill_name="Git",
                        requirement_level=2,
                        is_required=True,
                        is_additional=False,
                        confidence=0.95,
                    ),
                ],
                reasoning="Expand git",
            ),
        ]

        clarifications = [
            SkillClarificationNeeded(
                extracted_skill="git",
                candidate_skills=[
                    CandidateSkill(
                        skill_id=different_uuid,  # Different UUID
                        skill_name="Git",
                        similarity_score=0.7,
                    ),
                ],
            ),
        ]

        context = ClarificationContext(
            job_title="Engineer",
            job_id="job-1",
            confirmed_skills=[],
            already_accepted_skill_ids=set(),
            description_excerpt="",
        )

        validated = service._validate_decisions(decisions, clarifications, context)
        assert len(validated) == 0  # Entire decision rejected

    def test_new_skill_passes_without_validation(self, service: SkillClarificationService) -> None:
        """Test that NEW_SKILL decisions pass without candidate validation."""
        decisions = [
            SkillDecisionSchema(
                raw_skill="prompt-engineering",
                decision="NEW_SKILL",
                proposed_skill=SkillProposalSchema(
                    canonical_name="prompt-engineering",
                    display_name="Prompt Engineering",
                ),
                reasoning="New skill",
            ),
        ]

        clarifications = [
            SkillClarificationNeeded(
                extracted_skill="prompt-engineering",
                candidate_skills=[],  # No candidates
            ),
        ]

        context = ClarificationContext(
            job_title="Engineer",
            job_id="job-1",
            confirmed_skills=[],
            already_accepted_skill_ids=set(),
            description_excerpt="",
        )

        validated = service._validate_decisions(decisions, clarifications, context)
        assert len(validated) == 1
        assert validated[0].decision == "NEW_SKILL"

    def test_valid_match_passes_validation(self, service: SkillClarificationService) -> None:
        """Test that valid MATCH decisions pass validation."""
        decisions = [
            SkillDecisionSchema(
                raw_skill="python",
                decision="MATCH",
                matched_canonical_id=VALID_UUID_3,
                matched_canonical_name="Python",
                reasoning="Match",
            ),
        ]

        clarifications = [
            SkillClarificationNeeded(
                extracted_skill="python",
                candidate_skills=[
                    CandidateSkill(
                        skill_id=VALID_UUID_3,
                        skill_name="Python",
                        similarity_score=0.9,
                    ),
                ],
            ),
        ]

        context = ClarificationContext(
            job_title="Engineer",
            job_id="job-1",
            confirmed_skills=[],
            already_accepted_skill_ids=set(),
            description_excerpt="",
        )

        validated = service._validate_decisions(decisions, clarifications, context)
        assert len(validated) == 1
        assert validated[0].decision == "MATCH"
        assert validated[0].matched_canonical_id == VALID_UUID_3


class TestBuildPrompt:
    """Tests for prompt building logic."""

    @pytest.fixture
    def service(self) -> SkillClarificationService:
        """Create a mocked service for testing."""
        with patch("job_ingest_enrichment_service.services.skill_clarification.get_settings") as mock_settings:
            mock_settings.return_value = MagicMock(
                llm=MagicMock(),
                service_name="test-service",
            )
            with patch("job_ingest_enrichment_service.services.skill_clarification.LLMClient"):
                return SkillClarificationService()

    def test_build_prompt_includes_context(self, service: SkillClarificationService) -> None:
        """Test that prompt includes job context."""
        clarifications = [
            SkillClarificationNeeded(
                extracted_skill="python",
                candidate_skills=[
                    CandidateSkill(
                        skill_id=VALID_UUID_1,
                        skill_name="Python",
                        similarity_score=0.7,
                    ),
                ],
            ),
        ]

        context = ClarificationContext(
            job_title="Senior Engineer",
            job_id="job-123",
            confirmed_skills=["Docker", "Kubernetes"],
            already_accepted_skill_ids=set(),
            description_excerpt="We are looking for...",
        )

        prompt = service._build_prompt(clarifications, context)

        assert "Senior Engineer" in prompt
        assert "Docker, Kubernetes" in prompt

    def test_build_prompt_includes_already_accepted(self, service: SkillClarificationService) -> None:
        """Test that prompt includes already accepted skill IDs."""
        clarifications = [
            SkillClarificationNeeded(
                extracted_skill="python",
                candidate_skills=[
                    CandidateSkill(
                        skill_id=VALID_UUID_1,
                        skill_name="Python",
                        similarity_score=0.7,
                    ),
                ],
            ),
        ]

        context = ClarificationContext(
            job_title="Engineer",
            job_id="job-1",
            confirmed_skills=[],
            already_accepted_skill_ids={VALID_UUID_DUPLICATE, VALID_UUID_3},
            description_excerpt="",
        )

        prompt = service._build_prompt(clarifications, context)

        assert "Already Accepted Skill IDs" in prompt
        assert VALID_UUID_DUPLICATE in prompt
        assert VALID_UUID_3 in prompt

    def test_build_prompt_marks_already_accepted_candidates(self, service: SkillClarificationService) -> None:
        """Test that already-accepted candidates are marked."""
        clarifications = [
            SkillClarificationNeeded(
                extracted_skill="python",
                candidate_skills=[
                    CandidateSkill(
                        skill_id=VALID_UUID_DUPLICATE,
                        skill_name="Python",
                        similarity_score=0.9,
                    ),
                    CandidateSkill(
                        skill_id=VALID_UUID_1,
                        skill_name="Python 3",
                        similarity_score=0.7,
                    ),
                ],
            ),
        ]

        context = ClarificationContext(
            job_title="Engineer",
            job_id="job-1",
            confirmed_skills=[],
            already_accepted_skill_ids={VALID_UUID_DUPLICATE},
            description_excerpt="",
        )

        prompt = service._build_prompt(clarifications, context)

        assert "[ALREADY ACCEPTED]" in prompt

    def test_build_prompt_empty_already_accepted(self, service: SkillClarificationService) -> None:
        """Test prompt with no already-accepted skills."""
        clarifications = [
            SkillClarificationNeeded(
                extracted_skill="python",
                candidate_skills=[
                    CandidateSkill(
                        skill_id=VALID_UUID_1,
                        skill_name="Python",
                        similarity_score=0.7,
                    ),
                ],
            ),
        ]

        context = ClarificationContext(
            job_title="Engineer",
            job_id="job-1",
            confirmed_skills=[],
            already_accepted_skill_ids=set(),
            description_excerpt="",
        )

        prompt = service._build_prompt(clarifications, context)

        assert "[ALREADY ACCEPTED]" not in prompt
        # Should show "None" for already accepted
        assert "Already Accepted Skill IDs (DO NOT DUPLICATE)\nNone" in prompt


class TestPublishOutcomes:
    """Tests for publishing decision outcomes."""

    @pytest.fixture
    def service(self) -> SkillClarificationService:
        """Create a mocked service for testing."""
        with patch("job_ingest_enrichment_service.services.skill_clarification.get_settings") as mock_settings:
            mock_settings.return_value = MagicMock(
                llm=MagicMock(),
                service_name="test-service",
            )
            with patch("job_ingest_enrichment_service.services.skill_clarification.LLMClient"):
                return SkillClarificationService()

    @pytest.mark.asyncio
    async def test_publish_match_creates_alias(self, service: SkillClarificationService) -> None:
        """Test that MATCH decision publishes AliasLearned."""
        decisions = [
            SkillDecisionSchema(
                raw_skill="k8s",
                decision="MATCH",
                matched_canonical_id=VALID_UUID_1,
                matched_canonical_name="Kubernetes",
                reasoning="k8s is abbreviation for kubernetes",
            ),
        ]

        with patch("job_ingest_enrichment_service.services.skill_clarification.kafka_client") as mock_get_kafka:
            mock_get_kafka.publish = AsyncMock()

            await service.publish_outcomes(
                decisions=decisions,
                job_id="job-123",
                correlation_id="corr-123",
            )

            mock_get_kafka.publish.assert_called_once()
            call_args = mock_get_kafka.publish.call_args
            assert call_args[0][1].alias_text == "k8s"
            assert call_args[0][1].canonical_skill_name == "Kubernetes"

    @pytest.mark.asyncio
    async def test_publish_expand_creates_alias_only_for_primary(self, service: SkillClarificationService) -> None:
        """Test that EXPAND only creates alias for primary skill."""
        decisions = [
            SkillDecisionSchema(
                raw_skill="git",
                decision="EXPAND",
                expanded_skills=[
                    ExpandedSkillMatchSchema(
                        canonical_skill_id=VALID_UUID_1,
                        canonical_skill_name="Git",
                        requirement_level=2,
                        is_required=True,
                        is_additional=False,  # Primary
                        confidence=0.95,
                    ),
                    ExpandedSkillMatchSchema(
                        canonical_skill_id=VALID_UUID_2,
                        canonical_skill_name="GitHub",
                        requirement_level=2,
                        is_required=False,
                        is_additional=True,  # Additional - should NOT get alias
                        confidence=0.85,
                    ),
                ],
                reasoning="git implies both",
            ),
        ]

        with patch("job_ingest_enrichment_service.services.skill_clarification.kafka_client") as mock_get_kafka:
            mock_get_kafka.publish = AsyncMock()

            await service.publish_outcomes(
                decisions=decisions,
                job_id="job-123",
                correlation_id="corr-123",
            )

            # Should only publish one alias (for Git, not GitHub)
            assert mock_get_kafka.publish.call_count == 1
            call_args = mock_get_kafka.publish.call_args
            assert call_args[0][1].alias_text == "git"
            assert call_args[0][1].canonical_skill_name == "Git"

    @pytest.mark.asyncio
    async def test_publish_expand_no_alias_if_no_primary(self, service: SkillClarificationService) -> None:
        """Test that EXPAND with no primary skill doesn't create alias."""
        decisions = [
            SkillDecisionSchema(
                raw_skill="git",
                decision="EXPAND",
                expanded_skills=[
                    ExpandedSkillMatchSchema(
                        canonical_skill_id=VALID_UUID_1,
                        canonical_skill_name="Git",
                        requirement_level=2,
                        is_required=True,
                        is_additional=True,  # All are additional
                        confidence=0.95,
                    ),
                    ExpandedSkillMatchSchema(
                        canonical_skill_id=VALID_UUID_2,
                        canonical_skill_name="GitHub",
                        requirement_level=2,
                        is_required=False,
                        is_additional=True,
                        confidence=0.85,
                    ),
                ],
                reasoning="git implies both",
            ),
        ]

        with patch("job_ingest_enrichment_service.services.skill_clarification.kafka_client") as mock_get_kafka:
            mock_get_kafka.publish = AsyncMock()

            await service.publish_outcomes(
                decisions=decisions,
                job_id="job-123",
                correlation_id="corr-123",
            )

            # Should not publish any alias since all are additional
            mock_get_kafka.publish.assert_not_called()

    @pytest.mark.asyncio
    async def test_publish_new_skill_creates_proposal(self, service: SkillClarificationService) -> None:
        """Test that NEW_SKILL decision publishes SkillProposed."""
        decisions = [
            SkillDecisionSchema(
                raw_skill="prompt-engineering",
                decision="NEW_SKILL",
                proposed_skill=SkillProposalSchema(
                    canonical_name="prompt-engineering",
                    display_name="Prompt Engineering",
                    suggested_aliases=["prompt design"],
                    category="ai",
                    description="LLM prompt design",
                ),
                reasoning="Novel skill",
            ),
        ]

        with patch("job_ingest_enrichment_service.services.skill_clarification.kafka_client") as mock_get_kafka:
            mock_get_kafka.publish = AsyncMock()

            await service.publish_outcomes(
                decisions=decisions,
                job_id="job-123",
                correlation_id="corr-123",
            )

            mock_get_kafka.publish.assert_called_once()
            call_args = mock_get_kafka.publish.call_args
            assert call_args[0][1].proposal.canonical_name == "prompt-engineering"

    @pytest.mark.asyncio
    async def test_publish_multiple_decisions(self, service: SkillClarificationService) -> None:
        """Test publishing multiple decisions of different types."""
        decisions = [
            SkillDecisionSchema(
                raw_skill="k8s",
                decision="MATCH",
                matched_canonical_id=VALID_UUID_1,
                matched_canonical_name="Kubernetes",
                reasoning="abbreviation",
            ),
            SkillDecisionSchema(
                raw_skill="prompt-engineering",
                decision="NEW_SKILL",
                proposed_skill=SkillProposalSchema(
                    canonical_name="prompt-engineering",
                    display_name="Prompt Engineering",
                ),
                reasoning="Novel skill",
            ),
        ]

        with patch("job_ingest_enrichment_service.services.skill_clarification.kafka_client") as mock_get_kafka:
            mock_get_kafka.publish = AsyncMock()

            await service.publish_outcomes(
                decisions=decisions,
                job_id="job-123",
                correlation_id="corr-123",
            )

            assert mock_get_kafka.publish.call_count == 2


class TestGetSkillClarificationService:
    """Tests for singleton factory function."""

    def test_returns_singleton(self) -> None:
        """Test that get_skill_clarification_service returns the same instance via lru_cache."""
        # Clear the lru_cache before testing
        get_skill_clarification_service.cache_clear()

        with patch("job_ingest_enrichment_service.services.skill_clarification.get_settings") as mock_settings:
            mock_settings.return_value = MagicMock(
                llm=MagicMock(),
                service_name="test-service",
            )
            with patch("job_ingest_enrichment_service.services.skill_clarification.LLMClient"):
                service1 = get_skill_clarification_service()
                service2 = get_skill_clarification_service()

                assert service1 is service2

        # Clean up
        get_skill_clarification_service.cache_clear()

    def test_constructor_does_not_create_provider_agent(self) -> None:
        """Service construction retains a lazy client without allocating its model transport."""
        llm_client = MagicMock()

        with (
            patch(
                "job_ingest_enrichment_service.services.skill_clarification.get_settings",
                return_value=MagicMock(llm=MagicMock()),
            ),
            patch(
                "job_ingest_enrichment_service.services.skill_clarification.LLMClient",
                return_value=llm_client,
            ),
        ):
            service = SkillClarificationService()

        llm_client.create_agent.assert_not_called()
        assert service._agent is None

    @pytest.mark.asyncio
    async def test_service_close_awaits_public_llm_close(self) -> None:
        """The one-shot service delegates transport cleanup to LLMClient.close()."""
        llm_client = MagicMock(close=AsyncMock())

        with (
            patch(
                "job_ingest_enrichment_service.services.skill_clarification.get_settings",
                return_value=MagicMock(llm=MagicMock()),
            ),
            patch(
                "job_ingest_enrichment_service.services.skill_clarification.LLMClient",
                return_value=llm_client,
            ),
        ):
            service = SkillClarificationService()
            await service.close()

        llm_client.close.assert_awaited_once_with()

    @pytest.mark.asyncio
    async def test_lazy_agent_failure_remains_cached_and_closable(self) -> None:
        """Agent construction failure cannot orphan the client or its partial transports."""
        llm_client = MagicMock(close=AsyncMock())
        llm_client.create_agent.side_effect = RuntimeError("agent construction failed")
        get_skill_clarification_service.cache_clear()

        with (
            patch(
                "job_ingest_enrichment_service.services.skill_clarification.get_settings",
                return_value=MagicMock(llm=MagicMock()),
            ),
            patch(
                "job_ingest_enrichment_service.services.skill_clarification.LLMClient",
                return_value=llm_client,
            ),
        ):
            service = get_skill_clarification_service()
            assert get_skill_clarification_service() is service
            with pytest.raises(RuntimeError, match="agent construction failed"):
                service._get_agent()
            assert get_skill_clarification_service() is service
            await close_skill_clarification_service()

        llm_client.close.assert_awaited_once_with()
        assert get_skill_clarification_service.cache_info().currsize == 0

    @pytest.mark.asyncio
    async def test_lazy_agent_retry_then_close_recreates_service(self) -> None:
        """Failed lazy construction can retry; successful close permits fresh ownership."""
        agent = MagicMock()
        first_client = MagicMock(close=AsyncMock())
        first_client.create_agent.side_effect = [RuntimeError("try again"), agent]
        second_client = MagicMock(close=AsyncMock())
        get_skill_clarification_service.cache_clear()

        with (
            patch(
                "job_ingest_enrichment_service.services.skill_clarification.get_settings",
                return_value=MagicMock(llm=MagicMock()),
            ),
            patch(
                "job_ingest_enrichment_service.services.skill_clarification.LLMClient",
                side_effect=[first_client, second_client],
            ) as client_class,
        ):
            first_service = get_skill_clarification_service()
            with pytest.raises(RuntimeError, match="try again"):
                first_service._get_agent()
            assert first_service._get_agent() is agent
            await close_skill_clarification_service()
            second_service = get_skill_clarification_service()

        assert second_service is not first_service
        first_client.close.assert_awaited_once_with()
        assert client_class.call_count == 2
        get_skill_clarification_service.cache_clear()

    @pytest.mark.asyncio
    async def test_close_before_use_is_noop(self) -> None:
        """Shutdown does not instantiate an unused clarification service."""
        get_skill_clarification_service.cache_clear()
        with patch(
            "job_ingest_enrichment_service.services.skill_clarification.SkillClarificationService"
        ) as service_class:
            await close_skill_clarification_service()

        service_class.assert_not_called()

    @pytest.mark.asyncio
    async def test_close_is_idempotent_and_next_use_reconstructs(self) -> None:
        """The cached service closes once and the next use receives a fresh owner."""
        first = MagicMock(close=AsyncMock())
        second = MagicMock(close=AsyncMock())
        get_skill_clarification_service.cache_clear()

        with patch(
            "job_ingest_enrichment_service.services.skill_clarification.SkillClarificationService",
            side_effect=[first, second],
        ) as service_class:
            assert get_skill_clarification_service() is first
            await close_skill_clarification_service()
            await close_skill_clarification_service()
            assert get_skill_clarification_service() is second

        first.close.assert_awaited_once_with()
        second.close.assert_not_awaited()
        assert service_class.call_count == 2
        get_skill_clarification_service.cache_clear()

    @pytest.mark.asyncio
    async def test_close_failure_retains_owner_for_retry(self) -> None:
        """Failed cleanup preserves the cached owner so cleanup can be retried."""
        service = MagicMock(close=AsyncMock(side_effect=RuntimeError("close failed")))
        get_skill_clarification_service.cache_clear()

        with patch(
            "job_ingest_enrichment_service.services.skill_clarification.SkillClarificationService",
            return_value=service,
        ) as service_class:
            assert get_skill_clarification_service() is service
            with pytest.raises(RuntimeError, match="close failed"):
                await close_skill_clarification_service()
            assert get_skill_clarification_service() is service

        service.close.assert_awaited_once_with()
        service_class.assert_called_once_with()
        get_skill_clarification_service.cache_clear()


class TestCollectValidCandidateIds:
    """Tests for _collect_valid_candidate_ids helper."""

    @pytest.fixture
    def service(self) -> SkillClarificationService:
        """Create a mocked service for testing."""
        with patch("job_ingest_enrichment_service.services.skill_clarification.get_settings") as mock_settings:
            mock_settings.return_value = MagicMock(
                llm=MagicMock(),
                service_name="test-service",
            )
            with patch("job_ingest_enrichment_service.services.skill_clarification.LLMClient"):
                return SkillClarificationService()

    def test_collects_all_candidate_ids(self, service: SkillClarificationService) -> None:
        """Test that all candidate IDs are collected from all clarifications."""
        clarifications = [
            SkillClarificationNeeded(
                extracted_skill="python",
                candidate_skills=[
                    CandidateSkill(skill_id=VALID_UUID_1, skill_name="Python", similarity_score=0.9),
                    CandidateSkill(
                        skill_id=VALID_UUID_2,
                        skill_name="Python3",
                        similarity_score=0.8,
                    ),
                ],
            ),
            SkillClarificationNeeded(
                extracted_skill="java",
                candidate_skills=[
                    CandidateSkill(skill_id=VALID_UUID_3, skill_name="Java", similarity_score=0.9),
                ],
            ),
        ]

        valid_ids = service._collect_valid_candidate_ids(clarifications)

        assert valid_ids == {VALID_UUID_1, VALID_UUID_2, VALID_UUID_3}

    def test_collects_empty_from_no_candidates(self, service: SkillClarificationService) -> None:
        """Test that empty set is returned when no candidates."""
        clarifications = [
            SkillClarificationNeeded(
                extracted_skill="unknown-skill",
                candidate_skills=[],
            ),
        ]

        valid_ids = service._collect_valid_candidate_ids(clarifications)

        assert valid_ids == set()
