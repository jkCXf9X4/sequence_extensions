---
id: INFO-014
type: info
title: Stress-hardening findings and dispositions
summary: Adversarial probes found two hangs, a process-mode wrong-function bug, and determinism/audit holes; every item is fixed or documented with a regression test
date: 2026-10-22
status: current
---

# Stress-hardening findings and dispositions

Adversarial probes ran against 3.0.0: fork-isolated cases, hard timeouts, hash-seed subprocesses.
The suite holds 398 tests; 40 are in `tests/flow/test_hardening.py`.
Every item is fixed or documented; every fix has a named regression test.
The release decision is `DR-019`.

## Findings

| Item | Severity | Finding | Fix and evidence |
| --- | --- | --- | --- |
| C1 | critical | Run hangs in drain when attempt finalization raises; triggers: cyclic/deep result, lone surrogate, non-UTF-8 path, broken `__str__`, log I/O error | Attempts settle unconditionally; log failure fails the attempt; `jsonable` marks cycles/depth and describes unprintables; safe UTF-8 bytes; `_contains_future` guards. `test_cyclic_result_returns_and_is_marked`, `test_submitted_cyclic_child_does_not_hang`, `test_unencodable_surrogate_result_is_logged`, `test_non_utf8_path_result_is_logged`, `test_deep_result_is_marked_instead_of_crashing`, `test_broken_str_result_is_described`, `test_log_write_failure_fails_the_run_instead_of_hanging` |
| C2 | critical | Zero-delay retries recurse; about 495 hang a clean interpreter, sooner on a deep stack; run timeout cannot escape | One iterative attempt loop; callbacks/timers start the next attempt on a new stack; retries never nest. `test_many_zero_delay_retries_do_not_recurse`, `test_many_zero_delay_retries_can_succeed_on_the_last_attempt` |
| H1 | high | Process workers execute the wrong function for lambdas/factory closures with a colliding qualname; the log names the wrong result | Unique counter-suffixed pickle alias per `NodeFunction`; resolved wrappers reuse it. `test_process_lambdas_execute_their_own_function`, `test_process_factory_closures_execute_their_own_function` |
| H2 | high | `GraphFuture` stays pending when a body raises `SystemExit`/`KeyboardInterrupt`; `pool.result` times out | Wrap non-`Exception` as `RuntimeError` and settle; `_forward_result` does the same. `test_graph_future_settles_system_exit` |
| D1 | medium | `fixed_clock` bytes vary across hash seeds; nested dict key order and mixed sets are not canonical | Reference mode sorts nested mapping keys; unorderable sets sort by type and canonical JSON. `test_fixed_clock_dict_order_is_hash_seed_independent`, `test_jsonable_mixed_set_is_deterministic` |
| D2 | medium | Concurrent fixed-clock runs share one path and lose a log | Exclusive in-process registry; POSIX advisory file lock. `test_concurrent_fixed_clock_runs_are_rejected`, `test_fixed_clock_lock_is_cross_process` |
| D3 | medium | `diff` collapses repeated identical executions; a changed fan-out count compares equal | Duplicates form a multiset; the nth copy carries `occurrence: n` (first omits it), sorted by content. `test_diff_sees_a_changed_number_of_identical_calls`, `test_diff_identical_executions_are_a_multiset_not_a_sequence`, `test_diff_duplicate_identity_is_not_collapsed` |
| D4 | medium | Logs emit `NaN`/`Infinity`, invalid strict JSON | `jsonable` maps non-finite floats to `{"float": "nan"}` (also `"inf"`/`"-inf"`); `allow_nan=False`. `test_non_finite_floats_are_strict_json` |
| D5 | medium | Fire-and-forget child failure leaves `Run.status` ok; only the log knew | `Run.failed_nodes` and `run_end.failed_nodes` list settled failing paths; `status` stays the root verdict. `test_fire_and_forget_failure_is_listed_in_failed_nodes`, `test_retried_then_successful_node_is_not_a_failure` |
| O1 | low | Cross-pool bind cancels another pool's node | Bind raises `ValueError`; the owner keeps running. `test_cross_pool_bind_is_rejected_without_cancelling_the_owner` |
| O2 | low | Runner cannot pass a node parameter named `options`; reports a call-time `TypeError` | Positional prefix up to `options`; keyword-only is a usage error. `test_runner_passes_an_options_parameter_positionally`, `test_runner_passes_options_after_other_positional_inputs`, `test_runner_rejects_keyword_only_options_as_usage_error` |
| O3 | low | `intersect`/`union` lose order, drop duplicates, reject unhashables | Order-preserving dedupe; unhashable-safe membership; sets ordered deterministically. `test_intersect_preserves_order_and_dedupes`, `test_intersect_supports_unhashable_items`, `test_union_preserves_first_occurrence_order`, `test_union_orders_a_set_operand_deterministically` |
| O4 | low | Log dict-key collisions drop entries (`{1, "1"}`) | Deterministic `#<type>#n` suffix; no entry lost. `test_jsonable_disambiguates_dict_key_collisions` |
| O5 | low | `gather` returns mapping keys; tuple subclasses lose type | Any `Mapping` resolves to a plain dict; orderable tuple subclasses keep type. `test_gather_resolves_mapping_proxy`, `test_gather_resolves_user_dict`, `test_gather_keeps_orderable_tuple_subclass` |
| O6 | low | Nested run from a user-created thread is not detected; it opens a second log | Documented limit: `ContextVar` does not cross threads; use the same thread or propagate context. No engine fix possible without thread parentage |
| O7 | low | `gather` outside a run and unbound `GraphFuture.result()` block forever | Both raise `RuntimeError` with guidance. `test_gather_outside_a_run_raises`, `test_unbound_graph_future_result_raises` |
| O8 | low | Runner lets an import-time exception escape | Usage error (exit 2). `test_runner_import_time_exception_is_a_usage_error` |
| O9 | low | `filter(node=...)` also matches `run_start` | Documented; pass `record="node"`. `test_filter_node_includes_run_start_unless_record_is_node` |

## Limits

- O6 is inherent: the engine cannot see which thread created another.
- O9 is field-selection semantics; it is documented, not changed.
- The fixed-clock cross-process lock uses POSIX `flock`; Windows keeps the in-process lock.
- A thread a node body starts does not inherit the run `ContextVar`.

## Verification

- `pytest` - 398 passed; coverage 92.7%.
- `pytest tests/flow/test_hardening.py` - 40 regressions.
- `ruff check src tests` - clean.
- `UPDATE_REF=1 pytest tests/e2e` - reference logs regenerated for D1/D5.

## Owns
- The stress-hardening finding list, dispositions, and regression evidence.

## Excludes
- Engine semantics: `INFO-011`.
- Test strategy: `INFO-006`.
- Release decision: `DR-019`.
