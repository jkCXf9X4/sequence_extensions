"""
Tests for the engine's walk-context injection (IMP-007): the generic
mechanism the artifact store's registry wrapping builds on, the wrapped
registry view, and the engine/store decoupling the design buys (the
engine imports nothing from the store at runtime).
"""

import inspect

import pytest

from sequence_extensions import (
    Action,
    ArtifactStore,
    FunctionRegistry,
    Parallel,
    Sequential,
    Test_Framework,
)
from sequence_extensions.workflow import engine as engine_module
from sequence_extensions.workflow.artifacts import MANIFEST_NAME, WrappedRegistry
from sequence_extensions.workflow.engine import WalkContext

# --------------------------------------------------------------------------- #
# The generic injection: walk_context when declared
# --------------------------------------------------------------------------- #


def test_walk_context_injected_when_declared():
    """A plain-registry function declaring ``walk_context`` receives one."""
    seen = {}

    def probe(walk_context=None, **kwargs):
        seen["context"] = walk_context
        return "ok"

    registry = FunctionRegistry()
    registry.register("probe", probe)
    result = Test_Framework(Sequential(Action("probe")), registry=registry)
    assert result == "ok"
    context = seen["context"]
    assert isinstance(context, WalkContext)
    assert context.node.function == "probe"
    # A root action's chain is exactly one entry: (root group, own index).
    assert len(context.chain) == 1
    root, index = context.chain[0]
    assert isinstance(root, Sequential)
    assert root.children[index] is context.node
    assert index == 0


def test_walk_context_chain_descends_the_ancestry():
    """The chain locates the action root down, one (group, index) per level."""
    chains = []

    def probe(walk_context=None, **kwargs):
        chains.append(walk_context.chain)
        return "ok"

    registry = FunctionRegistry()
    registry.register("probe", probe)
    Test_Framework(
        Sequential(Sequential(Action("probe")), Parallel(Action("probe"))),
        registry=registry,
    )
    assert len(chains) == 2
    # First call: inside the inner Sequential, the root's first child.
    first = chains[0]
    assert len(first) == 2
    assert first[0][0].children[first[0][1]] is first[1][0]
    assert first[1][0].children[first[1][1]] is not None
    # Second call: inside the Parallel, the root's second child — the
    # chain's own parent entry is the Parallel group itself.
    second = chains[1]
    assert len(second) == 2
    assert second[0][1] == 1
    assert isinstance(second[1][0], Parallel)


def test_undeclaring_function_receives_no_walk_context():
    """Without a declaring callee nothing is injected (zero change)."""

    def plain(**kwargs):
        assert "walk_context" not in kwargs
        return dict(kwargs)

    registry = FunctionRegistry()
    registry.register("plain", plain)
    result = Test_Framework(
        Sequential(Action("plain", tag="x")), registry=registry
    )
    assert result == {"tag": "x"}


def test_walk_context_is_a_reserved_name_when_declared():
    """Like ``dag`` / ``artifacts``: the injected context wins."""

    def probe(walk_context=None, **kwargs):
        return walk_context

    registry = FunctionRegistry()
    registry.register("probe", probe)
    result = Test_Framework(
        Sequential(Action("probe", walk_context="user value")),
        registry=registry,
    )
    assert isinstance(result, WalkContext)
    assert result != "user value"


def test_plain_registry_wants_context_flag():
    """The registry's cached flag is signature-derived, like wants_dag."""

    def declaring(walk_context=None, **kwargs):
        return None

    def undeclaring(**kwargs):
        return None

    registry = FunctionRegistry()
    registry.register("declaring", declaring)
    registry.register("undeclaring", undeclaring)
    assert registry.wants_context("declaring")
    assert not registry.wants_context("undeclaring")


# --------------------------------------------------------------------------- #
# The wrapped registry view (the store's plug-in point)
# --------------------------------------------------------------------------- #


def test_wrapped_registry_preserves_inner_flags_and_caches_wrappers(tmp_path):
    """The view wraps lazily, preserves inner flags, never mutates inner."""
    store = ArtifactStore(tmp_path / "run")

    def adapting(dag=None, **kwargs):
        return None

    def plain(**kwargs):
        return None

    inner = FunctionRegistry()
    inner.register("adapting", adapting)
    inner.register("plain", plain)
    view = store.wrap_registry(inner)
    assert isinstance(view, WrappedRegistry)

    # dag / artifacts flags are the inner functions' own.
    assert view.adapts("adapting")
    assert not view.adapts("plain")
    assert not view.uses_artifacts("plain")
    # Every wrapper declares the walk context.
    assert view.wants_context("adapting")
    assert view.wants_context("plain")
    # Wrappers are cached per name and are not the inner functions.
    first = view.get("plain")
    assert first is view.get("plain")
    assert first is not inner.get("plain")
    # The inner registry is never mutated; the view mirrors its surface.
    assert "plain" in view and "plain" in inner
    assert view.names() == inner.names() == ["adapting", "plain"]
    # A re-registration through the view delegates and re-wraps.

    def replacement(**kwargs):
        return "replaced"

    with pytest.warns(UserWarning, match="already registered"):
        view.register("plain", replacement)
    assert view.get("plain") is not first
    assert inner.get("plain") is replacement


def test_wire_store_is_a_passthrough_without_a_store():
    """No store: the registry passes through the wiring unchanged."""
    registry = FunctionRegistry()
    assert engine_module._wire_store(registry, None) is registry


def test_wire_store_opens_the_store_and_wraps_the_registry(tmp_path):
    """With a store: the run root and manifest are created, the view wraps."""
    store = ArtifactStore(tmp_path / "run")
    registry = FunctionRegistry()
    view = engine_module._wire_store(registry, store)
    assert isinstance(view, WrappedRegistry)
    assert view is not registry
    assert (tmp_path / "run" / MANIFEST_NAME).is_file()


# --------------------------------------------------------------------------- #
# The decoupling: the engine carries no store knowledge (IMP-007)
# --------------------------------------------------------------------------- #


def test_engine_module_is_store_free():
    """No runtime artifacts import, no engine-side addressing machinery."""
    # The wiring point talks to the store through its protocol only.
    assert not hasattr(engine_module, "ArtifactStore")
    assert not hasattr(engine_module, "ArtifactHandle")
    # The old engine-side addressing machinery is gone.
    assert not hasattr(engine_module, "_WalkState")
    assert not hasattr(engine_module, "_mint_address")
    assert not hasattr(engine_module, "group_label")
    # The engine itself takes no store; the wiring happens before it.
    parameters = inspect.signature(engine_module._Engine.__init__).parameters
    assert "artifacts" not in parameters
    assert "store" not in parameters
