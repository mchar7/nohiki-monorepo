"""Unit tests for admin module data models and exceptions."""

from __future__ import annotations

import pytest
from nohiki_kafka_client.admin.exceptions import AdminError, TopicAlreadyExistsError
from nohiki_kafka_client.admin.models import (
    MAX_TOPIC_NAME_LENGTH,
    TOPIC_NAME_PATTERN,
    EnsureTopicsResult,
    TopicDescription,
    TopicSpec,
)
from nohiki_kafka_client.exceptions import KafkaClientError


class TestTopicSpec:
    """Tests for TopicSpec dataclass validation."""

    def test_valid_defaults(self) -> None:
        """TopicSpec with only name uses default partitions and replication."""
        spec = TopicSpec(name="my-topic")
        assert spec.name == "my-topic"
        assert spec.num_partitions == 3
        assert spec.replication_factor == 1
        assert spec.topic_configs is None

    def test_valid_all_fields(self) -> None:
        """TopicSpec with all fields set."""
        spec = TopicSpec(
            name="job.listing.created.v1",
            num_partitions=6,
            replication_factor=3,
            topic_configs={"retention.ms": "86400000"},
        )
        assert spec.name == "job.listing.created.v1"
        assert spec.num_partitions == 6
        assert spec.replication_factor == 3
        assert spec.topic_configs == {"retention.ms": "86400000"}

    @pytest.mark.parametrize(
        "name",
        ["simple", "with-hyphens", "with.dots", "with_underscores", "MiXeD.CaSe-123"],
    )
    def test_valid_name_variants(self, name: str) -> None:
        """Various valid topic name formats."""
        spec = TopicSpec(name=name)
        assert spec.name == name

    def test_valid_name_at_max_length(self) -> None:
        """Name exactly at max length is valid."""
        name = "a" * MAX_TOPIC_NAME_LENGTH
        spec = TopicSpec(name=name)
        assert len(spec.name) == MAX_TOPIC_NAME_LENGTH

    def test_invalid_empty_name(self) -> None:
        """Empty name raises ValueError."""
        with pytest.raises(ValueError, match="cannot be empty"):
            TopicSpec(name="")

    def test_invalid_whitespace_name(self) -> None:
        """Whitespace-only name raises ValueError."""
        with pytest.raises(ValueError, match="cannot be empty"):
            TopicSpec(name="   ")

    def test_invalid_name_too_long(self) -> None:
        """Name exceeding max length raises ValueError."""
        long_name = "a" * (MAX_TOPIC_NAME_LENGTH + 1)
        with pytest.raises(ValueError, match="exceeds"):
            TopicSpec(name=long_name)

    @pytest.mark.parametrize(
        "name",
        ["my topic", "path/slash", "at@sign", "hash#tag", "dollar$"],
    )
    def test_invalid_name_special_chars(self, name: str) -> None:
        """Names with invalid characters raise ValueError."""
        with pytest.raises(ValueError, match="invalid characters"):
            TopicSpec(name=name)

    def test_invalid_partitions_zero(self) -> None:
        """Zero partitions raises ValueError."""
        with pytest.raises(ValueError, match="num_partitions must be >= 1"):
            TopicSpec(name="valid", num_partitions=0)

    def test_invalid_partitions_negative(self) -> None:
        """Negative partitions raises ValueError."""
        with pytest.raises(ValueError, match="num_partitions must be >= 1"):
            TopicSpec(name="valid", num_partitions=-1)

    def test_invalid_replication_zero(self) -> None:
        """Zero replication factor raises ValueError."""
        with pytest.raises(ValueError, match="replication_factor must be >= 1"):
            TopicSpec(name="valid", replication_factor=0)

    def test_invalid_replication_negative(self) -> None:
        """Negative replication factor raises ValueError."""
        with pytest.raises(ValueError, match="replication_factor must be >= 1"):
            TopicSpec(name="valid", replication_factor=-1)

    def test_frozen_immutable(self) -> None:
        """TopicSpec is immutable (frozen dataclass)."""
        assert TopicSpec.__dataclass_params__.frozen

    def test_slots(self) -> None:
        """TopicSpec uses __slots__ for memory efficiency."""
        spec = TopicSpec(name="test")
        assert hasattr(spec, "__slots__")


class TestTopicDescription:
    """Tests for TopicDescription dataclass."""

    def test_creation(self) -> None:
        """TopicDescription stores name and partition count."""
        desc = TopicDescription(name="my-topic", num_partitions=6)
        assert desc.name == "my-topic"
        assert desc.num_partitions == 6

    def test_frozen_immutable(self) -> None:
        """TopicDescription is immutable."""
        assert TopicDescription.__dataclass_params__.frozen

    def test_slots(self) -> None:
        """TopicDescription uses __slots__."""
        desc = TopicDescription(name="test", num_partitions=1)
        assert hasattr(desc, "__slots__")


class TestEnsureTopicsResult:
    """Tests for EnsureTopicsResult dataclass."""

    def test_defaults_are_empty_tuples(self) -> None:
        """Default result has empty tuples for all fields."""
        result = EnsureTopicsResult()
        assert result.created == ()
        assert result.existing == ()
        assert result.warnings == ()

    def test_with_data(self) -> None:
        """Result with populated fields."""
        result = EnsureTopicsResult(
            created=("new-a", "new-b"),
            existing=("old-a",),
            warnings=("mismatch on old-a",),
        )
        assert len(result.created) == 2
        assert len(result.existing) == 1
        assert len(result.warnings) == 1

    def test_frozen_immutable(self) -> None:
        """EnsureTopicsResult is immutable."""
        assert EnsureTopicsResult.__dataclass_params__.frozen


class TestTopicNamePattern:
    """Tests for the TOPIC_NAME_PATTERN regex constant."""

    @pytest.mark.parametrize(
        "name",
        [
            "simple",
            "with-hyphens",
            "with.dots",
            "with_underscores",
            "MiXeD.CaSe-123",
            "a",
            "0",
        ],
    )
    def test_valid_names_match(self, name: str) -> None:
        """Valid topic names match the pattern."""
        assert TOPIC_NAME_PATTERN.match(name)

    @pytest.mark.parametrize(
        "name",
        ["with space", "with/slash", "with@at", ""],
    )
    def test_invalid_names_do_not_match(self, name: str) -> None:
        """Invalid topic names do not match the pattern."""
        assert not TOPIC_NAME_PATTERN.match(name)


class TestExceptionHierarchy:
    """Tests for admin exception inheritance chain."""

    def test_admin_error_inherits_kafka_client_error(self) -> None:
        """AdminError is a KafkaClientError."""
        assert issubclass(AdminError, KafkaClientError)

    def test_topic_already_exists_inherits_admin_error(self) -> None:
        """TopicAlreadyExistsError is an AdminError."""
        assert issubclass(TopicAlreadyExistsError, AdminError)

    def test_admin_error_catchable_as_kafka_client_error(self) -> None:
        """AdminError instances can be caught as KafkaClientError."""
        exc = AdminError("test")
        assert isinstance(exc, KafkaClientError)

    def test_topic_already_exists_catchable_as_admin_error(self) -> None:
        """TopicAlreadyExistsError instances can be caught as AdminError."""
        exc = TopicAlreadyExistsError("test")
        assert isinstance(exc, AdminError)

    def test_admin_error_details(self) -> None:
        """AdminError stores structured details."""
        exc = AdminError("failed", details={"topic": "my-topic", "code": 36})
        assert str(exc) == "failed"
        assert exc.details == {"topic": "my-topic", "code": 36}

    def test_admin_error_default_details_empty(self) -> None:
        """AdminError without details has empty dict."""
        exc = AdminError("test")
        assert exc.details == {}
