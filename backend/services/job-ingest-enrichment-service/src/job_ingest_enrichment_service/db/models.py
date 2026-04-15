"""SQLAlchemy models for job-ingest-enrichment-service."""

from __future__ import annotations

from typing import Final

from nohiki_db_utils import SagaBaseMixin
from sqlalchemy import String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

SCHEMA_NAME: Final[str] = "job_ingest_enrichment_schema"


class Base(DeclarativeBase):
    """SQLAlchemy declarative base for job-ingest-enrichment-service."""


class EnrichmentEmbeddingSaga(SagaBaseMixin, Base):
    """Saga tracking convergence of parallel embedding requests for job enrichment.

    Created when SkillNormalizationCallback arrives. Waits for retrieval, title,
    and skills EmbeddingCallback messages before publishing EnrichmentCompleted.

    """

    __tablename__ = "enrichment_embedding_saga"
    __table_args__ = ({"schema": "job_ingest_enrichment_schema"},)

    listing_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)

    enrichment_data_json: Mapped[str] = mapped_column(Text, nullable=False)
    llm_model_id: Mapped[str] = mapped_column(String(255), nullable=False)
    collection_version: Mapped[str] = mapped_column(String(10), nullable=False)

    retrieval_embedding_b64: Mapped[str | None] = mapped_column(Text, nullable=True)

    title_embedding_b64: Mapped[str | None] = mapped_column(Text, nullable=True)

    skills_embedding_b64: Mapped[str | None] = mapped_column(Text, nullable=True)
