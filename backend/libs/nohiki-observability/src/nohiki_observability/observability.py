"""Main Observability class for unified telemetry initialization.

The primary Observability class that consolidates
logging, tracing, and metrics setup into a single convenient API.
"""

from __future__ import annotations

import asyncio
import importlib
import logging
import sys
import uuid
from threading import Lock
from typing import TYPE_CHECKING

import structlog
from opentelemetry import metrics, trace
from opentelemetry._logs import set_logger_provider
from opentelemetry.baggage.propagation import W3CBaggagePropagator
from opentelemetry.exporter.otlp.proto.grpc._log_exporter import OTLPLogExporter
from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import OTLPMetricExporter
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.logging.handler import LoggingHandler
from opentelemetry.propagate import set_global_textmap
from opentelemetry.propagators.composite import CompositePropagator
from opentelemetry.sdk._logs import LoggerProvider
from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.sdk.trace.sampling import ALWAYS_OFF, ALWAYS_ON, ParentBasedTraceIdRatio
from opentelemetry.semconv._incubating.attributes import deployment_attributes
from opentelemetry.semconv.attributes import service_attributes
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator

from .builder import ObservabilityBuilder
from .config import ObservabilityOptions
from .logger import Logger, get_logger
from .processors import (
    ServiceInfoProcessor,
    add_correlation_id,
    add_timestamp,
    add_trace_info,
    redact_sensitive_data,
)
from .protocols import ObservabilityConfig, ObservabilitySettingsProvider

if TYPE_CHECKING:
    from fastapi import FastAPI
    from opentelemetry.sdk.trace.sampling import Sampler

LOG_FORMAT_MESSAGE_ONLY = "%(message)s"


class Observability:
    """Unified observability initialization for Nohiki services.

    Consolidates logging, tracing, and metrics setup into a single convenient API.
    """

    __slots__ = (
        "_initialized",
        "_lifecycle_lock",
        "_logger_provider",
        "_loop_lag_seconds",
        "_meter_provider",
        "_options",
        "_tracer_provider",
    )

    def __init__(self, options: ObservabilityOptions) -> None:
        """Initialize with configuration options."""
        self._options = options
        self._lifecycle_lock = Lock()
        self._initialized = False
        self._loop_lag_seconds: float = 0.0
        self._tracer_provider: TracerProvider | None = None
        self._meter_provider: MeterProvider | None = None
        self._logger_provider: LoggerProvider | None = None

    @classmethod
    def builder(cls) -> ObservabilityBuilder:
        """Create a new builder for fluent configuration."""
        return ObservabilityBuilder()

    @classmethod
    def from_settings(cls, settings: ObservabilitySettingsProvider | ObservabilityConfig) -> Observability:
        """Create Observability from a settings object.

        Supports either:
        - A service settings object exposing service_name/service_version/debug + .observability
        - A raw observability config implementing ObservabilityConfig
        """
        if isinstance(settings, ObservabilityConfig):
            obs_config = settings
            service_name = getattr(settings, "otel_service_name", "") or "unknown-service"
            service_version = "0.0.0"
            debug = False
            instrument_redis = False
        else:
            obs_config = settings.observability
            service_name = obs_config.otel_service_name or settings.service_name
            service_version = settings.service_version
            debug = settings.debug
            instrument_redis = settings.instrument_redis
        endpoint = obs_config.otel_endpoint or None
        environment = "development" if debug else "production"

        return (
            cls.builder()
            .service(service_name, service_version)
            .environment(environment)
            .otel_endpoint(endpoint, insecure=obs_config.otel_insecure)
            .log_level(obs_config.logging.level)
            .sample_rate(obs_config.tracing.sample_rate)
            .tracing_enabled(enabled=obs_config.tracing.enabled)
            .instrument_redis(enabled=instrument_redis)
            .build()
        )

    def init(self) -> None:
        """Initialize all observability components.

        This method:
        1. Configures structured logging with JSON output
        2. Sets up OpenTelemetry tracing with OTLP export
        3. Configures metrics collection
        4. Enables auto-instrumentation for HTTP, gRPC, etc.

        Safe to call multiple times - subsequent calls are no-ops.
        """
        with self._lifecycle_lock:
            if self._initialized:
                return

            self._configure_logging()
            self._configure_tracing()
            self._configure_metrics()
            self._setup_auto_instrumentation()
            self._setup_runtime_metrics()

            self._initialized = True

            structlog.get_logger(__name__).info(
                "Observability initialized",
                service_name=self._options.service_name,
                service_version=self._options.service_version,
                environment=self._options.environment,
                otel_enabled=self._options.otel.enabled,
            )

    def init_fastapi(self, app: FastAPI) -> None:
        """Initialize FastAPI-specific observability.

        This method:
        1. Calls init() if not already initialized
        2. Adds HTTPAccessLogMiddleware (inside correlation context)
        3. Adds CorrelationIdMiddleware (outermost)
        4. Instruments FastAPI with OpenTelemetry

        Args:
            app: The FastAPI application instance.

        """
        if not self._initialized:
            self.init()

        fastapi_module = importlib.import_module("opentelemetry.instrumentation.fastapi")
        correlation_module = importlib.import_module("nohiki_observability.correlation")
        access_log_module = importlib.import_module("nohiki_observability.access_log")

        # Starlette middleware is LIFO: last added = outermost.
        # CorrelationIdMiddleware runs first (outermost), then HTTPAccessLogMiddleware
        # executes inside with correlation_id context var already set.
        app.add_middleware(access_log_module.HTTPAccessLogMiddleware)
        app.add_middleware(correlation_module.CorrelationIdMiddleware)  # ty: ignore[invalid-argument-type]  # Starlette ParamSpec limitation (astral-sh/ty#1635)
        fastapi_module.FastAPIInstrumentor.instrument_app(app, tracer_provider=trace.get_tracer_provider())

    def get_logger(self, name: str) -> Logger:
        """Get a structured logger instance."""
        return get_logger(name)

    @property
    def options(self) -> ObservabilityOptions:
        """Get the current configuration options."""
        return self._options

    def shutdown(self) -> None:
        """Shutdown all OpenTelemetry providers gracefully.

        This flushes pending spans/metrics and closes exporters.
        Call this from FastAPI lifespan shutdown.

        Safe to call multiple times or before init() - subsequent calls are no-ops.
        """
        with self._lifecycle_lock:
            if not self._initialized:
                return

            providers = (
                ("tracing", self._tracer_provider),
                ("metrics", self._meter_provider),
                ("logging", self._logger_provider),
            )
            for provider_name, provider in providers:
                if provider is None:
                    continue
                try:
                    provider.shutdown()
                except (OSError, RuntimeError) as e:
                    structlog.get_logger(__name__).warning(
                        "Error during observability shutdown",
                        provider=provider_name,
                        error_type=type(e).__name__,
                    )

            self._initialized = False

    def _configure_logging(self) -> None:
        """Configure structured logging with OpenTelemetry integration."""
        log_level = getattr(logging, self._options.log_level.upper())

        logging.basicConfig(
            format=LOG_FORMAT_MESSAGE_ONLY,
            stream=sys.stdout,
            level=log_level,
            force=True,
        )

        self._configure_uvicorn_logging()

        service_processor = ServiceInfoProcessor(
            self._options.service_name,
            self._options.service_version,
        )

        processors: list[structlog.typing.Processor] = [
            structlog.contextvars.merge_contextvars,
            structlog.stdlib.filter_by_level,
            add_timestamp,
            service_processor,
            add_correlation_id,
            add_trace_info,
            structlog.stdlib.PositionalArgumentsFormatter(),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            redact_sensitive_data,
            structlog.processors.UnicodeDecoder(),
            structlog.processors.JSONRenderer(),
        ]

        structlog.configure(
            processors=processors,
            wrapper_class=structlog.stdlib.BoundLogger,
            logger_factory=structlog.stdlib.LoggerFactory(),
            cache_logger_on_first_use=True,
        )

        if self._options.otel.enabled and self._options.otel.endpoint:
            self._configure_otel_logging()

    def _configure_uvicorn_logging(self) -> None:
        """Configure uvicorn loggers to use structured format or be silenced.

        - uvicorn.access is silenced (replaced by HTTPAccessLogMiddleware)
        - uvicorn.error and uvicorn get a structlog ProcessorFormatter so their
          messages (startup/shutdown, errors) appear as structured JSON instead
          of plain text
        """
        uvicorn_access = logging.getLogger("uvicorn.access")
        uvicorn_access.handlers.clear()
        uvicorn_access.propagate = False

        # Route uvicorn.error and uvicorn through structlog for structured JSON
        formatter = structlog.stdlib.ProcessorFormatter(
            processors=[
                structlog.stdlib.ProcessorFormatter.remove_processors_meta,
                structlog.processors.JSONRenderer(),
            ],
            foreign_pre_chain=[
                structlog.stdlib.add_log_level,
                add_timestamp,
                ServiceInfoProcessor(self._options.service_name, self._options.service_version),
                add_correlation_id,
                structlog.processors.format_exc_info,
                redact_sensitive_data,
            ],
        )

        for logger_name in ("uvicorn.error", "uvicorn"):
            uv_logger = logging.getLogger(logger_name)
            uv_logger.handlers.clear()
            uv_logger.propagate = False
            handler = logging.StreamHandler(sys.stdout)
            handler.setFormatter(formatter)
            uv_logger.addHandler(handler)

        self._configure_alembic_logging()

    def _configure_alembic_logging(self) -> None:
        """Configure alembic loggers to propagate through root logger."""
        alembic_logger = logging.getLogger("alembic")
        alembic_logger.handlers.clear()
        alembic_logger.propagate = True

        alembic_env = logging.getLogger("alembic.env")
        alembic_env.handlers.clear()
        alembic_env.propagate = True

        alembic_runtime = logging.getLogger("alembic.runtime.migration")
        alembic_runtime.handlers.clear()
        alembic_runtime.propagate = True

    def _configure_otel_logging(self) -> None:
        """Configure OpenTelemetry log export."""
        try:
            resource = self._create_resource()
            logger_provider = LoggerProvider(resource=resource)
            self._logger_provider = logger_provider
            set_logger_provider(logger_provider)

            exporter = OTLPLogExporter(
                endpoint=self._options.otel.endpoint,
                insecure=self._options.otel.insecure,
                headers=dict(self._options.otel.headers),
                timeout=5,
            )
            processor = BatchLogRecordProcessor(
                exporter,
                schedule_delay_millis=5000,
                max_export_batch_size=512,
                export_timeout_millis=5000,
            )
            logger_provider.add_log_record_processor(processor)

            handler = LoggingHandler(
                level=getattr(logging, self._options.log_level.upper()),
                logger_provider=logger_provider,
            )
            logging.getLogger().addHandler(handler)
        except (OSError, RuntimeError) as e:
            structlog.get_logger(__name__).warning("Failed to configure OTEL logging", error=str(e))

    def _configure_tracing(self) -> None:
        """Configure distributed tracing with OpenTelemetry."""
        self._configure_trace_propagators()

        resource = self._create_resource()
        sampler = self._resolve_sampler()
        trace_provider = TracerProvider(resource=resource, sampler=sampler)
        self._tracer_provider = trace_provider

        if self._options.otel.enabled and self._options.otel.endpoint:
            exporter = OTLPSpanExporter(
                endpoint=self._options.otel.endpoint,
                insecure=self._options.otel.insecure,
                headers=dict(self._options.otel.headers),
                timeout=5,
            )
            processor = BatchSpanProcessor(
                exporter,
                max_queue_size=2048,
                max_export_batch_size=512,
                schedule_delay_millis=5000,
                export_timeout_millis=5000,
            )
            trace_provider.add_span_processor(processor)

        trace.set_tracer_provider(trace_provider)

    def _resolve_sampler(self) -> Sampler:
        """Resolve the trace sampler based on configuration."""
        if not self._options.tracing_enabled:
            return ALWAYS_OFF
        if self._options.sample_rate <= 0.0:
            return ALWAYS_OFF
        if self._options.sample_rate >= 1.0:
            return ALWAYS_ON
        return ParentBasedTraceIdRatio(self._options.sample_rate)

    def _configure_metrics(self) -> None:
        """Configure metrics collection with OpenTelemetry."""
        if not self._options.otel.enabled or not self._options.otel.endpoint:
            return

        try:
            resource = self._create_resource()
            metric_reader = PeriodicExportingMetricReader(
                OTLPMetricExporter(
                    endpoint=self._options.otel.endpoint,
                    insecure=self._options.otel.insecure,
                    headers=dict(self._options.otel.headers),
                    timeout=5,
                ),
                export_interval_millis=10000,
                export_timeout_millis=5000,
            )
            meter_provider = MeterProvider(resource=resource, metric_readers=[metric_reader])
            self._meter_provider = meter_provider
            metrics.set_meter_provider(meter_provider)
        except (OSError, RuntimeError) as e:
            structlog.get_logger(__name__).warning("Failed to configure OTEL metrics", error=str(e))

    def _setup_auto_instrumentation(self) -> None:
        """Set up automatic instrumentation for common libraries (lazy imports)."""
        if self._options.instrument_httpx:
            try:
                httpx_module = importlib.import_module("opentelemetry.instrumentation.httpx")
                httpx_module.HTTPXClientInstrumentor().instrument()
            except ImportError:
                structlog.get_logger(__name__).debug(
                    "HTTPX instrumentation not available - install nohiki-observability[httpx]"
                )

        if self._options.instrument_redis:
            try:
                redis_module = importlib.import_module("opentelemetry.instrumentation.redis")
                redis_module.RedisInstrumentor().instrument()
            except ImportError:
                structlog.get_logger(__name__).debug(
                    "Redis instrumentation not available - install nohiki-observability[redis]"
                )

        if self._options.instrument_grpc:
            try:
                grpc_module = importlib.import_module("opentelemetry.instrumentation.grpc")
                grpc_module.GrpcInstrumentorClient().instrument()
                grpc_module.GrpcInstrumentorServer().instrument()
            except ImportError:
                structlog.get_logger(__name__).debug(
                    "gRPC instrumentation not available - install nohiki-observability[grpc]"
                )

    def _setup_runtime_metrics(self) -> None:
        """Set up Python runtime metrics (GC, memory, threads, event loop lag)."""
        self._instrument_system_metrics()
        self._setup_event_loop_lag_metric()

    def _instrument_system_metrics(self) -> None:
        """Instrument process-level system metrics via OpenTelemetry."""
        try:
            system_module = importlib.import_module("opentelemetry.instrumentation.system_metrics")
            system_module.SystemMetricsInstrumentor().instrument()
        except ImportError:
            structlog.get_logger(__name__).debug(
                "System metrics instrumentation not available - install nohiki-observability[system]"
            )

    def _setup_event_loop_lag_metric(self) -> None:
        """Track asyncio event loop lag via observable gauge."""
        meter = metrics.get_meter("nohiki.runtime")

        def _measure_loop_lag(
            _options: metrics.CallbackOptions,
        ) -> list[metrics.Observation]:
            return [metrics.Observation(self._loop_lag_seconds)]

        meter.create_observable_gauge(
            "nohiki_runtime_event_loop_lag_seconds",
            callbacks=[_measure_loop_lag],
            description="Asyncio event loop scheduling lag",
            unit="s",
        )

        self._start_loop_lag_sampler()

    def _start_loop_lag_sampler(self) -> None:
        """Start a periodic callback that measures event loop scheduling delay."""
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return

        def _sample() -> None:
            expected = loop.time()

            def _on_callback() -> None:
                self._loop_lag_seconds = max(loop.time() - expected - 0.1, 0.0)
                if self._initialized:
                    loop.call_later(0.1, _sample)

            loop.call_later(0.1, _on_callback)

        loop.call_soon(_sample)

    def _create_resource(self) -> Resource:
        """Create OpenTelemetry resource with service metadata."""
        attributes: dict[str, str] = {
            service_attributes.SERVICE_NAME: self._options.service_name,
            service_attributes.SERVICE_VERSION: self._options.service_version,
            deployment_attributes.DEPLOYMENT_ENVIRONMENT_NAME: self._options.environment,
            "service.namespace": "nohiki",
            "service.instance.id": str(uuid.uuid4()),
        }
        if self._options.resource_attributes:
            attributes |= self._options.resource_attributes

        return Resource.create(attributes)

    @staticmethod
    def _configure_trace_propagators() -> None:
        """Configure W3C trace context and baggage propagators."""
        propagators = [
            TraceContextTextMapPropagator(),
            W3CBaggagePropagator(),
        ]
        set_global_textmap(CompositePropagator(propagators))
