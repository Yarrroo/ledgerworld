"""The prepared demo's offered advance and arrival terms, scoped to its queued jobs.

Simulation-safe: no connector, gateway or credential access. Ordinary API jobs keep
using the original world; an operator preparation opts into this synthetic offer.
"""
from dataclasses import replace

from .run import ADVANCE, TERMS


def demo_runner(runner):
    snapshot = runner.world.snapshot.model_copy(deep=True)
    data = snapshot.model_dump(mode="json")
    data["contracts"].append(ADVANCE)
    world = replace(runner.world, snapshot=type(snapshot).model_validate(data))
    return replace(runner, world=world, terms=TERMS)
