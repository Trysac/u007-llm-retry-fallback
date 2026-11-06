"""Backoff computation and the ``call_with_fallback`` driver."""

from __future__ import annotations

import logging
import math
import random
import time
from collections.abc import Callable, Sequence
from typing import TypeVar

from llm_retry_fallback.errors import (
    AllProvidersFailedError,
    DeadlineExceededError,
    FallbackError,
    invalid_policy,
)
from llm_retry_fallback.models import Attempt, Outcome, ProviderError, RetryPolicy

__all__ = ["DEFAULT_POLICY", "call_with_fallback", "compute_delay"]

T = TypeVar("T")

MAX_PROVIDERS = 16
MAX_PROVIDER_NAME_LENGTH = 128
DEFAULT_POLICY = RetryPolicy()

logger = logging.getLogger(__name__)
logger.addHandler(logging.NullHandler())


def compute_delay(retry: int, policy: RetryPolicy, rng: random.Random | None) -> float:
    """Return the backoff delay before retry number ``retry`` (1 for the first retry).

    ``cap = min(max_delay, base_delay * multiplier ** (retry - 1))``. With jitter ``"none"``
    the cap is returned; with ``"full"`` the result is ``rng.uniform(0, cap)`` (AWS Architecture
    Blog, "Exponential Backoff and Jitter"). ``rng=None`` uses a fresh ``random.Random()``.

    Raises:
        FallbackError: with code ``invalid_policy`` when ``retry`` is not an integer >= 1.
    """
    if isinstance(retry, bool) or not isinstance(retry, int) or retry < 1:
        raise invalid_policy("retry must be an integer >= 1")
    try:
        raw = float(policy.base_delay) * float(policy.multiplier) ** (retry - 1)
    except OverflowError:
        raw = float(policy.max_delay)
    cap = float(min(policy.max_delay, raw))
    if policy.jitter == "none":
        return cap
    source = rng if rng is not None else random.Random()  # noqa: S311 - jitter, not security
    return source.uniform(0.0, cap)


def _clean_hint(value: object) -> float | None:
    """Normalise a provider Retry-After hint: ignore garbage and NaN, clamp negatives to 0."""
    if isinstance(value, bool) or not isinstance(value, int | float) or math.isnan(value):
        return None
    return max(0.0, float(value))


def _retry_delay(
    number: int,
    policy: RetryPolicy,
    rng: random.Random,
    retry_after: object,
) -> float | None:
    """Return the sleep before the next attempt, or ``None`` to leave the provider."""
    delay = compute_delay(number, policy, rng)
    hint = _clean_hint(retry_after)
    if hint is None:
        return delay
    if hint > policy.max_delay:
        return None
    return max(delay, hint)


def _valid_name(name: object) -> bool:
    return isinstance(name, str) and 0 < len(name) <= MAX_PROVIDER_NAME_LENGTH


def _validate_providers(providers: Sequence[tuple[str, Callable[[float | None], T]]]) -> None:
    if isinstance(providers, str | bytes) or not isinstance(providers, Sequence):
        raise invalid_policy("providers must be a sequence of (name, callable) tuples")
    if not 1 <= len(providers) <= MAX_PROVIDERS:
        raise invalid_policy("providers must contain 1 to 16 entries")
    for entry in providers:
        valid = (
            isinstance(entry, tuple)
            and len(entry) == 2
            and _valid_name(entry[0])
            and callable(entry[1])
        )
        if not valid:
            raise invalid_policy("each provider must be a (name, callable) tuple")


def call_with_fallback(
    providers: Sequence[tuple[str, Callable[[float | None], T]]],
    policy: RetryPolicy = DEFAULT_POLICY,
    *,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
    rng: random.Random | None = None,
    on_attempt: Callable[[Attempt], None] | None = None,
) -> T:
    """Call providers in order, retrying transient failures and falling back on exhaustion.

    Each provider callable receives the remaining budget in seconds (``None`` without a
    deadline). Per failure: a :class:`FallbackError` (including ``DeadlineExceededError``) or
    any exception other than ``ProviderError`` and ``TimeoutError`` propagates unchanged. A
    retryable failure (status in ``retry_statuses``, or ``TimeoutError``) with attempts left
    sleeps and retries; a ``Retry-After`` hint above the computed delay replaces it, and one
    above ``max_delay`` leaves the provider instead. Otherwise the provider is left with
    outcome ``fallback`` if another provider follows (a non-retryable status also needs
    ``fallback_on_client_error``), else ``give_up``. Nothing sleeps between providers. Before
    sleeping, if the delay would pass the deadline, ``DeadlineExceededError`` is raised.

    Args:
        providers: 1 to 16 ``(name, callable)`` pairs, tried in order.
        policy: Retry configuration.
        sleep: Injected sleep function.
        clock: Injected monotonic clock.
        rng: Random source for jitter; ``None`` uses a fresh ``random.Random()``.
        on_attempt: Optional observer called with every failed :class:`Attempt`. Exceptions
            it raises propagate.

    Returns:
        The first successful provider result.

    Raises:
        AllProvidersFailedError: No provider succeeded.
        DeadlineExceededError: The deadline was reached.
        FallbackError: ``invalid_policy`` for bad arguments.
    """
    _validate_providers(providers)
    if not isinstance(policy, RetryPolicy):
        raise invalid_policy("policy must be a RetryPolicy")
    source = rng if rng is not None else random.Random()  # noqa: S311 - jitter, not security
    start = clock()
    deadline_at = None if policy.deadline is None else start + policy.deadline
    attempts: list[Attempt] = []

    def record(
        provider: str,
        number: int,
        status: int | None,
        error_type: str,
        delay: float,
        outcome: Outcome,
    ) -> None:
        attempt = Attempt(provider, number, status, error_type, delay, outcome)
        attempts.append(attempt)
        logger.debug(
            "provider=%s attempt=%d status=%s error_type=%s delay=%.3f outcome=%s",
            provider,
            number,
            status,
            error_type,
            delay,
            outcome,
        )
        if on_attempt is not None:
            on_attempt(attempt)

    last_index = len(providers) - 1
    for index, (name, call) in enumerate(providers):
        has_next = index < last_index
        number = 0
        outcome: Outcome = "fallback"
        while True:
            number += 1
            remaining: float | None = None
            if deadline_at is not None:
                remaining = deadline_at - clock()
                if remaining <= 0:
                    raise DeadlineExceededError(tuple(attempts))
            status: int | None = None
            retry_after: float | None = None
            retryable = True
            try:
                return call(remaining)
            except FallbackError:
                raise
            except (ProviderError, TimeoutError) as exc:
                error_type = type(exc).__name__
                if isinstance(exc, ProviderError):
                    status = exc.status
                    retry_after = exc.retry_after
                    retryable = status is not None and status in policy.retry_statuses
            delay: float | None = None
            if retryable and number < policy.max_attempts:
                delay = _retry_delay(number, policy, source, retry_after)
            if delay is not None:
                if deadline_at is not None and clock() + delay > deadline_at:
                    record(name, number, status, error_type, 0.0, "give_up")
                    raise DeadlineExceededError(tuple(attempts))
                record(name, number, status, error_type, delay, "retry")
                sleep(delay)
                continue
            client_error = not retryable and status is not None
            if has_next and (not client_error or policy.fallback_on_client_error):
                outcome = "fallback"
            else:
                outcome = "give_up"
            record(name, number, status, error_type, 0.0, outcome)
            break
        if outcome == "give_up":
            break
    raise AllProvidersFailedError(tuple(attempts))
