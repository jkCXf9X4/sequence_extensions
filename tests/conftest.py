"""Shared fixtures for the sequence_extensions test suite."""

import pytest

from markers import LEVEL_MARKERS, level_for
from sequence_extensions import dict_ext, list_ext


@pytest.fixture
def simple_int_list():
    return list_ext([1, 2, 3, 4])


@pytest.fixture
def empty_list():
    return list_ext()


@pytest.fixture
def int_dict():
    return dict_ext({"a": 1, "b": 2, "c": 3, "d": 4})


@pytest.fixture
def empty_dict():
    return dict_ext()


def pytest_collection_modifyitems(config, items):
    """Give every test exactly one level marker, by directory."""
    for item in items:
        if any(marker.name in LEVEL_MARKERS for marker in item.iter_markers()):
            continue
        item.add_marker(getattr(pytest.mark, level_for(item.path)))
