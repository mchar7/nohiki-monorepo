"""Unit tests for review-status and source-name mapping helpers."""

from __future__ import annotations

import pytest
from nohiki.skill.v1 import ReviewStatus, SkillSource
from nohiki_common_exceptions import ValidationError
from skill_graph_service.events.publishers import (
    _map_review_status,
    _map_source,
)


class TestMapReviewStatus:
    """Tests for ``_map_review_status``."""

    def test_maps_pending(self) -> None:
        assert _map_review_status("pending") == ReviewStatus.PENDING

    def test_maps_approved(self) -> None:
        assert _map_review_status("approved") == ReviewStatus.APPROVED

    def test_raises_on_unknown_value(self) -> None:
        with pytest.raises(ValidationError) as exc_info:
            _map_review_status("not_a_real_status")
        assert exc_info.value.field_name == "review_status"
        assert exc_info.value.invalid_value == "not_a_real_status"


class TestMapSource:
    """Tests for ``_map_source``."""

    def test_none_maps_to_unspecified(self) -> None:
        assert _map_source(None) == SkillSource.UNSPECIFIED

    def test_maps_known_source(self) -> None:
        assert _map_source("tabiya") == SkillSource.TABIYA

    def test_raises_on_unknown_value(self) -> None:
        with pytest.raises(ValidationError) as exc_info:
            _map_source("not_a_real_source")
        assert exc_info.value.field_name == "source_name"
        assert exc_info.value.invalid_value == "not_a_real_source"
