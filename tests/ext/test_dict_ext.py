import pytest

from sequence_extensions import list_ext
from sequence_extensions.ext.dict_ext import dict_ext


@pytest.fixture
def int_dict():
    return dict_ext({"a": 1, "b": 2, "c": 3, "d": 4})


@pytest.fixture
def empty_dict():
    return dict_ext()


def test_init_empty_then_setitem():
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


def test_map_dict(int_dict):
    d1 = int_dict.map(lambda key, value: (key * 2, value * 2))
    assert d1 == {"aa": 2, "bb": 4, "cc": 6, "dd": 8}
    # contract: default cast is dict_ext (returns dict_ext)
    assert type(d1) is dict_ext

    def f(key, value):
        return (key * 2, value * 2)

    d2 = int_dict.map(f)
    assert d2 == {"aa": 2, "bb": 4, "cc": 6, "dd": 8}

    def f2(key, value):
        return key * 2, value * 2

    d3 = int_dict.map(f2)
    assert d3 == {"aa": 2, "bb": 4, "cc": 6, "dd": 8}


def test_map_cast_dict_returns_plain_dict(int_dict):
    # contract: cast=dict returns a REAL plain dict
    d = int_dict.map(lambda key, value: (key, value), cast=dict)
    assert type(d) is dict
    assert not isinstance(d, dict_ext)
    assert d == {"a": 1, "b": 2, "c": 3, "d": 4}


def test_map_cast_tuple(int_dict):
    # contract: cast=tuple works
    t = int_dict.map(lambda key, value: (key, value), cast=tuple)
    assert t == (("a", 1), ("b", 2), ("c", 3), ("d", 4))


def test_map_list(int_dict):
    l1 = int_dict.map(lambda key, value: str(key) + str(value), cast=list_ext)
    assert l1 == ["a1", "b2", "c3", "d4"]

    l2 = int_dict.map(lambda key, value: [value, key], cast=list_ext)
    assert l2 == [[1, "a"], [2, "b"], [3, "c"], [4, "d"]]


def test_map_cast_list_ext_non_tuple_no_raise(int_dict):
    # contract: cast=list_ext does NO 2-tuple validation — a func returning a
    # non-tuple with cast=list_ext does NOT raise
    result = int_dict.map(lambda key, value: key, cast=list_ext)
    assert result == ["a", "b", "c", "d"]


def test_map_dict_ext_non_tuple_raises(int_dict):
    # contract: cast=dict_ext raises TypeError with a clear message for
    # non-2-tuple results
    with pytest.raises(TypeError, match="2-tuple"):
        int_dict.map(lambda key, value: key)


def test_filter(int_dict):

    d1 = int_dict.filter(lambda key, value: value % 2 == 0)

    assert "a" not in d1
    assert "b" in d1


def test_filter_no_match(int_dict):
    assert int_dict.filter(lambda key, value: value > 100) == dict_ext()


def test_for_each(int_dict):

    d = {}

    def f(key, value):
        d[key] = value

    result = int_dict.for_each(f)
    assert result is None
    assert int_dict == d


def test_to_strings(int_dict):
    string_dict = int_dict.to_strings()
    assert string_dict == {"a": "1", "b": "2", "c": "3", "d": "4"}


def test_to_strings_key_false(int_dict):
    # key=False keeps keys as-is, values converted to str
    string_dict = int_dict.to_strings(key=False)
    assert string_dict == {"a": "1", "b": "2", "c": "3", "d": "4"}
    assert type(string_dict) is dict_ext


def test_to_strings_value_false(int_dict):
    # value=False keeps values as-is, keys converted to str
    string_dict = int_dict.to_strings(value=False)
    assert string_dict == {"a": 1, "b": 2, "c": 3, "d": 4}


def test_to_string(int_dict):
    string_dict = int_dict.to_string()
    s = "a : 1\nb : 2\nc : 3\nd : 4"
    assert string_dict == s


def test_to_string_custom_separator(int_dict):
    string_dict = int_dict.to_string(separator="|")
    assert string_dict == "a : 1|b : 2|c : 3|d : 4"


def test_get_key_from_value(int_dict):
    key = int_dict.get_key_from_value(3)
    assert key == ["c"]


def test_get_key_from_value_multi_match():
    d = dict_ext({"a": 1, "b": 1})
    assert d.get_key_from_value(1) == ["a", "b"]


def test_get_key_from_value_no_match(int_dict):
    assert int_dict.get_key_from_value(99) == []


def test_get_keys(int_dict):
    keys = int_dict.get_keys()
    assert keys == ["a", "b", "c", "d"]
    assert isinstance(keys, list_ext)


def test_get_values(int_dict):
    values = int_dict.get_values()
    assert values == [1, 2, 3, 4]
    assert isinstance(values, list_ext)


def test_to_list(int_dict):
    result = int_dict.to_list()
    assert result == [["a", 1], ["b", 2], ["c", 3], ["d", 4]]


def test_to_list_empty(empty_dict):
    assert empty_dict.to_list() == []


def test_to_tuple(int_dict):
    t = int_dict.to_tuple()
    assert t == (("a", 1), ("b", 2), ("c", 3), ("d", 4))


def test_to_tuple_empty(empty_dict):
    assert empty_dict.to_tuple() == ()


def test_to_named_tuple(int_dict):
    t = int_dict.to_named_tuple()
    assert t[0].key == "a"
    assert t[0].value == 1


def test_to_named_tuple_empty(empty_dict):
    assert empty_dict.to_named_tuple() == ()


def test_reduce(int_dict):

    def red(a, b):
        return (a.key + b.key, a.value + b.value)

    reduction = int_dict.reduce(red)
    assert reduction == {"abcd": 10}


def test_reduce_single_item():
    def red(a, b):
        return (a.key + b.key, a.value + b.value)

    assert dict_ext({"a": 1}).reduce(red) == {"a": 1}


def test_extend(int_dict):

    new_dict = int_dict.extend({"e": 5})

    assert new_dict == {"a": 1, "b": 2, "c": 3, "d": 4, "e": 5}
    # extend returns a NEW dict; the original is unmodified
    assert int_dict == {"a": 1, "b": 2, "c": 3, "d": 4}


def test_extend_overwrite(int_dict):

    new_dict = int_dict.extend({"d": 5})

    assert new_dict == {"a": 1, "b": 2, "c": 3, "d": 5}
    assert int_dict == {"a": 1, "b": 2, "c": 3, "d": 4}


def test_extend_other_wins(int_dict):

    new_dict = int_dict.extend({"d": 5, "e": 6})

    assert new_dict == {"a": 1, "b": 2, "c": 3, "d": 5, "e": 6}
    assert int_dict == {"a": 1, "b": 2, "c": 3, "d": 4}


def test_filter_none_keeps_all(int_dict):

    d1 = int_dict.filter(None)

    assert d1 == int_dict
    assert d1 is not int_dict


def test_reduce_empty():

    def red(a, b):
        return (a.key + b.key, a.value + b.value)

    assert dict_ext().reduce(red) == dict_ext()


def test_all_any_values_not_keys():

    assert dict_ext({0: "x"}).all() is True
    assert dict_ext({"a": 0}).any() is False


def test_inverse(int_dict):

    inv = int_dict.inverse()

    assert inv == {1: "a", 2: "b", 3: "c", 4: "d"}


def test_inverse_collision_last_wins():
    # duplicate values: the LAST key wins silently
    assert dict_ext({"a": 1, "b": 1}).inverse() == {1: "b"}


def test_first(int_dict):

    kv = int_dict.first()

    assert kv.key == "a"
    assert kv.value == 1

    kv = int_dict.first(lambda key, value: value % 2 == 0)

    assert kv.key == "b"
    assert kv.value == 2


def test_first_no_match_raises_index_error(int_dict):
    with pytest.raises(IndexError):
        int_dict.first(lambda key, value: value > 5)


def test_last(int_dict):

    kv = int_dict.last()

    assert kv.key == "d"
    assert kv.value == 4

    kv = int_dict.last(lambda key, value: value % 2 == 0)

    assert kv.key == "d"
    assert kv.value == 4


def test_last_no_match_raises_index_error(int_dict):
    with pytest.raises(IndexError):
        int_dict.last(lambda key, value: value > 5)


def test_any(int_dict):
    results = int_dict.any(lambda key, value: value == 1)
    assert results is True

    results = int_dict.any(lambda key, value: value == 6)
    assert results is False


def test_all(int_dict):
    results = int_dict.all(lambda key, value: isinstance(value, int))
    assert results is True

    results = int_dict.all(lambda key, value: value == 1)
    assert results is False
