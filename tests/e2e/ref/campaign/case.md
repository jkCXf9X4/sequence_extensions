# Case: `campaign`

One file per committed reference flow. It records what the log bytes cannot:
why the flow exists, what this golden pins, and how it may be updated.

- **Scenario:** `flows.campaign` — four synthetic two-line csv cases
  (`c1`, `c2`, `c3`, `bad`) fan out through `simulate`, whose first attempt
  fails once per case through a marker file, then retries; `evaluate` consumes
  each sim, and `verdict` fans in one aggregate artifact. Fixed clock, fixed
  run id, four cases, all passing.
- **Fault pinned:** the happy-path contract at the library border — retry
  attempts (`attempt` 1 error, 2 ok), node `args`/`result` paths and hashes,
  fan-out/fan-in result identity, and the exact `verdict.json` bytes. A change
  in scheduling, retry policy, argument threading, or aggregation moves it.
- **Why the log is authoritative:** the JSON-lines run log is written by the
  run itself and compared positionally, field by field, by `e2e.oracle` — a
  parser that imports nothing from `sequence_extensions`. The committed
  artifact tree is checked byte for byte as a second, independent witness, so
  neither the engine's reader nor its serializer can validate itself.
- **Pinned fields:** `started`/`start`/`end`/`ended` =
  `1970-01-01T00:00:00+00:00`, `duration_ms` = `0`, `worker` = `fixed`,
  `run_id` = `campaign-fixed` (`oracle.PINNED`, plus the `run_id` check in
  `golden.verify`).
- **Excluded fields:** `seq`, `run_id`, `start`, `end`, `started`, `ended`,
  `duration_ms`, `worker`, `version` (`oracle.EXCLUDED`) — record position,
  identity, wall clock, worker name, and package version are not behavior.
  Adding a field here is a protocol change pinned by
  `test_version_is_excluded_from_comparison_on_purpose`.
- **Comparison:** positional JSON-lines field comparison outside `EXCLUDED`,
  plus a byte-for-byte artifact tree comparison (`verdict.json`,
  `sims/*.json`, `evals/*.json`). `case.md` itself is provenance, excluded
  from the artifact comparison.
- **Volatile fields:** none. Reference mode pins the wall clock; a live timing
  reading is rejected by `oracle.validate_log`, not silently ignored.
- **Update policy:** only with `UPDATE_REF=1` after the behavior change is
  reviewed as intended; refused when `CI` is set; the session guard
  (`e2e.fixture_guard`) fails any verify run that drifts `ref/` or `cases/`.
- **Input:** `tests/e2e/cases/c1.csv`, `c2.csv`, `c3.csv`, `bad.csv` —
  synthetic, two lines (`name,value`); see `tests/e2e/cases/README.md`.
- **Expected:** `ref/campaign.jsonl` and the `ref/campaign/` artifact tree.

## What this case proves

That the whole system path — fan-out, retry, dependency edge, fan-in, artifact
write, log write — reproduces the committed verdict and its recorded evidence.
Delete it and a silent change to the retry policy or the aggregation would go
unreported.

## Update history

| Date | Change | Reason |
|---|---|---|
| 2026-10-28 | Case note added | Per-flow provenance; bytes unchanged |
