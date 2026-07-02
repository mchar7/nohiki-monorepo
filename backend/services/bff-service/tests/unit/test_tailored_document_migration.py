"""Fresh-schema migration contract tests for tailored document projections."""

from pathlib import Path
from typing import Protocol, cast
from unittest.mock import MagicMock

from alembic.config import Config
from alembic.script import ScriptDirectory
from bff_service.db.models import (
    DocumentGenerationStatus,
    JobCorrelationProjection,
    JobListingProjection,
    TemplateProjection,
)


class _MigrationModule(Protocol):
    op: object

    def upgrade(self) -> None: ...


def _scripts() -> ScriptDirectory:
    service_root = Path(__file__).resolve().parents[2]
    config = Config(str(service_root / "alembic.ini"))
    config.set_main_option("script_location", str(service_root / "alembic"))
    config.set_main_option("path_separator", "os")
    return ScriptDirectory.from_config(config)


def test_initial_migration_remains_the_single_head() -> None:
    scripts = _scripts()
    heads = scripts.get_heads()

    assert heads == ["001"]
    revision = scripts.get_revision("001")
    assert revision is not None
    assert revision.down_revision is None


def test_tailored_columns_are_nullable_for_direct_render_compatibility() -> None:
    tailored = {
        JobListingProjection.__table__.c.snapshot,
        JobCorrelationProjection.__table__.c.pref_snapshot,
        JobCorrelationProjection.__table__.c.pref_uploads,
        TemplateProjection.__table__.c.version_id,
        DocumentGenerationStatus.__table__.c.job_correlation_id,
        DocumentGenerationStatus.__table__.c.pref_id,
        DocumentGenerationStatus.__table__.c.listing_id,
    }
    assert all(column.nullable for column in tailored)

    direct_required = {
        DocumentGenerationStatus.__table__.c.request_id,
        DocumentGenerationStatus.__table__.c.user_id,
        DocumentGenerationStatus.__table__.c.template_version_id,
        DocumentGenerationStatus.__table__.c.output_format,
    }
    assert all(not column.nullable for column in direct_required)


def test_initial_migration_creates_tailored_columns_in_fresh_tables() -> None:
    revision = _scripts().get_revision("001")
    assert revision is not None
    module = cast("_MigrationModule", revision.module)
    fake_op = MagicMock()
    original_op = module.op
    module.op = fake_op
    try:
        module.upgrade()
    finally:
        module.op = original_op

    tables: dict[str, dict[str, bool]] = {}
    for call in fake_op.create_table.call_args_list:
        table_name = call.args[0]
        columns = {
            argument.name: argument.nullable
            for argument in call.args[1:]
            if hasattr(argument, "nullable") and hasattr(argument, "name")
        }
        tables[table_name] = columns

    assert tables["job_listing_projections"]["snapshot"] is True
    assert tables["job_correlation_projections"]["pref_snapshot"] is True
    assert tables["job_correlation_projections"]["pref_uploads"] is True
    assert tables["template_projections"]["version_id"] is True
    status_columns = tables["document_generation_status"]
    assert status_columns["job_correlation_id"] is True
    assert status_columns["pref_id"] is True
    assert status_columns["listing_id"] is True
    assert status_columns["request_id"] is False
    assert status_columns["user_id"] is False
    assert status_columns["template_version_id"] is False
    assert status_columns["output_format"] is False
