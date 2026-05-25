"""Display functions for event flow analysis."""

from __future__ import annotations

from typing import TYPE_CHECKING

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.tree import Tree

if TYPE_CHECKING:
    from ast_explorer.models.events import EventFlow, EventFlowGraph, ServiceEventMap

console = Console()


def print_event_chain_tree(topic: str, chains: list[list[str]], flow_graph: EventFlowGraph) -> None:
    """Print event chain as a tree."""
    tree = Tree(f"[bold cyan]Event Chain: {topic}[/bold cyan]")

    for chain in chains:
        branch = tree.add(" → ".join(chain))
        for topic_name in chain:
            _add_flow_details_to_branch(branch, topic_name, flow_graph)

    console.print(tree)


def _add_flow_details_to_branch(branch: Tree, topic_name: str, flow_graph: EventFlowGraph) -> None:
    """Add producer/consumer details to a tree branch."""
    if flow := flow_graph.flows.get(topic_name):
        branch.add(f"[dim]Producers: {', '.join(flow.producer_services)}[/dim]")
        branch.add(f"[dim]Consumers: {', '.join(flow.consumer_services)}[/dim]")


def print_service_event_map(service: str, svc: ServiceEventMap, flow_graph: EventFlowGraph) -> None:
    """Print event map for a specific service."""
    console.print(Panel(f"[bold]{service}[/bold]", title="Service Event Map"))

    if svc.produces:
        _print_producer_table(svc)

    if svc.consumes:
        _print_consumer_table(svc)

    _print_service_relationships(service, flow_graph)


def _print_producer_table(svc: ServiceEventMap) -> None:
    """Print table of events this service produces."""
    table = Table(title="Produces", show_header=True)
    table.add_column("Topic", style="cyan")
    table.add_column("Function")
    table.add_column("File")

    for pub in svc.produces:
        table.add_row(pub.topic.topic_constant, pub.function_name, pub.file_path.name)

    console.print(table)


def _print_consumer_table(svc: ServiceEventMap) -> None:
    """Print table of events this service consumes."""
    table = Table(title="Consumes", show_header=True)
    table.add_column("Topic", style="green")
    table.add_column("Handler")
    table.add_column("Message Type")

    for handler in svc.consumes:
        table.add_row(handler.topic.topic_constant, handler.function_name, handler.message_type)

    console.print(table)


def _print_service_relationships(service: str, flow_graph: EventFlowGraph) -> None:
    """Print upstream/downstream service relationships."""
    downstream = flow_graph.get_downstream_services(service)
    upstream = flow_graph.get_upstream_services(service)

    if downstream:
        console.print(f"\n[bold]Downstream services:[/bold] {', '.join(downstream)}")
    if upstream:
        console.print(f"[bold]Upstream services:[/bold] {', '.join(upstream)}")


def print_single_event_flow(topic: str, flow: EventFlow) -> None:
    """Print details for a single event flow."""
    console.print(Panel(f"[bold]{topic}[/bold]\n{flow.topic}", title="Event Flow"))
    console.print(f"Domain: {flow.domain}, Classification: {flow.classification.value}")

    _print_event_publishers(flow)
    _print_event_handlers(flow)


def _print_event_publishers(flow: EventFlow) -> None:
    """Print list of publishers for an event."""
    console.print(f"\n[bold]Producers ({len(flow.publishers)}):[/bold]")
    for pub in flow.publishers:
        console.print(f"  • {pub.service_name}: {pub.function_name} ({pub.file_path.name}:{pub.line})")


def _print_event_handlers(flow: EventFlow) -> None:
    """Print list of handlers for an event."""
    console.print(f"\n[bold]Consumers ({len(flow.handlers)}):[/bold]")
    for handler in flow.handlers:
        console.print(f"  • {handler.service_name}: {handler.function_name} ({handler.file_path.name}:{handler.line})")


def print_all_event_flows(flow_graph: EventFlowGraph) -> None:
    """Print summary table of all event flows."""
    table = Table(title=f"Event Flows ({len(flow_graph.flows)} topics)", show_header=True)
    table.add_column("Topic", style="cyan")
    table.add_column("Domain")
    table.add_column("Type")
    table.add_column("Producers", style="yellow")
    table.add_column("Consumers", style="green")

    for topic_const, flow in sorted(flow_graph.flows.items()):
        table.add_row(
            topic_const,
            flow.domain,
            flow.classification.value,
            str(len(flow.publishers)),
            str(len(flow.handlers)),
        )

    console.print(table)
    console.print(f"\n[bold]Services:[/bold] {', '.join(sorted(flow_graph.services.keys()))}")
