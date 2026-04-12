"""Tests for template seeder."""

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from doc_template_service.core.seeder import (
    SEED_TEMPLATES_DIR,
    SYSTEM_SERVICE_UUID,
    _load_template_file,
    _seed_template,
    seed_default_templates,
)
from nohiki_db_utils.testing import create_mock_session


class TestConstants:
    """Tests for seeder constants."""

    def test_system_service_uuid_is_uuid(self) -> None:
        """Test that SYSTEM_SERVICE_UUID is a valid UUID."""
        import uuid

        assert isinstance(SYSTEM_SERVICE_UUID, uuid.UUID)

    def test_seed_templates_dir_is_path(self) -> None:
        """Test that SEED_TEMPLATES_DIR is a Path."""
        assert isinstance(SEED_TEMPLATES_DIR, Path)

    @pytest.mark.parametrize("template_file", sorted(SEED_TEMPLATES_DIR.glob("*.html")))
    def test_bundled_seed_has_explicit_title(self, template_file: Path) -> None:
        """Every shipped seed supplies a friendly title distinct from its machine key."""
        from doc_template_service.core.metadata import parse_template_metadata

        metadata = parse_template_metadata(template_file.read_text())

        assert metadata["title"].strip()
        assert metadata["title"] != metadata["name"]


class TestLoadLayoutFile:
    """Tests for _load_template_file function."""

    def test_load_existing_file(self, tmp_path: Path) -> None:
        """Test loading an existing template file."""
        template_file = tmp_path / "test.html"
        template_file.write_text("<html><body>Test</body></html>")

        content = _load_template_file(template_file)

        assert content == "<html><body>Test</body></html>"

    def test_load_nonexistent_file(self, tmp_path: Path) -> None:
        """Test loading a nonexistent file returns None."""
        template_file = tmp_path / "nonexistent.html"

        content = _load_template_file(template_file)

        assert content is None


class TestSeedDefaultLayouts:
    """Tests for seed_default_templates function."""

    @pytest.mark.asyncio
    async def test_skips_when_seeding_disabled(self) -> None:
        """Test that seeding is skipped when should_run_seeding returns False."""
        with patch("doc_template_service.core.seeder.should_run_seeding", return_value=False):
            # Should return early without doing anything
            await seed_default_templates()

    @pytest.mark.asyncio
    async def test_skips_when_directory_not_found(self) -> None:
        """Test that seeding is skipped when seed directory doesn't exist."""
        with (
            patch("doc_template_service.core.seeder.should_run_seeding", return_value=True),
            patch("doc_template_service.core.seeder.SEED_TEMPLATES_DIR") as mock_dir,
        ):
            mock_dir.exists.return_value = False
            await seed_default_templates()

    @pytest.mark.asyncio
    async def test_skips_when_no_template_files(self, tmp_path: Path) -> None:
        """Test that seeding is skipped when no template files found."""
        with (
            patch("doc_template_service.core.seeder.should_run_seeding", return_value=True),
            patch("doc_template_service.core.seeder.SEED_TEMPLATES_DIR", tmp_path),
        ):
            await seed_default_templates()


class TestSeedLayout:
    """Tests for _seed_template function."""

    @pytest.mark.asyncio
    async def test_skips_when_file_load_fails(self, tmp_path: Path) -> None:
        """Test that seeding is skipped when file load fails."""
        mock_session = create_mock_session()
        template_file = tmp_path / "nonexistent.html"

        await _seed_template(mock_session, template_file)

        # Should not call any session methods
        mock_session.execute.assert_not_called()

    @pytest.mark.asyncio
    async def test_skips_when_metadata_parse_fails(self, tmp_path: Path) -> None:
        """Test that seeding is skipped when metadata parsing fails."""
        mock_session = create_mock_session()
        template_file = tmp_path / "invalid.html"
        template_file.write_text("<html>No metadata</html>")

        await _seed_template(mock_session, template_file)

        # Should not call any session methods
        mock_session.execute.assert_not_called()

    @pytest.mark.asyncio
    async def test_skips_when_template_exists(self, tmp_path: Path) -> None:
        """Test that seeding is skipped when template already exists."""
        mock_session = create_mock_session()
        template_file = tmp_path / "existing.html"
        template_content = (
            '<!-- TMPL_META {"name": "test-template", "title": "Test", "namespace": "default", '
            '"version": "1.0.0", "description": "Test", "access_scope": "PUBLIC", "visibility": "public"} -->'
            "<html><body>Test</body></html>"
        )
        template_file.write_text(template_content)

        with patch(
            "doc_template_service.core.seeder.get_latest_template",
            new_callable=AsyncMock,
            return_value=type(
                "ExistingTemplate",
                (),
                {"version": "1.0.0", "template_content": template_content},
            )(),
        ):
            await _seed_template(mock_session, template_file)

        mock_session.execute.assert_not_called()

    @pytest.mark.asyncio
    async def test_creates_new_version_when_seed_content_changed(self, tmp_path: Path) -> None:
        """A repaired seed converges an existing deployment through an immutable new version."""
        mock_session = create_mock_session()
        template_file = tmp_path / "repaired.html"
        template_content = (
            '<!-- TMPL_META {"name": "resume", "title": "Resume", "namespace": "resume", '
            '"version": "1.1.0", "description": "Repaired", "access_scope": "SYSTEM", '
            '"visibility": "public", "requires_javascript": {"required": false}} -->'
            "<html><body>{{ full_name }}</body></html>"
        )
        template_file.write_text(template_content)
        existing = type(
            "ExistingTemplate",
            (),
            {"version": "1.0.0", "template_content": "<html>old unsafe seed</html>"},
        )()

        with (
            patch(
                "doc_template_service.core.seeder._load_seed_schema",
                return_value={"type": "object", "required": ["full_name"]},
            ),
            patch(
                "doc_template_service.core.seeder.get_latest_template",
                new_callable=AsyncMock,
                return_value=existing,
            ),
            patch(
                "doc_template_service.core.seeder.create_template",
                new_callable=AsyncMock,
            ) as mock_create,
            patch(
                "doc_template_service.core.seeder.publish_template_created_event",
                new_callable=AsyncMock,
            ),
        ):
            await _seed_template(mock_session, template_file)

        assert mock_create.await_args is not None
        request = mock_create.await_args.args[1]
        assert request.version == "1.1.0"
        assert request.template_content == template_content

    @pytest.mark.asyncio
    async def test_skips_exact_repaired_seed_on_subsequent_startup(self, tmp_path: Path) -> None:
        """Convergence is idempotent once version and content match the repaired seed."""
        mock_session = create_mock_session()
        template_file = tmp_path / "repaired.html"
        template_content = (
            '<!-- TMPL_META {"name": "resume", "title": "Resume", "namespace": "resume", '
            '"version": "1.1.0", "description": "Repaired", "access_scope": "SYSTEM", "visibility": "public"} -->'
            "<html><body>{{ full_name }}</body></html>"
        )
        template_file.write_text(template_content)
        existing = type(
            "ExistingTemplate",
            (),
            {"version": "1.1.0", "template_content": template_content},
        )()

        with (
            patch(
                "doc_template_service.core.seeder.get_latest_template",
                new_callable=AsyncMock,
                return_value=existing,
            ),
            patch(
                "doc_template_service.core.seeder.create_template",
                new_callable=AsyncMock,
            ) as mock_create,
        ):
            await _seed_template(mock_session, template_file)

        mock_create.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_creates_layout_when_not_exists(self, tmp_path: Path) -> None:
        """Test that template is created when it doesn't exist."""
        mock_session = create_mock_session()
        template_file = tmp_path / "new.html"
        template_content = (
            '<!-- TMPL_META {"name": "new-template", "title": "New Template", "namespace": "default", '
            '"version": "1.0.0", "description": "New", "access_scope": "PUBLIC", "visibility": "public"} -->'
            "<html><body>New</body></html>"
        )
        template_file.write_text(template_content)

        with (
            patch(
                "doc_template_service.core.seeder.get_latest_template",
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch(
                "doc_template_service.core.seeder.create_template",
                new_callable=AsyncMock,
            ) as mock_create,
            patch(
                "doc_template_service.core.seeder.publish_template_created_event",
                new_callable=AsyncMock,
            ),
        ):
            await _seed_template(mock_session, template_file)
            mock_create.assert_called_once()
        assert mock_create.await_args is not None
        request = mock_create.await_args.args[1]
        assert request.display_name == "New Template"

    @pytest.mark.asyncio
    async def test_handles_integrity_error(self, tmp_path: Path) -> None:
        """Test that IntegrityError is handled gracefully."""
        from sqlalchemy.exc import IntegrityError

        mock_session = create_mock_session()
        template_file = tmp_path / "race.html"
        template_content = (
            '<!-- TMPL_META {"name": "race-template", "title": "Race", "namespace": "default", '
            '"version": "1.0.0", "description": "Race", "access_scope": "PUBLIC", "visibility": "public"} -->'
            "<html><body>Race</body></html>"
        )
        template_file.write_text(template_content)

        with (
            patch(
                "doc_template_service.core.seeder.get_latest_template",
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch(
                "doc_template_service.core.seeder.create_template",
                new_callable=AsyncMock,
                side_effect=IntegrityError("duplicate", {}, Exception("duplicate key")),
            ),
            patch(
                "doc_template_service.core.seeder.publish_template_created_event",
                new_callable=AsyncMock,
            ),
        ):
            await _seed_template(mock_session, template_file)
            mock_session.rollback.assert_called_once()

    @pytest.mark.asyncio
    async def test_handles_timeout_error(self, tmp_path: Path) -> None:
        """Test that TimeoutError is handled gracefully."""
        mock_session = create_mock_session()
        template_file = tmp_path / "timeout.html"
        template_content = (
            '<!-- TMPL_META {"name": "timeout-template", "title": "Timeout", "namespace": "default", '
            '"version": "1.0.0", "description": "Timeout", "access_scope": "PUBLIC", "visibility": "public"} -->'
            "<html><body>Timeout</body></html>"
        )
        template_file.write_text(template_content)

        with (
            patch(
                "doc_template_service.core.seeder.get_latest_template",
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch(
                "doc_template_service.core.seeder.create_template",
                new_callable=AsyncMock,
                side_effect=TimeoutError("timed out"),
            ),
            patch(
                "doc_template_service.core.seeder.publish_template_created_event",
                new_callable=AsyncMock,
            ),
        ):
            await _seed_template(mock_session, template_file)
            mock_session.rollback.assert_called_once()


class TestShouldRunSeeding:
    """Tests for should_run_seeding function."""

    def test_returns_bool(self) -> None:
        """Test that should_run_seeding returns a boolean."""
        from doc_template_service.core.seeder import should_run_seeding

        result = should_run_seeding()
        assert isinstance(result, bool)


class TestSeedDefaultLayoutsWithFiles:
    """Tests for seed_default_templates with actual file processing."""

    @pytest.mark.asyncio
    async def test_processes_template_files(self, tmp_path: Path) -> None:
        """Test that template files are processed."""
        # Create a valid template file
        template_content = (
            '<!-- TMPL_META {"name": "test-template", "title": "Test", "namespace": "default", '
            '"version": "1.0.0", "description": "Test", "access_scope": "PUBLIC", "visibility": "public"} -->'
            "<html><body>Test</body></html>"
        )
        template_file = tmp_path / "test.html"
        template_file.write_text(template_content)

        mock_session = create_mock_session()

        with (
            patch("doc_template_service.core.seeder.should_run_seeding", return_value=True),
            patch("doc_template_service.core.seeder.SEED_TEMPLATES_DIR", tmp_path),
            patch("doc_template_service.core.seeder.get_async_sessionmaker") as mock_sessionmaker,
            patch(
                "doc_template_service.core.seeder.get_latest_template",
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch(
                "doc_template_service.core.seeder.create_template",
                new_callable=AsyncMock,
            ),
            patch(
                "doc_template_service.core.seeder.publish_template_created_event",
                new_callable=AsyncMock,
            ),
        ):
            mock_sessionmaker.return_value.return_value.__aenter__.return_value = mock_session
            await seed_default_templates()
