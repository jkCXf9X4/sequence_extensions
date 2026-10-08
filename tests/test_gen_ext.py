import itertools

import pytest

from sequence_extensions import list_ext
from sequence_extensions.ext.gen_ext import gen_ext


@pytest.fixture
def nodes():
    node_top = Node(text="node_top")
    node_1 = Node(text="node_1")
    node_2 = Node(text="node_2")
    node_1_1 = Node(text="node_1_1")
    node_1_2 = Node(text="node_1_2")
    node_2_1 = Node(text="node_2_1")
    node_top.add_child(node_1)
    node_top.add_child(node_2)
    node_1.add_child(node_1_1)
    node_1.add_child(node_1_2)
    node_2.add_child(node_2_1)
    nodes = [node_top, node_1, node_2, node_1_1, node_1_2, node_2_1]
    return nodes


class Node:
    def __init__(self, text="") -> None:
        self.parent = None
        self.children: list = []

        self.text = text

    def add_child(self, node):
        self.children.append(node)
        node.parent = self


def test_recursive(nodes):
    leaf = nodes[-1]
    g1 = gen_ext.recursive_gen(leaf, lambda x: x.parent, stop_f=lambda x: x is not None)
    l1 = list_ext(g1)

    texts = l1.map(lambda x: x.text)

    assert texts == ["node_2", "node_top"]


def test_recursive_stop_f_stops_immediately():
    # stop_f returns False for the very first next item -> nothing is yielded
    assert list(gen_ext.recursive_gen(5, lambda x: x - 1, stop_f=lambda x: False)) == []


def test_recursive_empty_chain():
    # iter_f immediately raises StopIteration -> clean empty result
    def empty_iter(x):
        raise StopIteration

    assert list(gen_ext.recursive_gen(5, empty_iter, stop_f=lambda x: True)) == []


def test_recursive_stop_f_none_infinite_bounded():
    # stop_f=None walks forever; bound the consumption with islice
    g = gen_ext.recursive_gen(0, lambda x: x + 1, stop_f=None)
    assert list(itertools.islice(g, 5)) == [1, 2, 3, 4, 5]


def test_recursive_stop_iteration_terminated_iter_f():
    # contract: recursive_gen catches StopIteration from iter_f and stops
    # cleanly (no RuntimeError)
    def bounded_iter(x):
        if x <= 0:
            raise StopIteration
        return x - 1

    assert list(gen_ext.recursive_gen(3, bounded_iter, stop_f=None)) == [2, 1, 0]


def test_gen_to_list():
    r = gen_ext.to_list(iter([1, 2, 3]))
    assert r == [1, 2, 3]
    assert type(r) is list
