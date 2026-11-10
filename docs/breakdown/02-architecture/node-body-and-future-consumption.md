---
id: INFO-015
type: info
title: Node body and future consumption
summary: A node body cannot consume a pending future in place — no mid-body await, no .result(), no iteration — so a fan-out list is concrete inside the body and the supported fan-out hands the producer's future to a fan-out node
date: 2026-11-10
status: current
---

# Node body and future consumption

A node body owns its work: it receives resolved arguments, may submit, and may
return a value or a future.  It cannot read a pending future's value in place,
and that is a deliberate contract, not a missing feature.

- A submitted node yields a `FlowFuture` handle, not its value.  Resolution
  happens only at the edges: submit arguments are resolved before a dependent
  body runs; a returned future settles the attempt by callback.  There is no
  mid-body await.
- `.result()` on an incomplete future inside a body (root or worker) raises
  with guidance instead of deadlocking, so a body cannot block on work it just
  submitted.
- A body cannot iterate a pending future either: `FlowFuture` is not iterable.
  A fan-out list must therefore be concrete inside the body, and fan-out width
  is fixed when the body runs, not discoverable before it (`IMP-023`).
- `gather` resolves the futures inside a value, preserving its shape, so fan-in
  stays future-first.

The supported fan-out shape produces the list in its own node and hands that
node's future to a separate fan-out node as an argument — the list is resolved
before the fan-out body runs, and `gather` fans back in:

    @node
    def list_cases(cases_dir):            return sorted(cases_dir.glob("*.csv"))

    @node
    def fan_out(cases, tolerance, out_dir):
        sims = [simulate.submit(c, out_dir) for c in cases]
        return gather([evaluate.submit(s, tolerance, out_dir) for s in sims])

    @node
    def campaign(cases_dir, tolerance, out_dir):
        return verdict.submit(
            fan_out.submit(list_cases.submit(cases_dir), tolerance, out_dir),
            out_dir,
        )

Locked by `tests/flow/test_node.py`:
`test_iterating_a_pending_future_inside_a_node_body_raises` (the rejected
shape) and `test_fan_out_receives_concrete_list_from_a_submitted_producer`
(the supported shape).  The owning engine leaf is `INFO-011`.