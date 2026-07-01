"""Shared API schemas for BFF service routers."""

from bff_service.api.schemas.commands import CommandAcceptedResponse
from bff_service.api.schemas.listings import JobListingResponse

__all__ = ["CommandAcceptedResponse", "JobListingResponse"]
