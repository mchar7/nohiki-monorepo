"""Template registry for notification event handling.

A declarative mapping of event types to template
configurations, enabling domain-agnostic notification handling.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING
from urllib.parse import urlparse

from jinja2 import Environment, PackageLoader, StrictUndefined, select_autoescape
from nohiki.doc.content.v1 import ContentGenerationCompleted
from nohiki.job.correlation.v1 import CorrelationEvaluated

if TYPE_CHECKING:
    from collections.abc import Callable

# Type alias for events that can trigger notifications
NotificationEvent = CorrelationEvaluated | ContentGenerationCompleted

_TEMPLATE_ENV = Environment(
    loader=PackageLoader("notification_service", "templates"),
    autoescape=select_autoescape(enabled_extensions=("html", "xml"), default_for_string=True),
    undefined=StrictUndefined,
)


def render_template(template_name: str, context: dict[str, str | int | None]) -> str:
    """Render a packaged notification template with strict HTML escaping."""
    return _TEMPLATE_ENV.get_template(f"{template_name}.html").render(context)


def _safe_http_url(value: str | None) -> str | None:
    """Allow only absolute HTTP(S) links in email attributes."""
    if not value:
        return None
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return None
    return value


@dataclass(frozen=True, slots=True)
class TemplateConfig:
    """Configuration for rendering a notification from an event.

    Attributes:
        template_name: Name of the email template to use.
        subject_template: Python format string for email subject.
        context_extractor: Function to extract template context from event.
        score_extractor: Function to extract score for threshold check (None if N/A).
        uses_threshold: Whether this notification uses threshold checking.
        requires_completed_status: Whether to check result.status == COMPLETED.

    """

    template_name: str
    subject_template: str
    context_extractor: Callable[[NotificationEvent], dict[str, str | int | None]]
    score_extractor: Callable[[NotificationEvent], int | None]
    uses_threshold: bool = True
    requires_completed_status: bool = False


def extract_job_match_context(event: NotificationEvent) -> dict[str, str | int | None]:
    """Extract template context from CorrelationEvaluated event.

    Args:
        event: The notification event (must be CorrelationEvaluated).

    Returns:
        Dictionary with template context variables.

    Raises:
        TypeError: If event is not CorrelationEvaluated.
        ValueError: If listing_snapshot is missing.

    """
    if not isinstance(event, CorrelationEvaluated):
        msg = f"Expected CorrelationEvaluated, got {type(event).__name__}"
        raise TypeError(msg)

    if event.listing_snapshot is None:
        msg = "CorrelationEvaluated.listing_snapshot is required but was None"
        raise ValueError(msg)

    listing = event.listing_snapshot

    return {
        "listing_title": listing.title,
        "company_name": listing.company_name,
        "listing_url": _safe_http_url(listing.listing_url),
        "fit_score": event.fit_score,
        "correlation_id": event.correlation_id,
        "listing_id": listing.id,
    }


def extract_content_generation_context(event: NotificationEvent) -> dict[str, str | int | None]:
    """Extract template context from ContentGenerationCompleted event.

    Args:
        event: The notification event (must be ContentGenerationCompleted).

    Returns:
        Dictionary with template context variables.

    Raises:
        TypeError: If event is not ContentGenerationCompleted.
        ValueError: If listing_id is empty.

    """
    if not isinstance(event, ContentGenerationCompleted):
        msg = f"Expected ContentGenerationCompleted, got {type(event).__name__}"
        raise TypeError(msg)

    if not event.listing_id:
        msg = "ContentGenerationCompleted.listing_id is required but was empty"
        raise ValueError(msg)

    listing = event.listing_snapshot

    return {
        "listing_title": listing.title if listing else None,
        "company_name": listing.company_name if listing else None,
        "request_id": event.request_id,
        "listing_id": event.listing_id,
    }


def _job_match_score_extractor(event: NotificationEvent) -> int | None:
    """Extract fit_score from CorrelationEvaluated.

    Args:
        event: The notification event.

    Returns:
        The fit_score value if event is CorrelationEvaluated, None otherwise.

    """
    if isinstance(event, CorrelationEvaluated):
        return event.fit_score
    return None


def _no_score(_event: NotificationEvent) -> None:
    """Return None for events without score-based threshold.

    Args:
        _event: The event (unused).

    Returns:
        None, indicating no score-based threshold applies.

    """


# Event type fully qualified names
EVENT_TYPE_CORRELATION_EVALUATED = "nohiki.job.correlation.v1.CorrelationEvaluated"
EVENT_TYPE_CONTENT_GENERATION_COMPLETED = "nohiki.doc.content.v1.ContentGenerationCompleted"


TEMPLATE_REGISTRY: dict[str, TemplateConfig] = {
    EVENT_TYPE_CORRELATION_EVALUATED: TemplateConfig(
        template_name="job_match",
        subject_template="New Job Match: {listing_title} at {company_name}",
        context_extractor=extract_job_match_context,
        score_extractor=_job_match_score_extractor,
        uses_threshold=True,
        requires_completed_status=False,
    ),
    EVENT_TYPE_CONTENT_GENERATION_COMPLETED: TemplateConfig(
        template_name="content_generation_completed",
        subject_template="Your Generated Document for {listing_title}",
        context_extractor=extract_content_generation_context,
        score_extractor=_no_score,
        uses_threshold=False,
        requires_completed_status=True,
    ),
}


def get_template_config(event_type: str) -> TemplateConfig | None:
    """Get template configuration for an event type.

    Args:
        event_type: Fully qualified event type name.

    Returns:
        TemplateConfig if registered, None otherwise.

    """
    return TEMPLATE_REGISTRY.get(event_type)
