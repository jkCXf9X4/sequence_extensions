"""Retries, backoff, timeouts, and the failure account.

Six small runs, each isolating one policy:

1. ``retries=2`` retries a flaky node until it succeeds;
2. a node with no decorator policy inherits ``RunOptions.node_defaults``;
3. ``timeout=`` turns a hung attempt into ``NodeTimeoutError``;
4. a failed dependency skips its dependent, and ``execute_flow`` raises with
   the failed run attached as ``.run``;
5. ``RunOptions(timeout=...)`` bounds the whole run;
6. ``RunOptions(retries=...)`` retries the whole run — one log per attempt.

Run::

    python examples/policies.py --out /tmp/policies
"""

from __future__ import annotations

import argparse
import time
from pathlib import Path

from sequence_extensions.flow import (
    NodePolicy,
    NodeTimeoutError,
    RunLog,
    RunOptions,
    execute_flow,
    gather,
    node,
)


def _count(counter: Path) -> int:
    """Increment and return an attempt counter kept in a file."""
    attempt = int(counter.read_text(encoding="utf-8")) + 1
    counter.write_text(str(attempt), encoding="utf-8")
    return attempt


@node(retries=2, retry_delay_seconds=0.01)
def flaky(counter: Path) -> int:
    """Fail twice, then succeed on the third attempt."""
    attempt = _count(counter)
    if attempt < 3:
        raise RuntimeError(f"transient failure {attempt}")
    return attempt


@node
def defaulted(counter: Path) -> int:
    """No decorator policy: the run's ``node_defaults`` supplies it."""
    attempt = _count(counter)
    if attempt < 2:
        raise RuntimeError("first attempt fails")
    return attempt


@node(timeout=0.05)
def too_slow() -> str:
    """Longer than the node timeout; the attempt is abandoned."""
    time.sleep(0.3)
    return "never returned"


@node
def explode() -> int:
    raise ValueError("deliberate failure")


@node
def consume(value: int) -> int:
    """Dependent on ``explode``; it must be skipped, not run."""
    return value + 1


@node
def retry_root(counter: Path) -> int:
    return flaky.submit(counter)


@node
def defaults_root(counter: Path) -> int:
    return defaulted.submit(counter)


@node
def timeout_root() -> str:
    return too_slow.submit()


@node
def failing_root() -> list:
    bad = explode.submit()
    return gather([consume.submit(bad)])


@node
def slow_root() -> str:
    """Longer than the run-level timeout."""
    time.sleep(0.3)
    return "too late"


@node
def run_flaky(counter: Path) -> int:
    """Fail the first whole-run attempt; RunOptions(retries=1) retries it."""
    attempt = _count(counter)
    if attempt < 2:
        raise RuntimeError("run attempt fails")
    return attempt


def _statuses(log, node_name: str) -> list[str]:
    records = RunLog.filter(log, record="node", node=node_name)
    return [record["status"] for record in records]


def main(argv: list[str] | None = None) -> dict:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=Path("examples/_out/policies"))
    args = parser.parse_args(argv)
    out = args.out
    out.mkdir(parents=True, exist_ok=True)

    # 1. Explicit retry policy: retries=2 means up to three attempts.
    retry_counter = out / "retry-counter"
    retry_counter.write_text("0", encoding="utf-8")
    retry_run = execute_flow(retry_root, retry_counter, options=RunOptions(log=out / "retry"))

    # 2. Run-level defaults: the decorator left retries/timeout unset.
    defaults_counter = out / "defaults-counter"
    defaults_counter.write_text("0", encoding="utf-8")
    defaults_run = execute_flow(
        defaults_root,
        defaults_counter,
        options=RunOptions(
            log=out / "defaults",
            node_defaults=NodePolicy(retries=1, retry_delay_seconds=0.01),
        ),
    )

    # 3. Node timeout: the attempt is abandoned and recorded as "timeout".
    try:
        execute_flow(timeout_root, options=RunOptions(log=out / "timeout"))
    except NodeTimeoutError as exc:
        timeout_result = {
            "error": type(exc).__name__,
            "node": exc.node,
            "timeout": exc.timeout,
            "statuses": _statuses(exc.run.log, "too_slow"),
        }
    else:  # pragma: no cover - the example would be broken
        raise AssertionError("too_slow should have timed out")

    # 4. Failure: the dependent is recorded skipped and the run is on .run.
    try:
        execute_flow(failing_root, options=RunOptions(log=out / "failure"))
    except ValueError as exc:
        skipped = RunLog.filter(exc.run.log, record="node", status="skipped")
        failure_result = {
            "error": str(exc),
            "run_status": exc.run.status,
            "skip_reason": skipped[0]["reason"] if skipped else None,
        }
    else:  # pragma: no cover
        raise AssertionError("failing_root should have failed")

    # 5. Run-level timeout: the whole attempt is bounded, run_end says so.
    try:
        execute_flow(
            slow_root,
            options=RunOptions(log=out / "run-timeout", timeout=0.05),
        )
    except NodeTimeoutError as exc:
        run_timeout_result = {
            "error": type(exc).__name__,
            "run_status": exc.run.status,
            "run_end_status": RunLog.records(exc.run.log)[-1]["status"],
        }
    else:  # pragma: no cover
        raise AssertionError("slow_root should have hit the run timeout")

    # 6. Run-level retries: one log file per attempt, each with its own id.
    run_retry_counter = out / "run-retry-counter"
    run_retry_counter.write_text("0", encoding="utf-8")
    run_retry_run = execute_flow(
        run_flaky,
        run_retry_counter,
        options=RunOptions(log=out / "run-retry", retries=1, retry_delay_seconds=0.01),
    )
    run_retry_logs = sorted((out / "run-retry").glob("*.jsonl"))

    print(f"retries:     {_statuses(retry_run.log, 'flaky')} -> {retry_run.result}")
    print(f"defaults:    {_statuses(defaults_run.log, 'defaulted')} -> {defaults_run.result}")
    print(f"node timeout:{timeout_result}")
    print(f"failure:     {failure_result}")
    print(f"run timeout: {run_timeout_result}")
    print(f"run retries: {run_retry_run.result} ({len(run_retry_logs)} logs)")

    return {
        "retry": {"result": retry_run.result, "statuses": _statuses(retry_run.log, "flaky")},
        "defaults": {
            "result": defaults_run.result,
            "statuses": _statuses(defaults_run.log, "defaulted"),
        },
        "timeout": timeout_result,
        "failure": failure_result,
        "run_timeout": run_timeout_result,
        "run_retry": {"result": run_retry_run.result, "logs": len(run_retry_logs)},
    }


if __name__ == "__main__":
    main()
