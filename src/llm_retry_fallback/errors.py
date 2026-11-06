"""Typed errors raised by ``llm_retry_fallback``."""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from collections.abc import Sequence

    from llm_retry_fallback.models import Attempt

__all__ = [
    "AllProvidersFailedError",
    "DeadlineExceededError",
    "ErrorCode",
    "FallbackError",
    "invalid_policy",
]

ErrorCode = Literal["all_providers_failed", "deadline_exceeded", "invalid_policy"]


class FallbackError(Exception):
    """Base class of every error raised by this library.

    Attributes:
        code: Stable machine-readable error code.
    """

    def __init__(self, message: str, *, code: ErrorCode) -> None:
        super().__init__(message)
        self.code: ErrorCode = code


class AllProvidersFailedError(FallbackError):
    """Every provider was tried (or skipped by policy) and none succeeded.

    Attributes:
        attempts: Every recorded failed attempt, in order.
    """

    def __init__(self, attempts: Sequence[Attempt]) -> None:
        super().__init__("all providers failed", code="all_providers_failed")
        self.attempts: tuple[Attempt, ...] = tuple(attempts)


class DeadlineExceededError(FallbackError, TimeoutError):
    """The overall deadline would be (or was) exceeded.

    It is also a :class:`TimeoutError`, but it is never retried by the library.

    Attributes:
        attempts: Every recorded failed attempt, in order.
    """

    def __init__(self, attempts: Sequence[Attempt]) -> None:
        super().__init__("deadline exceeded", code="deadline_exceeded")
        self.attempts: tuple[Attempt, ...] = tuple(attempts)


def invalid_policy(message: str) -> FallbackError:
    """Build the ``invalid_policy`` error for a fixed, input-free ``message``."""
    return FallbackError(message, code="invalid_policy")
