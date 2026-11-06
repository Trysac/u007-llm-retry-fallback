# llm-retry-fallback

[![PyPI version](https://img.shields.io/pypi/v/trysac-llm-retry-fallback)](https://pypi.org/project/trysac-llm-retry-fallback/)
[![License: MIT](https://img.shields.io/pypi/l/trysac-llm-retry-fallback)](LICENSE)
[![CI](https://github.com/Trysac/u007-llm-retry-fallback/actions/workflows/ci.yml/badge.svg)](https://github.com/Trysac/u007-llm-retry-fallback/actions/workflows/ci.yml)

Retries with capped exponential backoff and full jitter, RFC 9110 Retry-After parsing, an overall deadline and ordered provider fallback, all clock-injected

## Problem

LLM APIs fail transiently with 429, 5xx and timeouts. Naive retry loops hammer the API, ignore
`Retry-After`, sleep past the caller's deadline, or give up too early, and provider fallback is
usually bolted on later. This library wraps synchronous provider calls with one tested policy that
follows the retry rules of the official OpenAI and Anthropic SDKs, honours `Retry-After`, enforces
an overall deadline and falls back to the next provider in order.

## Install

```sh
pip install trysac-llm-retry-fallback
# or
uv add trysac-llm-retry-fallback
```

Requires Python 3.10 or newer. No runtime dependencies.

## Usage

```python
import time

from llm_retry_fallback import (
    AllProvidersFailedError,
    DeadlineExceededError,
    ProviderError,
    RetryPolicy,
    call_with_fallback,
)


def primary(remaining: float | None) -> str:
    # `remaining` is the seconds left in the deadline budget, or None.
    raise ProviderError("overloaded", status=503)


def backup(remaining: float | None) -> str:
    return "ok"


policy = RetryPolicy(max_attempts=3, base_delay=0.5, max_delay=30.0, deadline=60.0)
try:
    result = call_with_fallback(
        [("primary", primary), ("backup", backup)],
        policy,
        sleep=time.sleep,  # inject a fake sleep/clock in tests
        clock=time.monotonic,
        on_attempt=print,
    )
except DeadlineExceededError as exc:
    print("deadline exceeded", exc.attempts)
except AllProvidersFailedError as exc:
    print("all providers failed", exc.attempts)
```

## API

- `call_with_fallback(providers, policy, *, sleep, clock, rng, on_attempt)`: 1 to 16 `(name, callable)`
  pairs tried in order; each callable receives the remaining budget in seconds or `None`.
- `RetryPolicy`: `max_attempts` (per provider, 1 to 20), `base_delay`, `multiplier`, `max_delay`,
  `jitter` (`"none"` or `"full"`), `deadline`, `retry_statuses`, `fallback_on_client_error`.
  Invalid values raise `FallbackError` with code `invalid_policy`.
- `ProviderError(message, *, status=None, retry_after=None)`: raised by provider adapters.
- `Attempt`: `provider`, `number`, `status`, `error_type`, `delay`, `outcome`
  (`retry`, `fallback` or `give_up`). Exception messages are never stored.
- `compute_delay(retry, policy, rng)`: `min(max_delay, base_delay * multiplier ** (retry - 1))`,
  with full jitter drawn uniformly from `[0, cap]`.
- `parse_retry_after(value, now)`: RFC 9110 delay-seconds or HTTP-date to seconds, or `None`.
- Errors: `FallbackError` (`code`), `AllProvidersFailedError` and `DeadlineExceededError`
  (both with `.attempts`).

## Retry rules

- Retryable: status in `retry_statuses` (408, 409, 429, 500 to 599) or `TimeoutError`; the provider
  is retried with backoff while attempts remain.
- Otherwise the provider is left for the next one (non-retryable statuses need
  `fallback_on_client_error`); with no provider left, `AllProvidersFailedError` is raised.
- Nothing sleeps between providers, and the retry number restarts at 1 for each provider.
- `FallbackError` subclasses and any exception other than `ProviderError` or `TimeoutError`
  propagate unchanged.
- Before sleeping, if the delay would pass the deadline, `DeadlineExceededError` is raised.

## Retry-After

A `Retry-After` above the computed delay replaces it; above `max_delay` the provider is left
instead of sleeping less than asked; negative counts as 0. `parse_retry_after` accepts
delay-seconds (ASCII digits only) and the three HTTP-date formats (IMF-fixdate, rfc850, asctime),
returns `0.0` for past dates, and `None` for anything else or values over 64 characters. `now`
must be timezone-aware.

## Documentation

- [Architecture](docs/ARCHITECTURE.md) and [decisions](docs/decisions/)
- [Testing](docs/TESTING.md) and [security](docs/SECURITY.md)
- [Project record](docs/PROJECT.md) and [stack](docs/STACK.md)
- [Changelog](CHANGELOG.md) and [contributing guide](CONTRIBUTING.md)

## License

[MIT](LICENSE) (c) 2026 Miguel Gomez
