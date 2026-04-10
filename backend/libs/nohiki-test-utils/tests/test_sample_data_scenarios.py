"""Tests for sample_data.scenarios module."""

from __future__ import annotations

from nohiki.job.listing.v1 import ListingSnapshot
from nohiki.user.pref.v1 import SearchPrefSnapshot
from nohiki_test_utils.sample_data._types import MatchScenario
from nohiki_test_utils.sample_data.scenarios import (
    EXCELLENT_BACKEND_MATCH,
    EXCELLENT_DATA_SCIENCE_MATCH,
    GOOD_DEVOPS_MATCH,
    GOOD_FRONTEND_MATCH,
    POOR_MISMATCH_BACKEND_TO_FRONTEND,
    POOR_MISMATCH_FRONTEND_TO_BACKEND,
)

ALL_SCENARIOS = [
    EXCELLENT_BACKEND_MATCH,
    EXCELLENT_DATA_SCIENCE_MATCH,
    GOOD_DEVOPS_MATCH,
    GOOD_FRONTEND_MATCH,
    POOR_MISMATCH_BACKEND_TO_FRONTEND,
    POOR_MISMATCH_FRONTEND_TO_BACKEND,
]


class TestAllScenariosAreMatchScenarios:
    """Verify all scenarios are valid MatchScenario instances."""

    def test_all_are_match_scenarios(self) -> None:
        """All exported scenarios are MatchScenario instances."""
        for scenario in ALL_SCENARIOS:
            assert isinstance(scenario, MatchScenario)


class TestScenarioRequiredFields:
    """Tests for required field presence in scenarios."""

    def test_all_have_names(self) -> None:
        """All scenarios have non-empty names."""
        for scenario in ALL_SCENARIOS:
            assert scenario.name
            assert len(scenario.name) > 0

    def test_all_have_listings(self) -> None:
        """All scenarios have listing snapshots."""
        for scenario in ALL_SCENARIOS:
            assert scenario.listing is not None
            assert isinstance(scenario.listing, ListingSnapshot)

    def test_all_have_prefs(self) -> None:
        """All scenarios have preference snapshots."""
        for scenario in ALL_SCENARIOS:
            assert scenario.pref is not None
            assert isinstance(scenario.pref, SearchPrefSnapshot)

    def test_all_have_expected_quality(self) -> None:
        """All scenarios have expected quality labels."""
        for scenario in ALL_SCENARIOS:
            assert scenario.expected_quality
            assert scenario.expected_quality in ["excellent", "good", "fair", "poor"]

    def test_all_have_expected_score_range(self) -> None:
        """All scenarios have valid expected score ranges."""
        for scenario in ALL_SCENARIOS:
            assert scenario.expected_score_range is not None
            min_score, max_score = scenario.expected_score_range
            assert 0.0 <= min_score <= 1.0
            assert 0.0 <= max_score <= 1.0
            assert min_score < max_score

    def test_all_have_notes(self) -> None:
        """All scenarios have explanatory notes."""
        for scenario in ALL_SCENARIOS:
            assert scenario.notes
            assert len(scenario.notes) > 0


class TestScenarioQualityCategories:
    """Tests for scenario quality categorization."""

    def test_excellent_scenarios_have_high_score_ranges(self) -> None:
        """Excellent scenarios have score ranges >= 0.85."""
        excellent = [s for s in ALL_SCENARIOS if s.expected_quality == "excellent"]
        for scenario in excellent:
            min_score, _ = scenario.expected_score_range
            assert min_score >= 0.85

    def test_good_scenarios_have_mid_score_ranges(self) -> None:
        """Good scenarios have score ranges in 0.70-0.84 range."""
        good = [s for s in ALL_SCENARIOS if s.expected_quality == "good"]
        for scenario in good:
            min_score, max_score = scenario.expected_score_range
            assert min_score >= 0.70
            assert max_score <= 0.85

    def test_poor_scenarios_have_low_score_ranges(self) -> None:
        """Poor scenarios have score ranges <= 0.40."""
        poor = [s for s in ALL_SCENARIOS if s.expected_quality == "poor"]
        for scenario in poor:
            _, max_score = scenario.expected_score_range
            assert max_score <= 0.40


class TestSpecificScenarios:
    """Tests for specific scenario compositions."""

    def test_excellent_backend_match_composition(self) -> None:
        """Excellent backend match pairs senior Python job with backend pref."""
        scenario = EXCELLENT_BACKEND_MATCH
        assert "Python" in scenario.listing.title or "Backend" in scenario.listing.title
        assert scenario.pref.pref_name == "Backend Engineering Roles"
        assert scenario.expected_quality == "excellent"

    def test_excellent_data_science_match_composition(self) -> None:
        """Excellent data science match pairs data scientist job with DS pref."""
        scenario = EXCELLENT_DATA_SCIENCE_MATCH
        assert "Data Scientist" in scenario.listing.title or "Machine Learning" in scenario.listing.title
        assert scenario.pref.pref_name == "Data Science & ML Roles"
        assert scenario.expected_quality == "excellent"

    def test_good_frontend_match_composition(self) -> None:
        """Good frontend match pairs frontend job with frontend pref."""
        scenario = GOOD_FRONTEND_MATCH
        assert "Frontend" in scenario.listing.title or "React" in scenario.listing.title
        assert scenario.pref.pref_name == "Frontend Development Positions"
        assert scenario.expected_quality == "good"

    def test_good_devops_match_composition(self) -> None:
        """Good DevOps match pairs DevOps job with DevOps pref."""
        scenario = GOOD_DEVOPS_MATCH
        assert "DevOps" in scenario.listing.title or "Infrastructure" in scenario.listing.title
        assert scenario.pref.pref_name == "DevOps & Infrastructure"
        assert scenario.expected_quality == "good"

    def test_poor_backend_to_frontend_mismatch(self) -> None:
        """Poor mismatch pairs backend pref with frontend job."""
        scenario = POOR_MISMATCH_BACKEND_TO_FRONTEND
        assert "Frontend" in scenario.listing.title or "React" in scenario.listing.title
        assert scenario.pref.pref_name == "Backend Engineering Roles"
        assert scenario.expected_quality == "poor"

    def test_poor_frontend_to_backend_mismatch(self) -> None:
        """Poor mismatch pairs frontend pref with backend job."""
        scenario = POOR_MISMATCH_FRONTEND_TO_BACKEND
        assert "Python" in scenario.listing.title or "Backend" in scenario.listing.title
        assert scenario.pref.pref_name == "Frontend Development Positions"
        assert scenario.expected_quality == "poor"


class TestScenarioNamesUnique:
    """Tests for scenario name uniqueness."""

    def test_all_names_unique(self) -> None:
        """All scenario names are unique."""
        names = [s.name for s in ALL_SCENARIOS]
        assert len(names) == len(set(names))


class TestScenarioNotesQuality:
    """Tests for scenario notes quality and content."""

    def test_notes_explain_match_quality(self) -> None:
        """Scenario notes explain why the match quality is expected."""
        for scenario in ALL_SCENARIOS:
            notes_lower = scenario.notes.lower()
            quality = scenario.expected_quality
            if quality == "excellent":
                assert any(word in notes_lower for word in ["perfect", "strong", "excellent", "aligns", "matches"])
            elif quality == "poor":
                assert any(word in notes_lower for word in ["mismatch", "poor", "below", "too low"])

    def test_notes_mention_key_factors(self) -> None:
        """Scenario notes mention key matching factors."""
        for scenario in ALL_SCENARIOS:
            notes_lower = scenario.notes.lower()
            assert any(
                factor in notes_lower
                for factor in [
                    "skill",
                    "salary",
                    "seniority",
                    "location",
                    "work arrangement",
                    "remote",
                    "hybrid",
                ]
            )
