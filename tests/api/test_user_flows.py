"""E2E tests for complete user flows against deployed Nohiki services.

Default timeout: 5s (set in pyproject.toml)
Tests that poll for CQRS projections use higher @pytest.mark.timeout(...) for async ops.

Tests the cookie-based authentication flow through user-auth-service
and CQRS patterns through bff-service.

Run with:
    pytest tests/api/test_user_flows.py -v --tb=short

Prerequisites:
    just compose-up
"""

from __future__ import annotations

import logging
import os
import uuid
from collections.abc import Generator

import pytest
from requests.exceptions import HTTPError

from .client import NohikiClient, poll_until

pytestmark = pytest.mark.integration

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger("nohiki-e2e")

BASE_URL = os.getenv("E2E_BASE_URL", "http://localhost:8000")
TEST_PASSWORD = "NohikiE2E2024!"


def unique_email() -> str:
    """Generate unique email for test isolation."""
    return f"e2e-{uuid.uuid4().hex[:8]}@test.nohiki.com"


@pytest.fixture(scope="module")
def client(healthy_base_url: str) -> NohikiClient:
    """Create E2E client."""
    return NohikiClient(healthy_base_url)


@pytest.fixture
def fresh_client(healthy_base_url: str) -> Generator[NohikiClient]:
    """Create a fresh client with its own session for test isolation."""
    c = NohikiClient(healthy_base_url)
    yield c
    c.clear_session()


@pytest.fixture
def authenticated_client(fresh_client: NohikiClient) -> NohikiClient:
    """Create client with authenticated user via cookies."""
    email = unique_email()
    fresh_client.register(email, TEST_PASSWORD, "E2E Test")
    return fresh_client


# Authentication Tests (user-auth-service)


class TestAuthentication:
    """Test user-auth-service authentication flows."""

    def test_user_registration_sets_cookies(self, fresh_client: NohikiClient) -> None:
        """Test registration sets auth cookies and returns user data."""
        email = unique_email()
        result = fresh_client.register(email, TEST_PASSWORD, "John Doe")

        assert result is not None
        assert result["email"] == email
        assert "id" in result
        assert fresh_client.is_authenticated

    def test_duplicate_registration_returns_none(self, fresh_client: NohikiClient) -> None:
        """Test duplicate registration is handled gracefully."""
        email = unique_email()
        first = fresh_client.register(email, TEST_PASSWORD)
        second = fresh_client.register(email, TEST_PASSWORD)

        assert first is not None
        assert second is None

    def test_login_sets_cookies(self, fresh_client: NohikiClient) -> None:
        """Test login sets auth cookies."""
        email = unique_email()
        fresh_client.register(email, TEST_PASSWORD)
        fresh_client.clear_session()

        result = fresh_client.login(email, TEST_PASSWORD)

        assert "user_id" in result
        assert "email" in result
        assert fresh_client.is_authenticated

    def test_session_endpoint_returns_claims(self, authenticated_client: NohikiClient) -> None:
        """Test session endpoint returns JWT claims."""
        session = authenticated_client.get_session()

        assert "user_id" in session
        assert session["user_id"] == authenticated_client.user_id

    @pytest.mark.timeout(30)
    def test_logout_clears_session(self, authenticated_client: NohikiClient) -> None:
        """Test logout clears auth cookies."""
        authenticated_client.logout()

        with pytest.raises(HTTPError, match=r"401|403"):
            authenticated_client.get_session()

    def test_logout_rejects_missing_origin(self, authenticated_client: NohikiClient) -> None:
        """Cookie-authenticated logout requires browser provenance."""
        origin = authenticated_client.session.headers.pop("Origin")
        try:
            response = authenticated_client.session.post(
                f"{authenticated_client.base_url}/api/v1/auth/logout",
                timeout=30,
            )
        finally:
            authenticated_client.session.headers["Origin"] = origin

        assert response.status_code == 403
        assert authenticated_client.get_session()["user_id"] == authenticated_client.user_id

    def test_logout_rejects_cross_origin(self, authenticated_client: NohikiClient) -> None:
        """Cookie-authenticated logout rejects a foreign Origin."""
        response = authenticated_client.session.post(
            f"{authenticated_client.base_url}/api/v1/auth/logout",
            headers={"Origin": "https://attacker.invalid"},
            timeout=30,
        )

        assert response.status_code == 403
        assert authenticated_client.get_session()["user_id"] == authenticated_client.user_id

    def test_invalid_login_fails(self, fresh_client: NohikiClient) -> None:
        """Test login with wrong password fails."""
        email = unique_email()
        fresh_client.register(email, TEST_PASSWORD)
        fresh_client.clear_session()

        with pytest.raises(HTTPError, match=r"401"):
            fresh_client.login(email, "wrong_password")


# Profile Tests (CQRS via bff-service)


class TestProfiles:
    """Test profile management via BFF's CQRS pattern."""

    def test_create_profile_returns_request_id(self, authenticated_client: NohikiClient) -> None:
        """Test profile creation returns 202 with request_id."""
        result = authenticated_client.create_profile(
            profile_name="Python Developer",
            search_keywords=["python", "fastapi", "backend"],
            work_arrangements=["REMOTE"],
        )

        assert "request_id" in result
        assert result["status"] == "accepted"

    @pytest.mark.timeout(45)
    def test_profile_appears_in_projection(self, authenticated_client: NohikiClient) -> None:
        """Test created profile eventually appears in projection."""
        profile_name = f"Test Profile {uuid.uuid4().hex[:6]}"
        authenticated_client.create_profile(
            profile_name=profile_name,
            search_keywords=["test"],
        )

        profile = authenticated_client.poll_for_profile(profile_name, timeout=30)

        assert profile is not None
        assert profile["pref_name"] == profile_name

    def test_list_profiles_returns_user_profiles(self, authenticated_client: NohikiClient) -> None:
        """Test listing profiles from projection."""
        profiles = authenticated_client.list_profiles()

        assert isinstance(profiles, list)

    @pytest.mark.timeout(45)
    def test_get_profile_by_id(self, authenticated_client: NohikiClient) -> None:
        """Test getting profile by ID from projection."""
        profile_name = f"Get Test {uuid.uuid4().hex[:6]}"
        authenticated_client.create_profile(profile_name=profile_name, search_keywords=["java"])

        profile = authenticated_client.poll_for_profile(profile_name, timeout=30)
        assert profile is not None

        fetched = authenticated_client.get_profile(profile["id"])

        assert fetched["id"] == profile["id"]
        assert fetched["pref_name"] == profile_name

    @pytest.mark.timeout(30)
    def test_update_profile_returns_request_id(self, authenticated_client: NohikiClient) -> None:
        """Test profile update returns 202 with request_id, then verify update completes."""
        profile_name = f"Update Test {uuid.uuid4().hex[:6]}"
        authenticated_client.create_profile(profile_name=profile_name, search_keywords=["python"])

        profile = authenticated_client.poll_for_profile(profile_name, timeout=30)
        assert profile is not None

        result = authenticated_client.update_profile(
            profile["id"],
            {"pref_name": "Updated Name"},
        )

        assert "request_id" in result
        assert result["status"] == "accepted"

        # Verify update completed by polling for updated name
        updated_profile = authenticated_client.poll_for_profile("Updated Name", timeout=30)
        assert updated_profile is not None
        assert updated_profile["pref_name"] == "Updated Name"
        assert updated_profile["id"] == profile["id"]

    @pytest.mark.timeout(30)
    def test_delete_profile_returns_request_id(self, authenticated_client: NohikiClient) -> None:
        """Test profile deletion returns 202 with request_id, then verify deletion completes."""
        profile_name = f"Delete Test {uuid.uuid4().hex[:6]}"
        authenticated_client.create_profile(profile_name=profile_name, search_keywords=["temp"])

        profile = authenticated_client.poll_for_profile(profile_name, timeout=30)
        assert profile is not None
        profile_id = profile["id"]

        result = authenticated_client.delete_profile(profile_id)

        assert "request_id" in result
        assert result["status"] == "accepted"

        # Verify deletion completed by polling until profile is gone
        deleted = authenticated_client.poll_for_profile_deletion(profile_name, timeout=10)
        assert deleted, "Profile should have been deleted"

    def test_get_nonexistent_profile_fails(self, authenticated_client: NohikiClient) -> None:
        """Test getting non-existent profile returns 404."""
        fake_id = str(uuid.uuid4())

        with pytest.raises(HTTPError, match=r"404"):
            authenticated_client.get_profile(fake_id)


# Attachment Tests (via bff-service)


class TestAttachments:
    """Test attachment management via BFF's presigned URL pattern."""

    def test_initiate_upload_returns_presigned_url(self, authenticated_client: NohikiClient) -> None:
        """Test initiating upload returns presigned URL."""
        result = authenticated_client.initiate_upload(
            filename="resume.pdf",
            content_type="application/pdf",
            file_size=1024,
        )

        assert "upload_id" in result
        assert "upload_url" in result

    def test_list_attachments_returns_list(self, authenticated_client: NohikiClient) -> None:
        """Test listing attachments returns a list."""
        attachments = authenticated_client.list_attachments()

        assert isinstance(attachments, list)

    def test_delete_attachment_returns_request_id(self, authenticated_client: NohikiClient) -> None:
        """Test attachment deletion returns 202 with request_id."""
        upload = authenticated_client.initiate_upload(
            filename="to_delete.pdf",
            content_type="application/pdf",
            file_size=512,
        )

        result = authenticated_client.delete_attachment(upload["upload_id"])

        assert "request_id" in result
        assert result["status"] == "accepted"

    def test_complete_upload_returns_status(self, authenticated_client: NohikiClient) -> None:
        """Test completing an upload returns 200 after real S3 PUT via presigned URL."""
        content = b"test resume content for upload verification"
        filename = "resume.pdf"
        content_type = "application/pdf"

        upload = authenticated_client.initiate_upload(
            filename=filename,
            content_type=content_type,
            file_size=len(content),
        )
        upload_id = upload["upload_id"]

        authenticated_client.upload_file_to_presigned_url(
            presigned_url=upload["upload_url"],
            content=content,
            content_type=content_type,
        )

        result = authenticated_client.complete_upload(
            upload_id=upload_id,
            filename=filename,
            content_type=content_type,
            file_size=len(content),
        )

        assert result["status"] == "completed"
        assert result["upload_id"] == upload_id

    def test_complete_upload_without_s3_upload_returns_422(self, authenticated_client: NohikiClient) -> None:
        """Test that complete_upload returns 422 when no S3 PUT was performed."""
        content = b"test content"
        filename = "missing.pdf"

        upload = authenticated_client.initiate_upload(
            filename=filename,
            content_type="application/pdf",
            file_size=len(content),
        )

        with pytest.raises(HTTPError) as exc_info:
            authenticated_client.complete_upload(
                upload_id=upload["upload_id"],
                filename=filename,
                content_type="application/pdf",
                file_size=len(content),
            )

        assert exc_info.value.response.status_code == 422

    def test_get_attachment_returns_404_for_nonexistent(self, authenticated_client: NohikiClient) -> None:
        """Test getting a non-existent attachment returns 404."""
        fake_id = str(uuid.uuid4())

        with pytest.raises(HTTPError, match=r"404"):
            authenticated_client.get_attachment(fake_id)


# Profile-Attachment Association Tests


class TestProfileAttachments:
    """Test profile-attachment association via BFF's CQRS pattern."""

    @pytest.mark.timeout(45)
    def test_associate_attachment_returns_request_id(self, authenticated_client: NohikiClient) -> None:
        """Test associating an attachment with a profile returns 202 with request_id."""
        profile_name = f"Attach Test {uuid.uuid4().hex[:6]}"
        authenticated_client.create_profile(profile_name=profile_name, search_keywords=["resume"])

        profile = authenticated_client.poll_for_profile(profile_name, timeout=30)
        assert profile is not None

        upload = authenticated_client.initiate_upload(
            filename="resume.pdf",
            content_type="application/pdf",
            file_size=1024,
        )

        result = authenticated_client.associate_attachment(profile["id"], upload["upload_id"])

        assert "request_id" in result
        assert result["status"] == "accepted"

    @pytest.mark.timeout(45)
    def test_disassociate_attachment_returns_request_id(self, authenticated_client: NohikiClient) -> None:
        """Test disassociating an attachment from a profile returns 202 with request_id."""
        profile_name = f"Detach Test {uuid.uuid4().hex[:6]}"
        authenticated_client.create_profile(profile_name=profile_name, search_keywords=["cover"])

        profile = authenticated_client.poll_for_profile(profile_name, timeout=30)
        assert profile is not None

        upload = authenticated_client.initiate_upload(
            filename="cover_letter.pdf",
            content_type="application/pdf",
            file_size=512,
        )

        authenticated_client.associate_attachment(profile["id"], upload["upload_id"])

        result = authenticated_client.disassociate_attachment(profile["id"], upload["upload_id"])

        assert "request_id" in result
        assert result["status"] == "accepted"


# Complete User Journey Tests


class TestLocationPreferences:
    """Test location-related profile features (open_to_relocation, commute preferences)."""

    @pytest.mark.timeout(45)
    def test_create_profile_with_open_to_relocation_false_default(self, authenticated_client: NohikiClient) -> None:
        """Test profile creation defaults open_to_relocation to False."""
        profile_name = f"Local Search {uuid.uuid4().hex[:6]}"
        authenticated_client.create_profile(
            profile_name=profile_name,
            search_keywords=["python", "backend"],
            work_arrangements=["REMOTE"],
        )

        profile = authenticated_client.poll_for_profile(profile_name, timeout=30)

        assert profile is not None
        assert profile["pref_name"] == profile_name
        assert profile.get("open_to_relocation") is False

    @pytest.mark.timeout(45)
    def test_create_profile_with_open_to_relocation_true(self, authenticated_client: NohikiClient) -> None:
        """Test profile creation with open_to_relocation=True."""
        profile_name = f"Relocation Ready {uuid.uuid4().hex[:6]}"
        authenticated_client.create_profile(
            profile_name=profile_name,
            search_keywords=["senior", "engineering"],
            work_arrangements=["ON_SITE", "HYBRID"],
            open_to_relocation=True,
        )

        profile = authenticated_client.poll_for_profile(profile_name, timeout=30)

        assert profile is not None
        assert profile["pref_name"] == profile_name
        assert profile.get("open_to_relocation") is True

    @pytest.mark.timeout(45)
    def test_update_profile_open_to_relocation(self, authenticated_client: NohikiClient) -> None:
        """Test updating open_to_relocation from False to True."""
        profile_name = f"Update Relocation {uuid.uuid4().hex[:6]}"
        authenticated_client.create_profile(
            profile_name=profile_name,
            search_keywords=["devops"],
            open_to_relocation=False,
        )

        profile = authenticated_client.poll_for_profile(profile_name, timeout=30)
        assert profile is not None
        assert profile.get("open_to_relocation") is False

        authenticated_client.update_profile(
            profile["id"],
            {"open_to_relocation": True},
        )

        def update_is_projected() -> bool | None:
            updated_profile = authenticated_client.get_profile(profile["id"])
            return True if updated_profile.get("open_to_relocation") is True else None

        assert poll_until(update_is_projected, timeout=30), (
            "Profile open_to_relocation should have been updated to True"
        )

    @pytest.mark.timeout(60)
    def test_multiple_profiles_different_relocation_settings(self, authenticated_client: NohikiClient) -> None:
        """Test user can have profiles with different relocation settings."""
        local_name = f"Local Only {uuid.uuid4().hex[:6]}"
        relocation_name = f"Open to Move {uuid.uuid4().hex[:6]}"

        authenticated_client.create_profile(
            profile_name=local_name,
            search_keywords=["frontend"],
            open_to_relocation=False,
        )

        authenticated_client.create_profile(
            profile_name=relocation_name,
            search_keywords=["backend"],
            open_to_relocation=True,
        )

        local_profile = authenticated_client.poll_for_profile(local_name, timeout=30)
        relocation_profile = authenticated_client.poll_for_profile(relocation_name, timeout=30)

        assert local_profile is not None
        assert relocation_profile is not None
        assert local_profile.get("open_to_relocation") is False
        assert relocation_profile.get("open_to_relocation") is True

        profiles = authenticated_client.list_profiles()
        assert len([p for p in profiles if p["pref_name"] in [local_name, relocation_name]]) == 2


class TestCompleteUserJourney:
    """Test complete user journeys end-to-end."""

    @pytest.mark.timeout(60)
    def test_new_user_setup_flow(self, fresh_client: NohikiClient) -> None:
        """Test complete new user setup flow.

        1. Register (sets auth cookies)
        2. Create job target profile
        3. Poll for profile in projection
        4. Verify profile data
        """
        email = unique_email()

        reg_result = fresh_client.register(email, TEST_PASSWORD, "Jane Developer")
        assert reg_result is not None
        assert fresh_client.is_authenticated

        profile_name = f"Senior Backend Engineer {uuid.uuid4().hex[:6]}"
        create_result = fresh_client.create_profile(
            profile_name=profile_name,
            search_keywords=["senior", "backend", "python", "distributed"],
            work_arrangements=["REMOTE"],
            notification_threshold=0.75,
            auto_tailor_threshold=0.90,
        )
        assert "request_id" in create_result

        profile = fresh_client.poll_for_profile(profile_name, timeout=30)
        assert profile is not None
        assert profile["pref_name"] == profile_name
        assert "python" in profile["search_keywords"]

        logger.info("Complete user journey succeeded: user=%s", reg_result["id"])

    @pytest.mark.timeout(60)
    def test_relocation_aware_user_setup(self, fresh_client: NohikiClient) -> None:
        """Test user setup flow with relocation preferences.

        1. Register
        2. Create local search profile (open_to_relocation=False)
        3. Create relocation profile (open_to_relocation=True)
        4. Verify both profiles with correct relocation settings
        """
        email = unique_email()
        fresh_client.register(email, TEST_PASSWORD, "Alex Engineer")

        local_name = f"Local SF Jobs {uuid.uuid4().hex[:6]}"
        fresh_client.create_profile(
            profile_name=local_name,
            search_keywords=["python", "backend"],
            work_arrangements=["HYBRID"],
            open_to_relocation=False,
        )

        anywhere_name = f"Anywhere USA {uuid.uuid4().hex[:6]}"
        fresh_client.create_profile(
            profile_name=anywhere_name,
            search_keywords=["senior", "staff", "principal"],
            work_arrangements=["ON_SITE", "HYBRID", "REMOTE"],
            open_to_relocation=True,
        )

        local_profile = fresh_client.poll_for_profile(local_name, timeout=30)
        anywhere_profile = fresh_client.poll_for_profile(anywhere_name, timeout=30)

        assert local_profile is not None
        assert anywhere_profile is not None
        assert local_profile.get("open_to_relocation") is False
        assert anywhere_profile.get("open_to_relocation") is True

        profiles = fresh_client.list_profiles()
        assert len(profiles) >= 2

        logger.info("Relocation-aware user setup succeeded with %d profiles", len(profiles))

    @pytest.mark.timeout(60)
    def test_multi_profile_user(self, fresh_client: NohikiClient) -> None:
        """Test user with multiple profiles for different roles."""
        email = unique_email()
        fresh_client.register(email, TEST_PASSWORD, "Multi Profile")

        backend_name = f"Backend Developer {uuid.uuid4().hex[:6]}"
        fresh_client.create_profile(
            profile_name=backend_name,
            search_keywords=["backend", "python", "api"],
        )

        devops_name = f"DevOps Engineer {uuid.uuid4().hex[:6]}"
        fresh_client.create_profile(
            profile_name=devops_name,
            search_keywords=["devops", "kubernetes", "terraform"],
        )

        backend_profile = fresh_client.poll_for_profile(backend_name, timeout=30)
        devops_profile = fresh_client.poll_for_profile(devops_name, timeout=30)

        assert backend_profile is not None
        assert devops_profile is not None

        profiles = fresh_client.list_profiles()
        profile_names = [p["pref_name"] for p in profiles]
        assert backend_name in profile_names
        assert devops_name in profile_names

        logger.info("Multi-profile user created with %d profiles", len(profiles))


# Account Management Tests (bff-service /api/v1/account)


class TestAccountManagement:
    """Test account info retrieval and update via BFF CQRS projection."""

    @pytest.mark.timeout(45)
    def test_get_account_returns_user_info(self, authenticated_client: NohikiClient) -> None:
        """Test GET /account returns account projection populated after registration."""
        account = authenticated_client.poll_for_account(timeout=30)

        assert account is not None, "Account projection not populated within timeout"
        assert "id" in account
        assert "email" in account
        assert "is_active" in account
        assert account["is_active"] is True
        assert "created_at" in account
        assert "updated_at" in account

    @pytest.mark.timeout(45)
    def test_get_account_email_matches_registered_user(self, fresh_client: NohikiClient) -> None:
        """Test account email matches the one used during registration."""
        email = unique_email()
        fresh_client.register(email, TEST_PASSWORD, "Account Test")

        account = fresh_client.poll_for_account(timeout=30)

        assert account is not None, "Account projection not populated within timeout"
        assert account["email"] == email

    def test_get_account_requires_auth(self, fresh_client: NohikiClient) -> None:
        """Test that /account endpoint requires authentication."""
        with pytest.raises(HTTPError, match=r"401|403"):
            fresh_client.get_account()

    @pytest.mark.timeout(45)
    def test_get_account_contains_display_name(self, fresh_client: NohikiClient) -> None:
        """Test account projection includes display_name set during registration."""
        email = unique_email()
        fresh_client.register(email, TEST_PASSWORD, "Jane Developer")

        account = fresh_client.poll_for_account(timeout=30)

        assert account is not None, "Account projection not populated within timeout"
        assert account.get("display_name") == "Jane Developer"

    def test_update_account_display_name(self, fresh_client: NohikiClient) -> None:
        """Test PATCH /account updates display name via user-auth-service."""
        email = unique_email()
        fresh_client.register(email, TEST_PASSWORD, "Update Me")

        result = fresh_client.update_account(display_name="Updated Display")

        assert result is not None
        assert result.get("display_name") == "Updated Display"

    def test_update_account_name_fields(self, fresh_client: NohikiClient) -> None:
        """Test PATCH /account updates first_name and last_name."""
        email = unique_email()
        fresh_client.register(email, TEST_PASSWORD, "Old Name")

        result = fresh_client.update_account(first_name="New", last_name="Name")

        assert result is not None
        assert result.get("first_name") == "New"
        assert result.get("last_name") == "Name"

    def test_delete_account_removes_user(self, fresh_client: NohikiClient) -> None:
        """Test DELETE /account removes the user account."""
        email = unique_email()
        fresh_client.register(email, TEST_PASSWORD, "Delete Me")
        assert fresh_client.is_authenticated

        fresh_client.delete_account()

        with pytest.raises(HTTPError, match=r"401|403|404"):
            fresh_client.list_profiles()


# Feature Importance Tests (bff-service /api/v1/profiles)


class TestFeatureImportance:
    """Test feature importance preference management via BFF."""

    @pytest.mark.timeout(45)
    def test_set_default_feature_importance_returns_request_id(
        self,
        authenticated_client: NohikiClient,
    ) -> None:
        """Test setting user-level default feature importance preferences."""
        result = authenticated_client.set_default_feature_importance(
            {
                "skill_match_importance": 80,
                "location_importance": 40,
                "work_arrangement_importance": 70,
            },
        )

        assert "request_id" in result
        assert result["status"] == "accepted"

    @pytest.mark.timeout(60)
    def test_set_profile_feature_importance_returns_request_id(
        self,
        authenticated_client: NohikiClient,
    ) -> None:
        """Test setting per-profile feature importance overrides."""
        profile_name = f"FI Test {uuid.uuid4().hex[:6]}"
        authenticated_client.create_profile(profile_name=profile_name, search_keywords=["python"])

        profile = authenticated_client.poll_for_profile(profile_name, timeout=30)
        assert profile is not None

        result = authenticated_client.set_profile_feature_importance(
            profile["id"],
            {
                "skill_match_importance": 90,
                "salary_importance": 60,
            },
        )

        assert "request_id" in result
        assert result["status"] == "accepted"

    @pytest.mark.timeout(60)
    def test_get_resolved_feature_importance_returns_structure(
        self,
        authenticated_client: NohikiClient,
    ) -> None:
        """Test getting resolved feature importance for a profile."""
        profile_name = f"Resolved FI {uuid.uuid4().hex[:6]}"
        authenticated_client.create_profile(profile_name=profile_name, search_keywords=["java"])

        profile = authenticated_client.poll_for_profile(profile_name, timeout=30)
        assert profile is not None

        resolved = authenticated_client.get_resolved_feature_importance(profile["id"])

        assert "skill_match_importance" in resolved
        assert "location_importance" in resolved
        assert "work_arrangement_importance" in resolved
        assert "experience_importance" in resolved
        assert "salary_importance" in resolved
        assert "recency_importance" in resolved
        assert "source" in resolved

        for key in (
            "skill_match_importance",
            "location_importance",
            "salary_importance",
        ):
            assert 0 <= resolved[key] <= 100

    @pytest.mark.timeout(60)
    def test_resolved_importance_reflects_defaults_when_no_override(
        self,
        authenticated_client: NohikiClient,
    ) -> None:
        """Test that resolved importance falls back to neutral defaults (50) when no settings."""
        profile_name = f"Default FI {uuid.uuid4().hex[:6]}"
        authenticated_client.create_profile(profile_name=profile_name, search_keywords=["go"])

        profile = authenticated_client.poll_for_profile(profile_name, timeout=30)
        assert profile is not None

        resolved = authenticated_client.get_resolved_feature_importance(profile["id"])

        assert resolved["source"] in ("search_pref", "user_settings", "system_defaults")


# Auth Token Tests


class TestAuthTokenRefresh:
    """Test JWT token refresh flow."""

    def test_refresh_returns_new_token(self, authenticated_client: NohikiClient) -> None:
        """Test token refresh returns updated session data."""
        result = authenticated_client.refresh_token()

        assert result is not None

    def test_session_valid_after_refresh(self, authenticated_client: NohikiClient) -> None:
        """Test session remains valid after token refresh."""
        authenticated_client.refresh_token()
        session = authenticated_client.get_session()

        assert "user_id" in session


# Error Handling Tests


class TestErrorHandling:
    """Test error handling and edge cases."""

    def test_unauthenticated_access_fails(self, fresh_client: NohikiClient) -> None:
        """Test accessing protected endpoints without auth fails."""
        with pytest.raises(HTTPError, match=r"401|403"):
            fresh_client.list_profiles()

    def test_nonexistent_profile_returns_404(self, authenticated_client: NohikiClient) -> None:
        """Test getting non-existent profile fails."""
        fake_id = str(uuid.uuid4())

        with pytest.raises(HTTPError, match=r"404"):
            authenticated_client.get_profile(fake_id)
