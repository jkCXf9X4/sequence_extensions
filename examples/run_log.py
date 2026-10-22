"""Reading a run log: records, filter, summarize, diff — and reference mode.

Two identical runs with ``fixed_clock=True`` write byte-identical JSON-lines
files; ``RunLog.diff`` then proves the runs are semantically equal without
looking at order, wall-clock, worker names, or run identity.  The same file
is read back with ``records``, ``filter``, and ``summarize``.

Run::

    python examples/run_log.py --out /tmp/run-log
"""

from __future__ import annotations

import argparse
from pathlib import Path

from sequence_extensions.flow import RunLog, RunOptions, execute_flow, gather, node


@node
def square(value: int) -> int:
    return value * value


@node
def collect(values: list[int]) -> dict:
    """Fan out, then keep the dict shape around the list of results."""
    futures = [square.submit(value) for value in values]
    return gather({"values": futures, "count": len(values)})


def main(argv: list[str] | None = None) -> dict:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=Path("examples/_out/run-log"))
    args = parser.parse_args(argv)

    values = list(range(6))

    # Reference mode: pinned run id, pinned timing, canonical record order.
    first = execute_flow(
        collect,
        values,
        options=RunOptions(log=args.out / "first", fixed_clock=True, name="log_demo"),
    )
    second = execute_flow(
        collect,
        values,
        options=RunOptions(log=args.out / "second", fixed_clock=True, name="log_demo"),
    )

    first_log = first.log
    second_log = second.log
    byte_identical = first_log.read_bytes() == second_log.read_bytes()
    report = RunLog.diff(first_log, second_log)

    records = RunLog.records(first_log)
    ok_records = RunLog.filter(records, record="node", status="ok")
    squares = RunLog.filter(records, node="square")
    summary = RunLog.summarize(first_log)

    # summary=True keeps long payloads out of the log (counts, not items).
    summary_run = execute_flow(
        collect,
        list(range(20)),
        options=RunOptions(log=args.out / "summary", summary=True, name="summary_demo"),
    )
    summary_record = RunLog.filter(summary_run.log, record="node", node="collect")[0]
    summary_args = summary_record["args"][0]

    # log=None disables the file entirely — useful for tests and embedding.
    quiet = execute_flow(collect, [1, 2], options=RunOptions(log=None, name="quiet"))

    print(f"fixed logs byte-identical: {byte_identical}")
    print(f"diff equal:               {report['equal']}")
    print(f"records:                  {len(records)}")
    print(f"ok node records:          {len(ok_records)}")
    print(f"square records:           {len(squares)}")
    print(f"summary:                  {summary['run_id']} {summary['status']}")
    print(f"summary-mode args:        {summary_args}")
    print(f"quiet log:                {quiet.log}")

    return {
        "identical": byte_identical,
        "diff": report,
        "records": records,
        "ok_records": ok_records,
        "squares": squares,
        "summary": summary,
        "summary_args": summary_args,
        "quiet_log": quiet.log,
    }


if __name__ == "__main__":
    main()
