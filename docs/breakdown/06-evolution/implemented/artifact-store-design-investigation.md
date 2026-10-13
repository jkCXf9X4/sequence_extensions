---
id: IMP-005
type: imp
title: Artifact store — design investigation
summary: By-reference artifact store coupled to the DAG: control data stays by value in engine kwargs, bulk artifacts flow through a structurally addressed store with mint-at-call addressing and an append-only manifest
date: 2026-10-11
status: current
pb_exempt: true
---

# Artifact store — design investigation

Design study of the workflow layer's information flow. Finds the data plane
by-value-only, measures payload blowup under clone chains, and proposes a
by-reference artifact store coupled to the DAG. Extends the evidence story of
`INFO-001` (traceable, reproducible) from result values to run artifacts.
Builds on the engine and handle of `IMP-001` (`DR-001`, `DR-002`).
The store is implemented: the archived artifacts leaf holds the design, `DR-004` the
decision, and P1 (store core) and P2 (fan-in enumeration) are done. P0
(control-plane hygiene, the D5 echo contract) and P3 (comparison tooling,
content hashes) remain open.

## Question

How should bulk data flow through a workflow run?

Can data be decoupled from the engine and coupled only to the DAG, so that:

- functions exchange heavy artifacts outside the engine's kwargs,
- parallel branches get distinct, safe storage by construction,
- branches can be compared after a run, and at fan-in during a run?

## Plan

First-principles evaluation of information flow, four questions:

- Is data flow tied to control flow (ordering edges) or independent?
- Who determines what a consumer receives: push (ambient) or pull (declared)?
- How is information addressed: producer identity, code identity, position?
- What may a node emit?

Then code inspection of the data plane, a measurement of payload growth
under clone chains, then design exploration.

## Findings

### The data plane today

- Results flow by value through kwargs. Every downstream action receives all
  upstream results, keyed by the producing action's function name.
- Repeats get collision suffixes: `name`, `name_2`, `name_3`.
- Precedence: globals, then upstream results, then own params. `dag` is
  reserved and wins over all.
- Parallel children see the pre-group snapshot. A group's result list reaches
  only its parent's result list, never kwargs.
- Files a function writes are invisible to the engine and history. Functions
  choose paths ad hoc; nothing addresses or records them.

### Measured: echo compounding

- All upstream results fan into every downstream call.
- `simulate` returns `dict(params)`: it echoes its whole kwargs.
- Sweep and iteration clones share one scope; every clone sees all prior
  clones' results.
- Measurement (repr of final result, parameter_sweep over a simulate body):
  - sweep 2: 112 chars, nesting depth 5
  - sweep 6: 2,416 chars, depth 13
  - sweep 12: 196,597 chars, depth 25
- Repr length roughly doubles per clone. Extrapolated sweep 20: about 50 MB.
- History compounds too: record params hold resolved kwargs, so each result
  is stored once per later record.
- Single-run workflows stay small; nothing upstream to embed. Only clone
  chains blow up.

### Namespace collisions

- Function-name keying is code identity, not producer identity.
- The second result of function `run` takes key `run_2`. A distinct function
  named `run_2` takes the same key.
- Whichever produces later silently overwrites the other. Deterministic data
  loss, verified in `_run_action`'s keying loop.
- `_upstream_all` assumes dense suffixes. A skipped key breaks the walk.

### The information-flow contract

The evaluation supports eight rules. The engine already implements six.

- **One edge.** Ordering is the only edge; it carries all information.
  Determinism by construction.
- **Single assignment.** Each node's result is written once, at completion.
  Iteration copies are fresh variables.
- **Ambient past, declared consumption.** Everything upstream is available;
  functions consume deliberately.
- **Transform, not mirror.** A node's output is facts about its own
  computation. Mirrors compound.
- **Structure is downstream information.** The tree ahead of the walker is
  soft; behind it, frozen.
- **Handle sees structure, never data.** One data channel (kwargs), one
  structure channel.
- **Parallel groups are information barriers.** Siblings share an input view
  and never see each other.
- **History is the total projection, outside the flow.**

Two weaknesses:

- Function-name keying violates single assignment (collisions above).
- The data plane is by value only. Identity exists in history; bulk data has
  no reference plane.

### Demoted findings

Recorded, not acted on:

- Named-group aggregate kwargs would add a second data channel. The store's
  fan-in enumeration covers the motivating use, comparing branches.
- `dag.params()` reads would blur the handle's structure-only rule.
- Iteration drivers copy all preceding siblings. Crude, documented; a named
  body parameter is cheap if demanded.

## Design exploration

**Option 1 — status quo plus documentation (declined).** Echo growth is
measured, not hypothetical. The artifact evidence gap stays.

**Option 2 — structured results kwarg (declined).** Functions declaring a
reserved `results=` receive upstream results separately from merged params.
Touches the paper's flat call contract. No disk story. A second reserved data
kwarg.

**Option 3 — blackboard decoupled from ordering (declined).** Shared keyed
store, read on demand. Must prove no read-before-write under concurrency.
This is the merge negotiation the paper reports as its main complexity source.

**Option 4 — artifact store coupled to the DAG (adopted).** Bulk data flows by
reference through a structurally addressed store. The engine only injects a
scoped handle. Control data stays by value; paper listings run unchanged. The
store module couples to schema only, never the engine.

## Results

### The agreed design

**Split by weight:**

- Control data (verdicts, counts, paths, summaries) flows by value through
  kwargs. Unchanged.
- Artifacts (simulation outputs, reports, datasets) flow by reference through
  the store. Never enter kwargs.

**Placement and injection:**

- New module `workflow/artifacts.py`. Imports schema only. Same isolation as
  history.
- Injection mirrors `dag=`: the registry caches a wants-flag for the reserved
  kwarg; the engine injects a scoped handle at call time.
- Orthogonal to `dag=`: a function may declare both.
- Opt-in: `run_workflow` / `Test_Framework` take an `artifacts=` argument.
  Absent means today's behavior, zero change.

**Addressing:**

- An address derives from tree structure at call time: named scope, function
  name, ordinal on repeat.
- Mint at call time. Record in an append-only manifest. Never recompute.
- Positions shift under adaptation; minted addresses never move. Same
  identity-at-call-time pattern as history's `group_path`.
- The manifest is executed truth. The XML is declared truth. Together: the
  run's evidence.
- Clone identity: named scope plus ordinal. Reuses the kwargs suffix
  vocabulary (`name`, `name_2`); in path space, collisions are harmless.
- The manifest entry carries the action's OWN declared params, never the
  merged kwargs: the reference plane cannot echo upstream results.

**Scopes:**

- Write scope: the node's own directory. Nothing else.
- Read scope: the causal past. Everything behind the node in its chain is
  frozen and complete.
- The sequential invariant that makes `dag=` writes safe proves reads settled.
  The store inherits the walker's determinism argument.
- Fan-in enumeration: branch directories of a completed group the node is
  downstream of.
- No sibling reads during a run. The unsafe API does not exist; same
  philosophy as read-only parallel handles.
- Post-run: everything readable. External tools need no engine.

**Layout:**

```
runs/campaign-2026-10-11/
  manifest.jsonl                # append-only: seq, address, function, own params, dynamic
  find_files/
    files.json
  sweep/                        # <scope name="sweep">
    parameter_sweep/            # the sweep actor, inside its named scope
    solvers/                    # clone 1 of the swept parallel group
      simulate/
        result.csv              # simulate writes here, returns the pointer
      evaluate_results/
        summary.json
    solvers_2/                  # clone 2 — a fresh scope, own outputs
  compare/                      # fan-in consumer: branches("solvers") + read
```

**Replay:**

- Replay re-executes into a fresh run root.
- Or a replay handle serves reads from the recorded manifest; writes no-op.
  Mirrors the `ReplayHandle` design.

**What stays out:**

- Return-value semantics unchanged. The store is purely additive.
- Nothing polices what functions return. The split is convention, modeled by
  library exemplars: write the payload to the node directory, return the
  pointer.

## Work plan

- **P0 — control-plane hygiene. OPEN.** `_N` collision guard in
  `_run_action` keying; `_upstream_*` helpers scan actual keys. Mandated
  by single assignment. Independent of the store.
- **P1 — store core. DONE** (`workflow/artifacts.py`; engine minting and
  injection; `run_workflow` / `Test_Framework` wiring; history linkage per
  D3). Tests: layout determinism, parallel branch isolation, opt-in zero
  change, replay.
- **P2 — fan-in enumeration. DONE** (`ArtifactHandle.branches`; the
  walker threads completed groups alongside the chain). Tests: barrier
  holds; fan-in sees every branch (and every same-named group, in causal
  order).
- **P3 — tooling. OPEN.** Comparison over the manifest; content hashes.
  Docs: `docs/API.md` section (done), README example (done), CHANGELOG
  (done), fixture docs.

## Decisions (settled at implementation, 2026-10-11)

- **D1 — handle read surface.** Phased: minimal in P1, fan-in in P2. Both
  phases delivered in one pass; the design order held.
- **D2 — address scheme.** Names plus ordinal, kwargs suffix vocabulary in
  path space (`solvers`, `solvers_2`). The sketch's zero-padded
  `solvers/0001` form was refined to suffixes at implementation: the
  suffix form makes an action's directory derivable from its kwargs key
  in the common same-scope case. Branch order comes from mint order, not
  lexicographic order, so `_10` sorting is moot.
- **D3 — history linkage.** Linked: `ExecutionRecord.artifacts` carries
  the minted address, the join key into the manifest. `None` without a
  store.
- **D4 — reserved kwarg name.** `artifacts=`.
- **D5 — library echo contract.** OPEN, deferred to P0: bound
  `simulate` / `evaluate_results` echoes remain a control-plane change,
  separable from the store. The store itself is behavior-neutral for
  non-declaring functions (tested).

Two implementation findings, fixed with the store:

- Cloned groups now keep their optional `name` (`dag.copy` and the
  history replay clone dropped it; addresses fan out from labels, so the
  clone must carry its label).
- `branches(name)` concatenates every completed group of that name in
  causal order (all-occurrences, like the library's upstream suffix
  scans); latest-wins would hide a swept group's earlier clones.

## Evidence index

**Code:**

- `src/sequence_extensions/workflow/artifacts.py` — the store, the scoped
  handle, the replay stand-in (the implemented design).
- `src/sequence_extensions/workflow/engine.py` — `_WalkState` (addressing
  state threaded through the walks), `_mint_address` (mint at submission),
  `_run_action` (handle injection), `_record_call` (history linkage).
- `src/sequence_extensions/workflow/registry.py` — `wants_artifacts` /
  `uses_artifacts` (the cached flag, mirroring `wants_dag`).
- `src/sequence_extensions/workflow/history.py` — `ExecutionRecord.artifacts`;
  `replay` / `replay_records` re-inject `ReplayArtifacts`.
- `src/sequence_extensions/workflow/engine.py` — `_run_action`: fan-in
  construction, suffix keying, the `run_2` collision (the OPEN P0 fix).

**Measurement:** echo-growth script run during this investigation
(parameter_sweep 2 to 12 over a simulate body).

**Tests:** `tests/workflow/test_artifacts.py` (34 tests): opt-in zero
change, minted addresses and suffix series, manifest contents, causal-past
reads, parallel barriers (reads, writes, branch enumeration), sweep and
return-nodes clone addressing, determinism across runs, history linkage,
replay. Full suite: 433 passing at implementation time.

**Paper:** `docs/references/paper_44_yBqbPyj1.pdf` — listings exchange small
dict results; bulk artifacts are implied by the V&V domain but never
addressed (section 4.2, section 5).

**Docs:** `INFO-001` (vision: traceable, reproducible), the archived
engine leaf (the walker that mints), the archived artifacts leaf
(the implemented data plane),
`DR-004` (the decision), `IMP-001` (dynamic adaptation investigation).
