"""Required field type enforcement for betterproto2 generated code.

betterproto2 marks all message/optional fields as optional=True with | None types.
This module parses proto files for buf.validate required annotations and patches
the generated Python to enforce non-optional types for those fields.

Scoping strategy
----------------
Required fields are keyed by **(package_dir, message_name)** rather than by bare
message name. Two protos in different packages can declare a message with the
same simple name (e.g. ``Listing``); without package scoping their required-field
sets would silently merge and corrupt unrelated generated code.

The package directory is derived from the proto's ``package`` declaration
(``nohiki.foo.v1`` → ``nohiki/foo/v1``), which mirrors the directory structure
of the generated Python tree. When patching a generated ``__init__.py`` we look
up the required-field map for that file's package directory only.
"""

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final

REQUIRED_ANNOTATION: Final[str] = "(buf.validate.field).required = true"
OPTIONAL_TRUE_PATTERN: Final[str] = ", optional=True"


@dataclass
class RequiredFieldsMap:
    """Maps message names to their required field names within a single package."""

    fields: dict[str, set[str]] = field(default_factory=dict)

    @property
    def message_count(self) -> int:
        """Count of messages with required fields."""
        return len(self.fields)

    @property
    def field_count(self) -> int:
        """Total count of required fields across all messages."""
        return sum(len(f) for f in self.fields.values())

    def add(self, message: str, field_name: str) -> None:
        """Add a required field for a message."""
        self.fields.setdefault(message, set()).add(field_name)

    def merge(self, other: RequiredFieldsMap) -> None:
        """Merge another map into this one (used for same-package proto files)."""
        for msg, names in other.fields.items():
            for name in names:
                self.add(msg, name)


@dataclass
class PackageRequiredFields:
    """Required fields grouped by package directory.

    ``packages`` keys are POSIX-style relative directory paths matching the
    generated tree, e.g. ``"nohiki/job/listing/v1"``.
    """

    packages: dict[str, RequiredFieldsMap] = field(default_factory=dict)

    @property
    def message_count(self) -> int:
        """Total messages with required fields across all packages."""
        return sum(m.message_count for m in self.packages.values())

    @property
    def field_count(self) -> int:
        """Total required fields across all packages."""
        return sum(m.field_count for m in self.packages.values())

    @property
    def fields(self) -> dict[str, set[str]]:
        """Flattened message→fields view across all packages.

        Provided for CLI display only; do NOT use for patching generated code
        — same-named messages in different packages would collide.
        """
        flat: dict[str, set[str]] = {}
        for pkg in self.packages.values():
            for msg, names in pkg.fields.items():
                flat.setdefault(msg, set()).update(names)
        return flat

    def for_package(self, package_dir: str) -> RequiredFieldsMap:
        """Return the map for a package, or an empty map if unknown."""
        return self.packages.get(package_dir, RequiredFieldsMap())


@dataclass
class FixResult:
    """Result of fixing a single file."""

    path: Path
    type_fixes: int
    optional_fixes: int

    @property
    def total_fixes(self) -> int:
        """Total number of fixes applied."""
        return self.type_fixes + self.optional_fixes


def _extract_package_dir(content: str) -> str | None:
    """Return the ``package`` declaration from proto content as a directory path.

    ``package nohiki.foo.v1;`` → ``"nohiki/foo/v1"``. Returns None when no
    package line is present (proto2 default package is unsupported here).
    """
    if match := re.search(r"^\s*package\s+([\w.]+)\s*;", content, re.MULTILINE):
        return match.group(1).replace(".", "/")
    return None


def parse_proto_file(path: Path) -> tuple[str | None, RequiredFieldsMap]:
    """Extract required fields from a single proto file.

    Returns ``(package_dir, required_fields)``. Tracks message nesting via a
    stack so fields after a nested message close-brace are attributed to the
    correct enclosing message.
    """
    result = RequiredFieldsMap()
    content = path.read_text()
    package_dir = _extract_package_dir(content)

    # Stack of (message_name, brace_depth_at_open). The current message is
    # always the top of the stack; popping happens when brace_depth falls
    # back to the opening depth.
    message_stack: list[tuple[str, int]] = []
    brace_depth = 0

    for line in content.splitlines():
        stripped = line.strip()

        # Detect a new message opening on this line BEFORE updating brace_depth,
        # so the recorded "depth at open" is the depth before the opening brace.
        if stripped.startswith("message ") and (match := re.match(r"message\s+(\w+)", stripped)):
            message_stack.append((match.group(1), brace_depth))

        # Update running brace depth from this line's braces.
        brace_depth += stripped.count("{") - stripped.count("}")

        # Pop any messages whose closing brace we just passed.
        while message_stack and brace_depth <= message_stack[-1][1]:
            message_stack.pop()

        # Attribute required-field annotations to the innermost open message.
        if (
            message_stack
            and REQUIRED_ANNOTATION in stripped
            and (field_match := re.search(r"(\w+)\s*=\s*\d+", stripped))
        ):
            current_message = message_stack[-1][0]
            result.add(current_message, field_match.group(1))

    return package_dir, result


def parse_proto_directory(proto_dir: Path) -> PackageRequiredFields:
    """Parse all proto files in directory, grouping required fields by package.

    Files in the same proto package (e.g. multiple ``.proto`` files declaring
    ``package nohiki.foo.v1``) generate to a single shared ``__init__.py`` and
    so are merged into one ``RequiredFieldsMap``.
    """
    result = PackageRequiredFields()
    for proto_file in proto_dir.rglob("*.proto"):
        package_dir, file_result = parse_proto_file(proto_file)
        if package_dir is None or not file_result.fields:
            continue
        result.packages.setdefault(package_dir, RequiredFieldsMap()).merge(file_result)
    return result


def _remove_none_type_hints(content: str, required_map: dict[str, set[str]]) -> tuple[str, int]:
    """Remove ``| None`` from type hints for fields required in their enclosing class.

    Field-name matches are anchored with a ``[A-Za-z0-9_]`` lookbehind so a
    required field ``bar`` does not also strip ``| None`` from an unrelated
    optional field ``foobar``. The captured type non-greedily excludes trailing
    whitespace before ``|`` so the substituted annotation has no stray space
    inside the quoted type.
    """
    fixes = 0
    lines = content.splitlines()
    new_lines: list[str] = []
    current_class: str | None = None

    for line in lines:
        stripped = line.strip()
        if match := re.match(r"^class\s+(\w+)\(", stripped):
            current_class = match.group(1)

        output_line = line
        if current_class:
            for field_name in required_map.get(current_class, ()):
                pattern = rf'(?<![A-Za-z0-9_])({re.escape(field_name)}:\s*")([^"\s][^"]*?)\s*\|\s*None(")'
                output_line, count = re.subn(pattern, r"\1\2\3", output_line)
                fixes += count

        new_lines.append(output_line)

    return "\n".join(new_lines), fixes


def _remove_optional_true(content: str, required_map: dict[str, set[str]]) -> tuple[str, int]:
    """Remove ``optional=True`` from required field definitions."""
    fixes = 0
    new_lines: list[str] = []
    current_class: str | None = None
    required_params_depth = 0

    for line in content.splitlines():
        stripped = line.strip()
        if match := re.match(r"^class\s+(\w+)\(", stripped):
            current_class = match.group(1)
            required_params_depth = 0

        required_fields = required_map.get(current_class, set()) if current_class else set()
        starts_required_field = any(
            re.match(rf"^\s*{re.escape(field_name)}\s*:", line) for field_name in required_fields
        )

        output_line = line
        if starts_required_field:
            if OPTIONAL_TRUE_PATTERN in output_line:
                output_line = output_line.replace(OPTIONAL_TRUE_PATTERN, "")
                fixes += 1
            required_params_depth = output_line.count("(") - output_line.count(")")
        elif required_params_depth > 0:
            if re.match(r"^\s*optional=True,?\s*$", line):
                fixes += 1
                required_params_depth += line.count("(") - line.count(")")
                continue
            if OPTIONAL_TRUE_PATTERN in output_line:
                output_line = output_line.replace(OPTIONAL_TRUE_PATTERN, "")
                fixes += 1
            required_params_depth += output_line.count("(") - output_line.count(")")

        new_lines.append(output_line)

    return "\n".join(new_lines), fixes


def fix_python_file(path: Path, required_map: dict[str, set[str]]) -> FixResult:
    """Remove ``optional=True`` and ``| None`` for required fields in a single Python file.

    ``required_map`` is the per-package message→field-set map. Pass an empty
    dict for files in packages with no required fields (the function is a
    no-op in that case).
    """
    content = path.read_text()
    original = content

    content, type_fixes = _remove_none_type_hints(content, required_map)
    content, optional_fixes = _remove_optional_true(content, required_map)

    if content != original:
        path.write_text(content)

    return FixResult(path=path, type_fixes=type_fixes, optional_fixes=optional_fixes)


def _package_dir_for_init(init_file: Path, generated_root: Path) -> str:
    """Derive the proto package directory for a generated ``__init__.py``.

    ``<generated_root_parent>/nohiki/foo/v1/__init__.py`` →
    ``"nohiki/foo/v1"`` (matching ``package nohiki.foo.v1``).
    """
    rel_dir = init_file.parent.relative_to(generated_root.parent)
    return rel_dir.as_posix()


def fix_required_fields(proto_dir: Path, generated_dir: Path) -> list[FixResult]:
    """Fix all required fields in generated code. Returns list of results.

    ``proto_dir`` is the proto source root containing the ``nohiki/`` tree;
    ``generated_dir`` is the generated Python ``nohiki/`` directory. Each
    generated ``__init__.py`` is patched only with the required-field map for
    its own proto package, preventing cross-package collisions.
    """
    required = parse_proto_directory(proto_dir)

    results: list[FixResult] = []
    for init_file in generated_dir.rglob("__init__.py"):
        package_dir = _package_dir_for_init(init_file, generated_dir)
        package_map = required.for_package(package_dir).fields
        result = fix_python_file(init_file, package_map)
        results.append(result)

    return results
