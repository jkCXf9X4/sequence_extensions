"""Runner configuration: the strict TOML contract.

One file drives an invocation: which module and node to run, the run
options, and the root node's inputs.  Validation is strict and reports the
source path, so a typo fails before any node runs.
"""

from __future__ import annotations

import tomllib
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sequence_extensions.flow import NodePolicy, RunOptions

__all__ = ["RunnerConfig", "RunnerConfigError"]

_RUN_OPTION_KEYS = {
    "max_workers",
    "log",
    "summary",
    "fixed_clock",
    "retries",
    "retry_delay_seconds",
    "timeout",
}
_RUN_KEYS = {"module", "flow"} | _RUN_OPTION_KEYS
_NODE_KEYS = {"retries", "retry_delay_seconds", "timeout"}
_LEGACY_SECTIONS = {
    "flow": "[run]",
    "task": "[node]",
    "pool": "in code (RunOptions.pool / ProcessGraphPool)",
}


class RunnerConfigError(ValueError):
    """Invalid runner configuration: unreadable file, unknown key, or bad value."""


@dataclass(frozen=True)
class RunnerConfig:
    """One runner invocation: selection, inputs, and run options."""

    module: str | None = None
    flow: str | None = None
    inputs: dict[str, Any] = field(default_factory=dict)
    options: RunOptions = field(default_factory=RunOptions)

    @classmethod
    def from_toml(cls, path: str | Path) -> RunnerConfig:
        """Load and validate a TOML file (missing file and TOML errors become
        :class:`RunnerConfigError` with the path in the message)."""
        path = Path(path)
        try:
            with path.open("rb") as fh:
                data = tomllib.load(fh)
        except OSError as e:
            raise RunnerConfigError(f"cannot read config file {path}: {e}") from None
        except tomllib.TOMLDecodeError as e:
            raise RunnerConfigError(f"{path}: invalid TOML: {e}") from None
        return cls.from_dict(data, where=str(path))

    @classmethod
    def from_dict(cls, data: Mapping, where: str = "config") -> RunnerConfig:
        """Build a :class:`RunnerConfig` from a mapping (a parsed file, or code).

        Strict: unknown sections and keys are errors, every value is
        type-checked, and ``where`` prefixes messages with their source.
        """
        if not isinstance(data, Mapping):
            raise RunnerConfigError(f"{where}: config must be a table, got {type(data).__name__}")
        sections = set(data)
        legacy = sorted(sections & set(_LEGACY_SECTIONS))
        if legacy:
            renamed = ", ".join(f"[{name}] -> {_LEGACY_SECTIONS[name]}" for name in legacy)
            raise RunnerConfigError(f"{where}: section(s) renamed in 3.0: {renamed}")
        unknown = sorted(sections - {"run", "node", "inputs"})
        if unknown:
            listed = ", ".join(repr(key) for key in unknown)
            raise RunnerConfigError(
                f"{where}: unknown section(s): {listed} (known: run, node, inputs)"
            )

        run = _table(data, "run", where)
        _reject_unknown(run, _RUN_KEYS, where, "[run]")

        module = _optional_str(run.get("module"), "module", where, "[run]")
        flow = _optional_str(run.get("flow"), "flow", where, "[run]")

        node = _table(data, "node", where)
        _reject_unknown(node, _NODE_KEYS, where, "[node]")

        option_values = {key: run[key] for key in _RUN_OPTION_KEYS if key in run}
        if "node" in data:
            try:
                option_values["node_defaults"] = NodePolicy(**node)
            except ValueError as e:
                raise RunnerConfigError(f"{where}: [node] {e}") from None
        try:
            options = RunOptions(**option_values)
        except ValueError as e:
            raise RunnerConfigError(f"{where}: [run] {e}") from None

        inputs = data.get("inputs", {})
        if not isinstance(inputs, Mapping):
            raise RunnerConfigError(
                f"{where}: [inputs] must be a table, got {type(inputs).__name__}"
            )

        return cls(module=module, flow=flow, inputs=dict(inputs), options=options)


def _table(data: Mapping, title: str, where: str) -> Mapping:
    section = data.get(title, {})
    if not isinstance(section, Mapping):
        raise RunnerConfigError(f"{where}: [{title}] must be a table, got {type(section).__name__}")
    return section


def _reject_unknown(table: Mapping, allowed, where: str, section: str) -> None:
    unknown = sorted(set(table) - set(allowed))
    if not unknown:
        return
    listed = ", ".join(repr(key) for key in unknown)
    known = ", ".join(sorted(allowed))
    raise RunnerConfigError(f"{where}: unknown key(s) in {section}: {listed} (known: {known})")


def _optional_str(value, name: str, where: str, section: str):
    if value is None:
        return None
    if not isinstance(value, str) or not value:
        raise RunnerConfigError(f"{where}: {section} {name} must be a non-empty string")
    return value
