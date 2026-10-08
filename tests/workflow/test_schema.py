"""
Tests for the workflow XML schema (``sequence_extensions.workflow.schema``):
``parse_workflow`` and the ``Action`` / ``Sequential`` / ``Parallel`` node
structure it produces, including every rejection rule.

The fixture documents live in ``tests/resources/workflows/`` (indexed by its
README): the paper's Listing 9 (full workflow with global parameters),
Listing 5 (dynamic adaptation), and one file per parser rejection rule under
``invalid/``.
"""

import pytest

from resources import workflows
from sequence_extensions import Action, Parallel, Sequential, parse_workflow

from . import LISTING_5, LISTING_9, _children, _function, _globals, _params

# --------------------------------------------------------------------------- #
# 1. PARSING — Listing 9
# --------------------------------------------------------------------------- #


def test_parse_listing_9_structure():
    """Listing 9 parses into the expected nested Sequential/Action structure."""
    root = parse_workflow(LISTING_9)
    assert isinstance(root, Sequential)

    # Global parameter <model value="./model_1"/> is captured on the root.
    assert _globals(root).get("model") == "./model_1"

    top = _children(root)
    assert len(top) == 3

    # top[0]: find_test_cases with path="./test"
    assert isinstance(top[0], Action)
    assert _function(top[0]) == "find_test_cases"
    assert _params(top[0]).get("path") == "./test"

    # top[1]: a nested Sequential of [parameter_sweep, Sequential[simulate],
    # compare_parameter_sweep]
    assert isinstance(top[1], Sequential)
    inner = _children(top[1])
    assert len(inner) == 3
    assert isinstance(inner[0], Action)
    assert _function(inner[0]) == "parameter_sweep"
    assert _params(inner[0]).get("parameter_name") == "parameter_1"
    assert _params(inner[0]).get("values") == "5, 10, 15"

    assert isinstance(inner[1], Sequential)
    sim = _children(inner[1])
    assert len(sim) == 1
    assert isinstance(sim[0], Action)
    assert _function(sim[0]) == "simulate"

    assert isinstance(inner[2], Action)
    assert _function(inner[2]) == "compare_parameter_sweep"

    # top[2]: compare_results
    assert isinstance(top[2], Action)
    assert _function(top[2]) == "compare_results"


# --------------------------------------------------------------------------- #
# 2. PARSING — Listing 5 (and <parallel> -> Parallel)
# --------------------------------------------------------------------------- #


def test_parse_listing_5_structure():
    """Listing 5 parses; find_files is followed by a nested Sequential."""
    root = parse_workflow(LISTING_5)
    assert isinstance(root, Sequential)

    top = _children(root)
    assert len(top) == 2
    assert isinstance(top[0], Action)
    assert _function(top[0]) == "find_files"
    assert _params(top[0]).get("path") == "file_storage/"

    assert isinstance(top[1], Sequential)
    inner = _children(top[1])
    assert len(inner) == 2
    assert _function(inner[0]) == "simulate"
    assert _function(inner[1]) == "evaluate_results"


def test_parse_parallel_group():
    """A <parallel> group parses to a Parallel node with its actions in order."""
    xml = '<parallel><action function="a"/><action function="b"/></parallel>'
    root = parse_workflow(xml)
    assert isinstance(root, Parallel)
    children = _children(root)
    assert len(children) == 2
    assert _function(children[0]) == "a"
    assert _function(children[1]) == "b"


# --------------------------------------------------------------------------- #
# 3. PARSING REJECTION — invalid XML
# --------------------------------------------------------------------------- #


def test_parse_rejects_wrong_root():
    """A root element that is not <VerificationWorkflow> is rejected."""
    with pytest.raises(ValueError):
        parse_workflow(workflows.load("invalid/wrong_root.xml"))


def test_parse_rejects_zero_top_level_groupings():
    """A <VerificationWorkflow> with no top-level grouping is rejected."""
    with pytest.raises(ValueError):
        parse_workflow(workflows.load("invalid/missing_top_level_grouping.xml"))


def test_parse_rejects_multiple_top_level_groupings():
    """A <VerificationWorkflow> with two top-level groupings is rejected."""
    with pytest.raises(ValueError):
        parse_workflow(workflows.load("invalid/multiple_top_level_groupings.xml"))


def test_parse_rejects_action_without_function():
    """An <action> missing its function attribute is rejected."""
    with pytest.raises(ValueError):
        parse_workflow(workflows.load("invalid/action_without_function.xml"))


def test_parse_rejects_unknown_nesting_element():
    """An unknown element inside a grouping is rejected."""
    with pytest.raises(ValueError):
        parse_workflow(workflows.load("invalid/unknown_element.xml"))


def test_parse_rejects_param_without_value():
    """An action param child missing its value attribute is rejected."""
    with pytest.raises(ValueError):
        parse_workflow(workflows.load("invalid/param_without_value.xml"))
