"""Factory functions for creating Kafka clients from settings."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

from nohiki_kafka_client.client.auto_client import AutoKafkaClient, _get_global_instance, _set_global_instance
from nohiki_kafka_client.config import (
    AutoClientConfig,
    ConsumerConfig,
    GlobalDLQConfig,
    KafkaClientConfig,
    ObservabilityConfig,
    SecurityConfig,
)
from nohiki_kafka_client.handlers import DLQStrategy

if TYPE_CHECKING:
    from nohiki_core_settings import ObservabilitySettings

    from nohiki_kafka_client.config import KafkaSettings


@runtime_checkable
class HasKafkaSettings(Protocol):
    """Protocol for settings objects that have Kafka configuration."""

    @property
    def service_name(self) -> str:
        """Service name for identification."""
        ...

    @property
    def kafka(self) -> KafkaSettings:
        """Kafka configuration settings."""
        ...

    @property
    def observability(self) -> ObservabilitySettings:
        """Observability configuration settings."""
        ...


def create_kafka_client(
    settings: HasKafkaSettings,
    *,
    auto_start_consumers: bool = False,
) -> AutoKafkaClient:
    """Create a Kafka client from service settings.

    This is the recommended way to create a Kafka client in services.
    It extracts the necessary configuration from the settings object
    and creates a properly configured AutoKafkaClient.

    Args:
        settings: Service settings object with kafka, observability, and redis fields
        auto_start_consumers: If False, consumers won't auto-start on handler registration.
            Call start_consumers() explicitly after service initialization (e.g., after migrations).

    Returns:
        Configured AutoKafkaClient instance

    Example:
        ```python
        from nohiki_kafka_client import create_kafka_client
        from my_service.core.config import get_settings

        settings = get_settings()
        kafka_client = create_kafka_client(settings)

        @kafka_client.message_handler("my-topic.v1", MyMessage)
        async def handle_message(msg: MyMessage, ctx: MessageContext) -> None:
            ...
        ```

    """
    kafka = settings.kafka
    obs = settings.observability

    resilience = kafka.resilience
    dlq_config = GlobalDLQConfig(
        strategy=DLQStrategy(resilience.strategy),
        max_retries=resilience.max_retries,
        retry_backoff_ms=resilience.retry_backoff_ms,
        max_backoff_ms=resilience.max_backoff_ms,
        topic_prefix=resilience.topic_prefix,
    )

    config = KafkaClientConfig(
        bootstrap_servers=kafka.bootstrap_servers,
        consumer=ConsumerConfig(
            group_id=kafka.consumer_group,
            max_poll_records=kafka.consumer.max_poll_records,
            max_poll_interval_ms=kafka.consumer.max_poll_interval_ms,
            session_timeout_ms=kafka.consumer.session_timeout_ms,
            heartbeat_interval_ms=kafka.consumer.heartbeat_interval_ms,
            max_concurrent_handlers=kafka.consumer.max_concurrent_handlers,
        ),
        security=SecurityConfig(
            protocol=kafka.security.protocol,
            sasl_mechanism=kafka.security.sasl.mechanism,
            sasl_username=kafka.security.sasl.username,
            sasl_password=(
                kafka.security.sasl.password.get_secret_value() if kafka.security.sasl.password is not None else None
            ),
            ssl_ca_location=kafka.security.tls.ca_location,
            ssl_certificate_location=kafka.security.tls.certificate_location,
            ssl_key_location=kafka.security.tls.key_location,
            ssl_key_password=(
                kafka.security.tls.key_password.get_secret_value()
                if kafka.security.tls.key_password is not None
                else None
            ),
        ),
        dlq=dlq_config,
        observability=ObservabilityConfig(
            service_name=settings.service_name,
            log_level=obs.logging.level,
        ),
        default_group_id=kafka.consumer_group,
        auto_client=AutoClientConfig(auto_start_consumers=auto_start_consumers),
    )

    return init_kafka_client(config)


def get_kafka_client() -> AutoKafkaClient:
    """Get the global Kafka client singleton instance.

    Raises:
        RuntimeError: If the client has not been initialized.

    """
    if (instance := _get_global_instance()) is None:
        msg = "AutoKafkaClient not initialized. Call create_kafka_client() or init_kafka_client() first."
        raise RuntimeError(msg)
    return instance


def init_kafka_client(config: KafkaClientConfig) -> AutoKafkaClient:
    """Initialize the global Kafka client singleton.

    Args:
        config: Kafka client configuration.

    Returns:
        The initialized AutoKafkaClient.

    """
    client = AutoKafkaClient(config)
    _set_global_instance(client)
    return client
