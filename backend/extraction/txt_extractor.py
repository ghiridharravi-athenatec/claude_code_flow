"""Text extraction for plain-text uploads."""

from __future__ import annotations

from extraction.errors import DecodeError, EmptyContentError

MIN_NON_WHITESPACE_CHARS = 20


def extract_txt_text(file_bytes: bytes) -> str:
    """Read as UTF-8; retry with latin-1 on failure; else treat as extraction failure."""
    try:
        text = file_bytes.decode("utf-8")
    except UnicodeDecodeError:
        try:
            text = file_bytes.decode("latin-1")
        except UnicodeDecodeError as exc:
            raise DecodeError() from exc

    if len("".join(text.split())) < MIN_NON_WHITESPACE_CHARS:
        raise EmptyContentError()

    return text
