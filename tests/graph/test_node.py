"""Tests for the generic node layer (``sequence_extensions.graph.node``)."""

from sequence_extensions.graph.node import Group, Node
from sequence_extensions.workflow.schema import Action, Parallel, Sequential


def build_tree():
    """A three-level tree: group -> (leaf, group -> (leaf, leaf))."""
    leaf_a = Node(name="a")
    leaf_b = Node()
    leaf_c = Node()
    inner = Group(leaf_b, leaf_c, name="inner")
    root = Group(leaf_a, inner)
    return root, leaf_a, inner, leaf_b, leaf_c


class TestNodeConstruction:
    def test_children_stored_as_a_copy(self):
        children = [Node(), Node()]
        node = Node(*children)
        assert node.children == children
        assert node.children is not children
        node.children.append(Node())
        assert len(children) == 2

    def test_name_defaults_to_none(self):
        assert Node().name is None
        assert Node(name="x").name == "x"

    def test_group_is_a_node(self):
        assert issubclass(Group, Node)
        assert isinstance(Group(), Node)

    def test_repr_names_the_type_and_children(self):
        leaf = Node()
        node = Group(leaf, name="g")
        assert repr(node) == f"Group([{leaf!r}])"


class TestContains:
    def test_contains_self(self):
        node = Node()
        assert node.contains(node)

    def test_contains_direct_child_and_deep_descendant(self):
        root, leaf_a, inner, leaf_b, leaf_c = build_tree()
        assert root.contains(leaf_a)
        assert root.contains(inner)
        assert root.contains(leaf_b)
        assert root.contains(leaf_c)
        assert not inner.contains(leaf_a)

    def test_contains_is_identity_not_equality(self):
        # Two structurally equal trees are different tree positions.
        one = Group(Node())
        two = Group(Node())
        assert one != two
        assert not one.contains(two.children[0])


class TestLocate:
    def test_locates_direct_child(self):
        root, leaf_a, inner, _leaf_b, _leaf_c = build_tree()
        assert root.locate(leaf_a) == (root, 0)
        assert root.locate(inner) == (root, 1)

    def test_locates_deep_descendant_with_its_own_parent(self):
        root, _leaf_a, inner, leaf_b, leaf_c = build_tree()
        assert root.locate(leaf_b) == (inner, 0)
        assert root.locate(leaf_c) == (inner, 1)

    def test_absent_target_returns_none_and_minus_one(self):
        root, *_ = build_tree()
        assert root.locate(Node()) == (None, -1)

    def test_root_itself_is_not_locatable_from_itself(self):
        root, *_ = build_tree()
        assert root.locate(root) == (None, -1)

    def test_visits_in_order_first_match_wins(self):
        # Same object appearing twice: the first (leftmost) position wins.
        shared = Node()
        root = Group(shared, Group(shared))
        assert root.locate(shared) == (root, 0)


class TestClone:
    def test_default_copy_preserves_type_and_name(self):
        leaf = Node(name="a")
        clone = leaf.clone()
        assert type(clone) is Node
        assert clone.name == "a"
        assert clone.children == []

        inner = Group(leaf, name="inner")
        clone = inner.clone()
        assert type(clone) is Group
        assert clone.name == "inner"
        assert len(clone.children) == 1

    def test_no_node_object_is_shared(self):
        root, _leaf_a, _inner, _leaf_b, _leaf_c = build_tree()
        clone = root.clone()
        originals = [root, *root.children, *root.children[1].children]
        cloned = [clone, *clone.children, *clone.children[1].children]
        for original, copied in zip(originals, cloned):
            assert original is not copied

    def test_clone_is_deep_by_structure(self):
        root, _leaf_a, _inner, _leaf_b, _leaf_c = build_tree()
        clone = root.clone()
        clone.children[1].children.append(Node())
        assert len(root.children[1].children) == 2

    def test_overrides_reach_the_copy_hook_opaquely(self):
        seen = []

        class Recording(Node):
            def _copy(self, children, overrides):
                seen.append(overrides)
                return super()._copy(children, overrides)

        node = Recording(Recording(), Recording())
        node.clone(tag=1, other=2)
        assert seen == [{"tag": 1, "other": 2}, {"tag": 1, "other": 2}, {"tag": 1, "other": 2}]


class TestWorkflowSpecialization:
    """The workflow node classes are specializations of the generic layer."""

    def test_workflow_nodes_are_generic_nodes(self):
        assert issubclass(Action, Node)
        assert issubclass(Sequential, Group)
        assert issubclass(Parallel, Group)
        assert isinstance(Action("f"), Node)
        assert isinstance(Sequential(), Group)

    def test_action_is_a_leaf(self):
        action = Action("simulate", file="x.csv")
        assert action.children == []
        assert action.name is None

    def test_action_clone_merges_param_overrides(self):
        action = Action("simulate", file="a.csv", level=1)
        clone = action.clone(file="b.csv")
        assert clone.function == "simulate"
        assert clone.params == {"file": "b.csv", "level": 1}
        assert clone is not action
        assert clone.params is not action.params

    def test_group_clone_preserves_type_name_and_globals(self):
        group = Sequential(Action("a"), name="body")
        group.globals = {"model": "./m"}
        clone = group.clone()
        assert type(clone) is Sequential
        assert clone.name == "body"
        assert clone.globals == {"model": "./m"}
        assert clone.globals is not group.globals
        assert isinstance(clone.children[0], Action)

    def test_clone_of_a_parallel_stays_parallel(self):
        clone = Parallel(Action("a")).clone()
        assert type(clone) is Parallel
