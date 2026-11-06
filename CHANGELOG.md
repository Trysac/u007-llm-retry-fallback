# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- Add `call_with_fallback`, `compute_delay`, `parse_retry_after`, `RetryPolicy`, `Attempt`, `ProviderError` and typed `FallbackError` errors: retries with capped exponential backoff and full jitter, RFC 9110 Retry-After, an overall deadline and ordered provider fallback, all clock-injected.
- Initial project structure from the factory utility template.
