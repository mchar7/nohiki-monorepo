"""Type definitions for event processing."""

from __future__ import annotations

from dataclasses import dataclass

from nohiki.common.v1 import CommandHeader
from nohiki.doc.process.v1 import ProcessingLevel


@dataclass(frozen=True, slots=True)
class ProcessingParams:
    """Parameters extracted from a processing request for use across handler and publishers.

    Stores the original CommandHeader directly so publishers can call
    callback_from_command() without reconstructing it from scalar copies.
    """

    command: CommandHeader
    storage_key: str
    content_id: str
    processing_level: ProcessingLevel
    correlation_id: str
