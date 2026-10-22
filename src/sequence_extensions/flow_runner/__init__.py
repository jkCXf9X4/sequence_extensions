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

Implementation modules: :mod:`._config` (strict TOML contract),
:mod:`._discovery` (node scan and input binding), and this module (the
argument parser, imports, and exit-code mapping).
"""

from __future__ import annotations

import argparse
import importlib
import json
import sys
import traceback
from pathlib import Path

from sequence_extensions.flow import Run, execute_flow, jsonable
from sequence_extensions.flow_runner._config import RunnerConfig, RunnerConfigError
from sequence_extensions.flow_runner._discovery import (
    _bind_flow_inputs,
    find_nodes,
    list_nodes,
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


# ---------------------------------------------------------------- #
# Entry point
# ---------------------------------------------------------------- #
def _fail(message: str) -> int:
    print(f"flow-runner: {message}", file=sys.stderr)
    return EXIT_USAGE


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
        return _fail(f"module {cfg.module!r} raised while importing: {type(e).__name__}: {e}")

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
