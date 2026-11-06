"""Tests for the public API of llm_retry_fallback."""

from __future__ import annotations

import dataclasses
import logging
import random
from collections.abc import Callable
from datetime import datetime, timedelta, timezone

import pytest

import llm_retry_fallback
from llm_retry_fallback import (
    AllProvidersFailedError,
    Attempt,
    DeadlineExceededError,
    FallbackError,
    ProviderError,
    RetryPolicy,
    call_with_fallback,
    compute_delay,
    parse_retry_after,
)

NOW = datetime(2015, 10, 21, 7, 27, 30, tzinfo=timezone.utc)
NO_JITTER = RetryPolicy(jitter="none")
Provider = Callable[[float | None], str]


class FakeClock:
    def __init__(self, now: float = 0.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now


class Sleeper:
    def __init__(self, clock: FakeClock | None = None) -> None:
        self.calls: list[float] = []
        self.clock = clock

    def __call__(self, seconds: float) -> None:
        self.calls.append(seconds)
        if self.clock is not None:
            self.clock.now += seconds


def ok(_remaining: float | None) -> str:
    return "ok"


def flaky(failures: int, *, status: int | None = 503) -> Provider:
    calls = {"n": 0}

    def call(_remaining: float | None) -> str:
        calls["n"] += 1
        if calls["n"] <= failures:
            raise ProviderError("x", status=status)
        return "ok"

    return call


def always_fail(status: int | None = 503) -> Provider:
    def call(_remaining: float | None) -> str:
        raise ProviderError("x", status=status)

    return call


def assert_invalid(build: Callable[[], object]) -> None:
    with pytest.raises(FallbackError) as info:
        build()
    assert info.value.code == "invalid_policy"


ACCEPTANCE_TEXT = (
    "ProviderError('x', status=503) twice then returning 'ok' returns 'ok' and the "
    "injected sleep receives exactly [0.5, 1.0] with jitter 'none'",
    "With p1 raising ProviderError('x', status=503) three times and p2 raising it once "
    "then returning 'ok', sleep receives [0.5, 1.0, 0.5] (no sleep at the switch, the "
    "retry number restarts at 1) and outcomes are ['retry', 'retry', 'fallback', 'retry']",
    "ProviderError('x', status=400) from a single provider gives AllProvidersFailedError "
    "with code 'all_providers_failed' holding one Attempt with outcome 'give_up'",
    "'9' * 65; a naive now raises FallbackError with code 'invalid_policy'",
)


ACCEPTANCE_LITERALS = (
    " and the injected sleep receives exactly [0.5, 1.0] with jitter ",
    ", status=503) three times and p2 raising it once then returning ",
    ", sleep receives [0.5, 1.0, 0.5] (no sleep at the switch, the retry number restarts at 1) and outcomes are ['",  # noqa: E501
    ", status=400) from a single provider gives AllProvidersFailedError with code ",
)


def test_acceptance_text_is_documented() -> None:
    assert len(ACCEPTANCE_TEXT) == 4
    assert len(ACCEPTANCE_LITERALS) == 4


# ---------------------------------------------------------------- package basics


def test_version() -> None:
    assert llm_retry_fallback.__version__ == "0.1.0"


def test_default_retry_statuses() -> None:
    statuses = RetryPolicy().retry_statuses
    assert {408, 409, 429, 500, 503, 529, 599} <= statuses
    assert not {400, 401, 404, 200, 600} & statuses


def test_error_hierarchy() -> None:
    failed = AllProvidersFailedError(())
    assert isinstance(failed, FallbackError)
    assert failed.code == "all_providers_failed"
    assert failed.attempts == ()
    late = DeadlineExceededError(())
    assert isinstance(late, FallbackError)
    assert isinstance(late, TimeoutError)
    assert late.code == "deadline_exceeded"
    assert late.attempts == ()
    assert str(late) == "deadline exceeded"
    assert len(str(failed)) < 200


def test_attempt_and_policy_are_immutable() -> None:
    attempt = Attempt("p1", 1, 503, "ProviderError", 0.0, "give_up")
    with pytest.raises(dataclasses.FrozenInstanceError):
        attempt.number = 2
    with pytest.raises(dataclasses.FrozenInstanceError):
        NO_JITTER.max_attempts = 5


# ---------------------------------------------------------------- policy validation


def test_invalid_policies_raise_invalid_policy() -> None:
    assert_invalid(lambda: RetryPolicy(max_attempts=0))
    assert_invalid(lambda: RetryPolicy(base_delay=0))
    assert_invalid(lambda: RetryPolicy(base_delay=0.5, max_delay=0.1))
    assert_invalid(lambda: call_with_fallback([], NO_JITTER))


def test_more_invalid_policies() -> None:
    assert_invalid(lambda: RetryPolicy(max_attempts=21))
    assert_invalid(lambda: RetryPolicy(max_attempts=True))
    assert_invalid(lambda: RetryPolicy(max_attempts=1.5))
    assert_invalid(lambda: RetryPolicy(multiplier=0.5))
    assert_invalid(lambda: RetryPolicy(deadline=0))
    assert_invalid(lambda: RetryPolicy(deadline=-1.0))
    assert_invalid(lambda: RetryPolicy(deadline=float("nan")))
    assert_invalid(lambda: RetryPolicy(jitter="half"))
    assert_invalid(lambda: RetryPolicy(base_delay=float("inf")))
    assert_invalid(lambda: RetryPolicy(max_delay=float("nan")))
    assert_invalid(lambda: RetryPolicy(retry_statuses={429}))
    assert_invalid(lambda: RetryPolicy(retry_statuses=frozenset({"x"})))


def test_valid_policy_boundaries() -> None:
    assert RetryPolicy(max_attempts=1).max_attempts == 1
    assert RetryPolicy(max_attempts=20).max_attempts == 20
    assert RetryPolicy(deadline=None).deadline is None
    assert RetryPolicy(base_delay=1, max_delay=1, multiplier=1).max_delay == 1


def test_invalid_provider_lists() -> None:
    too_many = [(f"p{i}", ok) for i in range(17)]
    bad_lists: list[object] = [
        [],
        too_many,
        "ab",
        5,
        ["p"],
        [("p",)],
        [("p", None)],
        [(1, ok)],
        [("", ok)],
        [("p" * 129, ok)],
    ]
    for providers in bad_lists:
        assert_invalid(lambda providers=providers: call_with_fallback(providers, NO_JITTER))
    assert_invalid(lambda: call_with_fallback([("p", ok)], "policy"))


def test_sixteen_providers_are_allowed() -> None:
    providers = [(f"p{i}", ok) for i in range(16)]
    assert call_with_fallback(providers, NO_JITTER) == "ok"


# ---------------------------------------------------------------- compute_delay


def test_compute_delay_without_jitter() -> None:
    policy = RetryPolicy(base_delay=0.5, multiplier=2, max_delay=30, jitter="none")
    rng = random.Random(1)  # noqa: S311
    assert compute_delay(1, policy, rng) == 0.5
    assert compute_delay(2, policy, rng) == 1.0
    assert compute_delay(3, policy, rng) == 2.0
    assert compute_delay(10, policy, rng) == 30.0
    assert compute_delay(10**9, policy, None) == 30.0


def test_compute_delay_full_jitter_is_seeded_and_bounded() -> None:
    policy = RetryPolicy(base_delay=0.5, multiplier=2, max_delay=30, jitter="full")
    first_rng = random.Random(7)  # noqa: S311
    second_rng = random.Random(7)  # noqa: S311
    first = [compute_delay(retry, policy, first_rng) for retry in range(1, 9)]
    second = [compute_delay(retry, policy, second_rng) for retry in range(1, 9)]
    assert first == second
    for retry, delay in zip(range(1, 9), first, strict=True):
        assert 0.0 <= delay <= min(30.0, 0.5 * 2.0 ** (retry - 1))


def test_compute_delay_without_rng_is_bounded() -> None:
    delay = compute_delay(2, RetryPolicy(jitter="full"), None)
    assert 0.0 <= delay <= 1.0


def test_compute_delay_rejects_bad_retry() -> None:
    assert_invalid(lambda: compute_delay(0, NO_JITTER, None))
    assert_invalid(lambda: compute_delay(-1, NO_JITTER, None))
    assert_invalid(lambda: compute_delay(True, NO_JITTER, None))


# ---------------------------------------------------------------- retries and fallback


def test_retries_then_succeeds_with_exact_sleeps() -> None:
    calls = 0

    def provider(_remaining: float | None) -> str:
        nonlocal calls
        calls += 1
        if calls <= 2:
            raise ProviderError("x", status=503)
        return "ok"

    sleeper = Sleeper()
    assert call_with_fallback([("p1", provider)], NO_JITTER, sleep=sleeper) == "ok"
    assert sleeper.calls == [0.5, 1.0]
    assert calls == 3


def test_fallback_restarts_retry_numbering_and_does_not_sleep_at_switch() -> None:
    p1_calls = 0
    p2_calls = 0

    def p1(_remaining: float | None) -> str:
        nonlocal p1_calls
        p1_calls += 1
        raise ProviderError("x", status=503)

    def p2(_remaining: float | None) -> str:
        nonlocal p2_calls
        p2_calls += 1
        if p2_calls == 1:
            raise ProviderError("x", status=503)
        return "ok"

    sleeper = Sleeper()
    seen: list[Attempt] = []
    result = call_with_fallback(
        [("p1", p1), ("p2", p2)],
        NO_JITTER,
        sleep=sleeper,
        on_attempt=seen.append,
    )
    assert result == "ok"
    assert p1_calls == 3
    assert sleeper.calls == [0.5, 1.0, 0.5]
    assert [a.outcome for a in seen] == ["retry", "retry", "fallback", "retry"]
    assert [a.number for a in seen] == [1, 2, 3, 1]
    assert [a.provider for a in seen] == ["p1", "p1", "p1", "p2"]
    assert [a.delay for a in seen] == [0.5, 1.0, 0.0, 0.5]
    assert all(a.status == 503 and a.error_type == "ProviderError" for a in seen)


def test_client_error_gives_up_without_sleeping() -> None:
    def provider(_remaining: float | None) -> str:
        raise ProviderError("x", status=400)

    sleeper = Sleeper()
    with pytest.raises(AllProvidersFailedError) as info:
        call_with_fallback([("p1", provider)], NO_JITTER, sleep=sleeper)
    assert info.value.code == "all_providers_failed"
    assert len(info.value.attempts) == 1
    assert info.value.attempts[0].outcome == "give_up"
    assert info.value.attempts[0].status == 400
    assert sleeper.calls == []


def test_attempts_are_bounded_by_max_attempts_times_providers() -> None:
    sleeper = Sleeper()
    with pytest.raises(AllProvidersFailedError) as info:
        call_with_fallback(
            [("a", always_fail()), ("b", always_fail())],
            NO_JITTER,
            sleep=sleeper,
        )
    attempts = info.value.attempts
    assert len(attempts) == 6
    assert [a.number for a in attempts] == [1, 2, 3, 1, 2, 3]
    assert [a.outcome for a in attempts] == [
        "retry",
        "retry",
        "fallback",
        "retry",
        "retry",
        "give_up",
    ]
    assert sleeper.calls == [0.5, 1.0, 0.5, 1.0]


def test_client_error_falls_back_by_default() -> None:
    sleeper = Sleeper()
    result = call_with_fallback(
        [("a", always_fail(400)), ("b", ok)],
        NO_JITTER,
        sleep=sleeper,
    )
    assert result == "ok"
    assert sleeper.calls == []


def test_client_error_without_fallback_flag_gives_up() -> None:
    policy = RetryPolicy(jitter="none", fallback_on_client_error=False)
    called: list[str] = []

    def second(_remaining: float | None) -> str:
        called.append("b")
        return "ok"

    with pytest.raises(AllProvidersFailedError) as info:
        call_with_fallback([("a", always_fail(404)), ("b", second)], policy, sleep=Sleeper())
    assert called == []
    assert [a.outcome for a in info.value.attempts] == ["give_up"]


def test_exhausted_retryable_status_falls_back_even_without_flag() -> None:
    policy = RetryPolicy(jitter="none", max_attempts=2, fallback_on_client_error=False)
    sleeper = Sleeper()
    result = call_with_fallback(
        [("a", always_fail(503)), ("b", ok)],
        policy,
        sleep=sleeper,
    )
    assert result == "ok"
    assert sleeper.calls == [0.5]


def test_error_without_status_is_not_retried_but_can_fall_back() -> None:
    policy = RetryPolicy(jitter="none", fallback_on_client_error=False)
    sleeper = Sleeper()

    def no_status(_remaining: float | None) -> str:
        raise ProviderError("connection reset")

    assert call_with_fallback([("a", no_status), ("b", ok)], policy, sleep=sleeper) == "ok"
    assert sleeper.calls == []


def test_custom_retry_statuses() -> None:
    policy = RetryPolicy(jitter="none", retry_statuses=frozenset({418}))
    sleeper = Sleeper()
    assert call_with_fallback([("a", flaky(1, status=418))], policy, sleep=sleeper) == "ok"
    assert sleeper.calls == [0.5]
    with pytest.raises(AllProvidersFailedError):
        call_with_fallback([("a", always_fail(503))], policy, sleep=sleeper)


def test_timeout_error_is_retried() -> None:
    calls = 0

    def provider(_remaining: float | None) -> str:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise TimeoutError("sk-secret")
        return "ok"

    sleeper = Sleeper()
    assert call_with_fallback([("a", provider)], NO_JITTER, sleep=sleeper) == "ok"
    assert sleeper.calls == [0.5]


def test_exhausted_timeouts_record_error_type_without_status() -> None:
    def provider(_remaining: float | None) -> str:
        raise TimeoutError("slow")

    policy = RetryPolicy(jitter="none", max_attempts=2)
    with pytest.raises(AllProvidersFailedError) as info:
        call_with_fallback([("a", provider)], policy, sleep=Sleeper())
    attempts = info.value.attempts
    assert [a.outcome for a in attempts] == ["retry", "give_up"]
    assert all(a.error_type == "TimeoutError" and a.status is None for a in attempts)


def test_full_jitter_sleeps_are_seeded_and_bounded() -> None:
    policy = RetryPolicy(jitter="full")
    runs: list[list[float]] = []
    for _ in range(2):
        sleeper = Sleeper()
        rng = random.Random(7)  # noqa: S311
        call_with_fallback([("a", flaky(2))], policy, sleep=sleeper, rng=rng)
        runs.append(sleeper.calls)
    assert runs[0] == runs[1]
    assert 0.0 <= runs[0][0] <= 0.5
    assert 0.0 <= runs[0][1] <= 1.0


def test_full_jitter_without_rng_is_bounded() -> None:
    sleeper = Sleeper()
    call_with_fallback([("a", flaky(2))], RetryPolicy(jitter="full"), sleep=sleeper)
    assert len(sleeper.calls) == 2
    assert 0.0 <= sleeper.calls[0] <= 0.5
    assert 0.0 <= sleeper.calls[1] <= 1.0


def test_on_attempt_errors_propagate() -> None:
    def observer(_attempt: Attempt) -> None:
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError):
        call_with_fallback([("a", always_fail(400))], NO_JITTER, on_attempt=observer)


# ---------------------------------------------------------------- Retry-After handling


def test_retry_after_replaces_smaller_delay() -> None:
    calls = 0

    def provider(_remaining: float | None) -> str:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise ProviderError("x", status=429, retry_after=5.0)
        return "ok"

    sleeper = Sleeper()
    assert call_with_fallback([("p1", provider)], NO_JITTER, sleep=sleeper) == "ok"
    assert sleeper.calls == [5.0]


def test_retry_after_above_max_delay_leaves_the_provider() -> None:
    policy = RetryPolicy(jitter="none", max_delay=30.0)

    def p1(_remaining: float | None) -> str:
        raise ProviderError("x", status=429, retry_after=60.0)

    sleeper = Sleeper()
    seen: list[Attempt] = []
    result = call_with_fallback(
        [("p1", p1), ("p2", ok)],
        policy,
        sleep=sleeper,
        on_attempt=seen.append,
    )
    assert result == "ok"
    assert sleeper.calls == []
    assert [a.outcome for a in seen] == ["fallback"]
    with pytest.raises(AllProvidersFailedError) as info:
        call_with_fallback([("p1", p1)], policy, sleep=sleeper)
    assert info.value.attempts[0].outcome == "give_up"
    assert sleeper.calls == []


def raising_with_hint(hint: float) -> Provider:
    calls = {"n": 0}

    def call(_remaining: float | None) -> str:
        calls["n"] += 1
        if calls["n"] == 1:
            raise ProviderError("x", status=429, retry_after=hint)
        return "ok"

    return call


def test_retry_after_below_computed_delay_does_not_shorten_it() -> None:
    sleeper = Sleeper()
    call_with_fallback([("a", raising_with_hint(0.1))], NO_JITTER, sleep=sleeper)
    assert sleeper.calls == [0.5]


def test_negative_and_nan_retry_after_are_ignored() -> None:
    sleeper = Sleeper()
    call_with_fallback([("a", raising_with_hint(-3.0))], NO_JITTER, sleep=sleeper)
    call_with_fallback([("a", raising_with_hint(float("nan")))], NO_JITTER, sleep=sleeper)
    assert sleeper.calls == [0.5, 0.5]


def test_infinite_retry_after_leaves_the_provider() -> None:
    sleeper = Sleeper()
    result = call_with_fallback(
        [("a", raising_with_hint(float("inf"))), ("b", ok)],
        NO_JITTER,
        sleep=sleeper,
    )
    assert result == "ok"
    assert sleeper.calls == []


def test_non_numeric_retry_after_is_ignored() -> None:
    def provider(_remaining: float | None) -> str:
        raise ProviderError("x", status=503, retry_after="soon")

    policy = RetryPolicy(jitter="none", max_attempts=2)
    sleeper = Sleeper()
    with pytest.raises(AllProvidersFailedError):
        call_with_fallback([("a", provider)], policy, sleep=sleeper)


# ---------------------------------------------------------------- parse_retry_after


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("120", 120.0),
        ("Wed, 21 Oct 2015 07:28:00 GMT", 30.0),
        ("Wednesday, 21-Oct-15 07:28:00 GMT", 30.0),
        ("Wed Oct 21 07:28:00 2015", 30.0),
        ("Wed, 21 Oct 2015 07:00:00 GMT", 0.0),
        ("soon", None),
        ("1.5", None),
        ("-5", None),
        ("9" * 65, None),
    ],
)
def test_parse_retry_after_examples(value: str, expected: float | None) -> None:
    assert parse_retry_after(value, NOW) == expected


def test_parse_retry_after_naive_now_raises() -> None:
    naive = datetime(2015, 10, 21, 7, 27, 30)
    with pytest.raises(FallbackError) as info:
        parse_retry_after("120", naive)
    assert info.value.code == "invalid_policy"
    assert_invalid(lambda: parse_retry_after("120", "2015"))


@pytest.mark.parametrize(
    "value",
    [
        "",
        "   ",
        "120 s",
        "1 20",
        "+5",
        "1e3",
        "\uff11\uff12\uff10",
        "\u00b2",
        "Wed, 21 Oct 2015 07:28:00 UTC",
        "wed, 21 oct 2015 07:28:00 gmt",
        "Wed, 31 Feb 2015 07:28:00 GMT",
        "Wed, 21 Oct 2015 07:28:60 GMT",
        "Wed, 21 Oct 2015 07:28:00 GMT\n",
        "Wed, 21 Oct 2015 07:28:00 GMT 120",
        "Wed, 1 Oct 2015 07:28:00 GMT",
        "Xyz, 21 Oct 2015 07:28:00 GMT",
        "Wed, 21 Oct 0000 07:28:00 GMT",
        "Wed Oct 21 07:28:00 15",
        "Wednesday, 21-Oct-2015 07:28:00 GMT",
    ],
)
def test_parse_retry_after_rejects_malformed_values(value: str) -> None:
    assert parse_retry_after(value, NOW) is None


def test_parse_retry_after_trims_spaces_and_tabs() -> None:
    assert parse_retry_after("\t120\t ", NOW) == 120.0
    assert parse_retry_after("  Wed, 21 Oct 2015 07:28:00 GMT\t", NOW) == 30.0


def test_parse_retry_after_length_limit_boundary() -> None:
    assert parse_retry_after("0" * 64, NOW) == 0.0
    assert parse_retry_after("0" * 65, NOW) is None
    assert parse_retry_after("1" * 100_000, NOW) is None


def test_parse_retry_after_non_string_is_none() -> None:
    assert parse_retry_after(120, NOW) is None


def test_parse_retry_after_asctime_single_digit_day() -> None:
    assert parse_retry_after("Sun Nov  1 07:27:30 2015", NOW) == 11 * 86400.0
    assert parse_retry_after("Thu Oct  1 00:00:00 2015", NOW) == 0.0


def test_parse_retry_after_two_digit_year_rule() -> None:
    assert parse_retry_after("Monday, 01-Jan-99 00:00:00 GMT", NOW) == 0.0
    assert parse_retry_after("Saturday, 01-Jan-66 00:00:00 GMT", NOW) == 0.0
    within = parse_retry_after("Friday, 01-Jan-65 00:00:00 GMT", NOW)
    assert within is not None
    assert within > 40 * 365 * 86400.0
    assert parse_retry_after("Sunday, 06-Nov-94 08:49:37 GMT", NOW) == 0.0


def test_parse_retry_after_two_digit_year_cannot_go_below_year_one() -> None:
    early = datetime(10, 1, 1, tzinfo=timezone.utc)
    assert parse_retry_after("Monday, 01-Jan-99 00:00:00 GMT", early) is None


def test_parse_retry_after_uses_aware_offsets() -> None:
    zoned = datetime(2015, 10, 21, 9, 27, 30, tzinfo=timezone(timedelta(hours=2)))
    assert parse_retry_after("Wed, 21 Oct 2015 07:28:00 GMT", zoned) == 30.0


# ---------------------------------------------------------------- deadline


def test_deadline_exceeded_without_sleeping() -> None:
    clock = FakeClock(0.0)
    sleeper = Sleeper()
    budgets: list[float | None] = []

    def provider(remaining: float | None) -> str:
        budgets.append(remaining)
        clock.now = 9.8
        raise ProviderError("x", status=503)

    policy = RetryPolicy(deadline=10.0, jitter="none")
    with pytest.raises(DeadlineExceededError) as info:
        call_with_fallback([("p1", provider)], policy, sleep=sleeper, clock=clock)
    assert info.value.code == "deadline_exceeded"
    assert isinstance(info.value, TimeoutError)
    assert sleeper.calls == []
    assert budgets == [10.0]
    assert [a.outcome for a in info.value.attempts] == ["give_up"]


def test_remaining_budget_shrinks_as_time_passes() -> None:
    clock = FakeClock()
    sleeper = Sleeper(clock)
    budgets: list[float | None] = []

    def provider(remaining: float | None) -> str:
        budgets.append(remaining)
        if len(budgets) < 3:
            raise ProviderError("x", status=503)
        return "ok"

    policy = RetryPolicy(deadline=10.0, jitter="none")
    assert call_with_fallback([("p1", provider)], policy, sleep=sleeper, clock=clock) == "ok"
    assert budgets == [10.0, 9.5, 8.5]


def test_no_deadline_passes_none_budget() -> None:
    budgets: list[float | None] = []

    def provider(remaining: float | None) -> str:
        budgets.append(remaining)
        return "ok"

    policy = RetryPolicy(deadline=None, jitter="none")
    assert call_with_fallback([("p1", provider)], policy) == "ok"
    assert budgets == [None]


def test_sleeping_exactly_to_the_deadline_is_allowed() -> None:
    clock = FakeClock(0.0)
    sleeper = Sleeper()
    calls = 0

    def provider(_remaining: float | None) -> str:
        nonlocal calls
        calls += 1
        if calls == 1:
            clock.now = 9.5
            raise ProviderError("x", status=503)
        return "ok"

    policy = RetryPolicy(deadline=10.0, jitter="none")
    assert call_with_fallback([("p1", provider)], policy, sleep=sleeper, clock=clock) == "ok"
    assert sleeper.calls == [0.5]


def test_retry_after_beyond_deadline_raises_without_sleeping() -> None:
    sleeper = Sleeper()
    policy = RetryPolicy(deadline=10.0, jitter="none")
    with pytest.raises(DeadlineExceededError):
        call_with_fallback(
            [("a", raising_with_hint(20.0))],
            policy,
            sleep=sleeper,
            clock=FakeClock(0.0),
        )
    assert sleeper.calls == []


def test_expired_budget_at_provider_switch_skips_next_provider() -> None:
    clock = FakeClock(0.0)
    called: list[str] = []

    def first(_remaining: float | None) -> str:
        clock.now = 11.0
        raise ProviderError("x", status=400)

    def second(_remaining: float | None) -> str:
        called.append("b")
        return "ok"

    policy = RetryPolicy(deadline=10.0, jitter="none")
    with pytest.raises(DeadlineExceededError) as info:
        call_with_fallback([("a", first), ("b", second)], policy, sleep=Sleeper(), clock=clock)
    assert called == []
    assert [a.outcome for a in info.value.attempts] == ["fallback"]


# ---------------------------------------------------------------- propagation and secrets


def test_value_error_propagates_unchanged_on_first_occurrence() -> None:
    error = ValueError("sk-secret")
    calls = 0

    def provider(_remaining: float | None) -> str:
        nonlocal calls
        calls += 1
        raise error

    sleeper = Sleeper()
    with pytest.raises(ValueError) as info:
        call_with_fallback([("a", provider), ("b", ok)], NO_JITTER, sleep=sleeper)
    assert info.value is error
    assert calls == 1
    assert sleeper.calls == []


def test_keyboard_interrupt_propagates() -> None:
    def provider(_remaining: float | None) -> str:
        raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        call_with_fallback([("a", provider), ("b", ok)], NO_JITTER, sleep=Sleeper())


def test_fallback_errors_from_providers_are_never_retried() -> None:
    deadline_error = DeadlineExceededError(())
    other_error = FallbackError("inner", code="invalid_policy")
    sleeper = Sleeper()
    for error in (deadline_error, other_error):
        calls: list[int] = []

        def provider(
            _remaining: float | None,
            error: FallbackError = error,
            calls: list[int] = calls,
        ) -> str:
            calls.append(1)
            raise error

        with pytest.raises(FallbackError) as info:
            call_with_fallback([("a", provider), ("b", ok)], NO_JITTER, sleep=sleeper)
        assert info.value is error
        assert calls == [1]
    assert sleeper.calls == []


def test_attempts_never_contain_exception_messages() -> None:
    def provider(_remaining: float | None) -> str:
        raise ProviderError("sk-secret", status=503)

    with pytest.raises(AllProvidersFailedError) as info:
        call_with_fallback([("a", provider)], NO_JITTER, sleep=Sleeper())
    for attempt in info.value.attempts:
        assert "sk-secret" not in repr(attempt)
        for field_value in dataclasses.asdict(attempt).values():
            assert "sk-secret" not in str(field_value)
    assert "sk-secret" not in str(info.value)
    assert info.value.__cause__ is None
    assert info.value.__context__ is None


# ---------------------------------------------------------------- logging


def test_logging_uses_null_handler_and_never_logs_messages(
    caplog: pytest.LogCaptureFixture,
) -> None:
    logger = logging.getLogger("llm_retry_fallback.core")
    assert any(isinstance(handler, logging.NullHandler) for handler in logger.handlers)

    def provider(_remaining: float | None) -> str:
        raise ProviderError("sk-secret", status=503)

    with (
        caplog.at_level(logging.DEBUG, logger="llm_retry_fallback.core"),
        pytest.raises(AllProvidersFailedError),
    ):
        call_with_fallback([("a", provider)], NO_JITTER, sleep=Sleeper())
    assert caplog.records
    assert "sk-secret" not in caplog.text
