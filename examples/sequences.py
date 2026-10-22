"""Sequence helpers: ``list_ext``, ``dict_ext``, and ``gen_ext``.

A small run-report cleanup, showing the functional helpers as they are
normally used: filter, map, window, reduce, convert to a dict, and look at
one ``(key, value)`` pair without unpacking a tuple.

Run::

    python examples/sequences.py
"""

from __future__ import annotations

from sequence_extensions import dict_ext, gen_ext, list_ext


def main() -> dict:
    runs = list_ext(
        [
            {"case": "c1", "score": 0.82, "status": "ok"},
            {"case": "c2", "score": 0.91, "status": "ok"},
            {"case": "c3", "score": 0.74, "status": "ok"},
            {"case": "c4", "score": 0.66, "status": "timeout"},
        ]
    )

    metadata = dict_ext({"solver": "mock", "cases": len(runs)})
    print("metadata:", metadata.to_string(separator=", "))

    # list_ext transformations return list_ext, so calls chain.
    finished = runs.filter(lambda run: run["status"] == "ok")
    scores = finished.map(lambda run: run["score"])
    cases = finished.map(lambda run: run["case"])

    print("finished:", cases.to_string())
    print("scores:  ", scores.to_string())
    print("mean:    ", round(scores.average(), 3))
    print("best:    ", finished.first(lambda run: run["score"] == scores.max())["case"])
    print("moving:  ", scores.window(2).map(lambda window: round(window.average(), 3)).to_string())
    print("sum:     ", round(scores.reduce(lambda a, b: a + b), 3))

    # A list plus a key list is the common "columns -> records" conversion.
    by_case = scores.to_dict_key(cases)
    passing = by_case.filter(lambda case, score: score >= 0.75)
    print("passing: ", passing.to_string(separator=", "))

    # KeyValueTuple gives .key / .value; map(cast=dict) leaves the dict_ext world.
    best = by_case.first(lambda case, value: value == by_case.get_values().max())
    print("first:   ", f"{best.key} -> {best.value}")
    print("report:  ", by_case.map(lambda case, score: (case, round(score, 1)), cast=dict))
    print("inverse: ", by_case.inverse().to_string(separator=", "))

    # Safe lookup, and a bounded recursive walk without writing a loop.
    print("missing: ", list_ext([1, 2]).get_item_or_default(9, default="missing"))
    stages = gen_ext.to_list(gen_ext.recursive_gen(1, lambda n: n * 2, stop_f=lambda n: n < 64))
    print("stages:  ", stages)

    return {
        "finished": list(cases),
        "scores": list(scores),
        "mean": scores.average(),
        "moving": [round(window.average(), 3) for window in scores.window(2)],
        "by_case": dict(by_case),
        "passing": dict(passing),
        "best": best,
        "stages": stages,
        "metadata": dict(metadata),
    }


if __name__ == "__main__":
    main()
