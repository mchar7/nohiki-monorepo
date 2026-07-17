"""Unit tests for the Typer CLI commands and __main__ entry point."""

import importlib
import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from qdrant_init.cli import app
from qdrant_init.client import QdrantConnectionError
from qdrant_init.initializer import InitializationResult
from typer.testing import CliRunner

runner = CliRunner()


def _write_manifest(tmp_path: Path, data: dict[str, object] | None = None) -> Path:
    """Write a minimal manifest JSON to a temp file and return its path.

    The content does not need to be a valid SemanticRepresentationManifest because
    SemanticRepresentationManifest.load_from_path is mocked in these tests.  The
    file just needs to exist so the path-existence check passes.
    """
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(data or {}))
    return manifest_path


@pytest.fixture
def mock_manifest() -> MagicMock:
    """A mock SemanticRepresentationManifest with 4 collections."""
    manifest = MagicMock()
    manifest.collections.model_fields = {
        "jobs": MagicMock(),
        "profiles": MagicMock(),
        "skills": MagicMock(),
        "occupations": MagicMock(),
    }
    return manifest


class TestInitCommand:
    """Tests for the 'init' CLI command."""

    def test_exits_1_when_manifest_not_found(self) -> None:
        """Exit code 1 with an error log when the manifest path does not exist."""
        result = runner.invoke(app, ["init", "--manifest", "/nonexistent/manifest.json", "--no-wait"])
        assert result.exit_code == 1

    def test_success_exits_0(self, tmp_path: Path, mock_manifest: MagicMock) -> None:
        """Exit code 0 when all collections initialise successfully."""
        manifest_path = _write_manifest(tmp_path)
        success_result = InitializationResult(created=["jobs_v1", "profiles_v1", "skills_v1", "occupations_v1"])

        with (
            patch("qdrant_init.cli.SemanticRepresentationManifest.load_from_path", return_value=mock_manifest),
            patch("qdrant_init.cli.QdrantInitClient") as mock_client_cls,
        ):
            mock_ctx = MagicMock()
            mock_ctx.__enter__ = MagicMock(return_value=mock_ctx)
            mock_ctx.__exit__ = MagicMock(return_value=False)
            mock_client_cls.return_value = mock_ctx

            mock_initializer = MagicMock()
            mock_initializer.initialize_all.return_value = success_result

            with patch("qdrant_init.cli.CollectionInitializer", return_value=mock_initializer):
                result = runner.invoke(
                    app,
                    ["init", "--manifest", str(manifest_path), "--no-wait"],
                )

        assert result.exit_code == 0, result.output

    def test_exits_1_when_qdrant_unavailable(self, tmp_path: Path, mock_manifest: MagicMock) -> None:
        """Exit code 1 when wait_for_ready raises QdrantConnectionError."""
        manifest_path = _write_manifest(tmp_path)

        with (
            patch("qdrant_init.cli.SemanticRepresentationManifest.load_from_path", return_value=mock_manifest),
            patch("qdrant_init.cli.QdrantInitClient") as mock_client_cls,
        ):
            mock_ctx = MagicMock()
            mock_ctx.__enter__ = MagicMock(return_value=mock_ctx)
            mock_ctx.__exit__ = MagicMock(return_value=False)
            mock_ctx.wait_for_ready.side_effect = QdrantConnectionError("unreachable")
            mock_client_cls.return_value = mock_ctx

            result = runner.invoke(
                app,
                ["init", "--manifest", str(manifest_path), "--wait"],
            )

        assert result.exit_code == 1

    def test_exits_1_when_initialization_fails(self, tmp_path: Path, mock_manifest: MagicMock) -> None:
        """Exit code 1 when the initializer reports at least one failed collection."""
        manifest_path = _write_manifest(tmp_path)
        failure_result = InitializationResult(failed=["jobs_v1"])

        with (
            patch("qdrant_init.cli.SemanticRepresentationManifest.load_from_path", return_value=mock_manifest),
            patch("qdrant_init.cli.QdrantInitClient") as mock_client_cls,
        ):
            mock_ctx = MagicMock()
            mock_ctx.__enter__ = MagicMock(return_value=mock_ctx)
            mock_ctx.__exit__ = MagicMock(return_value=False)
            mock_client_cls.return_value = mock_ctx

            mock_initializer = MagicMock()
            mock_initializer.initialize_all.return_value = failure_result

            with patch("qdrant_init.cli.CollectionInitializer", return_value=mock_initializer):
                result = runner.invoke(
                    app,
                    ["init", "--manifest", str(manifest_path), "--no-wait"],
                )

        assert result.exit_code == 1

    def test_skip_existing_passed_to_initializer(self, tmp_path: Path, mock_manifest: MagicMock) -> None:
        """--skip-existing flag is forwarded to initialize_all."""
        manifest_path = _write_manifest(tmp_path)
        success_result = InitializationResult(skipped=["jobs_v1"])

        with (
            patch("qdrant_init.cli.SemanticRepresentationManifest.load_from_path", return_value=mock_manifest),
            patch("qdrant_init.cli.QdrantInitClient") as mock_client_cls,
        ):
            mock_ctx = MagicMock()
            mock_ctx.__enter__ = MagicMock(return_value=mock_ctx)
            mock_ctx.__exit__ = MagicMock(return_value=False)
            mock_client_cls.return_value = mock_ctx

            mock_initializer = MagicMock()
            mock_initializer.initialize_all.return_value = success_result

            with patch("qdrant_init.cli.CollectionInitializer", return_value=mock_initializer):
                runner.invoke(
                    app,
                    ["init", "--manifest", str(manifest_path), "--no-wait", "--skip-existing"],
                )

            mock_initializer.initialize_all.assert_called_once_with(skip_existing=True)


class TestListCommand:
    """Tests for the 'list' CLI command."""

    def test_shows_collection_names(self) -> None:
        """Prints collection names and their point counts."""
        with patch("qdrant_init.cli.QdrantInitClient") as mock_client_cls:
            mock_ctx = MagicMock()
            mock_ctx.__enter__ = MagicMock(return_value=mock_ctx)
            mock_ctx.__exit__ = MagicMock(return_value=False)
            mock_ctx.list_collections.return_value = ["jobs_v1", "skills_v1"]
            mock_ctx.get_collection_info.return_value = MagicMock(points_count=100)
            mock_client_cls.return_value = mock_ctx

            result = runner.invoke(app, ["list"])

        assert result.exit_code == 0
        assert "jobs_v1" in result.output
        assert "skills_v1" in result.output

    def test_no_collections_message(self) -> None:
        """Prints 'No collections found' when Qdrant has no collections."""
        with patch("qdrant_init.cli.QdrantInitClient") as mock_client_cls:
            mock_ctx = MagicMock()
            mock_ctx.__enter__ = MagicMock(return_value=mock_ctx)
            mock_ctx.__exit__ = MagicMock(return_value=False)
            mock_ctx.list_collections.return_value = []
            mock_client_cls.return_value = mock_ctx

            result = runner.invoke(app, ["list"])

        assert result.exit_code == 0
        assert "No collections found" in result.output

    def test_shows_collection_name_when_info_unavailable(self) -> None:
        """Prints collection name without point count when get_collection_info returns None."""
        with patch("qdrant_init.cli.QdrantInitClient") as mock_client_cls:
            mock_ctx = MagicMock()
            mock_ctx.__enter__ = MagicMock(return_value=mock_ctx)
            mock_ctx.__exit__ = MagicMock(return_value=False)
            mock_ctx.list_collections.return_value = ["jobs_v1"]
            # Simulate Qdrant returning None for collection info (e.g. transient race condition)
            mock_ctx.get_collection_info.return_value = None
            mock_client_cls.return_value = mock_ctx

            result = runner.invoke(app, ["list"])

        assert result.exit_code == 0
        assert "jobs_v1" in result.output

    def test_exits_1_when_qdrant_unavailable(self) -> None:
        """Exit code 1 when Qdrant is unreachable during list."""
        with patch("qdrant_init.cli.QdrantInitClient") as mock_client_cls:
            mock_ctx = MagicMock()
            mock_ctx.__enter__ = MagicMock(return_value=mock_ctx)
            mock_ctx.__exit__ = MagicMock(return_value=False)
            mock_ctx.wait_for_ready.side_effect = QdrantConnectionError("unreachable")
            mock_client_cls.return_value = mock_ctx

            result = runner.invoke(app, ["list"])

        assert result.exit_code == 1


class TestDeleteCommand:
    """Tests for the 'delete' CLI command."""

    def test_delete_with_force_flag(self) -> None:
        """--force skips confirmation prompt; exit code 0 on successful deletion."""
        with patch("qdrant_init.cli.QdrantInitClient") as mock_client_cls:
            mock_ctx = MagicMock()
            mock_ctx.__enter__ = MagicMock(return_value=mock_ctx)
            mock_ctx.__exit__ = MagicMock(return_value=False)
            mock_ctx.delete_collection.return_value = True
            mock_client_cls.return_value = mock_ctx

            result = runner.invoke(app, ["delete", "jobs_v1", "--force"])

        assert result.exit_code == 0
        mock_ctx.delete_collection.assert_called_once_with("jobs_v1")

    def test_delete_not_found_logs_warning(self) -> None:
        """Exit code 0 even when the collection doesn't exist (delete_collection returns False)."""
        with patch("qdrant_init.cli.QdrantInitClient") as mock_client_cls:
            mock_ctx = MagicMock()
            mock_ctx.__enter__ = MagicMock(return_value=mock_ctx)
            mock_ctx.__exit__ = MagicMock(return_value=False)
            mock_ctx.delete_collection.return_value = False
            mock_client_cls.return_value = mock_ctx

            result = runner.invoke(app, ["delete", "nonexistent", "--force"])

        assert result.exit_code == 0

    def test_delete_without_force_confirms_and_deletes(self) -> None:
        """Without --force, prompts for confirmation; 'y' proceeds with deletion."""
        with patch("qdrant_init.cli.QdrantInitClient") as mock_client_cls:
            mock_ctx = MagicMock()
            mock_ctx.__enter__ = MagicMock(return_value=mock_ctx)
            mock_ctx.__exit__ = MagicMock(return_value=False)
            mock_ctx.delete_collection.return_value = True
            mock_client_cls.return_value = mock_ctx

            # Simulate user typing 'y' at the confirmation prompt
            result = runner.invoke(app, ["delete", "jobs_v1"], input="y\n")

        assert result.exit_code == 0
        mock_ctx.delete_collection.assert_called_once_with("jobs_v1")

    def test_delete_without_force_aborts_on_no(self) -> None:
        """Without --force, typing 'n' at the confirmation prompt aborts the deletion."""
        with patch("qdrant_init.cli.QdrantInitClient") as mock_client_cls:
            mock_ctx = MagicMock()
            mock_ctx.__enter__ = MagicMock(return_value=mock_ctx)
            mock_ctx.__exit__ = MagicMock(return_value=False)
            mock_client_cls.return_value = mock_ctx

            result = runner.invoke(app, ["delete", "jobs_v1"], input="n\n")

        # Typer raises typer.Abort on cancellation: exit code 1
        assert result.exit_code != 0
        mock_ctx.delete_collection.assert_not_called()


class TestMainModule:
    """Tests for the __main__.py entry point module."""

    def test_main_module_exposes_app(self) -> None:
        """Verify __main__.py imports and exposes the CLI app entrypoint."""
        mod = importlib.import_module("qdrant_init.__main__")
        assert hasattr(mod, "app")
