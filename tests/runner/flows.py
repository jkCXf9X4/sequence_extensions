"""Nodes for ``flow-runner`` tests: one per shape the runner must handle."""

from sequence_extensions.flow import node


@node
def bump(x):
    """Add one to a value."""
    return x + 1


@node
def echo(value, factor=1):
    """Echo value times factor."""
    return value * factor


@node
def double(values):
    """Add one to every value, concurrently."""
    futures = [bump.submit(v) for v in values]
    return [f.result() for f in futures]


@node
def failing():
    """Fail on purpose."""
    raise RuntimeError("boom")
