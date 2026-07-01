"""Auth-listings router: unauthenticated endpoint for decorative job cards."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from bff_service.api.deps.auth_secret import validate_auth_secret
from bff_service.api.deps.rate_limit import rate_limit_auth_listings
from bff_service.core.config import Settings, get_settings
from bff_service.core.db import get_async_db
from bff_service.services.auth_listings import compile_auth_listings
from bff_service.services.auth_listings.schemas import AuthListingsResponse

router = APIRouter()


@router.get(
    "/",
    response_model=AuthListingsResponse,
    dependencies=[
        # Secret check first so an anonymous flood cannot drain the bucket
        # and lock out the legitimate Worker.
        Depends(validate_auth_secret),
        Depends(rate_limit_auth_listings),
    ],
)
async def get_auth_listings(
    db: Annotated[AsyncSession, Depends(get_async_db)],
    settings: Annotated[Settings, Depends(get_settings)],
    country: Annotated[str, Query(pattern=r"^[A-Z]{3}$")],
    _lat: Annotated[float | None, Query(alias="lat")] = None,
    _lon: Annotated[float | None, Query(alias="lon")] = None,
    lang: Annotated[str | None, Query()] = None,
) -> AuthListingsResponse:
    """Serve weighted, diversity-filtered job listings for the auth page.

    Args:
        db: Async database session.
        settings: Application settings.
        country: ISO 3166-1 alpha-3 country code (3 uppercase letters).
        _lat: Latitude (accepted for forward compatibility, unused in v1).
        _lon: Longitude (accepted for forward compatibility, unused in v1).
        lang: Language preference for weighting.

    Returns:
        Geo-targeted, diversity-filtered job listings.
    """
    return await compile_auth_listings(
        db=db,
        country_code=country,
        user_language=lang,
        settings=settings.auth_listings,
    )
