# 04-verification — Verification

How we know it is true: how each claim is checked, the acceptance criteria, and the test strategy and evidence.

## Ask

"How do we know it is true?" — the run commands, the per-area coverage, and how each claim is verified.

## When to Read

- Before changing a test or a coverage floor.
- When proving that a claim holds.

## Boundary

- Holds the proof only.
- Not the thing under test: its owning layer.
- Not routine build steps: `05-operation/`.
- The engine under test: INFO-011; the product claims: INFO-002.

## Contents

<!-- pb:index:start -->
<!-- GENERATED FILE — do not edit. Regenerate with pb-registers. -->
- **INFO-006** [Test strategy](testing.md) — How the pytest suite verifies the package — run commands, per-area coverage, and claim verification
- **INFO-014** [Stress-hardening findings and dispositions](stress-hardening-findings-and-dispositions.md) — Adversarial probes found two hangs, a process-mode wrong-function bug, and determinism/audit holes; every item is fixed or documented with a regression test
<!-- pb:index:end -->
