"""Loads and validates med_record_rubrics.json exactly once, at app startup.

This module never writes to the rubric file, never reloads it per-request,
and never modifies its structure — it only parses the fixed file into
typed, in-memory dataclasses for the LLM judge and scorer to consume.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Scale:
    min: int
    max: int
    meaning: str


@dataclass(frozen=True)
class RubricDimension:
    id: str
    name: str
    weight: int
    question: str
    reference: str
    levels: dict[str, str]  # keyed "1".."5"
    hard_rule: str | None = None
    primary_metric: str | None = None


@dataclass(frozen=True)
class DecisionBand:
    min: int
    max: int
    decision: str
    note: str


@dataclass(frozen=True)
class HardRule:
    id: str
    rubric_id: str
    trigger: str
    action: str
    reason: str


@dataclass(frozen=True)
class RubricSet:
    title: str
    version: str
    framework: str
    scale: Scale
    rubrics: list[RubricDimension] = field(default_factory=list)
    decision_bands: list[DecisionBand] = field(default_factory=list)
    severity_order: list[str] = field(default_factory=list)
    hard_rules: list[HardRule] = field(default_factory=list)

    def dimension_by_id(self, rubric_id: str) -> RubricDimension:
        for dimension in self.rubrics:
            if dimension.id == rubric_id:
                return dimension
        raise KeyError(f"Unknown rubric dimension id: {rubric_id}")


_rubric_cache: RubricSet | None = None


def _parse_rubric(raw: dict) -> RubricSet:
    scale = Scale(**raw["scale"])
    dimensions = [
        RubricDimension(
            id=item["id"],
            name=item["name"],
            weight=item["weight"],
            question=item["question"],
            reference=item["reference"],
            levels=item["levels"],
            hard_rule=item.get("hard_rule"),
            primary_metric=item.get("primary_metric"),
        )
        for item in raw["rubrics"]
    ]
    decision_bands = [DecisionBand(**band) for band in raw["decision_bands"]]
    hard_rules = [HardRule(**rule) for rule in raw["hard_rules"]]

    return RubricSet(
        title=raw["title"],
        version=raw["version"],
        framework=raw["framework"],
        scale=scale,
        rubrics=dimensions,
        decision_bands=decision_bands,
        severity_order=raw["severity_order"],
        hard_rules=hard_rules,
    )


def load_rubric(path: str) -> RubricSet:
    """Read and parse the rubric file. Intended to be called once, at startup."""
    global _rubric_cache
    with open(path, "r", encoding="utf-8") as handle:
        raw = json.load(handle)
    _rubric_cache = _parse_rubric(raw)
    return _rubric_cache


def get_rubric() -> RubricSet:
    """Return the in-memory rubric loaded by ``load_rubric``."""
    if _rubric_cache is None:
        raise RuntimeError("Rubric not loaded. Call load_rubric() during app startup.")
    return _rubric_cache
