"""Aurelius v2 agent primitives.

This package ports the most useful lightweight agent-side ideas from the
original Aurelius tree: trigger-based skill matching and DAG workflow
execution.
"""

from __future__ import annotations

from .skill_trigger_engine import (
    DEFAULT_TRIGGER_ENGINE,
    TRIGGER_ENGINE_REGISTRY,
    MatchedSkill,
    SkillTriggerEngine,
    TriggerEngineError,
    TriggerResult,
)
from .workflow_graph import AGENT_REGISTRY, NodeStatus, WorkflowGraph, WorkflowResult

__all__ = [
    "AGENT_REGISTRY",
    "DEFAULT_TRIGGER_ENGINE",
    "MatchedSkill",
    "NodeStatus",
    "SkillTriggerEngine",
    "TRIGGER_ENGINE_REGISTRY",
    "TriggerEngineError",
    "TriggerResult",
    "WorkflowGraph",
    "WorkflowResult",
]
