"""Tests for doc_process_service.events.types module."""

from __future__ import annotations

import dataclasses

import pytest
from doc_process_service.events.types import ProcessingParams
from nohiki.common.v1 import CommandHeader
from nohiki.doc.process.v1 import ProcessingLevel

_DEFAULT_CMD = CommandHeader(operation_id="req-123", callback_topic="my-callback")
_DEFAULT_PARAMS = ProcessingParams(
    command=_DEFAULT_CMD,
    storage_key="s3://bucket/key",
    content_id="content-456",
    processing_level=ProcessingLevel.BASIC,
    correlation_id="corr-789",
)


class TestProcessingParams:
    """Tests for ProcessingParams dataclass."""

    def test_create_minimal(self) -> None:
        """ProcessingParams stores all provided fields correctly."""
        cmd = CommandHeader(operation_id="req-123", callback_topic="my-callback")
        params = ProcessingParams(
            command=cmd,
            storage_key="s3://bucket/key",
            content_id="content-456",
            processing_level=ProcessingLevel.BASIC,
            correlation_id="corr-789",
        )

        assert params.command is cmd
        assert params.storage_key == "s3://bucket/key"
        assert params.content_id == "content-456"
        assert params.processing_level == ProcessingLevel.BASIC
        assert params.correlation_id == "corr-789"

    def test_command_fields_accessible(self) -> None:
        """command.operation_id, callback_topic, caller_context, and attributes are accessible."""
        cmd = CommandHeader(
            operation_id="op-999",
            callback_topic="cb-topic",
            caller_context=b"ctx",
            attributes={"k": "v"},
        )
        params = ProcessingParams(
            command=cmd,
            storage_key="s3://bucket/key",
            content_id="content-456",
            processing_level=ProcessingLevel.BASIC,
            correlation_id="corr-789",
        )

        assert params.command.operation_id == "op-999"
        assert params.command.callback_topic == "cb-topic"
        assert params.command.caller_context == b"ctx"
        assert params.command.attributes == {"k": "v"}

    def test_is_frozen_dataclass(self) -> None:
        """ProcessingParams is a frozen dataclass."""
        assert dataclasses.is_dataclass(ProcessingParams)
        dc_params = getattr(ProcessingParams, "__dataclass_params__", None)
        assert dc_params is not None
        assert dc_params.frozen is True

    def test_not_hashable_due_to_command_header(self) -> None:
        """ProcessingParams is not hashable because CommandHeader is not hashable."""
        with pytest.raises(TypeError, match="unhashable"):
            hash(_DEFAULT_PARAMS)

    def test_equality(self) -> None:
        """Two ProcessingParams with identical fields are equal."""
        cmd = CommandHeader(operation_id="req-123", callback_topic="my-callback")
        params1 = ProcessingParams(
            command=cmd,
            storage_key="s3://bucket/key",
            content_id="content-456",
            processing_level=ProcessingLevel.TABLES,
            correlation_id="corr-789",
        )
        params2 = ProcessingParams(
            command=cmd,
            storage_key="s3://bucket/key",
            content_id="content-456",
            processing_level=ProcessingLevel.TABLES,
            correlation_id="corr-789",
        )

        assert params1 == params2

    def test_inequality(self) -> None:
        """ProcessingParams with different storage keys are not equal."""
        cmd = CommandHeader(operation_id="req-123", callback_topic="my-callback")
        params1 = ProcessingParams(
            command=cmd,
            storage_key="s3://bucket/a",
            content_id="content-456",
            processing_level=ProcessingLevel.BASIC,
            correlation_id="corr-789",
        )
        params2 = ProcessingParams(
            command=cmd,
            storage_key="s3://bucket/b",
            content_id="content-456",
            processing_level=ProcessingLevel.BASIC,
            correlation_id="corr-789",
        )

        assert params1 != params2

    @pytest.mark.parametrize(
        "level",
        [
            ProcessingLevel.BASIC,
            ProcessingLevel.TABLES,
            ProcessingLevel.OCR,
            ProcessingLevel.IMAGES,
            ProcessingLevel.FULL,
        ],
    )
    def test_all_processing_levels(self, level: ProcessingLevel) -> None:
        """ProcessingParams accepts all valid processing levels."""
        params = ProcessingParams(
            command=_DEFAULT_CMD,
            storage_key="s3://bucket/key",
            content_id="content-456",
            processing_level=level,
            correlation_id="corr-789",
        )

        assert params.processing_level == level
