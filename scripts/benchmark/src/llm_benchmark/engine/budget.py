"""Pre-dispatch cost reservation and global provider concurrency control."""

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import TypeVar

_T = TypeVar("_T")


class BudgetExhaustedError(RuntimeError):
    """Raised when a call cannot be reserved within the approved budget."""


@dataclass(frozen=True, slots=True)
class BudgetSnapshot:
    """Immutable scheduler accounting totals in USD."""

    cap_usd: float
    reserved_usd: float
    actual_usd: float
    maximum_possible_usd: float
    charged_usd: float


class BudgetScheduler:
    """Reserve worst-case cost before dispatch under one concurrency bound."""

    def __init__(
        self,
        *,
        cap_usd: float,
        max_concurrency: int,
        initial_charged_usd: float = 0.0,
        initial_actual_usd: float = 0.0,
    ) -> None:
        """Initialize an owner-approved budget and provider concurrency bound.

        ``initial_charged_usd`` seeds the committed budget that gates dispatch,
        so a resumed run starts already charged for prior attempts (including
        fail-closed failure reservations). ``initial_actual_usd`` seeds only the
        reported realized provider spend and never affects the cap.
        """
        if cap_usd < 0:
            msg = "cap_usd must be non-negative"
            raise ValueError(msg)
        if max_concurrency < 1:
            msg = "max_concurrency must be at least 1"
            raise ValueError(msg)
        if initial_charged_usd < 0 or initial_charged_usd > cap_usd:
            msg = "initial_charged_usd must be within the approved budget"
            raise ValueError(msg)
        if initial_actual_usd < 0:
            msg = "initial_actual_usd must be non-negative"
            raise ValueError(msg)
        self._cap_usd = cap_usd
        self._semaphore = asyncio.Semaphore(max_concurrency)
        self._lock = asyncio.Lock()
        self._reserved_usd = 0.0
        self._actual_usd = initial_actual_usd
        self._maximum_possible_usd = initial_charged_usd
        self._charged_usd = initial_charged_usd

    @property
    def snapshot(self) -> BudgetSnapshot:
        """Return current accounting; call from the scheduler event loop."""
        return BudgetSnapshot(
            cap_usd=self._cap_usd,
            reserved_usd=self._reserved_usd,
            actual_usd=self._actual_usd,
            maximum_possible_usd=self._maximum_possible_usd,
            charged_usd=self._charged_usd,
        )

    async def run(
        self,
        maximum_cost_usd: float,
        call: Callable[[], Awaitable[tuple[_T, float | None]]],
    ) -> _T:
        """Reserve, dispatch, and settle one provider call.

        The callable must return its value and actual provider cost. If actual
        cost is unavailable, the full reservation is charged conservatively.
        """
        if maximum_cost_usd < 0:
            msg = "maximum_cost_usd must be non-negative"
            raise ValueError(msg)
        async with self._lock:
            committed = self._charged_usd + self._reserved_usd
            if committed + maximum_cost_usd > self._cap_usd:
                msg = (
                    f"Call reservation ${maximum_cost_usd:.6f} exceeds remaining "
                    f"budget ${max(0.0, self._cap_usd - committed):.6f}"
                )
                raise BudgetExhaustedError(msg)
            self._reserved_usd += maximum_cost_usd
            self._maximum_possible_usd += maximum_cost_usd

        dispatched = False
        try:
            async with self._semaphore:
                dispatched = True
                value, actual_cost_usd = await call()
        except BaseException:
            await self._settle(
                maximum_cost_usd,
                actual_usd=None,
                charged_usd=maximum_cost_usd if dispatched else 0.0,
            )
            raise

        if actual_cost_usd is not None and (actual_cost_usd < 0 or actual_cost_usd > maximum_cost_usd):
            await self._settle(maximum_cost_usd, actual_usd=None, charged_usd=maximum_cost_usd)
            msg = f"Actual cost ${actual_cost_usd:.6f} is outside reserved maximum ${maximum_cost_usd:.6f}"
            raise ValueError(msg)
        charged_cost = maximum_cost_usd if actual_cost_usd is None else actual_cost_usd
        await self._settle(maximum_cost_usd, actual_usd=actual_cost_usd, charged_usd=charged_cost)
        return value

    async def _settle(
        self,
        reserved_usd: float,
        *,
        actual_usd: float | None,
        charged_usd: float,
    ) -> None:
        async with self._lock:
            self._reserved_usd -= reserved_usd
            self._charged_usd += charged_usd
            if actual_usd is not None:
                self._actual_usd += actual_usd
