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

import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

__all__ = [
    "DEFAULT_LOG_DIR",
    "DEFAULT_MAX_WORKERS",
    "NodePolicy",
    "RunOptions",
    "UNSET",
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
        )
