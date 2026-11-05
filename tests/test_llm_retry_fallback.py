"""Behavior tests for the public API of llm_retry_fallback."""

from __future__ import annotations

import pytest

import llm_retry_fallback


def test_normalize_trims_and_lowercases() -> None:
    assert llm_retry_fallback.normalize("  Hello World ") == "hello world"


@pytest.mark.parametrize("value", ["", "   ", "\t\n"])
def test_normalize_rejects_blank_input(value: str) -> None:
    with pytest.raises(ValueError, match="must not be empty"):
        llm_retry_fallback.normalize(value)


def test_version_is_semver() -> None:
    parts = llm_retry_fallback.__version__.split(".")
    assert len(parts) == 3
    assert all(part.isdigit() for part in parts)
