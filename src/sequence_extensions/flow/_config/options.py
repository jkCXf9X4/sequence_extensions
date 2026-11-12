"""Node and run options — the explicit, per-call configuration surface.

There is no global configuration in 3.0.  A :class:`RunOptions` travels
with one ``execute_flow`` call; a :class:`NodePolicy` is the default policy
for nodes whose decorator left a value unset.

Resolution, from strongest to weakest:

* a plan document's ``node_policies`` override (``RunOptions.node_policies``);
* an explicit ``@node(...)`` keyword;
* ``RunOptions.node_defaults`` of the active run;
* the built-in default.

``RunOptions`` fields left at :data:`UNSET` fall back to the built-in
default.  ``log=None`` disables the file.
"""

from __future__ import annotations

import inspect
import math
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

__all__ = [
    "DEFAULT_LOG_DIR",
    "DEFAULT_MAX_WORKERS",
    "NodeIdentity",
    "NodePolicy",
    "RunOptions",
    "UNSET",
    "fill_parameters",
    "node_key",
    "validate_node_policy",
]

#: Default directory for run logs (relative to the current directory).
DEFAULT_LOG_DIR = "runs"

#: Default number of workers for a run-owned thread pool.
DEFAULT_MAX_WORKERS = 16


class _Unset:
    """Sentinel for "not given"."""

    __slots__ = ()

    def __repr__(self) -> str:
        return "UNSET"

    def __reduce__(self):
        # Pickle as the module singleton, never as a fresh instance.
        return (_get_unset, ())


def _get_unset() -> _Unset:
    return UNSET


#: Sentinel for "not given" — resolve from the built-in default.
UNSET = _Unset()


# ---------------------------------------------------------------- #
# Shared constraint checks
# ---------------------------------------------------------------- #
def validate_node_policy(retries=UNSET, retry_delay_seconds=UNSET, timeout=UNSET) -> None:
    """Node policy constraints; fields left ``UNSET`` are skipped."""
    if retries is not UNSET:
        _check_int(retries, "retries", minimum=0)
    if retry_delay_seconds is not UNSET:
        _check_number(retry_delay_seconds, "retry_delay_seconds", minimum=0)
    if timeout is not UNSET and timeout is not None:
        _check_number(timeout, "timeout")
        if timeout <= 0:
            raise ValueError(f"timeout must be > 0, got {timeout}")


def _check_int(value, name: str, *, minimum: int | None = None) -> None:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{name} must be an integer, got {value!r}")
    if minimum is not None and value < minimum:
        raise ValueError(f"{name} must be >= {minimum}, got {value}")


def _check_number(value, name: str, *, minimum=None) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a number, got {value!r}")
    if not math.isfinite(value):
        raise ValueError(f"{name} must be finite, got {value!r}")
    if minimum is not None and value < minimum:
        raise ValueError(f"{name} must be >= {minimum}, got {value}")


def _check_bool(value, name: str) -> None:
    if not isinstance(value, bool):
        raise ValueError(f"{name} must be true or false, got {value!r}")


def _check_str(value, name: str) -> None:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{name} must be a non-empty string, got {value!r}")


# ---------------------------------------------------------------- #
# Node identity
# ---------------------------------------------------------------- #
@dataclass(frozen=True)
class NodeIdentity:
    """Canonical identity of one submitted node occurrence.

    ``name`` is the node name.  ``path`` is the node-name chain from the run
    root (inclusive) to this occurrence.  ``instance`` is the 1-based
    occurrence among submissions sharing the same ``(name, path)`` in
    submission order.  Two occurrences of the same name at the same path are
    told apart by ``instance``; the same name at different paths differs in
    ``path``.
    """

    name: str
    path: tuple[str, ...]
    instance: int

    def __post_init__(self) -> None:
        _check_str(self.name, "NodeIdentity.name")
        if isinstance(self.path, list):
            object.__setattr__(self, "path", tuple(self.path))
        if not isinstance(self.path, tuple) or not all(isinstance(part, str) for part in self.path):
            raise ValueError(f"NodeIdentity.path must be a tuple of strings, got {self.path!r}")
        _check_int(self.instance, "NodeIdentity.instance", minimum=1)


def node_key(key) -> str | NodeIdentity:
    """Normalize an override key to a node name or a :class:`NodeIdentity`.

    ``RunOptions.parameters`` and ``RunOptions.node_policies`` accept either
    a bare node name (legacy, every occurrence) or a ``NodeIdentity`` (one
    occurrence).  Any other key is rejected.
    """
    if isinstance(key, str):
        _check_str(key, "node key")
        return key
    if isinstance(key, NodeIdentity):
        return key
    raise ValueError(f"node key must be a node name or NodeIdentity, got {key!r}")


# ---------------------------------------------------------------- #
# Node policy defaults
# ---------------------------------------------------------------- #
@dataclass(frozen=True)
class NodePolicy:
    """Default retry / backoff / timeout for nodes that left a value unset.

    Carried by :attr:`RunOptions.node_defaults`; an explicit ``@node``
    keyword always wins over it.
    """

    retries: int = 0
    retry_delay_seconds: float = 0.0
    timeout: float | None = None

    def __post_init__(self) -> None:
        validate_node_policy(self.retries, self.retry_delay_seconds, self.timeout)


# ---------------------------------------------------------------- #
# Per-run options
# ---------------------------------------------------------------- #
@dataclass(frozen=True)
class RunOptions:
    """Options for one ``execute_flow`` call.

    ``UNSET`` means "not given": the root run takes the built-in default.
    ``log=None`` (or ``""``) disables the file.
    """

    name: str | None = None
    max_workers: int | _Unset = UNSET
    log: str | Path | None | _Unset = UNSET
    summary: bool | _Unset = UNSET
    fixed_clock: bool | _Unset = UNSET
    pool: Any = None
    retries: int | _Unset = UNSET
    retry_delay_seconds: float | int | _Unset = UNSET
    timeout: float | int | None | _Unset = UNSET
    node_defaults: NodePolicy | None | _Unset = UNSET
    node_policies: dict[str | NodeIdentity, NodePolicy] | None | _Unset = UNSET
    parameters: dict[str | NodeIdentity, dict[str, Any]] | None | _Unset = UNSET

    def __post_init__(self) -> None:
        if self.name is not None:
            _check_str(self.name, "name")
        if self.max_workers is not UNSET:
            _check_int(self.max_workers, "max_workers", minimum=1)
        if self.log is not UNSET:
            if self.log == "":  # an empty string means "disabled"
                object.__setattr__(self, "log", None)
            elif self.log is not None and not isinstance(self.log, (str, Path)):
                raise ValueError(f"log must be a directory path, None, or '', got {self.log!r}")
        if self.summary is not UNSET:
            _check_bool(self.summary, "summary")
        if self.fixed_clock is not UNSET:
            _check_bool(self.fixed_clock, "fixed_clock")
        if self.pool is not None:
            # Imported lazily to keep this module free of engine imports.
            from sequence_extensions.graph.graph_future import GraphPool

            if not isinstance(self.pool, GraphPool):
                raise ValueError(f"pool must be a GraphPool or None, got {self.pool!r}")
        validate_node_policy(self.retries, self.retry_delay_seconds, self.timeout)
        if self.node_defaults is not UNSET:
            if self.node_defaults is not None and not isinstance(self.node_defaults, NodePolicy):
                raise ValueError(
                    f"node_defaults must be a NodePolicy or None, got {self.node_defaults!r}"
                )
        if self.node_policies is not UNSET and self.node_policies is not None:
            if not isinstance(self.node_policies, Mapping):
                raise ValueError(
                    "node_policies must be a dict of {node: NodePolicy}, "
                    f"got {self.node_policies!r}"
                )
            for key, policy in self.node_policies.items():
                node_key(key)
                if not isinstance(policy, NodePolicy):
                    raise ValueError(f"node_policies[{key!r}] must be a NodePolicy, got {policy!r}")
        if self.parameters is not UNSET and self.parameters is not None:
            if not isinstance(self.parameters, dict):
                raise ValueError(
                    "parameters must be a dict of "
                    f"{{node: {{param: value}}}}, got {self.parameters!r}"
                )
            for key, entry in self.parameters.items():
                node_key(key)
                if not isinstance(entry, dict):
                    raise ValueError(
                        f"parameters[{key!r}] must be a dict of {{param: value}}, got {entry!r}"
                    )

    # ------------------------------------------------------------ #
    # Resolution
    # ------------------------------------------------------------ #
    def resolve(self, node_name: str) -> RunOptions:
        """Return concrete options for a run rooted at ``node_name``.

        Every ``UNSET`` field is filled from the built-in default.
        """

        def default(field, fallback):
            value = getattr(self, field)
            return fallback if value is UNSET else value

        return RunOptions(
            name=self.name or node_name,
            max_workers=default("max_workers", DEFAULT_MAX_WORKERS),
            log=default("log", DEFAULT_LOG_DIR),
            summary=default("summary", False),
            fixed_clock=default("fixed_clock", False),
            pool=self.pool,
            retries=default("retries", 0),
            retry_delay_seconds=default("retry_delay_seconds", 0.0),
            timeout=default("timeout", None),
            node_defaults=default("node_defaults", None),
            node_policies=default("node_policies", None),
            parameters=default("parameters", None),
        )


def _signature_parameters(sig) -> list[tuple[str, inspect.Parameter, str]]:
    """A signature's plain parameters: ``(name, parameter, annotation)`` triples.

    ``*args`` and ``**kwargs`` are skipped; each annotation becomes its
    ``__name__`` when the annotation is a named object, else its string form,
    and ``""`` when the parameter is unannotated.  Order is signature order.
    """
    out = []
    for name, p in sig.parameters.items():
        if p.kind in (p.VAR_POSITIONAL, p.VAR_KEYWORD):
            continue
        annotation = p.annotation
        ann = (
            getattr(annotation, "__name__", str(annotation))
            if annotation is not inspect.Parameter.empty
            else ""
        )
        out.append((name, p, ann))
    return out


def fill_parameters(
    node_name: str, fn, args: tuple, kwargs: dict, registry, identity: NodeIdentity | None = None
) -> tuple:
    """Fill MISSING kwargs for a node occurrence from the override ``registry``.

    A parameter already bound positionally (via ``fn``'s signature) or
    explicitly in ``kwargs`` is code and wins; it is not overwritten.  The
    exact ``identity`` entry wins over the node-name entry for overlapping
    parameters; the name entry still fills parameters the identity entry does
    not mention.  A no-op when ``registry`` is None/empty or neither key is
    present.  Returns ``(args, new_kwargs)``.
    """
    if not registry:
        return args, kwargs
    merged: dict = {}
    name_entry = registry.get(node_name)
    if name_entry:
        merged.update(name_entry)
    if identity is not None:
        exact_entry = registry.get(identity)
        if exact_entry:
            merged.update(exact_entry)
    if not merged:
        return args, kwargs
    try:
        bound = inspect.signature(fn).bind_partial(*args, **kwargs)
    except (TypeError, ValueError):
        bound_names = set(kwargs)
    else:
        bound_names = set(bound.arguments)
    missing = {name: value for name, value in merged.items() if name not in bound_names}
    if not missing:
        return args, kwargs
    return args, {**kwargs, **missing}


def bind_flow_inputs(fn, inputs: Mapping) -> tuple[tuple, dict]:
    """Split a flow's inputs into positional args and keyword args.

    ``execute_flow`` reserves the keyword ``options`` for run options, so a
    node with a parameter also named ``options`` receives that input
    positionally: the positional prefix is built up to and including it.  A
    keyword-only ``options`` (or one reached after ``*args``/``**kwargs``)
    raises ``ValueError`` instead of failing with a confusing ``TypeError``
    at call time.
    """
    target = getattr(fn, "__wrapped__", fn)
    sig = inspect.signature(target)
    kwargs = dict(inputs)
    args: list = []
    if "options" in kwargs:
        handled = False
        for name, param in sig.parameters.items():
            if name == "options":
                if param.kind in (
                    inspect.Parameter.KEYWORD_ONLY,
                    inspect.Parameter.VAR_POSITIONAL,
                    inspect.Parameter.VAR_KEYWORD,
                ):
                    raise ValueError(
                        "node parameter 'options' must be positional "
                        "(and precede *args/**kwargs) to be driven by flow-runner"
                    )
                args.append(kwargs.pop("options"))
                handled = True
                break
            if param.kind is inspect.Parameter.VAR_POSITIONAL:
                raise ValueError(
                    "node parameter 'options' cannot be reached positionally past *args"
                )
            if param.kind is inspect.Parameter.VAR_KEYWORD:
                raise ValueError(
                    "a parameter named 'options' captured only by **kwargs "
                    "cannot be driven by flow-runner"
                )
            if param.kind in (
                inspect.Parameter.POSITIONAL_ONLY,
                inspect.Parameter.POSITIONAL_OR_KEYWORD,
            ):
                if name in kwargs:
                    args.append(kwargs.pop(name))
                elif param.default is not inspect.Parameter.empty:
                    args.append(param.default)
                else:
                    raise ValueError(f"missing required input {name!r}")
        if not handled:
            raise ValueError("flow has no parameter named 'options'")
    sig.bind(*args, **kwargs)
    return tuple(args), kwargs
