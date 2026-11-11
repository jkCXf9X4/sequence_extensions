"""Node and run options — the explicit, per-call configuration surface.

There is no global configuration in 3.0.  A :class:`RunOptions` travels
with one ``execute_flow`` call; a :class:`NodePolicy` is the default policy
for nodes whose decorator left a value unset.

Resolution, from strongest to weakest:

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
from dataclasses import dataclass, fields
from pathlib import Path
from typing import Any

__all__ = [
    "DEFAULT_LOG_DIR",
    "DEFAULT_MAX_WORKERS",
    "NodePolicy",
    "RunOptions",
    "UNSET",
    "fill_parameters",
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
#: RunOptions fields that are run code concerns, never config-file options:
#: ``name`` (the runner derives identity from module+flow), ``pool`` (a
#: caller-owned pool built in code), ``node_defaults`` (the ``[node]``
#: table), and ``parameters`` (the override registry).
_RUN_OPTION_EXCLUDED = frozenset({"name", "pool", "node_defaults", "parameters"})


@dataclass(frozen=True)
class RunOptions:
    """Options for one ``execute_flow`` call.

    ``UNSET`` means "not given": the root run takes the built-in default.
    ``log=None`` (or the TOML spelling ``""``) disables the file.
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
    parameters: dict[str, dict[str, Any]] | None | _Unset = UNSET

    def __post_init__(self) -> None:
        if self.name is not None:
            _check_str(self.name, "name")
        if self.max_workers is not UNSET:
            _check_int(self.max_workers, "max_workers", minimum=1)
        if self.log is not UNSET:
            if self.log == "":  # TOML has no null
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
        if self.parameters is not UNSET and self.parameters is not None:
            if not isinstance(self.parameters, dict):
                raise ValueError(
                    "parameters must be a dict of "
                    f"{{node: {{param: value}}}}, got {self.parameters!r}"
                )
            for name, entry in self.parameters.items():
                if not isinstance(entry, dict):
                    raise ValueError(
                        f"parameters[{name!r}] must be a dict of {{param: value}}, got {entry!r}"
                    )

    # ------------------------------------------------------------ #
    # Config-file surface
    # ------------------------------------------------------------ #
    @classmethod
    def toml_keys(cls) -> frozenset[str]:
        """The :class:`RunOptions` field names a config file may set.

        Derived from the dataclass fields minus the code concerns in
        ``_RUN_OPTION_EXCLUDED``; a field added to the dataclass appears
        here unless it is deliberately excluded.
        """
        return frozenset(f.name for f in fields(cls) if f.name not in _RUN_OPTION_EXCLUDED)

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


def fill_parameters(node_name: str, fn, args: tuple, kwargs: dict, registry) -> tuple:
    """Fill MISSING kwargs for ``node_name`` from the override ``registry``.

    A parameter already bound positionally (via ``fn``'s signature) or
    explicitly in ``kwargs`` is code and wins; it is not overwritten.
    A no-op when ``registry`` is None/empty or ``node_name`` is absent.
    Returns ``(args, new_kwargs)``.
    """
    if not registry:
        return args, kwargs
    entry = registry.get(node_name)
    if not entry:
        return args, kwargs
    try:
        bound = inspect.signature(fn).bind_partial(*args, **kwargs)
    except (TypeError, ValueError):
        bound_names = set(kwargs)
    else:
        bound_names = set(bound.arguments)
    missing = {name: value for name, value in entry.items() if name not in bound_names}
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
