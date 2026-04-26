"""Common base models for user-auth-service API schemas."""

from pydantic import BaseModel


class StrictBaseModel(BaseModel):
    """Base model with strict validation configuration."""

    model_config = {
        "validate_assignment": True,
        "extra": "forbid",
        "str_strip_whitespace": True,
        "from_attributes": True,
    }
