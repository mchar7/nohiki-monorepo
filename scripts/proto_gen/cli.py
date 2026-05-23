"""Typer CLI for betterproto2 proto generation.

Generates Python domain models from proto files with buf.validate enforcement.

Usage:
    uv run python -m proto_gen generate     # Full generation pipeline
    uv run python -m proto_gen fix-required # Fix required fields only
    uv run python -m proto_gen validate     # Validate generated types
    uv run python -m proto_gen check        # Verify committed output freshness
"""

import tempfile
from pathlib import Path
from typing import Annotated

import typer
from rich.table import Table

from . import console as con
from . import dependencies, generator, paths, post_processor, required_fields

app = typer.Typer(
    name="proto-gen",
    help="Generate betterproto2 domain models with buf.validate enforcement.",
    no_args_is_help=True,
    rich_markup_mode="rich",
)


@app.command("generate")
def generate_cmd(
    proto_dir: Annotated[Path | None, typer.Option("--proto-dir", "-p", help="Proto source directory")] = None,
    output_dir: Annotated[Path | None, typer.Option("--output-dir", "-o", help="Output directory")] = None,
) -> None:
    """Generate betterproto2 domain models from proto files."""
    proto_path = proto_dir or paths.PROTO_DIR
    out_path = output_dir or paths.OUTPUT_DIR
    deps_path = paths.get_deps_cache_dir()
    nohiki_proto = proto_path / "nohiki"
    nohiki_out = out_path / "nohiki"

    con.print_header("Proto Generator")

    with con.create_progress() as progress:
        task = progress.add_task("Fetching dependencies...", total=None)

        if not dependencies.fetch_dependencies(proto_path, deps_path):
            raise typer.Exit(1)
        progress.update(task, description="[green]✓[/green] Dependencies fetched")

        progress.update(task, description="Cleaning output directory...")
        post_processor.clean_output_directory(out_path)
        progress.update(task, description="[green]✓[/green] Output cleaned")

        progress.update(task, description="Finding proto files...")
        proto_files = paths.discover_proto_files(nohiki_proto)
        progress.update(task, description=f"[green]✓[/green] Found {len(proto_files)} proto files")

        progress.update(task, description="Running betterproto2 generation...")
        if not generator.run_protoc(proto_files, proto_path, deps_path, out_path):
            raise typer.Exit(1)
        progress.update(task, description="[green]✓[/green] Code generated")

        progress.update(task, description="Post-processing imports...")
        post_processor.run_post_processing(out_path)
        progress.update(task, description="[green]✓[/green] Imports fixed")

        progress.update(task, description="Fixing required fields...")
        results = required_fields.fix_required_fields(nohiki_proto, nohiki_out)
        total_fixes = sum(r.total_fixes for r in results)
        progress.update(task, description=f"[green]✓[/green] Fixed {total_fixes} required fields")

        progress.update(task, description="Fixing datetime annotations...")
        dt_fixes = post_processor.fix_datetime_optional_annotations(nohiki_out)
        progress.update(task, description=f"[green]✓[/green] Fixed {dt_fixes} datetime annotations")

    con.console.print()
    con.print_success(f"Generated {len(proto_files)} proto files to [cyan]{out_path}[/cyan]")
    con.console.print()
    con.print_info("Import pattern:")
    con.console.print("  [cyan]from nohiki.{domain}.{subdomain}.v1 import MessageClass[/cyan]")
    con.console.print()


def _file_map(root: Path) -> dict[Path, bytes]:
    """Return deterministic relative paths and bytes for a generated tree."""
    if not root.exists():
        return {}
    return {path.relative_to(root): path.read_bytes() for path in sorted(root.rglob("*")) if path.is_file()}


@app.command("check")
def check_cmd() -> None:
    """Regenerate in isolation and fail when committed output is stale."""
    with tempfile.TemporaryDirectory(prefix="nohiki-proto-check-") as tmpdir:
        generated = Path(tmpdir)
        generate_cmd(proto_dir=paths.PROTO_DIR, output_dir=generated)

        stale_roots = [
            name
            for name in ("nohiki", "nohiki_proto_google")
            if _file_map(generated / name) != _file_map(paths.OUTPUT_DIR / name)
        ]

    if stale_roots:
        con.print_error(f"Generated output is stale: {', '.join(stale_roots)}")
        raise typer.Exit(1)
    con.print_success("Generated output matches protobuf sources.")


@app.command("fix-required")
def fix_required_cmd(
    proto_dir: Annotated[Path | None, typer.Option("--proto-dir", "-p", help="Proto source directory")] = None,
    generated_dir: Annotated[
        Path | None, typer.Option("--generated-dir", "-g", help="Generated Python directory")
    ] = None,
    *,
    verbose: Annotated[bool, typer.Option("--verbose", "-v", help="Show detailed output")] = False,
) -> None:
    """Fix required fields in generated betterproto2 code."""
    proto_path = (proto_dir or paths.PROTO_DIR) / "nohiki"
    gen_path = (generated_dir or paths.OUTPUT_DIR) / "nohiki"

    if not proto_path.exists():
        con.print_error(f"Proto directory not found: {proto_path}")
        raise typer.Exit(1)

    if not gen_path.exists():
        con.print_error(f"Generated directory not found: {gen_path}")
        raise typer.Exit(1)

    required = required_fields.parse_proto_directory(proto_path)
    con.print_info(f"Found {required.field_count} required fields in {required.message_count} messages")

    if verbose:
        table = Table(title="Required Fields", show_lines=False)
        table.add_column("Message", style="cyan")
        table.add_column("Fields", style="green")
        for msg in sorted(required.fields.keys()):
            table.add_row(msg, ", ".join(sorted(required.fields[msg])))
        con.console.print(table)

    results = required_fields.fix_required_fields(proto_path, gen_path)
    total_fixes = sum(r.total_fixes for r in results)

    if verbose:
        con.console.print()
        for r in results:
            if r.total_fixes:
                rel_path = r.path.relative_to(gen_path)
                con.console.print(f"  [green]✓[/green] {rel_path}: {r.total_fixes} fixes")

    con.console.print(f"\n[bold]Total fixes:[/bold] {total_fixes}")


@app.command("validate")
def validate_cmd(
    generated_dir: Annotated[
        Path | None, typer.Option("--generated-dir", "-g", help="Generated Python directory")
    ] = None,
) -> None:
    """Validate generated proto types can be imported."""
    gen_path = (generated_dir or paths.OUTPUT_DIR) / "nohiki"

    if not gen_path.exists():
        con.print_error(f"Generated directory not found: {gen_path}")
        raise typer.Exit(1)

    con.print_info("Validating imports...")

    errors: list[str] = []
    for init_file in gen_path.rglob("__init__.py"):
        rel_path = init_file.relative_to(paths.OUTPUT_DIR)
        module_path = str(rel_path.parent).replace("/", ".")

        try:
            __import__(module_path)
        except ImportError as e:
            errors.append(f"{module_path}: {e}")

    if errors:
        con.print_error(f"Validation failed with {len(errors)} error(s):")
        for err in errors:
            con.console.print(f"  [red]•[/red] {err}")
        raise typer.Exit(1)

    con.print_success("All imports validated successfully.")
