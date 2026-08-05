import json
from dataclasses import FrozenInstanceError
from uuid import UUID

import pytest
from bff_service.sse.events import (
    SSE_EVENT_COMMAND_STATUS,
    SSE_EVENT_DOCUMENT_STATUS,
    CommandStatusPayload,
    DocumentStatusPayload,
    build_stream_name,
)


def test_to_sse_data_returns_valid_json_with_all_fields() -> None:
    payload = DocumentStatusPayload(
        type=SSE_EVENT_DOCUMENT_STATUS,
        request_id="abc-123",
        status="completed",
        storage_key="docs/output.pdf",
        file_size=1024,
        content_hash="deadbeef",
        error_message=None,
    )
    data = payload.to_sse_data()
    parsed = json.loads(data)

    assert parsed["type"] == SSE_EVENT_DOCUMENT_STATUS
    assert parsed["request_id"] == "abc-123"
    assert parsed["status"] == "completed"
    assert parsed["storage_key"] == "docs/output.pdf"
    assert parsed["file_size"] == 1024
    assert parsed["content_hash"] == "deadbeef"
    assert parsed["error_message"] is None


def test_command_status_payload_has_distinct_contract() -> None:
    payload = CommandStatusPayload(
        type=SSE_EVENT_COMMAND_STATUS,
        request_id="command-123",
        command_type="update_profile",
        status="failed",
        error_message="Enrichment failed",
    )

    assert json.loads(payload.to_sse_data()) == {
        "type": "command_status",
        "request_id": "command-123",
        "status": "failed",
        "command_type": "update_profile",
        "error_message": "Enrichment failed",
    }
    assert not isinstance(payload, DocumentStatusPayload)


def test_build_stream_name_scopes_user_and_request() -> None:
    user_id = UUID("12345678-1234-5678-1234-567812345678")
    assert build_stream_name(user_id, "request-123") == (
        "sse:document:12345678-1234-5678-1234-567812345678:request-123"
    )


def test_frozen_immutability_raises_on_assignment() -> None:
    payload = DocumentStatusPayload(
        type=SSE_EVENT_DOCUMENT_STATUS,
        request_id="abc-123",
        status="pending",
    )
    with pytest.raises(FrozenInstanceError):
        type(payload).__setattr__(payload, "status", "completed")


def test_none_optional_fields_are_serialized() -> None:
    payload = DocumentStatusPayload(
        type=SSE_EVENT_DOCUMENT_STATUS,
        request_id="abc-123",
        status="failed",
        error_message="LLM timeout",
    )
    parsed = json.loads(payload.to_sse_data())

    assert parsed["storage_key"] is None
    assert parsed["file_size"] is None
    assert parsed["content_hash"] is None
    assert parsed["error_message"] == "LLM timeout"


def test_sse_event_constant_values() -> None:
    assert SSE_EVENT_DOCUMENT_STATUS == "document_status"
    assert SSE_EVENT_COMMAND_STATUS == "command_status"
