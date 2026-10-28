# tests/e2e — the system-level golden

Two deterministic mock runs (`flows.py`) against a committed reference in
`ref/`. This is the suite's only system-level golden: the whole path from
`execute_flow` down to the JSON-lines log and the artifacts a node writes.

## The protocol: generation and verification never share an invocation

| phase | how | what it does |
| --- | --- | --- |
| verify | `python -m pytest tests/e2e` | runs the flows, compares against `ref/`; never writes |
| regenerate | `UPDATE_REF=1 python -m pytest tests/e2e` | runs the flows, writes `ref/`, then **skips** |

A regeneration run reports `skipped`, not `passed`. That is deliberate: if
`UPDATE_REF=1` both wrote the reference and compared against it, the invocation
would always be green and would certify nothing. `test_regeneration_writes_without_verifying`
pins this — it fails the build if the regeneration path ever reaches the
comparison. A normal run never writes `ref/`, so a red run cannot move the
goalposts.

## What the golden asserts

Strongest gate first:

1. **Structure of both logs** — `oracle.py`, hand-written and independent of
   `sequence_extensions`: each line parses as JSON, the required keys per record
   kind are present, `seq` is contiguous from 1, `run_start` is first and
   `run_end` last, statuses come from the documented vocabulary, an `ok` attempt
   carries `result`, a failed one carries `error`, a skipped one carries `attempt`
   0 and a reason, and no live timing leaked into the file.
2. **The log comparison** — positional and field by field, excluding exactly the
   fields in `oracle.EXCLUDED`. Reference mode writes records in canonical order,
   so the nth line must be the nth line: this is stricter than an identity-keyed
   diff.
3. **The artifact tree** — byte for byte: the same file set and the same bytes.
4. **`RunLog.diff`** — a second, weaker gate, kept because its report is easier to
   read once the hand-written oracle has failed. It is not the oracle: it shares
   the engine's reader and comparison, so it cannot catch a bug in either.

## What it does not assert

- **No engine correctness.** The flows are mocks; the golden detects change
  relative to itself, not mathematical or specification-conformance truth.
- **No wall-clock behavior.** `fixed_clock` pins `started`/`ended`/`start`/`end`
  to the epoch, `duration_ms` to `0`, the worker name to `fixed`, and the run id
  to `<flow>-fixed`. Timing fields are asserted to be those sentinels, never to
  be plausible readings; performance and concurrency timing are out of scope.
- **No package version.** `version` in `run_start` is metadata; a release bump
  must not redden the golden. `test_version_is_excluded_from_comparison_on_purpose`
  pins the exclusion set, so adding a field to `oracle.EXCLUDED` is a reviewed
  change, and shows the oracle still catches a behavioral field.
- **No order of arrival.** Record order is the canonical order the writer
  imposes, not the order in which nodes finished.

Determinism is itself asserted: `test_the_same_flow_gives_the_same_bytes_twice`
runs the same flow twice in one session (scratch cleaned in between, because the
retry markers live there) and requires identical log bytes and identical artifact
bytes.

The golden is also asserted to be **falsifiable**: flipping one hex digit of a
result hash, or one byte of `verdict.json`, in a *copy* of `ref/` turns the
comparison red. The real reference is never mutated by a test.

Position independence (the same flow at the root and as a child node) is
composition semantics, not a golden claim, so it lives with the other flow tests
in `tests/flow/test_position.py`.

## Scratch output

`out/` is scratch and is git-ignored. Each pytest worker gets its own root,
`tests/e2e/out/<worker>/` (`PYTEST_XDIST_WORKER`, or `main` without xdist), so
two workers never share a run tree. The flows, however, are handed the stable
alias `tests/e2e/out/<flow>` and run from `golden.scratch_view()` — a
per-worker cwd where that alias and `tests/e2e/cases` resolve through symlinks
into the worker's root and the committed inputs. The recorded paths therefore
stay repository-relative and identical for every worker (the golden holds
`tests/e2e/out/<flow>`), while the files on disk are per-worker. Being ignored
keeps `git status` clean, including after a crash in the middle of a run.
`test_scratch_output_is_ignored_and_untracked` guards both properties.
`cases/` holds the committed inputs whose paths and hashes end up in the logs.

Every committed flow directory carries a `case.md` recording what it pins, and
the inputs carry one `cases/README.md` for the set. `e2e.fixture_guard` hashes
`ref/` and `cases/` at session start and fails the session if either drifts
during a verify run; it is skipped when `UPDATE_REF` is set.

## Regenerate the reference

```
UPDATE_REF=1 python -m pytest tests/e2e
```

**Refused in CI.** `save_reference` fails with `refusing to update the e2e
reference in CI` when both `UPDATE_REF` and `CI` are set, before it writes
anything. A CI job must never move the goalposts it reports against; the guard
also skips its hashing under `UPDATE_REF`, so the only writer of `ref/` is a
human-run regeneration.

Run it only after a change is **decided intended**, then:

1. review the diff under `tests/e2e/ref/` — it is the behavior change, written
   down: which node, which inputs, which attempt, which artifact bytes;
2. re-run `python -m pytest tests/e2e` without `UPDATE_REF` to verify against
   what you just committed;
3. keep the regenerated `ref/` in the same commit as the change that caused it.

Regeneration is a reviewed change because the reference *is* the contract. The
generated files are what a future red run is measured against; regenerating to
make a failing run green silently redefines correct behavior, and nothing else
in the suite would notice.
