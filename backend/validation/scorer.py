"""Aggregation of Claude-judged dimension scores into the overall result (SPEC.md 2.3, Section 3)."""

from __future__ import annotations

import re

from schemas.validation_result import (
    DimensionResult,
    FlaggedGap,
    HardRuleTriggered,
    OverallResult,
    ValidationResult,
)
from validation.llm_judge import judge_record
from validation.rubric_loader import HardRule, RubricSet

GAP_SCORES = {"N/E", 1, 2}
HARD_RULE_TRIGGER_PATTERN = re.compile(r"score equals (\d+)", re.IGNORECASE)


def _points_earned(score: int | str, weight: int) -> float:
    if score == "N/E":
        return 0.0
    return round((score / 5) * weight, 1)


def _hard_rule_triggered(rule: HardRule, dimension_scores: dict[str, int | str]) -> bool:
    match = HARD_RULE_TRIGGER_PATTERN.search(rule.trigger)
    if not match:
        return False
    required_score = int(match.group(1))
    actual_score = dimension_scores.get(rule.rubric_id)
    return actual_score == required_score


def _resolve_final_decision(
    triggered_rules: list[HardRule],
    weighted_decision: str,
    severity_order: list[str],
) -> str:
    if not triggered_rules:
        return weighted_decision
    return max(triggered_rules, key=lambda rule: severity_order.index(rule.action)).action


def _decision_band_for_score(rubric: RubricSet, overall_score: float) -> tuple[str, str]:
    # The rubric's decision_bands use adjacent integer min/max (e.g. 58-73, 74-87),
    # but overall_score is a float rounded to 1 decimal -- a strict `min <= score
    # <= max` check leaves gaps at every boundary (e.g. 73.6 matches nothing).
    # Sorting descending by `min` and taking the first band the score clears
    # closes every gap without changing which band any score was ever meant to
    # land in.
    for band in sorted(rubric.decision_bands, key=lambda b: b.min, reverse=True):
        if overall_score >= band.min:
            return band.decision, band.note
    raise ValueError(f"No decision band covers overall score {overall_score}")


def _note_for_decision(rubric: RubricSet, decision: str) -> str:
    for band in rubric.decision_bands:
        if band.decision == decision:
            return band.note
    return ""


def score_record(
    rubric: RubricSet, record_filename: str, text: str, processed_at: str, api_key: str
) -> ValidationResult:
    """Get a Claude-judged score for all ten dimensions and aggregate into a ValidationResult."""
    judgments = judge_record(rubric, text, api_key)

    dimension_results: list[DimensionResult] = []
    flagged_gaps: list[FlaggedGap] = []
    dimension_scores: dict[str, int | str] = {}
    total_points = 0.0

    for dimension in rubric.rubrics:
        judgment = judgments[dimension.id]
        points = _points_earned(judgment.score, dimension.weight)
        total_points += points
        dimension_scores[dimension.id] = judgment.score

        dimension_results.append(
            DimensionResult(
                rubric_id=dimension.id,
                name=dimension.name,
                weight=dimension.weight,
                score=judgment.score,
                points_earned=points,
                matched_level_text=judgment.matched_level_text,
                matched_snippet=judgment.matched_snippet,
                hard_rule_triggered=None,  # filled in below once hard rules are evaluated
            )
        )

        if judgment.score in GAP_SCORES:
            flagged_gaps.append(
                FlaggedGap(
                    rubric_id=dimension.id,
                    name=dimension.name,
                    weight=dimension.weight,
                    score=judgment.score,
                )
            )

    triggered_rules = [
        rule for rule in rubric.hard_rules if _hard_rule_triggered(rule, dimension_scores)
    ]
    triggered_by_dimension = {rule.rubric_id: rule.id for rule in triggered_rules}
    for result in dimension_results:
        result.hard_rule_triggered = triggered_by_dimension.get(result.rubric_id)

    overall_score = round(total_points, 1)
    weighted_decision, _ = _decision_band_for_score(rubric, overall_score)
    final_decision = _resolve_final_decision(triggered_rules, weighted_decision, rubric.severity_order)
    decision_note = _note_for_decision(rubric, final_decision)

    overall = OverallResult(
        score_points=overall_score,
        score_max=100,
        decision=final_decision,
        decision_note=decision_note,
        hard_rules_triggered=[
            HardRuleTriggered(id=r.id, rubric_id=r.rubric_id, action=r.action, reason=r.reason)
            for r in triggered_rules
        ],
    )

    return ValidationResult(
        record_filename=record_filename,
        rubric_title=rubric.title,
        rubric_version=rubric.version,
        overall=overall,
        dimension_results=dimension_results,
        flagged_gaps=flagged_gaps,
        processed_at=processed_at,
    )
