# Workflow XML examples

Test resources for the V&V workflow layer (`sequence_extensions.workflow`).
Each file is a complete, self-contained workflow document that can be opened
directly in an editor, and loaded by tests via `resources.workflows.load(name)`.

The examples mirror the listings of the paper *"Automation Nation: Taming
Complex V&V Workflows"* (16th International Modelica & FMI Conference,
September 2025, Lucerne; DOI [10.3384/ecp12076741](https://doi.org/10.3384/ecp12076741)).
The paper's library functions used below are the test stubs in
[`../workflow_stubs.py`](../workflow_stubs.py).

## Valid workflows

| File | Paper | Demonstrates |
| --- | --- | --- |
| `eval_task_01.xml` | Listing 9 (referenced in the paper as `eval_task_01.xml`) | Full use-case-1 workflow: `<VerificationWorkflow>` wrapper, a global parameter (`<argument key="model">`), nested `<sequential>` groups, and the parameter-sweep pattern. |
| `dynamic_adaptation.xml` | Listing 5 | Dynamic adaptation: `find_files` discovers files at runtime and the downstream group is spliced once per found file. |
| `adaptation_scope.xml` | Listing 7 | Dynamic-adaptation scope: an outer action may splice anywhere downstream, an inner action only within its own grouping scope. |
| `sequential_example.xml` | Listing 2 | Minimal `<sequential>` dependency chain (strict execution order). |
| `parallel_example.xml` | Listing 3 | Minimal `<parallel>` group (children are independent). |

Every file in this table parses with `parse_workflow` and runs with
`run_workflow` (the stub functions self-register in `DEFAULT_REGISTRY` on
import of `resources.workflow_stubs`).

## Invalid workflows (`invalid/`)

Well-formed XML that the schema parser must reject with `ValueError` — one
file per rejection rule. The expected error for each file is named in the
`tests/workflow/test_schema.py` test that loads it.

Parameters (action parameters and global parameters) are written as
`<argument key="name" value="..."/>` elements; an element's name is not a
parameter name.

| File | Rejected because |
| --- | --- |
| `invalid/wrong_root.xml` | root element is neither `<VerificationWorkflow>`, `<sequential>` nor `<parallel>` |
| `invalid/missing_top_level_grouping.xml` | `<VerificationWorkflow>` contains global parameters but no top-level grouping |
| `invalid/multiple_top_level_groupings.xml` | `<VerificationWorkflow>` contains two top-level groupings |
| `invalid/wrapper_unknown_element.xml` | non-`<argument>`, non-grouping element inside `<VerificationWorkflow>` |
| `invalid/action_without_function.xml` | `<action>` is missing its `function` attribute |
| `invalid/unknown_element.xml` | unknown element inside a grouping |
| `invalid/action_unknown_element.xml` | non-`<argument>` element inside an `<action>` (parameters must be `<argument>` elements) |
| `invalid/argument_without_key.xml` | `<argument>` is missing its `key` attribute |
| `invalid/argument_without_value.xml` | `<argument>` is missing its `value` attribute |
| `invalid/duplicate_argument.xml` | two `<argument>` elements with the same key on one action |
| `invalid/argument_with_children.xml` | `<argument>` contains child elements |

## Notes

- Paper Listing 1 (a single `<action>` element) and Listing 6 (the
  `<VerificationWorkflow>` template) are fragments in the paper, not
  complete documents; the wrapper shape of Listing 6 is fully shown by
  `eval_task_01.xml`. Listing 10 is the Python API and is covered by
  `tests/test_workflow.py` directly.
- XML comments (e.g. in `sequential_example.xml`) are part of the paper's
  listings; ElementTree's parser ignores them, so they are safe to keep.
