"""
Tests for the workflow function registry (``sequence_extensions.workflow.registry``):
``FunctionRegistry`` / ``DEFAULT_REGISTRY`` and the ``workflow_function`` /
``registry.function`` decorators.
"""

import subprocess
import sys
import warnings

import pytest

from resources import workflow_stubs
from sequence_extensions import (
    DEFAULT_REGISTRY,
    Action,
    FunctionRegistry,
    Sequential,
    Test_Framework,
    run_workflow,
    workflow_function,
)


def test_default_registry_is_empty_by_default():
    """A fresh interpreter (no user registrations) sees an empty DEFAULT_REGISTRY.

    Checked in a subprocess because the test process itself registers the
    paper's stubs in DEFAULT_REGISTRY (via the decorator, like real
    library functions would).
    """
    code = (
        "import sequence_extensions as se\n"
        "names = se.DEFAULT_REGISTRY.names()\n"
        "assert names == [], names\n"
    )
    proc = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert proc.returncode == 0, proc.stderr


def test_registry_register_get_names():
    """.register / .get / .names work on a fresh FunctionRegistry."""
    registry = FunctionRegistry()

    def my_fn(**kwargs):
        return "ok"

    registry.register("my_fn", my_fn)
    assert "my_fn" in registry.names()
    assert registry.get("my_fn") is my_fn


def test_unknown_action_name_raises_clear_error():
    """An unknown function name at run time raises a ValueError naming it."""
    xml = "<sequential><action function='definitely_not_a_function'/></sequential>"
    with pytest.raises(ValueError, match="definitely_not_a_function"):
        run_workflow(xml)


# --- decorator registration (workflow_function / registry.function) ---


def test_workflow_function_bare_registers_under_own_name(pristine_default_registry):
    """@workflow_function registers the function under its own name in DEFAULT_REGISTRY."""

    @workflow_function
    def my_task(**kwargs):
        return "done"

    # Registered under its own name (after the paper stubs imported earlier).
    assert pristine_default_registry.names()[-1] == "my_task"
    assert pristine_default_registry.get("my_task") is my_task
    # The function is returned unchanged and stays directly callable.
    assert my_task() == "done"


def test_workflow_function_name_and_registry_kwargs():
    """name= and registry= steer the registry name and the target registry."""
    registry = FunctionRegistry()

    @workflow_function(name="task", registry=registry)
    def _my_task(**kwargs):
        return "done"

    assert registry.names() == ["task"]
    assert registry.get("task") is _my_task
    assert "my_task" not in registry
    # Nothing landed in DEFAULT_REGISTRY.
    assert "task" not in DEFAULT_REGISTRY


def test_workflow_function_rejects_empty_name():
    """An empty name raises the same ValueError as FunctionRegistry.register."""
    with pytest.raises(ValueError, match="non-empty"):
        workflow_function(name="")(lambda **kwargs: None)


def test_workflow_function_reregister_replaces_and_warns(pristine_default_registry):
    """Decorating twice under one name warns and replaces the earlier registration."""

    @workflow_function
    def first_version(**kwargs):
        return 1

    def second_version(**kwargs):
        return 2

    with pytest.warns(UserWarning, match="already registered"):
        workflow_function(name="first_version")(second_version)

    assert pristine_default_registry.names()[-1] == "first_version"
    assert pristine_default_registry.get("first_version")() == 2


def test_register_warns_on_replacement_but_not_on_same_function():
    """register warns when replacing a different function; same object is silent."""

    def first(**kwargs):
        return 1

    def second(**kwargs):
        return 2

    registry = FunctionRegistry()
    registry.register("dup", first)
    with pytest.warns(UserWarning, match="already registered"):
        registry.register("dup", second)
    assert registry.get("dup") is second

    # Re-registering the same function object is a silent no-op.
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        registry.register("dup", second)
    assert registry.get("dup") is second


def test_registry_function_decorator_registers_in_that_registry():
    """registry.function() registers in that registry (parenthesized and bare)."""
    registry = FunctionRegistry()

    @registry.function()
    def stub_a(**kwargs):
        return "a"

    @registry.function(name="b")
    def _stub_b(**kwargs):
        return "b"

    @registry.function
    def stub_c(**kwargs):
        return "c"

    # Without name=, the registry name is the function's own __name__.
    assert registry.names() == ["stub_a", "b", "stub_c"]
    assert registry.get("stub_a") is stub_a
    assert registry.get("b") is _stub_b
    assert registry.get("stub_c") is stub_c
    # The custom registry got the functions, not DEFAULT_REGISTRY.
    for name in ("stub_a", "b", "stub_c"):
        assert name not in DEFAULT_REGISTRY


def test_decorated_function_is_addressable_via_workflow_schema(pristine_default_registry):
    """A decorator-registered function runs from workflow XML and the Python API."""

    @workflow_function
    def add_one(value="0", **kwargs):
        return int(value) + 1

    xml = (
        "<sequential>"
        '<action function="add_one"><argument key="value" value="41"/></action>'
        "</sequential>"
    )
    assert run_workflow(xml) == 42
    assert Test_Framework(seq=Sequential(Action("add_one", value="41"))) == 42


def test_registry_function_end_to_end_via_xml():
    """A function registered via registry.function() runs through run_workflow."""
    registry = FunctionRegistry()

    @registry.function()
    def double(value="0", **kwargs):
        return int(value) * 2

    xml = (
        "<sequential>"
        '<action function="double"><argument key="value" value="21"/></action>'
        "</sequential>"
    )
    assert run_workflow(xml, registry=registry) == 42


def test_paper_stubs_registered_in_default_registry():
    """The paper's seven stubs are registered in DEFAULT_REGISTRY under their paper names."""
    assert DEFAULT_REGISTRY.names() == [
        "find_files",
        "simulate",
        "evaluate_results",
        "find_test_cases",
        "parameter_sweep",
        "compare_parameter_sweep",
        "compare_results",
    ]
    # The registered callables are the stub functions themselves.
    assert DEFAULT_REGISTRY.get("find_files") is workflow_stubs.find_files
    assert DEFAULT_REGISTRY.get("simulate") is workflow_stubs.simulate
