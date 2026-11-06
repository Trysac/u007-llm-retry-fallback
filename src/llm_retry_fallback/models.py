"""Data types: provider failures, the retry policy and attempt records."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Literal

from llm_retry_fallback.errors import invalid_policy

__all__ = ["Attempt", "Outcome", "ProviderError", "RetryPolicy"]

Outcome = Literal["retry", "fallback", "give_up"]

_MAX_ATTEMPTS = 20
_DEFAULT_RETRY_STATUSES: frozenset[int] = frozenset({408, 409, 429}) | frozenset(range(500, 600))


class ProviderError(Exception):
    """Failure reported by a provider adapter.

    Attributes:
        status: HTTP status code, or ``None`` when the failure carries no status.
        retry_after: Seconds the provider asked the caller to wait, if known.
    """

    def __init__(
        self,
        message: str,
        *,
        status: int | None = None,
        retry_after: float | None = None,
    ) -> None:
        super().__init__(message)
        self.status = status
        self.retry_after = retry_after


def _is_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _is_finite(value: object) -> bool:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return False
    return math.isfinite(value)


@dataclass(frozen=True)
class RetryPolicy:
    """Immutable retry configuration.

    Attributes:
        max_attempts: Attempts per provider (1 to 20).
        base_delay: Delay before the first retry, in seconds (> 0).
        multiplier: Exponential growth factor (>= 1).
        max_delay: Cap on a single delay, in seconds (>= base_delay).
        jitter: ``"full"`` draws uniformly from [0, cap]; ``"none"`` uses the cap.
        deadline: Overall budget in seconds, or ``None`` for no deadline.
        retry_statuses: HTTP statuses that are retried (default: 408, 409, 429 and 500-599).
        fallback_on_client_error: Whether a non-retryable status moves on to the next provider.

    Raises:
        FallbackError: with code ``invalid_policy`` when a field is out of range.
    """

    max_attempts: int = 3
    base_delay: float = 0.5
    multiplier: float = 2.0
    max_delay: float = 30.0
    jitter: Literal["none", "full"] = "full"
    deadline: float | None = 60.0
    retry_statuses: frozenset[int] = _DEFAULT_RETRY_STATUSES
    fallback_on_client_error: bool = True

    def __post_init__(self) -> None:
        if not _is_int(self.max_attempts) or not 1 <= self.max_attempts <= _MAX_ATTEMPTS:
            raise invalid_policy("max_attempts must be an integer from 1 to 20")
        if not _is_finite(self.base_delay) or self.base_delay <= 0:
            raise invalid_policy("base_delay must be a finite number greater than 0")
        if not _is_finite(self.multiplier) or self.multiplier < 1:
            raise invalid_policy("multiplier must be a finite number >= 1")
        if not _is_finite(self.max_delay) or self.max_delay < self.base_delay:
            raise invalid_policy("max_delay must be a finite number >= base_delay")
        if self.jitter not in ("none", "full"):
            raise invalid_policy("jitter must be 'none' or 'full'")
        if self.deadline is not None and (not _is_finite(self.deadline) or self.deadline <= 0):
            raise invalid_policy("deadline must be None or a finite number greater than 0")
        if not isinstance(self.retry_statuses, frozenset) or not all(
            _is_int(status) for status in self.retry_statuses
        ):
            raise invalid_policy("retry_statuses must be a frozenset of integers")


@dataclass(frozen=True)
class Attempt:
    """Record of one failed attempt. Exception messages are never stored.

    Attributes:
        provider: Provider name as given to ``call_with_fallback``.
        number: Attempt number, restarting at 1 for each provider.
        status: HTTP status of the failure, if any.
        error_type: Class name of the raised exception.
        delay: Seconds slept after this attempt (0.0 unless the outcome is ``retry``).
        outcome: ``retry``, ``fallback`` (provider left) or ``give_up`` (no more options).
    """

    provider: str
    number: int
    status: int | None
    error_type: str
    delay: float
    outcome: Outcome
