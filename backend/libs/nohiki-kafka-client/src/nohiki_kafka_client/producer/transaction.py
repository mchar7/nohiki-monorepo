"""Kafka transaction context manager for aiokafka."""

from __future__ import annotations

from typing import TYPE_CHECKING, Self

from aiokafka import AIOKafkaProducer
from aiokafka.errors import KafkaError
from nohiki_observability import get_logger

from nohiki_kafka_client.exceptions import ProducerError

if TYPE_CHECKING:
    import types

logger = get_logger(__name__)


class Transaction:
    """Kafka transaction with async context manager for begin/commit/abort."""

    __slots__ = ("_active", "_producer", "_transaction_id")

    def __init__(self, producer: AIOKafkaProducer, transaction_id: str) -> None:
        """Initialize transaction with producer and ID."""
        self._producer = producer
        self._transaction_id = transaction_id
        self._active = False

    async def __aenter__(self) -> Self:
        """Begin the transaction."""
        try:
            await self._producer.begin_transaction()
            self._active = True
            logger.debug("Transaction started", transaction_id=self._transaction_id)
        except KafkaError as e:
            msg = f"Failed to start transaction {self._transaction_id}"
            raise ProducerError(msg, details={"error": str(e)}) from e
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: types.TracebackType | None,
    ) -> None:
        """Commit or abort the transaction based on exception state."""
        if not self._active:
            return
        try:
            if exc_type is None:
                await self._producer.commit_transaction()
                logger.debug("Transaction committed", transaction_id=self._transaction_id)
            else:
                await self._producer.abort_transaction()
                logger.warning(
                    "Transaction aborted",
                    transaction_id=self._transaction_id,
                    error=str(exc_val),
                )
        except KafkaError as e:
            msg = f"Failed to finalize transaction {self._transaction_id}"
            raise ProducerError(msg, details={"error": str(e)}) from e
        finally:
            self._active = False

    async def abort(self) -> None:
        """Explicitly abort the transaction."""
        if self._active:
            await self._producer.abort_transaction()
            self._active = False
            logger.info("Transaction manually aborted", transaction_id=self._transaction_id)
