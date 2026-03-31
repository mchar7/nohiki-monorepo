"""Tests for BetterprotoEnumAdapter and betterproto2 enum Pydantic integration."""

from __future__ import annotations

from typing import Annotated

import pytest
from nohiki.common.v1 import CountryCode, PaymentFrequency, SeniorityLevel, WorkArrangement
from nohiki_domain_utils import BetterprotoEnumAdapter
from nohiki_domain_utils.enum_adapter import (
    UNSPECIFIED_ENUM_VALUE,
    _extract_enum_description,
    _get_enum_members,
    _normalize_enum_name,
    parse_enum_string,
)
from pydantic import BaseModel, Field, TypeAdapter, ValidationError


class LocationModel(BaseModel):
    """Test model with country code enum."""

    country: Annotated[CountryCode, BetterprotoEnumAdapter(exclude_unspecified=False)]


class JobModel(BaseModel):
    """Test model with multiple enum fields."""

    seniority: Annotated[SeniorityLevel, BetterprotoEnumAdapter(exclude_unspecified=True)]
    arrangement: Annotated[WorkArrangement, BetterprotoEnumAdapter(exclude_unspecified=False)]


class TestInternalUtilities:
    """Test internal utility functions for correctness and edge cases."""

    def test_normalize_strips_and_uppercases(self) -> None:
        """Normalization should strip, uppercase, and replace separators."""
        assert _normalize_enum_name("  on-site  ") == "ON_SITE"
        assert _normalize_enum_name("hybrid") == "HYBRID"
        assert _normalize_enum_name("ON SITE") == "ON_SITE"
        assert _normalize_enum_name("REMOTE") == "REMOTE"

    def test_get_members_excludes_unspecified(self) -> None:
        """Filtering should remove value=0 members when excluded."""
        all_members = _get_enum_members(WorkArrangement, exclude_unspecified=False)
        filtered = _get_enum_members(WorkArrangement, exclude_unspecified=True)

        assert any(m.value == UNSPECIFIED_ENUM_VALUE for m in all_members)
        assert all(m.value != UNSPECIFIED_ENUM_VALUE for m in filtered)
        assert len(filtered) < len(all_members)

    def test_get_members_includes_all_when_not_excluded(self) -> None:
        """All members should be returned when exclude_unspecified=False."""
        members = _get_enum_members(SeniorityLevel, exclude_unspecified=False)
        assert len(members) == len(list(SeniorityLevel))

    def test_extract_description_strips_separators(self) -> None:
        """Description extraction should strip betterproto2 box-drawing lines."""
        desc = _extract_enum_description(WorkArrangement)
        assert "═" not in desc
        assert len(desc) > 0

    def test_parse_enum_string_valid(self) -> None:
        """Valid string should parse to enum member."""
        assert parse_enum_string(WorkArrangement, "REMOTE") == WorkArrangement.REMOTE
        assert parse_enum_string(WorkArrangement, "on-site") == WorkArrangement.ON_SITE

    def test_parse_enum_string_invalid_raises(self) -> None:
        """Invalid string should raise ValueError with valid options."""
        with pytest.raises(ValueError, match="Invalid WorkArrangement"):
            parse_enum_string(WorkArrangement, "TELEPORT")

    def test_extract_description_fallback(self) -> None:
        """Falls back to class name when docstring is empty."""
        original_doc = WorkArrangement.__doc__
        try:
            WorkArrangement.__doc__ = ""
            assert _extract_enum_description(WorkArrangement) == "WorkArrangement"
        finally:
            WorkArrangement.__doc__ = original_doc


class TestEnumValidation:
    """Test enum validation from various input types."""

    def test_string_exact_match(self) -> None:
        """String with exact enum name should validate."""
        model = LocationModel(country="USA")
        assert model.country == CountryCode.USA

    def test_string_case_insensitive(self) -> None:
        """String with different casing should validate."""
        model = LocationModel(country="usa")
        assert model.country == CountryCode.USA

        model2 = LocationModel(country="Usa")
        assert model2.country == CountryCode.USA

    def test_string_with_hyphens(self) -> None:
        """Hyphens should be normalized to underscores."""
        model = JobModel(seniority="SENIOR", arrangement="on-site")
        assert model.arrangement == WorkArrangement.ON_SITE

    def test_int_value(self) -> None:
        """Integer enum value should validate."""
        model = LocationModel(country=CountryCode.USA.value)
        assert model.country == CountryCode.USA

    def test_enum_passthrough(self) -> None:
        """Enum instance should pass through unchanged."""
        model = LocationModel(country=CountryCode.CAN)
        assert model.country == CountryCode.CAN

    def test_unspecified_allowed(self) -> None:
        """UNSPECIFIED should be allowed when exclude_unspecified=False."""
        model = LocationModel(country="UNSPECIFIED")
        assert model.country == CountryCode.UNSPECIFIED

        model2 = LocationModel(country=0)
        assert model2.country == CountryCode.UNSPECIFIED

    def test_invalid_string_raises(self) -> None:
        """Invalid string should raise ValidationError."""
        with pytest.raises(ValidationError):
            LocationModel(country="INVALID_COUNTRY")

    def test_invalid_type_raises(self) -> None:
        """Invalid type should raise ValidationError."""
        invalid_value: object = 12.5
        with pytest.raises(ValidationError):
            LocationModel(country=invalid_value)

    def test_invalid_int_value_raises(self) -> None:
        """Out-of-range integer should raise ValidationError."""
        with pytest.raises(ValidationError):
            LocationModel(country=99999)


class TestEnumSerialization:
    """Test enum serialization to JSON."""

    def test_serialize_to_string_name(self) -> None:
        """Enum should serialize to string name."""
        model = LocationModel(country=CountryCode.GBR)
        data = model.model_dump()
        assert data["country"] == "GBR"

    def test_serialize_json(self) -> None:
        """Enum should serialize to string in JSON."""
        model = LocationModel(country=CountryCode.DEU)
        json_str = model.model_dump_json()
        assert '"DEU"' in json_str

    def test_roundtrip(self) -> None:
        """Model should roundtrip through JSON."""
        original = LocationModel(country=CountryCode.AUS)
        json_str = original.model_dump_json()
        restored = LocationModel.model_validate_json(json_str)
        assert restored.country == original.country


class TestMultipleEnums:
    """Test model with multiple enum fields."""

    def test_multiple_enums_validate(self) -> None:
        """Multiple enum fields should validate independently."""
        model = JobModel(seniority="SENIOR", arrangement="REMOTE")
        assert model.seniority == SeniorityLevel.SENIOR
        assert model.arrangement == WorkArrangement.REMOTE

    def test_mixed_input_types(self) -> None:
        """Different input types for different fields should work."""
        model = JobModel(seniority=SeniorityLevel.MID, arrangement="hybrid")
        assert model.seniority == SeniorityLevel.MID
        assert model.arrangement == WorkArrangement.HYBRID

    def test_json_roundtrip_multiple(self) -> None:
        """Multiple enums should roundtrip through JSON."""
        original = JobModel(seniority="STAFF", arrangement="ON_SITE")
        json_str = original.model_dump_json()
        restored = JobModel.model_validate_json(json_str)
        assert restored.seniority == original.seniority
        assert restored.arrangement == original.arrangement


class TestJsonSchema:
    """Test JSON schema generation."""

    def test_schema_has_enum_values(self) -> None:
        """Schema should list valid enum values in standalone definition."""
        schema = LocationModel.model_json_schema()
        defs = schema.get("$defs", {})
        country_def = next(d for d in defs.values() if "USA" in d.get("enum", []))
        assert "USA" in country_def["enum"]
        assert "CAN" in country_def["enum"]

    def test_schema_type_is_string(self) -> None:
        """Standalone definition type should be string."""
        schema = LocationModel.model_json_schema()
        defs = schema.get("$defs", {})
        country_def = next(d for d in defs.values() if "USA" in d.get("enum", []))
        assert country_def["type"] == "string"


class TestRefBasedSchemaGeneration:
    """Test that schemas produce $ref pointers and correct standalone definitions."""

    def test_model_schema_uses_ref(self) -> None:
        """Inline properties should use $ref to standalone definitions."""
        schema = JobModel.model_json_schema()
        seniority_prop = schema["properties"]["seniority"]
        assert "$ref" in seniority_prop
        assert seniority_prop["$ref"].endswith("/SeniorityLevel")

    def test_standalone_definition_has_string_enum(self) -> None:
        """Standalone definition should have type=string and enum names."""
        schema = JobModel.model_json_schema()
        defs = schema.get("$defs", {})
        assert "SeniorityLevel" in defs
        sl_def = defs["SeniorityLevel"]
        assert sl_def["type"] == "string"
        assert "SENIOR" in sl_def["enum"]
        assert all(not v.endswith("UNSPECIFIED") for v in sl_def["enum"])

    def test_list_field_items_use_ref(self) -> None:
        """List[Annotated[Enum, Adapter]] items should use $ref."""

        class ListModel(BaseModel):
            items: list[Annotated[WorkArrangement, BetterprotoEnumAdapter()]]

        schema = ListModel.model_json_schema()
        items_schema = schema["properties"]["items"]["items"]
        assert "$ref" in items_schema

    def test_exclude_unspecified_false_includes_zero_member(self) -> None:
        """When exclude_unspecified=False, the UNSPECIFIED member is included."""
        schema = LocationModel.model_json_schema()
        defs = schema.get("$defs", {})
        country_def = next(d for d in defs.values() if "USA" in d.get("enum", []))
        assert "UNSPECIFIED" in country_def["enum"]

    def test_shared_ref_for_same_enum(self) -> None:
        """Multiple fields using the same enum should share one $ref definition."""

        class MultiModel(BaseModel):
            a: Annotated[WorkArrangement, BetterprotoEnumAdapter()]
            b: Annotated[WorkArrangement, BetterprotoEnumAdapter()]

        schema = MultiModel.model_json_schema()
        a_prop = schema["properties"]["a"]
        b_prop = schema["properties"]["b"]
        assert "$ref" in a_prop
        assert "$ref" in b_prop
        assert a_prop["$ref"] == b_prop["$ref"]


class TestUnspecifiedEnforcement:
    """Test validation-time enforcement of exclude_unspecified."""

    def test_unspecified_rejected_by_int_when_excluded(self) -> None:
        """Value 0 should be rejected when exclude_unspecified=True."""
        with pytest.raises(ValidationError):
            JobModel(seniority=0, arrangement="REMOTE")

    def test_unspecified_rejected_by_name_when_excluded(self) -> None:
        """UNSPECIFIED name should be rejected when exclude_unspecified=True."""
        with pytest.raises(ValidationError):
            JobModel(seniority="SENIORITY_LEVEL_UNSPECIFIED", arrangement="REMOTE")

    def test_unspecified_enum_instance_rejected_when_excluded(self) -> None:
        """Passing the actual UNSPECIFIED enum instance should be rejected."""
        with pytest.raises(ValidationError):
            JobModel(seniority=SeniorityLevel.UNSPECIFIED, arrangement="REMOTE")

    def test_unspecified_accepted_when_not_excluded(self) -> None:
        """UNSPECIFIED should be accepted when exclude_unspecified=False."""
        model = JobModel(seniority="SENIOR", arrangement=0)
        assert model.arrangement.value == UNSPECIFIED_ENUM_VALUE


class TestSafetyNet:
    """Test the betterproto2.Enum.__get_pydantic_core_schema__ safety net."""

    def test_raw_enum_schema_is_string_type(self) -> None:
        """Raw enum (no adapter) should produce string-based JSON schema."""
        ta = TypeAdapter(WorkArrangement)
        schema = ta.json_schema()
        assert schema["type"] == "string"
        assert "ON_SITE" in schema["enum"]
        assert "HYBRID" in schema["enum"]
        assert "REMOTE" in schema["enum"]

    def test_raw_enum_excludes_unspecified_by_default(self) -> None:
        """Safety net uses exclude_unspecified=True by default."""
        ta = TypeAdapter(SeniorityLevel)
        schema = ta.json_schema()
        enum_values = schema["enum"]
        assert all(not v.endswith("UNSPECIFIED") for v in enum_values)

    def test_raw_enum_serializes_as_string(self) -> None:
        """Raw enum should serialize to string name, not integer value."""
        ta = TypeAdapter(WorkArrangement)
        result = ta.dump_python(WorkArrangement.REMOTE, mode="json")
        assert result == "REMOTE"

    def test_raw_enum_serializes_all_members_as_strings(self) -> None:
        """All enum members should serialize to their string names."""
        ta = TypeAdapter(PaymentFrequency)
        assert ta.dump_python(PaymentFrequency.ANNUALLY, mode="json") == "ANNUALLY"
        assert ta.dump_python(PaymentFrequency.MONTHLY, mode="json") == "MONTHLY"
        assert ta.dump_python(PaymentFrequency.HOURLY, mode="json") == "HOURLY"


class TestDefaultValueEncoding:
    """Test that enum field defaults are serialized as strings in JSON schema."""

    def test_field_default_is_string_in_schema(self) -> None:
        """Field with enum default should show string name, not integer."""

        class DefaultModel(BaseModel):
            freq: Annotated[PaymentFrequency, BetterprotoEnumAdapter()] = Field(
                default=PaymentFrequency.ANNUALLY,
            )

        schema = DefaultModel.model_json_schema()
        freq_prop = schema["properties"]["freq"]
        assert freq_prop["default"] == "ANNUALLY"

    def test_assignment_default_is_string_in_schema(self) -> None:
        """Assignment-style default should also show string name."""

        class DefaultModel(BaseModel):
            freq: Annotated[PaymentFrequency, BetterprotoEnumAdapter()] = PaymentFrequency.MONTHLY

        schema = DefaultModel.model_json_schema()
        freq_prop = schema["properties"]["freq"]
        assert freq_prop["default"] == "MONTHLY"

    def test_default_is_not_integer(self) -> None:
        """Default must never be the integer protobuf value."""

        class DefaultModel(BaseModel):
            freq: Annotated[PaymentFrequency, BetterprotoEnumAdapter()] = PaymentFrequency.ANNUALLY

        schema = DefaultModel.model_json_schema()
        freq_prop = schema["properties"]["freq"]
        assert not isinstance(freq_prop["default"], int)
