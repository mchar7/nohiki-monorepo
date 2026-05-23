"""Post-processing for generated betterproto2 code."""

import re
import shutil
from pathlib import Path
from typing import Final

MESSAGE_POOL_ABSOLUTE_IMPORT: Final[str] = "from message_pool import default_message_pool"

MESSAGE_POOL_PATTERNS: list[tuple[str, str]] = [
    (r"from \.\.\.\.\.message_pool import default_message_pool", MESSAGE_POOL_ABSOLUTE_IMPORT),
    (r"from \.\.\.\.message_pool import default_message_pool", MESSAGE_POOL_ABSOLUTE_IMPORT),
    (r"from \.\.\.message_pool import default_message_pool", MESSAGE_POOL_ABSOLUTE_IMPORT),
    (r"from \.\.message_pool import default_message_pool", MESSAGE_POOL_ABSOLUTE_IMPORT),
]

# Kept as an empty list for shape compatibility with the rest of the
# post-processor. The bare `datetime.datetime` annotation paired with a
# residual `optional=True` is the responsibility of ``required_fields.py``
# (which strips both the ``| None`` and the ``optional=True`` for required
# fields), not of a separate string-replace step here.
DATETIME_OPTIONAL_PATTERNS: list[tuple[str, str]] = []

STDLIB_SELF_PATTERNS: list[tuple[str, str]] = [
    (r"from typing_extensions import Self", "from typing import Self"),
]

GOOGLE_IMPORT_PATTERNS: list[tuple[str, str]] = [
    (
        r"from \.\.\.\.\.google import protobuf as ____google__protobuf__",
        "from nohiki_proto_google import protobuf as ____google__protobuf__",
    ),
    (
        r"from \.\.\.\.google import protobuf as ___google__protobuf__",
        "from nohiki_proto_google import protobuf as ___google__protobuf__",
    ),
]


def remove_directory(path: Path) -> None:
    """Remove a directory if it exists."""
    if path.exists() and path.is_dir():
        shutil.rmtree(path)


def remove_file(path: Path) -> None:
    """Remove a file if it exists."""
    if path.exists() and path.is_file():
        path.unlink()


def clean_output_directory(output_dir: Path) -> None:
    """Remove previously generated artifacts before regeneration."""
    for name in ("nohiki", "buf", "google", "nohiki_proto_google"):
        remove_directory(output_dir / name)
    remove_file(output_dir / "message_pool.py")
    remove_file(output_dir / "__init__.py")


def remove_buf_stubs(output_dir: Path) -> None:
    """Remove buf validation stubs (not needed at runtime)."""
    remove_directory(output_dir / "buf")


def rename_google_package(output_dir: Path) -> None:
    """Rename google package to avoid conflicts with system google-protobuf."""
    google_dir = output_dir / "google"
    target_dir = output_dir / "nohiki_proto_google"
    if google_dir.exists():
        remove_directory(target_dir)
        google_dir.rename(target_dir)


def _apply_patterns(content: str, patterns: list[tuple[str, str]]) -> str:
    """Apply a list of regex replacement patterns to content."""
    for pattern, replacement in patterns:
        content = re.sub(pattern, replacement, content)
    return content


def fix_imports_in_file(file_path: Path, patterns: list[tuple[str, str]]) -> bool:
    """Fix imports in a single file using the given patterns. Returns True if modified."""
    content = file_path.read_text()
    fixed = _apply_patterns(content, patterns)
    if fixed != content:
        file_path.write_text(fixed)
        return True
    return False


def fix_message_pool_imports(output_dir: Path) -> int:
    """Fix betterproto2 relative imports to absolute imports. Returns count of fixed files."""
    fixed_count = 0
    for init_file in output_dir.rglob("__init__.py"):
        if fix_imports_in_file(init_file, MESSAGE_POOL_PATTERNS):
            fixed_count += 1
    return fixed_count


def fix_stdlib_self_imports(output_dir: Path) -> int:
    """Replace generated backport imports available in the minimum Python version."""
    fixed_count = 0
    for init_file in output_dir.rglob("__init__.py"):
        if fix_imports_in_file(init_file, STDLIB_SELF_PATTERNS):
            fixed_count += 1
    return fixed_count


def fix_google_imports(nohiki_dir: Path) -> int:
    """Fix google.protobuf imports to use renamed module. Returns count of fixed files."""
    if not nohiki_dir.exists():
        return 0
    fixed_count = 0
    for init_file in nohiki_dir.rglob("__init__.py"):
        if fix_imports_in_file(init_file, GOOGLE_IMPORT_PATTERNS):
            fixed_count += 1
    return fixed_count


def create_py_typed_marker(nohiki_dir: Path) -> None:
    """Create py.typed marker for PEP 561 compliance."""
    py_typed = nohiki_dir / "py.typed"
    py_typed.parent.mkdir(parents=True, exist_ok=True)
    py_typed.touch()


def fix_datetime_optional_annotations(nohiki_dir: Path) -> int:
    """Fix Timestamp field annotations for Python 3.14 compatibility.

    betterproto2 generates proto Timestamp fields as ``"datetime.datetime "``
    but marks them optional in metadata. ``to_dict()`` then calls ``.__args__[0]``
    which fails because the resolved hint is plain ``datetime.datetime`` (no union).
    This rewrites the annotations to ``"datetime.datetime | None"`` so
    ``get_type_hints()`` resolves to a proper union type with ``__args__``.

    Returns:
        Count of modified files.
    """
    if not nohiki_dir.exists():
        return 0
    fixed_count = 0
    for init_file in nohiki_dir.rglob("__init__.py"):
        if fix_imports_in_file(init_file, DATETIME_OPTIONAL_PATTERNS):
            fixed_count += 1
    return fixed_count


def run_post_processing(output_dir: Path) -> None:
    """Run all post-processing steps on generated code."""
    remove_buf_stubs(output_dir)
    rename_google_package(output_dir)
    # betterproto2 creates __init__.py at the output root, which breaks
    # the PEP 420 namespace package layout required by nohiki-domain-models.
    remove_file(output_dir / "__init__.py")
    # Generated modules import the canonical ``message_pool`` package. The
    # compiler also emits a same-named module, which would be ambiguous.
    remove_file(output_dir / "message_pool.py")
    fix_message_pool_imports(output_dir)
    fix_stdlib_self_imports(output_dir)

    nohiki_dir = output_dir / "nohiki"
    remove_file(nohiki_dir / "__init__.py")
    fix_google_imports(nohiki_dir)
    create_py_typed_marker(nohiki_dir)
    # NOTE: fix_datetime_optional_annotations must run AFTER required_fields
    # processing, so it's called from cli.py, not here.
