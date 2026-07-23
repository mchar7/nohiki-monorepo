"""API test fixtures with session-scoped optimization.

Supports both Docker Compose and Kubernetes targets.
Set NOHIKI_TARGET=compose (default) or NOHIKI_TARGET=k8s.

Key design:
1. Session-scoped user fixture (one user for all tests)
2. Idempotent setup (checks before creating)
3. No database truncation at session start
4. Profile fixtures are session-scoped
"""

from __future__ import annotations

import logging
import os
import uuid
from collections.abc import Generator

import pytest
from requests.exceptions import RequestException

from tests.utils.deployment_platform import get_platform

from ._helpers import _is_profile_data_complete
from .client import NohikiClient
from .config import E2EConfig

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger("nohiki-api-tests")

BASE_URL = os.getenv("E2E_BASE_URL", "http://localhost:8000")

SESSION_USER_EMAIL = "e2e-session-user@example.com"
SESSION_USER_PASSWORD = "SessionUserP@ss123!"
TEST_PASSWORD = SESSION_USER_PASSWORD
SESSION_PROFILE_NAME = "E2E Session Profile"

# Rich profile data for L2R feature coverage, the scoring model has 32 features
# including salary, experience, and work arrangement signals. Profiles missing
# these fields produce degenerate feature vectors (mostly NaN).
_RICH_SALARY_PREFERENCE = {
    "min_salary": {"minor_units": 8000000, "currency": "USD"},
    "target_salary": {"minor_units": 12000000, "currency": "USD"},
    "preferred_frequency": "ANNUALLY",
}
_RICH_EXPERIENCE_PREFERENCE = {
    "experience_years": 5,
    "seniority_levels": ["MID", "SENIOR"],
}


@pytest.fixture(scope="session")
def e2e_config() -> E2EConfig:
    """Session-scoped configuration."""
    return E2EConfig.from_environment()


@pytest.fixture(scope="session")
def healthy_base_url() -> str:
    """Return the base URL after one bounded health verdict per test session."""
    client = NohikiClient(BASE_URL)
    if not client.wait_for_healthy():
        pytest.skip("Services not healthy - is the deployment running?")
    return BASE_URL


@pytest.fixture(scope="session")
def session_client(healthy_base_url: str) -> NohikiClient:
    """Session-scoped authenticated client.

    Creates user once at session start, reuses for all tests.
    Idempotent: tries login first, registers only if needed.
    """
    client = NohikiClient(healthy_base_url)

    try:
        client.login(SESSION_USER_EMAIL, SESSION_USER_PASSWORD)
        logger.info("Session user logged in: %s", SESSION_USER_EMAIL)
    except RequestException as login_exc:
        logger.info("Session user login failed (%s), registering...", login_exc)
        response = client.register(
            email=SESSION_USER_EMAIL,
            password=SESSION_USER_PASSWORD,
            display_name="E2E Session",
        )
        if response is not None:
            logger.info("Session user registered: %s", SESSION_USER_EMAIL)
        else:
            try:
                client.login(SESSION_USER_EMAIL, SESSION_USER_PASSWORD)
            except RequestException as retry_exc:
                pytest.skip(f"Cannot establish session for E2E user: {retry_exc}")
            logger.info("Session user already existed, logged in: %s", SESSION_USER_EMAIL)

    return client


@pytest.fixture(autouse=True)
def cleanup_synthetic_identities(monkeypatch: pytest.MonkeyPatch) -> Generator[None]:
    """Delete every account registered by a test through a separate live session."""
    cleanup_clients: list[NohikiClient] = []
    original_register = NohikiClient.register
    original_delete_account = NohikiClient.delete_account

    def tracked_register(
        client: NohikiClient,
        email: str,
        password: str,
        display_name: str = "Test Account",
    ) -> dict | None:
        result = original_register(client, email, password, display_name)
        if result is not None:
            cleanup_client = NohikiClient(client.base_url)
            cleanup_client.login(email, password)
            cleanup_clients.append(cleanup_client)
        return result

    def tracked_delete_account(client: NohikiClient) -> None:
        deleted_user_id = client.user_id
        original_delete_account(client)
        if deleted_user_id is None:
            return
        retained: list[NohikiClient] = []
        for cleanup_client in cleanup_clients:
            if cleanup_client.user_id == deleted_user_id:
                cleanup_client.clear_session()
            else:
                retained.append(cleanup_client)
        cleanup_clients[:] = retained

    monkeypatch.setattr(NohikiClient, "register", tracked_register)
    monkeypatch.setattr(NohikiClient, "delete_account", tracked_delete_account)
    yield

    failures: list[str] = []
    for cleanup_client in tuple(cleanup_clients):
        user_id = cleanup_client.user_id or "unknown"
        try:
            cleanup_client.delete_account()
        except RequestException:
            failures.append(user_id)
        finally:
            cleanup_client.clear_session()
    if failures:
        pytest.fail(f"synthetic identity cleanup failed for user ids: {failures}")


@pytest.fixture
def authenticated_client(session_client: NohikiClient) -> NohikiClient:
    """Get authenticated client using session user.

    This is an alias for session_client for backward compatibility.
    Existing tests can use this fixture without changes.
    """
    return session_client


@pytest.fixture
def fresh_client(healthy_base_url: str) -> Generator[NohikiClient]:
    """Get a fresh unauthenticated client.

    Use for testing auth flows that need unauthenticated state.
    """
    client = NohikiClient(healthy_base_url)
    yield client
    client.clear_session()


@pytest.fixture(scope="session")
def session_profile(session_client: NohikiClient) -> dict:
    """Session-scoped test profile for E2E tests.

    Creates or retrieves the session profile by name. Existing profiles from
    previous sessions are checked for data completeness. Incomplete profiles
    are deleted and recreated: their correlations were scored from incomplete
    feature vectors and never re-score (pref+listing is unique), so patching
    the profile would leave degenerate scores behind.

    Profile creation triggers backfill which generates correlations.
    """
    try:
        profiles = session_client.list_profiles()
    except RequestException as exc:
        logger.debug("Could not list profiles (%s), will create new one", exc)
        profiles = []

    for profile in profiles:
        if profile.get("pref_name") == SESSION_PROFILE_NAME:
            pref_id = profile["id"]
            logger.info("Found existing session profile: %s", pref_id)
            if _is_profile_data_complete(profile):
                return profile
            # Recreate rather than patch; see docstring
            logger.info("Recreating incomplete session profile: %s", pref_id)
            session_client.delete_profile(pref_id)
            session_client.poll_for_profile_deletion(SESSION_PROFILE_NAME, timeout=30)
            break

    session_client.create_profile(
        profile_name=SESSION_PROFILE_NAME,
        search_keywords=["python", "backend", "api", "software engineer"],
        work_arrangements=["REMOTE", "HYBRID"],
        open_to_relocation=True,
        salary_preference=_RICH_SALARY_PREFERENCE,
        experience_preference=_RICH_EXPERIENCE_PREFERENCE,
    )

    profile = session_client.poll_for_profile(
        profile_name=SESSION_PROFILE_NAME,
        timeout=60,
    )

    if profile:
        logger.info("Session profile created: %s", SESSION_PROFILE_NAME)
        return profile

    pytest.fail("Failed to create session profile")


def unique_email() -> str:
    """Generate unique email for tests that MUST create new users.

    Use sparingly - prefer session_client for most tests.
    """
    return f"e2e-{uuid.uuid4().hex[:8]}@test.nohiki.com"


@pytest.fixture(scope="session")
def ml_pipeline_ready() -> bool:
    """Check if ML pipeline is ready for end-to-end testing.

    Verifies ml-compute-service Kafka consumer is active.
    Works for both Docker Compose and Kubernetes targets.
    """
    platform = get_platform()
    platform.get_service_statuses()
    code, stdout, _ = platform.exec_kafka_cmd(
        [
            "kafka-consumer-groups",
            "--bootstrap-server",
            platform.kafka_bootstrap_server,
            "--describe",
            "--group",
            "ml-compute-service-consumer",
        ],
        timeout=15,
    )

    if code != 0:
        logger.warning("ML pipeline health check failed (exit code %d)", code)
        return False

    if "has no active members" in stdout:
        logger.warning("ML pipeline not ready: consumer has no active members")
        return False

    logger.info("ML pipeline ready")
    return True
