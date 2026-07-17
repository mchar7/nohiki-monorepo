"""Typer CLI for Qdrant collection initialization."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Annotated

import structlog
import typer
from nohiki_ml_manifest import SemanticRepresentationManifest

from qdrant_init.client import QdrantConnectionError, QdrantInitClient
from qdrant_init.initializer import CollectionInitializer

DEFAULT_QDRANT_URL = "http://localhost:6333"

structlog.configure(
    processors=[
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.add_log_level,
        structlog.dev.ConsoleRenderer(colors=True),
    ],
    wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
)

logger = structlog.get_logger(__name__)

app = typer.Typer(
    name="qdrant-init",
    help="Initialize Qdrant collections from semantic representation manifest.",
    no_args_is_help=True,
)


@app.command("init")
def init_collections(
    manifest_path: Annotated[
        Path,
        typer.Option(
            "--manifest",
            "-m",
            envvar="MANIFEST_PATH",
            help="Path to semantic representation manifest JSON.",
        ),
    ],
    qdrant_url: Annotated[
        str,
        typer.Option(
            "--qdrant-url",
            "-u",
            envvar="QDRANT_URL",
            help="Qdrant server URL.",
        ),
    ] = DEFAULT_QDRANT_URL,
    *,
    skip_existing: Annotated[
        bool,
        typer.Option(
            "--skip-existing/--recreate",
            help="Skip existing collections or recreate them.",
        ),
    ] = True,
    wait_for_ready: Annotated[
        bool,
        typer.Option(
            "--wait/--no-wait",
            help="Wait for Qdrant to become available.",
        ),
    ] = True,
) -> None:
    """Initialize all Qdrant collections from manifest."""
    logger.info("qdrant_init_starting", manifest=str(manifest_path), qdrant_url=qdrant_url)

    if not manifest_path.is_file():
        logger.error("manifest_not_file", path=str(manifest_path))
        raise typer.Exit(1)

    try:
        manifest = SemanticRepresentationManifest.load_from_path(manifest_path)
    except OSError, ValueError:
        logger.exception("manifest_invalid", path=str(manifest_path))
        raise typer.Exit(1) from None
    logger.info("manifest_loaded", collections=len(manifest.collections.model_fields))

    with QdrantInitClient(qdrant_url) as client:
        if wait_for_ready:
            try:
                client.wait_for_ready()
            except QdrantConnectionError:
                logger.exception("qdrant_not_available")
                raise typer.Exit(1) from None

        initializer = CollectionInitializer(client, manifest)
        result = initializer.initialize_all(skip_existing=skip_existing)

        logger.info(
            "initialization_complete",
            created=len(result.created),
            skipped=len(result.skipped),
            failed=len(result.failed),
        )

        if not result.success:
            logger.error("initialization_failed", failed=result.failed)
            raise typer.Exit(1)


@app.command("list")
def list_collections(
    qdrant_url: Annotated[
        str,
        typer.Option(
            "--qdrant-url",
            "-u",
            envvar="QDRANT_URL",
            help="Qdrant server URL.",
        ),
    ] = DEFAULT_QDRANT_URL,
) -> None:
    """List all existing Qdrant collections."""
    with QdrantInitClient(qdrant_url) as client:
        try:
            client.wait_for_ready(max_retries=5, retry_interval=1.0)
        except QdrantConnectionError:
            logger.exception("qdrant_not_available")
            raise typer.Exit(1) from None

        collections = client.list_collections()

        if not collections:
            typer.echo("No collections found.")
            return

        typer.echo(f"Found {len(collections)} collections:")
        for name in sorted(collections):
            info = client.get_collection_info(name)
            if info:
                typer.echo(f"  - {name}: {info.points_count} points")
            else:
                typer.echo(f"  - {name}")


@app.command("delete")
def delete_collection(
    collection_name: Annotated[
        str,
        typer.Argument(help="Collection name to delete."),
    ],
    qdrant_url: Annotated[
        str,
        typer.Option(
            "--qdrant-url",
            "-u",
            envvar="QDRANT_URL",
            help="Qdrant server URL.",
        ),
    ] = DEFAULT_QDRANT_URL,
    *,
    force: Annotated[
        bool,
        typer.Option(
            "--force",
            "-f",
            help="Skip confirmation prompt.",
        ),
    ] = False,
) -> None:
    """Delete a Qdrant collection."""
    if not force:
        confirmed = typer.confirm(f"Delete collection '{collection_name}'?")
        if not confirmed:
            raise typer.Abort

    with QdrantInitClient(qdrant_url) as client:
        if client.delete_collection(collection_name):
            logger.info("collection_deleted", collection=collection_name)
        else:
            logger.warning("collection_not_found", collection=collection_name)


if __name__ == "__main__":
    app()
