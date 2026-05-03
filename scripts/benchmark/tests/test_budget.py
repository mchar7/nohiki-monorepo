"""Behavior tests for benchmark cost admission."""

import asyncio
from unittest.mock import patch

import pytest
from pydantic_ai.usage import RequestUsage

from llm_benchmark.engine.budget import BudgetExhaustedError, BudgetScheduler
from llm_benchmark.pricing import resolve_maximum_call_cost


@pytest.mark.asyncio
async def test_simultaneous_reservations_admit_only_work_within_cap() -> None:
    scheduler = BudgetScheduler(cap_usd=1.0, max_concurrency=2)
    provider_started = asyncio.Event()
    rejected = asyncio.Event()
    release = asyncio.Event()
    dispatches = 0

    async def provider_call() -> tuple[str, float]:
        nonlocal dispatches
        dispatches += 1
        provider_started.set()
        await release.wait()
        return "completed", 0.4

    async def attempt() -> str | BudgetExhaustedError:
        try:
            return await scheduler.run(0.75, provider_call)
        except BudgetExhaustedError as error:
            rejected.set()
            return error

    tasks = [asyncio.create_task(attempt()) for _ in range(2)]
    await provider_started.wait()
    await rejected.wait()

    assert dispatches == 1
    assert scheduler.snapshot.reserved_usd == pytest.approx(0.75)
    release.set()
    outcomes = await asyncio.gather(*tasks)
    assert sum(outcome == "completed" for outcome in outcomes) == 1
    assert sum(isinstance(outcome, BudgetExhaustedError) for outcome in outcomes) == 1


@pytest.mark.asyncio
async def test_cap_rejection_can_be_retried_after_in_flight_cost_settles() -> None:
    scheduler = BudgetScheduler(cap_usd=0.6, max_concurrency=2)
    started = asyncio.Event()
    release = asyncio.Event()
    rejected_dispatches = 0

    async def first_call() -> tuple[str, float]:
        started.set()
        await release.wait()
        return "first", 0.2

    async def retryable_call() -> tuple[str, float]:
        nonlocal rejected_dispatches
        rejected_dispatches += 1
        return "retried", 0.3

    first = asyncio.create_task(scheduler.run(0.5, first_call))
    await started.wait()
    with pytest.raises(BudgetExhaustedError, match="exceeds remaining budget"):
        await scheduler.run(0.4, retryable_call)
    assert rejected_dispatches == 0

    release.set()
    assert await first == "first"
    assert await scheduler.run(0.39, retryable_call) == "retried"
    assert rejected_dispatches == 1
    assert scheduler.snapshot.charged_usd == pytest.approx(0.5)


@pytest.mark.asyncio
async def test_settlement_distinguishes_actual_cost_from_conservative_charge() -> None:
    scheduler = BudgetScheduler(cap_usd=1.0, max_concurrency=1)

    async def priced_call() -> tuple[str, float]:
        return "priced", 0.25

    async def unreported_call() -> tuple[str, None]:
        return "unreported", None

    assert await scheduler.run(0.5, priced_call) == "priced"
    assert await scheduler.run(0.4, unreported_call) == "unreported"

    snapshot = scheduler.snapshot
    assert snapshot.reserved_usd == pytest.approx(0.0)
    assert snapshot.actual_usd == pytest.approx(0.25)
    assert snapshot.charged_usd == pytest.approx(0.65)
    assert snapshot.maximum_possible_usd == pytest.approx(0.9)


@pytest.mark.asyncio
async def test_one_concurrency_limit_covers_all_provider_calls() -> None:
    scheduler = BudgetScheduler(cap_usd=4.0, max_concurrency=2)
    two_active = asyncio.Event()
    release = asyncio.Event()
    active = 0
    maximum_active = 0
    dispatches = 0

    async def provider_call() -> tuple[int, float]:
        nonlocal active, maximum_active, dispatches
        active += 1
        dispatches += 1
        maximum_active = max(maximum_active, active)
        if active == 2:
            two_active.set()
        await release.wait()
        active -= 1
        return dispatches, 0.1

    tasks = [asyncio.create_task(scheduler.run(0.5, provider_call)) for _ in range(4)]
    await two_active.wait()
    assert dispatches == 2
    assert maximum_active == 2

    release.set()
    await asyncio.gather(*tasks)
    assert dispatches == 4
    assert maximum_active == 2


def test_known_price_reservation_uses_hard_input_and_output_bounds() -> None:
    def synthetic_cost(usage: RequestUsage, _model: str) -> float:
        return usage.input_tokens * 0.000_001 + usage.output_tokens * 0.000_004

    with patch("llm_benchmark.pricing.calc_cost", side_effect=synthetic_cost):
        maximum = resolve_maximum_call_cost(
            "openrouter:synthetic/priced",
            max_input_tokens=4_000,
            max_output_tokens=500,
        )

    assert maximum == pytest.approx(0.006)


@pytest.mark.parametrize("explicit_maximum", [0.0, -0.01])
def test_unknown_price_rejects_non_positive_explicit_maximum(explicit_maximum: float) -> None:
    with (
        patch("llm_benchmark.pricing.calc_cost", return_value=None),
        pytest.raises(ValueError, match="must be greater than zero"),
    ):
        resolve_maximum_call_cost(
            "openrouter:synthetic/unpriced",
            max_input_tokens=4_000,
            max_output_tokens=500,
            unknown_price_max_usd=explicit_maximum,
        )


def test_unknown_price_requires_positive_owner_supplied_maximum() -> None:
    with patch("llm_benchmark.pricing.calc_cost", return_value=None):
        with pytest.raises(ValueError, match="Pricing is unavailable"):
            resolve_maximum_call_cost(
                "openrouter:synthetic/unpriced",
                max_input_tokens=4_000,
                max_output_tokens=500,
            )
        maximum = resolve_maximum_call_cost(
            "openrouter:synthetic/unpriced",
            max_input_tokens=4_000,
            max_output_tokens=500,
            unknown_price_max_usd=0.125,
        )

    assert maximum == pytest.approx(0.125)


@pytest.mark.asyncio
async def test_persisted_charge_gates_cumulative_cap_across_restarts() -> None:
    # A resumed scheduler seeds committed budget from the prior run's charged
    # total. When that already reaches the cap, no further work may dispatch.
    scheduler = BudgetScheduler(
        cap_usd=1.0,
        max_concurrency=1,
        initial_charged_usd=1.0,
        initial_actual_usd=0.30,
    )
    dispatched = False

    async def provider_call() -> tuple[str, float]:
        nonlocal dispatched
        dispatched = True
        return "completed", 0.01

    with pytest.raises(BudgetExhaustedError, match="exceeds remaining budget"):
        await scheduler.run(0.01, provider_call)
    assert dispatched is False
    # Reporting stays separate: charged seeds the gate, actual reports spend.
    assert scheduler.snapshot.charged_usd == pytest.approx(1.0)
    assert scheduler.snapshot.actual_usd == pytest.approx(0.30)
    assert scheduler.snapshot.maximum_possible_usd == pytest.approx(1.0)


@pytest.mark.asyncio
async def test_partial_persisted_charge_admits_only_remaining_headroom() -> None:
    # Prior run charged 0.7 of a 1.0 cap. A resumed reservation of 0.5 exceeds
    # the 0.3 headroom and is rejected; 0.3 fits and dispatches.
    scheduler = BudgetScheduler(
        cap_usd=1.0,
        max_concurrency=1,
        initial_charged_usd=0.7,
        initial_actual_usd=0.5,
    )

    async def provider_call() -> tuple[str, float]:
        return "completed", 0.2

    with pytest.raises(BudgetExhaustedError, match="exceeds remaining budget"):
        await scheduler.run(0.5, provider_call)
    assert await scheduler.run(0.3, provider_call) == "completed"
    snapshot = scheduler.snapshot
    # actual: 0.5 seed + 0.2 observed; charged: 0.7 seed + 0.2 settled.
    assert snapshot.actual_usd == pytest.approx(0.7)
    assert snapshot.charged_usd == pytest.approx(0.9)


@pytest.mark.asyncio
async def test_seeded_actual_cost_never_gates_admission() -> None:
    # A large prior actual spend with zero charged reservation must not block
    # new work: the cap is gated by charged, not actual.
    scheduler = BudgetScheduler(
        cap_usd=1.0,
        max_concurrency=1,
        initial_charged_usd=0.0,
        initial_actual_usd=0.9,
    )

    async def provider_call() -> tuple[str, float]:
        return "completed", 0.4

    assert await scheduler.run(0.8, provider_call) == "completed"
    assert scheduler.snapshot.actual_usd == pytest.approx(1.3)
    assert scheduler.snapshot.charged_usd == pytest.approx(0.4)


@pytest.mark.parametrize("initial_charged", [-0.01, 1.01])
def test_initial_charged_must_be_within_cap(initial_charged: float) -> None:
    with pytest.raises(ValueError, match="initial_charged_usd"):
        BudgetScheduler(cap_usd=1.0, max_concurrency=1, initial_charged_usd=initial_charged)


def test_initial_actual_must_be_non_negative() -> None:
    with pytest.raises(ValueError, match="initial_actual_usd"):
        BudgetScheduler(cap_usd=1.0, max_concurrency=1, initial_actual_usd=-0.01)
