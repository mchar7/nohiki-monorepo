"""Migration contracts for replay-safe profile projections."""

from pathlib import Path


def test_profile_projection_uses_one_folded_clean_migration() -> None:
    """Replay ordering and tombstones belong to the sole initial schema."""
    versions = Path(__file__).parents[3] / "alembic" / "versions"
    migrations = sorted(path.name for path in versions.glob("[0-9]*.py"))
    assert migrations == ["001_initial_migration.py"]

    migration = (versions / migrations[0]).read_text()
    profile_projection = migration.split("CREATE TABLE {SCHEMA_NAME}.profile_projections (", maxsplit=1)[1].split(
        "\n        )", maxsplit=1
    )[0]
    assert "is_active BOOLEAN NOT NULL DEFAULT true" in profile_projection
    assert "source_revision TIMESTAMPTZ NOT NULL" in profile_projection
    assert "snapshot_data JSONB NOT NULL" in profile_projection
    assert "ADD COLUMN" not in migration
