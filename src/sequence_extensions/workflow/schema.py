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

* ``<VerificationWorkflow>`` wraps any number of GLOBAL PARAMETER
  ``<argument>`` elements (e.g.
  ``<argument key="model" value="./model_1"/>``) followed by exactly ONE
  top-level grouping.  The globals are exposed on the returned root group
  as the ``.globals`` dict (e.g. ``{"model": "./model_1"}``); the group
  itself is returned as-is, so the engine reads ``root.globals``
  separately.
* A bare ``<sequential>`` or ``<parallel>`` root (no wrapper) is also
  accepted; its ``.globals`` is an empty dict.
* ``<action function="name">`` takes custom parameters as ``<argument>``
  child elements, one per parameter:
  ``<argument key="name" value="..."/>`` (``key`` attribute = parameter
  name, ``value`` attribute = parameter value).  ``<argument>`` is the only
  child element allowed inside an ``<action>`` (or anywhere for global
  parameters); the ``key`` attribute carries the parameter name, so a
  parameter can be any name without clashing with the structural element
  names.

Invalid structure raises ``ValueError`` with a message naming the problem:
a root element that is not ``<VerificationWorkflow>`` / ``<sequential>`` /
``<parallel>``, zero or multiple top-level groupings inside
``<VerificationWorkflow>``, an unknown element name anywhere (including a
non-``<argument>`` child of an ``<action>`` or of the
``<VerificationWorkflow>`` wrapper), an ``<action>`` without a ``function``
attribute, an ``<argument>`` without a ``key`` or ``value`` attribute, a
duplicate parameter key on one action, or an ``<argument>`` containing
child elements.  Malformed (non-well-formed) XML is also reported as
``ValueError``.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET

__all__ = ["Action", "Parallel", "Sequential", "parse_workflow"]

# Element names that denote a grouping node.
_GROUP_TAGS = ("sequential", "parallel")
# The element name that denotes a parameter (key/value pair), anywhere it
# appears (action parameters, global parameters).
_ARGUMENT_TAG = "argument"


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
        elif child.tag == _ARGUMENT_TAG:
            key, value = _argument(child)
            globals_[key] = value
        else:
            raise ValueError(
                f"unknown element <{child.tag}> inside <VerificationWorkflow>; "
                "global parameters must be <argument> elements"
            )
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
    """Parse an ``<action>`` element: function attribute + ``<argument>`` children."""
    function = element.attrib.get("function")
    if not function:
        raise ValueError("<action> element is missing its 'function' attribute")
    params: dict[str, str] = {}
    for child in element:
        if child.tag != _ARGUMENT_TAG:
            raise ValueError(
                f"unknown element <{child.tag}> inside <action function={function!r}>; "
                "action parameters must be <argument> elements"
            )
        key, value = _argument(child)
        if key in params:
            raise ValueError(
                f"duplicate parameter <argument key={key!r}> in <action function={function!r}>"
            )
        params[key] = value
    action = Action(function)
    # Assign directly so parameter names that are Python keywords
    # (e.g. <argument key="class" value="..."/>) cannot break a ``**params``
    # call.
    action.params = params
    return action


def _argument(element: ET.Element) -> tuple[str, str]:
    """Return the (key, value) of an ``<argument>`` element.

    The element must carry a ``key`` attribute (the parameter name) and a
    ``value`` attribute (the parameter value), and must not contain child
    elements.
    """
    if len(element):
        raise ValueError("<argument> element must not contain child elements")
    key = element.attrib.get("key")
    if not key:
        raise ValueError("<argument> element is missing its 'key' attribute")
    if "value" not in element.attrib:
        raise ValueError("<argument> element is missing its 'value' attribute")
    return key, element.attrib["value"]
