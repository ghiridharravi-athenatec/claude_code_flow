"""POST /api/v1/validate + POST /api/v1/api-key/validate.

/validate runs extraction + LLM-judged validation in one synchronous call.
/api-key/validate is a live, no-cost pre-check for the Claude API key the
frontend collects before the upload step is shown (SPEC.md Section 4.1.1).
"""

from __future__ import annotations

import logging
import traceback
from datetime import datetime, timezone

from flask import Blueprint, current_app, jsonify, request

from extraction.detect import check_actual_size, check_content_length, detect_file_type
from extraction.docx_extractor import extract_docx_text
from extraction.errors import ExtractionError, ExtractionFailedError, FileTooLargeError, UnsupportedFileTypeError
from extraction.pdf_extractor import extract_pdf_text
from extraction.txt_extractor import extract_txt_text
from phi.redact import redact_for_logging
from validation.errors import InvalidApiKeyError, LLMServiceError
from validation.llm_judge import validate_api_key
from validation.rubric_loader import get_rubric
from validation.scorer import score_record

validate_bp = Blueprint("validate", __name__)
logger = logging.getLogger(__name__)

EXTRACTORS = {
    "pdf": extract_pdf_text,
    "docx": extract_docx_text,
    "txt": extract_txt_text,
}


def _error_response(status: int, error: str, message: str, reason: str | None = None):
    body = {"error": error, "message": message}
    if reason is not None:
        body["reason"] = reason
    return jsonify(body), status


@validate_bp.route("/validate", methods=["POST"])
def validate():
    if "file" not in request.files or request.files["file"].filename == "":
        return _error_response(400, "missing_field", "The 'file' field is required.")

    # Read but never log this -- CLAUDE.md's "LLM API key handling" rules apply
    # to every line touching this value, not just this one.
    api_key = request.form.get("anthropic_api_key", "").strip()
    if not api_key:
        return _error_response(
            400, "missing_api_key", "The 'anthropic_api_key' field is required."
        )

    upload = request.files["file"]
    max_bytes = current_app.config["MAX_FILE_SIZE_BYTES"]

    try:
        check_content_length(request.content_length, max_bytes)
        file_bytes = upload.read()
        check_actual_size(file_bytes, max_bytes)

        file_type = detect_file_type(upload.filename, file_bytes)
        text = EXTRACTORS[file_type](file_bytes)

        rubric = get_rubric()
        processed_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        result = score_record(rubric, upload.filename, text, processed_at, api_key)

        return jsonify(result.to_dict()), 200

    except FileTooLargeError as exc:
        return _error_response(413, "file_too_large", exc.message)

    except UnsupportedFileTypeError as exc:
        return _error_response(415, "unsupported_file_type", exc.message)

    except ExtractionFailedError as exc:
        return _error_response(422, "extraction_failed", exc.message, reason=exc.reason)

    except ExtractionError as exc:
        return _error_response(422, "extraction_failed", exc.message)

    except InvalidApiKeyError as exc:
        return _error_response(401, "invalid_api_key", exc.message)

    except LLMServiceError as exc:
        return _error_response(502, "llm_service_error", exc.message)

    except Exception:
        # Redact the formatted traceback before it ever reaches a log sink -- it
        # may contain interpolated record text (CLAUDE.md PHI rule #2).
        redacted_traceback = redact_for_logging(traceback.format_exc())
        logger.error("Unhandled error while validating an upload:\n%s", redacted_traceback)
        return _error_response(500, "internal_error", "An unexpected error occurred.")


@validate_bp.route("/api-key/validate", methods=["POST"])
def validate_api_key_route():
    # No file involved here, so this endpoint takes JSON rather than
    # multipart/form-data (SPEC.md Section 4.1.1).
    body = request.get_json(silent=True) or {}
    api_key = (body.get("anthropic_api_key") or "").strip()
    if not api_key:
        return _error_response(
            400, "missing_api_key", "The 'anthropic_api_key' field is required."
        )

    try:
        validate_api_key(api_key)
    except InvalidApiKeyError as exc:
        return _error_response(401, "invalid_api_key", exc.message)
    except LLMServiceError as exc:
        return _error_response(502, "llm_service_error", exc.message)

    return jsonify({"valid": True}), 200
