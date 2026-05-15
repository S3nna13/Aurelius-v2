"""Aurelius v2 skill trigger engine.

This is a compact port of the original Aurelius trigger engine idea: match
incoming text against registered skills, then optionally dry-run or execute
matched skills via the v2 skill executor.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from src.skills.executor import SkillExecutor, SkillResult
from src.skills.manifest import SkillExecutionMode, SkillManifest, SkillStatus
from src.skills.registry import SkillRegistry


class TriggerEngineError(Exception):
    """Raised for invalid trigger engine operations."""


@dataclass(slots=True)
class MatchedSkill:
    """A skill that matched a trigger pattern against input text."""

    skill_id: str
    name: str
    trigger_pattern: str
    confidence: float = 1.0
    summary: str = ""


@dataclass(slots=True)
class TriggerResult:
    """Result of trigger matching and optional skill execution."""

    matches: list[MatchedSkill] = field(default_factory=list)
    executed: list[SkillResult] = field(default_factory=list)
    text: str = ""


class SkillTriggerEngine:
    """Match text against skill metadata and optionally execute matched skills."""

    def __init__(
        self,
        registry: SkillRegistry | None = None,
        executor: SkillExecutor | None = None,
    ) -> None:
        self.registry = registry
        self.executor = executor or SkillExecutor()
        self._skills: dict[str, SkillManifest] = {}

    def add_skill(self, skill_manifest: SkillManifest) -> None:
        """Register a skill in the engine's local overlay store."""
        self._skills[skill_manifest.id] = skill_manifest
        if self.registry is not None:
            self.registry.register(skill_manifest)

    def remove_skill(self, skill_id: str) -> None:
        """Remove a locally registered skill."""
        if skill_id not in self._skills:
            raise TriggerEngineError(f"skill not found: {skill_id!r}")
        del self._skills[skill_id]

    def match(self, text: str) -> TriggerResult:
        """Find skills whose metadata appears relevant to *text*."""
        if not isinstance(text, str):
            raise TypeError(f"text must be a str, got {type(text).__name__}")

        query = text.lower()
        query_tokens = set(re.findall(r"[a-z0-9_./-]+", query))
        seen: dict[str, MatchedSkill] = {}

        for manifest in self._iter_manifests():
            if manifest.status in {SkillStatus.UNSAFE, SkillStatus.DEPRECATED}:
                continue
            match = self._score_manifest(manifest, query, query_tokens)
            if match is None:
                continue
            skill_id, trigger_pattern, confidence = match
            seen.setdefault(
                skill_id,
                MatchedSkill(
                    skill_id=skill_id,
                    name=manifest.name,
                    trigger_pattern=trigger_pattern,
                    confidence=confidence,
                    summary=manifest.summary,
                ),
            )

        return TriggerResult(matches=list(seen.values()), text=text)

    def match_and_execute(
        self,
        text: str,
        context: Any | None = None,
        mode: SkillExecutionMode = SkillExecutionMode.DRY_RUN,
    ) -> TriggerResult:
        """Match *text* and run the matched skills through the v2 executor."""
        trigger_result = self.match(text)
        executed: list[SkillResult] = []

        for matched in trigger_result.matches:
            manifest = self._resolve_manifest(matched.skill_id)
            if manifest is None:
                continue
            try:
                result = self.executor.execute(
                    manifest,
                    mode=mode,
                    skill_callable=None,
                    inputs={"text": text, "matched": matched.trigger_pattern},
                    context=context,
                )
            except Exception as exc:  # pragma: no cover - defensive
                result = SkillResult(
                    skill_id=matched.skill_id,
                    mode=mode,
                    success=False,
                    error=str(exc),
                )
            executed.append(result)

        trigger_result.executed = executed
        return trigger_result

    def _iter_manifests(self) -> list[SkillManifest]:
        manifests: dict[str, SkillManifest] = {}

        if self.registry is not None:
            for entry in self.registry.list_skills():
                manifests[entry.manifest.id] = entry.manifest

        manifests.update(self._skills)
        return list(manifests.values())

    def _resolve_manifest(self, skill_id: str) -> SkillManifest | None:
        if skill_id in self._skills:
            return self._skills[skill_id]
        if self.registry is not None:
            entry = self.registry.get(skill_id)
            if entry is not None:
                return entry.manifest
        return None

    def _score_manifest(
        self,
        manifest: SkillManifest,
        query: str,
        query_tokens: set[str],
    ) -> tuple[str, str, float] | None:
        candidate_texts = [
            manifest.id,
            manifest.name,
            manifest.summary,
            manifest.description,
            " ".join(manifest.tags),
        ]
        best_pattern = ""
        best_score = 0.0

        for candidate in candidate_texts:
            if not candidate:
                continue
            candidate_lower = candidate.lower()
            if candidate_lower in query:
                score = min(1.0, 0.65 + len(candidate_lower) / 120.0)
            else:
                tokens = set(re.findall(r"[a-z0-9_./-]+", candidate_lower))
                overlap = query_tokens & tokens
                if not overlap:
                    continue
                score = min(1.0, 0.35 + (len(overlap) * 0.15))
            if score > best_score:
                best_pattern = candidate
                best_score = score

        if best_score == 0.0:
            return None
        return manifest.id, best_pattern, best_score


DEFAULT_TRIGGER_ENGINE: SkillTriggerEngine = SkillTriggerEngine(SkillRegistry())

TRIGGER_ENGINE_REGISTRY: dict[str, SkillTriggerEngine] = {
    "default": DEFAULT_TRIGGER_ENGINE,
}


__all__ = [
    "DEFAULT_TRIGGER_ENGINE",
    "TRIGGER_ENGINE_REGISTRY",
    "MatchedSkill",
    "SkillTriggerEngine",
    "TriggerEngineError",
    "TriggerResult",
]
