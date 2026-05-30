"""Immutable spec dataclasses validated at construction.

A :class:`ServiceSpec` or :class:`LibSpec` represents a fully-resolved
decision tree for what the scaffolder will produce. All cross-field
consistency rules are enforced in ``__post_init__`` so that any
``ScaffoldError`` subclass raised during rendering or workspace editing
can assume a valid spec.
"""

from __future__ import annotations

from .database import DatabaseOptions
from .kafka import KafkaOptions
from .lib import LibSpec
from .llm import LLMOptions
from .ml import MLOptions
from .qdrant import QdrantEntity, QdrantOptions
from .redis import RedisOptions
from .s3 import S3Options
from .service import ServiceSpec

__all__ = [
    "DatabaseOptions",
    "KafkaOptions",
    "LLMOptions",
    "LibSpec",
    "MLOptions",
    "QdrantEntity",
    "QdrantOptions",
    "RedisOptions",
    "S3Options",
    "ServiceSpec",
]
