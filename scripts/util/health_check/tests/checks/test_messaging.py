"""Tests for messaging health checks."""

from __future__ import annotations

import json

from health_check.checks.messaging.consumer_lag import ConsumerLagCheck
from health_check.checks.messaging.consumers import KafkaConsumersCheck
from health_check.checks.messaging.event_flow import KafkaEventFlowCheck
from health_check.checks.messaging.topics import KafkaTopicsCheck
from health_check.config.thresholds import KAFKA_CONNECT_DEFAULT_PORT
from health_check.core.models import CheckStatus

from tests.conftest import MockPlatform


class TestKafkaTopicsCheck:
    async def test_passes_when_all_topics_exist(self) -> None:
        from health_check.config.kafka import get_all_topic_names

        topic_list = "\n".join(get_all_topic_names())
        platform = MockPlatform(_kafka_cmd_result=(0, topic_list, ""))
        result = await KafkaTopicsCheck().execute(platform)
        assert result.status == CheckStatus.PASSED

    async def test_fails_when_topics_missing(self) -> None:
        platform = MockPlatform(_kafka_cmd_result=(0, "", ""))
        result = await KafkaTopicsCheck().execute(platform)
        assert result.status == CheckStatus.FAILED

    async def test_error_when_command_fails(self) -> None:
        platform = MockPlatform(_kafka_cmd_result=(1, "", "connection refused"))
        result = await KafkaTopicsCheck().execute(platform)
        assert result.status == CheckStatus.ERROR

    def test_metadata_check_id(self) -> None:
        assert KafkaTopicsCheck().metadata.check_id == "kafka_topics"

    def test_depends_on_broker(self) -> None:
        assert "kafka_broker" in KafkaTopicsCheck().metadata.depends_on


class TestKafkaConsumersCheck:
    async def test_passes_when_all_groups_have_members(self) -> None:
        members_line = "GROUP TOPIC PARTITION CONSUMER-ID\ngrp topic 0 consumer-0"
        platform = MockPlatform(_kafka_cmd_result=(0, members_line, ""))
        result = await KafkaConsumersCheck().execute(platform)
        assert result.status == CheckStatus.PASSED
        assert "critical consumer groups active" in result.summary

    async def test_fails_when_no_groups_have_members(self) -> None:
        platform = MockPlatform(_kafka_cmd_result=(0, "Consumer group has no active members.", ""))
        result = await KafkaConsumersCheck().execute(platform)
        assert result.status == CheckStatus.FAILED
        assert result.details
        assert all("NO ACTIVE MEMBERS" in detail for detail in result.details)
        assert result.remediation_hint is not None

    def test_metadata_check_id(self) -> None:
        assert KafkaConsumersCheck().metadata.check_id == "kafka_consumers"


class TestConsumerLagCheck:
    async def test_passes_when_no_lag(self) -> None:
        # Output with all zero lag values
        stdout = "GROUP TOPIC PARTITION CURRENT-OFFSET LOG-END-OFFSET LAG\nmy-group my-topic 0 100 100 0\n"
        platform = MockPlatform(_kafka_cmd_result=(0, stdout, ""))
        result = await ConsumerLagCheck().execute(platform)
        assert result.status == CheckStatus.PASSED
        assert "acceptable lag" in result.summary

    async def test_fails_when_excessive_lag(self) -> None:
        stdout = "GROUP TOPIC PARTITION CURRENT-OFFSET LOG-END-OFFSET LAG\nmy-group my-topic 0 0 10000 10000\n"
        platform = MockPlatform(_kafka_cmd_result=(0, stdout, ""))
        result = await ConsumerLagCheck().execute(platform)
        assert result.status == CheckStatus.FAILED
        assert result.details
        assert all("LAG=10000" in detail and "threshold=" in detail for detail in result.details)
        assert result.remediation_hint is not None
        assert "restart" in result.remediation_hint.lower()

    def test_metadata_check_id(self) -> None:
        assert ConsumerLagCheck().metadata.check_id == "consumer_lag"


class TestKafkaEventFlowCheck:
    async def test_passes_with_registered_connectors(self) -> None:
        connectors = json.dumps(["connector-a", "connector-b"])
        platform = MockPlatform(_curl_result=(0, connectors, ""))
        result = await KafkaEventFlowCheck().execute(platform)
        assert result.status == CheckStatus.PASSED
        assert "2 connector(s)" in result.summary

    async def test_passes_with_empty_connector_list(self) -> None:
        platform = MockPlatform(_curl_result=(0, json.dumps([]), ""))
        result = await KafkaEventFlowCheck().execute(platform)
        assert result.status == CheckStatus.PASSED
        assert "0 connector(s)" in result.summary

    async def test_fails_when_connect_api_unreachable(self) -> None:
        platform = MockPlatform(_curl_result=(1, "", "connection refused"))
        result = await KafkaEventFlowCheck().execute(platform)
        assert result.status == CheckStatus.FAILED
        assert "Cannot reach Kafka Connect" in result.summary

    async def test_passes_with_invalid_json_response(self) -> None:
        platform = MockPlatform(_curl_result=(0, "not-json", ""))
        result = await KafkaEventFlowCheck().execute(platform)
        assert result.status == CheckStatus.PASSED
        assert "0 connector(s)" in result.summary

    async def test_failure_includes_stderr_detail(self) -> None:
        platform = MockPlatform(_curl_result=(1, "", "timeout after 10s"))
        result = await KafkaEventFlowCheck().execute(platform)
        assert result.status == CheckStatus.FAILED
        assert any("timeout" in d for d in result.details)

    def test_metadata_check_id(self) -> None:
        assert KafkaEventFlowCheck().metadata.check_id == "kafka_event_flow"

    def test_metadata_connect_port_in_remediation(self) -> None:
        assert KafkaEventFlowCheck().metadata.check_id == "kafka_event_flow"
        assert KAFKA_CONNECT_DEFAULT_PORT == 8083
