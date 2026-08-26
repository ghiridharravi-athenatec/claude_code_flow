"""API-level tests against the Flask test client (SPEC.md Section 4).

MIME sniffing (``python-magic``) depends on the native ``libmagic`` library,
which is not guaranteed to be present in every dev/CI environment (notably
Windows without a separate libmagic install). These tests monkeypatch
``magic.from_buffer`` so the route-level contract can be verified without
that native dependency -- the sniffing behavior itself belongs to
``extraction/detect.py`` and is out of scope for these tests.

Dimension scoring is Claude-judged (SPEC.md Section 2.2); these tests mock
``validation.scorer.judge_record`` so no test makes a real network call or
needs a real Anthropic API key (CLAUDE.md's LLM API key rules).
"""

from __future__ import annotations

import io
from unittest.mock import patch

import pytest

import extraction.detect as detect_module
from app import create_app
from config import Config
from validation.errors import InvalidApiKeyError, LLMServiceError
from validation.llm_judge import NO_EVIDENCE_TEXT, DimensionJudgment
from validation.rubric_loader import load_rubric


class TestConfig(Config):
    ALLOWED_ORIGIN = "http://localhost:3000"
    MAX_FILE_SIZE_MB = 10
    MAX_FILE_SIZE_BYTES = 10 * 1024 * 1024


FAKE_API_KEY = "sk-ant-test-not-a-real-key"


def _fake_mime_sniff(file_bytes: bytes, mime: bool = True) -> str:
    if file_bytes.startswith(b"%PDF"):
        return "application/pdf"
    if file_bytes.startswith(b"PK"):
        return "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    if file_bytes.startswith(b"\x89PNG"):
        return "image/png"
    return "text/plain"


def _all_ne_judgments() -> dict[str, DimensionJudgment]:
    rubric = load_rubric(str(Config.RUBRIC_PATH))
    return {
        dimension.id: DimensionJudgment(score="N/E", matched_level_text=NO_EVIDENCE_TEXT, matched_snippet=None)
        for dimension in rubric.rubrics
    }


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(detect_module.magic, "from_buffer", _fake_mime_sniff)
    app = create_app(TestConfig)
    app.testing = True
    return app.test_client()


def test_health(client):
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    assert response.get_json() == {"status": "ok"}


def test_rubrics(client):
    response = client.get("/api/v1/rubrics")
    body = response.get_json()

    assert response.status_code == 200
    assert body["rubric_title"]
    assert body["rubric_version"] == "1.0"
    assert len(body["dimensions"]) == 10
    assert body["dimensions"][0] == {
        "rubric_id": "R1",
        "name": "Authentication and Legal Integrity",
        "weight": 8,
    }
    assert "levels" not in body["dimensions"][0]


def test_validate_missing_file_returns_400(client):
    response = client.post("/api/v1/validate", data={}, content_type="multipart/form-data")
    body = response.get_json()

    assert response.status_code == 400
    assert body["error"] == "missing_field"


def test_validate_missing_api_key_returns_400(client):
    data = {"file": (io.BytesIO(b"some record content here"), "record.txt")}
    response = client.post("/api/v1/validate", data=data, content_type="multipart/form-data")
    body = response.get_json()

    assert response.status_code == 400
    assert body["error"] == "missing_api_key"


def test_validate_unsupported_type_returns_415(client):
    data = {
        "file": (io.BytesIO(b"\x89PNG\r\n\x1a\n not a real record"), "scan.png"),
        "anthropic_api_key": FAKE_API_KEY,
    }
    response = client.post("/api/v1/validate", data=data, content_type="multipart/form-data")
    body = response.get_json()

    assert response.status_code == 415
    assert body["error"] == "unsupported_file_type"


def test_validate_empty_content_returns_422(client):
    data = {"file": (io.BytesIO(b"   "), "blank.txt"), "anthropic_api_key": FAKE_API_KEY}
    response = client.post("/api/v1/validate", data=data, content_type="multipart/form-data")
    body = response.get_json()

    assert response.status_code == 422
    assert body["error"] == "extraction_failed"
    assert body["reason"] == "empty_content"


def test_validate_success_returns_full_schema(client):
    record_text = (
        "Electronically signed by Jane Smith, MD.\n"
        "Chief complaint: chest pain. HPI describes location, quality, severity, and duration.\n"
    )
    data = {
        "file": (io.BytesIO(record_text.encode("utf-8")), "record.txt"),
        "anthropic_api_key": FAKE_API_KEY,
    }

    with patch("validation.scorer.judge_record", return_value=_all_ne_judgments()) as mock_judge:
        response = client.post("/api/v1/validate", data=data, content_type="multipart/form-data")
        assert mock_judge.call_args.args[2] == FAKE_API_KEY

    body = response.get_json()

    assert response.status_code == 200
    assert body["record_filename"] == "record.txt"
    assert set(body.keys()) == {
        "record_filename",
        "rubric_title",
        "rubric_version",
        "overall",
        "dimension_results",
        "flagged_gaps",
        "processed_at",
    }
    assert len(body["dimension_results"]) == 10
    assert [d["rubric_id"] for d in body["dimension_results"]] == [f"R{i}" for i in range(1, 11)]


def test_validate_invalid_api_key_returns_401(client):
    data = {"file": (io.BytesIO(b"some record content here"), "record.txt"), "anthropic_api_key": "sk-ant-bad-key"}

    with patch("validation.scorer.judge_record", side_effect=InvalidApiKeyError()):
        response = client.post("/api/v1/validate", data=data, content_type="multipart/form-data")

    body = response.get_json()
    assert response.status_code == 401
    assert body["error"] == "invalid_api_key"
    assert "sk-ant-bad-key" not in response.get_data(as_text=True)


def test_validate_llm_service_error_returns_502(client):
    data = {"file": (io.BytesIO(b"some record content here"), "record.txt"), "anthropic_api_key": FAKE_API_KEY}

    with patch("validation.scorer.judge_record", side_effect=LLMServiceError()):
        response = client.post("/api/v1/validate", data=data, content_type="multipart/form-data")

    body = response.get_json()
    assert response.status_code == 502
    assert body["error"] == "llm_service_error"


def test_validate_file_too_large_returns_413(client):
    oversized = b"x" * (TestConfig.MAX_FILE_SIZE_BYTES + 1)
    data = {"file": (io.BytesIO(oversized), "big.txt"), "anthropic_api_key": FAKE_API_KEY}
    response = client.post("/api/v1/validate", data=data, content_type="multipart/form-data")
    body = response.get_json()

    assert response.status_code == 413
    assert body["error"] == "file_too_large"


# --- POST /api/v1/api-key/validate (SPEC.md Section 4.1.1) ------------------


def test_validate_api_key_route_missing_key_returns_400(client):
    response = client.post("/api/v1/api-key/validate", json={})
    body = response.get_json()

    assert response.status_code == 400
    assert body["error"] == "missing_api_key"


def test_validate_api_key_route_success_returns_200(client):
    with patch("routes.validate.validate_api_key", return_value=None) as mock_check:
        response = client.post("/api/v1/api-key/validate", json={"anthropic_api_key": FAKE_API_KEY})
        mock_check.assert_called_once_with(FAKE_API_KEY)

    body = response.get_json()
    assert response.status_code == 200
    assert body == {"valid": True}


def test_validate_api_key_route_invalid_key_returns_401(client):
    with patch("routes.validate.validate_api_key", side_effect=InvalidApiKeyError()):
        response = client.post("/api/v1/api-key/validate", json={"anthropic_api_key": "sk-ant-bad-key"})

    body = response.get_json()
    assert response.status_code == 401
    assert body["error"] == "invalid_api_key"
    assert "sk-ant-bad-key" not in response.get_data(as_text=True)


def test_validate_api_key_route_service_error_returns_502(client):
    with patch("routes.validate.validate_api_key", side_effect=LLMServiceError()):
        response = client.post("/api/v1/api-key/validate", json={"anthropic_api_key": FAKE_API_KEY})

    body = response.get_json()
    assert response.status_code == 502
    assert body["error"] == "llm_service_error"
