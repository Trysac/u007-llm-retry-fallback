# Clock-injected retry with ordered provider fallback and no exception chaining

Status: accepted (generated, pending human review)

## Context

LLM provider calls fail transiently with 429, 5xx and timeouts. Naive retry loops ignore Retry-After, sleep past the caller's deadline, or lack provider fallback. The library must be deterministic to test, free of runtime dependencies and must not leak provider error messages, which can contain secrets.

## Decision

Implement a single synchronous driver, call_with_fallback, with injected sleep, clock and random source. Backoff is capped exponential with full jitter. Retry-After is parsed per RFC 9110 with fixed English tables instead of locale-dependent strptime. FallbackError subclasses and unknown exceptions propagate unchanged. Attempts record only the exception class name. Provider exceptions are not chained onto the library's errors. The deadline is checked before every sleep and before every attempt. A ProviderError with no status is not retried but may fall back, because the client-error flag applies only to real statuses.

## Consequences

Tests are fully deterministic with fake clocks and sleepers, and no secret can leak through attempts, logs or tracebacks of the raised errors. The cost is less debugging detail: callers who need the original exception must capture it in their adapter or in on_attempt. Policy validation is slightly stricter than the minimum (non-finite numbers and bad jitter are rejected). The library is synchronous only, and async callers need a separate implementation.
