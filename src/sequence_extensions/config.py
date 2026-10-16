"""External configuration: tune the flow engine without editing code.

A :class:`Config` holds the tunable surface of the flow engine — flow
pool size, log location, task retry / timeout policy, pool defaults.
Load one from a TOML file (:meth:`Config.from_toml`), build one in code
(:meth:`Config.from_dict` or the dataclass constructors — every
constructor validates), and install it with :func:`configure`.  The
file format is TOML, read with the standard library's ``tomllib``::

    [run]                      # flow-runner selection (ignored by configure)
    module = "mypackage.flows"
    flow = "campaign"

    [inputs]                   # keyword arguments for the flow
    items = [1, 2, 3]

    [flow]
    max_workers = 8            # default 16
    log = "output/runs"        # default "runs"; "" disables run logging
    summary = true              # default false

    [task]
    retries = 2                 # default 0
    retry_delay_seconds = 0.5   # default 0.0
    timeout = 30.0              # default: omit (no timeout)

    [pool]
    process_max_workers = 4     # default: omit (CPU count, ProcessGraphPool)

Every section and key is optional: an omitted key keeps its built-in
default, so a config-free program behaves exactly as before.

Resolution is per call, keyword-first:

* an explicit decorator keyword always wins (``@task(retries=2)``);
* else the value from the active config (:func:`active_config`);
* else the built-in default.

Resolution happens at call time, not at decoration time: a module of
decorated tasks and flows picks up a config installed after import, so
``configure()`` in ``main()`` reaches module-level decorators.  A
``ProcessGraphPool`` constructed without ``max_workers`` resolves at
construction time — construct it after ``configure()`` or pass
``max_workers`` explicitly.  The thread substrate (``graph``) and the
``ext`` helpers stay config-free: a ``GraphPool`` keeps its fixed
default, and ``@flow`` sizes its own pool from ``[flow].max_workers``.

The active config lives in a :class:`contextvars.ContextVar`, the same
plumbing the run context uses; worker threads started by the flow layer
restore it around task bodies, and a task's ``submit()`` snapshot
travels with it.

TOML has no ``null``: omit a key to keep its default.  ``log = ""`` is
the one spelling for "disable run logging" and normalizes to ``None``.
"""

from __future__ import annotations

import contextvars
import tomllib
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

__all__ = [
    "DEFAULT_LOG_DIR",
    "UNSET",
    "Config",
    "ConfigError",
    "FlowConfig",
    "PoolConfig",
    "RunConfig",
    "TaskConfig",
    "active_config",
    "configure",
    "reset_config",
    "use_config",
    "validate_task_policy",
]

#: Default directory for run logs (relative to the current directory).
DEFAULT_LOG_DIR = "runs"


class ConfigError(ValueError):
    """Invalid configuration: unreadable file, unknown key, or failing constraint."""


class _Unset:
    """``retries=UNSET`` on a decorator means "not given" — resolve at call time."""

    __slots__ = ()

    def __repr__(self) -> str:
        return "UNSET"

    def __reduce__(self):
        # Pickle as the module singleton, never as a fresh instance.
        return (_get_unset, ())


def _get_unset() -> _Unset:
    return UNSET


#: Sentinel for "not given at decoration time".  Per-call resolution:
#: explicit keyword > active config > built-in default.
UNSET = _Unset()


# ---------------------------------------------------------------- #
# Shared constraint checks
# ---------------------------------------------------------------- #
def validate_task_policy(retries, retry_delay_seconds, timeout) -> None:
    """Task policy constraints — the one check ``@task`` and ``Config`` share."""
    if retries < 0:
        raise ValueError(f"retries must be >= 0, got {retries}")
    if retry_delay_seconds < 0:
        raise ValueError(f"retry_delay_seconds must be >= 0, got {retry_delay_seconds}")
    if timeout is not None and timeout <= 0:
        raise ValueError(f"timeout must be > 0, got {timeout}")


def _check_int(value, name: str, *, minimum: int | None = None) -> None:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{name} must be an integer, got {value!r}")
    if minimum is not None and value < minimum:
        raise ValueError(f"{name} must be >= {minimum}, got {value}")


def _check_number(value, name: str, *, minimum=None) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a number, got {value!r}")
    if minimum is not None and value < minimum:
        raise ValueError(f"{name} must be >= {minimum}, got {value}")


def _check_bool(value, name: str) -> None:
    if not isinstance(value, bool):
        raise ValueError(f"{name} must be true or false, got {value!r}")


def _check_str(value, name: str) -> None:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{name} must be a non-empty string, got {value!r}")


# ---------------------------------------------------------------- #
# Config sections (frozen, validated on construction)
# ---------------------------------------------------------------- #
@dataclass(frozen=True)
class TaskConfig:
    """``[task]`` — default retry / backoff / timeout policy for ``@task``."""

    retries: int = 0
    retry_delay_seconds: float = 0.0
    timeout: float | None = None

    def __post_init__(self) -> None:
        _check_int(self.retries, "retries", minimum=0)
        _check_number(self.retry_delay_seconds, "retry_delay_seconds", minimum=0)
        if self.timeout is not None:
            _check_number(self.timeout, "timeout")
            if self.timeout <= 0:
                raise ValueError(f"timeout must be > 0, got {self.timeout}")


@dataclass(frozen=True)
class FlowConfig:
    """``[flow]`` — defaults for ``@flow`` when it builds its own pool and log."""

    max_workers: int = 16
    log: str | Path | None = DEFAULT_LOG_DIR
    summary: bool = False

    def __post_init__(self) -> None:
        _check_int(self.max_workers, "max_workers", minimum=1)
        _check_bool(self.summary, "summary")
        if self.log is not None and not isinstance(self.log, (str, Path)):
            raise ValueError(f"log must be a directory path, None, or '', got {self.log!r}")
        if self.log == "":  # the TOML spelling of "disabled" (TOML has no null)
            object.__setattr__(self, "log", None)


@dataclass(frozen=True)
class PoolConfig:
    """``[pool]`` — default for a ``ProcessGraphPool`` constructed bare.

    The thread substrate stays config-free: ``GraphPool`` keeps its
    fixed default (16), and ``@flow`` sizes its own pool from
    ``[flow].max_workers``.
    """

    process_max_workers: int | None = None

    def __post_init__(self) -> None:
        if self.process_max_workers is not None:
            _check_int(self.process_max_workers, "process_max_workers", minimum=1)


@dataclass(frozen=True)
class RunConfig:
    """``[run]`` — flow-runner selection; carried by ``Config``, unused by ``configure``."""

    module: str | None = None
    flow: str | None = None

    def __post_init__(self) -> None:
        if self.module is not None:
            _check_str(self.module, "module")
        if self.flow is not None:
            _check_str(self.flow, "flow")


@dataclass(frozen=True)
class Config:
    """The whole configuration file: engine defaults plus runner selection."""

    flow: FlowConfig = FlowConfig()
    task: TaskConfig = TaskConfig()
    pool: PoolConfig = PoolConfig()
    run: RunConfig = RunConfig()
    inputs: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.inputs, Mapping):
            raise ValueError(f"inputs must be a table, got {type(self.inputs).__name__}")

    @classmethod
    def from_toml(cls, path: str | Path) -> Config:
        """Load and validate a TOML config file (missing file and TOML errors
        become :class:`ConfigError` with the path in the message)."""
        path = Path(path)
        try:
            with path.open("rb") as fh:
                data = tomllib.load(fh)
        except OSError as e:
            raise ConfigError(f"cannot read config file {path}: {e}") from None
        except tomllib.TOMLDecodeError as e:
            raise ConfigError(f"{path}: invalid TOML: {e}") from None
        return cls.from_dict(data, where=str(path))

    @classmethod
    def from_dict(cls, data: Mapping, where: str = "config") -> Config:
        """Build a :class:`Config` from a mapping (a parsed file, or code).

        Strict: unknown sections and keys are errors, every value is
        type-checked, and ``where`` prefixes messages with their source.
        """
        if not isinstance(data, Mapping):
            raise ConfigError(f"{where}: config must be a table, got {type(data).__name__}")
        _check_keys(data, {"flow", "task", "pool", "run", "inputs"}, "", where)
        return cls(
            flow=_section(data, "flow", FlowConfig, where),
            task=_section(data, "task", TaskConfig, where),
            pool=_section(data, "pool", PoolConfig, where),
            run=_section(data, "run", RunConfig, where),
            inputs=_inputs(data, where),
        )


def _check_keys(section: Mapping, allowed: set, title: str, where: str) -> None:
    """Reject keys the section does not define (catches typos early)."""
    unknown = sorted(set(section) - allowed)
    if unknown:
        known = ", ".join(sorted(allowed))
        listed = ", ".join(repr(k) for k in unknown)
        if title:
            raise ConfigError(f"{where}: unknown key(s) in [{title}]: {listed} (known: {known})")
        raise ConfigError(f"{where}: unknown section(s): {listed} (known: {known})")


def _section(data: Mapping, title: str, build: Callable, where: str):
    """Build one config section: table check, key check, then validated construction."""
    section = data.get(title, {})
    if not isinstance(section, Mapping):
        raise ConfigError(f"{where}: [{title}] must be a table, got {type(section).__name__}")
    _check_keys(section, _KEYS[title], title, where)
    try:
        return build(**section)
    except ValueError as e:
        raise ConfigError(f"{where}: [{title}] {e}") from None


def _inputs(data: Mapping, where: str) -> dict:
    """``[inputs]`` passes through as-is: TOML values, any shape."""
    inputs = data.get("inputs", {})
    if not isinstance(inputs, Mapping):
        raise ConfigError(f"{where}: [inputs] must be a table, got {type(inputs).__name__}")
    return dict(inputs)


_KEYS = {
    "flow": {"max_workers", "log", "summary"},
    "task": {"retries", "retry_delay_seconds", "timeout"},
    "pool": {"process_max_workers"},
    "run": {"module", "flow"},
}


# ---------------------------------------------------------------- #
# The active configuration
# ---------------------------------------------------------------- #
_config_var: contextvars.ContextVar = contextvars.ContextVar(
    "sequence_extensions_config",
    # Safe: Config is a frozen dataclass — immutable, so a shared default
    # cannot be mutated out from under other threads.
    default=Config(),  # noqa: B039
)


def active_config() -> Config:
    """The configuration this thread resolves defaults from (built-ins without one)."""
    return _config_var.get()


def configure(config: Config):
    """Install ``config`` as the active configuration; returns a reset token.

    Every later-resolved default (a bare ``@task`` / ``@flow`` keyword,
    a pool constructed without ``max_workers``) reads from it; explicit
    decorator keywords keep winning.
    """
    if not isinstance(config, Config):
        raise TypeError(f"configure() expects a Config, got {config!r}")
    return _config_var.set(config)


def reset_config(token) -> None:
    """Restore the previous configuration (the pair of :func:`configure`)."""
    _config_var.reset(token)


@contextmanager
def use_config(config: Config) -> Iterator[Config]:
    """Run a block under ``config``; the previous configuration is restored on exit."""
    token = configure(config)
    try:
        yield config
    finally:
        reset_config(token)
