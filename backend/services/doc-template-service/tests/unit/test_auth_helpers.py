"""Tests for authentication helper functions."""

from uuid import UUID

from doc_template_service.core.auth_helpers import (
    SYSTEM_SERVICE_UUID,
    can_access_resource,
    can_write_resource,
)
from nohiki.common.v1 import AccessScope


class TestCanAccessResource:
    """Tests for can_access_resource function."""

    def test_public_resource_accessible_by_any_user(self) -> None:
        """Test that public resources are accessible by any user."""
        user_id = UUID("11111111-1111-1111-1111-111111111111")
        owner_id = UUID("22222222-2222-2222-2222-222222222222")

        assert can_access_resource(AccessScope.PUBLIC, owner_id, user_id) is True
        assert can_access_resource(AccessScope.PUBLIC, None, user_id) is True

    def test_user_resource_accessible_by_owner(self) -> None:
        """Test that user resources are accessible by their owner."""
        owner_id = UUID("11111111-1111-1111-1111-111111111111")

        assert can_access_resource(AccessScope.PRIVATE, owner_id, owner_id) is True

    def test_user_resource_not_accessible_by_other_user(self) -> None:
        """Test that user resources are not accessible by other users."""
        owner_id = UUID("11111111-1111-1111-1111-111111111111")
        other_user_id = UUID("22222222-2222-2222-2222-222222222222")

        assert can_access_resource(AccessScope.PRIVATE, owner_id, other_user_id) is False

    def test_user_resource_not_accessible_when_no_owner(self) -> None:
        """Test that user resources without owner are not accessible."""
        user_id = UUID("11111111-1111-1111-1111-111111111111")

        assert can_access_resource(AccessScope.PRIVATE, None, user_id) is False

    def test_internal_resource_accessible_by_system_service(self) -> None:
        """Test that internal resources are accessible by system services."""
        system_user_id = SYSTEM_SERVICE_UUID
        owner_id = UUID("11111111-1111-1111-1111-111111111111")

        assert can_access_resource(AccessScope.SYSTEM, owner_id, system_user_id) is True
        assert can_access_resource(AccessScope.SYSTEM, None, system_user_id) is True

    def test_internal_resource_not_accessible_by_regular_user(self) -> None:
        """Test that internal resources are not accessible by regular users."""
        regular_user_id = UUID("11111111-1111-1111-1111-111111111111")
        owner_id = UUID("22222222-2222-2222-2222-222222222222")

        assert can_access_resource(AccessScope.SYSTEM, owner_id, regular_user_id) is False


class TestCanWriteResource:
    """Tests for template version write authorization."""

    def test_private_resource_writable_only_by_owner(self) -> None:
        owner_id = UUID("11111111-1111-1111-1111-111111111111")
        other_user_id = UUID("22222222-2222-2222-2222-222222222222")

        assert can_write_resource(AccessScope.PRIVATE, owner_id, owner_id) is True
        assert can_write_resource(AccessScope.PRIVATE, owner_id, other_user_id) is False
        assert can_write_resource(AccessScope.PRIVATE, None, owner_id) is False

    def test_public_resource_writable_only_by_system_service(self) -> None:
        regular_user_id = UUID("11111111-1111-1111-1111-111111111111")

        assert can_write_resource(AccessScope.PUBLIC, None, SYSTEM_SERVICE_UUID) is True
        assert can_write_resource(AccessScope.PUBLIC, None, regular_user_id) is False

    def test_system_resource_writable_only_by_system_service(self) -> None:
        regular_user_id = UUID("11111111-1111-1111-1111-111111111111")

        assert can_write_resource(AccessScope.SYSTEM, None, SYSTEM_SERVICE_UUID) is True
        assert can_write_resource(AccessScope.SYSTEM, None, regular_user_id) is False
