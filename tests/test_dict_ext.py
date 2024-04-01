from typing import Any
import pytest
from sequence_extensions.dict_ext import dict_ext


@pytest.fixture
def int_dict():
    return dict_ext({"a": 1, "b": 2, "c": 3, "d": 4})


@pytest.fixture
def empty_dict():
    return dict_ext()


def test_init_1():
    d1 = dict_ext({"a": 1, "b": 2})
    assert d1["a"] == 1

    d2 = dict_ext()
    d2["c"] = 3
    assert d2["c"] == 3


def test_init_tuple():
    t1 = (("a", 1), ("b", 2))
    d1 = dict_ext(t1)
    assert d1["a"] == 1


def test_init_array():
    t1 = [("a", 1), ("b", 2)]
    d1 = dict_ext(t1)
    assert d1["a"] == 1
    # print(d1)


def test_map_dict(int_dict):
    d1 = int_dict.map_dict(lambda key, value: (key * 2, value * 2))
    assert d1 == {"aa": 2, "bb": 4, "cc": 6, "dd": 8}

    def f(key, value):
        return (key * 2, value * 2)

    d2 = int_dict.map_dict(f)
    assert d2 == {"aa": 2, "bb": 4, "cc": 6, "dd": 8}

    def f2(key, value):
        return key * 2, value * 2

    d3 = int_dict.map_dict(f2)
    assert d3 == {"aa": 2, "bb": 4, "cc": 6, "dd": 8}

def test_map_list(int_dict):
    l1 = int_dict.map_list(lambda key, value: str(key)+ str(value))
    assert l1 == ["a1", "b2", "c3", "d4"]


def test_filter(int_dict):

    d1 = int_dict.filter(lambda key, value: value % 2 == 0)

    assert "a" not in d1
    assert "b" in d1


def test_for_each(int_dict):

    d = {}

    def f(key, value):
        d[key] = value

    int_dict.for_each(f)
    assert int_dict == d


def test_to_strings(int_dict):
    
    int_dict : dict_ext
    
    string_dict = int_dict.to_strings()    
    assert string_dict == {"a": "1", "b": "2", "c": "3", "d": "4"}


def test_to_string(int_dict):
    int_dict : dict_ext
    string_dict = int_dict.to_string()
    s = "a : 1\nb : 2\nc : 3\nd : 4"
    assert string_dict == s


def test_get_key_from_value(int_dict):
    int_dict : dict_ext
    key = int_dict.get_key_from_value(3)
    assert key == ["c"]


def test_get_keys(int_dict):
    keys = int_dict.get_keys()
    assert keys == ["a", "b", "c", "d"]


def test_get_values(int_dict):
    values = int_dict.get_values()
    assert values == [1, 2, 3, 4]
      

def test_to_list(int_dict):
    l = int_dict.to_list()
    assert l == [["a", 1], ["b", 2], ["c", 3], ["d", 4]]


def test_to_tuple(int_dict):
    t = int_dict.to_tuple()
    # print(t)
    assert t == (("a", 1), ("b", 2), ("c", 3), ("d", 4))


def test_to_named_tuple(int_dict):
    t = int_dict.to_named_tuple()
    # print(t)
    assert t[0].key == "a"
    assert t[0].value == 1


def test_reduce(int_dict):

    def red(a, b):
        return (a.key + b.key, a.value + b.value)

    reduction = int_dict.reduce(red)
    assert reduction == {'abcd': 10}

def test_extend(int_dict):

    new_dict = int_dict.extend({"e": 5})

    assert new_dict == {"a": 1, "b": 2, "c": 3, "d": 4, "e": 5}


def test_extend_overwrite(int_dict):

    with pytest.raises(TypeError):
        int_dict.extend({"d": 5})


def test_inverse(int_dict):

    inv = int_dict.inverse()

    assert inv == {1:"a", 2: 'b', 3: 'c', 4: 'd'}


def test_first(int_dict):

    kv = int_dict.first()

    assert kv.key == "a"
    assert kv.value == 1

