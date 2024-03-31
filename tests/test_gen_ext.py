import pytest

from sequence_extensions import list_ext
from sequence_extensions.gen_ext import gen_ext


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
        self.parent  = None
        self.children : list = []

        self.text = text

    def add_child(self, node ):
        self.children.append(node)
        node.parent = self


def test_recursive(nodes):
    leaf = nodes[-1]
    g1 = gen_ext.recursive_gen(leaf, lambda x: x.parent)
    l1 = list_ext(g1)

    texts = l1.map(lambda x: x.text)

    assert texts == ['node_2', 'node_top']


