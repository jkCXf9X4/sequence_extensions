---
id: CP-032
type: capability
title: Extract what a flow can be tuned with
date: 2026-11-11
status: current
summary: A stable input manifest — every settable input of the flow and its nodes, which are required, what each defaults to
---

# Extract what a flow can be tuned with

## Scenario

- An operator tuning a flow they did not write asks: "tell me every input this
  flow takes, which are required, and what each defaults to — before I touch
  the run."
- The answer is a complete, stable input manifest: name, type,
  required/optional, default value; the same manifest every time for the same
  flow.

## Acceptance

- The manifest lists the root's user-facing inputs and every node's settable
  inputs, with type, required/optional, and default.
- Dependency edges are not inputs: a node's future arguments never appear in
  the manifest.
- The manifest is a projection of the plan document: identical flows give
  identical manifests.

## Evidence

- `tests/flow/test_plan_document.py`

## Owns

- The pre-execution input-survey need: name, type, required/optional, default.

## Excludes

- How the parameter surface is derived: `IMP-023`.
- Overriding the inputs: `CP-033`.