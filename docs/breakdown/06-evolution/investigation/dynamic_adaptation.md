# 06-evolution — Investigation: Adopting the paper's dynamic adaptation

**Date:** 2026-10-09
**Status:** design agreed in review; architecture decided — the lazy tree-walking engine, per
[implementation_plan.md](implementation_plan.md) (which amends §5.1 below); implementation not
started (see [§6 work plan](#6-work-plan))
**Scope:** design principle 2 of [00-intent/vision.md](../../00-intent/vision.md):

> **Dynamic adaptation** — actions may adjust downstream actions at runtime
> (e.g. per file found, per iteration), restricted to their own grouping
> scope; execution is strictly downstream (DAG, no loops) to stay deterministic.

**Method:** full-text extraction of the source paper
([paper_44_yBqbPyj1.pdf](../../00-intent/paper_44_yBqbPyj1.pdf), via
`pdftotext`) and code inspection of the workflow layer, followed by a design
exploration with three iterations (one rejected, two adopted).

---

## 1. What the paper actually specifies

### 1.1 The mechanism and its two objectives (§3.3)

> "The second principle is dynamic adaptation, which allows any action to
> change or add actions downstream."

The paper gives dynamic adaptation **two objectives**:

1. **Adaptation to unknown factors** — "an action that searches for scenarios
   in a folder has no way to know how many, or what kind of, scenarios it will
   find before execution. To enable this, the action, after finding the
   scenarios, will make adjustments to downstream actions to reflect the new
   information" (Listing 5: `find_files` → per-file `simulate` +
   `evaluate_results`).
2. **Adaptation to intermediate results** — "take into account intermediate
   results such as failures or fulfillment of conditions and automatically
   branch to alternative paths. This adaptability is often connected to
   handling iterative tasks where the number of iterations may not be known
   beforehand."

The paper's implementation model (§4.2):

> "the full DAG is passed to each action for modification and when returned,
> it is merged back into the original DAG before continuing execution."

Functions manipulate the DAG as they run. In parallel execution each branch
holds "its own notion of the DAG", and branches "must negotiate the new
notion of truth before continuing when merging branches" (§5).

### 1.2 Scope restriction (Listing 7)

> "An action may only adjust actions or groups that are within its own
> grouping scope. For example, in Listing 7, outer_action_1 can alter
> everything downstream, including the inner actions. However, when moving
> into the inner scope, the inner_action_1 can only alter actions downstream
> within its grouping scope, more specifically inner_action_2."

Note: `inner_action_2` is an **action**, not a group — adjusting the next
*action* sibling is explicitly in scope in the paper.

### 1.3 Determinism constraints (§4.2 Limitations, §5)

- Execution is **strictly downstream**; an action must not create a
  downstream dependency to an upstream action; data can only be accessed
  upstream along a dependency edge.
- **Feedback loops are prohibited**; every action executes at most once.
- The iteration workaround (§5): "in iterative workflows to achieve
  conditional effects the solution could be to copy the desired actions to
  the end when a condition is triggered, thus creating the next iteration."

### 1.4 Lessons the paper itself reports (§5)

- **Readability criticism** — "in Listing 5, it is not possible to determine
  how the function `find_files` will alter the downstream actions by only
  looking at the representation. This places requirements on the function
  library to provide clarity regarding what functions do and how they affect
  the workflow."
- **Parallel merge complexity** — the negotiation-at-merge design was the
  main source of complexity ("a clear case of premature optimization"); the
  scope restriction and loop prohibition exist precisely to cope with it.
- **Documentation requirement** — the mitigation for the invisibility of
  adaptation in XML is comprehensive documentation of each function's
  adaptation behavior.

---

## 2. What the package has today

| Paper element | Where it lives |
| --- | --- |
| Splice mechanism (Listings 5 & 7, outer case) | `workflow/engine.py` — a function returning `Action`/`Sequential`/`Parallel` node(s) has them spliced in place of its **next sibling, which must be a group**; the replaced group's subtree is cancelled; the spliced group's result becomes the action's result |
| Scope restriction | `check_splice_scope()` — structural: a splice can only touch the action's own next sibling, so an inner action can never reach outer scope |
| DAG / at-most-once / no loops | Engine builds one future per action and never re-runs a function |
| Objective-1 drivers | `workflow/library.py` — `find_files` (per found file), `parameter_sweep` (per sweep value) |
| History of splices | `workflow/history.py` — spliced actions recorded `dynamic=True`; deterministic `replay` |
| Tests | `tests/workflow/test_engine.py` §9–11 (per-file splice, both Listing-7 scope tests, at-most-once) |

**The narrowing.** Where the paper hands each function the DAG to modify, this
package narrows adaptation to a *return-nodes protocol*: functions are blind
to the workflow tree and may only emit brand-new nodes that replace the next
sibling group. That is a deliberate safety win (no merge negotiation is ever
possible), but it costs three capabilities the paper has:

| Paper capability | Return-nodes protocol |
| --- | --- |
| Function **reads** the DAG (sees the downstream group it adapts) | ❌ functions must construct nodes from scratch — `find_files` builds `Action("simulate", file=f)` instead of cloning the declared downstream group |
| Function **adjusts existing** downstream actions (e.g. retune parameters) | ❌ impossible — only whole-group replacement |
| Function **copies actions to the end** (§5 iteration workaround) | ❌ impossible — no append, only next-sibling replacement |

---

## 3. Findings

- **F1 — Listing 7's inner case is rejected.** The paper allows
  `inner_action_1` to alter `inner_action_2` (an action); `check_splice_scope`
  requires the next sibling to be a group, so that in-scope adaptation raises
  `ValueError`. The existing test
  (`test_scope_restriction_inner_cannot_affect_outer_siblings`) encodes this
  deviation as if it were the paper's rule — the engine cannot distinguish
  "out of scope" from "next sibling is not a group".
- **F2 — Objective 2 is unimplemented.** No library function and no test
  demonstrates branching to alternative paths on intermediate results, or
  iterating until a condition is met (the "per iteration" half of the
  principle). `find_files`/`parameter_sweep` only adapt to counts discovered
  in a single call.
- **F3 — The paper's documentation requirement is unmet.** `docs/API.md` and
  `README.md` do not document the workflow engine or dynamic adaptation at
  all (only the package-layout table mentions `run_workflow`). The alignment
  report's "P2 — Met" therefore overstates adoption given F1/F2.
- **F4 — Parallel-parent splice is underspecified (by inspection).**
  `check_splice_scope` accepts any next-sibling group regardless of whether
  the parent is `Sequential` or `Parallel`. Inside a `Parallel` group the next
  sibling may already be executing when the splice is attempted (cancellation
  is only consulted at call start, `_skip`), so the splice's mutation of
  `parent.children` has no defined effect on the already-built futures. No
  test exercises this case.
- **F5 — Template expansion is already guaranteed finite**
  (`test_parse_template_rejects_self_reference` — "expansion must stay
  finite"), which matters for the non-Turing-completeness argument in §5.5.

---

## 4. Design exploration

### 4.1 Option 1 — Declarative `<branch>`/`<case>` + `Repeat()` (REJECTED)

First sketch: keep functions graph-free by moving the decisions into the
schema.

- `<branch>` group with named `<case>` children; the preceding action returns
  a case *name* (a plain string); the engine splices the chosen case and the
  others never run.
- A `Repeat()` sentinel returned by a check action; the engine clones the
  declared iteration body plus the check and appends them at scope end
  (literally the paper's "copy the desired actions to the end").

**Pros:** functions never build graphs; alternative paths visible in XML
(addressing the paper's §5 readability criticism); deterministic.

**Cons (why rejected):**

- It adds **two schema constructs that are control flow** — a step toward a
  DSL with semantics, cutting against the schema's defining charm: *it is a
  small set of simple constructs, not a Turing-complete language*.
- It deviates from the paper's actual mechanism, in which functions manipulate
  the DAG as they run.
- The grammar grows instead of shrinks.

### 4.2 Option 2 — Scoped DAG handle (ADOPTED)

Adopt the paper's mechanism directly, made deterministic by construction:
**hand each adapting function a scoped view of the DAG and let it manipulate
that** — the paper's "full DAG passed to each action, merged back on return",
except the handle exposes only the action's own grouping scope and changes
are applied transactionally by the engine under its lock.

```python
def find_files(path, pattern="*.csv", *, dag, **kwargs):
    files = sorted(Path(path).glob(pattern))
    body = dag.following_group()              # READ the declared downstream scope
    for f in files:
        dag.append(body.adjusted(file=f))     # clone + retune, append at scope end
    return files                              # plain result still flows downstream
```

**Contract:**

- **Injection:** the engine passes a `dag=` keyword argument only when the
  function's signature declares it (fixture-style; zero schema/registry
  change). Functions that don't ask are unaffected.
- **Read:** the action's own grouping scope — following siblings and their
  subtrees (so an outer action can alter inner actions, Listing 7), and
  preceding siblings (so an end-of-body check can copy them to the end).
- **Write** — only within the own scope, and only onto nodes that provably
  have not started:
  - later siblings when the parent scope is `sequential` (they depend on this
    action transitively);
  - the subtree of a following scope (same guarantee);
  - fresh appends at scope end.
- **Parallel safety:** children of a parallel scope get a **read-only**
  handle. The paper's "two branches changed future common activities" race is
  designed out instead of negotiated — and this also resolves F4.
- **Ops:** `replace(target, nodes)`, `adjust(target, **params)`,
  `copy(target)` / `adjusted(**params)`, `append(nodes)`, plus reads.
- **Termination:** a bounded iteration count (runaway adaptation →
  deterministic `ValueError`, not a hang).
- **Backward compatibility:** the return-nodes protocol stays, as a
  compatible shortcut layered on the same internals.

Every paper pattern falls out with **zero new schema constructs**:

| Paper pattern | With the handle |
| --- | --- |
| Listing 5 (per file found) | clone the declared following scope once per file (function never builds nodes — it adapts the declared ones) |
| Listing 7 (scope) | outer actions reach into following subtrees; inner handles end at the inner scope boundary |
| §5 branching | alternatives are the children of the following scope; the decider picks one (`replace(next, [next.children[i]])`), the rest never run |
| §5 iteration (copy to end) | `dag.append(dag.copy(preceding_siblings))` — each copy is a fresh node → at-most-once holds, strictly downstream → still a DAG |

### 4.3 Refinement — `<scope type="...">` (ADOPTED)

Unify the two grouping elements into one that names the thing the feature
depends on:

```xml
<VerificationWorkflow>
  <model value="./model_1"/>
  <scope type="sequential">
    <action function="find_files">
      <argument key="path" value="file_storage/"/>
    </action>
    <scope type="parallel">        <!-- find_files clones this once per file -->
      <action function="simulate"/>
      <action function="evaluate_results"/>
    </scope>
  </scope>
</VerificationWorkflow>
```

- **It names the adaptation boundary.** "Grouping scope" was a derived,
  implicit concept; now the XML literally shows each action's boundary. The
  handle's write rules read directly off the element (§4.2).
- **The grammar gets smaller, not bigger.** Two grouping elements become one
  element with a validated attribute; combined with the handle (which
  replaces Option 1's constructs), the whole design nets out to *fewer*
  constructs than today while covering everything the paper describes.
- An optional `name` attribute on the same element
  (`<scope type="sequential" name="retry">`) gives the handle stable
  addressing for branch alternatives — still one construct.

---

## 5. The agreed design

### 5.1 Engine (`workflow/engine.py`)

- **Splice forms:** replace next-sibling *group* (unchanged, Listing 5);
  replace next-sibling *action* (Listing 7 inner case — closes F1); **append
  at scope end** when last (§5 "copy to the end"). All confined to the
  action's own scope by construction; the out-of-scope guarantee becomes
  purely structural.
- **Scoped DAG handle** per §4.2 (injection, read/write rules, ops,
  read-only parallel children, bounded iterations).
- Return-nodes protocol unchanged, on the same internals.

### 5.2 Schema (`workflow/schema.py`)

- `<scope type="sequential|parallel">` (decisions D1–D3 in [§7](#7-open-decisions)):
  `<sequential>`/`<parallel>` continue to parse (recommended alias strategy,
  no deprecation warnings — keeps every paper listing and the existing 295
  tests valid verbatim).
- Optional `name` attribute for handle addressing.
- Invalid/missing `type`, bad children → existing-style `ValueError`s.
- History path labels stay `sequential[i]`/`parallel[i]` (derived from type —
  traceability output unchanged).
- Python API unchanged: `Sequential`/`Parallel` remain the classes.

### 5.3 Library (`workflow/library.py`)

- `find_files` / `parameter_sweep` re-expressed paper-faithfully via the
  handle (clone the declared following scope per file / per value, instead of
  constructing nodes).
- New objective-2 drivers: `evaluate_goal` (decider — inspects an upstream
  result against a criterion, returns the alternative's name/index) and
  `check_convergence` (copy-to-end iteration; returns a summary when done).
- `register_library()` grows accordingly; still opt-in.

### 5.4 History and replay (`workflow/history.py`)

- Handle ops recorded on the `ExecutionRecord` (an `adaptations` field —
  *what the function did to the DAG*, not just what it returned).
- `replay` strips the recorded `dag` kwarg and re-injects a fresh handle;
  replayed adaptations are deterministic because ops depend only on inputs.

### 5.5 Why the schema stays non-Turing-complete

- The grammar has no loops, no recursion, no conditionals, no expressions —
  a workflow is a **finite tree**; parsing succeeds finitely or rejects.
- Templates expand at parse time and self-reference is rejected (F5), so
  templates cannot smuggle recursion in.
- The engine enforces at-most-once per node, strictly-downstream edges, and
  the bounded iteration count — runs terminate and replay.
- The only Turing-complete component is the Python library functions —
  exactly the paper's split: *complexity in the library, not the schema*.
  The handle adds no schema constructs; branching and iteration live in
  library functions.

---

## 6. Work plan

1. **Engine — splice forms:** allow replacing a next-sibling action; append
   at scope end when last; rewrite the two Listing-7 tests (the current
   inner test rejects the paper's in-scope case — F1); add a test proving
   splices/handle writes can only land in the action's own parent scope.
2. **Engine — handle:** implement the §4.2 contract (injection, ops, write
   rules, read-only parallel children, iteration bound); pin down F4 with a
   test (adaptation attempt inside a parallel scope → read-only, never a
   running-sibling mutation).
3. **Schema — `<scope>`:** new element + alias strategy (D1); `name`
   attribute; validation rules + invalid fixtures; alias-equivalence tests.
4. **Library:** re-express `find_files`/`parameter_sweep` via the handle; add
   `evaluate_goal`, `check_convergence`; driver tests.
5. **History:** `adaptations` field; replay re-injection; tests for both,
   including replay of handle-driven workflows.
6. **Tests (new):** branch-by-selection (chosen runs / others never), default
   alternative, unknown alternative → `ValueError`; iterate-until-converged
   with an unknown count; at-most-once across copied iterations; integration
   test combining `<scope>` + template + handle drivers + history in one XML.
   **Updated:** the two Listing-7 tests, `tests/resources/workflows/README.md`
   fixture table.
7. **Docs (closes F3):** `docs/API.md` gains a full `workflow` section —
   schema, engine, registry, library, history, the **adaptation contract
   table** ("what each driver needs after it / what it does to the DAG"), and
   the non-Turing-completeness guarantees; `README.md` example with
   `<scope>`; `CHANGELOG.md` entry. Optional: touch up the alignment
   report's P2 row.

---

## 7. Open decisions

| # | Decision | Recommendation |
| --- | --- | --- |
| D1 | `<scope>` alias vs. hard replace of `<sequential>`/`<parallel>` | **Alias** — old spellings still parse, documented as paper-legacy, no deprecation warnings (keeps test runs at zero warnings and every paper listing valid) |
| D2 | `type` attribute values | **`sequential` / `parallel`** — matches the Python classes and the paper's vocabulary (`sequence`/`parallel` acceptable if shorter is preferred) |
| D3 | `type` required vs. defaulted | **Required** — explicit, matching today's two-element explicitness |
| D4 | Handle injection mechanism | **Signature inspection** (`dag` kwarg provided only when declared) — zero schema/registry change; alternatives: registry flag (`register(..., adapts=True)`) or XML marker (`<action adapt="true">`, which has the side benefit of making adaptation visible in the representation) |
| D5 | Iteration bound default | A generous engine-level default (e.g. 10 000), overridable; runaway adaptation → deterministic `ValueError` |

---

## 8. Evidence index

**Paper** (see [00-intent](../../00-intent/vision.md) for the full citation):
§3.2 (requirement: "conditional rules that change the next steps"), §3.3
(principle, two objectives, Listings 4–5), §4.2 (implementation model, Listing
7, limitations), §5 (readability criticism, merge negotiation, loop
prohibition, copy-to-end iteration, documentation requirement).

**Code:**

- `src/sequence_extensions/workflow/engine.py` — splice mechanism,
  `check_splice_scope`, `_run_action`, `_cancel`/`_skip`, at-most-once
- `src/sequence_extensions/workflow/library.py` — `find_files`,
  `parameter_sweep`, `register_library`
- `src/sequence_extensions/workflow/history.py` — `ExecutionRecord.dynamic`,
  `replay`
- `src/sequence_extensions/workflow/schema.py` — current
  `<sequential>`/`<parallel>` parsing, templates

**Tests:**

- `tests/workflow/test_engine.py` §9–11 — per-file splice, Listing-7 scope
  tests, at-most-once
- `tests/workflow/test_history.py` — spliced records marked `dynamic`,
  replay determinism
- `tests/workflow/test_templates.py:454` — template self-reference rejection

**Docs:** `docs/alignment_report.md` (P2 row), `docs/API.md` /
`README.md` (workflow layer undocumented — F3).
