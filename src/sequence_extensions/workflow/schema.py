"""
Node classes and XML parser for the V&V workflow schema.

The schema is specified by the paper "Automation Nation: Taming Complex V&V
Workflows" (16th International Modelica & FMI Conference, September 2025,
Lucerne, Switzerland; DOI 10.3384/ecp12076741), section 4.1.

A workflow is a tree of three node types:

* ``Action(function, **params)`` — the smallest unit: one call to a
  registered function with custom keyword parameters.
* ``Sequential(*children)`` — children execute in strict order.
* ``Parallel(*children)`` — children are independent and may run
  concurrently.

Groups nest arbitrarily.  ``parse_workflow`` turns the paper's XML into
these nodes:

* ``<VerificationWorkflow>`` wraps any number of GLOBAL PARAMETER elements
  (e.g. ``<model value="./model_1"/>``) followed by exactly ONE top-level
  grouping.  The globals are exposed on the returned root group as the
  ``.globals`` dict (e.g. ``{"model": "./model_1"}``); the group itself is
  returned as-is, so the engine reads ``root.globals`` separately.
* A bare ``<sequential>`` or ``<parallel>`` root (no wrapper) is also
  accepted; its ``.globals`` is an empty dict.
* ``<action function="name">`` takes custom parameters as child elements,
  one per parameter: ``<param_name value="..."/>`` (element name = parameter
  name, ``value`` attribute = parameter value).

Invalid structure raises ``ValueError`` with a message naming the problem:
a root element that is not ``<VerificationWorkflow>`` / ``<sequential>`` /
``<parallel>``, zero or multiple top-level groupings inside
``<VerificationWorkflow>``, an unknown element name anywhere, an
``<action>`` without a ``function`` attribute, a parameter element without a
``value`` attribute, a duplicate parameter name on one action, or a
parameter element containing child elements.  Malformed (non-well-formed)
XML is also reported as ``ValueError``.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET

__all__ = ["Action", "Parallel", "Sequential", "parse_workflow"]

# Element names that denote a grouping node.
_GROUP_TAGS = ("sequential", "parallel")


class Action:
    """
    The smallest unit of a workflow: one function call.

    ``function`` is the name of the registered function to call; ``params``
    are its custom keyword parameters (e.g. ``Action("simulate",
    file="case_1.csv")``).
    """

    def __init__(self, function: str, **params) -> None:
        """Create an action node; ``params`` are stored as a plain dict."""
        self.function = function
        self.params = dict(params)

    def __repr__(self) -> str:
        """One-liner with the function name and its parameters."""
        return f"Action({self.function!r}, {self.params!r})"


class _Group:
    """
    Base class for the two grouping nodes (``Sequential`` / ``Parallel``).

    ``children`` is the ordered list of child nodes (Action / Sequential /
    Parallel); ``globals`` holds the global parameters declared in the
    enclosing ``<VerificationWorkflow>`` (empty for bare group roots and for
    groups built via the Python API).
    """

    def __init__(self, *children: Action | Sequential | Parallel) -> None:
        """Create a group with the given child nodes, in order."""
        self.children = list(children)
        self.globals: dict[str, str] = {}

    def __repr__(self) -> str:
        """One-liner with the group type and its children."""
        return f"{type(self).__name__}({self.children!r})"


class Sequential(_Group):
    """A group whose children execute in strict order."""


class Parallel(_Group):
    """A group whose children are independent (may run concurrently)."""


# --------------------------------------------------------------------------- #
# XML parsing
# --------------------------------------------------------------------------- #


def parse_workflow(xml_source: str | bytes) -> Sequential | Parallel:
    """
    Parse a workflow XML document and return its root group.

    ``xml_source`` is the XML as a string (or bytes).  The document is
    either a ``<VerificationWorkflow>`` wrapper (global parameters + exactly
    one top-level grouping) or a bare ``<sequential>`` / ``<parallel>``
    root.  Global parameters are stored on the returned group's ``.globals``
    dict (empty for bare roots).

    Raises ``ValueError`` for any invalid structure (see the module
    docstring for the full list).
    """
    try:
        root = ET.fromstring(xml_source)
    except ET.ParseError as exc:
        raise ValueError(f"workflow XML is not well-formed: {exc}") from exc

    if root.tag == "VerificationWorkflow":
        return _parse_wrapped(root)
    if root.tag in _GROUP_TAGS:
        return _parse_group(root)
    raise ValueError(
        f"workflow root must be <VerificationWorkflow>, <sequential> or "
        f"<parallel>, got <{root.tag}>"
    )


def _parse_wrapped(root: ET.Element) -> Sequential | Parallel:
    """Parse a ``<VerificationWorkflow>`` wrapper: globals + one top-level group."""
    globals_: dict[str, str] = {}
    group: Sequential | Parallel | None = None
    for child in root:
        if child.tag in _GROUP_TAGS:
            if group is not None:
                raise ValueError(
                    "<VerificationWorkflow> must contain exactly one top-level "
                    f"grouping, found <{child.tag}> after an earlier one"
                )
            group = _parse_group(child)
        else:
            globals_[child.tag] = _param_value(child)
    if group is None:
        raise ValueError(
            "<VerificationWorkflow> must contain exactly one top-level "
            "grouping (<sequential> or <parallel>), found none"
        )
    group.globals = globals_
    return group


def _parse_group(element: ET.Element) -> Sequential | Parallel:
    """Parse a ``<sequential>`` or ``<parallel>`` element into its group node."""
    children = [_parse_child(child) for child in element]
    if element.tag == "sequential":
        return Sequential(*children)
    return Parallel(*children)


def _parse_child(element: ET.Element) -> Action | Sequential | Parallel:
    """Parse one child of a grouping: an action or a nested group."""
    if element.tag == "action":
        return _parse_action(element)
    if element.tag in _GROUP_TAGS:
        return _parse_group(element)
    raise ValueError(f"unknown element <{element.tag}> inside a workflow grouping")


def _parse_action(element: ET.Element) -> Action:
    """Parse an ``<action>`` element: function attribute + param child elements."""
    function = element.attrib.get("function")
    if not function:
        raise ValueError("<action> element is missing its 'function' attribute")
    params: dict[str, str] = {}
    for child in element:
        if child.tag in params:
            raise ValueError(f"duplicate parameter <{child.tag}> in <action function={function!r}>")
        params[child.tag] = _param_value(child)
    action = Action(function)
    # Assign directly so XML parameter names that are Python keywords
    # (e.g. <class value="..."/>) cannot break a ``**params`` call.
    action.params = params
    return action


def _param_value(element: ET.Element) -> str:
    """Return a parameter element's value; it must carry a ``value`` attribute."""
    if len(element):
        raise ValueError(f"parameter element <{element.tag}> must not contain child elements")
    if "value" not in element.attrib:
        raise ValueError(f"parameter element <{element.tag}> is missing its 'value' attribute")
    return element.attrib["value"]
