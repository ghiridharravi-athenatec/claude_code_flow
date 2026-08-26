"""Golden regression suite for the aggregation pipeline (extraction fixtures + scorer.py).

Dimension scoring itself is now Claude-judged (SPEC.md Section 2.2), which is not
byte-for-byte deterministic, so `judge_record` is mocked here with the exact
judgments baked into each fixture's `.expected.json` -- this keeps the golden
suite testing what it always tested (deterministic aggregation: weighted points,
hard rules, decision bands, flagged gaps) without depending on a live LLM call.

Never edit a fixture (or its .expected.json) to make a failing test pass -- a
failure here means scorer.py's aggregation behavior changed. Confirm whether
that change was intended before touching the fixture (see CLAUDE.md).
"""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path
from unittest.mock import patch

import pytest

from validation.llm_judge import DimensionJudgment
from validation.rubric_loader import load_rubric
from validation.scorer import score_record

GOLDEN_DIR = Path(__file__).parent / "golden"
RUBRIC_PATH = Path(__file__).parent.parent / "med_record_rubrics.json"
FIXED_PROCESSED_AT = "2026-08-26T10:15:00Z"
FAKE_API_KEY = "sk-ant-test-not-a-real-key"

GOLDEN_CASES = [
    ("record_1.txt", "record_1.expected.json", "record_1.txt"),
    ("record_2.txt", "record_2.expected.json", "record_2.txt"),
]


@pytest.fixture(scope="module")
def rubric():
    return load_rubric(str(RUBRIC_PATH))


def _judgments_from_expected(expected: dict) -> dict[str, DimensionJudgment]:
    return {
        dim["rubric_id"]: DimensionJudgment(
            score=dim["score"],
            matched_level_text=dim["matched_level_text"],
            matched_snippet=dim["matched_snippet"],
        )
        for dim in expected["dimension_results"]
    }


@pytest.mark.parametrize("record_file,expected_file,filename", GOLDEN_CASES)
def test_golden_record(rubric, record_file, expected_file, filename):
    text = (GOLDEN_DIR / record_file).read_text(encoding="utf-8")
    expected = json.loads((GOLDEN_DIR / expected_file).read_text(encoding="utf-8"))
    fake_judgments = _judgments_from_expected(expected)

    with patch("validation.scorer.judge_record", return_value=fake_judgments) as mock_judge:
        result = score_record(rubric, filename, text, FIXED_PROCESSED_AT, FAKE_API_KEY)
        mock_judge.assert_called_once_with(rubric, text, FAKE_API_KEY)

    assert dataclasses.asdict(result) == expected
