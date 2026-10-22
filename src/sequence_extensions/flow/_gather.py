"""``gather``: resolve the futures inside a value without blocking a worker.

The value is planned into a template of slots in traversal order; the
collect node receives those futures as dependencies and fills the template.
Containers keep their shape; mappings other than ``dict`` become a plain
dict.  Cyclic or over-deep containers are rejected instead of recursing
without bound.
"""

from __future__ import annotations

from collections.abc import Mapping

from sequence_extensions.flow._context import current_run
from sequence_extensions.flow._futures import FlowFuture, _is_future

#: Recursion guard for container inspection and ``gather`` planning.
_MAX_CONTAINER_DEPTH = 200


def _contains_future(value, _seen=None, _depth: int = 0) -> bool:
    """True if a returned container still holds futures.

    A node should return one future (see :func:`gather`), not a list or
    dict of futures: the graph layer only awaits a single returned future.
    Self-referential containers and depth beyond ``_MAX_CONTAINER_DEPTH`` are
    treated as opaque (no future) instead of exhausting the stack; the log
    records them with a cycle/depth marker.
    """
    if _is_future(value):
        return True
    if _depth >= _MAX_CONTAINER_DEPTH:
        return False
    if isinstance(value, Mapping):
        if _seen is None:
            _seen = set()
        marker = id(value)
        if marker in _seen:
            return False
        _seen.add(marker)
        try:
            return any(_contains_future(v, _seen, _depth + 1) for v in value.values())
        finally:
            _seen.discard(marker)
    if isinstance(value, (list, tuple, set, frozenset)):
        if _seen is None:
            _seen = set()
        marker = id(value)
        if marker in _seen:
            return False
        _seen.add(marker)
        try:
            return any(_contains_future(v, _seen, _depth + 1) for v in value)
        finally:
            _seen.discard(marker)
    return False


class _Slot:
    """Template marker: fill me from ``values[index]``."""

    __slots__ = ("index",)

    def __init__(self, index):
        self.index = index

    def __reduce__(self):
        """Pickle transport for process pools (the template is dispatched)."""
        return (_make_slot, (self.index,))


def _make_slot(index):
    return _Slot(index)


def _enter_gather(value, _seen, _depth):
    """Cycle/depth guard shared by the ``_plan`` container branches."""
    if _depth >= _MAX_CONTAINER_DEPTH:
        raise ValueError("gather() container is deeper than the supported limit")
    if _seen is None:
        _seen = set()
    marker = id(value)
    if marker in _seen:
        raise ValueError("gather() cannot resolve a cyclic container")
    _seen.add(marker)
    return _seen, marker


def _plan(value, items, _seen=None, _depth: int = 0):
    """Template for ``value``: futures become slots, containers keep shape.

    Futures are collected into ``items`` in traversal order, which is the
    order of the collect node's dependencies (and therefore of ``values``
    in :func:`_fill`).  Mappings other than ``dict`` are resolved into a
    plain dict.  A cyclic or over-deep container raises ``ValueError``
    instead of recursing without bound.
    """
    if _is_future(value):
        items.append(value)
        return _Slot(len(items) - 1)
    if isinstance(value, Mapping):
        _seen, marker = _enter_gather(value, _seen, _depth)
        try:
            return {
                key: _plan(item, items, _seen, _depth + 1)
                for key, item in value.items()
            }
        finally:
            _seen.discard(marker)
    if isinstance(value, list):
        _seen, marker = _enter_gather(value, _seen, _depth)
        try:
            return [_plan(item, items, _seen, _depth + 1) for item in value]
        finally:
            _seen.discard(marker)
    if isinstance(value, tuple):
        _seen, marker = _enter_gather(value, _seen, _depth)
        try:
            planned = [_plan(item, items, _seen, _depth + 1) for item in value]
        finally:
            _seen.discard(marker)
        if hasattr(value, "_fields"):
            return type(value)(*planned)
        try:
            return type(value)(planned)
        except Exception:
            return tuple(planned)
    if isinstance(value, (set, frozenset)):
        _seen, marker = _enter_gather(value, _seen, _depth)
        try:
            return type(value)(_plan(item, items, _seen, _depth + 1) for item in value)
        finally:
            _seen.discard(marker)
    return value


def _fill(template, values):
    """Inverse of :func:`_plan`: rebuild the shape, slots become results."""
    if isinstance(template, _Slot):
        return values[template.index]
    if isinstance(template, Mapping):
        return {key: _fill(item, values) for key, item in template.items()}
    if isinstance(template, list):
        return [_fill(item, values) for item in template]
    if isinstance(template, tuple):
        filled = [_fill(item, values) for item in template]
        if hasattr(template, "_fields"):
            return type(template)(*filled)
        try:
            return type(template)(filled)
        except Exception:
            return tuple(filled)
    if isinstance(template, (set, frozenset)):
        return type(template)(_fill(item, values) for item in template)
    return template


def _collect_structural(template, *values):
    return _fill(template, values)


def gather(value):
    """Return a future for ``value`` with its futures replaced by results.

    Containers keep their shape, at any depth: ``{"a": submit(1)}``
    resolves to ``{"a": 1}``, a nested list stays a list, and a tuple or
    set stays a tuple or set.  Mappings other than ``dict`` resolve to a
    plain dict; namedtuples and orderable tuple subclasses keep their type.
    Only values are resolved (dict keys are kept as-is).  A bare future
    resolves to a one-element list, and any other iterable is materialized
    into a list.  The result is a :class:`FlowFuture`, so it can be returned
    from a node or passed as a dependency to :meth:`NodeFunction.submit`.

    ``gather`` needs an active run (its future is evaluated by the run's
    pool); outside one it raises ``RuntimeError`` instead of hanging.
    """
    if current_run() is None:
        raise RuntimeError(
            "gather() requires an active run: call execute_flow(...) around the node"
        )
    if _is_future(value):
        future = FlowFuture(_collect_structural, [_Slot(0)], value)
    else:
        if not isinstance(value, (list, tuple, Mapping, set, frozenset)):
            value = list(value)
        items = []
        future = FlowFuture(_collect_structural, _plan(value, items), *items)
    future.set_name("gather")
    return future
