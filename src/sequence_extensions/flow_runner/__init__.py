"""``flow-runner`` — launch a plan file's run from the command line.

    flow-runner PLAN.json --module MODULE [--flow NAME] [--log DIR]
    flow-runner --module MODULE --list

One ``flow-plan/2`` JSON document carries everything the run needs: the root
callable's bound parameters, every node's parameters and effective policy,
the edges, and the run options.  The module is named on the command line and
imported like any other; the root node is external state, selected with
``--flow`` (or auto-selected when the module defines exactly one node).

``PLAN`` is ``-`` for stdin.  ``--log DIR`` overrides the plan's log
location (the plan itself never stores it).  ``--list`` prints the module's
nodes and exits without reading a plan.

Exit codes: ``0`` the run succeeded; ``1`` the run raised; ``2`` usage or
configuration error (bad plan JSON/schema, missing or unknown flow, an
import-time failure, or a plan that does not fit the flow).

Nodes needing non-JSON inputs (open connections, custom objects) belong in a
small ``main.py`` that calls ``execute_flow`` directly — the runner is a
convenience, not a requirement.  A plan file names a module to import, so
treat it as trusted code.  Process pools are constructed in code; the runner
drives thread-mode runs.

Implementation modules: :mod:`._discovery` (the node scan) and this module
(the argument parser, plan loading, imports, and exit-code mapping).
"""

from __future__ import annotations

import argparse
import importlib
import json
import sys
import traceback
from pathlib import Path

from sequence_extensions.flow import Run, execute_plan, jsonable
from sequence_extensions.flow_runner._discovery import find_nodes, list_nodes

__all__ = ["find_nodes", "main"]

#: Exit codes: 0 ok, 1 run failure, 2 usage/config error.
EXIT_OK = 0
EXIT_RUN_ERROR = 1
EXIT_USAGE = 2

#: The one plan schema this runner accepts.
PLAN_SCHEMA = "flow-plan/2"


# ---------------------------------------------------------------- #
# Entry point
# ---------------------------------------------------------------- #
def _fail(message: str) -> int:
    print(f"flow-runner: {message}", file=sys.stderr)
    return EXIT_USAGE


def _read_plan(source: Path) -> dict:
    """Load and shape-check a plan JSON document (``-`` reads stdin)."""
    if str(source) == "-":
        text = sys.stdin.read()
        where = "stdin"
    else:
        try:
            text = source.read_text(encoding="utf-8")
        except OSError as e:
            raise ValueError(f"cannot read plan file {source}: {e}") from None
        where = str(source)

    try:
        document = json.loads(text)
    except json.JSONDecodeError as e:
        raise ValueError(f"{where}: invalid JSON: {e}") from None

    if not isinstance(document, dict):
        raise ValueError(f"{where}: plan must be a JSON object, got {type(document).__name__}")
    schema = document.get("schema")
    if schema != PLAN_SCHEMA:
        raise ValueError(f"{where}: expected schema {PLAN_SCHEMA!r}, got {schema!r}")
    return document


def main(argv: list[str] | None = None) -> int:
    """Run the flow a plan document describes.  Returns the process exit code."""
    parser = argparse.ArgumentParser(
        prog="flow-runner",
        description="Run a flow from a flow-plan/2 JSON document.",
    )
    parser.add_argument(
        "plan",
        nargs="?",
        type=Path,
        help="path to the plan JSON file ('-' for stdin); not needed with --list",
    )
    parser.add_argument(
        "--module",
        required=True,
        metavar="MODULE",
        help="dotted module name scanned for @node functions",
    )
    parser.add_argument(
        "--flow",
        metavar="NAME",
        help="root node to run (defaults to the module's only node)",
    )
    parser.add_argument(
        "--log",
        type=Path,
        metavar="DIR",
        help="override the plan's log directory",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="list the module's nodes and exit",
    )
    args = parser.parse_args(argv)

    try:
        module = importlib.import_module(args.module)
    except ImportError as e:
        return _fail(f"cannot import module {args.module!r}: {e}")
    except Exception as e:
        return _fail(
            f"module {args.module!r} raised while importing: {type(e).__name__}: {e}"
        )

    if args.list:
        print(f"flows in {args.module}:")
        entries = list_nodes(module)
        for node_name, summary in entries:
            print(f"  {node_name}" + (f"  — {summary}" if summary else ""))
        if not entries:
            print("  (none found)")
        return EXIT_OK

    if args.plan is None:
        return _fail("no plan given — pass PLAN.json (or - for stdin)")

    try:
        document = _read_plan(args.plan)
    except ValueError as e:
        return _fail(str(e))

    try:
        nodes = find_nodes(module)
    except ValueError as e:
        return _fail(str(e))

    if args.flow is not None:
        flow_name = args.flow
        fn = nodes.get(flow_name)
        if fn is None:
            available = ", ".join(sorted(nodes)) or "(none found)"
            return _fail(
                f"no flow {flow_name!r} in module {args.module!r}; available: {available}"
            )
    elif len(nodes) == 1:
        flow_name, fn = next(iter(nodes.items()))
    else:
        available = ", ".join(sorted(nodes)) or "(none found)"
        return _fail(f"no flow selected — pass --flow (available: {available})")

    try:
        run = execute_plan(fn, document, log=args.log)
    except ValueError as exc:
        # A document/config violation raises before anything runs; an
        # executed failure carries the run account (``.run``).
        if getattr(exc, "run", None) is None:
            return _fail(str(exc))
        traceback.print_exc()
        _report_run(exc.run, flow_name)
        return EXIT_RUN_ERROR
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
