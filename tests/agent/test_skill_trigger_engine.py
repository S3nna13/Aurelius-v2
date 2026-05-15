"""Tests for the Aurelius v2 skill trigger engine."""

from __future__ import annotations

import json

import pytest
from aurelius_cli.v2_cli import cmd_skills_suggest
from src.agent.skill_trigger_engine import SkillTriggerEngine, TriggerEngineError
from src.skills.manifest import SkillManifest, SkillStatus
from src.skills.registry import SkillEntry, SkillRegistry


def _manifest(skill_id: str, name: str, summary: str, tags: list[str]) -> SkillManifest:
    return SkillManifest(
        id=skill_id,
        name=name,
        version="1.0.0",
        category="testing",
        summary=summary,
        description=summary,
        status=SkillStatus.EXPERIMENTAL,
        tags=tags,
    )


class TestTriggerEngine:
    def test_match_empty_registry_returns_empty(self) -> None:
        engine = SkillTriggerEngine()
        result = engine.match("please review this code")
        assert result.matches == []

    def test_match_single_skill(self) -> None:
        registry = SkillRegistry()
        registry.register(_manifest("code.review", "Code Review", "Reviews code", ["review", "code"]))
        engine = SkillTriggerEngine(registry=registry)

        result = engine.match("please review this code")

        assert len(result.matches) == 1
        assert result.matches[0].skill_id == "code.review"
        assert result.matches[0].confidence > 0

    def test_match_multiple_skills_and_deduplicates(self) -> None:
        registry = SkillRegistry()
        registry.register(_manifest("code.review", "Code Review", "Reviews code", ["review", "code"]))
        registry.register(_manifest("test.generate", "Test Generator", "Generates tests", ["test"]))
        engine = SkillTriggerEngine(registry=registry)

        result = engine.match("review and test this code")

        assert {match.skill_id for match in result.matches} == {"code.review", "test.generate"}
        assert len(result.matches) == 2

    def test_non_string_text_raises(self) -> None:
        engine = SkillTriggerEngine()
        with pytest.raises(TypeError, match="str"):
            engine.match(123)  # type: ignore[arg-type]

    def test_internal_overlay_skills_are_matched(self) -> None:
        engine = SkillTriggerEngine()
        engine.add_skill(_manifest("internal.skill", "Internal Skill", "Internal workflow", ["internal"]))

        result = engine.match("run internal workflow now")

        assert len(result.matches) == 1
        assert result.matches[0].skill_id == "internal.skill"

    def test_remove_skill_missing_raises(self) -> None:
        engine = SkillTriggerEngine()
        with pytest.raises(TriggerEngineError, match="skill not found"):
            engine.remove_skill("missing.skill")

    def test_match_and_execute_returns_dry_run_result(self) -> None:
        registry = SkillRegistry()
        registry.register(_manifest("code.review", "Code Review", "Reviews code", ["review"]))
        engine = SkillTriggerEngine(registry=registry)

        result = engine.match_and_execute("please review this code")

        assert len(result.executed) == 1
        assert result.executed[0].success is True
        assert "Would execute" in result.executed[0].dry_run_details


class TestCliSkillsSuggest:
    def test_cmd_skills_suggest_outputs_json(self, monkeypatch, capsys) -> None:
        manifest = _manifest("code.review", "Code Review", "Reviews code", ["review", "code"])

        class FakeRegistry:
            def __init__(self) -> None:
                self._entries = [SkillEntry(manifest=manifest)]

            def discover_from_path(self, path: str | None = None) -> int:
                return 1

            def list_skills(self, category: str | None = None) -> list[SkillEntry]:
                return self._entries

        monkeypatch.setattr("src.skills.registry.SkillRegistry", FakeRegistry)

        rc = cmd_skills_suggest("please review this code")
        payload = json.loads(capsys.readouterr().out)

        assert rc == 0
        assert payload["count"] == 1
        assert payload["matches"][0]["skill_id"] == "code.review"
