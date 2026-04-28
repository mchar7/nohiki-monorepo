"""SQLAlchemy models for user-entitlement-service (user-entitlement domain).

Schema: user_entitlement_schema
Tables: entitlements
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, ClassVar

import sqlalchemy as sa
from nohiki.common.v1 import (
    BillingProvider,
    DiscoveryFrequency,
    JobBoardSource,
    SubscriptionStatus,
    SubscriptionTier,
)
from nohiki_db_utils import BaseEntity, StateMachineMixin
from sqlalchemy import DateTime, Integer, String
from sqlalchemy import Enum as SQLEnum
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

SCHEMA_NAME = "user_entitlement_schema"

_subscription_tier_enum = SQLEnum(
    SubscriptionTier,
    name="subscription_tier_enum",
    schema=SCHEMA_NAME,
    native_enum=True,
    create_type=False,
    values_callable=lambda e: [v.name for v in e],
)

_subscription_status_enum = SQLEnum(
    SubscriptionStatus,
    name="subscription_status_enum",
    schema=SCHEMA_NAME,
    native_enum=True,
    create_type=False,
    values_callable=lambda e: [v.name for v in e],
)

_billing_provider_enum = SQLEnum(
    BillingProvider,
    name="billing_provider_enum",
    schema=SCHEMA_NAME,
    native_enum=True,
    create_type=False,
    values_callable=lambda e: [v.name for v in e],
)

_discovery_frequency_enum = SQLEnum(
    DiscoveryFrequency,
    name="discovery_frequency_enum",
    schema=SCHEMA_NAME,
    native_enum=True,
    create_type=False,
    values_callable=lambda e: [v.name for v in e],
)

_job_board_source_enum = SQLEnum(
    JobBoardSource,
    name="job_board_source_enum",
    schema=SCHEMA_NAME,
    native_enum=True,
    create_type=False,
    values_callable=lambda e: [v.name for v in e],
)


class Base(DeclarativeBase):
    """Base class for all models."""


class Entitlement(BaseEntity, StateMachineMixin, Base):
    """Account entitlements model for subscription tiers and feature access."""

    __repr_fields__ = ("id", "user_id", "tier", "subscription_status")
    __status_field__ = "subscription_status"
    __transitions__: ClassVar[dict[str, frozenset[str]]] = {
        "NONE": frozenset({"TRIALING", "ACTIVE"}),
        "TRIALING": frozenset({"ACTIVE", "CANCELED", "EXPIRED"}),
        "ACTIVE": frozenset({"PAST_DUE", "CANCELED", "PAUSED"}),
        "PAST_DUE": frozenset({"ACTIVE", "CANCELED", "EXPIRED"}),
        "CANCELED": frozenset({"EXPIRED", "ACTIVE"}),
        "PAUSED": frozenset({"ACTIVE", "CANCELED", "EXPIRED"}),
        "EXPIRED": frozenset({"ACTIVE", "TRIALING"}),
    }

    __tablename__ = "entitlements"
    __table_args__ = ({"schema": SCHEMA_NAME},)

    # Owner reference (logical FK to user-auth-service)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(), nullable=False, unique=True, index=True)

    # Tier and subscription
    tier: Mapped[SubscriptionTier] = mapped_column(
        _subscription_tier_enum,
        nullable=False,
        server_default=sa.text("'FREE'"),
    )
    subscription_status: Mapped[SubscriptionStatus] = mapped_column(
        _subscription_status_enum,
        nullable=False,
        server_default=sa.text("'NONE'"),
    )

    # Billing provider (for future webhook integration)
    billing_provider: Mapped[BillingProvider] = mapped_column(
        _billing_provider_enum,
        nullable=False,
        server_default=sa.text("'NONE'"),
    )
    external_subscription_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    external_customer_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    current_period_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    current_period_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Computed limits (derived from tier)
    discovery_frequency_limit: Mapped[DiscoveryFrequency] = mapped_column(
        _discovery_frequency_enum,
        nullable=False,
        server_default=sa.text("'DAILY'"),
    )
    max_prefs: Mapped[int] = mapped_column(Integer, nullable=False, server_default=sa.text("1"))
    max_uploads_per_pref: Mapped[int] = mapped_column(Integer, nullable=False, server_default=sa.text("3"))

    # Source access (derived from tier)
    allowed_sources: Mapped[list[JobBoardSource]] = mapped_column(
        ARRAY(_job_board_source_enum),
        nullable=False,
        server_default=sa.text("ARRAY['INDEED']::user_entitlement_schema.job_board_source_enum[]"),
    )

    # Feature flags (JSONB for flexibility)
    features_enabled: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")
    )

    # BaseEntity provides: id, created_at, updated_at
