"""Tests for nohiki_test_utils.sample_data.documents module."""

from __future__ import annotations

from nohiki_test_utils.sample_data.documents import BACKEND_ENGINEER_RESUME


class TestBackendEngineerResume:
    """Tests for BACKEND_ENGINEER_RESUME sample data."""

    def test_has_required_top_level_keys(self) -> None:
        """Resume dict contains all expected top-level sections."""
        expected_keys = {"personal_info", "summary", "experience", "education", "skills", "projects", "certifications"}
        assert set(BACKEND_ENGINEER_RESUME.keys()) == expected_keys

    def test_personal_info_has_name_and_email(self) -> None:
        """Personal info section contains name and email fields."""
        info = BACKEND_ENGINEER_RESUME["personal_info"]
        assert isinstance(info, dict)
        name = info["full_name"]
        assert isinstance(name, str)
        assert name
        email = info["email"]
        assert isinstance(email, str)
        assert "@" in email

    def test_experience_is_non_empty_list(self) -> None:
        """Experience section is a non-empty list of entries."""
        experience = BACKEND_ENGINEER_RESUME["experience"]
        assert isinstance(experience, list)
        assert len(experience) > 0

    def test_experience_entries_have_required_fields(self) -> None:
        """Each experience entry has company, position, and highlights."""
        experience = BACKEND_ENGINEER_RESUME["experience"]
        assert isinstance(experience, list)
        for entry in experience:
            assert isinstance(entry, dict)
            assert "company" in entry
            assert "position" in entry
            highlights = entry["highlights"]
            assert isinstance(highlights, list)
            assert len(highlights) > 0

    def test_skills_has_languages_and_frameworks(self) -> None:
        """Skills section contains languages and frameworks lists."""
        skills = BACKEND_ENGINEER_RESUME["skills"]
        assert isinstance(skills, dict)
        languages = skills["languages"]
        assert isinstance(languages, list)
        frameworks = skills["frameworks"]
        assert isinstance(frameworks, list)
        assert len(frameworks) > 0
        assert "Python" in languages

    def test_certifications_is_list(self) -> None:
        """Certifications section is a list."""
        certs = BACKEND_ENGINEER_RESUME["certifications"]
        assert isinstance(certs, list)
        assert len(certs) > 0
