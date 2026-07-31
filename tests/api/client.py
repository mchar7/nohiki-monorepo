"""HTTP client for E2E testing against deployed Nohiki services.

Cookie-based authentication client using requests.Session.
All auth tokens are stored in HttpOnly cookies, not in request headers.
"""

from __future__ import annotations

import logging
import os
import time
from collections.abc import Callable
from typing import Any
from urllib.parse import urlsplit

import requests
from requests.exceptions import HTTPError, RequestException

logger = logging.getLogger("nohiki-e2e")

HTTP_UNAUTHORIZED = 401
HTTP_CONFLICT = 409
HTTP_NOT_FOUND = 404
HTTP_ACCEPTED = 202
DEFAULT_TIMEOUT = 30
HEALTH_REQUEST_TIMEOUT = (0.5, 1.0)
HEALTH_PROBE_ATTEMPTS = 3
HEALTH_PROBE_INTERVAL = 0.25
MAX_POLL_INTERVAL = 1.0
type JSONValue = None | bool | int | float | str | list[JSONValue] | dict[str, JSONValue]
type QueryValue = str | int

ACCOUNT_ENDPOINT = "/api/v1/account"
TEMPLATE_FAMILIES_ENDPOINT = "/api/v1/template-families"


def poll_until[T](
    probe: Callable[[], T | None],
    *,
    timeout: float,
    max_interval: float = 1.0,
) -> T | None:
    """Poll until a probe returns a result or its timeout expires.

    Polls immediately, then backs off from 100 ms to at most one second while
    bounding every sleep by the monotonic deadline.
    """
    deadline = time.monotonic() + timeout
    interval_cap = min(max_interval, MAX_POLL_INTERVAL)
    interval = min(0.1, interval_cap)
    while time.monotonic() < deadline:
        if (result := probe()) is not None:
            return result
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        time.sleep(min(interval, remaining))
        interval = min(interval * 2, interval_cap)
    return None


class NohikiClient:
    """Client for E2E testing against deployed Nohiki services.

    Uses cookie-based authentication via requests.Session.
    Auth tokens are stored in HttpOnly cookies, not headers.
    """

    def __init__(self, base_url: str = "http://localhost:8000") -> None:
        """Initialize client with gateway base URL and browser Origin."""
        self.base_url = base_url.rstrip("/")
        origin = os.getenv("E2E_ORIGIN", "http://localhost:5173").rstrip("/")
        parsed_origin = urlsplit(origin)
        if not parsed_origin.scheme or not parsed_origin.netloc or parsed_origin.path:
            msg = "E2E_ORIGIN must contain only a scheme and authority"
            raise ValueError(msg)
        self.origin = origin
        self.session = requests.Session()
        self.session.headers["Origin"] = self.origin
        self.user_id: str | None = None

    def _url(self, path: str) -> str:
        """Build full URL from path."""
        return f"{self.base_url}{path}"

    def _json_headers(self) -> dict[str, str]:
        """Get headers for JSON requests."""
        return {"Content-Type": "application/json", "Accept": "application/json"}

    def _request_with_auto_refresh(
        self,
        method: str,
        url: str,
        *,
        params: dict[str, QueryValue] | None = None,
    ) -> requests.Response:
        """Execute request with automatic token refresh on 401.

        If request returns 401 Unauthorized, attempts to refresh the access token
        using the refresh token cookie, then retries the original request once.
        """
        resp = self.session.request(method, url, params=params, timeout=DEFAULT_TIMEOUT)

        if resp.status_code == HTTP_UNAUTHORIZED and self.is_authenticated:
            logger.debug("Got 401, refreshing token...")
            try:
                refresh_url = self._url("/api/v1/auth/refresh")
                refresh_resp = self.session.post(refresh_url, timeout=DEFAULT_TIMEOUT)
                refresh_resp.raise_for_status()
                logger.debug("Token refreshed, retrying request")
                resp = self.session.request(method, url, params=params, timeout=DEFAULT_TIMEOUT)
            except HTTPError:
                logger.warning("Token refresh failed, returning original 401 response")

        return resp

    @property
    def is_authenticated(self) -> bool:
        """Check if client has auth cookies set."""
        return any("nohiki" in cookie.name for cookie in self.session.cookies)

    # Identity Service - /api/v1/auth

    def register(
        self,
        email: str,
        password: str,
        display_name: str = "Test Account",
    ) -> dict[str, Any] | None:
        """Register a new user with email, password, and display_name.

        On success, auth cookies are automatically set in the session.
        Returns user data or None if already exists.
        """
        url = self._url("/api/v1/auth/register")
        payload = {
            "email": email,
            "password": password,
            "display_name": display_name,
        }
        try:
            resp = self.session.post(url, json=payload, timeout=DEFAULT_TIMEOUT)
            resp.raise_for_status()
        except HTTPError as exc:
            if exc.response is not None and exc.response.status_code == HTTP_CONFLICT:
                logger.info("Account %s already exists", email)
                return None
            logger.exception(
                "Registration failed: %s",
                exc.response.text if exc.response is not None else "unknown",
            )
            raise
        else:
            data = resp.json()
            self.user_id = data.get("id")
            logger.info("Registered user: %s (ID: %s)", email, self.user_id)
            return data

    def login(self, email: str, password: str) -> dict[str, Any]:
        """Login user.

        Auth cookies are automatically set in the session.
        Returns user metadata (tokens are in HttpOnly cookies, not response body).
        """
        url = self._url("/api/v1/auth/login")
        payload = {"email": email, "password": password}
        resp = self.session.post(url, json=payload, timeout=DEFAULT_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
        self.user_id = data.get("user_id")
        logger.info("Logged in as %s", email)
        return data

    def logout(self) -> None:
        """Logout and clear session cookies."""
        url = self._url("/api/v1/auth/logout")
        resp = self.session.post(url, timeout=DEFAULT_TIMEOUT)
        resp.raise_for_status()
        self.user_id = None
        logger.info("Logged out")

    def refresh_token(self) -> dict[str, Any]:
        """Refresh access token using refresh token cookie."""
        url = self._url("/api/v1/auth/refresh")
        resp = self.session.post(url, timeout=DEFAULT_TIMEOUT)
        resp.raise_for_status()
        return resp.json()

    def get_session(self) -> dict[str, Any]:
        """Get current session info from JWT claims via BFF."""
        url = self._url("/api/v1/session")
        resp = self.session.get(url, timeout=DEFAULT_TIMEOUT)
        resp.raise_for_status()
        return resp.json()

    # OAuth Service - /api/v1/auth/oauth

    def get_oauth_providers(self) -> dict[str, Any]:
        """Get list of available OAuth providers.

        Returns dict with 'providers' list containing id, name, enabled.
        """
        url = self._url("/api/v1/auth/oauth/providers")
        resp = self.session.get(url, timeout=DEFAULT_TIMEOUT)
        resp.raise_for_status()
        return resp.json()

    def get_oauth_authorize_url(self, provider: str) -> str:
        """Note: This returns the redirect URL but doesn't follow it.

        Use allow_redirects=False to capture the Location header.
        """
        url = self._url(f"/api/v1/auth/oauth/{provider}/authorize")
        resp = self.session.get(url, allow_redirects=False, timeout=DEFAULT_TIMEOUT)
        return resp.headers.get("Location", "")

    def get_oauth_identities(self) -> dict[str, Any]:
        """Get linked OAuth identities for current user.

        Returns dict with 'identities' list and 'has_password' bool.
        Requires authentication.
        """
        url = self._url("/api/v1/account/oauth-identities")
        resp = self.session.get(url, timeout=DEFAULT_TIMEOUT)
        resp.raise_for_status()
        return resp.json()

    def unlink_oauth_provider(self, provider: str) -> bool:
        """Unlink an OAuth provider from current account.

        Returns True if successfully unlinked.
        Requires authentication.
        """
        url = self._url(f"/api/v1/account/oauth/{provider}")
        resp = self.session.delete(url, timeout=DEFAULT_TIMEOUT)
        resp.raise_for_status()
        return True

    # Profile Service - /api/v1/profiles (CQRS pattern via BFF)

    def create_profile(
        self,
        profile_name: str,
        search_keywords: list[str],
        *,
        work_arrangements: list[str] | None = None,
        notification_threshold: float = 0.7,
        auto_tailor_threshold: float | None = 0.85,
        open_to_relocation: bool = False,
        salary_preference: dict[str, Any] | None = None,
        experience_preference: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Create a job target profile.

        Returns 202 Accepted with request_id (CQRS async pattern).
        Use poll_for_profile() to wait for projection to be created.

        All fields are REQUIRED by the API. Defaults are provided for test convenience.
        """
        url = self._url("/api/v1/profiles")
        payload: dict[str, Any] = {
            "pref_name": profile_name,
            "search_keywords": search_keywords,
            "notification_threshold": notification_threshold,
            "open_to_relocation": open_to_relocation,
            "work_arrangements": work_arrangements or ["REMOTE", "HYBRID"],
            "salary_preference": salary_preference
            or {
                "min_salary": {"minor_units": 8000000, "currency": "USD"},
                "target_salary": {"minor_units": 12000000, "currency": "USD"},
                "preferred_frequency": "ANNUALLY",
            },
            "experience_preference": experience_preference
            or {
                "experience_years": 3,
                "seniority_levels": ["MID", "SENIOR"],
            },
        }
        if auto_tailor_threshold is not None:
            payload["auto_tailor_threshold"] = auto_tailor_threshold

        resp = self.session.post(url, json=payload, timeout=DEFAULT_TIMEOUT)
        if resp.status_code >= 400:
            logger.error("Profile create failed: %s - %s", resp.status_code, resp.text)
        resp.raise_for_status()
        data = resp.json()
        logger.info("Profile create command accepted: %s", data.get("request_id"))
        return data

    def get_profile(self, pref_id: str) -> dict[str, Any]:
        """Get profile by ID from projection."""
        url = self._url(f"/api/v1/profiles/{pref_id}")
        resp = self.session.get(url, timeout=DEFAULT_TIMEOUT)
        resp.raise_for_status()
        return resp.json()

    def list_profiles(self) -> list[dict[str, Any]]:
        """List all profiles for current user from projection."""
        url = self._url("/api/v1/profiles")
        resp = self.session.get(url, timeout=DEFAULT_TIMEOUT)
        if resp.status_code >= 400:
            logger.error("List profiles failed: %s - %s", resp.status_code, resp.text)
        resp.raise_for_status()
        data = resp.json()
        return data.get("items", [])

    def update_profile(self, pref_id: str, updates: dict[str, Any]) -> dict[str, Any]:
        """Update a profile.

        Returns 202 Accepted with request_id (CQRS async pattern).
        """
        url = self._url(f"/api/v1/profiles/{pref_id}")
        resp = self.session.patch(url, json=updates, timeout=DEFAULT_TIMEOUT)
        resp.raise_for_status()
        return resp.json()

    def delete_profile(self, pref_id: str) -> dict[str, Any]:
        """Delete a profile.

        Returns 202 Accepted with request_id (CQRS async pattern).
        """
        url = self._url(f"/api/v1/profiles/{pref_id}")
        resp = self.session.delete(url, timeout=DEFAULT_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
        logger.info("Profile delete command accepted: %s", data.get("request_id"))
        return data

    def poll_for_profile(
        self,
        profile_name: str,
        timeout: int = 30,
        interval: float = 0.5,
    ) -> dict[str, Any] | None:
        """Poll for a profile to appear in projections after async create.

        Returns the profile data if found, None if timeout.
        """

        def find_profile() -> dict[str, Any] | None:
            return next((profile for profile in self.list_profiles() if profile.get("pref_name") == profile_name), None)

        return poll_until(find_profile, timeout=timeout, max_interval=interval)

    def poll_for_profile_deletion(
        self,
        profile_name: str,
        timeout: int = 10,
        interval: float = 0.3,
    ) -> bool:
        """Poll until a profile is deleted from projections.

        Returns True if profile was deleted within timeout, False otherwise.
        """

        def profile_is_deleted() -> bool | None:
            profiles = self.list_profiles()
            return True if not any(profile.get("pref_name") == profile_name for profile in profiles) else None

        return poll_until(profile_is_deleted, timeout=timeout, max_interval=interval) is True

    def associate_attachment(self, pref_id: str, upload_id: str) -> dict[str, Any]:
        """Associate an attachment with a profile.

        Returns 202 Accepted with request_id (CQRS async pattern).
        """
        url = self._url(f"/api/v1/profiles/{pref_id}/attachments/{upload_id}")
        resp = self.session.post(url, json={}, timeout=DEFAULT_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
        logger.info("Attachment association command accepted: %s", data.get("request_id"))
        return data

    def disassociate_attachment(self, pref_id: str, upload_id: str) -> dict[str, Any]:
        """Disassociate an attachment from a profile.

        Returns 202 Accepted with request_id (CQRS async pattern).
        """
        url = self._url(f"/api/v1/profiles/{pref_id}/attachments/{upload_id}")
        resp = self.session.delete(url, timeout=DEFAULT_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
        logger.info("Attachment disassociation command accepted: %s", data.get("request_id"))
        return data

    def set_default_feature_importance(
        self,
        importance: dict[str, int | None],
    ) -> dict[str, Any]:
        """Set user-level default feature importance preferences.

        importance keys: skill_match_importance, location_importance,
            work_arrangement_importance, experience_importance,
            salary_importance, recency_importance (all 0-100 or None)
        Returns 202 Accepted with request_id (CQRS async pattern).
        """
        url = self._url("/api/v1/profiles/settings/feature-importance")
        resp = self.session.put(url, json=importance, timeout=DEFAULT_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
        logger.info("Default feature importance command accepted: %s", data.get("request_id"))
        return data

    def set_profile_feature_importance(
        self,
        pref_id: str,
        importance: dict[str, int | None],
    ) -> dict[str, Any]:
        """Override feature importance for a specific search preference.

        importance keys: skill_match_importance, location_importance,
            work_arrangement_importance, experience_importance,
            salary_importance, recency_importance (all 0-100 or None)
        Returns 202 Accepted with request_id (CQRS async pattern).
        """
        url = self._url(f"/api/v1/profiles/{pref_id}/feature-importance")
        resp = self.session.put(url, json=importance, timeout=DEFAULT_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
        logger.info("Profile feature importance command accepted: %s", data.get("request_id"))
        return data

    def get_resolved_feature_importance(self, pref_id: str) -> dict[str, Any]:
        """Get the resolved (merged) feature importance for a search preference.

        Resolution order:
        1) SearchPref.feature_importance
        2) UserPrefSettings.default_feature_importance
        3) Neutral defaults (50)
        """
        url = self._url(f"/api/v1/profiles/{pref_id}/resolved-importance")
        resp = self.session.get(url, timeout=DEFAULT_TIMEOUT)
        resp.raise_for_status()
        return resp.json()

    # Attachment Service - /api/v1/attachments (Presigned URL pattern via BFF)

    def initiate_upload(
        self,
        filename: str,
        content_type: str,
        file_size: int,
    ) -> dict[str, Any]:
        """Initiate a file upload and get a presigned URL.

        The client should then upload the file directly to the returned URL.
        """
        url = self._url("/api/v1/attachments/initiate")
        payload = {
            "filename": filename,
            "content_type": content_type,
            "file_size": file_size,
        }
        resp = self.session.post(url, json=payload, timeout=DEFAULT_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
        logger.info("Upload initiated: %s", data.get("upload_id"))
        return data

    def complete_upload(
        self,
        upload_id: str,
        filename: str,
        content_type: str,
        file_size: int,
    ) -> dict[str, Any]:
        """Complete a file upload after the client has uploaded to S3.

        The BFF verifies the object in S3 and computes the content hash
        server-side. No hash is supplied by the client.

        Args:
            upload_id: The upload ID returned by initiate_upload.
            filename: Original file name (must match what was used in initiate).
            content_type: MIME content type.
            file_size: File size in bytes.

        Returns:
            Response dict with status and upload_id.

        """
        url = self._url(f"/api/v1/attachments/{upload_id}/complete")
        payload = {
            "filename": filename,
            "content_type": content_type,
            "file_size": file_size,
        }
        resp = self.session.post(url, json=payload, timeout=DEFAULT_TIMEOUT)
        resp.raise_for_status()
        return resp.json()

    def upload_file_to_presigned_url(
        self,
        presigned_url: str,
        content: bytes,
        content_type: str,
    ) -> None:
        """Upload file content directly to S3 using a presigned PUT URL.

        This bypasses the BFF entirely: the request goes directly to S3/MinIO.
        Used in E2E tests to simulate the client-side upload step.

        Args:
            presigned_url: Presigned PUT URL returned by initiate_upload.
            content: Raw file bytes to upload.
            content_type: MIME type (must match what was declared in initiate_upload).

        Raises:
            requests.HTTPError: If the S3 PUT fails.

        """
        resp = self.session.put(
            presigned_url,
            data=content,
            headers={"Content-Type": content_type},
            timeout=DEFAULT_TIMEOUT,
        )
        resp.raise_for_status()

    def get_attachment(self, upload_id: str) -> dict[str, Any]:
        """Get attachment metadata by ID."""
        url = self._url(f"/api/v1/attachments/{upload_id}")
        resp = self.session.get(url, timeout=DEFAULT_TIMEOUT)
        resp.raise_for_status()
        return resp.json()

    def list_attachments(self) -> list[dict[str, Any]]:
        """List all attachments for current user from projection."""
        url = self._url("/api/v1/attachments")
        resp = self.session.get(url, timeout=DEFAULT_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
        return data.get("items", [])

    def delete_attachment(self, upload_id: str) -> dict[str, Any]:
        """Delete an attachment.

        Returns 202 Accepted with request_id (CQRS async pattern).
        """
        url = self._url(f"/api/v1/attachments/{upload_id}")
        resp = self.session.delete(url, timeout=DEFAULT_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
        logger.info("Attachment delete command accepted: %s", data.get("request_id"))
        return data

    # Correlation Feedback - /api/v1/correlations (via BFF)

    def record_correlation_feedback(
        self,
        correlation_id: str,
        feedback_type: str,
    ) -> dict[str, Any]:
        """Record user feedback on a job correlation.

        feedback_type: viewed, saved, applied, dismissed, liked, disliked
        Returns 202 Accepted with request_id (CQRS async pattern).
        """
        url = self._url(f"/api/v1/correlations/{correlation_id}/feedback")
        payload = {"feedback_type": feedback_type}
        resp = self.session.post(url, json=payload, timeout=DEFAULT_TIMEOUT)
        resp.raise_for_status()
        return resp.json()

    def submit_score_feedback(
        self,
        correlation_id: str,
        feedback_type: str,
    ) -> dict[str, Any]:
        """Submit asymmetric score feedback on a correlation.

        feedback_type: GOOD (accurate), TOO_HIGH (overstated), TOO_LOW (understated)
        Returns 202 Accepted with request_id (CQRS async pattern).
        """
        url = self._url(f"/api/v1/correlations/{correlation_id}/score-feedback")
        payload = {"feedback_type": feedback_type}
        resp = self.session.post(url, json=payload, timeout=DEFAULT_TIMEOUT)
        resp.raise_for_status()
        return resp.json()

    def submit_score_adjustment(
        self,
        correlation_id: str,
        adjusted_score: float,
        reasoning: str,
    ) -> dict[str, Any]:
        """Submit a manual score adjustment with reasoning.

        adjusted_score: 0.0 (irrelevant) to 1.0 (perfect match)
        reasoning: Explanation for the adjustment (min 10 chars)
        Returns 202 Accepted with request_id (CQRS async pattern).
        """
        url = self._url(f"/api/v1/correlations/{correlation_id}/adjust-score")
        payload = {"adjusted_score": adjusted_score, "reasoning": reasoning}
        resp = self.session.post(url, json=payload, timeout=DEFAULT_TIMEOUT)
        resp.raise_for_status()
        return resp.json()

    # Schema Service - /api/v1/schema-families (read-only projections via BFF)

    def list_schema_families(self) -> dict[str, Any]:
        """List schema families from projection."""
        url = self._url("/api/v1/schema-families")
        resp = self.session.get(url, timeout=DEFAULT_TIMEOUT)
        resp.raise_for_status()
        return resp.json()

    def get_schema_family(self, family_id: str) -> dict[str, Any]:
        """Get schema family by ID from projection."""
        url = self._url(f"/api/v1/schema-families/{family_id}")
        resp = self.session.get(url, timeout=DEFAULT_TIMEOUT)
        resp.raise_for_status()
        return resp.json()

    def list_schema_versions(self, family_id: str) -> list[dict[str, Any]]:
        """List all versions of a schema family from projection."""
        url = self._url(f"/api/v1/schema-families/{family_id}/versions")
        resp = self.session.get(url, timeout=DEFAULT_TIMEOUT)
        resp.raise_for_status()
        return resp.json()

    def get_schema_version(self, family_id: str, version: int) -> dict[str, Any]:
        """Get a specific version of a schema from projection."""
        url = self._url(f"/api/v1/schema-families/{family_id}/versions/{version}")
        resp = self.session.get(url, timeout=DEFAULT_TIMEOUT)
        resp.raise_for_status()
        return resp.json()

    # Template Service - /api/v1/template-families (read-only projections via BFF)

    def list_template_families(self) -> dict[str, Any]:
        """List template families from projection."""
        url = self._url(TEMPLATE_FAMILIES_ENDPOINT)
        resp = self.session.get(url, timeout=DEFAULT_TIMEOUT)
        resp.raise_for_status()
        return resp.json()

    def get_template_family(self, family_id: str) -> dict[str, Any]:
        """Get template family by ID from projection."""
        url = self._url(f"{TEMPLATE_FAMILIES_ENDPOINT}/{family_id}")
        resp = self.session.get(url, timeout=DEFAULT_TIMEOUT)
        resp.raise_for_status()
        return resp.json()

    def list_template_versions(self, namespace: str, name: str) -> list[dict[str, Any]]:
        """List all versions of a template family from projection."""
        url = self._url(f"{TEMPLATE_FAMILIES_ENDPOINT}/by-name/{namespace}/{name}/versions")
        resp = self.session.get(url, timeout=DEFAULT_TIMEOUT)
        resp.raise_for_status()
        return resp.json()

    def get_template_version(self, namespace: str, name: str, version: int) -> dict[str, Any]:
        """Get a specific version of a template from projection."""
        url = self._url(f"{TEMPLATE_FAMILIES_ENDPOINT}/by-name/{namespace}/{name}/{version}")
        resp = self.session.get(url, timeout=DEFAULT_TIMEOUT)
        resp.raise_for_status()
        return resp.json()

    def validate_template(self, template_content: str) -> dict[str, Any]:
        """Validate template content for Jinja2 and HTML issues."""
        url = self._url(f"{TEMPLATE_FAMILIES_ENDPOINT}/validate")
        payload = {"template": template_content}
        resp = self.session.post(url, json=payload, timeout=DEFAULT_TIMEOUT)
        resp.raise_for_status()
        return resp.json()

    def create_template(
        self,
        name: str,
        template_content: str,
        *,
        display_name: str,
        namespace: str = "default",
        description: str | None = None,
        schema_compatibility: list[str] | None = None,
    ) -> dict[str, Any]:
        """Create a new template family.

        Returns 202 Accepted with request_id for async tracking.
        """
        url = self._url(TEMPLATE_FAMILIES_ENDPOINT)
        payload: dict[str, Any] = {
            "name": name,
            "display_name": display_name,
            "template_content": template_content,
            "namespace": namespace,
        }
        if description:
            payload["description"] = description
        if schema_compatibility:
            payload["schema_compatibility"] = schema_compatibility
        resp = self.session.post(url, json=payload, timeout=DEFAULT_TIMEOUT)
        resp.raise_for_status()
        result = resp.json()
        logger.info("Template create command accepted: %s", result.get("request_id"))
        return result

    def add_template_version(
        self,
        family_id: str,
        version: str,
        template_content: str,
        *,
        description: str | None = None,
        schema_compatibility: list[str] | None = None,
    ) -> dict[str, Any]:
        """Add a new version to an existing template family.

        Returns 202 Accepted with request_id for async tracking.
        """
        url = self._url(f"{TEMPLATE_FAMILIES_ENDPOINT}/{family_id}/versions")
        payload: dict[str, Any] = {
            "version": version,
            "template_content": template_content,
        }
        if description:
            payload["description"] = description
        if schema_compatibility:
            payload["schema_compatibility"] = schema_compatibility
        resp = self.session.post(url, json=payload, timeout=DEFAULT_TIMEOUT)
        resp.raise_for_status()
        result = resp.json()
        logger.info("Template version add command accepted: %s", result.get("request_id"))
        return result

    def delete_template(self, family_id: str) -> dict[str, Any]:
        """Delete a template family and all its versions.

        Returns 202 Accepted with request_id for async tracking.
        """
        url = self._url(f"{TEMPLATE_FAMILIES_ENDPOINT}/{family_id}")
        resp = self.session.delete(url, timeout=DEFAULT_TIMEOUT)
        resp.raise_for_status()
        result = resp.json()
        logger.info("Template delete command accepted: %s", result.get("request_id"))
        return result

    def poll_for_template(
        self,
        template_name: str,
        timeout: int = 30,
        interval: float = 0.3,
    ) -> dict[str, Any] | None:
        """Poll for a template to appear in projections after async create.

        Returns the template family data if found, None if timeout.
        """

        def find_template() -> dict[str, Any] | None:
            page = 1
            while True:
                url = self._url(TEMPLATE_FAMILIES_ENDPOINT)
                resp = self.session.get(
                    url,
                    params={"page": page, "page_size": 100},
                    timeout=DEFAULT_TIMEOUT,
                )
                resp.raise_for_status()
                data = resp.json()
                if template := next(
                    (family for family in data.get("items", []) if family.get("name") == template_name),
                    None,
                ):
                    return template
                if not data.get("has_next", False):
                    return None
                page += 1

        return poll_until(find_template, timeout=timeout, max_interval=interval)

    # Document Generation - /api/v1/documents (async via BFF)

    def generate_document(
        self,
        template_version_id: str,
        data: dict[str, Any],
        *,
        output_format: str = "pdf",
    ) -> dict[str, Any]:
        """Initiate async document generation.

        Returns 202 Accepted with request_id.
        Use get_document_status() or document_events() to track progress.
        """
        url = self._url("/api/v1/documents/generate")
        payload: dict[str, Any] = {
            "template_version_id": template_version_id,
            "data": data,
            "output_format": output_format,
        }
        resp = self.session.post(url, json=payload, timeout=DEFAULT_TIMEOUT)
        resp.raise_for_status()
        data_resp = resp.json()
        logger.info("Document generation requested: %s", data_resp.get("request_id"))
        return data_resp

    def get_document_status(self, request_id: str) -> dict[str, Any]:
        """Get the status of a document generation request."""
        url = self._url(f"/api/v1/documents/{request_id}/status")
        resp = self.session.get(url, timeout=DEFAULT_TIMEOUT)
        resp.raise_for_status()
        return resp.json()

    def list_documents(self, *, limit: int = 20, offset: int = 0) -> dict[str, Any]:
        """List recent document generation requests for the current user."""
        url = self._url("/api/v1/documents")
        params = {"limit": limit, "offset": offset}
        resp = self.session.get(url, params=params, timeout=DEFAULT_TIMEOUT)
        resp.raise_for_status()
        return resp.json()

    def poll_for_document_completion(
        self,
        request_id: str,
        timeout: float = 10.0,
        interval: float = 0.1,
    ) -> dict[str, Any]:
        """Poll for document generation to complete.

        Returns the document status with download_url when completed.
        Raises TimeoutError if not completed within timeout.
        """

        def completed_status() -> dict[str, Any] | None:
            status = self.get_document_status(request_id)
            match status.get("status"):
                case "completed":
                    return status
                case "failed":
                    msg = f"Document generation failed: {status.get('error')}"
                    raise RuntimeError(msg)
                case _:
                    return None

        start = time.monotonic()
        if status := poll_until(completed_status, timeout=timeout, max_interval=interval):
            return status
        elapsed = time.monotonic() - start
        msg = f"Document generation not completed within {elapsed:.1f}s"
        raise TimeoutError(msg)

    # Request-scoped SSE streaming - /api/documents/{request_id}/events

    def _sse_url(self, request_id: str) -> str:
        """SSE endpoint URL for one document generation request."""
        return self._url(f"/api/documents/{request_id}/events")

    @staticmethod
    def _parse_sse_line(
        line: str,
        current: dict[str, str],
    ) -> tuple[dict[str, str], dict[str, str] | None]:
        """Parse a single SSE line into the current event buffer.

        Returns (updated_current, emitted_event_or_none).
        """
        if line == "":
            return ({}, current) if current else (current, None)
        if line.startswith(":"):
            return current, {"comment": line[1:].strip()}
        if ":" in line:
            field, _, value = line.partition(":")
            current[field.strip()] = value.strip()
        return current, None

    def connect_sse_raw(
        self,
        request_id: str,
        *,
        timeout: float = 10.0,
        last_event_id: str | None = None,
    ) -> requests.Response:
        """Open a raw streaming connection for one document request.

        Returns the Response object with stream=True for manual iteration.
        Raises HTTPError on non-2xx status (e.g., 401 without auth).
        Caller is responsible for closing the response.
        """
        headers = {"Accept": "text/event-stream"}
        if last_event_id is not None:
            headers["Last-Event-ID"] = last_event_id
        resp = self.session.get(
            self._sse_url(request_id),
            stream=True,
            timeout=timeout,
            headers=headers,
        )
        resp.raise_for_status()
        return resp

    def collect_sse_events(
        self,
        request_id: str,
        *,
        max_events: int = 50,
        timeout: float = 15.0,
        stop_on_event_type: str | None = None,
        last_event_id: str | None = None,
    ) -> list[dict[str, str]]:
        """Collect SSE events for one document generation request.

        Connects, collects events (parsed into {event, data, id} dicts),
        and returns them. Stops after max_events, timeout, or when
        stop_on_event_type is found.
        """
        events: list[dict[str, str]] = []
        current: dict[str, str] = {}
        deadline = time.monotonic() + timeout
        headers = {"Accept": "text/event-stream"}
        if last_event_id is not None:
            headers["Last-Event-ID"] = last_event_id

        try:
            with self.session.get(
                self._sse_url(request_id),
                stream=True,
                timeout=(5.0, timeout),
                headers=headers,
            ) as resp:
                resp.raise_for_status()
                for line in resp.iter_lines(decode_unicode=True):
                    if time.monotonic() >= deadline:
                        break
                    if line is None:
                        continue
                    decoded_line = line.decode() if isinstance(line, bytes) else line
                    current, event = self._parse_sse_line(decoded_line, current)
                    if event is None:
                        continue
                    events.append(event)
                    if self._should_stop_sse(event, len(events), max_events, stop_on_event_type):
                        break
        except (
            requests.exceptions.ReadTimeout,
            requests.exceptions.ChunkedEncodingError,
        ):
            pass  # Expected when timeout reached or server closes connection

        return events

    @staticmethod
    def _should_stop_sse(
        event: dict[str, str],
        count: int,
        max_events: int,
        stop_on_event_type: str | None,
    ) -> bool:
        """Check if SSE collection should stop."""
        if count >= max_events:
            return True
        return bool(stop_on_event_type and event.get("event") == stop_on_event_type)

    # Job Listings - /api/v1/listings (read-only projections via BFF)

    def list_job_listings(
        self,
        *,
        page: int = 1,
        page_size: int = 20,
        source: str | None = None,
        company: str | None = None,
    ) -> dict[str, Any]:
        """List job listings from projection."""
        url = self._url("/api/v1/listings")
        params: dict[str, QueryValue] = {"page": page, "page_size": page_size}
        if source:
            params["source"] = source
        if company:
            params["company"] = company
        resp = self._request_with_auto_refresh("GET", url, params=params)
        resp.raise_for_status()
        return resp.json()

    def get_job_listing(self, listing_id: str) -> dict[str, Any]:
        """Get a specific job listing by ID from projection."""
        url = self._url(f"/api/v1/listings/{listing_id}")
        resp = self._request_with_auto_refresh("GET", url)
        resp.raise_for_status()
        return resp.json()

    def search_job_listings(
        self,
        query: str,
        *,
        page: int = 1,
        page_size: int = 20,
    ) -> dict[str, Any]:
        """Search job listings using full-text search.

        Args:
            query: Search query string (min 2 chars)
            page: Page number (1-indexed)
            page_size: Results per page

        Returns:
            Dict with listings, total, page, page_size keys.

        """
        url = self._url("/api/v1/listings")
        params: dict[str, QueryValue] = {
            "q": query,
            "page": page,
            "page_size": page_size,
        }
        resp = self._request_with_auto_refresh("GET", url, params=params)
        resp.raise_for_status()
        return resp.json()

    def list_my_correlations(
        self,
        *,
        page: int = 1,
        page_size: int = 20,
        pref_id: str | None = None,
        min_score: int = 0,
    ) -> dict[str, Any]:
        """List job correlations/matches for the current user from projection."""
        url = self._url("/api/v1/listings/correlations/mine")
        params: dict[str, QueryValue] = {
            "page": page,
            "page_size": page_size,
            "min_score": min_score,
        }
        if pref_id:
            params["pref_id"] = pref_id
        resp = self._request_with_auto_refresh("GET", url, params=params)
        resp.raise_for_status()
        return resp.json()

    def get_correlation(self, correlation_id: str) -> dict[str, Any]:
        """Get a specific job correlation by ID from projection."""
        url = self._url(f"/api/v1/listings/correlations/{correlation_id}")
        resp = self._request_with_auto_refresh("GET", url)
        resp.raise_for_status()
        return resp.json()

    def poll_for_correlations(
        self,
        pref_id: str,
        *,
        min_count: int = 1,
        timeout: int = 60,
        interval: float = 1.0,
        page_size: int = 20,
    ) -> list[dict[str, Any]]:
        """Poll for correlations to appear for a profile.

        Returns correlations if found, empty list if timeout.
        """

        def find_correlations() -> list[dict[str, Any]] | None:
            resp = self.list_my_correlations(pref_id=pref_id, page_size=page_size)
            correlations = resp.get("items", [])
            return correlations if len(correlations) >= min_count else None

        return poll_until(find_correlations, timeout=timeout, max_interval=interval) or []

    # Account Management - /api/v1/account (via user-auth-service)

    def get_account(self) -> dict[str, Any]:
        """Get current user's account information."""
        url = self._url(ACCOUNT_ENDPOINT)
        resp = self.session.get(url, timeout=DEFAULT_TIMEOUT)
        resp.raise_for_status()
        return resp.json()

    def poll_for_account(
        self,
        timeout: int = 15,
        interval: float = 0.3,
    ) -> dict[str, Any] | None:
        """Poll for account projection to be populated after registration.

        The account projection is populated asynchronously via Kafka events from
        user-auth-service. Polling prevents flakiness in tests that call
        get_account() immediately after register().
        """

        def get_projected_account() -> dict[str, Any] | None:
            try:
                return self.get_account()
            except Exception:
                return None

        return poll_until(get_projected_account, timeout=timeout, max_interval=interval)

    def update_account(
        self,
        first_name: str | None = None,
        last_name: str | None = None,
        display_name: str | None = None,
    ) -> dict[str, Any]:
        """Update current user's account information."""
        url = self._url(ACCOUNT_ENDPOINT)
        payload: dict[str, Any] = {}
        if first_name is not None:
            payload["first_name"] = first_name
        if last_name is not None:
            payload["last_name"] = last_name
        if display_name is not None:
            payload["display_name"] = display_name
        resp = self.session.patch(url, json=payload, timeout=DEFAULT_TIMEOUT)
        resp.raise_for_status()
        return resp.json()

    def delete_account(self) -> None:
        """Delete current user's account (returns 204 No Content)."""
        url = self._url(ACCOUNT_ENDPOINT)
        resp = self.session.delete(url, timeout=DEFAULT_TIMEOUT)
        resp.raise_for_status()
        self.user_id = None
        logger.info("Account deleted")

    # Health Checks

    def check_health(self, path: str = "/api/ping") -> bool:
        """Check if gateway is healthy via BFF ping endpoint."""
        try:
            resp = self.session.get(self._url(path), timeout=HEALTH_REQUEST_TIMEOUT)
        except RequestException:
            return False
        else:
            return resp.status_code == 200

    def check_ping(self) -> bool:
        """Check if BFF ping endpoint is responding."""
        return self.check_health()

    def wait_for_healthy(self) -> bool:
        """Probe service health with a bounded retry budget."""
        start = time.monotonic()
        for attempt in range(HEALTH_PROBE_ATTEMPTS):
            if self.check_health():
                logger.info("Services healthy after %.1fs", time.monotonic() - start)
                return True
            if attempt + 1 < HEALTH_PROBE_ATTEMPTS:
                logger.info("Waiting for services... (attempt %d/%d)", attempt + 1, HEALTH_PROBE_ATTEMPTS)
                time.sleep(HEALTH_PROBE_INTERVAL)
        logger.error(
            "Services not healthy after %d attempts in %.1fs",
            HEALTH_PROBE_ATTEMPTS,
            time.monotonic() - start,
        )
        return False

    def clear_session(self) -> None:
        """Clear session cookies and user state."""
        self.session.cookies.clear()
        self.user_id = None

    def get_system_resume_template(self) -> dict[str, Any] | None:
        """Get a system-scoped resume template."""
        try:
            page = 1
            while True:
                url = self._url(TEMPLATE_FAMILIES_ENDPOINT)
                resp = self.session.get(
                    url,
                    params={"page": page, "page_size": 100},
                    timeout=DEFAULT_TIMEOUT,
                )
                resp.raise_for_status()
                data = resp.json()
                for family in data.get("items", []):
                    latest = family.get("latest_version")
                    if latest and latest.get("access_scope") == "SYSTEM" and family.get("name") == "resume":
                        return family
                if not data.get("has_next", False):
                    break
                page += 1
        except Exception:
            return None
        else:
            return None

    # Skills - /api/v1/skills (read-only projections via BFF, no auth required)

    def search_skills(
        self,
        query: str,
        *,
        limit: int = 10,
        category: str | None = None,
    ) -> dict[str, Any]:
        """Search canonical skills by name prefix."""
        url = self._url("/api/v1/skills/search")
        params: dict[str, Any] = {"q": query, "limit": limit}
        if category:
            params["category"] = category
        resp = self.session.get(url, params=params, timeout=DEFAULT_TIMEOUT)
        resp.raise_for_status()
        return resp.json()

    def get_skills_by_ids(self, skill_ids: list[str]) -> dict[str, Any]:
        """Batch-fetch skills by their UUIDs."""
        url = self._url("/api/v1/skills/batch")
        resp = self.session.post(url, json={"skill_ids": skill_ids}, timeout=DEFAULT_TIMEOUT)
        resp.raise_for_status()
        return resp.json()

    def get_skill(self, skill_id: str) -> dict[str, Any]:
        """Get a single skill by ID."""
        url = self._url(f"/api/v1/skills/{skill_id}")
        resp = self.session.get(url, timeout=DEFAULT_TIMEOUT)
        resp.raise_for_status()
        return resp.json()

    def list_skill_categories(self) -> list[str]:
        """List all skill categories."""
        url = self._url("/api/v1/skills/categories/list")
        resp = self.session.get(url, timeout=DEFAULT_TIMEOUT)
        resp.raise_for_status()
        return resp.json()


class SearchJobListingsResponse:
    """Response wrapper for job listings search results."""

    def __init__(self, data: dict[str, JSONValue]) -> None:
        """Initialize from response data."""
        self.data = data
        self.items = data.get("items", [])
        self.total = data.get("total", 0)
        self.page = data.get("page", 1)
        self.page_size = data.get("page_size", 20)

    def __getitem__(self, key: str) -> JSONValue:
        """Allow dict-style access."""
        return self.data[key]

    def get(self, key: str, default: JSONValue = None) -> JSONValue:
        """Get value with default."""
        return self.data.get(key, default)
