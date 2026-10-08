import pytest

from sequence_extensions import list_ext


@pytest.fixture
def simple_int_list():
    return list_ext([1, 2, 3, 4])


@pytest.fixture
def empty_list():
    return list_ext([])


def test_init_empty_then_append():
    l1 = list_ext([1, 2, 3, 4])
    assert l1[0] == 1

    l2 = list_ext()
    l2.append(1)
    assert l2[0] == 1


def test_map(simple_int_list):
    b = simple_int_list.map(lambda x: x * 2)

    assert b == [2, 4, 6, 8]


def test_filter(simple_int_list):
    b = simple_int_list.filter(lambda x: x % 2 == 0)

    assert b == [2, 4]


def test_reduce(simple_int_list):
    def _max(a, b):
        return a if a > b else b

    b = simple_int_list.reduce(_max)

    assert b == 4


def test_zip():
    a = list_ext([1, 2])

    b = [1, 2]

    c = a.zip(b)

    assert c == [(1, 1), (2, 2)]


def test_zip_multi_iterable():
    a = list_ext([1, 2])

    c = a.zip([3, 4], [5, 6])

    assert c == [(1, 3, 5), (2, 4, 6)]


def test_zip_unequal_lengths_truncates():
    a = list_ext([1, 2, 3])

    c = a.zip([10, 20])

    assert c == [(1, 10), (2, 20)]


def test_zip_no_iterables_returns_empty():
    # contract: zip() with no extra iterables returns [] (like builtin zip())
    assert list_ext([1, 2, 3]).zip() == []


def test_for_each(simple_int_list):
    b = []

    def _append(x):
        b.append(x)

    result = simple_int_list.for_each(_append)

    assert result is None
    assert b == [1, 2, 3, 4]
    assert simple_int_list == [1, 2, 3, 4]


def test_get_first(simple_int_list):
    assert simple_int_list.first() == 1


def test_get_first_error(empty_list):
    with pytest.raises(IndexError):
        empty_list.first()


def test_first_or_default_returns_none(empty_list):
    assert empty_list.first_or_default() is None


def test_get_first_default_no_error(empty_list):
    assert empty_list.first_or_default(default=1) == 1


def test_first(simple_int_list):
    f = simple_int_list.first(lambda x: x % 2 == 0)

    assert f == 2


def test_last(simple_int_list):
    f = simple_int_list.last(lambda x: x % 2 == 0)

    assert f == 4


def test_last_or_default(simple_int_list):
    f = simple_int_list.last_or_default(lambda x: x == 10, default=None)

    assert f is None


def test_get_last(simple_int_list):
    assert simple_int_list.last() == 4


def test_to_type(simple_int_list):
    fl = simple_int_list.to_type(float)
    assert fl == [1.0, 2.0, 3.0, 4.0]
    assert all([isinstance(f, float) for f in fl])


def test_to_string(simple_int_list):
    s = simple_int_list.to_string()
    assert s == "1, 2, 3, 4"


def test_to_string_pre(simple_int_list):

    s = simple_int_list.to_string(pre=True)
    assert s == ", 1, 2, 3, 4"


def test_to_string_post(simple_int_list):
    s = simple_int_list.to_string(post=True)
    assert s == "1, 2, 3, 4, "


def test_to_string_custom_separator(simple_int_list):
    s = simple_int_list.to_string(separator="|")
    assert s == "1|2|3|4"


def test_to_string_prefix_suffix(simple_int_list):
    # contract: to_string has new prefix="" / suffix="" params (pre/post unchanged)
    s = simple_int_list.to_string(prefix="[", suffix="]")
    assert s == "[1, 2, 3, 4]"


def test_of_type():
    lst = list_ext([1, "2"])
    assert lst.of_type(str) == ["2"]


def test_of_type_bool_vs_int_isinstance_semantics():
    # contract: of_type uses isinstance — bool is a subclass of int
    lst = list_ext([True, 1, 1.0])
    assert lst.of_type(int) == [True, 1]
    assert lst.of_type(bool) == [True]


def test_to_set(simple_int_list):
    assert {1, 2, 3, 4} == simple_int_list.to_set()


def test_to_tuple(simple_int_list):
    assert (1, 2, 3, 4) == simple_int_list.to_tuple()


def test_to_dict_key(simple_int_list):
    d = simple_int_list.to_dict_key(["a", "b", "c", "d"])

    assert d == {"a": 1, "b": 2, "c": 3, "d": 4}


def test_to_dict_value(simple_int_list):
    v = simple_int_list.to_dict_value(["a", "b", "c", "d"])

    assert v == {1: "a", 2: "b", 3: "c", 4: "d"}


def test_to_dict_key_mismatch_raises():
    # contract: to_dict_key raises ValueError when len(keys) != len(self)
    with pytest.raises(ValueError):
        list_ext([1, 2, 3, 4]).to_dict_key(["a", "b"])


def test_to_dict_value_mismatch_raises():
    # contract: to_dict_value raises ValueError when len(values) != len(self)
    with pytest.raises(ValueError):
        list_ext([1, 2, 3, 4]).to_dict_value(["a", "b"])


def test_to_dict_fn(simple_int_list):
    d = simple_int_list.to_dict_fn(value_func=lambda x: x * 2)

    assert d == {1: 2, 2: 4, 3: 6, 4: 8}


def test_to_dict_fn_key_func_only(simple_int_list):
    d = simple_int_list.to_dict_fn(key_func=lambda x: x * 10)

    assert d == {10: 1, 20: 2, 30: 3, 40: 4}


def test_to_dict_fn_no_funcs(simple_int_list):
    d = simple_int_list.to_dict_fn()

    assert d == {1: 1, 2: 2, 3: 3, 4: 4}


def test_all(simple_int_list):
    results = simple_int_list.all(lambda x: isinstance(x, int))
    assert results is True

    results = simple_int_list.all(lambda x: x == 1)
    assert results is False

    l1 = list_ext([True, True])
    assert l1.all() is True
    l2 = list_ext([True, False])
    assert l2.all() is False


def test_any(simple_int_list):
    results = simple_int_list.any(lambda x: x == 1)
    assert results is True

    results = simple_int_list.any(lambda x: x == 6)
    assert results is False

    l1 = list_ext([True, True])
    assert l1.any() is True
    l2 = list_ext([True, False])
    assert l2.any() is True


def test_contains(simple_int_list):
    assert simple_int_list.contains(4)
    assert not simple_int_list.contains(5)


def test_is_empty(simple_int_list, empty_list):
    assert not simple_int_list.is_empty()
    assert empty_list.is_empty()


def test_single(simple_int_list):
    assert not simple_int_list.is_single()

    result = simple_int_list.single(lambda x: x == 2)
    assert result == 2

    assert list_ext([2]).single() == 2

    # more than one match -> ValueError with a clear message
    with pytest.raises(ValueError, match="Expected exactly one item"):
        simple_int_list.single(lambda x: x % 2 == 0)

    # zero-match case: no item fulfills the condition
    with pytest.raises(ValueError, match="Expected exactly one item"):
        simple_int_list.single(lambda x: x > 100)


def test_execute_or_default_default_exception_tuple():
    # contract: default exception is (IndexError, KeyError) — IndexError caught
    assert list_ext.execute_or_default(lambda: [][0]) is None
    assert list_ext.execute_or_default(lambda: {}["missing"]) is None


def test_execute_or_default_typeerror_propagates():
    # contract: a TypeError from a buggy fn PROPAGATES with the default
    def buggy():
        return 1 + "a"

    with pytest.raises(TypeError):
        list_ext.execute_or_default(buggy)


def test_get_item_or_default_direct():
    lst = list_ext([1, 2])
    assert lst.get_item_or_default(5, default="x") == "x"
    assert lst.get_item_or_default(-1) == 2
    assert lst.get_item_or_default(0) == 1


def test_get_item_or_default_typeerror_caught():
    # contract: get_item_or_default("a", default="D") returns "D" (TypeError caught)
    lst = list_ext([1, 2])
    assert lst.get_item_or_default("a", default="D") == "D"


def test_chainmap():

    lst = list_ext([{"a": 1}, {"b": 2}, {"c": 3}])

    d = lst.chainmap()

    assert d == {"a": 1, "b": 2, "c": 3}


def test_chainmap_duplicate_key_first_wins():

    lst = list_ext([{"a": 1}, {"a": 2, "b": 3}])

    d = lst.chainmap()

    assert d == {"a": 1, "b": 3}


def test_chainmap_empty():
    assert list_ext([]).chainmap() == {}


def test_chainmap_non_dict_items_raise():
    # ChainMap over non-dict items raises (IndexError/TypeError from ChainMap)
    with pytest.raises((IndexError, TypeError)):
        list_ext([{"a": 1}, [1, 2]]).chainmap()


def test_window_select(simple_int_list):
    def f(a, b):
        return a + b

    assert simple_int_list.window_select(f) == [3, 5, 7]

    def f(a, b, c):
        return a + b + c

    assert simple_int_list.window_select(f, n=3) == [6, 9]


def test_window_select_n_greater_than_len(simple_int_list):
    assert simple_int_list.window_select(lambda a, b: a + b, n=5) == []


def test_window(simple_int_list):

    assert simple_int_list.window() == [[1, 2], [2, 3], [3, 4]]

    assert simple_int_list.window(n=3) == [[1, 2, 3], [2, 3, 4]]

    assert simple_int_list.window(n=1) == [[1], [2], [3], [4]]

    assert simple_int_list.window(n=5) == []


def test_window_inner_windows_are_list_ext():
    # contract: window inner windows are list_ext
    windows = list_ext([1, 2, 3]).window()
    assert isinstance(windows[0], list_ext)
    assert isinstance(windows[1], list_ext)
