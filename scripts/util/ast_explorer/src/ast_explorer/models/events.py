"""Models for Kafka event flow analysis."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ast_explorer.models.nodes import SymbolNode


class EventClassification(StrEnum):
    """Kafka topic classification based on naming convention."""

    CDC = "cdc"
    FACT = "fct"
    COMMAND = "cmd"
    SYSTEM = "sys"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class TopicReference:
    """A reference to a Kafka topic in code."""

    topic_constant: str
    topic_value: str
    file_path: Path
    line: int
    service_name: str

    @property
    def domain(self) -> str:
        """Extract domain from topic value (e.g., 'user-pref' from 'user-pref.cdc.created.v1')."""
        parts = self.topic_value.split(".")
        return parts[0] if parts else ""

    @property
    def classification(self) -> EventClassification:
        """Extract classification from topic value."""
        parts = self.topic_value.split(".")
        if len(parts) >= 2:
            try:
                return EventClassification(parts[1])
            except ValueError:
                pass
        return EventClassification.UNKNOWN


@dataclass(frozen=True, slots=True)
class EventHandler:
    """A Kafka message handler (consumer)."""

    function_name: str
    topic: TopicReference
    message_type: str
    group_id: str | None
    file_path: Path
    line: int
    symbol: SymbolNode | None = None

    @property
    def service_name(self) -> str:
        """Extract service name from file path."""
        return self.topic.service_name


@dataclass(frozen=True, slots=True)
class EventPublisher:
    """A Kafka event publisher (producer)."""

    function_name: str
    topic: TopicReference
    file_path: Path
    line: int
    symbol: SymbolNode | None = None

    @property
    def service_name(self) -> str:
        """Extract service name from file path."""
        return self.topic.service_name


@dataclass(slots=True)
class EventFlow:
    """Represents a complete event flow from publisher to handlers."""

    topic: str
    topic_constant: str
    classification: EventClassification
    domain: str
    publishers: list[EventPublisher] = field(default_factory=list)
    handlers: list[EventHandler] = field(default_factory=list)

    @property
    def producer_services(self) -> set[str]:
        """Set of services that produce this event."""
        return {p.service_name for p in self.publishers}

    @property
    def consumer_services(self) -> set[str]:
        """Set of services that consume this event."""
        return {h.service_name for h in self.handlers}

    @property
    def is_cross_service(self) -> bool:
        """True if event flows between different services."""
        return len(self.producer_services | self.consumer_services) > 1


@dataclass(slots=True)
class ServiceEventMap:
    """Complete event map for a service."""

    service_name: str
    service_path: Path
    produces: list[EventPublisher] = field(default_factory=list)
    consumes: list[EventHandler] = field(default_factory=list)

    @property
    def produced_topics(self) -> set[str]:
        """Set of topic constants this service produces."""
        return {p.topic.topic_constant for p in self.produces}

    @property
    def consumed_topics(self) -> set[str]:
        """Set of topic constants this service consumes."""
        return {h.topic.topic_constant for h in self.consumes}


@dataclass(slots=True)
class EventFlowGraph:
    """Complete event flow graph across all services."""

    flows: dict[str, EventFlow] = field(default_factory=dict)
    services: dict[str, ServiceEventMap] = field(default_factory=dict)

    def get_downstream_services(self, service_name: str) -> set[str]:
        """Get services that consume events produced by this service."""
        downstream: set[str] = set()
        service = self.services.get(service_name)
        if not service:
            return downstream

        for topic in service.produced_topics:
            flow = self.flows.get(topic)
            if flow:
                downstream.update(flow.consumer_services - {service_name})
        return downstream

    def get_upstream_services(self, service_name: str) -> set[str]:
        """Get services that produce events consumed by this service."""
        upstream: set[str] = set()
        service = self.services.get(service_name)
        if not service:
            return upstream

        for topic in service.consumed_topics:
            flow = self.flows.get(topic)
            if flow:
                upstream.update(flow.producer_services - {service_name})
        return upstream

    def _should_stop_tracing(self, topic: str, depth: int, max_depth: int, visited: set[str]) -> bool:
        """Check if tracing should stop for this topic."""
        return depth > max_depth or topic in visited

    def _find_downstream_topics(self, topic: str, flow: EventFlow) -> list[str]:
        """Find all downstream topics from the given flow."""
        downstream: list[str] = []
        for consumer_service in flow.consumer_services:
            service = self.services.get(consumer_service)
            if service:
                downstream.extend(
                    pub.topic.topic_constant for pub in service.produces if pub.topic.topic_constant != topic
                )
        return downstream

    def trace_event_chain(self, start_topic: str, max_depth: int = 5) -> list[list[str]]:
        """Trace event chains starting from a topic (what events trigger what)."""
        chains: list[list[str]] = []
        visited: set[str] = set()

        def _trace(topic: str, chain: list[str], depth: int) -> None:
            if self._should_stop_tracing(topic, depth, max_depth, visited):
                if chain:
                    chains.append(chain.copy())
                return

            visited.add(topic)
            chain.append(topic)

            flow = self.flows.get(topic)
            if not flow:
                chains.append(chain.copy())
                return

            downstream_topics = self._find_downstream_topics(topic, flow)
            if downstream_topics:
                for downstream_topic in downstream_topics:
                    _trace(downstream_topic, chain.copy(), depth + 1)
            else:
                chains.append(chain.copy())

        _trace(start_topic, [], 0)
        return chains

    def _get_downstream_topics(self, flow: EventFlow, current_topic: str) -> list[str]:
        """Get topics produced by services that consume the given flow."""
        topics: list[str] = []
        for consumer_service in flow.consumer_services:
            service = self.services.get(consumer_service)
            if service:
                topics.extend(
                    pub.topic.topic_constant for pub in service.produces if pub.topic.topic_constant != current_topic
                )
        return topics
