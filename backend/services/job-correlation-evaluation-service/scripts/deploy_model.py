#!/usr/bin/env python
"""L2R Model Deployment Script.

Update model metadata to set a new active version and optionally
copy model files to the deployment location.
"""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any

import joblib
import lightgbm as lgb
import typer
from rich.console import Console
from rich.table import Table

console = Console(stderr=True)
app = typer.Typer(
    name="deploy-model",
    help="Deploy and manage L2R model versions.",
    no_args_is_help=True,
)


@dataclass(frozen=True, slots=True)
class DeploymentConfig:
    """Configuration constants for deployment."""

    MIN_HISTORY_FOR_ROLLBACK: int = 2


CONFIG = DeploymentConfig()


def _load_metadata(models_dir: Path) -> dict[str, Any]:
    """Load model metadata from JSON file."""
    metadata_path = models_dir / "model_metadata.json"
    if not metadata_path.exists():
        msg = f"Metadata file not found: {metadata_path}"
        raise typer.BadParameter(msg)

    return json.loads(metadata_path.read_text())


def _save_metadata(models_dir: Path, metadata: dict[str, Any]) -> None:
    """Save model metadata to JSON file."""
    metadata_path = models_dir / "model_metadata.json"
    metadata_path.write_text(json.dumps(metadata, indent=2))


def _validate_version(models_dir: Path, version: str) -> tuple[Path, Path]:
    """Validate model files exist for the specified version."""
    metadata = _load_metadata(models_dir)
    versions = metadata.get("versions", {})

    if version not in versions:
        available = ", ".join(versions.keys())
        msg = f"Version '{version}' not found. Available: {available}"
        raise typer.BadParameter(msg)

    version_info = versions[version]
    model_file = version_info.get("l2r_model")
    calibrator_file = version_info.get("calibrator")

    if not model_file or not calibrator_file:
        msg = f"Version '{version}' missing file paths in metadata"
        raise typer.BadParameter(msg)

    model_path = models_dir / model_file
    calibrator_path = models_dir / calibrator_file

    if not model_path.exists():
        msg = f"Model file not found: {model_path}"
        raise typer.BadParameter(msg)

    if not calibrator_path.exists():
        msg = f"Calibrator file not found: {calibrator_path}"
        raise typer.BadParameter(msg)

    return model_path, calibrator_path


def _validate_models_dir(models_dir: Path) -> None:
    """Validate models directory exists."""
    if not models_dir.exists():
        console.print(f"[red]Error: Models directory not found: {models_dir}[/red]")
        raise typer.Exit(1)


@app.command("list")
def list_versions_cmd(
    models_dir: Annotated[
        Path,
        typer.Option("--models-dir", "-m", help="Directory containing model files."),
    ] = Path("models"),
) -> None:
    """List all available model versions."""
    _validate_models_dir(models_dir)

    metadata = _load_metadata(models_dir)
    current = metadata.get("current_version")
    versions = metadata.get("versions", {})

    console.print("\n[bold]Available Model Versions[/bold]")
    console.rule()

    if not versions:
        console.print("  [dim]No versions found[/dim]")
        return

    table = Table(show_header=True, header_style="bold")
    table.add_column("Version")
    table.add_column("Status")
    table.add_column("Created")
    table.add_column("NDCG@10")
    table.add_column("Samples")

    for version, info in sorted(
        versions.items(),
        key=lambda x: x[1].get("created_at", ""),
        reverse=True,
    ):
        status = "[green]ACTIVE[/green]" if version == current else ""
        created = info.get("created_at", "unknown")[:19]
        ndcg = info.get("ndcg_at_10", 0.0)
        samples = info.get("training_samples", 0)
        table.add_row(version, status, created, f"{ndcg:.4f}", str(samples))

    console.print(table)


def _copy_files_to_deploy_dir(
    model_path: Path,
    calibrator_path: Path,
    deploy_dir: Path,
    *,
    dry_run: bool = False,
) -> None:
    """Copy model files to deployment directory."""
    deploy_dir.mkdir(parents=True, exist_ok=True)

    dest_model = deploy_dir / "l2r_lightgbm_bootstrap.txt"
    dest_calibrator = deploy_dir / "calibrator_bootstrap.joblib"

    console.print(f"\n  Copying to deployment directory: {deploy_dir}")
    console.print(f"    {model_path.name} -> {dest_model.name}")
    console.print(f"    {calibrator_path.name} -> {dest_calibrator.name}")

    if not dry_run:
        shutil.copy2(model_path, dest_model)
        shutil.copy2(calibrator_path, dest_calibrator)


def _update_deployment_metadata(
    models_dir: Path,
    metadata: dict[str, Any],
    version: str,
    old_version: str | None,
) -> None:
    """Update metadata with new deployment."""
    metadata["current_version"] = version
    metadata["deployment_history"] = metadata.get("deployment_history", [])
    metadata["deployment_history"].append(
        {
            "version": version,
            "previous_version": old_version,
            "deployed_at": datetime.now(UTC).isoformat(),
        }
    )
    _save_metadata(models_dir, metadata)


@app.command("deploy")
def deploy_cmd(
    version: Annotated[str, typer.Argument(help="Version to deploy.")],
    models_dir: Annotated[
        Path,
        typer.Option(
            "--models-dir",
            "-m",
            help="Directory containing model files.",
            rich_help_panel="Paths",
        ),
    ] = Path("models"),
    deploy_dir: Annotated[
        Path | None,
        typer.Option(
            "--deploy-dir",
            "-d",
            help="Copy model files to this directory.",
            rich_help_panel="Paths",
        ),
    ] = None,
    dry_run: Annotated[
        bool,
        typer.Option(
            "--dry-run",
            help="Show what would be done without making changes.",
            rich_help_panel="Flags",
        ),
    ] = False,
) -> None:
    """Deploy a specific model version."""
    _validate_models_dir(models_dir)

    prefix = "[DRY RUN] " if dry_run else ""
    console.print(f"\n{prefix}[bold]Deploying version: {version}[/bold]")
    console.rule()

    model_path, calibrator_path = _validate_version(models_dir, version)
    console.print(f"  Model: {model_path}")
    console.print(f"  Calibrator: {calibrator_path}")

    metadata = _load_metadata(models_dir)
    old_version = metadata.get("current_version")

    if old_version == version:
        console.print(f"\n  [yellow]Version '{version}' is already active[/yellow]")
        return

    if deploy_dir:
        _copy_files_to_deploy_dir(model_path, calibrator_path, deploy_dir, dry_run=dry_run)

    console.print(f"\n  Updating current_version: {old_version} -> {version}")

    if not dry_run:
        _update_deployment_metadata(models_dir, metadata, version, old_version)

    console.print("\n[green]✅ Deployment complete![/green]")
    if not dry_run:
        console.print("\n  [dim]Note: Restart services to load new model[/dim]")
        console.print("  [dim]Or use rolling deployment to update gradually[/dim]")


@app.command("rollback")
def rollback_cmd(
    models_dir: Annotated[
        Path,
        typer.Option("--models-dir", "-m", help="Directory containing model files."),
    ] = Path("models"),
    dry_run: Annotated[
        bool,
        typer.Option("--dry-run", help="Show what would be done without making changes."),
    ] = False,
) -> None:
    """Rollback to previous model version."""
    _validate_models_dir(models_dir)

    prefix = "[DRY RUN] " if dry_run else ""
    console.print(f"\n{prefix}[bold]Rolling back to previous version[/bold]")
    console.rule()

    metadata = _load_metadata(models_dir)
    history = metadata.get("deployment_history", [])

    if len(history) < CONFIG.MIN_HISTORY_FOR_ROLLBACK:
        console.print("  [red]Error: No previous version in deployment history[/red]")
        console.print("  [dim]Use deploy command to specify a version manually[/dim]")
        raise typer.Exit(1)

    previous_entry = history[-2]
    previous_version = previous_entry.get("version")

    if not previous_version:
        console.print("  [red]Error: Could not determine previous version[/red]")
        raise typer.Exit(1)

    console.print(f"  Rolling back to: {previous_version}")

    model_path, calibrator_path = _validate_version(models_dir, previous_version)
    console.print(f"  Model: {model_path}")
    console.print(f"  Calibrator: {calibrator_path}")

    old_version = metadata.get("current_version")
    console.print(f"\n  Updating current_version: {old_version} -> {previous_version}")

    if not dry_run:
        _update_deployment_metadata(models_dir, metadata, previous_version, old_version)

    console.print("\n[green]✅ Rollback complete![/green]")


def _verify_model_loads(model_path: Path) -> bool:
    """Verify model file loads successfully."""
    try:
        model = lgb.Booster(model_file=str(model_path))
    except (OSError, ValueError, RuntimeError) as e:
        console.print(f"  [red]❌ Model load failed: {e}[/red]")
        return False
    else:
        console.print(f"  [green]✅ Model loads successfully ({model.num_trees()} trees)[/green]")
        return True


def _verify_calibrator_loads(calibrator_path: Path) -> bool:
    """Verify calibrator file loads successfully."""
    try:
        joblib.load(calibrator_path)
    except (OSError, ValueError, ModuleNotFoundError) as e:
        console.print(f"  [red]❌ Calibrator load failed: {e}[/red]")
        return False
    else:
        console.print("  [green]✅ Calibrator loads successfully[/green]")
        return True


@app.command("verify")
def verify_cmd(
    models_dir: Annotated[
        Path,
        typer.Option("--models-dir", "-m", help="Directory containing model files."),
    ] = Path("models"),
) -> None:
    """Verify the current deployment is valid."""
    console.print("\n[bold]Verifying current deployment...[/bold]")
    console.rule()

    if not models_dir.exists():
        console.print(f"  [red]❌ Models directory not found: {models_dir}[/red]")
        raise typer.Exit(1)

    try:
        metadata = _load_metadata(models_dir)
    except typer.BadParameter as e:
        console.print(f"  [red]❌ {e}[/red]")
        raise typer.Exit(1) from e

    current = metadata.get("current_version")
    if not current:
        console.print("  [yellow]⚠️  No current_version set[/yellow]")
        raise typer.Exit(1)

    console.print(f"  Current version: {current}")

    try:
        model_path, calibrator_path = _validate_version(models_dir, current)
        console.print(f"  [green]✅ Model file exists: {model_path.name}[/green]")
        console.print(f"  [green]✅ Calibrator file exists: {calibrator_path.name}[/green]")
    except typer.BadParameter as e:
        console.print(f"  [red]❌ {e}[/red]")
        raise typer.Exit(1) from e

    model_ok = _verify_model_loads(model_path)
    calibrator_ok = _verify_calibrator_loads(calibrator_path)

    if not model_ok or not calibrator_ok:
        raise typer.Exit(1)

    console.print("\n[green]✅ Deployment verification passed![/green]")


if __name__ == "__main__":
    app()
