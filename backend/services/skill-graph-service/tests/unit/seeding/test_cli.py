"""Tests for skill graph seeding CLI."""

from __future__ import annotations

import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from skill_graph_service.seeding.cli import (
    _check_already_seeded,
    _count_seeded,
    _require_env,
    _resolve_optional_csv,
    _validate_csv_paths,
    _wait_for_schema,
)


class TestRequireEnv:
    """Tests for _require_env function."""

    def test_returns_value_when_set(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """_require_env returns the environment variable value when set."""
        monkeypatch.setenv("TEST_VAR", "test_value")
        result = _require_env("TEST_VAR")
        assert result == "test_value"

    def test_strips_whitespace(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """_require_env strips whitespace from the value."""
        monkeypatch.setenv("TEST_VAR", "  test_value  ")
        result = _require_env("TEST_VAR")
        assert result == "test_value"

    def test_exits_when_not_set(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """_require_env exits with code 1 when variable is not set."""
        monkeypatch.delenv("MISSING_VAR", raising=False)
        with pytest.raises(SystemExit) as exc_info:
            _require_env("MISSING_VAR")
        assert exc_info.value.code == 1

    def test_exits_when_empty(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """_require_env exits with code 1 when variable is empty string."""
        monkeypatch.setenv("EMPTY_VAR", "")
        with pytest.raises(SystemExit) as exc_info:
            _require_env("EMPTY_VAR")
        assert exc_info.value.code == 1

    def test_exits_when_only_whitespace(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """_require_env exits with code 1 when variable is only whitespace."""
        monkeypatch.setenv("WHITESPACE_VAR", "   ")
        with pytest.raises(SystemExit) as exc_info:
            _require_env("WHITESPACE_VAR")
        assert exc_info.value.code == 1


class TestResolveOptionalCsv:
    """Tests for _resolve_optional_csv function."""

    def test_returns_none_when_not_set(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """_resolve_optional_csv returns None when env var is not set."""
        monkeypatch.delenv("OPTIONAL_CSV", raising=False)
        result = _resolve_optional_csv("OPTIONAL_CSV")
        assert result is None

    def test_returns_none_when_empty(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """_resolve_optional_csv returns None when env var is empty."""
        monkeypatch.setenv("OPTIONAL_CSV", "")
        result = _resolve_optional_csv("OPTIONAL_CSV")
        assert result is None

    def test_returns_none_when_file_not_exists(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        """_resolve_optional_csv returns None when file does not exist."""
        nonexistent = tmp_path / "nonexistent.csv"
        monkeypatch.setenv("OPTIONAL_CSV", str(nonexistent))
        result = _resolve_optional_csv("OPTIONAL_CSV")
        assert result is None

    def test_returns_path_when_file_exists(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        """_resolve_optional_csv returns Path when file exists."""
        csv_file = tmp_path / "test.csv"
        csv_file.write_text("header\nvalue")
        monkeypatch.setenv("OPTIONAL_CSV", str(csv_file))
        result = _resolve_optional_csv("OPTIONAL_CSV")
        assert result == csv_file


class TestValidateCsvPaths:
    """Tests for _validate_csv_paths function."""

    def test_passes_when_all_files_exist(self, tmp_path: Path) -> None:
        """_validate_csv_paths does not exit when all files exist."""
        csv1 = tmp_path / "file1.csv"
        csv2 = tmp_path / "file2.csv"
        csv1.write_text("header")
        csv2.write_text("header")
        _validate_csv_paths({"VAR1": csv1, "VAR2": csv2})

    def test_exits_when_file_missing(self, tmp_path: Path) -> None:
        """_validate_csv_paths exits with code 1 when a file is missing."""
        missing = tmp_path / "missing.csv"
        with pytest.raises(SystemExit) as exc_info:
            _validate_csv_paths({"MISSING_VAR": missing})
        assert exc_info.value.code == 1


class TestPublishSeededEvent:
    """Tests for _publish_seeded_event function."""

    @pytest.mark.asyncio
    async def test_publishes_event(self) -> None:
        """_publish_seeded_event publishes SkillGraphSeeded to Kafka."""
        from skill_graph_service.seeding.cli import _publish_seeded_event

        mock_producer = MagicMock()
        mock_producer.__aenter__ = AsyncMock(return_value=mock_producer)
        mock_producer.__aexit__ = AsyncMock(return_value=None)
        mock_producer.publish = AsyncMock()

        with patch("skill_graph_service.seeding.cli.KafkaProducer", return_value=mock_producer):
            await _publish_seeded_event(
                bootstrap_servers="localhost:29092",
                source_version="1.2.0",
                skills_seeded=100,
                aliases_seeded=50,
                occupations_seeded=25,
            )

        mock_producer.publish.assert_called_once()
        call_args = mock_producer.publish.call_args
        event = call_args[0][1]
        assert event.source_version == "1.2.0"
        assert event.skills_seeded == 100
        assert event.aliases_seeded == 50
        assert event.occupations_seeded == 25


class TestRun:
    """Tests for _run function."""

    @pytest.mark.asyncio
    async def test_orchestrates_seeding(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        """_run orchestrates seeding from configured sources."""
        from skill_graph_service.seeding.cli import _run
        from skill_graph_service.seeding.domain.stats import SeedResult, SeedStats

        skills_csv = tmp_path / "skills.csv"
        skills_csv.write_text("ID,PREFERREDLABEL,DESCRIPTION,SKILLTYPE,REUSELEVEL\n")

        monkeypatch.setenv("TABIYA_SOURCE_VERSION", "1.2.0")
        monkeypatch.setenv("TABIYA_SKILLS_CSV", str(skills_csv))
        monkeypatch.delenv("TABIYA_RELATIONSHIPS_CSV", raising=False)
        monkeypatch.delenv("TABIYA_OCCUPATION_SKILLS_CSV", raising=False)
        monkeypatch.delenv("TABIYA_OCCUPATIONS_CSV", raising=False)
        monkeypatch.delenv("TABIYA_SKILL_GROUPS_CSV", raising=False)
        monkeypatch.delenv("TABIYA_SKILLS_HIERARCHY_CSV", raising=False)

        mock_settings = MagicMock()
        mock_settings.database = MagicMock()
        mock_settings.kafka.bootstrap_servers = "localhost:29092"

        mock_engine = MagicMock()
        mock_engine.dispose = AsyncMock()

        mock_result = SeedResult(
            source_name="tabiya",
            source_version="1.2.0",
            stats=SeedStats(skills_added=10, aliases_added=5, occupations_added=2),
        )

        mock_seeder = MagicMock()
        mock_seeder.seed = AsyncMock(return_value=[mock_result])

        with (
            patch("skill_graph_service.seeding.cli.get_settings", return_value=mock_settings),
            patch("skill_graph_service.seeding.cli.get_async_engine", return_value=mock_engine),
            patch("skill_graph_service.seeding.cli._wait_for_schema", new_callable=AsyncMock),
            patch("skill_graph_service.seeding.cli._check_already_seeded", new_callable=AsyncMock, return_value=False),
            patch("skill_graph_service.seeding.cli.SkillGraphSeeder", return_value=mock_seeder),
            patch("skill_graph_service.seeding.cli._publish_seeded_event", new_callable=AsyncMock) as mock_publish,
        ):
            await _run()

        mock_seeder.seed.assert_called_once()
        mock_publish.assert_called_once_with(
            bootstrap_servers="localhost:29092",
            source_version="1.2.0",
            skills_seeded=10,
            aliases_seeded=5,
            occupations_seeded=2,
        )
        mock_engine.dispose.assert_called_once()

    @pytest.mark.asyncio
    async def test_exits_on_seeding_failure(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        """_run exits with code 1 when seeding fails."""
        from skill_graph_service.seeding.cli import _run

        skills_csv = tmp_path / "skills.csv"
        skills_csv.write_text("ID,PREFERREDLABEL,DESCRIPTION,SKILLTYPE,REUSELEVEL\n")

        monkeypatch.setenv("TABIYA_SOURCE_VERSION", "1.2.0")
        monkeypatch.setenv("TABIYA_SKILLS_CSV", str(skills_csv))
        monkeypatch.delenv("TABIYA_RELATIONSHIPS_CSV", raising=False)
        monkeypatch.delenv("TABIYA_OCCUPATION_SKILLS_CSV", raising=False)
        monkeypatch.delenv("TABIYA_OCCUPATIONS_CSV", raising=False)
        monkeypatch.delenv("TABIYA_SKILL_GROUPS_CSV", raising=False)
        monkeypatch.delenv("TABIYA_SKILLS_HIERARCHY_CSV", raising=False)

        mock_settings = MagicMock()
        mock_settings.database = MagicMock()

        mock_engine = MagicMock()
        mock_engine.dispose = AsyncMock()

        mock_seeder = MagicMock()
        mock_seeder.seed = AsyncMock(side_effect=Exception("DB error"))

        with (
            patch("skill_graph_service.seeding.cli.get_settings", return_value=mock_settings),
            patch("skill_graph_service.seeding.cli.get_async_engine", return_value=mock_engine),
            patch("skill_graph_service.seeding.cli._wait_for_schema", new_callable=AsyncMock),
            patch("skill_graph_service.seeding.cli._check_already_seeded", new_callable=AsyncMock, return_value=False),
            patch("skill_graph_service.seeding.cli.SkillGraphSeeder", return_value=mock_seeder),
            patch("skill_graph_service.seeding.cli._publish_seeded_event", new_callable=AsyncMock),
            pytest.raises(SystemExit) as exc_info,
        ):
            await _run()

        assert exc_info.value.code == 1
        mock_engine.dispose.assert_called_once()

    @pytest.mark.asyncio
    async def test_skips_seeding_when_already_seeded(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        """_run skips SkillGraphSeeder but publishes event when already seeded."""
        from skill_graph_service.seeding.cli import _run

        skills_csv = tmp_path / "skills.csv"
        skills_csv.write_text("ID,PREFERREDLABEL,DESCRIPTION,SKILLTYPE,REUSELEVEL\n")

        monkeypatch.setenv("TABIYA_SOURCE_VERSION", "1.2.0")
        monkeypatch.setenv("TABIYA_SKILLS_CSV", str(skills_csv))
        monkeypatch.delenv("TABIYA_RELATIONSHIPS_CSV", raising=False)
        monkeypatch.delenv("TABIYA_OCCUPATION_SKILLS_CSV", raising=False)
        monkeypatch.delenv("TABIYA_OCCUPATIONS_CSV", raising=False)
        monkeypatch.delenv("TABIYA_SKILL_GROUPS_CSV", raising=False)
        monkeypatch.delenv("TABIYA_SKILLS_HIERARCHY_CSV", raising=False)

        mock_settings = MagicMock()
        mock_settings.database = MagicMock()
        mock_settings.kafka.bootstrap_servers = "localhost:29092"

        mock_engine = MagicMock()
        mock_engine.dispose = AsyncMock()

        with (
            patch("skill_graph_service.seeding.cli.get_settings", return_value=mock_settings),
            patch("skill_graph_service.seeding.cli.get_async_engine", return_value=mock_engine),
            patch("skill_graph_service.seeding.cli._wait_for_schema", new_callable=AsyncMock),
            patch(
                "skill_graph_service.seeding.cli._check_already_seeded",
                new_callable=AsyncMock,
                return_value=True,
            ),
            patch(
                "skill_graph_service.seeding.cli._count_seeded",
                new_callable=AsyncMock,
                return_value=(100, 50, 25),
            ),
            patch("skill_graph_service.seeding.cli.SkillGraphSeeder") as mock_seeder_cls,
            patch("skill_graph_service.seeding.cli._publish_seeded_event", new_callable=AsyncMock) as mock_publish,
        ):
            await _run()

        mock_seeder_cls.assert_not_called()
        mock_publish.assert_called_once_with(
            bootstrap_servers="localhost:29092",
            source_version="1.2.0",
            skills_seeded=100,
            aliases_seeded=50,
            occupations_seeded=25,
        )
        mock_engine.dispose.assert_called_once()


class TestMain:
    """Tests for main entrypoint."""

    def test_calls_asyncio_run(self) -> None:
        """main() calls asyncio.run with _run coroutine."""
        from skill_graph_service.seeding.cli import main

        with (
            patch("skill_graph_service.seeding.cli.asyncio.run") as mock_run,
            patch("skill_graph_service.seeding.cli._run", new_callable=MagicMock) as mock_run_coro,
        ):
            mock_run_coro.return_value = MagicMock()
            main()
            mock_run.assert_called_once()


class TestWaitForSchema:
    """Tests for _wait_for_schema function."""

    @staticmethod
    def _make_engine_with_conn(mock_conn: AsyncMock) -> MagicMock:
        """Build a mock engine whose connect() yields mock_conn."""
        ctx = AsyncMock()
        ctx.__aenter__.return_value = mock_conn
        ctx.__aexit__.return_value = None
        engine = MagicMock()
        engine.connect.return_value = ctx
        return engine

    @pytest.mark.asyncio
    async def test_returns_when_schema_ready(self) -> None:
        """_wait_for_schema returns immediately when schema exists."""
        mock_conn = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar.return_value = 1
        mock_conn.execute.return_value = mock_result

        engine = self._make_engine_with_conn(mock_conn)
        await _wait_for_schema(engine, "test_schema")

    @pytest.mark.asyncio
    async def test_raises_on_timeout(self) -> None:
        """_wait_for_schema does not round the timeout up to the poll interval."""
        mock_conn = AsyncMock()
        mock_conn.execute.side_effect = Exception("relation does not exist")

        engine = self._make_engine_with_conn(mock_conn)

        started = time.monotonic()
        with pytest.raises(RuntimeError, match="not ready after"):
            await _wait_for_schema(engine, "test_schema", max_wait=0.05)

        assert time.monotonic() - started < 0.2

    @pytest.mark.asyncio
    async def test_retries_until_ready(self) -> None:
        """_wait_for_schema retries on failure then succeeds."""
        mock_conn = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar.return_value = 1
        mock_conn.execute.side_effect = [Exception("not yet"), mock_result]

        engine = self._make_engine_with_conn(mock_conn)

        with patch("skill_graph_service.seeding.cli.asyncio.sleep", new_callable=AsyncMock):
            await _wait_for_schema(engine, "test_schema")


class TestCheckAlreadySeeded:
    """Tests for _check_already_seeded function."""

    @staticmethod
    def _make_engine_with_conn(mock_conn: AsyncMock) -> MagicMock:
        """Build a mock engine whose connect() yields mock_conn."""
        ctx = AsyncMock()
        ctx.__aenter__.return_value = mock_conn
        ctx.__aexit__.return_value = None
        engine = MagicMock()
        engine.connect.return_value = ctx
        return engine

    @pytest.mark.asyncio
    async def test_returns_true_when_skills_exist(self) -> None:
        """_check_already_seeded returns True when skill_node has rows."""
        mock_conn = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar.return_value = 42
        mock_conn.execute.return_value = mock_result

        engine = self._make_engine_with_conn(mock_conn)
        result = await _check_already_seeded(engine, "test_schema")
        assert result is True

    @pytest.mark.asyncio
    async def test_returns_false_when_empty(self) -> None:
        """_check_already_seeded returns False when skill_node is empty."""
        mock_conn = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar.return_value = 0
        mock_conn.execute.return_value = mock_result

        engine = self._make_engine_with_conn(mock_conn)
        result = await _check_already_seeded(engine, "test_schema")
        assert result is False


class TestCountSeeded:
    """Tests for _count_seeded function."""

    @pytest.mark.asyncio
    async def test_returns_counts(self) -> None:
        """_count_seeded returns tuple of (skills, aliases, occupations)."""
        mock_conn = AsyncMock()

        result_skills = MagicMock()
        result_skills.scalar.return_value = 100
        result_aliases = MagicMock()
        result_aliases.scalar.return_value = 50
        result_occupations = MagicMock()
        result_occupations.scalar.return_value = 25
        mock_conn.execute.side_effect = [result_skills, result_aliases, result_occupations]

        ctx = AsyncMock()
        ctx.__aenter__.return_value = mock_conn
        ctx.__aexit__.return_value = None
        engine = MagicMock()
        engine.connect.return_value = ctx

        skills, aliases, occupations = await _count_seeded(engine, "test_schema")
        assert skills == 100
        assert aliases == 50
        assert occupations == 25
