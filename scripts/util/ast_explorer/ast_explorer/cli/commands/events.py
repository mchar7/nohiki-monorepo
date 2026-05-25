"""Events command for AST Explorer."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from ast_explorer.cli.utils import extract_codebase, validate_path


def events_cmd(
    path: Annotated[Path, typer.Argument(help="Path to scan")] = Path(),
    service: Annotated[str | None, typer.Option("--service", "-s", help="Filter by service name")] = None,
    topic: Annotated[str | None, typer.Option("--topic", "-t", help="Filter by topic constant")] = None,
    trace: Annotated[bool, typer.Option("--trace", help="Trace event chains from topic")] = False,
) -> None:
    """Analyze Kafka event flows across services."""
    from ast_explorer.analysis.event_analyzer import analyze_event_flows
    from ast_explorer.cli.display import console
    from ast_explorer.cli.display_events import (
        print_all_event_flows,
        print_event_chain_tree,
        print_service_event_map,
        print_single_event_flow,
    )

    root = validate_path(path)
    codebase = extract_codebase(root)

    topics_file = _get_topics_file(root)
    flow_graph = analyze_event_flows(codebase, topics_file)

    if trace and topic:
        chains = flow_graph.trace_event_chain(topic)
        print_event_chain_tree(topic, chains, flow_graph)
        return

    if service:
        if svc := flow_graph.services.get(service):
            print_service_event_map(service, svc, flow_graph)
        else:
            console.print(f"[yellow]Service not found: {service}[/yellow]")
            raise typer.Exit(1)
        return

    if topic:
        if flow := flow_graph.flows.get(topic):
            print_single_event_flow(topic, flow)
        else:
            console.print(f"[yellow]Topic not found: {topic}[/yellow]")
            raise typer.Exit(1)
        return

    print_all_event_flows(flow_graph)


def _get_topics_file(root: Path) -> Path | None:
    """Get path to Kafka topics file if it exists."""
    topics_file = root / "backend" / "libs" / "nohiki-kafka-client" / "src" / "nohiki_kafka_client" / "topics.py"
    return topics_file if topics_file.exists() else None
