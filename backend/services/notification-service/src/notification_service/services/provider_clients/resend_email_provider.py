"""Resend email provider implementation using httpx."""

from __future__ import annotations

import asyncio
import os
import time
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any, ClassVar

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


class ResendEmailProvider(BaseProvider):
    """Resend email provider using httpx."""

    channel: ClassVar[NotificationChannel] = NotificationChannel.EMAIL
    name: ClassVar[str] = "resend"
    required_secrets: ClassVar[list[str]] = ["resend_api_key"]

    def __init__(self, config: EmailConfig) -> None:
        """Initialize the Resend provider."""
        super().__init__(config)
        self.api_key = (
            config.api_key
            if config.provider_name == self.name and config.api_key
            else os.environ.get("RESEND_API_KEY", "")
        )

        self.base_url = "https://api.resend.com"
        self._headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        self._client: httpx.AsyncClient | None = None

        self._last_validation_time: datetime | None = None
        self._validation_cache_ttl = timedelta(minutes=15)
        self._validation_result: bool = False

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

    @tracer.start_as_current_span("resend.send")
    async def send(self, message: Message) -> ProviderResult:
        """Send email via Resend REST API."""
        metrics = get_notification_provider_metrics()
        start_time = time.perf_counter()
        layout_id = str(message.external_layout_id) if message.external_layout_id else "unknown"
        recipient_domain = self._extract_domain(message.recipient) if message.recipient else None

        try:
            payload = self._create_mail_payload(message)

            response = await self._http.post(
                "/emails",
                json=payload,
                headers={"Idempotency-Key": str(message.id)},
            )
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
        """Handle Resend response."""
        if response.status_code == status.HTTP_200_OK:
            try:
                data = response.json()
                provider_msg_id = data.get("id")
            except ValueError, KeyError, TypeError:
                provider_msg_id = None

            logger.info("Email sent", message_id=str(message.id))
            return ProviderResult(success=True, provider_msg_id=provider_msg_id)

        error_msg = self._parse_error_response(response)
        logger.error(
            "Resend error",
            message_id=str(message.id),
            status_code=response.status_code,
        )

        return ProviderResult(
            success=False,
            error=f"Resend error {response.status_code}: {error_msg}",
            retryable=self._is_retryable_error(response.status_code),
            retry_after_seconds=parse_retry_after(getattr(response, "headers", {}).get("Retry-After")),
        )

    def _handle_http_status_error(self, message: Message, error: httpx.HTTPStatusError) -> ProviderResult:
        """Handle HTTPStatusError from httpx."""
        error_msg = self._parse_error_response(error.response)
        logger.exception(
            "Resend HTTP error",
            message_id=str(message.id),
            status_code=error.response.status_code,
        )

        return ProviderResult(
            success=False,
            error=f"Resend HTTP error {error.response.status_code}: {error_msg}",
            retryable=self._is_retryable_error(error.response.status_code),
            retry_after_seconds=parse_retry_after(getattr(error.response, "headers", {}).get("Retry-After")),
        )

    def _create_mail_payload(self, message: Message) -> dict[str, Any]:
        """Create Resend mail payload."""
        if not message.recipient or not message.subject or not message.body:
            msg = "Missing required fields: recipient, subject, or body"
            raise ValueError(msg)

        payload: dict[str, Any] = {
            "from": f"{self.config.from_name} <{self.config.from_address}>",
            "to": [message.recipient],
            "subject": message.subject,
            "html": message.body,
        }

        if message.provider_payload and "text_alt" in message.provider_payload:
            text_content = message.provider_payload["text_alt"]
            if text_content and text_content.strip():
                payload["text"] = text_content

        if message.id or message.user_id:
            headers: dict[str, str] = {}
            if message.id:
                headers["X-Message-ID"] = str(message.id)
            if message.user_id:
                headers["X-Account-ID"] = str(message.user_id)
                headers["List-Unsubscribe"] = (
                    f"<mailto:unsubscribe@{self.config.unsubscribe_domain}?subject=unsubscribe:{message.user_id}>"
                )

            if headers:
                payload["headers"] = headers

        return payload

    def _parse_error_response(self, response: httpx.Response) -> str:
        """Parse Resend error response."""
        try:
            data = response.json()
            if isinstance(data, dict):
                if "message" in data:
                    return str(data["message"])
                if "error" in data:
                    return str(data["error"])
        except (ValueError, KeyError, TypeError) as e:
            logger.warning("Error parsing Resend response", error=str(e))
            return response.text or "Unknown error"
        else:
            return response.text or "Unknown error"

    @tracer.start_as_current_span("resend.validate_config")
    async def validate_config(self) -> bool:
        """Validate Resend configuration with caching and retry logic."""
        current_time = datetime.now(UTC)

        if self._last_validation_time and current_time - self._last_validation_time < self._validation_cache_ttl:
            return self._validation_result

        if not self.api_key:
            logger.error("Resend API key is missing")
            self._update_validation_cache(is_valid=False)
            return False

        if self.api_key != "test_api_key" and not self.api_key.startswith("re_"):
            logger.error("Resend API key is invalid (incorrect format)")
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
                logger.exception("Resend validation error", error=str(e))
                return False
            except Exception as e:
                logger.exception("Unexpected error during Resend validation", error=str(e))
                return False

        return False

    async def _attempt_validation(self) -> bool:
        """Attempt a single validation request to Resend."""
        response = await self._http.get("/api-keys")

        if response.status_code == status.HTTP_200_OK:
            logger.info("Resend API key validated")
            return True

        if response.status_code == status.HTTP_403_FORBIDDEN:
            logger.error("Resend API key is invalid or lacks permissions")
            return False

        logger.error("Resend validation failed", status_code=response.status_code)
        return False

    def _should_retry_dns_error(self, error: httpx.ConnectError, attempt: int, max_retries: int) -> bool:
        """Check if DNS error should be retried."""
        if "No address associated with hostname" not in str(error):
            logger.exception("Resend validation connection error", error=str(error))
            return False

        if attempt >= max_retries - 1:
            logger.error("DNS resolution failed after all retries", error=str(error))
            return False

        logger.warning(
            "DNS resolution failed, retrying",
            attempt=attempt + 1,
            max_retries=max_retries,
            error=str(error),
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
        """Check if error is retryable based on Resend documentation."""
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
