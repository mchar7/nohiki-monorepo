"""SendGrid email provider implementation using httpx."""

from __future__ import annotations

import asyncio
import os
import time
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any, ClassVar, cast

import httpx
from fastapi import status
from nohiki.common.v1 import NotificationChannel
from nohiki_observability import get_logger
from opentelemetry import trace

from notification_service.core.provider_metrics import (
    NotificationProviderMetrics,
    SendMetricData,
    get_notification_provider_metrics,
)
from notification_service.core.providers import BaseProvider, EmailConfig, ProviderResult, parse_retry_after
from notification_service.services.provider_clients.http_pool import build_pooled_client

if TYPE_CHECKING:
    from notification_service.db.models import Message

logger = get_logger(__name__)
tracer = trace.get_tracer(__name__)

_UNKNOWN_ERROR = "Unknown error"


class TwilioSendGridProvider(BaseProvider):
    """SendGrid email provider using httpx."""

    channel: ClassVar[NotificationChannel] = NotificationChannel.EMAIL
    name: ClassVar[str] = "twilio_sendgrid"
    required_secrets: ClassVar[list[str]] = ["sendgrid_api_key"]

    def __init__(self, config: EmailConfig) -> None:
        """Initialize the SendGrid provider."""
        super().__init__(config)
        self.api_key = (
            config.api_key
            if config.provider_name == self.name and config.api_key
            else os.environ.get("SENDGRID_API_KEY", "")
        )

        self.base_url = "https://api.sendgrid.com/v3"
        self._headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        self._client: httpx.AsyncClient | None = None

        # Cache validation results for 15 minutes to avoid excessive API calls
        self._last_validation_time: datetime | None = None
        self._validation_cache_ttl = timedelta(minutes=15)
        self._validation_result: bool = False

        # Don't validate during startup - wait until actually needed
        self._validation_task: asyncio.Task[None] | None = None

    @property
    def _http(self) -> httpx.AsyncClient:
        """Pooled client, built on first use and reused by every later call.

        Built lazily rather than in ``__init__`` so the pool is bound to the
        loop that actually drives sends, not to whichever thread happened to
        register the provider.
        """
        if self._client is None:
            self._client = build_pooled_client(base_url=self.base_url, headers=self._headers)
        return self._client

    @tracer.start_as_current_span("twilio_sendgrid.send")
    async def send(self, message: Message) -> ProviderResult:
        """Send email via SendGrid REST API."""
        metrics = get_notification_provider_metrics()
        start_time = time.perf_counter()
        layout_id = str(message.external_layout_id) if message.external_layout_id else "unknown"
        recipient_domain = self._extract_domain(message.recipient) if message.recipient else None

        try:
            payload = self._create_mail_payload(message)

            response = await self._http.post("/mail/send", json=payload)
            if response.status_code == status.HTTP_429_TOO_MANY_REQUESTS:
                metrics.record_rate_limit(self.name, "email")
            result = self._handle_response(message, response)
        except httpx.HTTPStatusError as e:
            if e.response.status_code == status.HTTP_429_TOO_MANY_REQUESTS:
                metrics.record_rate_limit(self.name, "email")
            result = self._handle_http_status_error(message, e)
            self._record_send_metric(metrics, start_time, layout_id, recipient_domain, success=False)
            return result
        except httpx.RequestError as e:
            logger.exception("Network error", message_id=str(message.id), error=str(e))
            self._record_send_metric(metrics, start_time, layout_id, recipient_domain, success=False)
            return ProviderResult(success=False, error=f"Network error: {e}", retryable=True)
        except ValueError as e:
            logger.exception("Message validation failed", message_id=str(message.id), error=str(e))
            self._record_send_metric(metrics, start_time, layout_id, recipient_domain, success=False)
            return ProviderResult(success=False, error=f"Validation error: {e}", retryable=False)
        except Exception as e:
            logger.exception("Unexpected error during send", message_id=str(message.id), error=str(e))
            self._record_send_metric(metrics, start_time, layout_id, recipient_domain, success=False)
            return ProviderResult(success=False, error=f"Unexpected error: {e}", retryable=True)
        else:
            self._record_send_metric(metrics, start_time, layout_id, recipient_domain, success=result.success)
            return result

    def _record_send_metric(
        self,
        metrics: NotificationProviderMetrics,
        start_time: float,
        layout_id: str,
        recipient_domain: str | None,
        *,
        success: bool,
    ) -> None:
        """Record send metrics."""
        duration = time.perf_counter() - start_time
        metrics.record_send(
            SendMetricData(
                provider=self.name,
                channel="email",
                template=layout_id,
                duration_seconds=duration,
                success=success,
                recipient_domain=recipient_domain,
            )
        )

    def _handle_response(self, message: Message, response: httpx.Response) -> ProviderResult:
        """Handle SendGrid response."""
        if response.status_code == status.HTTP_202_ACCEPTED:
            logger.info("Email sent", message_id=str(message.id))
            provider_msg_id = response.headers.get("X-Message-Id")
            return ProviderResult(success=True, provider_msg_id=provider_msg_id)

        error_msg = self._parse_error_response(response)
        logger.error("SendGrid error", message_id=str(message.id), status_code=response.status_code)

        return ProviderResult(
            success=False,
            error=f"SendGrid error {response.status_code}: {error_msg}",
            retryable=self._is_retryable_error(response.status_code),
            retry_after_seconds=parse_retry_after(getattr(response, "headers", {}).get("Retry-After")),
        )

    def _handle_http_status_error(self, message: Message, error: httpx.HTTPStatusError) -> ProviderResult:
        """Handle HTTPStatusError from httpx."""
        error_msg = self._parse_error_response(error.response)
        logger.exception(
            "SendGrid HTTP error",
            message_id=str(message.id),
            status_code=error.response.status_code,
        )

        return ProviderResult(
            success=False,
            error=f"SendGrid HTTP error {error.response.status_code}: {error_msg}",
            retryable=self._is_retryable_error(error.response.status_code),
            retry_after_seconds=parse_retry_after(getattr(error.response, "headers", {}).get("Retry-After")),
        )

    def _create_mail_payload(self, message: Message) -> dict[str, Any]:
        """Create SendGrid mail payload."""
        self._validate_message_fields(message)

        payload: dict[str, Any] = {
            "personalizations": [{"to": [{"email": message.recipient}]}],
            "from": {"email": self.config.from_address, "name": self.config.from_name},
            "subject": message.subject,
            "content": self._build_content(message),
        }

        headers = self._build_headers(message)
        if headers:
            payload["headers"] = headers

        return payload

    def _validate_message_fields(self, message: Message) -> None:
        """Validate required message fields."""
        if not message.recipient or not message.subject or not message.body:
            msg = "Missing required fields: recipient, subject, or body"
            raise ValueError(msg)

    def _build_content(self, message: Message) -> list[dict[str, str]]:
        """Build email content with HTML and optional plain text.

        Note: This method is called after _validate_message which ensures body is not None.
        """
        # Body is validated as non-None in _validate_message
        body = message.body or ""
        content: list[dict[str, str]] = [{"type": "text/html", "value": body}]

        text_alt = self._get_text_alt(message)
        if text_alt:
            content.insert(0, {"type": "text/plain", "value": text_alt})

        return content

    def _get_text_alt(self, message: Message) -> str | None:
        """Extract plain text alternative from provider payload."""
        if not message.provider_payload:
            return None
        text_content = message.provider_payload.get("text_alt")
        if isinstance(text_content, str) and text_content.strip():
            return text_content
        return None

    def _build_headers(self, message: Message) -> dict[str, str]:
        """Build custom headers for the email."""
        headers: dict[str, str] = {}

        if message.id:
            headers["X-Message-ID"] = str(message.id)

        if message.user_id:
            headers["X-Account-ID"] = str(message.user_id)
            headers["List-Unsubscribe"] = (
                f"<mailto:unsubscribe@{self.config.unsubscribe_domain}?subject=unsubscribe:{message.user_id}>"
            )

        return headers

    def _parse_error_response(self, response: httpx.Response) -> str:
        """Parse SendGrid error response."""
        try:
            data = response.json()
            error_messages = self._extract_error_messages(data)
            if error_messages:
                return error_messages
        except (ValueError, KeyError, TypeError) as e:
            logger.warning("Error parsing SendGrid response", error=str(e))
            return response.text or _UNKNOWN_ERROR

        return response.text or _UNKNOWN_ERROR

    def _extract_error_messages(self, data: object) -> str | None:
        """Extract error messages from SendGrid response data."""
        if not isinstance(data, dict):
            return None

        data_dict = cast(dict[str, object], data)
        errors = data_dict.get("errors")
        if not isinstance(errors, list) or not errors:
            return None

        messages = [self._format_error(cast(dict[str, Any], error)) for error in errors if isinstance(error, dict)]
        return "; ".join(messages) if messages else None

    def _format_error(self, error: dict[str, Any]) -> str:
        """Format a single error dict into a message string."""
        msg = error.get("message", _UNKNOWN_ERROR)
        field = error.get("field")
        return f"{field}: {msg}" if field else msg

    @tracer.start_as_current_span("twilio_sendgrid.validate_config")
    async def validate_config(self) -> bool:
        """Validate SendGrid configuration with caching and retry logic for DNS issues."""
        current_time = datetime.now(UTC)

        if self._last_validation_time and current_time - self._last_validation_time < self._validation_cache_ttl:
            return self._validation_result

        if not self.api_key:
            logger.error("SendGrid API key is missing")
            self._update_validation_cache(is_valid=False)
            return False

        if self.api_key != "test_api_key" and not self.api_key.startswith("SG."):
            logger.error("SendGrid API key is invalid (incorrect format)")
            self._update_validation_cache(is_valid=False)
            return False

        is_valid = await self._validate_with_retry()
        self._update_validation_cache(is_valid=is_valid)
        return is_valid

    async def _validate_with_retry(self) -> bool:
        """Validate with exponential backoff retry for DNS resolution issues."""
        max_retries = 3

        for attempt in range(max_retries):
            try:
                return await self._attempt_validation()
            except httpx.ConnectError as e:
                if not self._should_retry_dns_error(e, attempt, max_retries):
                    return False
                await self._wait_before_retry(attempt)
            except (httpx.RequestError, ValueError, KeyError, TypeError) as e:
                logger.exception("SendGrid validation error", error=str(e))
                return False
            except Exception as e:
                logger.exception("Unexpected error during SendGrid validation", error=str(e))
                return False

        return False

    async def _attempt_validation(self) -> bool:
        """Attempt a single validation request to SendGrid."""
        response = await self._http.get("/scopes")

        if response.status_code != status.HTTP_200_OK:
            logger.error("SendGrid validation failed", status_code=response.status_code)
            return False

        return self._validate_scopes_response(response)

    def _validate_scopes_response(self, response: httpx.Response) -> bool:
        """Validate the scopes response from SendGrid."""
        data = response.json()
        if not isinstance(data, dict):
            logger.error("SendGrid scopes response is not a dictionary")
            return False

        scopes = data.get("scopes", [])
        if "mail.send" in scopes:
            logger.info("SendGrid API key validated with mail.send permission")
            return True

        logger.error("SendGrid API key missing mail.send permission", scopes=scopes)
        return False

    def _should_retry_dns_error(self, error: httpx.ConnectError, attempt: int, max_retries: int) -> bool:
        """Check if DNS error should be retried."""
        if "No address associated with hostname" not in str(error):
            logger.exception("SendGrid validation connection error", error=str(error))
            return False

        if attempt >= max_retries - 1:
            logger.error("DNS resolution failed after all retries", error=str(error))
            return False

        logger.warning(
            "DNS resolution failed, retrying", attempt=attempt + 1, max_retries=max_retries, error=str(error)
        )
        return True

    async def _wait_before_retry(self, attempt: int) -> None:
        """Wait before retry with exponential backoff."""
        base_delay = 1.0
        delay = base_delay * (2**attempt)
        await asyncio.sleep(delay)

    def _update_validation_cache(self, *, is_valid: bool) -> None:
        """Update validation cache."""
        self._last_validation_time = datetime.now(UTC)
        self._validation_result = is_valid

    def _is_retryable_error(self, status_code: int) -> bool:
        """Check if error is retryable based on SendGrid documentation."""
        if status_code >= status.HTTP_500_INTERNAL_SERVER_ERROR:
            return True

        return status_code == status.HTTP_429_TOO_MANY_REQUESTS

    @staticmethod
    def _extract_domain(email: str) -> str | None:
        """Extract domain from email address for analytics."""
        if "@" in email:
            return email.rsplit("@", maxsplit=1)[-1].lower()
        return None

    async def aclose(self) -> None:
        """Release the pooled connections and drop the client."""
        if self._client is None:
            return
        client = self._client
        self._client = None
        await client.aclose()
