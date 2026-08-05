"""SSE event types and payload definitions."""

import json
from dataclasses import asdict, dataclass
from uuid import UUID

SSE_EVENT_DOCUMENT_STATUS = "document_status"
SSE_EVENT_COMMAND_STATUS = "command_status"


@dataclass(frozen=True, slots=True)
class CommandStatusPayload:
    """SSE payload for an asynchronously tracked command status."""

    type: str
    request_id: str
    status: str
    command_type: str | None = None
    error_message: str | None = None

    def to_sse_data(self) -> str:
        """Serialize the command status payload for SSE."""
        return json.dumps(asdict(self))


@dataclass(frozen=True, slots=True)
class DocumentStatusPayload:
    """SSE payload for document generation status transitions.

    Carries only the status transition data needed by the frontend,
    not full document metadata. The `type` field allows future
    multiplexing of additional event types over a single SSE stream.

    Attributes:
        type: The SSE event type discriminator (e.g., "document_status").
        request_id: UUID as string identifying the document generation request.
        status: Current status (one of: pending, in_progress, completed, failed).
        storage_key: S3 key for the generated document, set on completion.
        error_message: Human-readable error description, set on failure.
        file_size: Byte size of the generated document, set on completion.
        content_hash: SHA-256 content hash, set on completion.
    """

    type: str
    request_id: str
    status: str
    storage_key: str | None = None
    error_message: str | None = None
    file_size: int | None = None
    content_hash: str | None = None

    def to_sse_data(self) -> str:
        """Serialize payload to a JSON string for SSE data field.

        Returns:
            JSON-encoded string of all payload fields.
        """
        return json.dumps(asdict(self))


def build_stream_name(user_id: UUID, request_id: str) -> str:
    """Build the request-scoped Redis Stream key."""
    return f"sse:document:{user_id}:{request_id}"
