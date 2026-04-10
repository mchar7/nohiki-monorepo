#!/usr/bin/env python
"""Kafka Bootstrap Script.

Create Kafka topics using the KafkaAdmin abstraction from nohiki-kafka-client.
"""

from __future__ import annotations

import asyncio
from typing import Annotated

import typer
from nohiki_kafka_client import KafkaAdmin, Topics, TopicSpec
from nohiki_kafka_client.config import KafkaClientConfig
from rich.console import Console
from rich.table import Table

console = Console(stderr=True)
app = typer.Typer(
    name="bootstrap-kafka",
    help="Bootstrap Kafka topic setup.",
    no_args_is_help=True,
)

DEFAULT_PARTITIONS = 3
HIGH_THROUGHPUT_PARTITIONS = 6


def _get_topic_specs() -> list[TopicSpec]:
    """Build topic specifications from the canonical ``Topics`` registry.

    Partition counts are based on expected throughput per domain:
    - User/Doc/Notification/Query topics: default (3)
    - Job ingest/listing/correlation topics: high-throughput (6)
    """
    high_throughput_topics = frozenset(
        {
            Topics.JOB_INGEST_DISCOVERY_REQUESTED,
            Topics.JOB_INGEST_LISTING_DISCOVERED,
            Topics.JOB_INGEST_ENRICHMENT_COMPLETED,
            Topics.JOB_LISTING_ACCEPTED,
            Topics.JOB_LISTING_DUPLICATE_DETECTED,
            Topics.JOB_LISTING_CREATED,
            Topics.JOB_LISTING_UPDATED,
            Topics.JOB_LISTING_DELETED,
            Topics.JOB_CORRELATION_EVALUATED,
        }
    )

    topic_names = [
        Topics.USER_AUTH_ACCOUNT_DELETED,
        Topics.USER_AUTH_ACCOUNT_UPDATED,
        Topics.USER_AUTH_ACCESS_TOKEN_REVOKED,
        Topics.USER_PREF_CREATED,
        Topics.USER_PREF_UPDATED,
        Topics.USER_PREF_DELETED,
        Topics.USER_UPLOAD_CREATED,
        Topics.USER_UPLOAD_UPDATED,
        Topics.USER_UPLOAD_DELETED,
        Topics.USER_ENTITLEMENT_CHANGED,
        Topics.JOB_INGEST_DISCOVERY_REQUESTED,
        Topics.JOB_INGEST_LISTING_DISCOVERED,
        Topics.JOB_INGEST_ENRICHMENT_COMPLETED,
        Topics.JOB_LISTING_ACCEPTED,
        Topics.JOB_LISTING_DUPLICATE_DETECTED,
        Topics.JOB_LISTING_CREATED,
        Topics.JOB_LISTING_UPDATED,
        Topics.JOB_LISTING_DELETED,
        Topics.JOB_CORRELATION_EVALUATED,
        Topics.JOB_CORRELATION_BATCH_COMPLETED,
        Topics.JOB_QUERY_CREATED,
        Topics.JOB_QUERY_UPDATED,
        Topics.JOB_QUERY_DELETED,
        Topics.DOC_TEMPLATE_RENDER_REQUESTED,
        Topics.DOC_TEMPLATE_RENDER_COMPLETED,
        Topics.DOC_TEMPLATE_CREATED,
        Topics.DOC_TEMPLATE_UPDATED,
        Topics.DOC_TEMPLATE_DELETED,
        Topics.DOC_TEMPLATE_CREATE_REQUESTED,
        Topics.DOC_TEMPLATE_VERSION_ADD_REQUESTED,
        Topics.DOC_TEMPLATE_DELETE_REQUESTED,
        Topics.DOC_CONTENT_GENERATION_REQUESTED,
        Topics.DOC_CONTENT_GENERATION_COMPLETED,
        Topics.DOC_CONTENT_GENERATION_FAILED,
        Topics.NOTIFICATION_SENT,
        Topics.NOTIFICATION_FAILED,
    ]

    return [
        TopicSpec(
            name=name,
            num_partitions=(HIGH_THROUGHPUT_PARTITIONS if name in high_throughput_topics else DEFAULT_PARTITIONS),
        )
        for name in topic_names
    ]


async def _bootstrap_topics(bootstrap_servers: str) -> tuple[int, int, list[str]]:
    """Create required Kafka topics.

    Returns:
        Tuple of ``(created_count, existing_count, warnings)``.

    """
    config = KafkaClientConfig(bootstrap_servers=bootstrap_servers)
    specs = _get_topic_specs()

    console.print(f"[blue]Ensuring {len(specs)} topics exist...[/blue]")

    async with KafkaAdmin(config) as admin:
        result = await admin.ensure_topics_exist(specs)

    for name in result.created:
        console.print(f"  [green]✓[/green] Created: {name}")
    for name in result.existing:
        console.print(f"  [dim]○ Exists: {name}[/dim]")
    for warning in result.warnings:
        console.print(f"  [yellow]⚠ {warning}[/yellow]")

    return len(result.created), len(result.existing), list(result.warnings)


@app.command()
def main(
    bootstrap_servers: Annotated[
        str,
        typer.Option("--bootstrap-servers", "-b", help="Kafka bootstrap servers."),
    ],
) -> None:
    """Bootstrap Kafka infrastructure."""
    console.rule("[bold blue]Kafka Bootstrap[/bold blue]")
    console.print(f"Bootstrap servers: {bootstrap_servers}")
    console.print()

    created, existing, warnings = asyncio.run(_bootstrap_topics(bootstrap_servers))

    console.print()
    table = Table(title="Summary", show_header=True, header_style="bold")
    table.add_column("Metric")
    table.add_column("Count", justify="right")
    table.add_row("Topics Created", str(created))
    table.add_row("Topics Existing", str(existing))
    if warnings:
        table.add_row("Warnings", str(len(warnings)))
    console.print(table)

    console.rule("[bold green]Bootstrap Complete![/bold green]")


if __name__ == "__main__":
    app()
