"""tests for the Observability core module."""

from __future__ import annotations

import importlib
import logging
from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

import opentelemetry.sdk.trace.sampling as otel_sampling
import pytest
import structlog
from fastapi import FastAPI
from nohiki_observability import (
    CorrelationIdMiddleware,
    Logger,
    Observability,
    ObservabilityBuilder,
    ObservabilityConfig,
    ObservabilityOptions,
    OtelConfig,
    get_logger,
)
from opentelemetry import propagate as otel_propagate
from opentelemetry import trace as otel_trace
from opentelemetry._logs import _internal as otel_logs_internal
from opentelemetry.metrics import _internal as otel_metrics_internal
from opentelemetry.util._once import Once

if TYPE_CHECKING:
    from collections.abc import Generator


type _LoggerState = tuple[list[logging.Handler], list[logging.Filter], int, bool, bool]

_MUTATED_LOGGERS = (
    "",
    "uvicorn",
    "uvicorn.access",
    "uvicorn.error",
    "alembic",
    "alembic.env",
    "alembic.runtime.migration",
)


def _capture_logger_state(logger: logging.Logger) -> _LoggerState:
    return (
        list(logger.handlers),
        list(logger.filters),
        logger.level,
        logger.propagate,
        logger.disabled,
    )


def _restore_logger_state(logger: logging.Logger, state: _LoggerState) -> None:
    handlers, filters, level, propagate, disabled = state
    logger.handlers[:] = handlers
    logger.filters[:] = filters
    logger.setLevel(level)
    logger.propagate = propagate
    logger.disabled = disabled


@pytest.fixture(autouse=True)
def restore_process_observability_state(
    monkeypatch: pytest.MonkeyPatch,
) -> Generator[None]:
    """Restore logging, structlog, and OpenTelemetry globals after each test."""
    loggers = {name: logging.getLogger(name) for name in _MUTATED_LOGGERS}
    logger_states = {name: _capture_logger_state(logger) for name, logger in loggers.items()}
    structlog_config = structlog.get_config()

    for handler in loggers[""].handlers:
        monkeypatch.setattr(handler, "close", lambda: None)

    monkeypatch.setattr(otel_trace, "_TRACER_PROVIDER", None)
    monkeypatch.setattr(otel_trace, "_TRACER_PROVIDER_SET_ONCE", Once())
    monkeypatch.setattr(otel_metrics_internal, "_METER_PROVIDER", None)
    monkeypatch.setattr(otel_metrics_internal, "_METER_PROVIDER_SET_ONCE", Once())
    monkeypatch.setattr(otel_logs_internal, "_LOGGER_PROVIDER", None)
    monkeypatch.setattr(otel_logs_internal, "_LOGGER_PROVIDER_SET_ONCE", Once())
    monkeypatch.setattr(otel_propagate, "_HTTP_TEXT_FORMAT", otel_propagate._HTTP_TEXT_FORMAT)

    yield

    for provider in (
        otel_trace._TRACER_PROVIDER,
        otel_metrics_internal._METER_PROVIDER,
        otel_logs_internal._LOGGER_PROVIDER,
    ):
        if provider is not None:
            provider.shutdown()

    structlog.configure(**structlog_config)
    for name, logger in loggers.items():
        _restore_logger_state(logger, logger_states[name])


@pytest.fixture
def mock_otel_exporters() -> Generator[dict[str, MagicMock]]:
    """Mock all OpenTelemetry exporters to prevent actual network calls."""
    grpc_client = MagicMock(name="GrpcInstrumentorClient")
    grpc_server = MagicMock(name="GrpcInstrumentorServer")
    grpc_module = MagicMock()
    grpc_module.GrpcInstrumentorClient = grpc_client
    grpc_module.GrpcInstrumentorServer = grpc_server

    real_import_module = importlib.import_module

    # Create mock modules for dynamically imported instrumentors
    # Structure: httpx_module.HTTPXClientInstrumentor() returns instrumentor with .instrument()
    httpx_instr = MagicMock(name="HTTPXClientInstrumentor")
    httpx_module = MagicMock()
    httpx_module.HTTPXClientInstrumentor = httpx_instr

    redis_instr = MagicMock(name="RedisInstrumentor")
    redis_module = MagicMock()
    redis_module.RedisInstrumentor = redis_instr

    def import_module_side_effect(name: str, package: str | None = None) -> object:
        if name == "opentelemetry.instrumentation.grpc":
            return grpc_module
        if name == "opentelemetry.instrumentation.httpx":
            return httpx_module
        if name == "opentelemetry.instrumentation.redis":
            return redis_module
        return real_import_module(name, package)

    with (
        patch("nohiki_observability.observability.OTLPLogExporter") as log_exporter,
        patch("nohiki_observability.observability.OTLPSpanExporter") as span_exporter,
        patch("nohiki_observability.observability.OTLPMetricExporter") as metric_exporter,
        patch("nohiki_observability.observability.BatchSpanProcessor") as span_processor,
        patch("nohiki_observability.observability.BatchLogRecordProcessor") as log_processor,
        patch("nohiki_observability.observability.PeriodicExportingMetricReader") as metric_reader,
        patch("nohiki_observability.observability.importlib.import_module") as import_module,
    ):
        import_module.side_effect = import_module_side_effect
        yield {
            "log_exporter": log_exporter,
            "span_exporter": span_exporter,
            "metric_exporter": metric_exporter,
            "span_processor": span_processor,
            "log_processor": log_processor,
            "metric_reader": metric_reader,
            "httpx_instr": httpx_instr,
            "redis_instr": redis_instr,
            "import_module": import_module,
            "grpc_client": grpc_client,
            "grpc_server": grpc_server,
        }


class TestOtelConfig:
    """Tests for OtelConfig dataclass."""

    def test_enabled_when_endpoint_set(self) -> None:
        """Test enabled property returns True when endpoint is set."""
        config = OtelConfig(endpoint="http://collector:4317")
        assert config.enabled is True

    def test_disabled_when_endpoint_none(self) -> None:
        """Test enabled property returns False when endpoint is None."""
        config = OtelConfig(endpoint=None)
        assert config.enabled is False

    def test_disabled_when_endpoint_empty(self) -> None:
        """Test enabled property returns False when endpoint is empty string."""
        config = OtelConfig(endpoint="")
        assert config.enabled is False

    def test_default_insecure_true(self) -> None:
        """Test default insecure value is True."""
        config = OtelConfig(endpoint="http://collector:4317")
        assert config.insecure is True

    def test_insecure_can_be_false(self) -> None:
        """Test insecure can be set to False."""
        config = OtelConfig(endpoint="http://collector:4317", insecure=False)
        assert config.insecure is False

    def test_headers_default_empty(self) -> None:
        """Test headers default to empty dict."""
        config = OtelConfig(endpoint="http://collector:4317")
        assert dict(config.headers) == {}

    def test_headers_can_be_set(self) -> None:
        """Test headers can be set."""
        config = OtelConfig(
            endpoint="http://collector:4317",
            headers={"Authorization": "Bearer token"},
        )
        assert config.headers["Authorization"] == "Bearer token"


class TestObservabilityOptions:
    """Tests for ObservabilityOptions dataclass."""

    def test_required_fields(self) -> None:
        """Test required fields are enforced."""
        otel = OtelConfig(endpoint=None)
        options = ObservabilityOptions(
            service_name="test-service",
            service_version="1.0.0",
            environment="testing",
            otel=otel,
        )
        assert options.service_name == "test-service"
        assert options.service_version == "1.0.0"
        assert options.environment == "testing"

    def test_default_values(self) -> None:
        """Test default values are applied."""
        otel = OtelConfig(endpoint=None)
        options = ObservabilityOptions(
            service_name="test-service",
            service_version="1.0.0",
            environment="testing",
            otel=otel,
        )
        assert options.log_level == "INFO"
        assert options.instrument_redis is False
        assert options.instrument_grpc is True
        assert options.instrument_httpx is True
        assert dict(options.resource_attributes) == {}


class TestObservabilityBuilder:
    """Tests for ObservabilityBuilder fluent API."""

    def test_builder_requires_service_name(self) -> None:
        """Test builder raises error when service_name not set."""
        builder = ObservabilityBuilder()
        with pytest.raises(ValueError, match="service_name is required"):
            builder.build()

    def test_builder_service_method(self) -> None:
        """Test service() method sets name and version."""
        obs = Observability.builder().service("my-service", "2.0.0").build()
        assert obs.options.service_name == "my-service"
        assert obs.options.service_version == "2.0.0"

    def test_builder_environment_method(self) -> None:
        """Test environment() method sets environment."""
        obs = Observability.builder().service("my-service", "1.0.0").environment("production").build()
        assert obs.options.environment == "production"

    def test_builder_otel_endpoint_method(self) -> None:
        """Test otel_endpoint() method sets endpoint and insecure."""
        obs = (
            Observability.builder()
            .service("my-service", "1.0.0")
            .otel_endpoint("http://collector:4317", insecure=False)
            .build()
        )
        assert obs.options.otel.endpoint == "http://collector:4317"
        assert obs.options.otel.insecure is False

    def test_builder_otel_endpoint_empty_becomes_none(self) -> None:
        """Test empty otel_endpoint becomes None."""
        obs = Observability.builder().service("my-service", "1.0.0").otel_endpoint("").build()
        assert obs.options.otel.endpoint is None

    def test_builder_log_level_method(self) -> None:
        """Test log_level() method sets level (uppercased)."""
        obs = Observability.builder().service("my-service", "1.0.0").log_level("debug").build()
        assert obs.options.log_level == "DEBUG"

    def test_builder_instrument_redis_method(self) -> None:
        """Test instrument_redis() method."""
        obs = Observability.builder().service("my-service", "1.0.0").instrument_redis(enabled=True).build()
        assert obs.options.instrument_redis is True

    def test_builder_instrument_grpc_method(self) -> None:
        """Test instrument_grpc() method."""
        obs = Observability.builder().service("my-service", "1.0.0").instrument_grpc(enabled=False).build()
        assert obs.options.instrument_grpc is False

    def test_builder_instrument_httpx_method(self) -> None:
        """Test instrument_httpx() method."""
        obs = Observability.builder().service("my-service", "1.0.0").instrument_httpx(enabled=False).build()
        assert obs.options.instrument_httpx is False

    def test_builder_resource_attributes_method(self) -> None:
        """Test resource_attributes() method."""
        obs = (
            Observability.builder()
            .service("my-service", "1.0.0")
            .resource_attributes({"k8s.pod.name": "my-pod"})
            .build()
        )
        assert obs.options.resource_attributes["k8s.pod.name"] == "my-pod"

    def test_builder_otel_headers_method(self) -> None:
        """Test otel_headers() method."""
        obs = Observability.builder().service("my-service", "1.0.0").otel_headers({"X-Custom": "value"}).build()
        assert obs.options.otel.headers["X-Custom"] == "value"

    def test_builder_sample_rate_method(self) -> None:
        """Test sample_rate() method sets rate."""
        obs = Observability.builder().service("rate-test", "1.0.0").sample_rate(0.5).build()
        assert obs.options.sample_rate == 0.5

    def test_builder_sample_rate_validation(self) -> None:
        """Test sample_rate() raises ValueError for out-of-range values."""
        builder = Observability.builder().service("rate-test", "1.0.0")
        with pytest.raises(ValueError, match=r"sample_rate must be between 0\.0 and 1\.0"):
            builder.sample_rate(1.5)
        with pytest.raises(ValueError, match=r"sample_rate must be between 0\.0 and 1\.0"):
            builder.sample_rate(-0.1)

    def test_builder_tracing_enabled_method(self) -> None:
        """Test tracing_enabled() method."""
        obs = Observability.builder().service("trace-test", "1.0.0").tracing_enabled(enabled=False).build()
        assert obs.options.tracing_enabled is False

    def test_builder_fluent_chaining(self) -> None:
        """Test all builder methods can be chained."""
        obs = (
            Observability.builder()
            .service("chained-service", "3.0.0")
            .environment("staging")
            .otel_endpoint("http://collector:4317")
            .otel_headers({"Auth": "token"})
            .log_level("WARNING")
            .sample_rate(0.5)
            .tracing_enabled(enabled=True)
            .instrument_redis(enabled=True)
            .instrument_grpc(enabled=True)
            .instrument_httpx(enabled=True)
            .resource_attributes({"custom": "attr"})
            .build()
        )
        assert obs.options.service_name == "chained-service"
        assert obs.options.service_version == "3.0.0"
        assert obs.options.environment == "staging"
        assert obs.options.otel.endpoint == "http://collector:4317"
        assert obs.options.log_level == "WARNING"
        assert obs.options.sample_rate == 0.5
        assert obs.options.tracing_enabled is True


def _create_mock_settings(
    service_name: str,
    service_version: str,
    *,
    debug: bool = False,
    otel_endpoint: str = "",
    instrument_redis: bool = False,
) -> MagicMock:
    """Create a properly structured mock settings object for from_settings tests."""
    settings = MagicMock()
    settings.service_name = service_name
    settings.service_version = service_version
    settings.debug = debug
    settings.instrument_redis = instrument_redis

    obs_config = MagicMock()
    obs_config.otel_service_name = ""
    obs_config.otel_endpoint = otel_endpoint
    obs_config.otel_insecure = True
    obs_config.logging.level = "DEBUG" if debug else "INFO"
    obs_config.tracing.enabled = True
    obs_config.tracing.sample_rate = 1.0
    settings.observability = obs_config

    return settings


class TestObservabilityFromSettings:
    """Tests for Observability.from_settings() factory method."""

    def test_from_settings_basic(self) -> None:
        """Test from_settings with minimal settings object."""
        settings = _create_mock_settings(
            "settings-service",
            "1.2.3",
            otel_endpoint="http://collector:4317",
        )

        obs = Observability.from_settings(settings)

        assert obs.options.service_name == "settings-service"
        assert obs.options.service_version == "1.2.3"
        assert obs.options.environment == "production"
        assert obs.options.otel.endpoint == "http://collector:4317"

    def test_from_settings_debug_mode(self) -> None:
        """Test from_settings sets development environment in debug mode."""
        settings = _create_mock_settings(
            "debug-service",
            "0.0.1",
            debug=True,
            otel_endpoint="",
        )

        obs = Observability.from_settings(settings)

        assert obs.options.environment == "development"
        assert obs.options.otel.endpoint is None

    def test_from_settings_with_instrument_redis(self) -> None:
        """Test from_settings enables Redis instrumentation via instrument_redis property."""
        settings = _create_mock_settings(
            "redis-service",
            "1.0.0",
            instrument_redis=True,
        )

        obs = Observability.from_settings(settings)

        assert obs.options.instrument_redis is True

    def test_from_settings_raw_config(self) -> None:
        """Test from_settings with raw ObservabilityConfig object."""
        config = MagicMock(spec=ObservabilityConfig)
        config.otel_endpoint = "http://raw:4317"
        config.otel_insecure = False
        config.otel_service_name = "raw-service"
        config.logging.level = "WARNING"
        config.tracing.enabled = True
        config.tracing.sample_rate = 1.0

        obs = Observability.from_settings(config)

        assert obs.options.service_name == "raw-service"
        assert obs.options.otel.endpoint == "http://raw:4317"
        assert obs.options.otel.insecure is False
        assert obs.options.log_level == "WARNING"

    def test_from_settings_raw_config_default_name(self) -> None:
        """Test from_settings with raw config uses default name if not provided."""
        config = MagicMock(spec=ObservabilityConfig)
        config.otel_endpoint = ""
        config.otel_service_name = None
        config.logging.level = "INFO"
        config.tracing.enabled = True
        config.tracing.sample_rate = 1.0

        obs = Observability.from_settings(config)

        assert obs.options.service_name == "unknown-service"

    def test_from_settings_reads_sample_rate(self) -> None:
        """Test from_settings correctly reads tracing.sample_rate."""
        settings = _create_mock_settings("sample-service", "1.0.0")
        settings.observability.tracing.sample_rate = 0.25
        settings.observability.tracing.enabled = True

        obs = Observability.from_settings(settings)

        assert obs.options.sample_rate == 0.25
        assert obs.options.tracing_enabled is True

    def test_from_settings_reads_tracing_disabled(self) -> None:
        """Test from_settings correctly reads tracing.enabled=False."""
        settings = _create_mock_settings("disabled-service", "1.0.0")
        settings.observability.tracing.enabled = False
        settings.observability.tracing.sample_rate = 0.5

        obs = Observability.from_settings(settings)

        assert obs.options.tracing_enabled is False
        assert obs.options.sample_rate == 0.5


class TestObservabilityInit:
    """Tests for Observability.init() method."""

    def test_init_without_otel(self, mock_otel_exporters: dict[str, MagicMock]) -> None:
        """Test init() works without OTEL endpoint configured."""
        obs = Observability.builder().service("no-otel", "1.0.0").build()
        obs.init()

        # Should not call OTEL exporters
        mock_otel_exporters["span_exporter"].assert_not_called()
        mock_otel_exporters["metric_exporter"].assert_not_called()

    def test_init_with_otel(self, mock_otel_exporters: dict[str, MagicMock]) -> None:
        """Test init() configures OTEL when endpoint is set."""
        obs = Observability.builder().service("with-otel", "1.0.0").otel_endpoint("http://collector:4317").build()
        obs.init()

        mock_otel_exporters["span_exporter"].assert_called_once()
        mock_otel_exporters["span_processor"].assert_called_once()

    def test_init_idempotent(self, mock_otel_exporters: dict[str, MagicMock]) -> None:
        """Test init() is idempotent - multiple calls don't reconfigure."""
        obs = Observability.builder().service("idempotent", "1.0.0").build()
        obs.init()
        obs.init()
        obs.init()

        # Should only instrument once
        assert mock_otel_exporters["httpx_instr"].return_value.instrument.call_count == 1

    def test_init_respects_instrument_redis(self, mock_otel_exporters: dict[str, MagicMock]) -> None:
        """Test init() only instruments Redis when enabled."""
        obs = Observability.builder().service("redis-test", "1.0.0").instrument_redis(enabled=True).build()
        obs.init()

        mock_otel_exporters["redis_instr"].return_value.instrument.assert_called_once()

    def test_init_skips_redis_when_disabled(self, mock_otel_exporters: dict[str, MagicMock]) -> None:
        """Test init() skips Redis instrumentation when disabled."""
        obs = Observability.builder().service("no-redis", "1.0.0").instrument_redis(enabled=False).build()
        obs.init()

        mock_otel_exporters["redis_instr"].return_value.instrument.assert_not_called()

    def test_init_respects_instrument_grpc(self, mock_otel_exporters: dict[str, MagicMock]) -> None:
        """Test init() only instruments gRPC when enabled."""
        obs = Observability.builder().service("grpc-test", "1.0.0").instrument_grpc(enabled=False).build()
        obs.init()

        mock_otel_exporters["grpc_client"].return_value.instrument.assert_not_called()
        mock_otel_exporters["grpc_server"].return_value.instrument.assert_not_called()

    def test_init_respects_instrument_httpx(self, mock_otel_exporters: dict[str, MagicMock]) -> None:
        """Test init() only instruments HTTPX when enabled."""
        obs = Observability.builder().service("httpx-test", "1.0.0").instrument_httpx(enabled=False).build()
        obs.init()

        mock_otel_exporters["httpx_instr"].return_value.instrument.assert_not_called()

    def test_init_configures_uvicorn_logging(self, mock_otel_exporters: dict[str, MagicMock]) -> None:
        """Test init() configures uvicorn loggers to disable access logs."""
        import logging

        obs = Observability.builder().service("uvicorn-test", "1.0.0").build()
        obs.init()

        uvicorn_access = logging.getLogger("uvicorn.access")
        assert uvicorn_access.propagate is False

        uvicorn_error = logging.getLogger("uvicorn.error")
        assert uvicorn_error.propagate is False

        uvicorn_main = logging.getLogger("uvicorn")
        assert uvicorn_main.propagate is False

    def test_init_fastapi_registers_access_log_middleware(self, mock_otel_exporters: dict[str, MagicMock]) -> None:
        """Test init_fastapi() adds HTTPAccessLogMiddleware to the app."""
        obs = Observability.builder().service("access-log-test", "1.0.0").build()
        obs.init()
        app = FastAPI()
        obs.init_fastapi(app)
        middleware_classes = [m.cls for m in app.user_middleware]
        from nohiki_observability.access_log import HTTPAccessLogMiddleware

        assert HTTPAccessLogMiddleware in middleware_classes

    def test_init_configures_alembic_logging(self, mock_otel_exporters: dict[str, MagicMock]) -> None:
        """Test init() configures alembic loggers to propagate."""
        import logging

        obs = Observability.builder().service("alembic-test", "1.0.0").build()
        obs.init()

        alembic_logger = logging.getLogger("alembic")
        assert alembic_logger.propagate is True

        alembic_env = logging.getLogger("alembic.env")
        assert alembic_env.propagate is True

        alembic_runtime = logging.getLogger("alembic.runtime.migration")
        assert alembic_runtime.propagate is True


class TestObservabilityInitFastapi:
    """Tests for Observability.init_fastapi() method."""

    def test_init_fastapi_calls_init(self, mock_otel_exporters: dict[str, MagicMock]) -> None:
        """Test init_fastapi() calls init() if not already initialized."""
        obs = Observability.builder().service("fastapi-test", "1.0.0").build()
        app = MagicMock()

        mock_fastapi_instr = MagicMock()
        with patch.dict("sys.modules", {"opentelemetry.instrumentation.fastapi": mock_fastapi_instr}):
            obs.init_fastapi(app)

        # Should have called init (verified by httpx instrumentation)
        mock_otel_exporters["httpx_instr"].return_value.instrument.assert_called_once()

    def test_init_fastapi_adds_middleware(self) -> None:
        """Test init_fastapi() adds HTTPAccessLogMiddleware and CorrelationIdMiddleware."""
        obs = Observability.builder().service("middleware-test", "1.0.0").build()
        obs._initialized = True  # Skip full init
        app = MagicMock()

        mock_fastapi_instr = MagicMock()
        with patch.dict("sys.modules", {"opentelemetry.instrumentation.fastapi": mock_fastapi_instr}):
            obs.init_fastapi(app)

        # Both middlewares should be added
        assert app.add_middleware.call_count == 2
        calls = app.add_middleware.call_args_list
        from nohiki_observability.access_log import HTTPAccessLogMiddleware

        assert calls[0][0][0] == HTTPAccessLogMiddleware
        assert calls[1][0][0] == CorrelationIdMiddleware

    def test_init_fastapi_instruments_app(self) -> None:
        """Test init_fastapi() instruments FastAPI app."""
        obs = Observability.builder().service("instrument-test", "1.0.0").build()
        obs._initialized = True  # Skip full init
        app = MagicMock()

        mock_fastapi_instr = MagicMock()
        with patch.dict("sys.modules", {"opentelemetry.instrumentation.fastapi": mock_fastapi_instr}):
            obs.init_fastapi(app)

        mock_fastapi_instr.FastAPIInstrumentor.instrument_app.assert_called_once()


class TestLogger:
    """Tests for Logger wrapper class."""

    def test_logger_debug(self) -> None:
        """Test Logger.debug() method."""
        mock_bound = MagicMock()
        logger = Logger(mock_bound)

        logger.debug("test message", key="value")

        mock_bound.debug.assert_called_once_with("test message", key="value")

    def test_logger_info(self) -> None:
        """Test Logger.info() method."""
        mock_bound = MagicMock()
        logger = Logger(mock_bound)

        logger.info("test message", key="value")

        mock_bound.info.assert_called_once_with("test message", key="value")

    def test_logger_warning(self) -> None:
        """Test Logger.warning() method."""
        mock_bound = MagicMock()
        logger = Logger(mock_bound)

        logger.warning("test message", key="value")

        mock_bound.warning.assert_called_once_with("test message", key="value")

    def test_logger_error(self) -> None:
        """Test Logger.error() method."""
        mock_bound = MagicMock()
        logger = Logger(mock_bound)

        logger.error("test message", key="value")

        mock_bound.error.assert_called_once_with("test message", key="value")

    def test_logger_critical(self) -> None:
        """Test Logger.critical() method."""
        mock_bound = MagicMock()
        logger = Logger(mock_bound)

        logger.critical("test message", key="value")

        mock_bound.critical.assert_called_once_with("test message", key="value")

    def test_logger_exception(self) -> None:
        """Test Logger.exception() method."""
        mock_bound = MagicMock()
        logger = Logger(mock_bound)

        logger.exception("test message", key="value")

        mock_bound.exception.assert_called_once_with("test message", key="value")

    def test_logger_bind(self) -> None:
        """Test Logger.bind() returns new Logger with bound context."""
        mock_bound = MagicMock()
        mock_bound.bind.return_value = MagicMock()
        logger = Logger(mock_bound)

        new_logger = logger.bind(request_id="123")

        mock_bound.bind.assert_called_once_with(request_id="123")
        assert isinstance(new_logger, Logger)
        assert new_logger is not logger

    def test_logger_flush(self) -> None:
        """Test Logger flush parameter flushes stdout."""
        mock_bound = MagicMock()
        logger = Logger(mock_bound)

        with patch("sys.stdout") as mock_stdout:
            logger.info("test", flush=True)

        mock_stdout.flush.assert_called_once()


class TestGetLogger:
    """Tests for get_logger() convenience function."""

    def test_get_logger_returns_logger(self) -> None:
        """Test get_logger() returns a Logger instance."""
        logger = get_logger("test.module")
        assert isinstance(logger, Logger)

    def test_get_logger_with_name(self) -> None:
        """Test get_logger() uses provided name."""
        with patch("nohiki_observability.observability.structlog.get_logger") as mock_get:
            mock_get.return_value = MagicMock(spec=structlog.BoundLogger)
            get_logger("my.module.name")

        mock_get.assert_called_once_with("my.module.name")


class TestObservabilityOptionsProperty:
    """Test ObservabilityOptions property access."""

    def test_options_property(self) -> None:
        """Test options property returns the configuration."""
        obs = Observability.builder().service("options-test", "1.0.0").environment("staging").build()

        assert obs.options.service_name == "options-test"
        assert obs.options.environment == "staging"


class TestObservabilityShutdown:
    """Tests for Observability.shutdown() method."""

    def test_shutdown_before_init(self) -> None:
        """Verify shutdown before init is safe (no-op)."""
        obs = Observability.builder().service("shutdown-test", "1.0.0").build()

        # Should not raise - just a no-op
        obs.shutdown()

        # Should still be marked as not initialized
        assert obs._initialized is False

    def test_shutdown_after_init(self) -> None:
        """Verify proper shutdown sequence after init (without calling real init)."""
        obs = Observability.builder().service("shutdown-test", "1.0.0").build()

        # Manually set initialized state to test shutdown logic
        obs._initialized = True
        obs._tracer_provider = MagicMock()
        obs._meter_provider = MagicMock()
        obs._logger_provider = MagicMock()

        obs.shutdown()

        assert obs._initialized is False

    def test_shutdown_idempotent(self) -> None:
        """Verify multiple shutdown calls are safe."""
        obs = Observability.builder().service("shutdown-test", "1.0.0").build()

        # Manually set initialized state
        obs._initialized = True
        obs._tracer_provider = MagicMock()

        # Should not raise on multiple calls
        obs.shutdown()
        obs.shutdown()
        obs.shutdown()

        assert obs._initialized is False

    def test_shutdown_calls_provider_shutdown(self) -> None:
        """Verify shutdown calls shutdown on all providers."""
        obs = Observability.builder().service("shutdown-providers", "1.0.0").build()

        # Mock providers
        mock_tracer = MagicMock()
        mock_meter = MagicMock()
        mock_logger = MagicMock()

        obs._initialized = True
        obs._tracer_provider = mock_tracer
        obs._meter_provider = mock_meter
        obs._logger_provider = mock_logger

        obs.shutdown()

        mock_tracer.shutdown.assert_called_once()
        mock_meter.shutdown.assert_called_once()
        mock_logger.shutdown.assert_called_once()

    def test_shutdown_continues_after_provider_error(self) -> None:
        """A failed provider must not prevent later providers from shutting down."""
        obs = Observability.builder().service("shutdown-error", "1.0.0").build()
        mock_tracer = MagicMock()
        mock_tracer.shutdown.side_effect = RuntimeError("Shutdown failed")
        mock_meter = MagicMock()
        mock_logger = MagicMock()

        obs._initialized = True
        obs._tracer_provider = mock_tracer
        obs._meter_provider = mock_meter
        obs._logger_provider = mock_logger

        obs.shutdown()

        mock_meter.shutdown.assert_called_once()
        mock_logger.shutdown.assert_called_once()
        assert obs._initialized is False

    def test_shutdown_with_none_providers(self) -> None:
        """Verify shutdown works when providers are None."""
        obs = Observability.builder().service("shutdown-none", "1.0.0").build()

        obs._initialized = True
        obs._tracer_provider = None
        obs._meter_provider = None
        obs._logger_provider = None

        # Should not raise
        obs.shutdown()

        assert obs._initialized is False


class TestSamplerResolution:
    """Tests for trace sampler resolution based on sample_rate and tracing_enabled."""

    def test_sample_rate_full_uses_always_on(self) -> None:
        """Test sample_rate=1.0 resolves to ALWAYS_ON sampler."""
        obs = Observability.builder().service("sampler-test", "1.0.0").sample_rate(1.0).build()
        sampler = obs._resolve_sampler()
        assert sampler is otel_sampling.ALWAYS_ON

    def test_sample_rate_zero_uses_always_off(self) -> None:
        """Test sample_rate=0.0 resolves to ALWAYS_OFF sampler."""
        obs = Observability.builder().service("sampler-test", "1.0.0").sample_rate(0.0).build()
        sampler = obs._resolve_sampler()
        assert sampler is otel_sampling.ALWAYS_OFF

    def test_sample_rate_half_uses_parent_based(self) -> None:
        """Test sample_rate=0.5 resolves to ParentBasedTraceIdRatio sampler."""
        obs = Observability.builder().service("sampler-test", "1.0.0").sample_rate(0.5).build()
        sampler = obs._resolve_sampler()
        assert isinstance(sampler, otel_sampling.ParentBasedTraceIdRatio)

    def test_sample_rate_tenth_uses_parent_based(self) -> None:
        """Test sample_rate=0.1 resolves to ParentBasedTraceIdRatio sampler."""
        obs = Observability.builder().service("sampler-test", "1.0.0").sample_rate(0.1).build()
        sampler = obs._resolve_sampler()
        assert isinstance(sampler, otel_sampling.ParentBasedTraceIdRatio)

    def test_tracing_disabled_uses_always_off(self) -> None:
        """Test tracing_enabled=False resolves to ALWAYS_OFF regardless of sample_rate."""
        obs = (
            Observability.builder()
            .service("sampler-test", "1.0.0")
            .sample_rate(1.0)
            .tracing_enabled(enabled=False)
            .build()
        )
        sampler = obs._resolve_sampler()
        assert sampler is otel_sampling.ALWAYS_OFF

    def test_tracing_disabled_overrides_sample_rate(self) -> None:
        """Test tracing_enabled=False takes precedence over any sample_rate."""
        obs = (
            Observability.builder()
            .service("sampler-test", "1.0.0")
            .sample_rate(0.5)
            .tracing_enabled(enabled=False)
            .build()
        )
        sampler = obs._resolve_sampler()
        assert sampler is otel_sampling.ALWAYS_OFF

    def test_default_sample_rate_is_always_on(self) -> None:
        """Test default configuration (no explicit sample_rate) uses ALWAYS_ON."""
        obs = Observability.builder().service("sampler-test", "1.0.0").build()
        sampler = obs._resolve_sampler()
        assert sampler is otel_sampling.ALWAYS_ON
