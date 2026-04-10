"""Tests for sample_data.listings module."""

from __future__ import annotations

from uuid import UUID

from nohiki.common.v1 import LocationType, SeniorityLevel, WorkArrangement
from nohiki.job.listing.v1 import ListingSnapshot
from nohiki_test_utils.sample_data.listings import (
    DATA_SCIENTIST_REMOTE,
    DEVOPS_ENGINEER_HYBRID,
    DIRECTOR_ENGINEERING,
    ELECTRICIAN_ONSITE,
    FINANCIAL_ANALYST_HYBRID,
    HR_DIRECTOR_HYBRID,
    HVAC_TECHNICIAN,
    JUNIOR_FRONTEND_HYBRID,
    MARKETING_MANAGER_REMOTE,
    MID_SOFTWARE_ONSITE,
    NURSE_ICU_ONSITE,
    PHARMACIST_HYBRID,
    PHYSICAL_THERAPIST,
    SENIOR_PYTHON_REMOTE,
    STAFF_PLATFORM_HYBRID,
    VP_PRODUCT_REMOTE,
)

ALL_PERSONAS = [
    DATA_SCIENTIST_REMOTE,
    DEVOPS_ENGINEER_HYBRID,
    DIRECTOR_ENGINEERING,
    ELECTRICIAN_ONSITE,
    FINANCIAL_ANALYST_HYBRID,
    HR_DIRECTOR_HYBRID,
    HVAC_TECHNICIAN,
    JUNIOR_FRONTEND_HYBRID,
    MARKETING_MANAGER_REMOTE,
    MID_SOFTWARE_ONSITE,
    NURSE_ICU_ONSITE,
    PHARMACIST_HYBRID,
    PHYSICAL_THERAPIST,
    SENIOR_PYTHON_REMOTE,
    STAFF_PLATFORM_HYBRID,
    VP_PRODUCT_REMOTE,
]


class TestAllPersonasAreListingSnapshots:
    """Verify all personas are valid ListingSnapshot instances."""

    def test_all_are_listing_snapshots(self) -> None:
        """All exported personas are ListingSnapshot instances."""
        for persona in ALL_PERSONAS:
            assert isinstance(persona, ListingSnapshot)


class TestPersonaIds:
    """Tests for persona ID validity and uniqueness."""

    def test_all_have_valid_uuid_ids(self) -> None:
        """All personas have valid UUID IDs."""
        for persona in ALL_PERSONAS:
            UUID(persona.id)

    def test_all_ids_unique(self) -> None:
        """All persona IDs are unique."""
        ids = [p.id for p in ALL_PERSONAS]
        assert len(ids) == len(set(ids))


class TestPersonaRequiredFields:
    """Tests for required field presence."""

    def test_all_have_titles(self) -> None:
        """All personas have non-empty titles."""
        for persona in ALL_PERSONAS:
            assert persona.title
            assert len(persona.title) > 0

    def test_all_have_company_names(self) -> None:
        """All personas have non-empty company names."""
        for persona in ALL_PERSONAS:
            assert persona.company_name
            assert len(persona.company_name) > 0

    def test_all_have_descriptions(self) -> None:
        """All personas have non-empty descriptions."""
        for persona in ALL_PERSONAS:
            assert persona.description
            assert len(persona.description) > 50

    def test_all_have_listing_urls(self) -> None:
        """All personas have listing URLs."""
        for persona in ALL_PERSONAS:
            assert persona.listing_url
            assert persona.listing_url.startswith("https://")

    def test_all_have_required_skills(self) -> None:
        """All personas have at least one required skill."""
        for persona in ALL_PERSONAS:
            assert persona.required_skills
            assert len(persona.required_skills) >= 1


class TestRemotePersonas:
    """Tests for remote work personas."""

    REMOTE_PERSONAS = [
        SENIOR_PYTHON_REMOTE,
        DATA_SCIENTIST_REMOTE,
        MARKETING_MANAGER_REMOTE,
        VP_PRODUCT_REMOTE,
    ]

    def test_remote_personas_have_remote_arrangement(self) -> None:
        """Remote personas have REMOTE work arrangement."""
        for persona in self.REMOTE_PERSONAS:
            assert persona.work_arrangement == WorkArrangement.REMOTE

    def test_remote_personas_have_remote_location_type(self) -> None:
        """Remote personas have REMOTE location type."""
        for persona in self.REMOTE_PERSONAS:
            assert persona.location is not None
            assert persona.location.location_type == LocationType.REMOTE

    def test_remote_personas_have_no_city(self) -> None:
        """Remote personas have no city specified."""
        for persona in self.REMOTE_PERSONAS:
            assert persona.location is not None
            assert persona.location.city is None


class TestHybridPersonas:
    """Tests for hybrid work personas."""

    HYBRID_PERSONAS = [
        JUNIOR_FRONTEND_HYBRID,
        STAFF_PLATFORM_HYBRID,
        DEVOPS_ENGINEER_HYBRID,
        FINANCIAL_ANALYST_HYBRID,
        HR_DIRECTOR_HYBRID,
        PHARMACIST_HYBRID,
        DIRECTOR_ENGINEERING,
    ]

    def test_hybrid_personas_have_hybrid_arrangement(self) -> None:
        """Hybrid personas have HYBRID work arrangement."""
        for persona in self.HYBRID_PERSONAS:
            assert persona.work_arrangement == WorkArrangement.HYBRID

    def test_hybrid_personas_have_city(self) -> None:
        """Hybrid personas have a city specified."""
        for persona in self.HYBRID_PERSONAS:
            assert persona.location is not None
            assert persona.location.city is not None


class TestOnsitePersonas:
    """Tests for on-site work personas."""

    ONSITE_PERSONAS = [
        MID_SOFTWARE_ONSITE,
        NURSE_ICU_ONSITE,
        PHYSICAL_THERAPIST,
        ELECTRICIAN_ONSITE,
        HVAC_TECHNICIAN,
    ]

    def test_onsite_personas_have_onsite_arrangement(self) -> None:
        """On-site personas have ON_SITE work arrangement."""
        for persona in self.ONSITE_PERSONAS:
            assert persona.work_arrangement == WorkArrangement.ON_SITE

    def test_onsite_personas_have_city(self) -> None:
        """On-site personas have a city specified."""
        for persona in self.ONSITE_PERSONAS:
            assert persona.location is not None
            assert persona.location.city is not None


class TestSeniorityLevels:
    """Tests for seniority level consistency."""

    def test_junior_frontend_is_entry(self) -> None:
        """Junior frontend is entry level."""
        assert JUNIOR_FRONTEND_HYBRID.seniority_level == SeniorityLevel.ENTRY

    def test_senior_python_is_senior(self) -> None:
        """Senior Python engineer is senior level."""
        assert SENIOR_PYTHON_REMOTE.seniority_level == SeniorityLevel.SENIOR

    def test_staff_platform_is_staff(self) -> None:
        """Staff platform engineer is staff level."""
        assert STAFF_PLATFORM_HYBRID.seniority_level == SeniorityLevel.STAFF

    def test_director_is_director(self) -> None:
        """Director of engineering is director level."""
        assert DIRECTOR_ENGINEERING.seniority_level == SeniorityLevel.DIRECTOR

    def test_vp_is_vp(self) -> None:
        """VP of product is VP level."""
        assert VP_PRODUCT_REMOTE.seniority_level == SeniorityLevel.VP


class TestCompensation:
    """Tests for compensation data."""

    def test_all_have_compensation(self) -> None:
        """All personas have compensation data."""
        for persona in ALL_PERSONAS:
            assert persona.compensation is not None

    def test_compensation_min_less_than_max(self) -> None:
        """Compensation min is always less than max."""
        for persona in ALL_PERSONAS:
            comp = persona.compensation
            assert comp is not None
            assert comp.min_amount is not None
            assert comp.max_amount is not None
            assert comp.min_amount.amount.minor_units < comp.max_amount.amount.minor_units


class TestSkillRequirements:
    """Tests for skill requirement data."""

    def test_all_have_skill_requirements(self) -> None:
        """All personas have skill requirements generated."""
        for persona in ALL_PERSONAS:
            assert persona.skill_requirements
            assert len(persona.skill_requirements) > 0

    def test_skill_requirements_match_required_skills_count(self) -> None:
        """Skill requirements count matches required skills."""
        for persona in ALL_PERSONAS:
            assert len(persona.skill_requirements) == len(persona.required_skills)


class TestEmbeddings:
    """Tests for embedding data."""

    def test_all_have_skills_embedding(self) -> None:
        """All personas have skills embeddings."""
        for persona in ALL_PERSONAS:
            assert persona.skills_embedding is not None

    def test_all_have_title_embedding(self) -> None:
        """All personas have title embeddings."""
        for persona in ALL_PERSONAS:
            assert persona.title_embedding is not None

    def test_all_have_retrieval_embeddings(self) -> None:
        """All personas have retrieval embeddings."""
        for persona in ALL_PERSONAS:
            assert persona.retrieval_embeddings
            assert len(persona.retrieval_embeddings) > 0
