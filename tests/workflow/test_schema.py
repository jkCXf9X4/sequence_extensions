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

    # Global parameter <argument key="model" value="./model_1"/> is captured on the root.
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


def test_parse_rejects_argument_without_value():
    """An <argument> element missing its value attribute is rejected."""
    with pytest.raises(ValueError):
        parse_workflow(workflows.load("invalid/argument_without_value.xml"))


def test_parse_rejects_argument_without_key():
    """An <argument> element missing its key attribute is rejected."""
    with pytest.raises(ValueError):
        parse_workflow(workflows.load("invalid/argument_without_key.xml"))


def test_parse_rejects_non_argument_inside_action():
    """A non-<argument> child element of an <action> is rejected (the
    element-name-as-parameter form is no longer part of the schema)."""
    with pytest.raises(ValueError):
        parse_workflow(workflows.load("invalid/action_unknown_element.xml"))


def test_parse_rejects_non_argument_inside_wrapper():
    """A non-<argument>, non-grouping child of <VerificationWorkflow> is rejected."""
    with pytest.raises(ValueError):
        parse_workflow(workflows.load("invalid/wrapper_unknown_element.xml"))


def test_parse_rejects_duplicate_argument():
    """Two <argument> elements with the same key on one action are rejected."""
    with pytest.raises(ValueError):
        parse_workflow(workflows.load("invalid/duplicate_argument.xml"))


def test_parse_rejects_argument_with_children():
    """An <argument> element containing child elements is rejected."""
    with pytest.raises(ValueError):
        parse_workflow(workflows.load("invalid/argument_with_children.xml"))


# --------------------------------------------------------------------------- #
# 4. PARSING — <scope type="..."> + alias equivalence (Phase 7, plan §7)
# --------------------------------------------------------------------------- #


def test_parse_scope_sequential_root():
    """A <scope type="sequential"> root parses to a Sequential node."""
    root = parse_workflow(
        '<scope type="sequential"><action function="a"/><action function="b"/></scope>'
    )
    assert isinstance(root, Sequential)
    children = _children(root)
    assert [_function(c) for c in children] == ["a", "b"]


def test_parse_scope_parallel_root():
    """A <scope type="parallel"> root parses to a Parallel node."""
    root = parse_workflow(
        '<scope type="parallel"><action function="a"/><action function="b"/></scope>'
    )
    assert isinstance(root, Parallel)
    children = _children(root)
    assert [_function(c) for c in children] == ["a", "b"]


def test_parse_scope_alias_equivalent_to_sequential():
    """<scope type="sequential"> and <sequential> parse to the same structure."""
    via_scope = parse_workflow(
        '<scope type="sequential"><action function="a"/><action function="b"/></scope>'
    )
    via_alias = parse_workflow(
        "<sequential><action function='a'/><action function='b'/></sequential>"
    )
    assert type(via_scope) is type(via_alias) is Sequential
    assert [_function(c) for c in _children(via_scope)] == [
        _function(c) for c in _children(via_alias)
    ]


def test_parse_scope_alias_equivalent_to_parallel():
    """<scope type="parallel"> and <parallel> parse to the same structure."""
    via_scope = parse_workflow(
        '<scope type="parallel"><action function="a"/><action function="b"/></scope>'
    )
    via_alias = parse_workflow(
        "<parallel><action function='a'/><action function='b'/></parallel>"
    )
    assert type(via_scope) is type(via_alias) is Parallel
    assert [_function(c) for c in _children(via_scope)] == [
        _function(c) for c in _children(via_alias)
    ]


def test_parse_scope_as_wrapper_top_level_grouping():
    """A <scope> may be the single top-level grouping of a <VerificationWorkflow>."""
    root = parse_workflow(
        '<VerificationWorkflow><argument key="model" value="m"/>'
        '<scope type="sequential"><action function="a"/></scope>'
        "</VerificationWorkflow>"
    )
    assert isinstance(root, Sequential)
    assert _globals(root).get("model") == "m"
    assert [_function(c) for c in _children(root)] == ["a"]


def test_parse_scope_nested_inside_group():
    """A <scope> may be nested inside another group (mixed with the aliases)."""
    root = parse_workflow(
        "<sequential>"
        '<action function="a"/>'
        '<scope type="parallel"><action function="b"/><action function="c"/></scope>'
        "</sequential>"
    )
    assert isinstance(root, Sequential)
    children = _children(root)
    assert isinstance(children[1], Parallel)
    assert [_function(c) for c in _children(children[1])] == ["b", "c"]


def test_parse_scope_in_template_body():
    """A <scope> may be the body of a <template> (expanded at parse time)."""
    root = parse_workflow(
        '<VerificationWorkflow>'
        '<template name="t"><scope type="sequential">'
        '<action function="a"><argument key="file" value="{file}"/></action>'
        "</scope></template>"
        '<sequential><use-template name="t"><argument key="file" value="f1"/></use-template>'
        "</sequential>"
        "</VerificationWorkflow>"
    )
    assert isinstance(root, Sequential)
    inner = _children(root)[0]
    assert isinstance(inner, Sequential)
    assert _function(_children(inner)[0]) == "a"
    assert _params(_children(inner)[0]).get("file") == "f1"


def test_parse_scope_name_attribute_labels_group():
    """An optional name attribute on <scope> labels the group (does not affect type)."""
    root = parse_workflow(
        '<scope type="sequential" name="retry"><action function="a"/></scope>'
    )
    assert isinstance(root, Sequential)
    assert root.name == "retry"
    # The alias form carries no name (None) by default.
    alias_root = parse_workflow("<sequential><action function='a'/></sequential>")
    assert alias_root.name is None


def test_parse_scope_missing_type_rejected():
    """A <scope> missing its type attribute is rejected with ValueError."""
    with pytest.raises(ValueError, match="type"):
        parse_workflow('<scope><action function="a"/></scope>')


def test_parse_scope_invalid_type_rejected():
    """A <scope> with a type other than sequential/parallel is rejected."""
    with pytest.raises(ValueError, match="type"):
        parse_workflow('<scope type="loop"><action function="a"/></scope>')


def test_parse_scope_alias_emits_no_warning():
    """The <sequential>/<parallel> aliases parse with no deprecation warning (D1)."""
    import warnings

    with warnings.catch_warnings():
        warnings.simplefilter("error")  # any warning becomes an error
        parse_workflow("<sequential><action function='a'/></sequential>")
        parse_workflow("<parallel><action function='a'/></parallel>")
        # The explicit <scope> form is also warning-free.
        parse_workflow('<scope type="sequential"><action function="a"/></scope>')
