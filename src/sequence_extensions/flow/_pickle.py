"""Process-pool pickle transport: alias a node's raw function.

``@node`` replaces a module-level function with a :class:`NodeFunction`, so
pickling the raw function by reference fails pickle's identity check.  The
alias rebinds the raw function under a unique private name in its own
module; ``NodeFunction.__reduce__`` ships ``(module, alias)`` plus policy
instead of the function object.  The counter keeps lambdas and factory
closures distinct: a qualname alone collides and would execute the wrong
function in a worker.
"""

from __future__ import annotations

import itertools
import pickle
import re
import sys
import threading

_ALIAS_LOCK = threading.Lock()
_ALIAS_COUNTER = itertools.count()


def register_alias(fn, name: str) -> tuple[str, str] | None:
    """Bind ``fn`` under a unique alias in its own module.

    Returns ``(module_name, alias)`` for ``__reduce__``, or ``None`` when
    the function has no importable module (the node is then unpicklable).
    """
    module = sys.modules.get(getattr(fn, "__module__", None))
    if module is None:
        return None
    with _ALIAS_LOCK:
        tag = next(_ALIAS_COUNTER)
    stem = re.sub(r"\W+", "_", getattr(fn, "__qualname__", "") or name)
    alias = f"__seqext_node_fn_{stem}_{tag}"
    setattr(module, alias, fn)
    return (fn.__module__, alias)


def _reduce_node_function(self):
    """Pickle transport for process pools (see __init__)."""
    alias = getattr(self, "_pickle_alias", None)
    if alias is None:
        raise pickle.PicklingError(
            f"node '{self.name}' is not picklable: its function has no importable module"
        )
    return (
        _rebuild_node_function,
        (alias, self.retries, self.retry_delay_seconds, self.timeout, self.name),
    )


def _rebuild_node_function(alias, retries, retry_delay_seconds, timeout, name):
    """Unpickle a NodeFunction from its module alias (see __reduce__)."""
    from sequence_extensions.flow._decorator import NodeFunction

    module = sys.modules.get(alias[0])
    fn = getattr(module, alias[1], None) if module is not None else None
    if fn is None:
        # E.g. a spawn-started worker: the alias only exists where the
        # decoration ran (module level), not in a fresh interpreter.
        raise pickle.UnpicklingError(f"node function {alias!r} is not importable")
    return NodeFunction(
        fn,
        retries=retries,
        retry_delay_seconds=retry_delay_seconds,
        timeout=timeout,
        name=name,
        _alias=alias,
    )
