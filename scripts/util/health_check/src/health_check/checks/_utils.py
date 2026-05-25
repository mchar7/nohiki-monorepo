"""Shared async utility helpers used across multiple check modules."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from health_check.config.thresholds import (
    HTTP_CHECK_TIMEOUT_SECONDS,
    KAFKA_GROUP_MEMBERSHIP_TIMEOUT_SECONDS,
)

if TYPE_CHECKING:
    from health_check.platform.protocol import Platform

_HEALTHY_CONNECTOR_STATES: Final[frozenset[str]] = frozenset({"RUNNING"})


@dataclass(frozen=True, slots=True)
class ConnectorStatus:
    """Parsed health status for a single Kafka Connect connector."""

    name: str
    state: str
    task_states: tuple[str, ...]

    @property
    def issue(self) -> str | None:
        """Return a human-readable issue description, or None if healthy."""
        if self.state not in _HEALTHY_CONNECTOR_STATES:
            return f"{self.name}: connector {self.state}"
        if not self.task_states:
            return f"{self.name}: no tasks"
        failed = [f"task {i} {s}" for i, s in enumerate(self.task_states) if s != "RUNNING"]
        return f"{self.name}: {', '.join(failed)}" if failed else None


async def fetch_connector_status(
    platform: Platform,
    connect_base: str,
    name: str,
) -> ConnectorStatus:
    """Fetch and parse health for a single Kafka Connect connector.

    Args:
        platform: Active platform for HTTP curl.
        connect_base: Base URL of the Kafka Connect REST API.
        name: Connector name to inspect.

    Returns:
        Parsed ``ConnectorStatus`` with state and task states.
    """
    code, stdout, _ = await asyncio.to_thread(
        platform.curl,
        f"{connect_base}/connectors/{name}/status",
        timeout=int(HTTP_CHECK_TIMEOUT_SECONDS),
    )
    if code != 0:
        return ConnectorStatus(name=name, state="UNREACHABLE", task_states=())
    try:
        data = json.loads(stdout)
        state = data.get("connector", {}).get("state", "UNKNOWN")
        tasks = tuple(t.get("state", "UNKNOWN") for t in data.get("tasks", []))
        return ConnectorStatus(name=name, state=state, task_states=tasks)
    except json.JSONDecodeError, ValueError, AttributeError:
        return ConnectorStatus(name=name, state="INVALID_RESPONSE", task_states=())


async def fetch_connector_names(
    platform: Platform,
    connect_base: str,
) -> list[str] | None:
    """Fetch all registered connector names from the Kafka Connect REST API.

    Args:
        platform: Active platform for HTTP curl.
        connect_base: Base URL of the Kafka Connect REST API.

    Returns:
        List of connector names, or ``None`` if the API is unreachable.
    """
    code, stdout, _ = await asyncio.to_thread(
        platform.curl,
        f"{connect_base}/connectors",
        timeout=int(HTTP_CHECK_TIMEOUT_SECONDS),
    )
    if code != 0:
        return None
    try:
        result = json.loads(stdout)
        return result if isinstance(result, list) else None
    except json.JSONDecodeError, ValueError:
        return None


async def consumer_group_has_members(platform: Platform, group_id: str) -> bool:
    """Return True if the Kafka consumer group has at least one active member.

    Args:
        platform: Active platform to query Kafka through.
        group_id: Kafka consumer group ID to inspect.

    Returns:
        True when the group has active members, False otherwise.
    """
    code, stdout, _ = await asyncio.to_thread(
        platform.exec_kafka_cmd,
        [
            "kafka-consumer-groups",
            "--bootstrap-server",
            platform.kafka_bootstrap_server,
            "--describe",
            "--group",
            group_id,
        ],
        timeout=KAFKA_GROUP_MEMBERSHIP_TIMEOUT_SECONDS,
    )
    if code != 0:
        return False
    if "has no active members" in stdout:
        return False
    return any(line.strip() for line in stdout.splitlines()[1:])


async def any_group_has_members(platform: Platform, group_ids: tuple[str, ...]) -> bool:
    """Return True if at least one of the given consumer groups has active members.

    Checks all groups in parallel for efficiency.

    Args:
        platform: Active platform to query Kafka through.
        group_ids: Consumer group IDs to inspect.

    Returns:
        True if any group has active members.
    """
    if not group_ids:
        return False
    async with asyncio.TaskGroup() as tg:
        tasks = [tg.create_task(consumer_group_has_members(platform, gid)) for gid in group_ids]
    return any(t.result() for t in tasks)
