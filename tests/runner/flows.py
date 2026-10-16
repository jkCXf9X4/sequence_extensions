"""Flows for ``flow-runner`` tests: one per shape the runner must handle."""

from sequence_extensions.flow import flow, task


@task
def bump(x):
    """Add one to a value."""
    return x + 1


@flow
def echo(value, factor=1):
    """Echo value times factor."""
    return value * factor


@flow
def double(values):
    """Add one to every value, concurrently."""
    futures = [bump.submit(v) for v in values]
    return [f.result() for f in futures]


@flow
def failing():
    """Fail on purpose."""
    raise RuntimeError("boom")
