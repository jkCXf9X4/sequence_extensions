# Case: `failing_campaign`

One file per committed reference flow. It records what the log bytes cannot:
why the flow exists, what this golden pins, and how it may be updated.

- **Scenario:** `flows.failing_campaign` — the same case set fans out through
  `validate`; `bad.csv` carries a negative value and fails on every attempt,
  so its dependent `transform` work is skipped and the run ends with
  `status: "error"`. Fixed clock, fixed run id.
- **Fault pinned:** the failure path — the error `type`/`message` for the
  negative case, `attempt` bookkeeping on a retried failure, `skipped` records
  with attempt `0` and a reason, `run_end.failed_nodes`, and the absence of
  `transformed/` output for the failed case. A regression that turns a failure
  green, or loses the skip/attempt accounting, reddens it.
- **Why the log is authoritative:** the JSON-lines run log is written by the
  run itself and compared positionally, field by field, by `e2e.oracle` — a
  parser that imports nothing from `sequence_extensions`. The committed
  artifact tree (`ref/failing_campaign/transformed/`) is checked byte for byte
  as a second, independent witness.
- **Pinned fields:** `started`/`start`/`end`/`ended` =
  `1970-01-01T00:00:00+00:00`, `duration_ms` = `0`, `worker` = `fixed`,
  `run_id` = `failing_campaign-fixed` (`oracle.PINNED`, plus the `run_id` check
  in `golden.verify`).
- **Excluded fields:** `seq`, `run_id`, `start`, `end`, `started`, `ended`,
  `duration_ms`, `worker`, `version` (`oracle.EXCLUDED`) — record position,
  identity, wall clock, worker name, and package version are not behavior.
  Adding a field here is a protocol change pinned by
  `test_version_is_excluded_from_comparison_on_purpose`.
- **Comparison:** positional JSON-lines field comparison outside `EXCLUDED`,
  plus a byte-for-byte artifact tree comparison. `case.md` itself is
  provenance, excluded from the artifact comparison.
- **Volatile fields:** none. Reference mode pins the wall clock; a live timing
  reading is rejected by `oracle.validate_log`, not silently ignored.
- **Update policy:** only with `UPDATE_REF=1` after the behavior change is
  reviewed as intended; refused when `CI` is set; the session guard
  (`e2e.fixture_guard`) fails any verify run that drifts `ref/` or `cases/`.
- **Input:** `tests/e2e/cases/c1.csv`, `c2.csv`, `c3.csv`, `bad.csv` —
  synthetic, two lines (`name,value`); `bad.csv` is the negative value.
- **Expected:** `ref/failing_campaign.jsonl` and the
  `ref/failing_campaign/transformed/` artifact tree.

## What this case proves

That a failing run is recorded as a failure, with its error, attempts, skips,
and missing dependents, rather than collapsing into silence. Delete it and a
regression that reports failure as success — or drops skipped work from the
log — would go unreported.

## Update history

| Date | Change | Reason |
|---|---|---|
| 2026-10-28 | Case note added | Per-flow provenance; bytes unchanged |
