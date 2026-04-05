"""LLM instrumentation: wraps models with OpenTelemetry tracing for Phoenix.

Uses PydanticAI's ``instrument_model()`` to wrap the model chain. Traces
include OpenInference semantic attributes for Phoenix compatibility.
No global side effects: the TracerProvider is scoped to the wrapped model.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from nohiki_observability import get_logger
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, SimpleSpanProcessor
from pydantic_ai.models import Model
from pydantic_ai.models.instrumented import InstrumentationSettings, instrument_model

from nohiki_llm_client.config.constants import (
    INSTRUMENTATION_SPAN_EXPORT_BATCH_SIZE,
    INSTRUMENTATION_SPAN_EXPORT_DELAY_MS,
    INSTRUMENTATION_SPAN_QUEUE_MAX_SIZE,
)
from nohiki_llm_client.observability.phoenix import (
    create_grpc_exporter,
    create_openinference_processor,
    create_phoenix_resource,
)

if TYPE_CHECKING:
    from nohiki_llm_client.config.settings import LLMInstrumentationSettings

logger = get_logger(__name__)


def create_instrumented_model(
    model: Model,
    settings: LLMInstrumentationSettings,
) -> Model:
    """Wrap a model with PydanticAI instrumentation and OpenInference for Phoenix.

    If instrumentation is disabled or no collector endpoint is configured,
    returns the model unchanged.

    Args:
        model: The model (or ``FallbackModel`` chain) to instrument.
        settings: Instrumentation configuration.

    Returns:
        ``InstrumentedModel`` wrapper, or the original model if disabled.
    """
    if not settings.enabled or not settings.collector_endpoint:
        return model

    try:
        tracer_provider = _create_tracer_provider(settings)
        pydantic_ai_settings = InstrumentationSettings(
            tracer_provider=tracer_provider,
        )
        instrumented = instrument_model(model, pydantic_ai_settings)
    except Exception:
        logger.exception(
            "Failed to initialize LLM instrumentation, continuing without",
        )
        return model
    else:
        logger.info(
            "LLM instrumentation enabled",
            collector_endpoint=settings.collector_endpoint,
            project_name=settings.project_name,
            service_name=settings.service_name,
        )
        return instrumented


def _create_tracer_provider(
    settings: LLMInstrumentationSettings,
) -> TracerProvider:
    """Create TracerProvider with OpenInference processor and OTLP exporter.

    The provider includes:

    1. ``OpenInferenceSpanProcessor``: adds Phoenix semantic attributes to spans
    2. OTLP gRPC exporter via ``BatchSpanProcessor`` or ``SimpleSpanProcessor``

    Args:
        settings: Instrumentation configuration.

    Returns:
        Configured ``TracerProvider``.
    """
    resource = create_phoenix_resource(settings.project_name, settings.service_name)
    exporter = create_grpc_exporter(settings.collector_endpoint, settings.export_timeout_seconds)
    timeout_ms = int(settings.export_timeout_seconds * 1000)

    if settings.batch_export:
        export_processor = BatchSpanProcessor(
            exporter,
            max_queue_size=INSTRUMENTATION_SPAN_QUEUE_MAX_SIZE,
            max_export_batch_size=INSTRUMENTATION_SPAN_EXPORT_BATCH_SIZE,
            schedule_delay_millis=INSTRUMENTATION_SPAN_EXPORT_DELAY_MS,
            export_timeout_millis=timeout_ms,
        )
    else:
        export_processor = SimpleSpanProcessor(exporter)

    provider = TracerProvider(resource=resource)
    provider.add_span_processor(create_openinference_processor())
    provider.add_span_processor(export_processor)

    return provider
