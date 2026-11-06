"""Retry LLM provider calls with backoff, ``Retry-After``, a deadline and ordered fallback.

Capped exponential backoff with full jitter, RFC 9110 ``Retry-After`` parsing, an overall
deadline and ordered provider fallback, all driven by injectable clocks. Synchronous only,
zero runtime dependencies.
"""

from __future__ import annotations

from llm_retry_fallback.core import call_with_fallback, compute_delay
from llm_retry_fallback.errors import (
    AllProvidersFailedError,
    DeadlineExceededError,
    FallbackError,
)
from llm_retry_fallback.models import Attempt, ProviderError, RetryPolicy
from llm_retry_fallback.retry_after import parse_retry_after

__all__ = [
    "AllProvidersFailedError",
    "Attempt",
    "DeadlineExceededError",
    "FallbackError",
    "ProviderError",
    "RetryPolicy",
    "__version__",
    "call_with_fallback",
    "compute_delay",
    "parse_retry_after",
]

__version__ = "0.1.0"
