"""Plan a flow before running it — documents, overrides, diff, and execute.

Shows the plan half of the flow engine and its artifacts:

* ``plan_document()`` builds the DAG without executing anything and emits
  the ``flow-plan/2`` JSON document;
* ``plan_manifest()`` projects the document without values;
* ``apply_override()`` edits parameters per node while ``diff_plans()``
  shows exactly what changed;
* ``execute_plan()`` runs the edited document — the plan *is* the run
  configuration, so no separate parameter registry is needed.

The generated artifacts live next to the example, in ``artifacts/``, so you
can open them and see the documents the flow produced:

* ``plan.json`` — the full document (values serialized with ``jsonable``);
* ``plan.manifest.json`` — the same shape, every value stripped;
* ``plan.override.json`` — after ``apply_override``;
* ``diff.json`` — the diff between the original and the override;
* ``logs/campaign-fixed.jsonl`` — the run log (``fixed_clock`` pins the
  run id, so rerunning regenerates byte-identical artifacts).

Run::

    python examples/plan_workflow/plan_workflow.py
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from sequence_extensions.flow import (
    RunLog,
    RunOptions,
    apply_override,
    diff_plans,
    execute_plan,
    gather,
    jsonable,
    node,
    plan_document,
    plan_manifest,
)

#: case name -> the text this case is "scored" over.
CASES = {"alpha": "ab", "beta": "abcd", "gamma": "abcdef"}


def _write_cases(cases_dir: Path) -> list[Path]:
    """Create the input files so the example is runnable on its own."""
    cases_dir.mkdir(parents=True, exist_ok=True)
    paths = []
    for name, text in CASES.items():
        path = cases_dir / f"{name}.txt"
        path.write_text(text, encoding="utf-8")
        paths.append(path)
    return paths


def _write_json(path: Path, payload: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


@node
def score(case: Path, scale: float = 1.0) -> dict:
    """One case, one number: ``len(text) * scale``.

    ``scale`` is injected from the plan's node parameters, so the node body
    never hard-codes it — the caller tunes the flow without editing code.
    """
    text = case.read_text(encoding="utf-8")
    return {"case": case.stem, "score": round(len(text) * scale, 3)}


@node
def total(scores: list) -> dict:
    """Fan-in: the gathered list arrives as a plain list of dicts."""
    return {"count": len(scores), "total": round(sum(s["score"] for s in scores), 3)}


@node
def campaign(cases_dir: Path) -> dict:
    """Discover cases and fan out; ``scale`` is left to the plan."""
    cases = sorted(cases_dir.glob("*.txt"))
    scores = [score.submit(case) for case in cases]
    return total.submit(gather(scores))


def main(argv: list[str] | None = None) -> dict:
    parser = argparse.ArgumentParser(description=__doc__)
    #: The artifacts live next to the example, committed, so rerunning
    #: regenerates them in place (byte-identical under fixed_clock).
    default_out = Path(__file__).resolve().parent / "artifacts"
    parser.add_argument("--out", type=Path, default=default_out)
    args = parser.parse_args(argv)

    cases_dir = args.out / "cases"
    _write_cases(cases_dir)

    # 1. Plan pass: the DAG is built, nothing executes.  The document is
    #    the complete run configuration, options included.
    document = plan_document(
        campaign,
        cases_dir,
        # Fixed clock pins run id and timing: rerunning the example
        # regenerates the same log bytes, so the committed artifact
        # stays a clean reference.
        options=RunOptions(fixed_clock=True),
    )
    print(f"nodes:     {[entry['name'] for entry in document['nodes']]}")
    plan_path = args.out / "plan.json"
    try:
        plan_path = plan_path.relative_to(Path.cwd())
    except ValueError:
        pass
    print(f"plan:      {plan_path}")

    # 2. Full JSON document; Path values become {path, sha256} via jsonable.
    _write_json(args.out / "plan.json", jsonable(document))

    # 3. Manifest: same shape, every value stripped.
    _write_json(args.out / "plan.manifest.json", jsonable(plan_manifest(document)))

    # 4. Override scale per node, then diff against the original.
    #    The override reaches every occurrence of the node name (UC-C).
    overridden = apply_override(
        document, {"nodes": [{"name": "score", "params": [{"name": "scale", "value": 2.0}]}]}
    )
    _write_json(args.out / "plan.override.json", jsonable(overridden))
    changes = diff_plans(document, overridden)
    _write_json(args.out / "diff.json", changes)
    changed = [f"{c['name']}: {c['old']} -> {c['new']}" for c in changes["changes"]]
    print(f"diff:      {changed}")

    # 5. The edited document is the run configuration.
    run = execute_plan(campaign, overridden, log=args.out / "logs")

    print(f"status:  {run.status}")
    print(f"result:  {run.result}")
    print(f"log:     {run.log}")
    print("records: ", len(list(RunLog.records(run.log))))

    return {
        "document": document,
        "overridden": overridden,
        "diff": changes,
        "run": run,
    }


if __name__ == "__main__":
    main()
