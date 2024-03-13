import pytest
from sequence_extensions.ext_list import ext_list


@pytest.fixture
def simple_int_list():
    return ext_list([1, 2, 3, 4])


@pytest.fixture
def empty_list():
    return ext_list([])


def test_init_1():
    l1 = ext_list([1, 2, 3, 4])
    assert l1[0] == 1

    l2 = ext_list()
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
    a = ext_list([1, 2])

    b = [1, 2]

    c = a.zip(b)

    assert c == [(1, 1), (2, 2)]


def test_for_each(simple_int_list):
    b = []

    def _append(x):
        b.append(x)

    simple_int_list.for_each(_append)

    assert b == simple_int_list


def test_get_first(simple_int_list):
    assert simple_int_list.first() == 1


def test_get_first_error(empty_list):
    with pytest.raises(IndexError):
        empty_list.first()


def test_get_first_default_error(empty_list):
    assert empty_list.first_or_default() == None


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

    assert f == None


def test_get_last(simple_int_list):
    assert simple_int_list.last() == 4


def test_to_type(simple_int_list):
    fl = simple_int_list.to_type(float)
    assert all([type(f) == float for f in fl])


def test_to_string(simple_int_list):
    s = simple_int_list.to_string()
    assert s == "1, 2, 3, 4"


def test_to_string_pre(simple_int_list):

    s = simple_int_list.to_string(pre=True)
    assert s == ", 1, 2, 3, 4"


def test_of_type():
    l = ext_list([1, "2"])
    assert l.of_type(str) == ["2"]


def test_to_set(simple_int_list):
    assert {1, 2, 3, 4} == simple_int_list.to_set()


def test_to_tuple(simple_int_list):
    assert (1, 2, 3, 4) == simple_int_list.to_tuple()


def test_to_dict(simple_int_list):
    d = simple_int_list.to_dict(["a", "b", "c", "d"])

    assert d == {"a": 1, "b": 2, "c": 3, "d": 4}


def test_all(simple_int_list):
    results = simple_int_list.all(lambda x: True)
    assert results == True

    results = simple_int_list.all(lambda x: False)
    assert results == False


def test_any(simple_int_list):
    results = simple_int_list.any(lambda x: x == 1)
    assert results == True

    results = simple_int_list.any(lambda x: x == 6)
    assert results == False


def test_contains(simple_int_list):
    assert simple_int_list.contains(4)
    assert not simple_int_list.contains(5)


def test_is_empty(simple_int_list, empty_list):
    assert not simple_int_list.is_empty()
    assert empty_list.is_empty()


def test_single(simple_int_list):
    assert not simple_int_list.is_single()

    l = simple_int_list.single(lambda x: x == 2)
    assert l == 2

    assert ext_list([2]).single() == 2

    with pytest.raises(Exception):
        l = simple_int_list.single(lambda x: x % 2 == 0)
