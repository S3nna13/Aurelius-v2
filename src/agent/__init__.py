"""Aurelius v2 agent primitives.

This package ports the most useful lightweight agent-side ideas from the
original Aurelius tree: trigger-based skill matching, DAG workflow
execution, a persistent in-process task scheduler, and a transport-agnostic
MCP client shim.
"""

from __future__ import annotations

from .mcp_client import (
    MCP_PROTOCOL_VERSION,
    MCPClient,
    MCPPrompt,
    MCPProtocolError,
    MCPResource,
    MCPToolCallResult,
    MCPToolSpec,
)
from .skill_trigger_engine import (
    DEFAULT_TRIGGER_ENGINE,
    TRIGGER_ENGINE_REGISTRY,
    MatchedSkill,
    SkillTriggerEngine,
    TriggerEngineError,
    TriggerResult,
)
from .task_scheduler import Job, TaskScheduler, get_scheduler
from .workflow_graph import AGENT_REGISTRY, NodeStatus, WorkflowGraph, WorkflowResult

__all__ = [
    "AGENT_REGISTRY",
    "DEFAULT_TRIGGER_ENGINE",
    "Job",
    "MCPClient",
    "MCPPrompt",
    "MCPProtocolError",
    "MCPResource",
    "MCPToolCallResult",
    "MCPToolSpec",
    "MCP_PROTOCOL_VERSION",
    "MatchedSkill",
    "NodeStatus",
    "SkillTriggerEngine",
    "TaskScheduler",
    "TRIGGER_ENGINE_REGISTRY",
    "TriggerEngineError",
    "TriggerResult",
    "WorkflowGraph",
    "WorkflowResult",
    "get_scheduler",
]
