"""File-type detection (extension + MIME sniffing) and size validation."""

from __future__ import annotations

import magic

from extraction.errors import FileTooLargeError, UnsupportedFileTypeError

ALLOWED_MIME_TYPES = {
    "application/pdf": "pdf",
    "text/plain": "txt",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "docx",
}

ALLOWED_EXTENSIONS = {"pdf", "txt", "docx"}


def check_content_length(content_length: int | None, max_bytes: int) -> None:
    """Reject an upload before reading its body, based on the Content-Length header."""
    if content_length is not None and content_length > max_bytes:
        raise FileTooLargeError(
            f"File exceeds the maximum allowed size of {max_bytes // (1024 * 1024)} MB."
        )


def check_actual_size(file_bytes: bytes, max_bytes: int) -> None:
    """Re-validate the actual size once the file has been read into memory."""
    if len(file_bytes) > max_bytes:
        raise FileTooLargeError(
            f"File exceeds the maximum allowed size of {max_bytes // (1024 * 1024)} MB."
        )


def detect_file_type(filename: str, file_bytes: bytes) -> str:
    """Sniff the MIME type of ``file_bytes`` and confirm it is an allowed type.

    Returns the short type label ("pdf", "txt", or "docx"). Extension is
    used only as a secondary hint; MIME sniffing is authoritative.
    """
    extension = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    sniffed_mime = magic.from_buffer(file_bytes, mime=True)

    if sniffed_mime not in ALLOWED_MIME_TYPES:
        raise UnsupportedFileTypeError(
            f"Unsupported file type: {sniffed_mime}. Only PDF, TXT, and DOCX are accepted."
        )

    type_label = ALLOWED_MIME_TYPES[sniffed_mime]
    if extension and extension not in ALLOWED_EXTENSIONS:
        raise UnsupportedFileTypeError(
            f"Unsupported file extension: .{extension}. Only PDF, TXT, and DOCX are accepted."
        )

    return type_label
