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


# --------------------------------------------------------------------------- #
# Reserved kwarg names (IMP-009)
# --------------------------------------------------------------------------- #


def test_register_warns_when_a_function_declares_a_reserved_kwarg():
    """Declaring ``dag``/``walk_context``/``artifacts`` warns at registration.

    The engine injects its own value for such a parameter, winning over any
    same-named data; the warning tells a registrant who meant the name as
    data.
    """
    registry = FunctionRegistry()
    with pytest.warns(UserWarning, match="reserved kwarg"):
        registry.register("adapter", lambda dag=None, **kwargs: ("ok", dag))
    assert registry.adapts("adapter")  # the flag cache still works


def test_register_warn_reserved_false_silences_the_warning():
    """Batch registrations whose declarations ARE the contract can opt out."""
    registry = FunctionRegistry()
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        registry.register("quiet", lambda dag=None, **kwargs: "ok", warn_reserved=False)
    assert registry.adapts("quiet")


def test_register_no_warning_for_plain_functions():
    """A function that declares no reserved name registers silently."""
    registry = FunctionRegistry()
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        registry.register("plain", lambda **kwargs: "ok")
    assert registry.get("plain") is not None


# --------------------------------------------------------------------------- #
# Per-function parameter schema + generic coercion (opt-in)
# --------------------------------------------------------------------------- #


def test_schema_function_receives_typed_values_from_xml():
    """A schema-registered function driven from XML receives typed values.

    XML attribute values are strings; the schema coerces them to the
    declared types (int / float / bool / str) at injection time.
    """
    registry = FunctionRegistry()
    seen: dict = {}

    def simulate(duration, tolerance, verbose, label, **kwargs):
        seen["duration"] = duration
        seen["tolerance"] = tolerance
        seen["verbose"] = verbose
        seen["label"] = label
        return "ok"

    registry.register(
        "simulate",
        simulate,
        param_types={
            "duration": int,
            "tolerance": float,
            "verbose": bool,
            "label": str,
        },
    )

    xml = (
        "<sequential>"
        '<action function="simulate">'
        '<argument key="duration" value="10"/>'
        '<argument key="tolerance" value="0.5"/>'
        '<argument key="verbose" value="true"/>'
        '<argument key="label" value="run1"/>'
        "</action>"
        "</sequential>"
    )
    run_workflow(xml, registry=registry)
    assert seen["duration"] == 10 and type(seen["duration"]) is int
    assert seen["tolerance"] == 0.5 and type(seen["tolerance"]) is float
    assert seen["verbose"] is True
    assert seen["label"] == "run1" and type(seen["label"]) is str


def test_schema_function_receives_typed_values_from_python_api():
    """The schema also coerces the Python API form (native types pass through)."""
    registry = FunctionRegistry()
    seen: dict = {}

    def simulate(duration, tolerance, verbose, label, **kwargs):
        seen.update(duration=duration, tolerance=tolerance, verbose=verbose, label=label)
        return "ok"

    registry.register(
        "simulate",
        simulate,
        param_types={"duration": int, "tolerance": float, "verbose": bool, "label": str},
    )
    # Native types are already the right type: returned unchanged.
    Test_Framework(
        seq=Sequential(Action("simulate", duration=10, tolerance=0.5, verbose=True, label="run1")),
        registry=registry,
    )
    assert seen["duration"] == 10 and type(seen["duration"]) is int
    assert seen["tolerance"] == 0.5 and type(seen["tolerance"]) is float
    assert seen["verbose"] is True
    assert seen["label"] == "run1"


def test_schema_function_via_workflow_function_decorator():
    """@workflow_function(param_types=...) registers the schema."""
    registry = FunctionRegistry()
    seen: dict = {}

    @workflow_function(
        registry=registry,
        param_types={"count": int, "name": str},
    )
    def batch(count, name, **kwargs):
        seen["count"] = count
        seen["name"] = name
        return "ok"

    xml = (
        "<sequential>"
        '<action function="batch">'
        '<argument key="count" value="7"/>'
        '<argument key="name" value="b"/>'
        "</action>"
        "</sequential>"
    )
    run_workflow(xml, registry=registry)
    assert seen["count"] == 7 and type(seen["count"]) is int
    assert seen["name"] == "b"


def test_no_schema_function_is_unaffected():
    """A function registered without a schema keeps the exact current behavior.

    ``get`` returns the raw function (identity preserved) and XML string
    values pass through uncoerced.
    """
    registry = FunctionRegistry()
    seen: dict = {}

    def simulate(duration, **kwargs):
        seen["duration"] = duration
        return "ok"

    registry.register("simulate", simulate)
    # Identity: no wrapper is introduced.
    assert registry.get("simulate") is simulate
    assert registry.param_types("simulate") is None

    xml = (
        "<sequential>"
        '<action function="simulate"><argument key="duration" value="10"/></action>'
        "</sequential>"
    )
    run_workflow(xml, registry=registry)
    # The string "10" arrives uncoerced (the pre-existing behavior).
    assert seen["duration"] == "10" and type(seen["duration"]) is str


def test_schema_coercion_failure_raises_documented_error():
    """A value that cannot be coerced raises ParameterCoercionError naming
    the parameter and the function."""
    from sequence_extensions.workflow.params import ParameterCoercionError

    registry = FunctionRegistry()

    def simulate(duration, **kwargs):
        return "ok"

    registry.register("simulate", simulate, param_types={"duration": int})

    xml = (
        "<sequential>"
        '<action function="simulate"><argument key="duration" value="not_a_number"/></action>'
        "</sequential>"
    )
    with pytest.raises(ParameterCoercionError) as excinfo:
        run_workflow(xml, registry=registry)
    msg = str(excinfo.value)
    assert "duration" in msg
    assert "simulate" in msg
    assert "int" in msg
    # It is a ValueError subclass, so existing handlers still catch it.
    assert isinstance(excinfo.value, ValueError)


def test_schema_coercion_bool_spellings():
    """The documented boolean spellings are accepted (case-insensitive)."""
    from sequence_extensions.workflow.params import coerce_param

    for truthy in ("true", "True", "TRUE", "1", "yes", "Yes"):
        assert coerce_param(truthy, bool, function_name="f", param_name="b") is True
    for falsy in ("false", "False", "FALSE", "0", "no", "No"):
        assert coerce_param(falsy, bool, function_name="f", param_name="b") is False
    # Anything else is a coercion failure.
    from sequence_extensions.workflow.params import ParameterCoercionError

    with pytest.raises(ParameterCoercionError):
        coerce_param("maybe", bool, function_name="f", param_name="b")


def test_schema_coercion_int_float_promotion_and_str():
    """Non-string values are coerced via target_type(value); str is a no-op."""
    from sequence_extensions.workflow.params import coerce_param

    # int -> float promotion.
    assert coerce_param(10, float, function_name="f", param_name="t") == 10.0
    # bool is NOT "already an int": it is converted.
    assert coerce_param(True, int, function_name="f", param_name="d") == 1
    # int -> str.
    assert coerce_param(3, str, function_name="f", param_name="l") == "3"
    # str -> str is a no-op (no XML remnants).
    assert coerce_param("hello", str, function_name="f", param_name="l") == "hello"


def test_schema_wrapper_is_signature_transparent():
    """The coercion wrapper preserves the original signature and name, so
    the wants_dag / wants_artifacts / wants_context flags and history
    record fidelity are unaffected."""
    import inspect

    registry = FunctionRegistry()

    def simulate(dag=None, duration=0, **kwargs):
        return "ok"

    registry.register("simulate", simulate, param_types={"duration": int})
    wrapper = registry.get("simulate")
    # The wrapper is NOT the raw function (a schema is present)...
    assert wrapper is not simulate
    # ...but it is signature-transparent: inspect.signature resolves to the
    # original, so the cached flags still see the declared `dag` parameter.
    assert registry.adapts("simulate") is True
    assert "dag" in inspect.signature(wrapper).parameters
    # Name fidelity for history records.
    assert wrapper.__name__ == "simulate"
    assert wrapper.__wrapped__ is simulate


def test_schema_param_types_accessor():
    """param_types() returns the registered schema, or None when absent."""
    registry = FunctionRegistry()

    def a(**kwargs):
        return "a"

    def b(**kwargs):
        return "b"

    registry.register("a", a, param_types={"x": int})
    registry.register("b", b)
    assert registry.param_types("a") == {"x": int}
    assert registry.param_types("b") is None
    with pytest.raises(ValueError, match="unknown function"):
        registry.param_types("nope")
