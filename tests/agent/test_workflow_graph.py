"""Tests for the Aurelius v2 workflow graph."""

from __future__ import annotations

import pytest
from src.agent.workflow_graph import AGENT_REGISTRY, WorkflowGraph, WorkflowResult


def _value(output):
    def fn(state):
        return output

    return fn


def _error(message: str):
    def fn(state):
        raise RuntimeError(message)

    return fn


class TestRegistry:
    def test_registry_contains_workflow_graph(self) -> None:
        assert AGENT_REGISTRY["workflow_graph"] is WorkflowGraph


class TestAddNode:
    def test_add_node_and_duplicate_guard(self) -> None:
        graph = WorkflowGraph()
        graph.add_node("a", _value(1))

        assert "a" in graph._nodes
        with pytest.raises(ValueError, match="already registered"):
            graph.add_node("a", _value(2))


class TestValidate:
    def test_validate_detects_undefined_dependency(self) -> None:
        graph = WorkflowGraph()
        graph.add_node("a", _value(1), deps=["missing"])

        errors = graph.validate()

        assert any("undefined" in error for error in errors)

    def test_validate_detects_cycle(self) -> None:
        graph = WorkflowGraph()
        graph.add_node("a", _value(1), deps=["b"])
        graph.add_node("b", _value(2), deps=["a"])

        errors = graph.validate()

        assert any("Cycle" in error for error in errors)


class TestSequentialExecution:
    def test_run_sequential_propagates_dict_state(self) -> None:
        received = {}

        def capture(state):
            received.update(state)
            return {}

        graph = WorkflowGraph()
        graph.add_node("a", _value({"x": 1}))
        graph.add_node("b", capture, deps=["a"])

        results = graph.run_sequential({})

        assert results["a"].error is None
        assert received["x"] == 1

    def test_run_sequential_captures_exception(self) -> None:
        graph = WorkflowGraph()
        graph.add_node("boom", _error("kaboom"))

        results = graph.run_sequential({})

        assert results["boom"].error == "kaboom"
        assert results["boom"].output is None


class TestParallelExecution:
    def test_run_parallel_respects_dependencies(self) -> None:
        order: list[str] = []

        def node(name: str):
            def inner(state):
                order.append(name)
                return {}

            return inner

        graph = WorkflowGraph()
        graph.add_node("a", node("a"))
        graph.add_node("b", node("b"))
        graph.add_node("c", node("c"), deps=["a", "b"])

        results = graph.run_parallel({})

        assert results["c"].error is None
        assert order.index("c") > order.index("a")
        assert order.index("c") > order.index("b")

    def test_run_parallel_captures_exception(self) -> None:
        graph = WorkflowGraph()
        graph.add_node("bad", _error("parallel-boom"))

        results = graph.run_parallel({})

        assert results["bad"].error == "parallel-boom"


class TestNodeMerge:
    def test_node_merge_combines_dicts_and_scalars(self) -> None:
        graph = WorkflowGraph()
        results = {
            "a": WorkflowResult("a", {"x": 1}, None, 0.0),
            "b": WorkflowResult("b", 42, None, 0.0),
            "c": WorkflowResult("c", None, "oops", 0.0),
        }

        merged = graph.node_merge(results)

        assert merged == {"x": 1, "b": 42}

    def test_node_merge_empty(self) -> None:
        graph = WorkflowGraph()

        assert graph.node_merge({}) == {}
