"""Retired compatibility surface for the pre-task-resolver architecture.

The production chain has one and only one eligibility path:

    Stage B ACTION_READY node
      -> reasoning.task_resolver.resolve
      -> reasoning.task_resolver.build_task_pools

This module intentionally cannot add nodes, repair generators, or create an
actionable stock pool.  Keeping explicit failing shims is safer than leaving a
second seemingly valid architecture that future code might import by mistake.
"""
from __future__ import annotations

import copy


RETIRED_MESSAGE = (
    "candidates.generators is retired for action eligibility; use "
    "reasoning.task_resolver.resolve + build_task_pools"
)


def ensure_mainstream_generators(stage_b: dict, as_of: str) -> dict:
    """Compatibility no-op: never add or change a Stage-B node/generator."""
    del as_of
    return copy.deepcopy(stage_b)


def build_pools_from_nodes(nodes: list[dict], as_of: str) -> list[dict]:
    """Fail closed so legacy callers cannot bypass the task resolver."""
    del nodes, as_of
    raise RuntimeError(RETIRED_MESSAGE)
