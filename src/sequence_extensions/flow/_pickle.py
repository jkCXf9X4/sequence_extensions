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
