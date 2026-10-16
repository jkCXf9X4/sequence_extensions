"""Fixture flows for ``flow-runner`` tests — the module ``[run].module`` selects.

Kept in its own package so both the in-process ``main()`` tests and the
``python -m`` subprocess test import the same module path
(``runner.flows`` — ``tests/`` is on ``sys.path`` under pytest).
"""
