"""``flow-runner`` — launch a configured run from the command line.

    flow-runner config.toml
    python -m sequence_extensions.flow_runner config.toml

One TOML file drives everything: which module to import, which node to
run, what to pass it, and the run options::

    [run]
    module = "mypackage.flows"   # module scanned for @node functions
    flow = "campaign"            # node to run as a flow (or --flow NAME)
    max_workers = 8
    log = "runs"
    fixed_clock = false

    [node]                       # defaults for nodes that left a value unset
    retries = 2
    retry_delay_seconds = 0.5
    timeout = 30.0

    [inputs]                     # keyword arguments for the root node
    cases_dir = "cases"

The file is loaded and validated first; there is no global configuration.
Nodes are discovered by scanning the module for the ``__node__`` marker
``@node`` stamps on its wrapper — no registry, no registration call.

Exit codes: ``0`` the run succeeded; ``1`` the run raised; ``2`` usage or
configuration error (bad file, unknown key, missing selection, inputs that
do not match the node's signature).

Nodes needing non-TOML inputs (open connections, custom objects) belong in
a small ``main.py`` that calls ``execute_flow`` directly — the runner is a
convenience, not a requirement.  A config file names a module to import,
so treat it as trusted code.  Process pools are constructed in code; the
runner drives thread-mode runs.
"""

from __future__ import annotations

import argparse
import importlib
import inspect
import json
import sys
import tomllib
import traceback
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sequence_extensions.flow import (
    NodePolicy,
    Run,
    RunOptions,
    execute_flow,
    jsonable,
)

__all__ = [
    "RunnerConfig",
    "RunnerConfigError",
    "find_nodes",
    "list_nodes",
    "main",
]

#: Exit codes: 0 ok, 1 run failure, 2 usage/config error.
EXIT_OK = 0
EXIT_RUN_ERROR = 1
EXIT_USAGE = 2

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
            raise RunnerConfigError(
                f"{where}: config must be a table, got {type(data).__name__}"
            )
        sections = set(data)
        legacy = sorted(sections & set(_LEGACY_SECTIONS))
        if legacy:
            renamed = ", ".join(f"[{name}] -> {_LEGACY_SECTIONS[name]}" for name in legacy)
            raise RunnerConfigError(
                f"{where}: section(s) renamed in 3.0: {renamed}"
            )
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
        node_defaults = None
        if "node" in data:
            try:
                node_defaults = NodePolicy(**node)
            except ValueError as e:
                raise RunnerConfigError(f"{where}: [node] {e}") from None
            option_values["node_defaults"] = node_defaults
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
        raise RunnerConfigError(
            f"{where}: [{title}] must be a table, got {type(section).__name__}"
        )
    return section


def _reject_unknown(table: Mapping, allowed, where: str, section: str) -> None:
    unknown = sorted(set(table) - set(allowed))
    if not unknown:
        return
    listed = ", ".join(repr(key) for key in unknown)
    known = ", ".join(sorted(allowed))
    raise RunnerConfigError(
        f"{where}: unknown key(s) in {section}: {listed} (known: {known})"
    )


def _optional_str(value, name: str, where: str, section: str):
    if value is None:
        return None
    if not isinstance(value, str) or not value:
        raise RunnerConfigError(f"{where}: {section} {name} must be a non-empty string")
    return value


# ---------------------------------------------------------------- #
# Discovery
# ---------------------------------------------------------------- #
def find_nodes(module) -> dict[str, Callable]:
    """Every ``@node``-decorated callable in ``module``, keyed by node name.

    Scans module attributes for the ``__node__`` marker the decorator
    stamps; duplicate names for different objects are an error (the
    runner could only guess which to call).
    """
    nodes: dict[str, Callable] = {}
    for attr in dir(module):
        obj = getattr(module, attr)
        node_name = getattr(obj, "__node__", None)
        if isinstance(node_name, str):
            existing = nodes.get(node_name)
            if existing is not None and existing is not obj:
                raise RunnerConfigError(
                    f"node name {node_name!r} is defined twice in module {module.__name__!r}"
                )
            nodes[node_name] = obj
    return dict(sorted(nodes.items()))


def list_nodes(module) -> list[tuple[str, str]]:
    """One ``(node_name, first docstring line)`` pair per node in ``module``."""
    entries = []
    for node_name, fn in find_nodes(module).items():
        doc = (inspect.getdoc(fn) or "").strip()
        entries.append((node_name, doc.splitlines()[0] if doc else ""))
    return entries


# ---------------------------------------------------------------- #
# Entry point
# ---------------------------------------------------------------- #
def _fail(message: str) -> int:
    print(f"flow-runner: {message}", file=sys.stderr)
    return EXIT_USAGE


def _bind_flow_inputs(fn, inputs: Mapping) -> tuple[tuple, dict]:
    """Split ``[inputs]`` into positional args and keyword args.

    ``execute_flow`` reserves the keyword ``options`` for run options.  A root
    node with a parameter also named ``options`` therefore has to receive that
    input positionally; the runner builds the positional prefix up to and
    including it.  A keyword-only ``options`` (or one reached after
    ``*args``/``**kwargs``) is rejected with a config error instead of a
    confusing ``TypeError`` at call time.
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
                    raise RunnerConfigError(
                        "node parameter 'options' must be positional "
                        "(and precede *args/**kwargs) to be driven by flow-runner"
                    )
                args.append(kwargs.pop("options"))
                handled = True
                break
            if param.kind is inspect.Parameter.VAR_POSITIONAL:
                raise RunnerConfigError(
                    "node parameter 'options' cannot be reached positionally "
                    "past *args"
                )
            if param.kind is inspect.Parameter.VAR_KEYWORD:
                raise RunnerConfigError(
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
                    raise RunnerConfigError(f"missing required input {name!r}")
        if not handled:
            raise RunnerConfigError("flow has no parameter named 'options'")
    sig.bind(*args, **kwargs)
    return tuple(args), kwargs


def main(argv: list[str] | None = None) -> int:
    """Run the node a TOML config selects.  Returns the process exit code."""
    parser = argparse.ArgumentParser(
        prog="flow-runner",
        description="Run a flow selected, parameterized, and configured by a TOML file.",
    )
    parser.add_argument("config", type=Path, help="path to the TOML config file")
    parser.add_argument("--flow", metavar="NAME", help="override the config's [run].flow")
    parser.add_argument(
        "--list",
        action="store_true",
        help="list the nodes in the configured module and exit",
    )
    args = parser.parse_args(argv)

    try:
        cfg = RunnerConfig.from_toml(args.config)
    except RunnerConfigError as e:
        return _fail(str(e))

    if not cfg.module:
        return _fail(f"{args.config}: no module configured — set [run].module")

    try:
        module = importlib.import_module(cfg.module)
    except ImportError as e:
        return _fail(f"cannot import module {cfg.module!r}: {e}")
    except Exception as e:
        return _fail(
            f"module {cfg.module!r} raised while importing: "
            f"{type(e).__name__}: {e}"
        )

    if args.list:
        print(f"flows in {cfg.module}:")
        entries = list_nodes(module)
        for node_name, summary in entries:
            print(f"  {node_name}" + (f"  — {summary}" if summary else ""))
        if not entries:
            print("  (none found)")
        return EXIT_OK

    flow_name = args.flow or cfg.flow
    if not flow_name:
        return _fail(f"{args.config}: no flow selected — set [run].flow or pass --flow")

    try:
        nodes = find_nodes(module)
    except RunnerConfigError as e:
        return _fail(str(e))
    fn = nodes.get(flow_name)
    if fn is None:
        available = ", ".join(sorted(nodes)) or "(none found)"
        return _fail(f"no flow {flow_name!r} in module {cfg.module!r}; available: {available}")

    inputs = dict(cfg.inputs)
    # Validate against the decorated function's real signature —
    # functools.wraps exposes it through __wrapped__.
    try:
        call_args, call_kwargs = _bind_flow_inputs(fn, inputs)
    except (TypeError, RunnerConfigError) as e:
        return _fail(f"[inputs] do not match flow {flow_name!r}: {e}")

    try:
        run = execute_flow(fn, *call_args, options=cfg.options, **call_kwargs)
    except Exception as exc:
        traceback.print_exc()
        _report_run(getattr(exc, "run", None), flow_name)
        return EXIT_RUN_ERROR

    _report_run(run, flow_name)
    try:
        shown = json.dumps(jsonable(run.result), default=str)
    except Exception:  # pragma: no cover - jsonable's own fallbacks cover exotic types
        shown = repr(run.result)
    print(f"result: {shown}")
    return EXIT_OK


def _report_run(run: Run | None, flow_name: str) -> None:
    """Print the run's account line: status, duration, log path."""
    if run is None:
        print(f"flow {flow_name}: error")
        return
    line = f"flow {flow_name}: {run.status}"
    if run.duration_ms is not None:
        line += f" ({run.duration_ms} ms)"
    print(line)
    if run.log:
        print(f"log: {run.log}")
