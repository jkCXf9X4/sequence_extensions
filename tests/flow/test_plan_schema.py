"""Tests for the machine-readable flow-plan/2 JSON Schema artifact."""

from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest

import sequence_extensions
from sequence_extensions.flow import gather, jsonable, node, plan_document, plan_schema

_SCHEMA_PATH = (
    Path(sequence_extensions.__file__).resolve().parent / "schemas" / "flow-plan-2.schema.json"
)


def _validator():
    return jsonschema.Draft202012Validator(plan_schema())


def _assert_valid(document):
    errors = sorted(_validator().iter_errors(document), key=lambda error: list(error.path))
    assert not errors, "\n".join(error.message for error in errors)


def _simple_document():
    @node
    def double(value: int = 2) -> int:
        return value * 2

    @node
    def add_one(value: int = 2) -> int:
        return value + 1

    @node
    def simple(value: int = 2):
        return add_one.submit(double.submit(value))

    return plan_document(simple)


def test_schema_validates_a_simple_flow():
    _assert_valid(_simple_document())


def test_schema_validates_a_flow_with_a_gather_hub():
    @node
    def leaf(item: int) -> int:
        return item * 10

    @node
    def collect(items: list[int]):
        return gather([leaf.submit(item) for item in items])

    document = plan_document(collect, [1, 2])

    assert any(entry["kind"] == "gather" for entry in document["nodes"])
    _assert_valid(document)


def test_schema_validates_jsonable_parameters_with_defaults(tmp_path):
    @node
    def flow(
        root: Path,
        label: str = "case",
        scale: float = 1.5,
        tags: tuple = ("a", "b"),
        payload: bytes = b"raw",
    ):
        return None

    document = jsonable(plan_document(flow, tmp_path))

    assert document["parameters"][0]["default"] is None
    assert document["parameters"][0]["value"] == {"path": str(tmp_path), "sha256": None}
    _assert_valid(document)


def test_checked_in_schema_matches_plan_schema():
    text = _SCHEMA_PATH.read_text(encoding="utf-8")

    assert text == json.dumps(plan_schema(), indent=2) + "\n"
    assert json.loads(text) == plan_schema()


def _wrong_schema_const(document):
    document["schema"] = "flow-plan/1"


def _missing_required_root_key(document):
    del document["options"]


def _invalid_kind_enum(document):
    document["nodes"][0]["kind"] = "task"


def _wrong_edge_key_names(document):
    document["edges"] = [
        {"source": edge["from"], "target": edge["to"]} for edge in document["edges"]
    ]


def _extra_unknown_node_key(document):
    document["nodes"][0]["unexpected"] = True


@pytest.mark.parametrize(
    "mutate",
    [
        _wrong_schema_const,
        _missing_required_root_key,
        _invalid_kind_enum,
        _wrong_edge_key_names,
        _extra_unknown_node_key,
    ],
    ids=[
        "wrong-schema-const",
        "missing-required-root-key",
        "invalid-kind-enum",
        "wrong-edge-key-names",
        "extra-unknown-node-key",
    ],
)
def test_schema_rejects_invalid_documents(mutate):
    document = _simple_document()
    mutate(document)

    assert list(_validator().iter_errors(document))
