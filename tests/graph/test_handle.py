"""Tests for the generic scoped tree handle (``sequence_extensions.graph.handle``)."""

import pytest

from sequence_extensions.graph.handle import TreeHandle
from sequence_extensions.graph.node import Group, Node
from sequence_extensions.workflow.schema import Sequential


class RecordingHandle(TreeHandle):
    """A minimal concrete handle: records the emitted writes as plain data."""

    def __init__(self, parent, index, **kwargs):
        super().__init__(parent, index, **kwargs)
        self.emitted = []

    def _emit(self, *, kind, target=None, nodes=(), params=None, scope=None):
        self.emitted.append(
            {
                "kind": kind,
                "target": target,
                "nodes": tuple(nodes),
                "params": params,
                "scope": scope,
            }
        )


def make_scope():
    """``handle -> body(group alpha/group beta)`` in one parent group."""
    alpha = Group(name="alpha")
    beta = Group(name="beta")
    body = Group(alpha, beta, name="body")
    acting = Node(name="acting")
    parent = Group(acting, body)
    return RecordingHandle(parent, 0), acting, body, alpha, beta


class TestReads:
    def test_scope_index_and_read_only(self):
        handle, acting, _body, _alpha, _beta = make_scope()
        assert handle.scope.children[handle.index] is acting
        assert handle.index == 0
        assert handle.read_only is False
        assert RecordingHandle(handle.scope, 0, read_only=True).read_only is True

    def test_following_and_preceding(self):
        handle, acting, body, _alpha, _beta = make_scope()
        assert handle.following() == [body]
        assert handle.preceding() == []
        later = Node()
        handle.scope.children.append(later)
        assert handle.following() == [body, later]
        earlier = Node()
        handle.scope.children.insert(0, earlier)
        assert RecordingHandle(handle.scope, 1).preceding() == [earlier]

    def test_following_group_returns_first_group(self):
        handle, _acting, body, _alpha, _beta = make_scope()
        assert handle.following_group() is body

    def test_following_group_without_a_following_sibling_raises(self):
        parent = Group(Node())
        handle = RecordingHandle(parent, 0)
        with pytest.raises(ValueError, match="no following sibling"):
            handle.following_group()

    def test_following_group_when_first_following_is_a_leaf_raises(self):
        parent = Group(Node(), Node(), Group())
        handle = RecordingHandle(parent, 0)
        with pytest.raises(ValueError, match="not a group"):
            handle.following_group()


class TestValidation:
    def test_read_only_handle_rejects_writes(self):
        handle, _acting, body, _alpha, _beta = make_scope()
        handle._read_only = True
        with pytest.raises(ValueError, match="read-only"):
            handle.replace(body, [Group()])

    def test_target_must_be_a_node(self):
        handle, _acting, _body, _alpha, _beta = make_scope()
        with pytest.raises(ValueError, match="target must be a node"):
            handle._check_target("not a node", allow_preceding=False)

    def test_out_of_scope_target_raises(self):
        handle, _acting, _body, _alpha, _beta = make_scope()
        outsider = Group(Node())
        with pytest.raises(ValueError, match="scope"):
            handle._check_target(outsider, allow_preceding=False)

    def test_preceding_target_allowed_only_as_copy_source(self):
        handle, _acting, _body, _alpha, _beta = make_scope()
        before = Node(name="before")
        handle.scope.children.insert(0, before)
        handle = RecordingHandle(handle.scope, 1)
        with pytest.raises(ValueError, match="scope"):
            handle._check_target(before, allow_preceding=False)
        handle._check_target(before, allow_preceding=True)

    def test_nodes_must_be_nodes(self):
        handle, _acting, _body, _alpha, _beta = make_scope()
        single = Node()
        assert handle._check_nodes(single) == (single,)
        assert len(handle._check_nodes([Node(), Node()])) == 2
        with pytest.raises(ValueError, match="must be a node or a list"):
            handle._check_nodes("nope")
        with pytest.raises(ValueError, match="must be nodes"):
            handle._check_nodes([Node(), 42])

    def test_default_emit_hook_is_abstract(self):
        parent = Group(Node())
        handle = TreeHandle(parent, 0)
        with pytest.raises(NotImplementedError, match="_emit"):
            handle._emit(kind="replace")

    def test_default_empty_group_is_a_generic_group(self):
        parent = Group(Node())
        empty = TreeHandle(parent, 0)._empty_group()
        assert isinstance(empty, Group)
        assert empty.children == []


class TestWriteOps:
    def test_replace_emits_one_op(self):
        handle, _acting, body, alpha, _beta = make_scope()
        replacement = Group(alpha)
        handle.replace(body, [replacement])
        assert handle.emitted == [
            {
                "kind": "replace",
                "target": body,
                "nodes": (replacement,),
                "params": None,
                "scope": None,
            }
        ]

    def test_replace_wraps_a_single_node(self):
        handle, _acting, body, _alpha, _beta = make_scope()
        replacement = Group()
        handle.replace(body, replacement)
        assert handle.emitted[0]["nodes"] == (replacement,)

    def test_replace_needs_at_least_one_node(self):
        handle, _acting, body, _alpha, _beta = make_scope()
        with pytest.raises(ValueError, match="at least one"):
            handle.replace(body, [])
        assert handle.emitted == []

    def test_append_emits_with_the_scope(self):
        handle, _acting, _body, _alpha, _beta = make_scope()
        appended = Node()
        handle.append([appended])
        assert handle.emitted == [
            {
                "kind": "append",
                "target": None,
                "nodes": (appended,),
                "params": None,
                "scope": handle.scope,
            }
        ]

    def test_append_needs_at_least_one_node(self):
        handle, _acting, _body, _alpha, _beta = make_scope()
        with pytest.raises(ValueError, match="at least one"):
            handle.append([])


class TestCloneOps:
    def test_copy_clones_the_target(self):
        handle, _acting, body, _alpha, _beta = make_scope()
        clone = handle.copy(body)
        assert clone is not body
        assert clone.name == "body"
        assert len(clone.children) == 2

    def test_copy_self_clones_the_acting_node(self):
        handle, acting, _body, _alpha, _beta = make_scope()
        clone = handle.copy_self()
        assert clone is not acting
        assert clone.name == "acting"

    def test_adjusted_clones_the_first_following_sibling(self):
        handle, _acting, body, _alpha, _beta = make_scope()
        clone = handle.adjusted()
        assert clone.name == "body"


class TestPatterns:
    def test_fan_out_clones_per_override_set_and_replaces(self):
        handle, _acting, body, _alpha, _beta = make_scope()
        handle.fan_out([{"tag": 1}, {"tag": 2}])
        assert len(handle.emitted) == 1
        op = handle.emitted[0]
        assert op["kind"] == "replace"
        assert op["target"] is body
        assert len(op["nodes"]) == 2
        assert [clone.name for clone in op["nodes"]] == ["body", "body"]

    def test_fan_out_needs_at_least_one_override_set(self):
        handle, _acting, _body, _alpha, _beta = make_scope()
        with pytest.raises(ValueError, match="at least one"):
            handle.fan_out([])
        assert handle.emitted == []

    def test_fan_out_overrides_must_be_mappings(self):
        handle, _acting, _body, _alpha, _beta = make_scope()
        with pytest.raises(ValueError, match="mappings"):
            handle.fan_out([{"tag": 1}, "nope"])
        assert handle.emitted == []

    def test_select_replaces_the_group_with_the_named_child(self):
        handle, _acting, body, alpha, beta = make_scope()
        chosen = handle.select("beta")
        assert chosen is beta
        assert handle.emitted == [
            {"kind": "replace", "target": body, "nodes": (beta,), "params": None, "scope": None}
        ]

    def test_select_uses_the_default_when_the_name_misses(self):
        handle, _acting, body, alpha, _beta = make_scope()
        assert handle.select("gamma", "alpha") is alpha

    def test_select_default_must_be_a_named_child(self):
        handle, _acting, _body, _alpha, _beta = make_scope()
        with pytest.raises(ValueError, match="default"):
            handle.select("gamma", "delta")

    def test_select_without_a_match_or_default_raises(self):
        handle, _acting, _body, _alpha, _beta = make_scope()
        with pytest.raises(ValueError, match="no alternative named"):
            handle.select("gamma")

    def test_skip_replaces_the_group_with_one_empty_group(self):
        handle, _acting, body, _alpha, _beta = make_scope()
        handle.skip()
        (op,) = handle.emitted
        assert op["kind"] == "replace"
        assert op["target"] is body
        assert len(op["nodes"]) == 1
        assert op["nodes"][0].children == []

    def test_skip_following_replaces_each_following_sibling(self):
        handle, _acting, body, _alpha, _beta = make_scope()
        extra = Node()
        handle.scope.children.append(extra)
        handle.skip_following()
        assert [op["target"] for op in handle.emitted] == [body, extra]
        assert {len(op["nodes"]) for op in handle.emitted} == {1}

    def test_repeat_appends_body_copies_plus_a_copy_of_self(self):
        handle, _acting, body, _alpha, _beta = make_scope()
        before = Node(name="before")
        handle.scope.children.insert(0, before)
        handle = RecordingHandle(handle.scope, 1)
        handle.repeat()
        (op,) = handle.emitted
        assert op["kind"] == "append"
        assert op["scope"] is handle.scope
        assert len(op["nodes"]) == 2
        assert op["nodes"][0].name == "before"
        assert op["nodes"][1].name == "acting"

    def test_repeat_needs_a_preceding_body(self):
        handle, _acting, _body, _alpha, _beta = make_scope()
        with pytest.raises(ValueError, match="preceded"):
            handle.repeat()
        assert handle.emitted == []


class TestDomainInheritance:
    """The workflow handles are specializations of the generic handle."""

    def test_dag_and_replay_handles_subclass_the_generic_handle(self):
        from sequence_extensions.workflow.adaptation import DAGHandle
        from sequence_extensions.workflow.history import ReplayHandle

        assert issubclass(DAGHandle, TreeHandle)
        assert issubclass(ReplayHandle, TreeHandle)

    def test_dag_handle_flows_come_from_the_generic_layer(self):
        from sequence_extensions.workflow.adaptation import DAGHandle

        assert DAGHandle.copy is TreeHandle.copy
        assert DAGHandle.fan_out is TreeHandle.fan_out
        assert DAGHandle.select is TreeHandle.select
        assert DAGHandle.skip is TreeHandle.skip
        assert DAGHandle.skip_following is TreeHandle.skip_following
        assert DAGHandle.repeat is TreeHandle.repeat

    def test_dag_handle_empty_group_is_a_sequential(self):
        from sequence_extensions.workflow.adaptation import DAGHandle

        parent = Sequential(Node())
        empty = DAGHandle(parent, 0)._empty_group()
        assert type(empty) is Sequential
        assert isinstance(empty, Group)
