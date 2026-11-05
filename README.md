# llm-retry-fallback

[![PyPI version](https://img.shields.io/pypi/v/trysac-llm-retry-fallback)](https://pypi.org/project/trysac-llm-retry-fallback/)
[![License: MIT](https://img.shields.io/pypi/l/trysac-llm-retry-fallback)](LICENSE)
[![CI](https://github.com/Trysac/u007-llm-retry-fallback/actions/workflows/ci.yml/badge.svg)](https://github.com/Trysac/u007-llm-retry-fallback/actions/workflows/ci.yml)

Retries with capped exponential backoff and full jitter, RFC 9110 Retry-After parsing, an overall deadline and ordered provider fallback, all clock-injected

## Problem

Describe in two or three sentences the concrete problem this utility solves, who hits it, and what
they do today without it. Replace this paragraph when the first real feature lands.

## Install

```sh
pip install trysac-llm-retry-fallback
# or
uv add trysac-llm-retry-fallback
```

Requires Python 3.10 or newer. No runtime dependencies.

## Usage

```python
import llm_retry_fallback

# normalize() trims surrounding whitespace and lower-cases the text.
print(llm_retry_fallback.normalize("  Hello World "))  # -> "hello world"

# Blank input is rejected explicitly instead of returning an empty string.
try:
    llm_retry_fallback.normalize("   ")
except ValueError as exc:
    print(f"rejected: {exc}")
```

## Documentation

- [Architecture](docs/ARCHITECTURE.md) and [decisions](docs/decisions/)
- [Testing](docs/TESTING.md) and [security](docs/SECURITY.md)
- [Project record](docs/PROJECT.md) and [stack](docs/STACK.md)
- [Changelog](CHANGELOG.md) and [contributing guide](CONTRIBUTING.md)

## License

[MIT](LICENSE) (c) 2026 Miguel Gomez
