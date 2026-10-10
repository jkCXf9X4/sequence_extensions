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
* ``<scope type="sequential|parallel">`` is the explicit form of a
  grouping: ``type`` is required and must be ``sequential`` or
  ``parallel``; an optional ``name`` attribute labels the group (it does
  not appear in history path labels, which are derived from the group
  type).  ``<sequential>`` / ``<parallel>`` are aliases for
  ``<scope type="...">`` and parse exactly as before.  ``<scope>`` is
  allowed everywhere a group is allowed: as the root, as the
  ``<VerificationWorkflow>`` top-level grouping, nested inside other
  groups, and as a template body.
* ``<action function="name">`` takes custom parameters as ``<argument>``
  child elements, one per parameter:
  ``<argument key="name" value="..."/>`` (``key`` attribute = parameter
  name, ``value`` attribute = parameter value).  ``<argument>`` is the only
  child element allowed inside an ``<action>`` (or anywhere for global
  parameters); the ``key`` attribute carries the parameter name, so a
  parameter can be any name without clashing with the structural element
  names.

TEMPLATES — named, parameterized subtrees (the paper's design principle 4:
actions with parameters form templates for common verification scenarios,
limiting duplication between workflows):

* ``Template(name, body, **defaults)`` is a named, parameterized group.
  ``body`` is the subtree to reuse (a ``Sequential`` / ``Parallel`` group,
  or a single ``Action``, which is wrapped in a ``Sequential`` so an
  instantiation is always a group); ``defaults`` are the parameter values
  used when a use site does not bind them.  A parameter is *declared* by
  the template when it has a default or when the body references it as a
  ``{placeholder}`` inside an action parameter value.
* ``Template.instantiate(**params)`` returns a NEW node tree — a fresh copy
  of the body with every placeholder replaced by its bound value — so
  instantiating the same template with different parameters yields
  distinct, independent trees.  A placeholder that fills a whole
  parameter value (``value="{items}"``) is replaced by the bound value
  itself, preserving its type; a placeholder inside a longer string
  (``value="{model}/case.csv"``) is replaced by the string form of the
  bound value.  Resolution is STRICT: every placeholder in the body must
  resolve to a binding, a default or a same-named global parameter, so a
  typo in a placeholder name fails at parse/instantiation time instead of
  silently passing a literal ``"{...}"`` string to a function.
* In XML, a template is DEFINED as a ``<template name="...">`` element —
  a body group plus optional ``<argument>`` default values — and USED as
  ``<use-template name="...">`` with ``<argument>`` bindings.  Definitions
  live directly inside the ``<VerificationWorkflow>`` wrapper; use sites
  may appear anywhere a group may appear (including inside other template
  bodies, which may use templates defined before them).  Expansion happens
  at PARSE time: the parser replaces every ``<use-template>`` with the
  instantiated body, so the returned tree contains only ``Action`` /
  ``Sequential`` / ``Parallel`` nodes and is exactly the tree the
  equivalent inline workflow produces.  The engine never sees a template.
* Placeholder binding precedence: the use site's binding wins over the
  template's default, which wins over a workflow GLOBAL parameter of the
  same name (so a template can refer to a global without every use site
  re-binding it).  A use site must bind every declared parameter that has
  no default and no same-named global, and must not bind a parameter the
  template does not declare.

Invalid structure raises ``ValueError`` with a message naming the problem:
a root element that is not ``<VerificationWorkflow>`` / ``<sequential>``
/ ``<parallel>`` / ``<scope>``, a ``<scope>`` missing its ``type``
attribute or carrying a ``type`` other than ``sequential`` / ``parallel``,
zero or multiple top-level groupings inside
``<VerificationWorkflow>``, an unknown element name anywhere (including a
non-``<argument>`` child of an ``<action>`` or of the
``<VerificationWorkflow>`` wrapper), an ``<action>`` without a ``function``
attribute, an ``<argument>`` without a ``key`` or ``value`` attribute, a
duplicate parameter key on one action, or an ``<argument>`` containing
child elements.  Template misuse is reported the same way: a
``<template>`` without a ``name`` attribute, without a body, with more
than one body, with a duplicate default key or with an unknown child
element; a duplicate template name; a ``<template>`` definition inside a
grouping; and a ``<use-template>`` without a ``name`` attribute, naming
an unknown template, carrying an unknown or duplicate child element,
binding an undeclared parameter, or leaving a required parameter unbound.
Malformed (non-well-formed) XML is also reported as ``ValueError``.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from typing import Any

__all__ = ["Action", "Parallel", "Sequential", "Template", "parse_workflow"]

# Element names that denote a grouping node.
_GROUP_TAGS = ("sequential", "parallel")
# The element name that denotes a grouping node with an explicit, validated
# ``type`` attribute (``sequential`` / ``parallel``); ``<sequential>`` and
# ``<parallel>`` are aliases for ``<scope type="...">``.
_SCOPE_TAG = "scope"
# The element name that denotes a parameter (key/value pair), anywhere it
# appears (action parameters, global parameters, template defaults and
# template use-site bindings).
_ARGUMENT_TAG = "argument"
# The element name that defines a named, parameterized subtree.
_TEMPLATE_TAG = "template"
# The element name that references (instantiates) a defined template.
_USE_TEMPLATE_TAG = "use-template"
# A placeholder inside an action parameter value: ``{name}``, where ``name``
# is a template parameter or a global parameter.
_PLACEHOLDER = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)\}")


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
    groups built via the Python API); ``name`` is an optional label (``None``
    unless set from a ``<scope name=...>`` attribute) that does not affect
    history path labels, which are derived from the group type.
    """

    def __init__(self, *children: Action | Sequential | Parallel, name: str | None = None) -> None:
        """Create a group with the given child nodes, in order.

        ``name`` is an optional label (set from a ``<scope name=...>``
        attribute); it is not part of history path labels, which are derived
        from the group type.
        """
        self.children = list(children)
        self.globals: dict[str, str] = {}
        self.name = name

    def __repr__(self) -> str:
        """One-liner with the group type and its children."""
        return f"{type(self).__name__}({self.children!r})"


class Sequential(_Group):
    """A group whose children execute in strict order."""


class Parallel(_Group):
    """A group whose children are independent (may run concurrently)."""


# --------------------------------------------------------------------------- #
# Templates: named, parameterized subtrees (design principle 4, reuse)
# --------------------------------------------------------------------------- #


class Template:
    """
    A named, parameterized subtree: the unit of reuse between workflows.

    A template is defined once and instantiated wherever its verification
    scenario is needed, with different parameters per use site — limiting
    duplication between workflows (the paper's design principle 4).
    ``body`` is the subtree to reuse: a ``Sequential`` / ``Parallel`` group,
    or a single ``Action`` (which is wrapped in a ``Sequential``, so every
    instantiation is a group).  ``defaults`` declare parameters and their
    fallback values.

    A parameter is *declared* when it has a default or when the body
    references it as a ``{placeholder}`` inside an action parameter value
    (e.g. ``Action("simulate", file="{file}")``).  :meth:`instantiate` binds
    values to the declared parameters and returns a NEW node tree — a
    fresh copy of the body with every placeholder replaced — so two
    instantiations never share node objects, and instantiating the same
    template with different parameters yields distinct trees.

    ``name`` and ``body`` are positional-only so a template parameter may be
    called ``name`` or ``body`` without colliding with them.
    """

    def __init__(self, name: str, body: Action | Sequential | Parallel, /, **defaults: Any) -> None:
        """Create a template; ``defaults`` are the fallback parameter values."""
        if not isinstance(name, str) or not name:
            raise ValueError("template name must be a non-empty string")
        if isinstance(body, Action):
            body = Sequential(body)
        if not isinstance(body, (Sequential, Parallel)):
            raise ValueError(
                f"template {name!r} body must be an Action, Sequential or "
                f"Parallel, got {type(body).__name__}"
            )
        self.name = name
        self.body = body
        self.defaults: dict[str, Any] = dict(defaults)

    def __repr__(self) -> str:
        """One-liner with the template's name, body and default parameters."""
        return f"Template({self.name!r}, {self.body!r}, {self.defaults!r})"

    @property
    def parameters(self) -> list[str]:
        """The template's declared parameter names, sorted."""
        return sorted({*self.defaults, *_placeholder_names(self.body)})

    def instantiate(self, /, **params: Any) -> Sequential | Parallel:
        """
        Return a NEW node tree: the body with every placeholder bound.

        ``params`` bind the template's declared parameters and win over the
        defaults.  Raises ``ValueError`` when ``params`` name a parameter
        the template does not declare, or when a declared parameter has
        neither a binding nor a default (every placeholder in the body must
        resolve).
        """
        return self._expand(params, {})

    def _expand(self, bindings: dict[str, Any], globals_: dict[str, Any]) -> Sequential | Parallel:
        """
        Expand the template with ``bindings`` (and workflow ``globals_``).

        Shared by :meth:`instantiate` (the Python API binds everything
        explicitly, so it passes no globals) and the XML parser (workflow
        globals are the lowest-precedence binding, so a template can refer
        to a global without every use site re-binding it).  Raises
        ``ValueError`` for a binding that names an undeclared parameter, or
        for a placeholder that resolves to nothing.
        """
        declared = set(self.parameters)
        for key in bindings:
            if key not in declared:
                raise ValueError(
                    f"template {self.name!r} has no parameter {key!r}; "
                    f"declared parameters: {self.parameters}"
                )
        # Binding precedence: use-site binding > template default > global.
        values = {**globals_, **self.defaults, **bindings}
        unresolved = _placeholder_names(self.body) - values.keys()
        if unresolved:
            missing = ", ".join(sorted(repr(name) for name in unresolved))
            raise ValueError(
                f"template {self.name!r} requires parameter(s) {missing} "
                "with no default and no same-named global parameter"
            )
        return _substitute(self.body, values)


def _placeholder_names(node: Action | Sequential | Parallel) -> set[str]:
    """Collect every ``{placeholder}`` name in the subtree's action values."""
    if isinstance(node, Action):
        names: set[str] = set()
        for value in node.params.values():
            if isinstance(value, str):
                names.update(_PLACEHOLDER.findall(value))
        return names
    names = set()
    for child in node.children:
        names.update(_placeholder_names(child))
    return names


def _substitute(
    node: Action | Sequential | Parallel, values: dict[str, Any]
) -> Action | Sequential | Parallel:
    """
    Return a NEW copy of ``node``'s subtree with the placeholders bound.

    Every ``{name}`` inside an action parameter value that ``values`` binds
    is replaced.  A placeholder that fills the whole value is replaced by
    the bound value itself (preserving its type, e.g. a list of sweep
    values); a placeholder inside a longer string is replaced by the string
    form of the bound value.  No node object is shared with the original
    subtree, so instantiations are independent trees.
    """
    if isinstance(node, Action):
        copy = Action(node.function)
        # Assign directly so parameter names that are Python keywords
        # (e.g. <argument key="class" value="..."/>) cannot break a
        # ``**params`` call.
        copy.params = {key: _substitute_value(value, values) for key, value in node.params.items()}
        return copy
    copy = type(node)()
    copy.children = [_substitute(child, values) for child in node.children]
    copy.name = node.name
    return copy


def _substitute_value(value: Any, values: dict[str, Any]) -> Any:
    """Bind the placeholders in one action parameter value (see ``_substitute``)."""
    if not isinstance(value, str):
        return value
    whole = _PLACEHOLDER.fullmatch(value)
    if whole is not None and whole.group(1) in values:
        # A placeholder that fills the whole value is replaced by the bound
        # value itself, preserving its type (e.g. a list of sweep values).
        return values[whole.group(1)]

    def replace(match: re.Match) -> str:
        return str(values[match.group(1)])

    return _PLACEHOLDER.sub(replace, value)


# --------------------------------------------------------------------------- #
# XML parsing
# --------------------------------------------------------------------------- #


def parse_workflow(xml_source: str | bytes) -> Sequential | Parallel:
    """
    Parse a workflow XML document and return its root group.

    ``xml_source`` is the XML as a string (or bytes).  The document is
    either a ``<VerificationWorkflow>`` wrapper (global parameters, optional
    ``<template>`` definitions and exactly one top-level grouping) or a bare
    ``<sequential>`` / ``<parallel>`` / ``<scope>`` root.  Global parameters are stored on
    the returned group's ``.globals`` dict (empty for bare roots).  Every
    ``<use-template>`` is expanded at parse time into the instantiated
    template body, so the returned tree contains only ``Action`` /
    ``Sequential`` / ``Parallel`` nodes — exactly the tree the equivalent
    inline workflow produces.

    Raises ``ValueError`` for any invalid structure (see the module
    docstring for the full list).
    """
    try:
        root = ET.fromstring(xml_source)
    except ET.ParseError as exc:
        raise ValueError(f"workflow XML is not well-formed: {exc}") from exc

    if root.tag == "VerificationWorkflow":
        return _parse_wrapped(root)
    if root.tag in _GROUP_TAGS or root.tag == _SCOPE_TAG:
        return _parse_group(root, {}, {})
    raise ValueError(
        f"workflow root must be <VerificationWorkflow>, <sequential>, "
        f"<parallel> or <scope>, got <{root.tag}>"
    )


def _parse_wrapped(root: ET.Element) -> Sequential | Parallel:
    """
    Parse a ``<VerificationWorkflow>`` wrapper: globals, templates, one group.

    Global parameters and template definitions are collected first (in
    document order) so both are available to every template body and to the
    top-level grouping, wherever in the wrapper they appear; then the
    single top-level grouping is parsed with the template table.
    """
    globals_: dict[str, str] = {}
    for child in root:
        if child.tag == _ARGUMENT_TAG:
            key, value = _argument(child)
            globals_[key] = value
    templates: dict[str, Template] = {}
    for child in root:
        if child.tag == _TEMPLATE_TAG:
            template = _parse_template(child, templates, globals_)
            if template.name in templates:
                raise ValueError(
                    f"duplicate template name {template.name!r} in <VerificationWorkflow>"
                )
            templates[template.name] = template
    group: Sequential | Parallel | None = None
    for child in root:
        if child.tag in _GROUP_TAGS or child.tag == _SCOPE_TAG:
            if group is not None:
                raise ValueError(
                    "<VerificationWorkflow> must contain exactly one top-level "
                    f"grouping, found <{child.tag}> after an earlier one"
                )
            group = _parse_group(child, templates, globals_)
        elif child.tag not in (_ARGUMENT_TAG, _TEMPLATE_TAG):
            raise ValueError(
                f"unknown element <{child.tag}> inside <VerificationWorkflow>; "
                "only <argument> global parameters, <template> definitions and "
                "one top-level grouping are allowed"
            )
    if group is None:
        raise ValueError(
            "<VerificationWorkflow> must contain exactly one top-level "
            "grouping (<sequential>, <parallel> or <scope>), found none"
        )
    group.globals = globals_
    return group


def _parse_group(
    element: ET.Element, templates: dict[str, Template], globals_: dict[str, str]
) -> Sequential | Parallel:
    """
    Parse a grouping element into its group node.

    ``<sequential>`` / ``<parallel>`` are aliases for
    ``<scope type="sequential">`` / ``<scope type="parallel">``: the
    ``type`` attribute is required on ``<scope>`` and validated, and an
    optional ``name`` attribute labels the group (history path labels stay
    derived from the group type).
    """
    if element.tag == _SCOPE_TAG:
        scope_type = element.attrib.get("type")
        if not scope_type:
            raise ValueError("<scope> element is missing its 'type' attribute")
        if scope_type not in _GROUP_TAGS:
            raise ValueError(
                f"<scope> element has invalid 'type' attribute {scope_type!r}; "
                "must be 'sequential' or 'parallel'"
            )
    else:
        scope_type = element.tag
    name = element.attrib.get("name")
    children = [_parse_child(child, templates, globals_) for child in element]
    if scope_type == "sequential":
        return Sequential(*children, name=name)
    return Parallel(*children, name=name)


def _parse_child(
    element: ET.Element, templates: dict[str, Template], globals_: dict[str, str]
) -> Action | Sequential | Parallel:
    """Parse one child of a grouping: an action, a nested group, or a template use."""
    if element.tag == "action":
        return _parse_action(element)
    if element.tag in _GROUP_TAGS or element.tag == _SCOPE_TAG:
        return _parse_group(element, templates, globals_)
    if element.tag == _USE_TEMPLATE_TAG:
        return _parse_use_template(element, templates, globals_)
    if element.tag == _TEMPLATE_TAG:
        raise ValueError(
            "<template> definitions must appear directly inside "
            "<VerificationWorkflow>, not inside a workflow grouping"
        )
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


def _parse_template(
    element: ET.Element, templates: dict[str, Template], globals_: dict[str, str]
) -> Template:
    """
    Parse a ``<template>`` definition: name, body group, default arguments.

    The body is exactly one ``<sequential>`` / ``<parallel>`` / ``<action>``
    element (an ``<action>`` body is wrapped in a ``Sequential``); any number
    of ``<argument>`` elements declare default parameter values.  The body
    is parsed with the template table built so far, so a template body may
    use templates defined before it (a template cannot reference itself or
    a later template, so expansion always stays a finite tree).
    """
    name = element.attrib.get("name")
    if not name:
        raise ValueError("<template> element is missing its 'name' attribute")
    body: Action | Sequential | Parallel | None = None
    defaults: dict[str, str] = {}
    for child in element:
        if child.tag in _GROUP_TAGS or child.tag == _SCOPE_TAG or child.tag == "action":
            if body is not None:
                raise ValueError(
                    f"<template name={name!r}> must contain exactly one body "
                    f"(<sequential>, <parallel>, <scope> or <action>), "
                    f"found <{child.tag}> after an earlier one"
                )
            body = _parse_child(child, templates, globals_)
        elif child.tag == _ARGUMENT_TAG:
            key, value = _argument(child)
            if key in defaults:
                raise ValueError(
                    f"duplicate parameter <argument key={key!r}> in <template name={name!r}>"
                )
            defaults[key] = value
        else:
            raise ValueError(f"unknown element <{child.tag}> inside <template name={name!r}>")
    if body is None:
        raise ValueError(
            f"<template name={name!r}> must contain exactly one body "
            "(<sequential>, <parallel>, <scope> or <action>), found none"
        )
    return Template(name, body, **defaults)


def _parse_use_template(
    element: ET.Element, templates: dict[str, Template], globals_: dict[str, str]
) -> Sequential | Parallel:
    """
    Parse a ``<use-template>`` use site into the instantiated body.

    The element names the template and binds parameters with ``<argument>``
    children; the returned node is the expanded body (a fresh tree), so the
    parsed workflow never carries the reference itself.
    """
    name = element.attrib.get("name")
    if not name:
        raise ValueError("<use-template> element is missing its 'name' attribute")
    template = templates.get(name)
    if template is None:
        raise ValueError(f"unknown template {name!r}")
    bindings: dict[str, str] = {}
    for child in element:
        if child.tag != _ARGUMENT_TAG:
            raise ValueError(
                f"unknown element <{child.tag}> inside <use-template name={name!r}>; "
                "template parameters must be <argument> elements"
            )
        key, value = _argument(child)
        if key in bindings:
            raise ValueError(
                f"duplicate parameter <argument key={key!r}> in <use-template name={name!r}>"
            )
        bindings[key] = value
    return template._expand(bindings, globals_)


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
