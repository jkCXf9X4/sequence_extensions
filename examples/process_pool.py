"""CPU-bound fan-out with ``ProcessGraphPool``.

The same graph API as the thread pool, but node bodies run in worker
processes — the fix when the GIL serializes CPU-bound work.  Nodes and
arguments must be picklable, so the nodes here are module-level functions
and the payload is plain data.

Run::

    python examples/process_pool.py --out /tmp/process-pool
"""

from __future__ import annotations

import argparse
from pathlib import Path

from sequence_extensions.flow import (
    ProcessGraphPool,
    RunLog,
    RunOptions,
    execute_flow,
    gather,
    node,
)


@node
def burn(limit: int) -> int:
    """CPU-bound work; runs in a worker process under ProcessGraphPool."""
    total = 0
    for value in range(limit):
        total += value * value
    return total


@node
def cpu_campaign(sizes: list[int]) -> list[int]:
    """Fan out from the driver process; a process worker cannot submit."""
    return gather([burn.submit(size) for size in sizes])


def main(argv: list[str] | None = None) -> dict:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=Path("examples/_out/process-pool"))
    parser.add_argument("--size", type=int, default=400_000)
    args = parser.parse_args(argv)

    sizes = [args.size] * 4
    with ProcessGraphPool(max_workers=2) as pool:
        run = execute_flow(
            cpu_campaign,
            sizes,
            options=RunOptions(pool=pool, log=args.out / "runs"),
        )

    workers = sorted(
        {record["worker"] for record in RunLog.filter(run.log, record="node", node="burn")}
    )
    print(f"status:  {run.status}")
    print(f"results: {run.result}")
    print(f"workers: {workers}")
    print(f"log:     {run.log}")

    return {"run": run, "result": run.result, "workers": workers, "log": str(run.log)}


if __name__ == "__main__":
    main()
