"""SkillGraphSeeder: orchestrates seeding from multiple SkillDataSource instances."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Final, assert_never

from nohiki_observability import get_logger
from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert

from skill_graph_service.db.models import (
    OccupationNode,
    OccupationSkillRelation,
    SeedBatchRecord,
    SkillAlias,
    SkillNode,
    SkillRelationship,
    SkillSeedProvenance,
)
from skill_graph_service.seeding.domain.records import (
    AliasRecord,
    OccupationRecord,
    OccupationSkillRecord,
    RelationshipRecord,
    SkillRecord,
)
from skill_graph_service.seeding.domain.stats import SeedResult, SeedStats
from skill_graph_service.seeding.domain.strategies import ConflictStrategy
from skill_graph_service.seeding.normalizer import normalize_skill_text

if TYPE_CHECKING:
    from collections.abc import Iterator

    from sqlalchemy.ext.asyncio import AsyncEngine

    from skill_graph_service.seeding.protocols.source import SkillDataSource

logger = get_logger(__name__)

_DEFAULT_BATCH_SIZE: Final[int] = 1000
_STATUS_RUNNING: Final[str] = "running"
_STATUS_COMPLETED: Final[str] = "completed"
_STATUS_FAILED: Final[str] = "failed"

_SKILL_NODE_UPSERT_FIELDS: Final[list[str]] = [
    "display_name",
    "skill_type",
    "reuse_level",
    "category",
    "subcategory",
    "description",
]
_ALIAS_UPSERT_FIELDS: Final[list[str]] = ["source_version", "confidence"]
_PROVENANCE_UPSERT_FIELDS: Final[list[str]] = [
    "source_version",
    "authority",
    "external_id",
    "external_uri",
    "updated_at",
]


def _batched[T](items: list[T], size: int) -> Iterator[list[T]]:
    """Yield successive non-overlapping slices of at most `size` items."""
    for start in range(0, len(items), size):
        yield items[start : start + size]


def _collect_referenced_texts(
    aliases: list[AliasRecord],
    relationships: list[RelationshipRecord],
    occupations: list[OccupationSkillRecord],
) -> set[str]:
    """Collect all normalized skill texts referenced as FK targets across all record types."""
    texts: set[str] = set()
    for alias in aliases:
        texts.add(normalize_skill_text(alias.skill_normalized_text))
    for rel in relationships:
        texts.add(normalize_skill_text(rel.source_normalized_text))
        texts.add(normalize_skill_text(rel.target_normalized_text))
    for occ in occupations:
        texts.add(normalize_skill_text(occ.skill_normalized_text))
    texts.discard("")
    return texts


def _raise_if_seed_errors(stats: SeedStats) -> None:
    """Fail a source run when any records were rejected."""
    if stats.error_count:
        msg = f"Seeding completed with {stats.error_count} rejected records"
        raise RuntimeError(msg)


class SkillGraphSeeder:
    """Orchestrates seeding from one or more SkillDataSource instances."""

    def __init__(
        self,
        sources: list[SkillDataSource],
        engine: AsyncEngine,
        *,
        batch_size: int = _DEFAULT_BATCH_SIZE,
    ) -> None:
        """Initialize the seeder.

        Args:
            sources: Ordered list of data sources to seed from.
            engine: Async SQLAlchemy engine connected to the target database.
            batch_size: Number of rows per INSERT batch.

        """
        self._sources = sources
        self._engine = engine
        self._batch_size = batch_size

    async def seed(self) -> list[SeedResult]:
        """Seed all registered sources in order."""
        results: list[SeedResult] = []
        for source in self._sources:
            result = await self._seed_source(source)
            results.append(result)
        return results

    async def _seed_source(self, source: SkillDataSource) -> SeedResult:
        """Seed a single source end-to-end, tracking lifecycle in seed_batch_record."""
        skill_records = list(source.iter_skills())
        alias_records = list(source.iter_aliases())
        rel_records = list(source.iter_relationships())
        occ_relation_records = list(source.iter_occupation_relations())
        occupation_records = list(source.iter_occupations())

        batch_id = await self._start_batch_record(source)
        stats = SeedStats()

        try:
            skill_stats, attempted_texts = await self._insert_skills(source, skill_records)
            stats = stats + skill_stats

            all_texts = attempted_texts | _collect_referenced_texts(alias_records, rel_records, occ_relation_records)
            id_map = await self._load_skill_ids_by_texts(all_texts)

            await self._upsert_provenance(source, skill_records, id_map)

            alias_stats = await self._insert_aliases(source, alias_records, id_map)
            stats = stats + alias_stats

            rel_stats = await self._insert_relationships(source, rel_records, id_map)
            stats = stats + rel_stats

            occ_rel_stats = await self._insert_occupation_relations(source, occ_relation_records, id_map)
            stats = stats + occ_rel_stats

            occupation_stats = await self._insert_occupations(source, occupation_records)
            stats = stats + occupation_stats

            _raise_if_seed_errors(stats)

            await self._complete_batch_record(batch_id, stats, _STATUS_COMPLETED)

        except Exception:
            logger.exception(
                "Seeding failed for source",
                source_name=source.source_name,
                source_version=source.source_version,
            )
            await self._complete_batch_record(batch_id, stats, _STATUS_FAILED)
            raise

        logger.info(
            "Seeding completed",
            source_name=source.source_name,
            source_version=source.source_version,
            skills_added=stats.skills_added,
            aliases_added=stats.aliases_added,
        )

        return SeedResult(
            source_name=source.source_name,
            source_version=source.source_version,
            stats=stats,
            completed_at=datetime.now(UTC),
        )

    async def _start_batch_record(self, source: SkillDataSource) -> uuid.UUID:
        """Insert or reset a seed_batch_record with status='running'; return its DB-assigned id."""
        now = datetime.now(UTC)
        stmt = (
            insert(SeedBatchRecord)
            .values(
                source_name=source.source_name,
                source_version=source.source_version,
                status=_STATUS_RUNNING,
                started_at=now,
            )
            .on_conflict_do_update(
                index_elements=["source_name", "source_version"],
                set_={
                    "status": _STATUS_RUNNING,
                    "started_at": now,
                    "completed_at": None,
                    "skills_added": 0,
                    "skills_updated": 0,
                    "aliases_added": 0,
                    "relationships_added": 0,
                    "occupation_relations_added": 0,
                    "occupations_added": 0,
                    "error_count": 0,
                    "error_details": None,
                },
            )
            .returning(SeedBatchRecord.id)
        )
        async with self._engine.begin() as conn:
            result = await conn.execute(stmt)
            return result.scalar_one()

    async def _complete_batch_record(
        self,
        batch_id: uuid.UUID,
        stats: SeedStats,
        status: str,
    ) -> None:
        """Update seed_batch_record with final stats and terminal status."""
        stmt = (
            update(SeedBatchRecord)
            .where(SeedBatchRecord.id == batch_id)
            .values(
                status=status,
                skills_added=stats.skills_added,
                skills_updated=stats.skills_updated,
                aliases_added=stats.aliases_added,
                relationships_added=stats.relationships_added,
                occupation_relations_added=stats.occupation_relations_added,
                occupations_added=stats.occupations_added,
                error_count=stats.error_count,
                completed_at=datetime.now(UTC),
            )
        )
        async with self._engine.begin() as conn:
            await conn.execute(stmt)

    async def _load_skill_ids_by_texts(self, texts: set[str]) -> dict[str, uuid.UUID]:
        """Load normalized_text → skill_node.id for all given texts in one query."""
        if not texts:
            return {}
        stmt = select(SkillNode.normalized_text, SkillNode.id).where(SkillNode.normalized_text.in_(texts))
        async with self._engine.connect() as conn:
            result = await conn.execute(stmt)
            return {row.normalized_text: row.id for row in result.fetchall()}

    async def _insert_skills(
        self,
        source: SkillDataSource,
        records: list[SkillRecord],
    ) -> tuple[SeedStats, set[str]]:
        """Batch-insert skill_node rows."""
        attempted_texts: set[str] = set()
        added = 0
        updated = 0
        errors = 0

        for batch in _batched(records, self._batch_size):
            try:
                (
                    batch_texts,
                    batch_added,
                    batch_updated,
                ) = await self._insert_skill_batch(source, batch)
                attempted_texts |= batch_texts
                added += batch_added
                updated += batch_updated
            except Exception:
                logger.exception("Skill batch insert failed", batch_size=len(batch))
                errors += len(batch)

        return SeedStats(skills_added=added, skills_updated=updated, error_count=errors), attempted_texts

    async def _insert_skill_batch(
        self,
        source: SkillDataSource,
        skills: list[SkillRecord],
    ) -> tuple[set[str], int, int]:
        """Insert one batch of skill records."""
        values: list[dict[str, object]] = []
        texts_attempted: set[str] = set()

        for skill in skills:
            if norm := normalize_skill_text(skill.normalized_text):
                texts_attempted.add(norm)
                values.append(
                    {
                        "normalized_text": norm,
                        "display_name": skill.display_name,
                        "skill_type": skill.skill_type,
                        "reuse_level": skill.reuse_level,
                        "category": skill.category,
                        "subcategory": skill.subcategory,
                        "description": skill.description,
                    }
                )

        if not values:
            return texts_attempted, 0, 0

        base_stmt = insert(SkillNode)
        match source.conflict_strategy:
            case ConflictStrategy.SKIP | ConflictStrategy.VERSION_GATE_UPDATE:
                stmt = base_stmt.values(values).on_conflict_do_nothing(index_elements=["normalized_text"])
            case ConflictStrategy.UPSERT:
                stmt = base_stmt.values(values).on_conflict_do_update(
                    index_elements=["normalized_text"],
                    set_={f: base_stmt.excluded[f] for f in _SKILL_NODE_UPSERT_FIELDS},
                )
            case _:
                assert_never(source.conflict_strategy)

        async with self._engine.begin() as conn:
            result = await conn.execute(stmt)

        rowcount = max(0, result.rowcount) if result.rowcount >= 0 else 0
        match source.conflict_strategy:
            case ConflictStrategy.SKIP | ConflictStrategy.VERSION_GATE_UPDATE:
                return texts_attempted, rowcount, 0
            case ConflictStrategy.UPSERT:
                return texts_attempted, rowcount, len(values) - rowcount
            case _:
                assert_never(source.conflict_strategy)

    async def _upsert_provenance(
        self,
        source: SkillDataSource,
        records: list[SkillRecord],
        id_map: dict[str, uuid.UUID],
    ) -> None:
        """Bulk-upsert skill_seed_provenance for all successfully inserted skills."""
        now = datetime.now(UTC)
        values: list[dict[str, object]] = [
            {
                "skill_id": skill_id,
                "source_name": source.source_name,
                "source_version": source.source_version,
                "authority": source.authority.value,
                "external_id": skill.external_id,
                "external_uri": skill.external_uri,
                "seeded_at": now,
                "updated_at": now,
            }
            for skill in records
            if (skill_id := id_map.get(normalize_skill_text(skill.normalized_text))) is not None
        ]

        for batch in _batched(values, self._batch_size):
            base_stmt = insert(SkillSeedProvenance).values(batch)
            stmt = base_stmt.on_conflict_do_update(
                index_elements=["skill_id", "source_name"],
                set_={f: base_stmt.excluded[f] for f in _PROVENANCE_UPSERT_FIELDS},
            )
            async with self._engine.begin() as conn:
                await conn.execute(stmt)

    async def _insert_aliases(
        self,
        source: SkillDataSource,
        records: list[AliasRecord],
        id_map: dict[str, uuid.UUID],
    ) -> SeedStats:
        """Batch-insert skill_alias rows."""
        added = 0
        errors = 0

        for batch in _batched(records, self._batch_size):
            try:
                added += await self._insert_alias_batch(source, batch, id_map)
            except Exception:
                logger.exception("Alias batch insert failed", batch_size=len(batch))
                errors += len(batch)

        return SeedStats(aliases_added=added, error_count=errors)

    async def _insert_alias_batch(
        self,
        source: SkillDataSource,
        aliases: list[AliasRecord],
        id_map: dict[str, uuid.UUID],
    ) -> int:
        """Insert one batch of alias records, returning count of rows affected."""
        values_by_key: dict[tuple[str, str | None], dict[str, object]] = {}
        for alias in aliases:
            norm_alias = normalize_skill_text(alias.alias_text)
            norm_skill = normalize_skill_text(alias.skill_normalized_text)
            if not norm_alias or (skill_id := id_map.get(norm_skill)) is None:
                continue
            values_by_key[(norm_alias, alias.context_hint)] = {
                "alias_text": norm_alias,
                "canonical_skill_id": skill_id,
                "context_hint": alias.context_hint,
                "source": source.source_name,
                "source_version": source.source_version,
                "confidence": alias.confidence,
                "usage_count": 0,
            }

        if not values_by_key:
            return 0

        async with self._engine.begin() as conn:
            universal_aliases = {alias for alias, context in values_by_key if context is None}
            if universal_aliases:
                existing_result = await conn.execute(
                    select(SkillAlias.alias_text).where(
                        SkillAlias.alias_text.in_(universal_aliases),
                        SkillAlias.context_hint.is_(None),
                    )
                )
                existing_universal = set(existing_result.scalars().all())
                for alias in existing_universal:
                    values_by_key.pop((alias, None), None)

            values = list(values_by_key.values())
            if not values:
                return 0

            base_stmt = insert(SkillAlias)
            match source.conflict_strategy:
                case ConflictStrategy.SKIP:
                    stmt = base_stmt.values(values).on_conflict_do_nothing(
                        index_elements=["alias_text", "context_hint"]
                    )
                case ConflictStrategy.UPSERT | ConflictStrategy.VERSION_GATE_UPDATE:
                    stmt = base_stmt.values(values).on_conflict_do_update(
                        index_elements=["alias_text", "context_hint"],
                        set_={f: base_stmt.excluded[f] for f in _ALIAS_UPSERT_FIELDS},
                    )
                case _:
                    assert_never(source.conflict_strategy)

            result = await conn.execute(stmt)
        return max(0, result.rowcount) if result.rowcount >= 0 else 0

    async def _insert_relationships(
        self,
        source: SkillDataSource,
        records: list[RelationshipRecord],
        id_map: dict[str, uuid.UUID],
    ) -> SeedStats:
        """Batch-insert skill_relationship rows."""
        added = 0
        errors = 0

        for batch in _batched(records, self._batch_size):
            try:
                added += await self._insert_relationship_batch(source, batch, id_map)
            except Exception:
                logger.exception("Relationship batch insert failed", batch_size=len(batch))
                errors += len(batch)

        return SeedStats(relationships_added=added, error_count=errors)

    async def _insert_relationship_batch(
        self,
        source: SkillDataSource,
        relationships: list[RelationshipRecord],
        id_map: dict[str, uuid.UUID],
    ) -> int:
        """Insert one batch of relationship records."""
        values: list[dict[str, object]] = []
        for rel in relationships:
            src_id = id_map.get(normalize_skill_text(rel.source_normalized_text))
            tgt_id = id_map.get(normalize_skill_text(rel.target_normalized_text))
            if src_id is None or tgt_id is None:
                continue
            values.append(
                {
                    "source_skill_id": src_id,
                    "target_skill_id": tgt_id,
                    "relationship_type": rel.relationship_type,
                    "strength": rel.strength,
                    "bidirectional": rel.bidirectional,
                    "source": source.source_name,
                    "source_version": source.source_version,
                }
            )

        if not values:
            return 0

        stmt = (
            insert(SkillRelationship)
            .values(values)
            .on_conflict_do_nothing(index_elements=["source_skill_id", "target_skill_id", "relationship_type"])
        )
        async with self._engine.begin() as conn:
            result = await conn.execute(stmt)
        return max(0, result.rowcount) if result.rowcount >= 0 else 0

    async def _insert_occupation_relations(
        self,
        source: SkillDataSource,
        records: list[OccupationSkillRecord],
        id_map: dict[str, uuid.UUID],
    ) -> SeedStats:
        """Batch-insert occupation_skill_relation rows."""
        added = 0
        errors = 0

        for batch in _batched(records, self._batch_size):
            try:
                added += await self._insert_occupation_relation_batch(source, batch, id_map)
            except Exception:
                logger.exception("Occupation relation batch insert failed", batch_size=len(batch))
                errors += len(batch)

        return SeedStats(occupation_relations_added=added, error_count=errors)

    async def _insert_occupation_relation_batch(
        self,
        source: SkillDataSource,
        relations: list[OccupationSkillRecord],
        id_map: dict[str, uuid.UUID],
    ) -> int:
        """Insert one batch of occupation-skill relation records."""
        values: list[dict[str, object]] = []
        for rel in relations:
            if (skill_id := id_map.get(normalize_skill_text(rel.skill_normalized_text))) is None:
                continue
            values.append(
                {
                    "occupation_code": rel.occupation_code,
                    "occupation_label": rel.occupation_label,
                    "skill_id": skill_id,
                    "relation_type": rel.relation_type,
                    "source_name": source.source_name,
                    "source_version": source.source_version,
                    "source_metadata": rel.source_metadata,
                }
            )

        if not values:
            return 0

        stmt = (
            insert(OccupationSkillRelation)
            .values(values)
            .on_conflict_do_nothing(index_elements=["occupation_code", "skill_id", "source_name"])
        )
        async with self._engine.begin() as conn:
            result = await conn.execute(stmt)
        return max(0, result.rowcount) if result.rowcount >= 0 else 0

    async def _insert_occupations(
        self,
        source: SkillDataSource,
        records: list[OccupationRecord],
    ) -> SeedStats:
        """Insert occupation records into occupation_node table."""
        added = 0
        errors = 0

        for batch in _batched(records, self._batch_size):
            try:
                added += await self._insert_occupation_node_batch(source, batch)
            except Exception:
                logger.exception("Occupation node batch insert failed", batch_size=len(batch))
                errors += len(batch)

        return SeedStats(occupations_added=added, error_count=errors)

    async def _insert_occupation_node_batch(
        self,
        source: SkillDataSource,
        occupations: list[OccupationRecord],
    ) -> int:
        """Insert one batch of occupation records into occupation_node table."""
        values: list[dict[str, object]] = [
            {
                "occupation_code": occ.occupation_code,
                "preferred_label": occ.preferred_label,
                "description": occ.description,
                "alt_labels": occ.alt_labels,
                "isco_group_code": occ.isco_group_code,
                "occupation_type": occ.occupation_type,
                "source_name": source.source_name,
                "source_version": source.source_version,
            }
            for occ in occupations
        ]

        if not values:
            return 0

        stmt = insert(OccupationNode).values(values).on_conflict_do_nothing(index_elements=["occupation_code"])
        async with self._engine.begin() as conn:
            result = await conn.execute(stmt)
        return max(0, result.rowcount) if result.rowcount >= 0 else 0
