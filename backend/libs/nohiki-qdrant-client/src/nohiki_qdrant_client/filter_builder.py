"""Qdrant filter builder for constructing query filters."""

from __future__ import annotations

from datetime import datetime

from qdrant_client import models

# Type alias for filter values
type FilterValue = bool | str | int | float | list[str | int | float] | dict[str, str | int | float | datetime] | None


def build_filter(filters: dict[str, FilterValue]) -> models.Filter:
    """Build Qdrant filter from a dictionary of filter conditions.

    Supports:
        - Boolean values: exact match
        - String/int/float values: exact match
        - Lists: MatchAny (any value in list)
        - Dicts with operators: {"$gt": value}, {"$lt": value}, {"$gte": value}, {"$lte": value}
        - Range dicts: {"$gte": min, "$lte": max}

    Args:
        filters: Dictionary of field -> value/condition pairs

    Returns:
        Qdrant Filter object

    Examples:
        >>> build_filter({"is_active": True, "job_type": "full_time"})
        >>> build_filter({"company": ["Google", "Meta", "Apple"]})
        >>> build_filter({"posted_at": {"$gte": datetime(2024, 1, 1)}})

    """
    conditions = []

    for key, value in filters.items():
        condition = _build_condition(key, value)
        if condition is not None:
            conditions.append(condition)

    return models.Filter(must=conditions)


def build_filter_with_should(
    must_filters: dict[str, FilterValue] | None = None,
    should_filters: list[dict[str, FilterValue]] | None = None,
    must_not_filters: dict[str, FilterValue] | None = None,
) -> models.Filter:
    """Build complex Qdrant filter with must, should, and must_not conditions.

    Args:
        must_filters: Conditions that MUST all match
        should_filters: Conditions where at least one SHOULD match
        must_not_filters: Conditions that MUST NOT match

    Returns:
        Qdrant Filter object

    """
    must_conditions = _extract_conditions(must_filters) if must_filters else []
    should_conditions = _extract_conditions_from_list(should_filters) if should_filters else []
    must_not_conditions = _extract_conditions(must_not_filters) if must_not_filters else []

    return models.Filter(
        must=must_conditions or None,
        should=should_conditions or None,
        must_not=must_not_conditions or None,
    )


def _extract_conditions(filters: dict[str, FilterValue]) -> list[models.Condition]:
    """Extract conditions from a filter dict."""
    return [c for key, val in filters.items() if (c := _build_condition(key, val)) is not None]


def _extract_conditions_from_list(filter_list: list[dict[str, FilterValue]]) -> list[models.Condition]:
    """Extract conditions from a list of filter dicts."""
    conditions = []
    for filter_dict in filter_list:
        conditions.extend(_extract_conditions(filter_dict))
    return conditions


def _build_condition(key: str, value: FilterValue) -> models.Condition | None:
    """Build a single Qdrant condition from a key-value pair."""
    match value:
        case None:
            return None
        case dict():
            return _build_range_condition(key, value)
        case bool() | str() | int():
            return models.FieldCondition(key=key, match=models.MatchValue(value=value))
        case float():
            return models.FieldCondition(key=key, match=models.MatchValue(value=int(value)))
        case list() if value:
            return models.FieldCondition(key=key, match=models.MatchAny(any=[str(v) for v in value]))
    return None


def _build_range_condition(
    key: str,
    operators: dict[str, str | int | float | datetime] | None,
) -> models.FieldCondition | None:
    """Build a range condition from operator dict."""
    if not operators:
        return None

    op_mapping = {"$gt": "gt", "$gte": "gte", "$lt": "lt", "$lte": "lte"}
    range_params: dict[str, float | None] = {}

    for op, val in operators.items():
        if op not in op_mapping:
            continue
        try:
            if isinstance(val, datetime):
                range_params[op_mapping[op]] = val.timestamp()
            else:
                range_params[op_mapping[op]] = float(val)
        except ValueError, TypeError:
            continue

    return models.FieldCondition(key=key, range=models.Range(**range_params)) if range_params else None
