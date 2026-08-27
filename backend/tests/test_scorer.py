"""Unit tests for aggregation edge cases in scorer.py (SPEC.md Section 2.3)."""

from __future__ import annotations

from pathlib import Path

import pytest

from validation.rubric_loader import load_rubric
from validation.scorer import _decision_band_for_score, _points_earned, _round_half_up

RUBRIC_PATH = Path(__file__).parent.parent / "med_record_rubrics.json"


@pytest.fixture(scope="module")
def rubric():
    return load_rubric(str(RUBRIC_PATH))


@pytest.mark.parametrize(
    "score,expected_decision",
    [
        (100.0, "DOCUMENTATION ACCEPTED"),
        (88.0, "DOCUMENTATION ACCEPTED"),
        (87.9, "ACCEPTED WITH QUERY"),
        (74.0, "ACCEPTED WITH QUERY"),
        (73.6, "RETURN FOR CLARIFICATION"),  # the exact value that crashed in production
        (58.0, "RETURN FOR CLARIFICATION"),
        (57.9, "DEFICIENT"),
        (0.0, "DEFICIENT"),
    ],
)
def test_decision_band_covers_every_fractional_score(rubric, score, expected_decision):
    """decision_bands are defined with adjacent integer min/max (58-73, 74-87, ...),
    but overall_score is a rounded float -- every boundary used to have a gap
    that matched no band at all (e.g. 73.6). This locks in the fix."""
    decision, _ = _decision_band_for_score(rubric, score)
    assert decision == expected_decision


@pytest.mark.parametrize(
    "value,expected",
    [
        (0.25, 0.3),
        (0.75, 0.8),
        (1.25, 1.3),
        (2.25, 2.3),
        (73.65, 73.7),
    ],
)
def test_round_half_up_matches_expected(value, expected):
    assert _round_half_up(value, 1) == expected


@pytest.mark.parametrize("value", [0.25, 1.25, 2.25])
def test_round_half_up_diverges_from_bankers_rounding(value):
    """These are the cases where Python's builtin round() (banker's rounding,
    round-half-to-even) disagrees with half-up -- e.g. round(2.25, 1) is 2.2, not
    2.3. SPEC.md Section 2.3 requires half-up. This locks in the fix."""
    assert round(value, 1) != _round_half_up(value, 1)


def test_points_earned_rounds_half_up():
    assert _points_earned(3, 15) == 9.0
    assert _points_earned("N/E", 20) == 0.0
