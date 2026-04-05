"""OpenInference tracing utilities for enriching LLM spans.

Provides context managers for adding domain-specific metadata
to LLM traces beyond auto-instrumentation.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import TYPE_CHECKING, Any

from openinference.instrumentation import using_attributes, using_prompt_template
from opentelemetry import trace

if TYPE_CHECKING:
    from collections.abc import Generator


@contextmanager
def llm_span_context(
    *,
    use_case: str,
    user_id: str | None = None,
    session_id: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> Generator[None]:
    """Context manager to add domain-specific attributes to LLM spans.

    Args:
        use_case: Business use case (e.g., 'resume_tailoring', 'job_enrichment').
        user_id: Optional user identifier for the request.
        session_id: Optional session identifier for multi-turn conversations.
        metadata: Optional additional metadata dict.

    Yields:
        None - use as context manager.

    Example:
        with llm_span_context(use_case="resume_tailoring", user_id="123"):
            result = await client.run(agent, prompt, deps=deps)

    """
    combined_metadata = {"use_case": use_case} | (metadata or {})

    with using_attributes(
        user_id=user_id or "",
        session_id=session_id or "",
        metadata=combined_metadata,
    ):
        yield


@contextmanager
def prompt_template_context(
    *,
    template: str,
    variables: dict[str, Any],
    version: str = "v1",
) -> Generator[None]:
    """Context manager to track prompt template usage in LLM spans.

    Helps with prompt version tracking and A/B testing in Phoenix.

    Args:
        template: The prompt template string with placeholders.
        variables: Dict of template variable values.
        version: Version identifier for the prompt template.

    Yields:
        None - use as context manager.

    Example:
        template = "Summarize this job posting: {job_description}"
        with prompt_template_context(
            template=template,
            variables={"job_description": job.description},
            version="v2.1",
        ):
            result = await client.run(agent, formatted_prompt, deps=deps)

    """
    with using_prompt_template(
        template=template,
        variables=variables,
        version=version,
    ):
        yield


def set_llm_span_feedback(
    *,
    score: float | None = None,
    label: str | None = None,
    explanation: str | None = None,
) -> None:
    """Set feedback/annotation on the current LLM span.

    Call this after receiving user feedback to annotate the trace.

    Args:
        score: Numeric score (e.g., 1-5 rating, 0-1 thumbs).
        label: Categorical label (e.g., 'helpful', 'incorrect').
        explanation: Freeform explanation text.

    """
    span = trace.get_current_span()
    if span is None or not span.is_recording():
        return

    if score is not None:
        span.set_attribute("feedback.score", score)
    if label is not None:
        span.set_attribute("feedback.label", label)
    if explanation is not None:
        span.set_attribute("feedback.explanation", explanation)
