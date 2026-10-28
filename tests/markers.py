"""Test-level marker policy shared by ``conftest`` and the policy test.

Every collected test carries exactly one level marker, applied by directory.
``flaky_timing`` is an orthogonal marker for tests that assert wall-clock
bounds or use sleeps for synchronisation; CI can deselect them with
``-m "not flaky_timing"``.
"""

from pathlib import Path

LEVEL_MARKERS = frozenset(
    {
        "level_static",
        "level_unit",
        "level_component",
        "level_contract",
        "level_integration",
        "level_system",
        "level_acceptance",
    }
)

_TESTS_ROOT = Path(__file__).resolve().parent

_LEVEL_BY_TOP_DIR = {
    "ext": "level_unit",
    "graph": "level_component",
    "flow": "level_component",
    "runner": "level_component",
    "usage_examples": "level_system",
    "e2e": "level_system",
}


def level_for(path) -> str:
    """The one level marker a test file belongs to (directory policy)."""
    try:
        rel = Path(path).resolve().relative_to(_TESTS_ROOT)
    except ValueError:
        return "level_unit"
    parts = rel.parts
    if len(parts) == 1:
        # tests/test_package.py and root-level meta tests.
        return "level_unit"
    top = parts[0]
    if top == "flow" and (rel.name == "test_run.py" or rel.name.startswith("test_process")):
        # End-to-end run semantics and the process boundary: integration.
        return "level_integration"
    return _LEVEL_BY_TOP_DIR.get(top, "level_unit")
