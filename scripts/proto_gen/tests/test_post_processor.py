"""Tests for generated-code post-processing."""

from pathlib import Path

from proto_gen.post_processor import fix_stdlib_self_imports


def test_stdlib_self_import_rewrite_is_reported_and_idempotent(tmp_path: Path) -> None:
    """Generated ``Self`` imports move to stdlib exactly once."""
    package_dir = tmp_path / "nohiki" / "demo" / "v1"
    package_dir.mkdir(parents=True)
    init_file = package_dir / "__init__.py"
    init_file.write_text(
        "from typing_extensions import Self\n\nclass Builder:\n    def build(self) -> Self:\n        return self\n"
    )

    assert fix_stdlib_self_imports(tmp_path) == 1
    rewritten = init_file.read_text()
    assert rewritten == (
        "from typing import Self\n\nclass Builder:\n    def build(self) -> Self:\n        return self\n"
    )

    assert fix_stdlib_self_imports(tmp_path) == 0
    assert init_file.read_text() == rewritten
