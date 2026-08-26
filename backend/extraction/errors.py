"""Exception types for the file-detection and text-extraction pipeline."""

from __future__ import annotations


class ExtractionError(Exception):
    """Base class for every error raised while detecting or extracting a record."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class UnsupportedFileTypeError(ExtractionError):
    """Raised when the sniffed MIME type is not one of the three allowed types."""


class FileTooLargeError(ExtractionError):
    """Raised when the upload exceeds the configured maximum file size."""


class MissingFileError(ExtractionError):
    """Raised when the request has no ``file`` field."""


class ExtractionFailedError(ExtractionError):
    """Raised when text cannot be extracted from an otherwise valid file type.

    ``reason`` must be one of: "corrupted", "password_protected",
    "empty_content", "decode_error" (per SPEC.md Section 4.1).
    """

    def __init__(self, message: str, reason: str) -> None:
        super().__init__(message)
        self.reason = reason


class CorruptedFileError(ExtractionFailedError):
    def __init__(self, message: str = "The file could not be parsed.") -> None:
        super().__init__(message, reason="corrupted")


class PasswordProtectedError(ExtractionFailedError):
    def __init__(self, message: str = "The file is password-protected.") -> None:
        super().__init__(message, reason="password_protected")


class EmptyContentError(ExtractionFailedError):
    def __init__(
        self, message: str = "The file contains no extractable text content."
    ) -> None:
        super().__init__(message, reason="empty_content")


class DecodeError(ExtractionFailedError):
    def __init__(self, message: str = "The file's text encoding could not be decoded.") -> None:
        super().__init__(message, reason="decode_error")
