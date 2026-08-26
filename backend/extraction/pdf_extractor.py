"""Text extraction for PDF uploads."""

from __future__ import annotations

import io

from pypdf import PdfReader
from pypdf.errors import PdfReadError

from extraction.errors import CorruptedFileError, EmptyContentError, PasswordProtectedError

MIN_NON_WHITESPACE_CHARS = 20


def extract_pdf_text(file_bytes: bytes) -> str:
    """Concatenate ``page.extract_text()`` for every page, joined with "\\n\\n"."""
    try:
        reader = PdfReader(io.BytesIO(file_bytes))
    except PdfReadError as exc:
        raise CorruptedFileError() from exc

    if reader.is_encrypted:
        raise PasswordProtectedError()

    try:
        pages_text = [page.extract_text() or "" for page in reader.pages]
    except Exception as exc:  # pypdf can raise a variety of parse errors here
        raise CorruptedFileError() from exc

    text = "\n\n".join(pages_text)

    if len("".join(text.split())) < MIN_NON_WHITESPACE_CHARS:
        raise EmptyContentError()

    return text
