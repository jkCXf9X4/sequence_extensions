"""Policy: the e2e golden carries provenance and cannot be rewritten silently.

The e2e suite is the repository's best independent oracle, and its verdict is
only as trustworthy as the ability to notice a golden being rewritten.  These
checks cover the three holes a green run could otherwise hide:

* every committed reference flow has a ``case.md`` saying what it pins;
* no test module outside ``e2e/golden.py`` names the committed fixture paths,
  so only the reviewed update path writes them;
* the scratch root stays git-ignored.
"""

from __future__ import annotations

import ast
import subprocess
from pathlib import Path

import pytest

TESTS = Path(__file__).resolve().parent
E2E = TESTS / "e2e"
REF = E2E / "ref"
CASES = E2E / "cases"

#: Labels the adapted conversion-case template requires.
REQUIRED_FIELDS = (
    "Scenario",
    "Fault pinned",
    "Why the log is authoritative",
    "Pinned fields",
    "Excluded fields",
    "Comparison",
    "Volatile fields",
    "Update policy",
    "Input",
    "Expected",
)
REQUIRED_SECTIONS = ("## What this case proves", "## Update history")

#: The committed trees only ``e2e/golden.py`` may name in code.
GUARDED_LITERALS = ("tests/e2e/ref", "tests/e2e/cases")


def _reference_flows() -> list[Path]:
    return sorted(path for path in REF.iterdir() if path.is_dir())


def _notes() -> list[Path]:
    notes = [flow / "case.md" for flow in _reference_flows()]
    return [note for note in notes if note.is_file()]


def _string_literals(source: Path) -> list[str]:
    """String constants in ``source`` that are not docstrings."""
    tree = ast.parse(source.read_text(encoding="utf-8"))
    docstrings = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            body = getattr(node, "body", [])
            first = body[0] if body else None
            if (
                isinstance(first, ast.Expr)
                and isinstance(first.value, ast.Constant)
                and isinstance(first.value.value, str)
            ):
                docstrings.add(id(first.value))
    return [
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and id(node) not in docstrings
    ]


def test_every_reference_flow_carries_its_case_note():
    """A committed golden without provenance is a verdict with no argument."""
    flows = _reference_flows()
    assert flows, f"no reference flows under {REF}"
    missing = [flow.name for flow in flows if not (flow / "case.md").is_file()]
    assert not missing, f"reference flows without case.md: {sorted(missing)}"


def test_the_inputs_are_documented_as_one_case_set():
    """The four csvs are one set: one note, and it says why."""
    assert (CASES / "README.md").is_file(), "tests/e2e/cases has no README.md"
    assert not (CASES / "case.md").is_file(), (
        "cases/case.md contradicts the one-case-set README.md"
    )


@pytest.mark.parametrize("note", _notes(), ids=lambda p: p.relative_to(E2E).as_posix())
def test_case_notes_have_the_required_shape(note):
    """What scenario, which fault, why the log is authoritative, update policy."""
    text = note.read_text(encoding="utf-8")
    for field in REQUIRED_FIELDS:
        assert f"- **{field}:**" in text, f"{note}: missing the {field!r} field"
    for section in REQUIRED_SECTIONS:
        assert section in text, f"{note}: missing the {section!r} section"


def test_only_the_golden_module_names_the_committed_fixture_paths():
    """Writing ``ref/``/``cases/`` is the update path's job, not any test's."""
    offenders = {}
    for source in sorted(E2E.glob("*.py")):
        if source.name == "golden.py":
            continue
        hits = {
            literal
            for literal in _string_literals(source)
            if any(guarded in literal for guarded in GUARDED_LITERALS)
        }
        if hits:
            offenders[source.name] = sorted(hits)
    assert not offenders, (
        f"only e2e/golden.py may name tests/e2e/ref or tests/e2e/cases: {offenders}"
    )


def test_scratch_root_is_git_ignored_and_untracked():
    """Scratch is per-worker, git-ignored, and tracks nothing below it."""
    git = subprocess.run(
        ["git", "rev-parse", "--is-inside-work-tree"],
        cwd=TESTS.parent,
        capture_output=True,
        check=False,
    )
    if git.returncode != 0:
        pytest.skip("not a git work tree")
    ignored = subprocess.run(
        ["git", "check-ignore", "-q", "tests/e2e/out"],
        cwd=TESTS.parent,
        check=False,
    )
    assert ignored.returncode == 0, "tests/e2e/out is not git-ignored"
    tracked = subprocess.run(
        ["git", "ls-files", "tests/e2e/out"],
        cwd=TESTS.parent,
        capture_output=True,
        text=True,
        check=False,
    )
    assert tracked.stdout.strip() == "", f"scratch is tracked by git: {tracked.stdout}"
