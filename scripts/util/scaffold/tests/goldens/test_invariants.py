"""Semantic invariant assertions for scaffolded archetypes.

Each test renders a canonical archetype spec and asserts on the resulting
content. We check patterns, not bytes — a template can be reformatted or
have comments reworded without breaking these, but mixin order, lifespan
shutdown sequence, required imports, canonical build stanza, and similar
load-bearing patterns are locked in.
"""

from __future__ import annotations

import tomllib
from typing import cast

from ci_checks.checks.build_backend import BackendStatus, _classify

from .conftest import render
from .factories import (
    http_and_kafka_ml,
    http_only_producer,
    kafka_only_consumer,
    kafka_only_producer,
    lib_with_testing,
    namespace_lib,
    plain_lib,
)


def _parse(content: str) -> dict[str, object]:
    """Parse a TOML string into a dict."""
    return tomllib.loads(content)


class TestCanonicalBuildBackend:
    """Every scaffolded pyproject must classify as CANONICAL uv_build."""

    def test_kafka_only_consumer_is_canonical(self) -> None:
        rendered = render(kafka_only_consumer())
        pyproject = rendered["backend/services/demo-consumer-service/pyproject.toml"]
        status, backend, issues = _classify(_parse(pyproject))
        assert status == BackendStatus.CANONICAL, (backend, issues)

    def test_http_only_is_canonical(self) -> None:
        rendered = render(http_only_producer())
        pyproject = rendered["backend/services/demo-auth-service/pyproject.toml"]
        status, _, issues = _classify(_parse(pyproject))
        assert status == BackendStatus.CANONICAL, issues

    def test_ml_heavy_is_canonical(self) -> None:
        rendered = render(http_and_kafka_ml())
        pyproject = rendered["backend/services/demo-scorer-service/pyproject.toml"]
        status, _, issues = _classify(_parse(pyproject))
        assert status == BackendStatus.CANONICAL, issues

    def test_plain_lib_is_canonical(self) -> None:
        rendered = render(plain_lib())
        pyproject = rendered["backend/libs/nohiki-demo-utils/pyproject.toml"]
        status, _, issues = _classify(_parse(pyproject))
        assert status == BackendStatus.CANONICAL, issues

    def test_namespace_lib_is_canonical(self) -> None:
        rendered = render(namespace_lib())
        pyproject = rendered["backend/libs/nohiki-demo-models/pyproject.toml"]
        status, _, issues = _classify(_parse(pyproject))
        assert status == BackendStatus.CANONICAL, issues

    def test_lib_with_testing_is_canonical(self) -> None:
        rendered = render(lib_with_testing())
        pyproject = rendered["backend/libs/nohiki-demo-test-utils/pyproject.toml"]
        status, _, issues = _classify(_parse(pyproject))
        assert status == BackendStatus.CANONICAL, issues


class TestKafkaOnlyConsumer:
    def setup_method(self) -> None:
        self.rendered = render(kafka_only_consumer())
        self.main = self.rendered["backend/services/demo-consumer-service/src/demo_consumer_service/main.py"]
        self.config = self.rendered["backend/services/demo-consumer-service/src/demo_consumer_service/core/config.py"]

    def test_settings_mixin_order_has_base_last(self) -> None:
        """NohikiBaseSettings MUST be the rightmost mixin in the Settings class."""
        lines = self.config.splitlines()
        in_class = False
        class_body = []

        for line in lines:
            if line.startswith("class Settings("):
                in_class = True
                class_body.append(line)
            elif in_class:
                class_body.append(line)
                if "):" in line:
                    break

        if not class_body:
            msg = "class Settings(...) not found"
            raise AssertionError(msg)

        full_def = " ".join(class_body)
        bases_str = full_def.split("(", 1)[1].split("):", 1)[0]
        bases = [b.strip() for b in bases_str.split(",")]
        bases = [b for b in bases if b]

        assert bases[-1] == "NohikiBaseSettings", f"Last base is {bases[-1]}, expected NohikiBaseSettings"

    def test_env_prefix_used_throughout(self) -> None:
        assert 'env_prefix="DEMO_CONSUMER_"' in self.config

    def test_schema_name_is_correct(self) -> None:
        assert '"demo_consumer_schema"' in self.config

    def test_lifespan_shutdown_order(self) -> None:
        """Lifespan: consumers stop BEFORE kafka close BEFORE engine close BEFORE obs.shutdown."""
        lines = self.main.splitlines()
        lifespan_start = None
        lifespan_body = []

        for i, line in enumerate(lines):
            if "@asynccontextmanager" in line or "async def lifespan" in line:
                lifespan_start = i
            if lifespan_start is not None:
                lifespan_body.append(line)
                if i > lifespan_start and line.startswith(("def ", "class ")):
                    lifespan_body.pop()
                    break

        if not lifespan_body:
            msg = "lifespan context manager not found"
            raise AssertionError(msg)

        lifespan_text = "\n".join(lifespan_body)
        stop = lifespan_text.find("stop_consumers")
        kafka_close = lifespan_text.find("kafka_client.close")
        engines = lifespan_text.find("close_all_engines")
        obs_shutdown = lifespan_text.find("obs.shutdown")

        assert all(x >= 0 for x in [stop, kafka_close, engines, obs_shutdown]), (
            stop,
            kafka_close,
            engines,
            obs_shutdown,
        )
        assert stop < kafka_close < engines < obs_shutdown, (
            stop,
            kafka_close,
            engines,
            obs_shutdown,
        )

    def test_has_outbox_wiring(self) -> None:
        assert "set_db_session_factory" in self.main

    def test_consumer_capability_in_health(self) -> None:
        assert "CONSUMER_READY" in self.main

    def test_alembic_env_emitted(self) -> None:
        assert "backend/services/demo-consumer-service/alembic/env.py" in self.rendered

    def test_commands_handler_emitted(self) -> None:
        assert "backend/services/demo-consumer-service/src/demo_consumer_service/events/commands.py" in self.rendered


class TestKafkaOnlyProducer:
    def setup_method(self) -> None:
        self.rendered = render(kafka_only_producer())
        self.main = self.rendered["backend/services/demo-scheduler-service/src/demo_scheduler_service/main.py"]

    def test_no_start_consumers(self) -> None:
        """Producer-only must not call start_consumers."""
        assert "start_consumers" not in self.main

    def test_producer_ready_capability(self) -> None:
        assert "PRODUCER_READY" in self.main

    def test_no_consumer_handler_modules(self) -> None:
        paths = set(self.rendered.keys())
        cmd = "backend/services/demo-scheduler-service/src/demo_scheduler_service/events/commands.py"
        cb = "backend/services/demo-scheduler-service/src/demo_scheduler_service/events/callbacks.py"
        assert cmd not in paths
        assert cb not in paths


class TestHttpOnlyProducer:
    def setup_method(self) -> None:
        self.rendered = render(http_only_producer())
        self.main = self.rendered["backend/services/demo-auth-service/src/demo_auth_service/main.py"]

    def test_has_api_routers(self) -> None:
        assert "backend/services/demo-auth-service/src/demo_auth_service/api/routers/__init__.py" in self.rendered

    def test_no_consumer_handlers(self) -> None:
        paths = set(self.rendered.keys())
        assert not any(p.endswith("/events/commands.py") for p in paths)
        assert not any(p.endswith("/events/callbacks.py") for p in paths)

    def test_has_publishers(self) -> None:
        assert "backend/services/demo-auth-service/src/demo_auth_service/events/publishers.py" in self.rendered

    def test_http_shutdown_order(self) -> None:
        """HTTP-only: kafka close BEFORE engine close BEFORE obs.shutdown."""
        lines = self.main.splitlines()
        lifespan_start = None
        lifespan_body = []

        for i, line in enumerate(lines):
            if "@asynccontextmanager" in line or "async def lifespan" in line:
                lifespan_start = i
            if lifespan_start is not None:
                lifespan_body.append(line)
                if i > lifespan_start and line.startswith(("def ", "class ")):
                    lifespan_body.pop()
                    break

        if not lifespan_body:
            msg = "lifespan context manager not found"
            raise AssertionError(msg)

        lifespan_text = "\n".join(lifespan_body)
        kafka_close = lifespan_text.find("kafka_client.close")
        engines = lifespan_text.find("close_all_engines")
        obs_shutdown = lifespan_text.find("obs.shutdown")

        assert all(x >= 0 for x in [kafka_close, engines, obs_shutdown]), (
            kafka_close,
            engines,
            obs_shutdown,
        )
        assert kafka_close < engines < obs_shutdown


class TestPlainLib:
    def setup_method(self) -> None:
        self.rendered = render(plain_lib())

    def test_has_py_typed(self) -> None:
        assert "backend/libs/nohiki-demo-utils/src/nohiki_demo_utils/py.typed" in self.rendered

    def test_has_module_init(self) -> None:
        assert "backend/libs/nohiki-demo-utils/src/nohiki_demo_utils/__init__.py" in self.rendered

    def test_has_smoke_test(self) -> None:
        assert "backend/libs/nohiki-demo-utils/tests/test_smoke.py" in self.rendered

    def test_readme_purpose_is_generated_from_spec(self) -> None:
        readme = self.rendered["backend/libs/nohiki-demo-utils/README.md"]
        assert "`nohiki-demo-utils` provides minimal library archetype." in readme
        assert "The `platform` team owns its public contract and maintenance." in readme
        assert "TODO:" not in readme


class TestNamespaceLib:
    def setup_method(self) -> None:
        self.rendered = render(namespace_lib())
        self.pyproject = self.rendered["backend/libs/nohiki-demo-models/pyproject.toml"]

    def test_has_namespace_build_backend_block(self) -> None:
        """Namespace packages MUST declare module-name + namespace=true."""
        parsed = _parse(self.pyproject)
        tool = cast("dict[str, object]", parsed["tool"])
        uv = cast("dict[str, object]", tool["uv"])
        uv_build = cast("dict[str, object]", uv["build-backend"])
        assert uv_build["module-name"] == "nohiki"
        assert uv_build["namespace"] is True

    def test_no_module_init_file(self) -> None:
        """Namespace packages MUST NOT emit __init__.py under src/nohiki/."""
        assert "backend/libs/nohiki-demo-models/src/nohiki/__init__.py" not in self.rendered


class TestLibWithTesting:
    def setup_method(self) -> None:
        self.rendered = render(lib_with_testing())

    def test_testing_module_emitted(self) -> None:
        path = "backend/libs/nohiki-demo-test-utils/src/nohiki_demo_test_utils/testing.py"
        assert path in self.rendered
