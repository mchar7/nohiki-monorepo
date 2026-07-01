"""Shared command response schemas used across BFF routers."""

from pydantic import BaseModel, ConfigDict, Field


class CommandAcceptedResponse(BaseModel):
    """Response indicating an async command has been accepted for processing.

    Returned by endpoints that publish Kafka commands rather than
    returning results synchronously.
    """

    model_config = ConfigDict(extra="forbid")

    request_id: str = Field(description="UUID for tracking command completion")
    status: str = Field(default="accepted", description="Command acceptance status")
