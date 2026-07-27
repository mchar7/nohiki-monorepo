"""Kafka event flow analyzer using tree-sitter AST parsing."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from ast_explorer.models.events import (
    EventFlow,
    EventFlowGraph,
    EventHandler,
    EventPublisher,
    ServiceEventMap,
    TopicReference,
)

if TYPE_CHECKING:
    from ast_explorer.models.codebase import CodebaseAST


TOPIC_PATTERN = re.compile(r"Topics\.(\w+)")
TOPIC_VALUE_PATTERN = re.compile(r'"([a-z\-]+\.[a-z]+\.[a-z\-]+\.v\d+)"')


@dataclass(slots=True)
class TopicRegistry:
    """Registry of topic constants and their values."""

    topics: dict[str, str] = field(default_factory=dict)

    def get_value(self, constant: str) -> str:
        """Get topic value for a constant name."""
        return self.topics.get(constant, f"unknown.topic.{constant.lower()}.v1")


def _extract_service_name(file_path: Path, root: Path) -> str:
    """Extract service name from file path."""
    try:
        rel_path = file_path.relative_to(root)
    except ValueError:
        rel_path = file_path

    parts = rel_path.parts
    if "services" in parts:
        idx = parts.index("services")
        if idx + 1 < len(parts):
            return parts[idx + 1]
    if "libs" in parts:
        idx = parts.index("libs")
        if idx + 1 < len(parts):
            return parts[idx + 1]
    return "unknown"


def _parse_topic_constant(decorator_text: str) -> str | None:
    """Extract Topics.CONSTANT from decorator text."""
    return match.group(1) if (match := TOPIC_PATTERN.search(decorator_text)) else None


def _parse_message_type(decorator_text: str) -> str | None:
    """Extract message type from decorator arguments."""
    parts = decorator_text.split(",")
    if len(parts) >= 2:
        type_part = parts[1].strip()
        type_part = type_part.split(")")[0].strip()
        type_part = type_part.split("=")[0].strip()
        if type_part and not type_part.startswith("group_id"):
            return type_part
    return None


def _parse_group_id(decorator_text: str) -> str | None:
    """Extract group_id from decorator arguments."""
    return (
        match.group(1).strip().strip("\"'")
        if (match := re.search(r"group_id\s*=\s*([^,)]+)", decorator_text))
        else None
    )


class EventAnalyzer:
    """Analyzes Kafka event flows across a codebase."""

    def __init__(self, root: Path, topics: dict[str, str] | None = None) -> None:
        """Initialize analyzer with root path and optional topic constant mapping."""
        self.root = root.resolve()
        self.topic_registry = TopicRegistry(topics=topics or {})
        self._handlers: list[EventHandler] = []
        self._publishers: list[EventPublisher] = []

    def analyze(self, codebase: CodebaseAST) -> EventFlowGraph:
        """Analyze event flows in the codebase."""
        self._handlers = []
        self._publishers = []

        for file_ast in codebase.files.values():
            self._analyze_file(file_ast.path, codebase.root)

        return self._build_flow_graph()

    def _analyze_file(self, file_path: Path, root: Path) -> None:
        """Analyze a single file for event handlers and publishers."""
        if self._should_skip_file(file_path):
            return

        try:
            content = file_path.read_text(encoding="utf-8")
        except OSError, UnicodeDecodeError:
            return

        service_name = _extract_service_name(file_path, root)
        self._find_handlers(content, file_path, service_name)
        self._find_publishers(content, file_path, service_name)

    def _should_skip_file(self, file_path: Path) -> bool:
        """Check if file should be skipped for event analysis."""
        skip_patterns = {"topics.py", "__init__.py", "conftest.py"}
        is_skip_pattern = file_path.name in skip_patterns
        is_test_file = "test" in file_path.name.lower()
        return is_skip_pattern or is_test_file

    def _find_handlers(self, content: str, file_path: Path, service_name: str) -> None:
        """Find @kafka_client.message_handler decorators."""
        pattern = re.compile(
            r"@kafka_client\.message_handler\s*\(\s*"
            r"([^)]+)"
            r"\)\s*"
            r"(?:@[^\n]+\s*)*"
            r"async\s+def\s+(\w+)",
            re.MULTILINE,
        )

        for match in pattern.finditer(content):
            decorator_args = match.group(1)
            if not (topic_constant := _parse_topic_constant(decorator_args)):
                continue
            function_name = match.group(2)
            line = content[: match.start()].count("\n") + 1

            topic_value = self.topic_registry.get_value(topic_constant)
            topic_ref = TopicReference(
                topic_constant=topic_constant,
                topic_value=topic_value,
                file_path=file_path,
                line=line,
                service_name=service_name,
            )

            handler = EventHandler(
                function_name=function_name,
                topic=topic_ref,
                message_type=_parse_message_type(decorator_args) or "unknown",
                group_id=_parse_group_id(decorator_args),
                file_path=file_path,
                line=line,
            )
            self._handlers.append(handler)

    def _find_publishers(self, content: str, file_path: Path, service_name: str) -> None:
        """Find kafka_client.publish and outbox event calls."""
        patterns = [
            re.compile(r"get_kafka_client\(\)\.publish\s*\(\s*(?:topic\s*=\s*)?Topics\.(\w+)", re.MULTILINE),
            re.compile(r"_get_kafka_producer\(\)\.publish\s*\(\s*(?:topic\s*=\s*)?Topics\.(\w+)", re.MULTILINE),
            re.compile(r"kafka_client\.publish\s*\(\s*(?:topic\s*=\s*)?Topics\.(\w+)", re.MULTILINE),
            re.compile(r"self\._?kafka_?client\.publish\s*\(\s*(?:topic\s*=\s*)?Topics\.(\w+)", re.MULTILINE),
            re.compile(r"event_type\s*=\s*Topics\.(\w+)", re.MULTILINE),
        ]

        for pattern in patterns:
            for match in pattern.finditer(content):
                if not (function_name := self._find_enclosing_function(content, match.start())):
                    continue
                topic_constant = match.group(1)
                line = content[: match.start()].count("\n") + 1

                topic_value = self.topic_registry.get_value(topic_constant)
                topic_ref = TopicReference(
                    topic_constant=topic_constant,
                    topic_value=topic_value,
                    file_path=file_path,
                    line=line,
                    service_name=service_name,
                )

                publisher = EventPublisher(
                    function_name=function_name,
                    topic=topic_ref,
                    file_path=file_path,
                    line=line,
                )
                self._publishers.append(publisher)

    def _find_enclosing_function(self, content: str, position: int) -> str | None:
        """Find the function/method that encloses the given position."""
        for line in reversed(content[:position].split("\n")):
            if match := re.match(r"\s*(?:async\s+)?def\s+(\w+)\s*\(", line):
                return match.group(1)
            if re.match(r"^class\s+\w+", line):
                break
        return None

    def _build_flow_graph(self) -> EventFlowGraph:
        """Build the complete event flow graph."""
        flows: dict[str, EventFlow] = {}
        services: dict[str, ServiceEventMap] = {}

        for handler in self._handlers:
            flow = self._get_or_create_flow(flows, handler.topic)
            flow.handlers.append(handler)
            svc = self._get_or_create_service(services, handler.service_name, handler.file_path.parent)
            svc.consumes.append(handler)

        for publisher in self._publishers:
            flow = self._get_or_create_flow(flows, publisher.topic)
            flow.publishers.append(publisher)
            svc = self._get_or_create_service(services, publisher.service_name, publisher.file_path.parent)
            svc.produces.append(publisher)

        return EventFlowGraph(flows=flows, services=services)

    def _get_or_create_flow(self, flows: dict[str, EventFlow], topic: TopicReference) -> EventFlow:
        """Get existing flow or create new one for topic."""
        return flows.setdefault(
            topic.topic_constant,
            EventFlow(
                topic=topic.topic_value,
                topic_constant=topic.topic_constant,
                classification=topic.classification,
                domain=topic.domain,
            ),
        )

    def _get_or_create_service(self, services: dict[str, ServiceEventMap], name: str, path: Path) -> ServiceEventMap:
        """Get existing service or create new one."""
        return services.setdefault(name, ServiceEventMap(service_name=name, service_path=path))


def load_topic_values(topics_file: Path) -> dict[str, str]:
    """Load topic constant-to-value mappings from nohiki-kafka-client topics.py."""
    topics: dict[str, str] = {}

    try:
        content = topics_file.read_text(encoding="utf-8")
    except OSError, UnicodeDecodeError:
        return topics

    pattern = re.compile(r'(\w+):\s*Final\[str\]\s*=\s*"([^"]+)"')
    for match in pattern.finditer(content):
        topics[match.group(1)] = match.group(2)

    return topics


def analyze_event_flows(codebase: CodebaseAST, topics_file: Path | None = None) -> EventFlowGraph:
    """Analyze event flows in a codebase."""
    topics = load_topic_values(topics_file) if topics_file and topics_file.exists() else {}
    return EventAnalyzer(codebase.root, topics).analyze(codebase)
