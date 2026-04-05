"""Phoenix/OpenInference helper functions for LLM span instrumentation.

Provides factory functions for OpenInference span processors and OTel
resources used by ``instrumentation.py`` to wrap PydanticAI model chains.
"""

from __future__ import annotations

from openinference.instrumentation.pydantic_ai import OpenInferenceSpanProcessor
from openinference.instrumentation.pydantic_ai.utils import is_openinference_span
from openinference.semconv.resource import ResourceAttributes
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource

from nohiki_llm_client.config.constants import PHOENIX_SERVICE_NAMESPACE


def create_phoenix_resource(project_name: str, service_name: str) -> Resource:
    """Create OpenTelemetry resource with Phoenix/OpenInference attributes.

    Args:
        project_name: Phoenix project name for trace grouping.
        service_name: Service identifier.

    Returns:
        Configured Resource instance.

    """
    return Resource.create(
        {
            ResourceAttributes.PROJECT_NAME: project_name,
            "service.name": service_name,
            "service.namespace": PHOENIX_SERVICE_NAMESPACE,
        }
    )


def create_grpc_exporter(endpoint: str, timeout_seconds: float) -> OTLPSpanExporter:
    """Create gRPC OTLP span exporter for Phoenix.

    Args:
        endpoint: Phoenix collector gRPC endpoint.
        timeout_seconds: Export timeout.

    Returns:
        Configured OTLPSpanExporter instance.

    """
    return OTLPSpanExporter(
        endpoint=endpoint.removesuffix("/"),
        insecure=True,
        timeout=int(timeout_seconds),
    )


def create_openinference_processor() -> OpenInferenceSpanProcessor:
    """Create OpenInference span processor to enhance PydanticAI spans.

    Returns:
        OpenInferenceSpanProcessor that adds semantic attributes.

    """
    return OpenInferenceSpanProcessor(span_filter=is_openinference_span)
