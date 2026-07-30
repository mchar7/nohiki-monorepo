"""Unit tests for shared structured logging contracts."""

import uuid
from collections.abc import Iterator
from typing import TypedDict

import pytest
import structlog
from structlog.testing import LogCapture

from tests._helpers import TEST_USER_ID


class _ErrorScenario(TypedDict):
    service: str
    error_type: str
    error_message: str
    context: dict[str, str | int | list[str]]


class _UserActivity(TypedDict):
    service: str
    activity: str
    user_id: str
    metadata: dict[str, str | list[str]]


class _SecurityEvent(TypedDict):
    service: str
    event_type: str
    severity: str
    log_level: str
    details: dict[str, str | int]


class _BusinessMetric(TypedDict):
    service: str
    metric: str
    value: int
    dimensions: dict[str, str]


class _AggregationScenario(TypedDict):
    service: str
    message: str
    level: str
    structured_data: dict[str, str | int | float]


@pytest.fixture
def log_output() -> LogCapture:
    """Capture structured log event dictionaries."""
    return LogCapture()


@pytest.fixture(autouse=True)
def _configure_structlog(log_output: LogCapture) -> Iterator[None]:
    """Isolate structlog's process-global configuration for every test."""
    structlog.reset_defaults()
    structlog.configure(processors=[log_output], cache_logger_on_first_use=False)
    yield
    structlog.reset_defaults()


class TestObservabilityContracts:
    """Test shared structured logging event contracts."""

    def test_structured_logging_consistency(self, log_output: LogCapture) -> None:
        """Test that each service emits structured events at the requested levels."""
        services = [
            "user-service",
            "job-scraper-service",
            "job-ingest-enrichment-service",
            "scrape-post-process-service",
        ]
        expected: list[dict[str, object]] = []

        for service in services:
            test_id = f"test_{service}_{uuid.uuid4().hex[:8]}"
            logger = structlog.get_logger(service)
            logger.info("Testing structured logging", service=service, test_id=test_id)
            logger.warning("Testing warning level", service=service, test_id=test_id)
            logger.error("Testing error level", service=service, test_id=test_id)
            expected.extend(
                [
                    {
                        "event": "Testing structured logging",
                        "service": service,
                        "test_id": test_id,
                        "log_level": "info",
                    },
                    {
                        "event": "Testing warning level",
                        "service": service,
                        "test_id": test_id,
                        "log_level": "warning",
                    },
                    {
                        "event": "Testing error level",
                        "service": service,
                        "test_id": test_id,
                        "log_level": "error",
                    },
                ]
            )

        assert log_output.entries == expected

    def test_correlation_id_propagation(self, log_output: LogCapture) -> None:
        """Test that each service emits the same correlation ID."""
        correlation_id = str(uuid.uuid4())
        service_chain = [
            ("user-service", "role_updated"),
            ("job-scraper-service", "scraping_started"),
            ("scrape-post-process-service", "processing_started"),
            ("job-ingest-enrichment-service", "enrichment_started"),
        ]

        for service, operation in service_chain:
            structlog.get_logger(service).info(
                "Operation started",
                service=service,
                operation=operation,
                correlation_id=correlation_id,
            )

        assert log_output.entries == [
            {
                "event": "Operation started",
                "service": service,
                "operation": operation,
                "correlation_id": correlation_id,
                "log_level": "info",
            }
            for service, operation in service_chain
        ]

    def test_error_logging_and_tracking(self, log_output: LogCapture) -> None:
        """Test error event fields emitted by each service."""
        error_scenarios: list[_ErrorScenario] = [
            {
                "service": "job-scraper-service",
                "error_type": "ScrapingError",
                "error_message": "Failed to scrape job listings",
                "context": {"source": "indeed", "search_terms": ["python", "developer"]},
            },
            {
                "service": "job-ingest-enrichment-service",
                "error_type": "EnrichmentError",
                "error_message": "Failed to enrich job listing",
                "context": {"listing_id": "123", "retry_count": 3},
            },
            {
                "service": "user-service",
                "error_type": "DatabaseError",
                "error_message": "Connection timeout to PostgreSQL",
                "context": {"operation": "user_lookup", "timeout": 30},
            },
        ]

        for scenario in error_scenarios:
            structlog.get_logger(scenario["service"]).error(
                scenario["error_message"],
                service=scenario["service"],
                error_type=scenario["error_type"],
                **scenario["context"],
            )

        assert log_output.entries == [
            {
                "event": scenario["error_message"],
                "service": scenario["service"],
                "error_type": scenario["error_type"],
                **scenario["context"],
                "log_level": "error",
            }
            for scenario in error_scenarios
        ]

    def test_performance_metrics_logging(self, log_output: LogCapture) -> None:
        """Test performance event fields emitted by each service."""
        performance_scenarios = [
            {
                "service": "job-scraper-service",
                "operation": "scrape_jobs",
                "duration_ms": 2500,
                "jobs_found": 15,
                "success_rate": 0.93,
            },
            {
                "service": "job-ingest-enrichment-service",
                "operation": "enrich_listing",
                "duration_ms": 1200,
                "listings_enriched": 10,
                "success_rate": 0.95,
            },
            {
                "service": "scrape-post-process-service",
                "operation": "process_job_batch",
                "duration_ms": 800,
                "jobs_processed": 10,
                "success_rate": 1.0,
            },
        ]

        for scenario in performance_scenarios:
            structlog.get_logger(scenario["service"]).info("Operation completed", **scenario)

        assert log_output.entries == [
            {"event": "Operation completed", **scenario, "log_level": "info"} for scenario in performance_scenarios
        ]

    def test_user_activity_tracking(self, log_output: LogCapture) -> None:
        """Test user activity event fields emitted by each service."""
        user_activities: list[_UserActivity] = [
            {
                "service": "user-service",
                "activity": "user_login",
                "user_id": TEST_USER_ID,
                "metadata": {"login_method": "oauth", "provider": "google"},
            },
            {
                "service": "user-service",
                "activity": "role_created",
                "user_id": TEST_USER_ID,
                "metadata": {"role_name": "Python Developer", "search_keywords": ["python", "django"]},
            },
            {
                "service": "job-scraper-service",
                "activity": "job_search_initiated",
                "user_id": TEST_USER_ID,
                "metadata": {"search_terms": ["python"], "sources": ["indeed"]},
            },
        ]

        for activity in user_activities:
            structlog.get_logger(activity["service"]).info(
                "Account activity logged",
                service=activity["service"],
                activity=activity["activity"],
                user_id=activity["user_id"],
                **activity["metadata"],
            )

        assert log_output.entries == [
            {
                "event": "Account activity logged",
                "service": activity["service"],
                "activity": activity["activity"],
                "user_id": activity["user_id"],
                **activity["metadata"],
                "log_level": "info",
            }
            for activity in user_activities
        ]

    def test_security_event_logging(self, log_output: LogCapture) -> None:
        """Test security event fields and severity-dependent log levels."""
        security_events: list[_SecurityEvent] = [
            {
                "service": "user-service",
                "event_type": "authentication_failure",
                "severity": "warning",
                "log_level": "warning",
                "details": {"user_id": TEST_USER_ID, "reason": "invalid_credentials", "ip_address": "192.168.1.100"},
            },
            {
                "service": "user-service",
                "event_type": "suspicious_activity",
                "severity": "high",
                "log_level": "error",
                "details": {"user_id": TEST_USER_ID, "activity": "multiple_failed_logins", "count": 5},
            },
            {
                "service": "job-ingest-enrichment-service",
                "event_type": "config_update",
                "severity": "info",
                "log_level": "info",
                "details": {"config_key": "enrichment_model", "updated_at": "2024-01-15T10:30:00Z"},
            },
        ]

        for event in security_events:
            logger = structlog.get_logger(event["service"])
            fields = {
                "service": event["service"],
                "event_type": event["event_type"],
                "severity": event["severity"],
                **event["details"],
            }
            match event["log_level"]:
                case "error":
                    logger.error("Security event detected", **fields)
                case "warning":
                    logger.warning("Security event detected", **fields)
                case "info":
                    logger.info("Security event detected", **fields)
                case unexpected:
                    pytest.fail(f"Unsupported security log level: {unexpected}")

        assert log_output.entries == [
            {
                "event": "Security event detected",
                "service": event["service"],
                "event_type": event["event_type"],
                "severity": event["severity"],
                **event["details"],
                "log_level": event["log_level"],
            }
            for event in security_events
        ]

    def test_business_metrics_tracking(self, log_output: LogCapture) -> None:
        """Test business metric event fields emitted by each service."""
        business_metrics: list[_BusinessMetric] = [
            {
                "service": "job-scraper-service",
                "metric": "jobs_scraped_daily",
                "value": 1250,
                "dimensions": {"source": "indeed", "date": "2024-01-15"},
            },
            {
                "service": "job-ingest-enrichment-service",
                "metric": "listings_enriched",
                "value": 450,
                "dimensions": {"source": "indeed", "date": "2024-01-15"},
            },
            {
                "service": "user-service",
                "metric": "active_users",
                "value": 150,
                "dimensions": {"period": "daily", "date": "2024-01-15"},
            },
        ]

        for metric in business_metrics:
            structlog.get_logger(metric["service"]).info(
                "Business metric recorded",
                service=metric["service"],
                metric_name=metric["metric"],
                metric_value=metric["value"],
                **metric["dimensions"],
            )

        assert log_output.entries == [
            {
                "event": "Business metric recorded",
                "service": metric["service"],
                "metric_name": metric["metric"],
                "metric_value": metric["value"],
                **metric["dimensions"],
                "log_level": "info",
            }
            for metric in business_metrics
        ]

    def test_distributed_tracing_context(self, log_output: LogCapture) -> None:
        """Test that each service emits the same trace and span context."""
        trace_id = str(uuid.uuid4())
        span_id = str(uuid.uuid4())
        service_flow = [
            ("user-service", "handle_role_update"),
            ("job-scraper-service", "trigger_job_scraping"),
            ("job-scraper-service", "execute_scraping"),
            ("scrape-post-process-service", "process_results"),
            ("job-ingest-enrichment-service", "enrich_listings"),
        ]

        for service, operation in service_flow:
            structlog.get_logger(service).info(
                "Operation executed",
                service=service,
                operation=operation,
                trace_id=trace_id,
                span_id=span_id,
                user_id=TEST_USER_ID,
            )

        assert log_output.entries == [
            {
                "event": "Operation executed",
                "service": service,
                "operation": operation,
                "trace_id": trace_id,
                "span_id": span_id,
                "user_id": TEST_USER_ID,
                "log_level": "info",
            }
            for service, operation in service_flow
        ]

    def test_log_aggregation_compatibility(self, log_output: LogCapture) -> None:
        """Test aggregation events retain their event names, levels, and structured fields."""
        scenarios: list[_AggregationScenario] = [
            {
                "service": "job-scraper-service",
                "message": "Listing scraping completed successfully",
                "level": "info",
                "structured_data": {
                    "jobs_found": 25,
                    "duration_seconds": 45.2,
                    "source": "indeed",
                    "user_id": TEST_USER_ID,
                },
            },
            {
                "service": "job-ingest-enrichment-service",
                "message": "Enrichment processing failed",
                "level": "error",
                "structured_data": {
                    "error_code": "ENRICHMENT_FAILED",
                    "listing_id": "123",
                    "retry_count": 3,
                    "user_id": TEST_USER_ID,
                },
            },
        ]

        for scenario in scenarios:
            logger = structlog.get_logger(scenario["service"])
            fields = {"service": scenario["service"], **scenario["structured_data"]}
            match scenario["level"]:
                case "error":
                    logger.error(scenario["message"], **fields)
                case "info":
                    logger.info(scenario["message"], **fields)
                case unexpected:
                    pytest.fail(f"Unsupported aggregation log level: {unexpected}")

        assert log_output.entries == [
            {
                "event": scenario["message"],
                "service": scenario["service"],
                **scenario["structured_data"],
                "log_level": scenario["level"],
            }
            for scenario in scenarios
        ]
