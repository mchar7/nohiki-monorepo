"""Repository policy for prelaunch Alembic revision histories."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

_REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
_SERVICES_ROOT = _REPOSITORY_ROOT / "backend" / "services"
_MISSING = object()


def _module_constants(path: Path, names: tuple[str, ...]) -> tuple[object, ...]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    values: dict[str, ast.expr | None] = dict.fromkeys(names)
    for statement in tree.body:
        if isinstance(statement, ast.Assign):
            assigned_names = [
                target.id for target in statement.targets if isinstance(target, ast.Name) and target.id in values
            ]
        elif isinstance(statement, ast.AnnAssign) and isinstance(statement.target, ast.Name):
            assigned_names = [statement.target.id] if statement.target.id in values else []
        else:
            continue
        for name in assigned_names:
            values[name] = statement.value

    constants: list[object] = []
    for value in values.values():
        if value is None:
            constants.append(_MISSING)
            continue
        try:
            constants.append(ast.literal_eval(value))
        except ValueError, TypeError:
            constants.append(f"<non-literal: {ast.unparse(value)}>")
    return tuple(constants)


def _assert_contiguous_migration_chain(service_dir: Path) -> None:
    versions_dir = service_dir / "alembic" / "versions"
    revision_paths = sorted(path for path in versions_dir.iterdir() if path.is_file() and path.suffix == ".py")
    filenames = [path.name for path in revision_paths]
    assert revision_paths, f"{service_dir.name}: no Alembic revisions found in {versions_dir}"

    revisions: dict[str, tuple[object, Path]] = {}
    for migration in revision_paths:
        revision, down_revision = _module_constants(migration, ("revision", "down_revision"))
        assert isinstance(revision, str), f"{service_dir.name}: {migration.name} must define a literal string revision"
        assert revision not in revisions, (
            f"{service_dir.name}: duplicate revision {revision!r} in {migration.name} and {revisions[revision][1].name}"
        )
        revisions[revision] = (down_revision, migration)

    expected_revisions = [f"{number:03d}" for number in range(1, len(revision_paths) + 1)]
    assert sorted(revisions) == expected_revisions, (
        f"{service_dir.name}: revisions must be contiguous from '001'; found {sorted(revisions)!r} in {filenames!r}"
    )

    for number, revision in enumerate(expected_revisions, start=1):
        down_revision, migration = revisions[revision]
        expected_down_revision = None if number == 1 else expected_revisions[number - 2]
        assert down_revision == expected_down_revision, (
            f"{service_dir.name}: {migration.name} revision {revision!r} must point to "
            f"{expected_down_revision!r}, found {down_revision!r}; revisions: {filenames!r}"
        )


def test_service_alembic_histories_are_contiguous_forward_chains() -> None:
    services = sorted(path.parent.parent for path in _SERVICES_ROOT.glob("*/alembic/versions") if path.is_dir())
    assert services, f"No service Alembic version directories found under {_SERVICES_ROOT}"
    for service_dir in services:
        _assert_contiguous_migration_chain(service_dir)


def test_contiguous_later_revisions_are_accepted(tmp_path: Path) -> None:
    service_dir = tmp_path / "synthetic-service"
    versions_dir = service_dir / "alembic" / "versions"
    versions_dir.mkdir(parents=True)
    (versions_dir / "001_initial_migration.py").write_text("revision = '001'\ndown_revision = None\n", encoding="utf-8")
    (versions_dir / "002_later_revision.py").write_text("revision = '002'\ndown_revision = '001'\n", encoding="utf-8")

    _assert_contiguous_migration_chain(service_dir)


@pytest.mark.parametrize(
    "revision_files",
    [
        pytest.param(
            {
                "001_initial_migration.py": ("001", None),
                "003_gap_revision.py": ("003", "001"),
            },
            id="gap",
        ),
        pytest.param(
            {
                "001_initial_migration.py": ("001", None),
                "002_first_branch.py": ("002", "001"),
                "003_second_branch.py": ("003", "001"),
            },
            id="fork",
        ),
    ],
)
def test_gaps_and_forks_are_rejected_with_service_and_offending_files(
    tmp_path: Path, revision_files: dict[str, tuple[str, str | None]]
) -> None:
    service_dir = tmp_path / "synthetic-service"
    versions_dir = service_dir / "alembic" / "versions"
    versions_dir.mkdir(parents=True)
    for filename, (revision, down_revision) in revision_files.items():
        (versions_dir / filename).write_text(
            f"revision = {revision!r}\ndown_revision = {down_revision!r}\n",
            encoding="utf-8",
        )

    with pytest.raises(AssertionError) as error:
        _assert_contiguous_migration_chain(service_dir)

    message = str(error.value)
    assert "synthetic-service" in message
    for filename in revision_files:
        assert filename in message
