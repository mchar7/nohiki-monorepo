"""Tests for required-field enforcement of betterproto2-generated code."""

from pathlib import Path
from textwrap import dedent

from proto_gen.required_fields import (
    _remove_none_type_hints,
    _remove_optional_true,
    fix_required_fields,
    parse_proto_directory,
    parse_proto_file,
)


def _write_proto(dir_path: Path, name: str, content: str) -> Path:
    """Write a .proto file under ``dir_path`` and return its path."""
    dir_path.mkdir(parents=True, exist_ok=True)
    path = dir_path / name
    path.write_text(dedent(content).lstrip())
    return path


def _write_init(dir_path: Path, content: str) -> Path:
    """Write a generated ``__init__.py`` under ``dir_path``."""
    dir_path.mkdir(parents=True, exist_ok=True)
    path = dir_path / "__init__.py"
    path.write_text(dedent(content).lstrip())
    return path


# Fix 1: substring-collision regex bug


def test_required_field_does_not_strip_none_from_substring_collision_field() -> None:
    """Required ``bar`` must NOT also strip ``| None`` from optional ``foobar``."""
    content = dedent(
        """
        class Thing(betterproto.Message):
            bar: "str | None"
            foobar: "str | None"
        """
    ).lstrip()

    patched, fixes = _remove_none_type_hints(content, {"Thing": {"bar"}})

    assert fixes == 1
    assert 'bar: "str"' in patched
    # The optional foobar must remain optional.
    assert 'foobar: "str | None"' in patched


def test_required_field_does_not_strip_optional_true_from_substring_collision_field() -> None:
    """Required ``bar`` must NOT clear ``optional=True`` on optional ``foobar``.

    ``foobar`` is placed BEFORE ``bar`` so the existing ``prev_had_required``
    bleed-through (which clears ``optional=True`` on the line after a required
    field, supporting multi-line betterproto2 field declarations) cannot mask
    the substring collision under test.
    """
    content = dedent(
        """
        class Thing(betterproto.Message):
            foobar: dataclass_field(default=None, metadata={"betterproto": Field(2, optional=True)})
            unrelated: int = 0
            bar: dataclass_field(default=None, metadata={"betterproto": Field(1, optional=True)})
        """
    ).lstrip()

    patched, fixes = _remove_optional_true(content, {"Thing": {"bar"}})

    assert fixes == 1
    bar_line = next(line for line in patched.splitlines() if line.lstrip().startswith("bar:"))
    foobar_line = next(line for line in patched.splitlines() if line.lstrip().startswith("foobar:"))
    assert "optional=True" not in bar_line
    assert "optional=True" in foobar_line


# Fix 2: trailing-whitespace artifact in regex group capture


def test_substituted_type_annotation_has_no_trailing_whitespace() -> None:
    """Stripped annotation must not retain a trailing space inside the quoted type."""
    content = 'class Snap(betterproto.Message):\n    listing: "ListingSnapshot | None"\n'

    patched, fixes = _remove_none_type_hints(content, {"Snap": {"listing"}})

    assert fixes == 1
    assert 'listing: "ListingSnapshot"' in patched
    assert "ListingSnapshot " not in patched  # no trailing space inside quotes
    assert '"ListingSnapshot "' not in patched


# Fix 3: cross-file message name collision


def test_same_message_name_in_different_packages_does_not_cross_contaminate(
    tmp_path: Path,
) -> None:
    """A required field on ``foo.v1.Result`` must not affect ``bar.v1.Result``."""
    proto_root = tmp_path / "proto"

    _write_proto(
        proto_root / "nohiki" / "foo" / "v1",
        "result.proto",
        """
        syntax = "proto3";
        package nohiki.foo.v1;

        message Result {
            string value = 1 [(buf.validate.field).required = true];
        }
        """,
    )

    _write_proto(
        proto_root / "nohiki" / "bar" / "v1",
        "result.proto",
        """
        syntax = "proto3";
        package nohiki.bar.v1;

        message Result {
            string value = 1;
        }
        """,
    )

    parsed = parse_proto_directory(proto_root)

    foo_pkg = parsed.for_package("nohiki/foo/v1")
    bar_pkg = parsed.for_package("nohiki/bar/v1")

    assert foo_pkg.fields == {"Result": {"value"}}
    assert bar_pkg.fields == {}


def test_fix_required_fields_only_patches_matching_package(tmp_path: Path) -> None:
    """End-to-end: only ``foo.v1.Result.value`` is stripped; ``bar.v1.Result.value`` stays optional."""
    proto_root = tmp_path / "proto"
    gen_root = tmp_path / "gen" / "nohiki"

    _write_proto(
        proto_root / "nohiki" / "foo" / "v1",
        "result.proto",
        """
        syntax = "proto3";
        package nohiki.foo.v1;

        message Result {
            string value = 1 [(buf.validate.field).required = true];
        }
        """,
    )

    _write_proto(
        proto_root / "nohiki" / "bar" / "v1",
        "result.proto",
        """
        syntax = "proto3";
        package nohiki.bar.v1;

        message Result {
            string value = 1;
        }
        """,
    )

    foo_init = _write_init(
        gen_root / "foo" / "v1",
        """
        class Result(betterproto.Message):
            value: "str | None" = field(default=None, metadata={"betterproto": Field(1, optional=True)})
        """,
    )

    bar_init = _write_init(
        gen_root / "bar" / "v1",
        """
        class Result(betterproto.Message):
            value: "str | None" = field(default=None, metadata={"betterproto": Field(1, optional=True)})
        """,
    )

    fix_required_fields(proto_root, gen_root)

    foo_after = foo_init.read_text()
    bar_after = bar_init.read_text()

    assert 'value: "str"' in foo_after
    assert "optional=True" not in foo_after
    # Bar package is untouched.
    assert 'value: "str | None"' in bar_after
    assert "optional=True" in bar_after


# Fix 4: nested message support


def test_nested_messages_attribute_fields_to_correct_enclosing_message(
    tmp_path: Path,
) -> None:
    """Fields after a nested-message close-brace belong to the outer message."""
    proto_path = _write_proto(
        tmp_path,
        "nested.proto",
        """
        syntax = "proto3";
        package nohiki.nested.v1;

        message Outer {
            message Inner {
                string inner_required = 1 [(buf.validate.field).required = true];
                string inner_optional = 2;
            }

            string outer_before = 1;
            Inner inner = 2;
            string outer_after_required = 3 [(buf.validate.field).required = true];
        }
        """,
    )

    package_dir, parsed = parse_proto_file(proto_path)

    assert package_dir == "nohiki/nested/v1"
    assert parsed.fields == {
        "Inner": {"inner_required"},
        "Outer": {"outer_after_required"},
    }


# Fix 5: dead code removed


def test_required_fields_map_does_not_expose_all_field_names() -> None:
    """``all_field_names`` was unused after package-scoping and should be removed."""
    from proto_gen.required_fields import RequiredFieldsMap

    assert not hasattr(RequiredFieldsMap, "all_field_names")


# Existing happy-path coverage


def test_simple_required_field_strips_none_and_optional_true(tmp_path: Path) -> None:
    """Baseline: a single required field gets ``| None`` and ``optional=True`` stripped."""
    proto_root = tmp_path / "proto"
    gen_root = tmp_path / "gen" / "nohiki"

    _write_proto(
        proto_root / "nohiki" / "demo" / "v1",
        "thing.proto",
        """
        syntax = "proto3";
        package nohiki.demo.v1;

        message Thing {
            string note = 1;
            string spacer = 2;
            string name = 3 [(buf.validate.field).required = true];
        }
        """,
    )

    init_file = _write_init(
        gen_root / "demo" / "v1",
        """
        class Thing(betterproto.Message):
            note: "str | None" = field(default=None, metadata={"betterproto": Field(1, optional=True)})
            spacer: "str | None" = field(default=None, metadata={"betterproto": Field(2, optional=True)})
            name: "str | None" = field(default=None, metadata={"betterproto": Field(3, optional=True)})
        """,
    )

    results = fix_required_fields(proto_root, gen_root)

    patched = init_file.read_text()
    name_line = next(line for line in patched.splitlines() if line.lstrip().startswith("name:"))
    note_line = next(line for line in patched.splitlines() if line.lstrip().startswith("note:"))

    assert 'name: "str"' in name_line
    assert "optional=True" not in name_line
    # Optional field untouched.
    assert 'note: "str | None"' in note_line
    assert "optional=True" in note_line

    total_fixes = sum(r.total_fixes for r in results)
    assert total_fixes == 2  # one type-hint fix + one optional=True fix
