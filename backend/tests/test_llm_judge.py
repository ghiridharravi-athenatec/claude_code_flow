"""Unit tests for the Claude API judging module (SPEC.md Section 2.2, Section 6).

The Anthropic client is always mocked here -- these tests never make a real
network call and never need a real API key (CLAUDE.md's LLM API key rules).
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import anthropic
import httpx
import pytest

from validation.errors import InvalidApiKeyError, LLMServiceError
from validation.llm_judge import NO_EVIDENCE_TEXT, judge_record, validate_api_key
from validation.rubric_loader import load_rubric

RUBRIC_PATH = Path(__file__).parent.parent / "med_record_rubrics.json"
FAKE_API_KEY = "sk-ant-test-not-a-real-key"


@pytest.fixture(scope="module")
def rubric():
    return load_rubric(str(RUBRIC_PATH))


def _tool_use_message(dimensions: list[dict]):
    block = SimpleNamespace(type="tool_use", name="score_rubric_dimensions", input={"dimensions": dimensions})
    return SimpleNamespace(content=[block])


def _all_ne(rubric, overrides: dict | None = None) -> list[dict]:
    overrides = overrides or {}
    entries = []
    for dimension in rubric.rubrics:
        if dimension.id in overrides:
            entries.append(overrides[dimension.id])
        else:
            entries.append({"rubric_id": dimension.id, "score": "N/E", "evidence_quote": None})
    return entries


@patch("validation.llm_judge.anthropic.Anthropic")
def test_judge_record_returns_verified_snippet(mock_anthropic_cls, rubric):
    text = "Electronically signed by Jane Smith, MD, on 03/14/2026."
    entries = _all_ne(
        rubric,
        {
            "R1": {
                "rubric_id": "R1",
                "score": 5,
                "evidence_quote": "Electronically signed by Jane Smith, MD",
            }
        },
    )
    mock_client = MagicMock()
    mock_client.messages.create.return_value = _tool_use_message(entries)
    mock_anthropic_cls.return_value = mock_client

    results = judge_record(rubric, text, FAKE_API_KEY)

    assert results["R1"].score == 5
    assert results["R1"].matched_level_text == rubric.dimension_by_id("R1").levels["5"]
    assert results["R1"].matched_snippet == "Electronically signed by Jane Smith, MD"
    mock_anthropic_cls.assert_called_once_with(api_key=FAKE_API_KEY, timeout=60.0)


@patch("validation.llm_judge.anthropic.Anthropic")
def test_judge_record_nulls_unverified_snippet(mock_anthropic_cls, rubric):
    text = "The record contains no such phrase anywhere."
    entries = _all_ne(
        rubric,
        {"R1": {"rubric_id": "R1", "score": 4, "evidence_quote": "a quote that is not in the text"}},
    )
    mock_client = MagicMock()
    mock_client.messages.create.return_value = _tool_use_message(entries)
    mock_anthropic_cls.return_value = mock_client

    results = judge_record(rubric, text, FAKE_API_KEY)

    assert results["R1"].score == 4
    assert results["R1"].matched_snippet is None


@patch("validation.llm_judge.anthropic.Anthropic")
def test_judge_record_ne_score_never_has_a_snippet(mock_anthropic_cls, rubric):
    text = "Electronically signed by Jane Smith, MD."
    # A misbehaving model returns a quote alongside N/E -- must still be nulled.
    entries = _all_ne(
        rubric,
        {"R1": {"rubric_id": "R1", "score": "N/E", "evidence_quote": "Electronically signed by Jane Smith, MD"}},
    )
    mock_client = MagicMock()
    mock_client.messages.create.return_value = _tool_use_message(entries)
    mock_anthropic_cls.return_value = mock_client

    results = judge_record(rubric, text, FAKE_API_KEY)

    assert results["R1"].score == "N/E"
    assert results["R1"].matched_snippet is None
    assert results["R1"].matched_level_text == NO_EVIDENCE_TEXT


@patch("validation.llm_judge.anthropic.Anthropic")
def test_judge_record_raises_invalid_api_key_on_auth_error(mock_anthropic_cls, rubric):
    response = httpx.Response(401, request=httpx.Request("POST", "https://api.anthropic.com/v1/messages"))
    mock_client = MagicMock()
    mock_client.messages.create.side_effect = anthropic.AuthenticationError(
        "invalid x-api-key", response=response, body=None
    )
    mock_anthropic_cls.return_value = mock_client

    with pytest.raises(InvalidApiKeyError):
        judge_record(rubric, "some text", FAKE_API_KEY)


@patch("validation.llm_judge.anthropic.Anthropic")
def test_judge_record_raises_llm_service_error_on_client_construction_failure(mock_anthropic_cls, rubric):
    # Regression test: a broken local TLS/CA config raised FileNotFoundError out
    # of ssl.create_default_context during anthropic.Anthropic(...) construction
    # in production -- that's not an anthropic.* exception, and client
    # construction used to happen outside the try block, so it leaked out as an
    # unhandled 500 instead of a 502 llm_service_error.
    mock_anthropic_cls.side_effect = FileNotFoundError("[Errno 2] No such file or directory")

    with pytest.raises(LLMServiceError):
        judge_record(rubric, "some text", FAKE_API_KEY)


@patch("validation.llm_judge.anthropic.Anthropic")
def test_judge_record_raises_llm_service_error_on_connection_failure(mock_anthropic_cls, rubric):
    request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    mock_client = MagicMock()
    mock_client.messages.create.side_effect = anthropic.APIConnectionError(request=request)
    mock_anthropic_cls.return_value = mock_client

    with pytest.raises(LLMServiceError):
        judge_record(rubric, "some text", FAKE_API_KEY)


@patch("validation.llm_judge.anthropic.Anthropic")
def test_judge_record_raises_llm_service_error_on_missing_dimension(mock_anthropic_cls, rubric):
    entries = _all_ne(rubric)[1:]  # drop R1
    mock_client = MagicMock()
    mock_client.messages.create.return_value = _tool_use_message(entries)
    mock_anthropic_cls.return_value = mock_client

    with pytest.raises(LLMServiceError):
        judge_record(rubric, "some text", FAKE_API_KEY)


@patch("validation.llm_judge.anthropic.Anthropic")
def test_judge_record_raises_llm_service_error_on_invalid_score_value(mock_anthropic_cls, rubric):
    entries = _all_ne(rubric, {"R1": {"rubric_id": "R1", "score": 7, "evidence_quote": None}})
    mock_client = MagicMock()
    mock_client.messages.create.return_value = _tool_use_message(entries)
    mock_anthropic_cls.return_value = mock_client

    with pytest.raises(LLMServiceError):
        judge_record(rubric, "some text", FAKE_API_KEY)


@patch("validation.llm_judge.anthropic.Anthropic")
def test_judge_record_raises_llm_service_error_when_no_tool_use_block(mock_anthropic_cls, rubric):
    mock_client = MagicMock()
    mock_client.messages.create.return_value = SimpleNamespace(
        content=[SimpleNamespace(type="text", text="I refuse to use the tool.")]
    )
    mock_anthropic_cls.return_value = mock_client

    with pytest.raises(LLMServiceError):
        judge_record(rubric, "some text", FAKE_API_KEY)


@patch("validation.llm_judge.anthropic.Anthropic")
def test_judge_record_forces_tool_choice_and_omits_deprecated_temperature(mock_anthropic_cls, rubric):
    mock_client = MagicMock()
    mock_client.messages.create.return_value = _tool_use_message(_all_ne(rubric))
    mock_anthropic_cls.return_value = mock_client

    judge_record(rubric, "some text", FAKE_API_KEY)

    _, kwargs = mock_client.messages.create.call_args
    # claude-sonnet-5 rejects `temperature` as deprecated -- it must never be sent.
    assert "temperature" not in kwargs
    assert kwargs["tool_choice"] == {"type": "tool", "name": "score_rubric_dimensions"}
    assert kwargs["tools"][0]["name"] == "score_rubric_dimensions"


# --- validate_api_key (SPEC.md Section 4.1.1) -------------------------------


@patch("validation.llm_judge.anthropic.Anthropic")
def test_validate_api_key_succeeds_without_raising(mock_anthropic_cls):
    mock_client = MagicMock()
    mock_client.models.list.return_value = SimpleNamespace(data=[])
    mock_anthropic_cls.return_value = mock_client

    validate_api_key(FAKE_API_KEY)  # must not raise

    mock_anthropic_cls.assert_called_once_with(api_key=FAKE_API_KEY, timeout=15.0)
    _, kwargs = mock_client.models.list.call_args
    assert kwargs["limit"] == 1


@patch("validation.llm_judge.anthropic.Anthropic")
def test_validate_api_key_raises_invalid_api_key_on_auth_error(mock_anthropic_cls):
    response = httpx.Response(401, request=httpx.Request("GET", "https://api.anthropic.com/v1/models"))
    mock_client = MagicMock()
    mock_client.models.list.side_effect = anthropic.AuthenticationError(
        "invalid x-api-key", response=response, body=None
    )
    mock_anthropic_cls.return_value = mock_client

    with pytest.raises(InvalidApiKeyError):
        validate_api_key(FAKE_API_KEY)


@patch("validation.llm_judge.anthropic.Anthropic")
def test_validate_api_key_raises_llm_service_error_on_connection_failure(mock_anthropic_cls):
    request = httpx.Request("GET", "https://api.anthropic.com/v1/models")
    mock_client = MagicMock()
    mock_client.models.list.side_effect = anthropic.APIConnectionError(request=request)
    mock_anthropic_cls.return_value = mock_client

    with pytest.raises(LLMServiceError):
        validate_api_key(FAKE_API_KEY)


@patch("validation.llm_judge.anthropic.Anthropic")
def test_validate_api_key_never_calls_messages_create(mock_anthropic_cls):
    # A key check must never score anything or consume tokens.
    mock_client = MagicMock()
    mock_client.models.list.return_value = SimpleNamespace(data=[])
    mock_anthropic_cls.return_value = mock_client

    validate_api_key(FAKE_API_KEY)

    mock_client.messages.create.assert_not_called()
