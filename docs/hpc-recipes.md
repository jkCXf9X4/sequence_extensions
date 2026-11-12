# Larger workflows — shell, CI, and embedding

Two ways to drive the engine from outside its own code — a shell or pipeline on
the CLI, or an embedding application on the library. For the subprocess-and-poll
simulator recipe behind these pipelines, see [docs/API.md](API.md).

## From a shell or pipeline

`flow-runner` fits make, CI, cron, and batch scripts: one command, no driver script per run, and the outcome lands in the exit code.

```make
# Makefile — one target per plan
campaign:
	flow-runner plans/nightly.json --module mypackage.flows --flow campaign

report:
	flow-runner plans/report.json --module mypackage.flows --flow report
```

```yaml
# .github/workflows/campaign.yml — run, gate on the exit code, keep the log
- run: pip install .
- run: flow-runner plans/ci.json --module mypackage.flows --flow campaign --log artifacts/runs
- uses: actions/upload-artifact@v4
  if: always()                    # archive the log even when the run fails
  with:
    name: run-log
    path: artifacts/runs/
```

The pipeline picks the plan file, so one plan per environment keeps runs apart:

```
plans/
├── ci.json        # small pools, log into artifacts/
├── nightly.json   # more retries, longer timeouts
└── report.json    # other options and inputs
```

- **Branch on the exit code**: `0` success, `1` the run raised, `2` usage or config error — cron, CI, and SLURM see the same codes.
- **Fail before the first node**: a bad plan (invalid JSON, wrong schema, a plan that does not fit the module) fails with exit 2; nothing has run yet.
- **The log is the artifact**: `--log DIR` puts the JSON-lines file where the pipeline collects it; the account line (status, duration, log path) names it.
- **Look before you run**: `--list` shows the nodes in the module with their docstrings; `--flow NAME` selects the root.
- **Varying inputs per invocation** means one plan per variant — values come from the document, there is no `--set` flag. Edit the plan, re-export, or run it with a different file.
- **Flow selection stays external**: the same plan can run a module's root through `--flow`, because the document does not store it.
- **Store logs as golden files**: `fixed_clock: true` in the plan's `options` makes an identical run produce a byte-identical log (pinned run id, pinned timing, canonical record and nested-key order, strict JSON) — commit it, and re-running the pipeline leaves git clean. Fixed runs are exclusive, so generate reference files sequentially.

## Embedded in an application

The engine is a library: no service to run, no threads started at import, no dependencies beyond Python. Call `execute_flow` where the run belongs; the returned `Run` carries the verdict.

```python
# app.py
from sequence_extensions.flow import RunOptions, execute_flow

from mypackage.flows import campaign

run = execute_flow(campaign, cases_dir="cases", options=RunOptions(log="runs"))
if run.status != "ok":
    raise RuntimeError(f"campaign failed, see {run.log}")
archive(run.log)  # keep the JSONL beside app data
```

- **No global state, no import-order constraint**: options travel with the call; two runs can use different pools/logs/summaries in the same process.
- **Scoped by construction**: per-tenant or per-request settings are just different `RunOptions` values — there is no `configure()` to leak into the next caller.
- **Quiet when unwanted**: `log=None` disables run logging — tests and short-lived jobs keep the disk clean.
- **Determinism holds**: option values never enter run-log records, so identical code and inputs still diff identical.
- **Failures carry the account**: `execute_flow` raises with `.run` attached, so a host can log the status, duration, and log path while still propagating the exception.
- Nodes needing open connections or custom objects are called directly like this; the runner is the convenience for JSON-shaped inputs.
