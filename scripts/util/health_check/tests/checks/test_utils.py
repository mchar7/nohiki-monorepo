"""Tests for shared check utilities (_utils.py)."""

from __future__ import annotations

import json

from health_check.checks._utils import (
    ConnectorStatus,
    any_group_has_members,
    consumer_group_has_members,
    fetch_connector_names,
    fetch_connector_status,
)

from tests.conftest import MockPlatform


class TestConnectorStatus:
    def test_healthy_when_running(self) -> None:
        s = ConnectorStatus(name="c", state="RUNNING", task_states=("RUNNING",))
        assert s.issue is None

    def test_paused_is_not_running(self) -> None:
        s = ConnectorStatus(name="c", state="PAUSED", task_states=("RUNNING",))
        assert s.issue == "c: connector PAUSED"

    def test_failed_connector_state(self) -> None:
        s = ConnectorStatus(name="c", state="FAILED", task_states=())
        assert s.issue == "c: connector FAILED"

    def test_no_tasks_is_issue(self) -> None:
        s = ConnectorStatus(name="c", state="RUNNING", task_states=())
        assert s.issue == "c: no tasks"

    def test_failed_task_reported(self) -> None:
        s = ConnectorStatus(name="c", state="RUNNING", task_states=("RUNNING", "FAILED"))
        issue = s.issue
        assert issue is not None
        assert "task 1 FAILED" in issue

    def test_all_tasks_running_is_healthy(self) -> None:
        s = ConnectorStatus(name="c", state="RUNNING", task_states=("RUNNING", "RUNNING"))
        assert s.issue is None

    def test_unreachable_connector(self) -> None:
        s = ConnectorStatus(name="c", state="UNREACHABLE", task_states=())
        assert s.issue == "c: connector UNREACHABLE"


class TestFetchConnectorNames:
    async def test_returns_list_on_success(self) -> None:
        body = json.dumps(["conn-a", "conn-b"])
        platform = MockPlatform(_curl_result=(0, body, ""))
        result = await fetch_connector_names(platform, "http://localhost:8083")
        assert result == ["conn-a", "conn-b"]

    async def test_returns_none_on_curl_failure(self) -> None:
        platform = MockPlatform(_curl_result=(1, "", "error"))
        result = await fetch_connector_names(platform, "http://localhost:8083")
        assert result is None

    async def test_returns_none_on_invalid_json(self) -> None:
        platform = MockPlatform(_curl_result=(0, "not-json", ""))
        result = await fetch_connector_names(platform, "http://localhost:8083")
        assert result is None

    async def test_returns_none_when_response_is_dict(self) -> None:
        platform = MockPlatform(_curl_result=(0, json.dumps({"error": "x"}), ""))
        result = await fetch_connector_names(platform, "http://localhost:8083")
        assert result is None


class TestFetchConnectorStatus:
    async def test_parses_running_connector(self) -> None:
        body = json.dumps(
            {
                "connector": {"state": "RUNNING"},
                "tasks": [{"state": "RUNNING"}],
            }
        )
        platform = MockPlatform(_curl_result=(0, body, ""))
        s = await fetch_connector_status(platform, "http://localhost:8083", "my-conn")
        assert s.state == "RUNNING"
        assert s.task_states == ("RUNNING",)
        assert s.issue is None

    async def test_unreachable_when_curl_fails(self) -> None:
        platform = MockPlatform(_curl_result=(1, "", "error"))
        s = await fetch_connector_status(platform, "http://localhost:8083", "c")
        assert s.state == "UNREACHABLE"

    async def test_invalid_response_on_bad_json(self) -> None:
        platform = MockPlatform(_curl_result=(0, "!!!bad!!!", ""))
        s = await fetch_connector_status(platform, "http://localhost:8083", "c")
        assert s.state == "INVALID_RESPONSE"


class TestConsumerGroupHasMembers:
    async def test_returns_true_when_members_present(self) -> None:
        stdout = "GROUP TOPIC PARTITION CONSUMER-ID\nmy-group topic 0 consumer-0"
        platform = MockPlatform(_kafka_cmd_result=(0, stdout, ""))
        assert await consumer_group_has_members(platform, "my-group") is True

    async def test_returns_false_on_command_failure(self) -> None:
        platform = MockPlatform(_kafka_cmd_result=(1, "", "error"))
        assert await consumer_group_has_members(platform, "my-group") is False

    async def test_returns_false_when_no_active_members(self) -> None:
        platform = MockPlatform(_kafka_cmd_result=(0, "has no active members", ""))
        assert await consumer_group_has_members(platform, "my-group") is False

    async def test_returns_false_when_only_header_line(self) -> None:
        platform = MockPlatform(_kafka_cmd_result=(0, "GROUP TOPIC PARTITION\n", ""))
        assert await consumer_group_has_members(platform, "my-group") is False


class TestAnyGroupHasMembers:
    async def test_empty_group_ids_returns_false(self) -> None:
        platform = MockPlatform()
        assert await any_group_has_members(platform, ()) is False

    async def test_returns_true_when_one_has_members(self) -> None:
        stdout = "GROUP TOPIC\nmy-group topic 0 consumer"
        platform = MockPlatform(_kafka_cmd_result=(0, stdout, ""))
        assert await any_group_has_members(platform, ("grp-a",)) is True

    async def test_returns_false_when_none_have_members(self) -> None:
        platform = MockPlatform(_kafka_cmd_result=(1, "", ""))
        assert await any_group_has_members(platform, ("grp-a", "grp-b")) is False
