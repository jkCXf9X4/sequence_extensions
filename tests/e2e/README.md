# tests/e2e — version comparison against a committed reference

Two deterministic mock flows (`flows.py`) and a pytest file
(`test_flows.py`) that runs each flow and requires the run to compare
equal to the committed reference in `ref/`:

- **logs** — `RunLog.diff` (the package's own determinism check):
  identical task attempts, outcomes, inputs, and results.  Record
  order, run identity, wall-clock, worker names — and the
  package-version field — never count as differences.
- **artifacts** — byte-for-byte: the same file set and the same bytes.

`out/` is versioned scratch — one stable subtree per flow, plus the
logs under `out/logs/`.  The run id is pinned per flow, so the log
filename and the id inside every record are constant between runs:
repeated runs leave only timing-field differences in the logs, never
file churn.  `cases/` holds the committed input files whose paths and
hashes end up in the logs.

## What a failure means

Behavior changed between versions.  The diff report pinpoints it: which
task, which inputs, which attempt, which fields.  Intended changes
regenerate the reference and note it in the changelog; unintended ones
are regressions.

## Regenerate the reference

```
UPDATE_REF=1 python -m pytest tests/e2e
```

Run only after a change is decided intended — the reference is the
contract, not the output of the last failing run.
