"""Auth helpers for doc-template-service."""

from __future__ import annotations

from uuid import NAMESPACE_DNS, UUID, uuid5

from nohiki.common.v1 import AccessScope

SYSTEM_SERVICE_UUID = uuid5(NAMESPACE_DNS, "service:doc-template-service-seeder")


def can_access_resource(
    resource_access_scope: AccessScope,
    resource_owner_id: UUID | None,
    user_id: UUID,
) -> bool:
    """Check whether a user may read a resource.

    Args:
        resource_access_scope: Resource visibility policy.
        resource_owner_id: Owning user for private resources.
        user_id: User requesting access.

    Returns:
        Whether the user may read the resource.

    """
    match resource_access_scope:
        case AccessScope.PUBLIC:
            return True
        case AccessScope.PRIVATE:
            return resource_owner_id == user_id
        case AccessScope.SYSTEM:
            return user_id == SYSTEM_SERVICE_UUID
        case _:
            return False


def can_write_resource(
    resource_access_scope: AccessScope,
    resource_owner_id: UUID | None,
    user_id: UUID,
) -> bool:
    """Check whether a user may create a new resource version.

    Args:
        resource_access_scope: Resource visibility policy.
        resource_owner_id: Owning user for private resources.
        user_id: User requesting the write.

    Returns:
        Whether the user may create a new version.

    """
    match resource_access_scope:
        case AccessScope.PRIVATE:
            return resource_owner_id == user_id
        case AccessScope.PUBLIC | AccessScope.SYSTEM:
            return user_id == SYSTEM_SERVICE_UUID
        case _:
            return False
