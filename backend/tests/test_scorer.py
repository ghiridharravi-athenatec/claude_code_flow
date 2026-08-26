"""Unit tests for aggregation edge cases in scorer.py (SPEC.md Section 2.3)."""

from __future__ import annotations

from pathlib import Path

import pytest

from validation.rubric_loader import load_rubric
from validation.scorer import _decision_band_for_score

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
