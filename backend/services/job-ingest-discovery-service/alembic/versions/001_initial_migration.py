"""Create durable discovery command idempotency state."""

from alembic import op
from nohiki_db_utils.idempotency_migrations import (
    get_create_processed_events_index_sql,
    get_create_processed_events_sql,
)

revision = "001"
down_revision = None
branch_labels = None
depends_on = None

SCHEMA_NAME = "job_ingest_discovery_schema"


def upgrade() -> None:
    """Create the processed event claim table."""
    op.execute(f"CREATE SCHEMA IF NOT EXISTS {SCHEMA_NAME}")
    op.execute(get_create_processed_events_sql(SCHEMA_NAME))
    op.execute(get_create_processed_events_index_sql(SCHEMA_NAME))


def downgrade() -> None:
    """Drop discovery idempotency state."""
    op.execute(f"DROP TABLE IF EXISTS {SCHEMA_NAME}.processed_events CASCADE")
