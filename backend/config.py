"""Environment-driven configuration for the Clinical Documentation Integrity Scorer backend."""

from __future__ import annotations

import os
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent


class Config:
    """Application configuration, read from environment variables at startup."""

    ALLOWED_ORIGIN: str = os.environ.get("ALLOWED_ORIGIN", "http://localhost:3000")
    MAX_FILE_SIZE_MB: int = int(os.environ.get("MAX_FILE_SIZE_MB", "10"))
    MAX_FILE_SIZE_BYTES: int = MAX_FILE_SIZE_MB * 1024 * 1024
    RUBRIC_PATH: str = os.environ.get(
        "RUBRIC_PATH", str(BACKEND_DIR / "med_record_rubrics.json")
    )
    MIN_EXTRACTED_CHARS: int = int(os.environ.get("MIN_EXTRACTED_CHARS", "20"))
    LOG_LEVEL: str = os.environ.get("LOG_LEVEL", "INFO")

    # No ANTHROPIC_API_KEY here by design (SPEC.md Section 6.1) -- every /validate
    # call supplies its own key; the server never holds one of its own.
    CLAUDE_MODEL: str = os.environ.get("CLAUDE_MODEL", "claude-sonnet-5")
