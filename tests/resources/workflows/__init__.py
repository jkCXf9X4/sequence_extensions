"""
Workflow XML examples for the V&V workflow test suite.

Each file in this directory is a complete, self-contained workflow
document (see ``README.md`` in this directory for the full index).  The
examples mirror the listings of the paper "Automation Nation: Taming
Complex V&V Workflows" (16th International Modelica & FMI Conference,
September 2025, Lucerne, Switzerland; DOI 10.3384/ecp12076741):

* ``eval_task_01.xml``       — Listing 9: full use-case-1 workflow with
  global parameters.
* ``dynamic_adaptation.xml`` — Listing 5: per-file adaptation driven by
  ``find_files``.
* ``adaptation_scope.xml``   — Listing 7: dynamic-adaptation scope
  (nested groups).
* ``sequential_example.xml`` — Listing 2: minimal ``<sequential>`` chain.
* ``parallel_example.xml``   — Listing 3: minimal ``<parallel>`` group.
* ``template_reuse.xml``     — templates (design principle 4): a
  ``<template>`` defined once, used twice with different parameters.
* ``template_parallel.xml``  — templates inside a ``<parallel>`` group,
  with a default parameter overridden at one use site.

``invalid/`` holds well-formed XML documents that the schema parser must
reject, one file per rejection rule (see the ``README.md`` table).

Load a file with :func:`load` (or :func:`path` for the ``Path`` itself);
the text is ready to hand to ``parse_workflow`` / ``run_workflow``.
"""

from __future__ import annotations

from pathlib import Path

_DIR = Path(__file__).parent

__all__ = ["load", "path"]


def path(name: str) -> Path:
    """Return the ``Path`` of an example file (e.g. ``"invalid/bogus.xml"``)."""
    return _DIR / name


def load(name: str) -> str:
    """Return the text of an example workflow file, ready to parse."""
    return path(name).read_text(encoding="utf-8")
