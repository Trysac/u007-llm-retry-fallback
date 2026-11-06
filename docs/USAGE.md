# Usage

`trysac-llm-retry-fallback` wraps synchronous provider calls with one retry policy and an ordered
provider fallback. It has no runtime dependencies and never performs HTTP itself: adapters call
the provider and raise `ProviderError` for failures.

## Example

```python
from llm_retry_fallback import ProviderError, RetryPolicy, call_with_fallback


def primary(remaining: float | None) -> str:
    raise ProviderError("overloaded", status=503)


def backup(remaining: float | None) -> str:
    return "ok"


policy = RetryPolicy(max_attempts=2, base_delay=0.01)
print(call_with_fallback([("primary", primary), ("backup", backup)], policy))
```

Each callable receives the remaining time budget in seconds, or `None` when the policy has no
deadline. Pass it to the SDK as a request timeout.

## Rules applied to every failure

1. A `FallbackError` (including `DeadlineExceededError`, although it is a `TimeoutError`) or any
   exception other than `ProviderError` and `TimeoutError` propagates unchanged and is never
   retried.
2. A retryable failure (status in `retry_statuses`, or `TimeoutError`) with attempts left sleeps
   and retries. The default statuses are 408, 409, 429 and 500 to 599.
3. A `Retry-After` hint above the computed delay replaces it. A hint above `max_delay` makes the
   library leave the provider instead of sleeping less than asked. Negative hints count as 0.
4. Otherwise the provider is left with outcome `fallback` when another provider follows, or
   `give_up` (raising `AllProvidersFailedError`) when none does. A non-retryable status also
   needs `fallback_on_client_error=True` to fall back. A `ProviderError` without a status is not
   retried and may fall back regardless of that flag.
5. Nothing sleeps between providers, and the attempt number restarts at 1 for each provider.
6. Before sleeping, if the clock plus the delay would pass `start + deadline`,
   `DeadlineExceededError` is raised without sleeping. If the budget is already used up when an
   attempt would begin, the same error is raised without calling the provider.

## Backoff

`compute_delay(retry, policy, rng)` returns `min(max_delay, base_delay * multiplier ** (retry - 1))`
for jitter `none`, and a uniform draw from `[0, cap]` for jitter `full` (see the AWS Architecture
Blog article "Exponential Backoff and Jitter"). Pass a seeded `random.Random` for reproducible
delays.

## Retry-After

`parse_retry_after(value, now)` implements RFC 9110 section 10.2.3: delay-seconds (ASCII digits
only) or an HTTP-date in IMF-fixdate, rfc850-date or asctime-date form. Month and day names come
from fixed English tables, not from the locale. Weekday names are matched as names; they are not
checked against the date. A two-digit year more than 50 years ahead means the latest past year
with those digits. Past dates give `0.0`; anything else gives `None`. `now` must be
timezone-aware.

## Errors

All library errors derive from `FallbackError` and carry a stable `code`:
`all_providers_failed`, `deadline_exceeded` or `invalid_policy`.

## Limits and safety

- 1 to 16 providers, provider names up to 128 characters, 1 to 20 attempts per provider, so a
  call records at most 320 attempts.
- `parse_retry_after` ignores values longer than 64 characters.
- `Attempt.error_type` is the exception class name. Exception messages are never stored, logged or
  chained onto the errors the library raises.
- The library logs only through `logging.getLogger(__name__)` with a `NullHandler`, at debug
  level, and never logs messages or request bodies.
- Jitter uses `random.Random`, which is appropriate for load spreading and is not a security
  mechanism.

## Out of scope

HTTP clients and circuit breakers. Compared with `tenacity`, this library adds provider fallback
and `Retry-After` handling.
