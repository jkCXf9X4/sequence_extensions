"""
Command-line interface: run a workflow XML file from the shell.

``sequence-extensions`` (the ``console_scripts`` entry point) and
``python -m sequence_extensions`` both call :func:`main`.  The CLI is the
unattended entry point for campaigns: the library itself emits no logs, so
the CLI configures logging (root logger, timestamped format) and emits
campaign-level events around the run — a start line (workflow path + active
options), a completion line (record count + duration + run id), and a
failure line (the error).  ``--history-out`` writes the run's
:meth:`RunHistory.to_json` document and ``--artifacts-dir`` constructs the
run's :class:`ArtifactStore`, so a CLI run leaves durable evidence behind.

Every run option maps one-to-one onto a :func:`run_workflow` keyword
(``params_mode``, ``max_workers``, ``adaptation_bound``, ``action_timeout``,
``fail_fast``, ``dry_run``).  The CLI runs against its OWN
:class:`FunctionRegistry` with the built-in library registered — it never
mutates the process-global ``DEFAULT_REGISTRY``, so an embedding
application's registrations are untouched and the CLI is self-contained.

Exit codes: ``0`` on success, ``1`` on a failed run or an unreadable
workflow file, ``2`` on a usage error (argparse's own code).
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path

from sequence_extensions import ArtifactStore, FunctionRegistry, run_workflow
from sequence_extensions.workflow.history import RunHistory
from sequence_extensions.workflow.library import register_library

_LOG_FORMAT = "%(asctime)s %(levelname)-8s %(name)s: %(message)s"
_RESULT_REPR_LIMIT = 200


def _configure_logging(args: argparse.Namespace) -> None:
    """
    Configure the root logger for the CLI run.

    Default level is INFO (campaign events are visible by default — an
    unattended run has a voice); ``-q`` lowers it to WARNING, ``-v`` raises
    it to DEBUG.  A timestamped handler is added only when the root logger
    has none, so an embedding application's logging setup is not clobbered
    (the level is still applied to the root).
    """
    if args.verbose:
        level = logging.DEBUG
    elif args.quiet:
        level = logging.WARNING
    else:
        level = logging.INFO
    root = logging.getLogger()
    root.setLevel(level)
    if not root.handlers:
        handler = logging.StreamHandler(sys.stderr)
        handler.setFormatter(logging.Formatter(_LOG_FORMAT))
        root.addHandler(handler)


def _describe_options(options: dict) -> str:
    """A compact 'k=v' list of the non-default run options (for the start line)."""
    active = {k: v for k, v in options.items() if v is not None and v is not False}
    if not active:
        return "defaults"
    return ", ".join(f"{k}={v!r}" for k, v in active.items())


def build_parser() -> argparse.ArgumentParser:
    """The CLI's argument parser (exposed for tests and ``--help``)."""
    parser = argparse.ArgumentParser(
        prog="sequence-extensions",
        description=(
            "Run a workflow XML file with the sequence_extensions engine. "
            "Exit codes: 0 success, 1 failed run or unreadable workflow file, "
            "2 usage error."
        ),
    )
    parser.add_argument("workflow", help="path to the workflow XML file")
    parser.add_argument(
        "-v",
        "--verbose",
        action="count",
        default=0,
        help="log at DEBUG (default: INFO; -q: WARNING)",
    )
    parser.add_argument(
        "-q",
        "--quiet",
        action="store_true",
        help="log only warnings and errors",
    )
    parser.add_argument(
        "--params-mode",
        choices=("full", "summary"),
        default=None,
        help="recorded-params shape (default: full)",
    )
    parser.add_argument(
        "--max-workers",
        type=int,
        default=None,
        help="GraphPool worker count (default: 16)",
    )
    parser.add_argument(
        "--adaptation-bound",
        type=int,
        default=None,
        help="dynamic-node bound (default: the engine's ADAPTATION_BOUND)",
    )
    parser.add_argument(
        "--action-timeout",
        type=float,
        default=None,
        metavar="SECONDS",
        help="per-action wall-clock budget in seconds (default: no timeout)",
    )
    parser.add_argument(
        "--fail-fast",
        action="store_true",
        help="stop a parallel group at the first failure instead of draining",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="plan mode: parse and validate, execute nothing",
    )
    parser.add_argument(
        "--history-out",
        metavar="FILE",
        default=None,
        help="write the run's RunHistory.to_json() document to FILE",
    )
    parser.add_argument(
        "--artifacts-dir",
        metavar="DIR",
        default=None,
        help="run an ArtifactStore rooted at DIR (durable per-action evidence)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """
    Run the workflow named by ``argv[0]`` (or ``sys.argv[1:]`` when ``argv``
    is ``None``) and return the process exit code.

    Campaign-level events are logged around the run: start (workflow path +
    active options), completion (record count + duration + run id), failure
    (the error).  ``--history-out`` is written on BOTH paths — a failed run
    still leaves the partial history as evidence.
    """
    args = build_parser().parse_args(argv)
    _configure_logging(args)
    log = logging.getLogger("sequence_extensions.cli")

    # The CLI runs against its own registry with the built-in library
    # registered: self-contained, and it never mutates the process-global
    # DEFAULT_REGISTRY (an embedding application's registrations are
    # untouched).
    registry = FunctionRegistry()
    register_library(registry)

    xml_path = Path(args.workflow)
    try:
        xml_source = xml_path.read_text(encoding="utf-8")
    except OSError as exc:
        log.error("cannot read workflow file %s: %s", xml_path, exc)
        return 1

    options = {
        "params_mode": args.params_mode,
        "max_workers": args.max_workers,
        "adaptation_bound": args.adaptation_bound,
        "action_timeout": args.action_timeout,
        "fail_fast": args.fail_fast,
        "dry_run": args.dry_run,
    }
    log.info("starting workflow %s (options: %s)", xml_path, _describe_options(options))

    history = RunHistory()
    artifacts = (
        ArtifactStore(args.artifacts_dir, history=history)
        if args.artifacts_dir is not None
        else None
    )

    started = time.monotonic()
    try:
        result = run_workflow(
            xml_source,
            registry=registry,
            history=history,
            artifacts=artifacts,
            params_mode=args.params_mode or "full",
            max_workers=args.max_workers,
            adaptation_bound=args.adaptation_bound,
            action_timeout=args.action_timeout,
            fail_fast=args.fail_fast,
            dry_run=args.dry_run,
        )
    except Exception as exc:
        log.error(
            "workflow %s failed after %.3fs: %s: %s",
            xml_path,
            time.monotonic() - started,
            type(exc).__name__,
            exc,
        )
        result = None
        failed = True
    else:
        failed = False

    duration = time.monotonic() - started

    if args.history_out is not None:
        out = Path(args.history_out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(history.to_json() + "\n", encoding="utf-8")
        log.info("history written to %s", out)

    if failed:
        return 1

    log.info(
        "workflow %s completed in %.3fs: %d action record(s), run_id=%s",
        xml_path,
        duration,
        len(history),
        history.run_id,
    )
    if not args.dry_run:
        result_repr = repr(result)
        if len(result_repr) > _RESULT_REPR_LIMIT:
            result_repr = result_repr[:_RESULT_REPR_LIMIT] + "..."
        log.info("final result: %s", result_repr)
    if artifacts is not None:
        log.info("artifacts written to %s", artifacts.root)
    return 0
