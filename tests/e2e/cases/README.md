# Case set: `tests/e2e/cases`

One provenance file for the whole case set, not one per csv: the four inputs
are a single set consumed by both reference flows, and they carry no per-file
fixture semantics beyond a two-line `name,value` csv. `bad.csv` has the same
shape as the rest — its difference is one negative value, which is exactly the
fault `failing_campaign` pins. Splitting it out would duplicate the same
`case.md` four times with nothing file-specific to say.

- **Scenario:** four synthetic inputs (`c1`, `c2`, `c3` positive, `bad`
  negative) consumed by `campaign` and `failing_campaign` as the fan-out
  source.
- **Fault pinned:** the input contract — sorted `*.csv` discovery, two-line
  parse (`name,value`), and the specific file names that appear in the run
  log. Renaming or reordering a case changes the golden.
- **Why the log is authoritative:** case paths are recorded in the run log as
  repository-relative strings and hashed where a file is an argument; the
  committed `ref/*.jsonl` files pin both. The csv bytes themselves are not
  compared by the oracle, so the log is the evidence that these inputs were
  the ones consumed.
- **Pinned fields:** the case path (`tests/e2e/cases`), the recorded per-case
  paths and sha256 values in `args`/`result`, and the case names in artifacts.
- **Excluded fields:** the same `oracle.EXCLUDED` set as the flows — record
  position, identity, wall clock, worker name, and version. No case field is
  excluded.
- **Comparison:** paths and hashes through the log comparison; csv bytes only
  indirectly, through the artifacts and hashes they produce.
- **Volatile fields:** none. The csvs are static text with no timestamps.
- **Update policy:** a new or changed case is a reviewed change committed with
  the regenerated `ref/` (`UPDATE_REF=1`, refused in CI); the session guard
  fails any verify run that drifts `cases/`.
- **Input:** `c1.csv`, `c2.csv`, `c3.csv`, `bad.csv` — synthetic, two lines
  each (`name,value`).
- **Expected:** consumed by both flows; no per-case expected file — the golden
  is `tests/e2e/ref/`.

## What this case proves

That both flows run against exactly these inputs, discovered and parsed the
same way. Delete a case and the fan-out count, artifact set, and logged paths
all move, so the change cannot be silent.

## Update history

| Date | Change | Reason |
|---|---|---|
| 2026-10-28 | Case-set note added | Provenance for the shared inputs; bytes unchanged |
