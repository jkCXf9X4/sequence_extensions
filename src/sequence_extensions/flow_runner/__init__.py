"""``flow-runner`` — launch a configured flow from the command line.

    flow-runner config.toml
    python -m sequence_extensions.flow_runner config.toml

One TOML file drives everything: which module to import, which flow to
run, what to pass it, and the engine defaults the run resolves::

    [run]
    module = "mypackage.flows"   # module scanned for @flow functions
    flow = "campaign"            # flow to run (or --flow NAME)

    [inputs]                     # keyword arguments for the flow
    items = [1, 2, 3]

    [flow]                       # engine tuning, resolved per call
    max_workers = 8

The config is loaded and validated first; the active configuration is
installed *before* the target module is imported, so module-level pools
constructed without ``max_workers`` see it too.  Flows are discovered by
scanning the module for the ``__flow__`` marker ``@flow`` stamps on its
wrapper — no registry, no registration call.

Exit codes: ``0`` the run succeeded; ``1`` the flow raised; ``2`` usage
or configuration error (bad file, unknown key, missing selection,
inputs that do not match the flow's signature).

Flows needing non-TOML inputs (open connections, custom objects)
belong in a small ``main.py`` that calls them directly — the runner is
a convenience, not a requirement.  A config file names a module to
import, so treat it as trusted code.
"""

from __future__ import annotations

import argparse
import importlib
import inspect
import json
import sys
import traceback
from collections.abc import Callable
from pathlib import Path

from sequence_extensions.config import Config, ConfigError, configure
from sequence_extensions.flow.runlog import jsonable

__all__ = ["find_flows", "list_flows", "main"]

#: Exit codes: 0 ok, 1 flow failure, 2 usage/config error.
EXIT_OK = 0
EXIT_FLOW_ERROR = 1
EXIT_USAGE = 2


def find_flows(module) -> dict[str, Callable]:
    """Every ``@flow``-decorated callable in ``module``, keyed by flow name.

    Scans module attributes for the ``__flow__`` marker the decorator
    stamps; duplicate names for different objects are an error (the
    runner could only guess which to call).
    """
    flows: dict[str, Callable] = {}
    for attr in dir(module):
        obj = getattr(module, attr)
        flow_name = getattr(obj, "__flow__", None)
        if isinstance(flow_name, str):
            existing = flows.get(flow_name)
            if existing is not None and existing is not obj:
                raise ConfigError(
                    f"flow name {flow_name!r} is defined twice in module {module.__name__!r}"
                )
            flows[flow_name] = obj
    return dict(sorted(flows.items()))


def list_flows(module) -> list[tuple[str, str]]:
    """One ``(flow_name, first docstring line)`` pair per flow in ``module``."""
    entries = []
    for flow_name, fn in find_flows(module).items():
        doc = (inspect.getdoc(fn) or "").strip()
        entries.append((flow_name, doc.splitlines()[0] if doc else ""))
    return entries


def _fail(message: str) -> int:
    print(f"flow-runner: {message}", file=sys.stderr)
    return EXIT_USAGE


def main(argv: list[str] | None = None) -> int:
    """Run the flow a TOML config selects.  Returns the process exit code."""
    parser = argparse.ArgumentParser(
        prog="flow-runner",
        description="Run a flow selected, parameterized, and configured by a TOML file.",
    )
    parser.add_argument("config", type=Path, help="path to the TOML config file")
    parser.add_argument("--flow", metavar="NAME", help="override the config's [run].flow")
    parser.add_argument(
        "--list",
        action="store_true",
        help="list the flows in the configured module and exit",
    )
    args = parser.parse_args(argv)

    try:
        cfg = Config.from_toml(args.config)
    except ConfigError as e:
        return _fail(str(e))

    if not cfg.run.module:
        return _fail(f"{args.config}: no module configured — set [run].module")

    # Install the engine defaults *before* importing the target module,
    # so module-level side effects (pool construction) resolve from it.
    configure(cfg)

    try:
        module = importlib.import_module(cfg.run.module)
    except ImportError as e:
        return _fail(f"cannot import module {cfg.run.module!r}: {e}")

    if args.list:
        print(f"flows in {cfg.run.module}:")
        entries = list_flows(module)
        for flow_name, summary in entries:
            print(f"  {flow_name}" + (f"  — {summary}" if summary else ""))
        if not entries:
            print("  (none found)")
        return EXIT_OK

    flow_name = args.flow or cfg.run.flow
    if not flow_name:
        return _fail(f"{args.config}: no flow selected — set [run].flow or pass --flow")

    try:
        flows = find_flows(module)
    except ConfigError as e:
        return _fail(str(e))
    fn = flows.get(flow_name)
    if fn is None:
        available = ", ".join(sorted(flows)) or "(none found)"
        return _fail(f"no flow {flow_name!r} in module {cfg.run.module!r}; available: {available}")

    inputs = dict(cfg.inputs)
    # Validate against the decorated function's real signature —
    # functools.wraps exposes it through __wrapped__.
    target = getattr(fn, "__wrapped__", fn)
    try:
        inspect.signature(target).bind(**inputs)
    except TypeError as e:
        return _fail(f"[inputs] do not match flow {flow_name!r}: {e}")

    try:
        result = fn(**inputs)
    except Exception:
        traceback.print_exc()
        _report_last_run(fn, flow_name)
        return EXIT_FLOW_ERROR

    _report_last_run(fn, flow_name)
    try:
        shown = json.dumps(jsonable(result), default=str)
    except Exception:  # pragma: no cover - jsonable's own fallbacks cover exotic types
        shown = repr(result)
    print(f"result: {shown}")
    return EXIT_OK


def _report_last_run(fn: Callable, flow_name: str) -> None:
    """Print the run's account line: status, duration, log path."""
    last = getattr(fn, "last_run", None)
    if not isinstance(last, dict):
        return
    line = f"flow {flow_name}: {last.get('status', 'unknown')}"
    if last.get("duration_ms") is not None:
        line += f" ({last['duration_ms']} ms)"
    print(line)
    if last.get("log"):
        print(f"log: {last['log']}")
