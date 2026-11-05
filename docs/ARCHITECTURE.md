# Architecture

## Purpose

`trysac-llm-retry-fallback` is a small, dependency-free Python library: Retries with capped exponential backoff and full jitter, RFC 9110 Retry-After parsing, an overall deadline and ordered provider fallback, all clock-injected

## Shape

```text
caller code --> llm_retry_fallback (public API in __init__.py)
                    |
                    +-- pure functions, no I/O, no global state
```

- **Public API**: the names listed in `__all__` of `src/llm_retry_fallback/__init__.py`. Anything else is
  internal and may change without a major version.
- **Errors**: invalid input raises built-in exceptions (`ValueError`, `TypeError`) with a clear
  message; the library never prints or exits.
- **Side effects**: none. If a feature needs I/O, isolate it in its own module behind a small
  interface and record the choice in an ADR.

## Quality contract

`scripts/check.py` is the single definition of the gates; `fabrica.json` tells the factory and CI
how to run it. See [TESTING.md](TESTING.md).

## Decisions

Architecture decisions are recorded in [decisions/](decisions/) as numbered ADRs.
