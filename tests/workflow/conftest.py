"""Shared fixtures for the workflow test package."""

import pytest

from sequence_extensions import DEFAULT_REGISTRY


@pytest.fixture
def pristine_default_registry():
    """Snapshot DEFAULT_REGISTRY and restore it after the test (no leakage)."""
    functions = DEFAULT_REGISTRY._functions
    saved = dict(functions)
    yield DEFAULT_REGISTRY
    functions.clear()
    functions.update(saved)
