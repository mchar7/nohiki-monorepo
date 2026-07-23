"""Tests for the Kafka client's package-level lazy exports."""

from __future__ import annotations

import importlib
import sys


def test_admin_and_health_exports_load_on_first_use() -> None:
    """Keep admin and FastAPI health modules out of the plain root import."""
    saved_modules = {name: module for name, module in sys.modules.items() if name.startswith("nohiki_kafka_client")}
    try:
        for name in saved_modules:
            sys.modules.pop(name, None)

        kafka_client = importlib.import_module("nohiki_kafka_client")

        assert "nohiki_kafka_client.admin" not in sys.modules
        assert "nohiki_kafka_client.observability.health" not in sys.modules

        assert kafka_client.KafkaAdmin.__name__ == "KafkaAdmin"
        assert "nohiki_kafka_client.admin" in sys.modules

        assert kafka_client.KafkaHealthProbe.__name__ == "KafkaHealthProbe"
        assert "nohiki_kafka_client.observability.health" in sys.modules
    finally:
        loaded_modules = [name for name in sys.modules if name.startswith("nohiki_kafka_client")]
        for name in loaded_modules:
            del sys.modules[name]
        sys.modules.update(saved_modules)
