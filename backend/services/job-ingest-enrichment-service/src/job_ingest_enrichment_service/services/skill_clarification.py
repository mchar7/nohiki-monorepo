"""LLM-based skill clarification for uncertain matches."""

from __future__ import annotations

import asyncio
import functools
from dataclasses import dataclass
from typing import Annotated, Final

from nohiki.skill.v1 import (
    AliasLearned,
    SkillClarificationNeeded,
    SkillProposal,
    SkillProposed,
)
from nohiki_db_utils import create_event_metadata
from nohiki_kafka_client import Topics
from nohiki_llm_client import LLMClient, StructuredAgentConfig
from nohiki_observability import get_logger
from pydantic import BaseModel, ConfigDict, Field
from pydantic_ai import Agent
from uuid_utils.compat import uuid7

from job_ingest_enrichment_service.core.config import get_settings
from job_ingest_enrichment_service.core.kafka import kafka_client

logger = get_logger(__name__)


SYSTEM_PROMPT: Final[str] = """You are a skill canonicalization assistant for a job matching system.

For each skill requiring clarification, you must decide:
- **MATCH**: If ONE candidate is semantically equivalent to the raw skill
- **EXPAND**: If the raw skill implies MULTIPLE related canonical skills (e.g., "git" -> Git + GitHub)
- **NEW_SKILL**: If NONE of the candidates match the intended meaning

For ALL decisions, specify requirement_level (int):
- 0 = UNSPECIFIED (cannot determine)
- 1 = EXPOSURE (familiar with)
- 2 = WORKING (can use effectively) - DEFAULT
- 3 = PROFICIENT (strong skills)
- 4 = EXPERT (deep expertise)

Inferring Requirement Level:
- "5+ years Python" -> EXPERT (4)
- "experience with React" -> WORKING (2)
- "familiarity with Docker" -> EXPOSURE (1)
- "strong TypeScript skills" -> PROFICIENT (3)
- "nice to have: Kubernetes" -> WORKING (2), is_required=false

Critical Rules:
1. "k8s" and "kubernetes" are the SAME skill -> MATCH
2. "git" in DevOps context often implies Git + GitHub -> EXPAND
3. "React" and "React Native" are DIFFERENT skills
4. Only EXPAND when context clearly implies multiple skills
5. For NEW_SKILL, provide a standardized canonical name (lowercase, hyphens only)
6. NEVER select a skill ID from already_accepted_skill_ids (duplicate)
"""


class ExpandedSkillMatchSchema(BaseModel):
    """Schema for an expanded skill match."""

    model_config = ConfigDict(frozen=True, strict=True)

    canonical_skill_id: Annotated[str, Field(pattern=r"^[0-9a-f-]{36}$")]
    canonical_skill_name: Annotated[str, Field(min_length=1, max_length=200)]
    requirement_level: Annotated[int, Field(ge=0, le=4)]
    is_required: bool
    is_additional: bool
    confidence: Annotated[float, Field(ge=0.0, le=1.0)]


class SkillProposalSchema(BaseModel):
    """Schema for a new skill proposal."""

    model_config = ConfigDict(frozen=True, strict=True)

    canonical_name: Annotated[str, Field(min_length=1, max_length=100, pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")]
    display_name: Annotated[str, Field(min_length=1, max_length=200)]
    suggested_aliases: list[str] = Field(default_factory=list, max_length=5)
    category: str | None = None
    description: str | None = Field(default=None, max_length=500)
    reuse_level: str | None = Field(default=None, max_length=25)


class SkillDecisionSchema(BaseModel):
    """LLM decision for a single uncertain skill."""

    model_config = ConfigDict(frozen=True, strict=True)

    raw_skill: Annotated[str, Field(min_length=1, max_length=200)]
    decision: Annotated[str, Field(pattern=r"^(MATCH|EXPAND|NEW_SKILL)$")]

    # For MATCH
    matched_canonical_id: Annotated[str | None, Field(pattern=r"^[0-9a-f-]{36}$")] = None
    matched_canonical_name: Annotated[str | None, Field(max_length=200)] = None
    matched_requirement_level: Annotated[int, Field(ge=0, le=4)] = 2
    matched_is_required: bool = True

    # For EXPAND
    expanded_skills: list[ExpandedSkillMatchSchema] = Field(default_factory=list)

    # For NEW_SKILL
    proposed_skill: SkillProposalSchema | None = None
    proposed_requirement_level: Annotated[int, Field(ge=0, le=4)] = 2
    proposed_is_required: bool = True

    reasoning: Annotated[str, Field(max_length=500)]


class SkillClarificationResponse(BaseModel):
    """Batch response for all uncertain skills."""

    model_config = ConfigDict(frozen=True, strict=True)

    decisions: Annotated[list[SkillDecisionSchema], Field(min_length=1, max_length=100)]


_LLM_CLARIFICATION_CONFIDENCE: float = 0.9


@dataclass(slots=True)
class ClarificationContext:
    """Context for skill clarification."""

    job_title: str
    job_id: str
    confirmed_skills: list[str]
    already_accepted_skill_ids: set[str]
    description_excerpt: str


@dataclass(frozen=True, slots=True)
class AliasEventParams:
    """Parameters for publishing an AliasLearned event."""

    raw_skill: str
    canonical_id: str
    canonical_name: str
    job_id: str
    correlation_id: str


class SkillClarificationService:
    """Service for LLM-based skill clarification."""

    def __init__(self) -> None:
        """Initialize without constructing the provider model chain."""
        settings = get_settings()
        self._llm_client: LLMClient | None = LLMClient(settings.llm, chain="skill_clarification")
        self._settings = settings
        self._agent: Agent[ClarificationContext, SkillClarificationResponse] | None = None

    def _get_agent(self) -> Agent[ClarificationContext, SkillClarificationResponse]:
        """Build the model chain only when clarification first needs it."""
        if self._llm_client is None:
            msg = "Skill clarification service is closed"
            raise RuntimeError(msg)
        if self._agent is None:
            self._agent = self._llm_client.create_agent(
                StructuredAgentConfig(
                    deps_type=ClarificationContext,
                    output_type=SkillClarificationResponse,
                    system_prompt=SYSTEM_PROMPT,
                )
            )
        return self._agent

    async def close(self) -> None:
        """Close the client, retaining ownership if cleanup fails."""
        if self._llm_client is not None:
            await self._llm_client.close()
            self._llm_client = None
            self._agent = None

    async def clarify_skills(
        self,
        clarifications: list[SkillClarificationNeeded],
        context: ClarificationContext,
    ) -> list[SkillDecisionSchema]:
        """Clarify uncertain skills using LLM.

        Args:
            clarifications: List of skills needing clarification with candidates
            context: Job context for LLM decision-making

        Returns:
            List of validated skill decisions

        """
        prompt = self._build_prompt(clarifications, context)

        if self._llm_client is None:
            msg = "Skill clarification service is closed"
            raise RuntimeError(msg)
        result = await self._llm_client.run(
            self._get_agent(),
            prompt,
            deps=context,
        )

        return self._validate_decisions(result.output.decisions, clarifications, context)

    def _build_prompt(
        self,
        clarifications: list[SkillClarificationNeeded],
        context: ClarificationContext,
    ) -> str:
        """Build the LLM prompt for clarification."""
        lines = [
            "## Job Context",
            f"- Title: {context.job_title}",
            f"- Confirmed skills: {', '.join(context.confirmed_skills) or 'None'}",
            f"- Description: {context.description_excerpt[:300]}...",
            "",
            "## Already Accepted Skill IDs (DO NOT DUPLICATE)",
            ", ".join(sorted(context.already_accepted_skill_ids)) if context.already_accepted_skill_ids else "None",
            "",
            "## Skills Requiring Clarification",
            "",
        ]

        for clarification in clarifications:
            lines.append(f'### Skill: "{clarification.extracted_skill}"')
            if clarification.context_snippet:
                lines.append(f"Context: {clarification.context_snippet}")
            lines.append("Candidates:")
            for i, candidate in enumerate(clarification.candidate_skills, 1):
                marker = " [ALREADY ACCEPTED]" if candidate.skill_id in context.already_accepted_skill_ids else ""
                lines.append(
                    f"  {i}. {candidate.skill_name} "
                    f"(ID: {candidate.skill_id}, similarity: {candidate.similarity_score:.0%}){marker}"
                )
            lines.append("")

        return "\n".join(lines)

    def _validate_decisions(
        self,
        decisions: list[SkillDecisionSchema],
        clarifications: list[SkillClarificationNeeded],
        context: ClarificationContext,
    ) -> list[SkillDecisionSchema]:
        """Validate LLM decisions against provided candidates and duplicates.

        Filters out:
        - Decisions with hallucinated (non-existent) candidate IDs
        - Decisions that select already-accepted skills (duplicates)
        - EXPAND decisions where all expanded skills are invalid/duplicates

        Args:
            decisions: Raw decisions from LLM
            clarifications: Original clarification requests with valid candidates
            context: Context containing already_accepted_skill_ids

        Returns:
            List of validated decisions

        """
        valid_candidate_ids = self._collect_valid_candidate_ids(clarifications)
        validated: list[SkillDecisionSchema] = []

        for decision in decisions:
            validated_decision = self._validate_single_decision(decision, valid_candidate_ids, context)
            if validated_decision is not None:
                validated.append(validated_decision)

        return validated

    def _collect_valid_candidate_ids(self, clarifications: list[SkillClarificationNeeded]) -> set[str]:
        """Collect all valid candidate IDs from clarifications."""
        return {c.skill_id for clarification in clarifications for c in clarification.candidate_skills}

    def _validate_single_decision(
        self,
        decision: SkillDecisionSchema,
        valid_candidate_ids: set[str],
        context: ClarificationContext,
    ) -> SkillDecisionSchema | None:
        """Validate a single decision and return it or None if invalid."""
        match decision.decision:
            case "MATCH":
                return self._validate_match_decision(decision, valid_candidate_ids, context)
            case "EXPAND":
                return self._validate_expand_decision(decision, valid_candidate_ids, context)
            case _:
                return decision

    def _validate_match_decision(
        self,
        decision: SkillDecisionSchema,
        valid_candidate_ids: set[str],
        context: ClarificationContext,
    ) -> SkillDecisionSchema | None:
        """Validate a MATCH decision."""
        if decision.matched_canonical_id not in valid_candidate_ids:
            logger.warning(
                "LLM hallucinated candidate ID",
                raw_skill=decision.raw_skill,
                invalid_id=decision.matched_canonical_id,
            )
            return None
        if decision.matched_canonical_id in context.already_accepted_skill_ids:
            logger.warning(
                "LLM selected duplicate skill",
                raw_skill=decision.raw_skill,
                duplicate_id=decision.matched_canonical_id,
            )
            return None
        return decision

    def _validate_expand_decision(
        self,
        decision: SkillDecisionSchema,
        valid_candidate_ids: set[str],
        context: ClarificationContext,
    ) -> SkillDecisionSchema | None:
        """Validate an EXPAND decision and filter invalid expanded skills."""
        valid_expanded = [
            s
            for s in decision.expanded_skills
            if s.canonical_skill_id in valid_candidate_ids
            and s.canonical_skill_id not in context.already_accepted_skill_ids
        ]
        if not valid_expanded:
            logger.warning(
                "All expanded skills were invalid or duplicates",
                raw_skill=decision.raw_skill,
            )
            return None
        # Create new decision with filtered expanded skills
        return SkillDecisionSchema(
            raw_skill=decision.raw_skill,
            decision=decision.decision,
            expanded_skills=valid_expanded,
            reasoning=decision.reasoning,
        )

    async def publish_outcomes(
        self,
        decisions: list[SkillDecisionSchema],
        job_id: str,
        correlation_id: str,
    ) -> None:
        """Publish AliasLearned and SkillProposed events based on decisions.

        For EXPAND decisions, only the PRIMARY skill (is_additional=False)
        gets an alias. Additional skills are added to the job but do NOT
        create aliases (to avoid polluting the alias table).

        Args:
            decisions: Validated skill decisions
            job_id: Source job ID
            correlation_id: Correlation ID for event tracing

        """
        async with asyncio.TaskGroup() as tg:
            for d in decisions:
                tg.create_task(self._publish_decision_outcomes(d, job_id, correlation_id))

    async def _publish_decision_outcomes(
        self,
        decision: SkillDecisionSchema,
        job_id: str,
        correlation_id: str,
    ) -> None:
        """Publish outcomes for a single decision. Returns True on success."""
        try:
            service_name = self._settings.service_name

            match decision:
                case SkillDecisionSchema(decision="MATCH", matched_canonical_id=str(cid)) if cid:
                    params = AliasEventParams(
                        raw_skill=decision.raw_skill,
                        canonical_id=cid,
                        canonical_name=decision.matched_canonical_name or "",
                        job_id=job_id,
                        correlation_id=correlation_id,
                    )
                    await self._publish_alias_learned(params, service_name)
                case SkillDecisionSchema(decision="EXPAND", expanded_skills=[_, *_]):
                    await self._publish_expand_alias(decision, job_id, correlation_id, service_name)
                case SkillDecisionSchema(decision="NEW_SKILL", proposed_skill=p) if p:
                    await self._publish_skill_proposed(
                        proposal=p,
                        job_id=job_id,
                        correlation_id=correlation_id,
                        service_name=service_name,
                    )
        except Exception:
            logger.exception(
                "Failed to publish decision outcome",
                raw_skill=decision.raw_skill,
                decision_type=decision.decision,
            )
            raise

    async def _publish_expand_alias(
        self,
        decision: SkillDecisionSchema,
        job_id: str,
        correlation_id: str,
        service_name: str,
    ) -> None:
        """Publish alias for EXPAND decision - only for primary skill."""
        primary = next((s for s in decision.expanded_skills if not s.is_additional), None)
        if primary:
            params = AliasEventParams(
                raw_skill=decision.raw_skill,
                canonical_id=primary.canonical_skill_id,
                canonical_name=primary.canonical_skill_name,
                job_id=job_id,
                correlation_id=correlation_id,
            )
            await self._publish_alias_learned(params, service_name)

    async def _publish_alias_learned(self, params: AliasEventParams, service_name: str) -> None:
        """Publish AliasLearned event."""
        event = AliasLearned(
            metadata=create_event_metadata(service_name, params.correlation_id),
            alias_text=params.raw_skill,
            canonical_skill_id=params.canonical_id,
            canonical_skill_name=params.canonical_name,
            source_job_id=params.job_id,
            source="llm_clarification",
            confidence=_LLM_CLARIFICATION_CONFIDENCE,
        )
        await kafka_client.publish(Topics.SKILL_ALIAS_LEARNED, event)

        logger.info(
            "Published AliasLearned",
            alias=params.raw_skill,
            canonical=params.canonical_name,
        )

    async def _publish_skill_proposed(
        self,
        proposal: SkillProposalSchema,
        job_id: str,
        correlation_id: str,
        service_name: str,
    ) -> None:
        """Publish SkillProposed event."""
        event = SkillProposed(
            metadata=create_event_metadata(service_name, correlation_id),
            request_id=str(uuid7()),
            proposal=SkillProposal(
                canonical_name=proposal.canonical_name,
                display_name=proposal.display_name,
                suggested_aliases=list(proposal.suggested_aliases),
                category=proposal.category,
                description=proposal.description,
                reuse_level=proposal.reuse_level,
            ),
            source_job_id=job_id,
            source="llm_extraction",
        )
        await kafka_client.publish(Topics.SKILL_PROPOSED, event)

        logger.info(
            "Published SkillProposed",
            canonical_name=proposal.canonical_name,
        )


@functools.lru_cache(maxsize=1)
def get_skill_clarification_service() -> SkillClarificationService:
    """Get or create the skill clarification service singleton."""
    return SkillClarificationService()


async def close_skill_clarification_service() -> None:
    """Close and clear the cached clarification service if initialized."""
    if get_skill_clarification_service.cache_info().currsize:
        await get_skill_clarification_service().close()
    get_skill_clarification_service.cache_clear()
