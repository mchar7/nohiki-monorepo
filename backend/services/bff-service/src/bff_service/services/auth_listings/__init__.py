"""Auth-listings feature module: serves decorative job listings on the auth page."""

from bff_service.services.auth_listings.service import compile_auth_listings

__all__ = ["compile_auth_listings"]
