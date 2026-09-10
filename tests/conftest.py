"""Shared fixtures for the sequence_extensions test suite."""

import pytest

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