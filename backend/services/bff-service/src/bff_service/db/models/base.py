"""Shared database base, constants, and enum definitions for BFF projections."""

from __future__ import annotations

import sqlalchemy as sa
from nohiki.common.v1 import AccessScope, WorkArrangement
from nohiki.doc.template.v1 import TemplateAudience
from sqlalchemy import Enum as SQLEnum
from sqlalchemy.orm import DeclarativeBase

SQL_NOW = sa.text("now()")
SQL_GEN_UUID = sa.text("uuidv7()")
SCHEMA_NAME = "bff_schema"

WorkArrangementEnum = SQLEnum(
    WorkArrangement,
    name="work_arrangement_enum",
    schema=SCHEMA_NAME,
    native_enum=True,
    create_type=False,
    values_callable=lambda e: [v.name for v in e],
)

AccessScopeEnum = SQLEnum(
    AccessScope,
    name="access_scope_enum",
    schema=SCHEMA_NAME,
    native_enum=True,
    create_type=False,
    values_callable=lambda e: [v.name for v in e],
)

TemplateAudienceEnum = SQLEnum(
    TemplateAudience,
    name="template_audience_enum",
    schema=SCHEMA_NAME,
    native_enum=True,
    create_type=False,
    values_callable=lambda e: [v.name for v in e],
)


class Base(DeclarativeBase):
    """Base declarative class for SQLAlchemy models."""
