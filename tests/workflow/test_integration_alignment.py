"""
Cross-feature integration smoke test for the vision-alignment effort.

One workflow, all four features composed:

1. **Templates** — the workflow is defined in XML with a ``<template>``
   (a parameterized ``simulate`` + ``evaluate_results`` chain) expanded at
   two ``<use-template>`` sites with different parameters.
2. **Library** — every action's function comes from
   ``sequence_extensions.workflow.library`` (the paper's seven shipped
   functions), opted into the registry via ``register_library()``.
3. **History + replay** — the run executes through ``run_workflow`` with
   ``history=`` enabled, and the recorded history is replayed.
4. **Scaling** — the composition runs on the same engine paths the
   scaling tests exercise (parallel groups, many actions).

The assertion that matters: replaying the recorded history reproduces
the original run's final result exactly — proving the four features
compose rather than merely coexist.
"""

from __future__ import annotations

from sequence_extensions import run_workflow
from sequence_extensions.workflow.history import RunHistory, replay
from sequence_extensions.workflow.library import register_library

# A workflow that uses every feature at once:
#
# * a <template> "file_check" (simulate + evaluate_results per file),
#   instantiated twice with different files — the template feature;
# * the actions call library functions (simulate / evaluate_results /
#   compare_results) resolved through the registry after
#   register_library() — the library feature;
# * the two template uses sit in the root sequential group, so the final
#   compare_results action receives every upstream action's result
#   (keyed by function name, with collision suffixes) — the same engine
#   parameter-resolution paths the scaling tests exercise.
INTEGRATION_XML = """\
<VerificationWorkflow>
  <argument key="model" value="./model_1"/>
  <template name="file_check">
    <sequential>
      <action function="simulate">
        <argument key="file" value="{file}"/>
        <argument key="model" value="{model}"/>
      </action>
      <action function="evaluate_results">
        <argument key="file" value="{file}"/>
      </action>
    </sequential>
  </template>
  <sequential>
    <use-template name="file_check">
      <argument key="file" value="case_1.csv"/>
    </use-template>
    <use-template name="file_check">
      <argument key="file" value="case_2.csv"/>
    </use-template>
    <action function="compare_results"/>
  </sequential>
</VerificationWorkflow>
"""


def test_template_library_history_replay_compose(pristine_default_registry) -> None:
    """XML template + library functions + history/replay in one workflow."""
    # Feature 2: opt the shipped library into the default registry (the
    # fixture restores DEFAULT_REGISTRY afterwards — no cross-test leak).
    # Clear first so the call registers cleanly regardless of what the
    # surrounding test process already registered (same pattern as
    # test_library.py's default-registry tests).
    pristine_default_registry._functions.clear()
    register_library()

    # Features 1 + 2 + 3: run the XML-defined, template-expanded workflow
    # (whose actions are all library functions) with history recording on.
    history = RunHistory()
    result = run_workflow(INTEGRATION_XML, history=history)

    # The run executed: the final compare_results action summarized the
    # four upstream results (2x simulate + 2x evaluate_results, the
    # second of each keyed with a collision suffix).
    assert result == {
        "compare_results": {
            "simulate": 1,
            "simulate_2": 1,
            "evaluate_results": 1,
            "evaluate_results_2": 1,
        }
    }

    # The history captured every executed action in completion order:
    # 2 template uses x (simulate + evaluate_results) + 1 compare_results.
    assert len(history) == 5
    names = [record.name for record in history.records]
    assert sorted(names) == [
        "compare_results",
        "evaluate_results",
        "evaluate_results",
        "simulate",
        "simulate",
    ]
    # Template-expanded actions carry their resolved parameters (the
    # second simulate also receives the first template's upstream
    # results, keyed by function name — engine precedence order).
    simulate_params = [r.params for r in history.records if r.name == "simulate"]
    assert {"file": "case_1.csv", "model": "./model_1"} in simulate_params
    assert any(
        p.get("file") == "case_2.csv" and p.get("model") == "./model_1" for p in simulate_params
    )
    # Every action succeeded.
    assert all(record.exception is None for record in history.records)

    # Feature 3 (replay): re-executing the recorded history reproduces
    # the original run's final result exactly.
    replayed = replay(history)
    assert replayed == result
