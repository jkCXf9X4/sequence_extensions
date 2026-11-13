# sequence_extensions

**Version:** 3.0.1 · **Python:** >=3.11

Higher-order function extensions for Python lists, dicts, and generators, plus a
mini flow engine on dependency-graph futures: deterministic parallel campaigns,
local or at HPC — retries, timeouts, and a JSON-lines run log that is the
executed truth of every run.

The package is organized into three subpackages plus the CLI:

```
sequence_extensions/
├── ext/           # functional helpers for built-in sequences
├── graph/         # the execution substrate (GraphFuture / GraphPool)
├── flow/          # the mini flow engine (node / execute_flow / run log)
└── flow_runner/   # the flow-runner CLI
```

- `ext.list_ext` — an extended `list` class with functional helpers (`map`, `filter`, `reduce`, `window`, ...)
- `ext.dict_ext` — an extended `dict` class with functional helpers (`map`, `filter`, `reduce`, ...)
- `ext.gen_ext` — static helpers for generators (`to_list`, `recursive_gen`)
- `graph.graph_future` — dependency-graph futures (`GraphFuture`, `GraphPool`)
- `flow` — the flow engine: `@node` (retry, backoff, timeout policy, `.submit()`) and `execute_flow` (run identity, pool, audit log)
- `flow_runner` — the `flow-runner` command: run a `flow-plan/2` JSON plan against a module

`ext` and `graph` names are re-exported from the package root; `flow` is imported
as its own package (`from sequence_extensions.flow import node, execute_flow`).
See [docs/API.md](docs/API.md) for the full API reference.

## Contents

- [Installation](#installation)
- [Quickstart](#quickstart)
- [flow-runner](#flow-runner)
- [Examples](#examples)
- [Documentation](#documentation)
- [Development](#development)
- [License](#license)

## Installation

Requires **Python >= 3.11**.

```
pip install sequence-extensions-flow
```

From source:

```
pip install .
```

The PyPI name `sequence-extensions` is held by an unrelated, older project
(0.1.4) that does not contain the flow engine. This project publishes as
`sequence-extensions-flow`; the import package is still
`sequence_extensions`.

## Quickstart

A node is a function with retry/backoff/timeout policy; `execute_flow` opens a
run. Plain calls are sequential, `.submit()` is concurrent, and futures passed
as arguments are dependency edges.

```python
from sequence_extensions.flow import RunOptions, execute_flow, gather, node


@node(retries=2, retry_delay_seconds=0.1, timeout=60.0)
def simulate(case: int) -> dict:
    return {"case": case, "score": case * 2}


@node
def campaign(cases: list[int]) -> list:
    sims = [simulate.submit(c) for c in cases]  # .submit(): concurrent
    return gather(sims)  # one future, awaited by the node


run = execute_flow(campaign, [1, 2, 3], options=RunOptions(max_workers=8, log="runs"))
print(run.status, run.result, run.log)
```

Semantics, run options, and the plan document are in
[docs/flow-reference.md](docs/flow-reference.md); per-method API detail is in
[docs/API.md](docs/API.md).

## flow-runner

The `flow-runner` command runs a `flow-plan/2` JSON document against a workflow
module. The module is named on the command line; the plan carries the root
inputs, every node's parameters and effective policy, the edges, and the run
options.

```
flow-runner PLAN.json --module MODULE [--flow NAME] [--log DIR]
flow-runner --module MODULE --list
```

```
$ flow-runner plan.json --module mypackage.flows --flow campaign
flow campaign: ok (1843 ms)
log: runs/campaign-20261016T110258-b0e4a12e.jsonl
result: {"count": 6, "mean_score": 0.71, "passed": 6, "all_passed": true}

$ flow-runner --module mypackage.flows --list   # nodes in the module, with docstrings
$ flow-runner - --module mypackage.flows --flow report < plan.json   # plan from stdin
```

`--flow` selects the root; when the module defines exactly one node it is used
without a choice. Flow selection is never stored in the plan. `--log DIR`
overrides the plan's log location, which is also not stored. Same entry point as
a module: `python -m sequence_extensions.flow_runner plan.json --module
mypackage.flows`. Exit codes: `0` the run succeeded, `1` the run raised, `2`
usage or config error (bad plan JSON or schema, missing or unknown flow, import
failure, plan that does not fit the flow) — cron/CI/SLURM friendly. Process
pools are constructed in code, and the runner drives thread-mode runs. A plan
names a module to import, so treat it as trusted code.

For Make, CI, and application-embedding recipes, see
[docs/hpc-recipes.md](docs/hpc-recipes.md).

## Examples

[`examples/`](examples/) is a hands-on tour of the library: one small,
self-contained program per aspect, plus a plan-file `flow-runner` setup.
They are part of the test suite (`tests/usage_examples/`), so they cannot
drift from the code.

| Example | What it shows |
| --- | --- |
| [`examples/sequences.py`](examples/sequences.py) | `list_ext`, `dict_ext`, `KeyValueTuple`, `gen_ext` |
| [`examples/graph_futures.py`](examples/graph_futures.py) | `GraphFuture` / `GraphPool`: DAGs, chaining, errors, timeouts |
| [`examples/campaign.py`](examples/campaign.py) | `@node`, `.submit()`, dependency edges, `gather`, retries, run log |
| [`examples/policies.py`](examples/policies.py) | retries/backoff, `node_defaults`, node/run timeouts, skipped dependencies |
| [`examples/run_log.py`](examples/run_log.py) | `RunLog.records` / `filter` / `summarize` / `diff`, reference mode |
| [`examples/process_pool.py`](examples/process_pool.py) | `ProcessGraphPool` for CPU-bound fan-out |
| [`examples/flow_runner/`](examples/flow_runner) | the plan-file `flow-runner` command |

```bash
python examples/campaign.py --out /tmp/campaign
python examples/policies.py --out /tmp/policies
cd examples/flow_runner && flow-runner plan.json --module flows --flow campaign
```

The file-writing scripts take `--out` (default `examples/_out/<name>`,
gitignored) and print the result they check. See
[examples/README.md](examples/README.md) for the walkthrough and the expected
output of each example.

## Documentation

- [docs/API.md](docs/API.md) — canonical per-method API reference.
- [docs/flow-reference.md](docs/flow-reference.md) — sequence helper tours, graph futures, flow semantics, run options, and the plan document.
- [docs/hpc-recipes.md](docs/hpc-recipes.md) — Make, CI, and application-embedding recipes.
- [CONTRIBUTING.md](CONTRIBUTING.md) — development setup, tests, lint, and the pull-request process.

## Development

Editable install with dev extras:

```bash
pip install -e ".[dev]"
```

Run the suite with `pytest` (the 90% coverage floor is enforced) and lint with
`ruff check .`. See [CONTRIBUTING.md](CONTRIBUTING.md) for the full test,
coverage, lint, and format commands.

## License

MIT
