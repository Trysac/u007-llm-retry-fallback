# Project record

## Objective

Retries with capped exponential backoff and full jitter, RFC 9110 Retry-After parsing, an overall deadline and ordered provider fallback, all clock-injected

## Scope

- In scope: the public API documented in [README.md](../README.md), typed and tested.
- Out of scope: anything that needs runtime dependencies or I/O without an accepted ADR.

## Timeline

| Date | Event |
|---|---|
| 2026 | Repository created from the factory utility template. |

## Effort metrics

Measured values only; a value that has not been measured stays "pending measurement".

| Metric | Value |
|---|---|
| Tokens (input / output) | 677920 / 87610 |
| Hours (human) | pending measurement |
| Cost (USD) | 0.9388 |

## Factory run u007 (measured from API usage)

| Phase | Model | Batch | Input | Output | Cache write | Cache read | Cost (USD) |
|---|---|---|---|---|---|---|---|
| generation | claude-sonnet-5-5 | yes | 2766 | 64138 | 0 | 4246 | 0.3239 |
| fix-1 | claude-sonnet-5-5 | no | 6 | 1544 | 9399 | 43124 | 0.0433 |
| fix-2 | claude-sonnet-5-5 | no | 8 | 1024 | 9832 | 62247 | 0.0411 |
| fix-3 | claude-sonnet-5-5 | no | 8 | 1341 | 19780 | 68054 | 0.0697 |
| fix-4 | claude-sonnet-5-5 | no | 10 | 1396 | 9995 | 76353 | 0.0466 |
| fix-1 | claude-sonnet-5-5 | no | 6 | 528 | 16159 | 31018 | 0.0488 |
| fix-2 | claude-sonnet-5-5 | no | 12 | 1607 | 8546 | 91520 | 0.0466 |
| audit | claude-sonnet-5-5 | no | 12 | 3582 | 51333 | 135377 | 0.1777 |
| fix-3 | claude-sonnet-5-5 | no | 6 | 2314 | 11447 | 43839 | 0.0562 |
| docs | claude-haiku-5-5 | no | 119308 | 10136 | 0 | 0 | 0.0850 |

Total: $0.9388. Prices: Anthropic list prices.
