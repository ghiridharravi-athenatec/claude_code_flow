"""Dataclasses mirroring the response schema in SPEC.md Section 3.

These are the canonical structured types passed between ``validation/`` and
``routes/validate.py`` — no bare dicts standing in for a validation result.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Union

DimensionScore = Union[int, str]  # int 1-5, or the literal string "N/E"


@dataclass
class HardRuleTriggered:
    id: str
    rubric_id: str
    action: str
    reason: str


@dataclass
class DimensionResult:
    rubric_id: str
    name: str
    weight: int
    score: DimensionScore
    points_earned: float
    matched_level_text: str
    matched_snippet: str | None
    hard_rule_triggered: str | None


@dataclass
class FlaggedGap:
    rubric_id: str
    name: str
    weight: int
    score: DimensionScore


@dataclass
class OverallResult:
    score_points: float
    score_max: int
    decision: str
    decision_note: str
    hard_rules_triggered: list[HardRuleTriggered] = field(default_factory=list)


@dataclass
class ValidationResult:
    record_filename: str
    rubric_title: str
    rubric_version: str
    overall: OverallResult
    dimension_results: list[DimensionResult]
    flagged_gaps: list[FlaggedGap]
    processed_at: str

    def to_dict(self) -> dict:
        return asdict(self)
