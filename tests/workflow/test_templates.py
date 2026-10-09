"""
Tests for the template mechanism (``sequence_extensions.workflow.schema``):
``Template`` — a named, parameterized subtree that instantiates into a
``Sequential`` / ``Parallel`` group with bound parameters — and its XML
surface (``<template>`` definitions, ``<use-template>`` use sites), which
``parse_workflow`` expands at parse time.

This closes the paper's design-principle-4 gap ("actions with parameters
form templates for common verification scenarios, limiting duplication
between workflows"): a verification scenario is written once as a template
and reused — from XML and from the Python API — with different parameters
per use site.

Sections:

* **1. Python API** — ``Template`` construction, ``instantiate`` (distinct
  node trees per parameter set, placeholder substitution rules, defaults,
  error cases).
* **2. XML parsing** — valid documents (the ``template_reuse`` /
  ``template_parallel`` fixtures and inline XML), equivalence with the
  inline form, and every template rejection rule (the ``invalid/``
  fixtures).
* **3. Execution** — workflows that use templates run through
  ``run_workflow`` and ``Test_Framework``: parameter resolution (globals,
  upstream results, own parameters), templates inside parallel groups,
  and dynamic adaptation splicing a subtree that contains a template
  instantiation.
* **4. History** — template-expanded actions are ordinary actions after
  expansion, so the history records them like any other action.
"""

from __future__ import annotations

import threading

import pytest

from resources import workflows
from sequence_extensions import (
    Action,
    FunctionRegistry,
    Parallel,
    Sequential,
    Template,
    Test_Framework,
    parse_workflow,
    run_workflow,
)
from sequence_extensions.workflow.history import RunHistory, replay

from . import _make_recorder, _names_in_order

# The two template example documents (see tests/resources/workflows/).
TEMPLATE_REUSE = workflows.load("template_reuse.xml")
TEMPLATE_PARALLEL = workflows.load("template_parallel.xml")


# --------------------------------------------------------------------------- #
# 1. PYTHON API — Template / instantiate
# --------------------------------------------------------------------------- #


def test_template_instantiate_returns_distinct_trees():
    """Instantiating the same template twice yields distinct, independent trees."""
    template = Template(
        "file_check",
        Sequential(
            Action("simulate", file="{file}"),
            Action("evaluate_results", file="{file}"),
        ),
    )
    first = template.instantiate(file="case_1.csv")
    second = template.instantiate(file="case_2.csv")
    assert isinstance(first, Sequential) and isinstance(second, Sequential)
    # Distinct node objects at every level: no sharing with the body or
    # between instantiations.
    assert first is not second
    assert first.children[0] is not second.children[0]
    assert first.children[0] is not template.body.children[0]
    # ... and the parameters are bound per instantiation.
    assert first.children[0].params == {"file": "case_1.csv"}
    assert second.children[0].params == {"file": "case_2.csv"}


def test_template_instantiate_binds_every_occurrence():
    """A placeholder used in several actions is bound everywhere at once."""
    template = Template(
        "file_check",
        Sequential(
            Action("simulate", file="{file}"),
            Action("evaluate_results", file="{file}"),
        ),
    )
    tree = template.instantiate(file="case_1.csv")
    assert [child.params for child in tree.children] == [
        {"file": "case_1.csv"},
        {"file": "case_1.csv"},
    ]


def test_template_default_used_when_not_bound():
    """A declared default fills in when the use site does not bind the parameter."""
    template = Template(
        "check",
        Sequential(Action("evaluate_results", tolerance="{tolerance}")),
        tolerance="0.01",
    )
    assert template.instantiate().children[0].params == {"tolerance": "0.01"}
    assert template.instantiate(tolerance="0.05").children[0].params == {"tolerance": "0.05"}


def test_template_binding_wins_over_default():
    """A use-site binding overrides the template's default value."""
    template = Template(
        "check",
        Sequential(Action("a", p="{p}")),
        p="default",
    )
    assert template.instantiate(p="bound").children[0].params == {"p": "bound"}


def test_template_whole_value_placeholder_preserves_type():
    """A placeholder filling a whole value is replaced by the value itself."""
    template = Template(
        "sweep",
        Sequential(Action("parameter_sweep", values="{values}")),
    )
    tree = template.instantiate(values=[5, 10, 15])
    assert tree.children[0].params == {"values": [5, 10, 15]}


def test_template_non_string_parameter_untouched():
    """A non-string action parameter carries no placeholders and is copied as-is."""
    template = Template(
        "sweep",
        Sequential(Action("parameter_sweep", values=[5, 10, 15], n=3)),
    )
    tree = template.instantiate()
    assert tree.children[0].params == {"values": [5, 10, 15], "n": 3}


def test_template_embedded_placeholder_stringifies():
    """A placeholder inside a longer string is replaced by its string form."""
    template = Template(
        "check",
        Sequential(Action("simulate", path="{model}/case.csv")),
    )
    tree = template.instantiate(model="./model_1")
    assert tree.children[0].params == {"path": "./model_1/case.csv"}


def test_template_embedded_placeholder_stringifies_non_strings():
    """A non-string bound value inside a longer string uses its string form."""
    template = Template("check", Sequential(Action("a", path="run_{n}/out")))
    assert template.instantiate(n=7).children[0].params == {"path": "run_7/out"}


def test_template_unresolved_placeholder_is_an_error():
    """A placeholder that resolves to nothing is a strict error."""
    template = Template("check", Sequential(Action("a", p="{unknown}")))
    with pytest.raises(ValueError, match="requires parameter"):
        template.instantiate()


def test_template_single_action_body_is_wrapped():
    """A single-Action body is wrapped in a Sequential so instantiation is a group."""
    template = Template("one", Action("a", p="{p}"))
    tree = template.instantiate(p="x")
    assert isinstance(tree, Sequential)
    assert len(tree.children) == 1
    assert tree.children[0].function == "a"
    assert tree.children[0].params == {"p": "x"}


def test_template_parallel_body():
    """A Parallel body instantiates as a Parallel group."""
    template = Template(
        "fan_out",
        Parallel(Action("a", p="{p}"), Action("b", p="{p}")),
    )
    tree = template.instantiate(p="x")
    assert isinstance(tree, Parallel)
    assert [child.params for child in tree.children] == [{"p": "x"}, {"p": "x"}]


def test_template_nested_groups():
    """Placeholders bind through arbitrarily nested groups."""
    template = Template(
        "nested",
        Sequential(
            Action("a", p="{p}"),
            Parallel(Action("b", q="{p}"), Sequential(Action("c", r="{p}"))),
        ),
    )
    tree = template.instantiate(p="x")
    assert tree.children[0].params == {"p": "x"}
    assert tree.children[1].children[0].params == {"q": "x"}
    assert tree.children[1].children[1].children[0].params == {"r": "x"}


def test_template_parameters_property():
    """``parameters`` lists declared names: defaults plus placeholders."""
    template = Template(
        "t",
        Sequential(Action("a", p="{p}", q="{q}")),
        d="default",
    )
    assert template.parameters == ["d", "p", "q"]


def test_template_repr():
    """The repr names the template, its body and its defaults."""
    template = Template("t", Sequential(Action("a")), p="x")
    assert repr(template) == "Template('t', Sequential([Action('a', {})]), {'p': 'x'})"


def test_template_rejects_bad_name():
    """A template name must be a non-empty string."""
    with pytest.raises(ValueError, match="non-empty"):
        Template("", Sequential(Action("a")))
    with pytest.raises(ValueError, match="non-empty"):
        Template(None, Sequential(Action("a")))  # type: ignore[arg-type]


def test_template_rejects_bad_body():
    """A template body must be an Action, Sequential or Parallel."""
    with pytest.raises(ValueError, match="body must be"):
        Template("t", "not-a-node")  # type: ignore[arg-type]


def test_template_instantiate_rejects_undeclared_parameter():
    """Binding a parameter the template does not declare is an error."""
    template = Template("t", Sequential(Action("a", p="{p}")))
    with pytest.raises(ValueError, match="has no parameter 'wrong'"):
        template.instantiate(wrong="x")


def test_template_instantiate_requires_required_parameters():
    """A placeholder with no binding and no default is an error."""
    template = Template("t", Sequential(Action("a", p="{p}")))
    with pytest.raises(ValueError, match="requires parameter"):
        template.instantiate()


def test_template_body_is_not_mutated_by_instantiation():
    """The template body keeps its placeholders after an instantiation."""
    template = Template("t", Sequential(Action("a", p="{p}")))
    template.instantiate(p="x")
    assert template.body.children[0].params == {"p": "{p}"}


def test_template_keyword_parameter_names():
    """Template parameters may be Python keywords (positional-only API)."""
    template = Template("t", Sequential(Action("a", class_="{class}")))
    tree = template.instantiate(**{"class": "model_1"})
    assert tree.children[0].params == {"class_": "model_1"}


# --------------------------------------------------------------------------- #
# 2. XML PARSING — <template> definitions and <use-template> use sites
# --------------------------------------------------------------------------- #


def test_parse_template_reuse_structure():
    """The template_reuse fixture expands to the two per-file chains."""
    root = parse_workflow(TEMPLATE_REUSE)
    assert isinstance(root, Sequential)
    assert len(root.children) == 2
    for index, file in enumerate(("case_1.csv", "case_2.csv")):
        chain = root.children[index]
        assert isinstance(chain, Sequential)
        assert [child.function for child in chain.children] == [
            "simulate",
            "evaluate_results",
        ]
        assert chain.children[0].params == {"file": file, "model": "./model_1"}
        assert chain.children[1].params == {"file": file}
    # The global parameter is exposed on the root as usual.
    assert root.globals == {"model": "./model_1"}


def test_parse_template_parallel_structure():
    """The template_parallel fixture expands inside a parallel group."""
    root = parse_workflow(TEMPLATE_PARALLEL)
    assert isinstance(root, Parallel)
    assert len(root.children) == 2
    first, second = root.children
    assert isinstance(first, Sequential) and isinstance(second, Sequential)
    # Default tolerance at the first use site, overridden at the second.
    assert first.children[1].params["tolerance"] == "0.01"
    assert second.children[1].params["tolerance"] == "0.05"
    # The model global is resolved through the template body.
    assert first.children[0].params["model"] == "./model_1"


def test_parse_template_expansion_equals_inline():
    """A template use expands to exactly the tree the inline form produces."""
    with_template = parse_workflow(TEMPLATE_REUSE)
    inline = parse_workflow(
        "<VerificationWorkflow>"
        '<argument key="model" value="./model_1"/>'
        "<sequential>"
        "<sequential>"
        '<action function="simulate">'
        '<argument key="file" value="case_1.csv"/>'
        '<argument key="model" value="./model_1"/>'
        "</action>"
        '<action function="evaluate_results">'
        '<argument key="file" value="case_1.csv"/>'
        "</action>"
        "</sequential>"
        "<sequential>"
        '<action function="simulate">'
        '<argument key="file" value="case_2.csv"/>'
        '<argument key="model" value="./model_1"/>'
        "</action>"
        '<action function="evaluate_results">'
        '<argument key="file" value="case_2.csv"/>'
        "</action>"
        "</sequential>"
        "</sequential>"
        "</VerificationWorkflow>"
    )
    assert _describe(with_template) == _describe(inline)


def test_parse_template_use_inside_template_body():
    """A template body may use a template defined before it."""
    root = parse_workflow(
        "<VerificationWorkflow>"
        '<template name="inner">'
        "<sequential>"
        '<action function="a"><argument key="p" value="{p}"/></action>'
        "</sequential>"
        "</template>"
        '<template name="outer">'
        "<sequential>"
        '<use-template name="inner">'
        '<argument key="p" value="{q}"/>'
        "</use-template>"
        "</sequential>"
        "</template>"
        "<sequential>"
        '<use-template name="outer">'
        '<argument key="q" value="x"/>'
        "</use-template>"
        "</sequential>"
        "</VerificationWorkflow>"
    )
    assert _describe(root) == {
        "sequential": [
            {
                "sequential": [
                    {
                        "sequential": [
                            {"function": "a", "params": {"p": "x"}},
                        ],
                    },
                ],
            },
        ],
    }


def test_parse_template_action_body():
    """A bare <action> template body is wrapped in a Sequential."""
    root = parse_workflow(
        "<VerificationWorkflow>"
        '<template name="t">'
        '<action function="a"><argument key="p" value="{p}"/></action>'
        "</template>"
        "<sequential>"
        '<use-template name="t"><argument key="p" value="x"/></use-template>'
        "</sequential>"
        "</VerificationWorkflow>"
    )
    chain = root.children[0]
    assert isinstance(chain, Sequential)
    assert chain.children[0].params == {"p": "x"}


def test_parse_template_in_bare_group_root():
    """Templates work in a bare <sequential> root when defined in the wrapper..."""
    # A bare root has no wrapper, so no <template> can be defined there;
    # the use site must name a template that does not exist.
    with pytest.raises(ValueError, match="unknown template"):
        parse_workflow('<sequential><use-template name="t"/></sequential>')


def test_parse_template_definitions_may_surround_grouping():
    """Definitions and globals may appear in any order around the grouping."""
    root = parse_workflow(
        "<VerificationWorkflow>"
        '<sequential><use-template name="t"/></sequential>'
        '<template name="t"><sequential><action function="a"/></sequential></template>'
        "</VerificationWorkflow>"
    )
    assert _describe(root) == {"sequential": [{"sequential": [{"function": "a", "params": {}}]}]}


def test_parse_template_global_fills_required_parameter():
    """A same-named global parameter satisfies a required template parameter."""
    root = parse_workflow(
        "<VerificationWorkflow>"
        '<argument key="model" value="./model_1"/>'
        '<template name="t">'
        "<sequential>"
        '<action function="a"><argument key="m" value="{model}"/></action>'
        "</sequential>"
        "</template>"
        '<sequential><use-template name="t"/></sequential>'
        "</VerificationWorkflow>"
    )
    assert root.children[0].children[0].params == {"m": "./model_1"}


def test_parse_template_binding_wins_over_global():
    """A use-site binding overrides a same-named global parameter."""
    root = parse_workflow(
        "<VerificationWorkflow>"
        '<argument key="model" value="./model_1"/>'
        '<template name="t">'
        "<sequential>"
        '<action function="a"><argument key="m" value="{model}"/></action>'
        "</sequential>"
        "</template>"
        "<sequential>"
        '<use-template name="t">'
        '<argument key="model" value="./model_2"/>'
        "</use-template>"
        "</sequential>"
        "</VerificationWorkflow>"
    )
    assert root.children[0].children[0].params == {"m": "./model_2"}


def test_parse_template_default_wins_over_global():
    """A template default overrides a same-named global parameter."""
    root = parse_workflow(
        "<VerificationWorkflow>"
        '<argument key="model" value="./model_1"/>'
        '<template name="t">'
        '<argument key="model" value="./default"/>'
        "<sequential>"
        '<action function="a"><argument key="m" value="{model}"/></action>'
        "</sequential>"
        "</template>"
        '<sequential><use-template name="t"/></sequential>'
        "</VerificationWorkflow>"
    )
    assert root.children[0].children[0].params == {"m": "./default"}


def test_parse_template_rejects_self_reference():
    """A template cannot reference itself (expansion must stay finite)."""
    with pytest.raises(ValueError, match="unknown template 'loop'"):
        parse_workflow(
            "<VerificationWorkflow>"
            '<template name="loop">'
            '<sequential><use-template name="loop"/></sequential>'
            "</template>"
            '<sequential><use-template name="loop"/></sequential>'
            "</VerificationWorkflow>"
        )


def test_parse_template_rejects_forward_reference():
    """A template cannot use a template defined after it."""
    with pytest.raises(ValueError, match="unknown template 'later'"):
        parse_workflow(
            "<VerificationWorkflow>"
            '<template name="first">'
            '<sequential><use-template name="later"/></sequential>'
            "</template>"
            '<template name="later">'
            '<sequential><action function="a"/></sequential>'
            "</template>"
            '<sequential><use-template name="first"/></sequential>'
            "</VerificationWorkflow>"
        )


def test_parse_rejects_template_without_name():
    """A <template> must carry a name attribute."""
    with pytest.raises(ValueError):
        parse_workflow(workflows.load("invalid/template_without_name.xml"))


def test_parse_rejects_template_without_body():
    """A <template> must contain exactly one body group."""
    with pytest.raises(ValueError):
        parse_workflow(workflows.load("invalid/template_without_body.xml"))


def test_parse_rejects_template_multiple_bodies():
    """A <template> with two body groups is ambiguous and rejected."""
    with pytest.raises(ValueError):
        parse_workflow(workflows.load("invalid/template_multiple_bodies.xml"))


def test_parse_rejects_template_unknown_element():
    """Only groups, actions and <argument> defaults may appear in a <template>."""
    with pytest.raises(ValueError):
        parse_workflow(workflows.load("invalid/template_unknown_element.xml"))


def test_parse_rejects_template_duplicate_argument():
    """A duplicate default key on one <template> is rejected."""
    with pytest.raises(ValueError):
        parse_workflow(workflows.load("invalid/template_duplicate_argument.xml"))


def test_parse_rejects_duplicate_template_name():
    """Two <template> definitions with the same name are rejected."""
    with pytest.raises(ValueError):
        parse_workflow(workflows.load("invalid/duplicate_template_name.xml"))


def test_parse_rejects_template_inside_grouping():
    """<template> definitions live in the wrapper, not inside groupings."""
    with pytest.raises(ValueError):
        parse_workflow(workflows.load("invalid/template_inside_grouping.xml"))


def test_parse_rejects_use_template_without_name():
    """A <use-template> must carry a name attribute."""
    with pytest.raises(ValueError):
        parse_workflow(workflows.load("invalid/use_template_without_name.xml"))


def test_parse_rejects_use_template_unknown_name():
    """A <use-template> naming an undefined template is rejected."""
    with pytest.raises(ValueError):
        parse_workflow(workflows.load("invalid/use_template_unknown_name.xml"))


def test_parse_rejects_use_template_unknown_element():
    """Only <argument> bindings may appear in a <use-template>."""
    with pytest.raises(ValueError):
        parse_workflow(workflows.load("invalid/use_template_unknown_element.xml"))


def test_parse_rejects_use_template_undeclared_argument():
    """Binding a parameter the template does not declare is rejected."""
    with pytest.raises(ValueError):
        parse_workflow(workflows.load("invalid/use_template_undeclared_argument.xml"))


def test_parse_rejects_use_template_duplicate_argument():
    """A duplicate binding key on one <use-template> is rejected."""
    with pytest.raises(ValueError):
        parse_workflow(workflows.load("invalid/use_template_duplicate_argument.xml"))


def test_parse_rejects_use_template_missing_argument():
    """Leaving a required parameter unbound is rejected."""
    with pytest.raises(ValueError):
        parse_workflow(workflows.load("invalid/use_template_missing_argument.xml"))


# --------------------------------------------------------------------------- #
# 3. EXECUTION — templates through the engine
# --------------------------------------------------------------------------- #


def test_run_workflow_executes_template_workflow():
    """run_workflow runs a template workflow exactly like its inline form."""
    registry, calls = _make_recorder(["simulate", "evaluate_results"])
    result = run_workflow(TEMPLATE_REUSE, registry=registry)
    assert _names_in_order(calls) == [
        "simulate",
        "evaluate_results",
        "simulate",
        "evaluate_results",
    ]
    assert result == "evaluate_results"
    # The bound parameters reach the functions.
    assert calls[0][1]["file"] == "case_1.csv"
    assert calls[0][1]["model"] == "./model_1"
    assert calls[2][1]["file"] == "case_2.csv"


def test_run_workflow_template_result_equals_inline():
    """A template workflow returns the same result as the inline equivalent."""
    registry, _ = _make_recorder(["simulate", "evaluate_results"])
    inline = (
        "<VerificationWorkflow>"
        '<argument key="model" value="./model_1"/>'
        "<sequential>"
        "<sequential>"
        '<action function="simulate">'
        '<argument key="file" value="case_1.csv"/>'
        '<argument key="model" value="./model_1"/>'
        "</action>"
        '<action function="evaluate_results">'
        '<argument key="file" value="case_1.csv"/>'
        "</action>"
        "</sequential>"
        "<sequential>"
        '<action function="simulate">'
        '<argument key="file" value="case_2.csv"/>'
        '<argument key="model" value="./model_1"/>'
        "</action>"
        '<action function="evaluate_results">'
        '<argument key="file" value="case_2.csv"/>'
        "</action>"
        "</sequential>"
        "</sequential>"
        "</VerificationWorkflow>"
    )
    template_result = run_workflow(TEMPLATE_REUSE, registry=registry)
    inline_result = run_workflow(inline, registry=registry)
    assert template_result == inline_result == "evaluate_results"


def test_run_workflow_template_globals_and_upstream_results():
    """Template actions resolve globals, upstream results and own parameters."""
    seen = []

    def collect(**kwargs):
        seen.append(kwargs)
        return "upstream"

    registry = FunctionRegistry()
    registry.register("collect", collect)
    run_workflow(
        "<VerificationWorkflow>"
        '<argument key="model" value="./model_1"/>'
        '<template name="t">'
        "<sequential>"
        '<action function="collect"><argument key="a" value="{p}"/></action>'
        '<action function="collect"><argument key="b" value="{p}"/></action>'
        "</sequential>"
        "</template>"
        "<sequential>"
        '<use-template name="t"><argument key="p" value="x"/></use-template>'
        "</sequential>"
        "</VerificationWorkflow>",
        registry=registry,
    )
    # First call: the global plus its own parameter; second call: the
    # upstream result (keyed by the producing action's function name)
    # plus its own parameter.
    assert seen[0] == {"model": "./model_1", "a": "x"}
    assert seen[1] == {"model": "./model_1", "collect": "upstream", "b": "x"}


def test_run_workflow_template_inside_parallel_group():
    """Template use sites inside a parallel group run concurrently."""
    barrier = threading.Barrier(2, timeout=30)
    registry = FunctionRegistry()

    def join_and_report(**kwargs):
        barrier.wait()
        return kwargs["file"]

    registry.register("simulate", join_and_report)
    registry.register("evaluate_results", join_and_report)
    result = run_workflow(TEMPLATE_PARALLEL, registry=registry)
    # Both parallel branches ran (the barrier proves concurrency) and the
    # run's final result is the last action's result in root execution
    # order (the second branch's evaluate_results).
    assert result == "case_2.csv"


def test_run_workflow_template_inside_parallel_group_runs_both_branches():
    """Both template instantiations inside a parallel group execute."""
    registry, calls = _make_recorder(["simulate", "evaluate_results"])
    run_workflow(TEMPLATE_PARALLEL, registry=registry)
    assert sorted(_names_in_order(calls)) == [
        "evaluate_results",
        "evaluate_results",
        "simulate",
        "simulate",
    ]
    # The default tolerance and the overridden one both reach the functions.
    tolerances = {call[1].get("tolerance") for call in calls if "tolerance" in call[1]}
    assert tolerances == {"0.01", "0.05"}


def test_test_framework_runs_template_instantiation():
    """Test_Framework runs a Python-API template instantiation."""
    template = Template(
        "file_check",
        Sequential(
            Action("simulate", file="{file}"),
            Action("evaluate_results", file="{file}"),
        ),
    )
    registry, calls = _make_recorder(["simulate", "evaluate_results"])
    result = Test_Framework(
        Sequential(
            template.instantiate(file="case_1.csv"),
            template.instantiate(file="case_2.csv"),
        ),
        registry=registry,
    )
    assert _names_in_order(calls) == [
        "simulate",
        "evaluate_results",
        "simulate",
        "evaluate_results",
    ]
    assert result == "evaluate_results"
    assert calls[0][1]["file"] == "case_1.csv"
    assert calls[2][1]["file"] == "case_2.csv"


def test_template_instantiation_inside_dynamic_adaptation():
    """A spliced subtree may itself contain a template instantiation."""
    template = Template("chain", Sequential(Action("b", p="{p}"), Action("c", p="{p}")))
    registry = FunctionRegistry()

    def driver(**kwargs):
        return template.instantiate(p="spliced")

    registry.register("driver", driver)
    registry.register("b", lambda **kwargs: "b-result")
    registry.register("c", lambda **kwargs: "c-result")
    registry.register("placeholder", lambda **kwargs: "not-run")
    result = run_workflow(
        "<sequential>"
        '<action function="driver"/>'
        '<sequential><action function="placeholder"/></sequential>'
        "</sequential>",
        registry=registry,
    )
    # The spliced template instantiation replaced the placeholder group and
    # its final action produced the run's result.
    assert result == "c-result"


def test_template_instantiation_dynamic_actions_marked():
    """Template-expanded actions spliced at runtime are marked dynamic."""
    template = Template("chain", Sequential(Action("b"), Action("c")))
    registry = FunctionRegistry()
    registry.register("driver", lambda **kwargs: template.instantiate())
    registry.register("b", lambda **kwargs: "b")
    registry.register("c", lambda **kwargs: "c")
    registry.register("placeholder", lambda **kwargs: "not-run")
    history = RunHistory()
    run_workflow(
        "<sequential>"
        '<action function="driver"/>'
        '<sequential><action function="placeholder"/></sequential>'
        "</sequential>",
        registry=registry,
        history=history,
    )
    assert [record.dynamic for record in history.records] == [False, True, True]
    assert [record.name for record in history.records] == ["driver", "b", "c"]


# --------------------------------------------------------------------------- #
# 4. HISTORY — template-expanded actions are ordinary actions
# --------------------------------------------------------------------------- #


def test_history_records_template_expanded_actions():
    """The history records template-expanded actions like ordinary actions."""
    registry, calls = _make_recorder(["simulate", "evaluate_results"])
    history = RunHistory()
    result = run_workflow(TEMPLATE_REUSE, registry=registry, history=history)
    assert result == replay(history, registry)
    assert len(history) == 4
    assert [record.name for record in history] == [
        "simulate",
        "evaluate_results",
        "simulate",
        "evaluate_results",
    ]
    # The records carry the resolved (bound) parameters, not placeholders.
    files = [record.params["file"] for record in history]
    assert files == ["case_1.csv", "case_1.csv", "case_2.csv", "case_2.csv"]
    # No template-expanded action is marked dynamic: expansion happened at
    # parse time, so they are ordinary actions.
    assert not any(record.dynamic for record in history)
    # The group path reflects the expanded tree.
    assert history[0].group_path == "root/sequential[0]/action[0]"


def test_history_replay_template_workflow():
    """Replaying a template workflow reproduces the run's final result."""
    registry, _ = _make_recorder(["simulate", "evaluate_results"])
    history = RunHistory()
    result = run_workflow(TEMPLATE_REUSE, registry=registry, history=history)
    assert replay(history, registry) == result


def test_history_group_path_template_inside_parallel():
    """Group paths reflect the expanded tree inside parallel groups."""
    registry, _ = _make_recorder(["simulate", "evaluate_results"])
    history = RunHistory()
    run_workflow(TEMPLATE_PARALLEL, registry=registry, history=history)
    # The root group itself is always "root"; its two template-expanded
    # sequential children are sequential[0] / sequential[1].
    paths = {record.group_path for record in history}
    assert paths == {
        "root/sequential[0]/action[0]",
        "root/sequential[0]/action[1]",
        "root/sequential[1]/action[0]",
        "root/sequential[1]/action[1]",
    }


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def _describe(node):
    """A plain structural description of a node tree (for equality checks)."""
    if isinstance(node, Action):
        return {"function": node.function, "params": dict(node.params)}
    kind = "sequential" if isinstance(node, Sequential) else "parallel"
    return {kind: [_describe(child) for child in node.children]}
