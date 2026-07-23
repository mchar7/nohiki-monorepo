"""Integration tests for skill clarification decisions.

Tests that the SkillClarificationService correctly:
- Selects appropriate candidates from provided options
- Expands skills when appropriate
- Proposes new skills when no match exists
- Provides meaningful reasoning
"""

from __future__ import annotations

from typing import Protocol

import pytest
from job_ingest_enrichment_service.services.skill_clarification import (
    ClarificationContext,
    get_skill_clarification_service,
)
from nohiki.skill.v1 import CandidateSkill, SkillClarificationNeeded

VALID_UUID_1 = "11111111-1111-1111-1111-111111111111"
VALID_UUID_2 = "22222222-2222-2222-2222-222222222222"
VALID_UUID_3 = "33333333-3333-3333-3333-333333333333"


class FailureLoggerProtocol(Protocol):
    """Protocol for failure logger type hints."""

    def log_exception(self, fixture: object, error: Exception) -> None: ...


def _create_test_context(
    job_title: str = "Software Engineer",
    confirmed_skills: list[str] | None = None,
) -> ClarificationContext:
    """Create a test clarification context."""
    return ClarificationContext(
        job_title=job_title,
        job_id="test-job-id",
        confirmed_skills=confirmed_skills or [],
        already_accepted_skill_ids=set(),
        description_excerpt="A technical role requiring programming skills.",
    )


def _create_clarification(
    extracted_skill: str,
    candidates: list[tuple[str, str, float]],
    context_snippet: str | None = None,
) -> SkillClarificationNeeded:
    """Create a test clarification request."""
    return SkillClarificationNeeded(
        extracted_skill=extracted_skill,
        position=0,
        candidate_skills=[
            CandidateSkill(
                skill_id=skill_id,
                skill_name=skill_name,
                similarity_score=score,
            )
            for skill_id, skill_name, score in candidates
        ],
        context_snippet=context_snippet,
    )


@pytest.mark.integration
@pytest.mark.slow
@pytest.mark.llm_cost
@pytest.mark.asyncio
class TestSkillClarificationDecisions:
    """Tests for skill clarification decision making."""

    async def test_single_skill_match_decision(
        self,
        failure_logger: FailureLoggerProtocol,
    ) -> None:
        """Test that service correctly matches a skill to a single candidate."""
        service = get_skill_clarification_service()
        context = _create_test_context()

        clarifications = [
            _create_clarification(
                extracted_skill="Python programming",
                candidates=[
                    (VALID_UUID_1, "Python", 0.92),
                    (VALID_UUID_2, "Python 3", 0.85),
                ],
                context_snippet="Experience with Python programming required",
            ),
        ]

        try:
            decisions = await service.clarify_skills(clarifications, context)

            assert len(decisions) == 1, "Expected one decision"
            decision = decisions[0]

            assert decision.decision in (
                "MATCH",
                "EXPAND",
            ), f"Expected MATCH or EXPAND, got {decision.decision}"

            if decision.decision == "MATCH":
                assert decision.matched_canonical_id in (
                    VALID_UUID_1,
                    VALID_UUID_2,
                ), "Matched ID not in provided candidates"

            assert decision.reasoning, "Decision should include reasoning"

        except Exception as e:
            pytest.fail(f"Skill clarification failed: {e}")

    async def test_skill_expansion_decision(
        self,
        failure_logger: FailureLoggerProtocol,
    ) -> None:
        """Test that service expands umbrella skills appropriately."""
        service = get_skill_clarification_service()
        context = _create_test_context(
            job_title="DevOps Engineer",
            confirmed_skills=["Linux", "Docker"],
        )

        clarifications = [
            _create_clarification(
                extracted_skill="CI/CD",
                candidates=[
                    (VALID_UUID_1, "Continuous Integration", 0.88),
                    (VALID_UUID_2, "Continuous Deployment", 0.85),
                    (VALID_UUID_3, "GitHub Actions", 0.75),
                ],
                context_snippet="Build and maintain CI/CD pipelines using GitHub Actions",
            ),
        ]

        try:
            decisions = await service.clarify_skills(clarifications, context)

            assert len(decisions) == 1, "Expected one decision"
            decision = decisions[0]

            assert decision.decision in (
                "MATCH",
                "EXPAND",
            ), f"Expected MATCH or EXPAND, got {decision.decision}"

            assert decision.reasoning, "Decision should include reasoning"

        except Exception as e:
            pytest.fail(f"Skill expansion failed: {e}")

    async def test_new_skill_proposal(
        self,
        failure_logger: FailureLoggerProtocol,
    ) -> None:
        """Test that service proposes new skill when no good match exists."""
        service = get_skill_clarification_service()
        context = _create_test_context(job_title="AI Engineer")

        clarifications = [
            _create_clarification(
                extracted_skill="Prompt Engineering",
                candidates=[],
                context_snippet="Design and optimize prompts for large language models",
            ),
        ]

        try:
            decisions = await service.clarify_skills(clarifications, context)

            assert len(decisions) == 1, "Expected one decision"
            decision = decisions[0]

            assert decision.decision == "NEW_SKILL", f"Expected NEW_SKILL for unmatched skill, got {decision.decision}"

            if decision.proposed_skill:
                assert decision.proposed_skill.canonical_name, "Proposed skill should have canonical name"
                assert decision.proposed_skill.display_name, "Proposed skill should have display name"

            assert decision.reasoning, "Decision should include reasoning"

        except Exception as e:
            pytest.fail(f"New skill proposal failed: {e}")

    async def test_multiple_clarifications_batch(
        self,
        failure_logger: FailureLoggerProtocol,
    ) -> None:
        """Test that service handles multiple clarifications in a batch."""
        service = get_skill_clarification_service()
        context = _create_test_context()

        clarifications = [
            _create_clarification(
                extracted_skill="JS",
                candidates=[
                    (VALID_UUID_1, "JavaScript", 0.90),
                ],
            ),
            _create_clarification(
                extracted_skill="TS",
                candidates=[
                    (VALID_UUID_2, "TypeScript", 0.88),
                ],
            ),
        ]

        try:
            decisions = await service.clarify_skills(clarifications, context)

            assert len(decisions) == 2, f"Expected 2 decisions, got {len(decisions)}"

            for decision in decisions:
                assert decision.decision in ("MATCH", "EXPAND", "NEW_SKILL"), (
                    f"Invalid decision type: {decision.decision}"
                )
                assert decision.reasoning, "Each decision should have reasoning"

        except Exception as e:
            pytest.fail(f"Batch clarification failed: {e}")

    async def test_respects_already_accepted_skills(
        self,
        failure_logger: FailureLoggerProtocol,
    ) -> None:
        """Test that service avoids selecting already-accepted skills."""
        service = get_skill_clarification_service()

        context = ClarificationContext(
            job_title="Full Stack Developer",
            job_id="test-job-id",
            confirmed_skills=["JavaScript"],
            already_accepted_skill_ids={VALID_UUID_1},
            description_excerpt="Full stack development with React and Node.js",
        )

        clarifications = [
            _create_clarification(
                extracted_skill="React.js",
                candidates=[
                    (VALID_UUID_1, "JavaScript", 0.70),
                    (VALID_UUID_2, "React", 0.95),
                ],
            ),
        ]

        try:
            decisions = await service.clarify_skills(clarifications, context)

            assert len(decisions) == 1, "Expected one decision"
            decision = decisions[0]

            if decision.decision == "MATCH":
                assert decision.matched_canonical_id != VALID_UUID_1, "Should not select already-accepted skill"

        except Exception as e:
            pytest.fail(f"Already-accepted skills handling failed: {e}")
