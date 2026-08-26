"""Claude API call + structured-output validation (SPEC.md Section 2.2, Section 6).

Replaces the retired keyword/regex matcher (`matcher.py` / `dimension_indicators.py`).
One Claude API call scores all ten rubric dimensions for a single validation request.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import anthropic

from config import Config
from validation.errors import InvalidApiKeyError, LLMServiceError
from validation.rubric_loader import RubricSet

NO_EVIDENCE_TEXT = (
    "N/E - no evidence: the record provides no evidence either way for this dimension."
)

VALID_SCORES = {1, 2, 3, 4, 5, "N/E"}

# The SDK's own default read timeout is 600s -- far too long for a synchronous
# request/response web app. A stalled (not actively refused) network path would
# otherwise leave the user staring at a spinner for up to ten minutes with no
# error. 60s is generous for a single non-streaming call and still fails fast
# enough to surface as a clear 502 llm_service_error (SPEC.md Section 6.3).
REQUEST_TIMEOUT_SECONDS = 60.0

# The key-check call (SPEC.md Section 4.1.1) is a metadata lookup, not a
# scoring call -- it should fail fast well before a full scoring call would.
KEY_CHECK_TIMEOUT_SECONDS = 15.0

_SCORE_TOOL_NAME = "score_rubric_dimensions"

_SCORE_TOOL = {
    "name": _SCORE_TOOL_NAME,
    "description": (
        "Record the CDI rubric score for every dimension, based solely on the "
        "supplied record text and each dimension's five level descriptions."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "dimensions": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "rubric_id": {"type": "string"},
                        "score": {
                            "anyOf": [
                                {"type": "integer", "enum": [1, 2, 3, 4, 5]},
                                {"type": "string", "enum": ["N/E"]},
                            ]
                        },
                        "evidence_quote": {"type": ["string", "null"]},
                    },
                    "required": ["rubric_id", "score", "evidence_quote"],
                },
            }
        },
        "required": ["dimensions"],
    },
}


@dataclass(frozen=True)
class DimensionJudgment:
    score: int | str  # int 1-5, or the literal "N/E"
    matched_level_text: str
    matched_snippet: str | None


def _build_prompt(rubric: RubricSet, text: str) -> str:
    dimension_blocks = []
    for dimension in rubric.rubrics:
        levels_text = "\n".join(
            f"  Level {level}: {dimension.levels[level]}"
            for level in sorted(dimension.levels, key=int, reverse=True)
        )
        dimension_blocks.append(
            f"{dimension.id} - {dimension.name}\nQuestion: {dimension.question}\n{levels_text}"
        )
    dimensions_text = "\n\n".join(dimension_blocks)

    return (
        "You are scoring a single medical record against a clinical documentation "
        "integrity rubric. For EVERY dimension listed below, select the single "
        'best-fitting level (5, 4, 3, 2, or 1) based on its prose description, or '
        '"N/E" if the record provides no evidence either way for that dimension. '
        f"Call the {_SCORE_TOOL_NAME} tool exactly once with one entry per "
        "dimension, in the order given. For each dimension, evidence_quote must be "
        'either null (when score is "N/E") or a short excerpt copied VERBATIM '
        "from the record text below that supports the chosen score -- do not "
        "paraphrase or invent it.\n\n"
        f"RUBRIC DIMENSIONS:\n{dimensions_text}\n\n"
        f"RECORD TEXT:\n{text}"
    )


def _extract_tool_input(message: Any) -> dict:
    for block in message.content:
        if getattr(block, "type", None) == "tool_use" and block.name == _SCORE_TOOL_NAME:
            return block.input
    raise LLMServiceError("Claude did not return the expected structured response.")


def _parse_tool_response(message: Any, rubric: RubricSet) -> dict[str, dict]:
    payload = _extract_tool_input(message)
    dimensions = payload.get("dimensions")
    if not isinstance(dimensions, list):
        raise LLMServiceError("Claude's response was missing the dimensions array.")

    by_id: dict[str, dict] = {}
    for entry in dimensions:
        if not isinstance(entry, dict):
            raise LLMServiceError("Claude's response contained a malformed dimension entry.")
        rubric_id = entry.get("rubric_id")
        score = entry.get("score")
        if score not in VALID_SCORES:
            raise LLMServiceError(f"Claude returned an invalid score for {rubric_id!r}.")
        by_id[rubric_id] = entry

    expected_ids = {dimension.id for dimension in rubric.rubrics}
    if set(by_id) != expected_ids:
        raise LLMServiceError("Claude's response did not cover all ten rubric dimensions.")

    return by_id


def _judgments_from_response(rubric: RubricSet, text: str, by_id: dict[str, dict]) -> dict[str, DimensionJudgment]:
    text_lower = text.lower()
    results: dict[str, DimensionJudgment] = {}

    for dimension in rubric.rubrics:
        entry = by_id[dimension.id]
        score = entry["score"]
        evidence_quote = entry.get("evidence_quote")

        if score == "N/E":
            # SPEC.md Section 3: matched_snippet is unconditionally null for N/E,
            # regardless of what the model returned for evidence_quote.
            matched_level_text = NO_EVIDENCE_TEXT
            matched_snippet = None
        else:
            matched_level_text = dimension.levels[str(score)]
            matched_snippet = None
            if evidence_quote and evidence_quote.lower() in text_lower:
                matched_snippet = evidence_quote

        results[dimension.id] = DimensionJudgment(
            score=score,
            matched_level_text=matched_level_text,
            matched_snippet=matched_snippet,
        )

    return results


def _translate_anthropic_errors(fn, timeout_seconds: float):
    """Run fn() and translate any Claude API failure into InvalidApiKeyError/LLMServiceError.

    Shared by judge_record and validate_api_key so both raise only these two
    types, never a raw exception that would surface as an opaque 500 to the
    caller (SPEC.md Section 6.3). Everything that can go wrong -- client
    construction, the network call, response validation -- must happen inside
    fn() to be covered by this.
    """
    try:
        return fn()
    except anthropic.AuthenticationError as exc:
        raise InvalidApiKeyError() from exc
    except anthropic.APITimeoutError as exc:
        raise LLMServiceError(
            f"The Claude API call timed out after {timeout_seconds:.0f}s. "
            "Check that this server has outbound network access to api.anthropic.com "
            "(corporate proxy/firewall settings are the most common cause)."
        ) from exc
    except anthropic.APIError as exc:
        raise LLMServiceError(f"Claude API call failed: {exc}") from exc
    except LLMServiceError:
        raise  # already classified (e.g. by _parse_tool_response) -- pass through as-is
    except Exception as exc:
        # Catch-all for anything not modeled above (e.g. a broken local TLS/CA
        # configuration raising FileNotFoundError out of ssl.create_default_context
        # during client construction) -- still a Claude-call failure from the
        # caller's perspective, so it gets the same 502 treatment, not a raw 500.
        raise LLMServiceError(f"Unexpected error while calling the Claude API: {exc}") from exc


def judge_record(rubric: RubricSet, text: str, api_key: str) -> dict[str, DimensionJudgment]:
    """Call the Claude API once and return a judgment for every rubric dimension."""
    prompt = _build_prompt(rubric, text)

    def _call():
        client = anthropic.Anthropic(api_key=api_key, timeout=REQUEST_TIMEOUT_SECONDS)
        # No `temperature` param: Config.CLAUDE_MODEL (claude-sonnet-5) rejects it
        # as deprecated -- SPEC.md Section 2.2's "temperature 0" decision no longer
        # applies to this model generation; see SPEC.md's determinism note instead.
        message = client.messages.create(
            model=Config.CLAUDE_MODEL,
            max_tokens=4096,
            tools=[_SCORE_TOOL],
            tool_choice={"type": "tool", "name": _SCORE_TOOL_NAME},
            messages=[{"role": "user", "content": prompt}],
        )
        by_id = _parse_tool_response(message, rubric)
        return _judgments_from_response(rubric, text, by_id)

    return _translate_anthropic_errors(_call, REQUEST_TIMEOUT_SECONDS)


def validate_api_key(api_key: str) -> None:
    """Confirm the Claude API accepts this key, without scoring anything (SPEC.md Section 4.1.1).

    A pure authentication check against GET /v1/models -- no tokens consumed,
    no record content involved (there is none at this point). Raises
    InvalidApiKeyError or LLMServiceError; returns None on success.
    """

    def _call():
        client = anthropic.Anthropic(api_key=api_key, timeout=KEY_CHECK_TIMEOUT_SECONDS)
        client.models.list(limit=1)

    _translate_anthropic_errors(_call, KEY_CHECK_TIMEOUT_SECONDS)
